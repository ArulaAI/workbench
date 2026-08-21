#!/usr/bin/env bash
# test_tasks.sh — Tests for lib/tasks.sh task CRUD, state transitions, dependencies, topo sort
#
# Usage: bash tests/test_tasks.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)

    # Color/symbol stubs
    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" COLOR_STEP="" COLOR_ACCENT=""
    BOLD="" RESET="" SYM_CHECK="" SYM_CROSS="" SYM_WARN="" SYM_ARROW="" SYM_PENDING="" SYM_RUNNING=""
    VERBOSITY=0

    # Logging stubs
    log_error()   { :; }
    log_warn()    { :; }
    log_step()    { :; }
    log_success() { :; }

    # Config stubs
    export TASKS_DIR="${TEST_DIR}/tasks"
    export BRANCH_PREFIX="speed"
    export MODEL_SUPPORT="sonnet"
    mkdir -p "$TASKS_DIR"

    # Source tasks.sh
    source "${LIB_DIR}/tasks.sh"
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

assert_equals() {
    local expected="$1" actual="$2" context="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected '${expected}', got '${actual}'${context:+ (${context})}" >&2
        return 1
    fi
}

assert_not_empty() {
    local value="$1" context="${3:-}"
    if [[ -z "$value" ]]; then
        echo "    ASSERT: value is empty${context:+ (${context})}" >&2
        return 1
    fi
}

assert_json_field() {
    local json="$1" field="$2" expected="$3" context="${4:-}"
    local actual
    actual=$(echo "$json" | jq -r "$field")
    if [[ "$actual" != "$expected" ]]; then
        echo "    ASSERT: ${field} expected '${expected}', got '${actual}'${context:+ (${context})}" >&2
        return 1
    fi
}

# ── task_create tests ─────────────────────────────────────────────────────────

test_create_basic() {
    local result
    result=$(task_create "1" "Build Login Page" "Implement login" "User can log in" '[]')

    # Should return the file path
    [[ -f "$result" ]] || { echo "    ASSERT: task file not created at ${result}" >&2; return 1; }

    # Verify JSON structure
    local json
    json=$(cat "$result")

    assert_json_field "$json" ".id" "1" "id"
    assert_json_field "$json" ".title" "Build Login Page" "title"
    assert_json_field "$json" ".description" "Implement login" "description"
    assert_json_field "$json" ".acceptance_criteria" "User can log in" "acceptance_criteria"
    assert_json_field "$json" ".status" "pending" "status"
    assert_json_field "$json" ".agent_model" "sonnet" "default model"
    assert_json_field "$json" ".started_at" "null" "started_at"
    assert_json_field "$json" ".completed_at" "null" "completed_at"
    assert_json_field "$json" ".agent_pid" "null" "agent_pid"
    assert_json_field "$json" ".error" "null" "error"
    assert_json_field "$json" ".review_feedback" "null" "review_feedback"

    # Branch should contain slug
    local branch
    branch=$(echo "$json" | jq -r '.branch')
    [[ "$branch" == "speed/task-1-build-login-page" ]] || { echo "    ASSERT: branch '${branch}' does not match expected" >&2; return 1; }

    # created_at should be a timestamp
    local created
    created=$(echo "$json" | jq -r '.created_at')
    [[ "$created" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || \
        { echo "    ASSERT: created_at '${created}' is not a valid timestamp" >&2; return 1; }
}

test_create_with_dependencies() {
    local result
    result=$(task_create "3" "Wire Up API" "Connect frontend" "API works" '["1","2"]')

    local json
    json=$(cat "$result")

    local dep_count
    dep_count=$(echo "$json" | jq '.depends_on | length')
    assert_equals "2" "$dep_count" "depends_on count"

    local dep1 dep2
    dep1=$(echo "$json" | jq -r '.depends_on[0]')
    dep2=$(echo "$json" | jq -r '.depends_on[1]')
    assert_equals "1" "$dep1" "first dependency"
    assert_equals "2" "$dep2" "second dependency"
}

test_create_custom_model() {
    local result
    result=$(task_create "1" "Hard Task" "Complex work" "It works" '[]' "opus")

    local json
    json=$(cat "$result")
    assert_json_field "$json" ".agent_model" "opus" "custom model"
}

test_create_slug_special_chars() {
    local result
    result=$(task_create "1" "Fix Bug #42: API Error!!!" "Fix it" "No errors" '[]')

    local json
    json=$(cat "$result")
    local branch
    branch=$(echo "$json" | jq -r '.branch')

    # Slug should strip special chars, collapse hyphens
    [[ "$branch" =~ ^speed/task-1-fix-bug-42-api-error$ ]] || \
        { echo "    ASSERT: branch slug '${branch}' has unexpected format" >&2; return 1; }
}

# ── task_get tests ────────────────────────────────────────────────────────────

test_get_existing() {
    task_create "1" "Test Task" "Description" "Criteria" '[]' > /dev/null

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".id" "1" "get returns correct id"
    assert_json_field "$json" ".title" "Test Task" "get returns correct title"
}

test_get_nonexistent() {
    local rc=0
    task_get "999" > /dev/null 2>&1 || rc=$?
    assert_exit_code "1" "$rc" "get nonexistent task should fail"
}

# ── task_update tests ─────────────────────────────────────────────────────────

test_update_string_field() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null

    task_update "1" "status" "running"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "running" "updated status"
}

test_update_nonexistent() {
    local rc=0
    task_update "999" "status" "running" 2>/dev/null || rc=$?
    assert_exit_code "1" "$rc" "update nonexistent task should fail"
}

# ── task_update_raw tests ─────────────────────────────────────────────────────

test_update_raw_number() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null

    task_update_raw "1" "agent_pid" "12345"

    local json
    json=$(task_get "1")
    local pid
    pid=$(echo "$json" | jq '.agent_pid')
    assert_equals "12345" "$pid" "raw update with number"
}

