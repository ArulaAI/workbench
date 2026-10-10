/*
 * Review queue store. Phase 1 builds the data model and the hold write path only.
 * Analyst decisions and expiry are added later without changing the gateway.
 */

import type { ReasonCode } from '../risk/reasons.ts';
import { analystReason } from '../risk/reasons.ts';
import type { AuditLog } from './audit.ts';
import type { PaymentsService } from '../payments/service.ts';
import { log } from '../obs/index.ts';

export type ReviewStatus = 'held' | 'approved' | 'declined' | 'expired';

export type ReviewItem = {
  id: string;
  paymentId: string;
  maskedCard: string;
  merchantId: string;
  amount: number;
  score: number;
  analystReason: string;
  narrative: string | null;
  heldAt: number;
  status: ReviewStatus;
  decidedBy: string | null;
  note: string | null;
  decidedAt: number | null;
  // Context for the queue design and the narrative. None of it is card data.
  reasons: ReasonCode[];
  currency: string;
  merchantCategory: string;
  issuerCountry: string | null;
  ipCountry: string;
};

export type HoldArgs = {
  paymentId: string;
  maskedCard: string;
  merchantId: string;
  amount: number;
  currency: string;
  score: number;
  reasons: ReasonCode[];
  merchantCategory: string;
  issuerCountry: string | null;
  ipCountry: string;
};

export type ReviewErrorCode =
  | 'REVIEW_NOT_FOUND'
  | 'ANALYST_REQUIRED'
  | 'NOTE_REQUIRED'
  | 'NOTE_TOO_LONG'
  | 'ALREADY_DECIDED'
  | 'REVIEW_EXPIRED';

export class ReviewError extends Error {
  readonly code: ReviewErrorCode;

  constructor(code: ReviewErrorCode, message: string = code) {
    super(message);
    this.name = 'ReviewError';
    this.code = code;
  }
}

const REVIEW_TTL_MS = 72 * 60 * 60 * 1000;
const MAX_NOTE_LENGTH = 1000;

export interface ReviewQueue {
  hold(args: HoldArgs): ReviewItem;
  get(id: string): ReviewItem | undefined;
  /** Held items, oldest first. */
  listHeld(): ReviewItem[];
  approve(id: string, analyst: string, note: string, now?: number): ReviewItem;
  decline(id: string, analyst: string, note: string, now?: number): ReviewItem;
  /** Subscribe to newly held items. Returns an unsubscribe function. */
  onHeld(listener: (item: ReviewItem) => void): () => void;
  setNarrative(id: string, narrative: string): void;
  /** Mark a held item expired. Idempotent: returns false, changing nothing, if it is not held. */
  markExpired(id: string, now: number): boolean;
}

const MASKED_CARD = /^\d{6}\*+\d{4}$/;
const BIN_LAST4 = /^\d{6}:\d{4}$/;

export class InMemoryReviewQueue implements ReviewQueue {
  readonly #items = new Map<string, ReviewItem>();
  #seq = 0;

  readonly #audit: AuditLog;
  readonly #clock: () => number;
  readonly #payments: PaymentsService;
  readonly #listeners = new Set<(item: ReviewItem) => void>();

  constructor(audit: AuditLog, clock: () => number = Date.now, payments: PaymentsService) {
    this.#audit = audit;
    this.#clock = clock;
    this.#payments = payments;
  }

  onHeld(listener: (item: ReviewItem) => void): () => void {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  }

  setNarrative(id: string, narrative: string): void {
    const item = this.#items.get(id);
    if (!item) throw new ReviewError('REVIEW_NOT_FOUND', `no review item ${id}`);
    item.narrative = narrative;
  }

  markExpired(id: string, now: number): boolean {
    const item = this.#items.get(id);
    if (!item) throw new ReviewError('REVIEW_NOT_FOUND', `no review item ${id}`);
    if (item.status !== 'held') return false;
    item.status = 'expired';
    item.decidedAt = now;
    return true;
  }

  approve(id: string, analyst: string, note: string, now?: number): ReviewItem {
    return this.#decide('approve', id, analyst, note, now);
  }

  decline(id: string, analyst: string, note: string, now?: number): ReviewItem {
    return this.#decide('decline', id, analyst, note, now);
  }

  #decide(action: 'approve' | 'decline', id: string, analyst: string, note: string, now?: number): ReviewItem {
    const item = this.#items.get(id);
    if (!item) throw new ReviewError('REVIEW_NOT_FOUND', `no review item ${id}`);
    if (typeof analyst !== 'string' || analyst.trim() === '') {
      throw new ReviewError('ANALYST_REQUIRED', 'analyst identity is required');
    }
    if (typeof note !== 'string' || note.trim() === '') {
      throw new ReviewError('NOTE_REQUIRED', 'a decision note is required');
    }
    if (note.length > MAX_NOTE_LENGTH) {
      throw new ReviewError('NOTE_TOO_LONG', `note exceeds ${MAX_NOTE_LENGTH} characters`);
    }
    if (item.status !== 'held') throw new ReviewError('ALREADY_DECIDED', `${id} is already ${item.status}`);
    const at = now ?? this.#clock();
    if (at >= item.heldAt + REVIEW_TTL_MS) throw new ReviewError('REVIEW_EXPIRED', `${id} hold has expired`);

    if (action === 'approve') this.#payments.unblockCapture(item.paymentId);
    else this.#payments.void(item.paymentId);

    item.status = action === 'approve' ? 'approved' : 'declined';
    item.decidedBy = analyst;
    item.decidedAt = at;
    item.note = note;
    this.#audit.record({ action, subjectId: item.id, actor: analyst, reason: note, at });
    return item;
  }

  hold(args: HoldArgs): ReviewItem {
    if (!MASKED_CARD.test(args.maskedCard) && !BIN_LAST4.test(args.maskedCard)) {
      throw new RangeError('maskedCard must be BIN plus last four');
    }
    const heldAt = this.#clock();
    const item: ReviewItem = {
      id: `rev_${(++this.#seq).toString(36).padStart(6, '0')}`,
      paymentId: args.paymentId,
      maskedCard: args.maskedCard,
      merchantId: args.merchantId,
      amount: args.amount,
      score: args.score,
      analystReason: args.reasons.length > 0 ? analystReason(args.reasons[0]) : 'Scorer unavailable',
      narrative: null,
      heldAt,
      status: 'held',
      decidedBy: null,
      note: null,
      decidedAt: null,
      reasons: [...args.reasons],
      currency: args.currency,
      merchantCategory: args.merchantCategory,
      issuerCountry: args.issuerCountry,
      ipCountry: args.ipCountry,
    };
    this.#items.set(item.id, item);
    this.#audit.record({
      action: 'hold',
      subjectId: item.id,
      actor: 'system',
      reason: item.analystReason,
      at: heldAt,
    });
    for (const listener of [...this.#listeners]) {
      try {
        listener(item);
      } catch (error) {
        log.error(`onHeld listener failed for ${item.id}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    return item;
  }

  get(id: string): ReviewItem | undefined {
    return this.#items.get(id);
  }

  listHeld(): ReviewItem[] {
    return [...this.#items.values()]
      .filter(i => i.status === 'held')
      .sort((a, b) => a.heldAt - b.heldAt);
  }
}
