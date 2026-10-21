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
    printf "    %-14s %s\n" "Logs" "${LOGS_DIR#"${PROJECT_ROOT}"/}/"
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
    local was_complete=false
    if [[ "$(jq -r '.status // ""' "$STATE_FILE" 2>/dev/null)" == "completed" ]]; then
        was_complete=true
    fi

    # Get branches in topological order; skip ones already merged
    local branches=() missing=()
    local total=0 skipped=0
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
            missing+=("${task_id}: ${branch}")
        elif _git merge-base --is-ancestor "$branch" "$integrate_branch" 2>/dev/null; then
            skipped=$((skipped + 1))
            log_verbose "Branch ${branch} already merged"
        else
            branches+=("$branch")
        fi
    done <<< "$ordered_tasks"

    log_info "Feature '${FEATURE_NAME}': ${total} done tasks, merging into '${integrate_branch}'"
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_warn "${#missing[@]} done tasks have no branch, so they can't be merged:"
        for m in "${missing[@]}"; do
            echo "    - ${m}"
        done
    fi
    if [[ $skipped -gt 0 ]]; then
        log_step "${skipped} of ${total} branches already merged into ${integrate_branch}"
    fi

    # Integrating into a branch other than the one checked out is easy to do by accident.
    local current_branch
    current_branch=$(_git branch --show-current 2>/dev/null || true)
    if [[ -n "$current_branch" && "$current_branch" != "$integrate_branch" \
          && -z "${MAIN_BRANCH:-}" && "$assume_yes" != true ]]; then
        log_warn "You are on '${current_branch}', but integrate merges into '${integrate_branch}' (set MAIN_BRANCH to change)"
        if _integrate_has_tty; then
            local answer=""
            read -r -p "Integrate into '${integrate_branch}'? [y/N] " answer </dev/tty || answer=""
            if [[ ! "$answer" =~ ^[Yy]$ ]]; then
                log_info "Cancelled. Nothing was merged"
                exit 1
            fi
        else
            log_error "No terminal to confirm. Rerun with MAIN_BRANCH=${integrate_branch} or --yes"
            exit 1
        fi
    fi

    local branch_summary
    if [[ ${#branches[@]} -eq 0 ]]; then
        log_info "Nothing new to merge, so going straight to verification"
        branch_summary="${total} done, all already in ${integrate_branch}"
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

    local report
    report=$(parse_agent_json "$output" 2>/dev/null) || report=""
    if [[ -n "$report" ]] && jq -e 'type == "object"' >/dev/null 2>&1 <<< "$report"; then
        log_success "Integrator reports $(jq '.merged_branches // [] | length' <<< "$report") merged, $(jq '.conflicts_resolved // [] | length' <<< "$report") conflicts resolved, $(jq '.failed_merges // [] | length' <<< "$report") failed"
    else
        log_warn "Integrator report has no JSON summary"
    fi
    log_info "Full Integrator report: ${LOGS_DIR#"${PROJECT_ROOT}"/}/integration.log"

    # Don't trust the agent's report; check in git that every branch landed.
    if [[ -f "$(_git rev-parse --git-path MERGE_HEAD)" ]]; then
        log_error "A merge is still in progress in ${PROJECT_ROOT}; resolve or abort it, then rerun"
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
        log_error "Feature not marked complete. See ${LOGS_DIR}/integration.log"
        exit "$EXIT_MERGE_CONFLICT"
    fi
    log_success "Verified in git: all ${#branches[@]} branches are in ${integrate_branch}"
    branch_summary="${#branches[@]} merged now, ${skipped} already merged; verified in git"
    fi
    if [[ ${#missing[@]} -gt 0 ]]; then
        branch_summary+="; ${#missing[@]} with no branch"
    fi

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
        log_info "Checked out '${integrate_branch}' to run the checks"
    fi

    # Checks that fail stop the feature from being marked complete.
    local failed_checks=()
    local regression_summary contract_summary guardian_summary coverage_summary

    local gate_cmds
    gate_cmds=$(for g in test lint typecheck; do gates_get_config "$g" both || true; done | sed '/^$/d' | paste -sd ',' - | sed 's/,/, /g') || gate_cmds=""
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
        echo -e "  1. Check ${COLOR_STEP}${LOGS_DIR}/integration.log${RESET} for details"
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
            contract_summary="✗ FAILED (${CONTRACT_PASSED:-0}/${CONTRACT_TOTAL:-?} found)"
            log_error "This means the implementation doesn't support the product's core question"
        fi
    fi

    # ── Post-integration: Guardian vision check ──────────────────
    # Check: does the integrated result still align with the product vision?
    if [[ "${SKIP_GUARDIAN:-}" != "true" ]]; then
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
               echo -e "Report: ${COLOR_STEP}${LOGS_DIR}/guardian-post-integration-*.json${RESET}" ;;
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
        ) 2>/dev/null || trace_output=""
        if [[ -n "$trace_output" ]]; then
            log_success "Spec traceability: ${trace_output} coverage → spec-traceability.json"
            coverage_summary="$trace_output"
        fi
    fi

    if [[ ${#failed_checks[@]} -gt 0 ]]; then
        _integrate_summary "✗ Not complete: ${failed_checks[*]} failed. Fix and run 'speed integrate' again"
        log_error "Integration checks failed: ${failed_checks[*]}"
        log_error "Feature not marked complete. Fix the failures and run 'speed integrate' again"
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
        '.status = "completed" | .completed_at = $ts' \
        "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"

    [[ "${MP_ENABLED:-}" == "true" ]] && event_emit "integrate.completed" "$FEATURE_NAME" "{\"branches_merged\":${#branches[@]}}" || true

    if [[ "$was_complete" == true && ${#branches[@]} -eq 0 ]]; then
        _integrate_summary "✓ Already complete; re-verified and all checks pass"
    else
        _integrate_summary "✓ Feature complete"
    fi
}
