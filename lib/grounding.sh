#!/usr/bin/env bash
# grounding.sh — Non-LLM verification gates
#
# These checks use scripts, not LLMs, to verify facts.
# A script can't be bullshitted. That's the point.

# Requires config.sh and log.sh to be sourced first

# ── Grounding Gate: run all non-LLM checks on a completed task ────

grounding_run() {
    local task_id="$1"
    local worktree_path="${2:-$PROJECT_ROOT}"
    local all_passed=true
    local results=()
    local task_json="${TASKS_DIR}/${task_id}.json"

    # gate_results: structured JSON for failure classification
    local gate_checks='[]'
    local gate_scope='{}'

    log_step "Running grounding checks for task ${task_id}..."

    # Check 1: Diff is non-empty
    grounding_check_diff_nonempty "$task_id"
    local diff_rc=$?
    if [[ $diff_rc -eq 0 ]]; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} Non-empty diff${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"diff_non_empty","status":"pass"}]')
    elif [[ $diff_rc -eq 2 ]]; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} Diff absorbed — agent work already on integration branch${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"diff_non_empty","status":"pass","absorbed":true}]')
    else
        results+=("${COLOR_ERROR}${SYM_CROSS} Empty diff — agent produced no code changes${RESET}")
        all_passed=false
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"diff_non_empty","status":"fail"}]')
    fi

    # Check 2: Declared files exist
    local declared_result
    declared_result=$(grounding_check_declared_files "$task_id")
    local declared_exit=$?
    if [[ $declared_exit -eq 0 ]]; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} Declared files exist${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"declared_files","status":"pass"}]')
    else
        results+=("${COLOR_ERROR}${SYM_CROSS} Missing declared files: ${declared_result}${RESET}")
        all_passed=false
        local mf_json='[]'
        local IFS_SAVE="$IFS"; IFS=','
        for mf in $declared_result; do
            mf=$(echo "$mf" | sed 's/^[[:space:]]*//')
            mf_json=$(echo "$mf_json" | jq --arg v "$mf" '. + [$v]')
        done
        IFS="$IFS_SAVE"
        gate_checks=$(echo "$gate_checks" | jq --argjson mf "$mf_json" '. + [{"name":"declared_files","status":"fail","missing_files":$mf}]')
    fi

    # Check 3: Scope check (files touched vs declared)
    # Graduated enforcement: 1-2 undeclared = warning, 3+ = hard failure
    # Escape hatch: SCOPE_STRICT=false in speed.toml reverts to warning-only
    local scope_result
    scope_result=$(grounding_check_scope "$task_id")
    local scope_exit=$?
    if [[ $scope_exit -eq 0 ]]; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} Scope check${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"scope","status":"pass"}]')
    elif [[ $scope_exit -eq 1 ]]; then
        results+=("${COLOR_ERROR}${SYM_CROSS} Scope: modified file(s) owned by another task: ${scope_result}${RESET}")
        all_passed=false
        # Parse ownership violations into JSON array
        local ov_json='[]'
        local IFS_SAVE="$IFS"
        IFS=','
        for ov in $scope_result; do
            ov=$(echo "$ov" | sed 's/^[[:space:]]*//')
            ov_json=$(echo "$ov_json" | jq --arg v "$ov" '. + [$v]')
        done
        IFS="$IFS_SAVE"
        gate_checks=$(echo "$gate_checks" | jq --argjson ov "$ov_json" '. + [{"name":"scope","status":"fail","ownership_violations":$ov}]')
        gate_scope=$(echo "$gate_scope" | jq --argjson ov "$ov_json" '.ownership_violations = $ov')
    elif [[ $scope_exit -eq 2 ]]; then
        # Count undeclared files
        local undeclared_count
        undeclared_count=$(echo "$scope_result" | tr ',' '\n' | wc -l | tr -d ' ')
        local scope_strict
        scope_strict=$(toml_get_value "scope_strict" "true")

        # Parse undeclared files into JSON array
        local ud_json='[]'
        local IFS_SAVE="$IFS"
        IFS=','
        for ud in $scope_result; do
            ud=$(echo "$ud" | sed 's/^[[:space:]]*//')
            ud_json=$(echo "$ud_json" | jq --arg v "$ud" '. + [$v]')
        done
        IFS="$IFS_SAVE"

        if [[ "$scope_strict" == "false" ]] || [[ $undeclared_count -le 2 ]]; then
            results+=("${COLOR_WARN}${SYM_WARN} Scope: ${undeclared_count} undeclared file(s): ${scope_result}${RESET}")
            gate_checks=$(echo "$gate_checks" | jq --argjson ud "$ud_json" '. + [{"name":"scope","status":"warn","undeclared_files":$ud}]')
            # Warning only — cascading fixes are acceptable
        else
            results+=("${COLOR_ERROR}${SYM_CROSS} Scope: ${undeclared_count} undeclared files (>2 = hard failure): ${scope_result}${RESET}")
            all_passed=false
            gate_checks=$(echo "$gate_checks" | jq --argjson ud "$ud_json" '. + [{"name":"scope","status":"fail","undeclared_files":$ud}]')
        fi
        gate_scope=$(echo "$gate_scope" | jq --argjson ud "$ud_json" '.undeclared_files = $ud')
    else
        results+=("${COLOR_ERROR}${SYM_CROSS} Scope check failed${RESET}")
        all_passed=false
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"scope","status":"fail"}]')
    fi

    # Check 4: Python import verification
    if grounding_check_python_imports "$task_id" "$worktree_path"; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} Python imports resolve${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"python_imports","status":"pass"}]')
    else
        results+=("${COLOR_WARN}${SYM_WARN} Unresolved Python imports detected${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"python_imports","status":"warn"}]')
        # Warning — imports might resolve at runtime with installed packages
    fi

    # Check 5: Check for blocked status in agent output
    if grounding_check_not_blocked "$task_id"; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} Agent completed (not blocked)${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"not_blocked","status":"pass"}]')
    else
        results+=("${COLOR_ERROR}${SYM_CROSS} Agent reported blocked status${RESET}")
        all_passed=false
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"not_blocked","status":"fail"}]')
    fi

    # Check 6: Test file coverage
    local coverage_result
    coverage_result=$(grounding_check_test_coverage "$task_id")
    local coverage_exit=$?
    if [[ $coverage_exit -eq 0 ]]; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} Test file coverage${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"test_coverage","status":"pass"}]')
    elif _test_files_covered_by_siblings "$task_id"; then
        results+=("${COLOR_WARN}${SYM_WARN} Test coverage deferred to sibling tasks${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"test_coverage","status":"warn","note":"deferred to sibling tasks"}]')
    else
        results+=("${COLOR_ERROR}${SYM_CROSS} Missing test files: ${coverage_result}${RESET}")
        all_passed=false
        local uf_json='[]'
        local IFS_SAVE="$IFS"; IFS=','
        for uf in $coverage_result; do
            uf=$(echo "$uf" | sed 's/^[[:space:]]*//')
            uf_json=$(echo "$uf_json" | jq --arg v "$uf" '. + [$v]')
        done
        IFS="$IFS_SAVE"
        gate_checks=$(echo "$gate_checks" | jq --argjson uf "$uf_json" '. + [{"name":"test_coverage","status":"fail","uncovered_files":$uf}]')
    fi

    # Check 7: Gate invocation evidence (informational)
    # The orchestrator runs authoritative quality gates (syntax, lint, typecheck,
    # tests) immediately after grounding. This check verifies the agent also ran
    # gates during development, but can't reliably detect it from the agent's
    # summary text. Logged for observability, not a hard failure.
    if grounding_check_gate_evidence "$task_id"; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} Gate evidence (agent ran quality gates)${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"gate_evidence","status":"pass"}]')
    else
        results+=("${COLOR_WARN}${SYM_WARN} No gate invocation evidence in agent output${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"gate_evidence","status":"warn"}]')
    fi

    # Check 8: Criteria verification (NEW)
    # Calls lib/criteria_verify.py to verify structured acceptance criteria
    local criteria_result
    criteria_result=$(grounding_check_criteria "$task_id")
    local criteria_exit=$?
    if [[ $criteria_exit -eq 0 ]]; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} Criteria verification${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"criteria","status":"pass"}]')
    elif [[ $criteria_exit -eq 2 ]]; then
        # Some criteria unverifiable (manual) — not a failure
        results+=("${COLOR_WARN}${SYM_WARN} Criteria: some unverifiable (manual review needed)${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"criteria","status":"warn"}]')
    else
        results+=("${COLOR_ERROR}${SYM_CROSS} Criteria verification failed${RESET}")
        all_passed=false
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"criteria","status":"fail"}]')
        # Persist criteria detail so retry prompt can surface what failed
        if [[ -n "$criteria_result" ]]; then
            local tmp_cr; tmp_cr=$(mktemp) || true
            if [[ -n "$tmp_cr" ]]; then
                jq --argjson cr "$criteria_result" '.criteria_detail = $cr' "$task_json" > "$tmp_cr" 2>/dev/null \
                    && mv "$tmp_cr" "$task_json" || rm -f "$tmp_cr"
            fi
        fi
    fi

    # Check 9: Secrets scanner (HARD FAILURE)
    # Runs unconditionally — scans current file content from branch diff.
    if grounding_check_secrets "$task_id" "$worktree_path"; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} No committed secrets${RESET}")
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"secrets","status":"pass"}]')
    else
        results+=("${COLOR_ERROR}${SYM_CROSS} Committed secrets detected — pipeline blocked${RESET}")
        all_passed=false
        gate_checks=$(echo "$gate_checks" | jq '. + [{"name":"secrets","status":"fail"}]')
    fi

    # Print results
    echo ""
    echo -e "  ${BOLD}Grounding Checks:${RESET}"
    for r in "${results[@]}"; do
        echo -e "    $r"
    done
    echo ""

    # Persist gate_results to task JSON (non-fatal)
    if [[ -f "$task_json" ]]; then
        local gate_results_obj
        gate_results_obj=$(jq -n --argjson checks "$gate_checks" --argjson scope "$gate_scope" \
            '{"checks": $checks, "scope": $scope}')
        local tmp_gate
        tmp_gate=$(mktemp) || true
        if [[ -n "$tmp_gate" ]]; then
            jq --argjson gr "$gate_results_obj" '.gate_results = $gr' "$task_json" > "$tmp_gate" 2>/dev/null \
                && mv "$tmp_gate" "$task_json" \
                || rm -f "$tmp_gate"
        fi
    fi

    if $all_passed; then
        return 0
    else
        return 1
    fi
}

