/*
 * Rollout flag for the scored decision. RFC F2.1, Migration Strategy.
 *
 *   v1       risk rules v1 decide; the scorer is never called. This is the rollback.
 *   shadow   v1 decides; the scored decision is computed and logged alongside it.
 *   enforce  the scored decision decides, but only for merchants in enforcedMerchants.
 *            Every other merchant stays in shadow, so cutover is merchant by merchant.
 */

export type RiskMode = 'v1' | 'shadow' | 'enforce';

export type RiskRollout = { mode: RiskMode; enforcedMerchants: ReadonlySet<string> };

export const DEFAULT_ROLLOUT: RiskRollout = { mode: 'shadow', enforcedMerchants: new Set() };

const MODES: readonly string[] = ['v1', 'shadow', 'enforce'];

/** True only when the scored decision, not risk rules v1, decides for this merchant. */
export const scoredDecides = (rollout: RiskRollout, merchantId: string): boolean =>
  rollout.mode === 'enforce' && rollout.enforcedMerchants.has(merchantId);

/**
 * Read the rollout from configuration: RISK_MODE and RISK_ENFORCED_MERCHANTS (comma
 * separated). Missing values give the default, shadow with no merchants. An unknown mode
 * throws, so the gateway never starts on a mistyped flag.
 */
export function rolloutFromEnv(env: Record<string, string | undefined> = process.env): RiskRollout {
  const mode = env.RISK_MODE?.trim() || DEFAULT_ROLLOUT.mode;
  if (!MODES.includes(mode)) {
    throw new Error(`RISK_MODE must be one of ${MODES.join(', ')}, got ${JSON.stringify(mode)}`);
  }
  const enforcedMerchants = new Set(
    (env.RISK_ENFORCED_MERCHANTS ?? '').split(',').map(m => m.trim()).filter(m => m !== ''),
  );
  return { mode: mode as RiskMode, enforcedMerchants };
}
