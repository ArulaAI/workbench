/*
 * The payments service. Plan 2.4, satisfying FR-1, FR-2, FR-5 and FR-6.
 *
 * Flows: authorise, capture (including partial), refund, void.
 *
 * Read FR-6 before changing refund. Authorise and capture take an idempotency key.
 * Refund does not.
 */

import { type Minor, SCHEME_FEE_BPS, add, allocate, applyRate, minor, sub } from '../domain/money.ts';
import { Ledger } from '../domain/ledger.ts';
import { type Card, type Token, maskedFor, tokenise } from '../vault.ts';
import { log, redact, serialiseFailure, span, webhook } from '../obs/index.ts';

export type Capture = { id: string; amount: Minor; at: number };
export type Refund = { id: string; amount: Minor; captureId: string; at: number };

export type Payment = {
  id: string;
  token: Token;
  bin: string;
  last4: string;
  authorised: Minor;
  currency: string;
  status: 'authorised' | 'captured' | 'voided';
  captures: Capture[];
  refunds: Refund[];
};

export type PaymentStore = Map<string, Payment>;

export type AuthoriseRequest = {
  pan: string;
  expiry: string;
  amount: number;
  currency?: string;
  idempotencyKey?: string;
};

const SCHEME_FEE_RATE = SCHEME_FEE_BPS;

export class PaymentsService {
  readonly ledger = new Ledger();
  readonly payments: PaymentStore = new Map();

  /** Results already returned for an idempotency key, keyed by `${op}:${key}`. FR-5. */
  private readonly idempotent = new Map<string, { op: 'authorise' | 'capture'; result: Payment | Capture }>();
  private counter = 0;

  private nextId(prefix: string): string {
    return `${prefix}_${(++this.counter).toString(36).padStart(6, '0')}`;
  }

  authorise(req: AuthoriseRequest): Payment {
    const replayKey = req.idempotencyKey ? `authorise:${req.idempotencyKey}` : undefined;
    const seen = replayKey ? this.idempotent.get(replayKey) : undefined;
    if (seen) return seen.result as Payment;

    // Validate before anything is written. A fractional amount throws here.
    const authorised = minor(req.amount);

    let card: Card;
    try {
      card = tokenise(req.pan, req.expiry);
    } catch (error) {
      // Sink 5. The request travels with the error, redacted at the boundary.
      log.error(serialiseFailure(error, redact(req)));
      throw error;
    }
    const masked = maskedFor(card.token);

    const payment: Payment = {
      id: this.nextId('pay'),
      token: card.token,
      bin: card.bin,
      last4: card.last4,
      authorised,
      currency: req.currency ?? 'GBP',
      status: 'authorised',
      captures: [],
      refunds: [],
    };

    // Ledger.post validates before writing, so a throw here leaves the store untouched.
    this.ledger.post({
      debit: 'cardholder',
      credit: 'merchant_receivable',
      amount: payment.authorised,
      paymentId: payment.id,
      kind: 'authorise',
    });
    this.payments.set(payment.id, payment);
    if (replayKey) this.idempotent.set(replayKey, { op: 'authorise', result: payment });

    log.info(`authorised ${payment.id} for ${masked}`);
    span('payment.authorise', { paymentId: payment.id, card: masked, amount: payment.authorised });
    return payment;
  }

