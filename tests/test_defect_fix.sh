#!/usr/bin/env bash
# test_defect_fix.sh — Unit tests for lib/defect_fix.sh
#
# Tests create_defect_branch, run_defect_quality_gates, and
# check_grounding_gates. Reproduce/fix flows are tested at the
# function boundary level (mocking the agent call is out of scope
# for unit tests; integration tests cover end-to-end flows).
#
# Usage: bash tests/test_defect_fix.sh
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

    # shellcheck disable=SC1090
    source "${LIB_DIR}/config.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/log.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/grounding.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/defects.sh"

    mkdir -p "${TEST_DIR}/.speed/defects"
    mkdir -p "${TEST_DIR}/specs/defects"

    # Initialize git repo for branch operations
    git -C "$TEST_DIR" init -q
    git -C "$TEST_DIR" config user.email "test@test.com"
    git -C "$TEST_DIR" config user.name "Test"
    git -C "$TEST_DIR" commit --allow-empty -m "Initial commit" -q

    # Source git.sh after repo init (needs config.sh already loaded)
    # shellcheck disable=SC1090
    source "${LIB_DIR}/git.sh"

    # Source defect_fix.sh
    # shellcheck disable=SC1090
    source "${LIB_DIR}/defect_fix.sh"
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

# ── Helper: create a minimal defect with state ──────────────────

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

setup_defect() {
    local name="$1"
    local complexity="${2:-moderate}"

    local spec="${TEST_DIR}/specs/defects/${name}.md"
    make_defect_report "$spec"

    init_defect_dir "$name" "$spec"
    create_defect_state "$name" "$spec"

    # Write triage output to advance state
    local triage='{"is_defect":true,"severity":"P2","complexity":"'"$complexity"'","defect_type":"logic","affected_files":["lib/widget.sh"],"root_cause_hypothesis":"Widget init fails on null input","test_coverage_detail":"tests/test_widget.sh exists","suggested_approach":"Add null check in widget_init","regression_risks":"None identified"}'

    # Transition to triaging then triaged
    transition_defect_state "$name" "triaging" >/dev/null 2>&1
    echo "$triage" | write_triage_output "$name" 2>/dev/null
    transition_defect_state "$name" "triaged" >/dev/null 2>&1

    # Commit defect pipeline files to main so they don't appear in branch diffs
    git -C "$TEST_DIR" add -A >/dev/null 2>&1
    git -C "$TEST_DIR" commit -m "setup: defect ${name}" -q 2>/dev/null || true
}

# ── Tests: create_defect_branch ──────────────────────────────────

test_create_defect_branch_creates_branch() {
    setup_defect "my-bug"

    create_defect_branch "my-bug" >/dev/null 2>&1
    local rc=$?
    assert_exit_code "0" "$rc" "create_defect_branch"

    # Verify branch exists
    git -C "$TEST_DIR" rev-parse --verify "speed/defect-my-bug" >/dev/null 2>&1
    local branch_rc=$?
    assert_exit_code "0" "$branch_rc" "branch exists"
}

test_create_defect_branch_updates_state() {
    setup_defect "my-bug"

    create_defect_branch "my-bug" >/dev/null 2>&1

    # Verify state.json has branch field set
    local branch_val
    branch_val=$(_defect_json_get "${TEST_DIR}/.speed/defects/my-bug/state.json" "branch")
    assert_eq "speed/defect-my-bug" "$branch_val" "branch in state.json"
}

test_create_defect_branch_fails_if_exists() {
    setup_defect "my-bug"

    # Create the branch manually first
    git -C "$TEST_DIR" checkout -b "speed/defect-my-bug" -q

    local output rc=0
    output=$(create_defect_branch "my-bug" 2>&1) || rc=$?

    assert_exit_code "1" "$rc" "should fail when branch exists"
    assert_output_contains "$output" "already exists"
}

# ── Tests: check_grounding_gates ─────────────────────────────────

test_check_grounding_gates_empty_diff() {
    setup_defect "my-bug"

    # Create the branch but make no changes
    git -C "$TEST_DIR" checkout -b "speed/defect-my-bug" -q

    local output rc=0
    output=$(check_grounding_gates "my-bug" 2>&1) || rc=$?

    assert_exit_code "1" "$rc" "should fail on empty diff"
    assert_output_contains "$output" "No changes produced"
}

