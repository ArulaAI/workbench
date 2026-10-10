import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { TEST_CARDS } from './fixtures/cards.ts';
import { ALLOWLIST, run, scanFiles, scanHistory, scanText } from '../workbench/hooks/pan-scan.ts';
import { luhn } from '../workbench/lib.ts';

const HOOK = new URL('../workbench/hooks/pan-scan.ts', import.meta.url).pathname;

// Built at runtime so no non-test Luhn-valid literal sits in this file.
const completeLuhn = (body: string): string => {
  for (let c = 0; c < 10; c += 1) if (luhn(body + c)) return body + c;
  throw new Error('unreachable');
};
const REAL_LOOKING = completeLuhn('453201511283036');

const cli = (args: string[]) => {
  try {
    execFileSync('node', [HOOK, ...args], { stdio: 'pipe' });
    return 0;
  } catch (e) {
    return (e as { status: number }).status;
  }
};

const withFile = (content: string, fn: (path: string) => void) => {
  const dir = mkdtempSync(join(tmpdir(), 'pan-scan-'));
  const path = join(dir, 'sample.txt');
  writeFileSync(path, content);
  try { fn(path); } finally { rmSync(dir, { recursive: true }); }
};

test('allowlist covers every card in test/fixtures/cards.ts and is Luhn-valid', () => {
  for (const pan of Object.values(TEST_CARDS)) assert.ok(ALLOWLIST.includes(pan), pan);
  for (const pan of ALLOWLIST) assert.ok(luhn(pan), `${pan} is not Luhn-valid`);
});

test('the current repository passes', () => {
  assert.deepEqual(run().findings, []);
  assert.equal(cli([]), 0);
});

test('a Luhn-valid non-test number fails, with separators too', () => {
  assert.equal(scanText(`card ${REAL_LOOKING}`, 'f').length, 1);
  const spaced = REAL_LOOKING.replace(/(\d{4})(?=\d)/g, '$1 ');
  assert.equal(scanText(spaced, 'f').length, 1);
  const dashed = REAL_LOOKING.replace(/(\d{4})(?=\d)/g, '$1-');
  assert.equal(scanText(dashed, 'f').length, 1);
  withFile(`pan=${REAL_LOOKING}\n`, path => assert.equal(cli([path]), 1));
});

test('allowlisted test numbers and 13-digit timestamps pass', () => {
  const stamps = [1700000000000, 1700000000001, 1700000000002, 1700000000003, 1700000000004]
    .map(String).concat(String(Date.now()));
  const content = [...Object.values(TEST_CARDS), ...stamps].join('\n');
  assert.deepEqual(scanText(content, 'f'), []);
  withFile(content, path => assert.equal(cli([path]), 0));
});

test('every 13-digit timestamp in a range passes regardless of Luhn', () => {
  for (let t = 1700000000000; t < 1700000000200; t += 1) {
    assert.deepEqual(scanText(String(t), 'f'), [], String(t));
  }
});

test('an allowlisted BIN does not suppress a different number', () => {
  assert.equal(scanText(completeLuhn('411111222233334'), 'f').length, 1);
});

test('--history scans git log -p output', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pan-scan-git-'));
  const git = (...a: string[]) => execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@example.com', ...a], { cwd: dir, stdio: 'pipe' });
  try {
    git('init', '-q');
    writeFileSync(join(dir, 'a.txt'), `${REAL_LOOKING}\n`);
    git('add', '.');
    git('commit', '-q', '-m', 'add');
    writeFileSync(join(dir, 'a.txt'), 'clean\n');
    git('commit', '-qam', 'remove');
    // The working tree is clean, so only history still holds the removed number.
    assert.equal(scanFiles([join(dir, 'a.txt')]).length, 0);
    assert.ok(scanHistory(dir).length >= 1);
  } finally {
    rmSync(dir, { recursive: true });
  }
});
