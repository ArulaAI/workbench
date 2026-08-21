#!/usr/bin/env bash
# test_defect_state.sh — Unit tests for lib/defects.sh
#
# Tests state creation/reading, transitions, report parsing, triage output
# validation, and list_defects with multiple defects.
#
# Usage: bash tests/test_defect_state.sh
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

    # Set environment so config.sh initializes correctly
    export SPEED_PROJECT_ROOT="$TEST_DIR"
    export VERBOSITY=0

    # Source required libraries
    # shellcheck disable=SC1090
    source "${LIB_DIR}/config.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/log.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/defects.sh"

    mkdir -p "${TEST_DIR}/.speed/defects"
    mkdir -p "${TEST_DIR}/specs/defects"
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

assert_dir_exists() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        echo "    ASSERT: directory not found: ${dir}" >&2
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

# ── Helper: create a minimal valid defect report ──────────────────

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

# ── Tests: get_defect_dir / get_defect_branch ─────────────────────

test_get_defect_dir() {
    local result
    result=$(get_defect_dir "my-bug")
    assert_eq "${TEST_DIR}/.speed/defects/my-bug" "$result" "get_defect_dir"
}

test_get_defect_branch() {
    local result
    result=$(get_defect_branch "my-bug")
    assert_eq "speed/defect-my-bug" "$result" "get_defect_branch"
}

# ── Tests: init_defect_dir ────────────────────────────────────────

test_init_defect_dir_creates_structure() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"

    init_defect_dir "my-bug" "$spec"

    assert_dir_exists "${TEST_DIR}/.speed/defects/my-bug"
    assert_dir_exists "${TEST_DIR}/.speed/defects/my-bug/logs"
    assert_file_exists "${TEST_DIR}/.speed/defects/my-bug/report.md"
}

test_init_defect_dir_copies_spec() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec" "P1"

    init_defect_dir "my-bug" "$spec"

    assert_file_contains "${TEST_DIR}/.speed/defects/my-bug/report.md" "P1"
}

test_init_defect_dir_fails_if_exists() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"

    init_defect_dir "my-bug" "$spec"

    local rc=0
    init_defect_dir "my-bug" "$spec" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "second init should fail"
}

# ── Tests: create_defect_state ────────────────────────────────────

test_create_defect_state_writes_filed() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"

    create_defect_state "my-bug" "$spec"

    assert_file_exists "${TEST_DIR}/.speed/defects/my-bug/state.json"
    assert_file_contains "${TEST_DIR}/.speed/defects/my-bug/state.json" '"filed"'
}

test_create_defect_state_severity_null() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec" "P0"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    local state_file="${TEST_DIR}/.speed/defects/my-bug/state.json"
    local severity
    severity=$(python3 -c "import json; d=json.load(open('${state_file}')); print(d.get('severity'))")
    assert_eq "None" "$severity" "severity should be null until triage"
}

test_create_defect_state_has_timestamps() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    local state_file="${TEST_DIR}/.speed/defects/my-bug/state.json"
    assert_file_contains "$state_file" "created_at"
    assert_file_contains "$state_file" "updated_at"
}

test_create_defect_state_stores_source_spec() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    local state_file="${TEST_DIR}/.speed/defects/my-bug/state.json"
    assert_file_contains "$state_file" "source_spec"
}

# ── Tests: read_defect_state ──────────────────────────────────────

test_read_defect_state_returns_json() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    local output
    output=$(read_defect_state "my-bug")

    assert_output_contains "$output" "filed"
}

test_read_defect_state_missing_defect() {
    local rc=0
    read_defect_state "nonexistent" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "should fail for missing defect"
}

# ── Tests: transition_defect_state ────────────────────────────────

test_transition_filed_to_triaging() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    transition_defect_state "my-bug" "triaging"

    local status
    status=$(python3 -c "import json; d=json.load(open('${TEST_DIR}/.speed/defects/my-bug/state.json')); print(d['status'])")
    assert_eq "triaging" "$status" "status after transition"
}

test_transition_invalid_filed_to_resolved() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    local rc=0
    transition_defect_state "my-bug" "resolved" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "invalid transition should fail"
}

