#!/usr/bin/env bash
# test_integrate.sh — End-to-end tests for `speed integrate` (feature mode).
#
# Each test builds a throwaway git project with two done tasks and runs the
# real speed script. A fake `claude` on PATH stands in for the Integrator and
# Guardian agents, so no model is called.
#
# Usage: bash tests/test_integrate.sh
# Exit: 0 if all tests pass, 1 if any fail

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEED_BIN="${SCRIPT_DIR}/../speed"
PASS=0
FAIL=0
WORK=""

# Harness

setup() {
    WORK=$(mktemp -d)
    local project="${WORK}/project" bin="${WORK}/bin"
    mkdir -p "$project" "$bin"

    # Fake agent CLI. FAKE_MERGE=all merges every listed branch; FAKE_MERGE=skip-last
    # leaves the last one out. FAKE_GUARDIAN sets the Guardian status.
    cat > "${bin}/claude" <<'FAKE'
#!/bin/bash
[[ "${1:-}" == "--version" ]] && { echo "fake 0"; exit 0; }
prompt=$(cat)
result='{}'
if grep -q "## Integration Task" <<< "$prompt"; then
    dir=$(awk '/^### Working Directory/{getline; print; exit}' <<< "$prompt")
    target=$(grep -m1 -oE 'Merge the following branches into [^,]+' <<< "$prompt" | sed 's/.* into //')
    list=$(awk '/^Merge the following branches/{f=1;next} /^### Working Directory/{f=0} f && /^- /{sub(/^- /,""); print}' <<< "$prompt")
    [[ "${FAKE_MERGE:-all}" == "skip-last" ]] && list=$(sed '$d' <<< "$list")
    cd "$dir" && git checkout -q "$target"
    while IFS= read -r b; do
        [[ -n "$b" ]] && git merge -q --no-ff -m "Merge $b" "$b" >/dev/null 2>&1
    done <<< "$list"
    result='{"merged_branches":[],"conflicts_resolved":[],"failed_merges":[],"test_results":"not_configured"}'
elif grep -qi "product vision" <<< "$prompt"; then
    result="{\"status\":\"${FAKE_GUARDIAN:-aligned}\",\"summary\":\"fake\",\"flags\":[]}"
fi
jq -cn --arg r "$result" '{type:"result",subtype:"success",is_error:false,result:$r,usage:{input_tokens:0,output_tokens:0}}'
FAKE
    chmod +x "${bin}/claude"
    export PATH="${bin}:${PATH}"

    cd "$project"
    git init -q -b main
    git config user.email test@example.com
    git config user.name test
    echo base > base.txt && git add . && git commit -qm base
    git checkout -qb speed/demo/task-1 && echo one > one.txt && git add . && git commit -qm one
    git checkout -qb speed/demo/task-2 && echo two > two.txt && git add . && git commit -qm two
    git checkout -q main

    local feature=".speed/features/demo"
    mkdir -p "${feature}/tasks" "${feature}/logs"
    echo '{"status":"idle","agents":[],"started_at":null}' > .speed/state.json
    echo '{"status":"idle"}' > "${feature}/state.json"
    echo demo > .speed/active_feature
    echo '{"id":"1","title":"one","status":"done","branch":"speed/demo/task-1","depends_on":[]}' > "${feature}/tasks/1.json"
    echo '{"id":"2","title":"two","status":"done","branch":"speed/demo/task-2","depends_on":["1"]}' > "${feature}/tasks/2.json"
}

teardown() {
    cd /
    [[ -n "$WORK" ]] && rm -rf "$WORK"
}

gates() {
    printf '# Project\n\n## Quality Gates\n\n- test: `%s`\n' "$1" > "${WORK}/project/AGENTS.md"
}

run_integrate() {
    OUTPUT=$(SPEED_NO_TTY=1 SPEED_DIR="${SCRIPT_DIR}/.." "$SPEED_BIN" integrate --feature demo "$@" < /dev/null 2>&1)
    RC=$?
}

feature_status() {
    jq -r '.status' "${WORK}/project/.speed/features/demo/state.json"
}

check() {
    local name="$1" condition="$2"
    if eval "$condition"; then
        PASS=$((PASS + 1)); echo "  ✓ ${name}"
    else
        FAIL=$((FAIL + 1)); echo "  ✗ ${name}"; echo "$OUTPUT" | tail -15 | sed 's/^/      /'
    fi
}

# Tests

