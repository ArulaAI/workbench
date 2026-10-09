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
