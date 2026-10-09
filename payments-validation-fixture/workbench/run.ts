/*
 * The workflow runner. Plan 4.2 to 4.4, satisfying FR-20 to FR-24 and NFR-1.
 *
 * The whole point of this file is the negative space. Findings are the easy half. What
 * makes a bundle honest is that it names every class nothing examined, and it computes
 * that itself rather than believing a declaration.
 *
 * Usage:
 *   node workbench/run.ts                 run the whole workflow
 *   node workbench/run.ts --only=hook     hooks only
 *   node workbench/run.ts --check=mutation one named check
 *   node workbench/run.ts --config=.validation/workflow.yaml use a drafted workflow
 *   node workbench/run.ts --base=main     diff base for scope-guard and mutation
 *   node workbench/run.ts --no-gates      keep going past a failing gate
 *
 * On --no-gates. A gate exists so that agent time is not spent on a tree that does not
 * compile or that leaks a PAN. The cost is that one finding at a gate blinds everything
 * downstream, and a false positive at a gate blinds it for no reason. That tradeoff is
 * the substance of composing a workflow, so the flag exists and the default does not use it.
 */

import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { allClassIds, contract, failureClasses } from '../corpus/classes.ts';
import { type Check, type Evidence, checks } from './checks.ts';
import { type Result, ROOT } from './lib.ts';

type CheckReport = {
  id: string;
  kind: Check['kind'];
  ran: boolean;
  reason?: string;
  durationMs: number;
  evidence: Evidence;
  covers: string[];
  findings: Result['findings'];
};

type Bundle = {
  workflow: string;
  round: number | null;
  startedAt: string;
  durationMs: number;
  budget: { limitMs: number; spentMs: number; withinBudget: boolean };
  checks: CheckReport[];
  notExamined: { class: string; reason: string }[];
};

const arg = (name: string, fallback: string): string =>
  process.argv.find(a => a.startsWith(`--${name}=`))?.split('=')[1] ?? fallback;

/*
 * A three-line YAML reader for the two keys we need. Bringing in a YAML parser would
 * breach NFR-9, and the workflow file is ours, so its shape is known.
 */
const readChain = (path: string): { budgetMs: number; order: string[]; gates: string[] } => {
  const text = readFileSync(resolve(ROOT, path), 'utf8');
  const list = (key: string): string[] => {
    const lines = text.split('\n');
    const start = lines.findIndex(l => l.trim() === `${key}:`);
    if (start === -1) return [];
    const out: string[] = [];
    for (const line of lines.slice(start + 1)) {
      const m = line.match(/^\s{2}- ([\w-]+)\s*$/);
      if (m) out.push(m[1]);
      else if (/^\S/.test(line)) break;
    }
    return out;
  };
  const budget = Number(text.match(/^budgetMs:\s*(\d+)/m)?.[1] ?? 90_000);
  return { budgetMs: budget, order: list('order'), gates: list('gates') };
};

const runCheck = async (check: Check, base: string): Promise<Result> => {
  if (!check.module) {
    // A skill with no runner. FR-18: a workflow runs without a coding agent.
    return { findings: [], skipped: 'no coding agent configured for this skill' };
  }
  const mod = await import(join(ROOT, 'workbench', check.module));
  return await mod.run({ base });
};

