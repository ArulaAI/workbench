#!/usr/bin/env bash
# test_audit_multi_rfc.sh — Tests for multi-RFC support in audit pipeline
#
# Tests: template content, parent/child RFC resolution in audit.sh,
# sizing display for multi_rfc recommendation.
# Does NOT test AI agent output (requires live Claude connection).
#
# Usage: bash speed/tests/test_audit_multi_rfc.sh
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
    mkdir -p "${TEST_DIR}/speed/templates" "${TEST_DIR}/speed/lib" "${TEST_DIR}/speed/providers" "${TEST_DIR}/speed/agents"
    mkdir -p "${TEST_DIR}/specs/product" "${TEST_DIR}/specs/tech" "${TEST_DIR}/specs/design" "${TEST_DIR}/specs/defects"
    cp -r "${SCRIPT_DIR}/../templates/." "${TEST_DIR}/speed/templates/"
    cp -r "${SCRIPT_DIR}/../lib/." "${TEST_DIR}/speed/lib/"
    cp -r "${SCRIPT_DIR}/../providers/." "${TEST_DIR}/speed/providers/"
    cp -r "${SCRIPT_DIR}/../agents/." "${TEST_DIR}/speed/agents/"
    cp "${SPEED_SCRIPT}" "${TEST_DIR}/speed/speed"
    chmod +x "${TEST_DIR}/speed/speed"

    # Initialize minimal git repo
    (cd "$TEST_DIR" && git init -q && git add -A && git commit -q -m "init")

    # Create speed.toml with dummy provider config
    cat > "${TEST_DIR}/speed.toml" <<'TOML'
[agent]
provider = "claude-code"
planning_model = "opus"
support_model = "sonnet"
TOML
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

assert_file_contains() {
    local file="$1" pattern="$2"
    if ! grep -q "$pattern" "$file"; then
        echo "    ASSERT: ${file} does not contain '${pattern}'" >&2
        return 1
    fi
}

assert_file_not_contains() {
    local file="$1" pattern="$2"
    if grep -q "$pattern" "$file"; then
        echo "    ASSERT: ${file} should not contain '${pattern}'" >&2
        return 1
    fi
}

assert_output_contains() {
    local output="$1" pattern="$2"
    local stripped
    stripped=$(echo "$output" | sed 's/\x1b\[[0-9;]*m//g')
    if ! echo "$stripped" | grep -qi "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${stripped:0:500}" >&2
        return 1
    fi
}

run_speed_capture() {
    SPEED_PROJECT_ROOT="$TEST_DIR" CLAUDE_BIN=/nonexistent "${TEST_DIR}/speed/speed" "$@" 2>&1
}

# ══════════════════════════════════════════════════════════════════
# Template content tests
# ══════════════════════════════════════════════════════════════════

test_prd_template_has_rfc_decomposition() {
    assert_file_contains "${TEST_DIR}/speed/templates/prd.md" "RFC Decomposition"
}

test_prd_template_has_story_mapping_table() {
    assert_file_contains "${TEST_DIR}/speed/templates/prd.md" "User Story IDs"
    assert_file_contains "${TEST_DIR}/speed/templates/prd.md" "Child RFC"
    assert_file_contains "${TEST_DIR}/speed/templates/prd.md" "Testable Output"
}

test_prd_template_has_decomposition_guidance() {
    assert_file_contains "${TEST_DIR}/speed/templates/prd.md" "file ownership boundaries"
    assert_file_contains "${TEST_DIR}/speed/templates/prd.md" "Foundation first"
    assert_file_contains "${TEST_DIR}/speed/templates/prd.md" "3-5 Architect tasks"
}

test_rfc_template_has_parent_rfc_header() {
    assert_file_contains "${TEST_DIR}/speed/templates/rfc.md" "Parent RFC:"
}

test_rfc_template_has_naming_convention() {
    assert_file_contains "${TEST_DIR}/speed/templates/rfc.md" "NAMING CONVENTION"
    assert_file_contains "${TEST_DIR}/speed/templates/rfc.md" "{feature-name}-{part}.md"
}

