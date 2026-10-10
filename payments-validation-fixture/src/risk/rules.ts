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
 *
 * Adaptive authorisation (F2.1) puts HIGH_VALUE_CROSS_BORDER behind the rollout flag: for
 * a merchant on the scored decision the gateway turns it off and only CARD_VELOCITY runs.
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

  /**
   * `highValueCrossBorder: false` skips HIGH_VALUE_CROSS_BORDER for a merchant the scored
   * decision has taken over (see src/risk/rollout.ts). It defaults to true, so v1 and shadow
   * mode behave exactly as before. The rule is removed only after full cutover.
   */
  evaluate(input: RiskInput, opts: { highValueCrossBorder?: boolean } = {}): RiskDecision {
    const key = `${input.bin}:${input.last4}`;
    const recent = (this.attempts.get(key) ?? []).filter(t => input.at - t < VELOCITY_WINDOW_MS);
    recent.push(input.at);
    this.attempts.set(key, recent);

    const issuer = issuerCountry(input.bin);
    if (
      (opts.highValueCrossBorder ?? true) &&
      input.amount >= HIGH_VALUE_MINOR && issuer !== null && issuer !== input.ipCountry
    ) {
      return { outcome: 'decline', rule: 'HIGH_VALUE_CROSS_BORDER' };
    }
    if (recent.length > VELOCITY_LIMIT) {
      return { outcome: 'decline', rule: 'CARD_VELOCITY' };
    }
    return { outcome: 'approve' };
  }
}
