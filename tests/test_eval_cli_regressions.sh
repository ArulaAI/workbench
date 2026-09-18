#!/usr/bin/env bash
# test_eval_cli_regressions.sh — Regression tests for lib/cmd/eval.sh
#
# Covers four defects in the eval CLI layer:
#   1. _eval_verdict_line crashed under `set -u` on bash 3.2 and joined its
#      parts with a bare ';' instead of '; '.
#   2. Operational runtime failures exited 2, the same code as a real gate
#      failure, so CI could not tell "did not run" from "did not accept".
#   3. --json produced empty stdout on every error path.
#   4. --test-spec / --test-plan / --manual-results skipped path validation,
#      so a symlink or a traversal could read files outside the project, and
#      the RFC -> test-spec derivation replaced the leftmost '/tech/'.
#
# Usage: bash tests/test_eval_cli_regressions.sh
# Exit: 0 if all tests pass, 1 if any fail
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEED_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PASS=0
FAIL=0
TEST_DIR=""
OUTSIDE_DIR=""
SCENARIO_STATUS="pass"

setup() {
    TEST_DIR=$(mktemp -d)
    # A sibling of the project root: everything under it is off limits to eval.
    OUTSIDE_DIR=$(mktemp -d)
    export SPEED_PROJECT_ROOT="$TEST_DIR"
    export SPEED_DIR
    PROJECT_ROOT="$TEST_DIR"

    source "${SPEED_DIR}/lib/config.sh"
    source "${SPEED_DIR}/lib/log.sh"
    source "${SPEED_DIR}/lib/tasks.sh"
    source "${SPEED_DIR}/lib/features.sh"
    source "${SPEED_DIR}/lib/lock.sh"

    MP_ENABLED=""
    JSON_OUTPUT=false
    GLOBAL_FEATURE="books"
    feature_activate "books"
    feature_set_active "books"

    source "${SPEED_DIR}/lib/defects.sh"
    source "${SPEED_DIR}/lib/shared.sh"
    source "${SPEED_DIR}/lib/gates.sh"
    source "${SPEED_DIR}/lib/cmd/eval.sh"

    AGENT_FILE_PATH="${PROJECT_ROOT}/CLAUDE.md"
    export SPEED_AGENT_FILE="CLAUDE.md"
    printf '## Quality Gates\n- test: `python3 runner.py`\n' > "$AGENT_FILE_PATH"

    mkdir -p "${PROJECT_ROOT}/specs/tests"
    cat > "${PROJECT_ROOT}/specs/tests/books.md" <<'SPEC'
# Test Spec: Books

## Scenario Catalog

| ID | Scenario | Level | Expected outcome |
|----|----------|-------|------------------|
| AC-01 | Delete a book | integration | The book is removed |
SPEC
    printf '%s\n' "${PROJECT_ROOT}/specs/tests/books.md" > "${FEATURE_DIR}/test_spec_path"

    cat > "${TASKS_DIR}/1.json" <<'TASK'
{
  "id": "1",
  "status": "done",
  "files_touched": ["src/books.py"],
  "required_test_cases": ["AC-01"],
  "test_selectors": ["tests/test_books.py::test_delete"],
  "acceptance_criteria": [
    {"criterion": "A book can be deleted", "verify_by": "test", "scenario_ids": ["AC-01"]}
  ],
  "scenario_results": []
}
TASK

    _context_python() { command -v python3; }
    export SCENARIO_STATUS="pass"
    unset TOML_EVAL_TEST_COMMANDS SPEED_EVAL_TEST_COMMAND
    cat > "${PROJECT_ROOT}/runner.py" <<'PYRUNNER'
import json, os, sys
from pathlib import Path
with Path(".speed/commands.log").open("a") as stream:
    stream.write("python3 runner.py " + " ".join(sys.argv[1:]) + "\n")
status = os.environ["SCENARIO_STATUS"]
Path(os.environ["SPEED_EVAL_RESULT_FILE"]).write_text(json.dumps({
    "tests": [{"id": arg, "status": status} for arg in sys.argv[1:]]
}))
sys.exit(1 if status == "fail" else 0)
PYRUNNER
    printf '.speed/\n__pycache__/\n' > "${PROJECT_ROOT}/.gitignore"
    git -C "$PROJECT_ROOT" init -q
    printf '{"status":"completed"}\n' > "$STATE_FILE"
    : > "${PROJECT_ROOT}/.speed/commands.log"
}