test_all_branches_merged_and_checks_pass() {
    setup; gates "true"
    SKIP_GUARDIAN=true run_integrate
    check "exits 0 when everything passes" '[[ $RC -eq 0 ]]'
    check "verifies the merges in git" 'grep -q "Verified in git: all 2 branches" <<< "$OUTPUT"'
    check "marks the feature complete" '[[ "$(feature_status)" == completed ]]'
    check "skips observation extraction without a terminal" 'grep -q "No terminal, so skipping observation extraction" <<< "$OUTPUT"'
    check "prints a summary with the result" 'grep -q "Integration summary" <<< "$OUTPUT" && grep -q "Result .*Feature complete" <<< "$OUTPUT"'
    check "shows the skipped guardian" 'grep -q "Guardian check skipped (SKIP_GUARDIAN=true)" <<< "$OUTPUT"'
    check "keeps the agent report out of the terminal" '! grep -q "merged_branches" <<< "$OUTPUT"'
    teardown
}

test_unmerged_branch_stops_integration() {
    setup; gates "true"
    FAKE_MERGE=skip-last SKIP_GUARDIAN=true run_integrate
    check "exits with the merge-conflict code" '[[ $RC -eq 4 ]]'
    check "names the branch that is missing" 'grep -q "speed/demo/task-2" <<< "$OUTPUT" && grep -q "1 of 2 branches are not in main" <<< "$OUTPUT"'
    check "leaves the feature incomplete" '[[ "$(feature_status)" != completed ]]'
    teardown
}

test_failing_regression_stops_completion() {
    setup; gates "false"
    SKIP_GUARDIAN=true run_integrate
    check "exits with the gate-failure code" '[[ $RC -eq 2 ]]'
    check "reports which check failed" 'grep -q "Integration checks failed: regression tests" <<< "$OUTPUT"'
    check "leaves the feature incomplete" '[[ "$(feature_status)" != completed ]]'
    teardown
}

test_guardian_rejection_stops_completion() {
    setup; gates "true"
    mkdir -p "${WORK}/project/specs/product"
    echo "# Overview" > "${WORK}/project/specs/product/overview.md"
    FAKE_GUARDIAN=rejected run_integrate
    check "exits with the gate-failure code" '[[ $RC -eq 2 ]]'
    check "reports the guardian failure" 'grep -q "Integration checks failed: guardian" <<< "$OUTPUT"'
    check "leaves the feature incomplete" '[[ "$(feature_status)" != completed ]]'
    teardown
}

test_missing_gates_are_reported_not_passed() {
    setup
    SKIP_GUARDIAN=true run_integrate
    check "warns that nothing was tested" 'grep -q "No quality gates configured, so regression checked nothing" <<< "$OUTPUT"'
    check "does not claim the tests passed" '! grep -q "Regression tests passed" <<< "$OUTPUT"'
    teardown
}

test_rerun_skips_merged_branches() {
    setup; gates "true"
    SKIP_GUARDIAN=true run_integrate
    SKIP_GUARDIAN=true run_integrate
    check "second run exits 0" '[[ $RC -eq 0 ]]'
    check "second run reports the merged branches in one line" 'grep -q "2 of 2 branches already merged into main" <<< "$OUTPUT" && ! grep -q "task-1 already merged" <<< "$OUTPUT"'
    check "second run says the feature was already complete" 'grep -q "Already complete; re-verified" <<< "$OUTPUT"'
    teardown
}

test_other_target_branch_needs_confirmation() {
    setup; gates "true"
    git -C "${WORK}/project" checkout -qb work
    SKIP_GUARDIAN=true run_integrate
    check "refuses without a terminal to confirm" '[[ $RC -eq 1 ]] && grep -q "No terminal to confirm" <<< "$OUTPUT"'
    check "merges nothing when it refuses" '! git -C "${WORK}/project" merge-base --is-ancestor speed/demo/task-1 main'
    SKIP_GUARDIAN=true run_integrate --yes
    check "merges into main with --yes" '[[ $RC -eq 0 ]] && git -C "${WORK}/project" merge-base --is-ancestor speed/demo/task-2 main'
    teardown
}

test_checks_run_on_the_target_branch() {
    setup; gates "test -f two.txt"
    SKIP_GUARDIAN=true run_integrate
    git -C "${WORK}/project" checkout -qb old "$(git -C "${WORK}/project" rev-list --max-parents=0 HEAD)"
    SKIP_GUARDIAN=true run_integrate --yes
    check "switches to the target branch for the checks" 'grep -q "Checked out .main. to run the checks" <<< "$OUTPUT"'
    check "checks see the integrated code" '[[ $RC -eq 0 ]] && [[ "$(git -C "${WORK}/project" branch --show-current)" == main ]]'
    git -C "${WORK}/project" checkout -q old
    echo change >> "${WORK}/project/base.txt"
    SKIP_GUARDIAN=true run_integrate --yes
    check "refuses to switch with uncommitted changes" '[[ $RC -eq 1 ]] && grep -q "uncommitted changes" <<< "$OUTPUT" && [[ "$(git -C "${WORK}/project" branch --show-current)" == old ]]'
    teardown
}

