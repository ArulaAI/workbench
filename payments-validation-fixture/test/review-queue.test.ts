import test from 'node:test';
import assert from 'node:assert/strict';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { InMemoryReviewQueue, ReviewError, type HoldArgs } from '../src/review/queue.ts';
import { CaptureBlockedError, PaymentsService } from '../src/payments/service.ts';
import { resetSinks, sinks } from '../src/obs/index.ts';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';

const H72 = 72 * 60 * 60 * 1000;

const setup = () => {
  const audit = new InMemoryAuditLog();
  const payments = new PaymentsService();
  const queue = new InMemoryReviewQueue(audit, () => 1000, payments);
  const payment = payments.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount: 80_000 });
  payments.blockCapture(payment.id);
  const args: HoldArgs = {
    paymentId: payment.id, maskedCard: '411111******1111', merchantId: 'm_1',
    amount: 80_000, currency: 'GBP', score: 750, reasons: ['amount_unusual'],
    merchantCategory: 'electronics', issuerCountry: 'GB', ipCountry: 'JP',
  };
  const item = queue.hold(args);
  return { audit, payments, queue, payment, item };
};

const codeOf = (fn: () => unknown): string | undefined => {
  try {
    fn();
  } catch (e) {
    assert.ok(e instanceof ReviewError);
    return e.code;
  }
  return undefined;
};

test('blank note is rejected and writes no audit entry', () => {
  const { audit, queue, item } = setup();
  assert.equal(codeOf(() => queue.approve(item.id, 'ana', '   ')), 'NOTE_REQUIRED');
  assert.equal(audit.forSubject(item.id).length, 1);
  assert.equal(queue.get(item.id)?.status, 'held');
});

test('note of 1,001 characters is rejected, 1,000 accepted', () => {
  const { queue, item } = setup();
  assert.equal(codeOf(() => queue.approve(item.id, 'ana', 'x'.repeat(1001))), 'NOTE_TOO_LONG');
  assert.equal(queue.approve(item.id, 'ana', 'x'.repeat(1000)).status, 'approved');
});

test('unknown id and blank analyst', () => {
  const { queue, item } = setup();
  assert.equal(codeOf(() => queue.approve('rev_nope', 'ana', 'ok')), 'REVIEW_NOT_FOUND');
  assert.equal(codeOf(() => queue.decline(item.id, '  ', 'ok')), 'ANALYST_REQUIRED');
});

test('second decision throws ALREADY_DECIDED', () => {
  const { queue, item } = setup();
  queue.approve(item.id, 'ana', 'fine');
  assert.equal(codeOf(() => queue.approve(item.id, 'ana', 'again')), 'ALREADY_DECIDED');
  assert.equal(codeOf(() => queue.decline(item.id, 'ana', 'again')), 'ALREADY_DECIDED');
});

test('approve after 72h throws REVIEW_EXPIRED, at 72h minus 1s succeeds', () => {
  const a = setup();
  assert.equal(codeOf(() => a.queue.approve(a.item.id, 'ana', 'late', 1000 + H72 + 1000)), 'REVIEW_EXPIRED');
  assert.equal(codeOf(() => a.queue.decline(a.item.id, 'ana', 'late', 1000 + H72)), 'REVIEW_EXPIRED');
  const b = setup();
  assert.equal(b.queue.approve(b.item.id, 'ana', 'ok', 1000 + H72 - 1000).status, 'approved');
});

test('approve releases capture, audit has hold then approve', () => {
  const { audit, payments, queue, payment, item } = setup();
  assert.throws(() => payments.capture(payment.id), CaptureBlockedError);
  const done = queue.approve(item.id, 'ana', 'verified by phone', 2000);
  assert.equal(done.status, 'approved');
  assert.equal(done.decidedBy, 'ana');
  assert.equal(done.decidedAt, 2000);
  assert.equal(done.note, 'verified by phone');
  assert.equal(payments.isCaptureBlocked(payment.id), false);
  assert.ok(payments.capture(payment.id));
  const entries = audit.forSubject(item.id);
  assert.deepEqual(entries.map(e => e.action), ['hold', 'approve']);
  assert.equal(entries[1].actor, 'ana');
  assert.equal(entries[1].reason, 'verified by phone');
});

test('decline voids the payment and writes one audit entry', () => {
  const { audit, payments, queue, payment, item } = setup();
  const done = queue.decline(item.id, 'ana', 'looks fraudulent');
  assert.equal(done.status, 'declined');
  assert.equal(payments.payments.get(payment.id)?.status, 'voided');
  const entries = audit.forSubject(item.id).filter(e => e.action === 'decline');
  assert.equal(entries.length, 1);
  assert.equal(entries[0].actor, 'ana');
  assert.equal(entries[0].reason, 'looks fraudulent');
});

test('throwing onHeld listener does not break hold and is logged', () => {
  resetSinks();
  const { queue, payment } = setup();
  const seen: string[] = [];
  queue.onHeld(() => { throw new Error('boom'); });
  const off = queue.onHeld(i => seen.push(i.id));
  const item = queue.hold({
    paymentId: payment.id, maskedCard: '411111******1111', merchantId: 'm_1', amount: 1,
    currency: 'GBP', score: 750, reasons: [], merchantCategory: 'x', issuerCountry: null, ipCountry: 'GB',
  });
  assert.deepEqual(seen, [item.id]);
  assert.ok(sinks.logs.some(l => l.level === 'error' && l.message.includes('boom')));
  off();
});

test('setNarrative stores text and rejects unknown ids', () => {
  const { queue, item } = setup();
  queue.setNarrative(item.id, 'unusual amount');
  assert.equal(queue.get(item.id)?.narrative, 'unusual amount');
  assert.equal(codeOf(() => queue.setNarrative('rev_nope', 'x')), 'REVIEW_NOT_FOUND');
});
