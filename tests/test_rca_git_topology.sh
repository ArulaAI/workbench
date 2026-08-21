#!/usr/bin/env bash
# test_rca_git_topology.sh — Verify git topology claims from rca-perpetual-task-failure-loops.md
#
# Tests the core git mechanics that cause Scenario 1 (empty diff after refresh):
#   - --is-ancestor flips after --no-ff refresh
#   - merge-base lands at main tip after refresh
#   - fork-point diff becomes empty after refresh
#   - branch_audit returns "pass" before refresh, "empty" after
#
# Usage: bash tests/test_rca_git_topology.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

PASS=0
FAIL=0
TEST_DIR=""

# ── Harness ───────────────────────────────────────────────────────

setup() {
    TEST_DIR=$(mktemp -d)
    cd "$TEST_DIR"
    git init -q
    git checkout -q -b main
    echo "initial" > file.txt
    git add file.txt
    git commit -q -m "A: initial commit"
}

teardown() {
    cd /
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

# ── Test: --is-ancestor holds for merged branch ──────────────────

test_ancestor_holds_after_merge() {
    # Simulate: agent commits on task branch, branch gets merged into main
    git checkout -q -b task-11 main
    echo "agent work" > agent_file.py
    git add agent_file.py
    git commit -q -m "b6a358e: agent commits task-11 work"

    git checkout -q main
    git merge -q --no-ff task-11 -m "d88971d: merge task-11 into main"

    # RCA claim: --is-ancestor task-11 main → YES
    if ! git merge-base --is-ancestor task-11 main; then
        echo "    ASSERT: task-11 should be ancestor of main after merge"
        return 1
    fi
}

# ── Test: --is-ancestor holds even after main advances ───────────

test_ancestor_holds_after_main_advances() {
    git checkout -q -b task-11 main
    echo "agent work" > agent_file.py
    git add agent_file.py
    git commit -q -m "agent work"

    git checkout -q main
    git merge -q --no-ff task-11 -m "merge task-11"

    # Simulate 20 more commits on main from other tasks
    for i in $(seq 1 5); do
        echo "other work $i" > "other_${i}.py"
        git add "other_${i}.py"
        git commit -q -m "other task commit $i"
    done

    # RCA claim: --is-ancestor task-11 main → YES even after main advances
    if ! git merge-base --is-ancestor task-11 main; then
        echo "    ASSERT: task-11 should still be ancestor of main after main advances"
        return 1
    fi
}

# ── Test: --no-ff refresh flips --is-ancestor to false ───────────

test_refresh_defeats_ancestor_check() {
    # Create task branch, merge into main, advance main, then refresh
    git checkout -q -b task-11 main
    echo "agent work" > agent_file.py
    git add agent_file.py
    git commit -q -m "agent work on task-11"

    git checkout -q main
    git merge -q --no-ff task-11 -m "merge task-11 into main"

    # Advance main
    echo "other work" > other.py
    git add other.py
    git commit -q -m "other work on main"

    # Verify ancestor BEFORE refresh
    if ! git merge-base --is-ancestor task-11 main; then
        echo "    ASSERT: task-11 should be ancestor before refresh"
        return 1
    fi

    # Refresh: merge main into task-11 with --no-ff
    git checkout -q task-11
    git merge -q --no-ff main -m "speed: refresh branch against main"
    git checkout -q main

    # RCA claim: --is-ancestor task-11 main → NO after refresh
    if git merge-base --is-ancestor task-11 main 2>/dev/null; then
        echo "    ASSERT: task-11 should NOT be ancestor of main after refresh"
        return 1
    fi
}

# ── Test: fork-point diff is empty after refresh ─────────────────

test_fork_point_diff_empty_after_refresh() {
    # Replicate the exact topology from RCA Task 11 timeline
    git checkout -q -b task-11 main
    echo "agent work" > agent_file.py
    git add agent_file.py
    git commit -q -m "agent work"

    git checkout -q main
    git merge -q --no-ff task-11 -m "merge task-11"

    # Advance main
    echo "more work" > more.py
    git add more.py
    git commit -q -m "more work"

    # Refresh
    git checkout -q task-11
    git merge -q --no-ff main -m "speed: refresh"
    git checkout -q main

    # Compute fork point (merge-base)
    local fork_point
    fork_point=$(git merge-base main task-11)

    # RCA claim: fork_point is main's tip after refresh
    local main_tip
    main_tip=$(git rev-parse main)
    if [[ "$fork_point" != "$main_tip" ]]; then
        echo "    ASSERT: fork_point ($fork_point) should equal main tip ($main_tip) after refresh"
        return 1
    fi

    # RCA claim: diff fork_point..task-11 --name-only is empty
    local agent_diff
    agent_diff=$(git diff "${fork_point}..task-11" --name-only 2>/dev/null || true)
    if [[ -n "$agent_diff" ]]; then
        echo "    ASSERT: fork-point diff should be empty after refresh, got: $agent_diff"
        return 1
    fi
}

# ── Test: three-dot diff is also empty after refresh ─────────────

test_three_dot_diff_empty_after_refresh() {
    git checkout -q -b task-11 main
    echo "agent work" > agent_file.py
    git add agent_file.py
    git commit -q -m "agent work"

    git checkout -q main
    git merge -q --no-ff task-11 -m "merge task-11"

    echo "more" > more.py
    git add more.py
    git commit -q -m "more"

    git checkout -q task-11
    git merge -q --no-ff main -m "speed: refresh"
    git checkout -q main

    # RCA Scenario 8 claim: three-dot diff also empty
    local three_dot_diff
    three_dot_diff=$(git diff "main...task-11" --name-only 2>/dev/null || true)
    if [[ -n "$three_dot_diff" ]]; then
        echo "    ASSERT: three-dot diff should be empty after refresh, got: $three_dot_diff"
        return 1
    fi
}

# ── Test: branch_audit returns "pass" BEFORE refresh ─────────────

test_branch_audit_pass_before_refresh() {
    # Simulate: agent work merged into main, main advanced, NO refresh
    git checkout -q -b task-11 main
    echo "agent work" > agent_file.py
    git add agent_file.py
    git commit -q -m "agent work"

    git checkout -q main
    git merge -q --no-ff task-11 -m "merge task-11"

    echo "more" > more.py
    git add more.py
    git commit -q -m "more"

    # Before refresh: --is-ancestor should return true
    if ! git merge-base --is-ancestor task-11 main; then
        echo "    ASSERT: task-11 should be ancestor of main (pre-refresh)"
        return 1
    fi
    # branch_audit would return "pass" here (line 268-270 of grounding.sh)
}

# ── Test: squash merge defeats --is-ancestor ─────────────────────

test_squash_merge_defeats_ancestor() {
    git checkout -q -b task-11 main
    echo "agent work" > agent_file.py
    git add agent_file.py
    git commit -q -m "agent work"

    git checkout -q main
    git merge -q --squash task-11
    git commit -q -m "squash merge task-11"

    # RCA table: squash merge → no ancestor relationship
    if git merge-base --is-ancestor task-11 main 2>/dev/null; then
        echo "    ASSERT: squash merge should NOT preserve ancestor relationship"
        return 1
    fi
}

# ── Test: cherry-pick defeats --is-ancestor ──────────────────────

test_cherry_pick_defeats_ancestor() {
    git checkout -q -b task-11 main
    echo "agent work" > agent_file.py
    git add agent_file.py
    git commit -q -m "agent work"
    local task_commit
    task_commit=$(git rev-parse HEAD)

    git checkout -q main
    git cherry-pick -q "$task_commit"

    # RCA table: cherry-pick → no ancestor relationship
    if git merge-base --is-ancestor task-11 main 2>/dev/null; then
        echo "    ASSERT: cherry-pick should NOT preserve ancestor relationship"
        return 1
    fi
}

# ── Test: --ff merge preserves ancestor ──────────────────────────

test_ff_merge_preserves_ancestor() {
    # task branch is ahead of main, no divergence → fast-forward
    git checkout -q -b task-11 main
    echo "agent work" > agent_file.py
    git add agent_file.py
    git commit -q -m "agent work"

    git checkout -q main
    git merge -q --ff task-11

    # RCA table: ff merge → ancestor relationship exists
    if ! git merge-base --is-ancestor task-11 main; then
        echo "    ASSERT: ff merge should preserve ancestor relationship"
        return 1
    fi
}

# ── Test: blank branch from main satisfies --is-ancestor ─────────
# (RCA's rejected alternative: why standalone --is-ancestor fails)

test_blank_branch_is_ancestor_of_main() {
    # Create a branch from main's tip, no work done
    git checkout -q -b task-new main

    # The branch tip IS a commit on main → --is-ancestor returns true
    if ! git merge-base --is-ancestor task-new main; then
        echo "    ASSERT: blank branch tip should be ancestor of main (same commit)"
        return 1
    fi
    # This is the false positive: standalone --is-ancestor would mark
    # a zero-work branch as "pass" (done)
}

# ── Test: already-stuck branch still returns empty ───────────────
# (RCA Limitation: tasks whose branches were already refreshed)

test_already_stuck_branch_returns_empty() {
    git checkout -q -b task-11 main
    echo "agent work" > agent_file.py
    git add agent_file.py
    git commit -q -m "agent work"

    git checkout -q main
    git merge -q --no-ff task-11 -m "merge"

    echo "more" > more.py
    git add more.py
    git commit -q -m "more"

    # First refresh (simulates the poisoning that already happened)
    git checkout -q task-11
    git merge -q --no-ff main -m "speed: refresh"
    git checkout -q main

    # Now simulate what branch_audit sees WITHOUT a new refresh
    # --is-ancestor → NO (already poisoned)
    if git merge-base --is-ancestor task-11 main 2>/dev/null; then
        echo "    ASSERT: already-refreshed branch should NOT be ancestor"
        return 1
    fi

    # fork-point diff → empty
    local fork_point
    fork_point=$(git merge-base main task-11)
    local agent_diff
    agent_diff=$(git diff "${fork_point}..task-11" --name-only 2>/dev/null || true)
    if [[ -n "$agent_diff" ]]; then
        echo "    ASSERT: already-stuck branch should have empty fork-point diff, got: $agent_diff"
        return 1
    fi
    # branch_audit returns "empty" → task stays stuck even without new refresh
}

# ── Test: rebase defeats --is-ancestor ───────────────────────────

test_rebase_defeats_ancestor() {
    git checkout -q -b task-11 main
    echo "agent work" > agent_file.py
    git add agent_file.py
    git commit -q -m "agent work"

    # Advance main
    git checkout -q main
    echo "main work" > main_file.py
    git add main_file.py
    git commit -q -m "main work"

    # Rebase task onto main
    git checkout -q task-11
    git rebase -q main
    git checkout -q main

    # After rebase, new SHAs → no ancestor relationship from old branch name
    # Actually, rebase rewrites the branch, so task-11 now points to new commits
    # that ARE on top of main. Check: is task-11 still an ancestor of main?
    # After rebase, task-11 is AHEAD of main (main doesn't have the rebased commit)
    if git merge-base --is-ancestor task-11 main 2>/dev/null; then
        echo "    ASSERT: rebased branch (ahead of main) should NOT be ancestor of main"
        return 1
    fi
}

# ── Run ──────────────────────────────────────────────────────────

echo ""
echo "RCA Git Topology Verification"
echo "=============================="
echo ""

run_test test_ancestor_holds_after_merge
run_test test_ancestor_holds_after_main_advances
run_test test_refresh_defeats_ancestor_check
run_test test_fork_point_diff_empty_after_refresh
run_test test_three_dot_diff_empty_after_refresh
run_test test_branch_audit_pass_before_refresh
run_test test_squash_merge_defeats_ancestor
run_test test_cherry_pick_defeats_ancestor
run_test test_ff_merge_preserves_ancestor
run_test test_blank_branch_is_ancestor_of_main
run_test test_already_stuck_branch_returns_empty
run_test test_rebase_defeats_ancestor

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
exit $([[ $FAIL -eq 0 ]] && echo 0 || echo 1)
