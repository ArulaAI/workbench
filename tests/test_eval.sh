#!/usr/bin/env bash
# test_eval.sh — Tests for lib/cmd/eval.sh (speed eval)
#
# Usage: bash tests/test_eval.sh
# Exit: 0 if all tests pass, 1 if any fail
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEED_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PASS=0
FAIL=0
TEST_DIR=""
SCENARIO_STATUS="pass"
CAPTURED_COMMANDS=""

setup() {
    TEST_DIR=$(mktemp -d)
    export SPEED_PROJECT_ROOT="$TEST_DIR"
    export SPEED_DIR
    PROJECT_ROOT="$TEST_DIR"

    source "${SPEED_DIR}/lib/config.sh"
    source "${SPEED_DIR}/lib/log.sh"
    source "${SPEED_DIR}/lib/tasks.sh"
    source "${SPEED_DIR}/lib/features.sh"
    source "${SPEED_DIR}/lib/lock.sh"

    MP_ENABLED=""
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
    cat > "${PROJECT_ROOT}/specs/tests/books.md" <<'EOF'
# Test Spec: Books

## Scenario Catalog

| ID | Scenario | Level | Expected outcome |
|----|----------|-------|------------------|
| AC-01 | Delete a book | integration | The book is removed |
EOF
    printf '%s\n' "${PROJECT_ROOT}/specs/tests/books.md" > "${FEATURE_DIR}/test_spec_path"

    cat > "${TASKS_DIR}/1.json" <<'EOF'
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
EOF

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
    rm -rf "$TEST_DIR"
    unset SPEED_PROJECT_ROOT
}

assert_equals() {
    if [[ "$1" != "$2" ]]; then
        echo "expected '$1', got '$2'" >&2
        return 1
    fi
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

# Commit fixture inputs before evaluating the integrated build. Evaluation
# output and task runtime state are ignored by the fixture repository.
eval_clean() {
    git -C "$PROJECT_ROOT" add -A
    git -C "$PROJECT_ROOT" -c user.name=Tests -c user.email=tests@example.invalid \
        -c core.hooksPath=/dev/null commit -qm fixture --allow-empty
    cmd_eval "$@"
}

# Second task owning AC-02, plus the matching catalog row.
add_task_two() {
    local status="${1:-done}"
    printf '| AC-02 | Fetch a missing book | integration | A not-found result |\n' \
        >> "${PROJECT_ROOT}/specs/tests/books.md"
    cat > "${TASKS_DIR}/2.json" <<EOF
{
  "id": "2",
  "status": "${status}",
  "files_touched": ["src/books.py"],
  "required_test_cases": ["AC-02"],
  "test_selectors": ["tests/test_books.py::test_missing"],
  "acceptance_criteria": [],
  "scenario_results": []
}
EOF
}

drop_task_ownership() {
    local tmp
    tmp=$(mktemp)
    jq 'del(.required_test_cases) | .acceptance_criteria = []' "${TASKS_DIR}/1.json" > "$tmp" \
        && mv "$tmp" "${TASKS_DIR}/1.json"
}

test_accepts_when_task_declared_scenarios_pass() {
    eval_clean --strict --no-defects --skip-judge >/dev/null
    assert_equals "python3 runner.py tests/test_books.py::test_delete" "$(captured_commands | head -1)"
    assert_equals "pass" "$(jq -r '.results[0].status' "${FEATURE_DIR}/eval/scenario-results.json")"
    assert_equals "true" "$(jq -r '.accepted' "${FEATURE_DIR}/eval/report.json")"
    assert_equals "accepted" "$(jq -r '.status' "$STATE_FILE")"
    assert_equals "false" "$(jq 'has("integration_failure")' "$STATE_FILE")"
}

test_rejects_and_files_defect_on_failure() {
    SCENARIO_STATUS="fail"
    local rc=0
    eval_clean --strict --skip-judge >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_GATE_FAILURE" "$rc"
    assert_equals "false" "$(jq -r '.accepted' "${FEATURE_DIR}/eval/report.json")"
    assert_equals "integrated_not_accepted" "$(jq -r '.status' "$STATE_FILE")"
    [[ -f "${PROJECT_ROOT}/specs/defects/eval-books-ac-01.md" ]]
    [[ -f "${DEFECTS_DIR}/eval-books-ac-01/state.json" ]]
}

test_unverifiable_residue_blocks_without_filing_defect() {
    local tmp
    tmp=$(mktemp)
    jq '.acceptance_criteria += [{
        criterion: "The workflow is easy to understand",
        verify_by: "manual",
        scenario_ids: []
    }]' "${TASKS_DIR}/1.json" > "$tmp" && mv "$tmp" "${TASKS_DIR}/1.json"

    local rc=0
    eval_clean --strict --skip-judge >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_GATE_FAILURE" "$rc"
    assert_equals "1" "$(jq '.summary.unverifiable' "${FEATURE_DIR}/eval/report.json")"
    assert_equals "integrated_not_accepted" "$(jq -r '.status' "$STATE_FILE")"
    [[ ! -d "$DEFECTS_DIR" ]] || [[ -z "$(find "$DEFECTS_DIR" -mindepth 1 -print -quit)" ]]
}