# ── Check: diff is non-empty ──────────────────────────────────────

grounding_check_diff_nonempty() {
    local task_id="$1"
    local task_json="${TASKS_DIR}/${task_id}.json"
    local branch
    branch=$(jq -r '.branch // empty' "$task_json")

    if [[ -z "$branch" ]] || [[ "$branch" == "null" ]]; then
        return 1
    fi

    local main_branch
    main_branch=$(git_main_branch)

    # Primary check: three-dot diff against integration branch.
    local diff
    diff=$(_git diff "${main_branch}...${branch}" --stat 2>/dev/null)

    if [[ -n "$diff" ]]; then
        return 0
    fi

    # Fallback: the three-dot diff is empty. Check whether the agent
    # committed work that was absorbed by downstream merges. Same
    # fork-point technique used by branch_audit() and the scope check.
    local fork_point
    fork_point=$(_git merge-base "$main_branch" "$branch" 2>/dev/null) || true

    if [[ -z "$fork_point" ]]; then
        return 1
    fi

    local agent_diff
    agent_diff=$(_git diff "${fork_point}..${branch}" --name-only 2>/dev/null) || true

    if [[ -n "$agent_diff" ]]; then
        return 2  # absorbed: agent did work, integration branch already has it
    fi

    return 1  # genuinely empty
}

# ── Branch audit: check for prior agent work on a task branch ─────
# Called during recovery to evaluate interrupted tasks without spawning
# a new agent. Uses merge-base to detect only the agent's commits,
# not commits the task branch inherited from git_main_branch().
#
# Always returns 0. Control flow is via stdout:
#   "empty" — no agent commits on the branch (or branch missing)
#   "pass"  — agent committed work and it passes all gates
#   "fail"  — agent committed work but gates fail
#
# Usage:
#   local result
#   result=$(branch_audit "$task_id")
#   case "$result" in
#       empty) task_reset_pending "$task_id" ;;
#       pass)  task_set_done "$task_id" ;;
#       fail)  task_set_failed "$task_id" "..." ;;
#   esac
branch_audit() {
    local task_id="$1"
    local task_json="${TASKS_DIR}/${task_id}.json"

    if [[ ! -f "$task_json" ]]; then
        echo "empty"
        return 0
    fi

    local branch
    branch=$(jq -r '.branch // empty' "$task_json" 2>/dev/null)

    if [[ -z "$branch" ]] || [[ "$branch" == "null" ]]; then
        echo "empty"
        return 0
    fi

    # Check the branch exists in git
    if ! git_branch_exists "$branch"; then
        echo "empty"
        return 0
    fi

    # Review-fix loop: if reviewer requested changes, return "empty" so the
    # run loop spawns an agent to address the feedback. Prior commits stay
    # on the branch — the agent works on top of them via the worktree.
    local review_verdict
    review_verdict=$(jq -r '.review_verdict // empty' "$task_json" 2>/dev/null)
    if [[ "$review_verdict" == "request_changes" ]]; then
        echo "empty"
        return 0
    fi

    # If the task branch is already merged into main, the work is integrated.
    # Without this, merge-base returns the branch tip, diff is empty,
    # and the run loop spawns a needless agent that redoes finished work.
    local main_branch
    main_branch=$(git_main_branch)
    if _git merge-base --is-ancestor "$branch" "$main_branch" 2>/dev/null; then
        echo "pass"
        return 0
    fi

    # Find the fork point: where this task branch diverged from main.
    # Stable even if main moves forward via deferred merges.
    local fork_point
    fork_point=$(_git merge-base "$main_branch" "$branch" 2>/dev/null) || true

    if [[ -z "$fork_point" ]]; then
        echo "empty"
        return 0
    fi

    # Two-dot diff: only commits reachable from $branch but not $fork_point.
    # Shows agent-only work, not inherited commits.
    local agent_diff
    agent_diff=$(_git diff "${fork_point}..${branch}" --name-only 2>/dev/null) || true

    if [[ -z "$agent_diff" ]]; then
        echo "empty"
        return 0
    fi

    # Agent committed work. Before overwriting the log, check the existing
    # log for blocked status. If the prior agent reported blocked before
    # being killed, that evidence should not be discarded.
    local output_file="${LOGS_DIR}/${task_id}.log"
    if [[ -f "$output_file" ]] && grep -q '"status"[[:space:]]*:[[:space:]]*"blocked"' "$output_file" 2>/dev/null; then
        log_warn "Task ${task_id}: prior agent reported blocked status before interruption"
        echo "blocked"
        return 0
    fi

    # Write a recovery log so grounding checks that read the agent output
    # log (checks 5 and 7) get accurate input instead of missing/stale data.
    echo '{"status":"recovery","note":"Branch audit — no agent session. Prior agent committed work before interruption."}' > "$output_file"

    # Create temp worktree and run full gates
    local worktree_path
    worktree_path=$(git_create_worktree "$task_id" "$branch" 2>/dev/null) || {
        log_warn "Task ${task_id}: failed to create worktree for branch audit"
        echo "fail"
        return 0
    }
    git_setup_worktree_deps "$worktree_path"

    # Redirect gates_run stdout to stderr so its printed results
    # (grounding checks table, quality gates table) don't pollute
    # the stdout channel used for the pass/fail/empty control value.
    if gates_run "$task_id" "$worktree_path" >&2; then
        git_remove_worktree "$task_id"
        echo "pass"
    else
        git_remove_worktree "$task_id"
        echo "fail"
    fi
    return 0
}

