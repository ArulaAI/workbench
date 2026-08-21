#!/usr/bin/env bash
# test_rca_code_claims.sh — Verify RCA implementation is correctly applied
#
# Post-implementation verification: confirms that all changes from
# rca-perpetual-task-failure-loops.md are present in the codebase and
# that unchanged code still exists where expected.
#
# Uses grep-based pattern matching instead of hardcoded line numbers
# so tests survive future line shifts from unrelated edits.
#
# Usage: bash tests/test_rca_code_claims.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/.."
PASS=0
FAIL=0

run_test() {
    local test_name="$1"
    local rc=0
    "$test_name" || rc=$?
    if [[ $rc -eq 0 ]]; then
        printf "  PASS  %s\n" "$test_name"
        PASS=$((PASS + 1))
    else
        printf "  FAIL  %s\n" "$test_name"
        FAIL=$((FAIL + 1))
    fi
}

# Assert a pattern exists anywhere in the file
assert_file_contains() {
    local file="$1" pattern="$2" context="${3:-}"
    if ! grep -qE -- "$pattern" "$file"; then
        echo "    ASSERT: ${file} should contain '${pattern}'"
        [[ -n "$context" ]] && echo "    CONTEXT: ${context}"
        return 1
    fi
}

# Assert a pattern does NOT exist in the file
assert_file_not_contains() {
    local file="$1" pattern="$2" context="${3:-}"
    if grep -qE -- "$pattern" "$file"; then
        echo "    ASSERT: ${file} should NOT contain '${pattern}'"
        [[ -n "$context" ]] && echo "    CONTEXT: ${context}"
        return 1
    fi
}

# Assert pattern A appears BEFORE pattern B (by line number)
assert_pattern_before() {
    local file="$1" pattern_a="$2" pattern_b="$3" context="${4:-}"
    local line_a line_b
    line_a=$(grep -nE -- "$pattern_a" "$file" | head -1 | cut -d: -f1)
    line_b=$(grep -nE -- "$pattern_b" "$file" | head -1 | cut -d: -f1)
    if [[ -z "$line_a" ]]; then
        echo "    ASSERT: pattern A '${pattern_a}' not found in ${file}"
        [[ -n "$context" ]] && echo "    CONTEXT: ${context}"
        return 1
    fi
    if [[ -z "$line_b" ]]; then
        echo "    ASSERT: pattern B '${pattern_b}' not found in ${file}"
        [[ -n "$context" ]] && echo "    CONTEXT: ${context}"
        return 1
    fi
    if [[ "$line_a" -ge "$line_b" ]]; then
        echo "    ASSERT: '${pattern_a}' (line ${line_a}) should be BEFORE '${pattern_b}' (line ${line_b})"
        [[ -n "$context" ]] && echo "    CONTEXT: ${context}"
        return 1
    fi
}

# Assert a pattern exists within a function (between function name and next function or EOF)
assert_function_contains() {
    local file="$1" func_name="$2" pattern="$3" context="${4:-}"
    local func_start func_body
    func_start=$(grep -n "^${func_name}()" "$file" | head -1 | cut -d: -f1)
    if [[ -z "$func_start" ]]; then
        echo "    ASSERT: function ${func_name} not found in ${file}"
        [[ -n "$context" ]] && echo "    CONTEXT: ${context}"
        return 1
    fi
    # Extract from function start+1 to next top-level function or 300 lines
    local func_end
    func_end=$(tail -n +"$((func_start + 1))" "$file" | grep -n '^[a-z_]*() {' | head -1 | cut -d: -f1)
    if [[ -n "$func_end" ]]; then
        func_body=$(sed -n "${func_start},$((func_start + func_end - 1))p" "$file")
    else
        func_body=$(sed -n "${func_start},$((func_start + 300))p" "$file")
    fi
    if ! echo "$func_body" | grep -qE -- "$pattern"; then
        echo "    ASSERT: function ${func_name} should contain '${pattern}'"
        [[ -n "$context" ]] && echo "    CONTEXT: ${context}"
        return 1
    fi
}

