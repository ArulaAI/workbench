import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { InMemoryAttemptStore, cardKeyOf, type AttemptRecord } from '../src/risk/attempts.ts';
import { AttackDetector, InMemoryAttackStore } from '../src/risk/attacks.ts';
import { loadDetectorConfig } from '../src/risk/detector-config.ts';

const config = loadDetectorConfig(JSON.parse(readFileSync(new URL('../config/detector.json', import.meta.url), 'utf8')));
const NOW = Date.UTC(2026, 9, 3, 14, 0, 0);

const last4 = (i: number) => String(1000 + i).slice(-4);
const attempt = (card: number, merchant: number, at: number, bin = '411111', amount = 100): AttemptRecord => ({
  cardKey: cardKeyOf(bin, last4(card)), bin, amount, merchantId: `m_${merchant}`, ipCountry: 'GB', at,
});

/** `cards` distinct cards rotated across `merchants` merchants, the first at `start`, one second apart. */
const burst = (cards: number, merchants: number, start: number, bin = '411111'): AttemptRecord[] =>
  Array.from({ length: cards }, (_, i) => attempt(i, i % merchants, start + i * 1000, bin));

const make = (records: AttemptRecord[] = []) => {
  const attempts = new InMemoryAttemptStore();
  attempts.insertMany(records);
  const attacks = new InMemoryAttackStore();
  return { attempts, attacks, detector: new AttackDetector(attempts, attacks, config, () => NOW) };
};

const lastAt = (cards: number, start: number) => start + (cards - 1) * 1000;
const fits = (cards: number) => NOW - (cards - 1) * 1000;

test('minCards - 1 distinct cards at minMerchants merchants flags nothing', () => {
  const n = config.minCards - 1;
  const { detector } = make(burst(n, config.minMerchants, fits(n)));
  assert.deepEqual(detector.run(NOW), []);
});

test('minCards cards at minMerchants - 1 merchants flags nothing', () => {
  const n = config.minCards;
  const { detector } = make(burst(n, config.minMerchants - 1, fits(n)));
  assert.deepEqual(detector.run(NOW), []);
});

test('exactly minCards at exactly minMerchants, first attempt at the window edge, flags one attack', () => {
  const start = NOW - config.windowMs;
  const { detector, attacks } = make(burst(config.minCards, config.minMerchants, start));
  const flagged = detector.run(NOW);
  assert.equal(flagged.length, 1);
  const [a] = flagged;
  assert.match(a.id, /^atk_\d{6}$/);
  assert.equal(a.bin, '411111');
  assert.equal(a.amount, 100);
  assert.equal(a.firstSeenAt, start);
  assert.equal(a.flaggedAt, NOW);
  assert.equal(a.cards, config.minCards);
  assert.equal(a.status, 'blocked');
  assert.equal(a.releasedBy, null);
  assert.equal(a.releaseReason, null);
  assert.deepEqual(attacks.get(a.id), a);
});

test('an attempt just outside the window does not count', () => {
  const start = NOW - config.windowMs - 1;
  const { detector } = make(burst(config.minCards, config.minMerchants, start));
  assert.deepEqual(detector.run(NOW), []);
});

test('one card retried 20 times across 10 merchants flags nothing', () => {
  const records = Array.from({ length: 20 }, (_, i) => attempt(0, i % 10, NOW - i * 1000));
  const { detector } = make(records);
  assert.deepEqual(detector.run(NOW), []);
});

test('two simultaneous bursts on different BINs flag two attacks', () => {
  const n = config.minCards;
  const { detector } = make([...burst(n, config.minMerchants, fits(n), '411111'), ...burst(n, config.minMerchants, fits(n), '555555')]);
  const flagged = detector.run(NOW);
  assert.equal(flagged.length, 2);
  assert.deepEqual(flagged.map(a => a.bin).sort(), ['411111', '555555']);
  assert.notEqual(flagged[0].id, flagged[1].id);
});

test('different amounts on one BIN are separate groups', () => {
  const n = config.minCards;
  const half = burst(n, config.minMerchants, fits(n)).map((r, i) => ({ ...r, amount: i % 2 ? 100 : 200 }));
  const { detector } = make(half);
  assert.deepEqual(detector.run(NOW), []);
});