# ── Check: declared files exist ───────────────────────────────────

grounding_check_declared_files() {
    local task_id="$1"
    local task_json="${TASKS_DIR}/${task_id}.json"

    # Get files_touched from task (may not exist in older task format)
    local files_touched
    files_touched=$(jq -r '.files_touched[]?' "$task_json")

    if [[ -z "$files_touched" ]]; then
        # No files declared — can't check, pass by default
        return 0
    fi

    local branch
    branch=$(jq -r '.branch // empty' "$task_json")
    local missing=false
    local missing_files=""

    while IFS= read -r declared_file; do
        [[ -z "$declared_file" ]] && continue
        # Check if file exists on the branch OR was intentionally deleted
        if ! _git show "${branch}:${declared_file}" &>/dev/null; then
            if _git show "main:${declared_file}" &>/dev/null; then
                # File existed on main but was removed on branch — intentional deletion, not missing
                continue
            fi
            # File never existed on main OR branch — it's genuinely missing
            log_warn "Declared file missing: ${declared_file} (not on branch '${branch}' or main)"
            [[ -n "$missing_files" ]] && missing_files+=","
            missing_files+="$declared_file"
            missing=true
        fi
    done <<< "$files_touched"

    [[ -n "$missing_files" ]] && echo "$missing_files"
    ! $missing
}

# ── Check: scope (actual files vs declared files) ─────────────────

