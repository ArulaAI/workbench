#!/usr/bin/env bash
# test_security_audit.sh — Tests for security audit orchestration and defect creation
#
# Tests: security_audit_run, security_has_cached_audit, security_create_defects
# Does NOT require a live Claude connection (stubs provider_run_json).
#
# Usage: bash tests/test_security_audit.sh
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

    # Stub color/log variables
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" COLOR_STEP=""
    BOLD="" RESET="" SYM_CROSS="" SYM_WARN="" SYM_ARROW="" SYM_CHECK=""
    COLOR_HEADER="" COLOR_INFO=""
    VERBOSITY=0

    # Set paths that security.sh and config.sh depend on
    export STATE_DIR="${TEST_DIR}/.speed"
    export SPEED_DIR="${SCRIPT_DIR}/.."
    export MODEL_SUPPORT="sonnet"
    export DEFAULT_JSON_MAX_TURNS=3
    export PROJECT_ROOT="$TEST_DIR"

    mkdir -p "${STATE_DIR}"

    # Stub _context_python
    _context_python() { echo "python3"; }

    # Stub log functions
    log_step() { :; }
    log_error() { :; }
    log_warn() { :; }
    log_success() { :; }
    log_verbose() { :; }

    # Source security.sh (resets source guard)
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
        echo "    OUTPUT: ${output:0:400}" >&2
        return 1
    fi
}

# ── Helpers: mock audit JSON ───────────────────────────────────────────────────

make_audit_json() {
    local path="$1"
    cat > "$path" <<'AUDITJSON'
{
  "feature": "my-feature",
  "timestamp": "2026-02-26T12:00:00Z",
  "findings": [
    {
      "id": "SEC-001",
      "severity": "critical",
      "category": "injection",
      "title": "SQL Injection in User Query",
      "description": "Unsanitized user input passed to SQL query",
      "file": "lib/db.py",
      "line": 42,
      "snippet": "cursor.execute(f\"SELECT * FROM users WHERE id={user_id}\")",
      "recommendation": "Use parameterized queries"
    },
    {
      "id": "SEC-002",
      "severity": "high",
      "category": "auth",
      "title": "Missing Auth Check",
      "description": "Admin endpoint lacks authentication middleware",
      "file": "lib/routes.py",
      "line": 88,
      "snippet": "@app.route('/admin')",
      "recommendation": "Add @require_auth decorator"
    },
    {
      "id": "SEC-003",
      "severity": "medium",
      "category": "crypto",
      "title": "Weak Hash Algorithm",
      "description": "Using MD5 for password hashing",
      "file": "lib/auth.py",
      "line": 15,
      "snippet": "hashlib.md5(password.encode())",
      "recommendation": "Use bcrypt or argon2"
    },
    {
      "id": "SEC-004",
      "severity": "low",
      "category": "config",
      "title": "Debug Mode Enabled",
      "description": "Debug mode is enabled in production config",
      "file": "config.py",
      "line": 3,
      "snippet": "DEBUG = True",
      "recommendation": "Set DEBUG = False in production"
    },
    {
      "id": "SEC-005",
      "severity": "info",
      "category": "info-disclosure",
      "title": "Verbose Error Messages",
      "description": "Stack traces shown to users",
      "file": "lib/errors.py",
      "line": 20,
      "snippet": "return traceback.format_exc()",
      "recommendation": "Return generic error message in production"
    }
  ],
  "summary": {
    "total": 5,
    "by_severity": {
      "critical": 1,
      "high": 1,
      "medium": 1,
      "low": 1,
      "info": 1
    }
  }
}
AUDITJSON
}

# ── Tests: security_audit_run ──────────────────────────────────────────────────

test_audit_run_function_exists() {
    declare -f security_audit_run >/dev/null 2>&1
    assert_exit_code 0 $? "security_audit_run should be declared"
}

test_audit_run_creates_logs_dir() {
    local feature="test-feat"
    local logs_dir="${STATE_DIR}/features/${feature}/logs"

    # Stub context_assemble and provider to return empty
    context_assemble_security_auditor() { echo ""; }
    provider_run_json() { echo ""; }
    parse_agent_json() { return 1; }

    security_audit_run "$feature"

    if [[ ! -d "$logs_dir" ]]; then
        echo "    ASSERT: logs dir not created: ${logs_dir}" >&2
        return 1
    fi
}

