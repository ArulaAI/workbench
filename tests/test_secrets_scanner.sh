#!/usr/bin/env bash
# test_secrets_scanner.sh — Tests for grounding_check_secrets()
#
# Creates a temporary git repo with controlled test files to verify
# secret detection, exclusion patterns, binary skipping, and log output.
#
# Usage: bash tests/test_secrets_scanner.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ──────────────────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)

    # Minimal stubs for config.sh / log.sh / colors.sh dependencies
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" COLOR_STEP=""
    BOLD="" RESET="" SYM_CHECK="" SYM_CROSS="" SYM_WARN="" SYM_ARROW=""
    VERBOSITY=0

    # Logging stubs that capture to a variable
    CAPTURED_STDERR=""
    log_error() { CAPTURED_STDERR+="$*"$'\n'; }
    log_warn() { :; }
    log_step() { :; }
    log_success() { :; }

    # Stub _context_python
    _context_python() { echo "python3"; }

    # Set up a temporary git repo
    export PROJECT_ROOT="$TEST_DIR/repo"
    mkdir -p "$PROJECT_ROOT"
    git -C "$PROJECT_ROOT" init -b main --quiet
    git -C "$PROJECT_ROOT" config user.email "test@test.com"
    git -C "$PROJECT_ROOT" config user.name "Test"

    # Create an initial commit on main
    echo "init" > "$PROJECT_ROOT/README.md"
    git -C "$PROJECT_ROOT" add README.md
    git -C "$PROJECT_ROOT" commit -m "init" --quiet

    # Set up SPEED directory structure
    export STATE_DIR="${PROJECT_ROOT}/.speed"
    export FEATURES_DIR="${STATE_DIR}/features"
    export TASKS_DIR="${STATE_DIR}/tasks"
    export LOGS_DIR="${STATE_DIR}/logs"
    mkdir -p "$TASKS_DIR" "$LOGS_DIR"

    # Default: no TOML exclusion override
    unset TOML_SECURITY_SECRETS_EXCLUDE 2>/dev/null || true

    # _git wrapper (matches lib/git.sh)
    _git() { git -C "$PROJECT_ROOT" "$@"; }

    # git_main_branch stub
    git_main_branch() { echo "main"; }

    # Source grounding.sh (reset source guard if present)
    unset _GROUNDING_SH_LOADED 2>/dev/null || true
    # shellcheck source=../lib/grounding.sh
    source "${LIB_DIR}/grounding.sh"
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

# Helper: create a branch with a file and return a task JSON
_create_branch_with_file() {
    local branch_name="$1"
    local file_path="$2"
    local file_content="$3"
    local task_id="${4:-test-task}"

    git -C "$PROJECT_ROOT" checkout -b "$branch_name" --quiet
    mkdir -p "$(dirname "$PROJECT_ROOT/$file_path")"
    echo "$file_content" > "$PROJECT_ROOT/$file_path"
    git -C "$PROJECT_ROOT" add "$file_path"
    git -C "$PROJECT_ROOT" commit -m "add $file_path" --quiet

    # Write task JSON
    cat > "${TASKS_DIR}/${task_id}.json" <<EOF
{
    "id": "${task_id}",
    "branch": "${branch_name}",
    "description": "test task"
}
EOF
}

# ── Tests: AWS Access Key detection ──────────────────────────────────────────

test_aws_access_key_detected() {
    _create_branch_with_file "feat/aws-key" "src/config.py" \
        'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"'

    local rc=0
    grounding_check_secrets "test-task" "$PROJECT_ROOT" || rc=$?
    assert_exit_code "1" "$rc" "AWS access key should be detected"

    # Verify log has FOUND entry
    assert_output_contains "$(cat "$LOGS_DIR/secrets-scan.log")" "FOUND: AWS Access Key at src/config.py:1"
    # Verify log has BLOCKED footer
    assert_output_contains "$(cat "$LOGS_DIR/secrets-scan.log")" "RESULT: BLOCKED"
}

# ── Tests: GitHub token detection ────────────────────────────────────────────

test_github_token_detected() {
    local token="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx1234"
    _create_branch_with_file "feat/gh-token" "deploy.sh" \
        "TOKEN=${token}"

    local rc=0
    grounding_check_secrets "test-task" "$PROJECT_ROOT" || rc=$?
    assert_exit_code "1" "$rc" "GitHub token should be detected"

    assert_output_contains "$(cat "$LOGS_DIR/secrets-scan.log")" "FOUND: GitHub Token at deploy.sh:1"
}

# ── Tests: Private key header detection ──────────────────────────────────────

