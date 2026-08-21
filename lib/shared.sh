#!/usr/bin/env bash
# shared.sh — Helpers used by multiple command modules
#
# Sourced by the `speed` entrypoint before command modules.
# Requires: config.sh, log.sh, provider.sh, tasks.sh, gates.sh, cleanup.sh

set -euo pipefail

# ── Gate skip logging ────────────────────────────────────────────
# Appends a JSON line to skipped-gates.json when a gate is bypassed.
# Used by steps 12 (human corrections) during observation extraction.

_log_gate_skip() {
    local gate_name="$1"
    local stage="$2"
    local skip_file="${LOGS_DIR:-}/skipped-gates.json"

    # Graceful: if LOGS_DIR isn't set, skip logging silently
    [[ -z "${LOGS_DIR:-}" ]] && return 0
    [[ ! -d "${LOGS_DIR:-}" ]] && return 0

    printf '{"gate":"%s","stage":"%s","timestamp":"%s"}\n' \
        "$gate_name" "$stage" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$skip_file"
}

# ── Spec path ─────────────────────────────────────────────────────

_get_spec_path() {
    local dir="${FEATURE_DIR:-${STATE_DIR}}"
    if [[ -f "${dir}/spec_path" ]]; then
        local saved_path
        saved_path=$(cat "${dir}/spec_path")
        if [[ -n "$saved_path" ]] && [[ -f "$saved_path" ]]; then
            echo "$saved_path"
        elif [[ -n "$saved_path" ]]; then
            log_warn "Saved spec path '${saved_path}' no longer exists — was it moved or deleted?"
        fi
    fi
}

# ── Product Guardian ──────────────────────────────────────────────
# Runs the Product Guardian agent against any input (spec, diff, integration)
# Returns: 0 = aligned, 1 = rejected, 2 = flagged (warnings), 3 = unparseable

_run_guardian() {
    local check_type="$1"  # "pre-plan" | "post-review" | "post-integration"
    local content="$2"
    local label="${3:-}"

    local overview_file="${PROJECT_ROOT}/${VISION_FILE}"
    if [[ ! -f "$overview_file" ]]; then
        log_warn "Product overview not found at ${overview_file} — skipping guardian check"
        return 0
    fi

    local overview_content
    overview_content=$(cat "$overview_file")

    # Learnings injection
    local _mem="${STATE_DIR}/memory"
    [[ "${MP_ENABLED:-}" == "true" ]] && _mem="$(mp_knowledge_dir)"
    local learnings_file="${_mem}/learnings/guardian-learnings.json"
    local scope_calibration=""
    if [[ -f "$learnings_file" ]]; then
        scope_calibration=$(python3 -c "
import json, sys
data = json.load(open('$learnings_file'))
for e in data.get('entries', []):
    t = e['observation_type']
    ctx = e.get('reframing_context', '')
    detail = e.get('detail', {})
    summary = detail.get('summary', detail.get('description', ''))
    tag = f' [{ctx}]' if ctx else ''
    print(f'- **{t}**{tag}: {summary}')
" 2>/dev/null || true)
    fi

    local scope_section=""
    if [[ -n "$scope_calibration" ]]; then
        scope_section="
### Scope Calibration
${scope_calibration}
"
    fi

    local guardian_message="## Guardian Check: ${check_type}

### Product Vision (source of truth)
${overview_content}
${scope_section}
### Input to Evaluate
${content}

Evaluate this ${check_type} input against the product vision. Respond with JSON."

    log_step "Running Product Guardian (${check_type})..."

    local raw_guardian_output
    if ! raw_guardian_output=$(provider_run \
        "${AGENTS_DIR}/product-guardian.md" \
        "$guardian_message" \
        "$MODEL_SUPPORT" \
        "$AGENT_TOOLS_READONLY" \
        "Guardian"); then
        log_warn "Guardian agent failed (${check_type}) — check agent CLI connection"
        return 3
    fi

    if [[ -z "$raw_guardian_output" ]]; then
        log_warn "Guardian agent returned empty output (${check_type})"
        return 3
    fi

    local guardian_output
    guardian_output=$(parse_agent_json "$raw_guardian_output") || guardian_output="$raw_guardian_output"

    # Save report
    local timestamp
    timestamp=$(date +%s)
    local log_file="${LOGS_DIR}/guardian-${check_type}-${timestamp}.json"
    echo "$guardian_output" > "$log_file"
    _prune_logs "guardian-${check_type}-" ".json"

    # Parse status — if invalid JSON, falls through to the * case
    if ! _require_json "Guardian" "$guardian_output"; then
        log_warn "Review raw output: ${log_file}"
    fi

    local status
    status=$(echo "$guardian_output" | jq -r '.status // "unknown"' 2>/dev/null || echo "unknown")
    local summary
    summary=$(echo "$guardian_output" | jq -r '.summary // "No summary"' 2>/dev/null || echo "No summary")

    case "$status" in
        aligned)
            log_success "Guardian: ${COLOR_SUCCESS}ALIGNED${RESET} — ${summary}"
            echo "$guardian_output"
            return 0
            ;;
        flagged)
            log_warn "Guardian: ${COLOR_WARN}FLAGGED${RESET} — ${summary}"
            echo "$guardian_output"

            # Print flags
            local flag_count
            flag_count=$(echo "$guardian_output" | jq '.flags | length')
            if [[ "$flag_count" -gt 0 ]]; then
                echo ""
                echo -e "  ${BOLD}Vision Flags:${RESET}"
                echo "$guardian_output" | jq -r '.flags[] | "    \(.severity): \(.description)"'
                echo ""
            fi
            return 2
            ;;
        rejected)
            log_error "Guardian: ${COLOR_ERROR}REJECTED${RESET} — ${summary}"
            echo "$guardian_output"

            # Print critical flags
            local critical_flags
            critical_flags=$(echo "$guardian_output" | jq -r '.flags[] | select(.severity == "critical") | "    \(.description)\n    Spec: \(.vision_reference // .spec_reference)"' 2>/dev/null || echo "")
            if [[ -n "$critical_flags" ]]; then
                echo ""
                echo -e "  ${BOLD}Critical Violations:${RESET}"
                echo -e "$critical_flags"
                echo ""
            fi

            # Print Won't Have violations
            local wont_have
            wont_have=$(echo "$guardian_output" | jq -r '(.scope_violations // .wont_have_violations // [])[] | "    \(.feature) → maps to Won'\''t Have: \(.maps_to)"' 2>/dev/null || echo "")
            if [[ -n "$wont_have" ]]; then
                echo -e "  ${BOLD}Won't Have Violations:${RESET}"
                echo -e "$wont_have"
                echo ""
            fi
            return 1
            ;;
        *)
            log_warn "Guardian returned unparseable status '${status}'. Review: ${log_file}"
            log_warn "This may indicate the guardian agent failed or returned non-JSON output."
            # Show first 3 lines for quick diagnosis
            echo "$guardian_output" | head -3 | while IFS= read -r line; do
                echo -e "    ${COLOR_DIM}${line}${RESET}" >&2
            done
            echo "$guardian_output"
            return 3  # Distinct code: 0=aligned, 1=rejected, 2=flagged, 3=unparseable
            ;;
    esac
}

