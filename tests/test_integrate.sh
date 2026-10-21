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
    target=$(grep -m1 -oE 'branches into [^,]+' <<< "$prompt" | sed 's/branches into //')
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
    OUTPUT=$(SPEED_DIR="${SCRIPT_DIR}/.." "$SPEED_BIN" integrate --feature demo "$@" < /dev/null 2>&1)
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
    check "second run skips the merged branches" 'grep -q "All branches already merged" <<< "$OUTPUT"'
    teardown
}

echo "integrate"
test_all_branches_merged_and_checks_pass
test_unmerged_branch_stops_integration
test_failing_regression_stops_completion
test_guardian_rejection_stops_completion
test_missing_gates_are_reported_not_passed
test_rerun_skips_merged_branches

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ $FAIL -eq 0 ]]
