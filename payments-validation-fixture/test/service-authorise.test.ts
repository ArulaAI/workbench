import test from 'node:test';
import assert from 'node:assert/strict';
import { PaymentsService } from '../src/payments/service.ts';
import { sinks, resetSinks } from '../src/obs/index.ts';
import { findLuhnCandidates, findLuhnCandidatesIn } from '../src/vault.ts';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';

const request = (amount: number, idempotencyKey?: string) => ({
  pan: TEST_CARDS.visa,
  expiry: EXPIRY,
  amount,
  ...(idempotencyKey ? { idempotencyKey } : {}),
});

test('a fractional amount throws before anything is written', () => {
  const s = new PaymentsService();
  s.authorise(request(1_000));
  const entries = s.ledger.entries.length;
  const payments = s.payments.size;
  resetSinks();

  assert.throws(() => s.authorise(request(10.5)), {
    name: 'RangeError',
    message: 'money must be integer minor units, got 10.5',
  });
  assert.equal(s.ledger.entries.length, entries);
  assert.equal(s.payments.size, payments);
  assert.equal(sinks.logs.length, 0);
  assert.equal(sinks.spans.length, 0);
});

test('a ledger rejection leaves the store and idempotency map unchanged', () => {
  const s = new PaymentsService();
  assert.throws(() => s.authorise(request(0, 'k0')), RangeError);
  assert.equal(s.payments.size, 0);
  assert.equal(s.ledger.entries.length, 0);
  // The key was not recorded, so the next attempt with it is a fresh authorisation.
  const p = s.authorise(request(100, 'k0'));
  assert.equal(p.authorised, 100);
  assert.equal(s.payments.size, 1);
});

test('a replayed idempotency key returns the original payment and writes nothing', () => {
  const s = new PaymentsService();
  const a = s.authorise(request(500, 'k1'));
  const entries = s.ledger.entries.length;
  resetSinks();

  const b = s.authorise(request(500, 'k1'));
  assert.equal(b.id, a.id);
  assert.equal(b, a);
  assert.equal(s.payments.size, 1);
  assert.equal(s.ledger.entries.length, entries);
  assert.equal(sinks.logs.length, 0);
  assert.equal(sinks.spans.length, 0);

  // No ID was consumed by the replay.
  const c = s.authorise(request(500, 'k2'));
  assert.equal(c.id, 'pay_000002');
});

test('the stored payment keeps only the token, BIN and last four', () => {
  const s = new PaymentsService();
  const p = s.authorise(request(2_500));
  assert.equal(p.bin, '411111');
  assert.equal(p.last4, '1111');
  assert.match(p.token, /^tok_/);
  const stored = JSON.stringify(s.payments.get(p.id));
  assert.deepEqual(findLuhnCandidatesIn(s.payments.get(p.id)), []);
  assert.equal(stored.includes(TEST_CARDS.visa), false);
});

test('log and span carry only the masked card', () => {
  const s = new PaymentsService();
  resetSinks();
  const p = s.authorise(request(2_500));
  const masked = '411111******1111';
  assert.equal(sinks.logs.at(-1)?.message, `authorised ${p.id} for ${masked}`);
  assert.deepEqual(sinks.spans.at(-1), {
    name: 'payment.authorise',
    attributes: { paymentId: p.id, card: masked, amount: 2_500 },
  });
});

test('a tokenise failure logs a redacted failure and rethrows', () => {
  const s = new PaymentsService();
  resetSinks();
  const pan = `${TEST_CARDS.visa}x`;
  assert.throws(
    () => s.authorise({ pan, expiry: EXPIRY, amount: 1_000, idempotencyKey: 'k1' }),
    { name: 'RangeError', message: 'invalid card number' },
  );
  assert.equal(sinks.logs.length, 1);
  const logged = sinks.logs[0];
  assert.equal(logged.level, 'error');
  assert.equal(logged.message.includes(TEST_CARDS.visa), false);
  assert.deepEqual(findLuhnCandidates(logged.message), []);
  assert.equal(s.payments.size, 0);
  assert.equal(s.ledger.entries.length, 0);
  assert.equal(sinks.spans.length, 0);
});

test('idempotency keys are namespaced by operation', () => {
  const s = new PaymentsService();
  const p = s.authorise(request(10_000, 'shared'));

  // With a shared namespace, capture would hand back the stored Payment.
  let captured: unknown;
  try {
    captured = s.capture(p.id, 10_000, 'shared');
  } catch (error) {
    // capture's own fee path may reject (owned by the capture task); it must not replay.
    assert.ok(error instanceof RangeError);
  }
  assert.notEqual(captured, p);
  assert.equal((captured as { token?: unknown } | undefined)?.token, undefined);

  // And the authorise entry is still intact afterwards.
  assert.equal(s.authorise(request(10_000, 'shared')), p);
  assert.equal(s.payments.size, 1);
});
