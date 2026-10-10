/*
 * In-process scoring service. Architecture component 'Scoring service'.
 *
 * A gradient-boosted tree ensemble, read once at start-up, scores a ScoringInput into
 * 0 to 1000 and attributes the score to one to three ReasonCodes. The scorer is
 * stateless: no cross-request memory, so the same input always gives the same result.
 *
 * The model format is an assumption until data science delivers theirs. Swapping it
 * means a new Scorer implementation; callers depend on the interface only.
 */

import { readFileSync } from 'node:fs';
import type { GatewayRequest } from '../payments/gateway.ts';
import { span } from '../obs/index.ts';
import { issuerCountry } from './issuers.ts';
import { type ReasonCode, isReasonCode } from './reasons.ts';
import type { ScoreResult, ScoringInput } from './types.ts';

export type { ScoreResult, ScoringInput } from './types.ts';

export interface Scorer {
  score(input: ScoringInput): ScoreResult;
}

const MIN_SCORE = 0;
const MAX_SCORE = 1000;
const MAX_REASONS = 3;
const RESERVED_REASON: ReasonCode = 'card_testing_pattern';

/**
 * Build the scorer's input from a gateway request. The PAN is reduced to its BIN and
 * then dropped; nothing else from the card travels further.
 */
export const toScoringInput = (
  req: GatewayRequest,
  merchantCategory: string,
  now: () => number = Date.now,
): ScoringInput => {
  const bin = req.pan.replace(/\D/g, '').slice(0, 6);
  return {
    bin,
    amount: req.amount,
    currency: req.currency ?? 'GBP',
    issuerCountry: issuerCountry(bin) ?? undefined,
    ipCountry: req.ipCountry,
    merchantId: req.merchantId,
    merchantCategory,
    at: req.at ?? now(),
  };
};

/** A split goes left when the feature value is below the threshold. Missing features read as 0. */
export type TreeNode =
  | { leaf: number }
  | { feature: string; threshold: number; left: TreeNode; right: TreeNode };

export type Model = {
  version: string;
  baseScore: number;
  trees: TreeNode[];
  featureReasons: Record<string, ReasonCode>;
};

/** Named numeric features the trees split on. */
export const features = (input: ScoringInput): Record<string, number> => {
  const issuer = input.issuerCountry;
  return {
    amount: input.amount,
    hour: new Date(input.at).getUTCHours(),
    issuer_unknown: issuer === undefined ? 1 : 0,
    country_mismatch: issuer !== undefined && issuer !== input.ipCountry ? 1 : 0,
    [`currency=${input.currency}`]: 1,
    [`bin=${input.bin}`]: 1,
    [`issuer_country=${issuer ?? 'unknown'}`]: 1,
    [`ip_country=${input.ipCountry}`]: 1,
    [`merchant_category=${input.merchantCategory}`]: 1,
  };
};

const isObject = (x: unknown): x is Record<string, unknown> =>
  typeof x === 'object' && x !== null && !Array.isArray(x);

const parseNode = (x: unknown, where: string): TreeNode => {
  if (!isObject(x)) throw new Error(`${where} is not an object`);
  if ('leaf' in x) {
    if (typeof x.leaf !== 'number' || !Number.isFinite(x.leaf)) throw new Error(`${where}.leaf is not a finite number`);
    return { leaf: x.leaf };
  }
  if (typeof x.feature !== 'string' || x.feature === '') throw new Error(`${where}.feature is missing`);
  if (typeof x.threshold !== 'number' || !Number.isFinite(x.threshold)) {
    throw new Error(`${where}.threshold is not a finite number`);
  }
  return {
    feature: x.feature,
    threshold: x.threshold,
    left: parseNode(x.left, `${where}.left`),
    right: parseNode(x.right, `${where}.right`),
  };
};

