#!/usr/bin/env bash
# test_security_cmd.sh — Tests for cmd_security() in lib/cmd/security.sh
#
# Tests argument parsing, error handling, and dispatch behavior.
# Mocks provider-dependent functions (security_audit_run, etc.).
#
# Usage: bash tests/test_security_cmd.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ────────────────────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)
    export SPEED_PROJECT_ROOT="$TEST_DIR"
    export VERBOSITY=0
    export GLOBAL_FEATURE=""

    # Color stubs (config.sh defines these but we keep VERBOSITY=0)
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS=""
    COLOR_STEP="" COLOR_HEADER="" COLOR_INFO="" COLOR_ACCENT=""
    BOLD="" RESET="" SYM_CHECK="" SYM_CROSS="" SYM_WARN=""
    SYM_ARROW="" SYM_PENDING="" SYM_RUNNING=""

    # Source the config so STATE_DIR / FEATURES_DIR are defined
    # shellcheck disable=SC1090
    source "${LIB_DIR}/config.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/log.sh"

    # Stub features.sh primitives
    feature_get_active() { echo ""; }
    feature_activate()   { :; }

    # Security function mocks (avoid live agent calls)
    _audit_run_called=false
    _audit_run_feature=""
    security_audit_run() {
        _audit_run_called=true
        _audit_run_feature="$1"
    }

    _has_cached=false
    security_has_cached_audit() {
        "$_has_cached"
    }

    _create_defects_called=false
    _create_defects_args=()
    security_create_defects() {
        _create_defects_called=true
        _create_defects_args=("$@")
    }

    _banner_called=false
    security_print_banner() {
        _banner_called=true
    }

    # TOML defaults
    TOML_SECURITY_SEVERITY_THRESHOLD=""

    # Source the command module under test
    # shellcheck disable=SC1090
    source "${LIB_DIR}/cmd/security.sh"

    # Create feature log directory for audit_file tests
    mkdir -p "${TEST_DIR}/.speed/features/test-feature/logs"
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
    if ! echo "$output" | grep -q "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:400}" >&2
        return 1
    fi
}

# ── Tests ──────────────────────────────────────────────────────────────────────

test_cmd_security_function_exists() {
    if ! declare -f cmd_security > /dev/null 2>&1; then
        echo "    ASSERT: cmd_security function not defined" >&2
        return 1
    fi
}

test_no_feature_exits_error() {
    # No active feature and no --feature flag → exit 1
    feature_get_active() { echo ""; }
    local output rc=0
    output=$(cmd_security 2>&1) || rc=$?
    assert_exit_nonzero "$rc" "no feature should exit non-zero"
    assert_output_contains "$output" "No active feature"
}

test_feature_flag_sets_feature() {
    # --feature flag should set the feature name and run the audit
    local rc=0
    cmd_security --feature test-feature 2>/dev/null || rc=$?
    assert_eq "true" "$_audit_run_called" "_audit_run_called"
    assert_eq "test-feature" "$_audit_run_feature" "_audit_run_feature"
}

test_short_feature_flag() {
    # -f flag should also work
    local rc=0
    cmd_security -f test-feature 2>/dev/null || rc=$?
    assert_eq "true" "$_audit_run_called" "_audit_run_called via -f"
    assert_eq "test-feature" "$_audit_run_feature" "_audit_run_feature via -f"
}

test_active_feature_used_when_no_flag() {
    # Active feature is resolved from feature_get_active
    feature_get_active() { echo "auto-feature"; }
    local rc=0
    cmd_security 2>/dev/null || rc=$?
    assert_eq "true" "$_audit_run_called" "_audit_run_called"
    assert_eq "auto-feature" "$_audit_run_feature" "_audit_run_feature from active"
}

test_banner_printed_when_audit_file_exists() {
    # When the audit file exists after the run, security_print_banner is called
    security_audit_run() {
        _audit_run_called=true
        _audit_run_feature="$1"
        # Simulate writing the audit file
        local logs_dir="${STATE_DIR}/features/${1}/logs"
        mkdir -p "$logs_dir"
        echo '{"summary":{"total":0,"by_severity":{}},"findings":[]}' \
            > "${logs_dir}/security-audit.json"
    }
    local rc=0
    cmd_security --feature test-feature 2>/dev/null || rc=$?
    assert_eq "true" "$_banner_called" "banner should be called when audit file exists"
}

test_no_findings_printed_when_no_audit_file() {
    # When no audit file is produced, print "No security findings."
    local output rc=0
    output=$(cmd_security --feature test-feature 2>&1) || rc=$?
    assert_output_contains "$output" "No security findings"
}

