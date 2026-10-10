/*
 * The F2.2 card-testing runtime loop.
 *
 * tick() runs once per refreshIntervalMs on every replica: flush and purge attempts, run
 * the detector on the elected replica only, then refresh the in-memory block list. A
 * failure in the attempt store or detector is logged and swallowed, so the authorisation
 * path is never affected.
 */

import type { AttemptRecorder } from './attempts.ts';
import type { Attack, AttackDetector } from './attacks.ts';
import type { BlockList } from './blocks.ts';
import type { Clock, DetectorConfig } from './detector-config.ts';
import type { MerchantNotifier } from '../notify/merchant.ts';
import { log } from '../obs/index.ts';

export interface DetectorLease {
  tryAcquire(replicaId: string, now: number): boolean;
}

/** Single-holder lease with a TTL of 3 x refreshIntervalMs. Share one instance across runtimes. */
export class InMemoryDetectorLease implements DetectorLease {
  private holder: string | undefined;
  private expiresAt = 0;
  private readonly ttlMs: number;

  constructor(refreshIntervalMs: number) {
    this.ttlMs = 3 * refreshIntervalMs;
  }

  tryAcquire(replicaId: string, now: number): boolean {
    if (this.holder !== undefined && this.holder !== replicaId && now < this.expiresAt) return false;
    this.holder = replicaId;
    this.expiresAt = now + this.ttlMs;
    return true;
  }
}

export type RuntimeLogger = {
  info(message: string): void;
  alert(message: string): void;
};

/** The shared log has no alert level, so alerts go out at error level. */
export const defaultRuntimeLogger: RuntimeLogger = {
  info: m => log.info(m),
  alert: m => log.error(m),
};

export type CardTestingRuntimeDeps = {
  recorder: AttemptRecorder;
  detector: AttackDetector;
  blocks: BlockList;
  notifier: MerchantNotifier;
  lease: DetectorLease;
  config: DetectorConfig;
  clock: Clock;
  logger?: RuntimeLogger;
  /** Identifies this replica to the lease. Defaults to a process-unique id. */
  replicaId?: string;
};

let replicaSeq = 0;

export class CardTestingRuntime {
  private readonly recorder: AttemptRecorder;
  private readonly detector: AttackDetector;
  private readonly blocks: BlockList;
  private readonly notifier: MerchantNotifier;
  private readonly lease: DetectorLease;
  private readonly config: DetectorConfig;
  private readonly clock: Clock;
  private readonly logger: RuntimeLogger;
  private readonly replicaId: string;
  private timer: ReturnType<typeof setInterval> | undefined;

  constructor(deps: CardTestingRuntimeDeps) {
    this.recorder = deps.recorder;
    this.detector = deps.detector;
    this.blocks = deps.blocks;
    this.notifier = deps.notifier;
    this.lease = deps.lease;
    this.config = deps.config;
    this.clock = deps.clock;
    this.logger = deps.logger ?? defaultRuntimeLogger;
    this.replicaId = deps.replicaId ?? `replica_${(++replicaSeq).toString(36).padStart(4, '0')}`;
  }

  tick(now: number = this.clock()): void {
    try {
      this.recorder.flush();
      this.recorder.purgeExpired(now);
    } catch (error) {
      this.paused(error);
    }

    try {
      if (this.lease.tryAcquire(this.replicaId, now)) this.lead(now);
    } catch (error) {
      this.paused(error);
    }

    try {
      this.blocks.refresh(now);
    } catch (error) {
      this.paused(error);
    }
  }

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => this.tick(), this.config.refreshIntervalMs);
    this.timer.unref?.();
  }

  stop(): void {
    if (!this.timer) return;
    clearInterval(this.timer);
    this.timer = undefined;
  }

  private lead(now: number): void {
    const shadow = this.config.mode === 'shadow';
    for (const attack of this.detector.run(now)) {
      this.flagged(attack, shadow);
    }
    this.blocks.expire(now);
    this.notifier.tick(now);
  }

  private flagged(attack: Attack, shadow: boolean): void {
    if (!shadow) {
      this.blocks.createFor(attack);
      this.notifier.onFlagged(attack);
    }
    this.logger.info(
      `card_testing.attack_flagged id=${attack.id} cards=${attack.cards} merchants=${attack.merchants.length} mode=${this.config.mode}`,
    );
  }

  private paused(error: unknown): void {
    this.logger.alert(`card_testing.detection_paused: ${error instanceof Error ? error.message : String(error)}`);
  }
}
