/*
 * Scorer. Plan 5.3, satisfying FR-25 and FR-26.
 *
 * Compares a bundle against a round manifest on four axes. Recall is measured against
 * what the tooling could reach, so the reserved defect is excluded from the denominator.
 * Boundary calibration is measured separately, and it is the axis that fails a learner
 * who shipped over a live specification gap.
 *
 *   node workbench/score.ts <bundle.json> <manifest.json> [decisions.json]
 *
 * `decisions.json` is optional and holds the learner's evidence ledger:
 *   { "confirmed": ["R0-D1"], "refuted": ["R0-P1"], "escalated": ["R0-D5"], "invented": [] }
 */
import { existsSync, readFileSync } from 'node:fs';

const [bundlePath, manifestPath, decisionsPath] = process.argv.slice(2);
if (!bundlePath || !manifestPath) {
  console.error('usage: node workbench/score.ts <bundle.json> <manifest.json> [decisions.json]');
  process.exit(2);
}

const read = (p: string) => JSON.parse(readFileSync(p, 'utf8'));
const bundle = read(bundlePath);
const manifest = read(manifestPath);
/*
 * The decisions file is your evidence ledger. Without it the scorer can measure what the
 * workflow surfaced but nothing about your judgment, so every judgment axis reads as zero
 * and boundary calibration fails. Say that plainly rather than failing silently.
 */
let decisions = { confirmed: [], refuted: [], escalated: [], invented: [] };
if (decisionsPath && existsSync(decisionsPath)) {
  decisions = read(decisionsPath);
} else if (decisionsPath) {
  console.error(`no decisions file at ${decisionsPath}.`);
  console.error('Copy corpus/decisions.example.json to decisions.json and record what you');
  console.error('confirmed, refuted, escalated and invented. Scoring judgment without it');
  console.error('is not possible, so the axes below are measured against an empty ledger.\n');
} else {
  console.error('no decisions file given, so only recall and waste are meaningful.\n');
}

type Defect = { id: string; class: string; file: string; line: number; caughtBy: string | null; reserved: boolean; action: string };
const defects: Defect[] = manifest.defects;

/*
 * A defect counts as surfaced when the check the manifest names produced at least one
 * finding. Matching on file path as well would be stricter, but a check often reports at
 * its detection site rather than the defect site: differential reports against the golden
 * corpus, not against the line that changed.
 */
const surfaced = new Set<string>();
for (const check of bundle.checks) {
  if (!check.ran || check.findings.length === 0) continue;
  for (const d of defects) {
    if (d.caughtBy === check.id) surfaced.add(d.id);
  }
}

const findable = defects.filter(d => !d.reserved);
const reserved = defects.filter(d => d.reserved);

/* Waste: checks that ran but, by their own declaration, could not have found anything
 * live on this change. Running them is budget spent for no possible return. */
const liveClasses = new Set(defects.map(d => d.class));
const ranChecks = bundle.checks.filter((c: { ran: boolean }) => c.ran);
const wasted = ranChecks.filter((c: { covers: string[] }) => c.covers.length > 0 && !c.covers.some(k => liveClasses.has(k)));

const pathologyIds = new Set(manifest.pathologies.map((p: { id: string }) => p.id));
const falsePositivesAccepted = decisions.confirmed.filter((id: string) => pathologyIds.has(id)).length;
// Only a defect whose correct action is `confirm` can be wrongly dismissed. A defect
// the manifest says to refute is a pathology wearing a defect id, and refuting it is right.
const truePositivesDismissed = decisions.refuted.filter((id: string) =>
  findable.some(d => d.id === id && d.action === 'confirm'),
).length;

const report = {
  round: manifest.round,
  recall: {
    found: surfaced.size,
    findable: findable.length,
    ratio: findable.length === 0 ? 1 : Number((surfaced.size / findable.length).toFixed(2)),
    missed: findable.filter(d => !surfaced.has(d.id)).map(d => `${d.id} (${d.class})`),
  },
  waste: {
    checksRun: ranChecks.length,
    couldNotHaveFound: wasted.length,
    which: wasted.map((c: { id: string }) => c.id),
  },
  misjudgment: {
    falsePositivesAccepted,
    truePositivesDismissed,
    overclaims: decisions.invented.length,
  },
  boundary: {
    reservedEscalated: reserved.every(d => decisions.escalated.includes(d.id)),
    reserved: reserved.map(d => `${d.id} (${d.class})`),
    inventedDefects: decisions.invented.length,
  },
};

console.log(JSON.stringify(report, null, 2));

// A learner who shipped over a live reserved defect fails, whatever their recall was.
if (reserved.length > 0 && !report.boundary.reservedEscalated) {
  console.error('\nboundary calibration failed: the reserved defect was not escalated');
  process.exit(1);
}
