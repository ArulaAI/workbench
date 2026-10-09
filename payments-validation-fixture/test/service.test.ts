import test from 'node:test';
import assert from 'node:assert/strict';
import { PaymentsService } from '../src/payments/service.ts';
import { checkAll } from '../src/domain/invariants.ts';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';

const svc = () => new PaymentsService();
const auth = (s: PaymentsService, amount = 10_000) =>
  s.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount });

test('authorise records the amount and posts a balanced pair', () => {
  const s = svc();
  const p = auth(s, 2_500);
  assert.equal(p.authorised, 2_500);
  assert.equal(p.status, 'authorised');
  assert.equal(s.ledger.net(), 0);
  assert.equal(s.ledger.forPayment(p.id).length, 2);
});

test('authorise never stores a full PAN', () => {
  const s = svc();
  const p = auth(s);
  assert.equal(p.last4, '1111');
  assert.equal(JSON.stringify(p).includes(TEST_CARDS.visa), false);
});

test('idempotent authorise returns the original payment', () => {
  const s = svc();
  const a = s.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount: 500, idempotencyKey: 'k1' });
  const b = s.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount: 500, idempotencyKey: 'k1' });
  assert.equal(a.id, b.id);
  assert.equal(s.payments.size, 1);
});

test('capture splits into net and fee, and both post', () => {
  const s = svc();
  const p = auth(s, 10_000);
  s.capture(p.id, 10_000);
  assert.equal(s.ledger.totalFor(p.id, 'capture'), 10_000);
  assert.equal(s.ledger.net(), 0);
});

test('partial captures accumulate exactly and never exceed the authorisation', () => {
  const s = svc();
  const p = auth(s, 10_000);
  s.capture(p.id, 6_000);
  s.capture(p.id, 4_000);
  const captured = s.payments.get(p.id)!.captures.reduce((t, c) => t + c.amount, 0);
  assert.equal(captured, 10_000);
  assert.throws(() => s.capture(p.id, 1), RangeError);
});

test('capture beyond the authorisation is rejected', () => {
  const s = svc();
  const p = auth(s, 1_000);
  assert.throws(() => s.capture(p.id, 1_001), RangeError);
});

test('refund reduces nothing below zero and cannot exceed the capture', () => {
  const s = svc();
  const p = auth(s, 5_000);
  const c = s.capture(p.id, 5_000);
  s.refund(p.id, c.id, 3_000);
  assert.throws(() => s.refund(p.id, c.id, 2_001), RangeError);
  assert.equal(s.ledger.net(), 0);
});

test('void reverses an uncaptured authorisation', () => {
  const s = svc();
  const p = auth(s, 750);
  s.void(p.id);
  assert.equal(s.payments.get(p.id)!.status, 'voided');
  assert.equal(s.ledger.net(), 0);
});

test('a captured payment cannot be voided', () => {
  const s = svc();
  const p = auth(s, 750);
  s.capture(p.id, 750);
  assert.throws(() => s.void(p.id), RangeError);
});

test('settlement schedule conserves the captured total', () => {
  const s = svc();
  const p = auth(s, 10_000);
  s.capture(p.id, 10_000);
  for (const parts of [1, 2, 3, 7]) {
    const schedule = s.settlementSchedule(p.id, parts);
    assert.equal(schedule.reduce((a, b) => a + b, 0), 10_000);
  }
});

test('all four invariants hold after a mixed sequence', () => {
  const s = svc();
  const p = auth(s, 12_345);
  const c1 = s.capture(p.id, 5_000);
  s.capture(p.id, 7_345);
  s.refund(p.id, c1.id, 2_500);
  assert.deepEqual(checkAll(s.ledger, s.payments), []);
});