test_audit_run_returns_0_on_empty_context() {
    # When context assembly returns empty, should log_error and return 0
    context_assemble_security_auditor() { echo ""; }

    local rc=0
    security_audit_run "empty-feat" || rc=$?
    assert_exit_code 0 "$rc" "should return 0 on empty context"
}

test_audit_run_returns_0_on_unparseable_output() {
    local feature="bad-output"
    mkdir -p "${STATE_DIR}/features/${feature}/logs"

    context_assemble_security_auditor() { echo "some prompt content"; }
    provider_run_json() { echo "this is not json at all"; }

    local rc=0
    security_audit_run "$feature" || rc=$?
    assert_exit_code 0 "$rc" "should return 0 on unparseable output"
}

test_audit_run_writes_audit_json() {
    local feature="good-feat"
    local logs_dir="${STATE_DIR}/features/${feature}/logs"

    context_assemble_security_auditor() { echo "audit this code"; }
    provider_run_json() {
        echo '{"feature":"good-feat","findings":[],"summary":{"total":0,"by_severity":{}}}'
    }
    parse_agent_json() {
        local raw="${1:-$(cat)}"
        echo "$raw"
        return 0
    }

    security_audit_run "$feature"

    assert_file_exists "${logs_dir}/security-audit.json"

    # Validate it's valid JSON
    if ! jq empty "${logs_dir}/security-audit.json" 2>/dev/null; then
        echo "    ASSERT: security-audit.json is not valid JSON" >&2
        return 1
    fi
}

test_audit_run_writes_findings_to_json() {
    local feature="findings-feat"
    local logs_dir="${STATE_DIR}/features/${feature}/logs"

    local good_json='{"feature":"findings-feat","findings":[{"id":"SEC-001","severity":"high","title":"XSS Bug"}],"summary":{"total":1}}'

    context_assemble_security_auditor() { echo "audit prompt"; }
    provider_run_json() { echo "$good_json"; }
    parse_agent_json() {
        local raw="${1:-$(cat)}"
        echo "$raw"
        return 0
    }

    security_audit_run "$feature"

    local total
    total=$(jq -r '.summary.total' "${logs_dir}/security-audit.json")
    assert_eq "1" "$total" "should have 1 finding in JSON"
}

# ── Tests: security_has_cached_audit ───────────────────────────────────────────

test_cached_audit_function_exists() {
    declare -f security_has_cached_audit >/dev/null 2>&1
    assert_exit_code 0 $? "security_has_cached_audit should be declared"
}

test_cached_audit_returns_1_when_missing() {
    local rc=0
    security_has_cached_audit "nonexistent-feature" || rc=$?
    assert_exit_code 1 "$rc" "should return 1 when audit file missing"
}

test_cached_audit_returns_0_for_fresh_file() {
    local feature="fresh-feat"
    local logs_dir="${STATE_DIR}/features/${feature}/logs"
    mkdir -p "$logs_dir"

    # Create a fresh file (just created = 0 seconds old)
    echo '{"findings":[]}' > "${logs_dir}/security-audit.json"

    local rc=0
    security_has_cached_audit "$feature" || rc=$?
    assert_exit_code 0 "$rc" "should return 0 for file < 1 hour old"
}

test_cached_audit_returns_1_for_old_file() {
    local feature="old-feat"
    local logs_dir="${STATE_DIR}/features/${feature}/logs"
    mkdir -p "$logs_dir"

    echo '{"findings":[]}' > "${logs_dir}/security-audit.json"

    # Backdate the file by 2 hours (7200 seconds)
    if [[ "$(uname -s)" == "Darwin" ]]; then
        touch -t "$(date -v-2H '+%Y%m%d%H%M.%S')" "${logs_dir}/security-audit.json"
    else
        touch -d "2 hours ago" "${logs_dir}/security-audit.json"
    fi

    local rc=0
    security_has_cached_audit "$feature" || rc=$?
    assert_exit_code 1 "$rc" "should return 1 for file > 1 hour old"
}

# ── Tests: security_create_defects ─────────────────────────────────────────────

test_create_defects_function_exists() {
    declare -f security_create_defects >/dev/null 2>&1
    assert_exit_code 0 $? "security_create_defects should be declared"
}

test_create_defects_returns_1_on_missing_json() {
    local rc=0
    security_create_defects "/nonexistent/path.json" "medium" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "should return 1 when JSON missing"
}

