/*
 * Diff-scope guard. Plan 3.4, satisfying FR-13. Home for F6.
 *
 * The allowed-paths manifest comes from the plan for the change. Files touched outside it
 * fail mechanically, before any reasoning runs. That ordering matters: it is Rule 2, and
 * it is why a scope violation costs milliseconds rather than an agent call.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { type Finding, type Result, ROOT } from '../lib.ts';

const MANIFEST = join(ROOT, 'workbench', 'allowed-paths.json');

const changedFiles = (base: string): string[] => {
  try {
    const out = execFileSync('git', ['diff', '--name-only', `${base}...HEAD`], {
      cwd: ROOT,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    return out.split('\n').filter(Boolean);
  } catch {
    return [];
  }
};

export function run(opts: { base?: string } = {}): Result {
  if (!existsSync(MANIFEST)) {
    return { findings: [], skipped: 'no workbench/allowed-paths.json for this change' };
  }
  const allowed: string[] = JSON.parse(readFileSync(MANIFEST, 'utf8')).allowed;
  const files = changedFiles(opts.base ?? 'main');
  if (files.length === 0) {
    return { findings: [], skipped: 'no diff against base, nothing to scope' };
  }
  const findings: Finding[] = files
    .filter(f => !allowed.some(a => f === a || f.startsWith(a.replace(/\*$/, ''))))
    .map(f => ({
      file: f,
      line: 1,
      summary: `touched outside the allowed-paths manifest for this change`,
      severity: 'medium' as const,
    }));
  return { findings };
}