test_detached_head_needs_confirmation() {
    setup; gates "true"
    git -C "${WORK}/project" checkout -q --detach main
    SKIP_GUARDIAN=true run_integrate
    check "refuses on a detached HEAD without confirmation" '[[ $RC -eq 1 ]] && grep -q "You are on a detached HEAD" <<< "$OUTPUT"'
    check "merges nothing on a detached HEAD" '! git -C "${WORK}/project" merge-base --is-ancestor speed/demo/task-1 main'
    teardown
}

test_deleted_merged_branches_count_as_merged() {
    setup; gates "true"
    SKIP_GUARDIAN=true run_integrate
    git -C "${WORK}/project" branch -q -d speed/demo/task-1 speed/demo/task-2
    SKIP_GUARDIAN=true run_integrate
    check "counts merged-then-deleted branches as merged" '[[ $RC -eq 0 ]] && grep -q "2 of 2 branches already merged" <<< "$OUTPUT"'
    check "does not warn about them" '! grep -q "have no branch" <<< "$OUTPUT"'
    teardown
}

test_guardian_without_overview_is_reported_skipped() {
    setup; gates "true"
    run_integrate
    check "says the guardian was skipped for want of an overview" 'grep -q "Guardian check skipped (no product overview" <<< "$OUTPUT"'
    check "does not claim the guardian approved" '! grep -q "aligned" <<< "$OUTPUT"'
    teardown
}

test_missing_target_branch_is_refused() {
    setup; gates "true"
    MAIN_BRANCH=nope SKIP_GUARDIAN=true run_integrate
    check "refuses a target branch that does not exist" '[[ $RC -eq 1 ]] && grep -q "Target branch .nope. does not exist" <<< "$OUTPUT"'
    check "merges nothing" '! git -C "${WORK}/project" merge-base --is-ancestor speed/demo/task-1 main'
    teardown
}

test_uncommitted_changes_are_refused_before_merging() {
    setup; gates "true"
    echo change >> "${WORK}/project/base.txt"
    SKIP_GUARDIAN=true run_integrate
    check "refuses with uncommitted changes" '[[ $RC -eq 1 ]] && grep -q "uncommitted changes" <<< "$OUTPUT"'
    check "merges nothing" '! git -C "${WORK}/project" merge-base --is-ancestor speed/demo/task-1 main'
    teardown
}

test_target_checked_out_elsewhere_is_refused() {
    setup; gates "true"
    git -C "${WORK}/project" checkout -qb work
    git -C "${WORK}/project" worktree add -q "${WORK}/other" main
    SKIP_GUARDIAN=true run_integrate --yes
    check "refuses when the target is checked out in another worktree" '[[ $RC -eq 1 ]] && grep -q "checked out in another worktree" <<< "$OUTPUT"'
    check "merges nothing" '! git -C "${WORK}/project" merge-base --is-ancestor speed/demo/task-1 main'
    teardown
}

test_rerun_keeps_the_first_completion_time() {
    setup; gates "true"
    SKIP_GUARDIAN=true run_integrate
    local first; first=$(jq -r .completed_at "${WORK}/project/.speed/features/demo/state.json")
    sleep 1
    SKIP_GUARDIAN=true run_integrate
    check "keeps completed_at from the first completion" '[[ "$(jq -r .completed_at "${WORK}/project/.speed/features/demo/state.json")" == "$first" ]]'
    teardown
}

test_done_task_without_branch_is_reported() {
    setup; gates "true"
    git -C "${WORK}/project" branch -q -D speed/demo/task-2
    SKIP_GUARDIAN=true run_integrate
    check "warns about the task with no branch" 'grep -q "1 done tasks have no branch" <<< "$OUTPUT" && grep -q "2: speed/demo/task-2" <<< "$OUTPUT"'
    teardown
}

echo "integrate"
test_all_branches_merged_and_checks_pass
test_unmerged_branch_stops_integration
test_failing_regression_stops_completion
test_guardian_rejection_stops_completion
test_missing_gates_are_reported_not_passed
test_rerun_skips_merged_branches
test_other_target_branch_needs_confirmation
test_checks_run_on_the_target_branch
test_detached_head_needs_confirmation
test_deleted_merged_branches_count_as_merged
test_guardian_without_overview_is_reported_skipped
test_missing_target_branch_is_refused
test_uncommitted_changes_are_refused_before_merging
test_target_checked_out_elsewhere_is_refused
test_rerun_keeps_the_first_completion_time
test_done_task_without_branch_is_reported

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ $FAIL -eq 0 ]]
