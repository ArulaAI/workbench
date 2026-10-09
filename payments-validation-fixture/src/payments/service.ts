/*
 * The payments service. Plan 2.4, satisfying FR-1, FR-2, FR-5 and FR-6.
 *
 * Flows: authorise, capture (including partial), refund, void.
 *
 * Read FR-6 before changing refund. Authorise and capture take an idempotency key.
 * Refund does not.
 */

import { type Minor, add, allocate, applyRate, minor, sub } from '../domain/money.ts';
import { Ledger } from '../domain/ledger.ts';
import { type Card, type Token, maskedFor, tokenise } from '../vault.ts';
import { log, redact, serialiseFailure, span, webhook } from '../obs/index.ts';

export type Capture = { id: string; amount: Minor; at: number };
export type Refund = { id: string; amount: Minor; captureId: string; at: number };

export type Payment = {
  id: string;
  token: Token;
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

const SCHEME_FEE_RATE = 0.0149;

export class PaymentsService {
  readonly ledger = new Ledger();
  readonly payments: PaymentStore = new Map();

  /** Results already returned for an idempotency key. FR-5. */
  private readonly idempotent = new Map<string, unknown>();
  private counter = 0;

  private nextId(prefix: string): string {
    return `${prefix}_${(++this.counter).toString(36).padStart(6, '0')}`;
  }

  authorise(req: AuthoriseRequest): Payment {
    if (req.idempotencyKey && this.idempotent.has(req.idempotencyKey)) {
      return this.idempotent.get(req.idempotencyKey) as Payment;
    }

    let card: Card;
    try {
      card = tokenise(req.pan, req.expiry);
    } catch (error) {
      // Sink 5. The request travels with the error, redacted at the boundary.
      log.error(serialiseFailure(error, redact(req)));
      throw error;
    }

    const payment: Payment = {
      id: this.nextId('pay'),
      token: card.token,
      last4: card.last4,
      authorised: minor(req.amount),
      currency: req.currency ?? 'GBP',
      status: 'authorised',
      captures: [],
      refunds: [],
    };
    this.payments.set(payment.id, payment);

    this.ledger.post({
      debit: 'cardholder',
      credit: 'merchant_receivable',
      amount: payment.authorised,
      paymentId: payment.id,
      kind: 'authorise',
    });

    log.info(`authorised ${payment.id} for ${maskedFor(card.token)}`);
    const amount = payment.authorised;
    span('payment.authorise', { paymentId: payment.id, card: maskedFor(card.token), amount });

    if (req.idempotencyKey) this.idempotent.set(req.idempotencyKey, payment);
    return payment;
  }

  /**
   * Capture all or part of an authorisation. FR-2.
   * The scheme fee is taken from the captured amount, and the split is where rounding
   * behaviour becomes observable.
   */
  capture(paymentId: string, amount?: number, idempotencyKey?: string): Capture {
    if (idempotencyKey && this.idempotent.has(idempotencyKey)) {
      return this.idempotent.get(idempotencyKey) as Capture;
    }

    const payment = this.require(paymentId);
    const already = payment.captures.reduce((s, c) => s + c.amount, 0);
    const remaining = sub(payment.authorised, minor(already));
    const requested = minor(amount ?? remaining);

    if (requested > remaining) {
      throw new RangeError(`capture ${requested} exceeds remaining ${remaining}`);
    }

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
    this.ledger.post({
      debit: 'merchant_receivable',
      credit: 'scheme_fees',
      amount: fee,
      paymentId: payment.id,
      kind: 'capture',
    });

    span('payment.capture', { paymentId, amount: requested, fee, net });
    if (idempotencyKey) this.idempotent.set(idempotencyKey, capture);
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

    const requested = minor(amount ?? capture.amount);
    const captured = payment.captures.reduce((s, c) => s + c.amount, 0);
    const refunded = payment.refunds.reduce((s, r) => s + r.amount, 0);
    if (refunded + requested > captured) {
      throw new RangeError(`refund ${requested} exceeds refundable ${captured - refunded}`);
    }
    const refund: Refund = { id: this.nextId('ref'), amount: requested, captureId, at: Date.now() };
    payment.refunds.push(refund);

    this.ledger.post({
      debit: 'merchant_settled',
      credit: 'refunds_payable',
      amount: requested,
      paymentId: payment.id,
      kind: 'refund',
    });

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
    payment.status = 'voided';
    this.ledger.post({
      debit: 'merchant_receivable',
      credit: 'cardholder',
      amount: payment.authorised,
      paymentId,
      kind: 'void',
    });
    return payment;
  }

  /** Split a capture across several settlements. Uses allocate so nothing is lost. */
  settlementSchedule(paymentId: string, instalments: number): Minor[] {
    const payment = this.require(paymentId);
    const captured = payment.captures.reduce((s, c) => add(minor(s), c.amount), minor(0));
    return allocate(captured, instalments);
  }

  private require(paymentId: string): Payment {
    const payment = this.payments.get(paymentId);
    if (!payment) throw new RangeError(`unknown payment ${paymentId}`);
    return payment;
  }
}