test_create_defects_returns_1_on_empty_path() {
    local rc=0
    security_create_defects "" "medium" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "should return 1 on empty path"
}

test_create_defects_creates_specs_defects_dir() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    security_create_defects "$audit_json" "critical" >/dev/null

    if [[ ! -d "${TEST_DIR}/specs/defects" ]]; then
        echo "    ASSERT: specs/defects/ not created" >&2
        return 1
    fi
}

test_create_defects_creates_files_at_threshold() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    local output
    output=$(security_create_defects "$audit_json" "medium")

    # Should create defects for critical, high, and medium (3 findings)
    assert_output_contains "$output" "3 defect(s) created"
}

test_create_defects_skips_below_threshold() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    local output
    output=$(security_create_defects "$audit_json" "medium")

    # Should skip low and info (2 findings)
    assert_output_contains "$output" "2 skipped"
}

test_create_defects_critical_only_threshold() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    local output
    output=$(security_create_defects "$audit_json" "critical")

    # Only 1 critical finding
    assert_output_contains "$output" "1 defect(s) created"
    assert_output_contains "$output" "4 skipped"
}

test_create_defects_all_with_info_threshold() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    local output
    output=$(security_create_defects "$audit_json" "info")

    # All 5 findings at or above info
    assert_output_contains "$output" "5 defect(s) created"
    assert_output_contains "$output" "0 skipped"
}

test_create_defects_severity_mapping_critical_p0() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    security_create_defects "$audit_json" "critical" >/dev/null

    # Find the critical finding defect file
    local defect_file
    defect_file=$(ls specs/defects/sec-sql-injection-in-user-query*.md 2>/dev/null | head -1)
    assert_file_exists "$defect_file"
    assert_file_contains "$defect_file" "Severity: P0"
}

test_create_defects_severity_mapping_high_p1() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    security_create_defects "$audit_json" "high" >/dev/null

    local defect_file
    defect_file=$(ls specs/defects/sec-missing-auth-check*.md 2>/dev/null | head -1)
    assert_file_exists "$defect_file"
    assert_file_contains "$defect_file" "Severity: P1"
}

test_create_defects_severity_mapping_medium_p2() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    security_create_defects "$audit_json" "medium" >/dev/null

    local defect_file
    defect_file=$(ls specs/defects/sec-weak-hash-algorithm*.md 2>/dev/null | head -1)
    assert_file_exists "$defect_file"
    assert_file_contains "$defect_file" "Severity: P2"
}

test_create_defects_severity_mapping_low_p3() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    security_create_defects "$audit_json" "info" >/dev/null

    local defect_file
    defect_file=$(ls specs/defects/sec-debug-mode-enabled*.md 2>/dev/null | head -1)
    assert_file_exists "$defect_file"
    assert_file_contains "$defect_file" "Severity: P3"
}

test_create_defects_contains_classification_override() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    security_create_defects "$audit_json" "critical" >/dev/null

    local defect_file
    defect_file=$(ls specs/defects/sec-*.md 2>/dev/null | head -1)
    assert_file_exists "$defect_file"
    assert_file_contains "$defect_file" "Classification-Override: moderate"
}

test_create_defects_contains_tags_security() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    security_create_defects "$audit_json" "critical" >/dev/null

    local defect_file
    defect_file=$(ls specs/defects/sec-*.md 2>/dev/null | head -1)
    assert_file_exists "$defect_file"
    assert_file_contains "$defect_file" "Tags: security"
}

test_create_defects_contains_related_feature() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    security_create_defects "$audit_json" "critical" >/dev/null

    local defect_file
    defect_file=$(ls specs/defects/sec-*.md 2>/dev/null | head -1)
    assert_file_exists "$defect_file"
    assert_file_contains "$defect_file" "Related Feature: my-feature"
}

test_create_defects_slug_format() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    security_create_defects "$audit_json" "critical" >/dev/null

    # Check that the file uses sec- prefix and slugified title
    local defect_file
    defect_file=$(ls specs/defects/sec-sql-injection-in-user-query*.md 2>/dev/null | head -1)
    assert_file_exists "$defect_file"
}

