#!/usr/bin/env bash
# run.sh — Main task execution orchestrator

_cmd_run_defect() {
    local name="$1"

    # 1. Validate defect exists
    local state_json
    if ! state_json=$(defect_state_read "$name" 2>/dev/null); then
        log_error "Defect not found: ${name}"
        exit 1
    fi

    # 2. Read current status from state.json
    local current_state
    current_state=$(echo "$state_json" | jq -r '.status // "unknown"')

    # 3. Read complexity from triage output
    local triage_json
    if ! triage_json=$(defect_triage_read "$name" 2>/dev/null); then
        log_error "Defect '${name}' has no triage output — run 'speed defect <spec-path>' first"
        exit 1
    fi
    local complexity
    complexity=$(echo "$triage_json" | jq -r '.complexity // empty')

    # 4. Validate state is triaged
    if [[ "$current_state" != "triaged" ]]; then
        log_error "Defect ${name} is in state ${current_state}, expected triaged"
        exit 1
    fi

    log_header "Running Defect: ${name}"
    log_info "Complexity: ${complexity}"

    # 5/6. Run pipeline based on complexity
    if [[ "$complexity" == "trivial" ]]; then
        log_step "Running fix stage (trivial)..."
        fix_defect "$name"
    else
        log_step "Running reproduce stage..."
        reproduce_defect "$name"
        log_step "Running fix stage..."
        fix_defect "$name"
    fi

    # 7. Print success and next-step hint
    log_success "Defect '${name}' pipeline complete"
    echo ""
    echo -e "Next: ${COLOR_STEP}speed status --defects${RESET} to review defect state"
    echo ""
}

# ── Nested helpers (hoisted to file scope; rely on bash dynamic scoping) ──

