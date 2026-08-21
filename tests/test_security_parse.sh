#!/usr/bin/env bash
# test_security_parse.sh — Tests for lib/security.sh parse functions and helpers
#
# Tests: severity comparison, SAST/SCA parsers, banner output.
# Does NOT require a live Claude connection.
#
# Usage: bash tests/test_security_parse.sh
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

    # Source minimal stubs for config.sh / log.sh / colors.sh dependencies
    # so security.sh can be sourced in isolation.
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" BOLD="" RESET=""
    VERBOSITY=0

    # Stub _context_python to use the system python3
    _context_python() { echo "python3"; }

    # Source security.sh (resets source guard if re-running)
    unset _SECURITY_SH_LOADED
    # shellcheck source=../lib/security.sh
    source "${LIB_DIR}/security.sh"
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

assert_output_contains() {
    local output="$1" pattern="$2"
    if ! echo "$output" | grep -q "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:400}" >&2
        return 1
    fi
}

# ── Tests: _severity_at_or_above ──────────────────────────────────────────────

test_severity_high_gte_medium() {
    local rc=0
    _severity_at_or_above "high" "medium" || rc=$?
    assert_exit_code 0 "$rc" "high >= medium should return 0 (true)"
}

test_severity_low_not_gte_high() {
    local rc=0
    _severity_at_or_above "low" "high" && rc=99 || rc=$?
    # Should return 1 (false) — non-zero
    if [[ "$rc" -eq 0 ]]; then
        echo "    ASSERT: low >= high should return non-zero (false), got 0" >&2
        return 1
    fi
}

test_severity_equal_medium() {
    local rc=0
    _severity_at_or_above "medium" "medium" || rc=$?
    assert_exit_code 0 "$rc" "medium >= medium should return 0 (true)"
}

test_severity_critical_gte_info() {
    local rc=0
    _severity_at_or_above "critical" "info" || rc=$?
    assert_exit_code 0 "$rc" "critical >= info should return 0 (true)"
}

test_severity_info_not_gte_low() {
    local rc=0
    _severity_at_or_above "info" "low" && rc=99 || rc=$?
    if [[ "$rc" -eq 0 ]]; then
        echo "    ASSERT: info >= low should return non-zero (false), got 0" >&2
        return 1
    fi
}

# ── Tests: security_sast_parse — Semgrep ──────────────────────────────────────

_semgrep_fixture() {
    cat > "${TEST_DIR}/semgrep.json" <<'JSON'
{
  "results": [
    {
      "check_id": "python.django.security.injection.sql.django-sqli",
      "path": "app/views.py",
      "start": {"line": 42},
      "extra": {
        "severity": "ERROR",
        "message": "SQL injection risk in raw query"
      }
    },
    {
      "check_id": "python.flask.security.xss.template-injection",
      "path": "app/templates.py",
      "start": {"line": 15},
      "extra": {
        "severity": "WARNING",
        "message": "Potential XSS via template injection"
      }
    },
    {
      "check_id": "python.crypto.weak-hash",
      "path": "app/auth.py",
      "start": {"line": 7},
      "extra": {
        "severity": "INFO",
        "message": "Weak hash algorithm"
      }
    }
  ]
}
JSON
}

test_sast_semgrep_valid_json_array() {
    _semgrep_fixture
    local out="${TEST_DIR}/findings.json"
    security_sast_parse "${TEST_DIR}/semgrep.json" "$out"
    assert_json_valid "$out" "semgrep output"
    local count
    count=$(jq 'length' "$out")
    assert_eq "3" "$count" "finding count"
}

test_sast_semgrep_fields_present() {
    _semgrep_fixture
    local out="${TEST_DIR}/findings.json"
    security_sast_parse "${TEST_DIR}/semgrep.json" "$out"

    # Check first finding has required fields
    assert_jq "$out" '.[0].id' "SAST-001" "id field"
    assert_jq "$out" '.[0].severity' "high" "severity field (ERROR->high)"
    assert_jq "$out" '.[0].file' "app/views.py" "file field"
    assert_jq "$out" '.[0].line' "42" "line field"
    local title
    title=$(jq -r '.[0].title' "$out")
    if [[ -z "$title" ]]; then
        echo "    ASSERT: title field is empty" >&2
        return 1
    fi
}

test_sast_semgrep_severity_mapping() {
    _semgrep_fixture
    local out="${TEST_DIR}/findings.json"
    security_sast_parse "${TEST_DIR}/semgrep.json" "$out"

    assert_jq "$out" '.[0].severity' "high"   "ERROR -> high"
    assert_jq "$out" '.[1].severity' "medium" "WARNING -> medium"
    assert_jq "$out" '.[2].severity' "low"    "INFO -> low"
}

