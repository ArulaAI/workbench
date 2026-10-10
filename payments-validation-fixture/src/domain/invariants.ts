/*
 * The four named invariants. Plan 2.3, satisfying FR-9 and FR-10.
 *
 * These are assertable after an arbitrary operation sequence, which is what lets the
 * property command generate interleavings and retries and still check something real.
 * Each invariant is its own function and checkAll concatenates them.
 *
 * The store is typed structurally so Phase 2 can extend Payment without breaking this
 * checker. Existing callers pass service.payments, a Map, so that shape is accepted too.
 */

import type { Ledger } from './ledger.ts';
import { findLuhnCandidatesIn } from '../vault.ts';

export type Violation = { invariant: string; detail: string; paymentId?: string };

export type PaymentLike = {
  id: string;
  authorised: number;
  captures: ReadonlyArray<{ id: string; amount: number }>;
  refunds: ReadonlyArray<{ id: string; amount: number; captureId: string }>;
};

export interface StoreLike {
  payments(): Iterable<PaymentLike>;
  idempotency?(): Iterable<unknown>;
}

export type CheckableStore = StoreLike | ReadonlyMap<string, PaymentLike>;

const paymentsOf = (store: CheckableStore): PaymentLike[] =>
  store instanceof Map ? [...store.values()] : [...(store as StoreLike).payments()];

const idempotencyOf = (store: CheckableStore): unknown[] =>
  store instanceof Map ? [] : [...((store as StoreLike).idempotency?.() ?? [])];

export const LEDGER_BALANCED = (ledger: Ledger): Violation[] => {
  const out: Violation[] = [];
  for (const [pairId, entries] of ledger.pairs()) {
    const sum = entries.reduce((s, e) => s + e.amount, 0);
    if (entries.length !== 2) {
      out.push({
        invariant: 'LEDGER_BALANCED',
        paymentId: entries[0]?.paymentId,
        detail: `pair ${pairId} has ${entries.length} entries, expected 2`,
      });
    } else if (sum !== 0) {
      out.push({
        invariant: 'LEDGER_BALANCED',
        paymentId: entries[0].paymentId,
        detail: `pair ${pairId} sums to ${sum}, expected 0`,
      });
    }
  }
  return out;
};

export const CAPTURE_WITHIN_AUTH = (store: CheckableStore): Violation[] => {
  const out: Violation[] = [];
  for (const p of paymentsOf(store)) {
    const captured = p.captures.reduce((s, c) => s + c.amount, 0);
    if (captured > p.authorised) {
      out.push({
        invariant: 'CAPTURE_WITHIN_AUTH',
        paymentId: p.id,
        detail: `captured ${captured} exceeds authorised ${p.authorised}`,
      });
    }
  }
  return out;
};

export const REFUND_TRACES_CAPTURE = (store: CheckableStore): Violation[] => {
  const out: Violation[] = [];
  for (const p of paymentsOf(store)) {
    const captureAmounts = new Map(p.captures.map(c => [c.id, c.amount]));
    const refundedBy = new Map<string, number>();
    for (const r of p.refunds) {
      if (!captureAmounts.has(r.captureId)) {
        out.push({
          invariant: 'REFUND_TRACES_CAPTURE',
          paymentId: p.id,
          detail: `refund ${r.id} references unknown capture ${r.captureId}`,
        });
        continue;
      }
      refundedBy.set(r.captureId, (refundedBy.get(r.captureId) ?? 0) + r.amount);
    }
    for (const [captureId, refunded] of refundedBy) {
      const captured = captureAmounts.get(captureId)!;
      if (refunded > captured) {
        out.push({
          invariant: 'REFUND_TRACES_CAPTURE',
          paymentId: p.id,
          detail: `refunds ${refunded} against capture ${captureId} exceed its amount ${captured}`,
        });
      }
    }
  }
  return out;
};

/*
 * A stored record must never hold a full PAN. Only the vault may, and only as last4.
 * Length alone is not enough: a 13-digit millisecond timestamp would trip it. The vault's
 * Luhn-checked finder is applied to each record's string values only, so numeric
 * timestamps are never mistaken for a card number.
 */
export const NO_PAN_AT_REST = (ledger: Ledger, store: CheckableStore): Violation[] => {
  const out: Violation[] = [];
  const scan = (kind: string, record: unknown, paymentId?: string) => {
    for (const match of findLuhnCandidatesIn(record)) {
      out.push({
        invariant: 'NO_PAN_AT_REST',
        paymentId,
        detail: `${kind} holds a Luhn-valid ${match.replace(/\D/g, '').length}-digit value`,
      });
    }
  };
  for (const p of paymentsOf(store)) {
    scan('payment', p, p.id);
    for (const c of p.captures) scan('capture', c, p.id);
    for (const r of p.refunds) scan('refund', r, p.id);
  }
  for (const e of ledger.entries) scan('ledger entry', e, e.paymentId);
  for (const rec of idempotencyOf(store)) scan('idempotency record', rec);
  return out;
};

export const checkAll = (ledger: Ledger, store: CheckableStore): Violation[] => [
  ...LEDGER_BALANCED(ledger),
  ...CAPTURE_WITHIN_AUTH(store),
  ...REFUND_TRACES_CAPTURE(store),
  ...NO_PAN_AT_REST(ledger, store),
];
