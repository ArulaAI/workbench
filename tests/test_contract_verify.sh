#!/usr/bin/env bash
# test_contract_verify.sh — Tests for contract_verify.py
#
# Usage: bash speed/tests/test_contract_verify.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY_SCRIPT="${SCRIPT_DIR}/../lib/contract_verify.py"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)
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

assert_exit_code() {
    local expected="$1" actual="$2" context="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected exit ${expected}, got ${actual}${context:+ (${context})}" >&2
        return 1
    fi
}

assert_json_field() {
    local json="$1" field="$2" expected="$3" label="${4:-$field}"
    local actual
    actual=$(echo "$json" | python3 -c "import json,sys; print(json.load(sys.stdin)${field})")
    if [[ "$actual" != "$expected" ]]; then
        echo "    ASSERT: expected ${label}='${expected}', got '${actual}'" >&2
        return 1
    fi
}

run_verify() {
    python3 "$VERIFY_SCRIPT" "$@" 2>&1
}

# ── Tests: empty entities ─────────────────────────────────────────

test_empty_entities_fails() {
    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 1 "$rc" "empty entities should fail"
    assert_json_field "$output" "['passed']" "False" "passed"
    assert_json_field "$output" "['results'][0]['check']" "Entity coverage" "check"
    assert_json_field "$output" "['results'][0]['passed']" "False" "result.passed"
}

test_no_entities_key_fails() {
    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 1 "$rc" "missing entities key should fail"
    assert_json_field "$output" "['passed']" "False" "passed"
}

# ── Tests: file entities ──────────────────────────────────────────

test_file_entity_exists() {
    mkdir -p "${TEST_DIR}/speed/agents"
    echo "# Agent" > "${TEST_DIR}/speed/agents/audit.md"

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "AuditAgent", "type": "file", "path": "speed/agents/audit.md", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 0 "$rc" "existing file should pass"
    assert_json_field "$output" "['passed']" "True" "passed"
}

test_file_entity_missing() {
    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "Missing", "type": "file", "path": "does/not/exist.md", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 1 "$rc" "missing file should fail"
    assert_json_field "$output" "['passed']" "False" "passed"
}

test_file_entity_no_path_fails() {
    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "NoPath", "type": "file", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 1 "$rc" "file entity with no path should fail"
    assert_json_field "$output" "['passed']" "False" "passed"
}

test_file_entity_parameterized_path() {
    mkdir -p "${TEST_DIR}/.speed/defects"

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "DefectState", "type": "file", "path": ".speed/defects/<name>/state.json", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 0 "$rc" "parameterized path with existing parent should pass"
    assert_json_field "$output" "['passed']" "True" "passed"
}

test_file_entity_parameterized_path_missing() {
    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "DefectState", "type": "file", "path": ".speed/nonexistent/<name>/state.json", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 1 "$rc" "parameterized path with missing parent should fail"
    assert_json_field "$output" "['passed']" "False" "passed"
}

# ── Tests: function entities ──────────────────────────────────────

test_function_entity_exists() {
    mkdir -p "${TEST_DIR}/lib"
    cat > "${TEST_DIR}/lib/utils.py" <<'PYEOF'
def my_function():
    pass
PYEOF

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "MyFunc", "type": "function", "path": "lib/utils.py", "function": "my_function", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 0 "$rc" "function in existing file should pass"
    assert_json_field "$output" "['passed']" "True" "passed"
}

test_function_entity_symbol_missing() {
    mkdir -p "${TEST_DIR}/lib"
    cat > "${TEST_DIR}/lib/utils.py" <<'PYEOF'
def other_function():
    pass
PYEOF

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "MyFunc", "type": "function", "path": "lib/utils.py", "function": "my_function", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 1 "$rc" "missing function should fail"
    assert_json_field "$output" "['passed']" "False" "passed"
}

