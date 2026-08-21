# RFC: Salvage Complete Work on Turn Exhaustion

> See [defect report](../defects/turn-exhaustion-loses-complete-work.md) for problem context.

## Basic Example

Task 3 writes 500 lines of code and stages both files. All tests pass. The agent hits the 50-turn limit before committing. Today, the framework runs `gates_run`, grounding check 1 (`grounding_check_diff_nonempty`) sees no commits on the branch, and the task is marked "Quality gates failed."

After this fix:

```
Agent hits max turns → done marker created
  ├─ Framework detects worktree has uncommitted changes
  ├─ Auto-commits staged work: "speed: salvage work from turn-exhausted agent"
  ├─ Runs gates_run against the now-committed changes
  ├─ Gates pass → task marked done
  └─ Gates fail → task marked failed (with accurate error, not "Quality gates failed")
```

The agent's log (`3.log`) contains "Error: Reached max turns (50)". The framework currently doesn't distinguish this from a normal completion. The fix adds a salvage step between agent exit and gate evaluation.

## Root Cause

The completion handler in `run.sh:458-514` follows this path:

1. Agent exits (max turns, blocked, or normal) → done marker created
2. `if [[ -s "$output_file" ]]` — output file has content ("Error: Reached max turns") → enters normal completion
3. `gates_run "$task_id" "$task_worktree"` runs grounding checks
4. `grounding_check_diff_nonempty` calls `git diff main...branch --stat` — sees no *commits*, returns 1
5. Grounding fails → `task_set_failed "$task_id" "Quality gates failed"`

The problem: `git diff main...branch` only sees committed changes. Staged or unstaged changes in the worktree are invisible. When an agent runs out of turns before committing, the work exists in the worktree but grounding checks can't see it.

## Implementation

### New function: `_salvage_worktree_changes()`

Add to `lib/cmd/run.sh` in the helper functions section (near `_classify_task_failure`, line ~147):

```bash
# Check if a task worktree has uncommitted work and commit it.
# Called before gates_run when an agent may have exited early
# (max turns, timeout). Allows grounding checks to evaluate
# the actual work product rather than an empty diff.
#
# Args: task_id worktree_path
# Returns: 0 if changes were salvaged (or none existed), 1 on error
_salvage_worktree_changes() {
    local task_id="$1"
    local worktree_path="$2"

    # Check for staged changes
    local has_staged=false
    if ! git -C "$worktree_path" diff --cached --quiet 2>/dev/null; then
        has_staged=true
    fi

    # Check for unstaged changes to tracked files
    local has_unstaged=false
    if ! git -C "$worktree_path" diff --quiet 2>/dev/null; then
        has_unstaged=true
    fi

    if ! $has_staged && ! $has_unstaged; then
        return 0  # Nothing to salvage
    fi

    log_warn "Task ${task_id}: agent left uncommitted changes in worktree — salvaging"

    # Stage unstaged changes to tracked files (not untracked)
    if $has_unstaged; then
        git -C "$worktree_path" add -u 2>/dev/null || true
    fi

    # Commit
    git -C "$worktree_path" commit -m "speed: salvage work from interrupted agent" 2>/dev/null || {
        log_warn "Task ${task_id}: salvage commit failed"
        return 1
    }

    log_step "Task ${task_id}: salvaged uncommitted work into commit"
    return 0
}
```

Key decisions:

- **`git add -u` only, not `git add -A`.** Stages modifications to tracked files. Does not add untracked files (temp files, debug artifacts). The agent's `files_touched` declaration in the task JSON already lists intended files; untracked junk should not enter the commit.
- **Runs inside the worktree** via `git -C "$worktree_path"`. No checkout of the branch in the main repo needed.

### Modified completion handler in `run.sh`

The change is in the normal completion block, between agent output detection and `gates_run`. Currently (line ~458):

```bash
if [[ -s "$output_file" ]]; then
    log_success "Task ${task_id} agent completed"

    if gates_run "$task_id" "$task_worktree"; then
```

After:

```bash
if [[ -s "$output_file" ]]; then
    log_success "Task ${task_id} agent completed"

    # Salvage any uncommitted work before running gates.
    # Agents that hit max turns or exited early may leave
    # staged changes that grounding checks can't see.
    _salvage_worktree_changes "$task_id" "$task_worktree"

    if gates_run "$task_id" "$task_worktree"; then
```

The salvage runs unconditionally before gates. For agents that committed their own work (normal case), `_salvage_worktree_changes` is a no-op (both `git diff` checks return clean). Cost: two `git diff --quiet` calls per task completion, negligible.

### Improved failure classification

The `3.log` for Task 3 contains "Error: Reached max turns (50)". The framework should detect this pattern and record it distinctly from a genuine gate failure.

Add a max-turns detection check before the gate evaluation:

```bash
if [[ -s "$output_file" ]]; then
    log_success "Task ${task_id} agent completed"

    # Detect max-turns exhaustion for accurate failure classification
    local _max_turns_hit=false
    if grep -q "Reached max turns" "$output_file" 2>/dev/null; then
        _max_turns_hit=true
        log_warn "Task ${task_id}: agent reached max turns"
    fi

    _salvage_worktree_changes "$task_id" "$task_worktree"

    if gates_run "$task_id" "$task_worktree"; then
        task_set_done "$task_id"
        if $_max_turns_hit; then
            log_success "Task ${task_id}: ${COLOR_SUCCESS}DONE${RESET} (salvaged from max-turns exit)"
        else
            log_success "Task ${task_id}: ${COLOR_SUCCESS}DONE${RESET}"
        fi
```

When gates fail after max-turns, use a distinct error message:

```bash
    else
        if $_max_turns_hit; then
            task_set_failed "$task_id" "Max turns reached, gates failed on salvaged work"
        else
            task_set_failed "$task_id" "Quality gates failed"
        fi
```

This gives `speed retry` and the debugger accurate signal. "Max turns reached, gates failed on salvaged work" tells the human: the agent wrote code, but it wasn't good enough to pass. "Quality gates failed" (without the prefix) means the agent completed normally but its output failed checks.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| No uncommitted changes (normal case) | No-op, proceed to gates |
| Staged changes only | Commit them, proceed to gates |
| Staged + unstaged tracked changes | Stage unstaged via `add -u`, commit all, proceed to gates |
| Untracked files in worktree | Ignored (not staged by `add -u`) |
| Salvage commit fails | Log warning, proceed to gates (gates will likely fail on empty diff) |
| Max turns + salvage + gates pass | Task marked done with "(salvaged)" note in log |
| Max turns + salvage + gates fail | Distinct error: "Max turns reached, gates failed on salvaged work" |

## Files Changed

| File | Change |
|------|--------|
| `lib/cmd/run.sh` | Add `_salvage_worktree_changes()` helper; modify completion handler (~line 458) to call salvage before gates; add max-turns detection for failure classification |

## Dependencies

None. Uses standard git commands inside the worktree. No new external tools.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Salvage unconditionally vs. only on max-turns | Unconditionally | Handles edge cases (OOM, SIGTERM) without needing to detect every exit reason. No-op cost is two `git diff --quiet` calls. |
| `git add -u` vs. `git add -A` | `-u` only | Prevents untracked temp files from entering the commit. Agent's declared files should already be tracked. |
| Commit message | Fixed string, no metadata | Simplicity. The task JSON already tracks salvage context (error field, max_turns_hit). |
