/*
 * The four named invariants. Plan 2.3, satisfying FR-9 and FR-10.
 *
 * These are assertable after an arbitrary operation sequence, which is what lets the
 * property command generate interleavings and retries and still check something real.
 */

import type { Ledger } from './ledger.ts';
import type { PaymentStore } from '../payments/service.ts';

export type Violation = { invariant: string; detail: string; paymentId?: string };

export const LEDGER_BALANCED = (ledger: Ledger): Violation[] =>
  ledger.net() === 0
    ? []
    : [{ invariant: 'LEDGER_BALANCED', detail: `ledger nets to ${ledger.net()}, expected 0` }];

export const CAPTURE_WITHIN_AUTH = (store: PaymentStore): Violation[] => {
  const out: Violation[] = [];
  for (const p of store.values()) {
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

export const REFUND_TRACES_CAPTURE = (store: PaymentStore): Violation[] => {
  const out: Violation[] = [];
  for (const p of store.values()) {
    const captured = p.captures.reduce((s, c) => s + c.amount, 0);
    const refunded = p.refunds.reduce((s, r) => s + r.amount, 0);
    if (refunded > captured) {
      out.push({
        invariant: 'REFUND_TRACES_CAPTURE',
        paymentId: p.id,
        detail: `refunded ${refunded} exceeds captured ${captured}`,
      });
    }
  }
  return out;
};

/*
 * A stored record must never hold a full PAN. Only the vault may, and only as last4.
 *
 * Length alone is not enough. A millisecond timestamp is 13 digits, so a length-only
 * rule reports every record that carries an `at` field. Luhn plus a string-only walk is
 * what makes this assertable. That distinction is worth knowing: the same mistake in a
 * scanner is the difference between a useful hook and one nobody leaves enabled.
 */
const luhnValid = (digits: string): boolean => {
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i -= 1) {
    let d = digits.charCodeAt(i) - 48;
    if (alt) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
    alt = !alt;
  }
  return sum % 10 === 0;
};

const strings = (value: unknown, out: string[] = []): string[] => {
  if (typeof value === 'string') out.push(value);
  else if (Array.isArray(value)) value.forEach(v => strings(v, out));
  else if (value && typeof value === 'object') Object.values(value).forEach(v => strings(v, out));
  return out;
};

export const NO_PAN_AT_REST = (store: PaymentStore): Violation[] => {
  const out: Violation[] = [];
  for (const p of store.values()) {
    for (const s of strings(p)) {
      for (const match of s.matchAll(/\d{13,19}/g)) {
        if (!luhnValid(match[0])) continue;
        out.push({
          invariant: 'NO_PAN_AT_REST',
          paymentId: p.id,
          detail: `stored record holds a Luhn-valid ${match[0].length}-digit value`,
        });
      }
    }
  }
  return out;
};

export const checkAll = (ledger: Ledger, store: PaymentStore): Violation[] => [
  ...LEDGER_BALANCED(ledger),
  ...CAPTURE_WITHIN_AUTH(store),
  ...REFUND_TRACES_CAPTURE(store),
  ...NO_PAN_AT_REST(store),
];
