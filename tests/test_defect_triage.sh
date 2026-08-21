#!/usr/bin/env bash
# test_defect_triage.sh — Unit tests for lib/defect_triage.sh
#
# Tests resolve_related_specs, build_investigation_prompt,
# build_classification_prompt, escalate_to_feature, print_triage_summary,
# and route_by_complexity. Does NOT test triage_defect (requires live
# provider_run calls).
#
# Usage: bash tests/test_defect_triage.sh
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

    export SPEED_PROJECT_ROOT="$TEST_DIR"
    export VERBOSITY=0

    # Source required libraries
    # shellcheck disable=SC1090
    source "${LIB_DIR}/config.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/log.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/defects.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/defect_triage.sh"

    mkdir -p "${TEST_DIR}/.speed/defects"
    mkdir -p "${TEST_DIR}/specs/defects"
    mkdir -p "${TEST_DIR}/specs/product"
    mkdir -p "${TEST_DIR}/specs/tech"
}

teardown() {
    rm -rf "$TEST_DIR"
    unset SPEED_PROJECT_ROOT
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

assert_file_exists() {
    local file="$1"
    if [[ ! -f "$file" ]]; then
        echo "    ASSERT: file not found: ${file}" >&2
        return 1
    fi
}

assert_output_contains() {
    local output="$1" pattern="$2"
    if ! echo "$output" | grep -q "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:300}" >&2
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

# ── Helper: create a minimal valid defect report ──────────────────

make_defect_report() {
    local path="$1"
    local severity="${2:-P2}"
    local feature="${3:-my-feature}"
    cat > "$path" <<EOF
Severity: ${severity}
Related Feature: ${feature}
Observed Behavior: The widget crashes on load
Expected Behavior: The widget renders correctly
Reproduction Steps: Open the app and click the widget
EOF
}

# Helper: set up a defect through init + state creation + triage write
setup_triaged_defect() {
    local name="$1"
    local complexity="${2:-moderate}"
    local is_defect="${3:-true}"

    local spec="${TEST_DIR}/specs/defects/${name}.md"
    make_defect_report "$spec"
    init_defect_dir "$name" "$spec"
    create_defect_state "$name" "$spec"
    transition_defect_state "$name" "triaging"

    local triage_json
    triage_json=$(cat <<EOJSON
{
    "is_defect": ${is_defect},
    "complexity": "${complexity}",
    "defect_type": "logic",
    "affected_files": ["lib/defects.sh", "lib/defect_triage.sh"],
    "severity": "P2",
    "root_cause_hypothesis": "State machine missing transition",
    "blast_radius": "low",
    "blast_radius_detail": "Only affects defect pipeline",
    "test_coverage": "existing",
    "test_coverage_detail": "Tests exist in tests/test_defect_state.sh",
    "related_spec": "specs/product/my-feature.md",
    "suggested_approach": "Add missing transition to state machine",
    "regression_risks": ["Other transitions could break"],
    "escalation_reason": null
}
EOJSON
)

    echo "$triage_json" | write_triage_output "$name"
    transition_defect_state "$name" "triaged"
}

# ── Tests: resolve_related_specs ──────────────────────────────────

test_resolve_related_specs_finds_both() {
    echo "# Product spec" > "${TEST_DIR}/specs/product/my-feature.md"
    echo "# Tech spec" > "${TEST_DIR}/specs/tech/my-feature.md"

    local output
    output=$(resolve_related_specs "my-feature" 2>/dev/null)

    assert_output_contains "$output" "specs/product/my-feature.md"
    assert_output_contains "$output" "specs/tech/my-feature.md"
}

test_resolve_related_specs_product_only() {
    echo "# Product spec" > "${TEST_DIR}/specs/product/my-feature.md"

    local output stderr_output
    output=$(resolve_related_specs "my-feature" 2>/dev/null)
    stderr_output=$(resolve_related_specs "my-feature" 2>&1 >/dev/null)

    assert_output_contains "$output" "specs/product/my-feature.md"
    assert_output_not_contains "$output" "specs/tech/"
    # Should warn about missing tech spec on stderr
    assert_output_contains "$stderr_output" "Tech spec not found"
}

test_resolve_related_specs_warns_missing() {
    # Neither spec exists
    local stderr_output
    stderr_output=$(resolve_related_specs "nonexistent-feature" 2>&1 >/dev/null)

    assert_output_contains "$stderr_output" "not found"
}

test_resolve_related_specs_empty_name() {
    local rc=0
    resolve_related_specs "" 2>/dev/null || rc=$?
    assert_exit_code 0 "$rc" "empty feature name should not fail"
}

# ── Tests: build_investigation_prompt ─────────────────────────────

test_build_investigation_prompt_includes_report() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"

    local output
    output=$(build_investigation_prompt "$spec" "" "")

    assert_output_contains "$output" "Defect Report"
    assert_output_contains "$output" "widget crashes"
}

test_build_investigation_prompt_includes_product_spec() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    echo "# Feature Spec Content" > "${TEST_DIR}/specs/product/my-feature.md"

    local output
    output=$(build_investigation_prompt "$spec" "${TEST_DIR}/specs/product/my-feature.md" "")

    assert_output_contains "$output" "Related Product Spec"
    assert_output_contains "$output" "Feature Spec Content"
}