test_task_without_selectors_fails_its_scenarios() {
    local tmp
    tmp=$(mktemp)
    jq '.test_selectors = []' "${TASKS_DIR}/1.json" > "$tmp" && mv "$tmp" "${TASKS_DIR}/1.json"

    local rc=0
    eval_clean --strict --no-defects --skip-judge >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_GATE_FAILURE" "$rc"
    assert_equals "" "$(captured_commands)"
    assert_equals "unverifiable" "$(jq -r '.results[0].status' "${FEATURE_DIR}/eval/scenario-results.json")"
}

test_option_selector_is_rejected() {
    local tmp
    tmp=$(mktemp)
    jq '.test_selectors = ["--help"]' "${TASKS_DIR}/1.json" > "$tmp" \
        && mv "$tmp" "${TASKS_DIR}/1.json"

    local rc=0
    eval_clean --strict --no-defects --skip-judge >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_GATE_FAILURE" "$rc"
    assert_equals "" "$(captured_commands)"
}

# Append an Execution and Evidence mapping table to the test spec.
add_spec_mapping() {
    {
        printf '\n## Execution and Evidence\n\n| Scenario | Selector | Command |\n|---|---|---|\n'
        printf '%s\n' "$@"
    } >> "${PROJECT_ROOT}/specs/tests/books.md"
}

test_spec_mapping_table_is_executed() {
    drop_task_ownership
    add_spec_mapping '| AC-01 | tests/test_books.py::test_delete | |'

    eval_clean --strict --no-defects --skip-judge >/dev/null
    assert_equals "python3 runner.py tests/test_books.py::test_delete" "$(captured_commands | head -1)"
    assert_equals "pass" "$(jq -r '.results[0].status' "${FEATURE_DIR}/eval/scenario-results.json")"
    assert_equals "true" "$(jq -r '.accepted' "${FEATURE_DIR}/eval/report.json")"
    assert_equals "1" "$(jq '.test_cases | length' "${FEATURE_DIR}/eval/test-plan.json")"
}

test_test_plan_override_wins_over_the_spec_table() {
    drop_task_ownership
    add_spec_mapping '| AC-01 | tests/from_spec.py | |'
    printf '%s\n' '{"test_cases": [{"scenario_id": "AC-01", "selector": "tests/from_override.py"}]}' \
        > "${TEST_DIR}/override.json"

    eval_clean --strict --no-defects --skip-judge --test-plan "${TEST_DIR}/override.json" >/dev/null
    assert_equals "python3 runner.py tests/from_override.py" "$(captured_commands | head -1)"
}

test_missing_test_plan_override_is_a_config_error() {
    local rc=0
    eval_clean --skip-judge --test-plan "${TEST_DIR}/missing.json" >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
}

test_spec_mapping_rejects_unconfigured_commands() {
    drop_task_ownership
    add_spec_mapping '| AC-01 | tests/test_books.py | rm -rf / |'

    local rc=0
    eval_clean --strict --no-defects --skip-judge >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_GATE_FAILURE" "$rc"
    assert_equals "" "$(captured_commands)"
    assert_equals "unverifiable" "$(jq -r '.results[0].status' "${FEATURE_DIR}/eval/scenario-results.json")"
}

test_empty_selector_cell_leaves_the_scenario_unexamined() {
    drop_task_ownership
    add_spec_mapping '| AC-01 | | |'

    local rc=0
    eval_clean --strict --no-defects --skip-judge >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_GATE_FAILURE" "$rc"
    assert_equals "" "$(captured_commands)"
    assert_equals "unverifiable" "$(jq -r '.results[] | select(.id == "AC-01") | .status' "${FEATURE_DIR}/eval/report.json")"
}

test_toml_test_command_is_preferred_over_the_agent_file() {
    printf '[eval]\ntest_command = "python3 runner.py --configured"\n' > "${PROJECT_ROOT}/speed.toml"
    eval_clean --strict --no-defects --skip-judge >/dev/null
    assert_equals "python3 runner.py --configured tests/test_books.py::test_delete" "$(captured_commands | head -1)"
}