  /**
   * Capture all or part of an authorisation. FR-2.
   * The scheme fee is taken from the captured amount, and the split is where rounding
   * behaviour becomes observable.
   */
  capture(paymentId: string, amount?: number, idempotencyKey?: string): Capture {
    const seen = idempotencyKey ? this.idempotent.get(`capture:${idempotencyKey}`) : undefined;
    if (seen) return seen.result as Capture;

    const payment = this.require(paymentId);
    const already = payment.captures.reduce((s, c) => s + c.amount, 0);
    const remaining = sub(payment.authorised, minor(already));
    const requested = minor(amount ?? remaining);

    if (requested > remaining) {
      throw new RangeError(`capture ${requested} exceeds remaining ${remaining}`);
    }
    if (requested <= 0) {
      throw new RangeError(`capture amount must be positive, got ${requested}`);
    }

    // Everything is validated above. fee + net === requested by construction.
    const fee = applyRate(requested, SCHEME_FEE_RATE);
    const net = sub(requested, fee);

    const capture: Capture = { id: this.nextId('cap'), amount: requested, at: Date.now() };
    payment.captures.push(capture);
    payment.status = 'captured';

    this.ledger.post({
      debit: 'merchant_receivable',
      credit: 'merchant_settled',
      amount: net,
      paymentId: payment.id,
      kind: 'capture',
    });
    // A fee that rounds to zero has no entry, because the ledger rejects zero amounts.
    if (fee > 0) {
      this.ledger.post({
        debit: 'merchant_receivable',
        credit: 'scheme_fees',
        amount: fee,
        paymentId: payment.id,
        kind: 'capture',
      });
    }

    span('payment.capture', { paymentId, amount: requested, fee, net });
    if (idempotencyKey) this.idempotent.set(`capture:${idempotencyKey}`, { op: 'capture', result: capture });
    return capture;
  }

  /**
   * Refund against a capture.
   *
   * FR-6. No idempotency key, and that is deliberate.
   *
   * The guard below keeps REFUND_TRACES_CAPTURE true: you cannot refund more than was
   * captured. What no requirement answers is whether two identical partial refund
   * requests are one refund or two. Both stay inside the guard, both succeed, and both
   * are recorded. The money is not wrong. Whether the merchant meant to pay twice is a
   * question the specification never asked.
   */
  refund(paymentId: string, captureId: string, amount?: number): Refund {
    const payment = this.require(paymentId);
    const capture = payment.captures.find(c => c.id === captureId);
    if (!capture) throw new RangeError(`no capture ${captureId} on ${paymentId}`);

    const captured = payment.captures.reduce((s, c) => s + c.amount, 0);
    const refunded = payment.refunds.reduce((s, r) => s + r.amount, 0);
    const refundedOnCapture = payment.refunds
      .filter(r => r.captureId === captureId)
      .reduce((s, r) => s + r.amount, 0);
    const refundable = Math.min(capture.amount - refundedOnCapture, captured - refunded);
    const requested = minor(amount ?? capture.amount - refundedOnCapture);
    if (requested > refundable) {
      throw new RangeError(`refund ${requested} exceeds refundable ${refundable}`);
    }
    if (requested <= 0) {
      throw new RangeError(`refund amount must be positive, got ${requested}`);
    }

    // Everything is validated above. Post first: a ledger throw then leaves the payment untouched.
    const refund: Refund = { id: this.nextId('ref'), amount: requested, captureId, at: Date.now() };
    this.ledger.post({
      debit: 'merchant_settled',
      credit: 'refunds_payable',
      amount: requested,
      paymentId: payment.id,
      kind: 'refund',
    });
    payment.refunds.push(refund);

    log.info(`refunded ${requested} on ${paymentId}`);
    webhook('https://merchant.example/hooks/refund', 200, {
      paymentId,
      refundId: refund.id,
      amount: requested,
      card: maskedFor(payment.token),
    });
    return refund;
  }

  void(paymentId: string): Payment {
    const payment = this.require(paymentId);
    if (payment.captures.length > 0) throw new RangeError('cannot void a captured payment');
    this.ledger.post({
      debit: 'merchant_receivable',
      credit: 'cardholder',
      amount: payment.authorised,
      paymentId,
      kind: 'void',
    });
    payment.status = 'voided';
    return payment;
  }

  /** Split a capture across several settlements. Uses allocate so nothing is lost. */
  settlementSchedule(paymentId: string, instalments: number): Minor[] {
    const payment = this.require(paymentId);
    const captured = payment.captures.reduce((s, c) => add(minor(s), c.amount), minor(0));
    if (!Number.isInteger(instalments) || instalments < 1) throw new RangeError('parts must be at least 1');
    return allocate(captured, instalments);
  }

  private require(paymentId: string): Payment {
    const payment = this.payments.get(paymentId);
    if (!payment) throw new RangeError(`unknown payment ${paymentId}`);
    return payment;
  }
}
