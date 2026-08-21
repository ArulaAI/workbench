# Defect: Retried task branch not refreshed against main

Severity: P2
Related Feature: speed-security

## Observed Behavior

When a failed task is retried via `speed retry --task-id <id>`, the task branch stays at the commit it was originally created from. If other tasks completed and merged to main between the original run and the retry, the retried agent's worktree is missing those changes.

Task 3 of `speed-security` demonstrates the problem. Its branch was created from main at `75b8c09` (task-8 merge). By the time retry is needed, main has advanced to `44ee30e` (task-9 merge). The worktree for the retry would be missing `lib/security.sh` and `tests/test_security_audit.sh`, both added by tasks that merged after Task 3's branch was created.

The `git diff main` from the task-3 worktree shows those files as deletions, even though they're unrelated to Task 3's work.

## Expected Behavior

Before creating a worktree for a retried task, the system should merge main into the task branch (or rebase it onto main). The deferred dependency merge in `run.sh:668-726` already brings main up to date with completed dependencies. The missing step is bringing the *task branch itself* up to date with the now-advanced main.

The flow should be:

```
deferred dependency merge (deps → main)   ← exists, works
refresh task branch (main → task branch)   ← missing
git_create_worktree (checkout branch)      ← exists, works
```

## Reproduction Steps

1. Start a feature run with multiple tasks, some with dependencies
2. Task A fails (or hits max turns)
3. Tasks B and C (no dependency on A) complete and merge to main
4. Run `speed retry --task-id A --context "..."` then `speed run`
5. Task A's worktree is created on its old branch, missing B and C's changes

## Additional Context

**Affected code paths:**

- `lib/git.sh:123-161` (`git_create_worktree`) — line 143 checks `git_branch_exists`. For retries, the branch exists, so it does `git worktree add "$worktree_path" "$branch"` without any refresh. First runs are fine because the branch is created from HEAD (which is main after deferred merge).
- `lib/cmd/retry.sh:184-190` (`cmd_retry`) — removes the worktree and resets to pending but does not touch the branch.
- `lib/cmd/run.sh:668-726` — deferred dependency merge brings main up to date but never merges main back into the task branch.

**Existing infrastructure that can be reused:**

`git_safe_merge` (lib/git.sh:248-277) already handles merge with conflict detection and abort. The same function can merge main into the task branch. `MERGE_CONFLICT_MAX_RETRIES` (config.sh:93) already tracks conflict retry limits.

Reproducibility: always
