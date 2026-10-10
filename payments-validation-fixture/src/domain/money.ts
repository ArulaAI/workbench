/*
 * Money as integer minor units. Plan 2.1, satisfying FR-3.
 *
 * This module is the natural home for F7, silent regression. Partial capture has to
 * split an authorised amount across several captures, and the split is where a rounding
 * defect hides. A one-cent drift here changes a webhook payload and a ledger row that
 * no test in the suite looks at.
 */

export type Minor = number & { readonly __brand: 'minor' };

export const SCHEME_FEE_BPS = 149;
const BPS_DENOMINATOR = 10000;

export const minor = (n: number): Minor => {
  if (!Number.isSafeInteger(n)) throw new RangeError(`money must be integer minor units, got ${n}`);
  return n as Minor;
};

export const add = (a: Minor, b: Minor): Minor => minor(a + b);
export const sub = (a: Minor, b: Minor): Minor => minor(a - b);

export const format = (m: Minor, currency = 'GBP'): string =>
  `${currency} ${(m / 100).toFixed(2)}`;

/*
 * Split an amount into n parts with no money created or destroyed.
 *
 * The remainder is distributed one minor unit at a time across the leading parts, which
 * is Fowler's allocation. The invariant that matters: sum(allocate(a, n)) === a for every
 * a and n. A naive implementation using Math.round on a/n breaks that quietly.
 */
export const allocate = (amount: Minor, parts: number): Minor[] => {
  if (!Number.isInteger(parts) || parts < 1) {
    throw new RangeError(`parts must be an integer >= 1, got ${parts}`);
  }
  const sign = amount < 0 ? -1 : 1;
  const abs = Math.abs(amount);
  const base = (abs - (abs % parts)) / parts;
  const remainder = abs % parts;
  return Array.from({ length: parts }, (_, i) => minor(sign * (base + (i < remainder ? 1 : 0))));
};

/*
 * Apply a rate in basis points (1.49% is 149) to an amount, for scheme fees and partial
 * captures. Integer arithmetic only. Rounds half up on the absolute value so that
 * negative amounts round symmetrically: floor((abs * bps * 2 + 10000) / 20000).
 */
export const applyRate = (amount: Minor, rateBps: number): Minor => {
  if (!Number.isSafeInteger(rateBps)) {
    throw new RangeError(`rate must be integer basis points, got ${rateBps}`);
  }
  const sign = amount < 0 ? -1 : 1;
  const numerator = Math.abs(amount) * rateBps * 2 + BPS_DENOMINATOR;
  if (!Number.isSafeInteger(numerator)) throw new RangeError('rate calculation overflows safe integer range');
  const fee = (numerator - (numerator % (2 * BPS_DENOMINATOR))) / (2 * BPS_DENOMINATOR);
  return minor(sign * fee);
};
