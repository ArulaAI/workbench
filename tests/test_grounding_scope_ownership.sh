#!/usr/bin/env bash
# test_grounding_scope_ownership.sh — Tests for ownership detection in grounding_check_scope()
#
# Verifies Change B (reviewer merge conflict fix): grounding_check_scope()
# returns exit 1 when a developer modifies a file owned by another task,
# and grounding_run() propagates this as a hard failure.
#
# Usage: bash tests/test_grounding_scope_ownership.sh
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
    mkdir -p "$TASKS_DIR" "$LOGS_DIR"

    # Git helpers
    _git() { git -C "$PROJECT_ROOT" "$@"; }
    git_main_branch() { echo "main"; }

    # Source grounding.sh
    unset _GROUNDING_SH_LOADED 2>/dev/null || true
    # shellcheck source=../lib/grounding.sh
    source "${LIB_DIR}/grounding.sh"
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

assert_output_contains() {
    local output="$1" pattern="$2"
    if ! echo "$output" | grep -q "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:400}" >&2
        return 1
    fi
}

assert_output_not_contains() {
    local output="$1" pattern="$2"
    if echo "$output" | grep -q "$pattern"; then
        echo "    ASSERT: output should NOT contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:400}" >&2
        return 1
    fi
}

# Helper: create a branch with files and write the task JSON
_create_task_branch() {
    local task_id="$1"
    local branch_name="$2"
    shift 2
    # Remaining args are file paths
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
    "branch": "${branch_name}",
    "description": "test task ${task_id}",
    "files_touched": ${files_touched_json}
}
EOF
}

# ── Test 1: All files match declarations → exit 0 ────────────────────────────

test_all_files_declared_passes() {
    _create_task_branch "1" "feat/task-1" "src/app.py" "src/utils.py"

    local output rc=0
    output=$(grounding_check_scope "1") || rc=$?

    assert_exit_code "0" "$rc" "all files declared should pass"
}

# ── Test 2: Undeclared file, not owned by anyone → exit 2 ────────────────────

test_undeclared_unowned_file_warns() {
    # Task declares src/app.py but branch also has src/helper.py
    _create_task_branch "1" "feat/task-1" "src/app.py"

    # Add an extra file not in files_touched
    echo "// helper" > "$PROJECT_ROOT/src/helper.py"
    git -C "$PROJECT_ROOT" add src/helper.py
    git -C "$PROJECT_ROOT" commit -m "add undeclared helper" --quiet

    local output rc=0
    output=$(grounding_check_scope "1") || rc=$?

    assert_exit_code "2" "$rc" "undeclared unowned file should return exit 2"
    assert_output_contains "$output" "src/helper.py"
}

# ── Test 3: Undeclared file owned by another task → exit 1 ───────────────────

test_file_owned_by_another_task_fails() {
    # Task 1 owns whatsapp-link.tsx
    _create_task_branch "1" "feat/task-1" "src/whatsapp-link.tsx"

    # Task 3 declares page.tsx but also modifies whatsapp-link.tsx
    _create_task_branch "3" "feat/task-3" "src/page.tsx"
    echo "// modified by task 3" > "$PROJECT_ROOT/src/whatsapp-link.tsx"
    git -C "$PROJECT_ROOT" add src/whatsapp-link.tsx
    git -C "$PROJECT_ROOT" commit -m "task 3 touches task 1 file" --quiet

    local output rc=0
    output=$(grounding_check_scope "3") || rc=$?

    assert_exit_code "1" "$rc" "file owned by another task should return exit 1"
    assert_output_contains "$output" "src/whatsapp-link.tsx"
    assert_output_contains "$output" "task 1"
}

# ── Test 4: Mix of owned and unowned undeclared files → exit 1 ───────────────
# Ownership violations take priority over unowned undeclared files.

test_mixed_ownership_and_undeclared_fails() {
    # Task 1 owns component.tsx
    _create_task_branch "1" "feat/task-1" "src/component.tsx"

    # Task 2 declares page.tsx but also modifies component.tsx and helper.py
    _create_task_branch "2" "feat/task-2" "src/page.tsx"
    echo "// modified" > "$PROJECT_ROOT/src/component.tsx"
    echo "// new helper" > "$PROJECT_ROOT/src/helper.py"
    git -C "$PROJECT_ROOT" add src/component.tsx src/helper.py
    git -C "$PROJECT_ROOT" commit -m "task 2 touches extra files" --quiet

    local output rc=0
    output=$(grounding_check_scope "2") || rc=$?

    # Ownership violation takes priority (exit 1 returned before exit 2)
    assert_exit_code "1" "$rc" "ownership violation should take priority"
    assert_output_contains "$output" "src/component.tsx"
    assert_output_contains "$output" "task 1"
}

# ── Test 5: No files_touched declared → exit 0 (early return) ────────────────

test_no_files_touched_passes() {
    git -C "$PROJECT_ROOT" checkout -b "feat/no-decl" --quiet
    mkdir -p "$PROJECT_ROOT/src"
    echo "// code" > "$PROJECT_ROOT/src/anything.py"
    git -C "$PROJECT_ROOT" add src/anything.py
    git -C "$PROJECT_ROOT" commit -m "add file" --quiet

    # Task with no files_touched
    cat > "${TASKS_DIR}/4.json" <<EOF
{
    "id": "4",
    "branch": "feat/no-decl",
    "description": "task with no declarations"
}
EOF

    local output rc=0
    output=$(grounding_check_scope "4") || rc=$?

    assert_exit_code "0" "$rc" "no files_touched should pass (can't check scope)"
}

