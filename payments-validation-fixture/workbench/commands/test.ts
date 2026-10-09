/*
 * The suite as written. Plan 3.7, satisfying FR-15. Covers nothing on its own.
 *
 * Pin the TAP reporter. Node's default reporter prints "✖ name", not "not ok N - name",
 * so parsing the default output finds nothing and a red suite reports clean. That bug
 * shipped here once and hid every failing test behind a green row, which is the exact
 * thing this repository exists to teach people to distrust.
 */
import { execFileSync } from 'node:child_process';
import { type Result, ROOT } from '../lib.ts';

export function run(): Result {
  try {
    execFileSync(process.execPath, ['--test', '--test-reporter=tap', 'test/**/*.test.ts'], {
      cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
    });
    return { findings: [] };
  } catch (error) {
    const out = String((error as { stdout?: string }).stdout ?? '');
    const failures = [...out.matchAll(/^\s*not ok \d+ - (.+?)\s*$/gm)].map(m => m[1]);
    if (failures.length === 0) {
      // The suite failed but nothing parsed. Report that rather than a clean row.
      return { findings: [{ file: 'test/', line: 1, summary: 'the suite failed and no failing test name could be parsed', severity: 'high' as const }] };
    }
    return {
      findings: failures.map(name => ({
        file: 'test/', line: 1, summary: `failing test: ${name}`, severity: 'high' as const,
      })),
    };
  }
}