test_unmapped_scenario_is_unverifiable_without_defect() {
    drop_task_ownership

    local rc=0
    eval_clean --strict --skip-judge >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_GATE_FAILURE" "$rc"
    assert_equals "0" "$(jq '.summary.fail' "${FEATURE_DIR}/eval/report.json")"
    assert_equals "unverifiable" "$(jq -r '.results[] | select(.id == "AC-01") | .status' "${FEATURE_DIR}/eval/report.json")"
    assert_equals "integrated_not_accepted" "$(jq -r '.status' "$STATE_FILE")"
    [[ ! -d "$DEFECTS_DIR" ]] || [[ -z "$(find "$DEFECTS_DIR" -mindepth 1 -print -quit)" ]]
}

test_test_spec_is_derived_from_rfc_path() {
    rm -f "${FEATURE_DIR}/test_spec_path"
    mkdir -p "${PROJECT_ROOT}/specs/tech"
    printf '# RFC: Books\n' > "${PROJECT_ROOT}/specs/tech/books.md"
    printf '%s\n' "${PROJECT_ROOT}/specs/tech/books.md" > "${FEATURE_DIR}/spec_path"

    eval_clean --strict --no-defects --skip-judge >/dev/null
    assert_equals "true" "$(jq -r '.accepted' "${FEATURE_DIR}/eval/report.json")"
    # The report stores a resolved path; compare the spec-relative suffix so
    # macOS /var -> /private/var symlinks do not matter.
    assert_equals "specs/tests/books.md" "$(jq -r '.test_spec' "${FEATURE_DIR}/eval/report.json" | sed 's|.*/specs/|specs/|')"
}

test_missing_test_spec_is_a_config_error() {
    rm -f "${FEATURE_DIR}/test_spec_path"
    rm -f "${PROJECT_ROOT}/specs/tests/books.md"
    local rc=0
    eval_clean --skip-judge >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
}

test_feature_eval_requires_all_tasks_done() {
    add_task_two "pending"
    local rc=0
    eval_clean --skip-judge >/dev/null 2>&1 || rc=$?
    # Evaluation never ran, so this is not a gate failure. Sharing code 2 with
    # a real rejection told CI that acceptance had failed.
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
    assert_equals "" "$(captured_commands)"
}

test_task_scoped_eval_reports_only_that_task() {
    add_task_two
    eval_clean --task-id 1 --strict --no-defects --skip-judge >/dev/null

    local report="${FEATURE_DIR}/eval/task-1/report.json"
    assert_equals "1" "$(jq -r '.task_id' "$report")"
    assert_equals "AC-01" "$(jq -r '[.results[] | select(.kind == "scenario") | .id] | join(",")' "$report")"
    assert_equals "true" "$(jq -r '.accepted' "$report")"
    assert_equals "1" "$(printf '%s' "$(captured_commands)" | grep -c 'test_delete')"
    assert_equals "0" "$(printf '%s' "$(captured_commands)" | grep -c 'test_missing' || true)"
    # Feature state is decided by the full run only.
    assert_equals "false" "$(jq 'has("evaluation")' "$STATE_FILE")"
    [[ ! -f "${FEATURE_DIR}/eval/report.json" ]]
}

test_task_scoped_eval_ignores_other_tasks_state() {
    add_task_two "pending"
    eval_clean --task-id 1 --strict --no-defects --skip-judge >/dev/null
    assert_equals "true" "$(jq -r '.accepted' "${FEATURE_DIR}/eval/task-1/report.json")"
}

test_task_scoped_eval_requires_existing_task() {
    local rc=0
    eval_clean --task-id 9 --skip-judge >/dev/null 2>&1 || rc=$?
    assert_equals "$EXIT_CONFIG_ERROR" "$rc"
}

run_test test_accepts_when_task_declared_scenarios_pass
run_test test_rejects_and_files_defect_on_failure
run_test test_unverifiable_residue_blocks_without_filing_defect
run_test test_task_without_selectors_fails_its_scenarios
run_test test_option_selector_is_rejected
run_test test_spec_mapping_table_is_executed
run_test test_test_plan_override_wins_over_the_spec_table
run_test test_missing_test_plan_override_is_a_config_error
run_test test_spec_mapping_rejects_unconfigured_commands
run_test test_empty_selector_cell_leaves_the_scenario_unexamined
run_test test_toml_test_command_is_preferred_over_the_agent_file
run_test test_unmapped_scenario_is_unverifiable_without_defect
run_test test_test_spec_is_derived_from_rfc_path
run_test test_missing_test_spec_is_a_config_error
run_test test_feature_eval_requires_all_tasks_done
run_test test_task_scoped_eval_reports_only_that_task
run_test test_task_scoped_eval_ignores_other_tasks_state
run_test test_task_scoped_eval_requires_existing_task

echo "${PASS} passed, ${FAIL} failed"
[[ "$FAIL" -eq 0 ]]
