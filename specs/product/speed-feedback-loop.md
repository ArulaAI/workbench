# SPEED Feedback Loops

> Standalone enhancement — no parent RFC.
> Depends on: Existing SPEED pipeline (`speed/speed`, `gates.sh`, `grounding.sh`, `developer.md`, `provider.sh`)

## Problem

SPEED has four broken feedback loops:

### 1. Developer Agent: no mid-task self-correction

The Developer Agent is single-shot: it writes all code in one go, exits, then quality gates run post-hoc. If gates fail, the Debugger diagnoses and the task retries from scratch. There's no iterative feedback loop — the agent can't run lint, typecheck, or tests mid-task and self-correct before declaring done.

This creates two problems:

1. **High first-attempt failure rate.** A lint error on file 3 of 8 doesn't surface until the agent has written all 8 files, exited, and gates run. The Debugger then has to reverse-engineer what went wrong from gate output. A mid-task `eslint` would have caught it in 10 seconds.

2. **No test-driven signal.** The developer prompt says "write tests" but doesn't require the agent to *run* tests and verify they pass before declaring done. Under token pressure, agents skip tests or write untested code. There's no grounding gate that checks "did you actually run the gates?"

The defect pipeline (Phase 3) has better patterns: a TDD reproduce stage, subsystem-scoped gates, grounding gates for scope. These patterns should flow back into the feature pipeline.

### 2. Plan Verification: findings go nowhere

`speed verify` runs the Plan Verifier, which produces a detailed structured report — critical failures, semantic drift, recommendations. Then... nothing. The raw JSON is dumped to the terminal. The operator reads a wall of structured data, manually figures out which task file to edit, makes the fix by hand, and re-runs verify. The loop isn't closed.

Three specific failures:

1. **Parser fragility.** The verifier agent wraps valid JSON in markdown prose (separators, summary text). `cmd_verify()` uses `_require_json()` (raw `jq empty`) instead of `parse_agent_json()` (which handles code fences and brace scanning). The parser chokes and reports "invalid JSON" even though the verification succeeded.

2. **Raw JSON as user feedback.** Even when parsing works, the operator sees raw JSON. The verification report has great structure (`critical_failures`, `recommendations`, `semantic_drift`) but none of it is formatted for humans. Compare to how `gates_run()` presents results — colored checkmarks, crosses, summaries. The verifier should match this standard.

3. **No path from findings to fixes.** When verification fails, the message is "fix the spec or re-run speed plan." No guidance on *which task file* to edit, *what specific value* to change, or *where* the drift occurred. The verifier knows all of this — it just doesn't tell the operator in actionable terms.

### 3. Reviewer and pipeline: token-unaware, hits API limits

SPEED has no awareness of Claude's API rate limits. It fires requests as fast as it can — 3 parallel developer agents, then debugger/supervisor agents, then 5 sequential review calls — with no tracking of token consumption and no pacing.

This causes two failures:

1. **Spec dump blows context and token budgets.** `cmd_review()` loads every spec file in the project (288KB, ~70k tokens) into every review prompt. This exceeds Claude's context window ("prompt too long") and consumes the TPM budget in 2-3 calls ("rate limit reached"). The reviewer only needs the feature's own spec and specs that reference the changed files — not the GitHub adapter spec to review a grounding gate change.

2. **No rate limit awareness or recovery.** When the API returns a rate limit error, `cmd_review()` logs a warning and immediately moves to the next task — which also hits the rate limit. No backoff, no retry, no pacing. Claude Code's API limits are TPM-based (200k-300k for small teams) with a rolling 5-hour window. SPEED should track its token usage and pace calls to stay within budget.

3. **Unbounded diff size.** `cmd_review()` sends the full `git diff` with no truncation. `DIFF_HEAD_LINES=500` exists in config but is only applied by the Guardian, not the reviewer. Large diffs compound the context problem.

### 4. Reviewer nits: approved and forgotten

The reviewer produces structured findings with severity levels (`critical`, `major`, `minor`, `nit`). When the verdict is `request_changes`, findings drive a retry. But when the verdict is `approve`, all findings — including actionable nits and minor issues — are written to a log file and never seen again.

