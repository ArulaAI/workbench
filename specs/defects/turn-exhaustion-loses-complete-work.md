# Defect: Agent work discarded when max turns reached despite complete implementation

Severity: P2
Related Feature: speed-security

## Observed Behavior

Task 3 of `speed-security` hit the 50-turn limit and was classified as "Quality gates failed." The implementation is complete: `grounding_check_secrets()` added to `lib/grounding.sh` (160 lines), `tests/test_secrets_scanner.sh` created (335 lines), all 11 tests pass, and both files are staged in the worktree.

The framework treated max-turn exhaustion identically to a genuine gate failure. The task was marked `failed` with `error: "Quality gates failed"`, the `failure_classification` came back `unclassified/unknown`, and the completed work sits orphaned in a worktree that `cmd_retry` will delete.

The task's `3.log` contains only: `Error: Reached max turns (50)`. No distinction between "agent couldn't finish the work" and "agent finished but ran out of turns before the framework confirmed."

## Expected Behavior

When an agent hits the turn limit, the framework should check whether the work is actually complete before classifying the failure. A viable check:

1. Does the worktree have staged or committed changes on the task branch?
2. Do the quality gates pass when run against those changes?

If both are true, the task succeeded (the agent just took a long path to get there). Mark it `done`, not `failed`. If gates fail, then the "Quality gates failed" classification is accurate.

At minimum, the failure classification should distinguish "max turns, work present" from "max turns, no work" and from "gates explicitly failed." The current `unclassified/unknown` classification provides no signal for diagnosis or retry strategy.

## Reproduction Steps

1. Create a task with high complexity (12 acceptance criteria, 7 regex patterns, full test harness with temp git repos)
2. Assign a context budget where 95%+ of code budget is consumed and 16 files are dropped or skeletonized
3. Run the task — agent spends turns exploring code not in its context window
4. Agent completes the implementation and stages files
5. Agent hits 50-turn limit before committing or before the framework runs gates
6. Framework marks task as "Quality gates failed" despite the work being complete and passing

## Additional Context

**Evidence from Task 3:**

| Metric | Value |
|--------|-------|
| Code context budget | 48,000 tokens |
| Code context used | 45,901 (95.6%) |
| Files dropped | 8 (2-hop dependencies) |
| Files downgraded full to skeleton | 8 (1-hop dependencies) |
| Implementation lines written | ~500 (grounding.sh + test suite) |
| Tests passing | 11/11 |
| Worktree state | Both files staged, not committed |

**The context pressure likely caused the turn burn.** The agent received skeleton views of `lib/context_bridge.sh`, `lib/defects.sh`, `lib/criteria_verify.py`, and five other 1-hop files. Eight 2-hop files were dropped entirely. Without visibility into dependencies, the agent spent turns reading files to understand conventions, then iterating on the test harness setup.

**Affected code path:**

`lib/cmd/run.sh` — the completion handler around line 482-493. When the agent process exits (including from max turns), the framework checks gate status. If gates weren't confirmed as passing, it calls `task_set_failed "$task_id" "Quality gates failed"`. No intermediate check for "work exists in worktree."

Reproducibility: intermittent (depends on context budget pressure vs. task complexity)