teardown() {
    rm -rf "$TEST_DIR" "$OUTSIDE_DIR"
    unset SPEED_PROJECT_ROOT
}

assert_equals() {
    if [[ "$1" != "$2" ]]; then
        echo "expected '$1', got '$2'" >&2
        return 1
    fi
}

assert_not_equals() {
    if [[ "$1" == "$2" ]]; then
        echo "expected a value other than '$1'" >&2
        return 1
    fi
}

fail_with() {
    echo "$1" >&2
    return 1
}

run_test() {
    local name="$1"
    setup
    # A standalone subshell keeps errexit enabled inside each test. Putting
    # the function invocation in `if` or `||` silently disables it.
    local rc
    set +e
    (set -e; "$name")
    rc=$?
    set -e
    teardown
    if [[ "$rc" -eq 0 ]]; then
        echo "PASS ${name}"
        PASS=$((PASS + 1))
    else
        echo "FAIL ${name}"
        FAIL=$((FAIL + 1))
    fi
}

captured_commands() { cat "${PROJECT_ROOT}/.speed/commands.log"; }

# Commit fixture inputs before evaluating the integrated build.
eval_clean() {
    git -C "$PROJECT_ROOT" add -A
    git -C "$PROJECT_ROOT" -c user.name=Tests -c user.email=tests@example.invalid \
        -c core.hooksPath=/dev/null commit -qm fixture --allow-empty
    cmd_eval "$@"
}

drop_task_ownership() {
    local tmp
    tmp=$(mktemp)
    jq 'del(.required_test_cases) | .acceptance_criteria = []' "${TASKS_DIR}/1.json" > "$tmp" \
        && mv "$tmp" "${TASKS_DIR}/1.json"
}

add_spec_mapping() {
    {
        printf '\n## Execution and Evidence\n\n| Scenario | Selector | Command |\n|---|---|---|\n'
        printf '%s\n' "$@"
    } >> "${PROJECT_ROOT}/specs/tests/books.md"
}

add_task_two() {
    local status="${1:-done}"
    printf '| AC-02 | Fetch a missing book | integration | A not-found result |\n' \
        >> "${PROJECT_ROOT}/specs/tests/books.md"
    cat > "${TASKS_DIR}/2.json" <<TASK2
{
  "id": "2",
  "status": "${status}",
  "files_touched": ["src/books.py"],
  "required_test_cases": ["AC-02"],
  "test_selectors": ["tests/test_books.py::test_missing"],
  "acceptance_criteria": [],
  "scenario_results": []
}
TASK2
}

# ── Defect 1: the verdict line ────────────────────────────────────

# eval_report.py marks a report not accepted with every count at zero when no
# applicable result exists. The verdict line must survive that on bash 3.2.
test_verdict_line_survives_an_all_zero_summary() {
    local report="${PROJECT_ROOT}/zero-report.json"
    printf '%s\n' '{"accepted":false,"summary":{"fail":0,"partial":0,"blocked_upstream":0,"unverifiable":0}}' \
        > "$report"
    local line="" rc=0
    line=$(_eval_verdict_line "$report" 2>/dev/null) || rc=$?
    assert_equals "0" "$rc"
    [[ -n "$line" ]] || fail_with "verdict line was blank for an all-zero summary"
}