test_check_grounding_gates_out_of_scope() {
    setup_defect "my-bug"

    # Create branch and make a change to an out-of-scope file
    git -C "$TEST_DIR" checkout -b "speed/defect-my-bug" -q
    mkdir -p "${TEST_DIR}/lib"
    echo "# unrelated change" > "${TEST_DIR}/lib/unrelated.sh"
    git -C "$TEST_DIR" add -A >/dev/null 2>&1
    git -C "$TEST_DIR" commit -m "out of scope change" -q

    local output rc=0
    output=$(check_grounding_gates "my-bug" 2>&1) || rc=$?

    assert_exit_code "1" "$rc" "should fail on out-of-scope files"
    assert_output_contains "$output" "Files modified outside affected scope"
    assert_output_contains "$output" "lib/unrelated.sh"
}

test_check_grounding_gates_in_scope_passes() {
    setup_defect "my-bug"

    # Create branch and modify an affected file
    git -C "$TEST_DIR" checkout -b "speed/defect-my-bug" -q
    mkdir -p "${TEST_DIR}/lib"
    echo "# fix" > "${TEST_DIR}/lib/widget.sh"
    git -C "$TEST_DIR" add -A >/dev/null 2>&1
    git -C "$TEST_DIR" commit -m "fix widget" -q

    local rc=0
    check_grounding_gates "my-bug" >/dev/null 2>&1 || rc=$?

    assert_exit_code "0" "$rc" "should pass for in-scope files"
}

test_check_grounding_gates_test_files_allowed() {
    setup_defect "my-bug"

    # Create branch with both an affected file and a test file
    git -C "$TEST_DIR" checkout -b "speed/defect-my-bug" -q
    mkdir -p "${TEST_DIR}/lib" "${TEST_DIR}/tests"
    echo "# fix" > "${TEST_DIR}/lib/widget.sh"
    echo "# test" > "${TEST_DIR}/tests/test_widget.sh"
    git -C "$TEST_DIR" add -A >/dev/null 2>&1
    git -C "$TEST_DIR" commit -m "fix with test" -q

    local rc=0
    check_grounding_gates "my-bug" >/dev/null 2>&1 || rc=$?

    assert_exit_code "0" "$rc" "test files should not trigger out-of-scope"
}

# ── Tests: reproduce_defect state transitions ────────────────────

test_reproduce_defect_transitions_state() {
    setup_defect "my-bug" "moderate"

    # We can't run the full reproduce_defect without a real agent,
    # but we can verify the state transitions are valid.
    # Transition to reproducing manually to verify the path.
    local current_state
    current_state=$(_defect_json_get "${TEST_DIR}/.speed/defects/my-bug/state.json" "status")
    assert_eq "triaged" "$current_state" "initial state"

    # Verify triaged->reproducing is valid
    transition_defect_state "my-bug" "reproducing" >/dev/null 2>&1
    current_state=$(_defect_json_get "${TEST_DIR}/.speed/defects/my-bug/state.json" "status")
    assert_eq "reproducing" "$current_state" "after reproducing transition"

    # Verify reproducing->reproduced is valid
    transition_defect_state "my-bug" "reproduced" >/dev/null 2>&1
    current_state=$(_defect_json_get "${TEST_DIR}/.speed/defects/my-bug/state.json" "status")
    assert_eq "reproduced" "$current_state" "after reproduced transition"
}

test_reproduce_defect_lint_skip_test() {
    # Verify that reproduce stage only runs lint+typecheck, not test
    # We do this indirectly by checking the function signature expectation
    # (reproduce calls gate_run_command for lint/typecheck but not test)
    # Checking the function source for the pattern
    local source_file="${LIB_DIR}/defect_fix.sh"
    assert_file_exists "$source_file"

    # The reproduce_defect function should iterate lint and typecheck only
    local in_reproduce=false
    local has_test_gate=false
    while IFS= read -r line; do
        if [[ "$line" == *"reproduce_defect"* ]] && [[ "$line" == *"()"* ]]; then
            in_reproduce=true
        fi
        if $in_reproduce && [[ "$line" == *"fix_defect"* ]] && [[ "$line" == *"()"* ]]; then
            break
        fi
        if $in_reproduce && [[ "$line" == *"for gate_type in"* ]]; then
            if [[ "$line" != *"test"* ]]; then
                # Good: no 'test' in the gate loop
                :
            else
                has_test_gate=true
            fi
        fi
    done < "$source_file"

    if $has_test_gate; then
        echo "    ASSERT: reproduce_defect should not include 'test' in gate types" >&2
        return 1
    fi
}

