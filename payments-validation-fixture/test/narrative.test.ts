import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildNarrativeInput, assertNoCardData, NarrativeWriter, amountBandFor, type NarrativeInput,
} from '../src/risk/narrative.ts';
import type { ReviewItem } from '../src/review/queue.ts';
import { sinks, resetSinks } from '../src/obs/index.ts';

const traveller = (): ReviewItem => ({
  id: 'rev_000001', paymentId: 'pay_000001', maskedCard: '411111******1111',
  merchantId: 'm_electricals', amount: 249_900, score: 780,
  analystReason: 'IP country differs from issuer country', narrative: null, heldAt: 0,
  status: 'held', decidedBy: null, note: null, decidedAt: null,
  reasons: ['country_mismatch', 'amount_unusual'], currency: 'GBP',
  merchantCategory: 'electronics', issuerCountry: 'GB', ipCountry: 'JP',
});
const ctx = { merchantCategory: 'electronics', issuerCountry: 'GB', ipCountry: 'JP' };

test('buildNarrativeInput has exactly the allowed keys', () => {
  const input = buildNarrativeInput(traveller(), ctx);
  assert.deepEqual(Object.keys(input).sort(),
    ['amountBand', 'ipCountry', 'issuerCountry', 'merchantCategory', 'reasons', 'score']);
});

test('2,499.00 GBP maps to 1000_to_4999 and band edges hold', () => {
  assert.equal(buildNarrativeInput(traveller(), ctx).amountBand, '1000_to_4999');
  assert.equal(amountBandFor(9_999), 'under_100');
  assert.equal(amountBandFor(10_000), '100_to_999');
  assert.equal(amountBandFor(100_000), '1000_to_4999');
  assert.equal(amountBandFor(500_000), '5000_plus');
});

test('assertNoCardData throws on PAN, BIN, last-four pattern and extra keys', () => {
  const ok = buildNarrativeInput(traveller(), ctx);
  assert.doesNotThrow(() => assertNoCardData(ok));
  for (const bad of ['4111111111111111', '411111']) {
    assert.throws(() => assertNoCardData({ ...ok, merchantCategory: bad }));
    assert.throws(() => assertNoCardData({ ...ok, ipCountry: bad }));
    assert.throws(() => assertNoCardData({ ...ok, issuerCountry: bad }));
  }
  assert.throws(() => assertNoCardData({ ...ok, merchantCategory: '****1111' }));
  assert.throws(() => assertNoCardData({ ...ok, merchantCategory: '1111****' }));
  assert.throws(() => assertNoCardData({ ...ok, merchantId: 'm_electricals' } as NarrativeInput));
});

test('prompt for the traveller fixture holds no card data or merchant descriptor', async () => {
  const prompts: string[] = [];
  const writer = new NarrativeWriter({ complete: async p => { prompts.push(p); return 'ok'; } });
  const input = buildNarrativeInput(traveller(), ctx);
  assertNoCardData(input);
  assert.equal(await writer.describe(input), 'ok');
  assert.equal(prompts.length, 1);
  assert.doesNotMatch(prompts[0], /411111|1111|tok_|m_electricals/i);
  assert.match(prompts[0], /1000_to_4999/);
});

test('describe returns undefined without throwing when the client rejects', async () => {
  resetSinks();
  const writer = new NarrativeWriter({ complete: async () => { throw new Error('vendor down'); } });
  assert.equal(await writer.describe(buildNarrativeInput(traveller(), ctx)), undefined);
  assert.ok(sinks.logs.some(l => l.level === 'error' && l.message.includes('vendor down')));
});

test('describe returns undefined when the client exceeds timeoutMs', async () => {
  const writer = new NarrativeWriter({ complete: () => new Promise(() => {}) }, { timeoutMs: 20 });
  assert.equal(await writer.describe(buildNarrativeInput(traveller(), ctx)), undefined);
});
