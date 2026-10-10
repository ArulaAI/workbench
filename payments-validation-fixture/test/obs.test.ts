import test from 'node:test';
import assert from 'node:assert/strict';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';
import { findLuhnCandidates, findLuhnCandidatesIn } from '../src/vault.ts';
import { log, redact, resetSinks, serialiseError, serialiseFailure, sinks, span, webhook } from '../src/obs/index.ts';

const PAN = TEST_CARDS.stripeVisa;
const hasPan = (v: unknown) => findLuhnCandidatesIn(v).length > 0;

test('redact masks a spaced PAN, keeping first 6 and last 4', () => {
  const out = redact('card 4242 4242 4242 4242') as string;
  assert.equal(findLuhnCandidates(out).length, 0);
  assert.match(out, /424242\*{6}4242/);
});

test('redact leaves a non-Luhn 13-digit timestamp unchanged', () => {
  assert.equal(redact('at 1700000000000'), 'at 1700000000000');
  assert.equal(redact({ at: 1700000000000 }) instanceof Object, true);
});

test('redact handles nested objects, arrays and cycles', () => {
  const a: Record<string, unknown> = { list: [`n ${PAN}`, { deep: PAN }] };
  a.self = a;
  const out = redact(a);
  assert.equal(hasPan(out), false);
  assert.equal((out as { self: unknown }).self, '[circular]');
});

test('surface 1: log', () => {
  resetSinks();
  log.info(`paid ${PAN}`);
  log.error(`bad ${PAN}`);
  assert.equal(hasPan(sinks.logs), false);
});

test('surface 2: webhook body', () => {
  resetSinks();
  webhook('https://m.example/h', 500, { note: PAN, nested: [PAN] });
  assert.equal(hasPan(sinks.webhooks), false);
});

test('surface 3: span attributes', () => {
  resetSinks();
  span('payment', { card: PAN, list: [PAN] });
  assert.equal(hasPan(sinks.spans), false);
});

test('surface 4: fixture output', () => {
  const fixture = { request: { pan: TEST_CARDS.visa, expiry: EXPIRY, note: TEST_CARDS.visa } };
  assert.equal(hasPan(redact(fixture)), false);
});

test('surface 5: serialised exception path', () => {
  const err = new Error(`pan ${PAN}`, { cause: new Error(`cause ${PAN}`) });
  assert.equal(hasPan(serialiseError(err)), false);
  assert.equal(hasPan(serialiseError(new Error('pan 4242424242424242'))), false);
  assert.equal(hasPan(serialiseFailure(err, { n: PAN })), false);
});

test('resetSinks clears all sinks', () => {
  log.info('x');
  resetSinks();
  assert.equal(sinks.logs.length + sinks.spans.length + sinks.webhooks.length, 0);
});
