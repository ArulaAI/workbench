/*
 * Risk narrative writer. The narrative goes to an external AI vendor, so this module is
 * its own trust boundary: only reason codes, score, amount band, merchant category and
 * the issuer and IP countries may cross it. Failures never propagate to the caller.
 */

import type { ReasonCode } from './reasons.ts';
import { analystReason } from './reasons.ts';
import type { ReviewItem } from '../review/queue.ts';
import { log } from '../obs/index.ts';

/** Bands are in major units of the payment currency. */
export type AmountBand = 'under_100' | '100_to_999' | '1000_to_4999' | '5000_plus';

export type NarrativeInput = {
  reasons: ReasonCode[];
  score: number;
  amountBand: AmountBand;
  merchantCategory: string;
  issuerCountry: string | null;
  ipCountry: string;
};

export type NarrativeContext = Pick<NarrativeInput, 'merchantCategory' | 'issuerCountry' | 'ipCountry'>;

/** Injected so tests can spy on it and the payments path gains no runtime dependency. */
export type NarrativeClient = { complete(prompt: string): Promise<string> };

const ALLOWED_KEYS: ReadonlySet<string> = new Set([
  'reasons', 'score', 'amountBand', 'merchantCategory', 'issuerCountry', 'ipCountry',
]);

const MINOR_PER_MAJOR = 100;
const DEFAULT_TIMEOUT_MS = 10_000;

/** Item amounts are minor units, so 249900 is 2,499.00 in the payment currency. */
export const amountBandFor = (minorAmount: number): AmountBand => {
  const major = minorAmount / MINOR_PER_MAJOR;
  if (major < 100) return 'under_100';
  if (major < 1000) return '100_to_999';
  if (major < 5000) return '1000_to_4999';
  return '5000_plus';
};

export const buildNarrativeInput = (item: ReviewItem, ctx: NarrativeContext): NarrativeInput => ({
  reasons: [...item.reasons],
  score: item.score,
  amountBand: amountBandFor(item.amount),
  merchantCategory: ctx.merchantCategory,
  issuerCountry: ctx.issuerCountry,
  ipCountry: ctx.ipCountry,
});

const strings = (value: unknown, out: string[] = []): string[] => {
  if (typeof value === 'string') out.push(value);
  else if (typeof value === 'number' || typeof value === 'bigint') out.push(String(value));
  else if (Array.isArray(value)) value.forEach(v => strings(v, out));
  else if (value && typeof value === 'object') Object.values(value).forEach(v => strings(v, out));
  return out;
};

/** Throws if the input carries a key outside the allowed set or anything shaped like card data. */
export const assertNoCardData = (input: NarrativeInput): void => {
  for (const key of Object.keys(input)) {
    if (!ALLOWED_KEYS.has(key)) throw new Error(`narrative input has disallowed key '${key}'`);
  }
  for (const s of strings(input)) {
    if (/\d{6,}/.test(s)) throw new Error('narrative input contains a run of 6 or more digits');
    if (/\*\s*\d{4}|\d{4}\s*\*/.test(s)) throw new Error('narrative input contains a last-four pattern');
  }
};

const buildPrompt = (input: NarrativeInput): string =>
  [
    'Write a two sentence plain-English summary for a payments fraud analyst explaining why a payment was held for review.',
    'Use only the facts below. Do not speculate about the cardholder.',
    `Risk score: ${input.score}`,
    `Amount band (major currency units): ${input.amountBand}`,
    `Merchant category: ${input.merchantCategory}`,
    `Issuer country: ${input.issuerCountry ?? 'unknown'}`,
    `IP country: ${input.ipCountry}`,
    'Signals:',
    ...input.reasons.map(r => `- ${analystReason(r)}`),
  ].join('\n');

export class NarrativeWriter {
  readonly #client: NarrativeClient;
  readonly #timeoutMs: number;

  constructor(client: NarrativeClient, opts: { timeoutMs?: number } = {}) {
    this.#client = client;
    this.#timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  /** Returns undefined on any failure or timeout. Never throws. */
  async describe(input: NarrativeInput): Promise<string | undefined> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`narrative timed out after ${this.#timeoutMs}ms`)), this.#timeoutMs);
      });
      const text = await Promise.race([this.#client.complete(buildPrompt(input)), timeout]);
      return typeof text === 'string' && text.length > 0 ? text : undefined;
    } catch (error) {
      log.error(`narrative failed: ${error instanceof Error ? error.message : String(error)}`);
      return undefined;
    } finally {
      clearTimeout(timer);
    }
  }
}
