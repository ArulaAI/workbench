/*
 * Small-authorisation attempt recording for the F2.2 card-testing detector.
 *
 * Records hold only BIN, last four and a `bin:last4` key. A PAN-shaped value (12 or more
 * consecutive digits) in any string field is rejected and never stored or logged.
 */

import type { Clock, DetectorConfig } from './detector-config.ts';
import { log } from '../obs/index.ts';

export type AttemptRecord = {
  cardKey: string;
  bin: string;
  amount: number;
  merchantId: string;
  ipCountry: string;
  at: number;
};

export interface AttemptStore {
  insertMany(records: AttemptRecord[]): void;
  since(fromMs: number): AttemptRecord[];
  deleteOlderThan(cutoffMs: number): number;
}

/** Stands in for the shared Postgres table. Share one instance across recorders. */
export class InMemoryAttemptStore implements AttemptStore {
  private records: AttemptRecord[] = [];

  insertMany(records: AttemptRecord[]): void {
    this.records.push(...records.map(r => ({ ...r })));
  }

  since(fromMs: number): AttemptRecord[] {
    return this.records.filter(r => r.at >= fromMs).map(r => ({ ...r }));
  }

  deleteOlderThan(cutoffMs: number): number {
    const before = this.records.length;
    this.records = this.records.filter(r => r.at >= cutoffMs);
    return before - this.records.length;
  }
}

/** Same key format as RiskRules.evaluate in src/risk/rules.ts. */
export const cardKeyOf = (bin: string, last4: string): string => `${bin}:${last4}`;

const CARD_KEY = /^\d{6}:\d{4}$/;
const PAN_SHAPED = /\d{12,}/;
const RETENTION_MS = 60 * 60 * 1000;

export class AttemptRecorder {
  healthy = true;
  private buffer: AttemptRecord[] = [];
  private readonly store: AttemptStore;
  private readonly config: DetectorConfig;
  private readonly clock: Clock;
  private readonly logger: typeof log;

  constructor(store: AttemptStore, config: DetectorConfig, clock: Clock, logger: typeof log = log) {
    this.store = store;
    this.config = config;
    this.clock = clock;
    this.logger = logger;
  }

  record(attempt: AttemptRecord): void {
    try {
      const fields = [attempt?.cardKey, attempt?.bin, attempt?.merchantId, attempt?.ipCountry];
      if (fields.some(f => typeof f === 'string' && PAN_SHAPED.test(f))) {
        this.logger.error('attempts.rejected_pan');
        return;
      }
      if (
        typeof attempt.cardKey !== 'string' || !CARD_KEY.test(attempt.cardKey) ||
        typeof attempt.bin !== 'string' || typeof attempt.merchantId !== 'string' ||
        typeof attempt.ipCountry !== 'string' ||
        !Number.isFinite(attempt.amount) || !Number.isFinite(attempt.at) ||
        attempt.cardKey !== cardKeyOf(attempt.bin, attempt.cardKey.slice(-4))
      ) {
        this.logger.error('attempts.rejected_invalid');
        return;
      }
      if (attempt.amount > this.config.smallAmountCeiling) return;
      this.buffer.push({
        cardKey: attempt.cardKey,
        bin: attempt.bin,
        amount: attempt.amount,
        merchantId: attempt.merchantId,
        ipCountry: attempt.ipCountry,
        at: attempt.at,
      });
    } catch {
      // record() never throws to its caller.
    }
  }

  flush(): void {
    if (this.buffer.length === 0) return;
    const pending = this.buffer;
    try {
      this.store.insertMany(pending);
      this.buffer = this.buffer.slice(pending.length);
      this.healthy = true;
    } catch (error) {
      this.healthy = false;
      this.logger.error(`attempts.flush_failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  purgeExpired(now: number): number {
    return this.store.deleteOlderThan(now - RETENTION_MS);
  }
}
