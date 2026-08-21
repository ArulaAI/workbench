# Observation Infrastructure

> See [speed-continuous-learning.md](../../working-docs/speed-continuous-learning.md) for system design.
> Depends on: Existing SPEED pipeline (`speed integrate`, task JSON, review JSON, guardian logs, `lib/context/layer2.py`)

## Problem

SPEED runs features, produces code, ships it, and forgets everything. The fifth feature run on the same codebase starts from zero — the same context, the same blind spots, the same mistakes. Task 3 retried twice because the Developer missed a template update? That information exists in the task JSON, but nobody reads it. The Reviewer flagged missing isinstance checks three times across three features? Each finding lives in a separate review log, never connected. The Guardian false-flagged `__init__.py` touches in every feature? The pattern is invisible because no system looks across runs. The verify step caught spec drift on the same API pattern twice, but each finding evaporated after integration. The coherence checker flagged an interface mismatch that recurred three features later because nobody recorded it. The security auditor found the same hardcoded-timeout pattern in two consecutive features.

SPEED's pipeline produces structured artifacts at every stage: task outcomes, review findings, guardian verdicts, verify reports, coherence reports, security audits, context packages, git diffs. These artifacts contain the raw material for learning — what worked, what broke, what the human changed. Per-feature artifacts persist in `.speed/features/<name>/` until the directory is manually removed. Verify and coherence reports in `.speed/logs/` are overwritten on every run, surviving only until the next `speed verify` or `speed coherence` invocation.

Observation Infrastructure is the data collection layer. It reads pipeline artifacts after each feature run, converts them into typed observations, and stores them in an append-only log. No prompt changes, no agent modifications, no behavior differences. Collection only. Every downstream learning capability (convention discovery, synthesis, context tuning, human correction capture) depends on this data existing.

**Principle grounding:** P3 (failure memory first) — extraction prioritizes retry and failure observations because they carry the most learning signal. P1 (scaffolding not exploration) — observations capture what the pipeline's structured stages already produce (verify drift, coherence mismatches, security findings), converting existing artifacts into reusable knowledge rather than exploring for new signals. P4 (human corrections are ground truth) — guardian overrides and human-approved verdicts are recorded with higher weight than automated findings. P7 (additive, never blocking) — the pipeline runs identically with or without the observation infrastructure. A crash in extraction never affects integration.

## Users

### Engineering (Operator)
Runs the full pipeline: `speed plan`, `speed verify`, `speed run`, `speed review`, `speed coherence`, `speed security`, `speed integrate`. Wants to understand patterns across feature runs without manually reading task JSON, review logs, verify reports, coherence reports, and security audits. After 5 features, wants to know: "which areas cause the most retries? What does the Reviewer keep flagging? Where does the Guardian over-react? Which spec patterns drift? What interface mismatches recur? Which security categories keep surfacing?" Structured observations make these questions answerable.

### Learning System (Internal Consumer)
The synthesis engine, convention discovery, and context tuning layers consume observations to produce agent-specific learnings. Without structured observations, these systems have nothing to work with. Observation quality determines learning quality.

