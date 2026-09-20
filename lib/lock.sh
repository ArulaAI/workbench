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

# A lock directory exists before its holder has written pid. That window is
# microseconds wide, so a lock still empty after this many minutes belongs to a
# process that died inside it. find -mmin is portable across BSD and GNU.
LOCK_INIT_GRACE_MIN=1

# Internal: take the exclusive right to break "$1", run "$2" to decide, break.
#
# Breaking a lock is two steps (inspect, then remove) and a plain rm -rf between
# them is a race: two waiters both see the same dead holder, both remove, and
# the second one deletes the live lock the first has already re-acquired. The
# guard directory makes exactly one waiter the breaker, and the breaker re-reads
# the lock's state after winning. No new holder can appear in between, because
# mkdir cannot succeed while the lock directory is still there.
#
# Returns 0 if the lock was removed or had already gone, 1 to keep waiting.
_lock_break() (
    local lock="$1" verdict="$2" guard="${1}.breaking" rc=1
    local owner="" stale_owner stale_pid breaker_pid reclaimed=false

    # Remove only a dead breaker's unique marker. Concurrent reapers must not
    # delete another waiter's new guard, even if they observed the same orphan.
    for stale_owner in "$guard"/owner.*; do
        [[ -f "$stale_owner" && ! -L "$stale_owner" ]] || continue
        stale_pid=$(cat "$stale_owner" 2>/dev/null || true)
        if [[ "$stale_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$stale_pid" 2>/dev/null; then
            rm -f "$stale_owner"
            reclaimed=true
        elif [[ -z "$stale_pid" ]] &&
             [[ -n "$(find "$stale_owner" -maxdepth 0 -mmin "+${LOCK_INIT_GRACE_MIN}" 2>/dev/null)" ]]; then
            rm -f "$stale_owner"
            reclaimed=true
        fi
    done
    if $reclaimed; then
        rmdir "$guard" 2>/dev/null || true
    elif [[ -d "$guard" ]] &&
       [[ -n "$(find "$guard" -maxdepth 0 -mmin "+${LOCK_INIT_GRACE_MIN}" 2>/dev/null)" ]]; then
        # Legacy guards and death before the marker was written leave an
        # empty directory. rmdir cannot remove a live breaker's marker.
        rmdir "$guard" 2>/dev/null || true
    fi
    mkdir "$guard" 2>/dev/null || return 1
    # Isolate these traps from the caller's feature/merge cleanup handlers.
    trap '[[ -z "$owner" ]] || rm -f "$owner"; rmdir "$guard" 2>/dev/null || true' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    owner=$(mktemp "${guard}/owner.XXXXXXXX") || return 1
    # $$ is the caller's PID in a bash subshell; PPID from an exec'd child is
    # the breaker's actual PID, including on bash 3.2 without BASHPID.
    breaker_pid=$(exec sh -c 'echo "$PPID"')
    printf '%s\n' "$breaker_pid" > "$owner"
    if [[ ! -d "$lock" ]]; then
        rc=0
    elif "$verdict" "$lock"; then
        rm -rf "$lock"
        rc=0
    fi
    return $rc
)

# Internal: verdict for a lock whose recorded holder was seen dead.
_lock_holder_still_dead() {
    local pid
    pid=$(cat "${1}/pid" 2>/dev/null || echo "")
    # A pid that changed, or that has not been written yet, means someone else
    # already broke this lock and a live process now owns it.
    [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null
}

# Internal: verdict for a lock left empty by a process that died mid-acquire.
_lock_never_initialized() {
    [[ ! -f "${1}/pid" ]] &&
        [[ -n "$(find "$1" -maxdepth 0 -mmin "+${LOCK_INIT_GRACE_MIN}" 2>/dev/null)" ]]
}

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
                if _lock_break "$SPEED_LOCK" _lock_holder_still_dead; then
                    log_warn "Broke stale lock from '${lock_cmd}' (PID ${lock_pid}${actor_info}, acquired ${lock_time})"
                    continue
                fi
                # Another waiter is breaking it, or a live process already owns
                # it again. Fall through and wait rather than remove it blindly.
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
            # Another process may be between mkdir and writing its PID. An
            # empty lock is not proof that its owner crashed, but one that is
            # still empty long afterwards was abandoned inside that window.
            if _lock_break "$SPEED_LOCK" _lock_never_initialized; then
                log_warn "Broke an abandoned lock left uninitialized by a dead process"
                continue
            fi
            if [[ $max_wait -eq 0 ]]; then
                log_error "Cannot run '${command}': lock initialization is in progress (or needs speed recover)"
                return 1
            fi
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
    # A breaker that died mid-break would otherwise leave nobody able to break
    # a stale lock again.
    rm -rf "${SPEED_LOCK}.breaking" "${MAIN_BRANCH_LOCK}.breaking"
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
                if _lock_break "$MAIN_BRANCH_LOCK" _lock_holder_still_dead; then
                    log_warn "Broke stale main-branch lock (PID ${lock_pid})"
                    continue
                fi
            fi
        elif _lock_break "$MAIN_BRANCH_LOCK" _lock_never_initialized; then
            # Removing an empty lock unconditionally let two processes hold this
            # lock at once and run checkout + merge on main concurrently. An
            # empty lock usually means its owner is still writing its pid.
            log_warn "Broke an abandoned main-branch lock"
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
