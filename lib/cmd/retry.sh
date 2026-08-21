#!/usr/bin/env bash
# retry.sh — Task retry, recover, and fix-nits commands

_cmd_retry_defect() {
    local name="$1"
    local context="$2"
    local escalate="$3"

    # 1. Validate defect exists
    local state_json
    if ! state_json=$(defect_state_read "$name" 2>/dev/null); then
        log_error "Defect not found: ${name}"
        exit 1
    fi

    # 2. Read current status
    local current_status
    current_status=$(echo "$state_json" | jq -r '.status // empty')

    # 3. Escalate mode
    if [[ "$escalate" == "true" ]]; then
        local prd_path
        if ! prd_path=$(escalate_to_feature "$name"); then
            log_error "Failed to escalate defect '${name}' to feature"
            exit 1
        fi
        transition_defect_state "$name" "escalated"
        log_success "Defect '${name}' escalated to feature — PRD at ${prd_path}"
        echo -e "Next: ${COLOR_STEP}speed plan ${prd_path}${RESET}"
        return
    fi

    # 4. If context provided, append to context.md and reset to triaged
    if [[ -n "$context" ]]; then
        local context_file
        context_file="$(_defect_dir "$name")/context.md"
        echo "$context" >> "$context_file"
        log_info "Context added to ${context_file}"
        transition_defect_state "$name" "triaged"
        current_status="triaged"
    fi

    # 5. Determine failed stage and re-run
    case "$current_status" in
        reproducing)
            log_step "Re-running reproduce stage for '${name}'"
            reproduce_defect "$name"
            ;;
        fixing|triaged)
            log_step "Re-running fix stage for '${name}'"
            fix_defect "$name"
            ;;
        reviewing)
            log_step "Re-running review stage for '${name}'"
            review_defect_fix "$name"
            ;;
        integrating)
            log_step "Re-running integrate stage for '${name}'"
            integrate_defect "$name"
            ;;
        *)
            log_error "Cannot retry defect '${name}' from state '${current_status}'"
            log_error "Valid retryable states: reproducing, fixing, triaged, reviewing, integrating"
            exit 1
            ;;
    esac
}
cmd_retry() {
    local task_id=""
    local escalate=false
    local reset_branch=false
    local context=""
    local defect_name=""
    local context_flag_used=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --task-id)  task_id="$2"; shift 2 ;;
            --escalate) escalate=true; shift ;;
            --reset-branch) reset_branch=true; shift ;;
            --defect)   defect_name="$2"; shift 2 ;;
            --context)
                context_flag_used=true
                if [[ -z "${2:-}" ]] || [[ "${2:-}" == --* ]]; then
                    shift
                else
                    context="$2"; shift 2
                fi
                ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    # --defect mode: validate context flag usage and dispatch
    if [[ -n "$defect_name" ]]; then
        if [[ "$context_flag_used" == "true" ]] && [[ -z "$context" ]]; then
            log_error "Missing context text for --context flag"
            exit 1
        fi
        _cmd_retry_defect "$defect_name" "$context" "$escalate"
        return
    fi

    _require_feature "$GLOBAL_FEATURE"

    if [[ -z "$task_id" ]]; then
        log_error "Required: --task-id ID"
        log_error "Retry requires targeting a specific task. Use ${COLOR_STEP}speed status${RESET} to see failed tasks."
        exit 1
    fi

    if [[ -z "$context" ]]; then
        # Show the failure details so the human can diagnose
        local task_json
        task_json=$(task_get "$task_id")
        local title error_msg status retry_count
        title=$(echo "$task_json" | jq -r '.title')
        error_msg=$(echo "$task_json" | jq -r '.error // "No error details"')
        status=$(echo "$task_json" | jq -r '.status')
        retry_count=$(echo "$task_json" | jq -r '.retry_count // 0')

        echo ""
        echo -e "${BOLD}Task ${task_id}:${RESET} ${title}"
        echo -e "${BOLD}Status:${RESET} ${status}"
        echo -e "${BOLD}Error:${RESET} ${error_msg}"
        echo -e "${BOLD}Previous retries:${RESET} ${retry_count}"

        # Show debugger analysis if available
        local debugger_log="${LOGS_DIR}/debugger-${task_id}.json"
        if [[ -f "$debugger_log" ]]; then
            echo ""
            echo -e "${BOLD}Debugger analysis:${RESET}"
            echo -e "  ${COLOR_DIM}$(cat "$debugger_log" | jq -r '.root_cause // .diagnosis // "See full log"' 2>/dev/null)${RESET}"
        fi

        echo ""
        log_error "Blind retries are not allowed. Diagnose the failure and provide guidance:"
        echo -e "  ${COLOR_STEP}speed retry --task-id ${task_id} --context \"what to do differently\"${RESET}"
        echo ""
        exit 1
    fi

    local task_json
    task_json=$(task_get "$task_id")
    local title current_model error_msg status
    title=$(echo "$task_json" | jq -r '.title')
    current_model=$(echo "$task_json" | jq -r '.agent_model')
    error_msg=$(echo "$task_json" | jq -r '.error // "No error details"')
    status=$(echo "$task_json" | jq -r '.status')

    if [[ "$status" != "failed" ]] && [[ "$status" != "blocked" ]]; then
        log_error "Task ${task_id} is '${status}', not failed or blocked. Nothing to retry."
        exit 1
    fi

    log_step "Retrying task ${task_id}: ${COLOR_STEP}${title}${RESET}"

    # Accumulate attempt history — append, never overwrite
    local prev_feedback
    prev_feedback=$(echo "$task_json" | jq -r '.review_feedback // ""')
    local retry_count
    retry_count=$(echo "$task_json" | jq -r '.retry_count // 0')
    local attempt_entry
    attempt_entry="--- Attempt $((retry_count + 1)) ---\nFailed with: ${error_msg}\nHuman guidance: ${context}"

    local accumulated_feedback
    if [[ -n "$prev_feedback" ]]; then
        accumulated_feedback="${prev_feedback}\n\n${attempt_entry}"
    else
        accumulated_feedback="$attempt_entry"
    fi
    task_update "$task_id" "review_feedback" "$(echo -e "$accumulated_feedback")"

    # Escalate model if requested
    if $escalate; then
        local new_model
        if [[ "$current_model" == "$MODEL_PLANNING" ]]; then
            new_model="$MODEL_PLANNING"
        else
            new_model="$MODEL_PLANNING"
        fi
        task_update "$task_id" "agent_model" "$new_model"
        log_info "Escalated model: ${current_model} → ${new_model}"
    fi

    # Check if branch already has work that passes gates.
    # Skip when --context was provided: the user explicitly wants a retry
    # with new guidance, not an automatic resolution.
    if ! $reset_branch; then
        log_step "Checking branch for existing work..."
        local audit_result
        audit_result=$(branch_audit "$task_id")

        if [[ "$audit_result" == "pass" ]]; then
            task_set_done "$task_id"
            log_success "Task ${task_id}: prior work passes gates — marked DONE"
            echo ""
            echo -e "No retry needed. Task is complete."
            echo ""
            return 0
        fi
        if [[ "$audit_result" == "blocked" ]]; then
            log_warn "Task ${task_id}: prior agent was blocked — supervisor analysis recommended"
            echo -e "Prior agent reported blocked. Review supervisor analysis before retrying."
            echo ""
        fi
    fi

    # Clean up stale worktree if present
    git_remove_worktree "$task_id"

    # Force-delete tainted branch if requested
    if $reset_branch; then
        local branch
        branch=$(jq -r '.branch // empty' "${TASKS_DIR}/${task_id}.json" 2>/dev/null)
        if [[ -n "$branch" ]] && [[ "$branch" != "null" ]]; then
            git_force_delete_branch "$branch"
            log_step "Deleted branch: ${branch}"
        fi
    fi

    # Atomic reset to pending (increments retry_count)
    task_reset_pending "$task_id"

    log_success "Task ${task_id} reset to pending (attempt $((retry_count + 2)))"

    echo ""
    echo -e "Run ${COLOR_STEP}speed run${RESET} to execute."
    echo ""
}
cmd_recover() {
    _require_feature "$GLOBAL_FEATURE"
    log_header "Recovering SPEED State"

    # Force-break any stale lock
    speed_force_break_lock

    local recovered=0

    # Kill any orphan agent processes first — before touching state
    local killed
    killed=$(_kill_orphan_agents)
    if [[ "$killed" -gt 0 ]]; then
        log_step "Killed ${killed} orphan agent process(es)"
        recovered=$((recovered + killed))
    fi

    # Reset "running" tasks to pending (agents are dead now)
    for f in "${TASKS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local status tid
        status=$(jq -r '.status' "$f")
        tid=$(jq -r '.id' "$f")

        if [[ "$status" == "running" ]]; then
            log_step "Resetting task ${tid} to pending (manual recovery)"
            task_reset_pending "$tid" "no_increment"
            git_remove_worktree "$tid"
            ((recovered++)) || true
        fi
    done

    # Clean stale tracking directories
    rm -rf "${FEATURE_DIR}/running" "${FEATURE_DIR}/support"

    # Reset SPEED state
    jq '.status = "idle" | .agents = []' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"

    # Clean up orphaned worktrees
    git_cleanup_worktrees

    if [[ "$recovered" -gt 0 ]]; then
        log_success "Recovered ${recovered} stale item(s)"
    else
        log_info "No stale state found — SPEED is clean"
    fi

    echo ""
    task_print_summary
    echo ""
}
cmd_fix_nits() {
    _require_feature "$GLOBAL_FEATURE"
    local filter_task_id=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --task-id) filter_task_id="$2"; shift 2 ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    log_header "Fix Nits"

    local nits_file="${LOGS_DIR}/review-nits.json"

    if [[ ! -f "$nits_file" ]]; then
        log_error "No nits found. Run 'speed review' first."
        exit 1
    fi

    local nits_json
    nits_json=$(cat "$nits_file")

    local nit_count
    nit_count=$(echo "$nits_json" | jq 'length' 2>/dev/null) || nit_count=0

    if [[ "$nit_count" == "0" ]] || [[ -z "$nit_count" ]]; then
        log_error "No nits found in ${nits_file}. Run 'speed review' first."
        exit 1
    fi

    # Filter by task ID if provided
    if [[ -n "$filter_task_id" ]]; then
        nits_json=$(echo "$nits_json" | jq --arg tid "$filter_task_id" '[.[] | select(.task_id == $tid)]')
        nit_count=$(echo "$nits_json" | jq 'length' 2>/dev/null) || nit_count=0
        if [[ "$nit_count" == "0" ]] || [[ -z "$nit_count" ]]; then
            log_error "No nits found for task ${filter_task_id}."
            exit 1
        fi
    fi

    # Compute next task ID (max existing + 1)
    local max_id=0
    for f in "${TASKS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local tid
        tid=$(jq -r '.id' "$f" 2>/dev/null) || continue
        if [[ "$tid" -gt "$max_id" ]] 2>/dev/null; then
            max_id="$tid"
        fi
    done
    local next_id=$((max_id + 1))

    # Collect unique original task IDs
    local source_task_ids
    source_task_ids=$(echo "$nits_json" | jq -r '[.[].task_id] | unique | join(", ")' 2>/dev/null)

    # Build numbered description from nits
    local description=""
    description+="Fix the following reviewer nits. Each fix is small and mechanical."
    description+="\n"

    local i=1
    while IFS= read -r nit_line; do
        [[ -z "$nit_line" ]] && continue
        local nit_task nit_severity nit_message nit_file nit_line_num nit_suggestion
        nit_task=$(echo "$nit_line" | jq -r '.task_id // "?"')
        nit_severity=$(echo "$nit_line" | jq -r '.severity // "nit"')
        nit_message=$(echo "$nit_line" | jq -r '.message // .description // "no message"')
        nit_file=$(echo "$nit_line" | jq -r '.file // "?"')
        nit_line_num=$(echo "$nit_line" | jq -r '.line // "?"')
        nit_suggestion=$(echo "$nit_line" | jq -r '.suggestion // empty')

        description+="\n${i}. **${nit_file}:${nit_line_num}** (${nit_severity}, from task ${nit_task})"
        description+="\n   Issue: ${nit_message}"
        if [[ -n "$nit_suggestion" ]]; then
            description+="\n   Fix: ${nit_suggestion}"
        fi

        i=$((i + 1))
    done < <(echo "$nits_json" | jq -c '.[]')

    description+="\n\nApply each fix. If a suggestion is wrong or not applicable, add a code comment explaining why it was skipped."

    # Build acceptance criteria
    local criteria="- Each nit is fixed or has a comment explaining why not applicable\n- No new lint/typecheck/test failures\n- All quality gates pass"

    # Build depends_on from unique original task IDs
    local depends_on
    depends_on=$(echo "$nits_json" | jq -c '[.[].task_id] | unique')

    # Build files_touched from unique file paths
    local files_touched
    files_touched=$(echo "$nits_json" | jq -c '[.[].file // empty] | unique | map(select(. != "?"))')

    # Create the task
    local title="Fix review nits from tasks ${source_task_ids}"

    task_create "$next_id" "$title" "$(echo -e "$description")" "$(echo -e "$criteria")" "$depends_on" "$MODEL_SUPPORT"
    task_update_raw "$next_id" "files_touched" "$files_touched"

    echo ""
    log_success "Created task ${next_id}: ${title}"
    log_step "${nit_count} nit(s) from task(s) ${source_task_ids}"
    echo ""
    echo -e "  ${COLOR_DIM}Next: ${COLOR_STEP}speed run${COLOR_DIM} && ${COLOR_STEP}speed review${RESET}"
    echo ""
}