const parseModel = (x: unknown): Model => {
  if (!isObject(x)) throw new Error('model is not an object');
  if (typeof x.version !== 'string' || x.version === '') throw new Error('version is missing');
  if (typeof x.baseScore !== 'number' || !Number.isFinite(x.baseScore)) throw new Error('baseScore is not a finite number');
  if (!Array.isArray(x.trees)) throw new Error('trees is not an array');
  if (!isObject(x.featureReasons)) throw new Error('featureReasons is not an object');

  const featureReasons: Record<string, ReasonCode> = {};
  for (const [feature, code] of Object.entries(x.featureReasons)) {
    if (!isReasonCode(code)) throw new Error(`featureReasons.${feature} is not a known reason code`);
    if (code === RESERVED_REASON) throw new Error(`featureReasons.${feature} maps to reserved ${RESERVED_REASON}`);
    featureReasons[feature] = code;
  }
  if (Object.keys(featureReasons).length === 0) throw new Error('featureReasons is empty');

  return {
    version: x.version,
    baseScore: x.baseScore,
    trees: x.trees.map((t, i) => parseNode(t, `trees[${i}]`)),
    featureReasons,
  };
};

/** Walk one tree. Returns its leaf value and the feature of the last split on the path. */
const evaluate = (node: TreeNode, f: Record<string, number>): { value: number; feature: string | undefined } => {
  let current = node;
  let feature: string | undefined;
  while (!('leaf' in current)) {
    feature = current.feature;
    current = (f[current.feature] ?? 0) < current.threshold ? current.left : current.right;
  }
  return { value: current.leaf, feature };
};

export class ModelScorer implements Scorer {
  private readonly model: Model;

  private constructor(model: Model) {
    this.model = model;
  }

  /** Read and validate a serialised model. Throws, naming the path, if it is missing or malformed. */
  static load(path: string): ModelScorer {
    let text: string;
    try {
      text = readFileSync(path, 'utf8');
    } catch (error) {
      throw new Error(`cannot read model file ${path}: ${(error as Error).message}`);
    }
    let raw: unknown;
    try {
      raw = JSON.parse(text);
    } catch (error) {
      throw new Error(`model file ${path} is not valid JSON: ${(error as Error).message}`);
    }
    try {
      return new ModelScorer(parseModel(raw));
    } catch (error) {
      throw new Error(`model file ${path} is malformed: ${(error as Error).message}`);
    }
  }

  get version(): string {
    return this.model.version;
  }

  score(input: ScoringInput): ScoreResult {
    const f = features(input);
    const byReason = new Map<ReasonCode, number>();
    let total = this.model.baseScore;

    for (const tree of this.model.trees) {
      const { value, feature } = evaluate(tree, f);
      total += value;
      const code = feature === undefined ? undefined : this.model.featureReasons[feature];
      if (code !== undefined) byReason.set(code, (byReason.get(code) ?? 0) + value);
    }

    const score = Math.round(Math.min(MAX_SCORE, Math.max(MIN_SCORE, total)));
    const reasons = this.reasonsFor(byReason);
    const result: ScoreResult = { score, reasons, modelVersion: this.model.version };
    span('risk.score', { modelVersion: result.modelVersion, score, reasons });
    return result;
  }

  /** Top positive contributors, largest first, ties alphabetical. Never empty, never the reserved code. */
  private reasonsFor(byReason: Map<ReasonCode, number>): ReasonCode[] {
    const ranked = [...byReason.entries()]
      .filter(([code]) => code !== RESERVED_REASON)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    const positive = ranked.filter(([, v]) => v > 0).slice(0, MAX_REASONS).map(([code]) => code);
    if (positive.length > 0) return positive;
    if (ranked.length > 0) return [ranked[0][0]];
    return [Object.values(this.model.featureReasons)[0]];
  }
}

/** Integer score 0 to 1000, one to three known reason codes, a non-empty model version. */
export const validateScoreResult = (r: unknown): r is ScoreResult => {
  if (!isObject(r)) return false;
  const { score, reasons, modelVersion } = r;
  return (
    typeof score === 'number' && Number.isInteger(score) && score >= MIN_SCORE && score <= MAX_SCORE &&
    Array.isArray(reasons) && reasons.length >= 1 && reasons.length <= MAX_REASONS && reasons.every(isReasonCode) &&
    typeof modelVersion === 'string' && modelVersion !== ''
  );
};