# ── Invoke supervisor for diagnosis ──────────────────────────────
# Args: task_id trigger_type [mode]
#   mode: "async" (default) spawns background agent
#         "sync"  runs inline via provider_run and returns output

_invoke_supervisor() {
    local task_id="$1"
    local trigger_type="$2"  # "blocked", "pattern", "coherence", "contract"
    local mode="${3:-async}"

    local task_json
    task_json=$(task_get "$task_id")

    # Gather SPEED state
    local speed_state=""
    speed_state+="Total tasks: $(task_count_total)\n"
    speed_state+="Done: $(task_count_by_status "done")\n"
    speed_state+="Running: $(task_count_by_status "running")\n"
    speed_state+="Pending: $(task_count_by_status "pending")\n"
    speed_state+="Failed: $(task_count_by_status "failed")\n"
    speed_state+="Blocked: $(task_count_by_status "blocked")\n"

    # Gather failure history
    local failure_history=""
    local failure_log="${FEATURE_DIR}/failure_history.jsonl"
    if [[ -f "$failure_log" ]]; then
        failure_history=$(cat "$failure_log")
    fi

    # Gather task details
    local task_details=""
    task_details+="Task ${task_id}: $(echo "$task_json" | jq -r '.title')\n"
    task_details+="Status: $(echo "$task_json" | jq -r '.status')\n"
    task_details+="Error: $(echo "$task_json" | jq -r '.error // "none"')\n"

    # Include debugger analysis if available
    local debugger_log="${LOGS_DIR}/debugger-${task_id}.json"
    if [[ -f "$debugger_log" ]]; then
        task_details+="\nDebugger Analysis:\n$(cat "$debugger_log")\n"
    fi

    local supervisor_message="## Supervisor Trigger: ${trigger_type}

### SPEED State
$(echo -e "$speed_state")

### Triggering Task
$(echo -e "$task_details")

### Failure History
${failure_history}

Diagnose the situation and recommend recovery actions."

    if [[ "$mode" == "sync" ]]; then
        provider_run \
            "${AGENTS_DIR}/supervisor.md" \
            "$supervisor_message" \
            "$MODEL_SUPPORT" \
            "$AGENT_TOOLS_READONLY" \
            "Supervisor"
    else
        _spawn_support_agent "supervisor-${trigger_type}" "$task_id" "${AGENTS_DIR}/supervisor.md" "$supervisor_message"
    fi
}