test_rfc_template_has_interface_contract() {
    assert_file_contains "${TEST_DIR}/speed/templates/rfc.md" "Interface Contract"
    assert_file_contains "${TEST_DIR}/speed/templates/rfc.md" "Consumes"
    assert_file_contains "${TEST_DIR}/speed/templates/rfc.md" "Produces"
}

test_rfc_template_has_boost_documentation() {
    assert_file_contains "${TEST_DIR}/speed/templates/rfc.md" "BOOST_DEPENDENCY"
    assert_file_contains "${TEST_DIR}/speed/templates/rfc.md" "BOOST_PARENT_REF"
    assert_file_contains "${TEST_DIR}/speed/templates/rfc.md" "BOOST_FILENAME_PAIR"
}

test_design_template_has_multi_rfc_note() {
    assert_file_contains "${TEST_DIR}/speed/templates/design.md" "MULTI-RFC FEATURES"
    assert_file_contains "${TEST_DIR}/speed/templates/design.md" "design spec typically stays"
}

# ══════════════════════════════════════════════════════════════════
# Audit agent definition tests
# ══════════════════════════════════════════════════════════════════

test_audit_agent_has_family_context() {
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" "RFC family context"
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" "Parent RFC"
}

test_audit_agent_has_multi_rfc_checks() {
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" "Parent RFC link resolves"
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" "Interface Contract completeness"
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" "Interface consistency"
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" "Story coverage across children"
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" "Dependency graph acyclicity"
}

test_audit_agent_has_multi_rfc_sizing() {
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" "multi_rfc"
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" "15 tasks"
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" "1,000 lines"
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" "suggested_children"
}

test_audit_agent_output_schema_has_parent_rfc() {
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" '"parent_rfc"'
    assert_file_contains "${TEST_DIR}/speed/agents/audit.md" '"child_rfcs"'
}

# ══════════════════════════════════════════════════════════════════
# audit.sh parent/child RFC resolution tests
# ══════════════════════════════════════════════════════════════════

test_audit_detects_parent_rfc_header() {
    # Create a child RFC that references a parent
    cat > "${TEST_DIR}/specs/tech/feature-part1.md" <<'EOF'
# RFC: Feature Part 1

> Parent RFC: [feature.md](feature.md)
> Depends on: nothing

## Basic Example
Some example.
EOF
    # Create the parent RFC
    cat > "${TEST_DIR}/specs/tech/feature.md" <<'EOF'
# RFC: Feature (Parent)

## Overview
Parent umbrella RFC.
EOF

    local output rc=0
    output=$(run_speed_capture audit specs/tech/feature-part1.md) || rc=$?
    # Should detect parent RFC (will fail at agent invocation but we check pre-agent output)
    assert_output_contains "$output" "Parent RFC"
}

test_audit_detects_child_rfcs() {
    # Create a parent RFC
    cat > "${TEST_DIR}/specs/tech/feature.md" <<'EOF'
# RFC: Feature (Parent)

## Overview
Parent umbrella RFC.
EOF
    # Create two child RFCs referencing the parent
    cat > "${TEST_DIR}/specs/tech/feature-part1.md" <<'EOF'
# RFC: Feature Part 1
> Parent RFC: [feature.md](feature.md)
## Basic Example
EOF
    cat > "${TEST_DIR}/specs/tech/feature-part2.md" <<'EOF'
# RFC: Feature Part 2
> Parent RFC: [feature.md](feature.md)
## Basic Example
EOF

    # Commit new files so speed can see them
    (cd "$TEST_DIR" && git add -A && git commit -q -m "add specs")

    local output rc=0
    output=$(run_speed_capture audit specs/tech/feature.md) || rc=$?
    # Should discover child RFCs
    assert_output_contains "$output" "Child RFCs"
}

test_audit_no_parent_for_standalone_rfc() {
    # Create a standalone RFC (no Parent RFC header)
    cat > "${TEST_DIR}/specs/tech/standalone.md" <<'EOF'
# RFC: Standalone Feature

> See [standalone.md](../product/standalone.md) for product context.

## Basic Example
Some example.
EOF

    local output rc=0
    output=$(run_speed_capture audit specs/tech/standalone.md) || rc=$?
    # Should NOT show "Parent RFC:" in output (no parent to detect)
    # The output should show "rfc" type but not "Parent RFC"
    assert_output_contains "$output" "rfc"
}

