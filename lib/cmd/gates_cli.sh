#!/usr/bin/env bash
# gates_cli.sh — Quality gates CLI command

cmd_gates() {
    # Support -f/--feature as local flag so copy-pasteable commands work
    # regardless of flag position (before or after the subcommand)
    local local_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -f|--feature) GLOBAL_FEATURE="$2"; shift 2 ;;
            *) local_args+=("$1"); shift ;;
        esac
    done
    set -- "${local_args[@]+"${local_args[@]}"}"

    _require_feature "$GLOBAL_FEATURE"

    local task_id=""
    local mode="fast"
    local worktree_flag=""

    # Parse local flags
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --task)      task_id="$2"; shift 2 ;;
            --fast)      mode="fast"; shift ;;
            --full)      mode="full"; shift ;;
            --worktree)  worktree_flag="$2"; shift 2 ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    # Validate required flags
    if [[ -z "$task_id" ]]; then
        log_error "Required: --task ID"
        echo "Usage: speed gates -f <feature> --task <id> [--fast|--full] [--worktree <path>]"
        exit 1
    fi

    # Resolve worktree path
    local worktree_path
    if [[ -n "$worktree_flag" ]]; then
        worktree_path="$worktree_flag"
    elif [[ -d "${WORKTREES_DIR}/task-${task_id}" ]]; then
        worktree_path="${WORKTREES_DIR}/task-${task_id}"
    else
        worktree_path="${PROJECT_ROOT}"
    fi

    log_header "Quality Gates (${mode})"
    log_info "Task: ${task_id} | Worktree: ${worktree_path}"

    if [[ "$mode" == "full" ]]; then
        # Full mode: delegate entirely to gates_run (grounding + all quality gates)
        if gates_run "$task_id" "$worktree_path"; then
            log_success "All gates passed"
            # Promote failed tasks to done when gates pass (e.g. after fixing gate blockers)
            local task_status
            task_status=$(jq -r '.status' "${TASKS_DIR}/${task_id}.json" 2>/dev/null)
            if [[ "$task_status" == "failed" ]]; then
                task_set_done "$task_id"
                log_success "Task ${task_id}: promoted to done"
            fi
            exit 0
        else
            log_error "One or more gates failed"
            exit 1
        fi
    fi

    # Fast mode: syntax check + lint + typecheck only (no grounding, no tests)
    local subsystem
    subsystem=$(_detect_subsystem "$task_id")
    log_step "Subsystem: ${subsystem}"

    local results=()
    local all_passed=true

    # Syntax check
    if gate_syntax_check "$task_id" "$worktree_path"; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} Syntax check${RESET}")
    else
        results+=("${COLOR_ERROR}${SYM_CROSS} Syntax check${RESET}")
        all_passed=false
    fi

    # Lint
    local cmds
    cmds=$(gates_get_config "lint" "$subsystem")
    if [[ -n "$cmds" ]]; then
        while IFS= read -r cmd; do
            [[ -z "$cmd" ]] && continue
            if gate_run_command "Lint" "$cmd" "$worktree_path"; then
                results+=("${COLOR_SUCCESS}${SYM_CHECK} Lint: ${COLOR_DIM}${cmd}${RESET}")
            else
                results+=("${COLOR_ERROR}${SYM_CROSS} Lint: ${COLOR_DIM}${cmd}${RESET}")
                all_passed=false
            fi
        done <<< "$cmds"
    fi

    # Typecheck
    cmds=$(gates_get_config "typecheck" "$subsystem")
    if [[ -n "$cmds" ]]; then
        while IFS= read -r cmd; do
            [[ -z "$cmd" ]] && continue
            if gate_run_command "Typecheck" "$cmd" "$worktree_path"; then
                results+=("${COLOR_SUCCESS}${SYM_CHECK} Typecheck: ${COLOR_DIM}${cmd}${RESET}")
            else
                results+=("${COLOR_ERROR}${SYM_CROSS} Typecheck: ${COLOR_DIM}${cmd}${RESET}")
                all_passed=false
            fi
        done <<< "$cmds"
    fi

    # Print results
    echo ""
    echo -e "  ${BOLD}Quality Gates (fast):${RESET}"
    for r in "${results[@]}"; do
        echo -e "    $r"
    done
    echo ""

    if $all_passed; then
        log_success "All fast gates passed"
        exit 0
    else
        log_error "One or more gates failed"
        exit 1
    fi
}
