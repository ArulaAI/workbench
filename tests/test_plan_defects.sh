#!/usr/bin/env bash
# test_plan_defects.sh — Unit tests for defect-driven `speed plan --defects`
#
# Covers the deterministic pieces added on top of the --defects input path
# per PLAN_CONTRACT.md: defect file resolution (missing file, directory,
# multiple files), the F8 hard gate (fail/pass), Failure Class/Evidence
# metadata propagation, and CLI-level input validation (missing --feature,
# missing defect file). No agent/architect calls — per PLAN_CONTRACT.md
# §13, these are exactly the bash/jq pieces that are unit-testable without
# a model. The end-to-end run against specs/defects/1.md and 2.md (which
# does call the architect) is exercised separately via a real
# `speed plan --defects` invocation, not as part of this fast suite.
#
# Usage: bash tests/test_plan_defects.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEED_HOME="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_DIR="${SPEED_HOME}/lib"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)
    export SPEED_PROJECT_ROOT="$TEST_DIR"
    export VERBOSITY=0
    unset GLOBAL_FEATURE || true

    # shellcheck disable=SC1090
    source "${LIB_DIR}/config.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/log.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/tasks.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/features.sh"
    # shellcheck disable=SC1090
    source "${LIB_DIR}/cmd/plan.sh"

    mkdir -p "${TEST_DIR}/specs/defects"
    FEATURE_DIR="${TEST_DIR}/.speed/features/testfeat"
    TASKS_DIR="${FEATURE_DIR}/tasks"
    LOGS_DIR="${FEATURE_DIR}/logs"
    CONTRACT_FILE="${FEATURE_DIR}/contract.json"
    mkdir -p "$TASKS_DIR" "$LOGS_DIR"
}