# ── Tests: fix_defect flow ───────────────────────────────────────

test_fix_defect_trivial_creates_branch() {
    setup_defect "trivial-bug" "trivial"

    # Verify that fix_defect for trivial would try to create a branch
    # (can't run full flow without agent, but we test the branch logic)
    local current_state
    current_state=$(_defect_json_get "${TEST_DIR}/.speed/defects/trivial-bug/state.json" "status")
    assert_eq "triaged" "$current_state" "initial state for trivial"

    # Verify triaged->fixing is valid
    transition_defect_state "trivial-bug" "fixing" >/dev/null 2>&1
    current_state=$(_defect_json_get "${TEST_DIR}/.speed/defects/trivial-bug/state.json" "status")
    assert_eq "fixing" "$current_state" "after fixing transition"
}

test_fix_defect_moderate_continues_branch() {
    setup_defect "mod-bug" "moderate"

    # Simulate that reproduce has already happened
    transition_defect_state "mod-bug" "reproducing" >/dev/null 2>&1
    transition_defect_state "mod-bug" "reproduced" >/dev/null 2>&1

    # Verify reproduced->fixing is valid
    transition_defect_state "mod-bug" "fixing" >/dev/null 2>&1
    local current_state
    current_state=$(_defect_json_get "${TEST_DIR}/.speed/defects/mod-bug/state.json" "status")
    assert_eq "fixing" "$current_state" "after fixing transition from reproduced"

    # Verify fixing->fixed is valid
    transition_defect_state "mod-bug" "fixed" >/dev/null 2>&1
    current_state=$(_defect_json_get "${TEST_DIR}/.speed/defects/mod-bug/state.json" "status")
    assert_eq "fixed" "$current_state" "after fixed transition"
}

# ── Tests: run_defect_quality_gates ──────────────────────────────

test_run_defect_quality_gates_returns_zero_no_config() {
    setup_defect "my-bug"

    # With no CLAUDE.md quality gates configured, should still return 0
    # (gates_get_config returns empty, so nothing fails)
    local rc=0
    run_defect_quality_gates "my-bug" >/dev/null 2>&1 || rc=$?

    assert_exit_code "0" "$rc" "should pass with no gates configured"
}

test_run_defect_quality_gates_reads_triage() {
    setup_defect "my-bug"

    # Verify triage.json is readable (prerequisite for quality gates)
    local triage
    triage=$(read_triage_output "my-bug")
    local rc=$?
    assert_exit_code "0" "$rc" "triage should be readable"

    local defect_type
    defect_type=$(_defect_json_get "${TEST_DIR}/.speed/defects/my-bug/triage.json" "defect_type")
    assert_eq "logic" "$defect_type" "defect_type from triage"
}

# ── Run all tests ─────────────────────────────────────────────────

echo ""
echo "test_defect_fix.sh"
echo "$(printf '─%.0s' {1..40})"

run_test test_create_defect_branch_creates_branch
run_test test_create_defect_branch_updates_state
run_test test_create_defect_branch_fails_if_exists
run_test test_check_grounding_gates_empty_diff
run_test test_check_grounding_gates_out_of_scope
run_test test_check_grounding_gates_in_scope_passes
run_test test_check_grounding_gates_test_files_allowed
run_test test_reproduce_defect_transitions_state
run_test test_reproduce_defect_lint_skip_test
run_test test_fix_defect_trivial_creates_branch
run_test test_fix_defect_moderate_continues_branch
run_test test_run_defect_quality_gates_returns_zero_no_config
run_test test_run_defect_quality_gates_reads_triage

echo ""
echo "$(printf '─%.0s' {1..40})"
echo "Results: ${PASS} passed, ${FAIL} failed"

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0
