# Defect: Grounding check accepts trivial diffs as task completion

**Severity:** P2-moderate
**Related Feature:** lib/gates.sh (grounding checks), lib/cmd/run.sh (task completion)
**Reproducibility:** intermittent (3/10)
**Last Known Working:** never worked

## Observed Behavior

A developer agent commits a trivial change (a comment, an import reorder, a whitespace fix) and reports the task as "done." SPEED's grounding check passes because the `diff_non_empty` gate only verifies the diff has any content at all. The task moves to "done" status with no meaningful implementation.

The Reviewer catches this later during `speed review`, but by then the task is already marked complete and dependent tasks may have started on a branch that assumes the work exists.

Example from a real run: an agent read existing code that resembled the feature, concluded the work was already done, committed a one-line comment change, and exited. Grounding check passed. Reviewer flagged it as `request_changes` 15 minutes later.

## Expected Behavior

The grounding check should reject diffs that are trivially small relative to the task's scope. A task with 5 acceptance criteria and a 1-line whitespace change is not done. The check should flag this before the task is marked complete, not after.

Specifically:

- Diffs that consist entirely of comments, whitespace, or import reordering should fail grounding
- Diffs that touch none of the files listed in the task's `files_touched` should fail grounding (this may already be covered by the `declared_files` check, but not by substance)
- Diffs with a suspiciously low line count relative to the number of acceptance criteria should produce a warning

## Reproduction Steps

1. Create a spec for a feature that resembles existing code in the repo (e.g., "add a memberCount field" when similar counted fields already exist)
2. Run `speed plan` and `speed verify`
3. Run `speed run`
4. Observe that the agent reads the existing similar code, concludes the work is done, commits a trivial change
5. Grounding check passes with all green except `criteria: warn`
6. Task is marked "done"
7. `speed review` later catches the empty implementation

## Environment

Any repo where the feature overlaps with existing patterns. More likely on larger codebases where the agent has more similar code to confuse itself with. Observed on find-your-tribe (350 files) and appsmith (13K files).

## Error Output

Grounding check output when this happens:

```
Grounding Checks:
  ✓ Non-empty diff
  ✓ Declared files exist
  ✓ Scope check
  ✓ Python imports resolve
  ✓ Agent completed (not blocked)
  ✓ Test file coverage
  ⚠ No gate invocation evidence in agent output
  ⚠ Criteria: some unverifiable (manual review needed)
  ✓ No committed secrets
```

All checks pass. The `criteria: warn` is the only signal, and it doesn't block completion.

## Additional Context

Three contributing causes:

1. **Agent hallucination.** The agent reads similar existing code and concludes the work is already present. Common when the feature adds a field/method that parallels an existing one.

2. **Agent ran out of turns.** On large codebases, the agent spends all turns reading context and never reaches the edit phase. It commits whatever incidental changes it made along the way.

3. **Worktree state.** The agent edits files but a git conflict resolution silently reverts the changes. The committed diff contains only the merge resolution, not the feature work.

Possible fixes (mechanical, no LLM call needed in grounding):

- Count non-comment, non-whitespace changed lines. Reject if below a threshold (e.g., fewer than 3 substantive lines for a task with acceptance criteria).
- Compare the number of acceptance criteria to the diff size. A task with 5 criteria and a 2-line diff is suspect.
- Check that at least one file in `files_touched` has a substantive change (not just import reordering or comment edits). The `declared_files` check verifies the files exist but not that they were meaningfully modified.
