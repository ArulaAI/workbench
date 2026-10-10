import test from 'node:test';
import assert from 'node:assert/strict';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { InMemoryReviewQueue, type HoldArgs } from '../src/review/queue.ts';
import { PaymentsService } from '../src/payments/service.ts';
import { HOLD_TTL_MS, expireHeldReviews, startExpirySweeper } from '../src/review/expiry.ts';
import { resetSinks, sinks } from '../src/obs/index.ts';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';

const setup = () => {
  let clock = 1000;
  const audit = new InMemoryAuditLog();
  const payments = new PaymentsService();
  const queue = new InMemoryReviewQueue(audit, () => clock, payments);
  const calls: Array<Record<string, unknown>> = [];
  const webhook = { holdExpired: (a: Record<string, unknown>) => { calls.push(a); } };
  const hold = () => {
    const payment = payments.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount: 80_000 });
    payments.blockCapture(payment.id);
    const args: HoldArgs = {
      paymentId: payment.id, maskedCard: '411111******1111', merchantId: 'm_1',
      amount: 80_000, currency: 'GBP', score: 750, reasons: ['amount_unusual'],
      merchantCategory: 'electronics', issuerCountry: 'GB', ipCountry: 'JP',
    };
    return queue.hold(args);
  };
  const run = (now: number) => expireHeldReviews(queue, payments, audit, webhook, now);
  return { audit, payments, queue, calls, hold, run, setClock: (t: number) => { clock = t; } };
};

test('boundary: 72h minus 1ms is not expired, exactly 72h is', () => {
  const { queue, hold, run } = setup();
  const item = hold();
  assert.equal(run(item.heldAt + HOLD_TTL_MS - 1).length, 0);
  assert.equal(queue.get(item.id)?.status, 'held');
  assert.equal(run(item.heldAt + HOLD_TTL_MS).length, 1);
  assert.equal(queue.get(item.id)?.status, 'expired');
});

test('expired item voids the payment', () => {
  const { payments, hold, run } = setup();
  const item = hold();
  run(item.heldAt + HOLD_TTL_MS);
  assert.equal(payments.payments.get(item.paymentId)?.status, 'voided');
  assert.equal(payments.ledger.forPayment(item.paymentId).filter(e => e.kind === 'void').length, 2);
});

test('expiry writes one system audit entry, last in the history; sweeping twice adds none', () => {
  const { audit, hold, run } = setup();
  const item = hold();
  const at = item.heldAt + HOLD_TTL_MS;
  run(at);
  run(at + 60_000);
  const expiry = audit.forSubject(item.id).filter(e => e.action === 'expire');
  assert.equal(expiry.length, 1);
  const last = audit.forSubject(item.id).at(-1);
  assert.equal(last?.action, 'expire');
  assert.equal(last?.actor, 'system');
  assert.equal(last?.reason, 'hold ttl elapsed');
});

test('a void failure on one item does not stop the others', () => {
  resetSinks();
  const { payments, queue, hold, run } = setup();
  const a = hold();
  const b = hold();
  const realVoid = payments.void.bind(payments);
  payments.void = (id: string) => {
    if (id === a.paymentId) throw new Error('boom');
    return realVoid(id);
  };
  const out = run(a.heldAt + HOLD_TTL_MS);
  assert.deepEqual(out.map(i => i.id), [b.id]);
  assert.equal(queue.get(a.id)?.status, 'held');
  assert.equal(queue.get(b.id)?.status, 'expired');
  assert.ok(sinks.logs.some(l => l.level === 'error' && l.message.includes(a.id)));
});

test('webhook is called once with ids only and no long digit run', () => {
  const { calls, hold, run } = setup();
  const item = hold();
  const at = item.heldAt + HOLD_TTL_MS;
  run(at);
  run(at + 1);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0], { merchantId: 'm_1', paymentId: item.paymentId, reviewId: item.id, at });
  const digits = JSON.stringify(calls[0]).match(/\d+/g) ?? [];
  assert.equal(/\d{12,}/.test(JSON.stringify({ ...calls[0], at: undefined })), false);
});

test('webhook failure is logged and expiry still completes', () => {
  resetSinks();
  const { audit, payments, queue, hold } = setup();
  const item = hold();
  const webhook = { holdExpired: () => { throw new Error('down'); } };
  const out = expireHeldReviews(queue, payments, audit, webhook, item.heldAt + HOLD_TTL_MS);
  assert.equal(out.length, 1);
  assert.equal(queue.get(item.id)?.status, 'expired');
  assert.ok(sinks.logs.some(l => l.message.includes('webhook failed')));
});

test('sweeper expires on the timer with a fake clock and stops', t => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const { audit, payments, queue, calls, hold } = setup();
  const item = hold();
  let now = item.heldAt;
  const stop = startExpirySweeper({ queue, payments, audit, webhook: { holdExpired: a => { calls.push(a); } }, now: () => now });
  t.mock.timers.tick(60_000);
  assert.equal(queue.get(item.id)?.status, 'held');
  now = item.heldAt + HOLD_TTL_MS;
  t.mock.timers.tick(60_000);
  assert.equal(queue.get(item.id)?.status, 'expired');
  stop();
  const other = hold();
  now = other.heldAt + HOLD_TTL_MS;
  t.mock.timers.tick(120_000);
  assert.equal(queue.get(other.id)?.status, 'held');
});