# ── Test 6: grounding_run() propagates exit 1 as hard failure ────────────────

test_grounding_run_ownership_hard_failure() {
    # Task 1 owns whatsapp-link.tsx
    _create_task_branch "1" "feat/task-1" "src/whatsapp-link.tsx"

    # Task 3 declares page.tsx but also modifies whatsapp-link.tsx
    _create_task_branch "3" "feat/task-3" "src/page.tsx"
    echo "// modified by task 3" > "$PROJECT_ROOT/src/whatsapp-link.tsx"
    git -C "$PROJECT_ROOT" add src/whatsapp-link.tsx
    git -C "$PROJECT_ROOT" commit -m "task 3 touches task 1 file" --quiet

    # Stub all checks except scope
    grounding_check_diff_nonempty()  { return 0; }
    grounding_check_declared_files() { return 0; }
    grounding_check_python_imports() { return 0; }
    grounding_check_not_blocked()    { return 0; }
    grounding_check_test_coverage()  { return 0; }
    grounding_check_gate_evidence()  { return 0; }
    grounding_check_criteria()       { return 0; }
    grounding_check_secrets()        { return 0; }

    local output rc=0
    output=$(grounding_run "3" "$PROJECT_ROOT" 2>/dev/null) || rc=$?

    assert_exit_code "1" "$rc" "grounding_run should fail on ownership violation"
    assert_output_contains "$output" "owned by another task"
}

# ── Test 7: File owned by self (same task) stays on exit 0 path ──────────────

test_file_owned_by_self_passes() {
    _create_task_branch "1" "feat/task-1" "src/app.py" "src/utils.py"

    local output rc=0
    output=$(grounding_check_scope "1") || rc=$?

    assert_exit_code "0" "$rc" "files owned by self should pass"
}

# ── Test 8: grounding_run persists gate_results to task JSON ──────────────────

test_grounding_run_persists_gate_results() {
    _create_task_branch "1" "feat/task-1" "src/app.py"

    # Stub all checks to pass
    grounding_check_diff_nonempty()  { return 0; }
    grounding_check_declared_files() { return 0; }
    grounding_check_python_imports() { return 0; }
    grounding_check_not_blocked()    { return 0; }
    grounding_check_test_coverage()  { return 0; }
    grounding_check_gate_evidence()  { return 0; }
    grounding_check_criteria()       { return 0; }
    grounding_check_secrets()        { return 0; }

    grounding_run "1" "$PROJECT_ROOT" >/dev/null 2>&1 || true

    # Task JSON should now have gate_results
    local has_gate_results
    has_gate_results=$(jq 'has("gate_results")' "${TASKS_DIR}/1.json")
    [[ "$has_gate_results" == "true" ]] || { echo "    ASSERT: gate_results missing from task JSON" >&2; return 1; }

    # gate_results.checks should be a non-empty array
    local checks_len
    checks_len=$(jq '.gate_results.checks | length' "${TASKS_DIR}/1.json")
    [[ "$checks_len" -gt 0 ]] || { echo "    ASSERT: gate_results.checks is empty" >&2; return 1; }
}

# ── Test 9: gate_results includes ownership_violations on scope failure ───────

test_gate_results_has_ownership_violations() {
    # Task 1 owns whatsapp-link.tsx
    _create_task_branch "1" "feat/task-1" "src/whatsapp-link.tsx"

    # Task 3 declares page.tsx but also modifies whatsapp-link.tsx
    _create_task_branch "3" "feat/task-3" "src/page.tsx"
    echo "// modified by task 3" > "$PROJECT_ROOT/src/whatsapp-link.tsx"
    git -C "$PROJECT_ROOT" add src/whatsapp-link.tsx
    git -C "$PROJECT_ROOT" commit -m "task 3 touches task 1 file" --quiet

    # Stub all checks except scope
    grounding_check_diff_nonempty()  { return 0; }
    grounding_check_declared_files() { return 0; }
    grounding_check_python_imports() { return 0; }
    grounding_check_not_blocked()    { return 0; }
    grounding_check_test_coverage()  { return 0; }
    grounding_check_gate_evidence()  { return 0; }
    grounding_check_criteria()       { return 0; }
    grounding_check_secrets()        { return 0; }

    grounding_run "3" "$PROJECT_ROOT" >/dev/null 2>&1 || true

    # gate_results.scope should have ownership_violations
    local ov_len
    ov_len=$(jq '.gate_results.scope.ownership_violations | length' "${TASKS_DIR}/3.json" 2>/dev/null)
    [[ "$ov_len" -gt 0 ]] || { echo "    ASSERT: ownership_violations not in gate_results.scope" >&2; return 1; }

    # The scope check entry should also have ownership_violations
    local scope_check_ov
    scope_check_ov=$(jq '[.gate_results.checks[] | select(.name=="scope")] | .[0].ownership_violations | length' "${TASKS_DIR}/3.json" 2>/dev/null)
    [[ "$scope_check_ov" -gt 0 ]] || { echo "    ASSERT: ownership_violations not in scope check entry" >&2; return 1; }
}

# ── Run all tests ─────────────────────────────────────────────────────────────

echo ""
echo "Grounding scope ownership tests"
echo "──────────────────────────────────────"

run_test test_all_files_declared_passes
run_test test_undeclared_unowned_file_warns
run_test test_file_owned_by_another_task_fails
run_test test_mixed_ownership_and_undeclared_fails
run_test test_no_files_touched_passes
run_test test_grounding_run_ownership_hard_failure
run_test test_file_owned_by_self_passes
run_test test_grounding_run_persists_gate_results
run_test test_gate_results_has_ownership_violations

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