# ── File references ──────────────────────────────────────────────

GROUNDING="${PROJECT_ROOT}/lib/grounding.sh"
RUN="${PROJECT_ROOT}/lib/cmd/run.sh"
RETRY="${PROJECT_ROOT}/lib/cmd/retry.sh"
TASKS="${PROJECT_ROOT}/lib/tasks.sh"
GATES="${PROJECT_ROOT}/lib/gates.sh"

# ══════════════════════════════════════════════════════════════════
# grounding.sh — unchanged code still present
# ══════════════════════════════════════════════════════════════════

test_grounding_diff_nonempty_three_dot_diff() {
    assert_function_contains "$GROUNDING" "grounding_check_diff_nonempty" 'diff.*\.\.\.' \
        "grounding_check_diff_nonempty should use three-dot diff"
}

test_grounding_branch_audit_is_ancestor() {
    assert_function_contains "$GROUNDING" "branch_audit" 'merge-base --is-ancestor' \
        "branch_audit should have --is-ancestor check"
}

test_grounding_branch_audit_merge_base() {
    assert_function_contains "$GROUNDING" "branch_audit" 'fork_point.*merge-base' \
        "branch_audit should compute fork_point via merge-base"
}

test_grounding_branch_audit_two_dot_diff() {
    assert_function_contains "$GROUNDING" "branch_audit" 'fork_point.*\.\.' \
        "branch_audit should use two-dot diff"
}

test_grounding_branch_audit_empty_returns() {
    assert_function_contains "$GROUNDING" "branch_audit" 'echo.*empty' \
        "branch_audit should return 'empty' when agent_diff is empty"
}

test_grounding_scope_strict_default() {
    # scope_strict lives in grounding_run (where scope result is evaluated), not grounding_check_scope
    assert_function_contains "$GROUNDING" "grounding_run" 'scope_strict.*toml_get_value.*"true"' \
        "scope_strict should default to true"
}

test_grounding_scope_ownership_iteration() {
    assert_function_contains "$GROUNDING" "grounding_check_scope" 'for other_file in' \
        "scope check should iterate task JSONs"
}

test_grounding_scope_self_skip() {
    assert_function_contains "$GROUNDING" "grounding_check_scope" 'other_id.*==.*task_id.*continue' \
        "scope check should skip self"
}

test_grounding_ownership_format() {
    assert_function_contains "$GROUNDING" "grounding_check_scope" 'ownership_violations.*actual_file.*task.*owner_tid' \
        "ownership violation string format"
}

test_grounding_test_file_exemption() {
    assert_function_contains "$GROUNDING" "grounding_check_scope" '_is_test_file' \
        "test file exemption in scope check"
}

test_grounding_sibling_failed_skip() {
    assert_function_contains "$GROUNDING" "_test_files_covered_by_siblings" 'failed.*cancelled' \
        "sibling test coverage should skip failed/cancelled"
}

test_grounding_secrets_uses_diff() {
    assert_function_contains "$GROUNDING" "grounding_check_secrets" 'diff.*--name-only' \
        "secrets scanner should use diff"
}

test_grounding_gate_results_persistence() {
    assert_function_contains "$GROUNDING" "grounding_run" 'gate_results = \$gr' \
        "gate_results should be persisted to task JSON"
}

# ══════════════════════════════════════════════════════════════════
# grounding.sh — RCA fixes applied
# ══════════════════════════════════════════════════════════════════

test_fix_change1a_blocked_return() {
    # Change 1a: branch_audit returns "blocked" (not "fail") for prior blocked agent
    assert_function_contains "$GROUNDING" "branch_audit" 'echo.*"blocked"' \
        "branch_audit should return 'blocked' for prior blocked agent"
}

