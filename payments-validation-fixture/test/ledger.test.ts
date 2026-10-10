import test from 'node:test';
import assert from 'node:assert/strict';
import { Ledger } from '../src/domain/ledger.ts';
import { minor } from '../src/domain/money.ts';

test('every post writes a balanced pair', () => {
  const ledger = new Ledger();
  ledger.post({ debit: 'cardholder', credit: 'merchant_receivable', amount: minor(2500), paymentId: 'p1', kind: 'authorise' });
  assert.equal(ledger.entries.length, 2);
  assert.equal(ledger.net(), 0);
});

test('ledger nets to zero across many postings', () => {
  const ledger = new Ledger();
  for (let i = 0; i < 50; i += 1) {
    ledger.post({ debit: 'merchant_receivable', credit: 'merchant_settled', amount: minor(i * 7 + 1), paymentId: `p${i}`, kind: 'capture' });
  }
  assert.equal(ledger.net(), 0);
});

const base = { paymentId: 'p1', kind: 'authorise' as const };

test('post writes two entries sharing a pairId that sum to zero', () => {
  const ledger = new Ledger();
  const pairId = ledger.post({ debit: 'cardholder', credit: 'merchant_receivable', amount: minor(500), ...base });
  assert.equal(ledger.entries.length, 2);
  assert.equal(ledger.entries[0].pairId, pairId);
  assert.equal(ledger.entries[1].pairId, pairId);
  assert.equal(ledger.entries[0].amount + ledger.entries[1].amount, 0);
});

test('post rejects zero, negative and fractional amounts and writes nothing', () => {
  const ledger = new Ledger();
  for (const amount of [0, -5, 1.5]) {
    assert.throws(() => ledger.post({ debit: 'cardholder', credit: 'merchant_receivable', amount: amount as never, ...base }), RangeError);
  }
  assert.equal(ledger.entries.length, 0);
});

test('post rejects debit equal to credit', () => {
  const ledger = new Ledger();
  assert.throws(() => ledger.post({ debit: 'cardholder', credit: 'cardholder', amount: minor(5), ...base }), RangeError);
  assert.equal(ledger.entries.length, 0);
});

test('ledger exposes no single-entry write path and entries are read-only', () => {
  const ledger = new Ledger();
  ledger.post({ debit: 'cardholder', credit: 'merchant_receivable', amount: minor(5), ...base });
  const writers = Object.getOwnPropertyNames(Ledger.prototype).filter(n => /^(push|add|append|write|record)/i.test(n));
  assert.deepEqual(writers, []);
  assert.throws(() => { (ledger as unknown as { entries: unknown }).entries = []; });
  assert.equal(ledger.entries.length, 2);
});

test('forPayment returns only that payment\'s entries', () => {
  const ledger = new Ledger();
  ledger.post({ debit: 'cardholder', credit: 'merchant_receivable', amount: minor(5), paymentId: 'pay_x', kind: 'authorise' });
  ledger.post({ debit: 'cardholder', credit: 'merchant_receivable', amount: minor(7), paymentId: 'pay_y', kind: 'authorise' });
  const rows = ledger.forPayment('pay_x');
  assert.equal(rows.length, 2);
  assert.ok(rows.every(e => e.paymentId === 'pay_x'));
});

test('net(account) returns the signed balance of one account', () => {
  const ledger = new Ledger();
  ledger.post({ debit: 'cardholder', credit: 'merchant_receivable', amount: minor(500), ...base });
  assert.equal(ledger.net('cardholder'), 500);
  assert.equal(ledger.net('merchant_receivable'), -500);
  assert.equal(ledger.net('scheme_fees'), 0);
});

test('pairs groups entries by pairId in groups of exactly two', () => {
  const ledger = new Ledger();
  const a = ledger.post({ debit: 'cardholder', credit: 'merchant_receivable', amount: minor(5), ...base });
  const b = ledger.post({ debit: 'merchant_receivable', credit: 'scheme_fees', amount: minor(1), ...base });
  const pairs = ledger.pairs();
  assert.deepEqual([...pairs.keys()], [a, b]);
  for (const group of pairs.values()) assert.equal(group.length, 2);
});
