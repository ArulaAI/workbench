#!/usr/bin/env bash
# test_grounding_test_coverage_siblings.sh — Tests for sibling-aware test coverage
#
# Verifies _test_files_covered_by_siblings() and its integration with
# grounding_run() Check 6.
#
# Usage: bash tests/test_grounding_test_coverage_siblings.sh
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
    "branch": "${branch_name}",
    "description": "test task ${task_id}",
    "files_touched": ${files_touched_json}
}
EOF
}

# Helper: create a task JSON without a branch (sibling declaration only)
_create_sibling_task() {
    local task_id="$1"
    local status="${2:-pending}"
    shift 2
    local files_touched_json="["
    local first=true
    for file_path in "$@"; do
        if $first; then
            files_touched_json+="\"${file_path}\""
            first=false
        else
            files_touched_json+=", \"${file_path}\""
        fi
    done
    files_touched_json+="]"

    cat > "${TASKS_DIR}/${task_id}.json" <<EOF
{
    "id": "${task_id}",
    "status": "${status}",
    "description": "sibling task ${task_id}",
    "files_touched": ${files_touched_json}
}
EOF
}

# ── Test 1: Sibling covers missing test → 0 (covered) ────────────────────────

test_sibling_covers_missing_test() {
    # Task 1 adds a source file but no test
    _create_task_branch "1" "feat/task-1" "src/components/share/share-panel.tsx"

    # Sibling task 6 declares the test file
    _create_sibling_task "6" "pending" \
        "src/__tests__/components/share/share-panel.test.tsx"

    local rc=0
    _test_files_covered_by_siblings "1" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: expected exit 0 (covered), got ${rc}" >&2
        return 1
    fi
}

# ── Test 2: No sibling coverage → 1 (not covered) ────────────────────────────

test_no_sibling_coverage_fails() {
    # Task 1 adds a source file but no test
    _create_task_branch "1" "feat/task-1" "src/components/share/share-panel.tsx"

    # No sibling tasks exist

    local rc=0
    _test_files_covered_by_siblings "1" || rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: expected non-zero exit (not covered), got 0" >&2
        return 1
    fi
}

# ── Test 3: Failed sibling not counted → 1 (not covered) ─────────────────────

test_failed_sibling_not_counted() {
    # Task 1 adds a source file but no test
    _create_task_branch "1" "feat/task-1" "src/components/share/share-panel.tsx"

    # Sibling task 6 declares the test file but has failed status
    _create_sibling_task "6" "failed" \
        "src/__tests__/components/share/share-panel.test.tsx"

    local rc=0
    _test_files_covered_by_siblings "1" || rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: expected non-zero exit (failed sibling), got 0" >&2
        return 1
    fi
}

# ── Test 4: Cancelled sibling not counted → 1 (not covered) ──────────────────

test_cancelled_sibling_not_counted() {
    _create_task_branch "1" "feat/task-1" "src/components/share/share-panel.tsx"

    _create_sibling_task "6" "cancelled" \
        "src/__tests__/components/share/share-panel.test.tsx"

    local rc=0
    _test_files_covered_by_siblings "1" || rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: expected non-zero exit (cancelled sibling), got 0" >&2
        return 1
    fi
}

# ── Test 5: Sibling with __tests__/ layout matches by basename stem ───────────

test_sibling_tests_dir_layout_matches() {
    # Task 1 adds component in standard dir
    _create_task_branch "1" "feat/task-1" "travel-web/components/share/share-panel.tsx"

    # Sibling declares test in __tests__/ directory (different path)
    _create_sibling_task "7" "pending" \
        "travel-web/__tests__/components/share/share-panel.test.tsx"

    local rc=0
    _test_files_covered_by_siblings "1" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: expected exit 0 (__tests__/ layout match), got ${rc}" >&2
        return 1
    fi
}

# ── Test 6: grounding_run uses sibling fallback → warning, exit 0 ─────────────

test_grounding_run_sibling_coverage_warning() {
    # Task 1 adds a source file but no test
    _create_task_branch "1" "feat/task-1" "src/components/panel.tsx"

    # Sibling covers the test
    _create_sibling_task "6" "pending" \
        "src/components/panel.test.tsx"

    # Stub all checks except test coverage (let it run real)
    grounding_check_diff_nonempty()  { return 0; }
    grounding_check_declared_files() { return 0; }
    grounding_check_scope()          { return 0; }
    grounding_check_python_imports() { return 0; }
    grounding_check_not_blocked()    { return 0; }
    grounding_check_gate_evidence()  { return 0; }
    grounding_check_criteria()       { return 0; }
    grounding_check_secrets()        { return 0; }

    local output rc=0
    output=$(grounding_run "1" "$PROJECT_ROOT" 2>/dev/null) || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: expected exit 0 (warning not failure), got ${rc}" >&2
        echo "    OUTPUT: ${output:0:400}" >&2
        return 1
    fi

    # Should show the warning in output
    if ! echo "$output" | grep -qi "deferred"; then
        echo "    ASSERT: expected 'deferred' in output" >&2
        echo "    OUTPUT: ${output:0:400}" >&2
        return 1
    fi

    # gate_results should have test_coverage as warn
    local tc_status
    tc_status=$(jq -r '[.gate_results.checks[] | select(.name=="test_coverage")] | .[0].status' "${TASKS_DIR}/1.json" 2>/dev/null)
    if [[ "$tc_status" != "warn" ]]; then
        echo "    ASSERT: expected test_coverage status 'warn', got '${tc_status}'" >&2
        return 1
    fi
}

# ── Test 7: No testable files → sibling helper returns 0 ─────────────────────

test_no_testable_files_returns_success() {
    # Task adds only excluded files (config, types, etc.)
    _create_task_branch "1" "feat/task-1" "src/types.ts"

    local rc=0
    _test_files_covered_by_siblings "1" || rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "    ASSERT: expected exit 0 (no testable files), got ${rc}" >&2
        return 1
    fi
}

# ── Test 8: Multiple missing tests, only some covered → not covered ───────────

test_partial_sibling_coverage_fails() {
    # Task adds two source files, no tests
    _create_task_branch "1" "feat/task-1" \
        "src/components/share/share-panel.tsx" \
        "src/components/share/share-modal.tsx"

    # Sibling covers only one
    _create_sibling_task "6" "pending" \
        "src/__tests__/components/share/share-panel.test.tsx"

    local rc=0
    _test_files_covered_by_siblings "1" || rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: expected non-zero exit (partial coverage), got 0" >&2
        return 1
    fi
}

# ── Run all tests ─────────────────────────────────────────────────────────────

echo ""
echo "Grounding test coverage sibling tests"
echo "──────────────────────────────────────"

run_test test_sibling_covers_missing_test
run_test test_no_sibling_coverage_fails
run_test test_failed_sibling_not_counted
run_test test_cancelled_sibling_not_counted
run_test test_sibling_tests_dir_layout_matches
run_test test_grounding_run_sibling_coverage_warning
run_test test_no_testable_files_returns_success
run_test test_partial_sibling_coverage_fails

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