test_update_raw_null() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_update_raw "1" "agent_pid" "12345"
    task_update_raw "1" "agent_pid" "null"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".agent_pid" "null" "raw update to null"
}

test_update_raw_nonexistent() {
    local rc=0
    task_update_raw "999" "status" '"running"' 2>/dev/null || rc=$?
    assert_exit_code "1" "$rc" "update_raw nonexistent task should fail"
}

# ── task_set_running tests ────────────────────────────────────────────────────

test_set_running() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null

    task_set_running "1" 42

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "running" "status after set_running"
    local pid
    pid=$(echo "$json" | jq '.agent_pid')
    assert_equals "42" "$pid" "agent_pid after set_running"

    # started_at should be set
    local started
    started=$(echo "$json" | jq -r '.started_at')
    [[ "$started" != "null" ]] || { echo "    ASSERT: started_at should not be null" >&2; return 1; }
}

test_set_running_nonexistent() {
    local rc=0
    task_set_running "999" 42 2>/dev/null || rc=$?
    assert_exit_code "1" "$rc" "set_running nonexistent task should fail"
}

# ── task_set_done tests ───────────────────────────────────────────────────────

test_set_done() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42

    task_set_done "1"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "done" "status after set_done"
    assert_json_field "$json" ".agent_pid" "null" "agent_pid cleared after set_done"

    local completed
    completed=$(echo "$json" | jq -r '.completed_at')
    [[ "$completed" != "null" ]] || { echo "    ASSERT: completed_at should be set" >&2; return 1; }
}

# ── task_set_failed tests ─────────────────────────────────────────────────────

test_set_failed() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42

    task_set_failed "1" "Compile error in main.py"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "failed" "status after set_failed"
    assert_json_field "$json" ".error" "Compile error in main.py" "error message"
    assert_json_field "$json" ".agent_pid" "null" "agent_pid cleared after set_failed"
}

# ── task_set_blocked tests ────────────────────────────────────────────────────

