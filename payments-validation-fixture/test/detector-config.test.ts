import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadDetectorConfig, DetectorConfigError } from '../src/risk/detector-config.ts';

const defaults = JSON.parse(readFileSync(new URL('../config/detector.json', import.meta.url), 'utf8'));
const withField = (k: string, v: unknown) => ({ ...defaults, [k]: v });
const MIN = 60 * 1000;
const HOUR = 60 * MIN;

test('config/detector.json loads the documented defaults', () => {
  assert.deepEqual(loadDetectorConfig(defaults), {
    smallAmountCeiling: 500, windowMs: 120000, minCards: 10, minMerchants: 5,
    blockTtlMs: 3600000, refreshIntervalMs: 1000, notifyFollowUpMs: 300000,
    mode: 'shadow', version: 'f2.2-0.2-defaults',
  });
});

test('minCards and minMerchants below 2 throw', () => {
  assert.throws(() => loadDetectorConfig(withField('minCards', 1)), DetectorConfigError);
  assert.throws(() => loadDetectorConfig(withField('minMerchants', 1)), DetectorConfigError);
  assert.equal(loadDetectorConfig(withField('minCards', 2)).minCards, 2);
});

test('blockTtlMs bounds are inclusive', () => {
  assert.throws(() => loadDetectorConfig(withField('blockTtlMs', 4 * MIN)), DetectorConfigError);
  assert.throws(() => loadDetectorConfig(withField('blockTtlMs', 25 * HOUR)), DetectorConfigError);
  assert.equal(loadDetectorConfig(withField('blockTtlMs', 5 * MIN)).blockTtlMs, 5 * MIN);
  assert.equal(loadDetectorConfig(withField('blockTtlMs', 24 * HOUR)).blockTtlMs, 24 * HOUR);
});

test('non-integer, zero, negative or non-number numeric fields throw', () => {
  for (const f of ['smallAmountCeiling', 'windowMs', 'minCards', 'minMerchants', 'blockTtlMs', 'refreshIntervalMs', 'notifyFollowUpMs']) {
    for (const bad of [0, -1, 1.5, '5', null, NaN]) {
      assert.throws(() => loadDetectorConfig(withField(f, bad)), DetectorConfigError, `${f}=${String(bad)}`);
    }
  }
});

test('unknown mode or empty version throws', () => {
  assert.throws(() => loadDetectorConfig(withField('mode', 'panic')), DetectorConfigError);
  assert.throws(() => loadDetectorConfig(withField('version', '')), DetectorConfigError);
  assert.equal(loadDetectorConfig(withField('mode', 'block_and_notify')).mode, 'block_and_notify');
});

test('non-object input throws', () => {
  assert.throws(() => loadDetectorConfig(null), DetectorConfigError);
  assert.throws(() => loadDetectorConfig([]), DetectorConfigError);
});