test_fix_change3_ownership_skip_done() {
    # Change 3: skip ownership for done/integrated/cancelled tasks
    assert_function_contains "$GROUNDING" "grounding_check_scope" \
        'other_status.*==.*"done"' \
        "scope check should skip done tasks"
    assert_function_contains "$GROUNDING" "grounding_check_scope" \
        'other_status.*==.*"integrated"' \
        "scope check should skip integrated tasks"
    assert_function_contains "$GROUNDING" "grounding_check_scope" \
        'other_status.*==.*"cancelled"' \
        "scope check should skip cancelled tasks"
}

test_fix_change4_criteria_jq_fixed() {
    # Change 4: criteria uses .criteria_results[] not .[]
    assert_function_contains "$GROUNDING" "grounding_check_criteria" 'criteria_results\[\]' \
        "criteria jq should use .criteria_results[]"
}

test_fix_change4_criteria_echo() {
    # Change 4: criteria echoes verify_output before return
    assert_function_contains "$GROUNDING" "grounding_check_criteria" 'echo.*verify_output' \
        "criteria should echo verify_output"
}

test_fix_change4_declared_files_detail() {
    # Change 4: declared_files echoes missing file names
    assert_function_contains "$GROUNDING" "grounding_check_declared_files" 'echo.*missing_files' \
        "declared_files should echo missing file names"
}

test_fix_change4_test_coverage_detail() {
    # Change 4: test_coverage echoes uncovered files
    assert_function_contains "$GROUNDING" "grounding_check_test_coverage" 'echo.*missing_tests' \
        "test_coverage should echo missing test files"
}

test_fix_change4_grounding_run_declared_detail() {
    # Change 4: grounding_run captures declared_files detail into gate_checks
    assert_function_contains "$GROUNDING" "grounding_run" 'missing_files.*\$mf' \
        "grounding_run should capture missing_files detail"
}

test_fix_change4_grounding_run_coverage_detail() {
    # Change 4: grounding_run captures test_coverage detail into gate_checks
    assert_function_contains "$GROUNDING" "grounding_run" 'uncovered_files.*\$uf' \
        "grounding_run should capture uncovered_files detail"
}

test_fix_change4_criteria_detail_persisted() {
    # Change 4: criteria detail persisted to task JSON
    assert_function_contains "$GROUNDING" "grounding_run" 'criteria_detail.*=.*\$cr' \
        "criteria detail should be persisted to task JSON"
}

test_fix_secrets_comment() {
    # Fixed: comment no longer says "git history"
    assert_file_not_contains "$GROUNDING" 'secrets in git history' \
        "misleading 'git history' comment should be fixed"
    assert_file_contains "$GROUNDING" 'scans current file content from branch diff' \
        "comment should say 'branch diff'"
}

# ══════════════════════════════════════════════════════════════════
# run.sh — unchanged code still present
# ══════════════════════════════════════════════════════════════════

test_run_get_ready_tasks_pending_only() {
    assert_file_contains "$RUN" '_get_ready_tasks.*{' \
        "_get_ready_tasks function should exist"
    # Verify it filters by pending
    local func_line
    func_line=$(grep -n '_get_ready_tasks()' "$RUN" | head -1 | cut -d: -f1)
    local func_body
    func_body=$(sed -n "${func_line},$((func_line+15))p" "$RUN")
    if ! echo "$func_body" | grep -q 'pending'; then
        echo "    ASSERT: _get_ready_tasks should filter by 'pending'"
        return 1
    fi
}

test_run_timeout_first_escalation() {
    assert_file_contains "$RUN" 'opus' \
        "timeout escalation to opus should exist"
}

test_run_supervisor_invocation() {
    assert_file_contains "$RUN" '_invoke_supervisor' \
        "supervisor invocation should exist"
}

# ══════════════════════════════════════════════════════════════════
# run.sh — RCA fixes applied
# ══════════════════════════════════════════════════════════════════

