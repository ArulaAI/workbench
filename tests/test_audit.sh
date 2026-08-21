#!/usr/bin/env bash
# test_audit.sh — Integration tests for `speed audit` and --skip-audit flag
#
# Tests argument validation, spec type detection, and error handling.
# Does NOT test AI agent output (requires live Claude connection).
#
# Usage: bash speed/tests/test_audit.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEED_SCRIPT="${SCRIPT_DIR}/../speed"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)
    mkdir -p "${TEST_DIR}/speed/templates" "${TEST_DIR}/speed/lib" "${TEST_DIR}/speed/providers" "${TEST_DIR}/speed/agents"
    mkdir -p "${TEST_DIR}/specs/product" "${TEST_DIR}/specs/tech" "${TEST_DIR}/specs/design" "${TEST_DIR}/specs/defects"
    cp -r "${SCRIPT_DIR}/../templates/." "${TEST_DIR}/speed/templates/"
    cp -r "${SCRIPT_DIR}/../lib/." "${TEST_DIR}/speed/lib/"
    cp -r "${SCRIPT_DIR}/../providers/." "${TEST_DIR}/speed/providers/"
    cp -r "${SCRIPT_DIR}/../agents/." "${TEST_DIR}/speed/agents/"
    cp "${SPEED_SCRIPT}" "${TEST_DIR}/speed/speed"
    chmod +x "${TEST_DIR}/speed/speed"

    # Initialize minimal git repo (required by speed's git checks)
    (cd "$TEST_DIR" && git init -q && git add -A && git commit -q -m "init")

    # Create speed.toml with dummy provider config
    cat > "${TEST_DIR}/speed.toml" <<'TOML'
[agent]
provider = "claude-code"
planning_model = "opus"
support_model = "sonnet"
TOML
}

teardown() {
    rm -rf "$TEST_DIR"
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
    # Strip ANSI escape codes before matching
    local stripped
    stripped=$(echo "$output" | sed 's/\x1b\[[0-9;]*m//g')
    if ! echo "$stripped" | grep -qi "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${stripped:0:500}" >&2
        return 1
    fi
}

assert_output_not_contains() {
    local output="$1" pattern="$2"
    # Strip ANSI escape codes before matching
    local stripped
    stripped=$(echo "$output" | sed 's/\x1b\[[0-9;]*m//g')
    if echo "$stripped" | grep -qi "$pattern"; then
        echo "    ASSERT: output should not contain '${pattern}'" >&2
        return 1
    fi
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

# ── Helpers ───────────────────────────────────────────────────────

run_speed() {
    # Run the test copy of speed, suppressing all output.
    # Returns the exit code of the speed command.
    SPEED_PROJECT_ROOT="$TEST_DIR" "${TEST_DIR}/speed/speed" "$@" >/dev/null 2>&1
}

run_speed_capture() {
    # Run speed and capture combined stdout+stderr (ANSI codes included).
    # Caller must handle exit code separately.
    SPEED_PROJECT_ROOT="$TEST_DIR" CLAUDE_BIN=/nonexistent "${TEST_DIR}/speed/speed" "$@" 2>&1
}

# ── Tests: speed audit ───────────────────────────────────────────

test_audit_no_args() {
    local rc=0
    "${TEST_DIR}/speed/speed" audit >/dev/null 2>&1 || rc=$?
    assert_exit_code 1 "$rc" "audit with no args should exit 1"
}

test_audit_nonexistent_file() {
    local rc=0
    "${TEST_DIR}/speed/speed" audit nonexistent.md >/dev/null 2>&1 || rc=$?
    assert_exit_code 3 "$rc" "audit nonexistent file should exit EXIT_CONFIG_ERROR"
}

test_audit_unrecognized_path() {
    # Create the file so it passes the existence check but fails type detection
    mkdir -p "${TEST_DIR}/some-random"
    echo "# Some doc" > "${TEST_DIR}/some-random/path.md"
    local rc=0
    "${TEST_DIR}/speed/speed" audit some-random/path.md >/dev/null 2>&1 || rc=$?
    assert_exit_code 3 "$rc" "audit unrecognized path should exit EXIT_CONFIG_ERROR"
}

test_audit_product_spec_type() {
    echo "# My Feature PRD" > "${TEST_DIR}/specs/product/my-feature.md"
    local output rc=0
    output=$(run_speed_capture audit specs/product/my-feature.md) || rc=$?
    # Command will fail at agent invocation — we only check spec type detection
    assert_output_contains "$output" "prd"
}

test_audit_tech_spec_type() {
    echo "# My Feature RFC" > "${TEST_DIR}/specs/tech/my-feature.md"
    local output rc=0
    output=$(run_speed_capture audit specs/tech/my-feature.md) || rc=$?
    assert_output_contains "$output" "rfc"
}

test_audit_design_spec_type() {
    echo "# My Feature Design" > "${TEST_DIR}/specs/design/my-feature.md"
    local output rc=0
    output=$(run_speed_capture audit specs/design/my-feature.md) || rc=$?
    assert_output_contains "$output" "design"
}

test_audit_defect_spec_type() {
    echo "# My Bug Report" > "${TEST_DIR}/specs/defects/my-bug.md"
    local output rc=0
    output=$(run_speed_capture audit specs/defects/my-bug.md) || rc=$?
    assert_output_contains "$output" "defect"
}

test_audit_missing_template() {
    echo "# My Feature PRD" > "${TEST_DIR}/specs/product/my-feature.md"
    rm "${TEST_DIR}/speed/templates/prd.md"
    local rc=0
    "${TEST_DIR}/speed/speed" audit specs/product/my-feature.md >/dev/null 2>&1 || rc=$?
    assert_exit_code 3 "$rc" "audit with missing template should exit EXIT_CONFIG_ERROR"
}

test_audit_relative_path() {
    echo "# Test Spec" > "${TEST_DIR}/specs/product/test.md"
    local output rc=0
    output=$(run_speed_capture audit specs/product/test.md) || rc=$?
    # Verify correct type detected (relative path resolved via PROJECT_ROOT)
    assert_output_contains "$output" "prd"
}

# ── Tests: --skip-audit in cmd_plan ──────────────────────────────

test_plan_accepts_skip_audit() {
    # Create a dummy spec so we get past file-existence check
    echo "# Dummy Spec" > "${TEST_DIR}/specs/tech/dummy.md"
    local output rc=0
    output=$(run_speed_capture plan specs/tech/dummy.md --skip-audit) || rc=$?
    # The plan will fail downstream (no Claude CLI) but should NOT fail
    # with 'Unknown option: --skip-audit'
    assert_output_not_contains "$output" "Unknown option"
}

test_plan_help_shows_skip_audit() {
    local output rc=0
    output=$(run_speed_capture help) || rc=$?
    assert_output_contains "$output" "skip-audit"
}

# ── Main ─────────────────────────────────────────────────────────

echo "Running speed audit tests..."
echo ""

run_test test_audit_no_args
run_test test_audit_nonexistent_file
run_test test_audit_unrecognized_path
run_test test_audit_product_spec_type
run_test test_audit_tech_spec_type
run_test test_audit_design_spec_type
run_test test_audit_defect_spec_type
run_test test_audit_missing_template
run_test test_audit_relative_path
run_test test_plan_accepts_skip_audit
run_test test_plan_help_shows_skip_audit

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
