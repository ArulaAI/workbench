import test from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_THRESHOLDS, DecisionPolicy, loadThresholds, validateThresholds } from '../src/risk/policy.ts';
import type { ScoreResult } from '../src/risk/types.ts';

const policy = new DecisionPolicy(DEFAULT_THRESHOLDS);
const res = (score: number): ScoreResult => ({ score, reasons: ['time_of_day'], modelVersion: 'm1' });

test('default thresholds map scores to outcomes', () => {
  const cases: [number, string][] = [
    [0, 'approve'], [299, 'approve'], [300, 'step_up'], [699, 'step_up'],
    [700, 'hold'], [849, 'hold'], [850, 'decline'], [1000, 'decline'],
  ];
  for (const [score, outcome] of cases) assert.equal(policy.decide(res(score)).outcome, outcome, String(score));
});

test('scorer error holds and flags scorerFailed', () => {
  const d = policy.decide({ error: new Error('boom') });
  assert.equal(d.outcome, 'hold');
  assert.equal(d.scorerFailed, true);
  assert.deepEqual(d.reasons, []);
});

test('out-of-range or fractional scores hold, never approve', () => {
  for (const score of [1001, 12.5, -1, NaN]) {
    const d = policy.decide(res(score));
    assert.equal(d.outcome, 'hold');
    assert.equal(d.scorerFailed, true);
  }
});

test('every decision carries thresholdsVersion', () => {
  for (const r of [res(10), res(500), res(800), res(900), { error: 1 }, res(5000)]) {
    assert.equal(policy.decide(r).thresholdsVersion, 'arch-0.7-defaults');
  }
});

test('validateThresholds rejects bad configuration', () => {
  const ok = { ...DEFAULT_THRESHOLDS };
  assert.deepEqual(validateThresholds(ok), ok);
  assert.throws(() => validateThresholds({ ...ok, holdFrom: 200 }), /stepUpFrom <= holdFrom/);
  assert.throws(() => validateThresholds({ ...ok, declineFrom: 1001 }), /1000/);
  assert.throws(() => validateThresholds({ ...ok, stepUpFrom: 300.5 }), /integer/);
  assert.throws(() => validateThresholds({ ...ok, version: '' }), /version/);
  assert.throws(() => validateThresholds(null), /object/);
});

test('loadThresholds reads the shipped config', () => {
  assert.equal(loadThresholds('config/risk-thresholds.json').version, 'arch-0.7-defaults');
  assert.equal(loadThresholds().version, 'arch-0.7-defaults');
});

test('loadThresholds throws on a missing file', () => {
  assert.throws(() => loadThresholds('config/does-not-exist.json'), /cannot read/);
});
