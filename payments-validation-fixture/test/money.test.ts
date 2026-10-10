import test from 'node:test';
import assert from 'node:assert/strict';
import { SCHEME_FEE_BPS, add, allocate, applyRate, minor, sub } from '../src/domain/money.ts';

test('minor rejects fractional, NaN, Infinity and unsafe values', () => {
  assert.throws(() => minor(1.5), RangeError);
  assert.throws(() => minor(NaN), RangeError);
  assert.throws(() => minor(Infinity), RangeError);
  assert.throws(() => minor(2 ** 60), RangeError);
  assert.equal(minor(Number.MAX_SAFE_INTEGER), Number.MAX_SAFE_INTEGER);
});

test('add and sub check the result is a safe integer', () => {
  assert.equal(add(minor(2), minor(3)), 5);
  assert.equal(sub(minor(2), minor(3)), -1);
  assert.throws(() => add(minor(Number.MAX_SAFE_INTEGER), minor(1)), RangeError);
});

test('allocate never creates or destroys money', () => {
  for (let amount = -500; amount <= 500; amount += 1) {
    for (let parts = 1; parts <= 13; parts += 1) {
      const split = allocate(minor(amount), parts);
      assert.equal(split.reduce((a, b) => a + b, 0), amount, `${amount} into ${parts}`);
      assert.equal(split.length, parts);
    }
  }
  assert.equal(allocate(minor(9999), 7).reduce((a, b) => a + b, 0), 9999);
});

test('allocate front-loads the remainder', () => {
  assert.deepEqual(allocate(minor(10000), 3), [3334, 3333, 3333]);
  assert.deepEqual(allocate(minor(-10000), 3), [-3334, -3333, -3333]);
});

test('allocate rejects invalid part counts', () => {
  assert.throws(() => allocate(minor(100), 0), RangeError);
  assert.throws(() => allocate(minor(100), 1.5), RangeError);
  assert.throws(() => allocate(minor(100), -2), RangeError);
  assert.throws(() => allocate(minor(100), NaN), RangeError);
});

test('applyRate rounds half up in basis points', () => {
  assert.equal(SCHEME_FEE_BPS, 149);
  assert.equal(applyRate(minor(6000), 149), 89);
  assert.equal(applyRate(minor(4000), 149), 60);
  assert.equal(applyRate(minor(10000), 149), 149);
});

test('applyRate rounds symmetrically about zero', () => {
  assert.equal(applyRate(minor(-6000), 149), -89);
  assert.equal(applyRate(minor(-4000), 149), -60);
});

test('applyRate rejects a non-integer rate', () => {
  assert.throws(() => applyRate(minor(1000), 0.0149), RangeError);
});

test('fee + net === amount and the fee is an integer', () => {
  for (let a = 0; a <= 20000; a += 1) {
    const fee = applyRate(minor(a), SCHEME_FEE_BPS);
    assert.ok(Number.isInteger(fee), `fee for ${a}`);
    assert.equal(fee + sub(minor(a), fee), a);
  }
});