test_sast_semgrep_injection_category() {
    _semgrep_fixture
    local out="${TEST_DIR}/findings.json"
    security_sast_parse "${TEST_DIR}/semgrep.json" "$out"

    assert_jq "$out" '.[0].category' "injection" "sqli check_id -> injection category"
}

test_sast_semgrep_xss_category() {
    _semgrep_fixture
    local out="${TEST_DIR}/findings.json"
    security_sast_parse "${TEST_DIR}/semgrep.json" "$out"

    assert_jq "$out" '.[1].category' "xss" "xss check_id -> xss category"
}

# ── Tests: security_sast_parse — Bandit ───────────────────────────────────────

_bandit_fixture() {
    cat > "${TEST_DIR}/bandit.json" <<'JSON'
{
  "generated_at": "2024-01-01T00:00:00Z",
  "results": [
    {
      "test_name": "hardcoded_password_string",
      "filename": "app/config.py",
      "line_number": 10,
      "issue_severity": "HIGH",
      "issue_text": "Possible hardcoded password"
    },
    {
      "test_name": "subprocess_popen_with_shell_equals_true",
      "filename": "app/utils.py",
      "line_number": 33,
      "issue_severity": "MEDIUM",
      "issue_text": "Use of subprocess with shell=True"
    }
  ]
}
JSON
}

test_sast_bandit_valid_json_array() {
    _bandit_fixture
    local out="${TEST_DIR}/findings.json"
    security_sast_parse "${TEST_DIR}/bandit.json" "$out"
    assert_json_valid "$out" "bandit output"
    local count
    count=$(jq 'length' "$out")
    assert_eq "2" "$count" "bandit finding count"
}

test_sast_bandit_fields_present() {
    _bandit_fixture
    local out="${TEST_DIR}/findings.json"
    security_sast_parse "${TEST_DIR}/bandit.json" "$out"

    assert_jq "$out" '.[0].id' "SAST-001" "id field"
    assert_jq "$out" '.[0].severity' "high" "HIGH -> high"
    assert_jq "$out" '.[0].file' "app/config.py" "file field"
    assert_jq "$out" '.[0].line' "10" "line field"
    assert_jq "$out" '.[0].title' "hardcoded_password_string" "title from test_name"
}

# ── Tests: security_sast_parse — error cases ──────────────────────────────────

test_sast_missing_file_writes_empty_array() {
    local out="${TEST_DIR}/findings.json"
    security_sast_parse "/nonexistent/path.json" "$out"
    assert_json_valid "$out" "missing file output"
    assert_jq "$out" 'length' "0" "empty array for missing file"
}

test_sast_malformed_json_writes_empty_array() {
    echo "this is not json {{{" > "${TEST_DIR}/bad.json"
    local out="${TEST_DIR}/findings.json"
    security_sast_parse "${TEST_DIR}/bad.json" "$out"
    assert_json_valid "$out" "malformed json output"
    assert_jq "$out" 'length' "0" "empty array for malformed JSON"
}

# ── Tests: security_sca_parse — npm audit ─────────────────────────────────────

_npm_fixture() {
    cat > "${TEST_DIR}/npm-audit.json" <<'JSON'
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
      "severity": "moderate",
      "range": "<4.18.0",
      "via": ["lodash"],
      "fixAvailable": true
    }
  }
}
JSON
}

test_sca_npm_valid_json_array() {
    _npm_fixture
    local out="${TEST_DIR}/findings.json"
    security_sca_parse "${TEST_DIR}/npm-audit.json" "$out"
    assert_json_valid "$out" "npm audit output"
    local count
    count=$(jq 'length' "$out")
    assert_eq "2" "$count" "npm audit finding count"
}

test_sca_npm_fields_present() {
    _npm_fixture
    local out="${TEST_DIR}/findings.json"
    security_sca_parse "${TEST_DIR}/npm-audit.json" "$out"

    # Check id prefix format
    local id
    id=$(jq -r '.[0].id' "$out")
    if ! echo "$id" | grep -q "^SCA-"; then
        echo "    ASSERT: id should start with SCA-, got '${id}'" >&2
        return 1
    fi

    # Check recommendation present
    local rec
    rec=$(jq -r '.[0].recommendation' "$out")
    if [[ -z "$rec" ]]; then
        echo "    ASSERT: recommendation field is empty" >&2
        return 1
    fi
}

test_sca_npm_moderate_maps_to_medium() {
    _npm_fixture
    local out="${TEST_DIR}/findings.json"
    security_sca_parse "${TEST_DIR}/npm-audit.json" "$out"

    # Find the express entry (moderate severity)
    local express_severity
    express_severity=$(jq -r '.[] | select(.package == "express") | .severity' "$out")
    assert_eq "medium" "$express_severity" "npm moderate -> medium severity"
}