test_unknown_flag_exits_error() {
    local output rc=0
    output=$(cmd_security --feature test-feature --unknown-flag 2>&1) || rc=$?
    assert_exit_nonzero "$rc" "unknown flag should exit non-zero"
    assert_output_contains "$output" "Unknown option"
}

test_create_defects_calls_security_create_defects() {
    # Write the audit file so create_defects path proceeds
    local audit_file="${STATE_DIR}/features/test-feature/logs/security-audit.json"
    echo '{"summary":{"total":1,"by_severity":{"high":1}},"findings":[{"severity":"high","title":"SQLi"}]}' \
        > "$audit_file"
    security_audit_run() { _audit_run_called=true; _audit_run_feature="$1"; }
    local rc=0
    cmd_security --feature test-feature --create-defects 2>/dev/null || rc=$?
    assert_eq "true" "$_create_defects_called" "security_create_defects should be called"
    assert_eq "$audit_file" "${_create_defects_args[0]}" "audit_file arg"
}

test_create_defects_uses_cached_when_recent() {
    # When cache is fresh and --create-defects is set, skip re-running the audit
    _has_cached=true
    security_has_cached_audit() { return 0; }
    local audit_file="${STATE_DIR}/features/test-feature/logs/security-audit.json"
    echo '{"summary":{"total":0,"by_severity":{}},"findings":[]}' > "$audit_file"
    local rc=0
    cmd_security --feature test-feature --create-defects 2>/dev/null || rc=$?
    assert_eq "false" "$_audit_run_called" "audit_run should NOT be called when cache is fresh"
}

test_create_defects_no_audit_file_exits_error() {
    # --create-defects with no audit file should exit 1
    # The audit file does not exist and audit_run doesn't create it
    local rc=0
    local output
    output=$(cmd_security --feature test-feature --create-defects 2>&1) || rc=$?
    assert_exit_nonzero "$rc" "should exit non-zero when no audit file exists"
    assert_output_contains "$output" "No audit results"
}

test_create_defects_uses_toml_threshold() {
    # TOML_SECURITY_SEVERITY_THRESHOLD should be passed as threshold arg
    TOML_SECURITY_SEVERITY_THRESHOLD="high"
    local audit_file="${STATE_DIR}/features/test-feature/logs/security-audit.json"
    echo '{"summary":{"total":1,"by_severity":{"high":1}},"findings":[{"severity":"high","title":"SQLi"}]}' \
        > "$audit_file"
    local rc=0
    cmd_security --feature test-feature --create-defects 2>/dev/null || rc=$?
    assert_eq "high" "${_create_defects_args[1]}" "threshold arg from TOML"
}

test_create_defects_default_threshold_medium() {
    # When TOML_SECURITY_SEVERITY_THRESHOLD is unset, default is "medium"
    TOML_SECURITY_SEVERITY_THRESHOLD=""
    local audit_file="${STATE_DIR}/features/test-feature/logs/security-audit.json"
    echo '{"summary":{"total":0,"by_severity":{}},"findings":[]}' > "$audit_file"
    local rc=0
    cmd_security --feature test-feature --create-defects 2>/dev/null || rc=$?
    assert_eq "medium" "${_create_defects_args[1]}" "default threshold is medium"
}

test_speed_script_contains_security_case() {
    local speed_script="${SCRIPT_DIR}/../speed"
    if ! grep -q "security)" "$speed_script"; then
        echo "    ASSERT: speed script does not contain 'security)' case" >&2
        return 1
    fi
}

test_speed_script_sources_security_lib() {
    local speed_script="${SCRIPT_DIR}/../speed"
    if ! grep -q 'lib/security.sh' "$speed_script"; then
        echo "    ASSERT: speed script does not source lib/security.sh" >&2
        return 1
    fi
}

# ── Run all tests ──────────────────────────────────────────────────────────────

echo ""
echo "cmd_security tests"
echo "──────────────────────────────────────"

run_test test_cmd_security_function_exists
run_test test_no_feature_exits_error
run_test test_feature_flag_sets_feature
run_test test_short_feature_flag
run_test test_active_feature_used_when_no_flag
run_test test_banner_printed_when_audit_file_exists
run_test test_no_findings_printed_when_no_audit_file
run_test test_unknown_flag_exits_error
run_test test_create_defects_calls_security_create_defects
run_test test_create_defects_uses_cached_when_recent
run_test test_create_defects_no_audit_file_exits_error
run_test test_create_defects_uses_toml_threshold
run_test test_create_defects_default_threshold_medium
run_test test_speed_script_contains_security_case
run_test test_speed_script_sources_security_lib

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