### Developer Agent (Indirect Beneficiary)
Does not interact with observations directly. Benefits when downstream systems use observations to produce better conventions, better context packages, and better guidance. The Developer on feature 10 writes better code because observations from features 1-9 fed the learning pipeline.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| O1 | As an operator, I want pipeline observations extracted automatically after integration so that learning data accumulates without manual effort | Given a completed `speed integrate`, when the post-integrate step runs, then observations are extracted from all task JSON, review JSON, guardian logs, verify report, coherence report, security audit, and code-context JSON files and written to `.speed/memory/observations/<feature>.jsonl` | Must |
| O2 | As an operator, I want each observation typed and structured so that downstream systems can filter by type without parsing free text | Given an observation, then it has a deterministic ID, a typed `observation_type` (one of: retry, reviewer_finding, human_override, guardian_verdict, gate_failure, context_miss, context_waste, decomposition_miss, convention_violation, verify_finding, coherence_issue, security_finding, success, pattern_match), and a structured `detail` object with type-specific fields | Must |
| O3 | As an operator, I want extraction to be idempotent so that re-running after a crash or interruption produces no duplicates | Given `speed learn` has already run for a feature, when I run it again, then no new observations are added (IDs are deterministic: feature + task_id + stage + observation_type + content_hash) | Must |
| O4 | As an operator, I want task timing data captured so that task sizing calibration has duration evidence | Given a task that completed, then the observation includes `duration_seconds` (wall-clock from start to completion including retries) | Must |
| O5 | As an operator, I want success observations recorded alongside failures so that the system learns what works, not just what breaks | Given a task that passed all gates on first attempt with no Guardian flags and no context misses, then a `success` observation is recorded with conditions (file count, context tier, area) | Must |
| O6 | As an operator, I want context effectiveness tracked per task so that the context tuning layer knows which files helped and which were waste | Given a task with a code-context JSON and a git diff, when extraction runs, then `context_miss` observations are produced for files modified but not in the context package, and `context_waste` observations for files in the package but never referenced in the diff | Must |
| O7 | As an operator, I want decomposition quality measured per task so that the Architect gets feedback on task boundaries | Given a task where files_touched differs from files_declared in the task plan, then a `decomposition_miss` observation is produced with planned vs. actual file lists and analysis | Must |
| O8 | As an operator, I want review findings categorized so that synthesis can group them by type | Given a review finding in free-form text, when extraction processes it, then it is classified into one of: convention, correctness, scope, testing, style, performance (using a small model for post-hoc classification until the Reviewer tags findings at generation time) | Must |
| O9 | As an operator, I want cross-feature pattern detection so that recurring issues are flagged immediately | Given 3+ observations of the same pattern across features (e.g., "retry on tasks touching lib/toml.py due to missing template update"), then a `pattern_match` observation is appended with occurrences and frequency | Should |
| O10 | As an operator, I want extraction to handle missing and malformed artifacts gracefully so that partial data doesn't crash the system | Given a missing review JSON (task passed without review), when extraction runs, then step 2 is skipped for that task and a note is added to the success observation. Given malformed task JSON, then the task is skipped entirely with an error log | Must |
| O11 | As an operator, I want `speed learn` as a standalone command so that I can trigger extraction manually and inspect results | Given a completed feature, when I run `speed learn -f <feature>`, then extraction runs and prints a summary: N observations extracted (X retries, Y findings, Z context issues) | Must |
| O12 | As an operator, I want unattributed changes on the feature branch flagged rather than silently ignored | Given manual commits on the feature branch that don't correspond to any task, then an `unattributed_changes` observation is produced listing the files and commit SHAs | Should |
| O13 | As an operator, I want verify findings extracted so that recurring spec drift patterns become visible across features | Given a plan-verification.log with `critical_failures` or `spec_requirements` marked as `drifted` or `missing`, then `verify_finding` observations are produced for each, with the requirement text, spec location, and drift analysis | Must |
| O14 | As an operator, I want coherence issues extracted so that recurring cross-task integration problems surface | Given a coherence.log with `interface_mismatches`, `schema_inconsistencies`, or `missing_connections`, then `coherence_issue` observations are produced for each, with involved tasks, locations, and severity | Must |
| O15 | As an operator, I want security findings extracted so that recurring vulnerability patterns inform the Developer and Reviewer | Given a security-audit.json with `findings`, then `security_finding` observations are produced for each finding, with severity, category, file, line, and recommendation | Must |

## User Flows

### Post-integrate extraction (happy path)

1. Operator runs `speed integrate` on feature "speed-security" with 5 tasks
2. Integration succeeds, feature branch is merged
3. Post-integrate step triggers `speed learn` automatically
4. Extraction reads task JSON files: tasks 1, 2, 4, 5 passed first attempt; task 3 has retry_count=2
5. Step 1 produces 5 task outcome observations (4 successes, 1 retry with 2 sub-observations)
6. Step 2 reads review JSON files, finds 3 findings across tasks. Classifies each (convention, correctness, testing)
7. Step 3 reads guardian logs. Task 4 was flagged for undeclared `__init__.py` touch, human overrode
8. Step 4 reads plan-verification.log. One requirement flagged as "drifted" (header format changed post-spec)
9. Step 5 reads coherence.log. One interface mismatch between tasks 2 and 4
10. Step 6 reads security-audit.json. One medium-severity finding (hardcoded timeout)
11. Step 7 compares code-context JSON against git diff. Task 2 modified a file not in its context package. Task 5 had a file included but never referenced
12. Step 8 compares planned vs. actual file lists. Task 3 touched 5 files instead of planned 3
13. Step 9 records success observations for tasks 1, 2, 4, 5 with conditions
14. Step 10 checks previous observations — finds "missing template update" pattern matches 2 prior features. Flags as recurring
15. All observations written to `.speed/memory/observations/speed-security.jsonl`
16. Summary printed: "12 observations extracted (1 retry pattern, 3 review findings, 1 guardian override, 1 context miss, 1 context waste, 1 decomposition miss, 4 successes, 1 pattern match)"

