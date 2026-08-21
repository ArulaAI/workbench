# Human Correction Capture

> See [speed-continuous-learning.md](../../working-docs/speed-continuous-learning.md) for system design.
> Depends on: [Observation Infrastructure](speed-observations.md), [Agent-Specific Synthesis](speed-synthesis.md)

## Goal

Close the external feedback loop. Every other learning signal in SPEED is the system evaluating itself. Human corrections are the only signal where the operator demonstrates what the right output looks like. Capture the gap between what SPEED produced and what the human shipped, feed it through synthesis, and ensure the same mistake never recurs. The primary metric: when the human override rate drops to zero for a correction category, SPEED has earned trust in that area.

## Problem

Every other learning signal in SPEED is the system talking to itself. The Reviewer judges the Developer's code. The Guardian checks the Developer's scope. Extraction watches the pipeline's artifacts. Convention discovery reads the codebase. All internal signals, all limited by the same blind spots the system already has.

One signal is external: what the human does with SPEED's output.

When a human reviews SPEED's PR and merges it unchanged, that's validation no internal signal can match. When a human edits SPEED's output before merging, every edit is a lesson the system couldn't teach itself. The human replaced `httpx.get()` with `lib/api/client.py:fetch()` — no amount of self-review or convention discovery would have surfaced that wrapper convention until the human demonstrated it. The human added parametrized tests for malformed input variants — the Developer's blind spot for edge case coverage is invisible to the Developer.

Human corrections are ground truth. The gap between "what SPEED produced" and "what the human shipped" is the only metric that actually measures whether the system has earned trust. Every other metric (retry rate, reviewer findings, guardian accuracy) is a proxy. Human correction capture closes the loop: the human's actions directly feed back into the learnings that shape future agent behavior.

Without this feedback, the system can only learn from itself. With it, the system learns from the one judge whose opinion matters.

**Principle grounding:** P4 (human corrections are ground truth) — the entire feature exists because of this principle. Human corrections receive the highest authority in conflict resolution and the highest weight in synthesis. P3 (failure memory first) — corrections are failure signals (the system produced the wrong output). P1 (learning is scaffolding) — corrections become pre-computed context that prevents the same mistake on the next run.

## Users

### Engineering (Operator)
Reviews SPEED's PR, makes corrections, merges. Wants their corrections to actually change SPEED's behavior on the next feature. Today, corrections are ephemeral — the human fixes the PR and SPEED repeats the same mistakes next time. Human correction capture makes corrections durable.

### Learning System (Internal Consumer)
Synthesis treats human_override observations with the highest weight (2.5 per observation). A single human correction pattern (2+ occurrences) drives learnings entries that rank above most pipeline-internal signals. Human correction data is the primary calibration signal for every agent's learnings file.