# ── Process completed support agent output ────────────────────────
# Called from the polling loop when a debugger/supervisor finishes.

_handle_support_completion() {
    local agent_type="$1"  # e.g. "debugger" or "supervisor-pattern"
    local for_task_id="$2"
    local error="${3:-}"    # non-empty if agent crashed/timed out/CLI error
    local output_file="${LOGS_DIR}/${agent_type}-${for_task_id}-bg.log"

    # Build the parsed result, with fallback error JSON on any failure
    local parsed=""
    if [[ -n "$error" ]]; then
        log_warn "${agent_type} for task ${for_task_id}: ${error}"
        parsed="{\"error\": \"${agent_type} failed: ${error}\"}"
    elif [[ ! -s "$output_file" ]]; then
        log_warn "${agent_type} for task ${for_task_id} produced no output"
        parsed="{\"error\": \"${agent_type} returned empty output\"}"
    else
        local raw_output
        raw_output=$(cat "$output_file")
        parsed=$(parse_agent_json "$raw_output") || parsed="$raw_output"
    fi

    if [[ "$agent_type" == "debugger" ]]; then
        # Always write the file so retry path has something to read
        echo "$parsed" > "${LOGS_DIR}/debugger-${for_task_id}.json"
        if [[ -n "$error" ]]; then
            log_warn "Debugger failed for task ${for_task_id} — retry will proceed without analysis"
        else
            log_step "Debugger analysis saved to ${LOGS_DIR}/debugger-${for_task_id}.json"
        fi
    elif [[ "$agent_type" == supervisor-* ]]; then
        local supervisor_log="${LOGS_DIR}/supervisor-${for_task_id}-$(date +%s).json"
        echo "$parsed" > "$supervisor_log"
        _prune_logs "supervisor-${for_task_id}-" ".json"

        if ! _require_json "Supervisor" "$parsed"; then
            log_warn "Skipping supervisor analysis — see ${supervisor_log}"
            echo ""
            log_step "Full analysis: ${supervisor_log}"
            return 0
        fi

        # Surface diagnosis
        local diagnosis
        diagnosis=$(echo "$parsed" | jq -r '.diagnosis // empty')
        if [[ -n "$diagnosis" ]]; then
            echo ""
            echo -e "${BOLD}Supervisor Diagnosis:${RESET}"
            echo -e "  ${diagnosis}"
        fi

        # Surface pattern detection
        local pattern_desc
        pattern_desc=$(echo "$parsed" | jq -r '.pattern_detected.description // empty')
        if [[ -n "$pattern_desc" ]]; then
            local root_cause affected
            root_cause=$(echo "$parsed" | jq -r '.pattern_detected.root_cause // "Unknown"')
            affected=$(echo "$parsed" | jq -r '.pattern_detected.affected_tasks // [] | join(", ")')
            echo ""
            echo -e "${COLOR_ERROR}${BOLD}PATTERN DETECTED:${RESET} ${pattern_desc}"
            echo -e "  ${BOLD}Root cause:${RESET} ${root_cause}"
            echo -e "  ${BOLD}Affected tasks:${RESET} ${affected}"
        fi

        # Surface recommendations
        local action_count
        action_count=$(echo "$parsed" | jq '[.actions // [] | .[]] | length')
        if [[ "$action_count" -gt 0 ]]; then
            echo ""
            echo -e "${BOLD}Supervisor Recommendations:${RESET}"
            echo "$parsed" | jq -r '
                .actions[]? |
                "  \(.action) task \(.task_id // "?"): \(.reason // "no reason given")" +
                if .human_question then "\n    → HUMAN INPUT: \(.human_question)" else "" end +
                if .additional_context then "\n    → Context: \(.additional_context)" else "" end
            '
        fi

        local rec_count
        rec_count=$(echo "$parsed" | jq '[.recommendations // [] | .[]] | length')
        if [[ "$rec_count" -gt 0 ]]; then
            echo ""
            echo -e "${BOLD}Suggestions:${RESET}"
            echo "$parsed" | jq -r '.recommendations[]? | "  • \(.)"'
        fi

        # Check halt recommendation
        local should_halt
        should_halt=$(echo "$parsed" | jq -r '.should_halt // false')
        if [[ "$should_halt" == "true" ]]; then
            local halt_reason
            halt_reason=$(echo "$parsed" | jq -r '.halt_reason // "Unknown"')
            echo ""
            log_error "Supervisor recommends HALTING: ${halt_reason}"
        fi

        echo ""
        log_step "Full analysis: ${supervisor_log}"
    fi
}