grounding_check_scope() {
    local task_id="$1"
    local task_json="${TASKS_DIR}/${task_id}.json"

    local files_touched
    files_touched=$(jq -r '.files_touched[]?' "$task_json")

    if [[ -z "$files_touched" ]]; then
        # No declaration — can't check scope
        return 0
    fi

    local branch
    branch=$(jq -r '.branch // empty' "$task_json")

    # Get actual files changed on branch (two-dot diff from fork point,
    # same as branch_audit — excludes content inherited via refresh merges)
    local main_branch
    main_branch=$(git_main_branch)
    local fork_point
    fork_point=$(_git merge-base "$main_branch" "$branch" 2>/dev/null) || true
    local actual_files
    actual_files=$(_git diff "${fork_point}..${branch}" --name-only 2>/dev/null)

    if [[ -z "$actual_files" ]]; then
        return 0
    fi

    # Find files that were changed but not declared
    local undeclared=""
    local ownership_violations=""
    local has_impl_violation=false
    while IFS= read -r actual_file; do
        [[ -z "$actual_file" ]] && continue
        local found=false
        while IFS= read -r declared_file; do
            [[ -z "$declared_file" ]] && continue
            if [[ "$actual_file" == "$declared_file" ]]; then
                found=true
                break
            fi
        done <<< "$files_touched"

        if ! $found; then
            local owner_tid=""
            for other_file in "${TASKS_DIR}"/*.json; do
                [[ -f "$other_file" ]] || continue
                local other_id
                other_id=$(jq -r '.id' "$other_file")
                [[ "$other_id" == "$task_id" ]] && continue
                # Skip ownership from completed tasks — their files are available
                local other_status
                other_status=$(jq -r '.status // "pending"' "$other_file")
                if [[ "$other_status" == "done" ]] || [[ "$other_status" == "integrated" ]] || [[ "$other_status" == "cancelled" ]]; then
                    continue
                fi
                if jq -e --arg f "$actual_file" \
                    '.files_touched // [] | any(. == $f)' \
                    "$other_file" >/dev/null 2>&1; then
                    owner_tid="$other_id"
                    break
                fi
            done

            if [[ -n "$owner_tid" ]]; then
                [[ -n "$ownership_violations" ]] && ownership_violations+=", "
                ownership_violations+="${actual_file} (task ${owner_tid})"
                # Test files are downstream of implementation — fixing a
                # sibling's tests to match code changes is expected.
                if ! _is_test_file "$actual_file"; then
                    has_impl_violation=true
                fi
            else
                [[ -n "$undeclared" ]] && undeclared+=", "
                undeclared+="$actual_file"
            fi
        fi
    done <<< "$actual_files"

    if [[ -n "$ownership_violations" ]]; then
        echo "$ownership_violations"
        if $has_impl_violation; then
            return 1
        fi
        return 2  # test-only ownership violations → warning
    fi

    if [[ -n "$undeclared" ]]; then
        echo "$undeclared"
        return 2  # warning, not failure
    fi

    return 0
}

# ── Check: Python imports resolve ─────────────────────────────────

grounding_check_python_imports() {
    local task_id="$1"
    local worktree_path="${2:-$PROJECT_ROOT}"
    local task_json="${TASKS_DIR}/${task_id}.json"
    local branch
    branch=$(jq -r '.branch // empty' "$task_json")

    # Get Python files changed on this branch
    local py_files
    py_files=$(_git diff "$(git_main_branch)...${branch}" --name-only 2>/dev/null | grep '\.py$' || true)

    if [[ -z "$py_files" ]]; then
        return 0  # No Python files, nothing to check
    fi

    local failed=false
    while IFS= read -r py_file; do
        [[ -z "$py_file" ]] && continue
        local full_path="${worktree_path}/${py_file}"
        [[ -f "$full_path" ]] || continue

        # Extract import statements and check if referenced files exist
        # Only check relative/project imports, not stdlib/third-party
        local imports
        imports=$($(_context_python) -c "
import ast, sys
try:
    tree = ast.parse(open('${full_path}').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith('app.') or node.module.startswith('src.'):
                print(node.module)
except:
    pass
" 2>/dev/null || true)

        while IFS= read -r imp; do
            [[ -z "$imp" ]] && continue
            # Convert module path to file path
            local imp_path
            imp_path=$(echo "$imp" | tr '.' '/')
            # Check both as file and as package (look in worktree first, then main repo)
            local found=false
            for base_root in "$worktree_path" "$PROJECT_ROOT"; do
                for base_dir in "src/backend" "src/frontend" "."; do
                    if [[ -f "${base_root}/${base_dir}/${imp_path}.py" ]] || \
                       [[ -f "${base_root}/${base_dir}/${imp_path}/__init__.py" ]] || \
                       [[ -f "${base_root}/${imp_path}.py" ]] || \
                       [[ -f "${base_root}/${imp_path}/__init__.py" ]]; then
                        found=true
                        break 2
                    fi
                done
            done
            if ! $found; then
                log_warn "Unresolved import in ${py_file}: ${imp}"
                failed=true
            fi
        done <<< "$imports"
    done <<< "$py_files"

    ! $failed
}

# ── Check: agent did not report blocked status ────────────────────

grounding_check_not_blocked() {
    local task_id="$1"
    local output_file="${LOGS_DIR}/${task_id}.log"

    if [[ ! -f "$output_file" ]]; then
        return 1  # No output = problem
    fi

    # Check if the agent output contains a blocked status
    if grep -q '"status"[[:space:]]*:[[:space:]]*"blocked"' "$output_file" 2>/dev/null; then
        return 1  # Agent is blocked
    fi

    return 0
}

# ── Helper: check if sibling tasks cover missing test files ────────
# Returns 0 if ALL testable source files missing convention-matched tests
# have a corresponding test file declared by an active sibling task.
# "Active" means the sibling's status is not "failed" or "cancelled".

_test_files_covered_by_siblings() {
    local task_id="$1"
    local task_json="${TASKS_DIR}/${task_id}.json"
    local branch
    branch=$(jq -r '.branch // empty' "$task_json")

    if [[ -z "$branch" ]] || [[ "$branch" == "null" ]]; then
        return 1
    fi

    # Get newly added files
    local new_files
    new_files=$(_git diff "$(git_main_branch)...${branch}" --diff-filter=A --name-only 2>/dev/null || true)
    if [[ -z "$new_files" ]]; then
        return 0
    fi

    # All files in the branch diff
    local diff_files
    diff_files=$(_git diff "$(git_main_branch)...${branch}" --name-only 2>/dev/null || true)

    # Collect testable source files that lack convention-matched tests
    local missing_files=()
    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        if _test_coverage_excluded "$file"; then
            continue
        fi
        if ! _test_file_exists_in_diff "$file" "$diff_files"; then
            missing_files+=("$file")
        fi
    done <<< "$new_files"

    if [[ ${#missing_files[@]} -eq 0 ]]; then
        return 0  # Nothing missing
    fi

    # Check sibling tasks for test files with matching stem + language family
    local all_covered=true
    for src_file in "${missing_files[@]}"; do
        local src_basename src_stem src_family
        src_basename=$(basename "$src_file")
        src_stem="${src_basename%.*}"
        src_family=$(_lang_family "$src_file")
        local covered_by_sibling=false

        for other_file in "${TASKS_DIR}"/*.json; do
            [[ -f "$other_file" ]] || continue
            local other_id other_status
            other_id=$(jq -r '.id' "$other_file")
            [[ "$other_id" == "$task_id" ]] && continue

            # Skip failed/cancelled siblings
            other_status=$(jq -r '.status // "pending"' "$other_file")
            if [[ "$other_status" == "failed" ]] || [[ "$other_status" == "cancelled" ]]; then
                continue
            fi

            # Check sibling's files_touched for a test file with matching stem + family
            while IFS= read -r sibling_file; do
                [[ -z "$sibling_file" ]] && continue
                if _is_test_file "$sibling_file"; then
                    local sibling_stem
                    if ! sibling_stem=$(_test_file_stem "$sibling_file"); then
                        local _sb; _sb=$(basename "$sibling_file"); sibling_stem="${_sb%.*}"
                    fi
                    if [[ "$sibling_stem" == "$src_stem" ]] && \
                       [[ "$(_lang_family "$sibling_file")" == "$src_family" ]]; then
                        covered_by_sibling=true
                        break
                    fi
                fi
            done <<< "$(jq -r '.files_touched[]?' "$other_file")"

            if $covered_by_sibling; then
                break
            fi
        done

        if ! $covered_by_sibling; then
            all_covered=false
            break
        fi
    done

    $all_covered
}

# ── Check: test file coverage ─────────────────────────────────────

# Helper: returns 0 (exclude/skip) if the file does not require a test counterpart.
# Returns 1 (include) if a test file is required.
_test_coverage_excluded() {
    local file="$1"
    local basename
    basename=$(basename "$file")
    local dir
    dir=$(dirname "$file")

    # Test files themselves never require a test-of-test
    if _is_test_file "$file"; then
        return 0
    fi

    # Build and project files (no test coupling)
    case "$basename" in
        pom.xml|build.gradle|build.gradle.kts|settings.gradle|settings.gradle.kts|\
        go.mod|go.sum|Cargo.toml|Cargo.lock|\
        Gemfile|Gemfile.lock|*.gemspec|\
        composer.json|composer.lock|\
        Makefile|CMakeLists.txt|*.cmake|\
        build.sbt|*.csproj|*.sln|*.fsproj|\
        mix.exs|mix.lock|\
        pubspec.yaml|pubspec.lock|\
        Rakefile|*.cabal|stack.yaml|project.clj|\
        setup.py|setup.cfg|pyproject.toml|requirements*.txt|Pipfile|Pipfile.lock) return 0 ;;
    esac

    # Config and setup files
    case "$basename" in
        vitest.config.*|next.config.*|jest.config.*|tailwind.config.*|postcss.config.*|\
        eslint.config.*|prettier.config.*|tsconfig*.json|*.config.ts|*.config.js|\
        *.config.mjs|*.config.cjs|setup.ts|setup.js) return 0 ;;
    esac

    # Type definitions
    case "$basename" in
        *.d.ts) return 0 ;;
    esac
    if [[ "$basename" == "types.ts" ]] || [[ "$basename" == "types.tsx" ]]; then
        return 0
    fi

    # Barrel exports
    if [[ "$basename" == "index.ts" ]] || [[ "$basename" == "index.tsx" ]]; then
        return 0
    fi

    # Markdown and documentation files (agent definitions, specs, docs — no test coupling)
    case "$basename" in
        *.md|*.mdx) return 0 ;;
    esac

    # CSS / static assets
    case "$basename" in
        *.css|*.scss|*.sass|*.less|*.svg|*.png|*.jpg|*.jpeg|*.gif|*.ico|\
        *.woff|*.woff2|*.ttf|*.eot|*.webp|*.avif) return 0 ;;
    esac

    # Migrations (alembic or generic migrations directory)
    if [[ "$file" == alembic/* ]] || [[ "$file" == */alembic/* ]] || \
       [[ "$file" == migrations/* ]] || [[ "$file" == */migrations/* ]]; then
        return 0
    fi

    # Seed data (src/backend/app/seed/ or any seed directory)
    if [[ "$file" == */seed/* ]]; then
        return 0
    fi

    # Next.js layout and route segments (no logic to test independently)
    case "$basename" in
        page.tsx|page.ts|layout.tsx|layout.ts|route.tsx|route.ts|\
        middleware.ts|loading.tsx|error.tsx|not-found.tsx|template.tsx|\
        global-error.tsx|default.tsx) return 0 ;;
    esac

    # Test directories — all files within test/, tests/, __tests__/ are utilities, not tested
    if [[ "$file" == test/* ]] || [[ "$file" == tests/* ]] || \
       [[ "$file" == */test/* ]] || [[ "$file" == */tests/* ]] || \
       [[ "$file" == */__tests__/* ]]; then
        return 0
    fi

    # Test utility mocks
    if [[ "$file" == */__mocks__/* ]] || \
       [[ "$basename" == *.mock.ts ]] || [[ "$basename" == *.mock.tsx ]]; then
        return 0
    fi

    # shadcn/ui components (generated primitives, not product logic)
    if [[ "$file" == src/frontend/components/ui/* ]]; then
        return 0
    fi

    # GraphQL type definitions
    if [[ "$file" == */graphql/types/* ]] || [[ "$file" == */graphql/types.ts ]] || \
       [[ "$file" == */graphql/types.tsx ]]; then
        return 0
    fi

    # types/ directory anywhere in path
    if [[ "$dir" == */types ]] || [[ "$file" == */types/* ]]; then
        return 0
    fi

    # Custom exclude patterns from speed.toml
    local exclude_patterns
    exclude_patterns=$(toml_get_value "test_coverage.exclude_patterns" "" 2>/dev/null)
    if [[ -n "$exclude_patterns" ]]; then
        local excl_pattern
        while IFS= read -r excl_pattern; do
            [[ -z "$excl_pattern" ]] && continue
            excl_pattern=$(echo "$excl_pattern" | tr -d ' "'"'"'')
            [[ -z "$excl_pattern" ]] && continue
            # shellcheck disable=SC2254
            case "$file" in
                $excl_pattern) return 0 ;;
            esac
        done <<< "$(echo "$exclude_patterns" | tr ',' '\n')"
    fi

    return 1  # File requires a corresponding test
}

# Helper: returns 0 if a test file corresponding to $file exists in $diff_files.
# $diff_files is a newline-separated list of all files changed on the branch.
# Matches by stem equality AND language family to prevent cross-language collisions.
_test_file_exists_in_diff() {
    local file="$1"
    local diff_files="$2"
    local src_basename src_stem src_family

    src_basename=$(basename "$file")
    src_stem="${src_basename%.*}"
    src_family=$(_lang_family "$file")

    # Scan diff files for any test file whose stem and language family match
    while IFS= read -r df; do
        [[ -z "$df" ]] && continue
        local test_stem
        test_stem=$(_test_file_stem "$df") || continue
        if [[ "$test_stem" == "$src_stem" ]] && \
           [[ "$(_lang_family "$df")" == "$src_family" ]]; then
            return 0
        fi
    done <<< "$diff_files"

    return 1
}

grounding_check_test_coverage() {
    local task_id="$1"
    local task_json="${TASKS_DIR}/${task_id}.json"
    local branch
    branch=$(jq -r '.branch // empty' "$task_json")

    if [[ -z "$branch" ]] || [[ "$branch" == "null" ]]; then
        return 1
    fi

    # Escape hatch: skip test coverage check entirely via speed.toml
    local skip_coverage
    skip_coverage=$(toml_get_value "test_coverage.skip" "" 2>/dev/null)
    if [[ "$skip_coverage" == "true" ]]; then
        return 0
    fi

    # Only examine newly added files (not modified/deleted)
    local new_files
    new_files=$(_git diff "$(git_main_branch)...${branch}" --diff-filter=A --name-only 2>/dev/null || true)

    if [[ -z "$new_files" ]]; then
        return 0  # No new files — nothing to check
    fi

    # Check if any new files actually require tests
    local has_testable_files=false
    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        if ! _test_coverage_excluded "$file"; then
            has_testable_files=true
            break
        fi
    done <<< "$new_files"

    if ! $has_testable_files; then
        return 0  # No testable source files — nothing to check
    fi

    # ── Task-level test coverage ─────────────────────────────────
    # The Architect declares both source and test files in files_touched.
    # Instead of guessing which test covers which source via filename
    # conventions, verify that:
    #   1. The task plan includes at least one test file
    #   2. That test file was actually created in the diff
    #
    # This respects the Architect's mapping (shared tests, umbrella tests,
    # non-standard naming) without hardcoding project conventions.

    local files_touched
    files_touched=$(jq -r '.files_touched[]?' "$task_json")

    # All files in the branch diff
    local diff_files
    diff_files=$(_git diff "$(git_main_branch)...${branch}" --name-only 2>/dev/null || true)

    # Identify declared test files via _is_test_file (go-enry conventions + speed.toml)
    local declared_test_files=()
    while IFS= read -r ft; do
        [[ -z "$ft" ]] && continue
        if _is_test_file "$ft"; then
            declared_test_files+=("$ft")
        fi
    done <<< "$files_touched"

    if [[ ${#declared_test_files[@]} -eq 0 ]]; then
        # Architect declared no test files for a task with testable source files.
        # Fall back to per-file convention matching so the gate still catches this.
        local missing_tests=()
        while IFS= read -r file; do
            [[ -z "$file" ]] && continue
            if _test_coverage_excluded "$file"; then
                continue
            fi
            if ! _test_file_exists_in_diff "$file" "$diff_files"; then
                missing_tests+=("$file")
            fi
        done <<< "$new_files"

        if [[ ${#missing_tests[@]} -gt 0 ]]; then
            log_error "No test files declared in task plan, and convention matching found gaps:"
            for f in "${missing_tests[@]}"; do
                log_error "  ${f}"
            done
            log_error "Either add test files to the task's files_touched or create convention-matched test files."
            echo "$(IFS=,; echo "${missing_tests[*]}")"
            return 1
        fi
        return 0
    fi

    # Verify declared test files are present in the diff
    local missing_declared_tests=()
    for tf in "${declared_test_files[@]}"; do
        if ! echo "$diff_files" | grep -qxF "$tf"; then
            missing_declared_tests+=("$tf")
        fi
    done

    if [[ ${#missing_declared_tests[@]} -gt 0 ]]; then
        log_error "Declared test files missing from branch diff:"
        for f in "${missing_declared_tests[@]}"; do
            log_error "  ${f}"
        done
        echo "$(IFS=,; echo "${missing_declared_tests[*]}")"
        return 1
    fi

    return 0
}

# Returns a language family identifier for a file path.
# Used to prevent cross-language stem collisions in test matching.
_lang_family() {
    case "$1" in
        *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs) echo "js"      ;;
        *.py)                               echo "py"      ;;
        *.go)                               echo "go"      ;;
        *.rb)                               echo "rb"      ;;
        *.java)                             echo "jvm"     ;;
        *.scala)                            echo "jvm"     ;;
        *.kt|*.kts)                         echo "jvm"     ;;
        *.cs)                               echo "dotnet"  ;;
        *.php)                              echo "php"     ;;
        *.sh|*.bash)                        echo "sh"      ;;
        *.swift)                            echo "swift"   ;;
        *.rs)                               echo "rust"    ;;
        *.dart)                             echo "dart"    ;;
        *.ex|*.exs)                         echo "elixir"  ;;
        *.c|*.h)                            echo "c"       ;;
        *.cpp|*.cc|*.cxx|*.hpp|*.hh)        echo "cpp"     ;;
        *.lua)                              echo "lua"     ;;
        *.pl|*.pm|*.t)                      echo "perl"    ;;
        *.hs)                               echo "haskell" ;;
        *.clj|*.cljs|*.cljc)               echo "clojure" ;;
        *)                                  echo "unknown" ;;
    esac
}

# Returns the source stem from a test filename on stdout.
# Exit 0 = test file (stem printed), exit 1 = not a test file.
# This is the single source of truth for language-aware test file detection.
_test_file_stem() {
    local file="$1"
    local bn
    bn=$(basename "$file")

    # Custom patterns from speed.toml: test_coverage.patterns
    # Format: comma-separated glob=rule pairs, e.g. *Test.kt=suffix:Test
    local custom_patterns
    custom_patterns=$(toml_get_value "test_coverage.patterns" "" 2>/dev/null)
    if [[ -n "$custom_patterns" ]]; then
        local pair
        while IFS= read -r pair; do
            [[ -z "$pair" ]] && continue
            pair=$(echo "$pair" | tr -d ' ')
            local glob_part="${pair%%=*}"
            local rule_part="${pair#*=}"
            # shellcheck disable=SC2254
            case "$bn" in
                $glob_part)
                    local rule_type="${rule_part%%:*}"
                    local rule_val="${rule_part#*:}"
                    local no_ext="${bn%.*}"
                    case "$rule_type" in
                        suffix) echo "${no_ext%${rule_val}}"; return 0 ;;
                        prefix) echo "${no_ext#${rule_val}}"; return 0 ;;
                    esac
                    ;;
            esac
        done <<< "$(echo "$custom_patterns" | tr ',' '\n')"
    fi

    # __tests__/ directory: stem is basename minus any .test./.spec. infix + extension
    if [[ "$file" == */__tests__/* ]]; then
        case "$bn" in
            *.test.*) echo "${bn%.test.*}" ;;
            *.spec.*) echo "${bn%.spec.*}" ;;
            *)        echo "${bn%.*}" ;;
        esac
        return 0
    fi

    # Built-in: 20 language groups
    case "$bn" in
        # JS/TS
        *.test.ts|*.test.tsx|*.test.js|*.test.jsx)  echo "${bn%.test.*}";  return 0 ;;
        *.spec.ts|*.spec.tsx|*.spec.js|*.spec.jsx)  echo "${bn%.spec.*}";  return 0 ;;
        # Python
        test_*.py)   local s="${bn#test_}"; echo "${s%.py}";  return 0 ;;
        *_test.py)   echo "${bn%_test.py}";                   return 0 ;;
        # Go
        *_test.go)   echo "${bn%_test.go}";                   return 0 ;;
        # Ruby
        *_spec.rb)   echo "${bn%_spec.rb}";                   return 0 ;;
        *_test.rb)   echo "${bn%_test.rb}";                   return 0 ;;
        test_*.rb)   local s="${bn#test_}"; echo "${s%.rb}";  return 0 ;;
        # Java
        *Tests.java) echo "${bn%Tests.java}";                 return 0 ;;
        *Test.java)  echo "${bn%Test.java}";                  return 0 ;;
        # Scala
        *Spec.scala) echo "${bn%Spec.scala}";                 return 0 ;;
        *Test.scala) echo "${bn%Test.scala}";                 return 0 ;;
        # C#
        *Tests.cs)   echo "${bn%Tests.cs}";                   return 0 ;;
        *Test.cs)    echo "${bn%Test.cs}";                    return 0 ;;
        # PHP
        *Tests.php)  echo "${bn%Tests.php}";                  return 0 ;;
        *Test.php)   echo "${bn%Test.php}";                   return 0 ;;
        # Bash
        test_*.sh)   local s="${bn#test_}"; echo "${s%.sh}";  return 0 ;;
        # Kotlin
        *Tests.kt)   echo "${bn%Tests.kt}";                  return 0 ;;
        *Test.kt)    echo "${bn%Test.kt}";                    return 0 ;;
        # Swift
        *Tests.swift) echo "${bn%Tests.swift}";               return 0 ;;
        *Test.swift)  echo "${bn%Test.swift}";                return 0 ;;
        # Rust
        *_test.rs)   echo "${bn%_test.rs}";                   return 0 ;;
        # Dart
        *_test.dart) echo "${bn%_test.dart}";                 return 0 ;;
        # Elixir
        *_test.exs)  echo "${bn%_test.exs}";                  return 0 ;;
        # C
        test_*.c)    local s="${bn#test_}"; echo "${s%.c}";   return 0 ;;
        *_test.c)    echo "${bn%_test.c}";                    return 0 ;;
        # C++
        test_*.cpp)  local s="${bn#test_}"; echo "${s%.cpp}"; return 0 ;;
        *_test.cpp)  echo "${bn%_test.cpp}";                  return 0 ;;
        test_*.cc)   local s="${bn#test_}"; echo "${s%.cc}";  return 0 ;;
        *_test.cc)   echo "${bn%_test.cc}";                   return 0 ;;
        test_*.cxx)  local s="${bn#test_}"; echo "${s%.cxx}"; return 0 ;;
        *_test.cxx)  echo "${bn%_test.cxx}";                  return 0 ;;
        # Lua
        test_*.lua)  local s="${bn#test_}"; echo "${s%.lua}"; return 0 ;;
        *_test.lua)  echo "${bn%_test.lua}";                  return 0 ;;
        *_spec.lua)  echo "${bn%_spec.lua}";                  return 0 ;;
        # Perl
        *.t)         echo "${bn%.t}";                         return 0 ;;
        *_test.pl)   echo "${bn%_test.pl}";                   return 0 ;;
        # Haskell
        *Spec.hs)    echo "${bn%Spec.hs}";                    return 0 ;;
        *Test.hs)    echo "${bn%Test.hs}";                    return 0 ;;
        # Clojure
        *_test.clj)  echo "${bn%_test.clj}";                  return 0 ;;
    esac

    return 1
}

# Helper: returns 0 if the file looks like a test file.
# Uses go-enry conventions + speed.toml overrides.
_is_test_file() {
    local file="$1"
    local basename
    basename=$(basename "$file")

    # Custom patterns from speed.toml
    local custom_patterns
    custom_patterns=$(toml_get_value "test_patterns.patterns" "" 2>/dev/null)
    if [[ -n "$custom_patterns" ]]; then
        local pattern
        while IFS= read -r pattern; do
            [[ -z "$pattern" ]] && continue
            pattern=$(echo "$pattern" | sed 's/^[[:space:]]*"//;s/"[[:space:]]*$//' | sed "s/^[[:space:]]*'//;s/'[[:space:]]*$//")
            [[ -z "$pattern" ]] && continue
            local regex="$pattern"
            regex=$(echo "$regex" | sed 's/\./\\./g' | sed 's/\*\*/.*/g' | sed 's/\*/[^\/]*/g')
            regex=$(echo "$regex" | sed 's/{/(/g;s/}/)/g;s/,/|/g')
            if echo "$file" | grep -qE "$regex"; then
                return 0
            fi
        done <<< "$(echo "$custom_patterns" | tr ',' '\n')"
    fi

    # Delegate: _test_file_stem returns 0 for test files
    _test_file_stem "$file" >/dev/null 2>&1
}

# ── Check: gate invocation evidence ───────────────────────────────

grounding_check_gate_evidence() {
    local task_id="$1"
    local output_file="${LOGS_DIR}/${task_id}.log"

    if [[ ! -f "$output_file" ]]; then
        return 1  # No log file — no evidence
    fi

    # Look for markers indicating the agent ran quality gates
    if grep -qE 'Quality Gates:|Running quality gates for task|speed gates' "$output_file" 2>/dev/null; then
        return 0
    fi

    return 1
}

# ── Check: criteria verification (NEW) ───────────────────────────
# Calls lib/criteria_verify.py to verify structured acceptance criteria.
# Returns: 0 = all pass, 1 = any fail, 2 = some unverifiable

grounding_check_criteria() {
    local task_id="$1"
    local task_json="${TASKS_DIR}/${task_id}.json"

    if [[ ! -f "$task_json" ]]; then
        return 0  # No task file — skip
    fi

    # Check if task has structured acceptance_criteria
    local has_criteria
    has_criteria=$(jq -r '.acceptance_criteria // [] | length' "$task_json" 2>/dev/null)
    if [[ "$has_criteria" == "0" ]] || [[ -z "$has_criteria" ]]; then
        return 0  # No criteria — skip
    fi

    local verify_script="${LIB_DIR}/criteria_verify.py"
    if [[ ! -f "$verify_script" ]]; then
        # Fall back to project root lib/
        verify_script="${PROJECT_ROOT}/lib/criteria_verify.py"
    fi

    if [[ ! -f "$verify_script" ]]; then
        return 2  # Script not found — unverifiable
    fi

    # Run criteria verification
    local verify_output
    verify_output=$($(_context_python) -c "
import json, sys
sys.path.insert(0, '${PROJECT_ROOT}')
from lib.criteria_verify import verify_criteria

task = json.load(open('${task_json}'))
project_root = '${PROJECT_ROOT}'

# Load CSG and project map if available
csg = None
project_map = None
context_dir = '${PROJECT_ROOT}/.speed/context'
try:
    with open(context_dir + '/semantic-graph.json') as f:
        csg = json.load(f)
except: pass
try:
    with open(context_dir + '/project-map.json') as f:
        project_map = json.load(f)
except: pass

results = verify_criteria(task, project_root, csg=csg, project_map=project_map)
print(json.dumps(results))
" 2>/dev/null)

    if [[ -z "$verify_output" ]]; then
        return 2  # No output — unverifiable
    fi

    # Parse results
    local has_fail has_unverifiable
    has_fail=$(echo "$verify_output" | jq '[.criteria_results[] | select(.status == "fail")] | length' 2>/dev/null)
    has_unverifiable=$(echo "$verify_output" | jq '[.criteria_results[] | select(.status == "unverifiable")] | length' 2>/dev/null)

    if [[ "$has_fail" -gt 0 ]]; then
        echo "$verify_output"
        return 1  # Hard failure
    elif [[ "$has_unverifiable" -gt 0 ]]; then
        echo "$verify_output"
        return 2  # Some unverifiable
    fi

    echo "$verify_output"
    return 0
}

# ── Helper: get toml config value ────────────────────────────────
# Simple helper for reading speed.toml values.
# Falls back to default if key not found.

toml_get_value() {
    local key="$1"
    local default_val="${2:-}"

    local toml_file="${PROJECT_ROOT}/speed.toml"
    if [[ ! -f "$toml_file" ]]; then
        echo "$default_val"
        return
    fi

    # Simple grep-based extraction (no toml parser needed for flat keys)
    local value
    value=$(grep -E "^${key}\s*=" "$toml_file" 2>/dev/null | head -1 | sed 's/^[^=]*=\s*//' | tr -d '"' | tr -d "'" | tr -d ' ')

    if [[ -n "$value" ]]; then
        echo "$value"
    else
        echo "$default_val"
    fi
}

# ── Contract Check: verify artifacts declared in contract.json ────
# Uses existence checks (speed/lib/contract_verify.py) — verifies
# that declared files, symbols, and model classes exist on disk.
# Semantic correctness is verified by LLM agents (reviewer, coherence).

contract_check() {
    local contract_file="${CONTRACT_FILE:-${STATE_DIR}/contract.json}"

    if [[ ! -f "$contract_file" ]]; then
        log_warn "No contract.json found — skipping contract verification"
        return 0
    fi

    local verify_script="${LIB_DIR}/contract_verify.py"
    if [[ ! -f "$verify_script" ]]; then
        log_error "contract_verify.py not found at ${verify_script}"
        return 1
    fi

    log_step "Verifying contract artifacts..."

    local verify_output
    verify_output=$(python3 "$verify_script" "$contract_file" "$PROJECT_ROOT" 2>&1)
    local verify_exit=$?

    # Exit code 2 = script error (bad args, unreadable contract)
    if [[ $verify_exit -eq 2 ]]; then
        local err_msg
        err_msg=$(echo "$verify_output" | jq -r '.error // "Unknown error"' 2>/dev/null || echo "$verify_output")
        log_error "Contract verification script failed: ${err_msg}"
        return 1
    fi

    # Parse structured results
    local results_json
    results_json=$(echo "$verify_output" | jq -c '.' 2>/dev/null)

    if [[ -z "$results_json" ]]; then
        log_error "Contract verification produced no output"
        return 1
    fi

    local all_passed
    all_passed=$(echo "$results_json" | jq -r '.passed')

    # Print each check result
    echo ""
    echo -e "  ${BOLD}Contract Verification:${RESET}"

    local check_count
    check_count=$(echo "$results_json" | jq '.results | length')
    local i=0
    while [[ $i -lt $check_count ]]; do
        local check_name passed detail
        check_name=$(echo "$results_json" | jq -r ".results[$i].check")
        passed=$(echo "$results_json" | jq -r ".results[$i].passed")
        detail=$(echo "$results_json" | jq -r ".results[$i].detail")

        if [[ "$passed" == "true" ]]; then
            echo -e "    ${COLOR_SUCCESS}${SYM_CHECK} ${check_name}${RESET} ${COLOR_DIM}${detail}${RESET}"
        else
            echo -e "    ${COLOR_ERROR}${SYM_CROSS} ${check_name}${RESET} — ${detail}"
        fi
        ((i++)) || true
    done

    echo ""

    if [[ "$all_passed" == "true" ]]; then
        log_success "Contract satisfied — all declared artifacts exist"
        return 0
    else
        log_error "Contract VIOLATED — declared artifacts missing from implementation"
        return 1
    fi
}

# ── Regression Gate: run full test suite ──────────────────────────

regression_run() {
    log_step "Running regression tests (full suite)..."

    local all_passed=true
    local results=()

    # Regression runs ALL gate commands (no subsystem filter — "both")
    local gate_type gate_label
    for gate_type in test lint typecheck; do
        case "$gate_type" in
            test)      gate_label="Tests" ;;
            lint)      gate_label="Lint" ;;
            typecheck) gate_label="Typecheck" ;;
        esac

        local cmds
        cmds=$(gates_get_config "$gate_type" "both")
        if [[ -n "$cmds" ]]; then
            while IFS= read -r cmd; do
                [[ -z "$cmd" ]] && continue
                if gate_run_command "Regression ${gate_label}" "$cmd"; then
                    results+=("${COLOR_SUCCESS}${SYM_CHECK} ${gate_label}: ${COLOR_DIM}${cmd}${RESET}")
                else
                    results+=("${COLOR_ERROR}${SYM_CROSS} ${gate_label} FAILED: ${COLOR_DIM}${cmd}${RESET}")
                    all_passed=false
                fi
            done <<< "$cmds"
        else
            results+=("${COLOR_DIM}○ ${gate_label} (not configured)${RESET}")
        fi
    done

    echo ""
    echo -e "  ${BOLD}Regression Check:${RESET}"
    for r in "${results[@]}"; do
        echo -e "    $r"
    done
    echo ""

    if $all_passed; then
        return 0
    else
        return 1
    fi
}

