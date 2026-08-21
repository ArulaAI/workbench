#!/usr/bin/env bash
# test_status.sh — Tests for security summary line in cmd_status()
#
# Verifies that cmd_status() prints the correct security summary when
# security log files are present, and omits it when they are absent.
#
# Usage: bash tests/test_status.sh
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

    # Minimal color stubs — no tty in tests
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" BOLD="" RESET=""
    SYM_CHECK="✓" SYM_CROSS="✗" SYM_WARN="⚠" SYM_PENDING="○" SYM_RUNNING="◉"

    # Source config to get STATE_DIR, FEATURES_DIR etc.
    # shellcheck source=../lib/config.sh
    source "${LIB_DIR}/config.sh"

    # Stub log functions
    log_header() { :; }
    log_info()   { :; }
    log_step()   { :; }
    log_error()  { echo "ERROR: $*" >&2; }
    log_warn()   { :; }
    log_verbose(){ :; }

    # Set up a test feature directory
    local feat_dir="${FEATURES_DIR}/test-feature"
    mkdir -p "${feat_dir}/tasks" "${feat_dir}/logs"

    # Write a minimal task so cmd_status doesn't bail out early
    echo '{"id":"1","title":"test task","status":"done","depends_on":[],"timeout_count":0,"retry_count":0}' \
        > "${feat_dir}/tasks/1.json"

    # Write a minimal state.json
    echo '{"status":"idle","agents":[]}' > "${feat_dir}/state.json"

    # Set active feature
    mkdir -p "$STATE_DIR"
    echo "test-feature" > "${STATE_DIR}/active_feature"

    # Set GLOBAL_FEATURE so cmd_status targets our test feature
    GLOBAL_FEATURE="test-feature"

    # Activate the feature (sets TASKS_DIR, LOGS_DIR, etc.)
    FEATURE_NAME="test-feature"
    FEATURE_DIR="${FEATURES_DIR}/test-feature"
    TASKS_DIR="${FEATURE_DIR}/tasks"
    LOGS_DIR="${FEATURE_DIR}/logs"
    CONTRACT_FILE="${FEATURE_DIR}/contract.json"
    STATE_FILE="${FEATURE_DIR}/state.json"
    WORKTREES_DIR="${STATE_DIR}/worktrees/test-feature"
    SPEED_LOCK="${FEATURE_DIR}/speed.lock"
    BRANCH_PREFIX="speed/test-feature"

    # Stub the functions cmd_status calls that are complex to fully set up
    feature_list()       { echo "test-feature"; }
    feature_get_active() { echo "test-feature"; }
    feature_activate()   { :; }  # Already activated above

    task_count_total()      { echo "1"; }
    task_print_graph()      { echo "  ✓  1  test task"; }
    task_print_summary()    { echo "Tasks: 1 total | 1 done | 0 running | 0 pending | 0 failed"; }
    task_count_by_status()  { echo "0"; }
    list_defects()          { echo ""; }

    # Source cmd/status.sh
    # shellcheck source=../lib/cmd/status.sh
    source "${LIB_DIR}/cmd/status.sh"
}

teardown() {
    rm -rf "$TEST_DIR"
    unset SPEED_PROJECT_ROOT GLOBAL_FEATURE
}

run_test() {
    local test_name="$1"
    setup
    local rc=0
    "$test_name" || rc=$?
    teardown
    if [[ $rc -eq 0 ]]; then
        printf "  PASS  %s\n" "$test_name"
        PASS=$(( PASS + 1 ))
    else
        printf "  FAIL  %s\n" "$test_name"
        FAIL=$(( FAIL + 1 ))
    fi
}

assert_output_contains() {
    local output="$1" pattern="$2"
    if ! echo "$output" | grep -qF "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:600}" >&2
        return 1
    fi
}

assert_output_not_contains() {
    local output="$1" pattern="$2"
    if echo "$output" | grep -qF "$pattern"; then
        echo "    ASSERT: output should NOT contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:600}" >&2
        return 1
    fi
}

# ── Tests ─────────────────────────────────────────────────────────

# No security log files → no Security: line in output
test_no_security_line_without_files() {
    local out
    out=$(cmd_status 2>/dev/null)
    assert_output_not_contains "$out" "Security:"
}

# security-audit.json with findings → warning line with count
test_security_line_audit_findings() {
    cat > "${LOGS_DIR}/security-audit.json" <<'EOF'
{
  "summary": {
    "total": 3,
    "by_severity": { "high": 2, "medium": 1 }
  },
  "findings": []
}
EOF
    local out
    out=$(cmd_status 2>/dev/null)
    assert_output_contains "$out" "Security:"
    assert_output_contains "$out" "3 findings"
    assert_output_contains "$out" "2 high"
    assert_output_contains "$out" "1 medium"
}

# security-audit.json with zero findings → success checkmark line
test_security_line_zero_findings() {
    cat > "${LOGS_DIR}/security-audit.json" <<'EOF'
{
  "summary": {
    "total": 0,
    "by_severity": {}
  },
  "findings": []
}
EOF
    local out
    out=$(cmd_status 2>/dev/null)
    assert_output_contains "$out" "Security:"
    assert_output_contains "$out" "no findings"
    assert_output_not_contains "$out" "findings ("
}

# sast-findings.json and sca-findings.json aggregate correctly
test_security_aggregates_sast_and_sca() {
    cat > "${LOGS_DIR}/sast-findings.json" <<'EOF'
[
  {"id": "SAST-001", "severity": "medium", "title": "sql-injection"},
  {"id": "SAST-002", "severity": "low", "title": "info-leak"}
]
EOF
    cat > "${LOGS_DIR}/sca-findings.json" <<'EOF'
[
  {"id": "SCA-001", "severity": "high", "title": "lodash vuln"}
]
EOF
    local out
    out=$(cmd_status 2>/dev/null)
    assert_output_contains "$out" "Security:"
    assert_output_contains "$out" "3 findings"
    assert_output_contains "$out" "1 high"
    assert_output_contains "$out" "1 medium"
    assert_output_contains "$out" "1 low"
}

# All three sources present — counts merge correctly
test_security_aggregates_all_three_sources() {
    cat > "${LOGS_DIR}/security-audit.json" <<'EOF'
{
  "summary": {
    "total": 2,
    "by_severity": { "critical": 1, "high": 1 }
  },
  "findings": []
}
EOF
    cat > "${LOGS_DIR}/sast-findings.json" <<'EOF'
[
  {"id": "SAST-001", "severity": "medium", "title": "xss"}
]
EOF
    cat > "${LOGS_DIR}/sca-findings.json" <<'EOF'
[
  {"id": "SCA-001", "severity": "info", "title": "outdated pkg"}
]
EOF
    local out
    out=$(cmd_status 2>/dev/null)
    assert_output_contains "$out" "Security:"
    assert_output_contains "$out" "4 findings"
    assert_output_contains "$out" "1 critical"
    assert_output_contains "$out" "1 high"
    assert_output_contains "$out" "1 medium"
    assert_output_contains "$out" "1 info"
}

# ── Main ──────────────────────────────────────────────────────────

echo "test_status.sh"
run_test test_no_security_line_without_files
run_test test_security_line_audit_findings
run_test test_security_line_zero_findings
run_test test_security_aggregates_sast_and_sca
run_test test_security_aggregates_all_three_sources

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
