#!/usr/bin/env bash
# test_defect_cli.sh — Tests for cmd_defect() and cmd_status --defects
#
# Tests argument validation, path safety, and status --defects output.
# Does NOT test triage_defect (requires live provider calls).
#
# Usage: bash tests/test_defect_cli.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEED_SCRIPT="${SCRIPT_DIR}/../speed"
LIB_DIR="${SCRIPT_DIR}/../lib"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)
    export SPEED_PROJECT_ROOT="$TEST_DIR"
    export VERBOSITY=0

    # Source required libraries for direct lib testing
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

assert_exit_nonzero() {
    local actual="$1" context="${2:-}"
    if [[ "$actual" -eq 0 ]]; then
        echo "    ASSERT: expected non-zero exit, got 0${context:+ (${context})}" >&2
        return 1
    fi
}

assert_output_contains() {
    local output="$1" pattern="$2"
    if ! echo "$output" | grep -qF "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:400}" >&2
        return 1
    fi
}

# ── Helper: create a minimal valid defect report ──────────────────

_make_report() {
    local path="$1"
    mkdir -p "$(dirname "$path")"
    cat > "$path" <<'EOF'
Severity: P2
Related Feature: some-feature
Observed Behavior: Widget crashes on load
Expected Behavior: Widget loads successfully
Reproduction Steps: Open widget page
EOF
}

# ── Tests ─────────────────────────────────────────────────────────

test_defect_no_args_prints_usage() {
    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" defect 2>&1) || rc=$?
    assert_exit_nonzero "$rc" "no args"
    assert_output_contains "$output" "Usage: speed defect"
}

test_defect_nonexistent_file_prints_error() {
    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" defect /nonexistent/path/x.md 2>&1) || rc=$?
    assert_exit_nonzero "$rc" "nonexistent file"
    assert_output_contains "$output" "Defect spec not found:"
}

test_defect_path_escape_prints_error() {
    # Create a file outside the project root
    local outside_file
    outside_file=$(mktemp /tmp/outside-spec-XXXXXX.md)
    _make_report "$outside_file"

    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" defect "$outside_file" 2>&1) || rc=$?
    assert_exit_nonzero "$rc" "path escape"
    assert_output_contains "$output" "Invalid spec path:"
    rm -f "$outside_file"
}

test_status_defects_no_defects_message() {
    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" status --defects 2>&1) || rc=$?
    assert_eq 0 "$rc" "exit code"
    assert_output_contains "$output" "No defects found."
}

test_status_defects_shows_table_header() {
    # Create a defect state to populate the listing
    mkdir -p "${TEST_DIR}/.speed/defects/widget-crash/logs"
    local now
    now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    cat > "${TEST_DIR}/.speed/defects/widget-crash/state.json" <<EOF
{
  "status": "triaged",
  "reported_severity": "P2",
  "severity": "P2",
  "defect_type": "logic",
  "complexity": "trivial",
  "branch": "speed/defect-widget-crash",
  "created_at": "${now}",
  "updated_at": "${now}",
  "source_spec": "specs/defects/widget-crash.md"
}
EOF

    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" status --defects 2>&1) || rc=$?
    assert_eq 0 "$rc" "exit code"
    assert_output_contains "$output" "Defects:"
    assert_output_contains "$output" "widget-crash"
}

test_status_defects_resolved_shows_merged() {
    mkdir -p "${TEST_DIR}/.speed/defects/old-bug/logs"
    local now
    now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    cat > "${TEST_DIR}/.speed/defects/old-bug/state.json" <<EOF
{
  "status": "resolved",
  "reported_severity": "P1",
  "severity": "P1",
  "defect_type": "logic",
  "complexity": "trivial",
  "branch": null,
  "created_at": "${now}",
  "updated_at": "${now}",
  "source_spec": "specs/defects/old-bug.md"
}
EOF

    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" status --defects 2>&1) || rc=$?
    assert_eq 0 "$rc" "exit code"
    assert_output_contains "$output" "(merged)"
}

test_status_defects_escalated_shows_prd_path() {
    mkdir -p "${TEST_DIR}/.speed/defects/big-bug/logs"
    local now
    now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    cat > "${TEST_DIR}/.speed/defects/big-bug/state.json" <<EOF
{
  "status": "escalated",
  "reported_severity": "P0",
  "severity": "P0",
  "defect_type": "logic",
  "complexity": "complex",
  "branch": null,
  "created_at": "${now}",
  "updated_at": "${now}",
  "source_spec": "specs/defects/big-bug.md"
}
EOF

    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" status --defects 2>&1) || rc=$?
    assert_eq 0 "$rc" "exit code"
    assert_output_contains "$output" "specs/product/big-bug.md"
}

