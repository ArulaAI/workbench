/*
 * Bundle diff. Plan 7.2, satisfying FR-28 and FR-29.
 *
 * Produces the Chapter 6 artifact, the re-validation delta. You commissioned a repair,
 * you ran the workflow again, and now you have two bundles. The question is what the repair
 * actually changed.
 *
 *   node workbench/diff.ts <before.json> <after.json>
 *
 * The category that matters is `newly silent`. A check that stopped running has no
 * findings, exactly like a check that started passing. On any summary that counts
 * findings they are the same number, and the difference is everything: one means the
 * defect is gone, the other means nobody looked. A repair that deletes a test, breaks a
 * hook or blows the budget reads as an improvement unless you separate them.
 */

import { readFileSync } from 'node:fs';

const [beforePath, afterPath] = process.argv.slice(2);
if (!beforePath || !afterPath) {
  console.error('usage: node workbench/diff.ts <before.json> <after.json>');
  process.exit(2);
}

type Finding = { file: string; line: number; summary: string };
type Check = { id: string; kind: string; ran: boolean; reason?: string; evidence: string; findings: Finding[] };
type Bundle = { checks: Check[]; notExamined: { class: string; reason: string }[]; budget: { withinBudget: boolean; spentMs: number } };

const read = (p: string): Bundle => JSON.parse(readFileSync(p, 'utf8'));
const before = read(beforePath);
const after = read(afterPath);

const byId = (b: Bundle) => new Map(b.checks.map(c => [c.id, c]));
const b0 = byId(before);
const b1 = byId(after);

const key = (f: Finding) => `${f.file}:${f.line}:${f.summary}`;

const newlyClean: string[] = [];
const newlyFailing: { id: string; findings: Finding[] }[] = [];
const newlySilent: { id: string; reason: string }[] = [];
const stillFailing: { id: string; findings: Finding[] }[] = [];
const unchanged: string[] = [];

for (const id of new Set([...b0.keys(), ...b1.keys()])) {
  const a = b0.get(id);
  const b = b1.get(id);

  if (!b) { newlySilent.push({ id, reason: 'absent from the second bundle entirely' }); continue; }
  if (!a) { newlyFailing.push({ id, findings: b.findings }); continue; }

  // FR-29. Check this before comparing findings, because a check that stopped running
  // has zero findings and would otherwise be counted as a fix.
  if (a.ran && !b.ran) { newlySilent.push({ id, reason: b.reason ?? 'stopped running' }); continue; }

  if (!a.ran && !b.ran) { unchanged.push(id); continue; }

  const was = new Set(a.findings.map(key));
  const now = new Set(b.findings.map(key));
  const gone = [...was].filter(k => !now.has(k));
  const fresh = b.findings.filter(f => !was.has(key(f)));

  if (fresh.length > 0) newlyFailing.push({ id, findings: fresh });
  else if (gone.length > 0 && now.size === 0) newlyClean.push(id);
  else if (gone.length > 0) stillFailing.push({ id, findings: b.findings });
  else unchanged.push(id);
}

const classes = (b: Bundle) => new Set(b.notExamined.map(n => n.class));
const before0 = classes(before);
const after0 = classes(after);
const nowExamined = [...before0].filter(c => !after0.has(c));
const nowUnexamined = [...after0].filter(c => !before0.has(c));

const pad = (s: string, n: number) => s.padEnd(n);
console.log('\nre-validation delta\n');
console.log(`  newly clean     ${newlyClean.length}`);
for (const id of newlyClean) console.log(`    ${id}`);
console.log(`  newly failing   ${newlyFailing.length}`);
for (const n of newlyFailing) {
  console.log(`    ${n.id}`);
  for (const f of n.findings) console.log(`      ${f.file}:${f.line}  ${f.summary}`);
}
console.log(`  newly silent    ${newlySilent.length}`);
for (const n of newlySilent) console.log(`    ${pad(n.id, 22)} ${n.reason}`);
console.log(`  still failing   ${stillFailing.length}`);
for (const n of stillFailing) console.log(`    ${n.id}`);
console.log(`  unchanged       ${unchanged.length}`);

console.log('\n  classes');
if (nowExamined.length > 0) console.log(`    now examined      ${nowExamined.join(', ')}`);
if (nowUnexamined.length > 0) console.log(`    now unexamined    ${nowUnexamined.join(', ')}`);
if (nowExamined.length === 0 && nowUnexamined.length === 0) console.log('    no change in what was examined');

console.log(`\n  budget            ${before.budget.spentMs} ms then ${after.budget.spentMs} ms`);

/*
 * Newly silent is the failure mode this command exists to catch, so it is the one that
 * changes the exit code. Newly failing is loud on its own.
 */
if (newlySilent.length > 0) {
  console.error(`\n${newlySilent.length} check${newlySilent.length === 1 ? '' : 's'} stopped running. That is not a fix. Establish why before accepting the repair.`);
  process.exit(1);
}
if (newlyFailing.length > 0) {
  console.error('\nthe repair introduced findings that were not there before.');
  process.exit(1);
}
console.log('');