This means:
1. **Nits accumulate silently.** Each approved task may carry 2-3 minor issues. Across 5 tasks, that's 10-15 items nobody tracks.
2. **The operator can't act on what they can't see.** The review log JSON is structured but not surfaced. The operator sees "Task 3: approved by Reviewer" and moves on.
3. **No summary across tasks.** Even if the operator reads individual review logs, there's no aggregated view of all nits from a review run.

## Users

### Engineering (Operator)
Runs `speed plan` and `speed run`. Wants a higher first-attempt pass rate so fewer tasks need debugging and retry. Wants confidence that the agent tested its own code before declaring done. Wants `speed review` to work reliably without hitting API limits.

### Developer Agent (Internal User)
Executes inside a worktree. Needs a single command that runs the right gates for the right subsystem without worrying about venv activation, directory resolution, or which linter to invoke.

### Product (Spec Author)
Writes specs that become tasks. Wants assurance that agent-written code is actually tested — not just "tests exist" but "tests were run and passed."

## User Stories

| ID | Story | Priority |
|----|-------|----------|
| S1 | As a Developer Agent, I want a single command to run quality gates from my worktree so I can check my work mid-task | Must |
| S2 | As a Developer Agent, I want a `--fast` tier (lint + typecheck only) so I can check syntax without waiting for the full test suite | Must |
| S3 | As an operator, I want a grounding gate that verifies new source files have corresponding test files in the diff | Must |
| S4 | As an operator, I want the developer prompt to include explicit, copy-pasteable gate commands instead of vague "write tests" instructions | Must |
| S5 | As an operator, I want a grounding gate that checks whether the agent actually ran `speed gates` during its session | Should |
| S6 | As a Developer Agent, I want `speed gates` to auto-detect my subsystem from the task so I don't run irrelevant gates | Must |
| S7 | As a Developer Agent, I want `speed gates` to work correctly from my isolated worktree without needing to know the project root | Must |
| S8 | As an operator, I want `speed verify` to present findings in a human-readable format with colors and symbols, not raw JSON | Must |
| S9 | As an operator, I want `speed verify` to automatically fix plan issues and re-verify until the plan passes or a fix requires my judgment | Must |
| S10 | As an operator, I want `speed verify` to tell me exactly which task file to edit and what to change when it can't auto-fix | Must |
| S11 | As an operator, I want the JSON parser to handle agent output wrapped in markdown prose without failing | Must |
| S12 | As an operator, I want `speed review` to load only specs relevant to the code being reviewed, not every spec in the project | Must |
| S13 | As an operator, I want `speed review` to truncate large diffs so individual reviews don't exceed context limits | Must |
| S14 | As an operator, I want SPEED to track token usage and pace API calls so I don't hit rate limits mid-pipeline | Must |
| S15 | As an operator, I want SPEED to retry on rate limit errors with backoff instead of failing immediately | Must |
| S16 | As an operator, I want to see a summary of all reviewer nits and minor issues at the end of `speed review`, not just pass/fail per task | Must |
| S17 | As an operator, I want reviewer nits saved to a structured file I can act on later | Should |
| S18 | As an operator, I want `speed fix-nits` to create a task from reviewer nits so I can fix them through the normal pipeline | Should |

## User Flows

### Developer Agent iterating mid-task

1. Agent receives task with explicit gate commands in the prompt
2. Agent writes core data structures and interfaces
3. Agent runs `./speed/speed gates -f <feature> --task <id> --fast` — lint + typecheck only
4. Lint catches an unused import — agent fixes it
5. Agent writes main logic and tests
6. Agent runs `./speed/speed gates -f <feature> --task <id> --full` — lint + typecheck + tests
7. Tests fail — agent reads output, fixes the bug
8. Agent runs `./speed/speed gates -f <feature> --task <id> --full` again — all pass
9. Agent commits and declares done
10. Post-hoc gates run (same gates) — pass on first attempt

### Operator observing improved pipeline

1. Operator runs `speed run`
2. Developer Agents execute with iterative gate checks
3. Post-hoc gates pass on first attempt for most tasks
4. Fewer tasks enter the Debugger → Retry cycle
5. Overall pipeline completion time decreases

### Grounding gate catching untested code

1. Developer Agent creates `src/frontend/components/features/new-widget.tsx`
2. Agent does not create a corresponding test file
3. Agent declares done
4. Post-hoc grounding gate: test file coverage check runs
5. Check finds `new-widget.tsx` in diff but no `new-widget.test.tsx` — hard failure
6. Task fails, Debugger diagnoses "missing test file for new-widget.tsx"
7. Retry: agent writes the test file

