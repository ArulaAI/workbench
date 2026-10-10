import test from 'node:test';
import assert from 'node:assert/strict';
import {
  REASON_CODES, isReasonCode, cardholderReason, analystReason, CARDHOLDER_REASONS, assertCardholderReasonSafe,
} from '../src/risk/reasons.ts';

const BANNED = /fraud|suspicious|score|threshold|\d/i;

test('ReasonCode list holds exactly the six codes', () => {
  assert.deepEqual([...REASON_CODES].sort(), [
    'amount_unusual', 'card_testing_pattern', 'country_mismatch',
    'issuer_unknown', 'merchant_category_risk', 'time_of_day',
  ]);
  assert.ok(isReasonCode('time_of_day'));
  assert.ok(!isReasonCode('nope'));
});

test('cardholderReason is short and free of banned terms for every code', () => {
  for (const code of REASON_CODES) {
    const text = cardholderReason(code);
    assert.ok(text !== undefined);
    assert.ok(text.length <= 140);
    assert.doesNotMatch(text, BANNED);
  }
});

test('every allowlist entry is safe', () => {
  for (const text of Object.values(CARDHOLDER_REASONS)) {
    assert.ok(text.length <= 140);
    assert.doesNotMatch(text, BANNED);
  }
  assert.ok(Object.isFrozen(CARDHOLDER_REASONS));
});

test('model-feature codes do not reveal the feature', () => {
  assert.equal(cardholderReason('amount_unusual'), cardholderReason('country_mismatch'));
});

test('step_up_not_confirmed has its own text', () => {
  assert.equal(cardholderReason('step_up_not_confirmed'), "Your bank couldn't confirm this payment.");
});

test('analystReason is non-empty and never a cardholder string', () => {
  const cardholder = new Set(Object.values(CARDHOLDER_REASONS));
  for (const code of REASON_CODES) {
    assert.ok(analystReason(code).length > 0);
    assert.ok(!cardholder.has(analystReason(code)));
  }
});

test('CARDHOLDER_REASONS snapshot', () => {
  assert.deepEqual(CARDHOLDER_REASONS, {
    decline_generic: 'Your bank could not approve this payment.',
    step_up_not_confirmed: "Your bank couldn't confirm this payment.",
    card_testing_pattern: "Your bank couldn't confirm this payment. You haven't been charged.",
  });
});

test('assertCardholderReasonSafe accepts every allowlist entry', () => {
  for (const text of Object.values(CARDHOLDER_REASONS)) assertCardholderReasonSafe(text);
});

test('assertCardholderReasonSafe rejects long text, digits and banned terms', () => {
  assert.throws(() => assertCardholderReasonSafe('a'.repeat(141)), /140/);
  assertCardholderReasonSafe('a'.repeat(140));
  assert.throws(() => assertCardholderReasonSafe('Try 3 times'), /digit/);
  for (const term of [
    'fraud', 'Suspicious', 'score', 'threshold', 'model', 'BIN', 'IP', 'country', 'velocity', 'amount band',
  ]) {
    assert.throws(() => assertCardholderReasonSafe(`Your ${term} matters`), /banned/, term);
  }
  assertCardholderReasonSafe('Please try a different tip');
});

test('cardholderReason returns allowlisted text only', () => {
  const allowed = new Set(Object.values(CARDHOLDER_REASONS));
  const analyst = new Set(REASON_CODES.map(analystReason));
  for (const code of [...REASON_CODES, 'step_up_not_confirmed' as const]) {
    const text = cardholderReason(code);
    assert.ok(text !== undefined && allowed.has(text) && !analyst.has(text));
  }
  assert.equal(cardholderReason('card_testing_pattern'), CARDHOLDER_REASONS.card_testing_pattern);
});
