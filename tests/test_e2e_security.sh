#!/usr/bin/env bash
# test_e2e_security.sh — End-to-end integration tests for the full security pipeline
#
# Covers: SAST gates, SCA gates, no-config graceful skip, secrets blocking,
# secrets exclusion, speed security command, defect creation, status security line.
# Tests 1-3 provide regression coverage for the full gate wiring path (not
# strictly e2e but intentional overlap with test_gates_security.sh).
#
# Each test creates an isolated fixture environment (temp dirs, mock tools,
# speed.toml, task JSONs), runs the function under test, and asserts on
# output content and file existence.
#
# Requires: bash 4+ (for associative arrays in cmd_status), jq, git, python3
# Usage: bash tests/test_e2e_security.sh
# Exit: 0 if all tests pass, 1 if any fail

if [[ "${BASH_VERSION%%.*}" -lt 4 ]]; then
    echo "ERROR: bash 4+ required (found ${BASH_VERSION}). Install via: brew install bash" >&2
    exit 1
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
PASS=0
FAIL=0
TEST_DIR=""

# ── Test Harness ─────────────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)

    # Stub colors and symbols
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" COLOR_STEP=""
    COLOR_INFO="" COLOR_HEADER=""
    BOLD="" RESET="" SYM_CHECK="ok" SYM_CROSS="fail" SYM_WARN="warn"
    SYM_PENDING="-" SYM_ARROW="->"
    VERBOSITY=0

    # Stub log functions
    log_step()    { :; }
    log_info()    { :; }
    log_verbose() { :; }
    log_debug()   { :; }
    log_success() { :; }
    log_header()  { :; }
    log_warn()    { echo "WARN: $*" >&2; }
    log_error()   { echo "ERROR: $*" >&2; }

    # Stub _context_python to use system python3
    _context_python() { echo "python3"; }

    # Set up directory structure
    PROJECT_ROOT="${TEST_DIR}/project"
    STATE_DIR="${PROJECT_ROOT}/.speed"
    FEATURES_DIR="${STATE_DIR}/features"
    TASKS_DIR="${STATE_DIR}/features/test-feature/tasks"
    LOGS_DIR="${STATE_DIR}/features/test-feature/logs"
    CONTRACT_FILE="${STATE_DIR}/contract.json"
    STATE_FILE="${STATE_DIR}/state.json"
    DEFECTS_DIR="${STATE_DIR}/defects"
    mkdir -p "$PROJECT_ROOT" "$STATE_DIR" "$TASKS_DIR" "$LOGS_DIR" "$DEFECTS_DIR"

    # Also create a global tasks dir for gate functions that look there
    mkdir -p "${STATE_DIR}/tasks"

    # Create minimal task file
    cat > "${TASKS_DIR}/1.json" <<'JSON'
{
  "id": "1",
  "feature": "test-feature",
  "description": "A test task",
  "files_touched": ["src/app.py"],
  "status": "done"
}
JSON
    # Symlink or copy to global tasks dir (gates look at STATE_DIR/tasks)
    cp "${TASKS_DIR}/1.json" "${STATE_DIR}/tasks/1.json"

    # Unset security config vars
    unset TOML_SECURITY_SAST_CMD 2>/dev/null || true
    unset TOML_SECURITY_SCA_CMD 2>/dev/null || true
    unset TOML_SECURITY_SEVERITY_THRESHOLD 2>/dev/null || true
    unset TOML_SECURITY_SECRETS_EXCLUDE 2>/dev/null || true

    # Unset source guards and source required libs
    unset _SECURITY_SH_LOADED 2>/dev/null || true
    unset _GROUNDING_SH_LOADED 2>/dev/null || true

    # Source security.sh (parsers, banner, create_defects)
    source "${LIB_DIR}/security.sh"

    # Source gates.sh (gate_sast, gate_sca)
    source "${LIB_DIR}/gates.sh" 2>/dev/null || true
}