test_transition_terminal_state_blocked() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    transition_defect_state "my-bug" "triaging"
    transition_defect_state "my-bug" "rejected"

    local rc=0
    transition_defect_state "my-bug" "triaging" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "transition from terminal state should fail"
}

test_transition_retry_fixing_to_triaged() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    transition_defect_state "my-bug" "triaging"
    transition_defect_state "my-bug" "triaged"
    transition_defect_state "my-bug" "fixing"
    # Retry backward transition
    transition_defect_state "my-bug" "triaged"

    local status
    status=$(python3 -c "import json; d=json.load(open('${TEST_DIR}/.speed/defects/my-bug/state.json')); print(d['status'])")
    assert_eq "triaged" "$status" "retry backward transition fixing→triaged"
}

test_transition_retry_reproducing_to_triaged() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    transition_defect_state "my-bug" "triaging"
    transition_defect_state "my-bug" "triaged"
    transition_defect_state "my-bug" "reproducing"
    # Retry backward transition
    transition_defect_state "my-bug" "triaged"

    local status
    status=$(python3 -c "import json; d=json.load(open('${TEST_DIR}/.speed/defects/my-bug/state.json')); print(d['status'])")
    assert_eq "triaged" "$status" "retry backward transition reproducing→triaged"
}

test_transition_retry_integrating_to_fixed() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    transition_defect_state "my-bug" "triaging"
    transition_defect_state "my-bug" "triaged"
    transition_defect_state "my-bug" "fixing"
    transition_defect_state "my-bug" "fixed"
    transition_defect_state "my-bug" "integrating"
    # Retry backward transition
    transition_defect_state "my-bug" "fixed"

    local status
    status=$(python3 -c "import json; d=json.load(open('${TEST_DIR}/.speed/defects/my-bug/state.json')); print(d['status'])")
    assert_eq "fixed" "$status" "retry backward transition integrating→fixed"
}

# ── Tests: parse_defect_report ────────────────────────────────────

test_parse_valid_report() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec" "P1"

    local output
    output=$(parse_defect_report "$spec")

    assert_output_contains "$output" "severity=P1"
    assert_output_contains "$output" "observed_behavior="
    assert_output_contains "$output" "expected_behavior="
    assert_output_contains "$output" "reproduction_steps="
}

test_parse_report_missing_severity() {
    local spec="${TEST_DIR}/missing-sev.md"
    cat > "$spec" <<EOF
Related Feature: my-feature
Observed Behavior: Something broke
Expected Behavior: Should work
Reproduction Steps: Click here
EOF

    local rc=0
    parse_defect_report "$spec" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing severity should exit non-zero"
}

test_parse_report_missing_observed() {
    local spec="${TEST_DIR}/missing-obs.md"
    cat > "$spec" <<EOF
Severity: P2
Related Feature: my-feature
Expected Behavior: Should work
Reproduction Steps: Click here
EOF

    local rc=0
    parse_defect_report "$spec" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing observed behavior should exit non-zero"
}

test_parse_report_missing_expected() {
    local spec="${TEST_DIR}/missing-exp.md"
    cat > "$spec" <<EOF
Severity: P2
Related Feature: my-feature
Observed Behavior: Something broke
Reproduction Steps: Click here
EOF

    local rc=0
    parse_defect_report "$spec" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing expected behavior should exit non-zero"
}

test_parse_report_missing_repro() {
    local spec="${TEST_DIR}/missing-repro.md"
    cat > "$spec" <<EOF
Severity: P2
Related Feature: my-feature
Observed Behavior: Something broke
Expected Behavior: Should work
EOF

    local rc=0
    parse_defect_report "$spec" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing reproduction steps should exit non-zero"
}

test_parse_report_nonexistent_file() {
    local rc=0
    parse_defect_report "${TEST_DIR}/nope.md" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "nonexistent file should exit non-zero"
}

# ── Tests: validate_defect_report ────────────────────────────────

test_validate_valid_report() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec" "P0"

    local rc=0
    validate_defect_report "$spec" 2>/dev/null || rc=$?
    assert_exit_code 0 "$rc" "valid report should return 0"
}

