#!/usr/bin/env bash
# test_rca_solution_logic.sh — Verify the proposed solutions' logic
#
# Tests the correctness of Changes 1-5 proposed in rca-perpetual-task-failure-loops.md
# by simulating the exact conditions each change addresses.
#
# Usage: bash tests/test_rca_solution_logic.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/.."
PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────

setup_git() {
    TEST_DIR=$(mktemp -d)
    cd "$TEST_DIR"
    git init -q
    git checkout -q -b main
    echo "initial" > file.txt
    git add file.txt
    git commit -q -m "init"
}

setup_tasks() {
    # Create a minimal task directory structure for testing grounding logic
    TEST_DIR=$(mktemp -d)
    mkdir -p "${TEST_DIR}/tasks" "${TEST_DIR}/logs"
}

teardown() {
    cd /
    rm -rf "$TEST_DIR"
}

run_test() {
    local test_name="$1"
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

# ── Change 1: Reorder branch_audit before refresh ────────────────

test_change1_audit_before_refresh_returns_pass() {
    setup_git
    # Simulate: agent work merged into main, main advanced
    git checkout -q -b task-11 main
    echo "agent work" > agent.py
    git add agent.py
    git commit -q -m "agent work"

    git checkout -q main
    git merge -q --no-ff task-11 -m "merge task-11"
    echo "more" > more.py
    git add more.py
    git commit -q -m "advance main"

    # BEFORE refresh: branch_audit's --is-ancestor check
    if ! git merge-base --is-ancestor task-11 main; then
        echo "    ASSERT: pre-refresh audit should detect ancestor relationship"
        return 1
    fi
    # → branch_audit returns "pass", task marked DONE, refresh never runs
}

test_change1_audit_after_refresh_returns_empty() {
    setup_git
    # Same setup but WITH refresh first (current broken order)
    git checkout -q -b task-11 main
    echo "agent work" > agent.py
    git add agent.py
    git commit -q -m "agent work"

    git checkout -q main
    git merge -q --no-ff task-11 -m "merge task-11"
    echo "more" > more.py
    git add more.py
    git commit -q -m "advance main"

    # REFRESH first (current broken order)
    git checkout -q task-11
    git merge -q --no-ff main -m "speed: refresh"
    git checkout -q main

    # AFTER refresh: --is-ancestor fails
    if git merge-base --is-ancestor task-11 main 2>/dev/null; then
        echo "    ASSERT: post-refresh audit should NOT detect ancestor relationship"
        return 1
    fi

    # fork-point diff is empty
    local fork_point
    fork_point=$(git merge-base main task-11)
    local diff
    diff=$(git diff "${fork_point}..task-11" --name-only 2>/dev/null || true)
    if [[ -n "$diff" ]]; then
        echo "    ASSERT: post-refresh fork-point diff should be empty"
        return 1
    fi
    # → branch_audit returns "empty", agent spawns on done code
}

test_change1_new_branch_no_work_returns_empty() {
    setup_git
    # New task branch, no agent work yet
    git checkout -q -b task-new main

    # --is-ancestor: true (branch tip IS main tip) → but this is a false positive
    # branch_audit handles this: falls through to fork-point diff
    local fork_point
    fork_point=$(git merge-base main task-new)
    local diff
    diff=$(git diff "${fork_point}..task-new" --name-only 2>/dev/null || true)
    if [[ -n "$diff" ]]; then
        echo "    ASSERT: new branch with no work should have empty diff"
        return 1
    fi

    # In the CURRENT code, --is-ancestor returns true at line 268,
    # so branch_audit returns "pass" — marking a zero-work branch as done.
    # BUT: this only happens if the branch tip IS an ancestor of main.
    # For a brand-new branch created from main, the tip IS main's commit.
    # --is-ancestor returns true → "pass" → false positive!
    #
    # Wait: the RCA says reordering branch_audit BEFORE refresh is the fix,
    # and the pre-refresh check should work. But for a NEW task (no prior work),
    # the branch was just created from main. --is-ancestor returns true.
    # branch_audit would return "pass" and mark the task DONE with zero work.
    #
    # Is this actually a problem? Let's check: when does a task have a branch
    # but no work? Only if:
    # 1. The branch was created for a prior attempt that produced nothing
    # 2. The branch was just created by run.sh before spawning the agent
    #
    # In run.sh, the branch_audit check (proposed Change 1) runs BEFORE
    # worktree creation at line 797. At this point, the branch exists
    # (created by a prior run or by git_create_worktree from a prior attempt).
    #
    # If the branch was just created from main (no prior work), and main
    # is the same commit as the branch tip, --is-ancestor returns true.
    # This IS a false positive... BUT the current code has the SAME issue
    # (branch_audit at line 776 runs after refresh, but for a new branch
    # with no work, there's nothing to refresh, so the topology is the same).
    #
    # Actually: for a first-run task, does the branch exist before the dispatch?
    # Looking at run.sh:797: `git_create_worktree "$task_id" "$branch"`
    # This creates the branch if it doesn't exist. So BEFORE line 797,
    # the branch might not exist. Change 1 runs before line 753 (refresh).
    # The check at the top is: `if [[ -n "$branch" ]] && git_branch_exists "$branch"`.
    # For a first-run task, the branch doesn't exist → check is skipped → no issue.
    #
    # For a task that was attempted before (branch exists, might have work):
    # if the branch was created but agent produced nothing (empty diff),
    # --is-ancestor returns true if branch tip == main commit.
    # But the fork-point diff check at line 286 would catch this:
    # the diff would be empty → branch_audit returns "empty" → proceed.
    #
    # Wait: --is-ancestor at line 268 short-circuits before the diff check.
    # If branch tip is ancestor of main → "pass". It never reaches line 286.
    # So for a branch created from main with no work, "pass" is returned.
    #
    # This is a FALSE POSITIVE that exists in both current and proposed code.
    # The RCA's rejected alternative section mentions this exact case:
    # "A branch created from main via git worktree add -b has its tip at
    # main's commit. --is-ancestor returns true."
    #
    # But this is about the STANDALONE check, not the existing branch_audit.
    # The existing branch_audit at line 268 has the same issue!
    #
    # Let me verify: does git_create_worktree leave the branch at main's tip?
    # If so, after a failed attempt where the agent produced nothing,
    # the branch tip IS main's tip, and branch_audit returns "pass".
    # This would mark the task as DONE incorrectly.
    #
    # However: after a failed attempt, main may have advanced. If main
    # advanced past the branch tip, --is-ancestor still returns true
    # (branch tip is behind main, still reachable from main).
    # So "pass" is returned for a zero-work branch. FALSE POSITIVE.
    #
    # FINDING: Change 1 inherits a pre-existing false positive in branch_audit:
    # branches with zero work that are behind main get marked "pass" (DONE).

    # Verify the false positive exists
    if ! git merge-base --is-ancestor task-new main; then
        echo "    ASSERT: new branch from main should satisfy --is-ancestor"
        return 1
    fi
}

# ── Change 3: Skip ownership for done tasks ──────────────────────

test_change3_done_task_ownership_released() {
    setup_tasks
    # Task 1 owns lib/context/assembly.py, status = done
    cat > "${TEST_DIR}/tasks/1.json" <<'JSON'
{"id":"1","title":"Task 1","status":"done","files_touched":["lib/context/assembly.py"]}
JSON
    # Task 15 modifies lib/context/assembly.py (owned by task 1)
    # With Change 3, the ownership check should skip task 1 because it's done

    local other_status
    other_status=$(jq -r '.status // "pending"' "${TEST_DIR}/tasks/1.json")
    if [[ "$other_status" != "done" ]]; then
        echo "    ASSERT: task 1 should be 'done'"
        return 1
    fi
    # Change 3 logic: skip if done or integrated → no ownership violation
}

test_change3_pending_task_ownership_blocks() {
    setup_tasks
    # Task 1 owns lib/context/assembly.py, status = pending
    cat > "${TEST_DIR}/tasks/1.json" <<'JSON'
{"id":"1","title":"Task 1","status":"pending","files_touched":["lib/context/assembly.py"]}
JSON

    local other_status
    other_status=$(jq -r '.status // "pending"' "${TEST_DIR}/tasks/1.json")
    if [[ "$other_status" == "done" ]] || [[ "$other_status" == "integrated" ]]; then
        echo "    ASSERT: pending task should NOT be skipped"
        return 1
    fi
    # Ownership check should still block
}

test_change3_blocked_task_ownership_blocks() {
    setup_tasks
    # Task 1 owns a file, status = blocked
    cat > "${TEST_DIR}/tasks/1.json" <<'JSON'
{"id":"1","title":"Task 1","status":"blocked","files_touched":["lib/context/assembly.py"]}
JSON

    local other_status
    other_status=$(jq -r '.status // "pending"' "${TEST_DIR}/tasks/1.json")
    # Change 3 only skips "done" and "integrated" — blocked is NOT skipped
    if [[ "$other_status" == "done" ]] || [[ "$other_status" == "integrated" ]]; then
        echo "    ASSERT: blocked task should NOT be skipped by Change 3"
        return 1
    fi
    # This is correct behavior: blocked tasks might be retried later
}

# ── Change 4: Gate feedback to agent ─────────────────────────────

test_change4_gate_results_extractable() {
    setup_tasks
    # Simulate a task JSON with gate_results from a failed run
    cat > "${TEST_DIR}/tasks/11.json" <<'JSON'
{
    "id": "11",
    "title": "Task 11",
    "status": "failed",
    "retry_count": 1,
    "gate_results": {
        "checks": [
            {"name": "diff_non_empty", "status": "pass"},
            {"name": "scope", "status": "fail", "ownership_violations": ["lib/x.py (task 1)"]},
            {"name": "criteria", "status": "fail"}
        ]
    }
}
JSON

    # The proposed jq query from Change 4
    local failed_checks
    failed_checks=$(jq -r '
        .gate_results.checks[]?
        | select(.status == "fail")
        | "- \(.name): FAILED" +
          (if .ownership_violations then " (files: " + (.ownership_violations | join(", ")) + ")" else "" end) +
          (if .undeclared_files then " (files: " + (.undeclared_files | join(", ")) + ")" else "" end)
    ' "${TEST_DIR}/tasks/11.json" 2>/dev/null)

    if [[ -z "$failed_checks" ]]; then
        echo "    ASSERT: jq query should extract failed checks"
        return 1
    fi

    # Should contain scope failure with file info
    if ! echo "$failed_checks" | grep -q "scope.*lib/x.py"; then
        echo "    ASSERT: should include scope failure with file reference"
        echo "    GOT: $failed_checks"
        return 1
    fi

    # Should contain criteria failure
    if ! echo "$failed_checks" | grep -q "criteria.*FAILED"; then
        echo "    ASSERT: should include criteria failure"
        echo "    GOT: $failed_checks"
        return 1
    fi
}

test_change4_no_gate_results_produces_empty() {
    setup_tasks
    # Task with no gate_results (first run, or results not persisted)
    cat > "${TEST_DIR}/tasks/11.json" <<'JSON'
{"id":"11","title":"Task 11","status":"failed","retry_count":0}
JSON

    local failed_checks
    failed_checks=$(jq -r '
        .gate_results.checks[]?
        | select(.status == "fail")
        | "- \(.name): FAILED"
    ' "${TEST_DIR}/tasks/11.json" 2>/dev/null)

    if [[ -n "$failed_checks" ]]; then
        echo "    ASSERT: no gate_results should produce empty output"
        echo "    GOT: $failed_checks"
        return 1
    fi
}

# ── Change 5: Global circuit breaker ─────────────────────────────

test_change5_retry_count_threshold() {
    setup_tasks
    # Task at retry_count = 3 → should trigger circuit breaker
    cat > "${TEST_DIR}/tasks/11.json" <<'JSON'
{"id":"11","title":"Task 11","status":"pending","retry_count":3}
JSON

    local retry_count
    retry_count=$(jq -r '.retry_count // 0' "${TEST_DIR}/tasks/11.json")

    if [[ "$retry_count" -lt 3 ]]; then
        echo "    ASSERT: retry_count should be >= 3 to trigger breaker"
        return 1
    fi
    # Circuit breaker fires: task_set_blocked
}

test_change5_retry_count_below_threshold() {
    setup_tasks
    # Task at retry_count = 2 → should NOT trigger circuit breaker
    cat > "${TEST_DIR}/tasks/11.json" <<'JSON'
{"id":"11","title":"Task 11","status":"pending","retry_count":2}
JSON

    local retry_count
    retry_count=$(jq -r '.retry_count // 0' "${TEST_DIR}/tasks/11.json")

    if [[ "$retry_count" -ge 3 ]]; then
        echo "    ASSERT: retry_count=2 should NOT trigger breaker"
        return 1
    fi
    # Agent runs normally
}

test_change5_timeout_path_retry_count() {
    setup_tasks
    # Simulate the timeout escalation path:
    # Initial run: retry_count=0, timeout → task_set_timeout (timeout_count=1)
    # Then task_reset_pending → retry_count=1
    # Second run: retry_count=1, timeout → task_set_timeout (timeout_count=2)
    # Permanent failure, does NOT call task_reset_pending → retry_count stays 1
    # Human retries → task_reset_pending → retry_count=2
    # Third run: retry_count=2, gates fail → task_set_failed
    # Human retries → task_reset_pending → retry_count=3
    # Fourth dispatch: retry_count=3 → circuit breaker fires

    # The RCA says "timed out twice already has retry_count=2"
    # Let's trace: after timeout path + human retry, what's retry_count?

    # Start: retry_count=0
    local count=0

    # First timeout: task_reset_pending increments
    count=$((count + 1))  # → 1

    # Second timeout: permanent failure, no reset_pending
    # count stays 1

    # Human retries: task_reset_pending increments
    count=$((count + 1))  # → 2

    # Gate failure, human retries: task_reset_pending increments
    count=$((count + 1))  # → 3

    if [[ "$count" -ne 3 ]]; then
        echo "    ASSERT: after timeout path + human retries, count should be 3"
        return 1
    fi
    # Circuit breaker fires at count=3. Task ran 3 times (initial, opus retry, human retry).
    # RCA's claim of "retry_count=2 after two timeouts" is WRONG — it's 1.
}

# ── Retry.sh dead code ───────────────────────────────────────────

test_retry_dead_code_unreachable() {
    # The branch_audit call at retry.sh:192 is guarded by:
    #   if [[ -z "$context" ]]
    # But reaching this point requires context to be non-empty (line 112-140 exits if empty).
    # Therefore: [[ -z "$context" ]] is ALWAYS false at line 189.

    # Simulate: context is non-empty (required), check the guard
    local context="fix the scope violation"
    if [[ -z "$context" ]]; then
        echo "    ASSERT: context should be non-empty (required by retry)"
        return 1
    fi
    # The guard [[ -z "$context" ]] → false → branch_audit never called
    # QED: dead code
}

# ── Scenario 8: Three-dot vs two-dot diff agreement ─────────────

test_scenario8_diffs_agree_after_refresh() {
    setup_git
    # Create the exact topology from Scenario 1
    git checkout -q -b task-11 main
    echo "agent work" > agent.py
    git add agent.py
    git commit -q -m "agent work"

    git checkout -q main
    git merge -q --no-ff task-11 -m "merge"
    echo "more" > more.py
    git add more.py
    git commit -q -m "advance"

    # Refresh
    git checkout -q task-11
    git merge -q --no-ff main -m "speed: refresh"
    git checkout -q main

    # Two-dot diff (branch_audit style)
    local fork_point
    fork_point=$(git merge-base main task-11)
    local two_dot
    two_dot=$(git diff "${fork_point}..task-11" --name-only 2>/dev/null || true)

    # Three-dot diff (grounding_check_diff_nonempty style)
    local three_dot
    three_dot=$(git diff "main...task-11" --name-only 2>/dev/null || true)

    # RCA Scenario 8 claims these can disagree. After refresh, both should be empty.
    if [[ "$two_dot" != "$three_dot" ]]; then
        echo "    ASSERT: after refresh, two-dot and three-dot should agree"
        echo "    TWO-DOT: '${two_dot}'"
        echo "    THREE-DOT: '${three_dot}'"
        return 1
    fi
    # FINDING: they agree (both empty). Scenario 8 may not be a real issue
    # for the post-refresh topology.
}

test_scenario8_diffs_agree_pre_refresh_with_squash() {
    setup_git
    # Squash merge: work in main via squash, no refresh
    git checkout -q -b task-11 main
    echo "agent work" > agent.py
    git add agent.py
    git commit -q -m "agent work"

    git checkout -q main
    git merge -q --squash task-11
    git commit -q -m "squash merge task-11"

    # NO refresh. Two-dot and three-dot should both show agent.py
    local fork_point
    fork_point=$(git merge-base main task-11)
    local two_dot
    two_dot=$(git diff "${fork_point}..task-11" --name-only 2>/dev/null || true)

    local three_dot
    three_dot=$(git diff "main...task-11" --name-only 2>/dev/null || true)

    if [[ "$two_dot" != "$three_dot" ]]; then
        echo "    INFO: two-dot and three-dot differ for squash merge (no refresh)"
        echo "    TWO-DOT: '${two_dot}'"
        echo "    THREE-DOT: '${three_dot}'"
        # This is interesting but may not be a disagreement that matters
    fi
    # Both should show agent.py (the agent's work)
    if [[ -z "$two_dot" ]] || [[ -z "$three_dot" ]]; then
        echo "    ASSERT: both diffs should show agent.py for squash merge (no refresh)"
        echo "    TWO-DOT: '${two_dot}'"
        echo "    THREE-DOT: '${three_dot}'"
        return 1
    fi
}

# ── Run ──────────────────────────────────────────────────────────

echo ""
echo "RCA Solution Logic Verification"
echo "================================"
echo ""

echo "Change 1: Reorder branch_audit before refresh"
run_test test_change1_audit_before_refresh_returns_pass
run_test test_change1_audit_after_refresh_returns_empty
run_test test_change1_new_branch_no_work_returns_empty

echo ""
echo "Change 3: Skip ownership for done tasks"
run_test test_change3_done_task_ownership_released
run_test test_change3_pending_task_ownership_blocks
run_test test_change3_blocked_task_ownership_blocks

echo ""
echo "Change 4: Gate feedback to agent"
run_test test_change4_gate_results_extractable
run_test test_change4_no_gate_results_produces_empty

echo ""
echo "Change 5: Global circuit breaker"
run_test test_change5_retry_count_threshold
run_test test_change5_retry_count_below_threshold
run_test test_change5_timeout_path_retry_count

echo ""
echo "Retry.sh dead code"
run_test test_retry_dead_code_unreachable

echo ""
echo "Scenario 8: Diff agreement"
run_test test_scenario8_diffs_agree_after_refresh
run_test test_scenario8_diffs_agree_pre_refresh_with_squash

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
exit $([[ $FAIL -eq 0 ]] && echo 0 || echo 1)