test_function_entity_file_missing() {
    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "MyFunc", "type": "function", "path": "lib/nope.py", "function": "my_function", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 1 "$rc" "missing file should fail"
    assert_json_field "$output" "['passed']" "False" "passed"
}

test_function_entity_no_function_name() {
    mkdir -p "${TEST_DIR}/lib"
    echo "x = 1" > "${TEST_DIR}/lib/utils.py"

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "Utils", "type": "function", "path": "lib/utils.py", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 0 "$rc" "function entity with no function name but existing file should pass"
    assert_json_field "$output" "['passed']" "True" "passed"
}

test_function_entity_no_path_fails() {
    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "NoPath", "type": "function", "function": "foo", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 1 "$rc" "function entity with no path should fail"
    assert_json_field "$output" "['passed']" "False" "passed"
}

# ── Tests: database entities ──────────────────────────────────────

test_database_entity_with_path_and_class() {
    mkdir -p "${TEST_DIR}/models"
    cat > "${TEST_DIR}/models/user.py" <<'PYEOF'
class User:
    __tablename__ = "users"
PYEOF

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "users", "type": "database", "table": "users", "path": "models/user.py", "function": "User", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 0 "$rc" "database entity with path+class should pass"
    assert_json_field "$output" "['passed']" "True" "passed"
}

test_database_entity_with_path_class_missing() {
    mkdir -p "${TEST_DIR}/models"
    echo "class Team: pass" > "${TEST_DIR}/models/user.py"

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "users", "type": "database", "table": "users", "path": "models/user.py", "function": "User", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 1 "$rc" "database entity with missing class should fail"
    assert_json_field "$output" "['passed']" "False" "passed"
}

test_database_entity_legacy_no_path() {
    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "users", "type": "database", "table": "users", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 0 "$rc" "legacy database entity without path should pass with advisory"
    assert_json_field "$output" "['passed']" "True" "passed"
}

# ── Tests: type inference (backward compat) ───────────────────────

test_infer_file_type_from_table_field() {
    mkdir -p "${TEST_DIR}/speed/agents"
    echo "# Agent" > "${TEST_DIR}/speed/agents/audit.md"

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "AuditAgent", "table": "speed/agents/audit.md", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 0 "$rc" "legacy table with path-like value should infer as file"
    assert_json_field "$output" "['passed']" "True" "passed"
}

test_infer_function_type_from_table_field() {
    mkdir -p "${TEST_DIR}/speed"
    echo "cmd_audit() { echo hi; }" > "${TEST_DIR}/speed/speed"

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "AuditCmd", "table": "speed/speed:cmd_audit", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 0 "$rc" "legacy table with file:func format should infer as function"
    assert_json_field "$output" "['passed']" "True" "passed"
}

# ── Tests: unknown type ──────────────────────────────────────────

test_unknown_entity_type_fails() {
    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "X", "type": "graphql", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 1 "$rc" "unknown entity type should fail"
    assert_json_field "$output" "['passed']" "False" "passed"
}

# ── Tests: mixed entities ─────────────────────────────────────────

test_mixed_pass_and_fail() {
    mkdir -p "${TEST_DIR}/speed/agents"
    echo "# Agent" > "${TEST_DIR}/speed/agents/audit.md"

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [
    {"name": "Exists", "type": "file", "path": "speed/agents/audit.md", "created_by_task": "1", "key_fields": []},
    {"name": "Missing", "type": "file", "path": "speed/agents/nope.md", "created_by_task": "2", "key_fields": []}
], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 1 "$rc" "any failing entity should fail overall"
    assert_json_field "$output" "['passed']" "False" "passed"
}