teardown() {
    rm -rf "$TEST_DIR"
    unset SPEED_PROJECT_ROOT GLOBAL_FEATURE
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

assert_output_contains() {
    local output="$1" pattern="$2"
    if ! echo "$output" | grep -qF "$pattern"; then
        echo "    ASSERT: output does not contain '${pattern}'" >&2
        echo "    OUTPUT: ${output:0:400}" >&2
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

# ── Helper: minimal valid defect fixture ──────────────────────────

make_defect() {
    local path="$1" failure_class="${2:-}" evidence="${3:-}"
    {
        echo "# Defect: test defect"
        echo ""
        echo "Severity: P2"
        echo "Related Feature: test-feature"
        [[ -n "$failure_class" ]] && echo "Failure Class: ${failure_class}"
        [[ -n "$evidence" ]] && echo "Evidence: ${evidence}"
        echo ""
        echo "## Observed Behavior"
        echo ""
        echo "Something is wrong."
        echo ""
        echo "## Expected Behavior"
        echo ""
        echo "Something should be right."
    } > "$path"
}

# ── Tests: _resolve_defect_files ──────────────────────────────────

test_resolve_defect_files_single_file() {
    local f="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f"
    local result
    result=$(_resolve_defect_files "$f")
    assert_eq "$f" "$result" "resolved path"
}

test_resolve_defect_files_multiple_files() {
    local f1="${TEST_DIR}/specs/defects/1.md" f2="${TEST_DIR}/specs/defects/2.md"
    make_defect "$f1"
    make_defect "$f2"
    local result count
    result=$(_resolve_defect_files "$f1" "$f2")
    count=$(echo "$result" | wc -l | tr -d ' ')
    assert_eq "2" "$count" "resolved file count" || return 1
    assert_output_contains "$result" "$f1" || return 1
    assert_output_contains "$result" "$f2" || return 1
}

test_resolve_defect_files_relative_to_project_root() {
    local f="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f"
    # Resolution checks the path relative to CWD first (same convention as
    # the existing tech-spec resolution elsewhere in plan.sh), falling back
    # to PROJECT_ROOT only when that fails. Run from an unrelated CWD (not
    # TEST_DIR) so the relative path can only resolve via the PROJECT_ROOT
    # fallback, not the CWD-relative check.
    local other_cwd
    other_cwd=$(mktemp -d)
    local result rc=0
    result=$(cd "$other_cwd" && _resolve_defect_files "specs/defects/1.md") || rc=$?
    rm -rf "$other_cwd"
    assert_exit_code "0" "$rc" || return 1
    assert_eq "$f" "$result" "resolved relative path"
}

test_resolve_defect_files_missing_file_fails() {
    local output rc=0
    output=$(_resolve_defect_files "${TEST_DIR}/specs/defects/nope.md" 2>&1) || rc=$?
    assert_exit_code "1" "$rc" || return 1
    assert_output_contains "$output" "not found" || return 1
}

test_resolve_defect_files_directory_rejected() {
    local output rc=0
    output=$(_resolve_defect_files "${TEST_DIR}/specs/defects" 2>&1) || rc=$?
    assert_exit_code "1" "$rc" || return 1
    assert_output_contains "$output" "directory" || return 1
}

test_resolve_defect_files_stops_at_first_bad_path() {
    # Proves every path in a multi-file --defects call is validated
    # individually, not just the first — the third (missing) file must
    # still be caught even though the first two resolve fine.
    local f1="${TEST_DIR}/specs/defects/1.md" f2="${TEST_DIR}/specs/defects/2.md"
    make_defect "$f1"
    make_defect "$f2"
    local output rc=0
    output=$(_resolve_defect_files "$f1" "$f2" "${TEST_DIR}/specs/defects/3.md" 2>&1) || rc=$?
    assert_exit_code "1" "$rc" || return 1
    assert_output_contains "$output" "3.md" || return 1
}

# ── Tests: _extract_defect_metadata ────────────────────────────────
# Regression coverage: the first real E2E run against specs/defects/1.md
# and 2.md (neither declares Failure Class/Evidence — the common case
# per PLAN_CONTRACT.md §14) crashed the whole plan run. Cause: the
# extraction grep exits 1 on no match, and under this script's
# `set -euo pipefail` an unguarded `fc=$(grep ... )` with no match
# silently kills the shell before any error is ever logged. These tests
# run under the same `set -e` (inherited from sourcing config.sh) that
# caused the crash, so they fail the same way the real bug did if the
# `|| true` guards are ever removed.

test_extract_defect_metadata_handles_files_with_no_failure_class() {
    local f1="${TEST_DIR}/specs/defects/1.md" f2="${TEST_DIR}/specs/defects/2.md"
    make_defect "$f1"   # no Failure Class / Evidence lines
    make_defect "$f2"   # no Failure Class / Evidence lines
    defect_files=("$f1" "$f2")

    _extract_defect_metadata

    assert_eq "2" "${#defect_contents[@]}" "content count" || return 1
    assert_eq "" "${defect_failure_class[0]:-}" "failure_class[0]" || return 1
    assert_eq "" "${defect_evidence[1]:-}" "evidence[1]"
}

test_extract_defect_metadata_extracts_declared_fields() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1" "F8" "silence"
    defect_files=("$f1")

    _extract_defect_metadata

    assert_eq "F8" "${defect_failure_class[0]:-}" "failure_class[0]" || return 1
    assert_eq "silence" "${defect_evidence[0]:-}" "evidence[0]"
}

test_extract_defect_metadata_mixed_declared_and_undeclared() {
    local f1="${TEST_DIR}/specs/defects/1.md" f2="${TEST_DIR}/specs/defects/2.md"
    make_defect "$f1"            # no fields
    make_defect "$f2" "F2" "proof"
    defect_files=("$f1" "$f2")

    _extract_defect_metadata

    assert_eq "" "${defect_failure_class[0]:-}" "failure_class[0]" || return 1
    assert_eq "F2" "${defect_failure_class[1]:-}" "failure_class[1]" || return 1
    assert_eq "proof" "${defect_evidence[1]:-}" "evidence[1]"
}

# ── Tests: _defect_index_for_spec_refs ────────────────────────────

test_defect_index_matches_absolute_path() {
    local f1="${TEST_DIR}/specs/defects/1.md" f2="${TEST_DIR}/specs/defects/2.md"
    make_defect "$f1"; make_defect "$f2"
    defect_files=("$f1" "$f2")
    local refs result
    refs='[{"spec":"'"$f2"'","section":"x","requirement":"y"}]'
    result=$(_defect_index_for_spec_refs "$refs")
    assert_eq "1" "$result" "matched index"
}

test_defect_index_matches_relative_path() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1"
    defect_files=("$f1")
    local result
    result=$(_defect_index_for_spec_refs '[{"spec":"specs/defects/1.md","section":"x","requirement":"y"}]')
    assert_eq "0" "$result" "matched index"
}