const main = async (): Promise<void> => {
  /*
   * The learner's workflow, once `workbench plan` has written one. Before that, fall back
   * to the baseline this repository ships, so a fresh clone can validate immediately.
   */
  const preferred = arg('config', contract.paths.workflow);
  const config = existsSync(join(ROOT, preferred)) ? preferred : 'corpus/workflow.baseline.yaml';
  const workflow = readChain(config);
  const only = arg('only', '');
  const selected = arg('check', '');
  const base = arg('base', 'main');
  const startedAt = new Date().toISOString();
  const t0 = Date.now();

  const reports: CheckReport[] = [];
  let gateFailed: string | null = null;

  for (const id of workflow.order) {
    const check = checks.find(c => c.id === id);
    if (!check) throw new Error(`workflow.yaml names an unknown check: ${id}`);

    if (selected && check.id !== selected) {
      reports.push({ ...base_(check), ran: false, reason: `filtered out by --check=${selected}`, durationMs: 0, evidence: 'silence', findings: [] });
      continue;
    }
    // FR-24: a check that did not run still appears, with evidence `silence`.
    if (only && check.kind !== only) {
      reports.push({ ...base_(check), ran: false, reason: `filtered out by --only=${only}`, durationMs: 0, evidence: 'silence', findings: [] });
      continue;
    }
    if (gateFailed && !process.argv.includes('--no-gates')) {
      reports.push({ ...base_(check), ran: false, reason: `workflow stopped at failing gate ${gateFailed}`, durationMs: 0, evidence: 'silence', findings: [] });
      continue;
    }

    const started = Date.now();
    let result: Result;
    try {
      result = await runCheck(check, base);
    } catch (error) {
      result = { findings: [], skipped: `check threw: ${(error as Error).message.split('\n')[0]}` };
    }
    const durationMs = Date.now() - started;

    const ran = result.skipped === undefined;
    reports.push({
      ...base_(check),
      ran,
      reason: result.skipped,
      durationMs,
      evidence: ran ? check.evidence : 'silence',
      findings: result.findings,
    });

    if (ran && workflow.gates.includes(check.id) && result.findings.length > 0) {
      gateFailed = check.id;
    }
  }

  if (selected && !checks.some(check => check.id === selected)) {
    console.error(`unknown check: ${selected}`);
    process.exit(2);
  }

  /*
   * FR-21. Subtract the classes covered by checks that actually ran from all eight.
   * This is computed, never supplied. A check that was skipped covers nothing, which is
   * why a workflow full of unconfigured skills produces a long notExamined list rather than
   * a short green one.
   */
  const examined = new Set(reports.filter(r => r.ran).flatMap(r => r.covers));
  const notExamined = allClassIds
    .filter(id => !examined.has(id))
    .map(id => {
      const cls = failureClasses.find(c => c.id === id)!;
      return {
        class: id,
        reason: cls.humanReserved
          ? `No check covers ${id}. It is human-reserved by design.`
          : `No check in this workflow examined ${id} on this run.`,
      };
    });

  const spentMs = Date.now() - t0;
  const bundle: Bundle = {
    workflow: config,
    round: Number(arg('round', '')) || null,
    startedAt,
    durationMs: spentMs,
    budget: { limitMs: workflow.budgetMs, spentMs, withinBudget: spentMs <= workflow.budgetMs },
    checks: reports,
    notExamined,
  };

  // FR-22. Refusing to emit is the only way this guarantee is worth anything.
  if (!Array.isArray(bundle.notExamined)) {
    console.error('refusing to emit a bundle with no notExamined array');
    process.exit(2);
  }

  const out = join(ROOT, 'bundles', `${startedAt.replace(/[:.]/g, '-')}.json`);
  writeFileSync(out, `${JSON.stringify(bundle, null, 2)}\n`);

  report(bundle, out);
  process.exit(bundle.checks.some(c => c.ran && c.findings.length > 0) ? 1 : 0);
};

const base_ = (check: Check) => ({
  id: check.id,
  kind: check.kind,
  covers: check.covers as string[],
});

const report = (bundle: Bundle, out: string): void => {
  const pad = (s: string, n: number) => s.padEnd(n);
  console.log(`\nchain: ${bundle.workflow}   ${bundle.durationMs} ms of ${bundle.budget.limitMs} ms budget\n`);
  for (const c of bundle.checks) {
    const state = c.ran
      ? c.findings.length > 0
        ? `${c.findings.length} finding${c.findings.length === 1 ? '' : 's'}`
        : 'clean'
      : 'not run';
    console.log(`  ${pad(c.kind, 8)} ${pad(c.id, 22)} ${pad(state, 12)} ${pad(c.evidence, 15)} ${c.reason ?? ''}`);
    for (const f of c.findings) console.log(`           ${f.file}:${f.line}  ${f.summary}`);
  }
  console.log('\n  classes not examined');
  for (const n of bundle.notExamined) console.log(`    ${n.class}  ${n.reason}`);
  if (bundle.notExamined.length === 0) console.log('    none, which should be impossible while F8 exists');
  if (!bundle.budget.withinBudget) console.log(`\n  OVER BUDGET by ${bundle.budget.spentMs - bundle.budget.limitMs} ms`);
  console.log(`\n  bundle: ${out.replace(ROOT, '.')}\n`);
};

await main();
