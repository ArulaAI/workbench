#!/usr/bin/env bash
# test_review.sh — Review handling for persisted tasks with missing branches

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
PASS=0
FAIL=0
TEST_DIR=""

setup() {
    TEST_DIR=$(mktemp -d)
    TASKS_DIR="${TEST_DIR}/tasks"
    mkdir -p "$TASKS_DIR"

    EXIT_CONFIG_ERROR=3
    GLOBAL_FEATURE="payments"
    FEATURE_DIR="$TEST_DIR/feature"
    LOGS_DIR="$TEST_DIR/logs"
    DIFF_HEAD_LINES=500
    AGENTS_DIR="$TEST_DIR/agents"
    MODEL_SUPPORT="sonnet"
    AGENT_TOOLS_READONLY="Read"
    mkdir -p "$LOGS_DIR" "$AGENTS_DIR"
    COLOR_STEP=""
    RESET=""
    BOLD=""

    git -C "$TEST_DIR" init -q
    git -C "$TEST_DIR" config user.email test@example.com
    git -C "$TEST_DIR" config user.name "Review Test"
    touch "$TEST_DIR/README.md"
    git -C "$TEST_DIR" add README.md
    git -C "$TEST_DIR" commit -q -m baseline
    git -C "$TEST_DIR" branch -M main
    git -C "$TEST_DIR" branch missing-branch
    git -C "$TEST_DIR" branch valid-branch
    git -C "$TEST_DIR" branch -D missing-branch >/dev/null

    cat > "${TASKS_DIR}/1.json" <<'EOF'
{
  "id": "1",
  "title": "Persisted payment task",
  "acceptance_criteria": "The payment workflow remains valid.",
  "status": "done",
    "branch": "missing-branch",
  "review_verdict": null
}
EOF
        cat > "${TASKS_DIR}/2.json" <<'EOF'
{
    "id": "2",
    "title": "Valid persisted payment task",
    "acceptance_criteria": "The valid task is still reviewed.",
    "status": "done",
    "branch": "valid-branch",
    "review_verdict": null
}
EOF

    _require_feature() { :; }
    log_header() { :; }
    log_info() { :; }
    log_step() { :; }
    log_warn() { :; }
    log_success() { :; }
    log_error() { echo "ERROR: $*" >&2; }
    task_list_by_status() { printf "1\n2\n"; }
    task_get() { cat "${TASKS_DIR}/$1.json"; }
    PROJECT_ROOT="$TEST_DIR"
    _git() { git -C "$PROJECT_ROOT" "$@"; }
    git_main_branch() { echo "main"; }
    git_branch_exists() { git -C "$PROJECT_ROOT" rev-parse --verify "$1" >/dev/null 2>&1; }

    source "${LIB_DIR}/cmd/review.sh"

    _load_relevant_specs() { :; }
    _get_spec_path() { echo ""; }
    context_build_layer2_task() { :; }
    context_assemble_reviewer() { echo "review prompt"; }
    _estimate_tokens() { echo "1"; }
    _pace_api_call() { :; }
    _call_with_retry() { echo '{"verdict":"approve","issues":[]}'; }
    parse_agent_json() { echo "$1"; }
    _require_json() { return 0; }
    _track_tokens() { :; }
    task_set_reviewed() { echo "$1" > "$TEST_DIR/reviewed-task"; }
    _log_gate_skip() { :; }
    SKIP_GUARDIAN=true
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

test_missing_branch_is_configuration_error() {
    local before after output rc=0
    before=$(cat "${TASKS_DIR}/1.json")
    output=$(cmd_review 2>&1) || rc=$?
    after=$(cat "${TASKS_DIR}/1.json")

    [[ "$rc" -eq "$EXIT_CONFIG_ERROR" ]] || {
        echo "    ASSERT: expected exit ${EXIT_CONFIG_ERROR}, got ${rc}" >&2
        return 1
    }
    echo "$output" | grep -qF "Task 1 cannot be reviewed" || {
        echo "    ASSERT: missing-branch error was not reported" >&2
        return 1
    }
    ! echo "$output" | grep -qF "skipping" || {
        echo "    ASSERT: missing branch was silently treated as skippable" >&2
        return 1
    }
    [[ "$before" == "$after" ]] || {
        echo "    ASSERT: persisted task state was rewritten" >&2
        return 1
    }
    [[ "$(cat "$TEST_DIR/reviewed-task")" == "2" ]] || {
        echo "    ASSERT: valid task was not processed" >&2
        return 1
    }
}

run_test test_missing_branch_is_configuration_error

printf "\nReview tests: %d passed, %d failed\n" "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]