# ── File conflict detection ───────────────────────────────────────
# Check if a task's declared files conflict with any running task

grounding_check_file_conflicts() {
    local task_id="$1"
    local task_json="${TASKS_DIR}/${task_id}.json"

    local my_files
    my_files=$(jq -r '.files_touched[]?' "$task_json")

    if [[ -z "$my_files" ]]; then
        return 0  # No declarations, can't check
    fi

    # Check against all running tasks
    local running_tasks
    running_tasks=$(task_list_by_status "running")

    if [[ -z "$running_tasks" ]]; then
        return 0
    fi

    local conflicts=""
    while IFS= read -r other_id; do
        [[ -z "$other_id" ]] && continue
        [[ "$other_id" == "$task_id" ]] && continue

        local other_json="${TASKS_DIR}/${other_id}.json"
        local other_files
        other_files=$(jq -r '.files_touched[]?' "$other_json")

        while IFS= read -r my_file; do
            [[ -z "$my_file" ]] && continue
            while IFS= read -r other_file; do
                [[ -z "$other_file" ]] && continue
                if [[ "$my_file" == "$other_file" ]]; then
                    conflicts+="Task ${task_id} and Task ${other_id} both touch: ${my_file}\n"
                fi
            done <<< "$other_files"
        done <<< "$my_files"
    done <<< "$running_tasks"

    if [[ -n "$conflicts" ]]; then
        echo -e "$conflicts"
        return 1
    fi

    return 0
}

