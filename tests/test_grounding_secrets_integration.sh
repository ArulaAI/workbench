#!/usr/bin/env bash
# test_grounding_secrets_integration.sh — Integration tests for grounding_check_secrets
# wired into grounding_run()
#
# Verifies that grounding_run() calls grounding_check_secrets, propagates its
# result into the results array, and sets all_passed=false on detection.
#
# Usage: bash tests/test_grounding_secrets_integration.sh
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

    # Color/symbol stubs (grounding_run uses these in result messages)
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" COLOR_STEP=""
    BOLD="" RESET="" SYM_CHECK="" SYM_CROSS="" SYM_WARN="" SYM_ARROW=""
    VERBOSITY=0

    # Logging stubs
    log_error() { :; }
    log_warn()  { :; }
    log_step()  { :; }
    log_success() { :; }

    # _context_python stub (used by grounding_check_criteria internals)
    _context_python() { echo "python3"; }

    # Set up a temporary git repo
    export PROJECT_ROOT="$TEST_DIR/repo"
    mkdir -p "$PROJECT_ROOT"
    git -C "$PROJECT_ROOT" init -b main --quiet
    git -C "$PROJECT_ROOT" config user.email "test@test.com"
    git -C "$PROJECT_ROOT" config user.name "Test"

    # Initial commit on main so the diff base exists
    echo "init" > "$PROJECT_ROOT/README.md"
    git -C "$PROJECT_ROOT" add README.md
    git -C "$PROJECT_ROOT" commit -m "init" --quiet

    # SPEED directory structure
    export STATE_DIR="${PROJECT_ROOT}/.speed"
    export FEATURES_DIR="${STATE_DIR}/features"
    export TASKS_DIR="${STATE_DIR}/tasks"
    export LOGS_DIR="${STATE_DIR}/logs"
    mkdir -p "$TASKS_DIR" "$LOGS_DIR"

    # No custom exclusion override by default
    unset TOML_SECURITY_SECRETS_EXCLUDE 2>/dev/null || true

    # Git helpers (match lib/git.sh conventions)
    _git() { git -C "$PROJECT_ROOT" "$@"; }
    git_main_branch() { echo "main"; }

    # Source grounding.sh
    unset _GROUNDING_SH_LOADED 2>/dev/null || true
    # shellcheck source=../lib/grounding.sh
    source "${LIB_DIR}/grounding.sh"

    # Stub every check except grounding_check_secrets so that any pass/fail
    # in grounding_run() comes exclusively from the secrets scanner.
    grounding_check_diff_nonempty()  { return 0; }
    grounding_check_declared_files() { return 0; }
    grounding_check_scope()          { return 0; }
    grounding_check_python_imports() { return 0; }
    grounding_check_not_blocked()    { return 0; }
    grounding_check_test_coverage()  { return 0; }
    grounding_check_gate_evidence()  { return 0; }
    grounding_check_criteria()       { return 0; }
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

# Helper: create a feature branch with one file and write the task JSON.
_create_branch_with_file() {
    local branch_name="$1"
    local file_path="$2"
    local file_content="$3"
    local task_id="${4:-test-task}"

    git -C "$PROJECT_ROOT" checkout -b "$branch_name" --quiet
    mkdir -p "$(dirname "$PROJECT_ROOT/$file_path")"
    printf '%s\n' "$file_content" > "$PROJECT_ROOT/$file_path"
    git -C "$PROJECT_ROOT" add "$file_path"
    git -C "$PROJECT_ROOT" commit -m "add $file_path" --quiet

    cat > "${TASKS_DIR}/${task_id}.json" <<EOF
{
    "id": "${task_id}",
    "branch": "${branch_name}",
    "description": "test task"
}
EOF
}

# ── Test 1: Clean run ─────────────────────────────────────────────────────────
# A feature branch with no secrets should cause grounding_run() to pass and
# include "No committed secrets" in the printed results.

test_clean_run_passes() {
    _create_branch_with_file "feat/clean" "src/app.py" \
        'def hello(): return "world"'

    local output rc=0
    output=$(grounding_run "test-task" "$PROJECT_ROOT" 2>/dev/null) || rc=$?

    assert_exit_code "0" "$rc" "grounding_run should pass for clean files"
    assert_output_contains "$output" "No committed secrets"
}

# ── Test 2: Secret detected ───────────────────────────────────────────────────
# An AWS key pattern in a non-excluded file must cause grounding_run() to
# return 1 and include the pipeline-blocked message in the results output.

test_secret_detected_blocks_grounding() {
    _create_branch_with_file "feat/aws-secret" "src/config.py" \
        'AWS_KEY = "AKIA1234567890ABCDEF"'

    local output rc=0
    output=$(grounding_run "test-task" "$PROJECT_ROOT" 2>/dev/null) || rc=$?

    assert_exit_code "1" "$rc" "grounding_run should fail when AWS key is present"
    assert_output_contains "$output" "Committed secrets detected"
}

# ── Test 3: Excluded file ─────────────────────────────────────────────────────
# A .env.test file matches the default .env* exclusion pattern, so secrets
# within it should not trigger a grounding failure.

test_excluded_env_file_passes() {
    git -C "$PROJECT_ROOT" checkout -b "feat/env-excl" --quiet
    printf '%s\n' 'AWS_KEY=AKIA1234567890ABCDEF' > "$PROJECT_ROOT/.env.test"
    git -C "$PROJECT_ROOT" add .env.test
    git -C "$PROJECT_ROOT" commit -m "add .env.test with secret" --quiet

    cat > "${TASKS_DIR}/test-task.json" <<EOF
{
    "id": "test-task",
    "branch": "feat/env-excl",
    "description": "test task"
}
EOF

    local output rc=0
    output=$(grounding_run "test-task" "$PROJECT_ROOT" 2>/dev/null) || rc=$?

    assert_exit_code "0" "$rc" "grounding_run should pass when secret is in excluded .env.test"
    assert_output_contains "$output" "No committed secrets"
}

# ── Run all tests ─────────────────────────────────────────────────────────────

echo ""
echo "Grounding secrets integration tests"
echo "──────────────────────────────────────"

run_test test_clean_run_passes
run_test test_secret_detected_blocks_grounding
run_test test_excluded_env_file_passes

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