test_validate_missing_severity() {
    local spec="${TEST_DIR}/no-sev.md"
    cat > "$spec" <<EOF
Observed Behavior: Crash
Expected Behavior: No crash
Reproduction Steps: Run it
EOF

    local rc=0
    validate_defect_report "$spec" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing severity should return 1"
}

test_validate_invalid_severity_value() {
    local spec="${TEST_DIR}/bad-sev.md"
    cat > "$spec" <<EOF
Severity: P5
Observed Behavior: Crash
Expected Behavior: No crash
Reproduction Steps: Run it
EOF

    local rc=0
    validate_defect_report "$spec" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "invalid severity 'P5' should return 1"
}

# ── Tests: write_triage_output / read_triage_output ───────────────

test_write_triage_output_valid() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    echo '{"is_defect": true, "complexity": "moderate", "defect_type": "logic", "affected_files": ["lib/defects.sh"], "severity": "P2", "root_cause_hypothesis": "Bad state"}' \
        | write_triage_output "my-bug"

    assert_file_exists "${TEST_DIR}/.speed/defects/my-bug/triage.json"
    assert_file_contains "${TEST_DIR}/.speed/defects/my-bug/triage.json" '"moderate"'
}

test_write_triage_output_updates_state() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    echo '{"is_defect": true, "complexity": "trivial", "defect_type": "logic", "affected_files": ["lib/defects.sh"], "severity": "P1"}' \
        | write_triage_output "my-bug"

    local state_file="${TEST_DIR}/.speed/defects/my-bug/state.json"
    local complexity
    complexity=$(python3 -c "import json; d=json.load(open('${state_file}')); print(d.get('complexity',''))")
    assert_eq "trivial" "$complexity" "state.complexity should be updated from triage"
}

test_write_triage_output_missing_is_defect() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    local rc=0
    echo '{"complexity": "moderate", "defect_type": "logic", "affected_files": ["lib/defects.sh"]}' \
        | write_triage_output "my-bug" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing is_defect should reject"
}

test_write_triage_output_missing_complexity() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    local rc=0
    echo '{"is_defect": true, "defect_type": "logic", "affected_files": ["lib/defects.sh"]}' \
        | write_triage_output "my-bug" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing complexity should reject"
}

test_read_triage_output_returns_json() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    echo '{"is_defect": true, "complexity": "trivial", "defect_type": "visual", "affected_files": ["site/src/index.astro"]}' \
        | write_triage_output "my-bug"

    local output
    output=$(read_triage_output "my-bug")
    assert_output_contains "$output" "trivial"
}

test_read_triage_output_missing() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    local rc=0
    read_triage_output "my-bug" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing triage.json should fail"
}

# ── Tests: set_defect_branch ──────────────────────────────────────

test_set_defect_branch_updates_state() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    set_defect_branch "my-bug" "speed/defect-my-bug"

    local state_file="${TEST_DIR}/.speed/defects/my-bug/state.json"
    local branch
    branch=$(python3 -c "import json; d=json.load(open('${state_file}')); print(d.get('branch',''))")
    assert_eq "speed/defect-my-bug" "$branch" "branch field in state.json"
}

test_set_defect_branch_updates_timestamp() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    local before
    before=$(python3 -c "import json; d=json.load(open('${TEST_DIR}/.speed/defects/my-bug/state.json')); print(d.get('updated_at',''))")

    sleep 1
    set_defect_branch "my-bug" "speed/defect-my-bug"

    local after
    after=$(python3 -c "import json; d=json.load(open('${TEST_DIR}/.speed/defects/my-bug/state.json')); print(d.get('updated_at',''))")

    if [[ "$before" == "$after" ]]; then
        echo "    ASSERT: updated_at should have changed after set_defect_branch" >&2
        return 1
    fi
}

test_set_defect_branch_missing_defect() {
    local rc=0
    set_defect_branch "nonexistent" "speed/defect-nonexistent" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "should fail for missing defect"
}

# ── Tests: list_defects ───────────────────────────────────────────

