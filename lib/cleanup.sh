#!/usr/bin/env bash
# cleanup.sh — Session-level process and temp file cleanup registry
#
# Tracks background PIDs and temp files so SPEED can clean up on
# interrupt (Ctrl+C, SIGTERM) or normal exit. Designed to coexist
# with SPEED's existing cleanup logic — call cleanup_all() from
# the top-level trap handler.
#
# Usage:
#   source cleanup.sh
#   cleanup_register_pid "$pid"
#   cleanup_register_file "/tmp/foo"
#   ...
#   cleanup_unregister_pid "$pid"   # on normal completion
#   cleanup_all                      # from trap handler

# ── Registry ────────────────────────────────────────────────────
_CLEANUP_PIDS=()
_CLEANUP_FILES=()

cleanup_register_pid() {
    _CLEANUP_PIDS+=("$1")
}

cleanup_unregister_pid() {
    local target="$1"
    local new=()
    local pid
    for pid in "${_CLEANUP_PIDS[@]+"${_CLEANUP_PIDS[@]}"}"; do
        [[ "$pid" != "$target" ]] && new+=("$pid")
    done
    _CLEANUP_PIDS=("${new[@]+"${new[@]}"}")
}

cleanup_register_file() {
    _CLEANUP_FILES+=("$1")
}

cleanup_unregister_file() {
    local target="$1"
    local new=()
    local f
    for f in "${_CLEANUP_FILES[@]+"${_CLEANUP_FILES[@]}"}"; do
        [[ "$f" != "$target" ]] && new+=("$f")
    done
    _CLEANUP_FILES=("${new[@]+"${new[@]}"}")
}

# ── Kill and clean ──────────────────────────────────────────────

cleanup_all() {
    # Guard: nothing to do if both registries are empty
    [[ ${#_CLEANUP_PIDS[@]} -eq 0 && ${#_CLEANUP_FILES[@]} -eq 0 ]] && return 0

    # 1. SIGTERM all registered PIDs
    local pid
    for pid in "${_CLEANUP_PIDS[@]+"${_CLEANUP_PIDS[@]}"}"; do
        [[ -z "$pid" ]] && continue
        kill -TERM "$pid" 2>/dev/null || true
    done

    # 2. Brief wait for graceful shutdown
    local waited=0
    local any_alive=true
    while [[ "$any_alive" == "true" ]] && [[ $waited -lt 3 ]]; do
        any_alive=false
        for pid in "${_CLEANUP_PIDS[@]+"${_CLEANUP_PIDS[@]}"}"; do
            [[ -z "$pid" ]] && continue
            if kill -0 "$pid" 2>/dev/null; then
                any_alive=true
            fi
        done
        [[ "$any_alive" == "true" ]] && sleep 1
        waited=$((waited + 1))
    done

    # 3. SIGKILL any still alive
    for pid in "${_CLEANUP_PIDS[@]+"${_CLEANUP_PIDS[@]}"}"; do
        [[ -z "$pid" ]] && continue
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL "$pid" 2>/dev/null || true
        fi
    done

    # 4. Reap zombies
    for pid in "${_CLEANUP_PIDS[@]+"${_CLEANUP_PIDS[@]}"}"; do
        [[ -z "$pid" ]] && continue
        wait "$pid" 2>/dev/null || true
    done

    # 5. Delete temp files
    local f
    for f in "${_CLEANUP_FILES[@]+"${_CLEANUP_FILES[@]}"}"; do
        [[ -z "$f" ]] && continue
        rm -f "$f" 2>/dev/null || true
    done

    _CLEANUP_PIDS=()
    _CLEANUP_FILES=()
}