### Developer Agent (Indirect Beneficiary)
Receives developer-learnings.json entries derived from human corrections: "HTTP calls go through lib/api/client.py:fetch() — human corrected raw httpx calls in 2 PRs." On feature 10, the Developer follows the wrapper convention because the human's corrections from features 3 and 5 became prompt context.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| HC1 | As an operator, I want my PR corrections captured as learning signals so that SPEED doesn't repeat mistakes I've already fixed | Given a PR where the human replaced `httpx.get()` with `lib/api/client.py:fetch()`, when `speed learn --post-merge` runs, then a `human_override` observation is created with file, change type (transformative), category (convention), what SPEED wrote, what the human changed, and agent attribution (developer) | Must |
| HC2 | As an operator, I want zero-delta merges recorded as positive signals so that the system knows when its output was fully accepted | Given a PR merged without any human changes, when `speed learn --post-merge` runs, then a `human_approved` observation is created recording the number of tasks and files approved | Must |
| HC3 | As an operator, I want corrections classified by change type so that synthesis routes them to the right agent | Given a human correction, then it is classified by change type (additive, subtractive, transformative, cosmetic) deterministically from diff structure. Learning category (convention, correctness, scope, testing, style, architecture, dependency) is deferred to synthesis, which has cross-feature context and higher classification accuracy than per-hunk extraction-time classification. See DD1. | Must |
| HC4 | As an operator, I want corrections attributed to the responsible agent so that each agent's learnings file receives relevant feedback | Given a subtractive correction (human removed unnecessary code), then it is attributed to Guardian (should have caught scope drift) and Developer (over-engineered). Given a transformative convention correction, then attributed to Developer and conventions.json | Must |
| HC5 | As an operator, I want multi-commit PRs processed per-commit so that each correction is a separate learning signal | Given a PR with 3 human commits (fix convention, add test, remove helper), when extraction processes the PR, then each commit produces a separate observation with its own classification and attribution | Must |
| HC6 | As an operator, I want PR comments captured alongside diff hunks so that I understand *why* the human made a change, not just what they changed | Given a PR comment "We always use the project wrapper for HTTP calls" on a diff hunk, when the observation is created, then the `human_comment` field contains the comment text. Given no PR comment, then the observation is still valid with `human_comment: null` | Should |
| HC7 | As an operator, I want noise filtered before classification so that changelog updates, merge artifacts, and whitespace changes don't pollute the observation log | Given a commit that only changes the CHANGELOG and bumps the version, when noise filtering runs, then the commit is excluded from observation extraction. Given a cosmetic-only commit (whitespace), then it is recorded with weight 0.1 | Must |
| HC8 | As an operator, I want `speed learn --post-merge` as a standalone command so that I can trigger correction capture after merging a PR | Given a merged feature, when I run `speed learn --post-merge -f <feature>`, then the system diffs SPEED's branch tip against the merged result, processes each human commit, and prints a summary | Must |
| HC9 | As an operator, I want partial corrections acknowledged without over-interpreting unchanged code | Given a PR where the human fixed 3 issues but left 12 other files unchanged, then the 3 corrections produce observations but the 12 unchanged files are treated as "unknown" (not "approved"). Only a zero-delta merge counts as full approval | Must |
| HC10 | As an operator, I want additive corrections (human added what SPEED missed) weighted heavily because they reveal blind spots | Given the human added a parametrized test SPEED didn't write, when synthesis processes this, then the observation carries high weight because additive corrections indicate gaps in the system's understanding, not just preference differences | Must |
| HC11 | As an operator, I want human corrections to have the highest authority in conflict resolution | Given the Reviewer flagged "helper function is scope creep" (2 occurrences) but the human accepted helper functions unchanged (1 occurrence), when synthesis resolves the conflict, then the human's acceptance wins: the Reviewer gets a "known false alarm" entry | Must |
| HC12 | As an operator, I want my retry diagnosis captured as a learning signal so that the system learns from my debugging, not just the retry outcome | Given a task retry with `--context "the auth handler needs to validate tokens before checking permissions"`, when extraction runs, then a `human_override` observation is created with change_type=guidance, the human's text as the detail, and attribution to the agent that failed. The human's text is distinguished from reviewer/guardian feedback in the same `review_feedback` field by the `--- Attempt N ---` / `Human guidance:` markers already written by retry.sh | Must |
| HC13 | As an operator, I want skip flags recorded so that the system learns which gates I consistently bypass | Given `SKIP_GUARDIAN=true speed plan specs/auth.md`, when extraction runs for that feature, then a `human_override` observation is created with change_type=skip, detail recording which gate was skipped, and weight 0.5. Repeated skips of the same gate across features surface as a pattern in synthesis, signaling the gate may need recalibration | Should |
| HC14 | As an operator, I want forced approvals detected so that the system learns when reviewer findings are false alarms | Given a task where `review_verdict` was set to `approve` without a corresponding reviewer run (no `review-{task_id}.json` log, or log timestamp predates the verdict change), then a `human_override` observation records the forced approval with the reviewer's original findings as context | Should |
| HC15 | As an operator, I want defect rejections captured so that the triage system learns which defect patterns are false positives | Given a defect transitioned to `rejected`, when extraction runs, then a `human_override` observation is created with the defect's original classification, triage output, and the `rejected` terminal state. Synthesis routes this to the agent that filed the defect | Should |

