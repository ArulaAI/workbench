import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CardTestingRuntime, InMemoryDetectorLease } from '../src/risk/card-testing-runtime.ts';
import { AttemptRecorder, InMemoryAttemptStore, cardKeyOf, type AttemptStore } from '../src/risk/attempts.ts';
import { AttackDetector, InMemoryAttackStore } from '../src/risk/attacks.ts';
import { BlockList, InMemoryBlockStore } from '../src/risk/blocks.ts';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { InMemoryNotificationSink, MerchantNotifier } from '../src/notify/merchant.ts';
import { loadDetectorConfig, type DetectorMode } from '../src/risk/detector-config.ts';

const base = JSON.parse(readFileSync(new URL('../config/detector.json', import.meta.url), 'utf8'));
const NOW = Date.UTC(2026, 9, 3, 14, 0, 0);

const setup = (mode: DetectorMode, attemptStore: AttemptStore = new InMemoryAttemptStore()) => {
  const config = loadDetectorConfig({ ...base, mode });
  let now = NOW;
  const clock = () => now;
  const attacks = new InMemoryAttackStore();
  const blockStore = new InMemoryBlockStore();
  const audit = new InMemoryAuditLog();
  const sink = new InMemoryNotificationSink();
  const lease = new InMemoryDetectorLease(config.refreshIntervalMs);
  const logs: string[] = [];
  const logger = { info: (m: string) => logs.push(`info ${m}`), alert: (m: string) => logs.push(`alert ${m}`) };
  const replica = (id: string) => {
    const recorder = new AttemptRecorder(attemptStore, config, clock);
    const detector = new AttackDetector(attemptStore, attacks, config, clock);
    const blocks = new BlockList(blockStore, attacks, audit, config, clock);
    const notifier = new MerchantNotifier(sink, attacks, detector, config, clock);
    const runtime = new CardTestingRuntime({ recorder, detector, blocks, notifier, lease, config, clock, logger, replicaId: id });
    return { recorder, blocks, runtime };
  };
  const traffic = (r: { recorder: AttemptRecorder }, n = 20) => {
    for (let i = 0; i < n; i += 1) {
      const last4 = String(1000 + i);
      r.recorder.record({
        cardKey: cardKeyOf('411111', last4), bin: '411111', amount: 100,
        merchantId: `m_${i % 10}`, ipCountry: 'GB', at: NOW - 1000 + i,
      });
    }
  };
  return { config, attacks, sink, logs, replica, traffic, setNow: (n: number) => { now = n; } };
};

test('only one of two runtimes sharing a lease runs the detector', () => {
  const s = setup('block');
  const a = s.replica('a');
  const b = s.replica('b');
  let runs = 0;
  for (const r of [a, b]) {
    const detector = (r.runtime as any).detector;
    const orig = detector.run.bind(detector);
    detector.run = (n: number) => { runs += 1; return orig(n); };
  }
  a.runtime.tick(NOW);
  b.runtime.tick(NOW);
  assert.equal(runs, 1);
});

test('crossing the threshold flags, blocks and notifies in one tick', () => {
  const s = setup('block_and_notify');
  const a = s.replica('a');
  s.traffic(a);
  a.runtime.tick(NOW);
  assert.equal(s.attacks.listByStatus('blocked').length, 1);
  assert.ok(a.blocks.matches({ bin: '411111', amount: 100 }));
  assert.ok(s.sink.sent.length > 0);
  assert.ok(s.logs.some(l => l.includes('card_testing.attack_flagged')));
});

test('shadow mode logs the attack but creates no block and sends no notice', () => {
  const s = setup('shadow');
  const a = s.replica('a');
  s.traffic(a);
  a.runtime.tick(NOW);
  assert.ok(s.logs.some(l => l.includes('card_testing.attack_flagged')));
  assert.equal(a.blocks.matches({ bin: '411111', amount: 100 }), undefined);
  assert.equal(s.sink.sent.length, 0);
});

test('an attempt store failure is logged as detection_paused and tick does not throw', () => {
  const broken: AttemptStore = {
    insertMany: () => { throw new Error('db down'); },
    since: () => { throw new Error('db down'); },
    deleteOlderThan: () => { throw new Error('db down'); },
  };
  const s = setup('block', broken);
  const a = s.replica('a');
  s.traffic(a, 1);
  assert.doesNotThrow(() => a.runtime.tick(NOW));
  assert.ok(s.logs.some(l => l.startsWith('alert card_testing.detection_paused')));
});

test('expired blocks are expired by the leader and vanish from both replicas after refresh', () => {
  const s = setup('block');
  const a = s.replica('a');
  const b = s.replica('b');
  s.traffic(a);
  a.runtime.tick(NOW);
  b.runtime.tick(NOW);
  assert.ok(a.blocks.matches({ bin: '411111', amount: 100 }));
  assert.ok(b.blocks.matches({ bin: '411111', amount: 100 }));

  const later = NOW + s.config.blockTtlMs + 1;
  s.setNow(later);
  a.runtime.tick(later);
  b.runtime.tick(later);
  assert.equal(s.attacks.listByStatus('expired').length, 1);
  assert.equal(a.blocks.matches({ bin: '411111', amount: 100 }), undefined);
  assert.equal(b.blocks.matches({ bin: '411111', amount: 100 }), undefined);
});