test_private_key_header_detected() {
    _create_branch_with_file "feat/pem" "certs/server.key" \
        '-----BEGIN RSA PRIVATE KEY-----'

    local rc=0
    grounding_check_secrets "test-task" "$PROJECT_ROOT" || rc=$?
    assert_exit_code "1" "$rc" "PEM private key header should be detected"

    assert_output_contains "$(cat "$LOGS_DIR/secrets-scan.log")" "FOUND: Private Key Header at certs/server.key:1"
}

# ── Tests: Clean file passes ─────────────────────────────────────────────────

test_clean_file_passes() {
    _create_branch_with_file "feat/clean" "src/app.py" \
        'def hello(): return "world"'

    local rc=0
    grounding_check_secrets "test-task" "$PROJECT_ROOT" || rc=$?
    assert_exit_code "0" "$rc" "Clean file should pass"

    assert_output_contains "$(cat "$LOGS_DIR/secrets-scan.log")" "RESULT: CLEAN"
}

# ── Tests: .env files excluded by default ────────────────────────────────────

test_env_file_excluded() {
    git -C "$PROJECT_ROOT" checkout -b "feat/env-excl" --quiet
    mkdir -p "$PROJECT_ROOT/src"

    # .env.local with a secret — should be skipped
    echo 'AWS_KEY=AKIAIOSFODNN7EXAMPLE' > "$PROJECT_ROOT/.env.local"
    # Clean source file
    echo 'x = 1' > "$PROJECT_ROOT/src/main.py"

    git -C "$PROJECT_ROOT" add .env.local src/main.py
    git -C "$PROJECT_ROOT" commit -m "add files" --quiet

    cat > "${TASKS_DIR}/test-task.json" <<EOF
{"id": "test-task", "branch": "feat/env-excl", "description": "test"}
EOF

    local rc=0
    grounding_check_secrets "test-task" "$PROJECT_ROOT" || rc=$?
    assert_exit_code "0" "$rc" ".env.local should be excluded by default"

    assert_output_contains "$(cat "$LOGS_DIR/secrets-scan.log")" "SKIP: .env.local (excluded)"
}

# ── Tests: tests/fixtures/** excluded by default ─────────────────────────────

test_fixtures_excluded() {
    git -C "$PROJECT_ROOT" checkout -b "feat/fixtures-excl" --quiet
    mkdir -p "$PROJECT_ROOT/tests/fixtures"
    mkdir -p "$PROJECT_ROOT/src"

    echo 'SECRET=AKIAIOSFODNN7EXAMPLE' > "$PROJECT_ROOT/tests/fixtures/mock.env"
    echo 'x = 1' > "$PROJECT_ROOT/src/clean.py"

    git -C "$PROJECT_ROOT" add tests/fixtures/mock.env src/clean.py
    git -C "$PROJECT_ROOT" commit -m "add files" --quiet

    cat > "${TASKS_DIR}/test-task.json" <<EOF
{"id": "test-task", "branch": "feat/fixtures-excl", "description": "test"}
EOF

    local rc=0
    grounding_check_secrets "test-task" "$PROJECT_ROOT" || rc=$?
    assert_exit_code "0" "$rc" "tests/fixtures/** should be excluded by default"

    assert_output_contains "$(cat "$LOGS_DIR/secrets-scan.log")" "SKIP: tests/fixtures/mock.env (excluded)"
}

# ── Tests: Custom TOML exclusion patterns ────────────────────────────────────

test_custom_toml_exclude() {
    TOML_SECURITY_SECRETS_EXCLUDE="*.example config/secrets/*"

    git -C "$PROJECT_ROOT" checkout -b "feat/custom-excl" --quiet
    mkdir -p "$PROJECT_ROOT/config/secrets"

    echo 'KEY=AKIAIOSFODNN7EXAMPLE' > "$PROJECT_ROOT/config/secrets/prod.env"
    echo 'KEY=AKIAIOSFODNN7EXAMPLE' > "$PROJECT_ROOT/creds.example"
    echo 'x = 1' > "$PROJECT_ROOT/app.py"

    git -C "$PROJECT_ROOT" add config/secrets/prod.env creds.example app.py
    git -C "$PROJECT_ROOT" commit -m "add files" --quiet

    cat > "${TASKS_DIR}/test-task.json" <<EOF
{"id": "test-task", "branch": "feat/custom-excl", "description": "test"}
EOF

    local rc=0
    grounding_check_secrets "test-task" "$PROJECT_ROOT" || rc=$?
    assert_exit_code "0" "$rc" "Custom exclusion patterns should be respected"
}