## User Flows

### Post-merge correction capture (happy path)

1. Feature "speed-security" completes `speed integrate`. SPEED's PR is created
2. Human reviews the PR (5 tasks, 15 files)
3. Human makes 3 commits:
   - Commit B: replaces `httpx.get()` with `lib/api/client.py:fetch()` in `lib/security.py`, PR comment: "We always use the project wrapper"
   - Commit C: adds parametrized test for malformed input in `tests/test_security.py`
   - Commit D: removes unused `_format_output()` helper from `lib/security.py`
4. Human merges the PR
5. Operator runs `speed learn --post-merge -f speed-security` (or it triggers via post-merge hook)
6. System identifies SPEED's branch tip (last commit before human review) and the merged result
7. Identifies 3 human commits by author/commit-message pattern
8. Processes each commit:
   - Commit B: transformative, convention, attributed to Developer. PR comment captured
   - Commit C: additive, testing, attributed to Developer. No PR comment
   - Commit D: subtractive, scope, attributed to Guardian + Developer. No PR comment
9. Noise filter: no changelog, merge artifacts, or whitespace-only changes detected
10. 3 observations written to `.speed/memory/observations/speed-security.jsonl`
11. Summary: "3 human corrections captured (1 convention, 1 testing, 1 scope). 12 files unchanged (unknown, not approved)."

### Zero-delta merge

1. Feature "speed-audit" completes `speed integrate`. SPEED's PR is created
2. Human reviews the PR (4 tasks, 10 files)
3. Human merges without any changes
4. `speed learn --post-merge -f speed-audit` runs
5. No human commits found between SPEED's branch tip and merge
6. `human_approved` observation created: 4 tasks approved, 10 files approved
7. Summary: "Zero-delta merge. SPEED's output required no corrections."

### Noise filtering

1. Human made 5 commits during PR review
2. Commit B: convention fix in `lib/security.py` — real correction
3. Commit C: updates CHANGELOG.md — merge process artifact
4. Commit D: adds test for malformed input — real correction
5. Commit E: removes helper function — real correction
6. Commit F: reformats indentation in `lib/security.py` — cosmetic only
7. Noise filter:
   - Commit C: excluded (CHANGELOG is a merge artifact, not a correction)
   - Commit F: recorded with weight 0.1 (cosmetic, but tracked in case frequent formatting corrections indicate a convention)
8. 3 substantive observations + 1 cosmetic observation produced

### Correction feeding into next feature

1. Features 3 and 5 both produced `human_override` observations: "human replaced raw httpx with project wrapper"
2. Synthesis processes: 2 occurrences → pattern. Weight: 5.0 (2 × human_override 2.5)
3. developer-learnings.json entry: "HTTP calls go through lib/api/client.py:fetch(). Human corrected raw httpx in 2 PRs."
4. Feature 7 starts. Task 2 touches `lib/api/`
5. Developer prompt includes the learnings entry
6. Developer uses `lib/api/client.py:fetch()` instead of raw httpx
7. Human reviews PR — no httpx corrections needed
8. The correction from features 3 and 5 prevented the mistake in feature 7

### Correction with PR comment context

1. Human replaces raw httpx call, leaves PR comment: "We always use the project wrapper for HTTP calls — it handles retries and timeouts"
2. Extraction captures the PR comment via `gh api repos/.../pulls/.../comments`
3. Observation includes `human_comment`: "We always use the project wrapper for HTTP calls — it handles retries and timeouts"
4. During synthesis formatting, the LLM uses the comment to produce richer guidance: "HTTP calls go through lib/api/client.py:fetch(). The wrapper handles retries and timeouts — never bypass it with raw httpx."
5. The comment-enriched guidance is more informative than the diff alone would produce