test_defect_index_matches_basename() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1"
    defect_files=("$f1")
    local result
    result=$(_defect_index_for_spec_refs '[{"spec":"1.md","section":"x","requirement":"y"}]')
    assert_eq "0" "$result" "matched index"
}

test_defect_index_no_match_returns_failure() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1"
    defect_files=("$f1")
    local rc=0
    _defect_index_for_spec_refs '[{"spec":"product","section":"x","requirement":"y"}]' >/dev/null || rc=$?
    assert_exit_code "1" "$rc"
}

# ── Tests: _attach_defect_metadata ─────────────────────────────────

test_attach_defect_metadata_propagates_fields() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1" "F2" "single opinion"
    defect_files=("$f1")
    defect_failure_class=("F2")
    defect_evidence=("single opinion")

    task_create "1" "Fix the thing" "desc" "criteria" "[]" "sonnet" >/dev/null
    local refs="[{\"spec\":\"${f1}\",\"section\":\"Observed Behavior\",\"requirement\":\"fix it\"}]"
    _attach_defect_metadata "1" "$refs"

    local task_file="${TASKS_DIR}/1.json"
    assert_eq "F2" "$(jq -r '.failure_class' "$task_file")" "failure_class" || return 1
    assert_eq "single opinion" "$(jq -r '.evidence' "$task_file")" "evidence" || return 1
    assert_eq "specs/defects/1.md" "$(jq -r '.source_defect' "$task_file")" "source_defect" || return 1
}

test_attach_defect_metadata_is_set_e_safe_with_no_evidence() {
    # Regression: the second real E2E run crashed silently mid-task-loop.
    # Root cause: _attach_defect_metadata's last executed statement was a
    # bare `[[ -n "$_ev" ]] && task_update ...`, which is 1 whenever
    # evidence is undeclared (the common case), and under `set -e` that
    # kills the whole plan run right after the call site's bare
    # `if ...; then _attach_defect_metadata ...; fi`.
    #
    # This cannot be reproduced inside a `(...)` subshell of this test
    # script, even one with its own explicit `set -e`: bash suspends
    # errexit for the ENTIRE dynamic extent of a function invoked where
    # its exit status is checked (exactly what `run_test`'s
    # `"$test_name" || rc=$?` does for every test here), and that
    # suspension propagates into subshells started within it too. Only a
    # genuinely separate bash process escapes that suspension, so this
    # test shells out to one, sourcing the real plan.sh fresh and
    # exercising the exact same unguarded call-site pattern.
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1"   # no Failure Class / Evidence lines
    local marker="${TEST_DIR}/reached_marker"
    local repro_tasks_dir="${TEST_DIR}/repro_tasks"
    mkdir -p "$repro_tasks_dir"
    rm -f "$marker"

    local repro="${TEST_DIR}/repro.sh"
    cat > "$repro" <<REPRO
#!/usr/bin/env bash
source "${LIB_DIR}/config.sh"
source "${LIB_DIR}/log.sh"
source "${LIB_DIR}/tasks.sh"
source "${LIB_DIR}/features.sh"
source "${LIB_DIR}/cmd/plan.sh"

TASKS_DIR="${repro_tasks_dir}"

defect_files=("${f1}")
defect_failure_class=("")
defect_evidence=("")
defects_mode="true"

task_create "1" "Some task" "desc" "criteria" "[]" "sonnet" >/dev/null
refs="[{\"spec\":\"${f1}\",\"section\":\"x\",\"requirement\":\"y\"}]"

if [[ "\$defects_mode" == "true" ]]; then
    _attach_defect_metadata "1" "\$refs"
fi
echo ok > "${marker}"
REPRO

    SPEED_PROJECT_ROOT="$TEST_DIR" VERBOSITY=0 bash "$repro" >/dev/null 2>&1

    assert_file_exists "$marker"
}

