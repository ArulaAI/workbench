/*
 * Reason codes and the wording attached to them.
 *
 * Cardholder text is a draft allowlist pending Legal approval. Analyst text names features
 * and must never reach the merchant or a GatewayResult.
 */

export type ReasonCode =
  | 'amount_unusual'
  | 'country_mismatch'
  | 'merchant_category_risk'
  | 'time_of_day'
  | 'issuer_unknown'
  | 'card_testing_pattern'; // reserved for F2.2

export const REASON_CODES: readonly ReasonCode[] = Object.freeze([
  'amount_unusual',
  'country_mismatch',
  'merchant_category_risk',
  'time_of_day',
  'issuer_unknown',
  'card_testing_pattern',
] as const);

export const isReasonCode = (x: unknown): x is ReasonCode =>
  typeof x === 'string' && (REASON_CODES as readonly string[]).includes(x);

export const CARDHOLDER_REASONS: Readonly<Record<string, string>> = Object.freeze({
  decline_generic: 'Your bank could not approve this payment.',
  step_up_not_confirmed: "Your bank couldn't confirm this payment.",
  card_testing_pattern: "Your bank couldn't confirm this payment. You haven't been charged.",
});

const MAX_CARDHOLDER_REASON_LENGTH = 140;

/** Short terms match whole words only, so 'tip' or 'binary' are not flagged. */
const BANNED_TERMS: readonly string[] = [
  'fraud', 'suspicious', 'score', 'threshold', 'model', 'BIN', 'IP', 'country', 'velocity', 'amount band',
];
const WHOLE_WORD_TERMS = new Set(['BIN', 'IP']);

/** Throws if cardholder-facing text is too long, holds a digit, or names a banned term. */
export const assertCardholderReasonSafe = (text: string): void => {
  if (text.length > MAX_CARDHOLDER_REASON_LENGTH) {
    throw new Error(`cardholder reason exceeds ${MAX_CARDHOLDER_REASON_LENGTH} characters`);
  }
  if (/\d/.test(text)) throw new Error('cardholder reason contains a digit');
  const lower = text.toLowerCase();
  for (const term of BANNED_TERMS) {
    const t = term.toLowerCase();
    const re = new RegExp(WHOLE_WORD_TERMS.has(term) ? `\\b${t}\\b` : `\\b${t}`);
    if (re.test(lower)) throw new Error(`cardholder reason contains banned term '${term}'`);
  }
};

for (const [key, text] of Object.entries(CARDHOLDER_REASONS)) {
  try {
    assertCardholderReasonSafe(text);
  } catch (error) {
    throw new Error(`unsafe cardholder reason '${key}': ${(error as Error).message}`);
  }
}

/** Every model reason maps to the same text, so a reason cannot help tune the next attempt. */
export const cardholderReason = (code: ReasonCode | 'step_up_not_confirmed'): string | undefined =>
  code === 'step_up_not_confirmed'
    ? CARDHOLDER_REASONS.step_up_not_confirmed
    : code === 'card_testing_pattern'
      ? CARDHOLDER_REASONS.card_testing_pattern
      : isReasonCode(code)
        ? CARDHOLDER_REASONS.decline_generic
        : undefined;

const ANALYST_REASONS: Readonly<Record<ReasonCode, string>> = Object.freeze({
  amount_unusual: 'Amount is unusual for this card or merchant category',
  country_mismatch: 'IP country differs from issuer country',
  merchant_category_risk: 'Merchant category carries elevated risk',
  time_of_day: 'Transaction time is unusual for this card',
  issuer_unknown: 'Issuer could not be determined from the BIN',
  card_testing_pattern: 'Matches an active card-testing block',
});

export const analystReason = (code: ReasonCode): string => ANALYST_REASONS[code];