test_defect_subcommand_registered() {
    # Verify 'defect' appears in help output
    local output
    output=$("$SPEED_SCRIPT" help 2>&1 || true)
    # The defect command may or may not be in help text — just verify
    # the dispatch accepts it (no "Unknown command" for valid args)
    local rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" defect 2>&1) || rc=$?
    # Should print usage, not "Unknown command"
    if echo "$output" | grep -q "Unknown command: defect"; then
        echo "    ASSERT: 'defect' not registered in dispatch" >&2
        return 1
    fi
}

# ── Helper: create a minimal defect state ────────────────────────

_make_defect_state() {
    local name="$1" status="${2:-triaged}"
    mkdir -p "${TEST_DIR}/.speed/defects/${name}/logs"
    local now
    now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    cat > "${TEST_DIR}/.speed/defects/${name}/state.json" <<EOF
{
  "status": "${status}",
  "reported_severity": "P2",
  "severity": "P2",
  "defect_type": "logic",
  "complexity": "trivial",
  "branch": "speed/defect-${name}",
  "created_at": "${now}",
  "updated_at": "${now}",
  "source_spec": "specs/defects/${name}.md"
}
EOF
}

# ── retry --defect tests ──────────────────────────────────────────

test_retry_defect_nonexistent_exits_with_error() {
    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" retry --defect nonexistent 2>&1) || rc=$?
    assert_exit_nonzero "$rc" "nonexistent defect"
    assert_output_contains "$output" "Defect not found: nonexistent"
}

test_retry_defect_context_missing_value_exits_with_error() {
    _make_defect_state "my-bug" "fixing"
    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" retry --defect my-bug --context --escalate 2>&1) || rc=$?
    assert_exit_nonzero "$rc" "--context without value"
    assert_output_contains "$output" "Missing context text for --context flag"
}

test_retry_defect_context_missing_at_end_exits_with_error() {
    _make_defect_state "my-bug" "fixing"
    local output rc=0
    # --context as last arg with no value
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" retry --defect my-bug --context 2>&1) || rc=$?
    assert_exit_nonzero "$rc" "--context at end"
    assert_output_contains "$output" "Missing context text for --context flag"
}

test_retry_defect_invalid_state_exits_with_error() {
    _make_defect_state "my-bug" "resolved"
    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" retry --defect my-bug 2>&1) || rc=$?
    assert_exit_nonzero "$rc" "resolved state"
    assert_output_contains "$output" "Cannot retry defect 'my-bug'"
}

test_retry_defect_skips_feature_requirement() {
    # --defect mode should not require a SPEED feature to be active
    # We verify this by running with no feature and checking it doesn't
    # error with "feature not found" or similar — it should get to the
    # defect validation step (which fails for nonexistent, not feature error)
    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" retry --defect no-such-defect 2>&1) || rc=$?
    assert_exit_nonzero "$rc" "no feature needed"
    # Should fail on defect-not-found, not on feature requirement
    assert_output_contains "$output" "Defect not found:"
    if echo "$output" | grep -qiE "feature|_require_feature|No feature"; then
        # Some feature-related errors are acceptable (e.g. log output) but
        # the command should not exit with a feature error before checking defect
        if echo "$output" | grep -q "Defect not found:"; then
            return 0
        fi
        echo "    ASSERT: got feature error before defect check" >&2
        return 1
    fi
}

test_retry_defect_context_appended_to_file() {
    _make_defect_state "my-bug" "triaged"
    # We can't run the full fix pipeline in unit tests (requires provider),
    # but we can verify the context.md gets written before that step runs.
    # Use a mock by checking the state file transition and context file.
    # Since fix_defect will fail without a provider, capture any exit.
    local output rc=0
    output=$(SPEED_PROJECT_ROOT="$TEST_DIR" "$SPEED_SCRIPT" retry --defect my-bug --context "try a different approach" 2>&1) || rc=$?
    # Context file should exist regardless of whether fix_defect succeeded
    local context_file="${TEST_DIR}/.speed/defects/my-bug/context.md"
    if [[ ! -f "$context_file" ]]; then
        echo "    ASSERT: context.md not written" >&2
        return 1
    fi
    local content
    content=$(cat "$context_file")
    assert_output_contains "$content" "try a different approach"
}

# ── Main ──────────────────────────────────────────────────────────

echo ""
echo "test_defect_cli.sh"
echo "────────────────────────────────────────"

run_test test_defect_no_args_prints_usage
run_test test_defect_nonexistent_file_prints_error
run_test test_defect_path_escape_prints_error
run_test test_status_defects_no_defects_message
run_test test_status_defects_shows_table_header
run_test test_status_defects_resolved_shows_merged
run_test test_status_defects_escalated_shows_prd_path
run_test test_defect_subcommand_registered
run_test test_retry_defect_nonexistent_exits_with_error
run_test test_retry_defect_context_missing_value_exits_with_error
run_test test_retry_defect_context_missing_at_end_exits_with_error
run_test test_retry_defect_invalid_state_exits_with_error
run_test test_retry_defect_skips_feature_requirement
run_test test_retry_defect_context_appended_to_file

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
