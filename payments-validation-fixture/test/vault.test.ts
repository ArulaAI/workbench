import test from 'node:test';
import assert from 'node:assert/strict';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';
import { findLuhnCandidates, findLuhnCandidatesIn, isLuhnValid, maskedFor, records, reset, tokenise, type Token } from '../src/vault.ts';

const PUBLISHED_TEST_NUMBERS = new Set([
  '4111111111111111',
  '4242424242424242',
  '4000056655665556',
  '5555555555554444',
  '378282246310005',
  '6011111111111117',
]);

const withCheckDigit = (body: string): string => {
  for (let c = 0; c < 10; c += 1) if (isLuhnValid(body + c)) return body + c;
  throw new Error('unreachable');
};

test('tokenise returns token, last4 and bin', () => {
  reset();
  const card = tokenise(TEST_CARDS.stripeVisa, EXPIRY);
  assert.ok(card.token.startsWith('tok_'));
  assert.equal(card.last4, '4242');
  assert.equal(card.bin, '424242');
  assert.equal(tokenise(TEST_CARDS.amex, EXPIRY).token === card.token, false);
});

test('tokens are deterministic after reset', () => {
  reset();
  const a = tokenise(TEST_CARDS.visa, EXPIRY).token;
  reset();
  assert.equal(tokenise(TEST_CARDS.visa, EXPIRY).token, a);
});

test('tokenise rejects Luhn-invalid numbers', () => {
  assert.throws(() => tokenise('4242424242424241', EXPIRY));
  assert.throws(() => tokenise('abc', EXPIRY));
});

test('records hold no Luhn-valid 13-19 digit sequence', () => {
  reset();
  for (const pan of Object.values(TEST_CARDS)) tokenise(pan, EXPIRY);
  assert.equal(records().length, Object.keys(TEST_CARDS).length);
  assert.deepEqual(findLuhnCandidatesIn(records()), []);
});

test('maskedFor shows only bin and last four', () => {
  reset();
  const { token } = tokenise(TEST_CARDS.stripeVisa, EXPIRY);
  const masked = maskedFor(token);
  assert.equal(masked, '424242******4242');
  assert.ok(!masked.includes(TEST_CARDS.stripeVisa));
  assert.throws(() => maskedFor('tok_nope' as Token));
});

test('isLuhnValid', () => {
  assert.equal(isLuhnValid('4242424242424242'), true);
  assert.equal(isLuhnValid('4242424242424241'), false);
});

test('findLuhnCandidates is Luhn based, not length based', () => {
  const ts = '1700000000000';
  const invalid = isLuhnValid(ts) ? '1700000000001' : ts;
  assert.deepEqual(findLuhnCandidates(invalid), []);
  const thirteen = withCheckDigit('170000000000');
  assert.equal(thirteen.length, 13);
  assert.deepEqual(findLuhnCandidates(`at ${thirteen}`), [thirteen]);
  assert.deepEqual(findLuhnCandidates('card 4242 4242-4242 4242 end'), ['4242 4242-4242 4242']);
  assert.deepEqual(findLuhnCandidates('4242 4242 4242 4241'), []);
});

test('every fixture card is a published scheme test number', () => {
  for (const pan of Object.values(TEST_CARDS)) {
    assert.ok(PUBLISHED_TEST_NUMBERS.has(pan), pan);
    assert.ok(isLuhnValid(pan));
  }
});
