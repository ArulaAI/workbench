# RFC: Refresh Task Branch on Retry

> See [defect report](../defects/stale-branch-on-retry.md) for problem context.

## Basic Example

Task 3 fails during a `speed-security` run. Tasks 9 and 10 complete and merge to main. The user retries Task 3:

```bash
speed retry --task-id 3 --context "hit max turns, implementation is complete"
speed run
```

Before this fix, the retry worktree is based on `75b8c09` (missing tasks 9/10 work). After this fix, `run.sh` merges main into the task branch before creating the worktree, so the agent sees the full codebase.

```
# Current behavior (broken)
deferred dep merge (deps → main)    ✓
git_create_worktree (old branch)    ← branch at original commit, stale

# Fixed behavior
deferred dep merge (deps → main)    ✓
git_refresh_task_branch (main → branch)   ← NEW
git_create_worktree (refreshed branch)    ✓
```

## Implementation

### New function: `git_refresh_task_branch()`

Add to `lib/git.sh` after `git_create_task_branch()` (line ~117):

```bash
# Merge main into a task branch so retried tasks see all upstream changes.
# No-op if the branch is already up to date with main.
# Args: branch_name
# Returns: 0 on success or already up-to-date, 1 on merge conflict
git_refresh_task_branch() {
    local branch="$1"
    local main
    main=$(git_main_branch)

    # Skip if branch doesn't exist (first run, not a retry)
    git_branch_exists "$branch" || return 0

    # Skip if branch already contains main
    if _git merge-base --is-ancestor "$main" "$branch" 2>/dev/null; then
        return 0
    fi

    # Count how far behind
    local behind
    behind=$(_git rev-list --count "${branch}..${main}" 2>/dev/null)
    log_step "Task branch ${branch} is ${behind} commit(s) behind ${main} — refreshing"

    # Checkout the task branch, merge main into it, return to main
    local prev_branch
    prev_branch=$(git_current_branch)

    if ! _git checkout "$branch" 2>/dev/null; then
        log_error "Cannot checkout ${branch} for refresh"
        return 1
    fi

    local merge_output
    if merge_output=$(_git merge --no-ff "$main" -m "speed: refresh branch against ${main}" 2>&1); then
        log_success "Refreshed ${branch} (merged ${behind} commit(s) from ${main})"
        _git checkout "$prev_branch" 2>/dev/null
        return 0
    else
        log_error "Merge conflict refreshing ${branch} against ${main}"
        _git merge --abort 2>/dev/null || true
        _git checkout "$prev_branch" 2>/dev/null
        return 1
    fi
}
```

Key behaviors:

- **No-op on first run.** `git_branch_exists` returns false for new branches (they're created by `git_create_worktree` via `git worktree add -b`). The refresh only fires for branches that already exist from a prior attempt.
- **No-op when current.** `merge-base --is-ancestor` skips the merge when the branch already contains main's HEAD.
- **Conflict-safe.** On conflict, aborts the merge, restores the previous branch, and returns 1. The caller decides whether to block or defer.

### Call site in `run.sh`

Insert between the deferred dependency merge block (line ~726) and `git_create_worktree` (line ~730):

```bash
# ── Refresh task branch against updated main ───────
# After deferred dep merges advanced main, bring the task
# branch forward so the worktree sees all upstream work.
# Only relevant for retried tasks whose branch already exists.
if ! git_refresh_task_branch "$branch"; then
    _record_merge_attempt "$task_id"
    local refresh_attempts
    refresh_attempts=$(_get_merge_attempts "$task_id")
    if [[ "$refresh_attempts" -ge "$MERGE_CONFLICT_MAX_RETRIES" ]]; then
        task_set_blocked "$task_id" "Merge conflict refreshing branch against ${main_branch} (failed ${refresh_attempts}x)"
        _record_failure "$task_id" "Branch refresh conflict"
    else
        log_warn "Branch refresh failed for task ${task_id} — deferring (attempt ${refresh_attempts}/${MERGE_CONFLICT_MAX_RETRIES})"
    fi
    main_branch_release_lock
    continue
fi
```

The conflict handling reuses `_record_merge_attempt`, `_get_merge_attempts`, and `MERGE_CONFLICT_MAX_RETRIES` from the deferred merge block directly above. After `MERGE_CONFLICT_MAX_RETRIES` (default: 3) failed attempts, the task is blocked and requires manual resolution.

**Lock scope.** The refresh runs while the main-branch lock is held (acquired for the deferred dep merge). The lock is released after `git_create_worktree` on line ~730 or on `continue` if refresh fails. No new lock acquisition needed.

### Staged changes from failed attempts

`cmd_retry` calls `git_remove_worktree` but does not reset the branch. If the previous attempt left staged-but-not-committed changes, those changes are on the branch's index. When `git_refresh_task_branch` checks out the branch and merges main, the staged changes may conflict with the merge.

Handle this by committing staged changes before the merge if the index is dirty:

```bash
# Inside git_refresh_task_branch, after checkout:
if ! _git diff --cached --quiet 2>/dev/null; then
    _git commit -m "speed: save staged work from previous attempt" 2>/dev/null || true
fi
```

This preserves the previous attempt's work. The retried agent will see it in the diff and can build on it rather than starting from scratch.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Branch doesn't exist (first run) | No-op, return 0 |
| Branch already contains main | No-op, return 0 |
| Checkout fails (branch locked by another worktree) | Log error, return 1 |
| Merge conflict | Abort merge, restore previous branch, return 1 |
| Merge conflict after max retries | Task set to `blocked`, requires manual resolution |
| Staged changes from prior attempt | Auto-committed before merge |

## Files Changed

| File | Change |
|------|--------|
| `lib/git.sh` | Add `git_refresh_task_branch()` after `git_create_task_branch()` |
| `lib/cmd/run.sh` | Add refresh call + conflict handling between deferred merge and `git_create_worktree` (~line 727) |

## Dependencies

None. Uses existing `git_safe_merge` patterns, `_record_merge_attempt`, and `MERGE_CONFLICT_MAX_RETRIES`. Pure bash, no new external tools.