### Grounding gate catching skipped gates

1. Developer Agent writes all code, skips running `speed gates`
2. Agent declares done
3. Post-hoc grounding gate: gate invocation evidence check runs
4. Check greps agent log for gate output markers — finds none
5. Warning logged (promoted to hard failure after rollout stabilizes)
6. Post-hoc quality gates still run, but the warning signals the agent didn't self-check

### Plan verification auto-correction (happy path)

1. Operator runs `speed verify`
2. Plan Verifier produces structured report with one critical failure: "Task 1 says > 10 tasks, spec says > 8 tasks"
3. `cmd_verify()` parses the JSON (robust extraction handles markdown wrapping)
4. Findings are printed in human-readable format:
   ```
   Plan Verification:
     ✓ Core question answerable
     ✓ 24 of 25 spec requirements covered
     ✗ L4 sizing threshold: spec says "> 8 tasks", Task 1 says "> 10 tasks"
     ⚠ Sizing heuristic not included in agent prompt (recommendation)

   1 critical failure, 1 recommendation
   ```
5. Auto-fix loop starts: spawns a Fix Agent with the verification report and task files
6. Fix Agent edits `.speed/features/<name>/tasks/1.json`: changes "> 10 tasks" to "> 8 tasks"
7. Re-verification runs automatically
8. Second pass: all checks pass
9. Operator sees: "Plan verification PASSED (1 issue auto-fixed)"

### Plan verification with human escalation

1. Operator runs `speed verify`
2. Verifier finds a semantic drift issue: "spec says 'approved: true/false' output format but plan maps to existing validation severity"
3. Auto-fix loop starts, but the Fix Agent determines this requires a design decision — both approaches are valid
4. Fix Agent reports it can't auto-fix: the issue requires human judgment
5. `cmd_verify()` prints:
   ```
   Plan Verification:
     ✗ Architect RFC review output format drifted from spec

   Cannot auto-fix — requires your judgment:
     Task 2 (.speed/features/speed-audit/tasks/2.json):
       Spec says: "{ approved: true/false, issues: [...] } format"
       Plan says: "validation array with severity: critical"
       Both are functionally equivalent. Which should the plan use?
   ```
6. Operator edits the task file or accepts the drift
7. Operator re-runs `speed verify` — passes

### Reviewer completing without hitting limits

1. Operator runs `speed review` after 5 tasks complete
2. For task 1, `cmd_review()` builds the diff, truncates at 500 lines
3. Two-layer grep finds 2 relevant specs (out of 15+ in the project) — loads only those
4. Pre-flight estimate: ~15k tokens. Within TPM budget. Sends the call.
5. Review completes successfully. Token tracker updates remaining budget.
6. Before task 2, pacing check: budget sufficient, no delay needed. Sends immediately.
7. Tasks 2-4 review without issue.
8. Before task 5, pacing check: approaching TPM limit. Waits 30 seconds for budget to replenish.
9. Task 5 reviews successfully.
10. All 5 reviews complete in one `speed review` invocation — no rate limit errors, no prompt-too-long failures.

### Reviewer hitting rate limit with graceful recovery

1. Operator runs `speed review` after a large batch
2. Task 3 review triggers a rate limit error from the API
3. SPEED logs: "Rate limit reached — waiting 60s before retry (attempt 1/3)"
4. After backoff, retries the same review call
5. Call succeeds. Pipeline continues with remaining tasks.
6. If all 3 retries fail, SPEED logs the failure and moves to the next task (same as today, but with retries first)

### Plan verification with all issues auto-fixed

1. Operator runs `speed verify`
2. Verifier finds 3 issues: one threshold number wrong, one missing heuristic detail, one unclear placement instruction
3. All 3 are concrete, unambiguous fixes — no design decisions needed
4. Fix Agent applies all 3 edits to task JSON files
5. Re-verification passes on second attempt
6. Operator sees a summary of all auto-applied fixes and the final pass status
7. Total wall time: one command, no manual edits

## Success Criteria