# ── Tests: security_sca_parse — pip-audit ─────────────────────────────────────

_pip_fixture() {
    cat > "${TEST_DIR}/pip-audit.json" <<'JSON'
[
  {
    "name": "requests",
    "vulns": [
      {
        "id": "CVE-2023-32681",
        "description": "Requests forwards proxy-authorization headers to destination",
        "fix_versions": ["2.31.0"]
      }
    ]
  },
  {
    "name": "pillow",
    "vulns": [
      {
        "id": "CVE-2023-44271",
        "description": "Uncontrolled resource consumption in PIL",
        "fix_versions": []
      }
    ]
  }
]
JSON
}

test_sca_pip_valid_json_array() {
    _pip_fixture
    local out="${TEST_DIR}/findings.json"
    security_sca_parse "${TEST_DIR}/pip-audit.json" "$out"
    assert_json_valid "$out" "pip-audit output"
    local count
    count=$(jq 'length' "$out")
    assert_eq "2" "$count" "pip-audit finding count"
}

test_sca_pip_cve_in_title() {
    _pip_fixture
    local out="${TEST_DIR}/findings.json"
    security_sca_parse "${TEST_DIR}/pip-audit.json" "$out"

    local title
    title=$(jq -r '.[0].title' "$out")
    if ! echo "$title" | grep -q "CVE-2023-32681"; then
        echo "    ASSERT: title should contain CVE ID, got '${title}'" >&2
        return 1
    fi
}

test_sca_missing_file_writes_empty_array() {
    local out="${TEST_DIR}/findings.json"
    security_sca_parse "/nonexistent/path.json" "$out"
    assert_json_valid "$out" "missing file output"
    assert_jq "$out" 'length' "0" "empty array for missing file"
}

# ── Tests: security_print_banner ──────────────────────────────────────────────

_banner_fixture() {
    cat > "${TEST_DIR}/security-audit.json" <<'JSON'
{
  "summary": {
    "total": 3,
    "by_severity": {
      "critical": 0,
      "high": 1,
      "medium": 1,
      "low": 1,
      "info": 0
    }
  },
  "findings": [
    {
      "id": "SAST-001",
      "severity": "high",
      "title": "SQL injection",
      "file": "app/views.py",
      "line": 42,
      "message": "Raw SQL query"
    },
    {
      "id": "SCA-001",
      "severity": "medium",
      "title": "Prototype Pollution",
      "file": "",
      "line": 0,
      "message": "lodash vulnerability"
    },
    {
      "id": "SAST-002",
      "severity": "low",
      "title": "Weak hash",
      "file": "app/auth.py",
      "line": 7,
      "message": "MD5 usage"
    }
  ]
}
JSON
}

test_banner_severity_breakdown() {
    _banner_fixture
    local output
    output=$(security_print_banner "${TEST_DIR}/security-audit.json" 2>&1)
    assert_output_contains "$output" "High"
}

test_banner_missing_file_graceful() {
    local output
    output=$(security_print_banner "/nonexistent/security-audit.json" 2>&1)
    assert_output_contains "$output" "No security audit results"
}

test_banner_warn_not_block_message() {
    _banner_fixture
    local output
    output=$(security_print_banner "${TEST_DIR}/security-audit.json" 2>&1)
    assert_output_contains "$output" "Gate not blocking"
}

# ── Run all tests ──────────────────────────────────────────────────────────────

echo ""
echo "Security parse tests"
echo "──────────────────────────────────────"

# Severity helpers
run_test test_severity_high_gte_medium
run_test test_severity_low_not_gte_high
run_test test_severity_equal_medium
run_test test_severity_critical_gte_info
run_test test_severity_info_not_gte_low

# SAST: Semgrep
run_test test_sast_semgrep_valid_json_array
run_test test_sast_semgrep_fields_present
run_test test_sast_semgrep_severity_mapping
run_test test_sast_semgrep_injection_category
run_test test_sast_semgrep_xss_category

# SAST: Bandit
run_test test_sast_bandit_valid_json_array
run_test test_sast_bandit_fields_present

# SAST: error cases
run_test test_sast_missing_file_writes_empty_array
run_test test_sast_malformed_json_writes_empty_array

# SCA: npm audit
run_test test_sca_npm_valid_json_array
run_test test_sca_npm_fields_present
run_test test_sca_npm_moderate_maps_to_medium

# SCA: pip-audit
run_test test_sca_pip_valid_json_array
run_test test_sca_pip_cve_in_title
run_test test_sca_missing_file_writes_empty_array

# Banner
run_test test_banner_severity_breakdown
run_test test_banner_missing_file_graceful
run_test test_banner_warn_not_block_message

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
