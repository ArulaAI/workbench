/*
 * Mechanical signals in a change.
 *
 * Everything here is an observation. Nothing here is a verdict.
 *
 * `workbench diagnose` fills the signal column of the risk surface from these, and leaves
 * plausible and costOfMissing blank. That split is the course's own thesis applied to its
 * own tooling: the machine supplies evidence, the person supplies judgment.
 *
 * Do not add a rule that marks a class plausible. A learner who is handed a verdict
 * accepts the verdict, which is the failure Course 1 exists to prevent.
 */

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { ClassId } from '../corpus/classes.ts';
import { ROOT } from './lib.ts';

export type Signal = { text: string; where: string[] };

export type ChangeFacts = {
  base: string;
  files: string[];
  added: string[];
  linesChanged: number;
  signals: Partial<Record<ClassId, Signal[]>>;
};

const diffNames = (base: string, filter?: string): string[] => {
  const args = ['diff', '--name-only', ...(filter ? [`--diff-filter=${filter}`] : []), `${base}...HEAD`];
  try {
    return execFileSync('git', args, { cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] })
      .split('\n').filter(Boolean);
  } catch {
    return [];
  }
};

const addedLines = (base: string): string[] => {
  try {
    return execFileSync('git', ['diff', '-U0', `${base}...HEAD`], {
      cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
    }).split('\n').filter(l => l.startsWith('+') && !l.startsWith('+++'));
  } catch {
    return [];
  }
};

/** Files whose added lines match a pattern, reported as file:line where possible. */
const locate = (base: string, files: string[], pattern: RegExp): string[] => {
  const hits: string[] = [];
  for (const file of files) {
    const full = join(ROOT, file);
    if (!existsSync(full)) continue;
    readFileSync(full, 'utf8').split('\n').forEach((line, i) => {
      if (pattern.test(line)) hits.push(`${file}:${i + 1}`);
    });
  }
  return hits;
};

export function collect(base = 'main'): ChangeFacts {
  const files = diffNames(base);
  const added = diffNames(base, 'A');
  const plus = addedLines(base);
  const source = files.filter(f => f.startsWith('src/'));
  const tests = files.filter(f => f.startsWith('test/'));
  const linesChanged = (() => {
    try {
      return execFileSync('git', ['diff', '--numstat', `${base}...HEAD`], {
        cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
      }).trim().split('\n').filter(Boolean)
        .reduce((n, l) => { const [a, d] = l.split('\t'); return n + (Number(a) || 0) + (Number(d) || 0); }, 0);
    } catch { return 0; }
  })();

  const signals: Partial<Record<ClassId, Signal[]>> = {};
  const add = (id: ClassId, text: string, where: string[] = []) => {
    (signals[id] ??= []).push({ text, where });
  };

  // F1. New imports and new modules are where an invented surface would appear.
  const newImports = plus.filter(l => /^\+\s*import\b/.test(l)).length;
  if (added.length > 0 || newImports > 0) {
    add('F1', `${added.length} new file(s) and ${newImports} new import statement(s)`, added);
  }

  // F2. Observability sinks and card-shaped literals in the added lines.
  const sinkHits = locate(base, source, /\b(log\.(debug|info|error|warn)|webhook|span|serialiseFailure|console\.(log|error))\s*\(/);
  if (sinkHits.length > 0) add('F2', `${sinkHits.length} observability sink call(s) in the files this change touched, not all of them new`, sinkHits);
  const cardish = locate(base, files, /\b(?:\d[ -]?){12,18}\d\b/);
  if (cardish.length > 0) add('F2', `${cardish.length} long digit sequence(s) in the files this change touched, not all of them new`, cardish);
  if (plus.some(l => /redact|sanitis|mask/i.test(l))) add('F2', 'a redaction or masking call appears in the added lines');

  // F3. Tests that arrived with the change.
  if (tests.length > 0) {
    const newTests = added.filter(f => f.startsWith('test/'));
    add('F3', `${tests.length} test file(s) touched, ${newTests.length} of them new`, tests);
  }

  // F4. Retry and money-movement vocabulary.
  const retryHits = plus.filter(l => /\b(retry|retries|attempt|idempot|reissue)\b/i.test(l)).length;
  if (retryHits > 0) add('F4', `${retryHits} added line(s) mention retry or idempotency`);
  const moneyFiles = source.filter(f => /money|ledger|payment|refund|capture/i.test(f));
  if (moneyFiles.length > 0) add('F4', `${moneyFiles.length} money path file(s) changed`, moneyFiles);

  // F5. Provenance, read from the round manifest rather than guessed.
  for (const dir of ['round-0']) {
    const mf = join(ROOT, 'corpus', dir, 'manifest.json');
    if (!existsSync(mf)) continue;
    const prov = JSON.parse(readFileSync(mf, 'utf8')).provenance;
    if (prov?.author) {
      add('F5', `change author recorded as "${prov.author}"${prov.transcript ? '' : ', no authoring transcript available'}`);
    }
  }

  // F6. Size and spread, which is what scope creep looks like before you read anything.
  // Directory of each file, so a two-segment path counts as its folder rather than itself.
  const dirs = new Set(files.map(f => f.split('/').slice(0, -1).join('/') || '.'));
  add('F6', `${files.length} file(s), ${linesChanged} line(s), across ${dirs.size} area(s)`, [...dirs]);

  // F7. Changed source with no corresponding test change is where a silent regression hides.
  const untested = source.filter(f => {
    const stem = f.split('/').pop()!.replace(/\.ts$/, '');
    return !tests.some(t => t.includes(stem));
  });
  if (untested.length > 0) add('F7', `${untested.length} changed source file(s) with no matching test change`, untested);

  // F8. Vocabulary in the change that the product spec may not cover.
  const spec = join(ROOT, 'specs', 'product', 'payments.md');
  if (existsSync(spec)) {
    const specText = readFileSync(spec, 'utf8').toLowerCase();
    const introduced = [...new Set(
      plus.flatMap(l => l.match(/\b(reissue|retry|retries|idempotency|chargeback|reversal)\b/gi) ?? []),
    )].map(w => w.toLowerCase());
    const absent = introduced.filter(w => !specText.includes(w));
    if (absent.length > 0) {
      add('F8', `term(s) in the change that the product spec never uses: ${absent.join(', ')}`);
    }
  }

  return { base, files, added, linesChanged, signals };
}
