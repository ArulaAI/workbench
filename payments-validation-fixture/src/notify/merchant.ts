/*
 * Merchant notifications for F2.2 card-testing attacks.
 *
 * A notice carries only the attack id, the merchant's own window and an attempt count.
 * validateNotice keeps BIN, last four and masked card numbers out of the payload.
 */

import type { Attack, AttackDetector, AttackStore } from '../risk/attacks.ts';
import type { Clock, DetectorConfig } from '../risk/detector-config.ts';

export type CardTestingNotice = {
  attackId: string;
  windowStart: number;
  windowEnd: number;
  attempts: number;
};

export type MerchantMessageType = 'card_testing_alert';

export interface MerchantNotificationService {
  send(merchantId: string, messageType: MerchantMessageType, payload: CardTestingNotice): void;
}

export type SentNotification = {
  merchantId: string;
  messageType: MerchantMessageType;
  payload: CardTestingNotice;
};

export class InMemoryNotificationSink implements MerchantNotificationService {
  readonly sent: SentNotification[] = [];

  send(merchantId: string, messageType: MerchantMessageType, payload: CardTestingNotice): void {
    this.sent.push({ merchantId, messageType, payload: { ...payload } });
  }
}

export class NoticeValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NoticeValidationError';
  }
}

const ALLOWED_KEYS = ['attackId', 'windowStart', 'windowEnd', 'attempts'];

export function validateNotice(notice: CardTestingNotice): void {
  const record = notice as unknown as Record<string, unknown>;
  for (const key of Object.keys(record)) {
    if (!ALLOWED_KEYS.includes(key)) throw new NoticeValidationError(`notice has unexpected field '${key}'`);
  }
  for (const [key, value] of Object.entries(record)) {
    if (key === 'attackId') continue;
    if (typeof value === 'string' && /\d{6,}/.test(value)) {
      throw new NoticeValidationError(`notice field '${key}' contains a digit run of 6 or more`);
    }
  }
}

export function buildNotices(attack: Attack): { merchantId: string; notice: CardTestingNotice }[] {
  return attack.merchants.map(m => ({
    merchantId: m.merchantId,
    notice: { attackId: attack.id, windowStart: m.firstAt, windowEnd: m.lastAt, attempts: m.attempts },
  }));
}

export class MerchantNotifier {
  private readonly service: MerchantNotificationService;
  private readonly attacks: AttackStore;
  private readonly detector: AttackDetector;
  private readonly config: DetectorConfig;
  private readonly clock: Clock;
  /** Last attempt count sent, keyed by attackId then merchantId. */
  private readonly lastCounts = new Map<string, Map<string, number>>();
  private readonly lastNoticeAt = new Map<string, number>();

  constructor(
    service: MerchantNotificationService,
    attacks: AttackStore,
    detector: AttackDetector,
    config: DetectorConfig,
    clock: Clock,
  ) {
    this.service = service;
    this.attacks = attacks;
    this.detector = detector;
    this.config = config;
    this.clock = clock;
  }

  onFlagged(attack: Attack): void {
    if (this.config.mode !== 'block_and_notify') return;
    const counts = new Map<string, number>();
    this.lastCounts.set(attack.id, counts);
    this.lastNoticeAt.set(attack.id, this.clock());
    for (const { merchantId, notice } of buildNotices(attack)) {
      this.deliver(merchantId, notice);
      counts.set(merchantId, notice.attempts);
    }
  }

  tick(now: number = this.clock()): void {
    if (this.config.mode !== 'block_and_notify') return;
    const blocked = new Set(this.attacks.listByStatus('blocked').map(a => a.id));
    for (const id of [...this.lastCounts.keys()]) {
      if (!blocked.has(id)) {
        this.lastCounts.delete(id);
        this.lastNoticeAt.delete(id);
      }
    }

    for (const id of blocked) {
      const counts = this.lastCounts.get(id);
      const last = this.lastNoticeAt.get(id);
      if (!counts || last === undefined || now - last < this.config.notifyFollowUpMs) continue;
      const refreshed = this.detector.refreshTimeline(id, now);
      this.lastNoticeAt.set(id, now);
      if (!refreshed || refreshed.status !== 'blocked') continue;
      for (const { merchantId, notice } of buildNotices(refreshed)) {
        if (notice.attempts <= (counts.get(merchantId) ?? 0)) continue;
        this.deliver(merchantId, notice);
        counts.set(merchantId, notice.attempts);
      }
    }
  }

  private deliver(merchantId: string, notice: CardTestingNotice): void {
    validateNotice(notice);
    this.service.send(merchantId, 'card_testing_alert', notice);
  }
}
