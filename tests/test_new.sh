#!/usr/bin/env bash
# test_new.sh — Integration tests for `speed new` command
#
# Usage: bash speed/tests/test_new.sh
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
    mkdir -p "${TEST_DIR}/speed/templates" "${TEST_DIR}/speed/lib" "${TEST_DIR}/speed/providers"
    mkdir -p "${TEST_DIR}/specs/product" "${TEST_DIR}/specs/tech" "${TEST_DIR}/specs/design"
    cp -r "${SCRIPT_DIR}/../templates/". "${TEST_DIR}/speed/templates/"
    cp -r "${SCRIPT_DIR}/../lib/". "${TEST_DIR}/speed/lib/"
    cp -r "${SCRIPT_DIR}/../providers/". "${TEST_DIR}/speed/providers/"
    cp "${SPEED_SCRIPT}" "${TEST_DIR}/speed/speed"
    chmod +x "${TEST_DIR}/speed/speed"
}

teardown() {
    rm -rf "$TEST_DIR"
}

assert_file_exists() {
    local file="$1"
    if [[ ! -f "$file" ]]; then
        echo "    ASSERT: file not found: ${file}" >&2
        return 1
    fi
}

assert_dir_exists() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        echo "    ASSERT: directory not found: ${dir}" >&2
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

assert_file_not_contains() {
    local file="$1" pattern="$2"
    if grep -qF "$pattern" "$file"; then
        echo "    ASSERT: '${file}' should not contain '${pattern}'" >&2
        return 1
    fi
}

assert_eq() {
    local expected="$1" actual="$2" label="${3:-value}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected ${label}='${expected}', got '${actual}'" >&2
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

# ── Tests ─────────────────────────────────────────────────────────

test_prd_creates_file() {
    run_speed new prd my-feature
    assert_file_exists "${TEST_DIR}/specs/product/my-feature.md"
}

test_rfc_creates_file() {
    run_speed new rfc my-feature
    assert_file_exists "${TEST_DIR}/specs/tech/my-feature.md"
}

test_design_creates_file() {
    run_speed new design my-feature
    assert_file_exists "${TEST_DIR}/specs/design/my-feature.md"
}

test_defect_creates_file() {
    run_speed new defect my-bug
    assert_file_exists "${TEST_DIR}/specs/defects/my-bug.md"
}

test_defect_creates_directory() {
    # specs/defects/ is not created by setup — cmd_new must create it
    run_speed new defect my-bug
    assert_dir_exists "${TEST_DIR}/specs/defects"
}

test_feature_name_replacement() {
    run_speed new prd my-feature
    assert_file_contains "${TEST_DIR}/specs/product/my-feature.md" "My Feature"
}

test_name_replacement() {
    # {product-spec} substitution embeds the raw name into rfc output
    run_speed new rfc my-feature
    assert_file_contains "${TEST_DIR}/specs/tech/my-feature.md" "my-feature"
}

test_product_spec_replacement() {
    run_speed new rfc my-feature
    assert_file_contains "${TEST_DIR}/specs/tech/my-feature.md" "specs/product/my-feature.md"
}

test_n_placeholder_preserved() {
    # {n} is the feature number set by the architect — must not be replaced
    run_speed new prd my-feature
    assert_file_contains "${TEST_DIR}/specs/product/my-feature.md" "{n}"
}

test_dep_placeholder_preserved() {
    # {dep} is filled in by the RFC author — must not be replaced
    run_speed new rfc my-feature
    assert_file_contains "${TEST_DIR}/specs/tech/my-feature.md" "{dep}"
}

test_no_overwrite() {
    run_speed new prd my-feature
    local original_content
    original_content=$(cat "${TEST_DIR}/specs/product/my-feature.md")

    local rc=0
    run_speed new prd my-feature || rc=$?
    assert_exit_code 3 "$rc" "second run should exit 3"

    local after_content
    after_content=$(cat "${TEST_DIR}/specs/product/my-feature.md")
    assert_eq "$original_content" "$after_content" "file content"
}

test_missing_name() {
    local rc=0
    run_speed new prd || rc=$?
    assert_exit_code 3 "$rc"
}

test_invalid_name_uppercase() {
    local rc=0
    run_speed new prd MyFeature || rc=$?
    assert_exit_code 3 "$rc"
}

test_invalid_name_leading_hyphen() {
    local rc=0
    run_speed new prd -my-feature || rc=$?
    assert_exit_code 3 "$rc"
}

test_invalid_name_trailing_hyphen() {
    local rc=0
    run_speed new prd my-feature- || rc=$?
    assert_exit_code 3 "$rc"
}

test_valid_name_single_char() {
    local rc=0
    run_speed new prd a || rc=$?
    assert_exit_code 0 "$rc"
    assert_file_exists "${TEST_DIR}/specs/product/a.md"
}

test_invalid_subcommand() {
    local rc=0
    run_speed new spec my-feature || rc=$?
    assert_exit_code 3 "$rc"
}

test_missing_template() {
    rm "${TEST_DIR}/speed/templates/prd.md"
    local rc=0
    run_speed new prd my-feature || rc=$?
    assert_exit_code 3 "$rc"
}

test_editor_not_opened_when_unset() {
    # EDITOR="" prevents exec into an editor; command should complete normally
    local rc=0
    EDITOR="" run_speed new prd my-feature || rc=$?
    assert_exit_code 0 "$rc"
    assert_file_exists "${TEST_DIR}/specs/product/my-feature.md"
}

test_multi_word_humanization() {
    run_speed new prd my-cool-feature
    assert_file_contains "${TEST_DIR}/specs/product/my-cool-feature.md" "My Cool Feature"
}

# ── Main ──────────────────────────────────────────────────────────

echo "Running speed new tests..."
echo ""

run_test test_prd_creates_file
run_test test_rfc_creates_file
run_test test_design_creates_file
run_test test_defect_creates_file
run_test test_defect_creates_directory
run_test test_feature_name_replacement
run_test test_name_replacement
run_test test_product_spec_replacement
run_test test_n_placeholder_preserved
run_test test_dep_placeholder_preserved
run_test test_no_overwrite
run_test test_missing_name
run_test test_invalid_name_uppercase
run_test test_invalid_name_leading_hyphen
run_test test_invalid_name_trailing_hyphen
run_test test_valid_name_single_char
run_test test_invalid_subcommand
run_test test_missing_template
run_test test_editor_not_opened_when_unset
run_test test_multi_word_humanization

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
