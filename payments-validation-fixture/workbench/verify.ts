/*
 * Self-check. Plan 6.3, satisfying NFR-7, NFR-11, CR-8 and FR-17.
 *
 * Asserts the rules this repository makes about itself, so they fail loudly rather than
 * rotting. Everything here is a rule that a future change could break silently.
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { checks } from './checks.ts';
import { allClassIds, contract } from '../corpus/classes.ts';
import { ROOT, sourceFiles, rel } from './lib.ts';

const failures: string[] = [];
const check = (ok: boolean, message: string) => { if (!ok) failures.push(message); };

// NFR-11: the repository must run with no install.
const pkg = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'));
check(!pkg.dependencies, 'NFR-9: package.json declares dependencies');
check(!pkg.devDependencies, 'NFR-9: package.json declares devDependencies');

/*
 * NFR-8 vocabulary and NFR-7 style.
 *
 * Built from character codes rather than written out, because this file would otherwise
 * match its own rules. specs/ is exempt: it quotes the course and the client brief.
 */
/*
 * Conformance to the course contract. The course is the standard, so every rule in this
 * block is read from corpus/course-contract.json rather than written here.
 *
 * Exempt from the vocabulary scan: specs/, which quotes the course and the client
 * verbatim; this file, which necessarily names the words it bans; and the contract
 * itself, which defines them.
 */
const EXEMPT = new Set(['workbench/verify.ts', 'corpus/course-contract.json']);
const EM_DASH = String.fromCharCode(0x2014);

for (const file of sourceFiles()) {
  const path = rel(file);
  if (path.startsWith('docs/') || path.startsWith('.validation/') || EXEMPT.has(path)) continue;
  const text = readFileSync(file, 'utf8');
  for (const word of contract.vocabulary.banned) {
    if (new RegExp(`\\b${word}s?\\b`, 'i').test(text)) {
      failures.push(`vocabulary: the course bans "${word}", found in ${path}`);
    }
  }
  if (text.includes(EM_DASH)) failures.push(`NFR-7: em-dash in ${path}`);
}

// The composed artifact must be named what the course calls it.
const baseline = join(ROOT, 'corpus', 'workflow.baseline.yaml');
check(existsSync(baseline), 'corpus/workflow.baseline.yaml is missing, so `workbench plan` has nothing to write from');

// Kinds and evidence types come from the course, not from here.
const contractKinds = Object.keys(contract.vocabulary.kinds).sort();
const usedKinds = [...new Set(checks.map(c => c.kind))].sort();
check(
  usedKinds.every(k => contractKinds.includes(k)),
  `check kinds ${usedKinds.join(',')} are not all in the course contract (${contractKinds.join(',')})`,
);
const contractEvidence = new Set(contract.evidenceTypes.map(e => e.key));
for (const c of checks) {
  check(contractEvidence.has(c.evidence), `${c.id} uses evidence type "${c.evidence}", which the course does not define`);
}

/*
 * Every class the course teaches must have somewhere to be met. A class with no seeded
 * defect is the course claiming coverage the fixture cannot back.
 */
const seeded = new Set<string>();
for (const dir of readdirSync(join(ROOT, 'corpus')).filter(d => d.startsWith('round-'))) {
  const mf = join(ROOT, 'corpus', dir, 'manifest.json');
  if (!existsSync(mf)) continue;
  for (const d of JSON.parse(readFileSync(mf, 'utf8')).defects) seeded.add(d.class);
}
const unseeded = contract.failureClasses.filter(c => !seeded.has(c.id)).map(c => c.id);
if (unseeded.length > 0) {
  failures.push(`the course teaches ${unseeded.join(', ')} but no round seeds a defect for them`);
}

// FR-11 and FR-21: every check declares a kind and covers only real classes.
for (const c of checks) {
  check(['hook', 'command', 'skill'].includes(c.kind), `FR-11: ${c.id} has an unknown kind`);
  for (const cls of c.covers) {
    check(allClassIds.includes(cls), `FR-21: ${c.id} covers unknown class ${cls}`);
  }
}

// G5 and FR-6: F8 must remain uncovered. This is the guarantee the course rests on.
const coversF8 = checks.filter(c => (c.covers as string[]).includes('F8'));
check(coversF8.length === 0, `G5: F8 is claimed as covered by ${coversF8.map(c => c.id).join(', ')}`);

