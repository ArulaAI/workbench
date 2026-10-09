/*
 * Risk rules v1. Written for launch, before there was any fraud data to learn from.
 *
 * Two hard-coded rules, evaluated in order, first match wins:
 *
 *   HIGH_VALUE_CROSS_BORDER  1,000.00 or more, and the shopper's IP country differs from
 *                            the issuer country. Declined.
 *   CARD_VELOCITY            more than five attempts on the same card in ten minutes.
 *                            Declined.
 *
 * The thresholds were picked by the launch team and have not been revisited. Velocity is
 * counted in process memory, so each gateway replica keeps its own count and a restart
 * forgets everything.
 */

import { issuerCountry } from './issuers.ts';

export type RiskOutcome = 'approve' | 'decline';

export type RuleId = 'HIGH_VALUE_CROSS_BORDER' | 'CARD_VELOCITY';

export type RiskInput = {
  /** First six digits. The rules never see more of the card than this and last4. */
  bin: string;
  last4: string;
  amount: number;
  ipCountry: string;
  merchantId: string;
  at: number;
};

export type RiskDecision = { outcome: RiskOutcome; rule?: RuleId };

export const HIGH_VALUE_MINOR = 100_000;
export const VELOCITY_LIMIT = 5;
export const VELOCITY_WINDOW_MS = 10 * 60 * 1000;

export class RiskRules {
  /** Attempt times per card, keyed by BIN and last four. */
  private readonly attempts = new Map<string, number[]>();

  evaluate(input: RiskInput): RiskDecision {
    const key = `${input.bin}:${input.last4}`;
    const recent = (this.attempts.get(key) ?? []).filter(t => input.at - t < VELOCITY_WINDOW_MS);
    recent.push(input.at);
    this.attempts.set(key, recent);

    const issuer = issuerCountry(input.bin);
    if (input.amount >= HIGH_VALUE_MINOR && issuer !== null && issuer !== input.ipCountry) {
      return { outcome: 'decline', rule: 'HIGH_VALUE_CROSS_BORDER' };
    }
    if (recent.length > VELOCITY_LIMIT) {
      return { outcome: 'decline', rule: 'CARD_VELOCITY' };
    }
    return { outcome: 'approve' };
  }
}
