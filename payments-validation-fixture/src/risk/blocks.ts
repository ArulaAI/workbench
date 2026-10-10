/*
 * Blocks for flagged card-testing attacks (F2.2).
 *
 * The store is shared across replicas. Each BlockList keeps its own in-memory copy of the
 * active blocks, keyed by BIN, so the authorisation path never calls the store. The copy
 * is only as fresh as the last refresh().
 */

import type { Attack, AttackStore } from './attacks.ts';
import type { Clock, DetectorConfig } from './detector-config.ts';
import type { AuditLog } from '../review/audit.ts';
import { log } from '../obs/index.ts';

export type Block = {
  attackId: string;
  bin: string;
  amountCeiling: number;
  scope: 'all_merchants';
  expiresAt: number;
};

export interface BlockStore {
  insert(block: Block): void;
  remove(attackId: string): void;
  /** Blocks whose expiresAt is after `now`. */
  listActive(now: number): Block[];
}

export class InMemoryBlockStore implements BlockStore {
  private readonly blocks = new Map<string, Block>();

  insert(block: Block): void {
    if (this.blocks.has(block.attackId)) throw new RangeError(`block for ${block.attackId} already exists`);
    this.blocks.set(block.attackId, { ...block });
  }

  remove(attackId: string): void {
    this.blocks.delete(attackId);
  }

  listActive(now: number): Block[] {
    return [...this.blocks.values()].filter(b => b.expiresAt > now).map(b => ({ ...b }));
  }
}

export class BlockList {
  private readonly store: BlockStore;
  private readonly attacks: AttackStore;
  private readonly audit: AuditLog;
  private readonly config: DetectorConfig;
  private readonly clock: Clock;
  private loaded = new Map<string, Block>();

  constructor(store: BlockStore, attacks: AttackStore, audit: AuditLog, config: DetectorConfig, clock: Clock) {
    this.store = store;
    this.attacks = attacks;
    this.audit = audit;
    this.config = config;
    this.clock = clock;
  }

  createFor(attack: Attack): Block {
    const block: Block = {
      attackId: attack.id,
      bin: attack.bin,
      amountCeiling: this.config.smallAmountCeiling,
      scope: 'all_merchants',
      expiresAt: attack.flaggedAt + this.config.blockTtlMs,
    };
    this.store.insert(block);
    return block;
  }

  /** Reload this replica's blocks. On failure the last loaded set stays in place. */
  refresh(now: number = this.clock()): void {
    try {
      const next = new Map<string, Block>();
      for (const b of this.store.listActive(now)) {
        const existing = next.get(b.bin);
        if (!existing || b.expiresAt > existing.expiresAt) next.set(b.bin, b);
      }
      this.loaded = next;
    } catch (error) {
      log.error(`blocks.refresh_failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  /** In-memory only. Makes no store call. */
  matches({ bin, amount }: { bin: string; amount: number }): Block | undefined {
    const block = this.loaded.get(bin);
    if (!block) return undefined;
    return amount <= block.amountCeiling && block.expiresAt > this.clock() ? block : undefined;
  }

  /** Expire blocked attacks whose block TTL has elapsed. Released attacks are left alone. */
  expire(now: number = this.clock()): Attack[] {
    const expired: Attack[] = [];
    for (const attack of this.attacks.listByStatus('blocked')) {
      if (attack.flaggedAt + this.config.blockTtlMs > now) continue;
      const updated: Attack = { ...attack, status: 'expired' };
      this.attacks.update(updated);
      this.removeFor(attack.id);
      this.audit.record({
        action: 'expire',
        subjectId: attack.id,
        actor: 'system',
        reason: 'block ttl elapsed',
        at: now,
      });
      expired.push(updated);
    }
    return expired;
  }

  removeFor(attackId: string): void {
    this.store.remove(attackId);
    for (const [bin, block] of this.loaded) {
      if (block.attackId === attackId) this.loaded.delete(bin);
    }
  }
}
