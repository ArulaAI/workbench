/*
 * Readiness report. Plan 7.1, satisfying FR-27.
 *
 * The course tells learners to run this before the lab, so it has to answer one question
 * honestly: if I start a workflow now, what will actually run?
 *
 * An unavailable skill is survivable. A workflow runs without a coding agent and reports
 * silence, which is a true statement about what was examined. An unavailable hook is not
 * survivable, because a hook that cannot run is a class nobody looked at, and the whole
 * point of the exercise is not to mistake those for each other.
 */

import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { checks } from './checks.ts';
import { ROOT } from './lib.ts';

type State = 'ready' | 'misconfigured' | 'unavailable';
type Row = { id: string; kind: string; state: State; detail: string };

const rows: Row[] = [];

/* Environment first. A missing git is not obvious from a check failing on its own. */
const env: Row[] = [];
const nodeMajor = Number(process.versions.node.split('.')[0]);
env.push({
  id: 'node',
  kind: 'runtime',
  state: nodeMajor >= 22 ? 'ready' : 'unavailable',
  detail: nodeMajor >= 22
    ? `v${process.versions.node}, native type stripping available`
    : `v${process.versions.node}. Node 22 or later is required, per NFR-4`,
});

let gitOk = false;
try {
  execFileSync('git', ['rev-parse', '--git-dir'], { cwd: ROOT, stdio: 'ignore' });
  gitOk = true;
} catch {
  gitOk = false;
}
env.push({
  id: 'git',
  kind: 'runtime',
  state: gitOk ? 'ready' : 'misconfigured',
  detail: gitOk
    ? 'available, so scope-guard and mutation can diff against a base'
    : 'not available. scope-guard and mutation fall back to defaults and examine less',
});

const agent = process.env.WORKBENCH_AGENT;
env.push({
  id: 'coding agent',
  kind: 'runtime',
  state: agent ? 'ready' : 'unavailable',
  detail: agent
    ? `WORKBENCH_AGENT=${agent}`
    : 'WORKBENCH_AGENT is not set, so every skill will report silence',
});

for (const check of checks) {
  if (check.kind === 'skill') {
    const contract = join(ROOT, 'workbench', 'skills', `${check.id}.md`);
    if (!existsSync(contract)) {
      rows.push({ id: check.id, kind: check.kind, state: 'misconfigured', detail: 'no contract in workbench/skills/' });
    } else if (!agent) {
      rows.push({ id: check.id, kind: check.kind, state: 'unavailable', detail: 'contract present, no coding agent configured' });
    } else {
      rows.push({ id: check.id, kind: check.kind, state: 'ready', detail: 'contract present, agent configured' });
    }
    continue;
  }

  if (!check.module) {
    rows.push({ id: check.id, kind: check.kind, state: 'misconfigured', detail: 'declares no module' });
    continue;
  }
  const path = join(ROOT, 'workbench', check.module);
  if (!existsSync(path)) {
    rows.push({ id: check.id, kind: check.kind, state: 'unavailable', detail: `${check.module} does not exist` });
    continue;
  }
  try {
    const mod = await import(path);
    if (typeof mod.run !== 'function') {
      rows.push({ id: check.id, kind: check.kind, state: 'misconfigured', detail: `${check.module} exports no run()` });
    } else {
      rows.push({ id: check.id, kind: check.kind, state: 'ready', detail: check.summary });
    }
  } catch (error) {
    rows.push({
      id: check.id,
      kind: check.kind,
      state: 'misconfigured',
      detail: `failed to load: ${(error as Error).message.split('\n')[0]}`,
    });
  }
}

const mark = { ready: 'ok  ', misconfigured: 'BAD ', unavailable: '--  ' } as const;
const pad = (s: string, n: number) => s.padEnd(n);

console.log('\nenvironment');
for (const r of env) console.log(`  ${mark[r.state]} ${pad(r.id, 22)} ${r.detail}`);

for (const kind of ['hook', 'command', 'skill'] as const) {
  console.log(`\n${kind}s`);
  for (const r of rows.filter(r => r.kind === kind)) {
    console.log(`  ${mark[r.state]} ${pad(r.id, 22)} ${r.detail}`);
  }
}

const blocking = rows.filter(r => r.kind !== 'skill' && r.state !== 'ready');
const skillsOut = rows.filter(r => r.kind === 'skill' && r.state !== 'ready');
const envBad = env.filter(r => r.state === 'misconfigured' || (r.id === 'node' && r.state !== 'ready'));

console.log('');
if (blocking.length > 0) {
  console.error(`not ready. ${blocking.length} hook or command is not usable: ${blocking.map(r => r.id).join(', ')}`);
  console.error('Resolve these before the lab. A check that cannot run is a class nobody examined.');
  process.exit(1);
}
if (envBad.length > 0) {
  console.error(`ready, with a degraded environment: ${envBad.map(r => r.id).join(', ')}`);
  process.exit(1);
}
console.log(`ready. ${rows.length - skillsOut.length} of ${rows.length} checks are usable.`);
if (skillsOut.length > 0) {
  console.log(`${skillsOut.length} skill${skillsOut.length === 1 ? '' : 's'} will report silence: ${skillsOut.map(r => r.id).join(', ')}.`);
  console.log('That is survivable. The bundle will say so, and those classes appear in notExamined.');
}
