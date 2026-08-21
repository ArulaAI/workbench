#!/usr/bin/env bash
# test_defect_review.sh — Unit tests for lib/defect_review.sh
#
# Tests check_guardian_threshold, review_defect_fix state handling,
# integrate_defect state validation, and _review_revert_to_fixed.
#
# Agent-dependent functions (review_defect_fix, run_defect_guardian) are
# tested for state transitions and error paths using stubs rather than
# calling live agents.
#
# Usage: bash tests/test_defect_review.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)

    export SPEED_PROJECT_ROOT="$TEST_DIR"
    export VERBOSITY=0

    # Source required libraries
    # shellcheck disable=SC1090
    source "${LIB_DIR}/config.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/log.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/git.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/defects.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/defect_review.sh"

    mkdir -p "${TEST_DIR}/.speed/defects"
    mkdir -p "${TEST_DIR}/specs/defects"

    # Initialize a bare git repo for diff operations
    git -C "$TEST_DIR" init -q
    git -C "$TEST_DIR" commit --allow-empty -m "Initial commit" -q
}

teardown() {
    rm -rf "$TEST_DIR"
    unset SPEED_PROJECT_ROOT
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

assert_eq() {
    local expected="$1" actual="$2" label="${3:-value}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected ${label}='${expected}', got '${actual}'" >&2
        return 1
    fi
}

assert_exit_code() {
    local expected="$1" actual="$2" context="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected exit ${expected}, got ${actual}${context:+ (${context})}" >&2
        return 1
    fi
}

assert_file_exists() {
    local file="$1"
    if [[ ! -f "$file" ]]; then
        echo "    ASSERT: file not found: ${file}" >&2
        return 1
    fi
}

assert_file_contains() {
    local file="$1" pattern="$2"
    if ! grep -qF "$pattern" "$file"; then
        echo "    ASSERT: '${file}' does not contain '${pattern}'" >&2
        return 1
    fi
}

assert_output_contains() {
    local output="$1" pattern="$2"
    if ! echo "$output" | grep -q "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:300}" >&2
        return 1
    fi
}

# ── Helper: create defect with report, state, and triage ──────────

make_defect_report() {
    local path="$1"
    local severity="${2:-P2}"
    cat > "$path" <<EOF
Severity: ${severity}
Related Feature: my-feature
Observed Behavior: The widget crashes on load
Expected Behavior: The widget renders correctly
Reproduction Steps: Open the app and click the widget
EOF
}

# Set up a defect at a given state with a branch
_setup_defect_at_state() {
    local name="$1"
    local target_state="$2"
    local complexity="${3:-moderate}"

    local spec="${TEST_DIR}/specs/defects/${name}.md"
    make_defect_report "$spec" "P2"
    init_defect_dir "$name" "$spec"
    create_defect_state "$name" "$spec"

    # Write triage output
    echo "{\"is_defect\": true, \"complexity\": \"${complexity}\", \"defect_type\": \"logic\", \"affected_files\": [\"lib/defects.sh\"], \"severity\": \"P2\", \"root_cause_hypothesis\": \"Bad state transition\", \"regression_risks\": \"State machine changes\"}" \
        | write_triage_output "$name" 2>/dev/null

    # Walk through transitions to reach target state
    case "$target_state" in
        triaged)
            transition_defect_state "$name" "triaging"
            transition_defect_state "$name" "triaged"
            ;;
        fixing)
            transition_defect_state "$name" "triaging"
            transition_defect_state "$name" "triaged"
            transition_defect_state "$name" "fixing"
            ;;
        fixed)
            transition_defect_state "$name" "triaging"
            transition_defect_state "$name" "triaged"
            transition_defect_state "$name" "fixing"
            transition_defect_state "$name" "fixed"
            ;;
        reviewing)
            transition_defect_state "$name" "triaging"
            transition_defect_state "$name" "triaged"
            transition_defect_state "$name" "fixing"
            transition_defect_state "$name" "fixed"
            transition_defect_state "$name" "reviewing"
            ;;
        reviewed)
            transition_defect_state "$name" "triaging"
            transition_defect_state "$name" "triaged"
            transition_defect_state "$name" "fixing"
            transition_defect_state "$name" "fixed"
            transition_defect_state "$name" "reviewing"
            transition_defect_state "$name" "reviewed"
            ;;
    esac

    # Set a branch on the defect
    local branch="speed/defect-${name}"
    set_defect_branch "$name" "$branch"
}

# ── Tests: _review_revert_to_fixed ───────────────────────────────

test_review_revert_to_fixed() {
    _setup_defect_at_state "revert-bug" "reviewing"

    _review_revert_to_fixed "revert-bug"

    local status
    status=$(python3 -c "import json; d=json.load(open('${TEST_DIR}/.speed/defects/revert-bug/state.json')); print(d['status'])")
    assert_eq "fixed" "$status" "status after revert"
}

# ── Tests: review_defect_fix ──────────────────────────────────────

test_review_defect_fix_rejects_wrong_state() {
    _setup_defect_at_state "wrong-state-bug" "triaged"

    local rc=0
    review_defect_fix "wrong-state-bug" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "should reject non-fixed state"
}