test_set_blocked() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42

    task_set_blocked "1" "Missing API key"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "blocked" "status after set_blocked"
    assert_json_field "$json" ".error" "Missing API key" "blocked error message"
    assert_json_field "$json" ".agent_pid" "null" "agent_pid cleared after set_blocked"
}

# ── task_request_changes tests ────────────────────────────────────────────────

test_request_changes() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42
    task_set_done "1"

    task_request_changes "1" "Missing error handling in auth flow"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "pending" "status reverts to pending"
    assert_json_field "$json" ".review_feedback" "Missing error handling in auth flow" "feedback stored"
    assert_json_field "$json" ".review_verdict" "request_changes" "verdict set"
}

# ── task_set_reviewed tests ───────────────────────────────────────────────────

test_set_reviewed_approve() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42
    task_set_done "1"

    task_set_reviewed "1" "approve"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".review_verdict" "approve" "verdict"
    # Status should remain done (set_reviewed does not change status)
    assert_json_field "$json" ".status" "done" "status unchanged"

    local reviewed_at
    reviewed_at=$(echo "$json" | jq -r '.reviewed_at')
    [[ "$reviewed_at" != "null" ]] || { echo "    ASSERT: reviewed_at should be set" >&2; return 1; }
}

test_set_reviewed_request_changes() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42
    task_set_done "1"

    task_set_reviewed "1" "request_changes"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".review_verdict" "request_changes" "verdict"
    assert_json_field "$json" ".status" "done" "status unchanged by set_reviewed"
}

# ── task_set_timeout tests ────────────────────────────────────────────────────

test_set_timeout_first() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42

    task_set_timeout "1" "Agent exceeded 600s limit"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "failed" "status after timeout"
    assert_json_field "$json" ".error" "Agent exceeded 600s limit" "timeout error"
    assert_json_field "$json" ".agent_pid" "null" "agent_pid cleared"

    local tc
    tc=$(echo "$json" | jq '.timeout_count')
    assert_equals "1" "$tc" "first timeout_count"
}

test_set_timeout_increments() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42
    task_set_timeout "1" "first timeout"

    # Reset and timeout again
    task_reset_pending "1" "no_increment"
    task_set_running "1" 43
    task_set_timeout "1" "second timeout"

    local json
    json=$(task_get "1")
    local tc
    tc=$(echo "$json" | jq '.timeout_count')
    assert_equals "2" "$tc" "timeout_count after two timeouts"
}

# ── task_reset_pending tests ──────────────────────────────────────────────────

test_reset_pending_with_increment() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42
    task_set_failed "1" "some error"

    task_reset_pending "1"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "pending" "status reset to pending"
    assert_json_field "$json" ".error" "null" "error cleared"
    assert_json_field "$json" ".agent_pid" "null" "agent_pid cleared"
    assert_json_field "$json" ".started_at" "null" "started_at cleared"
    assert_json_field "$json" ".completed_at" "null" "completed_at cleared"

    local rc
    rc=$(echo "$json" | jq '.retry_count')
    assert_equals "1" "$rc" "retry_count incremented"
}

test_reset_pending_no_increment() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42
    task_set_failed "1" "interrupted"

    task_reset_pending "1" "no_increment"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "pending" "status reset to pending"

    local rc
    rc=$(echo "$json" | jq '.retry_count // 0')
    assert_equals "0" "$rc" "retry_count not incremented"
}

test_reset_pending_preserves_review_feedback() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42
    task_set_done "1"
    task_request_changes "1" "Fix the bug"

    # Now task is pending with review_feedback. Run it, fail it, reset it.
    task_set_running "1" 43
    task_set_failed "1" "still broken"
    task_reset_pending "1"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".review_feedback" "Fix the bug" "review_feedback preserved"
}

test_reset_pending_preserves_review_verdict() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null
    task_set_running "1" 42
    task_set_done "1"
    task_request_changes "1" "Fix the bug"

    # Simulate fix agent interrupted: pending → running → failed → reset
    task_set_running "1" 43
    task_set_failed "1" "agent interrupted"
    task_reset_pending "1"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".review_verdict" "request_changes" "review_verdict preserved"
}

