# Failure Autopsy & Prescriptive Retry

## Problem

When a SPEED task fails, the pipeline reports "Quality gates failed" and stops. An operator then spends 15 minutes reading the agent log, examining the worktree diff, comparing the implementation against the spec, and hand-writing a `--context` string for retry. The system already produces every artifact needed to do this automatically. It doesn't connect them.

Task 3 of `speed-security` is the canonical case. The agent hit the 50-turn limit with 504 lines of code staged (addressing 11 of 12 acceptance criteria). Gates never ran. The failure classifier returned `unclassified/unknown` because turn exhaustion without a timeout flag doesn't match any of the 6 existing rules. The operator saw "Quality gates failed" and had to discover the real cause manually. On retry, the worktree was deleted. The new agent rewrote everything from zero.

Three distinct problems compound here:

1. **Classification gap.** `failure_classify.py` has 6 rules covering context cuts, exploration death, decomposition errors, spec gaps, exceeded capacity, and implementation errors. Turn exhaustion (budget ran out, work exists) falls through all of them. The catch-all `unclassified/unknown` tells the operator nothing.

2. **No failure-to-retry feedback.** The diagnosis (when an operator manually performs one) doesn't flow into the retry. The operator hand-writes `--context "the issue was X, focus on Y"` and hopes the next agent picks it up. Nothing about the failed attempt's code, its partial progress, or the specific acceptance criteria it missed is structured or reusable.

3. **Salvageable work destroyed.** When a task fails, `cmd_retry` deletes the worktree. Task 3 had 504 lines addressing 11 of 12 criteria. All of it was thrown away. A defect spec (`specs/defects/turn-exhaustion-loses-complete-work.md`) already documents this pattern, and a tech spec (`specs/tech/fix-turn-exhaustion-loses-work.md`) provides the salvage mechanism. The autopsy agent depends on salvaged work being available.

## Users

### Operator (Engineering)

Runs `speed run` and manages the pipeline. Spends 15-30 minutes per failed task on manual diagnosis. Wants the system to handle routine failure recovery, escalating only when human judgment is genuinely needed.

### Spec Author (Product)

Writes specs with acceptance criteria that decompose into tasks. Already writes evaluation definitions (`[verify: test]`, `[verify: schema_check]`, etc.) as part of normal spec authoring. Wants confidence that these signals drive retry behavior, not just status display.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As an operator, I want failed tasks to produce a structured diagnosis automatically so I don't spend 15 minutes reading agent logs | Given a task that transitions to `failed`, when the autopsy agent runs, then a `diagnosis.json` is produced within 60 seconds containing root cause class, evidence, spec divergences, and salvageability flag | Must |
| S2 | As an operator, I want the diagnosis to distinguish turn exhaustion from gate failure from spec gaps so I know which intervention is needed | Given a task that hit the turn limit with staged code, when autopsy runs, then `root_cause` is `turn_exhaustion` (not `gate_failure` or `unclassified`) with evidence citing turn count, staged lines, and gate absence | Must |
| S3 | As an operator, I want `speed retry` to pre-populate context from the diagnosis so I don't hand-write `--context` strings | Given a failed task with `diagnosis.json`, when I run `speed retry --task-id N`, then the retry agent receives the diagnostic context automatically, and I can append with `--context` (additive, not replacing) | Must |
| S4 | As an operator, I want the retry turn budget adjusted when the previous attempt exhausted its budget | Given a task that failed with `turn_exhaustion`, when the retry executes, then the turn budget is 50% higher than the exhausted budget (e.g., 50 becomes 75) | Must |
| S5 | As an operator, I want salvageable code from failed attempts preserved as reference for retries | Given a failed task with staged or committed changes in the worktree, when the diagnosis flags `salvageable: true`, then the retry agent receives a reference to the salvaged code alongside the diagnostic context | Must |
| S6 | As an operator, I want the diagnosis to identify which acceptance criteria were addressed and which were missed so the retry agent can focus | Given a task with structured acceptance criteria, when autopsy compares the worktree diff against the criteria, then `diagnosis.json` lists `criteria_addressed` and `criteria_missed` with evidence | Should |
| S7 | As an operator, I want spec divergences surfaced when the implementation follows a local file convention instead of the spec requirement | Given a task where the implementation uses `LOGS_DIR` but the spec requires `STATE_DIR/features/<feature>/logs/`, when autopsy analyzes the diff against the spec, then the divergence appears in `spec_divergences` with the conflicting references | Should |

