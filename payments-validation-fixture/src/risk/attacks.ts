/*
 * Card-testing attacks for F2.2.
 *
 * The detector groups recent small-authorisation attempts by (bin, amount) and flags an
 * attack when enough distinct cards are tried across enough distinct merchants inside
 * the window. It only flags. Blocks and notifications are built from the returned attacks.
 */

import type { AttemptRecord, AttemptStore } from './attempts.ts';
import type { Clock, DetectorConfig } from './detector-config.ts';

export type AttackStatus = 'blocked' | 'released' | 'expired';

export type MerchantActivity = { merchantId: string; attempts: number; firstAt: number; lastAt: number };

export type Attack = {
  id: string;
  bin: string;
  amount: number;
  firstSeenAt: number;
  flaggedAt: number;
  /** Distinct cards seen in the triggering window. A retried card counts once. */
  cards: number;
  merchants: MerchantActivity[];
  status: AttackStatus;
  releasedBy: string | null;
  releaseReason: string | null;
};

export interface AttackStore {
  insert(attack: Attack): void;
  get(id: string): Attack | undefined;
  update(attack: Attack): void;
  listByStatus(status: AttackStatus): Attack[];
  /** The blocked attack for this (bin, amount), if any. */
  activeFor(bin: string, amount: number): Attack | undefined;
}

const copy = (a: Attack): Attack => ({ ...a, merchants: a.merchants.map(m => ({ ...m })) });

export class InMemoryAttackStore implements AttackStore {
  private readonly attacks = new Map<string, Attack>();

  insert(attack: Attack): void {
    if (this.attacks.has(attack.id)) throw new RangeError(`attack ${attack.id} already exists`);
    this.attacks.set(attack.id, copy(attack));
  }

  get(id: string): Attack | undefined {
    const a = this.attacks.get(id);
    return a ? copy(a) : undefined;
  }

  update(attack: Attack): void {
    if (!this.attacks.has(attack.id)) throw new RangeError(`unknown attack ${attack.id}`);
    this.attacks.set(attack.id, copy(attack));
  }

  listByStatus(status: AttackStatus): Attack[] {
    return [...this.attacks.values()].filter(a => a.status === status).map(copy);
  }

  activeFor(bin: string, amount: number): Attack | undefined {
    for (const a of this.attacks.values()) {
      if (a.status === 'blocked' && a.bin === bin && a.amount === amount) return copy(a);
    }
    return undefined;
  }
}

let seq = 0;
const nextAttackId = (): string => `atk_${String(++seq).padStart(6, '0')}`;

const merchantActivity = (attempts: AttemptRecord[]): MerchantActivity[] => {
  const byMerchant = new Map<string, MerchantActivity>();
  for (const a of attempts) {
    const m = byMerchant.get(a.merchantId);
    if (!m) {
      byMerchant.set(a.merchantId, { merchantId: a.merchantId, attempts: 1, firstAt: a.at, lastAt: a.at });
    } else {
      m.attempts += 1;
      m.firstAt = Math.min(m.firstAt, a.at);
      m.lastAt = Math.max(m.lastAt, a.at);
    }
  }
  return [...byMerchant.values()].sort((x, y) => x.firstAt - y.firstAt || x.merchantId.localeCompare(y.merchantId));
};

export class AttackDetector {
  private readonly attempts: AttemptStore;
  private readonly attacks: AttackStore;
  private readonly config: DetectorConfig;
  private readonly clock: Clock;

  constructor(attempts: AttemptStore, attacks: AttackStore, config: DetectorConfig, clock: Clock) {
    this.attempts = attempts;
    this.attacks = attacks;
    this.config = config;
    this.clock = clock;
  }

  /** Flag new attacks from attempts in [now - windowMs, now]. Returns only this run's attacks. */
  run(now: number = this.clock()): Attack[] {
    const windowStart = now - this.config.windowMs;
    const groups = new Map<string, AttemptRecord[]>();
    for (const a of this.attempts.since(windowStart)) {
      if (a.at < windowStart || a.at > now) continue;
      const key = `${a.bin}|${a.amount}`;
      const group = groups.get(key);
      if (group) group.push(a);
      else groups.set(key, [a]);
    }

    const flagged: Attack[] = [];
    for (const group of groups.values()) {
      const cards = new Set(group.map(a => a.cardKey)).size;
      const merchants = new Set(group.map(a => a.merchantId)).size;
      if (cards < this.config.minCards || merchants < this.config.minMerchants) continue;

      const { bin, amount } = group[0];
      if (this.attacks.activeFor(bin, amount)) continue;

      const attack: Attack = {
        id: nextAttackId(),
        bin,
        amount,
        firstSeenAt: Math.min(...group.map(a => a.at)),
        flaggedAt: now,
        cards,
        merchants: merchantActivity(group),
        status: 'blocked',
        releasedBy: null,
        releaseReason: null,
      };
      this.attacks.insert(attack);
      flagged.push(copy(attack));
    }
    return flagged;
  }

  /** Blocked attacks, newest first. */
  activeAttacks(): Attack[] {
    return this.attacks
      .listByStatus('blocked')
      .sort((x, y) => y.flaggedAt - x.flaggedAt || y.id.localeCompare(x.id));
  }

  getAttack(id: string): Attack | undefined {
    return this.attacks.get(id);
  }

  /**
   * Recount per-merchant activity for the attack's (bin, amount) from firstSeenAt to now,
   * so attempts that arrive after the flag show up. Counts never shrink, which keeps the
   * timeline intact once older attempts are purged from the attempt store.
   */
  refreshTimeline(attackId: string, now: number = this.clock()): Attack | undefined {
    const attack = this.attacks.get(attackId);
    if (!attack) return undefined;

    const fresh = merchantActivity(
      this.attempts
        .since(attack.firstSeenAt)
        .filter(a => a.at <= now && a.bin === attack.bin && a.amount === attack.amount),
    );

    const merged = new Map(attack.merchants.map(m => [m.merchantId, { ...m }]));
    for (const f of fresh) {
      const m = merged.get(f.merchantId);
      if (!m) {
        merged.set(f.merchantId, f);
      } else {
        m.attempts = Math.max(m.attempts, f.attempts);
        m.firstAt = Math.min(m.firstAt, f.firstAt);
        m.lastAt = Math.max(m.lastAt, f.lastAt);
      }
    }
    attack.merchants = [...merged.values()].sort(
      (x, y) => x.firstAt - y.firstAt || x.merchantId.localeCompare(y.merchantId),
    );
    this.attacks.update(attack);
    return copy(attack);
  }
}