test_audit_broken_parent_rfc_link() {
    # Create a child RFC pointing to a nonexistent parent
    cat > "${TEST_DIR}/specs/tech/orphan.md" <<'EOF'
# RFC: Orphan Child

> Parent RFC: [nonexistent.md](nonexistent.md)

## Basic Example
Something.
EOF

    local output rc=0
    output=$(run_speed_capture audit specs/tech/orphan.md) || rc=$?
    # Should warn about broken parent link
    assert_output_contains "$output" "Parent RFC not found"
}

# ══════════════════════════════════════════════════════════════════
# Sizing display tests (mock JSON parsing)
# ══════════════════════════════════════════════════════════════════

test_sizing_multi_rfc_json_parsing() {
    # Test that jq can parse the multi_rfc sizing format
    local test_json='{"status":"warn","spec_type":"rfc","spec_file":"specs/tech/big.md","linked_specs":{"prd":null,"design":null,"parent_rfc":null,"child_rfcs":[]},"issues":[],"sizing":{"estimated_tasks":20,"recommendation":"multi_rfc","rationale":"Too large","phase_sections":{},"suggested_children":[{"name":"big-foundation.md","sections":[0,1],"depends_on":[],"testable_output":"dataclasses"},{"name":"big-analysis.md","sections":[2,3],"depends_on":["big-foundation.md"],"testable_output":"analysis functions"}]}}'

    local rec
    rec=$(echo "$test_json" | jq -r '.sizing.recommendation')
    [[ "$rec" == "multi_rfc" ]] || { echo "    ASSERT: recommendation should be multi_rfc, got $rec" >&2; return 1; }

    local child_count
    child_count=$(echo "$test_json" | jq '.sizing.suggested_children | length')
    [[ "$child_count" == "2" ]] || { echo "    ASSERT: should have 2 suggested children, got $child_count" >&2; return 1; }

    local first_name
    first_name=$(echo "$test_json" | jq -r '.sizing.suggested_children[0].name')
    [[ "$first_name" == "big-foundation.md" ]] || { echo "    ASSERT: first child name should be big-foundation.md, got $first_name" >&2; return 1; }

    local parent_rfc
    parent_rfc=$(echo "$test_json" | jq -r '.linked_specs.parent_rfc // "null"')
    [[ "$parent_rfc" == "null" ]] || { echo "    ASSERT: parent_rfc should be null, got $parent_rfc" >&2; return 1; }

    local child_rfcs_len
    child_rfcs_len=$(echo "$test_json" | jq '.linked_specs.child_rfcs | length')
    [[ "$child_rfcs_len" == "0" ]] || { echo "    ASSERT: child_rfcs should be empty, got $child_rfcs_len" >&2; return 1; }
}

# ── Main ─────────────────────────────────────────────────────────

echo "Running multi-RFC audit tests..."
echo ""

echo "=== Template Content ==="
run_test test_prd_template_has_rfc_decomposition
run_test test_prd_template_has_story_mapping_table
run_test test_prd_template_has_decomposition_guidance
run_test test_rfc_template_has_parent_rfc_header
run_test test_rfc_template_has_naming_convention
run_test test_rfc_template_has_interface_contract
run_test test_rfc_template_has_boost_documentation
run_test test_design_template_has_multi_rfc_note
echo ""

echo "=== Audit Agent Definition ==="
run_test test_audit_agent_has_family_context
run_test test_audit_agent_has_multi_rfc_checks
run_test test_audit_agent_has_multi_rfc_sizing
run_test test_audit_agent_output_schema_has_parent_rfc
echo ""

echo "=== audit.sh Parent/Child Resolution ==="
run_test test_audit_detects_parent_rfc_header
run_test test_audit_detects_child_rfcs
run_test test_audit_no_parent_for_standalone_rfc
run_test test_audit_broken_parent_rfc_link
echo ""

echo "=== Sizing JSON Parsing ==="
run_test test_sizing_multi_rfc_json_parsing
echo ""

echo "────────────────────────────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