### Re-running extraction after crash

1. Extraction crashed after writing 7 of 12 observations
2. Operator runs `speed learn -f speed-security` again
3. Extraction re-processes all artifacts, generates 12 observations with deterministic IDs
4. 7 IDs already exist in the JSONL file — skipped
5. 5 new observations are appended
6. Final file contains exactly 12 observations, no duplicates

### Extraction with missing artifacts

1. Feature ran with SKIP_GUARDIAN on task 2 (no guardian log)
2. Task 4's review JSON is missing (task was approved without review)
3. Extraction processes what's available:
   - Task 2: guardian step records `verdict: skipped`
   - Task 4: review step is skipped, success observation notes "no review"
4. No crash, no partial observations, clear log of what was skipped and why

### Manual inspection

1. Operator runs `speed learn -f speed-security` after integration
2. Operator runs `speed learn --summary` to see aggregate stats across all features
3. Output: "4 features observed. 47 total observations. Top patterns: missing template update (3 features), isinstance guard missing (2 features)"
4. Operator reads `.speed/memory/observations/speed-security.jsonl` directly for raw data

## Success Criteria

- [ ] `speed learn` extracts observations from all task JSON, review JSON, guardian log, verify report, coherence report, security audit, and code-context JSON files for a completed feature
- [ ] Each observation has a deterministic ID derived from feature + task_id + stage + observation_type + content_hash
- [ ] Re-running `speed learn` on the same feature produces no duplicate observations
- [ ] Task outcomes include retry_count, duration_seconds, files_touched, files_declared, model used
- [ ] Review findings are classified into categories (convention, correctness, scope, testing, style, performance) using post-hoc LLM classification
- [ ] Guardian verdicts capture flagged/cleared/skipped/human-overridden status
- [ ] Verify findings are extracted from plan-verification.log, producing verify_finding observations for drifted/missing requirements and critical failures
- [ ] Coherence issues are extracted from coherence.log, producing coherence_issue observations for interface mismatches, schema inconsistencies, and missing connections
- [ ] Security findings are extracted from security-audit.json, producing security_finding observations for each finding with severity, category, file, and line
- [ ] Context effectiveness compares code-context JSON against git diff per task, producing context_miss and context_waste observations
- [ ] Decomposition quality compares planned vs. actual files per task, producing decomposition_miss observations
- [ ] Success observations record clean-pass conditions (file count, context tiers, codebase area)
- [ ] Cross-feature pattern matching flags observations that recur in 3+ features
- [ ] Missing artifacts are handled gracefully (skip the step, log the absence, never crash)
- [ ] Malformed artifacts are skipped entirely with an error log (no partial observations)
- [ ] Unattributed commits on the feature branch produce flagged observations
- [ ] `speed learn -f <feature>` runs extraction and prints a summary
- [ ] `speed learn` runs automatically as part of `speed integrate`
- [ ] Extraction never blocks integration — a crash in `speed learn` logs an error but does not fail `speed integrate`
- [ ] `.speed/memory/observations/` directory is created on first run
- [ ] Observation JSONL files are append-only (never modified, never deleted by the system)

## Scope

### In Scope
- `speed learn` CLI command (`cmd_learn()` in `speed/speed`)
- Observation data model (typed observations with deterministic IDs)
- Ten-step extraction pipeline (task outcomes → review findings → guardian verdicts → verify findings → coherence issues → security findings → context effectiveness → decomposition quality → success observations → pattern matching)
- Success observation recording
- Cross-feature pattern matching
- Review finding classification (post-hoc LLM call)
- Timing data capture
- Idempotency via content-hash IDs
- Graceful handling of missing/malformed artifacts
- `.speed/memory/` directory structure creation
- Integration into `speed integrate` as a post-step
- `speed learn --summary` for aggregate stats