test_verdict_line_joins_parts_with_a_semicolon_and_a_space() {
    local report="${PROJECT_ROOT}/mixed-report.json"
    printf '%s\n' '{"accepted":false,"summary":{"fail":2,"partial":0,"blocked_upstream":0,"unverifiable":1}}' \
        > "$report"
    assert_equals "2 failed; 1 never examined" "$(_eval_verdict_line "$report")"
}

test_verdict_line_reports_a_single_part_without_a_separator() {
    local report="${PROJECT_ROOT}/single-report.json"
    printf '%s\n' '{"accepted":false,"summary":{"fail":0,"partial":1,"blocked_upstream":0,"unverifiable":0}}' \
        > "$report"
    assert_equals "1 failed" "$(_eval_verdict_line "$report")"
}

# ── Defect 2: "could not run" is not "did not accept" ─────────────

# eval_runtime.py exits 2 on RuntimeError, which includes the operational
# "Evaluation requires done tasks". EXIT_GATE_FAILURE is also 2.
test_unrunnable_evaluation_is_not_reported_as_a_gate_failure() {
    add_task_two "pending"
    local rc=0
    eval_clean --strict --no-defects --skip-judge >/dev/null 2>&1 || rc=$?
    assert_not_equals "$EXIT_GATE_FAILURE" "$rc"
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
    assert_equals "" "$(captured_commands)"
}

# A genuine acceptance failure keeps EXIT_GATE_FAILURE, so the two stay apart.
test_rejected_acceptance_still_exits_with_the_gate_code() {
    SCENARIO_STATUS="fail"
    local rc=0
    eval_clean --strict --no-defects --skip-judge >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_GATE_FAILURE" "$rc"
}

# ── Defect 3: --json owes stdout one object on every path ─────────

test_json_missing_spec_emits_one_valid_object() {
    rm -f "${FEATURE_DIR}/test_spec_path"
    rm -f "${PROJECT_ROOT}/specs/tests/books.md"
    local out="" rc=0
    out=$( JSON_OUTPUT=true; eval_clean --skip-judge 2>/dev/null ) || rc=$?
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
    printf '%s' "$out" | jq -e . >/dev/null 2>&1 \
        || fail_with "stdout was not valid JSON: '${out}'"
    assert_equals "false" "$(printf '%s' "$out" | jq -r '.accepted')"
    [[ -n "$(printf '%s' "$out" | jq -r '.error // empty')" ]] \
        || fail_with "error object carried no reason: '${out}'"
}

test_json_bad_option_emits_one_valid_object() {
    local out="" rc=0
    out=$( JSON_OUTPUT=true; cmd_eval --not-an-option 2>/dev/null ) || rc=$?
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
    printf '%s' "$out" | jq -e . >/dev/null 2>&1 \
        || fail_with "stdout was not valid JSON: '${out}'"
    assert_equals "false" "$(printf '%s' "$out" | jq -r '.accepted')"
}

test_json_lock_conflict_emits_one_valid_object() {
    mkdir -p "$SPEED_LOCK"
    printf '%s\n' "$$" > "${SPEED_LOCK}/pid"
    printf 'run\n' > "${SPEED_LOCK}/command"
    printf 'now\n' > "${SPEED_LOCK}/acquired_at"
    local out="" rc=0
    out=$( JSON_OUTPUT=true; eval_clean --skip-judge 2>/dev/null ) || rc=$?
    rm -rf "$SPEED_LOCK"
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
    printf '%s' "$out" | jq -e . >/dev/null 2>&1 \
        || fail_with "stdout was not valid JSON: '${out}'"
    assert_equals "false" "$(printf '%s' "$out" | jq -r '.accepted')"
}

# Guard: the success path must keep emitting the report itself.
test_json_success_path_still_emits_the_report() {
    local out=""
    out=$( JSON_OUTPUT=true; eval_clean --strict --no-defects --skip-judge 2>/dev/null )
    assert_equals "true" "$(printf '%s' "$out" | jq -r '.accepted')"
    assert_equals "null" "$(printf '%s' "$out" | jq -r '.error // "null"')"
}