teardown() {
    rm -rf "$TEST_DIR"
}

run_test() {
    local test_name="$1"
    if ! setup; then
        printf "  ERROR  %s (setup failed)\n" "$test_name"
        FAIL=$((FAIL + 1))
        return
    fi
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

# ── Assertions ───────────────────────────────────────────────────────────────

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

assert_output_not_contains() {
    local output="$1" pattern="$2"
    if echo "$output" | grep -q "$pattern"; then
        echo "    ASSERT: output should NOT contain '${pattern}'" >&2
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
            echo "      - ${r}" >&2
        done
        return 1
    fi
}

# ── Mock Tools ───────────────────────────────────────────────────────────────

_create_mock_semgrep() {
    local mock_path="${TEST_DIR}/mock_semgrep.sh"
    cat > "$mock_path" <<'SCRIPT'
#!/usr/bin/env bash
# Mock Semgrep: outputs 2 findings (1 medium, 1 low)
cat <<'JSON'
{
  "results": [
    {
      "check_id": "python.injection.sql-injection",
      "path": "src/db.py",
      "start": {"line": 42, "col": 5},
      "end": {"line": 42, "col": 60},
      "extra": {
        "severity": "WARNING",
        "message": "Possible SQL injection via string formatting"
      }
    },
    {
      "check_id": "python.crypto.insecure-hash",
      "path": "src/auth.py",
      "start": {"line": 10, "col": 1},
      "end": {"line": 10, "col": 30},
      "extra": {
        "severity": "INFO",
        "message": "Use of MD5 hash function"
      }
    }
  ],
  "errors": []
}
JSON
SCRIPT
    chmod +x "$mock_path"
    echo "$mock_path"
}

_create_mock_npm_audit() {
    local mock_path="${TEST_DIR}/mock_npm_audit.sh"
    cat > "$mock_path" <<'SCRIPT'
#!/usr/bin/env bash
# Mock npm audit: outputs 1 high finding
cat <<'JSON'
{
  "vulnerabilities": {
    "lodash": {
      "name": "lodash",
      "severity": "high",
      "via": [
        {
          "title": "Prototype Pollution",
          "url": "https://npmjs.com/advisories/1523"
        }
      ],
      "range": "<4.17.21",
      "fixAvailable": {
        "name": "lodash",
        "version": "4.17.21"
      }
    }
  }
}
JSON
SCRIPT
    chmod +x "$mock_path"
    echo "$mock_path"
}

# ── Test 1: SAST gate integration ────────────────────────────────────────────
# Set TOML_SECURITY_SAST_CMD to mock_semgrep.sh, call gate_sast, verify
# output files are written, findings count == 2, return code 0, and
# results array contains SAST warning.

test_sast_gate_integration() {
    local mock_path
    mock_path=$(_create_mock_semgrep)

    TOML_SECURITY_SAST_CMD="bash ${mock_path}"

    local results=()
    local rc=0
    gate_sast "1" "$PROJECT_ROOT" || rc=$?

    assert_exit_code "0" "$rc" "gate_sast should return 0 (warn-only)"

    local logs_dir="${STATE_DIR}/features/test-feature/logs"
    assert_file_exists "${logs_dir}/sast-output.json" "sast-output.json"
    assert_file_exists "${logs_dir}/sast-findings.json" "sast-findings.json"
    assert_json_valid "${logs_dir}/sast-findings.json" "sast-findings.json"

    # Verify 2 findings
    assert_jq "${logs_dir}/sast-findings.json" 'length' "2" "findings count"

    # Verify results array got the SAST warning
    assert_results_contain "SAST"
}

# ── Test 2: SCA gate integration ─────────────────────────────────────────────
# Set TOML_SECURITY_SCA_CMD to mock_npm_audit.sh, call gate_sca, verify
# output files are written, findings count == 1, return code 0.

test_sca_gate_integration() {
    local mock_path
    mock_path=$(_create_mock_npm_audit)

    TOML_SECURITY_SCA_CMD="bash ${mock_path}"

    local results=()
    local rc=0
    gate_sca "1" "$PROJECT_ROOT" || rc=$?

    assert_exit_code "0" "$rc" "gate_sca should return 0 (warn-only)"

    local logs_dir="${STATE_DIR}/features/test-feature/logs"
    assert_file_exists "${logs_dir}/sca-output.json" "sca-output.json"
    assert_file_exists "${logs_dir}/sca-findings.json" "sca-findings.json"
    assert_json_valid "${logs_dir}/sca-findings.json" "sca-findings.json"

    # Verify 1 finding
    assert_jq "${logs_dir}/sca-findings.json" 'length' "1" "findings count"

    # Verify results array got the SCA warning
    assert_results_contain "SCA"
}

# ── Test 3: No-config graceful skip ──────────────────────────────────────────
# With both TOML_SECURITY_SAST_CMD and TOML_SECURITY_SCA_CMD unset, both
# gates should return 0 and create no output files.

test_no_config_graceful_skip() {
    unset TOML_SECURITY_SAST_CMD 2>/dev/null || true
    unset TOML_SECURITY_SCA_CMD 2>/dev/null || true

    local results=()

    local rc_sast=0
    gate_sast "1" "$PROJECT_ROOT" || rc_sast=$?
    assert_exit_code "0" "$rc_sast" "gate_sast with no config"

    local rc_sca=0
    gate_sca "1" "$PROJECT_ROOT" || rc_sca=$?
    assert_exit_code "0" "$rc_sca" "gate_sca with no config"

    # No output files should be created
    local logs_dir="${STATE_DIR}/features/test-feature/logs"
    assert_file_not_exists "${logs_dir}/sast-output.json" "sast-output.json"
    assert_file_not_exists "${logs_dir}/sca-output.json" "sca-output.json"
}

# ── Test 4: Secrets blocking in grounding ────────────────────────────────────
# Create a source file containing AKIA1234567890ABCDEF in the mock worktree.
# Mock git diff to return that file. Call grounding_check_secrets. Verify:
# returns 1, secrets-scan.log contains FOUND and BLOCKED.

test_secrets_block_grounding() {
    # Set up a git repo for the secrets scanner
    local repo_dir="${TEST_DIR}/secrets-repo"
    mkdir -p "$repo_dir"
    git -C "$repo_dir" init -b main --quiet
    git -C "$repo_dir" config user.email "test@test.com"
    git -C "$repo_dir" config user.name "Test"

    echo "init" > "$repo_dir/README.md"
    git -C "$repo_dir" add README.md
    git -C "$repo_dir" commit -m "init" --quiet

    # Create feature branch with a leaked AWS key
    git -C "$repo_dir" checkout -b "feat/leak" --quiet
    mkdir -p "$repo_dir/src"
    printf 'AWS_KEY = "AKIA1234567890ABCDEF"\n' > "$repo_dir/src/config.py"
    git -C "$repo_dir" add src/config.py
    git -C "$repo_dir" commit -m "add config with secret" --quiet

    # Point globals at this repo
    local orig_project_root="$PROJECT_ROOT"
    PROJECT_ROOT="$repo_dir"
    LOGS_DIR="${repo_dir}/.speed/logs"
    mkdir -p "$LOGS_DIR"

    # Write task JSON with branch
    local tasks_dir="${repo_dir}/.speed/tasks"
    mkdir -p "$tasks_dir"
    TASKS_DIR="$tasks_dir"
    cat > "${tasks_dir}/sec-task.json" <<'JSON'
{
    "id": "sec-task",
    "branch": "feat/leak",
    "description": "test secret detection"
}
JSON

    # Git helpers scoped to this repo
    _git() { git -C "$repo_dir" "$@"; }
    git_main_branch() { echo "main"; }

    # Source grounding.sh for grounding_check_secrets
    unset _GROUNDING_SH_LOADED 2>/dev/null || true
    source "${LIB_DIR}/grounding.sh"

    local rc=0
    grounding_check_secrets "sec-task" "$repo_dir" 2>/dev/null || rc=$?

    assert_exit_code "1" "$rc" "grounding_check_secrets should block on AWS key"

    local log_file="${LOGS_DIR}/secrets-scan.log"
    assert_file_exists "$log_file" "secrets-scan.log"

    local log_content
    log_content=$(cat "$log_file")
    assert_output_contains "$log_content" "FOUND"
    assert_output_contains "$log_content" "BLOCKED"

    # Restore
    PROJECT_ROOT="$orig_project_root"
}

# ── Test 5: Secrets exclusion ────────────────────────────────────────────────
# Create .env.local containing an API key. With default exclusions (.env*),
# grounding_check_secrets should return 0, scan log shows CLEAN.

test_secrets_exclusion() {
    local repo_dir="${TEST_DIR}/excl-repo"
    mkdir -p "$repo_dir"
    git -C "$repo_dir" init -b main --quiet
    git -C "$repo_dir" config user.email "test@test.com"
    git -C "$repo_dir" config user.name "Test"

    echo "init" > "$repo_dir/README.md"
    git -C "$repo_dir" add README.md
    git -C "$repo_dir" commit -m "init" --quiet

    # Create feature branch with secret in .env.local (excluded by default)
    git -C "$repo_dir" checkout -b "feat/env-secret" --quiet
    printf 'API_KEY=AKIA1234567890ABCDEF\n' > "$repo_dir/.env.local"
    git -C "$repo_dir" add .env.local
    git -C "$repo_dir" commit -m "add .env.local" --quiet

    # Point globals at this repo
    local orig_project_root="$PROJECT_ROOT"
    PROJECT_ROOT="$repo_dir"
    LOGS_DIR="${repo_dir}/.speed/logs"
    mkdir -p "$LOGS_DIR"

    local tasks_dir="${repo_dir}/.speed/tasks"
    mkdir -p "$tasks_dir"
    TASKS_DIR="$tasks_dir"
    cat > "${tasks_dir}/excl-task.json" <<'JSON'
{
    "id": "excl-task",
    "branch": "feat/env-secret",
    "description": "test exclusion"
}
JSON

    _git() { git -C "$repo_dir" "$@"; }
    git_main_branch() { echo "main"; }

    # Use default exclusions (includes .env*)
    unset TOML_SECURITY_SECRETS_EXCLUDE 2>/dev/null || true

    unset _GROUNDING_SH_LOADED 2>/dev/null || true
    source "${LIB_DIR}/grounding.sh"

    local rc=0
    grounding_check_secrets "excl-task" "$repo_dir" 2>/dev/null || rc=$?

    assert_exit_code "0" "$rc" "grounding_check_secrets should pass for excluded .env.local"

    local log_file="${LOGS_DIR}/secrets-scan.log"
    assert_file_exists "$log_file" "secrets-scan.log"

    local log_content
    log_content=$(cat "$log_file")
    assert_output_contains "$log_content" "CLEAN"

    PROJECT_ROOT="$orig_project_root"
}

# ── Test 6: speed security command ───────────────────────────────────────────
# Mock provider_run_json to return fixture security-audit.json content.
# Call cmd_security --feature test-feature. Verify: security-audit.json
# written, banner output contains severity breakdown.

test_speed_security_command() {
    # Create fixture audit JSON
    local audit_json="${LOGS_DIR}/security-audit.json"
    cat > "$audit_json" <<'JSON'
{
  "feature": "test-feature",
  "summary": {
    "total": 3,
    "by_severity": {
      "critical": 0,
      "high": 2,
      "medium": 1,
      "low": 0,
      "info": 0
    }
  },
  "findings": [
    {
      "id": "SEC-001",
      "severity": "high",
      "title": "SQL Injection",
      "file": "src/db.py",
      "line": 42,
      "category": "injection",
      "description": "Unsanitized input in query",
      "recommendation": "Use parameterized queries"
    },
    {
      "id": "SEC-002",
      "severity": "high",
      "title": "XSS Vulnerability",
      "file": "src/views.py",
      "line": 15,
      "category": "xss",
      "description": "Unescaped user input in template",
      "recommendation": "Use template auto-escaping"
    },
    {
      "id": "SEC-003",
      "severity": "medium",
      "title": "Insecure Hash",
      "file": "src/auth.py",
      "line": 8,
      "category": "crypto",
      "description": "MD5 used for password hashing",
      "recommendation": "Use bcrypt or argon2"
    }
  ]
}
JSON

    # Stub functions that cmd_security depends on
    GLOBAL_FEATURE="test-feature"
    feature_get_active() { echo "test-feature"; }

    # Mock security_audit_run to skip the LLM call (audit already written)
    security_audit_run() { :; }

    # Mock security_has_cached_audit to return true
    security_has_cached_audit() { return 0; }

    # Source cmd/security.sh
    source "${LIB_DIR}/cmd/security.sh"

    local output rc=0
    output=$(cmd_security --feature test-feature 2>&1) || rc=$?

    assert_exit_code "0" "$rc" "cmd_security should succeed"
    assert_file_exists "$audit_json" "security-audit.json"

    # Banner should display severity breakdown
    assert_output_contains "$output" "High"
    assert_output_contains "$output" "Medium"
    assert_output_contains "$output" "Total findings"
}

# ── Test 7: Create defects from audit ────────────────────────────────────────
# Write fixture security-audit.json with 1 high and 1 low finding. Set
# threshold to medium. Call cmd_security --create-defects to exercise the
# full CLI path (including TOML_SECURITY_SEVERITY_THRESHOLD resolution).
# Verify: 1 defect spec created (high), 1 skipped (low), defect file
# contains Classification-Override and Tags fields.

test_create_defects() {
    # Write audit JSON at the path cmd_security expects
    local audit_json="${LOGS_DIR}/security-audit.json"
    cat > "$audit_json" <<'JSON'
{
  "feature": "test-feature",
  "summary": {
    "total": 2,
    "by_severity": {"high": 1, "low": 1}
  },
  "findings": [
    {
      "id": "SEC-001",
      "severity": "high",
      "title": "SQL Injection",
      "file": "src/db.py",
      "line": 42,
      "category": "injection",
      "description": "Unsanitized input",
      "recommendation": "Use parameterized queries",
      "snippet": "query = f\"SELECT * FROM {table}\""
    },
    {
      "id": "SEC-002",
      "severity": "low",
      "title": "Debug Logging",
      "file": "src/app.py",
      "line": 5,
      "category": "other",
      "description": "Debug logging left enabled",
      "recommendation": "Disable debug logging in production"
    }
  ]
}
JSON

    # Create specs/defects directory (security_create_defects writes there)
    mkdir -p "${PROJECT_ROOT}/specs/defects"

    # Stub functions cmd_security depends on
    GLOBAL_FEATURE="test-feature"
    feature_get_active() { echo "test-feature"; }
    security_audit_run() { :; }
    security_has_cached_audit() { return 0; }

    # Set threshold via TOML var (the path cmd_security reads at line 62)
    TOML_SECURITY_SEVERITY_THRESHOLD="medium"

    # Source cmd/security.sh
    source "${LIB_DIR}/cmd/security.sh"

    # cd to PROJECT_ROOT since security_create_defects uses relative paths
    local orig_pwd="$PWD"
    cd "$PROJECT_ROOT"

    local output rc=0
    output=$(cmd_security --feature test-feature --create-defects 2>&1) || rc=$?

    cd "$orig_pwd"

    assert_exit_code "0" "$rc" "cmd_security --create-defects should succeed"

    # Should report 1 created, 1 skipped
    assert_output_contains "$output" "1 defect(s) created"
    assert_output_contains "$output" "1 skipped"

    # Find the created defect file (slug: sql-injection)
    local defect_file="${PROJECT_ROOT}/specs/defects/sec-sql-injection.md"
    assert_file_exists "$defect_file" "sec-sql-injection.md"

    local defect_content
    defect_content=$(cat "$defect_file")

    # Verify required fields
    assert_output_contains "$defect_content" "Classification-Override"
    assert_output_contains "$defect_content" "Tags: security"
    assert_output_contains "$defect_content" "Severity: P1"

    # Low-severity finding should not have produced a defect file
    # (slug: debug-logging)
    assert_file_not_exists "${PROJECT_ROOT}/specs/defects/sec-debug-logging.md" "low-severity defect"
}

# ── Test 8: Status security line ─────────────────────────────────────────────
# Write fixture security-audit.json with known severity counts. Call the
# security status rendering block. Verify output contains "Security:" with
# correct counts.

test_status_security_line() {
    # Write audit file with known counts
    cat > "${LOGS_DIR}/security-audit.json" <<'JSON'
{
  "summary": {
    "total": 5,
    "by_severity": {
      "critical": 1,
      "high": 2,
      "medium": 1,
      "low": 1,
      "info": 0
    }
  },
  "findings": []
}
JSON

    # Write SAST findings (1 medium)
    cat > "${LOGS_DIR}/sast-findings.json" <<'JSON'
[
  {"id": "SAST-001", "severity": "medium", "title": "test", "file": "x.py", "line": 1}
]
JSON

    # No SCA findings file (tests partial aggregation)

    # Stub all functions that cmd_status depends on but aren't related to security
    feature_list() { echo "test-feature"; }
    feature_get_active() { echo "test-feature"; }
    feature_activate() {
        TASKS_DIR="${STATE_DIR}/features/test-feature/tasks"
        LOGS_DIR="${STATE_DIR}/features/test-feature/logs"
    }
    task_count_total() { echo "1"; }
    task_count_by_status() { echo "0"; }
    task_print_graph() { echo "  [1] Test task (done)"; }
    task_print_summary() { echo "1/1 tasks complete"; }
    list_defects() { :; }
    toml_get_value() { echo ""; }
    GLOBAL_FEATURE="test-feature"

    # Create state file
    cat > "$STATE_FILE" <<'JSON'
{"status": "idle", "agents": []}
JSON
    # Create contract file
    echo '{}' > "$CONTRACT_FILE"

    # Source cmd/status.sh
    source "${LIB_DIR}/cmd/status.sh"

    local output rc=0
    output=$(cmd_status 2>&1) || rc=$?

    assert_exit_code "0" "$rc" "cmd_status should succeed"

    # Security line should appear with aggregated counts.
    # Audit has critical=1, high=2, medium=1, low=1
    # SAST adds medium=1
    # Total: 1 critical, 2 high, 2 medium, 1 low = 6 findings
    assert_output_contains "$output" "Security:"
    assert_output_contains "$output" "1 critical"
    assert_output_contains "$output" "2 high"
    assert_output_contains "$output" "2 medium"
    assert_output_contains "$output" "1 low"
}

# ── Run All Tests ────────────────────────────────────────────────────────────

echo ""
echo "E2E Security Pipeline Integration Tests"
echo "──────────────────────────────────────"

run_test test_sast_gate_integration
run_test test_sca_gate_integration
run_test test_no_config_graceful_skip
run_test test_secrets_block_grounding
run_test test_secrets_exclusion
run_test test_speed_security_command
run_test test_create_defects
run_test test_status_security_line

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