test_attach_defect_metadata_noop_without_match() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1" "F2" "single opinion"
    defect_files=("$f1")
    defect_failure_class=("F2")
    defect_evidence=("single opinion")

    task_create "1" "Unrelated task" "desc" "criteria" "[]" "sonnet" >/dev/null
    _attach_defect_metadata "1" '[{"spec":"product","section":"x","requirement":"y"}]'

    local task_file="${TASKS_DIR}/1.json"
    assert_eq "false" "$(jq -r 'has("failure_class")' "$task_file")" "failure_class should be absent"
}

test_attach_defect_metadata_skips_missing_evidence_fields() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1"   # no Failure Class / Evidence lines
    defect_files=("$f1")
    defect_failure_class=("")
    defect_evidence=("")

    task_create "1" "Fix currency check" "desc" "criteria" "[]" "sonnet" >/dev/null
    local refs="[{\"spec\":\"${f1}\",\"section\":\"x\",\"requirement\":\"y\"}]"
    _attach_defect_metadata "1" "$refs"

    local task_file="${TASKS_DIR}/1.json"
    assert_eq "specs/defects/1.md" "$(jq -r '.source_defect' "$task_file")" "source_defect" || return 1
    assert_eq "false" "$(jq -r 'has("failure_class")' "$task_file")" "failure_class should be absent"
}

# ── Tests: _run_f8_gate ─────────────────────────────────────────────

test_f8_gate_fails_when_no_task_traces_to_f8_defect() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1" "F8" "silence"
    defect_files=("$f1")
    defect_failure_class=("F8")
    defect_evidence=("silence")
    tasks_json='[{"id":"1","title":"Implement something else","spec_references":[{"spec":"other.md"}],"files_touched":["a.py"]}]'

    _run_f8_gate
    assert_eq "fail" "$_f8_status" "gate status" || return 1
    assert_eq "1" "${#_f8_errors[@]}" "error count"
}

test_f8_gate_fails_when_f8_defect_gets_implementation_task() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1" "F8" "silence"
    defect_files=("$f1")
    defect_failure_class=("F8")
    defect_evidence=("silence")
    tasks_json="[{\"id\":\"1\",\"title\":\"Add refund idempotency check\",\"spec_references\":[{\"spec\":\"${f1}\"}],\"files_touched\":[\"refunds.py\"]}]"

    _run_f8_gate
    assert_eq "fail" "$_f8_status" "gate status" || return 1
    assert_output_contains "${_f8_errors[0]}" "implementation task" || return 1
}

test_f8_gate_passes_with_valid_escalation_task() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1" "F8" "silence"
    defect_files=("$f1")
    defect_failure_class=("F8")
    defect_evidence=("silence")
    tasks_json="[{\"id\":\"1\",\"title\":\"Escalate: refund idempotency policy undefined\",\"spec_references\":[{\"spec\":\"${f1}\"}],\"files_touched\":[]}]"

    _run_f8_gate
    assert_eq "pass" "$_f8_status" "gate status" || return 1
    assert_eq "1" "$_f8_checked_count" "checked count"
}

test_f8_gate_ignores_non_f8_defects() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1" "F2" "proof"
    defect_files=("$f1")
    defect_failure_class=("F2")
    defect_evidence=("proof")
    tasks_json="[{\"id\":\"1\",\"title\":\"Mask PAN in logs\",\"spec_references\":[{\"spec\":\"${f1}\"}],\"files_touched\":[\"logger.py\"]}]"

    _run_f8_gate
    assert_eq "pass" "$_f8_status" "gate status" || return 1
    assert_eq "0" "$_f8_checked_count" "checked count (no F8 defects present)"
}