- [ ] `speed gates -f <feature> --task <id> --fast` runs lint + typecheck for the task's subsystem
- [ ] `speed gates -f <feature> --task <id> --full` runs lint + typecheck + tests for the task's subsystem
- [ ] `speed gates` auto-detects subsystem from the task's `files_touched`
- [ ] `speed gates` activates the correct venv/node_modules in the worktree
- [ ] `speed gates` works from an isolated worktree (resolves paths correctly)
- [ ] Developer Agent prompt includes explicit `speed gates` commands with copy-pasteable syntax (including `-f` and `--task` flags)
- [ ] Developer Agent prompt instructs: run `--fast` after each file group, run `--full` before declaring done
- [ ] Grounding gate: new source files without corresponding test files → hard failure
- [ ] Grounding gate: test file coverage check excludes config files, type definitions, and migrations
- [ ] Grounding gate: agent log checked for gate invocation evidence → warning (initially)
- [ ] No duplication of gate logic — `cmd_gates()` reuses `gates_run()`, `_detect_subsystem()`, `gates_get_config()`
- [ ] `speed verify` uses `parse_agent_json()` for robust JSON extraction from agent output
- [ ] `speed verify` prints a human-readable report with colored symbols (checkmarks, crosses, warnings) matching the `gates_run()` output style
- [ ] `speed verify` critical failures show: which task, which field, what the spec says vs. what the plan says
- [ ] `speed verify` recommendations show: actionable fix with task file path
- [ ] `speed verify` auto-fix loop: spawns Fix Agent to apply corrections to task JSON files
- [ ] `speed verify` auto-fix loop: re-verifies after fixes are applied
- [ ] `speed verify` auto-fix loop: stops and prints actionable guidance when a fix requires human judgment
- [ ] `speed verify` auto-fix loop: caps at 3 iterations to prevent infinite loops
- [ ] `speed verify` auto-fix loop: prints summary of all auto-applied fixes
- [ ] `speed review` loads only specs relevant to the task's diff (two-layer grep: file paths + function names)
- [ ] `speed review` truncates diffs exceeding `DIFF_HEAD_LINES` (500) with a truncation note
- [ ] SPEED tracks token consumption per API call and cumulative per pipeline run
- [ ] SPEED paces API calls when approaching TPM/RPM budget limits
- [ ] SPEED retries rate-limited API calls with exponential backoff (3 attempts max)
- [ ] Token budget config: `TPM_BUDGET`, `RPM_BUDGET` in `config.sh` with sensible defaults
- [ ] `speed review` prints a nit/minor summary at the end of the run for all approved tasks
- [ ] `speed review` saves aggregated nits to `${LOGS_DIR}/review-nits.json`
- [ ] `speed fix-nits` reads `review-nits.json` and creates a single aggregate task with all nits as numbered fix instructions
- [ ] `speed fix-nits --task-id ID` filters nits to a specific original task
- [ ] The generated task goes through the normal `run → review` cycle with no special-casing
- [ ] `speed coherence` on re-run shows a delta summary comparing against the previous run's critical issues
- [ ] Delta shows fixed, remaining, and new issues with distinct visual indicators
- [ ] Count transition header shows `"Critical issues: N → M"`
- [ ] Previous report is cleaned up after a passing coherence check
- [ ] No delta shown on first run (no previous report exists)

## Scope

