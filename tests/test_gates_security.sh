#!/usr/bin/env bash
# test_gates_security.sh — Tests for gate_sast() and gate_sca() in lib/gates.sh
#
# Uses mock SAST/SCA tools (bash scripts outputting fixture JSON) to verify
# the security gate functions without requiring real scanners.
#
# Usage: bash tests/test_gates_security.sh
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

    # Stub colors and symbols (no escape sequences in test output)
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" COLOR_INFO=""
    BOLD="" RESET="" SYM_CHECK="ok" SYM_CROSS="fail" SYM_WARN="warn" SYM_PENDING="-"
    VERBOSITY=0

    # Stub log functions
    log_step()    { :; }
    log_info()    { :; }
    log_verbose() { :; }
    log_warn()    { echo "WARN: $*" >&2; }
    log_error()   { echo "ERROR: $*" >&2; }

    # Stub _context_python to use the system python3
    _context_python() { echo "python3"; }

    # Set up required directory structure
    PROJECT_ROOT="${TEST_DIR}/project"
    STATE_DIR="${TEST_DIR}/project/.speed"
    TASKS_DIR="${STATE_DIR}/tasks"
    LOGS_DIR="${STATE_DIR}/logs"
    mkdir -p "$PROJECT_ROOT" "$STATE_DIR" "$TASKS_DIR" "$LOGS_DIR"

    # Create a mock task file
    cat > "${TASKS_DIR}/test-task-1.json" <<'JSON'
{
  "id": "test-task-1",
  "feature": "test-feature",
  "description": "A test task",
  "files_touched": ["lib/gates.sh"]
}
JSON

    # Source security.sh (resets source guard if re-running)
    unset _SECURITY_SH_LOADED
    # shellcheck source=../lib/security.sh
    source "${LIB_DIR}/security.sh"

    # Source gates.sh (only the functions we need — skip grounding/config deps)
    # We source it manually since it depends on config.sh globals we've stubbed above
    source "${LIB_DIR}/gates.sh" 2>/dev/null || true
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

