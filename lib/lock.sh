#!/usr/bin/env bash
# lock.sh — SPEED-level exclusive lock for mutation operations
#
# Uses mkdir as a portable atomic lock (POSIX-guaranteed atomic).
# Stores PID, command name, and timestamp for diagnostics.
# Automatically detects and breaks stale locks from crashed processes.
#
# Requires config.sh and log.sh to be sourced first.

# Default lock location; overridden by feature_activate() in MP mode
SPEED_LOCK="${STATE_DIR}/speed.lock"

# Acquire exclusive lock for a mutation command.
# Args: command_name [max_wait_seconds]
#   max_wait=0 (default) means fail immediately if locked.
# Returns 0 on success, 1 if another command holds the lock.
speed_acquire_lock() {
    local command="$1"
    local max_wait="${2:-0}"
    local waited=0

    mkdir -p "$STATE_DIR"

    while ! mkdir "$SPEED_LOCK" 2>/dev/null; do
        # Check for stale lock (holder process is dead)
        if [[ -f "$SPEED_LOCK/pid" ]]; then
            local lock_pid lock_cmd lock_time
            lock_pid=$(cat "$SPEED_LOCK/pid" 2>/dev/null || echo "")
            lock_cmd=$(cat "$SPEED_LOCK/command" 2>/dev/null || echo "unknown")
            lock_time=$(cat "$SPEED_LOCK/acquired_at" 2>/dev/null || echo "unknown")

            if [[ -n "$lock_pid" ]] && ! kill -0 "$lock_pid" 2>/dev/null; then
                local lock_actor
                lock_actor=$(cat "$SPEED_LOCK/actor" 2>/dev/null || echo "")
                local actor_info=""
                [[ -n "$lock_actor" ]] && actor_info=", actor ${lock_actor}"
                log_warn "Breaking stale lock from '${lock_cmd}' (PID ${lock_pid}${actor_info}, acquired ${lock_time})"
                rm -rf "$SPEED_LOCK"
                continue
            fi

            # Lock is held by a live process
            if [[ $max_wait -eq 0 ]]; then
                local lock_actor
                lock_actor=$(cat "$SPEED_LOCK/actor" 2>/dev/null || echo "")
                local actor_info=""
                [[ -n "$lock_actor" ]] && actor_info=" by ${lock_actor}"
                log_error "Cannot run '${command}': '${lock_cmd}' is already running${actor_info} (PID ${lock_pid}, since ${lock_time})"
                log_error "If the process is stuck, run: speed recover"
                return 1
            fi
        else
            # Lock dir exists but no PID file — broken state, clean up
            rm -rf "$SPEED_LOCK"
            continue
        fi

        if [[ $waited -ge $max_wait ]]; then
            log_error "Timed out waiting for lock after ${max_wait}s"
            return 1
        fi
        sleep 1
        ((waited++)) || true
    done

    # Write lock metadata
    echo $$ > "$SPEED_LOCK/pid"
    echo "$command" > "$SPEED_LOCK/command"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$SPEED_LOCK/acquired_at"
    [[ "${MP_ENABLED:-}" == "true" ]] && actor_get > "$SPEED_LOCK/actor" 2>/dev/null

    # Ensure lock is released on exit, interrupt, or termination
    trap '_speed_cleanup_on_exit' EXIT
    trap '_speed_cleanup_on_signal' INT TERM

    return 0
}

# Release the lock. Safe to call multiple times.
speed_release_lock() {
    if [[ -d "$SPEED_LOCK" ]]; then
        # Only release if we own it
        local lock_pid
        lock_pid=$(cat "$SPEED_LOCK/pid" 2>/dev/null || echo "")
        if [[ "$lock_pid" == "$$" ]]; then
            rm -rf "$SPEED_LOCK"
        fi
    fi
}

