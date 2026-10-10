import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { BlockList, InMemoryBlockStore, type BlockStore } from '../src/risk/blocks.ts';
import { InMemoryAttackStore, type Attack } from '../src/risk/attacks.ts';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { loadDetectorConfig } from '../src/risk/detector-config.ts';
import { resetSinks, sinks } from '../src/obs/index.ts';

const config = loadDetectorConfig(JSON.parse(readFileSync(new URL('../config/detector.json', import.meta.url), 'utf8')));
const NOW = Date.UTC(2026, 9, 3, 14, 0, 0);

const attack = (id = 'atk_000001', status: Attack['status'] = 'blocked'): Attack => ({
  id, bin: '411111', amount: 100, firstSeenAt: NOW - 60_000, flaggedAt: NOW, cards: 12,
  merchants: [], status, releasedBy: null, releaseReason: null,
});

const setup = (store: BlockStore = new InMemoryBlockStore()) => {
  let now = NOW;
  const attacks = new InMemoryAttackStore();
  const audit = new InMemoryAuditLog();
  const replica = () => new BlockList(store, attacks, audit, config, () => now);
  return { store, attacks, audit, replica, setNow: (n: number) => { now = n; } };
};

test('matches at the ceiling and not above it', () => {
  const { replica } = setup();
  const list = replica();
  list.createFor(attack());
  list.refresh(NOW);
  assert.equal(list.matches({ bin: '411111', amount: config.smallAmountCeiling })?.attackId, 'atk_000001');
  assert.equal(list.matches({ bin: '411111', amount: config.smallAmountCeiling + 1 }), undefined);
});

test('matches returns undefined for a different BIN', () => {
  const { replica } = setup();
  const list = replica();
  list.createFor(attack());
  list.refresh(NOW);
  assert.equal(list.matches({ bin: '555555', amount: 100 }), undefined);
});

test('a block created on replica A is matched on replica B only after B refreshes', () => {
  const { replica } = setup();
  const a = replica();
  const b = replica();
  a.createFor(attack());
  assert.equal(b.matches({ bin: '411111', amount: 100 }), undefined);
  b.refresh(NOW);
  assert.ok(b.matches({ bin: '411111', amount: 100 }));
});

test('createFor sets expiry from flaggedAt and the ceiling from config', () => {
  const { replica } = setup();
  const block = replica().createFor(attack());
  assert.equal(block.expiresAt, NOW + config.blockTtlMs);
  assert.equal(block.amountCeiling, config.smallAmountCeiling);
  assert.equal(block.scope, 'all_merchants');
});

test('expire after the TTL marks the attack expired, removes the block and audits once', () => {
  const { replica, attacks, audit, setNow } = setup();
  const list = replica();
  const a = attack();
  attacks.insert(a);
  list.createFor(a);
  list.refresh(NOW);
  assert.ok(list.matches({ bin: '411111', amount: 100 }));

  const later = NOW + config.blockTtlMs;
  setNow(later);
  const expired = list.expire(later);
  assert.equal(expired.length, 1);
  assert.equal(attacks.get(a.id)?.status, 'expired');
  const entries = audit.forSubject(a.id);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].action, 'expire');
  assert.equal(entries[0].actor, 'system');
  assert.equal(entries[0].reason, 'block ttl elapsed');
  assert.equal(list.matches({ bin: '411111', amount: 100 }), undefined);

  assert.equal(list.expire(later + 1000).length, 0);
  assert.equal(audit.forSubject(a.id).length, 1);
});

test('expire does not touch released attacks', () => {
  const { replica, attacks, audit } = setup();
  const list = replica();
  const a = attack('atk_000002', 'released');
  attacks.insert(a);
  assert.deepEqual(list.expire(NOW + config.blockTtlMs * 2), []);
  assert.equal(attacks.get(a.id)?.status, 'released');
  assert.equal(audit.forSubject(a.id).length, 0);
});

test('expire leaves attacks whose TTL has not elapsed', () => {
  const { replica, attacks } = setup();
  const a = attack();
  attacks.insert(a);
  assert.deepEqual(replica().expire(NOW + config.blockTtlMs - 1), []);
  assert.equal(attacks.get(a.id)?.status, 'blocked');
});

test('matches makes no BlockStore call', () => {
  const inner = new InMemoryBlockStore();
  const calls: string[] = [];
  const spy: BlockStore = {
    insert: b => { calls.push('insert'); inner.insert(b); },
    remove: id => { calls.push('remove'); inner.remove(id); },
    listActive: n => { calls.push('listActive'); return inner.listActive(n); },
  };
  const { replica } = setup(spy);
  const list = replica();
  list.createFor(attack());
  list.refresh(NOW);
  calls.length = 0;
  list.matches({ bin: '411111', amount: 100 });
  list.matches({ bin: '555555', amount: 100 });
  assert.deepEqual(calls, []);
});

test('a refresh failure keeps the last loaded set and logs blocks.refresh_failed', () => {
  const inner = new InMemoryBlockStore();
  let failing = false;
  const flaky: BlockStore = {
    insert: b => inner.insert(b),
    remove: id => inner.remove(id),
    listActive: n => { if (failing) throw new Error('store down'); return inner.listActive(n); },
  };
  const { replica } = setup(flaky);
  const list = replica();
  list.createFor(attack());
  list.refresh(NOW);
  resetSinks();
  failing = true;
  list.refresh(NOW);
  assert.ok(list.matches({ bin: '411111', amount: 100 }));
  assert.ok(sinks.logs.some(l => l.message.startsWith('blocks.refresh_failed')));
});

test('removeFor drops the block from the store and this replica', () => {
  const { replica } = setup();
  const list = replica();
  const other = replica();
  list.createFor(attack());
  list.refresh(NOW);
  other.refresh(NOW);
  list.removeFor('atk_000001');
  assert.equal(list.matches({ bin: '411111', amount: 100 }), undefined);
  other.refresh(NOW);
  assert.equal(other.matches({ bin: '411111', amount: 100 }), undefined);
});
