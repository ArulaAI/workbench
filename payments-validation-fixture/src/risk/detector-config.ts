/*
 * Configuration for the F2.2 card-testing detector.
 *
 * `mode` is the rollout flag: 'shadow' detects and logs only, 'block' adds the step-up
 * on block matches, and 'block_and_notify' adds merchant notifications.
 */

export type Clock = () => number;

export type DetectorMode = 'shadow' | 'block' | 'block_and_notify';

export type DetectorConfig = {
  /** Largest amount, in minor units, that counts as a small authorisation. */
  smallAmountCeiling: number;
  windowMs: number;
  minCards: number;
  minMerchants: number;
  blockTtlMs: number;
  refreshIntervalMs: number;
  notifyFollowUpMs: number;
  mode: DetectorMode;
  version: string;
};

export class DetectorConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DetectorConfigError';
  }
}

const MODES: readonly string[] = ['shadow', 'block', 'block_and_notify'];
const MIN_BLOCK_TTL_MS = 5 * 60 * 1000;
const MAX_BLOCK_TTL_MS = 24 * 60 * 60 * 1000;

const NUMERIC_FIELDS = [
  'smallAmountCeiling', 'windowMs', 'minCards', 'minMerchants',
  'blockTtlMs', 'refreshIntervalMs', 'notifyFollowUpMs',
] as const;

export function loadDetectorConfig(raw: unknown): DetectorConfig {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new DetectorConfigError('detector config must be an object');
  }
  const r = raw as Record<string, unknown>;

  for (const field of NUMERIC_FIELDS) {
    const v = r[field];
    if (typeof v !== 'number' || !Number.isInteger(v) || v <= 0) {
      throw new DetectorConfigError(`${field} must be a positive integer, got ${String(v)}`);
    }
  }
  const n = r as Record<(typeof NUMERIC_FIELDS)[number], number>;

  if (n.minCards < 2) throw new DetectorConfigError(`minCards must be at least 2, got ${n.minCards}`);
  if (n.minMerchants < 2) throw new DetectorConfigError(`minMerchants must be at least 2, got ${n.minMerchants}`);
  if (n.blockTtlMs < MIN_BLOCK_TTL_MS || n.blockTtlMs > MAX_BLOCK_TTL_MS) {
    throw new DetectorConfigError(`blockTtlMs must be between 5 minutes and 24 hours, got ${n.blockTtlMs}`);
  }
  if (typeof r.mode !== 'string' || !MODES.includes(r.mode)) {
    throw new DetectorConfigError(`mode must be one of ${MODES.join(', ')}, got ${String(r.mode)}`);
  }
  if (typeof r.version !== 'string' || r.version.trim() === '') {
    throw new DetectorConfigError('version must be a non-empty string');
  }

  return {
    smallAmountCeiling: n.smallAmountCeiling,
    windowMs: n.windowMs,
    minCards: n.minCards,
    minMerchants: n.minMerchants,
    blockTtlMs: n.blockTtlMs,
    refreshIntervalMs: n.refreshIntervalMs,
    notifyFollowUpMs: n.notifyFollowUpMs,
    mode: r.mode as DetectorMode,
    version: r.version,
  };
}
