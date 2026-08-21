#!/usr/bin/env bash
# rebuild.sh — Rebuild materialized state from the event log
#
# Replays all events and compares against current task files.
# Dry-run by default; pass --apply to overwrite diverged state.

cmd_rebuild_state() {
    local apply=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --apply) apply=true; shift ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "rebuild-state requires multi-player mode. Run 'speed mp-init' first."
        exit 1
    fi

    log_header "Rebuild State from Event Log"

    local reconstructed
    reconstructed=$(event_replay_all)

    if [[ "$reconstructed" == "{}" ]]; then
        log_info "No events found. Nothing to rebuild."
        return 0
    fi

    # Compare reconstructed state against materialized task files
    local features
    features=$(echo "$reconstructed" | jq -r 'keys[]' 2>/dev/null)

    local diverged=0
    local matched=0

    while IFS= read -r feat; do
        [[ -z "$feat" ]] && continue

        local feat_tasks_dir="${SHARED_FEATURES_DIR}/${feat}/tasks"
        local replay_tasks
        replay_tasks=$(echo "$reconstructed" | jq -c ".\"${feat}\".tasks // {}" 2>/dev/null)

        # Check each replayed task against materialized file
        local task_ids
        task_ids=$(echo "$replay_tasks" | jq -r 'keys[]' 2>/dev/null)
        while IFS= read -r tid; do
            [[ -z "$tid" ]] && continue
            local replay_status
            replay_status=$(echo "$replay_tasks" | jq -r ".\"${tid}\".status // \"unknown\"" 2>/dev/null)

            local task_file="${feat_tasks_dir}/${tid}.json"
            if [[ -f "$task_file" ]]; then
                local current_status
                current_status=$(jq -r '.status // "unknown"' "$task_file" 2>/dev/null)
                if [[ "$current_status" == "$replay_status" ]]; then
                    ((matched++)) || true
                else
                    ((diverged++)) || true
                    if [[ "$apply" == "true" ]]; then
                        log_step "Task ${feat}/${tid}: ${current_status} → ${replay_status} (applying)"
                        local tmp; tmp=$(mktemp)
                        jq --arg s "$replay_status" '.status = $s' "$task_file" > "$tmp" && mv "$tmp" "$task_file"
                    else
                        log_warn "Task ${feat}/${tid}: materialized=${current_status} replayed=${replay_status}"
                    fi
                fi
            else
                ((diverged++)) || true
                log_warn "Task ${feat}/${tid}: exists in events but no task file"
            fi
        done <<< "$task_ids"

    done <<< "$features"

    echo ""
    if [[ $diverged -eq 0 ]]; then
        log_success "State matches: ${matched} task(s) verified, 0 diverged"
    else
        if [[ "$apply" == "true" ]]; then
            log_success "Rebuilt: ${diverged} task(s) corrected, ${matched} already matched"
        else
            log_warn "${diverged} task(s) diverged, ${matched} matched"
            log_info "Run with --apply to overwrite materialized state"
        fi
    fi
}
