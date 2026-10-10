/*
 * Decision policy. Maps a score to an outcome using Risk-tunable thresholds.
 * Kept separate from scoring so thresholds change without touching the model.
 */

import { readFileSync } from 'node:fs';
import { isReasonCode } from './reasons.ts';
import type { Decision, ScoreResult } from './types.ts';

export type { Decision } from './types.ts';

/** A Decision that may record a scorer failure. Reasons are empty in that case. */
export type PolicyDecision = Decision & { scorerFailed?: true };

export type PolicyThresholds = {
  stepUpFrom: number;
  holdFrom: number;
  declineFrom: number;
  version: string;
};

export const DEFAULT_THRESHOLDS: PolicyThresholds = {
  stepUpFrom: 300,
  holdFrom: 700,
  declineFrom: 850,
  version: 'arch-0.7-defaults',
};

const DEFAULT_PATH = 'config/risk-thresholds.json';

export function validateThresholds(x: unknown): PolicyThresholds {
  if (x === null || typeof x !== 'object' || Array.isArray(x)) {
    throw new Error('risk thresholds must be an object');
  }
  const o = x as Record<string, unknown>;
  for (const key of ['stepUpFrom', 'holdFrom', 'declineFrom'] as const) {
    if (!Number.isInteger(o[key])) {
      throw new Error(`risk thresholds: ${key} must be an integer, got ${JSON.stringify(o[key])}`);
    }
  }
  const stepUpFrom = o.stepUpFrom as number;
  const holdFrom = o.holdFrom as number;
  const declineFrom = o.declineFrom as number;
  if (!(stepUpFrom >= 0 && stepUpFrom <= holdFrom && holdFrom <= declineFrom && declineFrom <= 1000)) {
    throw new Error(
      `risk thresholds must satisfy 0 <= stepUpFrom <= holdFrom <= declineFrom <= 1000, got ${stepUpFrom}, ${holdFrom}, ${declineFrom}`,
    );
  }
  if (typeof o.version !== 'string' || o.version.trim() === '') {
    throw new Error('risk thresholds: version must be a non-empty string');
  }
  return { stepUpFrom, holdFrom, declineFrom, version: o.version };
}

export function loadThresholds(path?: string): PolicyThresholds {
  const file = path ?? process.env.RISK_THRESHOLDS_PATH ?? DEFAULT_PATH;
  let raw: string;
  try {
    raw = readFileSync(file, 'utf8');
  } catch (error) {
    throw new Error(`cannot read risk thresholds from ${file}: ${(error as Error).message}`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new Error(`risk thresholds in ${file} are not valid JSON: ${(error as Error).message}`);
  }
  return validateThresholds(parsed);
}

/** Local check of the ScoreResult contract, so this file does not depend on scoring.ts. */
function isValidScoreResult(x: unknown): x is ScoreResult {
  if (x === null || typeof x !== 'object') return false;
  const r = x as Record<string, unknown>;
  return (
    Number.isInteger(r.score) &&
    (r.score as number) >= 0 &&
    (r.score as number) <= 1000 &&
    Array.isArray(r.reasons) &&
    r.reasons.length >= 1 &&
    r.reasons.length <= 3 &&
    r.reasons.every(c => typeof c === 'string' && isReasonCode(c)) &&
    typeof r.modelVersion === 'string' &&
    r.modelVersion !== ''
  );
}

export class DecisionPolicy {
  readonly thresholds: PolicyThresholds;

  constructor(t: PolicyThresholds) {
    this.thresholds = validateThresholds(t);
  }

  decide(result: ScoreResult | { error: unknown }): PolicyDecision {
    const thresholdsVersion = this.thresholds.version;
    if (!isValidScoreResult(result)) {
      return { outcome: 'hold', score: 0, reasons: [], thresholdsVersion, scorerFailed: true };
    }
    const { score, reasons } = result;
    const t = this.thresholds;
    const outcome =
      score >= t.declineFrom ? 'decline'
      : score >= t.holdFrom ? 'hold'
      : score >= t.stepUpFrom ? 'step_up'
      : 'approve';
    return { outcome, score, reasons: [...reasons], thresholdsVersion };
  }
}