# ── Orphan agent detection and cleanup ────────────────────────────

# Check if a PID is a live SPEED agent (not a recycled PID).
# Returns 0 if the PID is alive AND looks like a SPEED-managed agent process.
_is_speed_agent() {
    local pid="$1"

    # Not running at all — definitely not our agent
    kill -0 "$pid" 2>/dev/null || return 1

    # Running — verify it's actually an agent-related process
    local cmd_line
    cmd_line=$(ps -p "$pid" -o command= 2>/dev/null || echo "")
    [[ -z "$cmd_line" ]] && return 1

    local bn
    bn=$(basename "${PROVIDER_BIN:-}")
    [[ -z "$bn" ]] && return 1  # no provider binary known — can't match

    # Match provider binary anywhere in cmdline
    if [[ "$cmd_line" == *"$bn"* ]]; then
        return 0
    fi

    # Match timeout/gtimeout as the COMMAND (prefix), not as a substring.
    # *timeout* would false-positive on any bash -c whose argument text
    # contains the word "timeout".
    if [[ "$cmd_line" == timeout* ]] || [[ "$cmd_line" == */timeout* ]] || \
       [[ "$cmd_line" == gtimeout* ]] || [[ "$cmd_line" == */gtimeout* ]]; then
        return 0
    fi

    # PID is alive but doesn't look like our agent — recycled PID
    return 1
}

# Kill a process tree: SIGTERM first, wait, then SIGKILL if still alive.
_kill_agent_tree() {
    local pid="$1"
    local task_label="${2:-unknown}"

    if ! kill -0 "$pid" 2>/dev/null; then
        return 0  # Already dead
    fi

    log_step "Terminating orphan agent for ${task_label} (PID ${pid})"

    # Kill the process group (negative PID) to catch child processes too.
    # Fall back to single-process kill if PGID kill fails (different session).
    kill -TERM -- -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true

    # Wait up to 5 seconds for graceful shutdown
    local waited=0
    while kill -0 "$pid" 2>/dev/null && [[ $waited -lt 5 ]]; do
        sleep 1
        ((waited++)) || true
    done

    # Force-kill if still alive
    if kill -0 "$pid" 2>/dev/null; then
        log_warn "Agent PID ${pid} didn't respond to SIGTERM — sending SIGKILL"
        kill -KILL -- -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
        sleep 1
    fi
}

# Kill all orphan agents for the current feature.
# Scans both running_dir PID files and task JSON agent_pid fields.
# Returns the count of orphans killed.
_kill_orphan_agents() {
    local killed=0
    local running_dir="${FEATURE_DIR}/running"
    local support_dir="${FEATURE_DIR}/support"

    # 1. Kill orphan developer agents tracked in running_dir
    if [[ -d "$running_dir" ]]; then
        for pid_file in "$running_dir"/*.pid; do
            [[ -f "$pid_file" ]] || continue
            local task_id pid
            task_id=$(basename "$pid_file" .pid)
            pid=$(cat "$pid_file")

            if _is_speed_agent "$pid"; then
                _kill_agent_tree "$pid" "task-${task_id}"
                ((killed++)) || true
            fi
            rm -f "$pid_file"
            rm -f "${LOGS_DIR}/${task_id}.log.done"
        done
    fi

    # 2. Kill orphan support agents (debugger/supervisor) tracked in support_dir
    if [[ -d "$support_dir" ]]; then
        for pid_file in "$support_dir"/*.pid; do
            [[ -f "$pid_file" ]] || continue
            local support_name pid
            support_name=$(basename "$pid_file" .pid)
            pid=$(cat "$pid_file")

            if _is_speed_agent "$pid"; then
                _kill_agent_tree "$pid" "${support_name}"
                ((killed++)) || true
            fi
            rm -f "$pid_file" "${support_dir}/${support_name}.task"
        done
    fi

    # 3. Cross-check: kill any agent_pid in task JSONs not caught above
    #    (covers case where running_dir was already deleted but task JSON retained the PID)
    for f in "${TASKS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local status agent_pid tid
        status=$(jq -r '.status // "unknown"' "$f" 2>/dev/null) || continue
        [[ "$status" == "running" ]] || continue

        tid=$(jq -r '.id' "$f" 2>/dev/null) || continue
        agent_pid=$(jq -r '.agent_pid // "null"' "$f" 2>/dev/null) || continue
        [[ "$agent_pid" == "null" ]] && continue

        if _is_speed_agent "$agent_pid"; then
            _kill_agent_tree "$agent_pid" "task-${tid}"
            ((killed++)) || true
        fi
    done

    echo "$killed"
}