### Out of Scope (and why)
- **Synthesis of observations into agent-specific learnings** — Separate feature (speed-synthesis). Observation Infrastructure collects raw data; synthesis interprets it. Coupling them would delay data collection while synthesis design stabilizes.
- **Convention discovery from codebase analysis** — Separate feature (speed-conventions). Convention Discovery uses observations as one input among several (AST, git history, CSG). The extraction format defined here is the interface contract.
- **Human correction capture (post-merge diffs)** — Separate feature (speed-human-corrections). Requires a different trigger (post-merge, not post-integrate) and a different data source (PR diffs, not pipeline artifacts).
- **Prompt injection of observations** — Observations are raw data, too granular for prompts. Synthesis produces the prompt-ready format. No agent reads observations directly.
- **Observation visualization or dashboard** — `speed learn --summary` provides text-based aggregate stats. A graphical dashboard is a separate concern that can be built on top of the JSONL files.
- **Automated remediation based on observations** — Observations inform, they don't act. The system records "missing template update caused retry" but doesn't auto-fix future template omissions. That's the synthesis → injection pathway.

## Dependencies

- **`speed integrate`** — Extraction runs post-integrate. The integration step must complete before observations can be extracted. Integration provides the feature directory with all pipeline artifacts.
- **Pipeline artifact format** — Task JSON (`task-*.json`), review JSON (`review-*.json`), guardian logs (`guardian-*.log`), verify report (`plan-verification.log`), coherence report (`coherence.log`), security audit (`security-audit.json`), code-context JSON (`code-context-*.json`). Extraction depends on these file formats being stable. Changes to artifact format require extraction updates.
- **`lib/provider.sh`** — Review finding classification uses a small model via `claude_run()`. Provider infrastructure must be available for the post-hoc classification step.
- **Git history** — Context effectiveness and decomposition quality use `git diff` and `git log` on the feature branch. The feature branch must still exist (not deleted) when extraction runs.

## Security & Controls

**No new PII surfaces.** Observations contain file paths, line numbers, retry counts, finding categories, and timing data. No user data, credentials, or personal information. Code snippets are not stored in observations — only file paths and line references.

**Append-only storage.** Observation files are never modified or deleted by the system. Corruption of one observation doesn't affect others. The human can delete observation files manually if needed.

**LLM calls for classification.** Review finding classification uses a small, fast model. The input is the review finding text (which the Reviewer already generated) and task metadata. No source code is sent for classification. The classification prompt is deterministic and auditable.

**Local-only.** All observations are stored locally in `.speed/memory/observations/`. No telemetry, no external transmission. The observation directory can be gitignored if the team doesn't want to track observations in version control.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Observation storage grows unbounded over many features | Low | JSONL files are small (dozens of KB per feature). 100 features would produce ~5MB total. Storage is not a practical concern. If needed, archival of old observations can be added later. |
| Review finding classification accuracy (post-hoc LLM) | Medium | Classification has 6 categories with clear boundaries. Misclassification affects synthesis quality but not data integrity. Phase 2 adds generation-time tagging by the Reviewer, reducing dependence on post-hoc classification. |
| Extraction crashes mid-run leave partial observation files | Low | Idempotency handles this. Re-running produces no duplicates. Partial files are valid JSONL (each line is independent). |
| Git branch deleted before extraction runs | Medium | Extraction should run as part of `speed integrate` before the branch is cleaned up. If the branch is already deleted, context effectiveness and decomposition quality steps are skipped with a warning. |
| Pipeline artifact format changes break extraction | Low | Extraction reads known JSON keys and degrades on unknown structure. New fields are ignored. Missing expected fields produce a warning, not a crash. |
| Cross-feature pattern matching produces false patterns | Low | Pattern matching requires 3+ occurrences across features. Low threshold ensures real patterns surface; synthesis applies additional filtering before injecting into prompts. |

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should `speed learn` run as a substep of `speed integrate` or as a separate post-hook? Substep is simpler but couples the commands. Post-hook is cleaner but requires hook infrastructure. | Determines integration mechanism and failure isolation. | **Resolved.** `speed integrate` prompts the operator interactively (Y/n, default yes) before invoking `speed learn`. The operator stays in control. `speed learn` also remains available as a standalone command for manual runs. |
| Q2 | Should observations be gitignored by default or tracked in version control? Tracking enables team-wide learning; gitignoring keeps repos clean. | Affects whether learning is per-machine or per-team. | **Resolved.** Gitignored. `.speed/memory/observations/` is added to `.gitignore`. Learning data is per-machine. |
| Q3 | What model should review finding classification use — `support_model` or a hardcoded small model? Using support_model follows existing config; a hardcoded model ensures cost control. | Affects classification cost and consistency. | **Resolved.** Configurable via `speed.toml` (new `learn_model` key alongside existing `support_model`/`main_model`). Non-LLM classifiers (sklearn, rule-based) should also be evaluated if they provide better classification quality. Data quality is the priority over cost or speed. |