test_fix_change1_audit_before_refresh() {
    # Change 1: branch_audit call should appear BEFORE the refresh step
    assert_pattern_before "$RUN" \
        'branch_audit.*task_id' \
        'merge --no-ff.*main.*refresh' \
        "branch_audit should run BEFORE refresh"
}

test_fix_change1_blocked_handler() {
    # Change 1: branch_audit "blocked" → task_set_blocked + _invoke_supervisor
    assert_file_contains "$RUN" 'audit_result.*==.*"blocked"' \
        "run.sh should handle branch_audit 'blocked' result"
    assert_file_contains "$RUN" 'task_set_blocked.*Prior agent reported blocked' \
        "blocked audit should call task_set_blocked"
}

test_fix_change1_fail_clears_gate_results() {
    # Change 1: branch_audit "fail" → clear stale gate_results
    assert_file_contains "$RUN" 'audit_result.*==.*"fail"' \
        "run.sh should handle branch_audit 'fail' result"
    assert_file_contains "$RUN" 'del\(\.gate_results\)' \
        "fail path should clear gate_results"
}

test_fix_change4_failure_context_built() {
    # Change 4: failure_context built from gate_results on retry
    assert_file_contains "$RUN" 'gate_results\.checks\[\]\?' \
        "failure_context jq should read gate_results.checks"
    assert_file_contains "$RUN" 'failure_context=' \
        "failure_context variable should be assigned"
}

test_fix_change4_failure_context_injected() {
    # Change 4: failure_context injected into agent_message
    # They appear on adjacent lines: agent_message+="...\n${failure_context}"
    assert_file_contains "$RUN" '\$failure_context' \
        "failure_context should be referenced in agent prompt assembly"
    assert_file_contains "$RUN" 'Append gate failure context for retries' \
        "failure_context injection comment should exist"
}

test_fix_change5_circuit_breaker() {
    # Change 5: global circuit breaker at retry_count >= 3
    assert_file_contains "$RUN" 'retry_count.*-ge 3' \
        "circuit breaker should check retry_count >= 3"
    assert_file_contains "$RUN" 'hit global retry limit.*BLOCKED' \
        "circuit breaker should log BLOCKED"
}

test_fix_change5_before_task_set_failed() {
    # Change 5: circuit breaker should appear BEFORE task_set_failed
    assert_pattern_before "$RUN" \
        'hit global retry limit' \
        'task_set_failed.*Quality gates' \
        "circuit breaker should fire before task_set_failed"
}

test_fix_change5_pid_cleanup() {
    # Regression fix: circuit breaker must clean up PID file and done marker
    # before `continue`, otherwise the poll loop re-processes the same agent
    # completion indefinitely (stale PID file → re-enter completion block →
    # re-run gates → circuit breaker → continue without cleanup → repeat).
    # Extract the circuit breaker block and verify rm -f appears before continue.
    local cb_start cb_block
    cb_start=$(grep -n 'hit global retry limit' "$RUN" | head -1 | cut -d: -f1)
    cb_block=$(sed -n "$((cb_start-5)),$((cb_start+5))p" "$RUN")
    if ! echo "$cb_block" | grep -q 'rm -f.*pid_file'; then
        echo "    ASSERT: circuit breaker must rm pid_file before continue"
        return 1
    fi
}

test_fix_scenario_b_worktree_error() {
    # Scenario B: worktree creation error handling
    assert_file_contains "$RUN" 'Worktree creation failed' \
        "worktree creation failure should be handled"
}

test_fix_scenario_c_lock_escalation() {
    # Scenario C: lock deferral counter escalation
    assert_file_contains "$RUN" 'Could not acquire main-branch lock after' \
        "lock deferral should escalate to blocked"
}

test_fix_scenario_c_conflict_escalation() {
    # Scenario C: file conflict deferral counter escalation
    assert_file_contains "$RUN" 'File conflict persisted after' \
        "file conflict deferral should escalate to blocked"
}

