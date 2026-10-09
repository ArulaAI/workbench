/*
 * Money as integer minor units. Plan 2.1, satisfying FR-3.
 *
 * This module is the natural home for F7, silent regression. Partial capture has to
 * split an authorised amount across several captures, and the split is where a rounding
 * defect hides. A one-cent drift here changes a webhook payload and a ledger row that
 * no test in the suite looks at.
 */

export type Minor = number & { readonly __brand: 'minor' };

export const minor = (n: number): Minor => {
  if (!Number.isInteger(n)) throw new RangeError(`money must be integer minor units, got ${n}`);
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
  if (parts < 1) throw new RangeError('parts must be at least 1');
  const base = Math.trunc(amount / parts);
  const remainder = amount - base * parts;
  return Array.from({ length: parts }, (_, i) => minor(base + (i < remainder ? 1 : 0)));
};

/*
 * Apply a rate to an amount, for scheme fees and partial captures.
 * Rounds half up on the absolute value so that negative amounts round symmetrically.
 */
export const applyRate = (amount: Minor, rate: number): Minor => {
  const raw = amount * rate;
  const sign = raw < 0 ? -1 : 1;
  return minor(sign * Math.round(Math.abs(raw)));
};