## User Flows

### Automatic diagnosis on failure

1. `speed run` executes task 3. The agent writes 504 lines but hits the 50-turn limit before committing.
2. Pipeline detects failure. Salvage mechanism commits the staged work (per `fix-turn-exhaustion-loses-work.md`).
3. Autopsy agent launches on the `failed` status transition.
4. Autopsy reads four artifacts: agent conversation log, worktree diff (now committed via salvage), task spec with acceptance criteria, and gate output directory.
5. Autopsy produces `diagnosis.json` stored alongside the task:
   - `root_cause`: `turn_exhaustion`
   - `evidence`: "Agent reached 50/50 turns. 504 lines salvaged. Gate output absent."
   - `criteria_addressed`: 11 of 12 appear satisfied
   - `criteria_missed`: ["Secrets scan log written to STATE_DIR path"]
   - `spec_divergences`: ["Implementation uses LOGS_DIR; spec requires STATE_DIR/features/<feature>/logs/"]
   - `salvageable`: true
   - `recommended_budget`: 75
6. Operator sees the diagnosis in `speed status` without reading any logs.

### Prescriptive retry

1. Operator runs `speed retry --task-id 3`.
2. Retry reads `diagnosis.json` and synthesizes context for the agent: root cause, which criteria to focus on, which spec divergences to fix, reference to salvaged code.
3. Turn budget is 75 (50% increase from exhausted 50).
4. Retry agent receives the synthesized context as part of its prompt. Completes in 23 turns.

### Retry with operator override

1. Task 5 fails. Autopsy produces `diagnosis.json` with `root_cause: spec_gap`.
2. Operator reads the diagnosis, realizes the spec needs a one-line clarification.
3. Operator edits the spec, then runs `speed retry --task-id 5 --context "Spec now clarifies empty input returns null"`.
4. Retry receives both the autopsy diagnosis and the operator's additional context. The `--context` flag appends to the autopsy context, not replacing it.

### No diagnosis possible

1. Task 7 fails. Autopsy reads the artifacts but cannot determine a root cause (agent log is truncated, no pattern matches).
2. `diagnosis.json` has `root_cause: undiagnosable` with whatever partial evidence was available.
3. `speed retry` still works but uses only the partial evidence. No budget adjustment (no signal to justify one).
4. Operator can add `--context` to supply what the autopsy couldn't determine.

## Success Criteria

- [ ] Every `failed` task produces `diagnosis.json` within 60 seconds of status transition
- [ ] `turn_exhaustion` is correctly distinguished from `gate_failure` when the agent hit the turn limit with staged work
- [ ] `diagnosis.json` contains: `root_cause`, `evidence`, `criteria_addressed`, `criteria_missed`, `spec_divergences`, `salvageable`, `recommended_budget`
- [ ] `speed retry --task-id N` reads `diagnosis.json` and injects diagnostic context into the retry agent's prompt
- [ ] Operator's `--context` flag appends to autopsy context (not replacing)
- [ ] Turn budget on retry is 50% higher when the previous attempt exhausted its budget
- [ ] Salvageable code (when flagged) is referenced in the retry context
- [ ] Autopsy agent is read-only: reads logs, diffs, specs, gate output; produces `diagnosis.json`; no file writes, no shell commands, no state modification beyond the diagnosis file
- [ ] `speed status` displays the diagnosis summary for failed tasks

## Scope

### In Scope

- Autopsy agent definition (`agents/autopsy.md`) with read-only access to task artifacts
- `turn_exhaustion` root cause class added to `failure_classify.py`
- Structured `diagnosis.json` output per failed task
- `speed retry` pre-population from diagnosis
- Turn budget adjustment on retry (50% increase when exhausted)
- Salvaged code reference in retry context (depends on `fix-turn-exhaustion-loses-work.md` being implemented)
- Criteria-level analysis comparing worktree diff against acceptance criteria
- Spec divergence detection comparing implementation paths against spec requirements
- Diagnosis summary in `speed status` output

