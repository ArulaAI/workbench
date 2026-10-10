import test from 'node:test';
import assert from 'node:assert/strict';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { InMemoryReviewQueue, type HoldArgs } from '../src/review/queue.ts';
import { PaymentsService } from '../src/payments/service.ts';
import { ConsoleError, ReviewConsole, requireAnalyst, type ConsoleSession } from '../src/review/console.ts';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';

const session: ConsoleSession = { analyst: 'a@ops', authenticated: true };

const setup = () => {
  const audit = new InMemoryAuditLog();
  const payments = new PaymentsService();
  let now = 1000;
  const queue = new InMemoryReviewQueue(audit, () => now, payments);
  const hold = (maskedCard = '411111******1111') => {
    const payment = payments.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount: 80_000 });
    payments.blockCapture(payment.id);
    const args: HoldArgs = {
      paymentId: payment.id, maskedCard, merchantId: 'm_1', amount: 80_000, currency: 'GBP',
      score: 750, reasons: ['amount_unusual'], merchantCategory: 'electronics',
      issuerCountry: 'GB', ipCountry: 'JP',
    };
    return queue.hold(args);
  };
  const console_ = new ReviewConsole({ queue, merchantName: id => `Merchant ${id}` });
  return { audit, queue, hold, console_, tick: (ms: number) => { now += ms; } };
};

const codeOf = (fn: () => unknown): string | undefined => {
  try {
    fn();
  } catch (e) {
    assert.ok(e instanceof ConsoleError);
    return e.code;
  }
  return undefined;
};

test('unauthenticated or blank-analyst sessions throw UNAUTHENTICATED', () => {
  const { console_ } = setup();
  assert.equal(codeOf(() => console_.list({ authenticated: false })), 'UNAUTHENTICATED');
  assert.equal(codeOf(() => console_.list({ authenticated: true, analyst: '  ' })), 'UNAUTHENTICATED');
  assert.equal(codeOf(() => requireAnalyst({ authenticated: false, analyst: 'x' })), 'UNAUTHENTICATED');
  assert.equal(requireAnalyst(session), 'a@ops');
});

test('list returns held items oldest first with reason and masked card', () => {
  const { console_, hold, tick } = setup();
  const first = hold();
  tick(500);
  const second = hold('411111:2222');
  const rows = console_.list(session);
  assert.deepEqual(rows.map(r => r.reviewId), [first.id, second.id]);
  for (const r of rows) {
    assert.ok(r.reason.length > 0);
    assert.match(r.maskedCard, /^\d{6}\*{6}\d{4}$/);
    assert.equal(r.merchantName, 'Merchant m_1');
    assert.deepEqual(r.amount, { minor: 80_000, currency: 'GBP' });
  }
  assert.equal(rows[1].maskedCard, '411111******2222');
});

test('approve ignores body analyst and records the session analyst', () => {
  const { console_, hold, audit } = setup();
  const item = hold();
  console_.approve(session, item.id, { note: 'ok', analyst: 'evil' } as any);
  const entry = audit.forSubject(item.id).find(e => e.action === 'approve');
  assert.equal(entry?.actor, 'a@ops');
  assert.deepEqual(console_.list(session), []);
});

test('get includes narrative only once set', () => {
  const { console_, hold, queue } = setup();
  const item = hold();
  assert.equal('narrative' in console_.get(session, item.id), false);
  queue.setNarrative(item.id, 'Unusual amount for this merchant');
  const detail = console_.get(session, item.id);
  assert.equal(detail.narrative, 'Unusual amount for this merchant');
  assert.equal(detail.status, 'held');
  assert.ok(detail.reasons.length > 0);
});

test('queue errors pass through as typed codes', () => {
  const { console_, hold } = setup();
  const item = hold();
  assert.equal(codeOf(() => console_.approve(session, item.id, { note: '  ' })), 'NOTE_REQUIRED');
  assert.equal(codeOf(() => console_.approve(session, 'rev_nope', { note: 'ok' })), 'REVIEW_NOT_FOUND');
  console_.decline(session, item.id, { note: 'fraud' });
  assert.equal(codeOf(() => console_.approve(session, item.id, { note: 'ok' })), 'ALREADY_DECIDED');
});

test('decisions need an authenticated session', () => {
  const { console_, hold } = setup();
  const item = hold();
  assert.equal(codeOf(() => console_.decline({ authenticated: false }, item.id, { note: 'x' })), 'UNAUTHENTICATED');
});

test('review expiry passes through', () => {
  const { console_, hold, tick } = setup();
  const item = hold();
  tick(72 * 60 * 60 * 1000);
  assert.equal(codeOf(() => console_.approve(session, item.id, { note: 'late' })), 'REVIEW_EXPIRED');
});
