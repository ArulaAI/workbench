/*
 * Attacks console backend contract. Analyst identity comes from the ConsoleSession,
 * never from a request body.
 */

import type { Attack, AttackStore } from '../risk/attacks.ts';
import type { BlockList } from '../risk/blocks.ts';
import type { Clock } from '../risk/detector-config.ts';
import type { AuditLog } from './audit.ts';
import { ConsoleError, requireAnalyst, type ConsoleSession } from './console.ts';

const MAX_REASON_LENGTH = 1000;

export class AttacksConsole {
  readonly #attacks: AttackStore;
  readonly #blocks: BlockList;
  readonly #audit: AuditLog;
  readonly #clock: Clock;

  constructor(attacks: AttackStore, blocks: BlockList, audit: AuditLog, clock: Clock) {
    this.#attacks = attacks;
    this.#blocks = blocks;
    this.#audit = audit;
    this.#clock = clock;
  }

  /** Blocked attacks, newest flaggedAt first. */
  listAttacks(): Attack[] {
    return this.#attacks.listByStatus('blocked').sort(byNewest);
  }

  getAttack(id: string): Attack {
    const attack = this.#attacks.get(id);
    if (!attack) throw new ConsoleError('ATTACK_NOT_FOUND', `no attack ${id}`);
    return attack;
  }

  release(id: string, session: ConsoleSession, reason: string): Attack {
    const analyst = requireAnalyst(session);
    const attack = this.#attacks.get(id);
    if (!attack) throw new ConsoleError('ATTACK_NOT_FOUND', `no attack ${id}`);
    const trimmed = typeof reason === 'string' ? reason.trim() : '';
    if (trimmed === '') throw new ConsoleError('REASON_REQUIRED', 'a release reason is required');
    if (trimmed.length > MAX_REASON_LENGTH) {
      throw new ConsoleError('REASON_TOO_LONG', `reason exceeds ${MAX_REASON_LENGTH} characters`);
    }
    if (attack.status !== 'blocked') {
      throw new ConsoleError('NOT_BLOCKED', `attack ${id} is ${attack.status}, not blocked`);
    }

    const released: Attack = { ...attack, status: 'released', releasedBy: analyst, releaseReason: trimmed };
    this.#attacks.update(released);
    this.#blocks.removeFor(id);
    this.#audit.record({ action: 'release', subjectId: id, actor: analyst, reason: trimmed, at: this.#clock() });
    return released;
  }

  /** Released and expired attacks, newest first, for the empty-state link. */
  listRecentlyClosed(limit: number): Attack[] {
    return [...this.#attacks.listByStatus('released'), ...this.#attacks.listByStatus('expired')]
      .sort(byNewest)
      .slice(0, Math.max(0, limit));
  }
}

const byNewest = (a: Attack, b: Attack): number => b.flaggedAt - a.flaggedAt || a.id.localeCompare(b.id);