test_all_pass() {
    mkdir -p "${TEST_DIR}/speed/agents" "${TEST_DIR}/lib"
    echo "# Agent" > "${TEST_DIR}/speed/agents/audit.md"
    echo "def verify(): pass" > "${TEST_DIR}/lib/check.py"

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [
    {"name": "Agent", "type": "file", "path": "speed/agents/audit.md", "created_by_task": "1", "key_fields": []},
    {"name": "Verify", "type": "function", "path": "lib/check.py", "function": "verify", "created_by_task": "2", "key_fields": []}
], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 0 "$rc" "all passing entities should pass"
    assert_json_field "$output" "['passed']" "True" "passed"
}

# ── Tests: relationships are ignored ──────────────────────────────

test_relationships_ignored() {
    mkdir -p "${TEST_DIR}/lib"
    echo "x = 1" > "${TEST_DIR}/lib/a.py"

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [
    {"name": "A", "type": "file", "path": "lib/a.py", "created_by_task": "1", "key_fields": []}
], "relationships": [
    {"from": "users", "to": "teams", "type": "belongs_to", "via": "team_id", "created_by_task": "1"}
], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?
    assert_exit_code 0 "$rc" "relationships should be ignored by automated verifier"
    assert_json_field "$output" "['passed']" "True" "passed"
}

# ── Tests: CLI errors ─────────────────────────────────────────────

test_bad_args() {
    local rc=0
    python3 "$VERIFY_SCRIPT" 2>/dev/null || rc=$?
    assert_exit_code 2 "$rc" "no args should exit 2"
}

test_bad_contract_file() {
    local rc=0
    python3 "$VERIFY_SCRIPT" "${TEST_DIR}/nope.json" "$TEST_DIR" 2>/dev/null || rc=$?
    assert_exit_code 2 "$rc" "missing contract file should exit 2"
}

test_invalid_json() {
    echo "not json" > "${TEST_DIR}/bad.json"
    local rc=0
    python3 "$VERIFY_SCRIPT" "${TEST_DIR}/bad.json" "$TEST_DIR" 2>/dev/null || rc=$?
    assert_exit_code 2 "$rc" "invalid JSON should exit 2"
}

# ── Tests: no schema_summary in output ────────────────────────────

test_no_schema_summary() {
    mkdir -p "${TEST_DIR}/lib"
    echo "x = 1" > "${TEST_DIR}/lib/a.py"

    local contract="${TEST_DIR}/contract.json"
    cat > "$contract" <<'EOF'
{"entities": [{"name": "A", "type": "file", "path": "lib/a.py", "created_by_task": "1", "key_fields": []}], "relationships": [], "core_queries": []}
EOF
    local output rc=0
    output=$(run_verify "$contract" "$TEST_DIR") || rc=$?

    if echo "$output" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'schema_summary' not in d" 2>/dev/null; then
        return 0
    else
        echo "    ASSERT: output should NOT contain schema_summary" >&2
        return 1
    fi
}

# ── Main ──────────────────────────────────────────────────────────

echo "Running contract_verify tests..."
echo ""

# Empty entities
run_test test_empty_entities_fails
run_test test_no_entities_key_fails

# File entities
run_test test_file_entity_exists
run_test test_file_entity_missing
run_test test_file_entity_no_path_fails
run_test test_file_entity_parameterized_path
run_test test_file_entity_parameterized_path_missing

# Function entities
run_test test_function_entity_exists
run_test test_function_entity_symbol_missing
run_test test_function_entity_file_missing
run_test test_function_entity_no_function_name
run_test test_function_entity_no_path_fails

# Database entities
run_test test_database_entity_with_path_and_class
run_test test_database_entity_with_path_class_missing
run_test test_database_entity_legacy_no_path

# Type inference
run_test test_infer_file_type_from_table_field
run_test test_infer_function_type_from_table_field

# Unknown type
run_test test_unknown_entity_type_fails

# Mixed
run_test test_mixed_pass_and_fail
run_test test_all_pass

# Relationships ignored
run_test test_relationships_ignored

# CLI errors
run_test test_bad_args
run_test test_bad_contract_file
run_test test_invalid_json

# Output format
run_test test_no_schema_summary

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
