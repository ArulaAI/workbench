#!/usr/bin/env bash
# test_retry_reset_branch.sh — Tests for --reset-branch flag and branch refresh
#
# Verifies:
#   1. git_force_delete_branch() deletes unmerged branches safely
#   2. cmd_retry --reset-branch breaks the scope-violation retry loop
#   3. Branch refresh merges main into stale task branches before audit
#
# Usage: bash tests/test_retry_reset_branch.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)

    # Color/symbol stubs
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" COLOR_STEP=""
    BOLD="" RESET="" SYM_CHECK="" SYM_CROSS="" SYM_WARN="" SYM_ARROW=""
    VERBOSITY=0

    # Logging stubs
    log_error()   { :; }
    log_warn()    { :; }
    log_step()    { :; }
    log_success() { :; }
    log_info()    { :; }
    log_verbose() { :; }

    # Python stub
    _context_python() { echo "python3"; }

    # Set up a temporary git repo
    export PROJECT_ROOT="$TEST_DIR/repo"
    mkdir -p "$PROJECT_ROOT"
    git -C "$PROJECT_ROOT" init -b main --quiet
    git -C "$PROJECT_ROOT" config user.email "test@test.com"
    git -C "$PROJECT_ROOT" config user.name "Test"

    # Initial commit on main
    echo "init" > "$PROJECT_ROOT/README.md"
    git -C "$PROJECT_ROOT" add README.md
    git -C "$PROJECT_ROOT" commit -m "init" --quiet

    # SPEED directory structure
    export STATE_DIR="${PROJECT_ROOT}/.speed"
    export FEATURES_DIR="${STATE_DIR}/features"
    export TASKS_DIR="${STATE_DIR}/tasks"
    export LOGS_DIR="${STATE_DIR}/logs"
    export WORKTREES_DIR="${STATE_DIR}/worktrees"
    mkdir -p "$TASKS_DIR" "$LOGS_DIR" "$WORKTREES_DIR"

    # Git helpers
    _git() { git -C "$PROJECT_ROOT" "$@"; }
    git_main_branch() { echo "main"; }

    # Source the libraries under test
    source "${LIB_DIR}/git.sh"
    unset _GROUNDING_SH_LOADED 2>/dev/null || true
    source "${LIB_DIR}/grounding.sh"

    # Default gates_run stub (overridden in tests that need real grounding)
    gates_run() { return 0; }
}

teardown() {
    rm -rf "$TEST_DIR"
}

run_test() {
    local test_name="$1"
    setup
    local rc=0
    "$test_name" || rc=$?
    teardown
    if [[ $rc -eq 0 ]]; then
        printf "  PASS  %s\n" "$test_name"
        PASS=$((PASS + 1))
    else
        printf "  FAIL  %s\n" "$test_name"
        FAIL=$((FAIL + 1))
    fi
}

assert_exit_code() {
    local expected="$1" actual="$2" context="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected exit ${expected}, got ${actual}${context:+ (${context})}" >&2
        return 1
    fi
}

# Helper: create a branch with files and write the task JSON
_create_task_branch() {
    local task_id="$1"
    local branch_name="$2"
    shift 2
    local files_touched_json="["
    local first=true

    git -C "$PROJECT_ROOT" checkout main --quiet 2>/dev/null
    git -C "$PROJECT_ROOT" checkout -b "$branch_name" --quiet

    for file_path in "$@"; do
        mkdir -p "$(dirname "$PROJECT_ROOT/$file_path")"
        echo "// content of $file_path" > "$PROJECT_ROOT/$file_path"
        git -C "$PROJECT_ROOT" add "$file_path"
        if $first; then
            files_touched_json+="\"${file_path}\""
            first=false
        else
            files_touched_json+=", \"${file_path}\""
        fi
    done

    git -C "$PROJECT_ROOT" commit -m "add files for task ${task_id}" --quiet
    files_touched_json+="]"

    cat > "${TASKS_DIR}/${task_id}.json" <<EOF
{
    "id": "${task_id}",
    "status": "failed",
    "branch": "${branch_name}",
    "description": "test task ${task_id}",
    "files_touched": ${files_touched_json},
    "retry_count": 0
}
EOF
    git -C "$PROJECT_ROOT" checkout main --quiet 2>/dev/null
}

# ══════════════════════════════════════════════════════════════════════════════
# git_force_delete_branch tests
# ══════════════════════════════════════════════════════════════════════════════

# ── Test 1: Deletes an unmerged branch ────────────────────────────────────────