// FR-19: every check named in the workflow exists, and every check is in the workflow.
const chainText = readFileSync(baseline, 'utf8');
const named = [...chainText.matchAll(/^\s{2}- ([\w-]+)\s*$/gm)].map(m => m[1]);
for (const c of checks) check(named.includes(c.id), `FR-19: ${c.id} is declared but absent from workflow.yaml`);

// CR-8: every manifest validates against the schema.
const schema = JSON.parse(readFileSync(join(ROOT, 'corpus', 'manifest.schema.json'), 'utf8'));
const rounds = readdirSync(join(ROOT, 'corpus')).filter(d => d.startsWith('round-'));
for (const dir of rounds) {
  const path = join(ROOT, 'corpus', dir, 'manifest.json');
  if (!existsSync(path)) { failures.push(`CR-1: ${dir} has no manifest.json`); continue; }
  const manifest = JSON.parse(readFileSync(path, 'utf8'));
  for (const key of schema.required) {
    check(key in manifest, `CR-8: ${dir}/manifest.json is missing "${key}"`);
  }
  // The manifest claimed 212 lines against a 54-line diff. Measure it.
  if (typeof manifest.diffLines === 'number') {
    try {
      const stat = execFileSync('git', ['diff', '--numstat', `${manifest.base}...${dir.replace('round-', 'round-')}`], {
        cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
      });
      const actual = stat.trim().split('\n').filter(Boolean)
        .reduce((n, line) => { const [a, d] = line.split('\t'); return n + (Number(a) || 0) + (Number(d) || 0); }, 0);
      if (actual > 0) check(actual === manifest.diffLines, `${dir} claims diffLines ${manifest.diffLines}, the diff is ${actual}`);
    } catch { /* branch not present in this checkout */ }
  }

  // CR-3: exactly one reserved defect.
  const reserved = manifest.defects.filter((d: { reserved: boolean }) => d.reserved);
  check(reserved.length === 1, `CR-3: ${dir} has ${reserved.length} reserved defects, expected exactly 1`);
  // CR-4: at least one pathology.
  check(manifest.pathologies.length >= 1, `CR-4: ${dir} declares no evidence pathology`);
  // A reserved defect must not claim a check can catch it.
  for (const d of reserved) {
    check((d as { caughtBy: string | null }).caughtBy === null, `CR-3: reserved defect in ${dir} names a catching check`);
  }
}

/*
 * The learner's requirement, specs/product/payments.md, must stay silent on refund
 * idempotency. That silence is F8 and it is the whole of Course 5.
 *
 * FR-6 in our build spec asks a human to remember this. A human remembering is the
 * weakest guard there is, so check it.
 */
const productSpec = readFileSync(join(ROOT, 'specs', 'product', 'payments.md'), 'utf8');
/*
 * Scan the whole document rather than a named section. The previous version sliced from a
 * "## Retries" heading, and when the spec was restructured that heading went away, so the
 * slice was empty and the check passed without examining anything. Green because nothing
 * looked, in the repository that exists to teach people to catch exactly that.
 */
const decidesRefundRepeats = productSpec
  .split(/(?<=[.!?])\s+|\n/)
  .some(sentence => /refund/i.test(sentence) && /idempoten|repeated|duplicate|retried|twice|same request/i.test(sentence));
check(
  !decidesRefundRepeats,
  'specs/product/payments.md now decides what a repeated refund request means. That closes the F8 gap Course 5 depends on',
);

/*
 * Every command the README tells a learner to run must exist. A README that names a
 * script nobody kept is the same failure as markup naming a CSS class nobody kept: the
 * tests pass, and the first person to follow the instructions hits a wall.
 */
const readme = readFileSync(join(ROOT, 'README.md'), 'utf8');
const scripts = Object.keys(pkg.scripts ?? {});
for (const m of readme.matchAll(/npm run ([a-z][a-z0-9:-]*)/g)) {
  check(scripts.includes(m[1]), `README tells the learner to run "npm run ${m[1]}", which is not a script`);
}
for (const m of readme.matchAll(/node (workbench\/[a-z-]+\.ts)/g)) {
  check(existsSync(join(ROOT, m[1])), `README references ${m[1]}, which does not exist`);
}

if (failures.length > 0) {
  console.error(`verify: ${failures.length} failure${failures.length === 1 ? '' : 's'}`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log(`verify: ok. ${checks.length} checks, ${rounds.length} round${rounds.length === 1 ? '' : 's'}, no required dependencies.`);
