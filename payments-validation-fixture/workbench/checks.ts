/*
 * Every check declared once. Plan 1.1, satisfying FR-11, FR-18 and NFR-8.
 *
 * Vocabulary: a hook fires on an event, a command is run deliberately by the engineer,
 * and a skill is invoked by the coding agent. There is no generic noun for all three
 * beyond "check". Do not reintroduce the generic noun this repository banned in NFR-8.
 *
 * `covers` is load-bearing. The runner subtracts the union of covered classes across
 * checks that actually ran from the eight classes to produce `notExamined` (FR-21).
 * Declaring a class here that a check cannot really decide would hide a gap, which is
 * the exact failure the course exists to prevent.
 */

import type { ClassId } from '../corpus/classes.ts';

export type Kind = 'hook' | 'command' | 'skill';

export type Evidence =
  | 'counterexample'
  | 'proof'
  | 'statistical'
  | 'corroborated'
  | 'opinion'
  | 'silence';

export type Check = {
  id: string;
  kind: Kind;
  covers: ClassId[];
  /** The evidence type a clean or dirty result from this check constitutes. */
  evidence: Evidence;
  summary: string;
  /** Module under workbench/ that exports `run`. Skills have no runner here. */
  module?: string;
};

export const checks: Check[] = [
  // Hooks. Offline, no account, fast. FR-12, FR-13.
  {
    id: 'typecheck',
    kind: 'hook',
    covers: ['F1'],
    evidence: 'proof',
    summary: 'The named surface exists and resolves.',
    module: 'hooks/typecheck.ts',
  },
  {
    id: 'dep-provenance',
    kind: 'hook',
    covers: ['F1'],
    evidence: 'proof',
    summary: 'Every package exists, matches the lockfile and is not newly introduced.',
    module: 'hooks/dep-provenance.ts',
  },
  {
    id: 'pan-scan',
    kind: 'hook',
    covers: ['F2'],
    evidence: 'proof',
    summary: 'Luhn-valid card numbers outside the allowlist, anywhere in the tree.',
    module: 'hooks/pan-scan.ts',
  },
  {
    id: 'secret-scan',
    kind: 'hook',
    covers: ['F2'],
    evidence: 'proof',
    summary: 'Keys, tokens and high-entropy strings.',
    module: 'hooks/secret-scan.ts',
  },
  {
    id: 'taint',
    kind: 'hook',
    covers: ['F2'],
    evidence: 'proof',
    summary: 'A PAN-typed value reaching a log, webhook, telemetry or serialisation sink.',
    module: 'hooks/taint.ts',
  },
  {
    id: 'scope-guard',
    kind: 'hook',
    covers: ['F6'],
    evidence: 'proof',
    summary: 'Files touched outside the allowed-paths manifest for this change.',
    module: 'hooks/scope-guard.ts',
  },

  // Commands. The engineer runs them. FR-15.
  {
    id: 'test',
    kind: 'command',
    covers: [],
    evidence: 'statistical',
    summary: 'The suite as written. Covers nothing on its own, because the suite may be weak.',
    module: 'commands/test.ts',
  },
  {
    id: 'invariant',
    kind: 'command',
    covers: ['F4'],
    evidence: 'counterexample',
    summary: 'The four named invariants after a fixed scenario.',
    module: 'commands/invariant.ts',
  },
  {
    id: 'property',
    kind: 'command',
    covers: ['F4'],
    evidence: 'statistical',
    summary: 'Invariants after N generated operation sequences, including retries.',
    module: 'commands/property.ts',
  },
  {
    id: 'mutation',
    kind: 'command',
    covers: ['F3'],
    evidence: 'counterexample',
    summary: 'A surviving mutant proves the suite cannot see that defect.',
    module: 'commands/mutation.ts',
  },
  {
    id: 'differential',
    kind: 'command',
    covers: ['F7'],
    evidence: 'statistical',
    summary: 'Replay a golden corpus and diff the responses and the ledger.',
    module: 'commands/differential.ts',
  },

  // Skills. The coding agent invokes them. FR-18.
  // No module: a workflow runs without an agent, and these report silence when absent.
  {
    id: 'zero-context-review',
    kind: 'skill',
    covers: ['F5'],
    evidence: 'opinion',
    summary: 'Fresh session given the diff and the requirement only, never the transcript.',
  },
  {
    id: 'red-team',
    kind: 'skill',
    covers: ['F5'],
    evidence: 'opinion',
    summary: 'Prompted to break the change rather than to assess it.',
  },
  {
    id: 'intent-conformance',
    kind: 'skill',
    covers: ['F6'],
    evidence: 'opinion',
    summary: 'Behaviour present in code but absent from the stated requirement.',
  },
  {
    id: 'requirements-coverage',
    kind: 'skill',
    covers: [],
    evidence: 'silence',
    summary:
      'Narrows the surface a human must read for F8. It covers nothing, because it decides nothing.',
  },
];

export const checkById = new Map(checks.map(c => [c.id, c]));

/*
 * F8 appears in no `covers` array anywhere above, and that is deliberate (G5, FR-6).
 * requirements-coverage points at it but declares `covers: []`, because narrowing a
 * surface is not deciding a class. Any change that adds 'F8' to a covers array is
 * claiming the tooling can settle a specification gap, which it cannot.
 */