### In Scope
- `speed gates` CLI command (`cmd_gates()` in `speed/speed`)
- Fast and full gate tiers (`--fast` / `--full`)
- Developer Agent prompt enhancement with explicit gate commands
- Test file coverage grounding gate (`grounding_check_test_coverage()`)
- Gate invocation evidence grounding gate (`grounding_check_gate_evidence()`)
- Subsystem auto-detection for `speed gates` (reuses existing `_detect_subsystem()`)
- Worktree-aware path resolution for `speed gates`
- `cmd_verify()` rewrite: robust JSON parsing, human-readable output, auto-fix loop
- Verify → Fix → Re-verify automatic loop with iteration cap
- Human escalation for ambiguous fixes (design decisions the agent can't make)
- Smart spec loader for `cmd_review()` — two-layer grep to find relevant specs
- Diff truncation in `cmd_review()` using `DIFF_HEAD_LINES`
- Token budget tracking and pacing (`TPM_BUDGET`, `RPM_BUDGET` in config)
- Rate limit retry with exponential backoff in provider layer
- Pre-flight token estimation before API calls
- Reviewer nit summary at end of `speed review` run
- Aggregated nit output file (`review-nits.json`)
- `speed fix-nits` command to create a task from reviewer nits (`cmd_fix_nits()` in `speed/speed`)

### Out of Scope (and why)
- Mid-agent injection (pausing the agent to force gate runs) — architecturally invasive, Claude Code doesn't support it
- Enforcing TDD ordering (test before implementation) — temporal ordering is impractical to verify from a post-hoc diff; diminishing returns vs. just verifying test files exist
- Standalone user-facing gates tool (for humans running gates outside SPEED) — different UX requirements, different scope; `speed gates` is designed for agent use
- Automatic retry on gate failure mid-task — the agent should fix the issue itself; if it can't, it declares done and the normal retry pipeline handles it
- `speed verify --no-fix` flag (run verification without auto-fix) — future; the auto-fix loop is the default and only mode initially
- Spec-level fixes (the auto-fix loop fixes task JSON files, not the source spec) — if the spec itself is wrong, that's a human problem
- Per-call token counting via API response headers — Claude Code CLI doesn't expose token usage; estimation from character count is sufficient for pacing
- Automatic TPM tier detection — too fragile; operator sets their budget in config
- Request queuing or priority scheduling — SPEED's sequential review loop is simple enough; pacing + backoff is sufficient

## Dependencies

- `speed/lib/gates.sh` — `gates_run()`, `_detect_subsystem()`, `gates_get_config()`, `gate_run_command()`
- `speed/lib/grounding.sh` — `grounding_run()` (new checks added here)
- `speed/lib/provider.sh` — `parse_agent_json()`, `_require_json()`, `claude_run()`
- `speed/agents/developer.md` — prompt enhancement
- `speed/agents/plan-verifier.md` — existing verifier agent (output consumed by new formatting/fix logic)
- `speed/lib/config.sh` — path constants, subsystem detection config, `DIFF_HEAD_LINES`, new `TPM_BUDGET`/`RPM_BUDGET`
- `speed/providers/claude-code.sh` — `provider_run()` (rate limit detection + retry + token tracking)

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Token cost of iterative gate runs | Medium | `--fast` tier (lint + typecheck) is cheap. Agent instruction limits `--full` to one final check. Gate output is piped to a log file, not consumed by the agent's context window. |
| Test coverage check too rigid (flags files that legitimately don't need tests) | Medium | Exclusion patterns for known no-test categories: config files, type definitions, migrations, barrel exports, CSS/asset files. Patterns match project conventions from CLAUDE.md. |
| Agent ignores gate instructions under token pressure | Medium | Gate invocation evidence grounding gate catches this. Starts as warning, promoted to hard failure after confirming agents comply in practice. |
| `speed gates` command slows down agent execution | Low | Fast tier takes seconds. Full tier takes the same time tests would take anyway — the cost is running them twice (mid-task + post-hoc) which is marginal vs. the cost of a full retry cycle. |
| Fix Agent makes wrong edits to task JSON | Medium | Re-verification catches bad fixes. If the same issue persists after a fix attempt, the loop stops and escalates to the human. 3-iteration cap prevents runaway. |
| Fix Agent changes task semantics beyond what was flagged | Low | Fix Agent prompt is scoped: "apply ONLY the fixes listed in the verification report, change nothing else." Re-verification catches scope drift. |
| Auto-fix loop feels opaque (operator doesn't know what changed) | Medium | Every auto-applied fix is logged with before/after values. Summary printed at end: "Auto-fixed 2 issues: Task 1 threshold 10→8, Task 1 added sizing heuristic." |
| Smart spec loader misses a relevant spec (false negative) | Low | Two-layer grep (file paths + function names) casts a wide net. False positives are acceptable. The feature's own spec is always included regardless of grep results. |
| Token estimation inaccurate | Low | Character-based estimation (~4 chars/token) is a rough heuristic, not precise. Budget includes 20% headroom. The goal is pacing, not exact accounting. |
| Rate limit backoff slows pipeline | Low | Only triggers when hitting actual limits. Waiting 60s is better than failing and requiring manual re-run. Backoff caps at 5 minutes. |
| `DIFF_HEAD_LINES` truncation hides important code from reviewer | Low | 500 lines covers most single-task diffs. Truncation note tells reviewer the diff is partial. Reviewer has read-only file access for full inspection if needed. |
