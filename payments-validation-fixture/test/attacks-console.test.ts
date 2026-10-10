import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { AttacksConsole } from '../src/review/attacks.ts';
import { ConsoleError } from '../src/review/console.ts';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { InMemoryAttackStore, type Attack } from '../src/risk/attacks.ts';
import { BlockList, InMemoryBlockStore } from '../src/risk/blocks.ts';
import { loadDetectorConfig } from '../src/risk/detector-config.ts';

const config = loadDetectorConfig(JSON.parse(readFileSync(new URL('../config/detector.json', import.meta.url), 'utf8')));
const NOW = Date.UTC(2026, 9, 3, 14, 0, 0);
const session = { analyst: 'ana', authenticated: true };

const attack = (id: string, flaggedAt: number, status: Attack['status'] = 'blocked'): Attack => ({
  id, bin: '411111', amount: 100, firstSeenAt: flaggedAt - 60_000, flaggedAt, cards: 12,
  merchants: [{ merchantId: 'm_01', attempts: 3, firstAt: flaggedAt - 60_000, lastAt: flaggedAt }],
  status, releasedBy: null, releaseReason: null,
});

const setup = () => {
  const attacks = new InMemoryAttackStore();
  const audit = new InMemoryAuditLog();
  const blocks = new BlockList(new InMemoryBlockStore(), attacks, audit, config, () => NOW);
  const console_ = new AttacksConsole(attacks, blocks, audit, () => NOW);
  return { attacks, audit, blocks, console_ };
};

const code = (c: string) => (e: unknown) => e instanceof ConsoleError && e.code === c;

test('listAttacks returns only blocked attacks, newest first', () => {
  const { attacks, console_ } = setup();
  attacks.insert(attack('atk_1', NOW - 2000));
  attacks.insert(attack('atk_2', NOW));
  attacks.insert(attack('atk_3', NOW + 1, 'released'));
  assert.deepEqual(console_.listAttacks().map(a => a.id), ['atk_2', 'atk_1']);
});

test('getAttack returns the timeline and throws for unknown ids', () => {
  const { attacks, console_ } = setup();
  attacks.insert(attack('atk_1', NOW));
  assert.equal(console_.getAttack('atk_1').merchants[0]?.merchantId, 'm_01');
  assert.throws(() => console_.getAttack('nope'), code('ATTACK_NOT_FOUND'));
});

test('release with a blank reason throws REASON_REQUIRED and writes no audit entry', () => {
  const { attacks, audit, console_ } = setup();
  attacks.insert(attack('atk_1', NOW));
  assert.throws(() => console_.release('atk_1', session, '   '), code('REASON_REQUIRED'));
  assert.throws(() => console_.release('atk_1', session, 'x'.repeat(1001)), code('REASON_TOO_LONG'));
  assert.throws(() => console_.release('nope', session, 'ok'), code('ATTACK_NOT_FOUND'));
  assert.equal(audit.forSubject('atk_1').length, 0);
});

test('release of a released or expired attack throws NOT_BLOCKED', () => {
  const { attacks, console_ } = setup();
  attacks.insert(attack('atk_1', NOW, 'released'));
  attacks.insert(attack('atk_2', NOW, 'expired'));
  assert.throws(() => console_.release('atk_1', session, 'ok'), code('NOT_BLOCKED'));
  assert.throws(() => console_.release('atk_2', session, 'ok'), code('NOT_BLOCKED'));
});

test('release with an unauthenticated session throws UNAUTHENTICATED and writes no audit entry', () => {
  const { attacks, audit, console_ } = setup();
  attacks.insert(attack('atk_1', NOW));
  assert.throws(() => console_.release('atk_1', { authenticated: false }, 'ok'), code('UNAUTHENTICATED'));
  assert.equal(audit.forSubject('atk_1').length, 0);
  assert.equal(attacks.get('atk_1')?.status, 'blocked');
});

test('successful release audits, removes the block and records the analyst', () => {
  const { attacks, audit, blocks, console_ } = setup();
  const a = attack('atk_1', NOW);
  attacks.insert(a);
  blocks.createFor(a);
  blocks.refresh(NOW);
  assert.ok(blocks.matches({ bin: '411111', amount: 100 }));

  const released = console_.release('atk_1', session, '  false positive  ');
  assert.equal(released.status, 'released');
  assert.equal(released.releasedBy, 'ana');
  assert.equal(released.releaseReason, 'false positive');
  assert.equal(attacks.get('atk_1')?.status, 'released');

  blocks.refresh(NOW);
  assert.equal(blocks.matches({ bin: '411111', amount: 100 }), undefined);
  const entries = audit.forSubject('atk_1');
  assert.equal(entries.length, 1);
  assert.equal(entries[0]?.action, 'release');
  assert.equal(entries[0]?.actor, 'ana');
  assert.equal(entries[0]?.reason, 'false positive');
});

test('listRecentlyClosed returns released and expired attacks up to the limit', () => {
  const { attacks, console_ } = setup();
  attacks.insert(attack('atk_1', NOW - 3000, 'released'));
  attacks.insert(attack('atk_2', NOW - 1000, 'expired'));
  attacks.insert(attack('atk_3', NOW, 'blocked'));
  assert.deepEqual(console_.listRecentlyClosed(10).map(a => a.id), ['atk_2', 'atk_1']);
  assert.deepEqual(console_.listRecentlyClosed(1).map(a => a.id), ['atk_2']);
});