test_f8_gate_warns_on_escalation_task_with_files_touched() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1" "F8" "silence"
    defect_files=("$f1")
    defect_failure_class=("F8")
    defect_evidence=("silence")
    tasks_json="[{\"id\":\"1\",\"title\":\"Escalate: refund idempotency policy undefined\",\"spec_references\":[{\"spec\":\"${f1}\"}],\"files_touched\":[\"refunds.py\"]}]"

    _run_f8_gate
    assert_eq "pass" "$_f8_status" "gate status (warning only, not a hard fail)" || return 1
    assert_eq "1" "${#_f8_warnings[@]}" "warning count"
}

# ── Tests: cmd_plan CLI-level input validation (defect-driven mode) ──

test_cmd_plan_defects_missing_feature_exits_config_error() {
    local f1="${TEST_DIR}/specs/defects/1.md"
    make_defect "$f1"
    local output rc=0
    output=$(cmd_plan --defects "$f1" 2>&1) || rc=$?
    assert_exit_code "$EXIT_CONFIG_ERROR" "$rc" || return 1
    assert_output_contains "$output" "feature" || return 1
}

test_cmd_plan_defects_missing_file_exits_config_error() {
    export GLOBAL_FEATURE="testfeat"
    local output rc=0
    output=$(cmd_plan --defects "${TEST_DIR}/specs/defects/does-not-exist.md" 2>&1) || rc=$?
    assert_exit_code "$EXIT_CONFIG_ERROR" "$rc" || return 1
    assert_output_contains "$output" "not found" || return 1
}

test_cmd_plan_defects_directory_exits_config_error() {
    export GLOBAL_FEATURE="testfeat"
    local output rc=0
    output=$(cmd_plan --defects "${TEST_DIR}/specs/defects" 2>&1) || rc=$?
    assert_exit_code "$EXIT_CONFIG_ERROR" "$rc" || return 1
    assert_output_contains "$output" "directory" || return 1
}

test_cmd_plan_defects_multiple_files_each_validated() {
    export GLOBAL_FEATURE="testfeat"
    local f1="${TEST_DIR}/specs/defects/1.md" f2="${TEST_DIR}/specs/defects/2.md"
    make_defect "$f1"
    make_defect "$f2"
    local output rc=0
    # Third file doesn't exist — proves cmd_plan validates every --defects
    # path, not just the first, before doing anything else.
    output=$(cmd_plan --defects "$f1" "$f2" "${TEST_DIR}/specs/defects/3.md" 2>&1) || rc=$?
    assert_exit_code "$EXIT_CONFIG_ERROR" "$rc" || return 1
    assert_output_contains "$output" "3.md" || return 1
}

# ── Run ─────────────────────────────────────────────────────────────

run_test test_resolve_defect_files_single_file
run_test test_resolve_defect_files_multiple_files
run_test test_resolve_defect_files_relative_to_project_root
run_test test_resolve_defect_files_missing_file_fails
run_test test_resolve_defect_files_directory_rejected
run_test test_resolve_defect_files_stops_at_first_bad_path

run_test test_extract_defect_metadata_handles_files_with_no_failure_class
run_test test_extract_defect_metadata_extracts_declared_fields
run_test test_extract_defect_metadata_mixed_declared_and_undeclared

run_test test_defect_index_matches_absolute_path
run_test test_defect_index_matches_relative_path
run_test test_defect_index_matches_basename
run_test test_defect_index_no_match_returns_failure

run_test test_attach_defect_metadata_propagates_fields
run_test test_attach_defect_metadata_noop_without_match
run_test test_attach_defect_metadata_skips_missing_evidence_fields
run_test test_attach_defect_metadata_is_set_e_safe_with_no_evidence

run_test test_f8_gate_fails_when_no_task_traces_to_f8_defect
run_test test_f8_gate_fails_when_f8_defect_gets_implementation_task
run_test test_f8_gate_passes_with_valid_escalation_task
run_test test_f8_gate_ignores_non_f8_defects
run_test test_f8_gate_warns_on_escalation_task_with_files_touched

run_test test_cmd_plan_defects_missing_feature_exits_config_error
run_test test_cmd_plan_defects_missing_file_exits_config_error
run_test test_cmd_plan_defects_directory_exits_config_error
run_test test_cmd_plan_defects_multiple_files_each_validated

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