# ── Tests: Stderr has file:line but NOT the secret value ─────────────────────

test_stderr_no_secret_value() {
    local aws_key="AKIAIOSFODNN7EXAMPLE"
    _create_branch_with_file "feat/no-leak" "src/leak.py" \
        "KEY = \"${aws_key}\""

    CAPTURED_STDERR=""
    local rc=0
    grounding_check_secrets "test-task" "$PROJECT_ROOT" || rc=$?
    assert_exit_code "1" "$rc" "Should detect the secret"

    # Stderr should contain file:line reference
    assert_output_contains "$CAPTURED_STDERR" "src/leak.py:1"
    # Stderr should contain pattern name
    assert_output_contains "$CAPTURED_STDERR" "AWS Access Key"
    # Stderr must NOT contain the actual secret value
    assert_output_not_contains "$CAPTURED_STDERR" "$aws_key"
}

# ── Tests: Log file written with FOUND/CLEAN entries ─────────────────────────

test_log_file_found_entries() {
    _create_branch_with_file "feat/log-found" "src/bad.py" \
        'KEY = "AKIAIOSFODNN7EXAMPLE"'

    grounding_check_secrets "test-task" "$PROJECT_ROOT" || true

    local log_content
    log_content=$(cat "$LOGS_DIR/secrets-scan.log")

    # Header
    assert_output_contains "$log_content" "=== Secrets Scan ==="
    assert_output_contains "$log_content" "Task: test-task"
    assert_output_contains "$log_content" "Branch: feat/log-found"
    # FOUND entry with pattern name, file, and line
    assert_output_contains "$log_content" "FOUND: AWS Access Key at src/bad.py:1"
    # Footer
    assert_output_contains "$log_content" "RESULT: BLOCKED"
}

test_log_file_clean_entries() {
    _create_branch_with_file "feat/log-clean" "src/ok.py" \
        'x = 42'

    grounding_check_secrets "test-task" "$PROJECT_ROOT" || true

    local log_content
    log_content=$(cat "$LOGS_DIR/secrets-scan.log")

    assert_output_contains "$log_content" "=== Secrets Scan ==="
    assert_output_contains "$log_content" "RESULT: CLEAN"
}

# ── Tests: Binary files skipped ──────────────────────────────────────────────

test_binary_file_skipped() {
    git -C "$PROJECT_ROOT" checkout -b "feat/binary" --quiet

    # Create a binary file (contains null bytes)
    printf 'AKIAIOSFODNN7EXAMPLE\x00binary data' > "$PROJECT_ROOT/data.bin"
    echo 'x = 1' > "$PROJECT_ROOT/clean.py"

    git -C "$PROJECT_ROOT" add data.bin clean.py
    git -C "$PROJECT_ROOT" commit -m "add files" --quiet

    cat > "${TASKS_DIR}/test-task.json" <<EOF
{"id": "test-task", "branch": "feat/binary", "description": "test"}
EOF

    local rc=0
    grounding_check_secrets "test-task" "$PROJECT_ROOT" || rc=$?
    assert_exit_code "0" "$rc" "Binary files should be skipped"

    assert_output_contains "$(cat "$LOGS_DIR/secrets-scan.log")" "SKIP: data.bin (binary)"
}

# ── Tests: No changed files returns 0 ───────────────────────────────────────

test_no_changed_files_returns_clean() {
    # Create a branch with no changes (identical to main)
    git -C "$PROJECT_ROOT" checkout -b "feat/empty" --quiet

    cat > "${TASKS_DIR}/test-task.json" <<EOF
{"id": "test-task", "branch": "feat/empty", "description": "test"}
EOF

    local rc=0
    grounding_check_secrets "test-task" "$PROJECT_ROOT" || rc=$?
    assert_exit_code "0" "$rc" "No changed files should return clean"
}

# ── Run all tests ────────────────────────────────────────────────────────────

echo ""
echo "Secrets scanner tests"
echo "──────────────────────────────────────"

# Detection
run_test test_aws_access_key_detected
run_test test_github_token_detected
run_test test_private_key_header_detected

# Clean pass
run_test test_clean_file_passes

# Exclusions
run_test test_env_file_excluded
run_test test_fixtures_excluded
run_test test_custom_toml_exclude

# Security: no secret leakage in output
run_test test_stderr_no_secret_value

# Log file format
run_test test_log_file_found_entries
run_test test_log_file_clean_entries

# Edge cases
run_test test_binary_file_skipped
run_test test_no_changed_files_returns_clean

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
