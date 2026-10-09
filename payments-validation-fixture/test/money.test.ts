import test from 'node:test';
import assert from 'node:assert/strict';
import { allocate, applyRate, minor } from '../src/domain/money.ts';

test('allocate never creates or destroys money', () => {
  for (const amount of [1, 7, 100, 1000, 9999, 123457]) {
    for (const parts of [1, 2, 3, 7, 11]) {
      const split = allocate(minor(amount), parts);
      assert.equal(split.reduce((a, b) => a + b, 0), amount, `${amount} into ${parts}`);
      assert.equal(split.length, parts);
    }
  }
});

test('allocate front-loads the remainder', () => {
  assert.deepEqual(allocate(minor(1000), 3), [334, 333, 333]);
});

test('applyRate rounds symmetrically about zero', () => {
  assert.equal(applyRate(minor(1000), 0.0149), 15);
  assert.equal(applyRate(minor(-1000), 0.0149), -15);
});

test('money rejects fractional minor units', () => {
  assert.throws(() => minor(1.5), RangeError);
});