# ── Spec Grounding: verify spec claims against codebase ───────────
# Runs BEFORE the architect to catch spec-codebase discrepancies.
# Parses spec markdown for table/column claims, code patterns, and
# file paths, then compares against the actual codebase.
#
# Always returns 0 (warnings don't block planning).
# Sets SPEC_CODEBASE_CONTEXT with a text block for the architect.
#
# Args: spec_file

spec_grounding_check() {
    local spec_file="$1"

    local ground_script="${LIB_DIR}/spec_ground.py"
    if [[ ! -f "$ground_script" ]]; then
        log_warn "spec_ground.py not found — skipping spec grounding"
        SPEC_CODEBASE_CONTEXT=""
        return 0
    fi

    log_step "Grounding spec against codebase..."

    local output
    output=$(python3 "$ground_script" "$spec_file" "$PROJECT_ROOT" 2>&1)
    local exit_code=$?

    if [[ $exit_code -eq 2 ]]; then
        local err_msg
        err_msg=$(echo "$output" | jq -r '.error // "unknown"' 2>/dev/null || echo "$output")
        log_warn "Spec grounding error: ${err_msg} — skipping"
        SPEC_CODEBASE_CONTEXT=""
        return 0
    fi

    # Parse results
    local stats_json warnings_json
    stats_json=$(echo "$output" | jq -c '.stats // {}')
    warnings_json=$(echo "$output" | jq -c '.warnings // []')

    local errors warns infos spec_tables codebase_tables
    errors=$(echo "$stats_json" | jq -r '.errors // 0')
    warns=$(echo "$stats_json" | jq -r '.warnings // 0')
    infos=$(echo "$stats_json" | jq -r '.infos // 0')
    spec_tables=$(echo "$stats_json" | jq -r '.spec_tables // 0')
    codebase_tables=$(echo "$stats_json" | jq -r '.codebase_tables // 0')

    # Display summary
    echo ""
    echo -e "  ${BOLD}Spec Grounding:${RESET} ${spec_tables} tables in spec, ${codebase_tables} in codebase"

    local warn_count
    warn_count=$(echo "$warnings_json" | jq 'length')

    if [[ $warn_count -gt 0 ]]; then
        local i=0
        while [[ $i -lt $warn_count ]]; do
            local severity msg
            severity=$(echo "$warnings_json" | jq -r ".[$i].severity")
            msg=$(echo "$warnings_json" | jq -r ".[$i].message")

            case "$severity" in
                error) echo -e "    ${COLOR_ERROR}${SYM_CROSS} ${msg}${RESET}" ;;
                warn)  echo -e "    ${COLOR_WARN}${SYM_WARN} ${msg}${RESET}" ;;
                info)  echo -e "    ${COLOR_DIM}${SYM_CHECK} ${msg}${RESET}" ;;
            esac
            ((i++)) || true
        done
    else
        echo -e "    ${COLOR_SUCCESS}${SYM_CHECK} No discrepancies found${RESET}"
    fi
    echo ""

    if [[ $errors -gt 0 ]]; then
        log_warn "Spec has ${errors} convention error(s) — consider fixing before planning"
    fi

    # Export codebase context for injection into architect prompt
    SPEC_CODEBASE_CONTEXT=$(echo "$output" | jq -r '.codebase_context // ""')
    export SPEC_CODEBASE_CONTEXT

    return 0
}

