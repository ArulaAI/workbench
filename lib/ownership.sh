#!/usr/bin/env bash
# ownership.sh — Feature ownership for multi-player mode
#
# One owner per feature. Ownership is derived from the event log:
# the latest feature.claimed / feature.released event determines the owner.
# Stale claims (no activity within the configurable window) are treated as released.
#
# Requires: actor.sh, events.sh, multiplayer.sh, config.sh

# Stale window in seconds (default 1 hour, configurable via speed.toml)
OWNERSHIP_STALE_WINDOW="${TOML_MULTIPLAYER_STALE_WINDOW:-3600}"

# Check ownership of a feature.
# Returns: 0 = owned by current actor, 1 = owned by someone else, 2 = unclaimed
# Sets OWNERSHIP_OWNER to the current owner name (or empty).
ownership_check() {
    local feature="$1"
    OWNERSHIP_OWNER=""
    OWNERSHIP_OWNER_EMAIL=""

    [[ "${MP_ENABLED:-}" == "true" ]] || return 0  # single-player: always owned

    local events_dir
    events_dir=$(mp_events_dir)
    [[ -d "$events_dir" ]] || return 2  # no events = unclaimed

    # Find the latest claim/release event for this feature
    local latest_claim="" latest_release="" latest_claim_actor="" latest_claim_email="" latest_claim_ts=""

    for f in "${events_dir}"/*_feature-claimed_"${feature}".jsonl "${events_dir}"/*_feature-released_"${feature}".jsonl; do
        [[ -f "$f" ]] || continue
        local etype actor actor_email ts
        etype=$(jq -r '.type // ""' "$f" 2>/dev/null)
        actor=$(jq -r '.actor // ""' "$f" 2>/dev/null)
        actor_email=$(jq -r '.actor_email // ""' "$f" 2>/dev/null)
        ts=$(jq -r '.timestamp // ""' "$f" 2>/dev/null)

        if [[ "$etype" == "feature.claimed" ]]; then
            if [[ -z "$latest_claim" ]] || [[ "$ts" > "$latest_claim_ts" ]]; then
                latest_claim="$f"
                latest_claim_actor="$actor"
                latest_claim_email="$actor_email"
                latest_claim_ts="$ts"
            fi
        elif [[ "$etype" == "feature.released" ]]; then
            if [[ -z "$latest_release" ]] || [[ "$ts" > "$latest_release" ]]; then
                latest_release="$ts"
            fi
        fi
    done

    # No claim events at all
    if [[ -z "$latest_claim" ]]; then
        return 2
    fi

    # Release happened after the latest claim
    if [[ -n "$latest_release" ]] && [[ "$latest_release" > "$latest_claim_ts" ]]; then
        return 2
    fi

    # Check staleness
    local now_epoch claim_epoch
    now_epoch=$(date +%s)
    # Parse ISO8601 timestamp to epoch (portable across macOS/Linux)
    claim_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$latest_claim_ts" +%s 2>/dev/null || \
                  date -d "$latest_claim_ts" +%s 2>/dev/null || echo "0")
    local age=$(( now_epoch - claim_epoch ))
    if [[ $age -gt $OWNERSHIP_STALE_WINDOW ]]; then
        return 2  # stale claim treated as released
    fi

    OWNERSHIP_OWNER="$latest_claim_actor"
    OWNERSHIP_OWNER_EMAIL="$latest_claim_email"

    # Email-first comparison with name fallback for old events
    local me_email
    me_email=$(actor_email_get)

    if [[ -n "$OWNERSHIP_OWNER_EMAIL" ]] && [[ -n "$me_email" ]]; then
        if [[ "$OWNERSHIP_OWNER_EMAIL" == "$me_email" ]]; then
            return 0
        fi
        return 1
    fi

    # Fallback: old event has no actor_email, compare on name
    local me
    me=$(actor_get)
    if [[ "$OWNERSHIP_OWNER" == "$me" ]]; then
        return 0
    fi

    return 1
}

# Require ownership of a feature. Exits with error if not owned.
ownership_require() {
    local feature="$1"
    local rc=0
    ownership_check "$feature" || rc=$?

    case $rc in
        0) return 0 ;;  # owned by me
        1)
            log_error "Feature '${feature}' is claimed by ${OWNERSHIP_OWNER}"
            log_error "Wait for them to release it, or use 'speed release ${feature}' if they're done"
            exit 1
            ;;
        2)
            log_error "Feature '${feature}' is unclaimed"
            log_error "Run 'speed claim ${feature}' first"
            exit 1
            ;;
    esac
}

# Return the current owner of a feature (or empty string).
ownership_current_owner() {
    local feature="$1"
    ownership_check "$feature" >/dev/null 2>&1 || true
    echo "${OWNERSHIP_OWNER:-}"
}