# Force-break the lock regardless of owner. Used by cmd_recover.
speed_force_break_lock() {
    if [[ -d "$SPEED_LOCK" ]]; then
        local lock_pid lock_cmd
        lock_pid=$(cat "$SPEED_LOCK/pid" 2>/dev/null || echo "unknown")
        lock_cmd=$(cat "$SPEED_LOCK/command" 2>/dev/null || echo "unknown")
        log_step "Force-breaking lock held by '${lock_cmd}' (PID ${lock_pid})"
        rm -rf "$SPEED_LOCK"
    fi
    if [[ -d "$MAIN_BRANCH_LOCK" ]]; then
        log_step "Force-breaking main-branch lock"
        rm -rf "$MAIN_BRANCH_LOCK"
    fi
}

# ── Main-branch lock ─────────────────────────────────────────
# Separate from the per-feature SPEED lock. Serializes short-lived
# git operations on the shared main branch (checkout + merge).
# Multiple features can run concurrently, but only one merges at a time.

# Main-branch lock: use local/ in MP mode to avoid commit conflicts
if [[ "${MP_ENABLED:-}" == "true" ]]; then
    MAIN_BRANCH_LOCK="${LOCAL_DIR}/main.lock"
else
    MAIN_BRANCH_LOCK="${STATE_DIR}/main.lock"
fi
MAIN_LOCK_MAX_WAIT=30   # seconds to wait before giving up

# Acquire the main-branch lock. Blocks up to MAIN_LOCK_MAX_WAIT seconds.
# Returns 0 on success, 1 on timeout.
main_branch_acquire_lock() {
    local caller="${1:-merge}"
    local waited=0

    mkdir -p "$STATE_DIR"

    while ! mkdir "$MAIN_BRANCH_LOCK" 2>/dev/null; do
        # Check for stale lock
        if [[ -f "$MAIN_BRANCH_LOCK/pid" ]]; then
            local lock_pid
            lock_pid=$(cat "$MAIN_BRANCH_LOCK/pid" 2>/dev/null || echo "")
            if [[ -n "$lock_pid" ]] && ! kill -0 "$lock_pid" 2>/dev/null; then
                rm -rf "$MAIN_BRANCH_LOCK"
                continue
            fi
        else
            rm -rf "$MAIN_BRANCH_LOCK"
            continue
        fi

        if [[ $waited -ge $MAIN_LOCK_MAX_WAIT ]]; then
            log_warn "Timed out waiting for main-branch lock after ${MAIN_LOCK_MAX_WAIT}s"
            return 1
        fi
        sleep 1
        ((waited++)) || true
    done

    echo $$ > "$MAIN_BRANCH_LOCK/pid"
    echo "$caller" > "$MAIN_BRANCH_LOCK/command"
    [[ "${MP_ENABLED:-}" == "true" ]] && actor_get > "$MAIN_BRANCH_LOCK/actor" 2>/dev/null
    return 0
}

# Release the main-branch lock. Safe to call multiple times.
main_branch_release_lock() {
    if [[ -d "$MAIN_BRANCH_LOCK" ]]; then
        local lock_pid
        lock_pid=$(cat "$MAIN_BRANCH_LOCK/pid" 2>/dev/null || echo "")
        if [[ "$lock_pid" == "$$" ]]; then
            rm -rf "$MAIN_BRANCH_LOCK"
        fi
    fi
}

# Internal: cleanup handler for normal exit
_speed_cleanup_on_exit() {
    main_branch_release_lock
    speed_release_lock
}

# Internal: cleanup handler for signals (INT, TERM)
# Sets state to idle before releasing lock.
_speed_cleanup_on_signal() {
    echo "" # newline after ^C
    log_warn "Interrupted — cleaning up..."

    # Update SPEED state to idle
    if [[ -f "$STATE_FILE" ]]; then
        jq '.status = "idle" | .agents = []' "$STATE_FILE" > "${STATE_FILE}.tmp" && \
            mv "${STATE_FILE}.tmp" "$STATE_FILE" 2>/dev/null || true
    fi

    main_branch_release_lock
    speed_release_lock

    # Re-raise the signal so the shell exits with correct status
    trap - INT TERM
    kill -s INT $$ 2>/dev/null || exit 130
}
