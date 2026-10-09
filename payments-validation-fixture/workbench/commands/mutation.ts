/*
 * Mutation testing. Plan 3.8, satisfying FR-15 and FR-16.
 *
 * Inject the defect, then ask whether the suite notices. A surviving mutant is positive
 * proof that the test cannot distinguish correct from broken, which is the only decisive
 * evidence about test strength.
 *
 * Changed files only, per FR-16. Mutating the whole tree would blow the 90-second budget
 * (NFR-1), and a workflow that cannot finish is a workflow nobody runs.
 *
 * Not every survivor is a defect. An equivalent mutant changes the source without
 * changing behaviour, so no test can kill it and fixing it is wasted work. Telling those
 * apart is the judgment this command exists to teach, per FR-17.
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { type Finding, type Result, ROOT, rel } from '../lib.ts';

type Mutator = { name: string; find: RegExp; replace: string };

const MUTATORS: Mutator[] = [
  { name: 'conditional-boundary', find: /([^<>=!])>=/g, replace: '$1>' },
  { name: 'conditional-boundary', find: /([^<>=!])<=/g, replace: '$1<' },
  { name: 'invert-negation', find: /!==/g, replace: '===' },
  { name: 'arithmetic', find: /([\w)\]]) \+ /g, replace: '$1 - ' },
  { name: 'return-true', find: /return sum % 10 === 0;/g, replace: 'return true;' },
];

const DEFAULT_TARGETS = ['src/domain/money.ts', 'src/domain/ledger.ts', 'src/payments/service.ts'];

const changedFiles = (base: string): string[] => {
  try {
    return execFileSync('git', ['diff', '--name-only', `${base}...HEAD`], {
      cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
    }).split('\n').filter(f => f.endsWith('.ts') && f.startsWith('src/'));
  } catch {
    return [];
  }
};

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

export function run(opts: { base?: string } = {}): Result {
  /*
   * A mutant is "killed" when the suite fails with it applied. If the suite already
   * fails without it, every mutant looks killed and the command reports a confident
   * zero. That is worse than useless, so refuse to run and say why.
   */
  if (!suitePasses()) {
    return { findings: [], skipped: 'suite is red before mutation, so survivors cannot be measured' };
  }

  const targets = changedFiles(opts.base ?? 'main');
  const files = targets.length > 0 ? targets : DEFAULT_TARGETS;
  const findings: Finding[] = [];

  for (const relPath of files) {
    const full = join(ROOT, relPath);
    let original: string;
    try {
      original = readFileSync(full, 'utf8');
    } catch {
      continue;
    }
    const lines = original.split('\n');

    for (const mutator of MUTATORS) {
      for (let i = 0; i < lines.length; i += 1) {
        const line = lines[i];
        if (line.trimStart().startsWith('*') || line.trimStart().startsWith('//')) continue;
        const mutated = line.replace(mutator.find, mutator.replace);
        if (mutated === line) continue;

        const copy = [...lines];
        copy[i] = mutated;
        writeFileSync(full, copy.join('\n'));
        const survived = suitePasses();
        writeFileSync(full, original);

        if (survived) {
          findings.push({
            file: relPath,
            line: i + 1,
            summary: `surviving mutant (${mutator.name}): the suite passes with this line changed`,
            severity: 'high',
          });
        }
      }
    }
  }
  return { findings };
}
