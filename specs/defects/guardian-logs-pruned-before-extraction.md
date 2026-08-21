# Defect: Guardian logs pruned before observation extraction can read them

Severity: P3
Related Feature: continuous-learning
Tags: observations, guardian

## Observed Behavior

`_prune_logs()` in `lib/gates.sh` keeps only the 3 most recent guardian logs per check type (`LOG_RETAIN_PER_CATEGORY`, default 3). Guardian logs are written to `${LOGS_DIR}/guardian-${check_type}-${timestamp}.json` and pruned after every guardian invocation. On a feature with 5+ tasks, earlier guardian verdicts are deleted before `speed learn` runs.

The observation infrastructure works around this by reading guardian rejections from task JSON instead. When a guardian rejects, `task_request_changes()` writes `"GUARDIAN REJECTED: <summary>"` to the task's `review_feedback` field. That field persists.

The workaround only captures rejections. Three categories of guardian data are lost:

1. **Cleared verdicts.** Task passed guardian with no flags. No trace remains in task JSON (the task simply proceeds to "done").
2. **Flagged-but-passed verdicts.** Guardian raised flags but the operator approved. The approval leaves no artifact; the task proceeds as if cleared.
3. **Detailed rejection metadata.** Guardian JSON includes `flags[]`, `scope_violations[]`, and structured `status` fields. Task JSON only preserves the free-text `summary` string via `review_feedback`.

## Expected Behavior

Guardian verdict data should survive long enough for observation extraction. Either increase the retention count, or copy verdict summaries to a persistent location during the guardian check.

## Impact

The observation system can only produce `guardian_verdict` observations for rejections, and only with the summary text (not structured flags or scope violations). Cleared and flagged-but-passed verdicts are invisible. Synthesis cannot learn patterns like "guardian flags tasks touching area X but operator always approves" because the approve-after-flag path leaves no trace.

## Suggested Fix

Two options, not mutually exclusive:

1. **Increase retention or disable pruning for feature runs.** Set `LOG_RETAIN_PER_CATEGORY` high enough that all tasks in a feature retain their guardian logs until extraction completes. Simple but doesn't solve the structured-data-in-task-JSON gap.

2. **Write a guardian summary to task JSON on every verdict, not just rejections.** After `_run_guardian()` returns, write the verdict (`aligned`/`flagged`/`rejected`) and flag count to a `guardian_verdict` field in task JSON. Extraction reads this field instead of parsing log files. Requires a small change to `lib/shared.sh` and `lib/tasks.sh`.

Option 2 is more robust. It follows the same pattern the pipeline already uses for review verdicts (`review_verdict` field in task JSON).
