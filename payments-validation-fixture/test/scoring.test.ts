import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ModelScorer, toScoringInput, validateScoreResult, type ScoringInput } from '../src/risk/scoring.ts';
import { REASON_CODES } from '../src/risk/reasons.ts';
import { resetSinks, sinks } from '../src/obs/index.ts';
import { travellerTelevision } from './fixtures/traffic.ts';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';

const MODEL = join(import.meta.dirname, 'fixtures', 'model.json');
const scorer = ModelScorer.load(MODEL);
const traveller = (): ScoringInput => toScoringInput(travellerTelevision.request, 'electronics');

const luhnValid = (digits: string): boolean => {
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i -= 1) {
    let d = digits.charCodeAt(i) - 48;
    if (alt) { d *= 2; if (d > 9) d -= 9; }
    sum += d;
    alt = !alt;
  }
  return sum % 10 === 0;
};

test('score returns an integer 0 to 1000, 1 to 3 reasons and the model version', () => {
  const r = scorer.score(traveller());
  assert.ok(Number.isInteger(r.score));
  assert.ok(r.score >= 0 && r.score <= 1000);
  assert.ok(r.reasons.length >= 1 && r.reasons.length <= 3);
  assert.equal(r.modelVersion, 'fixture-gbm-0.1');
  assert.ok(validateScoreResult(r));
});

test('scoring is deterministic and stateless across repeated calls', () => {
  const first = scorer.score(traveller());
  scorer.score(toScoringInput({ ...travellerTelevision.request, amount: 100, ipCountry: 'GB' }, 'gambling'));
  for (let i = 0; i < 5; i += 1) assert.deepEqual(scorer.score(traveller()), first);
  assert.deepEqual(ModelScorer.load(MODEL).score(traveller()), first);
});

test('the traveller scores 300 to 699 with country_mismatch among its reasons', () => {
  const r = scorer.score(traveller());
  assert.ok(r.score >= 300 && r.score <= 699, `score ${r.score}`);
  assert.ok(r.reasons.includes('country_mismatch'));
  assert.deepEqual(r.reasons, ['country_mismatch', 'amount_unusual']);
});

test('reasons are ranked by contribution and capped at three', () => {
  const input: ScoringInput = {
    bin: '999999', amount: 90_000, currency: 'GBP', issuerCountry: undefined, ipCountry: 'GB',
    merchantId: 'm_x', merchantCategory: 'gambling', at: Date.UTC(2026, 0, 1, 3, 0, 0),
  };
  const r = scorer.score(input);
  // 100 base - 20 amount + 300 issuer + 120 hour + 400 gambling/amount = 900
  assert.equal(r.score, 900);
  assert.deepEqual(r.reasons, ['amount_unusual', 'issuer_unknown', 'time_of_day']);
});

test('score clamps into range and still returns a reason when nothing contributes', () => {
  const low = scorer.score({
    bin: '411111', amount: 100, currency: 'GBP', issuerCountry: 'GB', ipCountry: 'GB',
    merchantId: 'm_x', merchantCategory: 'grocery', at: Date.UTC(2026, 0, 1, 12, 0, 0),
  });
  assert.equal(low.score, 80);
  assert.equal(low.reasons.length, 1);
  assert.ok(validateScoreResult(low));

  const high = scorer.score({
    bin: '999999', amount: 500_000, currency: 'GBP', issuerCountry: undefined, ipCountry: 'GB',
    merchantId: 'm_x', merchantCategory: 'gambling', at: Date.UTC(2026, 0, 1, 3, 0, 0),
  });
  // 100 + 150 + 300 + 120 + 400 = 1070, clamped
  assert.equal(high.score, 1000);
});

test('score never returns card_testing_pattern', () => {
  for (const category of ['electronics', 'gambling']) {
    for (const ip of ['GB', 'JP']) {
      const r = scorer.score(toScoringInput({ ...travellerTelevision.request, ipCountry: ip }, category));
      assert.ok(!r.reasons.includes('card_testing_pattern'));
    }
  }
});

test('scoring records a span without card data', () => {
  resetSinks();
  scorer.score(traveller());
  const s = sinks.spans.find(x => x.name === 'risk.score');
  assert.ok(s);
  assert.doesNotMatch(JSON.stringify(s), /\d{6,}/);
});