# ── Defect 4: user-supplied paths must be validated ───────────────

# A committed symlink needs no '../' to read a file outside the project, and
# the test spec is pasted verbatim into the evaluator prompt.
test_symlinked_test_spec_outside_the_project_is_rejected() {
    cp "${PROJECT_ROOT}/specs/tests/books.md" "${OUTSIDE_DIR}/books.md"
    rm -f "${PROJECT_ROOT}/specs/tests/books.md"
    ln -s "${OUTSIDE_DIR}/books.md" "${PROJECT_ROOT}/specs/tests/books.md"

    local rc=0
    eval_clean --strict --no-defects --skip-judge >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
    [[ ! -f "${FEATURE_DIR}/eval/report.json" ]] \
        || fail_with "evaluation ran against a spec that resolves outside the project"
}

test_test_spec_override_outside_the_project_is_rejected() {
    cp "${PROJECT_ROOT}/specs/tests/books.md" "${OUTSIDE_DIR}/books.md"
    local rc=0
    eval_clean --strict --no-defects --skip-judge --test-spec "${OUTSIDE_DIR}/books.md" \
        >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
    [[ ! -f "${FEATURE_DIR}/eval/report.json" ]] \
        || fail_with "evaluation ran against a spec outside the project"
}

test_symlinked_test_plan_outside_the_project_is_rejected() {
    drop_task_ownership
    add_spec_mapping '| AC-01 | tests/test_books.py::test_delete | |'
    printf '%s\n' '{"test_cases": [{"scenario_id": "AC-01", "selector": "tests/from_outside.py"}]}' \
        > "${OUTSIDE_DIR}/plan.json"
    ln -s "${OUTSIDE_DIR}/plan.json" "${PROJECT_ROOT}/plan.json"

    local rc=0
    eval_clean --strict --no-defects --skip-judge --test-plan plan.json >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
    assert_equals "" "$(captured_commands)"
}

test_manual_results_traversing_out_of_the_project_is_rejected() {
    printf '%s\n' '{"results": []}' > "${OUTSIDE_DIR}/manual.json"
    local relative="../${OUTSIDE_DIR##*/}/manual.json"

    local rc=0
    eval_clean --strict --no-defects --skip-judge --manual-results "$relative" \
        >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
    [[ ! -f "${FEATURE_DIR}/eval/report.json" ]] \
        || fail_with "evaluation ran with manual evidence from outside the project"
}

# An in-project test plan must keep working.
test_in_project_test_plan_override_is_accepted() {
    drop_task_ownership
    add_spec_mapping '| AC-01 | tests/from_spec.py | |'
    printf '%s\n' '{"test_cases": [{"scenario_id": "AC-01", "selector": "tests/from_override.py"}]}' \
        > "${PROJECT_ROOT}/override.json"

    eval_clean --strict --no-defects --skip-judge --test-plan override.json >/dev/null
    assert_equals "python3 runner.py tests/from_override.py" "$(captured_commands | head -1)"
}

# The derivation must rewrite the last '/tech/', not the leftmost one, so a
# checkout under a directory named 'tech' still finds its spec.
test_rfc_with_an_earlier_tech_segment_derives_the_right_spec() {
    rm -f "${FEATURE_DIR}/test_spec_path"
    mkdir -p "${PROJECT_ROOT}/tech/specs/tech" "${PROJECT_ROOT}/tech/specs/tests"
    printf '# RFC: Books\n' > "${PROJECT_ROOT}/tech/specs/tech/books.md"
    mv "${PROJECT_ROOT}/specs/tests/books.md" "${PROJECT_ROOT}/tech/specs/tests/books.md"
    printf '%s\n' "${PROJECT_ROOT}/tech/specs/tech/books.md" > "${FEATURE_DIR}/spec_path"

    assert_equals "${PROJECT_ROOT}/tech/specs/tests/books.md" "$(_eval_test_spec_path "")"
    eval_clean --strict --no-defects --skip-judge >/dev/null
    assert_equals "true" "$(jq -r '.accepted' "${FEATURE_DIR}/eval/report.json")"
}