test('a second run with the same traffic does not duplicate a blocked attack', () => {
  const n = config.minCards;
  const { detector } = make(burst(n, config.minMerchants, fits(n)));
  assert.equal(detector.run(NOW).length, 1);
  assert.deepEqual(detector.run(NOW + 1000), []);
  assert.equal(detector.activeAttacks().length, 1);
});

test('after release, renewed traffic flags a new attack and the old record is kept', () => {
  const n = config.minCards;
  const { detector, attacks, attempts } = make(burst(n, config.minMerchants, fits(n)));
  const [first] = detector.run(NOW);
  attacks.update({ ...first, status: 'released', releasedBy: 'analyst_1', releaseReason: 'false positive' });

  const later = NOW + 60_000;
  attempts.insertMany(burst(n, config.minMerchants, later - (n - 1) * 1000));
  const [second] = detector.run(later);
  assert.ok(second);
  assert.notEqual(second.id, first.id);
  assert.equal(attacks.get(first.id)?.status, 'released');
  assert.equal(attacks.get(first.id)?.releasedBy, 'analyst_1');
  assert.equal(detector.getAttack(second.id)?.status, 'blocked');
});

test('an expired attack does not stop a new one being flagged', () => {
  const n = config.minCards;
  const { detector, attacks } = make(burst(n, config.minMerchants, fits(n)));
  const [first] = detector.run(NOW);
  attacks.update({ ...first, status: 'expired' });
  const [second] = detector.run(NOW + 1000);
  assert.ok(second);
  assert.notEqual(second.id, first.id);
});

test('Attack.merchants lists per-merchant attempts, firstAt and lastAt', () => {
  const n = config.minCards;
  const start = fits(n);
  const { detector } = make(burst(n, config.minMerchants, start));
  const [a] = detector.run(NOW);
  assert.equal(a.merchants.length, config.minMerchants);
  const m0 = a.merchants.find(m => m.merchantId === 'm_0');
  // Cards 0, 5 at m_0 with the default 10 cards over 5 merchants.
  const indices = Array.from({ length: n }, (_, i) => i).filter(i => i % config.minMerchants === 0);
  assert.deepEqual(m0, {
    merchantId: 'm_0', attempts: indices.length,
    firstAt: start + indices[0] * 1000, lastAt: start + indices[indices.length - 1] * 1000,
  });
  assert.equal(a.merchants.reduce((s, m) => s + m.attempts, 0), n);
  assert.equal(Math.max(...a.merchants.map(m => m.lastAt)), lastAt(n, start));
});

test('refreshTimeline adds attempts made after the flag', () => {
  const n = config.minCards;
  const { detector, attempts } = make(burst(n, config.minMerchants, fits(n)));
  const [a] = detector.run(NOW);
  attempts.insertMany([attempt(50, 0, NOW + 5000), attempt(51, 99, NOW + 6000), attempt(52, 0, NOW + 7000, '999999')]);
  const updated = detector.refreshTimeline(a.id, NOW + 10_000);
  assert.ok(updated);
  const before = a.merchants.find(m => m.merchantId === 'm_0')!;
  const m0 = updated.merchants.find(m => m.merchantId === 'm_0')!;
  assert.equal(m0.attempts, before.attempts + 1);
  assert.equal(m0.lastAt, NOW + 5000);
  assert.deepEqual(updated.merchants.find(m => m.merchantId === 'm_99'), { merchantId: 'm_99', attempts: 1, firstAt: NOW + 6000, lastAt: NOW + 6000 });
  assert.deepEqual(detector.getAttack(a.id)?.merchants, updated.merchants);
  assert.equal(detector.refreshTimeline('atk_missing', NOW), undefined);
});

test('activeAttacks returns blocked attacks newest first', () => {
  const n = config.minCards;
  const { detector, attempts, attacks } = make(burst(n, config.minMerchants, fits(n), '411111'));
  const [older] = detector.run(NOW);
  attempts.insertMany(burst(n, config.minMerchants, fits(n) + 5000, '555555'));
  const [newer] = detector.run(NOW + 5000);
  assert.deepEqual(detector.activeAttacks().map(a => a.id), [newer.id, older.id]);
  attacks.update({ ...newer, status: 'released' });
  assert.deepEqual(detector.activeAttacks().map(a => a.id), [older.id]);
});