test('validateScoreResult rejects out-of-range scores, bad reason counts and unknown codes', () => {
  const ok = { score: 500, reasons: ['country_mismatch'], modelVersion: 'v1' };
  assert.ok(validateScoreResult(ok));
  assert.ok(!validateScoreResult({ ...ok, score: 1001 }));
  assert.ok(!validateScoreResult({ ...ok, score: -1 }));
  assert.ok(!validateScoreResult({ ...ok, score: 12.5 }));
  assert.ok(!validateScoreResult({ ...ok, reasons: [] }));
  assert.ok(!validateScoreResult({
    ...ok, reasons: ['country_mismatch', 'amount_unusual', 'time_of_day', 'issuer_unknown'],
  }));
  assert.ok(!validateScoreResult({ ...ok, reasons: ['not_a_code'] }));
  assert.ok(!validateScoreResult({ ...ok, modelVersion: '' }));
  assert.ok(!validateScoreResult(null));
});

test('toScoringInput keeps only the BIN and holds no PAN', () => {
  for (const pan of Object.values(TEST_CARDS)) {
    const input = toScoringInput(
      { pan, expiry: EXPIRY, amount: 249_900, currency: 'GBP', merchantId: 'm_electricals', ipCountry: 'JP' },
      'electronics',
      () => Date.UTC(2026, 9, 3, 14, 0, 0),
    );
    assert.equal(input.bin, pan.slice(0, 6));
    assert.ok(!('pan' in input));
    assert.ok(!('expiry' in input));
    for (const [key, value] of Object.entries(input)) {
      const text = String(value);
      for (const m of text.matchAll(/\d{13,19}/g)) {
        assert.ok(!luhnValid(m[0]), `${key} holds a Luhn-valid ${m[0].length}-digit run`);
      }
      // Numeric `at` is epoch milliseconds, excluded as NO_PAN_AT_REST excludes timestamps.
      if (typeof value === 'string') assert.doesNotMatch(value, /\d{7,}/, `${key} holds 7+ digits`);
    }
  }
});

test('toScoringInput derives issuer country, at and currency', () => {
  const input = traveller();
  assert.equal(input.issuerCountry, 'GB');
  assert.equal(input.ipCountry, 'JP');
  assert.equal(input.merchantCategory, 'electronics');
  assert.equal(input.at, travellerTelevision.request.at);

  const { at: _at, currency: _c, ...rest } = travellerTelevision.request;
  const clocked = toScoringInput({ ...rest, pan: '9999990000000000' }, 'electronics', () => 42);
  assert.equal(clocked.at, 42);
  assert.equal(clocked.currency, 'GBP');
  assert.equal(clocked.issuerCountry, undefined);
});

test('ModelScorer.load throws on a missing or malformed model file', () => {
  const dir = mkdtempSync(join(tmpdir(), 'scoring-'));
  const write = (name: string, body: string): string => {
    const p = join(dir, name);
    writeFileSync(p, body);
    return p;
  };
  const valid = { version: 'v', baseScore: 0, trees: [], featureReasons: { amount: 'amount_unusual' } };

  assert.throws(() => ModelScorer.load(join(dir, 'missing.json')), /cannot read/);
  assert.throws(() => ModelScorer.load(write('bad.json', '{ not json')), /not valid JSON/);
  const malformed: unknown[] = [
    [],
    { ...valid, version: '' },
    { ...valid, baseScore: 'x' },
    { ...valid, trees: {} },
    { ...valid, trees: [{ feature: 'amount', threshold: 1, left: { leaf: 1 } }] },
    { ...valid, trees: [{ leaf: 'x' }] },
    { ...valid, featureReasons: {} },
    { ...valid, featureReasons: { amount: 'nope' } },
    { ...valid, featureReasons: { amount: 'card_testing_pattern' } },
  ];
  malformed.forEach((m, i) => {
    assert.throws(() => ModelScorer.load(write(`m${i}.json`, JSON.stringify(m))), /malformed/);
  });
  assert.ok(ModelScorer.load(write('ok.json', JSON.stringify(valid))));
});

test('every reason code the fixture model can return is known', () => {
  const r = scorer.score(traveller());
  for (const code of r.reasons) assert.ok(REASON_CODES.includes(code));
});