test_reset_pending_multiple_increments() {
    task_create "1" "Task" "Desc" "Criteria" '[]' > /dev/null

    task_set_running "1" 42
    task_set_failed "1" "fail 1"
    task_reset_pending "1"

    task_set_running "1" 43
    task_set_failed "1" "fail 2"
    task_reset_pending "1"

    task_set_running "1" 44
    task_set_failed "1" "fail 3"
    task_reset_pending "1"

    local json
    json=$(task_get "1")
    local rc
    rc=$(echo "$json" | jq '.retry_count')
    assert_equals "3" "$rc" "retry_count after 3 resets"
}

# ── task_list_ids tests ───────────────────────────────────────────────────────

test_list_ids_empty() {
    local ids
    ids=$(task_list_ids)
    assert_equals "" "$ids" "empty dir returns no ids"
}

test_list_ids_multiple() {
    task_create "3" "Third" "d" "c" '[]' > /dev/null
    task_create "1" "First" "d" "c" '[]' > /dev/null
    task_create "2" "Second" "d" "c" '[]' > /dev/null

    local ids
    ids=$(task_list_ids)

    # Should be sorted numerically
    local expected
    expected=$(printf "1\n2\n3")
    assert_equals "$expected" "$ids" "list_ids sorted numerically"
}

# ── task_list_by_status tests ─────────────────────────────────────────────────

test_list_by_status() {
    task_create "1" "T1" "d" "c" '[]' > /dev/null
    task_create "2" "T2" "d" "c" '[]' > /dev/null
    task_create "3" "T3" "d" "c" '[]' > /dev/null
    task_set_running "2" 42
    task_set_running "3" 43
    task_set_done "3"

    local pending running done
    pending=$(task_list_by_status "pending")
    running=$(task_list_by_status "running")
    done=$(task_list_by_status "done")

    assert_equals "1" "$pending" "only task 1 is pending"
    assert_equals "2" "$running" "only task 2 is running"
    assert_equals "3" "$done" "only task 3 is done"
}

test_list_by_status_none_match() {
    task_create "1" "T1" "d" "c" '[]' > /dev/null

    local failed
    failed=$(task_list_by_status "failed")
    assert_equals "" "$failed" "no failed tasks"
}

# ── task_deps_met tests ───────────────────────────────────────────────────────

test_deps_met_no_deps() {
    task_create "1" "Task" "d" "c" '[]' > /dev/null

    local rc=0
    task_deps_met "1" || rc=$?
    assert_exit_code "0" "$rc" "no deps always met"
}

test_deps_met_all_done() {
    task_create "1" "Dep1" "d" "c" '[]' > /dev/null
    task_create "2" "Dep2" "d" "c" '[]' > /dev/null
    task_create "3" "Main" "d" "c" '["1","2"]' > /dev/null

    task_set_running "1" 10
    task_set_done "1"
    task_set_running "2" 11
    task_set_done "2"

    local rc=0
    task_deps_met "3" || rc=$?
    assert_exit_code "0" "$rc" "all deps done"
}

test_deps_met_one_not_done() {
    task_create "1" "Dep1" "d" "c" '[]' > /dev/null
    task_create "2" "Dep2" "d" "c" '[]' > /dev/null
    task_create "3" "Main" "d" "c" '["1","2"]' > /dev/null

    task_set_running "1" 10
    task_set_done "1"
    # Task 2 stays pending

    local rc=0
    task_deps_met "3" || rc=$?
    assert_exit_code "1" "$rc" "dep 2 not done"
}

test_deps_met_dep_failed() {
    task_create "1" "Dep" "d" "c" '[]' > /dev/null
    task_create "2" "Main" "d" "c" '["1"]' > /dev/null

    task_set_running "1" 10
    task_set_failed "1" "broke"

    local rc=0
    task_deps_met "2" || rc=$?
    assert_exit_code "1" "$rc" "failed dep not met"
}

# ── task_list_ready tests ─────────────────────────────────────────────────────

