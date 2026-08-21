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
cmd_integrate() {
    local skip_tests=false
    local defect_name=""

    # Parse flags before _require_feature so --defect can skip feature requirement
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skip-tests) skip_tests=true; shift ;;
            --defect)     defect_name="$2"; shift 2 ;;
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

    # Get branches in topological order
    local branches=()
    local ordered_tasks
    ordered_tasks=$(task_topo_sort)

    while IFS= read -r task_id; do
        local status
        status=$(jq -r '.status // "unknown"' "${TASKS_DIR}/${task_id}.json")
        if [[ "$status" == "done" ]]; then
            local branch
            branch=$(jq -r '.branch' "${TASKS_DIR}/${task_id}.json")
            if git_branch_exists "$branch"; then
                # Skip branches already merged (idempotent)
                if _git merge-base --is-ancestor "$branch" "$(git_main_branch)" 2>/dev/null; then
                    log_step "Branch ${branch} already merged — skipping"
                    continue
                fi
                branches+=("$branch")
            fi
        fi
    done <<< "$ordered_tasks"

    if [[ ${#branches[@]} -eq 0 ]]; then
        log_info "All branches already merged — skipping to verification."
    else

    log_step "Merging ${#branches[@]} branches in dependency order..."
    echo ""

    # Build branch list for integrator
    local branch_list=""
    for b in "${branches[@]}"; do
        branch_list+="- ${b}"$'\n'
    done

    local integrate_branch
    integrate_branch=$(git_main_branch)

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

    echo "$output"
    echo ""

    # Save integration log
    echo "$output" > "${LOGS_DIR}/integration.log"
    log_success "Integration log saved to ${LOGS_DIR}/integration.log"
    fi

    # ── Post-integration: regression tests ────────────────────────
    echo ""
    log_header "Post-Integration Verification"

    if [[ "$skip_tests" == true ]]; then
        log_info "Regression tests skipped (--skip-tests)"
        _log_gate_skip "tests" "integrate"
    elif regression_run; then
        log_success "Regression tests passed"
    else
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
    log_step "Rebuilding code symbol graph..."
    context_build_layer1 "true" >/dev/null 2>&1 || log_warn "CSG rebuild failed — contract check will use stale index"

    # ── Post-integration: contract check ──────────────────────────
    if [[ -f "${CONTRACT_FILE}" ]]; then
        if contract_check; then
            log_success "Contract check passed — schema matches plan"
        else
            log_error "Contract check FAILED — built schema doesn't match the plan"
            log_error "This means the implementation doesn't support the product's core question"
            echo ""

            # Invoke supervisor for contract failure
            _invoke_supervisor "0" "contract"
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
        if [[ $grc -eq 1 ]]; then
            echo ""
            log_error "Guardian REJECTED the integrated result — vision violation detected"
            log_error "Review the guardian report before shipping"
            echo -e "Report: ${COLOR_STEP}${LOGS_DIR}/guardian-post-integration-*.json${RESET}"
        elif [[ $grc -eq 3 ]]; then
            log_warn "Guardian returned unparseable output during post-integration check"
        fi
    else
        _log_gate_skip "guardian_post_integration" "integrate"
    fi

    # ── Post-integration: spec traceability ──────────────────────
    local spec_file
    spec_file=$(_get_spec_path)
    if [[ -n "$spec_file" ]] && [[ -f "$spec_file" ]]; then
        log_step "Running spec traceability..."
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
        fi
    fi

    # ── Post-integration: observation extraction ─────────────────
    echo ""
    local run_learn="y"
    read -r -p "Integration complete. Run observation extraction? [Y/n] " run_learn </dev/tty || run_learn="y"
    run_learn="${run_learn:-y}"
    if [[ "$run_learn" =~ ^[Yy]$ ]]; then
        cmd_learn || log_warn "Observation extraction failed (non-blocking)"
    fi

    echo ""

    # Mark feature complete
    jq --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '.status = "completed" | .completed_at = $ts' \
        "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"

    [[ "${MP_ENABLED:-}" == "true" ]] && event_emit "integrate.completed" "$FEATURE_NAME" "{\"branches_merged\":${#branches[@]}}" || true

    log_success "Feature marked complete"
}