_setup_defect() {
    local name="$1" severity="$2" status="$3"
    local spec="${TEST_DIR}/specs/defects/${name}.md"
    make_defect_report "$spec" "$severity"
    init_defect_dir "$name" "$spec"
    create_defect_state "$name" "$spec"

    case "$status" in
        triaging)
            transition_defect_state "$name" "triaging"
            ;;
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
        resolved)
            transition_defect_state "$name" "triaging"
            transition_defect_state "$name" "triaged"
            transition_defect_state "$name" "fixing"
            transition_defect_state "$name" "fixed"
            transition_defect_state "$name" "integrating"
            transition_defect_state "$name" "resolved"
            ;;
    esac
}

test_list_defects_empty() {
    # No defects — should return successfully with no output
    local rc=0
    list_defects 2>/dev/null || rc=$?
    assert_exit_code 0 "$rc" "empty list should succeed"
}

test_list_defects_single() {
    _setup_defect "alpha-bug" "P1" "filing"

    local output
    output=$(list_defects 2>/dev/null)
    assert_output_contains "$output" "alpha-bug"
}

test_list_defects_multiple() {
    _setup_defect "bug-a" "P0" "triaging"
    _setup_defect "bug-b" "P2" "fixing"
    _setup_defect "bug-c" "P1" "fixed"

    local output
    output=$(list_defects 2>/dev/null)
    assert_output_contains "$output" "bug-a"
    assert_output_contains "$output" "bug-b"
    assert_output_contains "$output" "bug-c"
}

test_list_defects_shows_status() {
    _setup_defect "status-bug" "P2" "triaging"

    local output
    output=$(list_defects 2>/dev/null)
    assert_output_contains "$output" "triaging"
}

test_list_defects_shows_severity() {
    # Severity appears in list_defects after triage sets it via write_triage_output
    local spec="${TEST_DIR}/specs/defects/sev-bug.md"
    make_defect_report "$spec" "P0"
    init_defect_dir "sev-bug" "$spec"
    create_defect_state "sev-bug" "$spec"

    echo '{"is_defect": true, "complexity": "trivial", "defect_type": "logic", "affected_files": ["lib/defects.sh"], "severity": "P0"}' \
        | write_triage_output "sev-bug" 2>/dev/null

    local output
    output=$(list_defects 2>/dev/null)
    assert_output_contains "$output" "P0"
}

# ── Main ──────────────────────────────────────────────────────────

echo "Running defect state management tests..."
echo ""

# get_defect_dir / get_defect_branch
run_test test_get_defect_dir
run_test test_get_defect_branch

# init_defect_dir
run_test test_init_defect_dir_creates_structure
run_test test_init_defect_dir_copies_spec
run_test test_init_defect_dir_fails_if_exists

# create_defect_state
run_test test_create_defect_state_writes_filed
run_test test_create_defect_state_severity_null
run_test test_create_defect_state_has_timestamps
run_test test_create_defect_state_stores_source_spec

# read_defect_state
run_test test_read_defect_state_returns_json
run_test test_read_defect_state_missing_defect

# transition_defect_state
run_test test_transition_filed_to_triaging
run_test test_transition_invalid_filed_to_resolved
run_test test_transition_terminal_state_blocked
run_test test_transition_retry_fixing_to_triaged
run_test test_transition_retry_reproducing_to_triaged
run_test test_transition_retry_integrating_to_fixed

# parse_defect_report
run_test test_parse_valid_report
run_test test_parse_report_missing_severity
run_test test_parse_report_missing_observed
run_test test_parse_report_missing_expected
run_test test_parse_report_missing_repro
run_test test_parse_report_nonexistent_file

# validate_defect_report
run_test test_validate_valid_report
run_test test_validate_missing_severity
run_test test_validate_invalid_severity_value

# write_triage_output / read_triage_output
run_test test_write_triage_output_valid
run_test test_write_triage_output_updates_state
run_test test_write_triage_output_missing_is_defect
run_test test_write_triage_output_missing_complexity
run_test test_read_triage_output_returns_json
run_test test_read_triage_output_missing

# set_defect_branch
run_test test_set_defect_branch_updates_state
run_test test_set_defect_branch_updates_timestamp
run_test test_set_defect_branch_missing_defect

# list_defects
run_test test_list_defects_empty
run_test test_list_defects_single
run_test test_list_defects_multiple
run_test test_list_defects_shows_status
run_test test_list_defects_shows_severity

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