### Out of Scope (and why)

| Exclusion | Reason |
|-----------|--------|
| Pattern memory across runs | Phase 2 of Adaptive Build Intelligence. Requires accumulating cases over multiple runs. The autopsy agent provides the structured data that pattern memory will later consume. |
| Convention clash detection at context assembly time | Phase 2. Requires comparing spec paths against target file conventions before the agent starts. Autopsy detects these post-hoc; prevention requires Layer 2 integration. |
| Adaptive turn budgets from task characteristics | Phase 3. Requires historical data from multiple runs. The 50% increase on retry is a simple heuristic; complexity-based prediction needs a data foundation. |
| Continuous auto-retry mode | Phase 3. Requires the autopsy and pattern memory to be reliable before automating the retry loop. |
| Cross-project transfer learning | Out of scope for all phases. Project-scoped memory first. |
| Automated spec rewriting | The spec is the source of truth. Only humans modify it. |

## Dependencies

| Dependency | What It Provides | Status |
|------------|-----------------|--------|
| Salvage mechanism (`fix-turn-exhaustion-loses-work.md`) | Commits staged work before gates run, so autopsy has code to analyze | Tech spec written, not implemented |
| Failure classification (`lib/failure_classify.py`) | 6-rule classifier that autopsy extends with `turn_exhaustion` | Built, in production |
| Criteria verification (`lib/criteria_verify.py`) | Per-criterion pass/fail/unverifiable with evidence | Built, in production |
| Task state machine (`lib/cmd/run.sh`) | Status transitions that trigger autopsy | Built, in production |
| Context assembly (`lib/context/assembly.py`) | Layer 3 formatting that retry context plugs into | Built, in production |

## Security & Controls

**Autopsy agent access.** Read-only. Reads agent logs, worktree diffs, task JSONs, spec sections, and gate output directories. Produces `diagnosis.json`. No file writes beyond the diagnosis, no shell commands, no state modification.

**Diagnosis content.** Contains file paths, line numbers, turn counts, and acceptance criteria text. No secrets, credentials, or user data. Stored locally in `.speed/features/<name>/tasks/<id>/diagnosis.json`.

**Retry context injection.** The autopsy-generated context is additive. The operator can override or supplement with `--context`. The system never modifies specs, task descriptions, or acceptance criteria based on autopsy output.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Autopsy misdiagnoses root cause, sending the retry agent in the wrong direction | Medium | Diagnosis includes evidence strings, not just labels. Operator sees evidence in `speed status` and can override with `--context`. Two failures with the same diagnosis should trigger manual review (continuous mode, Phase 3, enforces this). |
| Autopsy agent token cost on long agent logs (50+ turns of conversation) | Medium | Use `support_model` (sonnet) for autopsy. The task is structured reading and pattern matching, not creative reasoning. Log truncation to last 20 turns if log exceeds budget. |
| Criteria-level analysis produces false positives (claims criterion is "addressed" when it isn't) | Medium | Criteria analysis is advisory, feeding into retry context as hints. The retry agent still verifies against the actual acceptance criteria. False positives waste some retry focus but don't corrupt the output. |
| Dependency on salvage mechanism not yet implemented | Low | Autopsy can still analyze committed diffs and gate output without the salvage mechanism. Salvage increases the signal available (staged code that would otherwise be lost), but its absence degrades the diagnosis, not breaks it. |

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should the autopsy agent use `support_model` (sonnet) or `planning_model` (opus)? Diagnosis reads 50+ turn logs but the task is structured pattern matching. | Determines autopsy cost. Sonnet is 5-10x cheaper. Opus may catch subtle root causes sonnet misses. | Open |
| Q2 | How should salvaged code be presented to the retry agent? Full diff, function-level summary, or diff plus a natural-language completion summary? | Full diffs consume retry context budget. Summaries may lose critical detail. | Open |
| Q3 | Should autopsy run synchronously (blocking the pipeline) or asynchronously (diagnosis available for later retry)? | Synchronous adds 30-60s to failure handling. Async means the first manual `speed retry` might not have a diagnosis yet. | Open |
