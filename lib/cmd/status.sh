#!/usr/bin/env bash
# status.sh — Feature status command

cmd_status() {
    # ── Parse flags ────────────────────────────────────────────────
    local show_defects=false
    local show_team=false
    local status_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --defects) show_defects=true; shift ;;
            --team)    show_team=true; shift ;;
            *) status_args+=("$1"); shift ;;
        esac
    done
    set -- "${status_args[@]+"${status_args[@]}"}"

    # ── --team mode ──────────────────────────────────────────────
    if [[ "$show_team" == "true" ]]; then
        if [[ "${MP_ENABLED:-}" != "true" ]]; then
            log_error "Team roster requires multi-player mode. Run 'speed mp-init' first."
            exit 1
        fi
        log_header "Team Roster"
        roster_format_table
        echo ""
        return
    fi

    # ── --defects mode ─────────────────────────────────────────────
    if [[ "$show_defects" == "true" ]]; then
        log_header "Defects"
        local defect_rows
        defect_rows=$(list_defects)
        if [[ -z "$defect_rows" ]]; then
            echo "No defects found."
        else
            echo "Defects:"
            echo "$defect_rows"
        fi
        echo ""
        return
    fi

    log_header "SPEED Status"

    # ── Feature overview ──────────────────────────────────────────
    local features
    features=$(feature_list)
    local active_feature
    active_feature=$(feature_get_active)

    if [[ -z "$features" ]]; then
        log_info "No features planned. Run 'speed plan <spec>' to start."
        return
    fi

    echo -e "${BOLD}Features:${RESET}"
    local _feat_root="$FEATURES_DIR"
    [[ "${MP_ENABLED:-}" == "true" ]] && _feat_root="$SHARED_FEATURES_DIR"

    while IFS= read -r feat; do
        [[ -z "$feat" ]] && continue
        local feat_dir="${_feat_root}/${feat}"
        local feat_done=0 feat_total=0 feat_running=0 feat_failed=0
        for f in "${feat_dir}/tasks/"*.json; do
            [[ -f "$f" ]] || continue
            ((feat_total++)) || true
            local s
            s=$(jq -r '.status // "unknown"' "$f")
            case "$s" in
                done) ((feat_done++)) || true ;;
                running) ((feat_running++)) || true ;;
                failed) ((feat_failed++)) || true ;;
            esac
        done
        local marker=""
        if [[ "$feat" == "$active_feature" ]]; then
            marker=" ${COLOR_SUCCESS}(active)${RESET}"
        fi
        local progress="${feat_done}/${feat_total}"
        local detail=""
        if [[ $feat_running -gt 0 ]]; then detail+=", ${COLOR_WARN}${feat_running} running${RESET}"; fi
        if [[ $feat_failed -gt 0 ]]; then detail+=", ${COLOR_ERROR}${feat_failed} failed${RESET}"; fi
        echo -e "  ${COLOR_STEP}${feat}${RESET}${marker} — ${progress} done${detail}"
    done <<< "$features"
    echo ""

    # ── Detailed view for the target feature ──────────────────────
    # If --feature is specified, show that one. Otherwise show the active feature.
    local target_feature=""
    if [[ -n "$GLOBAL_FEATURE" ]]; then
        target_feature="$GLOBAL_FEATURE"
    elif [[ -n "$active_feature" ]] && [[ -d "${_feat_root}/${active_feature}" ]]; then
        target_feature="$active_feature"
    else
        # Show first feature if only one exists
        local feat_count
        feat_count=$(echo "$features" | wc -l | tr -d ' ')
        if [[ "$feat_count" -eq 1 ]]; then
            target_feature="$features"
        else
            echo -e "Use ${COLOR_STEP}--feature <name>${RESET} to see details for a specific feature."
            echo ""
            return
        fi
    fi

    feature_activate "$target_feature"
    echo -e "${BOLD}Showing: ${COLOR_STEP}${target_feature}${RESET}"
    echo ""

    # Check if initialized
    if [[ ! -d "$TASKS_DIR" ]]; then
        log_info "Feature '${target_feature}' has no tasks."
        return
    fi

    local total
    total=$(task_count_total)

    if [[ "$total" -eq 0 ]]; then
        log_info "No tasks. Run 'speed plan <spec>' to create tasks."
        return
    fi

    # Task graph
    task_print_graph
    echo ""
    task_print_summary
    echo ""

    # State info
    if [[ -f "$STATE_FILE" ]]; then
        local speed_status
        speed_status=$(jq -r '.status' "$STATE_FILE")
        local agent_count
        agent_count=$(jq '.agents | length' "$STATE_FILE")

        echo -e "${BOLD}SPEED:${RESET} ${speed_status} | Active agents: ${agent_count}"

        if [[ "$agent_count" -gt 0 ]]; then
            echo -e "${BOLD}Active Agents:${RESET}"
            jq -r '.agents[] | "  PID \(.pid) → Task \(.task_id)"' "$STATE_FILE"
        fi
    fi

    # Contract info
    if [[ -f "${CONTRACT_FILE}" ]]; then
        echo -e "${BOLD}Contract:${RESET} ${COLOR_SUCCESS}present${RESET}"
    else
        echo -e "${BOLD}Contract:${RESET} ${COLOR_WARN}missing${RESET}"
    fi

    # Security findings summary
    local sec_audit="${LOGS_DIR}/security-audit.json"
    local sec_sast="${LOGS_DIR}/sast-findings.json"
    local sec_sca="${LOGS_DIR}/sca-findings.json"

    local sec_has_files=false
    [[ -f "$sec_audit" ]] && sec_has_files=true
    [[ -f "$sec_sast" ]] && sec_has_files=true
    [[ -f "$sec_sca" ]] && sec_has_files=true

    if $sec_has_files; then
        local sec_critical=0 sec_high=0 sec_medium=0 sec_low=0 sec_info=0 sec_tmp
        local c h m l i

        if [[ -f "$sec_audit" ]]; then
            sec_tmp=$(jq -r '(.summary.by_severity // {}) | "\(.critical // 0) \(.high // 0) \(.medium // 0) \(.low // 0) \(.info // 0)"' "$sec_audit" 2>/dev/null) || sec_tmp="0 0 0 0 0"
            read -r c h m l i <<< "$sec_tmp"
            sec_critical=$(( sec_critical + ${c:-0} )); sec_high=$(( sec_high + ${h:-0} ))
            sec_medium=$(( sec_medium + ${m:-0} )); sec_low=$(( sec_low + ${l:-0} )); sec_info=$(( sec_info + ${i:-0} ))
        fi

        if [[ -f "$sec_sast" ]]; then
            sec_tmp=$(jq -r 'group_by(.severity) | map({key: .[0].severity, value: length}) | from_entries | "\(.critical // 0) \(.high // 0) \(.medium // 0) \(.low // 0) \(.info // 0)"' "$sec_sast" 2>/dev/null) || sec_tmp="0 0 0 0 0"
            read -r c h m l i <<< "$sec_tmp"
            sec_critical=$(( sec_critical + ${c:-0} )); sec_high=$(( sec_high + ${h:-0} ))
            sec_medium=$(( sec_medium + ${m:-0} )); sec_low=$(( sec_low + ${l:-0} )); sec_info=$(( sec_info + ${i:-0} ))
        fi

        if [[ -f "$sec_sca" ]]; then
            sec_tmp=$(jq -r 'group_by(.severity) | map({key: .[0].severity, value: length}) | from_entries | "\(.critical // 0) \(.high // 0) \(.medium // 0) \(.low // 0) \(.info // 0)"' "$sec_sca" 2>/dev/null) || sec_tmp="0 0 0 0 0"
            read -r c h m l i <<< "$sec_tmp"
            sec_critical=$(( sec_critical + ${c:-0} )); sec_high=$(( sec_high + ${h:-0} ))
            sec_medium=$(( sec_medium + ${m:-0} )); sec_low=$(( sec_low + ${l:-0} )); sec_info=$(( sec_info + ${i:-0} ))
        fi

        local sec_total=$(( sec_critical + sec_high + sec_medium + sec_low + sec_info ))

        if [[ "$sec_total" -gt 0 ]]; then
            local sec_detail=""
            [[ "$sec_critical" -gt 0 ]] && sec_detail+="${COLOR_ERROR}${sec_critical} critical${RESET}, "
            [[ "$sec_high" -gt 0 ]] && sec_detail+="${COLOR_ERROR}${sec_high} high${RESET}, "
            [[ "$sec_medium" -gt 0 ]] && sec_detail+="${COLOR_WARN}${sec_medium} medium${RESET}, "
            [[ "$sec_low" -gt 0 ]] && sec_detail+="${COLOR_DIM}${sec_low} low${RESET}, "
            [[ "$sec_info" -gt 0 ]] && sec_detail+="${COLOR_DIM}${sec_info} info${RESET}, "
            sec_detail="${sec_detail%, }"
            echo -e "${BOLD}Security:${RESET} ${COLOR_WARN}${SYM_WARN} ${sec_total} findings${RESET} (${sec_detail})"
        else
            echo -e "${BOLD}Security:${RESET} ${COLOR_SUCCESS}${SYM_CHECK} no findings${RESET}"
        fi
    fi

    # Blocked tasks
    local blocked_count
    blocked_count=$(task_count_by_status "blocked")
    if [[ "$blocked_count" -gt 0 ]]; then
        echo ""
        echo -e "${BOLD}Blocked Tasks (need human input):${RESET}"
        for f in "${TASKS_DIR}"/*.json; do
            [[ -f "$f" ]] || continue
            local status
            status=$(jq -r '.status' "$f")
            if [[ "$status" == "blocked" ]]; then
                local id title error
                id=$(jq -r '.id' "$f")
                title=$(jq -r '.title' "$f")
                error=$(jq -r '.error // "No details"' "$f")
                echo -e "  ${COLOR_WARN}${SYM_WARN}${RESET} Task ${id}: ${title}"
                echo -e "    ${COLOR_DIM}${error}${RESET}"
            fi
        done
    fi

    # Timed-out tasks (failed after timeout escalation — need decomposition)
    local has_timeouts=false
    for f in "${TASKS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local tc
        tc=$(jq -r '.timeout_count // 0' "$f")
        if [[ "$tc" -gt 0 ]]; then
            if ! $has_timeouts; then
                echo ""
                echo -e "${BOLD}Timed-Out Tasks (consider decomposing):${RESET}"
                has_timeouts=true
            fi
            local id title model tc_val status
            id=$(jq -r '.id' "$f")
            title=$(jq -r '.title' "$f")
            model=$(jq -r --arg def "$MODEL_SUPPORT" '.agent_model // $def' "$f")
            tc_val=$(jq -r '.timeout_count' "$f")
            status=$(jq -r '.status' "$f")
            echo -e "  ${COLOR_WARN}${SYM_WARN}${RESET} Task ${id}: ${title} ${COLOR_DIM}(${tc_val}x timeout, model: ${model}, status: ${status})${RESET}"
        fi
    done

    # Failure classification breakdown
    local fc_total=0 fc_pipeline=0 fc_complexity=0 fc_unclassified=0
    declare -A fc_breakdown
    for f in "${TASKS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local fc_class fc_sub
        fc_class=$(jq -r '.failure_classification.class // empty' "$f" 2>/dev/null)
        [[ -z "$fc_class" ]] && continue
        fc_sub=$(jq -r '.failure_classification.subclass // "unknown"' "$f" 2>/dev/null)
        ((fc_total++)) || true
        case "$fc_class" in
            pipeline) ((fc_pipeline++)) || true ;;
            complexity) ((fc_complexity++)) || true ;;
            *) ((fc_unclassified++)) || true ;;
        esac
        local fc_key="${fc_class}:${fc_sub}"
        fc_breakdown["$fc_key"]=$(( ${fc_breakdown["$fc_key"]:-0} + 1 ))
    done
    if [[ $fc_total -gt 0 ]]; then
        local fc_ratio=0
        if [[ $fc_total -gt 0 ]]; then
            fc_ratio=$(( fc_pipeline * 100 / fc_total ))
        fi
        echo ""
        echo -e "${BOLD}Failure Classification:${RESET} ${fc_total} classified failures"
        echo -e "  Pipeline: ${COLOR_WARN}${fc_pipeline}${RESET} (${fc_ratio}%)  |  Complexity: ${COLOR_ERROR}${fc_complexity}${RESET}  |  Unclassified: ${fc_unclassified}"
        if [[ ${#fc_breakdown[@]} -gt 0 ]]; then
            echo -e "  ${COLOR_DIM}Breakdown:${RESET}"
            for key in $(echo "${!fc_breakdown[@]}" | tr ' ' '\n' | sort); do
                local count=${fc_breakdown[$key]}
                echo -e "    ${key}: ${count}"
            done
        fi
        if [[ $fc_pipeline -gt $fc_complexity ]]; then
            echo -e "  ${COLOR_WARN}${SYM_WARN}${RESET} Majority pipeline failures — context or decomposition may need adjustment"
        fi
    fi

    # Latest supervisor analysis (show the most recent log if it exists)
    local latest_supervisor
    latest_supervisor=$(ls -t "${LOGS_DIR}"/supervisor-*.json 2>/dev/null | head -1 || true)
    if [[ -n "$latest_supervisor" ]] && [[ -f "$latest_supervisor" ]]; then
        local sup_diagnosis sup_pattern sup_recommendations
        sup_diagnosis=$(jq -r '.diagnosis // empty' "$latest_supervisor" 2>/dev/null)
        sup_pattern=$(jq -r '.pattern_detected.description // empty' "$latest_supervisor" 2>/dev/null)
        sup_recommendations=$(jq -r '[.recommendations // [] | .[]] | length' "$latest_supervisor" 2>/dev/null || echo "0")

        if [[ -n "$sup_diagnosis" ]] || [[ -n "$sup_pattern" ]]; then
            echo ""
            echo -e "${BOLD}Latest Supervisor Analysis:${RESET}"
            if [[ -n "$sup_diagnosis" ]]; then
                echo -e "  ${COLOR_DIM}Diagnosis:${RESET} ${sup_diagnosis}"
            fi
            if [[ -n "$sup_pattern" ]]; then
                local sup_root_cause
                sup_root_cause=$(jq -r '.pattern_detected.root_cause // "Unknown"' "$latest_supervisor" 2>/dev/null)
                echo -e "  ${COLOR_ERROR}Pattern:${RESET} ${sup_pattern}"
                echo -e "  ${COLOR_ERROR}Root cause:${RESET} ${sup_root_cause}"
            fi
            if [[ "$sup_recommendations" -gt 0 ]]; then
                echo -e "  ${COLOR_DIM}Suggestions:${RESET}"
                jq -r '.recommendations[]? | "    • \(.)"' "$latest_supervisor" 2>/dev/null
            fi
            echo -e "  ${COLOR_DIM}Full log: ${latest_supervisor}${RESET}"
        fi
    fi

    echo ""
}
