import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { InMemoryAttemptStore, cardKeyOf, type AttemptRecord } from '../src/risk/attempts.ts';
import { AttackDetector, InMemoryAttackStore } from '../src/risk/attacks.ts';
import { loadDetectorConfig, type DetectorMode } from '../src/risk/detector-config.ts';
import {
  InMemoryNotificationSink, MerchantNotifier, NoticeValidationError, buildNotices, validateNotice,
  type CardTestingNotice,
} from '../src/notify/merchant.ts';

const base = loadDetectorConfig(JSON.parse(readFileSync(new URL('../config/detector.json', import.meta.url), 'utf8')));
const NOW = Date.UTC(2026, 9, 3, 14, 0, 0);
const MERCHANTS = 10;

const rec = (card: number, merchant: number, at: number): AttemptRecord => ({
  cardKey: cardKeyOf('411111', String(1000 + card).slice(-4)), bin: '411111', amount: 100,
  merchantId: `m_${merchant}`, ipCountry: 'GB', at,
});

const setup = (mode: DetectorMode = 'block_and_notify') => {
  const config = { ...base, mode, minMerchants: Math.min(base.minMerchants, MERCHANTS) };
  let now = NOW;
  const attempts = new InMemoryAttemptStore();
  const cards = Math.max(config.minCards, MERCHANTS);
  attempts.insertMany(Array.from({ length: cards }, (_, i) => rec(i, i % MERCHANTS, NOW - 60_000 + i * 1000)));
  const attacks = new InMemoryAttackStore();
  const detector = new AttackDetector(attempts, attacks, config, () => now);
  const sink = new InMemoryNotificationSink();
  const notifier = new MerchantNotifier(sink, attacks, detector, config, () => now);
  const [attack] = detector.run(NOW);
  return { config, attempts, attacks, detector, sink, notifier, attack, setNow: (n: number) => { now = n; } };
};

test('onFlagged sends one notice per merchant with its own window and count', () => {
  const { sink, notifier, attack } = setup();
  assert.equal(attack.merchants.length, MERCHANTS);
  notifier.onFlagged(attack);
  assert.equal(sink.sent.length, MERCHANTS);
  for (const m of attack.merchants) {
    const s = sink.sent.find(x => x.merchantId === m.merchantId)!;
    assert.deepEqual(s.payload, { attackId: attack.id, windowStart: m.firstAt, windowEnd: m.lastAt, attempts: m.attempts });
  }
});

test('notice payload has exactly the four keys and no card data', () => {
  const { sink, notifier, attack } = setup();
  notifier.onFlagged(attack);
  for (const s of sink.sent) {
    assert.deepEqual(Object.keys(s.payload).sort(), ['attackId', 'attempts', 'windowEnd', 'windowStart']);
  }
  const text = JSON.stringify(sink.sent);
  assert.doesNotMatch(text, /411111|\*{2,}|last4|bin/i);
});

test('validateNotice rejects an extra bin field and a 6-digit run in a string field', () => {
  const ok: CardTestingNotice = { attackId: 'atk_000001', windowStart: 1, windowEnd: 2, attempts: 3 };
  validateNotice(ok);
  assert.throws(() => validateNotice({ ...ok, bin: '123' } as CardTestingNotice), NoticeValidationError);
  assert.throws(
    () => validateNotice({ ...ok, windowStart: '411111' } as unknown as CardTestingNotice),
    NoticeValidationError,
  );
  assert.throws(() => validateNotice({ ...ok, extra: 1 } as CardTestingNotice), NoticeValidationError);
});

test('buildNotices yields one notice per merchant', () => {
  const { attack } = setup();
  assert.equal(buildNotices(attack).length, MERCHANTS);
});

test('tick follows up only merchants with new attempts, and nothing for a released attack', () => {
  const { config, attempts, attacks, sink, notifier, attack, setNow } = setup();
  notifier.onFlagged(attack);
  sink.sent.length = 0;

  const later = NOW + config.notifyFollowUpMs;
  attempts.insertMany([rec(500, 3, NOW + 1000), rec(501, 3, NOW + 2000)]);
  setNow(later);
  notifier.tick(later - 1);
  assert.equal(sink.sent.length, 0);
  notifier.tick(later);
  assert.equal(sink.sent.length, 1);
  assert.equal(sink.sent[0].merchantId, 'm_3');
  const before = attack.merchants.find(m => m.merchantId === 'm_3')!.attempts;
  assert.equal(sink.sent[0].payload.attempts, before + 2);

  sink.sent.length = 0;
  notifier.tick(later + config.notifyFollowUpMs);
  assert.equal(sink.sent.length, 0);

  attempts.insertMany([rec(502, 4, later + 1000)]);
  attacks.update({ ...attacks.get(attack.id)!, status: 'released' });
  notifier.tick(later + 2 * config.notifyFollowUpMs);
  assert.equal(sink.sent.length, 0);
});

for (const mode of ['shadow', 'block'] as const) {
  test(`mode ${mode} sends no notices`, () => {
    const { config, sink, notifier, attack, setNow } = setup(mode);
    notifier.onFlagged(attack);
    setNow(NOW + config.notifyFollowUpMs);
    notifier.tick(NOW + config.notifyFollowUpMs);
    assert.equal(sink.sent.length, 0);
  });
}