test_build_investigation_prompt_includes_tech_spec() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    echo "# Tech Spec Content" > "${TEST_DIR}/specs/tech/my-feature.md"

    local output
    output=$(build_investigation_prompt "$spec" "" "${TEST_DIR}/specs/tech/my-feature.md")

    assert_output_contains "$output" "Related Tech Spec"
    assert_output_contains "$output" "Tech Spec Content"
}

test_build_investigation_prompt_includes_agent_def() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"

    local output
    output=$(build_investigation_prompt "$spec" "" "")

    assert_output_contains "$output" "Triage Agent"
    assert_output_contains "$output" "Begin Phase 1 investigation"
}

# ── Tests: build_classification_prompt ────────────────────────────

test_build_classification_prompt_includes_transcript() {
    local transcript="I found the bug in lib/defects.sh line 42"

    local output
    output=$(build_classification_prompt "$transcript")

    assert_output_contains "$output" "Investigation Transcript"
    assert_output_contains "$output" "found the bug"
}

test_build_classification_prompt_includes_phase2_instruction() {
    local transcript="Investigation results here"

    local output
    output=$(build_classification_prompt "$transcript")

    assert_output_contains "$output" "Phase 2 classification JSON"
}

# ── Tests: escalate_to_feature ────────────────────────────────────

test_escalate_to_feature_creates_prd() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    local output
    output=$(escalate_to_feature "my-bug" 2>/dev/null)

    assert_file_exists "${TEST_DIR}/specs/product/my-bug.md"
    assert_output_contains "$output" "specs/product/my-bug.md"
}

test_escalate_to_feature_maps_fields() {
    local spec="${TEST_DIR}/specs/defects/my-bug.md"
    make_defect_report "$spec"
    init_defect_dir "my-bug" "$spec"
    create_defect_state "my-bug" "$spec"

    escalate_to_feature "my-bug" >/dev/null 2>/dev/null

    local prd="${TEST_DIR}/specs/product/my-bug.md"
    assert_output_contains "$(cat "$prd")" "Problem"
    assert_output_contains "$(cat "$prd")" "Success Criteria"
    assert_output_contains "$(cat "$prd")" "User Flows"
    assert_output_contains "$(cat "$prd")" "Dependencies"
}

test_escalate_to_feature_fails_missing_defect() {
    local rc=0
    escalate_to_feature "nonexistent" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "should fail for missing defect"
}

# ── Tests: print_triage_summary ───────────────────────────────────

test_print_triage_summary_shows_complexity() {
    setup_triaged_defect "summary-bug" "moderate"

    # Reset to triaging for summary test (state is at triaged after setup)
    local output
    output=$(print_triage_summary "summary-bug" 2>/dev/null)

    assert_output_contains "$output" "moderate"
}

test_print_triage_summary_shows_affected_files() {
    setup_triaged_defect "files-bug" "trivial"

    local output
    output=$(print_triage_summary "files-bug" 2>/dev/null)

    assert_output_contains "$output" "lib/defects.sh"
}

test_print_triage_summary_shows_suggested_approach() {
    setup_triaged_defect "approach-bug" "moderate"

    local output
    output=$(print_triage_summary "approach-bug" 2>/dev/null)

    assert_output_contains "$output" "Add missing transition"
}

test_print_triage_summary_rejected_defect() {
    local name="rejected-bug"
    local spec="${TEST_DIR}/specs/defects/${name}.md"
    make_defect_report "$spec"
    init_defect_dir "$name" "$spec"
    create_defect_state "$name" "$spec"
    transition_defect_state "$name" "triaging"

    # Write triage.json directly (write_triage_output treats boolean false
    # as empty due to jq's // empty semantics, so bypass validation)
    local triage_json='{"is_defect": false, "complexity": "trivial", "defect_type": "logic", "affected_files": ["lib/defects.sh"], "root_cause_hypothesis": "Spec says X, code does X. Feature change request."}'
    defect_triage_write "$name" "$triage_json"

    local output
    output=$(print_triage_summary "$name" 2>/dev/null)

    assert_output_contains "$output" "Not a defect"
}

test_print_triage_summary_missing_triage() {
    local spec="${TEST_DIR}/specs/defects/no-triage.md"
    make_defect_report "$spec"
    init_defect_dir "no-triage" "$spec"
    create_defect_state "no-triage" "$spec"

    local rc=0
    print_triage_summary "no-triage" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "should fail without triage.json"
}

