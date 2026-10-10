import test from 'node:test';
import assert from 'node:assert/strict';
import { PaymentsService } from '../src/payments/service.ts';
import { resetSinks, sinks } from '../src/obs/index.ts';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';

const auth = (s: PaymentsService, amount = 10_000) =>
  s.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount });

test('refund references the capture and over-refund reports refundable', () => {
  const s = new PaymentsService();
  const p = auth(s, 5_000);
  const c = s.capture(p.id, 5_000);
  const r = s.refund(p.id, c.id, 2_000);
  assert.equal(r.captureId, c.id);
  assert.throws(() => s.refund(p.id, c.id, 3_001), { message: 'refund 3001 exceeds refundable 3000' });
  assert.equal(s.refund(p.id, c.id).amount, 3_000);
});

test('refund rejects unknown payment and a capture from another payment', () => {
  const s = new PaymentsService();
  const p1 = auth(s);
  const p2 = auth(s);
  const c2 = s.capture(p2.id, 1_000);
  s.capture(p1.id, 1_000);
  assert.throws(() => s.refund('nope', c2.id), { message: 'unknown payment nope' });
  assert.throws(() => s.refund(p1.id, c2.id), { message: `no capture ${c2.id} on ${p1.id}` });
  assert.equal(s.ledger.forPayment(p1.id).some(e => e.kind === 'refund'), false);
});

test('refund is bounded per capture', () => {
  const s = new PaymentsService();
  const p = auth(s, 10_000);
  const c1 = s.capture(p.id, 4_000);
  s.capture(p.id, 6_000);
  s.refund(p.id, c1.id, 4_000);
  assert.throws(() => s.refund(p.id, c1.id, 1), { message: 'refund 1 exceeds refundable 0' });
});

test('refund webhook and log carry no full card number', () => {
  resetSinks();
  const s = new PaymentsService();
  const p = auth(s, 5_000);
  const c = s.capture(p.id, 5_000);
  s.refund(p.id, c.id, 100);
  const out = JSON.stringify([sinks.logs, sinks.webhooks]);
  assert.equal(out.includes(TEST_CARDS.visa), false);
  assert.ok(out.includes('411111******1111'));
});

test('void on an uncaptured payment returns it voided', () => {
  const s = new PaymentsService();
  const p = auth(s, 750);
  assert.equal(s.void(p.id).status, 'voided');
  assert.throws(() => s.void('nope'), { message: 'unknown payment nope' });
});

test('void after a partial capture throws and leaves state unchanged', () => {
  const s = new PaymentsService();
  const p = auth(s, 750);
  s.capture(p.id, 100);
  const entries = s.ledger.entries.length;
  assert.throws(() => s.void(p.id), { message: 'cannot void a captured payment' });
  assert.equal(s.payments.get(p.id)!.status, 'captured');
  assert.equal(s.ledger.entries.length, entries);
});

test('settlementSchedule allocates the captured total', () => {
  const s = new PaymentsService();
  const p = auth(s, 10_000);
  s.capture(p.id, 10_000);
  assert.deepEqual(s.settlementSchedule(p.id, 3), [3334, 3333, 3333]);
  assert.throws(() => s.settlementSchedule(p.id, 0), { name: 'RangeError', message: 'parts must be at least 1' });
  assert.throws(() => s.settlementSchedule('nope', 3), { message: 'unknown payment nope' });
  const q = auth(s, 9_999);
  s.capture(q.id, 9_999);
  assert.equal(s.settlementSchedule(q.id, 7).reduce((a, b) => a + b, 0), 9_999);
});
