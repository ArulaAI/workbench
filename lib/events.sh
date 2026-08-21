#!/usr/bin/env bash
# events.sh — Append-only event log for multi-player mode
#
# Each state mutation emits a JSONL event file under shared/events/.
# File naming: {ISO8601}_{actor_slug}_{event-type}_{feature}.jsonl
# Unique filenames ensure git merges are conflict-free.
#
# Requires: actor.sh, multiplayer.sh, config.sh

# Emit an event to the shared event log.
# Args: event_type feature data_json
# Example: event_emit "task.completed" "auth" '{"id":"3"}'
event_emit() {
    local event_type="$1"
    local feature="${2:-unknown}"
    local data_json="${3:-"{}"}"

    [[ "${MP_ENABLED:-}" == "true" ]] || return 0

    local events_dir
    events_dir=$(mp_events_dir)
    mkdir -p "$events_dir"

    local ts
    ts=$(date -u +%Y%m%dT%H%M%S%3NZ 2>/dev/null || date -u +%Y%m%dT%H%M%SZ)
    local slug
    slug=$(actor_slug)
    local safe_type
    safe_type=$(echo "$event_type" | tr '.' '-')

    local filename="${ts}_${slug}_${safe_type}_${feature}.jsonl"
    local tmp
    tmp=$(mktemp "${TMPDIR:-/tmp}/_speed_event_XXXXXX")

    jq -nc \
        --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg type "$event_type" \
        --arg feature "$feature" \
        --arg actor "$(actor_get)" \
        --arg actor_email "$(actor_email_get)" \
        --argjson data "$data_json" \
        '{timestamp: $ts, type: $type, feature: $feature, actor: $actor, actor_email: $actor_email, data: $data}' \
        > "$tmp" 2>/dev/null

    mv "$tmp" "${events_dir}/${filename}"
}

# List events, optionally filtered by feature and/or type.
# Args: [feature] [event_type] [since_ts]
# Outputs: sorted JSONL lines to stdout.
event_list() {
    local feature="${1:-}"
    local event_type="${2:-}"
    local since_ts="${3:-}"

    local events_dir
    events_dir=$(mp_events_dir)
    [[ -d "$events_dir" ]] || return 0

    local pattern="*"
    if [[ -n "$feature" ]]; then
        pattern="*_${feature}.jsonl"
    fi

    # Pre-filter by filename, then content-filter
    for f in "${events_dir}"/${pattern}; do
        [[ -f "$f" ]] || continue

        # Type filter via filename
        if [[ -n "$event_type" ]]; then
            local safe_type
            safe_type=$(echo "$event_type" | tr '.' '-')
            case "$f" in
                *_${safe_type}_*) ;;
                *) continue ;;
            esac
        fi

        cat "$f"
    done | if [[ -n "$since_ts" ]]; then
        jq -c --arg since "$since_ts" 'select(.timestamp >= $since)'
    else
        cat
    fi | sort -t'"' -k4
}

