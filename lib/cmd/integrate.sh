#!/usr/bin/env bash
# integrate.sh — Task integration command

_cmd_integrate_defect() {
    local name="$1"

    # 1. Validate defect exists
    local state_json
    if ! state_json=$(defect_state_read "$name"); then
        log_error "Defect not found: ${name}"
        exit 1
    fi

    # 2. Read current status
    local state
    state=$(echo "$state_json" | jq -r '.status')

    # 3. Read complexity from triage
    local triage_json complexity=""
    if triage_json=$(defect_triage_read "$name" 2>/dev/null); then
        complexity=$(echo "$triage_json" | jq -r '.complexity // ""' 2>/dev/null)
    fi

    # 4. Validate state
    if [[ "$state" != "fixed" && "$state" != "reviewed" ]]; then
        log_error "Defect ${name} is in state ${state}, expected fixed or reviewed"
        exit 1
    fi

    # 5. For moderate defects in fixed state, run review first
    if [[ "$complexity" == "moderate" && "$state" == "fixed" ]]; then
        log_step "Running fix review for moderate defect '${name}'..."
        if ! review_defect_fix "$name"; then
            log_error "Review failed for defect '${name}' — fix issues and retry"
            exit 1
        fi
    fi

    # 6. Integrate (runs guardian check, merges, and runs regression)
    integrate_defect "$name"
}
_integrate_has_tty() {
    [[ "${SPEED_NO_TTY:-}" == 1 ]] && return 1
    { : </dev/tty; } 2>/dev/null
}

# Print the end-of-run summary. Reads the caller's locals.
_integrate_summary() {
    local result="$1"
    echo ""
    echo -e "  ${BOLD}Integration summary${RESET}  ${FEATURE_NAME} → ${integrate_branch}"
    printf "    %-14s %s\n" "Branches" "$branch_summary"
    printf "    %-14s %s\n" "Regression" "$regression_summary"
    printf "    %-14s %s\n" "Contract" "$contract_summary"
    printf "    %-14s %s\n" "Guardian" "$guardian_summary"
    printf "    %-14s %s\n" "Spec coverage" "$coverage_summary"
    printf "    %-14s %s\n" "Logs" "${logs_rel}/"
    echo -e "    $(printf '%-14s' Result) ${result}"
    echo ""
}

