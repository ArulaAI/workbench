#!/usr/bin/env bash
# test_grounding_fork_point.sh — Regression test for the task-base fork-point bug
#
# grounding.sh's scope/coverage/declared-files checks used to diff every task
# branch against git_main_branch() to find the branch's fork point. That is
# only correct when task branches are cut directly from the repo's main
# branch. git_create_worktree() actually bases every task branch on whatever
# is HEAD in the main checkout at creation time (`git worktree add -b`), and
# that checkout never moves again for the rest of the run — so the real base
# is not always main. A long-lived integration/course branch that has itself
# diverged from main (its own baseline commits, merges, spec reshaping, etc.)
# is a normal case, and diffing against main there sweeps every one of those
# unrelated commits into what looks like the task's own diff, false-positive
# failing scope and test-coverage checks on every single task cut from it.
#
# git_task_base_branch() (lib/git.sh) fixes this by resolving to
# git_current_branch() instead of git_main_branch(). This test proves the
# fix: a task branched from a base that has diverged heavily from main must
# not see that divergence as its own scope violation.
#
# Usage: bash tests/test_grounding_fork_point.sh
# Exit: 0 if all tests pass, 1 if any fail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
PASS=0
FAIL=0
TEST_DIR=""

setup() {
    TEST_DIR=$(mktemp -d)

    COLOR_ERROR="" COLOR_WARN="" COLOR_DIM="" COLOR_SUCCESS="" COLOR_STEP=""
    BOLD="" RESET="" SYM_CHECK="" SYM_CROSS="" SYM_WARN="" SYM_ARROW=""
    VERBOSITY=0

    log_error()   { :; }
    log_warn()    { :; }
    log_step()    { :; }
    log_success() { :; }
    _context_python() { echo "python3"; }

    export PROJECT_ROOT="$TEST_DIR/repo"
    mkdir -p "$PROJECT_ROOT"
    git -C "$PROJECT_ROOT" init -b main --quiet
    git -C "$PROJECT_ROOT" config user.email "test@test.com"
    git -C "$PROJECT_ROOT" config user.name "Test"

    echo "init" > "$PROJECT_ROOT/README.md"
    git -C "$PROJECT_ROOT" add README.md
    git -C "$PROJECT_ROOT" commit -m "init" --quiet

    export STATE_DIR="${PROJECT_ROOT}/.speed"
    export FEATURES_DIR="${STATE_DIR}/features"
    export TASKS_DIR="${STATE_DIR}/tasks"
    export LOGS_DIR="${STATE_DIR}/logs"
    mkdir -p "$TASKS_DIR" "$LOGS_DIR"

    unset MAIN_BRANCH 2>/dev/null || true

    # Real git helpers, not stubs — the fix is in these.
    # shellcheck source=../lib/git.sh
    source "${LIB_DIR}/git.sh"

    unset _GROUNDING_SH_LOADED 2>/dev/null || true
    # shellcheck source=../lib/grounding.sh
    source "${LIB_DIR}/grounding.sh"
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

assert_equals() {
    local expected="$1" actual="$2" context="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        echo "    ASSERT: expected '${expected}', got '${actual}'${context:+ (${context})}" >&2
        return 1
    fi
}

# ── Scenario setup: a base branch (like round-0) that has diverged heavily
# from main, with a task branch cut from its tip ──────────────────────────
_diverge_base_branch_from_main() {
    local base_branch="$1"
    git -C "$PROJECT_ROOT" checkout -b "$base_branch" --quiet

    # Several unrelated commits, simulating a long-lived branch's own history
    # (spec reshaping, baseline commits, merges — none of it task work).
    echo "a" > "$PROJECT_ROOT/unrelated-1.txt"
    git -C "$PROJECT_ROOT" add unrelated-1.txt
    git -C "$PROJECT_ROOT" commit -m "unrelated baseline commit 1" --quiet

    mkdir -p "$PROJECT_ROOT/.speed/features/x/logs"
    echo "b" > "$PROJECT_ROOT/.speed/features/x/logs/audit.jsonl"
    echo "c" > "$PROJECT_ROOT/speed.toml"
    git -C "$PROJECT_ROOT" add .speed speed.toml
    git -C "$PROJECT_ROOT" commit -m "unrelated baseline commit 2 (tool state)" --quiet
}

_create_task_branch_from_current() {
    local task_id="$1" branch_name="$2"
    shift 2
    local files_touched_json="["
    local first=true

    git -C "$PROJECT_ROOT" checkout -b "$branch_name" --quiet

    for file_path in "$@"; do
        mkdir -p "$(dirname "$PROJECT_ROOT/$file_path")"
        echo "// content of $file_path" > "$PROJECT_ROOT/$file_path"
        git -C "$PROJECT_ROOT" add "$file_path"
        if $first; then
            files_touched_json+="\"${file_path}\""
            first=false
        else
            files_touched_json+=", \"${file_path}\""
        fi
    done
    git -C "$PROJECT_ROOT" commit -m "task ${task_id} work" --quiet
    files_touched_json+="]"

    cat > "${TASKS_DIR}/${task_id}.json" <<EOF
{
  "id": "${task_id}",
  "branch": "${branch_name}",
  "status": "running",
  "files_touched": ${files_touched_json}
}
EOF
}

# ── Tests ───────────────────────────────────────────────────────────────

test_task_base_branch_resolves_to_current_not_main() {
    _diverge_base_branch_from_main "round-0"
    assert_equals "round-0" "$(git_task_base_branch)" "should resolve to the checked-out base, not main"
}

test_scope_check_ignores_base_branch_divergence() {
    _diverge_base_branch_from_main "round-0"
    _create_task_branch_from_current "1" "task/1-work" "src/feature.ts"

    # Main checkout never moves off the base branch during a real run —
    # only an isolated worktree holds the task branch.
    git -C "$PROJECT_ROOT" checkout round-0 --quiet

    local result rc=0
    result=$(grounding_check_scope "1") || rc=$?
    assert_equals "0" "$rc" "round-0's own divergence from main must not count against task 1 (undeclared: ${result})"
}

test_declared_files_check_finds_file_on_diverged_branch() {
    _diverge_base_branch_from_main "round-0"
    _create_task_branch_from_current "1" "task/1-work" "src/feature.ts"
    git -C "$PROJECT_ROOT" checkout round-0 --quiet

    local result rc=0
    result=$(grounding_check_declared_files "1") || rc=$?
    assert_equals "0" "$rc" "declared file genuinely present on the branch must pass"
}

test_scope_check_still_catches_real_undeclared_files() {
    _diverge_base_branch_from_main "round-0"
    _create_task_branch_from_current "1" "task/1-work" "src/feature.ts" "src/extra-1.ts" "src/extra-2.ts" "src/extra-3.ts"
    git -C "$PROJECT_ROOT" checkout round-0 --quiet

    # files_touched only declared src/feature.ts; the other three are real
    # undeclared scope creep by the agent and must still be caught.
    local result rc=0
    result=$(grounding_check_scope "1") || rc=$?
    assert_equals "2" "$rc" "genuinely undeclared files from the task itself must still fail scope"
}

echo "Running grounding fork-point regression tests..."
echo ""

run_test test_task_base_branch_resolves_to_current_not_main
run_test test_scope_check_ignores_base_branch_divergence
run_test test_declared_files_check_finds_file_on_diverged_branch
run_test test_scope_check_still_catches_real_undeclared_files

echo ""
echo "──────────────────────────────────────"
echo "Results: ${PASS} passed, ${FAIL} failed"

[[ $FAIL -eq 0 ]]