### Retry guidance capture

1. Task 3 fails with a timeout in the auth handler
2. Human runs `speed retry --task-id 3 --context "The auth handler needs to validate tokens before checking permissions — the current order causes a race condition"`
3. retry.sh writes to `review_feedback`: `--- Attempt 2 ---\nFailed with: timeout\nHuman guidance: The auth handler needs to validate tokens before checking permissions...`
4. Task 3 succeeds on retry
5. `speed learn` runs extraction for the feature
6. Step 11 (human corrections) parses `review_feedback`, finds `Human guidance:` markers
7. Observation created: `human_override`, change_type=guidance, detail includes the human's diagnosis text, attributed to developer
8. Synthesis: if the same diagnosis pattern appears across 2+ features, it becomes a learnings entry ("validate tokens before checking permissions in auth handlers")

### Skip flag recording

1. Human runs `SKIP_GUARDIAN=true speed plan specs/auth.md` three features in a row
2. Each plan run logs the skip to `.speed/features/<name>/logs/skipped-gates.json`
3. `speed learn` extraction reads the skip log, creates `human_override` observations with change_type=skip, weight 0.5
4. Synthesis: 3 skip observations for the same gate produce a pattern. Guardian receives a "scope calibration" entry: "operator skipped pre-plan guardian check 3 times — review trigger sensitivity"

## Success Criteria