test_review_defect_fix_rejects_missing_defect() {
    local rc=0
    review_defect_fix "nonexistent" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "should reject missing defect"
}

test_review_defect_fix_requires_branch() {
    local name="no-branch-bug"
    local spec="${TEST_DIR}/specs/defects/${name}.md"
    make_defect_report "$spec"
    init_defect_dir "$name" "$spec"
    create_defect_state "$name" "$spec"

    echo '{"is_defect": true, "complexity": "moderate", "defect_type": "logic", "affected_files": ["lib/defects.sh"], "severity": "P2"}' \
        | write_triage_output "$name" 2>/dev/null

    transition_defect_state "$name" "triaging"
    transition_defect_state "$name" "triaged"
    transition_defect_state "$name" "fixing"
    transition_defect_state "$name" "fixed"

    # Don't set a branch
    local rc=0
    review_defect_fix "$name" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "should reject defect without branch"
}

# ── Tests: check_guardian_threshold ───────────────────────────────

test_guardian_threshold_small_diff_returns_1() {
    local name="small-bug"
    _setup_defect_at_state "$name" "fixed"

    # Create the branch with a small change (under both thresholds)
    local branch="speed/defect-${name}"
    git -C "$TEST_DIR" checkout -b "$branch" -q 2>/dev/null
    echo "one small change" > "${TEST_DIR}/file1.txt"
    git -C "$TEST_DIR" add file1.txt
    git -C "$TEST_DIR" commit -m "small fix" -q
    git -C "$TEST_DIR" checkout main -q 2>/dev/null || git -C "$TEST_DIR" checkout master -q 2>/dev/null

    local rc=0
    check_guardian_threshold "$name" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "small diff should return 1 (skip guardian)"
}

test_guardian_threshold_many_files_returns_0() {
    local name="big-bug"
    _setup_defect_at_state "$name" "fixed"

    # Create branch with changes to 4+ files (exceeds file threshold)
    local branch="speed/defect-${name}"
    git -C "$TEST_DIR" checkout -b "$branch" -q 2>/dev/null
    for i in 1 2 3 4; do
        echo "change $i" > "${TEST_DIR}/file${i}.txt"
    done
    git -C "$TEST_DIR" add file1.txt file2.txt file3.txt file4.txt
    git -C "$TEST_DIR" commit -m "big fix" -q
    git -C "$TEST_DIR" checkout main -q 2>/dev/null || git -C "$TEST_DIR" checkout master -q 2>/dev/null

    local rc=0
    check_guardian_threshold "$name" 2>/dev/null || rc=$?
    assert_exit_code 0 "$rc" "many files should return 0 (run guardian)"
}

test_guardian_threshold_missing_branch_returns_1() {
    local name="no-branch"
    local spec="${TEST_DIR}/specs/defects/${name}.md"
    make_defect_report "$spec"
    init_defect_dir "$name" "$spec"
    create_defect_state "$name" "$spec"

    # No branch set, no triage
    local rc=0
    check_guardian_threshold "$name" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing branch should return 1"
}

# ── Tests: integrate_defect ───────────────────────────────────────

test_integrate_defect_rejects_moderate_not_reviewed() {
    _setup_defect_at_state "not-reviewed" "fixed" "moderate"

    local rc=0
    integrate_defect "not-reviewed" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "moderate defect not in reviewed state should fail"
}

test_integrate_defect_accepts_trivial_fixed() {
    _setup_defect_at_state "trivial-bug" "fixed" "trivial"

    # Create the branch with a commit so merge has something to do
    local branch="speed/defect-trivial-bug"
    git -C "$TEST_DIR" checkout -b "$branch" -q 2>/dev/null
    echo "fix content" > "${TEST_DIR}/trivial-fix.txt"
    git -C "$TEST_DIR" add trivial-fix.txt
    git -C "$TEST_DIR" commit -m "trivial fix" -q
    git -C "$TEST_DIR" checkout main -q 2>/dev/null || git -C "$TEST_DIR" checkout master -q 2>/dev/null

    # Stub regression_run to pass (we're not testing regression here)
    regression_run() { return 0; }
    export -f regression_run 2>/dev/null || true

    # Stub run_defect_guardian (no real agent)
    run_defect_guardian() { return 0; }

    local rc=0
    integrate_defect "trivial-bug" 2>/dev/null || rc=$?
    assert_exit_code 0 "$rc" "trivial defect in fixed state should integrate"

    local status
    status=$(python3 -c "import json; d=json.load(open('${TEST_DIR}/.speed/defects/trivial-bug/state.json')); print(d['status'])")
    assert_eq "resolved" "$status" "status after integration"
}

