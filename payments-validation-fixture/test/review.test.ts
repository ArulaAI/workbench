import test from 'node:test';
import assert from 'node:assert/strict';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { InMemoryReviewQueue, type HoldArgs } from '../src/review/queue.ts';

const args = (over: Partial<HoldArgs> = {}): HoldArgs => ({
  paymentId: 'pay_000001', maskedCard: '411111******1111', merchantId: 'm_1',
  amount: 80_000, currency: 'GBP', score: 750, reasons: ['amount_unusual'],
  merchantCategory: 'electronics', issuerCountry: 'GB', ipCountry: 'JP', ...over,
});

test('hold returns a held item and writes one system audit entry', () => {
  const audit = new InMemoryAuditLog();
  const q = new InMemoryReviewQueue(audit, () => 1000);
  const item = q.hold(args());
  assert.match(item.id, /^rev_/);
  assert.equal(item.status, 'held');
  assert.equal(item.narrative, null);
  assert.equal(item.decidedBy, null);
  assert.equal(item.heldAt, 1000);
  const entries = audit.forSubject(item.id);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].action, 'hold');
  assert.equal(entries[0].actor, 'system');
  assert.match(entries[0].id, /^aud_/);
});

test('hold with empty reasons says scorer unavailable', () => {
  const q = new InMemoryReviewQueue(new InMemoryAuditLog(), () => 1);
  assert.equal(q.hold(args({ reasons: [], score: 0 })).analystReason, 'Scorer unavailable');
});

test('hold rejects a 16-digit card and accepts bin:last4', () => {
  const q = new InMemoryReviewQueue(new InMemoryAuditLog(), () => 1);
  assert.throws(() => q.hold(args({ maskedCard: '4111111111111111' })));
  assert.doesNotThrow(() => q.hold(args({ maskedCard: '411111:1111' })));
});

test('listHeld is ordered by heldAt ascending', () => {
  let now = 300;
  const q = new InMemoryReviewQueue(new InMemoryAuditLog(), () => now);
  const a = q.hold(args());
  now = 100;
  const b = q.hold(args());
  now = 200;
  const c = q.hold(args());
  assert.deepEqual(q.listHeld().map(i => i.id), [b.id, c.id, a.id]);
});

test('audit rejects blank reason for an analyst and freezes entries', () => {
  const audit = new InMemoryAuditLog();
  assert.throws(() => audit.record({ action: 'approve', subjectId: 'rev_1', actor: 'analyst@ops', reason: '  ' }));
  const e = audit.record({ action: 'approve', subjectId: 'rev_1', actor: 'analyst@ops', reason: 'ok' });
  assert.ok(Object.isFrozen(e));
});

test('audit log has no update or delete', () => {
  const audit = new InMemoryAuditLog() as unknown as Record<string, unknown>;
  for (const m of ['update', 'delete', 'remove', 'clear']) assert.equal(audit[m], undefined);
});

test('forSubject orders by at', () => {
  const audit = new InMemoryAuditLog();
  audit.record({ action: 'expire', subjectId: 'r', actor: 'system', reason: '', at: 20 });
  audit.record({ action: 'hold', subjectId: 'r', actor: 'system', reason: '', at: 10 });
  assert.deepEqual(audit.forSubject('r').map(e => e.action), ['hold', 'expire']);
});
