import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { AttemptRecorder, InMemoryAttemptStore, cardKeyOf, type AttemptRecord, type AttemptStore } from '../src/risk/attempts.ts';
import { loadDetectorConfig } from '../src/risk/detector-config.ts';
import { sinks, resetSinks } from '../src/obs/index.ts';

const config = loadDetectorConfig(JSON.parse(readFileSync(new URL('../config/detector.json', import.meta.url), 'utf8')));
const NOW = Date.UTC(2026, 9, 3, 14, 0, 0);
const HOUR = 60 * 60 * 1000;
const attempt = (over: Partial<AttemptRecord> = {}): AttemptRecord => ({
  cardKey: cardKeyOf('411111', '1234'), bin: '411111', amount: 100, merchantId: 'm_1', ipCountry: 'GB', at: NOW, ...over,
});
const make = (store: AttemptStore = new InMemoryAttemptStore()) => ({ store, rec: new AttemptRecorder(store, config, () => NOW) });

test('record then flush makes the attempt visible through since()', () => {
  const { store, rec } = make();
  rec.record(attempt());
  assert.equal(store.since(0).length, 0);
  rec.flush();
  assert.deepEqual(store.since(0), [attempt()]);
});

test('a 16-digit PAN as cardKey stores nothing and does not throw', () => {
  resetSinks();
  const { store, rec } = make();
  rec.record(attempt({ cardKey: '4111111111111111' }));
  rec.flush();
  assert.equal(store.since(0).length, 0);
  assert.ok(sinks.logs.some(l => l.message.includes('attempts.rejected_pan')));
  assert.ok(!sinks.logs.some(l => l.message.includes('4111111111111111')));
});

test('a cardKey that does not match bin:last4 is not stored', () => {
  const { store, rec } = make();
  rec.record(attempt({ cardKey: '222222:1234' }));
  rec.flush();
  assert.equal(store.since(0).length, 0);
});

test('amount above smallAmountCeiling stores nothing', () => {
  const { store, rec } = make();
  rec.record(attempt({ amount: config.smallAmountCeiling + 1 }));
  rec.flush();
  assert.equal(store.since(0).length, 0);
});

test('flush failure keeps the buffer, logs, and the next flush writes it', () => {
  resetSinks();
  const inner = new InMemoryAttemptStore();
  let fail = true;
  const store: AttemptStore = {
    insertMany: r => { if (fail) throw new Error('db down'); inner.insertMany(r); },
    since: m => inner.since(m),
    deleteOlderThan: m => inner.deleteOlderThan(m),
  };
  const { rec } = make(store);
  rec.record(attempt());
  assert.doesNotThrow(() => rec.flush());
  assert.equal(rec.healthy, false);
  assert.ok(sinks.logs.some(l => l.message.includes('attempts.flush_failed')));
  assert.equal(inner.since(0).length, 0);
  fail = false;
  rec.flush();
  assert.equal(rec.healthy, true);
  assert.equal(inner.since(0).length, 1);
});

test('purgeExpired removes records older than 1 hour and keeps newer ones', () => {
  const { store, rec } = make();
  rec.record(attempt({ at: NOW - HOUR - 1 }));
  rec.record(attempt({ at: NOW - HOUR + 1000 }));
  rec.flush();
  assert.equal(rec.purgeExpired(NOW), 1);
  assert.equal(store.since(0).length, 1);
});

test('two recorders sharing one store both write to it', () => {
  const store = new InMemoryAttemptStore();
  const a = make(store).rec;
  const b = make(store).rec;
  a.record(attempt({ merchantId: 'm_a' }));
  b.record(attempt({ merchantId: 'm_b' }));
  a.flush();
  b.flush();
  assert.deepEqual(store.since(0).map(r => r.merchantId).sort(), ['m_a', 'm_b']);
});