test_list_ready_no_deps() {
    task_create "1" "T1" "d" "c" '[]' > /dev/null
    task_create "2" "T2" "d" "c" '[]' > /dev/null

    local ready
    ready=$(task_list_ready)
    local expected
    expected=$(printf "1\n2")
    assert_equals "$expected" "$ready" "both tasks ready (no deps)"
}

test_list_ready_with_unmet_deps() {
    task_create "1" "T1" "d" "c" '[]' > /dev/null
    task_create "2" "T2" "d" "c" '["1"]' > /dev/null
    task_create "3" "T3" "d" "c" '["1"]' > /dev/null

    # Task 1 pending, so 2 and 3 cannot run
    local ready
    ready=$(task_list_ready)
    assert_equals "1" "$ready" "only task 1 is ready"
}

test_list_ready_after_dep_completes() {
    task_create "1" "T1" "d" "c" '[]' > /dev/null
    task_create "2" "T2" "d" "c" '["1"]' > /dev/null

    task_set_running "1" 10
    task_set_done "1"

    local ready
    ready=$(task_list_ready)
    assert_equals "2" "$ready" "task 2 ready after dep 1 done"
}

test_list_ready_excludes_running() {
    task_create "1" "T1" "d" "c" '[]' > /dev/null
    task_create "2" "T2" "d" "c" '[]' > /dev/null
    task_set_running "1" 10

    local ready
    ready=$(task_list_ready)
    assert_equals "2" "$ready" "running task excluded from ready"
}

test_list_ready_excludes_done() {
    task_create "1" "T1" "d" "c" '[]' > /dev/null
    task_create "2" "T2" "d" "c" '["1"]' > /dev/null
    task_set_running "1" 10
    task_set_done "1"

    # Task 1 done, task 2 pending with dep met
    local ready
    ready=$(task_list_ready)
    assert_equals "2" "$ready" "done task excluded, dependent task ready"
}

test_list_ready_empty_when_all_running() {
    task_create "1" "T1" "d" "c" '[]' > /dev/null
    task_set_running "1" 10

    local ready
    ready=$(task_list_ready)
    assert_equals "" "$ready" "no ready tasks when all running"
}

# ── task_count_by_status / task_count_total tests ─────────────────────────────

test_count_by_status() {
    task_create "1" "T1" "d" "c" '[]' > /dev/null
    task_create "2" "T2" "d" "c" '[]' > /dev/null
    task_create "3" "T3" "d" "c" '[]' > /dev/null
    task_set_running "2" 42
    task_set_running "3" 43
    task_set_done "3"

    assert_equals "1" "$(task_count_by_status "pending")" "1 pending"
    assert_equals "1" "$(task_count_by_status "running")" "1 running"
    assert_equals "1" "$(task_count_by_status "done")" "1 done"
    assert_equals "0" "$(task_count_by_status "failed")" "0 failed"
}

test_count_total() {
    assert_equals "0" "$(task_count_total)" "0 tasks initially"

    task_create "1" "T1" "d" "c" '[]' > /dev/null
    task_create "2" "T2" "d" "c" '[]' > /dev/null
    assert_equals "2" "$(task_count_total)" "2 tasks after creation"

    task_create "3" "T3" "d" "c" '[]' > /dev/null
    assert_equals "3" "$(task_count_total)" "3 tasks"
}

# ── task_topo_sort tests ──────────────────────────────────────────────────────

test_topo_sort_linear_chain() {
    # 1 → 2 → 3
    task_create "1" "First" "d" "c" '[]' > /dev/null
    task_create "2" "Second" "d" "c" '["1"]' > /dev/null
    task_create "3" "Third" "d" "c" '["2"]' > /dev/null

    local sorted
    sorted=$(task_topo_sort)

    # 1 must come before 2, 2 before 3
    local pos1 pos2 pos3
    pos1=$(echo "$sorted" | grep -n "^1$" | cut -d: -f1)
    pos2=$(echo "$sorted" | grep -n "^2$" | cut -d: -f1)
    pos3=$(echo "$sorted" | grep -n "^3$" | cut -d: -f1)

    [[ "$pos1" -lt "$pos2" ]] || { echo "    ASSERT: 1 should come before 2 (pos ${pos1} vs ${pos2})" >&2; return 1; }
    [[ "$pos2" -lt "$pos3" ]] || { echo "    ASSERT: 2 should come before 3 (pos ${pos2} vs ${pos3})" >&2; return 1; }
}