assert_eq() {
    local expected="$1" actual="$2" context="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected '${expected}', got '${actual}'${context:+ (${context})}" >&2
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

assert_json_valid() {
    local file="$1" label="${2:-$1}"
    if ! jq empty "$file" 2>/dev/null; then
        echo "    ASSERT: ${label} is not valid JSON" >&2
        return 1
    fi
}

assert_jq() {
    local file="$1" query="$2" expected="$3" label="${4:-$query}"
    local actual
    actual=$(jq -r "$query" "$file" 2>/dev/null)
    if [[ "$actual" != "$expected" ]]; then
        echo "    ASSERT: ${label}: expected '${expected}', got '${actual}'" >&2
        return 1
    fi
}

assert_file_exists() {
    local path="$1" label="${2:-$1}"
    if [[ ! -f "$path" ]]; then
        echo "    ASSERT: file not found: ${label}" >&2
        return 1
    fi
}

assert_file_not_exists() {
    local path="$1" label="${2:-$1}"
    if [[ -f "$path" ]]; then
        echo "    ASSERT: file should not exist: ${label}" >&2
        return 1
    fi
}

assert_results_contain() {
    local pattern="$1"
    local found=false
    for r in "${results[@]}"; do
        if echo "$r" | grep -q "$pattern"; then
            found=true
            break
        fi
    done
    if ! $found; then
        echo "    ASSERT: results array does not contain '${pattern}'" >&2
        echo "    RESULTS:" >&2
        for r in "${results[@]}"; do
            echo "      $r" >&2
        done
        return 1
    fi
}

# ── Mock SAST/SCA tools ───────────────────────────────────────────────────────

_create_mock_sast_tool() {
    # Creates a mock SAST tool that outputs Semgrep-format JSON
    local mock_path="${TEST_DIR}/mock-semgrep"
    cat > "$mock_path" <<'SCRIPT'
#!/usr/bin/env bash
cat <<'JSON'
{
  "results": [
    {
      "check_id": "python.django.security.injection.sql.django-sqli",
      "path": "app/views.py",
      "start": {"line": 42},
      "extra": {
        "severity": "ERROR",
        "message": "SQL injection risk"
      }
    },
    {
      "check_id": "python.flask.security.xss.template-injection",
      "path": "app/templates.py",
      "start": {"line": 15},
      "extra": {
        "severity": "WARNING",
        "message": "XSS via template injection"
      }
    }
  ]
}
JSON
SCRIPT
    chmod +x "$mock_path"
    echo "$mock_path"
}

_create_mock_sast_clean_tool() {
    # Mock SAST tool that reports zero findings
    local mock_path="${TEST_DIR}/mock-semgrep-clean"
    cat > "$mock_path" <<'SCRIPT'
#!/usr/bin/env bash
echo '{"results": []}'
SCRIPT
    chmod +x "$mock_path"
    echo "$mock_path"
}

_create_mock_sca_tool() {
    # Creates a mock SCA tool that outputs npm-audit-format JSON
    local mock_path="${TEST_DIR}/mock-npm-audit"
    cat > "$mock_path" <<'SCRIPT'
#!/usr/bin/env bash
cat <<'JSON'
{
  "vulnerabilities": {
    "lodash": {
      "severity": "high",
      "range": "<4.17.21",
      "via": [
        {
          "title": "Prototype Pollution in lodash",
          "severity": "high"
        }
      ],
      "fixAvailable": {
        "name": "lodash",
        "version": "4.17.21"
      }
    },
    "express": {
      "severity": "critical",
      "range": "<4.18.0",
      "via": [
        {
          "title": "Open Redirect in express",
          "severity": "critical"
        }
      ],
      "fixAvailable": true
    }
  }
}
JSON
SCRIPT
    chmod +x "$mock_path"
    echo "$mock_path"
}

_create_mock_sca_clean_tool() {
    # Mock SCA tool that reports zero findings
    local mock_path="${TEST_DIR}/mock-npm-audit-clean"
    cat > "$mock_path" <<'SCRIPT'
#!/usr/bin/env bash
echo '{"vulnerabilities": {}}'
SCRIPT
    chmod +x "$mock_path"
    echo "$mock_path"
}

_create_mock_missing_tool() {
    # Mock tool that fails with non-zero exit and no output (simulates missing binary)
    local mock_path="${TEST_DIR}/mock-missing-tool"
    cat > "$mock_path" <<'SCRIPT'
#!/usr/bin/env bash
exit 127
SCRIPT
    chmod +x "$mock_path"
    echo "$mock_path"
}

# ── Tests: gate_sast — empty config ──────────────────────────────────────────

test_sast_empty_cmd_returns_0() {
    TOML_SECURITY_SAST_CMD=""
    local results=()
    local rc=0
    gate_sast "test-task-1" "$PROJECT_ROOT" || rc=$?
    assert_exit_code 0 "$rc" "empty SAST cmd should return 0"
}

test_sast_empty_cmd_no_output() {
    TOML_SECURITY_SAST_CMD=""
    local results=()
    local output
    output=$(gate_sast "test-task-1" "$PROJECT_ROOT" 2>&1)
    assert_eq "" "$output" "empty SAST cmd should produce no output"
}

test_sast_empty_cmd_no_results() {
    TOML_SECURITY_SAST_CMD=""
    local results=()
    gate_sast "test-task-1" "$PROJECT_ROOT"
    assert_eq "0" "${#results[@]}" "empty SAST cmd should not append to results"
}

# ── Tests: gate_sast — with configured mock tool ────────────────────────────

test_sast_writes_output_files() {
    local mock_tool
    mock_tool=$(_create_mock_sast_tool)
    TOML_SECURITY_SAST_CMD="$mock_tool"
    local results=()

    gate_sast "test-task-1" "$PROJECT_ROOT"

    local logs_dir="${STATE_DIR}/features/test-feature/logs"
    assert_file_exists "${logs_dir}/sast-output.json" "sast-output.json"
    assert_file_exists "${logs_dir}/sast-findings.json" "sast-findings.json"
}

test_sast_parsed_findings_valid_json() {
    local mock_tool
    mock_tool=$(_create_mock_sast_tool)
    TOML_SECURITY_SAST_CMD="$mock_tool"
    local results=()

    gate_sast "test-task-1" "$PROJECT_ROOT"

    local findings="${STATE_DIR}/features/test-feature/logs/sast-findings.json"
    assert_json_valid "$findings" "sast-findings.json"
}

test_sast_findings_count() {
    local mock_tool
    mock_tool=$(_create_mock_sast_tool)
    TOML_SECURITY_SAST_CMD="$mock_tool"
    local results=()

    gate_sast "test-task-1" "$PROJECT_ROOT"

    local findings="${STATE_DIR}/features/test-feature/logs/sast-findings.json"
    local count
    count=$(jq 'length' "$findings")
    assert_eq "2" "$count" "should have 2 SAST findings"
}

test_sast_returns_0_with_findings() {
    local mock_tool
    mock_tool=$(_create_mock_sast_tool)
    TOML_SECURITY_SAST_CMD="$mock_tool"
    local results=()

    local rc=0
    gate_sast "test-task-1" "$PROJECT_ROOT" || rc=$?
    assert_exit_code 0 "$rc" "SAST should return 0 even with findings"
}

test_sast_results_contain_severity_summary() {
    local mock_tool
    mock_tool=$(_create_mock_sast_tool)
    TOML_SECURITY_SAST_CMD="$mock_tool"
    local results=()

    gate_sast "test-task-1" "$PROJECT_ROOT" >/dev/null 2>&1

    assert_results_contain "SAST: 2 finding"
}

test_sast_clean_shows_no_findings() {
    local mock_tool
    mock_tool=$(_create_mock_sast_clean_tool)
    TOML_SECURITY_SAST_CMD="$mock_tool"
    local results=()

    gate_sast "test-task-1" "$PROJECT_ROOT" >/dev/null 2>&1

    assert_results_contain "SAST: no findings"
}

# ── Tests: gate_sca — empty config ───────────────────────────────────────────

test_sca_empty_cmd_returns_0() {
    TOML_SECURITY_SCA_CMD=""
    local results=()
    local rc=0
    gate_sca "test-task-1" "$PROJECT_ROOT" || rc=$?
    assert_exit_code 0 "$rc" "empty SCA cmd should return 0"
}

test_sca_empty_cmd_no_output() {
    TOML_SECURITY_SCA_CMD=""
    local results=()
    local output
    output=$(gate_sca "test-task-1" "$PROJECT_ROOT" 2>&1)
    assert_eq "" "$output" "empty SCA cmd should produce no output"
}

# ── Tests: gate_sca — with configured mock tool ─────────────────────────────

test_sca_writes_output_files() {
    local mock_tool
    mock_tool=$(_create_mock_sca_tool)
    TOML_SECURITY_SCA_CMD="$mock_tool"
    local results=()

    gate_sca "test-task-1" "$PROJECT_ROOT"

    local logs_dir="${STATE_DIR}/features/test-feature/logs"
    assert_file_exists "${logs_dir}/sca-output.json" "sca-output.json"
    assert_file_exists "${logs_dir}/sca-findings.json" "sca-findings.json"
}

test_sca_findings_count() {
    local mock_tool
    mock_tool=$(_create_mock_sca_tool)
    TOML_SECURITY_SCA_CMD="$mock_tool"
    local results=()

    gate_sca "test-task-1" "$PROJECT_ROOT"

    local findings="${STATE_DIR}/features/test-feature/logs/sca-findings.json"
    local count
    count=$(jq 'length' "$findings")
    assert_eq "2" "$count" "should have 2 SCA findings"
}

test_sca_returns_0_with_findings() {
    local mock_tool
    mock_tool=$(_create_mock_sca_tool)
    TOML_SECURITY_SCA_CMD="$mock_tool"
    local results=()

    local rc=0
    gate_sca "test-task-1" "$PROJECT_ROOT" || rc=$?
    assert_exit_code 0 "$rc" "SCA should return 0 even with findings"
}

test_sca_results_contain_severity_summary() {
    local mock_tool
    mock_tool=$(_create_mock_sca_tool)
    TOML_SECURITY_SCA_CMD="$mock_tool"
    local results=()

    gate_sca "test-task-1" "$PROJECT_ROOT" >/dev/null 2>&1

    assert_results_contain "SCA: 2 finding"
}

test_sca_clean_shows_no_findings() {
    local mock_tool
    mock_tool=$(_create_mock_sca_clean_tool)
    TOML_SECURITY_SCA_CMD="$mock_tool"
    local results=()

    gate_sca "test-task-1" "$PROJECT_ROOT" >/dev/null 2>&1

    assert_results_contain "SCA: no findings"
}

# ── Tests: missing tool ──────────────────────────────────────────────────────

test_sast_missing_tool_warns() {
    local mock_tool
    mock_tool=$(_create_mock_missing_tool)
    TOML_SECURITY_SAST_CMD="$mock_tool"
    local results=()

    local output
    output=$(gate_sast "test-task-1" "$PROJECT_ROOT" 2>&1)
    local rc=$?

    assert_exit_code 0 "$rc" "missing tool should still return 0"
    if ! echo "$output" | grep -q "SAST tool failed"; then
        echo "    ASSERT: expected install hint warning in output" >&2
        echo "    OUTPUT: ${output}" >&2
        return 1
    fi
}

test_sca_missing_tool_warns() {
    local mock_tool
    mock_tool=$(_create_mock_missing_tool)
    TOML_SECURITY_SCA_CMD="$mock_tool"
    local results=()

    local output
    output=$(gate_sca "test-task-1" "$PROJECT_ROOT" 2>&1)
    local rc=$?

    assert_exit_code 0 "$rc" "missing tool should still return 0"
    if ! echo "$output" | grep -q "SCA tool failed"; then
        echo "    ASSERT: expected install hint warning in output" >&2
        echo "    OUTPUT: ${output}" >&2
        return 1
    fi
}

# ── Tests: gates_run integration ─────────────────────────────────────────────

test_gates_run_calls_security_gates() {
    # Verify gate_sast and gate_sca are called by gates_run by checking
    # that the functions exist and are callable from the same scope
    if ! declare -f gate_sast >/dev/null 2>&1; then
        echo "    ASSERT: gate_sast function not defined" >&2
        return 1
    fi
    if ! declare -f gate_sca >/dev/null 2>&1; then
        echo "    ASSERT: gate_sca function not defined" >&2
        return 1
    fi

    # Verify gates_run references gate_sast and gate_sca
    local gates_source
    gates_source=$(declare -f gates_run 2>/dev/null || true)
    if ! echo "$gates_source" | grep -q "gate_sast"; then
        echo "    ASSERT: gates_run does not call gate_sast" >&2
        return 1
    fi
    if ! echo "$gates_source" | grep -q "gate_sca"; then
        echo "    ASSERT: gates_run does not call gate_sca" >&2
        return 1
    fi
}

# ── Run all tests ──────────────────────────────────────────────────────────────

echo ""
echo "Security gate tests (gate_sast / gate_sca)"
echo "──────────────────────────────────────"

# gate_sast: empty config
run_test test_sast_empty_cmd_returns_0
run_test test_sast_empty_cmd_no_output
run_test test_sast_empty_cmd_no_results

# gate_sast: with mock tool
run_test test_sast_writes_output_files
run_test test_sast_parsed_findings_valid_json
run_test test_sast_findings_count
run_test test_sast_returns_0_with_findings
run_test test_sast_results_contain_severity_summary
run_test test_sast_clean_shows_no_findings

# gate_sca: empty config
run_test test_sca_empty_cmd_returns_0
run_test test_sca_empty_cmd_no_output

# gate_sca: with mock tool
run_test test_sca_writes_output_files
run_test test_sca_findings_count
run_test test_sca_returns_0_with_findings
run_test test_sca_results_contain_severity_summary
run_test test_sca_clean_shows_no_findings

# Missing tool
run_test test_sast_missing_tool_warns
run_test test_sca_missing_tool_warns

# Integration
run_test test_gates_run_calls_security_gates

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