# ── Tests: route_by_complexity ────────────────────────────────────

test_route_trivial_returns_0() {
    setup_triaged_defect "trivial-bug" "trivial"

    local rc=0
    route_by_complexity "trivial-bug" 2>/dev/null || rc=$?
    assert_exit_code 0 "$rc" "trivial should return 0 (continue)"
}

test_route_moderate_returns_1() {
    setup_triaged_defect "moderate-bug" "moderate"

    local rc=0
    route_by_complexity "moderate-bug" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "moderate should return 1 (stop)"
}

test_route_moderate_prints_run_command() {
    setup_triaged_defect "mod-cmd-bug" "moderate"

    local output
    output=$(route_by_complexity "mod-cmd-bug" 2>&1)

    assert_output_contains "$output" "Human review required"
    assert_output_contains "$output" "speed run --defect"
}

test_route_complex_calls_escalate() {
    setup_triaged_defect "complex-bug" "complex"

    local rc=0
    route_by_complexity "complex-bug" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "complex should return 1 (stop)"

    # Should have created a PRD
    assert_file_exists "${TEST_DIR}/specs/product/complex-bug.md"
}

test_route_rejected_returns_1() {
    local name="not-a-bug"
    local spec="${TEST_DIR}/specs/defects/${name}.md"
    make_defect_report "$spec"
    init_defect_dir "$name" "$spec"
    create_defect_state "$name" "$spec"
    transition_defect_state "$name" "triaging"

    # Write triage.json directly (write_triage_output treats boolean false
    # as empty due to jq's // empty semantics, so bypass validation)
    local triage_json='{"is_defect": false, "complexity": "trivial", "defect_type": "logic", "affected_files": ["lib/x.sh"], "root_cause_hypothesis": "Code behaves per spec"}'
    defect_triage_write "$name" "$triage_json"

    local rc=0
    route_by_complexity "$name" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "rejected defect should return 1"
}

test_route_rejected_prints_explanation() {
    local name="explain-reject"
    local spec="${TEST_DIR}/specs/defects/${name}.md"
    make_defect_report "$spec"
    init_defect_dir "$name" "$spec"
    create_defect_state "$name" "$spec"
    transition_defect_state "$name" "triaging"

    # Write triage.json directly (bypass write_triage_output boolean validation)
    local triage_json='{"is_defect": false, "complexity": "trivial", "defect_type": "logic", "affected_files": ["lib/x.sh"], "root_cause_hypothesis": "Code behaves per spec"}'
    defect_triage_write "$name" "$triage_json"

    local output
    output=$(route_by_complexity "$name" 2>&1)

    assert_output_contains "$output" "Rejected"
    assert_output_contains "$output" "Code behaves per spec"
}

test_route_missing_triage_fails() {
    local spec="${TEST_DIR}/specs/defects/no-triage2.md"
    make_defect_report "$spec"
    init_defect_dir "no-triage2" "$spec"
    create_defect_state "no-triage2" "$spec"

    local rc=0
    route_by_complexity "no-triage2" 2>/dev/null || rc=$?
    assert_exit_code 1 "$rc" "missing triage.json should fail"
}

# ── Main ──────────────────────────────────────────────────────────

echo "Running defect triage pipeline tests..."
echo ""

# resolve_related_specs
run_test test_resolve_related_specs_finds_both
run_test test_resolve_related_specs_product_only
run_test test_resolve_related_specs_warns_missing
run_test test_resolve_related_specs_empty_name

# build_investigation_prompt
run_test test_build_investigation_prompt_includes_report
run_test test_build_investigation_prompt_includes_product_spec
run_test test_build_investigation_prompt_includes_tech_spec
run_test test_build_investigation_prompt_includes_agent_def

# build_classification_prompt
run_test test_build_classification_prompt_includes_transcript
run_test test_build_classification_prompt_includes_phase2_instruction

# escalate_to_feature
run_test test_escalate_to_feature_creates_prd
run_test test_escalate_to_feature_maps_fields
run_test test_escalate_to_feature_fails_missing_defect

# print_triage_summary
run_test test_print_triage_summary_shows_complexity
run_test test_print_triage_summary_shows_affected_files
run_test test_print_triage_summary_shows_suggested_approach
run_test test_print_triage_summary_rejected_defect
run_test test_print_triage_summary_missing_triage

# route_by_complexity
run_test test_route_trivial_returns_0
run_test test_route_moderate_returns_1
run_test test_route_moderate_prints_run_command
run_test test_route_complex_calls_escalate
run_test test_route_rejected_returns_1
run_test test_route_rejected_prints_explanation
run_test test_route_missing_triage_fails

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

[[ $FAIL -eq 0 ]]
