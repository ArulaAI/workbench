/*
 * Operations console backend contract. The console repository's server mounts this
 * handler class; this repository has no HTTP framework. Analyst identity always comes
 * from the session, never from a request body.
 */

import { analystReason } from '../risk/reasons.ts';
import { ReviewError, type ReviewErrorCode, type ReviewItem, type ReviewQueue, type ReviewStatus } from './queue.ts';

export type ConsoleSession = { analyst?: string; authenticated: boolean };

export type ConsoleErrorCode =
  | 'UNAUTHENTICATED'
  | ReviewErrorCode
  | 'ATTACK_NOT_FOUND'
  | 'REASON_REQUIRED'
  | 'REASON_TOO_LONG'
  | 'NOT_BLOCKED';

export class ConsoleError extends Error {
  readonly code: ConsoleErrorCode;

  constructor(code: ConsoleErrorCode, message: string = code) {
    super(message);
    this.name = 'ConsoleError';
    this.code = code;
  }
}

/** The authenticated analyst's identity, or ConsoleError('UNAUTHENTICATED'). */
export const requireAnalyst = (session: ConsoleSession): string => {
  const analyst = session?.analyst;
  if (!session?.authenticated || typeof analyst !== 'string' || analyst.trim() === '') {
    throw new ConsoleError('UNAUTHENTICATED', 'an authenticated analyst session is required');
  }
  return analyst;
};

export type QueueRowDto = {
  reviewId: string;
  maskedCard: string;
  merchantName: string;
  amount: { minor: number; currency: string };
  score: number;
  reason: string;
  heldSince: number;
};

export type PaymentDetailDto = QueueRowDto & {
  reasons: string[];
  narrative?: string;
  status: ReviewStatus;
};

export type ReviewConsoleDeps = {
  queue: ReviewQueue;
  merchantName: (merchantId: string) => string;
};

/** Normalise to the 411111******1111 form, from BIN and last four only. */
const mask = (stored: string): string => {
  const bin = stored.slice(0, 6);
  const last4 = stored.slice(-4);
  return `${bin}${'*'.repeat(6)}${last4}`;
};

export class ReviewConsole {
  readonly #queue: ReviewQueue;
  readonly #merchantName: (merchantId: string) => string;

  constructor(deps: ReviewConsoleDeps) {
    this.#queue = deps.queue;
    this.#merchantName = deps.merchantName;
  }

  list(session: ConsoleSession): QueueRowDto[] {
    requireAnalyst(session);
    return this.#queue.listHeld().map(item => this.#row(item));
  }

  get(session: ConsoleSession, id: string): PaymentDetailDto {
    requireAnalyst(session);
    const item = this.#queue.get(id);
    if (!item) throw new ConsoleError('REVIEW_NOT_FOUND', `no review item ${id}`);
    const detail: PaymentDetailDto = {
      ...this.#row(item),
      reasons: item.reasons.map(analystReason),
      status: item.status,
    };
    if (item.narrative) detail.narrative = item.narrative;
    return detail;
  }

  approve(session: ConsoleSession, id: string, body: { note: string }): PaymentDetailDto {
    return this.#decide('approve', session, id, body);
  }

  decline(session: ConsoleSession, id: string, body: { note: string }): PaymentDetailDto {
    return this.#decide('decline', session, id, body);
  }

  #decide(action: 'approve' | 'decline', session: ConsoleSession, id: string, body: { note: string }): PaymentDetailDto {
    const analyst = requireAnalyst(session);
    try {
      this.#queue[action](id, analyst, body?.note);
    } catch (error) {
      if (error instanceof ReviewError) throw new ConsoleError(error.code, error.message);
      throw error;
    }
    return this.get(session, id);
  }

  #row(item: ReviewItem): QueueRowDto {
    return {
      reviewId: item.id,
      maskedCard: mask(item.maskedCard),
      merchantName: this.#merchantName(item.merchantId),
      amount: { minor: item.amount, currency: item.currency },
      score: item.score,
      reason: item.reasons.length > 0 ? analystReason(item.reasons[0]) : item.analystReason,
      heldSince: item.heldAt,
    };
  }
}
