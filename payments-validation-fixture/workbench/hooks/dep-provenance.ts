/*
 * Dependency provenance. Plan 3.5, satisfying FR-13.
 *
 * Also enforces NFR-9. This repository must run with no install, so any declared
 * dependency or devDependency is itself the finding.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { type Finding, type Result, ROOT } from '../lib.ts';

export function run(): Result {
  const pkg = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'));
  const findings: Finding[] = [];
  for (const field of ['dependencies', 'devDependencies'] as const) {
    for (const name of Object.keys(pkg[field] ?? {})) {
      findings.push({
        file: 'package.json',
        line: 1,
        summary: `${field}.${name} breaks NFR-9: the repository must run with no install`,
        severity: 'high',
      });
    }
  }
  return { findings };
}
