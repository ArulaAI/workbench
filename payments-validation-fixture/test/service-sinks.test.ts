import test, { beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';
import { PaymentsService } from '../src/payments/service.ts';
import { findLuhnCandidatesIn, maskedFor, reset } from '../src/vault.ts';
import { NO_PAN_AT_REST } from '../src/domain/invariants.ts';
import { resetSinks, serialiseError, serialiseFailure, sinks } from '../src/obs/index.ts';

const PAN = TEST_CARDS.visa;

/** Everything every sink currently holds, serialised. */
const allSinkContent = (extra: unknown[] = []): string =>
  JSON.stringify({ logs: sinks.logs, spans: sinks.spans, webhooks: sinks.webhooks, extra });

const assertNoPan = (label: string, extra: unknown[] = []) => {
  const content = { logs: sinks.logs, spans: sinks.spans, webhooks: sinks.webhooks, extra };
  assert.deepEqual(findLuhnCandidatesIn(content), [], `${label}: a Luhn-valid PAN reached a sink`);
};

let svc: PaymentsService;
beforeEach(() => {
  reset();
  resetSinks();
  svc = new PaymentsService();
});

test('authorise leaks no PAN to any sink', () => {
  svc.authorise({ pan: PAN, expiry: EXPIRY, amount: 10_000 });
  assert.ok(sinks.logs.length > 0 && sinks.spans.length > 0);
  assertNoPan('authorise');
});

test('capture leaks no PAN to any sink', () => {
  const p = svc.authorise({ pan: PAN, expiry: EXPIRY, amount: 10_000 });
  svc.capture(p.id, 6_000);
  assert.ok(sinks.spans.some(s => s.name === 'payment.capture'));
  assertNoPan('capture');
});

test('refund leaks no PAN to any sink', () => {
  const p = svc.authorise({ pan: PAN, expiry: EXPIRY, amount: 10_000 });
  const c = svc.capture(p.id);
  svc.refund(p.id, c.id, 1_000);
  assert.equal(sinks.webhooks.length, 1);
  assertNoPan('refund');
});

test('void leaks no PAN to any sink', () => {
  const p = svc.authorise({ pan: PAN, expiry: EXPIRY, amount: 10_000 });
  svc.void(p.id);
  assertNoPan('void');
});

test('failing authorise with a malformed card leaks no PAN to logs or serialised errors', () => {
  const malformed = `${PAN}x`;
  let thrown: unknown;
  try {
    svc.authorise({ pan: malformed, expiry: EXPIRY, amount: 10_000 });
  } catch (e) {
    thrown = e;
  }
  assert.ok(thrown instanceof RangeError);
  assert.ok(sinks.logs.some(l => l.level === 'error'), 'failure was logged');
  const serialised = [
    serialiseError(thrown),
    serialiseFailure(thrown, { pan: malformed, note: `card ${malformed}` }),
    serialiseFailure(new Error(`bad ${PAN}`), { raw: PAN }),
  ];
  assertNoPan('failing authorise', serialised);
});

test('a 13-digit millisecond timestamp in a stored record is not reported by NO_PAN_AT_REST', () => {
  const p = svc.authorise({ pan: PAN, expiry: EXPIRY, amount: 10_000 });
  const c = svc.capture(p.id);
  const stamp = 1_700_000_000_000;
  assert.equal(String(stamp).length, 13);
  c.at = stamp;
  assert.ok(JSON.stringify(c).includes(String(stamp)));
  assert.deepEqual(NO_PAN_AT_REST(svc.ledger, svc.payments), []);
  const live = Date.now();
  c.at = live;
  assert.deepEqual(NO_PAN_AT_REST(svc.ledger, svc.payments), []);
});

test('masked card shows only the BIN and last four', () => {
  const p = svc.authorise({ pan: PAN, expiry: EXPIRY, amount: 10_000 });
  const masked = maskedFor(p.token);
  assert.equal(masked, `${PAN.slice(0, 6)}${'*'.repeat(6)}${PAN.slice(-4)}`);
  assert.equal(masked.length, PAN.length);
  assert.ok(sinks.logs.some(l => l.message.includes(masked)));
  assert.ok(!allSinkContent().includes(PAN.slice(6, 12)));
});