test_run_lock_release_before_refresh() {
    # Structural: lock release should be before refresh
    assert_pattern_before "$RUN" \
        'main_branch_release_lock' \
        'Refresh task branch against main' \
        "lock release should be before refresh"
}

# ══════════════════════════════════════════════════════════════════
# retry.sh — RCA fixes applied
# ══════════════════════════════════════════════════════════════════

test_retry_context_required() {
    assert_file_contains "$RETRY" 'exit 1' \
        "retry should exit 1 when context is empty"
}

test_fix_retry_dead_code_fixed() {
    # Dead code guard replaced: uses $reset_branch not $context
    assert_file_contains "$RETRY" 'if ! \$reset_branch' \
        "retry branch_audit guard should use reset_branch, not context"
    # The old guard 'if [[ -z "$context" ]]' immediately before branch_audit is gone.
    # Other uses of -z "$context" at lines 96 and 112 are for different logic.
    # Verify the branch_audit section uses reset_branch, not context.
    local audit_line
    audit_line=$(grep -n 'branch_audit' "$RETRY" | head -1 | cut -d: -f1)
    local guard_line=$((audit_line - 3))
    local guard_context
    guard_context=$(sed -n "${guard_line},$((audit_line))p" "$RETRY")
    if echo "$guard_context" | grep -q '\-z.*context'; then
        echo "    ASSERT: branch_audit guard should NOT use -z context"
        return 1
    fi
}

test_fix_retry_blocked_handler() {
    # Blocked handler added
    assert_file_contains "$RETRY" 'audit_result.*==.*"blocked"' \
        "retry should handle branch_audit 'blocked' result"
}

test_retry_branch_audit_exists() {
    assert_file_contains "$RETRY" 'branch_audit.*task_id' \
        "branch_audit call should exist in retry.sh"
}

# ══════════════════════════════════════════════════════════════════
# tasks.sh — RCA fixes applied
# ══════════════════════════════════════════════════════════════════

test_tasks_reset_pending_increments_retry() {
    assert_file_contains "$TASKS" 'retry_count.*\+ 1' \
        "task_reset_pending should increment retry_count"
}

test_fix_tasks_clears_gate_results() {
    # Change 4 Step 3: task_reset_pending clears gate_results
    assert_function_contains "$TASKS" "task_reset_pending" 'del\(\.gate_results\)' \
        "task_reset_pending should clear gate_results"
}

test_fix_tasks_clears_criteria_detail() {
    # Change 4 Step 3: task_reset_pending clears criteria_detail
    assert_function_contains "$TASKS" "task_reset_pending" 'del\(\.criteria_detail\)' \
        "task_reset_pending should clear criteria_detail"
}

test_tasks_timeout_increments_timeout_count() {
    assert_file_contains "$TASKS" 'timeout_count.*\+ 1' \
        "task_set_timeout should increment timeout_count"
}

test_tasks_timeout_sets_failed() {
    assert_file_contains "$TASKS" 'status.*=.*"failed"' \
        "task_set_timeout should set status to failed"
}

# ══════════════════════════════════════════════════════════════════
# gates.sh — Scenario A implementation
# ══════════════════════════════════════════════════════════════════

test_fix_gates_quality_checks_variable() {
    # Scenario A: quality_checks tracking array
    assert_function_contains "$GATES" "gates_run" "quality_checks='\\[\\]'" \
        "gates_run should declare quality_checks array"
}

test_fix_gates_syntax_captured() {
    # Scenario A: syntax check result captured
    assert_function_contains "$GATES" "gates_run" 'quality_checks.*syntax.*status' \
        "syntax check result should be captured in quality_checks"
}

test_fix_gates_quality_persisted() {
    # Scenario A: quality checks appended to gate_results
    assert_function_contains "$GATES" "gates_run" 'gate_results\.checks.*\+.*\$qc' \
        "quality checks should be appended to gate_results.checks"
}

test_fix_gates_failure_output_captured() {
    # Scenario A: failed gate output captured for feedback
    assert_function_contains "$GATES" "gates_run" 'gate_output.*tail' \
        "failed gate log output should be captured"
}