# ── Check: secrets scanner (HARD FAILURE) ─────────────────────
# Scans changed files on the feature branch for hardcoded secrets.
# Unlike other security findings, detected secrets cause a HARD FAILURE
# (return 1) that blocks the pipeline. Secrets in git history require
# history rewriting — prevention is the only safe option.
#
# Args: task_id [worktree_path]
# Returns: 0 = clean, 1 = secrets detected

grounding_check_secrets() {
    local task_id="$1"
    local worktree_path="${2:-$PROJECT_ROOT}"
    local task_json="${TASKS_DIR}/${task_id}.json"

    # ── Read task JSON and extract branch ─────────────────
    if [[ ! -f "$task_json" ]]; then
        log_error "Secrets scan: task file not found: ${task_json}"
        return 1
    fi

    local branch
    branch=$(jq -r '.branch // empty' "$task_json")

    if [[ -z "$branch" ]] || [[ "$branch" == "null" ]]; then
        return 0  # No branch — nothing to scan
    fi

    # ── Get changed files on the feature branch ──────────
    local changed_files
    changed_files=$(_git diff "$(git_main_branch)...${branch}" --name-only 2>/dev/null)

    if [[ -z "$changed_files" ]]; then
        return 0  # No changed files — nothing to scan
    fi

    # ── Build exclusion list ─────────────────────────────
    local exclude_raw="${TOML_SECURITY_SECRETS_EXCLUDE:-.env* *.example tests/fixtures/**}"
    # Split into array with globbing disabled to prevent wildcard expansion
    local _old_glob
    _old_glob=$(shopt -p nullglob dotglob failglob 2>/dev/null || true)
    set -f  # disable globbing
    # shellcheck disable=SC2206
    local -a exclude_patterns=($exclude_raw)
    set +f  # re-enable globbing
    eval "$_old_glob" 2>/dev/null || true

    # ── Define secret patterns ───────────────────────────
    # Pattern name and regex pairs. CRITICAL: never echo matched content.
    # If TOML_SECURITY_SECRETS_PATTERNS is set, parse it as space-separated
    # "name|regex" pairs. Otherwise use built-in defaults.
    local -a pattern_names=()
    local -a pattern_regexes=()

    if [[ -n "${TOML_SECURITY_SECRETS_PATTERNS:-}" ]]; then
        local _pat
        for _pat in $TOML_SECURITY_SECRETS_PATTERNS; do
            pattern_names+=("${_pat%%|*}")
            pattern_regexes+=("${_pat#*|}")
        done
    else
        pattern_names=(
            "AWS Access Key"
            "AWS Secret Key"
            "GitHub Token"
            "Generic API Key"
            "Private Key Header"
            "Generic High-Entropy Secret"
            "Database URL"
        )
        pattern_regexes=(
            'AKIA[0-9A-Z]{16}'
            "['\"][0-9a-zA-Z/+]{40}['\"]"
            'gh[pousr]_[A-Za-z0-9_]{36,}'
            "['\"]sk-[a-zA-Z0-9]{20,}['\"]"
            '-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----'
            "['\"][A-Za-z0-9+/=]{40,}['\"]"
            '[a-z]+://[^:]+:[^@]+@[^/]+'
        )
    fi

    # ── Prepare log file ─────────────────────────────────
    local log_file="${LOGS_DIR}/secrets-scan.log"
    mkdir -p "$(dirname "$log_file")"
    {
        echo "=== Secrets Scan ==="
        echo "Task: ${task_id}"
        echo "Branch: ${branch}"
        echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
        echo "---"
    } > "$log_file"

    local found_secrets=false

    while IFS= read -r file; do
        [[ -z "$file" ]] && continue

        # ── Check exclusions (case-pattern on path and basename) ──
        local excluded=false
        local file_basename
        file_basename=$(basename "$file")
        for pattern in "${exclude_patterns[@]}"; do
            # Handle directory/** glob as prefix match (case doesn't expand ** from vars)
            if [[ "$pattern" == *"/**" ]]; then
                local prefix="${pattern%/**}/"
                if [[ "$file" == "$prefix"* ]]; then
                    excluded=true; break
                fi
                continue
            fi
            # Match against full path
            # shellcheck disable=SC2254
            case "$file" in
                $pattern) excluded=true; break ;;
            esac
            # Match against basename
            # shellcheck disable=SC2254
            case "$file_basename" in
                $pattern) excluded=true; break ;;
            esac
        done
        if $excluded; then
            echo "SKIP: ${file} (excluded)" >> "$log_file"
            continue
        fi

        # ── Skip binary files ────────────────────────────
        local full_path="${worktree_path}/${file}"
        if [[ -f "$full_path" ]]; then
            local file_type
            file_type=$(file -b "$full_path" 2>/dev/null || echo "unknown")
            case "$file_type" in
                *executable*|*binary*|*data*|*ELF*|*Mach-O*|*PE32*)
                    echo "SKIP: ${file} (binary)" >> "$log_file"
                    continue
                    ;;
            esac
        else
            # File doesn't exist on disk (may exist only on branch) — try git show
            local content
            if ! content=$(_git show "${branch}:${file}" 2>/dev/null); then
                echo "SKIP: ${file} (unreadable)" >> "$log_file"
                continue
            fi
            # Scan content from git directly
            local pattern_idx=0
            while [[ $pattern_idx -lt ${#pattern_names[@]} ]]; do
                local pname="${pattern_names[$pattern_idx]}"
                local pregex="${pattern_regexes[$pattern_idx]}"
                local line_num=0
                while IFS= read -r line; do
                    ((line_num++)) || true
                    if echo "$line" | grep -qE -e "$pregex" 2>/dev/null; then
                        found_secrets=true
                        echo "FOUND: ${pname} at ${file}:${line_num}" >> "$log_file"
                        log_error "Secret detected [${pname}] in ${file}:${line_num}"
                    fi
                done <<< "$content"
                ((pattern_idx++)) || true
            done
            continue
        fi

        # ── Scan file against all patterns ───────────────
        local pattern_idx=0
        while [[ $pattern_idx -lt ${#pattern_names[@]} ]]; do
            local pname="${pattern_names[$pattern_idx]}"
            local pregex="${pattern_regexes[$pattern_idx]}"

            # grep -nE returns "linenum:content" — extract only line number
            # Use -e to avoid patterns starting with -- being parsed as flags
            local matches
            matches=$(grep -nE -e "$pregex" "$full_path" 2>/dev/null || true)
            if [[ -n "$matches" ]]; then
                while IFS= read -r match_line; do
                    local line_num="${match_line%%:*}"
                    found_secrets=true
                    echo "FOUND: ${pname} at ${file}:${line_num}" >> "$log_file"
                    log_error "Secret detected [${pname}] in ${file}:${line_num}"
                done <<< "$matches"
            fi
            ((pattern_idx++)) || true
        done

    done <<< "$changed_files"

    # ── Write footer and return ──────────────────────────
    if $found_secrets; then
        echo "---" >> "$log_file"
        echo "RESULT: BLOCKED" >> "$log_file"
        return 1
    else
        echo "---" >> "$log_file"
        echo "RESULT: CLEAN" >> "$log_file"
        return 0
    fi
}
