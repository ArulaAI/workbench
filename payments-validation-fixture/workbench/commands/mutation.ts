/*
 * Mutation testing. Plan 3.8, satisfying FR-15 and FR-16.
 *
 * Inject the defect, then ask whether the suite notices. A surviving mutant is positive
 * proof that the test cannot distinguish correct from broken, which is the only decisive
 * evidence about test strength.
 *
 * Targeted mutants only, per FR-16. Mutating the whole tree would blow the 90-second budget
 * (NFR-1), and a workflow that cannot finish is a workflow nobody runs.
 *
 * Not every survivor is a defect. An equivalent mutant changes the source without
 * changing behaviour, so no test can kill it and fixing it is wasted work. Telling those
 * apart is the judgment this command exists to teach, per FR-17.
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { type Finding, type Result, ROOT } from '../lib.ts';

type Mutant = { name: string; file: string; find: string; replace: string };

/*
 * Each mutant targets one behaviour the plan names: applyRate rounding, allocate
 * remainder distribution, the capture-over-remaining check and the refund-over-refundable
 * check. Every one must be killed by the suite.
 */
const MUTANTS: Mutant[] = [
  { name: 'applyRate rounds down instead of half up', file: 'src/domain/money.ts',
    find: 'Math.abs(amount) * rateBps * 2 + BPS_DENOMINATOR;', replace: 'Math.abs(amount) * rateBps * 2;' },
  { name: 'applyRate rounds up instead of half up', file: 'src/domain/money.ts',
    find: 'Math.abs(amount) * rateBps * 2 + BPS_DENOMINATOR;', replace: 'Math.abs(amount) * rateBps * 2 + 2 * BPS_DENOMINATOR - 1;' },
  { name: 'allocate gives the remainder to one extra part', file: 'src/domain/money.ts',
    find: 'i < remainder ? 1 : 0', replace: 'i <= remainder ? 1 : 0' },
  { name: 'allocate gives the remainder to the trailing parts', file: 'src/domain/money.ts',
    find: 'i < remainder ? 1 : 0', replace: 'i >= parts - remainder ? 1 : 0' },
  { name: 'capture rejects the full remaining amount', file: 'src/payments/service.ts',
    find: 'if (requested > remaining) {', replace: 'if (requested >= remaining) {' },
  { name: 'capture over-remaining check removed', file: 'src/payments/service.ts',
    find: 'if (requested > remaining) {', replace: 'if (false) {' },
  { name: 'refund rejects the full refundable amount', file: 'src/payments/service.ts',
    find: 'if (requested > refundable) {', replace: 'if (requested >= refundable) {' },
  { name: 'refund over-refundable check removed', file: 'src/payments/service.ts',
    find: 'if (requested > refundable) {', replace: 'if (false) {' },
];

const suitePasses = (): boolean => {
  try {
    execFileSync(process.execPath, ['--test', 'test/**/*.test.ts'], {
      cwd: ROOT, stdio: 'ignore',
    });
    return true;
  } catch {
    return false;
  }
};

export function run(): Result {
  /*
   * A mutant is "killed" when the suite fails with it applied. If the suite already
   * fails without it, every mutant looks killed and the command reports a confident
   * zero. That is worse than useless, so refuse to run and say why.
   */
  if (!suitePasses()) {
    return { findings: [], skipped: 'suite is red before mutation, so survivors cannot be measured' };
  }

  const findings: Finding[] = [];
  for (const mutant of MUTANTS) {
    const full = join(ROOT, mutant.file);
    const original = readFileSync(full, 'utf8');
    const index = original.indexOf(mutant.find);
    if (index < 0 || original.indexOf(mutant.find, index + 1) >= 0) {
      findings.push({
        file: mutant.file,
        line: 1,
        summary: `mutant "${mutant.name}" does not apply: expected exactly one match for ${mutant.find}`,
        severity: 'high',
      });
      continue;
    }
    const line = original.slice(0, index).split('\n').length;
    try {
      writeFileSync(full, original.replace(mutant.find, () => mutant.replace));
      if (suitePasses()) {
        findings.push({
          file: mutant.file,
          line,
          summary: `surviving mutant (${mutant.name}): the suite passes with this line changed`,
          severity: 'high',
        });
      }
    } finally {
      writeFileSync(full, original);
    }
  }
  return { findings };
}