cmd_integrate() {
    local skip_tests=false
    local assume_yes=false
    local defect_name=""

    # Parse flags before _require_feature so --defect can skip feature requirement
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skip-tests) skip_tests=true; shift ;;
            --yes|-y)     assume_yes=true; shift ;;
            --defect)     _need_value "$@"; defect_name="$2"; shift 2 ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    # Defect mode: bypass feature requirement entirely
    if [[ -n "$defect_name" ]]; then
        _cmd_integrate_defect "$defect_name"
        return
    fi

    _require_feature "$GLOBAL_FEATURE"

    # ── Acquire exclusive lock ────────────────────────────────────
    speed_acquire_lock "integrate" || exit 1

    log_header "Integrating Completed Work"

    # Check for circular dependencies
    if ! task_topo_sort > /dev/null; then
        log_error "Cannot integrate: circular dependencies in task graph."
        exit 1
    fi

    local done_tasks
    done_tasks=$(task_list_by_status "done")

    if [[ -z "$done_tasks" ]]; then
        log_info "No completed tasks to integrate."
        return
    fi

    local integrate_branch
    integrate_branch=$(git_main_branch)
    if ! git_branch_exists "$integrate_branch"; then
        log_error "Target branch '${integrate_branch}' does not exist. Create it or set MAIN_BRANCH to an existing branch"
        exit 1
    fi
    local logs_rel="${LOGS_DIR#"${PROJECT_ROOT}"/}"
    local was_complete=false
    if [[ "$(jq -r '.status // ""' "$STATE_FILE" 2>/dev/null)" == "completed" ]]; then
        was_complete=true
    fi

    # Get branches in topological order; skip ones already merged
    local branches=() missing=()
    local total=0 skipped=0
    local merge_subjects
    local ordered_tasks
    ordered_tasks=$(task_topo_sort)

    while IFS= read -r task_id; do
        local status
        status=$(jq -r '.status // "unknown"' "${TASKS_DIR}/${task_id}.json")
        [[ "$status" == "done" ]] || continue
        local branch
        branch=$(jq -r '.branch' "${TASKS_DIR}/${task_id}.json")
        total=$((total + 1))
        if ! git_branch_exists "$branch"; then
            # A branch deleted after merging leaves its merge commit behind.
            if [[ -z "${merge_subjects+set}" ]]; then
                merge_subjects=$(_git log --merges --format=%s "$integrate_branch" 2>/dev/null || true)
            fi
            if awk -v b="$branch" '{ for (i = 1; i <= NF; i++) { w = $i; gsub(/^["\047]|["\047]$/, "", w); if (w == b) found = 1 } }
                    END { exit !found }' <<< "$merge_subjects"; then
                skipped=$((skipped + 1))
                log_verbose "Branch ${branch} already merged and deleted"
            else
                missing+=("${task_id}: ${branch}")
            fi
        elif _git merge-base --is-ancestor "$branch" "$integrate_branch" 2>/dev/null; then
            skipped=$((skipped + 1))
            log_verbose "Branch ${branch} already merged"
        else
            branches+=("$branch")
        fi
    done <<< "$ordered_tasks"

    log_info "Feature '${FEATURE_NAME}': ${total} done tasks, merging into '${integrate_branch}'"
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_warn "${#missing[@]} done tasks have no branch, and their work isn't in '${integrate_branch}':"
        for m in "${missing[@]}"; do
            echo "    - ${m}"
        done
    fi
    if [[ $skipped -gt 0 ]]; then
        log_step "${skipped} of ${total} branches already merged into ${integrate_branch}"
    fi

    # Integrating into a branch other than the one checked out is easy to do by accident.
    local current_branch head_label
    current_branch=$(_git branch --show-current 2>/dev/null || true)
    head_label="'${current_branch}'"
    if [[ -z "$current_branch" ]]; then
        head_label="a detached HEAD ($(_git rev-parse --short HEAD 2>/dev/null || echo unknown))"
    fi
    if [[ "$current_branch" != "$integrate_branch" && -z "${MAIN_BRANCH:-}" && "$assume_yes" != true ]]; then
        log_warn "You are on ${head_label}, but integrate works on '${integrate_branch}' (set MAIN_BRANCH to change)"
        local question="Switch to '${integrate_branch}' to re-verify? [y/N] "
        [[ ${#branches[@]} -gt 0 ]] && question="Integrate ${#branches[@]} branches into '${integrate_branch}'? [y/N] "
        if _integrate_has_tty; then
            local answer=""
            read -r -p "$question" answer </dev/tty || answer=""
            if [[ ! "$answer" =~ ^[Yy]$ ]]; then
                log_info "Cancelled. Nothing was changed"
                exit 1
            fi
        else
            log_error "No terminal to confirm. Rerun with MAIN_BRANCH=${integrate_branch} or --yes"
            exit 1
        fi
    fi

    # Refuse before anything is merged or checked out.
    if [[ ${#branches[@]} -gt 0 || "$current_branch" != "$integrate_branch" ]]; then
        if [[ -n "$(_git status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
            log_error "There are uncommitted changes in ${PROJECT_ROOT}. Commit or stash them, then rerun"
            exit 1
        fi
        local wt_line wt_path="" other_worktree="" here
        here=$(cd "$PROJECT_ROOT" && pwd -P)
        while IFS= read -r wt_line; do
            case "$wt_line" in
                "worktree "*) wt_path="${wt_line#worktree }" ;;
                "branch refs/heads/${integrate_branch}")
                    if [[ "$(cd "$wt_path" 2>/dev/null && pwd -P)" != "$here" ]]; then
                        other_worktree="$wt_path"
                    fi ;;
            esac
        done < <(_git worktree list --porcelain 2>/dev/null || true)
        if [[ -n "$other_worktree" ]]; then
            log_error "'${integrate_branch}' is checked out in another worktree: ${other_worktree}"
            log_error "Run integrate from that worktree, or free the branch there (or 'git worktree prune' if it is gone)"
            exit 1
        fi
    fi

    local branch_summary
    if [[ ${#branches[@]} -eq 0 ]]; then
        log_info "Nothing new to merge, so going straight to verification"
        :
    else

    log_step "Merging ${#branches[@]} branches in dependency order..."

    # Build branch list for integrator
    local branch_list=""
    for b in "${branches[@]}"; do
        branch_list+="- ${b}"$'\n'
    done

    local agent_message="## Integration Task

Merge the following branches into ${integrate_branch}, in the order listed (dependency order):

${branch_list}

### Working Directory
${PROJECT_ROOT}

### Instructions
1. For each branch, checkout ${integrate_branch}, then merge the branch with --no-ff
2. If there are merge conflicts, resolve them intelligently
3. After each merge, verify the code still works
4. Report results as JSON"

    log_step "Sending to Integrator agent..."

    local output
    if ! output=$(provider_run \
        "${AGENTS_DIR}/integrator.md" \
        "$agent_message" \
        "$MODEL_SUPPORT" \
        "$AGENT_TOOLS_FULL" \
        "Integrator"); then
        log_error "Integrator agent failed — check agent CLI connection"
        exit 1
    fi

    if [[ -z "$output" ]]; then
        log_error "Integrator agent returned empty output"
        exit 1
    fi

    echo "$output" > "${LOGS_DIR}/integration.log"
    if [[ "${VERBOSITY:-1}" -ge 2 ]]; then
        echo "$output"
    fi

    local report counts=""
    report=$(parse_agent_json "$output" 2>/dev/null) || report=""
    if [[ -n "$report" ]]; then
        counts=$(jq -r 'def n(k): (.[k] // [] | if type == "array" then length else null end);
            [n("merged_branches"), n("conflicts_resolved"), n("failed_merges")]
            | if any(. == null) then empty else @tsv end' <<< "$report" 2>/dev/null) || counts=""
    fi
    if [[ -n "$counts" ]]; then
        local n_merged n_conflicts n_failed
        IFS=$'\t' read -r n_merged n_conflicts n_failed <<< "$counts"
        if [[ "$n_failed" -gt 0 ]]; then
            log_warn "Integrator reports ${n_merged} merged, ${n_conflicts} conflicts resolved, ${n_failed} failed"
        else
            log_success "Integrator reports ${n_merged} merged, ${n_conflicts} conflicts resolved, ${n_failed} failed"
        fi
    else
        log_warn "Integrator report isn't in the expected JSON format"
    fi
    log_info "Full Integrator report: ${logs_rel}/integration.log"

    # Don't trust the agent's report; check in git that every branch landed.
    if [[ -f "$(_git rev-parse --git-path MERGE_HEAD)" ]]; then
        log_error "A merge is still in progress in ${PROJECT_ROOT}; resolve or abort it, then rerun"
        log_error "Feature not marked complete"
        exit "$EXIT_MERGE_CONFLICT"
    fi
    if [[ -n "$(_git status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
        log_error "The Integrator left uncommitted changes in ${PROJECT_ROOT}. See ${logs_rel}/integration.log"
        log_error "Feature not marked complete"
        exit "$EXIT_MERGE_CONFLICT"
    fi
    local unmerged=()
    for b in "${branches[@]}"; do
        _git merge-base --is-ancestor "$b" "$integrate_branch" 2>/dev/null || unmerged+=("$b")
    done
    if [[ ${#unmerged[@]} -gt 0 ]]; then
        log_error "${#unmerged[@]} of ${#branches[@]} branches are not in ${integrate_branch} after the Integrator ran:"
        for b in "${unmerged[@]}"; do
            echo "    - ${b}"
        done
        log_error "Feature not marked complete. See ${logs_rel}/integration.log"
        exit "$EXIT_MERGE_CONFLICT"
    fi
    log_success "Verified in git: all ${#branches[@]} branches are in ${integrate_branch}"
    fi

    local branch_parts=()
    [[ ${#branches[@]} -gt 0 ]] && branch_parts+=("${#branches[@]} merged now (verified in git)")
    [[ $skipped -gt 0 ]] && branch_parts+=("${skipped} already in ${integrate_branch}")
    [[ ${#missing[@]} -gt 0 ]] && branch_parts+=("${#missing[@]} not found (no branch)")
    branch_summary=$(IFS=';'; echo "${branch_parts[*]}")
    branch_summary="${total} done: ${branch_summary//;/, }"

    # ── Post-integration: regression tests ────────────────────────
    echo ""
    log_header "Post-Integration Verification"

    # The checks must look at the branch that was integrated into.
    local head_branch
    head_branch=$(_git branch --show-current 2>/dev/null || true)
    if [[ "$head_branch" != "$integrate_branch" ]]; then
        if [[ -n "$(_git status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
            log_error "Checks must run on '${integrate_branch}', but '${head_branch:-HEAD}' has uncommitted changes. Commit or stash them, then rerun"
            exit 1
        fi
        if ! _git checkout -q "$integrate_branch"; then
            log_error "Could not check out '${integrate_branch}' to run the checks"
            exit 1
        fi
        log_info "Checked out '${integrate_branch}' to run the checks (you were on ${head_label})"
    fi

    # Checks that fail stop the feature from being marked complete.
    local failed_checks=()
    local regression_summary contract_summary guardian_summary coverage_summary

    local gate_cmds="" gate_cmd
    while IFS= read -r gate_cmd; do
        [[ -n "$gate_cmd" ]] && gate_cmds+="${gate_cmds:+; }${gate_cmd}"
    done < <(for g in test lint typecheck; do gates_get_config "$g" both || true; done)
    if [[ "$skip_tests" == true ]]; then
        log_info "Regression tests skipped (--skip-tests)"
        _log_gate_skip "tests" "integrate"
        regression_summary="skipped (--skip-tests)"
    elif [[ -z "$gate_cmds" ]]; then
        log_warn "No quality gates configured, so regression checked nothing"
        log_warn "Add a '## Quality Gates' section (e.g. '- test: \`npm test\`') to ${AGENT_FILE:-AGENTS.md}"
        _log_gate_skip "tests" "integrate"
        regression_summary="not configured (nothing tested)"
    elif regression_run; then
        log_success "Regression tests passed"
        regression_summary="✓ passed (${gate_cmds})"
    else
        failed_checks+=("regression tests")
        regression_summary="✗ FAILED (${gate_cmds})"
        log_error "Regression tests FAILED after integration"
        log_error "The merge may have introduced incompatibilities"
        echo ""
        echo -e "Options:"
        echo -e "  1. Check the gate logs in ${COLOR_STEP}${logs_rel}/${RESET}"
        echo -e "  2. Use ${COLOR_STEP}git log --oneline${RESET} to review merge commits"
        echo -e "  3. Use ${COLOR_STEP}git reset --hard HEAD~N${RESET} to rollback (destructive)"
        echo ""
    fi

    # ── Post-integration: rebuild CSG for accurate contract check ──
    local csg_start=$SECONDS
    if context_build_layer1 "true" >/dev/null 2>&1; then
        log_success "Code index rebuilt ($((SECONDS - csg_start))s)"
    else
        log_warn "Code index rebuild failed, so the contract check uses the previous index"
    fi

    # ── Post-integration: contract check ──────────────────────────
    contract_summary="no contract"
    if [[ -f "${CONTRACT_FILE}" ]]; then
        if contract_check; then
            contract_summary="✓ ${CONTRACT_PASSED}/${CONTRACT_TOTAL} declared artifacts found"
        else
            failed_checks+=("contract check")
            if [[ -n "${CONTRACT_TOTAL:-}" ]]; then
                contract_summary="✗ FAILED (${CONTRACT_PASSED}/${CONTRACT_TOTAL} found)"
                log_error "This means the implementation doesn't support the product's core question"
            else
                contract_summary="✗ could not run (see the error above)"
            fi
        fi
    fi

    # ── Post-integration: Guardian vision check ──────────────────
    # Check: does the integrated result still align with the product vision?
    if [[ "${SKIP_GUARDIAN:-}" != "true" && ! -f "${PROJECT_ROOT}/${VISION_FILE}" ]]; then
        log_info "Guardian check skipped (no product overview at ${VISION_FILE})"
        _log_gate_skip "guardian_post_integration" "integrate"
        guardian_summary="skipped (no ${VISION_FILE})"
    elif [[ "${SKIP_GUARDIAN:-}" != "true" ]]; then
        echo ""
        log_header "Post-Integration Vision Check"

        # Gather the full integration diff
        local integration_diff=""
        for b in "${branches[@]}"; do
            integration_diff+="--- Branch: ${b} ---"$'\n'
            integration_diff+=$(git_diff_branch "$b" 2>/dev/null || echo "No diff")$'\n\n'
        done

        # Include the spec for context
        local spec_content=""
        local spec_file
        spec_file=$(_get_spec_path)
        if [[ -n "$spec_file" ]] && [[ -f "$spec_file" ]]; then
            spec_content="
### Feature Specification
$(cat "$spec_file")"
        fi

        local guardian_input="## Integrated Work: ${#branches[@]} branches merged

### Combined Diff
${integration_diff}
${spec_content}

This is a post-integration check. Evaluate whether the integrated result, taken as a whole, is consistent with the product vision."

        local grc=0
        local _guardian_out
        _guardian_out=$(_run_guardian "post-integration" "$guardian_input" "integration") || grc=$?
        case $grc in
            0) guardian_summary="✓ aligned" ;;
            2) guardian_summary="flagged (see guardian report)" ;;
            3) guardian_summary="no usable answer"
               log_warn "Guardian returned unparseable output during post-integration check" ;;
            *) guardian_summary="✗ REJECTED"
               failed_checks+=("guardian")
               echo ""
               log_error "Guardian REJECTED the integrated result — vision violation detected"
               log_error "Review the guardian report before shipping"
               echo -e "Report: ${COLOR_STEP}${logs_rel}/guardian-post-integration-*.json${RESET}" ;;
        esac
    else
        log_info "Guardian check skipped (SKIP_GUARDIAN=true)"
        _log_gate_skip "guardian_post_integration" "integrate"
        guardian_summary="skipped (SKIP_GUARDIAN=true)"
    fi

    # ── Post-integration: spec traceability ──────────────────────
    coverage_summary="no spec"
    local spec_file
    spec_file=$(_get_spec_path)
    if [[ -n "$spec_file" ]] && [[ -f "$spec_file" ]]; then
        coverage_summary="could not compute (see ${logs_rel}/integrate.log)"
        local trace_output
        trace_output=$($(_context_python) - "${TASKS_DIR}" "${FEATURE_DIR}/spec-traceability.json" "$spec_file" <<'PYTHON_EOF'
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))
all_tasks_dir = sys.argv[1]
output_path = sys.argv[2]
spec_path = sys.argv[3]
with open(spec_path) as f:
    spec_content = f.read()
all_tasks = []
if os.path.isdir(all_tasks_dir):
    for fname in sorted(os.listdir(all_tasks_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(all_tasks_dir, fname)) as f:
                all_tasks.append(json.load(f))
from lib.spec_traceability import spec_to_task_check
from lib.context.utils import write_json
result = spec_to_task_check(spec_content, all_tasks)
write_json(output_path, result)
print(f"{result.get('coverage_ratio', 0)}")
PYTHON_EOF
        ) 2>>"${LOGS_DIR}/integrate.log" || trace_output=""
        if [[ -n "$trace_output" ]]; then
            log_success "Spec traceability: ${trace_output} coverage → spec-traceability.json"
            coverage_summary="$trace_output"
        fi
    fi

    if [[ ${#failed_checks[@]} -gt 0 ]]; then
        local failed_list
        failed_list=$(IFS=';'; echo "${failed_checks[*]}")
        failed_list="${failed_list//;/, }"
        if [[ "$was_complete" == true ]]; then
            _integrate_summary "✗ Checks now fail (${failed_list}), though the feature was marked complete before"
        else
            _integrate_summary "✗ Not complete: ${failed_list} failed. Fix and run 'speed integrate' again"
        fi
        log_error "Integration checks failed: ${failed_list}"
        exit "$EXIT_GATE_FAILURE"
    fi

    # ── Post-integration: observation extraction ─────────────────
    echo ""
    local run_learn="n"
    if _integrate_has_tty; then
        read -r -p "Integration complete. Run observation extraction? [Y/n] " run_learn </dev/tty || run_learn="n"
        run_learn="${run_learn:-y}"
    else
        log_info "No terminal, so skipping observation extraction (run 'speed learn' to do it later)"
    fi
    if [[ "$run_learn" =~ ^[Yy]$ ]]; then
        cmd_learn || log_warn "Observation extraction failed (non-blocking)"
    fi

    # Mark feature complete
    jq --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '.status = "completed" | .completed_at = (.completed_at // $ts)' \
        "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"

    [[ "${MP_ENABLED:-}" == "true" ]] && event_emit "integrate.completed" "$FEATURE_NAME" "{\"branches_merged\":${#branches[@]}}" || true

    if [[ "$was_complete" == true && ${#branches[@]} -eq 0 ]]; then
        _integrate_summary "✓ Already complete; re-verified and all checks pass"
    else
        _integrate_summary "✓ Feature complete"
    fi
}