test_create_defects_slug_truncation() {
    # Create audit JSON with a very long title
    local audit_json="${TEST_DIR}/long-title-audit.json"
    cat > "$audit_json" <<'EOF'
{
  "feature": "truncation-test",
  "findings": [
    {
      "id": "SEC-001",
      "severity": "critical",
      "category": "injection",
      "title": "This Is A Very Long Title That Should Be Truncated To Forty Characters Maximum",
      "description": "desc",
      "file": "lib/foo.py",
      "line": 1,
      "snippet": "code",
      "recommendation": "fix it"
    }
  ],
  "summary": {"total": 1, "by_severity": {"critical": 1}}
}
EOF

    cd "$TEST_DIR"
    security_create_defects "$audit_json" "critical" >/dev/null

    # Verify the slug part of the filename is <= 40 chars
    local defect_file
    defect_file=$(ls specs/defects/sec-*.md 2>/dev/null | head -1)
    assert_file_exists "$defect_file"

    local filename
    filename=$(basename "$defect_file")
    # Strip "sec-" prefix and ".md" suffix to get the slug
    local slug="${filename#sec-}"
    slug="${slug%.md}"
    local slug_len=${#slug}
    if [[ $slug_len -gt 40 ]]; then
        echo "    ASSERT: slug length ${slug_len} exceeds 40 char limit: '${slug}'" >&2
        return 1
    fi
}

test_create_defects_empty_findings() {
    local audit_json="${TEST_DIR}/empty-audit.json"
    cat > "$audit_json" <<'EOF'
{
  "feature": "empty-feat",
  "findings": [],
  "summary": {"total": 0, "by_severity": {}}
}
EOF

    cd "$TEST_DIR"
    local output
    output=$(security_create_defects "$audit_json" "medium")

    assert_output_contains "$output" "0 defect(s) created"
    assert_output_contains "$output" "0 skipped"
}

test_create_defects_defect_file_content() {
    local audit_json="${TEST_DIR}/audit.json"
    make_audit_json "$audit_json"

    cd "$TEST_DIR"
    security_create_defects "$audit_json" "critical" >/dev/null

    local defect_file
    defect_file=$(ls specs/defects/sec-sql-injection-in-user-query*.md 2>/dev/null | head -1)

    # Verify all required fields
    assert_file_contains "$defect_file" "Severity: P0"
    assert_file_contains "$defect_file" "Related Feature: my-feature"
    assert_file_contains "$defect_file" "Tags: security"
    assert_file_contains "$defect_file" "Classification-Override: moderate"
    assert_file_contains "$defect_file" "Observed:"
    assert_file_contains "$defect_file" "Expected:"
    assert_file_contains "$defect_file" "Repro:"
    assert_file_contains "$defect_file" "lib/db.py"
}

# ── Main ──────────────────────────────────────────────────────────────────────

echo "Running security audit orchestration tests..."
echo ""

# security_audit_run
echo "security_audit_run:"
run_test test_audit_run_function_exists
run_test test_audit_run_creates_logs_dir
run_test test_audit_run_returns_0_on_empty_context
run_test test_audit_run_returns_0_on_unparseable_output
run_test test_audit_run_writes_audit_json
run_test test_audit_run_writes_findings_to_json
echo ""

# security_has_cached_audit
echo "security_has_cached_audit:"
run_test test_cached_audit_function_exists
run_test test_cached_audit_returns_1_when_missing
run_test test_cached_audit_returns_0_for_fresh_file
run_test test_cached_audit_returns_1_for_old_file
echo ""

# security_create_defects
echo "security_create_defects:"
run_test test_create_defects_function_exists
run_test test_create_defects_returns_1_on_missing_json
run_test test_create_defects_returns_1_on_empty_path
run_test test_create_defects_creates_specs_defects_dir
run_test test_create_defects_creates_files_at_threshold
run_test test_create_defects_skips_below_threshold
run_test test_create_defects_critical_only_threshold
run_test test_create_defects_all_with_info_threshold
run_test test_create_defects_severity_mapping_critical_p0
run_test test_create_defects_severity_mapping_high_p1
run_test test_create_defects_severity_mapping_medium_p2
run_test test_create_defects_severity_mapping_low_p3
run_test test_create_defects_contains_classification_override
run_test test_create_defects_contains_tags_security
run_test test_create_defects_contains_related_feature
run_test test_create_defects_slug_format
run_test test_create_defects_slug_truncation
run_test test_create_defects_empty_findings
run_test test_create_defects_defect_file_content
echo ""

echo "────────────────────────────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
