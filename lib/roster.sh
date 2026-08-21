#!/usr/bin/env bash
# roster.sh — Team roster for multi-player mode
#
# Writes a per-actor JSON file on every command invocation.
# Readers use file timestamps and content to build team awareness.
#
# Requires: actor.sh, multiplayer.sh, config.sh

# Update the current actor's roster entry.
# Called from speed main() on every command when MP is enabled.
roster_heartbeat() {
    [[ "${MP_ENABLED:-}" == "true" ]] || return 0

    local roster_dir
    roster_dir=$(mp_roster_dir)
    mkdir -p "$roster_dir"

    local slug
    slug=$(actor_slug)
    local roster_file="${roster_dir}/${slug}.json"

    local active_feature=""
    active_feature=$(feature_get_active 2>/dev/null || true)

    local active_stage=""
    if [[ -n "$active_feature" ]]; then
        local feat_root="$SHARED_FEATURES_DIR"
        local state_file="${LOCAL_DIR}/features/${active_feature}/state.json"
        if [[ -f "$state_file" ]]; then
            active_stage=$(jq -r '.status // "idle"' "$state_file" 2>/dev/null)
        fi
    fi

    local tmp
    tmp=$(mktemp "${TMPDIR:-/tmp}/_speed_roster_XXXXXX")
    jq -nc \
        --arg name "$(actor_get)" \
        --arg email "$(actor_email_get)" \
        --arg feature "${active_feature:-}" \
        --arg stage "${active_stage:-}" \
        --arg last_seen "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg last_command "${_SPEED_CURRENT_COMMAND:-unknown}" \
        '{name: $name, email: $email, active_feature: $feature, active_stage: $stage, last_seen: $last_seen, last_command: $last_command}' \
        > "$tmp" 2>/dev/null && mv "$tmp" "$roster_file"
}

# List all roster entries, sorted by last_seen descending.
# Filters out entries older than 24 hours.
roster_list() {
    local roster_dir
    roster_dir=$(mp_roster_dir)
    [[ -d "$roster_dir" ]] || return 0

    local cutoff_epoch
    cutoff_epoch=$(( $(date +%s) - 86400 ))

    for f in "${roster_dir}"/*.json; do
        [[ -f "$f" ]] || continue
        local last_seen
        last_seen=$(jq -r '.last_seen // ""' "$f" 2>/dev/null)
        [[ -z "$last_seen" ]] && continue

        # Parse timestamp to epoch
        local entry_epoch
        entry_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$last_seen" +%s 2>/dev/null || \
                      date -d "$last_seen" +%s 2>/dev/null || echo "0")

        if [[ $entry_epoch -ge $cutoff_epoch ]]; then
            cat "$f"
        fi
    done | jq -sc 'sort_by(.last_seen) | reverse'
}

# Format roster as an aligned table for terminal output.
roster_format_table() {
    local entries
    entries=$(roster_list)

    if [[ -z "$entries" ]] || [[ "$entries" == "[]" ]]; then
        echo "No team members active in the last 24 hours."
        return 0
    fi

    # Header
    printf "  ${BOLD}%-20s %-20s %-12s %-20s %-15s${RESET}\n" \
        "ACTOR" "FEATURE" "STAGE" "LAST SEEN" "COMMAND"

    echo "$entries" | jq -r '.[] | "\(.name)\t\(.active_feature // "-")\t\(.active_stage // "-")\t\(.last_seen // "-")\t\(.last_command // "-")"' | \
    while IFS=$'\t' read -r name feature stage seen cmd; do
        # Relative time from last_seen
        local relative=""
        if [[ "$seen" != "-" ]]; then
            local seen_epoch now_epoch
            seen_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$seen" +%s 2>/dev/null || \
                         date -d "$seen" +%s 2>/dev/null || echo "0")
            now_epoch=$(date +%s)
            local age=$(( now_epoch - seen_epoch ))
            if [[ $age -lt 60 ]]; then
                relative="just now"
            elif [[ $age -lt 3600 ]]; then
                relative="$(( age / 60 ))m ago"
            else
                relative="$(( age / 3600 ))h ago"
            fi
        fi

        printf "  %-20s %-20s %-12s %-20s %-15s\n" \
            "$name" "$feature" "$stage" "$relative" "$cmd"
    done
}