- [ ] `speed learn --post-merge -f <feature>` diffs SPEED's branch tip against the merged result and extracts human corrections
- [ ] Each human commit is processed individually (not collapsed into one diff)
- [ ] Human commits identified by author or commit-message pattern (not SPEED's commits)
- [ ] Corrections classified along two dimensions: change type (additive, subtractive, transformative, cosmetic) and learning category (convention, correctness, scope, testing, style, architecture, dependency)
- [ ] Change type classification is deterministic from diff structure (no LLM call). Learning category is assigned during synthesis, not at extraction time. See DD1.
- [ ] Corrections attributed to responsible agents: transformative-architecture → Architect, transformative-convention → Developer, additive-testing → Developer, subtractive-scope → Guardian + Developer, any missed-by-reviewer → Reviewer, wrong-context → Context
- [ ] Multi-commit PRs: each human commit produces separate observations
- [ ] PR comments captured via `gh api` and associated with corresponding diff hunks
- [ ] PR comments stored in observation's `human_comment` field. Missing comments → `null` (observation still valid)
- [ ] Zero-delta merges produce `human_approved` observations (strongest positive signal)
- [ ] Noise filtering: changelog/version bumps excluded, merge artifacts excluded, changes to untouched files excluded, cosmetic-only changes recorded with weight 0.1
- [ ] Partial correction acknowledgment: unchanged files are "unknown," not "approved." Only zero-delta = full approval
- [ ] Human override observations carry weight 2.5 in synthesis (highest for failure signals)
- [ ] Human corrections win conflict resolution against internal signals (Reviewer, Guardian)
- [ ] `speed learn --post-merge` prints a summary: N corrections captured, categories, zero-delta status
- [ ] Feature branch must still exist (or merged commit accessible) for diff comparison. If unavailable, warning + skip
- [ ] Extraction handles GitHub-hosted and local-only repos (gh api for GitHub, git notes fallback for local)
- [ ] Retry guidance extracted from `review_feedback` by parsing `Human guidance:` markers. Each retry with `--context` produces a `human_override` observation with change_type=guidance
- [ ] Skip flags (`SKIP_GUARDIAN`, `SKIP_GATES`, `--skip-audit`, `--skip-tests`) logged to `skipped-gates.json` and extracted as `human_override` observations with change_type=skip, weight 0.5
- [ ] Forced approvals detected when `review_verdict=approve` has no matching reviewer log or log predates the verdict. Produces `human_override` observation with original reviewer findings
- [ ] Defect rejections produce `human_override` observations with the defect's classification and triage context

## Scope

### In Scope
- `speed learn --post-merge` CLI command
- Branch tip vs. merged result diff extraction
- Per-commit human correction identification
- Two-dimensional correction classification (change type × learning category)
- Agent attribution logic
- PR comment extraction via `gh api`
- Zero-delta merge detection and `human_approved` observation creation
- Noise filtering (merge artifacts, cosmetic changes, unrelated file changes)
- Partial correction semantics (unchanged ≠ approved)
- Post-merge git hook integration (optional)
- Observations written to existing `.speed/memory/observations/<feature>.jsonl`
- Retry guidance extraction from `review_feedback` field (parsing `Human guidance:` markers)
- Skip flag logging and observation creation (`SKIP_GUARDIAN`, `SKIP_GATES`, `--skip-audit`, `--skip-tests`)
- Forced approval detection (verdict without matching reviewer log)
- Defect rejection observation creation

### Out of Scope (and why)
- **Automated remediation of corrections** — If the human replaced raw httpx with a wrapper, the system doesn't auto-fix future httpx calls. Corrections feed into learnings that guide the Developer; the Developer applies the guidance. Auto-remediation risks introducing subtle behavioral changes without the Developer understanding why.
- **Real-time PR monitoring** — Correction capture happens post-merge, not during review. Real-time monitoring would require GitHub webhooks or polling infrastructure that adds complexity without proportional benefit. Post-merge capture gets the same data with a simpler trigger.
- **Corrections from external reviewers** — The system captures what changed between SPEED's output and the merged result. It doesn't distinguish "author's corrections" from "external reviewer's corrections." All changes are treated as human corrections regardless of who made them.
- **Correction dispute resolution** — If the human's correction is itself wrong (introduced a bug), the system still records it as ground truth. The next feature run may hit the bug, producing a new observation that counter-evidence the correction. Self-correcting through the observation pipeline, not through a dispute mechanism.
- **Automatic gate recalibration from skip patterns** — Skip observations feed into learnings that inform agents, but the system doesn't automatically adjust gate thresholds. Gate sensitivity is a product decision, not a learning system decision.

## Dependencies

- **Observation Infrastructure** ([speed-observations.md](speed-observations.md)) — Human corrections are stored as observations in the same JSONL format. The observation data model (typed observations with deterministic IDs) applies. Existing extraction idempotency protects against duplicate corrections.
- **Agent-Specific Synthesis** ([speed-synthesis.md](speed-synthesis.md)) — Human override observations flow into synthesis with weight 2.5. Synthesis produces learnings entries attributed to the corrected agent. Without synthesis, corrections are collected but not actionable.
- **Git history** — Requires the feature branch tip and merged result to be accessible. If the branch was deleted and garbage collected before `--post-merge` runs, the diff is unavailable.
- **GitHub API (optional)** — PR comment extraction uses `gh api`. For non-GitHub repos or local-only reviews, comments are unavailable. Corrections from the diff alone are still valid.
- **Provider infrastructure** (`lib/provider.sh`) — Post-merge extraction does not require LLM calls. If future refinement adds optional LLM enrichment, it uses the same provider infrastructure as the rest of the pipeline.
- **Skip flag logging** — Requires each gate function to write a log entry when skipped. Today, skip flags are checked and the gate is bypassed silently. A small change to each gate call site to append to `skipped-gates.json`.

## Security & Controls

**No secrets in correction observations.** Classification records what changed (file, change type, category) but does not store the actual diff content in the observation. If the human's correction involves removing a hardcoded secret, the observation records "subtractive correction in lib/config.py, category: correctness" — not the secret itself.

**PR comment content is stored.** Unlike diff content, PR comments are human-authored text explicitly written for others to read. Storing them in the observation is safe. Comments containing secrets would be a human error in the PR review process, not a system concern.

**No LLM calls for classification.** Post-merge classification is deterministic (change type from diff structure, agent attribution from file-path rules). No code is sent to any provider during correction extraction. See DD1.

**Observation append-only.** Human override observations follow the same append-only storage model as all other observations. Corrections are never modified or deleted by the system.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Human correction is itself wrong (introduces a bug) | Medium | Self-correcting: the bug surfaces in subsequent features as a new observation. The wrong correction gets counter-evidence. P4 (human corrections are ground truth) accepts this risk — human corrections are the best available signal even when imperfect. |
| Feature branch deleted before `--post-merge` runs | Medium | Encourage running `--post-merge` immediately after merge (or as a post-merge hook). If the branch is gone, warn and skip. The correction data for that feature is lost but future features still work. |
| Classification accuracy for ambiguous corrections | Low | Change type is deterministic (100% accuracy validated). Agent attribution is rule-based (90% accuracy validated). Learning category is deferred to synthesis, which has cross-feature context. Misattribution risk is limited to file-path edge cases. |
| Human makes many cosmetic changes that aren't real corrections | Low | Noise filtering excludes pure whitespace/formatting changes. Cosmetic changes that pass the filter are recorded with weight 0.1 — negligible impact on synthesis unless they're frequent and consistent (which would indicate a formatting convention worth capturing). |
| Over-reliance on small number of human corrections early on | Medium | Recurrence filter in synthesis requires 2+ occurrences. A single human correction is noted but doesn't become guidance until confirmed by a second occurrence. Prevents single-instance corrections from prematurely driving agent behavior. |
| PR comments unavailable (non-GitHub repo, API limits) | Low | Comments enrich observations but aren't required. Diff-based classification works without comments. `human_comment: null` is a valid state. |

## Design Decisions

| ID | Decision | Rationale | Evidence |
|----|----------|-----------|----------|
| DD1 | Post-merge path uses deterministic classification (change type from diff structure, agent attribution from rules). Learning category deferred to synthesis. No LLM calls at extraction time. | TF-IDF prototype classifier validated at 20% category accuracy on real diff hunks (vocabulary mismatch: code tokens vs. prose prototypes). Change type accuracy: 100%. Agent attribution accuracy: 90%. LLM classification adds cost, latency, non-determinism, and provider dependency for a step whose accuracy is unproven. Synthesis has cross-feature context and can assign categories with more signal. | `tests/validate_classifier_postmerge.py` — 20 hunks across 4 tasks from speed-defects and speed-security. |

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should `speed learn --post-merge` run automatically via a post-merge git hook, or should it always be manual? Automatic ensures data is captured; manual gives the operator control over when extraction runs. | Determines whether correction data is consistently captured or opportunistic. | Decided: Manual. Keep it simple. Document hook setup for teams that want automation. |
| Q2 | How should the system handle squash merges where all human commits are collapsed into one? The per-commit extraction model loses granularity. | Affects correction granularity for teams that squash-merge. | Decided: Per-hunk fallback. When a single squash commit is detected, fall back to per-hunk analysis within that commit rather than per-commit. |
| Q3 | Should corrections from CI-authored commits (automated formatters, linters) be treated as human corrections or filtered as noise? | Determines whether automated tooling corrections are learning signals (they indicate a convention the Developer should follow) or noise (they're not human judgment). | Decided: Filter as noise. CI commits are automated tooling, not human judgment. Detect by author pattern or commit message convention. |
| Q4 | Should retry guidance extraction require the task to have succeeded on retry, or capture guidance even when all retries fail? | Determines whether failed diagnoses become learning signals | Open |
| Q5 | For skip flag recording, should the observation be created at skip time (immediate) or at extraction time (batch)? Immediate ensures capture; batch keeps the existing extraction model. | Determines when skip data enters the observation log | Open |