_running_count() {
    local count=0
    for f in "$running_dir"/*.pid; do
        [[ -f "$f" ]] && ((count++)) || true
    done
    echo "$count"
}

_running_task_ids() {
    for f in "$running_dir"/*.pid; do
        [[ -f "$f" ]] || continue
        basename "$f" .pid
    done
}

_record_failure() {
    local task_id="$1"
    local error="$2"
    jq -nc --arg tid "$task_id" --arg err "$error" --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{task_id: $tid, error: $err, timestamp: $ts}' >> "$failure_log"
}

_failure_count() {
    wc -l < "$failure_log" 2>/dev/null | tr -d ' '
}

_spawn_support_agent() {
    local agent_type="$1"   # "debugger" or "supervisor"
    local for_task_id="$2"
    local prompt_file="$3"
    local message="$4"
    local output_file="${LOGS_DIR}/${agent_type}-${for_task_id}-bg.log"

    local pid
    pid=$(provider_spawn_bg \
        "$prompt_file" \
        "$message" \
        "$output_file" \
        "$MODEL_SUPPORT" \
        "$AGENT_TOOLS_READONLY") || {
        log_warn "Failed to spawn ${agent_type} for task ${for_task_id} — continuing without it"
        return 0
    }

    echo "$pid" > "${support_dir}/${agent_type}-${for_task_id}.pid"
    echo "$for_task_id" > "${support_dir}/${agent_type}-${for_task_id}.task"
    log_step "Spawned ${COLOR_STEP}${agent_type}${RESET} for task ${for_task_id}"
    log_verbose "  PID: ${pid} | log: ${output_file}"
}

MERGE_CONFLICT_MAX_RETRIES=3

_record_merge_attempt() {
    local tid="$1"
    local attempt_file="${merge_attempts_dir}/${tid}"
    local count=0
    if [[ -f "$attempt_file" ]]; then
        count=$(cat "$attempt_file")
    fi
    echo "$(( count + 1 ))" > "$attempt_file"
}

_get_merge_attempts() {
    local tid="$1"
    local attempt_file="${merge_attempts_dir}/${tid}"
    if [[ -f "$attempt_file" ]]; then
        cat "$attempt_file"
    else
        echo "0"
    fi
}

# ── Get ready tasks: pending + deps met + not blocked ────────

_get_ready_tasks() {
    _ensure_jq
    local pending
    pending=$(task_list_by_status "pending")

    if [[ -z "$pending" ]]; then
        return
    fi

    while IFS= read -r id; do
        if task_deps_met "$id"; then
            echo "$id"
        fi
    done <<< "$pending"
}

# ── Classify and record a task failure ────────────────────────
# Calls the failure classification system and writes the result
# to the task JSON's failure_classification field.

_classify_task_failure() {
    local task_id="$1"
    local agent_output="${2:-}"
    local escalated="${3:-false}"
    local timed_out="${4:-false}"

    local task_file="${TASKS_DIR}/${task_id}.json"
    [[ -f "$task_file" ]] || return 0

    local fc_result
    fc_result=$(context_classify_failure "$task_file" "$agent_output" "$escalated" "$timed_out" 2>/dev/null) || return 0

    if [[ -n "$fc_result" ]]; then
        local fc_class fc_sub fc_evidence
        fc_class=$(echo "$fc_result" | jq -r '.class // "unclassified"' 2>/dev/null)
        fc_sub=$(echo "$fc_result" | jq -r '.subclass // "unknown"' 2>/dev/null)
        fc_evidence=$(echo "$fc_result" | jq -r '.evidence // ""' 2>/dev/null)

        # Write failure_classification to task JSON
        local tmp
        tmp=$(mktemp)
        jq --argjson fc "$fc_result" '.failure_classification = $fc' "$task_file" > "$tmp" && mv "$tmp" "$task_file"

        log_verbose "  Failure classified: ${fc_class}/${fc_sub}"
    fi
}

# ── Invoke debugger on a failed task ─────────────────────────

_invoke_debugger() {
    local task_id="$1"
    local task_json
    task_json=$(task_get "$task_id")
    local title description criteria branch
    title=$(echo "$task_json" | jq -r '.title')
    description=$(echo "$task_json" | jq -r '.description')
    criteria=$(echo "$task_json" | jq -r '.acceptance_criteria')
    branch=$(echo "$task_json" | jq -r '.branch')

    local output_file="${LOGS_DIR}/${task_id}.log"
    local agent_output=""
    if [[ -f "$output_file" ]]; then
        local total_lines
        total_lines=$(wc -l < "$output_file" | tr -d ' ')
        if [[ "$total_lines" -le "$AGENT_OUTPUT_TAIL" ]]; then
            agent_output=$(cat "$output_file")
        else
            local half=$(( AGENT_OUTPUT_TAIL / 2 ))
            local omitted=$(( total_lines - AGENT_OUTPUT_TAIL ))
            agent_output=$(head -"$half" "$output_file")
            agent_output+=$'\n'"... ${omitted} lines omitted ..."$'\n'
            agent_output+=$(tail -"$half" "$output_file")
        fi
    fi

    local diff=""
    if git_branch_exists "$branch" 2>/dev/null; then
        diff=$(_git diff "$(git_main_branch)...${branch}" 2>/dev/null | head -"$DIFF_HEAD_LINES" || echo "No diff")
    fi

    # Assemble debugger context with budget analysis and failure classification
    local task_file_path="${TASKS_DIR}/${task_id}.json"
    local debugger_message
    debugger_message=$(context_assemble_debugger \
        "$task_file_path" \
        "$agent_output" \
        "$diff" 2>/dev/null) || debugger_message=""

    # Fallback to inline prompt
    if [[ -z "$debugger_message" ]]; then
        debugger_message="## Failed Task ${task_id}: ${title}

### Task Description
${description}

### Acceptance Criteria
${criteria}

### Agent Output
${agent_output}

### Git Diff (first 500 lines)
\`\`\`diff
${diff}
\`\`\`

Diagnose why this task failed and provide a specific fix."
    fi

    _spawn_support_agent "debugger" "$task_id" "${AGENTS_DIR}/debugger.md" "$debugger_message"
}

cmd_run() {
    local max_parallel=$DEFAULT_MAX_PARALLEL
    local model=$MODEL_SUPPORT
    local defect_name=""
    local run_start=$SECONDS

    # Parse arguments before _require_feature so --defect can skip the feature requirement
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --max-parallel) max_parallel="$2"; shift 2 ;;
            --model)        model="$2"; shift 2 ;;
            --defect)       defect_name="$2"; shift 2 ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    # ── --defect mode: run defect pipeline, skip feature requirement ──
    if [[ -n "$defect_name" ]]; then
        _cmd_run_defect "$defect_name"
        return
    fi

    _require_feature "$GLOBAL_FEATURE"

    # ── Acquire exclusive lock ────────────────────────────────────
    speed_acquire_lock "run" || exit 1

    # ── Hard gate: timeout command is required ────────────────────
    require_timeout_cmd || exit $EXIT_CONFIG_ERROR

    log_header "Running SPEED"
    log_info "Max parallel: ${max_parallel} | Model: ${model}"

    # Check for circular dependencies before starting
    if ! task_topo_sort > /dev/null; then
        log_error "Cannot run: circular dependencies in task graph. Fix depends_on fields."
        exit 1
    fi

    # Ensure working tree is committed so task branches see all files
    # Acquire main-branch lock since this does git add + commit on the shared tree
    if main_branch_acquire_lock "baseline"; then
        git_create_baseline
        main_branch_release_lock
    else
        log_warn "Could not acquire main-branch lock for baseline — proceeding (may miss uncommitted files)"
    fi

    # Verify tasks exist
    local total
    total=$(task_count_total)
    if [[ "$total" -eq 0 ]]; then
        log_error "No tasks found. Run 'speed plan <spec>' first."
        exit 1
    fi

    # Check for stale state — auto-recover if previous run was killed
    local current_state
    current_state=$(jq -r '.status // "idle"' "$STATE_FILE" 2>/dev/null || echo "idle")
    if [[ "$current_state" == "running" ]]; then
        log_warn "SPEED state is 'running' — previous run likely crashed. Auto-recovering..."

        # Kill any orphan agents still running from the crashed session
        local killed
        killed=$(_kill_orphan_agents)
        if [[ "$killed" -gt 0 ]]; then
            log_step "Killed ${killed} orphan agent process(es)"
        fi

        # Reset running tasks back to pending
        for f in "${TASKS_DIR}"/*.json; do
            [[ -f "$f" ]] || continue
            local status tid
            status=$(jq -r '.status' "$f" 2>/dev/null) || { log_warn "Skipping unreadable task file: $f"; continue; }
            tid=$(jq -r '.id' "$f" 2>/dev/null) || continue
            if [[ "$status" == "running" ]]; then
                log_step "Resetting task ${tid} to pending (prior run didn't exit cleanly)"
                task_reset_pending "$tid" "no_increment"
                git_remove_worktree "$tid"
            fi
        done

        # Clean stale tracking state
        rm -rf "${FEATURE_DIR}/running" "${FEATURE_DIR}/support"

        # Clean up orphaned worktrees
        git_cleanup_worktrees

        # Break stale locks
        speed_force_break_lock

        log_success "Auto-recovery complete — starting fresh"
    fi

    # Update state
    jq -n \
        --arg status "running" \
        --arg started "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{status: $status, agents: [], started_at: $started, failure_history: []}' > "$STATE_FILE"

    [[ "${MP_ENABLED:-}" == "true" ]] && event_emit "run.started" "$FEATURE_NAME" "{\"max_parallel\":$max_parallel}" || true

    # Detect the base branch all task branches fork from
    local main_branch
    main_branch=$(git_main_branch)

    # ── Agent tracking via files (bash 3 compatible) ───────────
    local running_dir="${FEATURE_DIR}/running"
    rm -rf "$running_dir"
    mkdir -p "$running_dir"

    # ── Failure tracking for pattern detection ─────────────────
    local failure_log="${FEATURE_DIR}/failure_history.jsonl"
    > "$failure_log"  # Clear

    # ── Support agent tracking (debugger, supervisor) ──────────
    local support_dir="${FEATURE_DIR}/support"
    rm -rf "$support_dir"
    mkdir -p "$support_dir"

    # ── Merge-conflict tracking (bash 3 compatible, file-based) ──
    local merge_attempts_dir="${FEATURE_DIR}/merge_attempts"
    rm -rf "$merge_attempts_dir"
    mkdir -p "$merge_attempts_dir"

    # ── Status line tracking ─────────────────────────────────────
    local _prev_status_counts=""

    # ── Reconcile running tasks on exit ───────────────────────────
    # Sets every "running" task to "pending" when the orchestrator exits.
    # Called from: (1) normal/halt exit path, (2) cmd_run's signal trap.
    # Does NOT check process liveness (agents are still alive at exit
    # time; cleanup_all kills them after). Does NOT check branches
    # (branch_audit runs at spawn time on the next speed run).
    _reconcile_running_tasks() {
        for f in "${TASKS_DIR}"/*.json; do
            [[ -f "$f" ]] || continue
            local status tid
            status=$(jq -r '.status' "$f" 2>/dev/null) || continue
            tid=$(jq -r '.id' "$f" 2>/dev/null) || continue

            if [[ "$status" == "running" ]]; then
                task_reset_pending "$tid" "no_increment"
                log_step "Task ${tid}: orchestrator exiting — reset to pending"
            fi
        done
    }

    # Chain cmd_run's reconciliation before the global signal handler.
    # On Ctrl-C: reconcile tasks → _speed_cleanup_on_signal (state.json
    # to idle, release locks) → cleanup_all (kill PIDs).
    trap '_reconcile_running_tasks 2>/dev/null || true; _speed_cleanup_on_signal' INT TERM

    # ── Main orchestration loop ──────────────────────────────────
    while true; do
        # Check for completed agents
        for pid_file in "$running_dir"/*.pid; do
            [[ -f "$pid_file" ]] || continue
            local task_id pid
            task_id=$(basename "$pid_file" .pid)
            pid=$(cat "$pid_file")

            # Check if done marker exists (agent finished) or process stopped
            local output_file="${LOGS_DIR}/${task_id}.log"
            local done_marker="${output_file}.done"

            if [[ -f "$done_marker" ]] || ! provider_is_running "$pid"; then
                # Wait briefly for file writes to flush
                sleep "$COMPLETION_FLUSH_WAIT"

                # ── Check for crash: process gone but no .done marker ──
                if [[ ! -f "$done_marker" ]] && ! provider_is_running "$pid"; then
                    log_error "Task ${task_id}: agent process disappeared without completion marker (crash/OOM/SIGKILL)"
                    task_set_failed "$task_id" "Agent process crashed (no completion marker)"
                    _record_failure "$task_id" "Agent process crashed"
                    rm -f "$pid_file"
                    git_remove_worktree "$task_id"
                    continue
                fi

                # ── Check for CLI error (auth failure, model not found, etc.) ──
                local error_marker="${output_file}.error"
                if [[ -f "$error_marker" ]]; then
                    local cli_exit_code
                    cli_exit_code=$(cat "$error_marker" 2>/dev/null || echo "?")
                    log_error "Task ${task_id}: Agent CLI error (exit code ${cli_exit_code})"
                    task_set_failed "$task_id" "Agent CLI error (exit code ${cli_exit_code})"
                    _record_failure "$task_id" "Agent CLI error (exit code ${cli_exit_code})"
                    rm -f "$pid_file" "$done_marker" "$error_marker"
                    git_remove_worktree "$task_id"
                    continue
                fi

                # ── Check for timeout (before blocked — timeouts are not blocked) ──
                local timeout_marker="${output_file}.timeout"
                if [[ -f "$timeout_marker" ]]; then
                    local timeout_count current_model
                    timeout_count=$(jq -r '.timeout_count // 0' "${TASKS_DIR}/${task_id}.json")
                    current_model=$(jq -r --arg def "$MODEL_SUPPORT" '.agent_model // $def' "${TASKS_DIR}/${task_id}.json")

                    task_set_timeout "$task_id" "Agent timed out after ${DEFAULT_AGENT_TIMEOUT}s"
                    rm -f "$pid_file" "$done_marker" "$timeout_marker"
                    git_remove_worktree "$task_id"

                    # If the agent committed no work before timing out, delete the
                    # branch ref. A zero-commit branch still points at the integration
                    # branch commit it was created from, making it an ancestor. Later,
                    # branch_audit's --is-ancestor check misreads this as "work already
                    # integrated" and marks the task done. Deleting the ref ensures
                    # branch_audit falls through to "empty" (no branch → spawn agent).
                    local branch_for_cleanup
                    branch_for_cleanup=$(jq -r '.branch // empty' "${TASKS_DIR}/${task_id}.json" 2>/dev/null)
                    if [[ -n "$branch_for_cleanup" ]] && git_branch_exists "$branch_for_cleanup"; then
                        local cleanup_fork cleanup_diff
                        cleanup_fork=$(_git merge-base "$main_branch" "$branch_for_cleanup" 2>/dev/null) || true
                        if [[ -n "$cleanup_fork" ]]; then
                            cleanup_diff=$(_git diff "${cleanup_fork}..${branch_for_cleanup}" --name-only 2>/dev/null) || true
                            if [[ -z "$cleanup_diff" ]]; then
                                _git branch -D "$branch_for_cleanup" 2>/dev/null || true
                                log_verbose "  Deleted zero-work branch: ${branch_for_cleanup}"
                            fi
                        fi
                    fi

                    if [[ "$timeout_count" -eq 0 ]] && [[ "$current_model" != "$MODEL_PLANNING" ]]; then
                        # First timeout on support tier → escalate to planning tier
                        log_warn "Task ${task_id}: timed out on ${current_model} — escalating to ${MODEL_PLANNING} and retrying"
                        task_update "$task_id" "agent_model" "$MODEL_PLANNING"
                        task_reset_pending "$task_id"
                    else
                        # Already at planning tier or second timeout → human problem
                        log_error_block \
                            "Task ${task_id} timed out after ${DEFAULT_AGENT_TIMEOUT}s" \
                            "Agent exceeded time limit on ${current_model} (attempt $((timeout_count + 1)))" \
                            "speed retry --task-id ${task_id} --escalate"
                        _record_failure "$task_id" "Timeout after model escalation"
                        _classify_task_failure "$task_id" "" "true" "true"
                    fi
                    continue
                fi

                # ── Check for blocked status ───────────────────────
                local blocked_json
                blocked_json=$(parse_agent_json "$(cat "$output_file")" 2>/dev/null) || blocked_json=""
                if [[ -n "$blocked_json" ]] && echo "$blocked_json" | jq -e '.status == "blocked"' &>/dev/null; then
                    log_warn "Task ${task_id}: agent reported BLOCKED"

                    local uncertain_about
                    uncertain_about=$(echo "$blocked_json" | jq -r '.uncertain_about // "Unknown"')
                    log_warn "  Uncertainty: ${uncertain_about}"

                    # Atomic: status + error + agent_pid in one write
                    task_set_blocked "$task_id" "$blocked_json"

                    # Invoke supervisor for blocked tasks
                    _invoke_supervisor "$task_id" "blocked"

                    rm -f "$pid_file" "$done_marker"
                    git_remove_worktree "$task_id"
                    continue
                fi

                # ── Normal completion check ───────────────────────
                # Resolve worktree path for this task
                local task_worktree="${WORKTREES_DIR}/task-${task_id}"

                if [[ -s "$output_file" ]]; then
                    log_success "Task ${task_id} agent completed"

                    if gates_run "$task_id" "$task_worktree"; then
                        # Atomic: status + completed_at + agent_pid in one write
                        task_set_done "$task_id"
                        log_success "Task ${task_id}: ${COLOR_SUCCESS}DONE${RESET}"

                        # Extract decisions and concerns from agent output
                        # so downstream dependent tasks can see what this agent learned
                        local completion_json
                        completion_json=$(parse_agent_json "$(cat "$output_file")" 2>/dev/null) || completion_json=""
                        if [[ -n "$completion_json" ]] && echo "$completion_json" | jq -e '.status == "done"' &>/dev/null; then
                            local has_metadata
                            has_metadata=$(echo "$completion_json" | jq 'has("decisions") or has("concerns")')
                            if [[ "$has_metadata" == "true" ]]; then
                                local tmp_task; tmp_task=$(mktemp)
                                jq --argjson dec "$(echo "$completion_json" | jq '.decisions // []')" \
                                   --argjson con "$(echo "$completion_json" | jq '.concerns // []')" \
                                    '.decisions = $dec | .concerns = $con' \
                                    "${TASKS_DIR}/${task_id}.json" > "$tmp_task" && mv "$tmp_task" "${TASKS_DIR}/${task_id}.json"
                            fi
                        fi

                        # Clean up worktree (frees the branch lock)
                        # NOTE: We do NOT merge into main here. Merging is deferred
                        # to just before spawning a dependent task, so in-flight agents
                        # are never disturbed by main moving underneath them.
                        git_remove_worktree "$task_id"
                    else
                        # Global circuit breaker: escalate to blocked after 3 retries
                        local retry_count_cb
                        retry_count_cb=$(jq -r '.retry_count // 0' "${TASKS_DIR}/${task_id}.json")
                        if [[ $retry_count_cb -ge 3 ]]; then
                            task_set_blocked "$task_id" \
                                "Failed $retry_count_cb times across different gates — needs human review"
                            log_warn "Task ${task_id}: hit global retry limit — marked BLOCKED"
                            git_remove_worktree "$task_id"
                            rm -f "$pid_file" "$done_marker"
                            continue
                        fi
                        # Atomic: status + error + agent_pid in one write
                        task_set_failed "$task_id" "Quality gates failed"
                        log_error_block \
                            "Quality gates failed for task ${task_id}" \
                            "One or more quality checks did not pass" \
                            "Fix the issues and run: speed retry --task-id ${task_id}"
                        _record_failure "$task_id" "Quality gates failed"

                        # Classify the failure (pipeline vs complexity)
                        local _agent_out=""
                        [[ -f "${LOGS_DIR}/${task_id}.log" ]] && _agent_out=$(cat "${LOGS_DIR}/${task_id}.log" 2>/dev/null | tail -500)
                        _classify_task_failure "$task_id" "$_agent_out"

                        # Keep worktree for debugger analysis
                        # (will be cleaned up on retry or recover)

                        # Invoke debugger for diagnosis
                        _invoke_debugger "$task_id"

                        # Check for pattern failures
                        local fail_count
                        fail_count=$(_failure_count)
                        if [[ "$fail_count" -ge "$PATTERN_FAILURE_THRESHOLD" ]]; then
                            log_warn "Multiple failures detected — invoking Supervisor for pattern analysis"
                            _invoke_supervisor "$task_id" "pattern"
                        fi
                    fi
                else
                    # Atomic: status + error + agent_pid in one write
                    task_set_failed "$task_id" "Agent produced no output"
                    log_error "Task ${task_id}: agent produced no output"
                    _record_failure "$task_id" "Agent produced no output"
                    _classify_task_failure "$task_id" ""
                    git_remove_worktree "$task_id"
                fi

                # Clean up tracking
                rm -f "$pid_file" "$done_marker"
            fi
        done

        # ── Check for completed support agents (debugger/supervisor) ──
        for support_pid_file in "$support_dir"/*.pid; do
            [[ -f "$support_pid_file" ]] || continue
            local support_name support_pid support_output_file support_done_marker
            support_name=$(basename "$support_pid_file" .pid)
            support_pid=$(cat "$support_pid_file")
            support_output_file="${LOGS_DIR}/${support_name}-bg.log"
            support_done_marker="${support_output_file}.done"

            if [[ -f "$support_done_marker" ]] || ! kill -0 "$support_pid" 2>/dev/null; then
                sleep "$COMPLETION_FLUSH_WAIT"

                # Detect failure mode
                local support_error=""
                if [[ ! -f "$support_done_marker" ]] && ! kill -0 "$support_pid" 2>/dev/null; then
                    support_error="Agent process crashed (no completion marker)"
                elif [[ -f "${support_output_file}.timeout" ]]; then
                    support_error="Agent timed out after ${DEFAULT_AGENT_TIMEOUT}s"
                elif [[ -f "${support_output_file}.error" ]]; then
                    local cli_rc
                    cli_rc=$(cat "${support_output_file}.error" 2>/dev/null || echo "?")
                    support_error="Agent CLI error (exit code ${cli_rc})"
                fi

                # Parse agent_type and task_id from the name (e.g. "debugger-3" or "supervisor-pattern-3")
                local support_task_id support_agent_type
                support_task_id=$(cat "${support_dir}/${support_name}.task" 2>/dev/null || echo "")
                # Agent type is everything before the last -<task_id>
                support_agent_type="${support_name%-"${support_task_id}"}"

                if [[ -n "$support_task_id" ]] && [[ -n "$support_agent_type" ]]; then
                    _handle_support_completion "$support_agent_type" "$support_task_id" "$support_error"
                fi
                rm -f "$support_pid_file" "${support_dir}/${support_name}.task" \
                      "$support_done_marker" "${support_output_file}.timeout" "${support_output_file}.error"
            fi
        done

        # Count running agents
        local running_count
        running_count=$(_running_count)

        # Count running support agents (don't exit loop while they're active)
        local support_count=0
        for f in "$support_dir"/*.pid; do
            [[ -f "$f" ]] && ((support_count++)) || true
        done

        # Find ready tasks and spawn agents
        local ready_tasks
        ready_tasks=$(_get_ready_tasks)

        if [[ -z "$ready_tasks" ]] && [[ $running_count -eq 0 ]]; then
            # Nothing ready and nothing running — check if blocked tasks exist
            local blocked_count
            blocked_count=$(task_count_by_status "blocked")
            if [[ "$blocked_count" -gt 0 ]]; then
                log_warn "${blocked_count} task(s) blocked — awaiting human input"
                log_warn "Run ${COLOR_STEP}speed status${RESET} for supervisor analysis"
            fi
            if [[ $support_count -gt 0 ]]; then
                log_info "${support_count} support agent(s) finishing in background — output in ${LOGS_DIR}/"
            fi
            break
        fi

        if [[ -n "$ready_tasks" ]]; then
            while IFS= read -r task_id; do
                if [[ $running_count -ge $max_parallel ]]; then
                    break
                fi

                # ── File conflict check ───────────────────────────
                local conflict_output
                local conflict_rc=0
                conflict_output=$(grounding_check_file_conflicts "$task_id") || conflict_rc=$?
                if [[ $conflict_rc -ne 0 ]] && [[ -n "$conflict_output" ]]; then
                    _record_merge_attempt "$task_id"
                    local conflict_attempts
                    conflict_attempts=$(_get_merge_attempts "$task_id")
                    if [[ "$conflict_attempts" -ge "$MERGE_CONFLICT_MAX_RETRIES" ]]; then
                        task_set_blocked "$task_id" "File conflict persisted after ${conflict_attempts} deferrals: ${conflict_output}"
                        log_warn "Task ${task_id}: file conflict — marked BLOCKED"
                    else
                        log_warn "Task ${task_id}: file conflict detected, deferring (attempt ${conflict_attempts}/${MERGE_CONFLICT_MAX_RETRIES})"
                        log_warn "  ${conflict_output}"
                    fi
                    continue
                fi

                # Read task details
                local task_json
                task_json=$(task_get "$task_id")
                local title description criteria task_model branch
                title=$(echo "$task_json" | jq -r '.title')
                description=$(echo "$task_json" | jq -r '.description')
                criteria=$(echo "$task_json" | jq -r '.acceptance_criteria')
                task_model=$(echo "$task_json" | jq -r ".agent_model // \"${model}\"")
                branch=$(echo "$task_json" | jq -r '.branch')

                # Get files_touched for scope awareness
                local files_touched
                files_touched=$(echo "$task_json" | jq -r '.files_touched // [] | join(", ")')

                # Append review feedback if retrying
                local feedback
                feedback=$(echo "$task_json" | jq -r '.review_feedback // empty')
                local extra_context=""
                if [[ -n "$feedback" ]]; then
                    extra_context=$'\n\n## Previous Review Feedback\n\n'"${feedback}"
                fi

                # Append debugger analysis if retrying after failure
                local debugger_log="${LOGS_DIR}/debugger-${task_id}.json"
                if [[ -f "$debugger_log" ]]; then
                    extra_context+=$'\n\n## Debugger Analysis (from previous failure)\n\n'"$(cat "$debugger_log")"
                fi

                # Build gate failure context for retries (Change 4)
                local retry_count
                retry_count=$(jq -r '.retry_count // 0' "${TASKS_DIR}/${task_id}.json")
                local failure_context=""
                if [[ $retry_count -gt 0 ]]; then
                    local failed_checks
                    failed_checks=$(jq -r '
                        .gate_results.checks[]?
                        | select(.status == "fail")
                        | "- \(.name): FAILED" +
                          (if .ownership_violations then " (files: " + (.ownership_violations | join(", ")) + ")" else "" end) +
                          (if .undeclared_files then " (undeclared: " + (.undeclared_files | join(", ")) + ")" else "" end) +
                          (if .missing_files then " (missing: " + (.missing_files | join(", ")) + ")" else "" end) +
                          (if .uncovered_files then " (need tests: " + (.uncovered_files | join(", ")) + ")" else "" end) +
                          (if .criteria_detail then " (reason: " + (.criteria_detail | tostring) + ")" else "" end) +
                          (if .output and .output != "" then " (" + (.output | split("\n")[0:3] | join("; ")) + ")" else "" end) +
                          (if .command then " [" + .command + "]" else "" end)
                    ' "${TASKS_DIR}/${task_id}.json" 2>/dev/null)

                    if [[ -n "$failed_checks" ]]; then
                        failure_context="
### Prior Attempt Failures (retry ${retry_count})
The previous attempt failed these quality gates:
${failed_checks}

Adapt your approach to avoid these failures."
                    fi
                fi

                # Gather decisions and concerns from completed dependencies
                # so this agent knows what upstream agents learned and flagged
                local upstream_context=""
                local dep_ids_for_context
                dep_ids_for_context=$(echo "$task_json" | jq -r '.depends_on[]?' 2>/dev/null)
                if [[ -n "$dep_ids_for_context" ]]; then
                    while IFS= read -r dep_id; do
                        [[ -z "$dep_id" ]] && continue
                        local dep_file="${TASKS_DIR}/${dep_id}.json"
                        [[ -f "$dep_file" ]] || continue
                        local dep_title dep_decisions dep_concerns
                        dep_title=$(jq -r '.title' "$dep_file")
                        dep_decisions=$(jq -r '.decisions // [] | if length > 0 then map("  - " + .) | join("\n") else empty end' "$dep_file")
                        dep_concerns=$(jq -r '.concerns // [] | if length > 0 then map("  - " + .) | join("\n") else empty end' "$dep_file")
                        if [[ -n "$dep_decisions" ]] || [[ -n "$dep_concerns" ]]; then
                            upstream_context+=$'\n'"#### Task ${dep_id}: ${dep_title}"
                            if [[ -n "$dep_decisions" ]]; then
                                upstream_context+=$'\n'"Decisions:"$'\n'"${dep_decisions}"
                            fi
                            if [[ -n "$dep_concerns" ]]; then
                                upstream_context+=$'\n'"Concerns:"$'\n'"${dep_concerns}"
                            fi
                        fi
                    done <<< "$dep_ids_for_context"
                fi
                if [[ -n "$upstream_context" ]]; then
                    extra_context+=$'\n\n## Context from Completed Dependencies\n'"${upstream_context}"
                fi

                # ── Deferred dependency merge ────────────────────
                # Merge completed dependency branches into main NOW, right
                # before creating this task's worktree. This ensures the new
                # worktree sees all predecessor work without ever disturbing
                # agents that are already running in their own worktrees.
                #
                # The main-branch lock serializes merges across parallel
                # features so two orchestrators never do checkout+merge
                # on the shared working tree simultaneously.
                local dep_ids
                dep_ids=$(echo "$task_json" | jq -r '.depends_on[]?' 2>/dev/null)
                if [[ -n "$dep_ids" ]]; then
                    local merge_failed=false

                    if ! main_branch_acquire_lock "deferred-merge/task-${task_id}"; then
                        _record_merge_attempt "$task_id"
                        local lock_attempts
                        lock_attempts=$(_get_merge_attempts "$task_id")
                        if [[ "$lock_attempts" -ge "$MERGE_CONFLICT_MAX_RETRIES" ]]; then
                            task_set_blocked "$task_id" "Could not acquire main-branch lock after ${lock_attempts} attempts"
                            log_warn "Task ${task_id}: lock contention — marked BLOCKED"
                        else
                            log_warn "Task ${task_id}: could not acquire main-branch lock — deferring (attempt ${lock_attempts}/${MERGE_CONFLICT_MAX_RETRIES})"
                        fi
                        continue
                    fi

                    while IFS= read -r dep_id; do
                        [[ -z "$dep_id" ]] && continue
                        local dep_branch
                        dep_branch=$(jq -r '.branch // empty' "${TASKS_DIR}/${dep_id}.json" 2>/dev/null)
                        [[ -z "$dep_branch" || "$dep_branch" == "null" ]] && continue
                        git_branch_exists "$dep_branch" || continue

                        # Skip if already merged into main
                        if _git merge-base --is-ancestor "$dep_branch" "$main_branch" 2>/dev/null; then
                            continue
                        fi

                        log_step "Deferred merge: ${dep_branch} → ${main_branch} (dependency of task ${task_id})"
                        if git_safe_merge "$dep_branch" "$main_branch"; then
                            log_success "Merged ${dep_branch} into ${main_branch}"
                        else
                            _record_merge_attempt "$task_id"
                            local attempts
                            attempts=$(_get_merge_attempts "$task_id")
                            if [[ "$attempts" -ge "$MERGE_CONFLICT_MAX_RETRIES" ]]; then
                                log_error_block \
                                    "Cannot merge ${dep_branch} into ${main_branch}" \
                                    "Conflicting changes persisted after ${attempts} attempts" \
                                    "Resolve manually, then: speed integrate --continue"
                                task_set_blocked "$task_id" "Merge conflict: ${dep_branch} into ${main_branch} (failed ${attempts}x)"
                                _record_failure "$task_id" "Persistent merge conflict: ${dep_branch}"
                            else
                                log_warn "Deferred merge failed for ${dep_branch} — deferring task ${task_id} (attempt ${attempts}/${MERGE_CONFLICT_MAX_RETRIES})"
                            fi
                            merge_failed=true
                            break
                        fi
                    done <<< "$dep_ids"

                    main_branch_release_lock

                    if $merge_failed; then
                        continue  # skip this task, try again next loop iteration
                    fi
                fi

                # ── Branch audit: check for prior agent work ─────────
                # Run BEFORE refresh. The refresh creates a --no-ff merge
                # commit that defeats branch_audit's --is-ancestor check
                # and empties the fork-point diff.
                if [[ -n "$branch" ]] && git_branch_exists "$branch"; then
                    local audit_result
                    audit_result=$(branch_audit "$task_id")

                    if [[ "$audit_result" == "pass" ]]; then
                        task_set_done "$task_id"
                        log_success "Task ${task_id}: branch already integrated — marked DONE"
                        continue
                    fi
                    if [[ "$audit_result" == "blocked" ]]; then
                        task_set_blocked "$task_id" "Prior agent reported blocked before interruption"
                        log_warn "Task ${task_id}: prior agent was blocked — marked BLOCKED"
                        _invoke_supervisor "$task_id" "blocked"
                        continue
                    fi
                    # "fail" → prior work exists but failed gates.
                    # Keep gate_results so the agent reads failure context (line 689).
                    # gates_run at line 486 overwrites them after the agent finishes.
                    # "empty" → proceed to refresh and spawn agent
                fi

                # ── Refresh task branch against main ──────────────────
                # Merge main into the task branch so the agent sees all
                # predecessor work. Skip if branch doesn't exist or is
                # already up-to-date. Conflict = warn and proceed stale.
                if [[ -n "$branch" ]] && git_branch_exists "$branch"; then
                    local main_branch
                    main_branch=$(git_main_branch)
                    if ! _git merge-base --is-ancestor "$main_branch" "$branch" 2>/dev/null; then
                        log_verbose "  Refreshing ${branch} against ${main_branch}"
                        if ! _git checkout "$branch" >/dev/null 2>&1 || \
                           ! _git merge --no-ff "$main_branch" -m "speed: refresh branch against ${main_branch}" >/dev/null 2>&1; then
                            _git merge --abort 2>/dev/null || true
                            log_warn "Task ${task_id}: could not refresh branch against ${main_branch} — proceeding with stale branch"
                        fi
                        _git checkout "$main_branch" >/dev/null 2>&1 || true
                    fi
                fi

                # Create isolated worktree for this agent
                local worktree_path
                worktree_path=$(git_create_worktree "$task_id" "$branch") || {
                    task_set_failed "$task_id" "Worktree creation failed for branch ${branch}"
                    log_error "Task ${task_id}: worktree creation failed"
                    _record_failure "$task_id" "Worktree creation failed"
                    continue
                }
                git_setup_worktree_deps "$worktree_path"

                # ── Layer 2: Build task-specific context package ──────
                # Builds code context (tiered file content), task context
                # (upstream/downstream/reasoning), spec context, and budget.
                local task_file_path="${TASKS_DIR}/${task_id}.json"

                # Collect completed task outputs for upstream propagation
                local completed_json="{}"
                local dep_ids_for_l2
                dep_ids_for_l2=$(echo "$task_json" | jq -r '.depends_on[]?' 2>/dev/null)
                if [[ -n "$dep_ids_for_l2" ]]; then
                    while IFS= read -r dep_id; do
                        [[ -z "$dep_id" ]] && continue
                        local dep_file="${TASKS_DIR}/${dep_id}.json"
                        [[ -f "$dep_file" ]] || continue
                        completed_json=$(echo "$completed_json" | jq --arg did "$dep_id" --slurpfile dep "$dep_file" '. + {($did): $dep[0]}') || {
                            log_warn "Task ${task_id}: could not parse dependency task file ${dep_file} — skipping dependency context"
                            continue
                        }
                    done <<< "$dep_ids_for_l2"
                fi

                local l2_result
                l2_result=$(context_build_layer2_task "$task_file_path" "${TASKS_DIR}" "$completed_json" "developer" 2>/dev/null) || l2_result=""
                if [[ -n "$l2_result" ]]; then
                    log_verbose "  Layer 2 built for task ${task_id}"
                fi

                # Load cross-cutting concerns
                local cc_json=""
                if [[ -f "${FEATURE_DIR}/cross_cutting_concerns.json" ]]; then
                    cc_json=$(cat "${FEATURE_DIR}/cross_cutting_concerns.json")
                fi

                # ── Layer 3: Assemble developer prompt ────────────────
                # Replaces inline string-building with structured context
                # assembly: pre-loaded code, rationale, criteria, constraints,
                # upstream decisions, downstream expectations, warnings, spec.
                local agent_message
                agent_message=$(context_assemble_developer \
                    "$task_file_path" \
                    "$branch" \
                    "$worktree_path" \
                    "${FEATURE_NAME}" \
                    "$cc_json" 2>/dev/null) || agent_message=""

                # Fallback: if assembly fails, use the basic inline prompt
                if [[ -z "$agent_message" ]]; then
                    log_verbose "  Layer 3 assembly unavailable for task ${task_id} — using inline prompt"
                    local files_section=""
                    if [[ -n "$files_touched" ]]; then
                        files_section="
### Declared Files (stay within scope)
${files_touched}"
                    fi

                    agent_message="## Task: ${title}

### Description
${description}

### Acceptance Criteria
${criteria}
${files_section}

### Git Branch
You are working on branch: \`${branch}\`
You are already on this branch in an isolated worktree. Do NOT run git checkout.
Commit your work to this branch.

### Quality Checks
Run gates iteratively as you work:
- After each group of files: \`${SPEED_CMD} gates -f ${FEATURE_NAME} --task ${task_id} --fast\`
- Before declaring done: \`${SPEED_CMD} gates -f ${FEATURE_NAME} --task ${task_id} --full\`
All gates must pass before you output your completion JSON.

### Working Directory
${worktree_path}"
                fi

                # Append extra context (review feedback, debugger analysis, upstream)
                agent_message+="${extra_context}"

                # Append gate failure context for retries (Change 4)
                if [[ -n "$failure_context" ]]; then
                    agent_message+="
${failure_context}"
                fi

                # Spawn agent in the worktree directory
                local output_file="${LOGS_DIR}/${task_id}.log"
                local pid
                pid=$(provider_spawn_bg \
                    "${AGENTS_DIR}/developer.md" \
                    "$agent_message" \
                    "$output_file" \
                    "$task_model" \
                    "$AGENT_TOOLS_FULL" \
                    "$worktree_path") || {
                    task_set_failed "$task_id" "Agent spawn failed"
                    log_error "Task ${task_id}: agent spawn failed — check agent files and provider config"
                    _record_failure "$task_id" "Agent spawn failed"
                    git_remove_worktree "$task_id"
                    continue
                }

                echo "$pid" > "${running_dir}/${task_id}.pid"

                # Atomic: status + started_at + agent_pid in one write
                task_set_running "$task_id" "$pid"
                ((running_count++)) || true

                log_step "Spawned agent for task ${task_id}: ${COLOR_STEP}${title}${RESET}"
                log_verbose "  PID: ${pid} | model: ${task_model} | branch: ${branch}"

                # Update state file
                jq --arg tid "$task_id" --arg pid "$pid" \
                    '.agents += [{"task_id": $tid, "pid": ($pid | tonumber)}]' \
                    "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"

            done <<< "$ready_tasks"
        fi

        # Brief status update
        local done_count pending_count failed_count blocked_count
        done_count=$(task_count_by_status "done")
        running_count=$(_running_count)
        pending_count=$(task_count_by_status "pending")
        failed_count=$(task_count_by_status "failed")
        blocked_count=$(task_count_by_status "blocked")
        local elapsed=$((SECONDS - run_start))
        local elapsed_fmt
        elapsed_fmt=$(format_duration "$elapsed")
        if [[ "${VERBOSITY:-1}" -ge 1 ]]; then
            local support_suffix=""
            if [[ "$support_count" -gt 0 ]]; then
                support_suffix=" ${COLOR_DIM}+${support_count}s${RESET}"
            fi
            local remaining=$((total - done_count - failed_count))
            local status_line="${COLOR_STEP}${SYM_ARROW}${RESET} ${done_count}/${total} done  ${running_count} active  ${remaining} left${support_suffix}  ${COLOR_DIM}${elapsed_fmt}${RESET}"
            if [[ "$failed_count" -gt 0 ]]; then
                status_line="${COLOR_STEP}${SYM_ARROW}${RESET} ${done_count}/${total} done  ${running_count} active  ${remaining} left  ${COLOR_ERROR}${failed_count} failed${RESET}${support_suffix}  ${COLOR_DIM}${elapsed_fmt}${RESET}"
            fi
            local status_counts="${running_count}:${done_count}:${pending_count}:${failed_count}:${support_count}"

            if [[ -t 2 ]]; then
                # TTY: overwrite in place on stderr, clear to end of line
                echo -ne "\r\033[K${COLOR_DIM}[$(_log_timestamp)]${RESET} ${status_line}" >&2
            elif [[ "$status_counts" != "$_prev_status_counts" ]]; then
                # Non-TTY: print only when counts change, with newline
                echo -e "${COLOR_DIM}[$(_log_timestamp)]${RESET} ${status_line}" >&2
            fi
            _prev_status_counts="$status_counts"
        fi

        # Check halt threshold
        local fail_pct=0
        if [[ "$total" -gt 0 ]]; then
            fail_pct=$(( (failed_count * 100) / total ))
        fi
        if [[ "$fail_pct" -ge "$HALT_FAILURE_PCT" ]]; then
            echo ""
            log_error_block \
                "Over ${HALT_FAILURE_PCT}% of tasks failed (${failed_count}/${total}) — halting SPEED" \
                "Too many tasks are failing, indicating a systemic issue" \
                "Run: speed status  — then fix the root cause and: speed retry"
            break
        fi

        # Sleep before next check
        sleep "$POLL_INTERVAL"
    done

    # Clear the status line before final output
    if [[ -t 2 ]]; then
        echo -ne "\r\033[K" >&2
    fi
    echo ""

    # Reconcile any tasks still at "running" before setting state to idle
    _reconcile_running_tasks

    # Clean up
    rm -rf "$running_dir" "$merge_attempts_dir" "$support_dir"

    # Final state update
    jq '.status = "idle" | .agents = []' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"

    # ── Compute final stats ──────────────────────────────────────
    local final_done final_failed final_blocked final_pending
    final_done=$(task_count_by_status "done")
    final_failed=$(task_count_by_status "failed")
    final_blocked=$(task_count_by_status "blocked")
    final_pending=$(task_count_by_status "pending")

    [[ "${MP_ENABLED:-}" == "true" ]] && event_emit "run.completed" "$FEATURE_NAME" "{\"done\":$final_done,\"failed\":$final_failed,\"blocked\":$final_blocked}" || true
    local elapsed=$((SECONDS - run_start))
    local elapsed_fmt
    elapsed_fmt=$(format_duration "$elapsed")

    # ── Determine exit code ──────────────────────────────────────
    local run_exit=$EXIT_OK
    if [[ "$final_failed" -gt 0 ]]; then
        local fail_pct_final=0
        if [[ "$total" -gt 0 ]]; then
            fail_pct_final=$(( (final_failed * 100) / total ))
        fi
        if [[ "$fail_pct_final" -ge "$HALT_FAILURE_PCT" ]]; then
            run_exit=$EXIT_HALTED
        else
            run_exit=$EXIT_TASK_FAILURE
        fi
    fi

    # ── JSON output mode ─────────────────────────────────────────
    if [[ "$JSON_OUTPUT" == "true" ]]; then
        local status_str="completed"
        [[ $run_exit -ne 0 ]] && status_str="failed"

        # Build failures array
        local failures_json="[]"
        if [[ "$final_failed" -gt 0 ]]; then
            failures_json=$(
                for f in "${TASKS_DIR}"/*.json; do
                    [[ -f "$f" ]] || continue
                    local s
                    s=$(jq -r '.status' "$f")
                    [[ "$s" == "failed" ]] && jq -c '{task_id: .id, title: .title, error: (.error // "unknown")}' "$f"
                done | jq -sc '.'
            )
        fi

        jq -nc \
            --arg status "$status_str" \
            --argjson tasks_total "$total" \
            --argjson tasks_passed "$final_done" \
            --argjson tasks_failed "$final_failed" \
            --argjson duration_seconds "$elapsed" \
            --argjson exit_code "$run_exit" \
            --argjson failures "$failures_json" \
            '{status: $status, tasks_total: $tasks_total, tasks_passed: $tasks_passed, tasks_failed: $tasks_failed, duration_seconds: $duration_seconds, exit_code: $exit_code, failures: $failures}'
        exit "$run_exit"
    fi

    # ── Print run summary ────────────────────────────────────────
    log_header "Run Summary"
    echo ""
    echo -e "  Total tasks:  ${total}"
    echo -e "  Passed:       ${final_done}   ${COLOR_SUCCESS}${SYM_CHECK}${RESET}"
    if [[ "$final_failed" -gt 0 ]]; then
        echo -e "  Failed:       ${final_failed}   ${COLOR_ERROR}${SYM_CROSS}${RESET}"
    else
        echo -e "  Failed:       0"
    fi
    if [[ "$final_blocked" -gt 0 ]]; then
        echo -e "  Blocked:      ${final_blocked}   ${COLOR_WARN}${SYM_WARN}${RESET}"
    fi
    if [[ "$final_pending" -gt 0 ]]; then
        echo -e "  Pending:      ${final_pending}   ${SYM_PENDING}"
    fi
    echo -e "  Duration:     ${elapsed_fmt}"
    echo ""

    # Show failed task details
    if [[ "$final_failed" -gt 0 ]]; then
        echo -e "  ${COLOR_ERROR}Failed tasks:${RESET}"
        for f in "${TASKS_DIR}"/*.json; do
            [[ -f "$f" ]] || continue
            local s tid ttitle terror
            s=$(jq -r '.status' "$f")
            [[ "$s" == "failed" ]] || continue
            tid=$(jq -r '.id' "$f")
            ttitle=$(jq -r '.title' "$f")
            terror=$(jq -r '.error // "unknown"' "$f")
            echo -e "    Task ${tid}: ${COLOR_DIM}\"${ttitle}\"${RESET}"
            echo -e "      Error: ${terror}"
            echo -e "      Fix:   ${COLOR_STEP}speed retry --task-id ${tid}${RESET}"
        done
        echo ""
    fi

    echo -e "${COLOR_DIM}$(printf '─%.0s' $(seq 1 50))${RESET}"
    echo ""

    # Task graph and summary
    task_print_graph
    echo ""
    task_print_summary
    echo ""

    if [[ "$final_failed" -gt 0 ]]; then
        log_warn "${final_failed} task(s) failed. Diagnose with ${COLOR_STEP}speed retry --task-id ID${RESET} then provide guidance with ${COLOR_STEP}--context${RESET}."
    fi

    if [[ "$final_blocked" -gt 0 ]]; then
        log_warn "${final_blocked} task(s) blocked. Run ${COLOR_STEP}speed status${RESET} for details and supervisor analysis."
    fi

    if [[ "$final_done" -gt 0 ]]; then
        echo -e "Next: ${COLOR_STEP}speed review${RESET} then ${COLOR_STEP}speed coherence${RESET} then ${COLOR_STEP}speed integrate${RESET}"
    fi
    echo ""
    log_result "Completed in ${elapsed_fmt}"

    exit "$run_exit"
}