# Replay events for a feature to reconstruct task state.
# Args: feature
# Outputs: reconstructed state as JSON to stdout.
event_replay() {
    local feature="$1"

    local events_dir
    events_dir=$(mp_events_dir)
    [[ -d "$events_dir" ]] || { echo "{}"; return 0; }

    # Collect all events for this feature, sorted by filename (chronological)
    local events=""
    for f in "${events_dir}"/*_"${feature}".jsonl; do
        [[ -f "$f" ]] || continue
        events+=$(cat "$f")$'\n'
    done

    [[ -z "$events" ]] && { echo "{}"; return 0; }

    # Replay via Python for complex state reconstruction
    echo "$events" | PYTHONPATH="${SPEED_DIR:-$SCRIPT_DIR}" python3 -c "
import sys, json

tasks = {}
feature_state = {'status': 'idle', 'owner': None}

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        continue

    etype = ev.get('type', '')
    data = ev.get('data', {})

    if etype == 'feature.claimed':
        feature_state['owner'] = ev.get('actor')
        feature_state['status'] = 'claimed'
    elif etype == 'feature.released':
        feature_state['owner'] = None
        feature_state['status'] = 'idle'
    elif etype == 'feature.planned':
        feature_state['status'] = 'planned'
        feature_state['task_count'] = data.get('task_count', 0)
    elif etype == 'task.created':
        tid = data.get('id', '')
        tasks[tid] = {'id': tid, 'title': data.get('title', ''), 'status': 'pending'}
    elif etype == 'task.started':
        tid = data.get('id', '')
        if tid in tasks:
            tasks[tid]['status'] = 'running'
    elif etype == 'task.completed':
        tid = data.get('id', '')
        if tid in tasks:
            tasks[tid]['status'] = 'done'
    elif etype == 'task.failed':
        tid = data.get('id', '')
        if tid in tasks:
            tasks[tid]['status'] = 'failed'
            tasks[tid]['error'] = data.get('error', '')
    elif etype == 'task.blocked':
        tid = data.get('id', '')
        if tid in tasks:
            tasks[tid]['status'] = 'blocked'
    elif etype == 'task.reset':
        tid = data.get('id', '')
        if tid in tasks:
            tasks[tid]['status'] = 'pending'

result = {'feature': feature_state, 'tasks': tasks}
json.dump(result, sys.stdout, indent=2)
" 2>/dev/null
}

# Replay events for all features.
# Outputs: JSON object keyed by feature name.
event_replay_all() {
    local events_dir
    events_dir=$(mp_events_dir)
    [[ -d "$events_dir" ]] || { echo "{}"; return 0; }

    # Extract unique feature names from event filenames
    local features=""
    for f in "${events_dir}"/*.jsonl; do
        [[ -f "$f" ]] || continue
        local base
        base=$(basename "$f" .jsonl)
        # Feature name is the last segment after the last underscore
        local feat
        feat=${base##*_}
        features+="${feat}"$'\n'
    done

    features=$(echo "$features" | sort -u | sed '/^$/d')
    [[ -z "$features" ]] && { echo "{}"; return 0; }

    echo "{"
    local first=true
    while IFS= read -r feat; do
        [[ -z "$feat" ]] && continue
        if $first; then first=false; else echo ","; fi
        printf '  "%s": ' "$feat"
        event_replay "$feat"
    done <<< "$features"
    echo ""
    echo "}"
}

# Prune old events into a compressed archive file per feature.
# Events older than $1 days are moved into {feature}-archive.jsonl.
# Args: [max_age_days]
event_prune() {
    local max_age_days="${1:-30}"

    local events_dir
    events_dir=$(mp_events_dir)
    [[ -d "$events_dir" ]] || return 0

    local cutoff_epoch
    cutoff_epoch=$(( $(date +%s) - (max_age_days * 86400) ))
    local pruned=0

    for f in "${events_dir}"/*.jsonl; do
        [[ -f "$f" ]] || continue
        local base
        base=$(basename "$f")

        # Skip archive files
        case "$base" in *-archive.jsonl) continue ;; esac

        # Extract timestamp from filename (first segment before _)
        local file_ts
        file_ts=$(echo "$base" | cut -d'_' -f1)
        # Normalize: strip sub-second digits (e.g. 20260326T050919302Z → 20260326T050919Z)
        local clean_ts
        clean_ts=$(echo "$file_ts" | sed 's/^\([0-9]\{8\}T[0-9]\{6\}\).*$/\1Z/')
        local file_epoch
        file_epoch=$(date -j -f "%Y%m%dT%H%M%SZ" "$clean_ts" +%s 2>/dev/null || \
                     date -d "${clean_ts:0:4}-${clean_ts:4:2}-${clean_ts:6:2}T${clean_ts:9:2}:${clean_ts:11:2}:${clean_ts:13:2}Z" +%s 2>/dev/null || \
                     echo "0")

        if [[ $file_epoch -gt 0 ]] && [[ $file_epoch -lt $cutoff_epoch ]]; then
            # Extract feature name (last segment before .jsonl)
            local feat
            feat=${base%.jsonl}
            feat=${feat##*_}

            # Append to archive
            cat "$f" >> "${events_dir}/${feat}-archive.jsonl"
            rm "$f"
            ((pruned++)) || true
        fi
    done

    if [[ $pruned -gt 0 ]]; then
        log_step "Pruned ${pruned} event(s) older than ${max_age_days} days into archive files"
    fi
}
