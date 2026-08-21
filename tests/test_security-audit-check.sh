#!/usr/bin/env bash
# test_security_audit_check.sh — Tests for lib/security-audit-check.sh
#
# Usage: bash tests/test_security_audit_check.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_SCRIPT="${SCRIPT_DIR}/../lib/security-audit-check.sh"
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

assert_empty() {
    local actual="$1" context="${2:-}"
    if [[ -n "$actual" ]]; then
        echo "    ASSERT: expected empty, got '${actual}'${context:+ (${context})}" >&2
        return 1
    fi
}

assert_not_empty() {
    local actual="$1" context="${2:-}"
    if [[ -z "$actual" ]]; then
        echo "    ASSERT: expected non-empty result${context:+ (${context})}" >&2
        return 1
    fi
}

assert_contains() {
    local haystack="$1" needle="$2" context="${3:-}"
    if ! echo "$haystack" | grep -q "$needle"; then
        echo "    ASSERT: '${haystack}' does not contain '${needle}'${context:+ (${context})}" >&2
        return 1
    fi
}

# Load the library under test
# shellcheck source=../lib/security-audit-check.sh
source "$LIB_SCRIPT"

# ── Tests: check_security_section ────────────────────────────────

test_security_section_with_controls_passes() {
    local spec="${TEST_DIR}/spec.md"
    cat > "$spec" <<'EOF'
# My Feature

## Overview
Some description here.

## Security & Controls
All data is encrypted at rest using AES-256.
Rate limiting is applied at the API gateway.

## Implementation
Details here.
EOF
    local result
    result=$(check_security_section "$spec")
    assert_empty "$result" "## Security & Controls with content should return empty"
}

test_security_section_lowercase_passes() {
    local spec="${TEST_DIR}/spec.md"
    cat > "$spec" <<'EOF'
# My Feature

## Overview
Stuff.

## security considerations
Must validate all inputs against the schema.

## Next Section
Other stuff.
EOF
    local result
    result=$(check_security_section "$spec")
    assert_empty "$result" "lowercase ## security should pass (case-insensitive)"
}

test_missing_security_section_warns() {
    local spec="${TEST_DIR}/spec.md"
    cat > "$spec" <<'EOF'
# My Feature

## Overview
Some description.

## Implementation
Code stuff.
EOF
    local result
    result=$(check_security_section "$spec")
    assert_not_empty "$result" "missing security section should warn"
    assert_contains "$result" "WARN" "warning should start with WARN"
    assert_contains "$result" "Missing security" "should say Missing security"
}

test_empty_security_section_warns() {
    local spec="${TEST_DIR}/spec.md"
    cat > "$spec" <<'EOF'
# My Feature

## Overview
Description.

## Security

## Next Section
Content here.
EOF
    local result
    result=$(check_security_section "$spec")
    assert_not_empty "$result" "empty security section should warn"
    assert_contains "$result" "WARN" "warning should start with WARN"
    assert_contains "$result" "Empty security" "should say Empty security"
}

test_whitespace_only_security_section_warns() {
    local spec="${TEST_DIR}/spec.md"
    # Section has only blank lines before the next heading
    printf '# My Feature\n\n## Security\n   \n\t\n## Next Section\nContent.\n' > "$spec"
    local result
    result=$(check_security_section "$spec")
    assert_not_empty "$result" "whitespace-only security section should warn"
    assert_contains "$result" "WARN" "warning should start with WARN"
    assert_contains "$result" "Empty security" "should say Empty security"
}

test_warning_includes_filename() {
    local spec="${TEST_DIR}/my-feature-spec.md"
    cat > "$spec" <<'EOF'
# My Feature

## Overview
No security section here.
EOF
    local result
    result=$(check_security_section "$spec")
    assert_contains "$result" "my-feature-spec.md" "warning should include the filename"
}

test_security_at_eof_with_content_passes() {
    local spec="${TEST_DIR}/spec.md"
    # Security section at end of file — no trailing ## heading
    cat > "$spec" <<'EOF'
# My Feature

## Overview
Stuff.

## Security
Authentication uses OAuth 2.0 with PKCE.
EOF
    local result
    result=$(check_security_section "$spec")
    assert_empty "$result" "security section at EOF with content should pass"
}

test_security_at_eof_empty_warns() {
    local spec="${TEST_DIR}/spec.md"
    printf '# My Feature\n\n## Security\n' > "$spec"
    local result
    result=$(check_security_section "$spec")
    assert_not_empty "$result" "empty security section at EOF should warn"
}

test_missing_warning_includes_filename() {
    local spec="${TEST_DIR}/other-spec.md"
    cat > "$spec" <<'EOF'
# No Security
Some content.
EOF
    local result
    result=$(check_security_section "$spec")
    assert_contains "$result" "other-spec.md" "missing warning should include filename"
}

# ── Tests: check_security_sections_in_specs ──────────────────────

test_all_specs_pass_returns_empty() {
    cat > "${TEST_DIR}/spec-a.md" <<'EOF'
## Security
Uses HTTPS for all connections.
EOF
    cat > "${TEST_DIR}/spec-b.md" <<'EOF'
## Security Considerations
Input is sanitized.
EOF
    local result
    result=$(check_security_sections_in_specs "$TEST_DIR")
    assert_empty "$result" "all specs with security sections should return empty"
}

test_collects_warnings_from_multiple_files() {
    cat > "${TEST_DIR}/good.md" <<'EOF'
## Security
Using TLS 1.3.
EOF
    cat > "${TEST_DIR}/bad-a.md" <<'EOF'
## Overview
No security here.
EOF
    cat > "${TEST_DIR}/bad-b.md" <<'EOF'
## Security

## Next Section
EOF
    local result
    result=$(check_security_sections_in_specs "$TEST_DIR")
    assert_not_empty "$result" "should collect warnings from failing specs"
    assert_contains "$result" "bad-a.md" "should include bad-a.md in warnings"
    assert_contains "$result" "bad-b.md" "should include bad-b.md in warnings"
    # good.md should not appear
    if echo "$result" | grep -q "good.md"; then
        echo "    ASSERT: good.md should not appear in warnings" >&2
        return 1
    fi
}

test_processes_all_md_files_in_directory() {
    # Create 3 specs all missing security sections
    cat > "${TEST_DIR}/one.md" <<'EOF'
# Spec One
No security.
EOF
    cat > "${TEST_DIR}/two.md" <<'EOF'
# Spec Two
No security.
EOF
    cat > "${TEST_DIR}/three.md" <<'EOF'
# Spec Three
No security.
EOF
    local result
    result=$(check_security_sections_in_specs "$TEST_DIR")
    # All three should produce warnings
    local count
    count=$(echo "$result" | grep -c "WARN" || true)
    if [[ "$count" -ne 3 ]]; then
        echo "    ASSERT: expected 3 warnings, got ${count}" >&2
        return 1
    fi
}

# ── Main ──────────────────────────────────────────────────────────

echo "Running security-audit-check tests..."
echo ""

# check_security_section
run_test test_security_section_with_controls_passes
run_test test_security_section_lowercase_passes
run_test test_missing_security_section_warns
run_test test_empty_security_section_warns
run_test test_whitespace_only_security_section_warns
run_test test_warning_includes_filename
run_test test_security_at_eof_with_content_passes
run_test test_security_at_eof_empty_warns
run_test test_missing_warning_includes_filename

# check_security_sections_in_specs
run_test test_all_specs_pass_returns_empty
run_test test_collects_warnings_from_multiple_files
run_test test_processes_all_md_files_in_directory

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
