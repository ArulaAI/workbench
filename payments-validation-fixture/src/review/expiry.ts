/*
 * Held payment expiry. A held payment with no analyst decision after 72 hours is voided.
 * HOLD_TTL_MS must stay equal to the REVIEW_TTL_MS used for REVIEW_EXPIRED in queue.ts.
 */

import type { AuditLog } from './audit.ts';
import type { ReviewItem, ReviewQueue } from './queue.ts';
import type { PaymentsService } from '../payments/service.ts';
import { log } from '../obs/index.ts';

export const HOLD_TTL_MS = 72 * 60 * 60 * 1000;

/** Port to the merchant notification service. The payload carries no card data. */
export type MerchantWebhook = {
  holdExpired(args: { merchantId: string; paymentId: string; reviewId: string; at: number }): void;
};

export type ExpiryDeps = {
  queue: ReviewQueue;
  payments: PaymentsService;
  audit: AuditLog;
  webhook: MerchantWebhook;
  now?: () => number;
};

const message = (error: unknown): string => (error instanceof Error ? error.message : String(error));

export function expireHeldReviews(
  queue: ReviewQueue,
  payments: PaymentsService,
  audit: AuditLog,
  webhook: MerchantWebhook,
  now: number,
): ReviewItem[] {
  const expired: ReviewItem[] = [];
  for (const item of queue.listHeld()) {
    if (now - item.heldAt < HOLD_TTL_MS) continue;
    try {
      payments.void(item.paymentId);
      // Another replica may have expired it first; markExpired reports whether this call did.
      if (!queue.markExpired(item.id, now)) continue;
      audit.record({ action: 'expire', subjectId: item.id, actor: 'system', reason: 'hold ttl elapsed', at: now });
      expired.push(item);
    } catch (error) {
      log.error(`expiry failed for ${item.id}: ${message(error)}`);
      continue;
    }
    try {
      webhook.holdExpired({ merchantId: item.merchantId, paymentId: item.paymentId, reviewId: item.id, at: now });
    } catch (error) {
      log.error(`hold-expired webhook failed for ${item.id}: ${message(error)}`);
    }
  }
  return expired;
}

export function startExpirySweeper(deps: ExpiryDeps, intervalMs = 60_000): () => void {
  const clock = deps.now ?? Date.now;
  const timer = setInterval(() => {
    try {
      expireHeldReviews(deps.queue, deps.payments, deps.audit, deps.webhook, clock());
    } catch (error) {
      log.error(`expiry sweep failed: ${message(error)}`);
    }
  }, intervalMs);
  timer.unref?.();
  return () => clearInterval(timer);
}