test_default_spec_without_plan_metadata_runs() {
    rm -f "${FEATURE_DIR}/test_spec_path"
    eval_clean --strict --no-defects --skip-judge >/dev/null
    assert_equals "true" "$(jq -r '.accepted' "${FEATURE_DIR}/eval/report.json")"
}

test_absent_derived_spec_falls_back_but_explicit_missing_path_does_not() {
    rm -f "${FEATURE_DIR}/test_spec_path"
    printf '%s\n' "${PROJECT_ROOT}/specs/tech/old-name.md" > "${FEATURE_DIR}/spec_path"
    assert_equals "${PROJECT_ROOT}/specs/tests/books.md" "$(_eval_test_spec_path "")"
    local rc=0
    _eval_test_spec_path missing.md >/dev/null || rc=$?
    assert_equals "1" "$rc"
}

test_json_feature_claimed_by_another_actor_emits_config_error() {
    MP_ENABLED=true
    ownership_check() { OWNERSHIP_OWNER="another-actor"; return 1; }
    local out="" rc=0
    out=$( JSON_OUTPUT=true; cmd_eval --skip-judge 2>/dev/null ) || rc=$?
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
    assert_equals "1" "$(printf '%s' "$out" | jq -s length)"
    assert_equals "false" "$(printf '%s' "$out" | jq -r '.accepted')"
    [[ -n "$(printf '%s' "$out" | jq -r '.error // empty')" ]]
    assert_equals "" "$(captured_commands)"
}

test_summary_shortens_only_commit_hashes() {
    local report="${PROJECT_ROOT}/display-report.json" out
    printf '%s\n' '{"commit":null,"results":[]}' > "$report"
    out=$(_eval_print_summary "$report" "specs/tests/books.md" "$FEATURE_DIR")
    [[ "$out" == *"@ uncommitted-working-tree "* ]]
    printf '%s\n' '{"commit":"034505bf724f3a52144ed0f10b068200467d76fd","results":[]}' > "$report"
    out=$(_eval_print_summary "$report" "specs/tests/books.md" "$FEATURE_DIR")
    [[ "$out" == *"@ 034505b "* ]]
}

run_test test_default_spec_without_plan_metadata_runs
run_test test_absent_derived_spec_falls_back_but_explicit_missing_path_does_not
run_test test_json_feature_claimed_by_another_actor_emits_config_error
run_test test_summary_shortens_only_commit_hashes

run_test test_verdict_line_survives_an_all_zero_summary
run_test test_verdict_line_joins_parts_with_a_semicolon_and_a_space
run_test test_verdict_line_reports_a_single_part_without_a_separator
run_test test_unrunnable_evaluation_is_not_reported_as_a_gate_failure
run_test test_rejected_acceptance_still_exits_with_the_gate_code
run_test test_json_missing_spec_emits_one_valid_object
run_test test_json_bad_option_emits_one_valid_object
run_test test_json_lock_conflict_emits_one_valid_object
run_test test_json_success_path_still_emits_the_report
run_test test_symlinked_test_spec_outside_the_project_is_rejected
run_test test_test_spec_override_outside_the_project_is_rejected
run_test test_symlinked_test_plan_outside_the_project_is_rejected
run_test test_manual_results_traversing_out_of_the_project_is_rejected
run_test test_in_project_test_plan_override_is_accepted
run_test test_rfc_with_an_earlier_tech_segment_derives_the_right_spec

echo "${PASS} passed, ${FAIL} failed"
[[ "$FAIL" -eq 0 ]]
