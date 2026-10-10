import test from 'node:test';
import assert from 'node:assert/strict';
import { PaymentsService } from '../src/payments/service.ts';
import { checkAll } from '../src/domain/invariants.ts';
import { sinks } from '../src/obs/index.ts';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';

const setup = (amount = 10_000) => {
  const s = new PaymentsService();
  const p = s.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount });
  return { s, p };
};
const lastSpan = () => sinks.spans.at(-1)!;

test('6000 then 4000 succeed and 1 more is rejected', () => {
  const { s, p } = setup();
  s.capture(p.id, 6_000);
  s.capture(p.id, 4_000);
  assert.throws(() => s.capture(p.id, 1), new RangeError('capture 1 exceeds remaining 0'));
  assert.deepEqual(checkAll(s.ledger, s.payments), []);
});

test('capture with no amount takes the full remaining', () => {
  const { s, p } = setup();
  s.capture(p.id, 6_000);
  assert.equal(s.capture(p.id).amount, 4_000);
});

test('fee and net split at 1.49%', () => {
  const { s, p } = setup();
  s.capture(p.id, 6_000);
  assert.equal(lastSpan().attributes.fee, 89);
  assert.equal(lastSpan().attributes.net, 5_911);
  s.capture(p.id, 4_000);
  assert.equal(lastSpan().attributes.fee, 60);
  assert.equal(lastSpan().attributes.net, 3_940);
  assert.equal(s.ledger.totalFor(p.id, 'capture'), 10_000);
});

test('fee + net === amount for every capture', () => {
  for (const amt of [1, 2, 33, 67, 99, 101, 9_999]) {
    const { s, p } = setup(amt);
    s.capture(p.id, amt);
    const a = lastSpan().attributes;
    assert.equal((a.fee as number) + (a.net as number), amt);
    assert.equal(s.ledger.net(), 0);
  }
});

test('replay with the same key returns the same capture and writes nothing', () => {
  const { s, p } = setup();
  const a = s.capture(p.id, 1_000, 'k');
  const n = s.ledger.entries.length;
  const b = s.capture(p.id, 2_000, 'k');
  assert.equal(a.id, b.id);
  assert.equal(s.ledger.entries.length, n);
  assert.equal(s.payments.get(p.id)!.captures.length, 1);
});

test('unknown payment throws and writes nothing', () => {
  const s = new PaymentsService();
  assert.throws(() => s.capture('nope', 1), new RangeError('unknown payment nope'));
  assert.equal(s.ledger.entries.length, 0);
});

test('exactly remaining succeeds, remaining + 1 is rejected without writes', () => {
  const { s, p } = setup(500);
  const n = s.ledger.entries.length;
  assert.throws(() => s.capture(p.id, 501), new RangeError('capture 501 exceeds remaining 500'));
  assert.equal(s.ledger.entries.length, n);
  assert.equal(s.payments.get(p.id)!.captures.length, 0);
  s.capture(p.id, 500);
});

test('invalid amounts are rejected before any write', () => {
  const { s, p } = setup();
  const n = s.ledger.entries.length;
  for (const bad of [0, -5, 1.5]) assert.throws(() => s.capture(p.id, bad), RangeError);
  assert.equal(s.ledger.entries.length, n);
  assert.equal(s.payments.get(p.id)!.captures.length, 0);
});
