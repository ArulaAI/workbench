/*
 * Append-only audit log. Every audit entry about a review item uses the review id as
 * its subjectId, so forSubject(reviewId) is the item's full history.
 */

export type AuditAction = 'hold' | 'approve' | 'decline' | 'expire' | 'release';

export type AuditEntry = {
  id: string;
  action: AuditAction;
  subjectId: string;
  /** Analyst identity, or 'system'. */
  actor: string;
  reason: string;
  at: number;
};

export interface AuditLog {
  record(entry: Omit<AuditEntry, 'id' | 'at'> & { at?: number }): AuditEntry;
  forSubject(subjectId: string): AuditEntry[];
}

export class InMemoryAuditLog implements AuditLog {
  readonly #entries: AuditEntry[] = [];
  #seq = 0;

  record(entry: Omit<AuditEntry, 'id' | 'at'> & { at?: number }): AuditEntry {
    if (entry.actor !== 'system' && entry.reason.trim() === '') {
      throw new RangeError('audit reason must be non-empty when the actor is not system');
    }
    const recorded: AuditEntry = Object.freeze({
      id: `aud_${(++this.#seq).toString(36).padStart(6, '0')}`,
      action: entry.action,
      subjectId: entry.subjectId,
      actor: entry.actor,
      reason: entry.reason,
      at: entry.at ?? Date.now(),
    });
    this.#entries.push(recorded);
    return recorded;
  }

  /** Ordered by (subjectId, at); insertion order breaks ties. */
  forSubject(subjectId: string): AuditEntry[] {
    return this.#entries
      .filter(e => e.subjectId === subjectId)
      .sort((a, b) => a.at - b.at);
  }
}