# ══════════════════════════════════════════════════════════════════
# Behavioral claims (still valid post-implementation)
# ══════════════════════════════════════════════════════════════════

test_claim_failed_tasks_not_auto_retried() {
    # _get_ready_tasks only picks up "pending" → failed tasks stay stuck
    local func_line
    func_line=$(grep -n '_get_ready_tasks()' "$RUN" | head -1 | cut -d: -f1)
    local func_body
    func_body=$(sed -n "${func_line},$((func_line+15))p" "$RUN")
    if echo "$func_body" | grep -q '"failed"'; then
        echo "    ASSERT: _get_ready_tasks should NOT include failed tasks"
        return 1
    fi
}

# ── Run ──────────────────────────────────────────────────────────

echo ""
echo "RCA Implementation Verification"
echo "================================"
echo ""

echo "grounding.sh — unchanged code"
run_test test_grounding_diff_nonempty_three_dot_diff
run_test test_grounding_branch_audit_is_ancestor
run_test test_grounding_branch_audit_merge_base
run_test test_grounding_branch_audit_two_dot_diff
run_test test_grounding_branch_audit_empty_returns
run_test test_grounding_scope_strict_default
run_test test_grounding_scope_ownership_iteration
run_test test_grounding_scope_self_skip
run_test test_grounding_ownership_format
run_test test_grounding_test_file_exemption
run_test test_grounding_sibling_failed_skip
run_test test_grounding_secrets_uses_diff
run_test test_grounding_gate_results_persistence

echo ""
echo "grounding.sh — fixes applied"
run_test test_fix_change1a_blocked_return
run_test test_fix_change3_ownership_skip_done
run_test test_fix_change4_criteria_jq_fixed
run_test test_fix_change4_criteria_echo
run_test test_fix_change4_declared_files_detail
run_test test_fix_change4_test_coverage_detail
run_test test_fix_change4_grounding_run_declared_detail
run_test test_fix_change4_grounding_run_coverage_detail
run_test test_fix_change4_criteria_detail_persisted
run_test test_fix_secrets_comment

echo ""
echo "run.sh — unchanged code"
run_test test_run_get_ready_tasks_pending_only
run_test test_run_timeout_first_escalation
run_test test_run_supervisor_invocation

echo ""
echo "run.sh — fixes applied"
run_test test_fix_change1_audit_before_refresh
run_test test_fix_change1_blocked_handler
run_test test_fix_change1_fail_clears_gate_results
run_test test_fix_change4_failure_context_built
run_test test_fix_change4_failure_context_injected
run_test test_fix_change5_circuit_breaker
run_test test_fix_change5_before_task_set_failed
run_test test_fix_change5_pid_cleanup
run_test test_fix_scenario_b_worktree_error
run_test test_fix_scenario_c_lock_escalation
run_test test_fix_scenario_c_conflict_escalation
run_test test_run_lock_release_before_refresh

echo ""
echo "retry.sh"
run_test test_retry_context_required
run_test test_fix_retry_dead_code_fixed
run_test test_fix_retry_blocked_handler
run_test test_retry_branch_audit_exists

echo ""
echo "tasks.sh"
run_test test_tasks_reset_pending_increments_retry
run_test test_fix_tasks_clears_gate_results
run_test test_fix_tasks_clears_criteria_detail
run_test test_tasks_timeout_increments_timeout_count
run_test test_tasks_timeout_sets_failed

echo ""
echo "gates.sh — Scenario A"
run_test test_fix_gates_quality_checks_variable
run_test test_fix_gates_syntax_captured
run_test test_fix_gates_quality_persisted
run_test test_fix_gates_failure_output_captured

echo ""
echo "Behavioral claims"
run_test test_claim_failed_tasks_not_auto_retried

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
exit $([[ $FAIL -eq 0 ]] && echo 0 || echo 1)