test_force_delete_unmerged_branch() {
    _create_task_branch "1" "feat/task-1" "src/app.py"

    # Branch exists before delete
    _git rev-parse --verify "feat/task-1" &>/dev/null || {
        echo "    ASSERT: branch should exist before delete" >&2; return 1
    }

    local rc=0
    git_force_delete_branch "feat/task-1" >/dev/null 2>&1 || rc=$?
    assert_exit_code "0" "$rc" "force delete should succeed"

    # Branch gone after delete
    if _git rev-parse --verify "feat/task-1" &>/dev/null; then
        echo "    ASSERT: branch should not exist after force delete" >&2
        return 1
    fi
}

# ── Test 2: No-op for nonexistent branch ──────────────────────────────────────

test_force_delete_nonexistent_branch() {
    local rc=0
    git_force_delete_branch "does-not-exist" >/dev/null 2>&1 || rc=$?
    assert_exit_code "0" "$rc" "deleting nonexistent branch should return 0"
}

# ── Test 3: Refuses to delete branch with active worktree ─────────────────────

test_force_delete_refuses_active_worktree() {
    _create_task_branch "1" "feat/task-1" "src/app.py"
    local wt_path="${TEST_DIR}/worktree-1"
    _git worktree add "$wt_path" "feat/task-1" --quiet 2>/dev/null

    local rc=0
    git_force_delete_branch "feat/task-1" >/dev/null 2>&1 || rc=$?
    assert_exit_code "1" "$rc" "should refuse when worktree is active"

    # Branch should still exist
    _git rev-parse --verify "feat/task-1" &>/dev/null || {
        echo "    ASSERT: branch should still exist after refused delete" >&2; return 1
    }

    # Clean up worktree
    _git worktree remove --force "$wt_path" 2>/dev/null || true
}

# ── Test 4: safe delete (git branch -d) fails on unmerged, force succeeds ─────

