/*
 * Characterisation tests for the gateway and risk rules v1.
 *
 * These pin what the gateway does today, including the behaviour the adaptive
 * authorisation work exists to change. A test that starts failing because of that work is
 * expected to be rewritten, deliberately, alongside the spec that changed it.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { AuthorisationGateway } from '../src/payments/gateway.ts';
import { sinks, resetSinks } from '../src/obs/index.ts';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';
import { cardTestingBurst, domesticGroceries, travellerTelevision } from './fixtures/traffic.ts';

const gw = () => new AuthorisationGateway();

test('[GW-01] a routine domestic purchase is approved', () => {
  const result = gw().authorise(domesticGroceries.request);
  assert.equal(result.status, 'approved');
});

test('[GW-02] a high-value purchase from abroad is declined', () => {
  const result = gw().authorise(travellerTelevision.request);
  assert.deepEqual(result, { status: 'declined', code: 'do_not_honour' });
});

test('[GW-03] a decline tells the merchant nothing about why', () => {
  resetSinks();
  const result = gw().authorise(travellerTelevision.request);
  assert.deepEqual(Object.keys(result).sort(), ['code', 'status']);
  assert.match(sinks.logs.at(-1)?.message ?? '', /HIGH_VALUE_CROSS_BORDER/);
});

test('[GW-04] a sixth attempt on one card inside ten minutes is declined', () => {
  const g = gw();
  const at = Date.UTC(2026, 9, 3, 9, 0, 0);
  const attempt = (i: number) => g.authorise({
    pan: TEST_CARDS.mastercard, expiry: EXPIRY, amount: 1_000,
    merchantId: 'm_cafe', ipCountry: 'GB', at: at + i * 1_000,
  });
  for (let i = 0; i < 5; i += 1) assert.equal(attempt(i).status, 'approved');
  assert.equal(attempt(5).status, 'declined');
});

test('[GW-05] a card-testing burst across merchants is approved in full', () => {
  const g = gw();
  const burst = cardTestingBurst();
  const approved = burst.filter(({ request }) => g.authorise(request).status === 'approved');
  assert.equal(approved.length, burst.length);
});

test('[GW-06] velocity is per gateway instance, so a second replica starts from zero', () => {
  const at = Date.UTC(2026, 9, 3, 9, 0, 0);
  const req = (i: number) => ({
    pan: TEST_CARDS.mastercard, expiry: EXPIRY, amount: 1_000,
    merchantId: 'm_cafe', ipCountry: 'GB', at: at + i * 1_000,
  });
  const a = gw();
  const b = gw();
  for (let i = 0; i < 5; i += 1) a.authorise(req(i));
  assert.equal(b.authorise(req(5)).status, 'approved');
});
