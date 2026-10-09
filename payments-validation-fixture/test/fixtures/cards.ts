/*
 * Synthetic card data only. FR-8.
 *
 * Every number here is a published scheme test BIN. They are Luhn-valid on purpose,
 * because pan-scan has to see them and then suppress them via the allowlist. That
 * suppression is the documented false positive a learner meets in Chapter 4.
 */
export const TEST_CARDS = {
  visa: '4111111111111111',
  visaDebit: '4000056655665556',
  mastercard: '5555555555554444',
  amex: '378282246310005',
  discover: '6011111111111117',
} as const;

export const EXPIRY = '12/30';