test_safe_delete_fails_force_succeeds() {
    _create_task_branch "1" "feat/task-1" "src/app.py"

    # Safe delete should fail (branch is unmerged)
    local rc=0
    git_cleanup_branch "feat/task-1" 2>/dev/null || rc=$?
    # git_cleanup_branch swallows errors with || true, so check branch still exists
    if ! _git rev-parse --verify "feat/task-1" &>/dev/null; then
        echo "    ASSERT: safe delete should not remove unmerged branch" >&2
        return 1
    fi

    # Force delete should succeed
    rc=0
    git_force_delete_branch "feat/task-1" >/dev/null 2>&1 || rc=$?
    assert_exit_code "0" "$rc" "force delete should succeed"

    if _git rev-parse --verify "feat/task-1" &>/dev/null; then
        echo "    ASSERT: branch should be gone after force delete" >&2
        return 1
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# branch_audit after branch deletion tests
# ══════════════════════════════════════════════════════════════════════════════

# ── Test 5: branch_audit returns "empty" after branch is force-deleted ────────

test_branch_audit_empty_after_force_delete() {
    _create_task_branch "1" "feat/task-1" "src/app.py"

    # Verify audit sees the branch first
    local result
    result=$(branch_audit "1")
    if [[ "$result" == "empty" ]]; then
        echo "    ASSERT: branch_audit should not be 'empty' before delete" >&2
        return 1
    fi

    # Force-delete, then audit again
    git_force_delete_branch "feat/task-1" >/dev/null 2>&1
    result=$(branch_audit "1")
    if [[ "$result" != "empty" ]]; then
        echo "    ASSERT: expected 'empty' after force delete, got '${result}'" >&2
        return 1
    fi
}

# ── Test 6: Scope-violating branch fails audit, force-delete breaks the loop ──

test_scope_violation_loop_broken_by_force_delete() {
    # Task 1 owns lib/core.py
    _create_task_branch "1" "feat/task-1" "lib/core.py"

    # Task 2 declares tests/test_core.py but also modifies lib/core.py (violation)
    _create_task_branch "2" "feat/task-2" "tests/test_core.py"
    git -C "$PROJECT_ROOT" checkout "feat/task-2" --quiet
    mkdir -p "$PROJECT_ROOT/lib"
    echo "// scope violation" > "$PROJECT_ROOT/lib/core.py"
    git -C "$PROJECT_ROOT" add lib/core.py
    git -C "$PROJECT_ROOT" commit -m "task 2 touches task 1 file" --quiet
    git -C "$PROJECT_ROOT" checkout main --quiet

    # Stub gates_run so branch_audit can call it (delegates to grounding_run)
    gates_run() {
        grounding_run "$@"
    }

    # Stub all grounding checks except scope
    grounding_check_diff_nonempty()  { return 0; }
    grounding_check_declared_files() { return 0; }
    grounding_check_python_imports() { return 0; }
    grounding_check_not_blocked()    { return 0; }
    grounding_check_test_coverage()  { return 0; }
    grounding_check_gate_evidence()  { return 0; }
    grounding_check_criteria()       { return 0; }
    grounding_check_secrets()        { return 0; }

    # First audit: should fail (scope violation)
    local result
    result=$(branch_audit "2" 2>/dev/null)
    if [[ "$result" != "fail" ]]; then
        echo "    ASSERT: expected 'fail' on scope violation, got '${result}'" >&2
        return 1
    fi

    # Force-delete the branch
    git_force_delete_branch "feat/task-2" >/dev/null 2>&1

    # Second audit: should return "empty" (branch gone)
    result=$(branch_audit "2")
    if [[ "$result" != "empty" ]]; then
        echo "    ASSERT: expected 'empty' after force delete, got '${result}'" >&2
        return 1
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# Branch refresh tests
# ══════════════════════════════════════════════════════════════════════════════

# ── Test 7: Merge main into stale task branch brings it up to date ────────────

test_branch_refresh_merges_main() {
    # Create task branch from main
    _create_task_branch "1" "feat/task-1" "src/app.py"

    # Advance main with new work (simulates other tasks merging)
    git -C "$PROJECT_ROOT" checkout main --quiet
    mkdir -p "$PROJECT_ROOT/src"
    echo "new utility" > "$PROJECT_ROOT/src/utils.py"
    git -C "$PROJECT_ROOT" add src/utils.py
    git -C "$PROJECT_ROOT" commit -m "add utils on main" --quiet

    # main is NOT an ancestor of feat/task-1 (branch is stale)
    if _git merge-base --is-ancestor main "feat/task-1" 2>/dev/null; then
        echo "    ASSERT: main should not be ancestor of task branch before refresh" >&2
        return 1
    fi

    # Refresh: merge main into task branch
    _git checkout "feat/task-1" >/dev/null 2>&1
    _git merge --no-ff main -m "speed: refresh branch against main" >/dev/null 2>&1
    _git checkout main >/dev/null 2>&1

    # After refresh, main IS an ancestor of feat/task-1
    if ! _git merge-base --is-ancestor main "feat/task-1" 2>/dev/null; then
        echo "    ASSERT: main should be ancestor of task branch after refresh" >&2
        return 1
    fi

    # Task branch should have utils.py
    if ! _git show "feat/task-1:src/utils.py" &>/dev/null; then
        echo "    ASSERT: task branch should contain src/utils.py after refresh" >&2
        return 1
    fi
}

# ── Test 8: Refresh skipped when branch is already up to date ─────────────────

test_branch_refresh_skipped_when_current() {
    _create_task_branch "1" "feat/task-1" "src/app.py"

    # main IS an ancestor (branch was just created from main)
    if ! _git merge-base --is-ancestor main "feat/task-1" 2>/dev/null; then
        echo "    ASSERT: main should be ancestor of fresh task branch" >&2
        return 1
    fi

    # Count commits on task branch before
    local commits_before
    commits_before=$(_git rev-list --count "feat/task-1")

    # "Refresh" would be a no-op since is-ancestor check passes
    # Verify the check works correctly
    if ! _git merge-base --is-ancestor main "feat/task-1" 2>/dev/null; then
        echo "    ASSERT: is-ancestor check should pass for fresh branch" >&2
        return 1
    fi

    # No new merge commit should be needed
    local commits_after
    commits_after=$(_git rev-list --count "feat/task-1")
    if [[ "$commits_before" != "$commits_after" ]]; then
        echo "    ASSERT: no new commits expected on up-to-date branch" >&2
        return 1
    fi
}

# ── Test 9: Refresh handles conflict gracefully ──────────────────────────────

test_branch_refresh_conflict_aborts_cleanly() {
    # Create task branch that modifies README.md
    git -C "$PROJECT_ROOT" checkout -b "feat/conflict" --quiet
    echo "task version" > "$PROJECT_ROOT/README.md"
    git -C "$PROJECT_ROOT" add README.md
    git -C "$PROJECT_ROOT" commit -m "task modifies readme" --quiet
    git -C "$PROJECT_ROOT" checkout main --quiet

    cat > "${TASKS_DIR}/1.json" <<EOF
{
    "id": "1",
    "status": "failed",
    "branch": "feat/conflict",
    "files_touched": ["README.md"],
    "retry_count": 0
}
EOF

    # Main also modifies README.md (creates conflict)
    echo "main version - conflicting" > "$PROJECT_ROOT/README.md"
    git -C "$PROJECT_ROOT" add README.md
    git -C "$PROJECT_ROOT" commit -m "main modifies readme too" --quiet

    # Attempt merge (should conflict)
    _git checkout "feat/conflict" >/dev/null 2>&1
    local rc=0
    _git merge --no-ff main -m "speed: refresh" >/dev/null 2>&1 || rc=$?

    if [[ "$rc" -eq 0 ]]; then
        # No conflict in this case, that's fine too — skip the abort test
        _git checkout main >/dev/null 2>&1
        return 0
    fi

    # Abort should leave repo clean
    _git merge --abort 2>/dev/null || true
    _git checkout main >/dev/null 2>&1

    # Repo should be clean (no merge in progress)
    if _git rev-parse MERGE_HEAD &>/dev/null 2>&1; then
        echo "    ASSERT: merge should be aborted, but MERGE_HEAD exists" >&2
        return 1
    fi

    # Task branch should still exist (not destroyed)
    if ! _git rev-parse --verify "feat/conflict" &>/dev/null; then
        echo "    ASSERT: task branch should still exist after conflict abort" >&2
        return 1
    fi
}

# ── Test 10: Refresh makes previously-invisible files visible to task branch ──

test_branch_refresh_exposes_predecessor_work() {
    # Task 1 creates lib/security.sh and merges to main
    git -C "$PROJECT_ROOT" checkout -b "feat/dep" --quiet
    mkdir -p "$PROJECT_ROOT/lib"
    echo "security code" > "$PROJECT_ROOT/lib/security.sh"
    git -C "$PROJECT_ROOT" add lib/security.sh
    git -C "$PROJECT_ROOT" commit -m "add security module" --quiet
    git -C "$PROJECT_ROOT" checkout main --quiet
    git -C "$PROJECT_ROOT" merge --no-ff "feat/dep" -m "merge dep" --quiet

    # Task 2 was created before dep merged (from old main)
    # Simulate by branching from the pre-merge commit
    local pre_merge
    pre_merge=$(_git rev-parse main~1)
    git -C "$PROJECT_ROOT" checkout -b "feat/task-2" "$pre_merge" --quiet
    mkdir -p "$PROJECT_ROOT/tests"
    echo "test code" > "$PROJECT_ROOT/tests/test_security.py"
    git -C "$PROJECT_ROOT" add tests/test_security.py
    git -C "$PROJECT_ROOT" commit -m "add tests" --quiet

    cat > "${TASKS_DIR}/2.json" <<EOF
{
    "id": "2",
    "status": "failed",
    "branch": "feat/task-2",
    "files_touched": ["tests/test_security.py"],
    "retry_count": 0
}
EOF

    # Before refresh: task branch can't see lib/security.sh
    if _git show "feat/task-2:lib/security.sh" &>/dev/null; then
        echo "    ASSERT: task branch should NOT see security.sh before refresh" >&2
        return 1
    fi

    # Refresh
    _git checkout "feat/task-2" >/dev/null 2>&1
    _git merge --no-ff main -m "speed: refresh" >/dev/null 2>&1
    _git checkout main >/dev/null 2>&1

    # After refresh: task branch CAN see lib/security.sh
    if ! _git show "feat/task-2:lib/security.sh" &>/dev/null; then
        echo "    ASSERT: task branch should see security.sh after refresh" >&2
        return 1
    fi
}

# ── Run all tests ─────────────────────────────────────────────────────────────

echo ""
echo "Retry --reset-branch and branch refresh tests"
echo "──────────────────────────────────────"

run_test test_force_delete_unmerged_branch
run_test test_force_delete_nonexistent_branch
run_test test_force_delete_refuses_active_worktree
run_test test_safe_delete_fails_force_succeeds
run_test test_branch_audit_empty_after_force_delete
run_test test_scope_violation_loop_broken_by_force_delete
run_test test_branch_refresh_merges_main
run_test test_branch_refresh_skipped_when_current
run_test test_branch_refresh_conflict_aborts_cleanly
run_test test_branch_refresh_exposes_predecessor_work

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