test_topo_sort_diamond() {
    #     1
    #    / \
    #   2   3
    #    \ /
    #     4
    task_create "1" "Root" "d" "c" '[]' > /dev/null
    task_create "2" "Left" "d" "c" '["1"]' > /dev/null
    task_create "3" "Right" "d" "c" '["1"]' > /dev/null
    task_create "4" "Merge" "d" "c" '["2","3"]' > /dev/null

    local sorted
    sorted=$(task_topo_sort)

    local pos1 pos2 pos3 pos4
    pos1=$(echo "$sorted" | grep -n "^1$" | cut -d: -f1)
    pos2=$(echo "$sorted" | grep -n "^2$" | cut -d: -f1)
    pos3=$(echo "$sorted" | grep -n "^3$" | cut -d: -f1)
    pos4=$(echo "$sorted" | grep -n "^4$" | cut -d: -f1)

    [[ "$pos1" -lt "$pos2" ]] || { echo "    ASSERT: 1 before 2" >&2; return 1; }
    [[ "$pos1" -lt "$pos3" ]] || { echo "    ASSERT: 1 before 3" >&2; return 1; }
    [[ "$pos2" -lt "$pos4" ]] || { echo "    ASSERT: 2 before 4" >&2; return 1; }
    [[ "$pos3" -lt "$pos4" ]] || { echo "    ASSERT: 3 before 4" >&2; return 1; }

    # All four tasks present
    local count
    count=$(echo "$sorted" | wc -l | tr -d ' ')
    assert_equals "4" "$count" "all 4 tasks in output"
}

test_topo_sort_independent() {
    task_create "1" "A" "d" "c" '[]' > /dev/null
    task_create "2" "B" "d" "c" '[]' > /dev/null
    task_create "3" "C" "d" "c" '[]' > /dev/null

    local sorted
    sorted=$(task_topo_sort)

    local count
    count=$(echo "$sorted" | wc -l | tr -d ' ')
    assert_equals "3" "$count" "all 3 independent tasks in output"
}

test_topo_sort_cycle_detection() {
    # 1 → 2 → 3 → 1 (cycle)
    task_create "1" "A" "d" "c" '["3"]' > /dev/null
    task_create "2" "B" "d" "c" '["1"]' > /dev/null
    task_create "3" "C" "d" "c" '["2"]' > /dev/null

    # Capture stderr for log_error (need real log_error for this test)
    log_error() { echo "ERROR: $*" >&2; }

    local rc=0
    task_topo_sort > /dev/null 2>&1 || rc=$?
    assert_exit_code "1" "$rc" "cycle should return exit 1"
}

test_topo_sort_partial_cycle() {
    # 1 → 2, 3 → 4 → 3 (cycle in 3-4 but 1-2 are fine)
    task_create "1" "A" "d" "c" '[]' > /dev/null
    task_create "2" "B" "d" "c" '["1"]' > /dev/null
    task_create "3" "C" "d" "c" '["4"]' > /dev/null
    task_create "4" "D" "d" "c" '["3"]' > /dev/null

    log_error() { echo "ERROR: $*" >&2; }

    local rc=0
    task_topo_sort > /dev/null 2>&1 || rc=$?
    assert_exit_code "1" "$rc" "partial cycle should still fail"
}

test_topo_sort_single_task() {
    task_create "1" "Solo" "d" "c" '[]' > /dev/null

    local sorted
    sorted=$(task_topo_sort)
    assert_equals "1" "$sorted" "single task sorts to itself"
}

# ── State transition sequences ────────────────────────────────────────────────

