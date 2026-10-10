import test, { beforeEach, afterEach, mock } from 'node:test';
import assert from 'node:assert/strict';
import { PaymentsService } from '../src/payments/service.ts';
import { checkAll } from '../src/domain/invariants.ts';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';

// The PAN scan flags any Luhn-valid run of 13+ digits, which includes the odd Date.now()
// value. Pin the clock to a timestamp that is not Luhn-valid so checkAll is deterministic.
beforeEach(() => { mock.method(Date, 'now', () => 1_700_000_000_000); });
afterEach(() => { mock.restoreAll(); });

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

// ---- End-to-end scenarios. Each one finishes with settled(), which runs checkAll. ----

const settled = (s: PaymentsService) => {
  assert.deepEqual(checkAll(s.ledger, s.payments), []);
  assert.equal(s.ledger.net(), 0);
  for (const entries of s.ledger.pairs().values()) {
    assert.equal(entries.reduce((t, e) => t + e.amount, 0), 0);
  }
};

const capturePostings = (s: PaymentsService, paymentId: string, account: 'merchant_settled' | 'scheme_fees') =>
  s.ledger.forPayment(paymentId).filter(e => e.kind === 'capture' && e.account === account).map(e => Math.abs(e.amount));

const counts = (s: PaymentsService) => ({
  payments: s.payments.size,
  captures: [...s.payments.values()].reduce((t, p) => t + p.captures.length, 0),
  ledger: s.ledger.entries.length,
});

test('RFC Basic Example reproduces exactly', () => {
  const s = svc();
  const p = s.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount: 10_000, idempotencyKey: 'k1' });
  assert.equal(p.id, 'pay_000001');
  assert.equal(p.status, 'authorised');
  const c1 = s.capture(p.id, 6_000);
  const c2 = s.capture(p.id, 4_000);
  assert.equal(c1.id, 'cap_000002');
  assert.equal(c2.id, 'cap_000003');
  assert.deepEqual(capturePostings(s, p.id, 'scheme_fees'), [89, 60]);
  assert.deepEqual(capturePostings(s, p.id, 'merchant_settled'), [5_911, 3_940]);
  assert.throws(() => s.capture(p.id, 1), /exceeds remaining 0/);
  const r = s.refund(p.id, c1.id, 2_500);
  assert.equal(r.id, 'ref_000004');
  assert.deepEqual(s.settlementSchedule(p.id, 3), [3_334, 3_333, 3_333]);
  settled(s);

  const before = counts(s);
  const again = s.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount: 10_000, idempotencyKey: 'k1' });
  assert.equal(again.id, 'pay_000001');
  assert.deepEqual(counts(s), before);
  settled(s);
});

test('full capture splits into fee and net that sum to the capture', () => {
  const s = svc();
  const p = auth(s, 10_000);
  const c = s.capture(p.id);
  assert.equal(c.amount, 10_000);
  const [fee] = capturePostings(s, p.id, 'scheme_fees');
  const [net] = capturePostings(s, p.id, 'merchant_settled');
  assert.equal(fee + net, c.amount);
  assert.equal(s.payments.get(p.id)!.status, 'captured');
  settled(s);
});

test('partial capture leaves the remainder capturable', () => {
  const s = svc();
  const p = auth(s, 10_000);
  const c = s.capture(p.id, 3_000);
  assert.equal(c.amount, 3_000);
  const [fee] = capturePostings(s, p.id, 'scheme_fees');
  const [net] = capturePostings(s, p.id, 'merchant_settled');
  assert.equal(fee + net, 3_000);
  const rest = s.capture(p.id);
  assert.equal(rest.amount, 7_000);
  settled(s);
});

test('over-capture is rejected and writes nothing', () => {
  const s = svc();
  const p = auth(s, 1_000);
  s.capture(p.id, 400);
  const before = counts(s);
  assert.throws(() => s.capture(p.id, 601), RangeError);
  assert.deepEqual(counts(s), before);
  settled(s);
});

test('refund up to the capture succeeds and over-refund is rejected', () => {
  const s = svc();
  const p = auth(s, 5_000);
  const c = s.capture(p.id, 5_000);
  s.refund(p.id, c.id, 1_000);
  s.refund(p.id, c.id);
  assert.equal(s.payments.get(p.id)!.refunds.reduce((t, r) => t + r.amount, 0), 5_000);
  const before = counts(s);
  assert.throws(() => s.refund(p.id, c.id, 1), RangeError);
  assert.deepEqual(counts(s), before);
  settled(s);
});

test('refunding a capture from another payment is rejected', () => {
  const s = svc();
  const a = auth(s, 2_000);
  const b = auth(s, 3_000);
  s.capture(a.id, 2_000);
  const cb = s.capture(b.id, 3_000);
  const before = counts(s);
  assert.throws(() => s.refund(a.id, cb.id, 100), /no capture/);
  assert.deepEqual(counts(s), before);
  settled(s);
});

test('void before capture reverses the authorisation', () => {
  const s = svc();
  const p = auth(s, 900);
  s.void(p.id);
  assert.equal(s.payments.get(p.id)!.status, 'voided');
  assert.equal(s.ledger.totalFor(p.id, 'void'), 900);
  settled(s);
});

test('void after capture is rejected and writes nothing', () => {
  const s = svc();
  const p = auth(s, 900);
  s.capture(p.id, 900);
  const before = counts(s);
  assert.throws(() => s.void(p.id), RangeError);
  assert.deepEqual(counts(s), before);
  assert.equal(s.payments.get(p.id)!.status, 'captured');
  settled(s);
});

test('idempotent authorise replay changes no counts', () => {
  const s = svc();
  const req = { pan: TEST_CARDS.visa, expiry: EXPIRY, amount: 700, idempotencyKey: 'auth-1' };
  const a = s.authorise(req);
  const before = counts(s);
  const b = s.authorise(req);
  assert.equal(b, a);
  assert.deepEqual(counts(s), before);
  settled(s);
});

test('idempotent capture replay changes no counts, even after a later capture', () => {
  const s = svc();
  const p = auth(s, 10_000);
  const first = s.capture(p.id, 6_000, 'cap-1');
  const replay = s.capture(p.id, 6_000, 'cap-1');
  assert.equal(replay.id, first.id);
  s.capture(p.id, 4_000, 'cap-2');
  const before = counts(s);
  const late = s.capture(p.id, 6_000, 'cap-1');
  assert.equal(late.id, first.id);
  assert.deepEqual(counts(s), before);
  assert.equal(s.payments.get(p.id)!.captures.length, 2);
  settled(s);
});

test('settlement schedule of a single minor unit', () => {
  const s = svc();
  const p = auth(s, 1);
  const c = s.capture(p.id, 1);
  assert.equal(c.amount, 1);
  assert.equal(capturePostings(s, p.id, 'scheme_fees').length, 0);
  assert.deepEqual(capturePostings(s, p.id, 'merchant_settled'), [1]);
  assert.deepEqual(s.settlementSchedule(p.id, 1), [1]);
  assert.deepEqual(s.settlementSchedule(p.id, 3), [1, 0, 0]);
  settled(s);
});

test('settlement schedule 9999 over 7 and 10000 over 3', () => {
  const s = svc();
  const a = auth(s, 9_999);
  s.capture(a.id);
  assert.deepEqual(s.settlementSchedule(a.id, 7), [1_429, 1_429, 1_429, 1_428, 1_428, 1_428, 1_428]);
  const b = auth(s, 10_000);
  s.capture(b.id);
  assert.deepEqual(s.settlementSchedule(b.id, 3), [3_334, 3_333, 3_333]);
  settled(s);
});
