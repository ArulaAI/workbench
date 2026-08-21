#!/usr/bin/env bash
# test_security_auditor_context.sh — Tests for context_assemble_security_auditor
#
# Exercises the function directly by sourcing context_bridge.sh in a controlled
# temp directory that mimics the .speed/features/<name>/tasks/ layout.
#
# Usage: bash tests/test_security_auditor_context.sh
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
    export PROJECT_ROOT="$TEST_DIR"
    mkdir -p "${TEST_DIR}/.speed/features/my-feature/tasks"
    mkdir -p "${TEST_DIR}/specs/product"
    mkdir -p "${TEST_DIR}/specs/tech"
    mkdir -p "${TEST_DIR}/src"
}

teardown() {
    rm -rf "$TEST_DIR"
    unset PROJECT_ROOT
}

assert_output_contains() {
    local output="$1" pattern="$2"
    if ! echo "$output" | grep -q "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT (first 800): ${output:0:800}" >&2
        return 1
    fi
}

assert_output_not_contains() {
    local output="$1" pattern="$2"
    if echo "$output" | grep -q "$pattern"; then
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

# Source the bridge (requires PROJECT_ROOT to be set)
source_bridge() {
    # shellcheck source=../lib/context_bridge.sh
    source "${LIB_DIR}/context_bridge.sh"
}

# ── Tests ─────────────────────────────────────────────────────────

test_header_contains_feature_name() {
    source_bridge
    local output
    output=$(context_assemble_security_auditor "my-feature")
    assert_output_contains "$output" "Security Audit: my-feature"
}

test_empty_feature_produces_minimal_prompt() {
    # No task files, no specs — should still produce the header without error
    source_bridge
    local output rc=0
    output=$(context_assemble_security_auditor "my-feature") || rc=$?
    [[ $rc -eq 0 ]]
    assert_output_contains "$output" "Security Audit: my-feature"
    assert_output_contains "$output" "Files in scope"
}

test_file_contents_included_for_existing_files() {
    # Create a task JSON with files_touched pointing to a real file
    cat > "${TEST_DIR}/.speed/features/my-feature/tasks/1.json" <<'JSON'
{"id": "1", "title": "Task one", "files_touched": ["src/main.py"]}
JSON
    echo "def hello(): pass" > "${TEST_DIR}/src/main.py"

    source_bridge
    local output
    output=$(context_assemble_security_auditor "my-feature")
    assert_output_contains "$output" "### src/main.py"
    assert_output_contains "$output" "def hello(): pass"
}

test_missing_files_skipped_without_error() {
    # files_touched references a file that does not exist on disk
    cat > "${TEST_DIR}/.speed/features/my-feature/tasks/1.json" <<'JSON'
{"id": "1", "title": "Task one", "files_touched": ["src/nonexistent.py"]}
JSON

    source_bridge
    local output rc=0
    output=$(context_assemble_security_auditor "my-feature") || rc=$?
    [[ $rc -eq 0 ]]
    # The missing file should not appear as a code section
    assert_output_not_contains "$output" "### src/nonexistent.py"
}

test_product_spec_included_when_present() {
    echo "# My Feature PRD" > "${TEST_DIR}/specs/product/my-feature.md"

    source_bridge
    local output
    output=$(context_assemble_security_auditor "my-feature")
    assert_output_contains "$output" "## Product spec"
    assert_output_contains "$output" "My Feature PRD"
}

test_tech_spec_included_when_present() {
    echo "# My Feature RFC" > "${TEST_DIR}/specs/tech/my-feature.md"

    source_bridge
    local output
    output=$(context_assemble_security_auditor "my-feature")
    assert_output_contains "$output" "## Tech spec"
    assert_output_contains "$output" "My Feature RFC"
}

test_claude_md_included_when_present() {
    echo "# Project Conventions" > "${TEST_DIR}/CLAUDE.md"

    source_bridge
    local output
    output=$(context_assemble_security_auditor "my-feature")
    assert_output_contains "$output" "## Project conventions"
    assert_output_contains "$output" "Project Conventions"
}

test_files_deduplicated_across_tasks() {
    # Two tasks both declare the same file — it should appear only once
    cat > "${TEST_DIR}/.speed/features/my-feature/tasks/1.json" <<'JSON'
{"id": "1", "title": "Task one", "files_touched": ["src/shared.py"]}
JSON
    cat > "${TEST_DIR}/.speed/features/my-feature/tasks/2.json" <<'JSON'
{"id": "2", "title": "Task two", "files_touched": ["src/shared.py"]}
JSON
    echo "x = 1" > "${TEST_DIR}/src/shared.py"

    source_bridge
    local output
    output=$(context_assemble_security_auditor "my-feature")
    # Count occurrences of the path header — should be exactly 1
    local count
    count=$(echo "$output" | grep -c "### src/shared.py")
    [[ "$count" -eq 1 ]]
}

# ── Main ─────────────────────────────────────────────────────────

echo "Running context_assemble_security_auditor tests..."
echo ""

run_test test_header_contains_feature_name
run_test test_empty_feature_produces_minimal_prompt
run_test test_file_contents_included_for_existing_files
run_test test_missing_files_skipped_without_error
run_test test_product_spec_included_when_present
run_test test_tech_spec_included_when_present
run_test test_claude_md_included_when_present
run_test test_files_deduplicated_across_tasks

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