test_full_lifecycle() {
    task_create "1" "Lifecycle" "d" "c" '[]' > /dev/null

    # pending → running → done
    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "pending" "starts pending"

    task_set_running "1" 100
    json=$(task_get "1")
    assert_json_field "$json" ".status" "running" "now running"

    task_set_done "1"
    json=$(task_get "1")
    assert_json_field "$json" ".status" "done" "now done"
}

test_retry_lifecycle() {
    task_create "1" "Retry" "d" "c" '[]' > /dev/null

    # pending → running → failed → pending (retry) → running → done
    task_set_running "1" 100
    task_set_failed "1" "oops"
    task_reset_pending "1"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "pending" "back to pending"
    local rc
    rc=$(echo "$json" | jq '.retry_count')
    assert_equals "1" "$rc" "retry_count = 1"

    task_set_running "1" 101
    task_set_done "1"

    json=$(task_get "1")
    assert_json_field "$json" ".status" "done" "done after retry"
    # retry_count should persist
    rc=$(echo "$json" | jq '.retry_count')
    assert_equals "1" "$rc" "retry_count preserved after done"
}

test_review_cycle() {
    task_create "1" "Review" "d" "c" '[]' > /dev/null

    # pending → running → done → request_changes → pending → running → done → approve
    task_set_running "1" 100
    task_set_done "1"
    task_request_changes "1" "Add tests"

    local json
    json=$(task_get "1")
    assert_json_field "$json" ".status" "pending" "back to pending after review"
    assert_json_field "$json" ".review_feedback" "Add tests" "feedback stored"

    task_set_running "1" 101
    task_set_done "1"
    task_set_reviewed "1" "approve"

    json=$(task_get "1")
    assert_json_field "$json" ".status" "done" "done after approval"
    assert_json_field "$json" ".review_verdict" "approve" "approved"
}

# ── Run all tests ─────────────────────────────────────────────────────────────

echo ""
echo "Task CRUD and state machine tests"
echo "──────────────────────────────────────"

# task_create
run_test test_create_basic
run_test test_create_with_dependencies
run_test test_create_custom_model
run_test test_create_slug_special_chars

# task_get
run_test test_get_existing
run_test test_get_nonexistent

# task_update / task_update_raw
run_test test_update_string_field
run_test test_update_nonexistent
run_test test_update_raw_number
run_test test_update_raw_null
run_test test_update_raw_nonexistent

# State transitions
run_test test_set_running
run_test test_set_running_nonexistent
run_test test_set_done
run_test test_set_failed
run_test test_set_blocked
run_test test_request_changes
run_test test_set_reviewed_approve
run_test test_set_reviewed_request_changes
run_test test_set_timeout_first
run_test test_set_timeout_increments

# Reset pending
run_test test_reset_pending_with_increment
run_test test_reset_pending_no_increment
run_test test_reset_pending_preserves_review_feedback
run_test test_reset_pending_preserves_review_verdict
run_test test_reset_pending_multiple_increments

# Listing
run_test test_list_ids_empty
run_test test_list_ids_multiple
run_test test_list_by_status
run_test test_list_by_status_none_match

# Dependencies
run_test test_deps_met_no_deps
run_test test_deps_met_all_done
run_test test_deps_met_one_not_done
run_test test_deps_met_dep_failed

# Ready tasks
run_test test_list_ready_no_deps
run_test test_list_ready_with_unmet_deps
run_test test_list_ready_after_dep_completes
run_test test_list_ready_excludes_running
run_test test_list_ready_excludes_done
run_test test_list_ready_empty_when_all_running

# Counting
run_test test_count_by_status
run_test test_count_total

# Topological sort
run_test test_topo_sort_linear_chain
run_test test_topo_sort_diamond
run_test test_topo_sort_independent
run_test test_topo_sort_cycle_detection
run_test test_topo_sort_partial_cycle
run_test test_topo_sort_single_task

# Integration / lifecycle
run_test test_full_lifecycle
run_test test_retry_lifecycle
run_test test_review_cycle

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