test_integrate_defect_accepts_moderate_reviewed() {
    _setup_defect_at_state "reviewed-bug" "reviewed" "moderate"

    local branch="speed/defect-reviewed-bug"
    git -C "$TEST_DIR" checkout -b "$branch" -q 2>/dev/null
    echo "reviewed fix" > "${TEST_DIR}/reviewed-fix.txt"
    git -C "$TEST_DIR" add reviewed-fix.txt
    git -C "$TEST_DIR" commit -m "reviewed fix" -q
    git -C "$TEST_DIR" checkout main -q 2>/dev/null || git -C "$TEST_DIR" checkout master -q 2>/dev/null

    regression_run() { return 0; }
    export -f regression_run 2>/dev/null || true
    run_defect_guardian() { return 0; }

    local rc=0
    integrate_defect "reviewed-bug" 2>/dev/null || rc=$?
    assert_exit_code 0 "$rc" "moderate defect in reviewed state should integrate"

    local status
    status=$(python3 -c "import json; d=json.load(open('${TEST_DIR}/.speed/defects/reviewed-bug/state.json')); print(d['status'])")
    assert_eq "resolved" "$status" "status after integration"
}

test_integrate_defect_missing_defect() {
    local rc=0
    integrate_defect "nonexistent" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing defect should fail"
}

test_integrate_defect_requires_branch() {
    local name="no-branch-int"
    local spec="${TEST_DIR}/specs/defects/${name}.md"
    make_defect_report "$spec"
    init_defect_dir "$name" "$spec"
    create_defect_state "$name" "$spec"

    echo '{"is_defect": true, "complexity": "trivial", "defect_type": "logic", "affected_files": ["lib/defects.sh"], "severity": "P2"}' \
        | write_triage_output "$name" 2>/dev/null

    transition_defect_state "$name" "triaging"
    transition_defect_state "$name" "triaged"
    transition_defect_state "$name" "fixing"
    transition_defect_state "$name" "fixed"
    # No branch set

    run_defect_guardian() { return 0; }

    local rc=0
    integrate_defect "$name" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing branch should fail"
}

test_integrate_defect_stays_integrating_on_regression_fail() {
    _setup_defect_at_state "regfail-bug" "fixed" "trivial"

    local branch="speed/defect-regfail-bug"
    git -C "$TEST_DIR" checkout -b "$branch" -q 2>/dev/null
    echo "regression fail" > "${TEST_DIR}/regfail.txt"
    git -C "$TEST_DIR" add regfail.txt
    git -C "$TEST_DIR" commit -m "will fail regression" -q
    git -C "$TEST_DIR" checkout main -q 2>/dev/null || git -C "$TEST_DIR" checkout master -q 2>/dev/null

    # Stub regression to fail
    regression_run() { return 1; }
    export -f regression_run 2>/dev/null || true
    run_defect_guardian() { return 0; }

    local rc=0
    integrate_defect "regfail-bug" 2>/dev/null || rc=$?

    # Should fail (non-zero exit)
    if [[ $rc -eq 0 ]]; then
        echo "    ASSERT: expected non-zero exit on regression failure" >&2
        return 1
    fi

    local status
    status=$(python3 -c "import json; d=json.load(open('${TEST_DIR}/.speed/defects/regfail-bug/state.json')); print(d['status'])")
    assert_eq "integrating" "$status" "state should stay at integrating on regression fail"
}

test_integrate_defect_deletes_branch_on_success() {
    _setup_defect_at_state "cleanup-bug" "fixed" "trivial"

    local branch="speed/defect-cleanup-bug"
    git -C "$TEST_DIR" checkout -b "$branch" -q 2>/dev/null
    echo "cleanup" > "${TEST_DIR}/cleanup.txt"
    git -C "$TEST_DIR" add cleanup.txt
    git -C "$TEST_DIR" commit -m "cleanup fix" -q
    git -C "$TEST_DIR" checkout main -q 2>/dev/null || git -C "$TEST_DIR" checkout master -q 2>/dev/null

    regression_run() { return 0; }
    export -f regression_run 2>/dev/null || true
    run_defect_guardian() { return 0; }

    integrate_defect "cleanup-bug" 2>/dev/null

    # Branch should be deleted
    local branch_exists=0
    git -C "$TEST_DIR" rev-parse --verify "$branch" &>/dev/null || branch_exists=1
    assert_eq 1 "$branch_exists" "branch should be deleted after integration"
}

# ── Main ──────────────────────────────────────────────────────────

echo "Running defect review tests..."
echo ""

# _review_revert_to_fixed
run_test test_review_revert_to_fixed

# review_defect_fix
run_test test_review_defect_fix_rejects_wrong_state
run_test test_review_defect_fix_rejects_missing_defect
run_test test_review_defect_fix_requires_branch

# check_guardian_threshold
run_test test_guardian_threshold_small_diff_returns_1
run_test test_guardian_threshold_many_files_returns_0
run_test test_guardian_threshold_missing_branch_returns_1

# integrate_defect
run_test test_integrate_defect_rejects_moderate_not_reviewed
run_test test_integrate_defect_accepts_trivial_fixed
run_test test_integrate_defect_accepts_moderate_reviewed
run_test test_integrate_defect_missing_defect
run_test test_integrate_defect_requires_branch
run_test test_integrate_defect_stays_integrating_on_regression_fail
run_test test_integrate_defect_deletes_branch_on_success

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
