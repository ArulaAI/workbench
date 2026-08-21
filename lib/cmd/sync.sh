#!/usr/bin/env bash
# sync.sh — Background sync daemon for multi-player mode
#
# Watches .speed/shared/ for changes, auto-commits and pushes events/roster.
# Pulls remote changes on a configurable interval.
# Designed for 3-8 person teams where manual git push/pull is friction.
#
# Usage: speed sync start [--interval N]
#        speed sync stop
#        speed sync status
#
# Requires: multiplayer.sh, config.sh

SYNC_PID_FILE="${STATE_DIR}/local/sync.pid"
SYNC_LOG_FILE="${STATE_DIR}/local/sync.log"
SYNC_DEFAULT_INTERVAL="${TOML_MULTIPLAYER_SYNC_INTERVAL:-30}"

# ── Start the sync daemon ─────────────────────────────────────
_sync_daemon() {
    local interval="$1"

    echo $$ > "$SYNC_PID_FILE"
    log_info "Sync daemon started (PID $$, interval ${interval}s)" >> "$SYNC_LOG_FILE" 2>&1

    while true; do
        # Pull remote changes
        _git fetch origin 2>/dev/null || true
        local current_branch
        current_branch=$(_git rev-parse --abbrev-ref HEAD 2>/dev/null)

        if [[ -n "$current_branch" ]]; then
            # Merge remote shared state (fast-forward only to avoid conflicts)
            _git merge --ff-only "origin/${current_branch}" 2>/dev/null || true
        fi

        # Check for local shared changes to push
        local shared_changes
        shared_changes=$(_git status --porcelain -- .speed/shared/ 2>/dev/null)

        if [[ -n "$shared_changes" ]]; then
            local ts
            ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
            local actor
            actor=$(actor_get 2>/dev/null || echo "sync")

            _git add .speed/shared/ 2>/dev/null
            _git commit -m "speed-sync: ${actor} at ${ts}" --no-verify 2>/dev/null || true
            _git push origin "${current_branch}" 2>/dev/null || {
                echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) push failed, will retry" >> "$SYNC_LOG_FILE"
            }
        fi

        sleep "$interval"
    done
}

# ── Public commands ───────────────────────────────────────────

cmd_sync() {
    local subcmd="${1:-status}"
    shift || true

    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Sync requires multi-player mode. Run 'speed mp-init' first."
        exit 1
    fi

    case "$subcmd" in
        start)
            local interval="$SYNC_DEFAULT_INTERVAL"
            while [[ $# -gt 0 ]]; do
                case "$1" in
                    --interval) interval="$2"; shift 2 ;;
                    *) log_error "Unknown option: $1"; exit 1 ;;
                esac
            done

            # Check if already running
            if [[ -f "$SYNC_PID_FILE" ]]; then
                local existing_pid
                existing_pid=$(cat "$SYNC_PID_FILE")
                if kill -0 "$existing_pid" 2>/dev/null; then
                    log_info "Sync daemon already running (PID ${existing_pid})"
                    return 0
                fi
                rm -f "$SYNC_PID_FILE"
            fi

            mkdir -p "$(dirname "$SYNC_PID_FILE")"
            > "$SYNC_LOG_FILE"

            # Fork daemon to background
            _sync_daemon "$interval" >> "$SYNC_LOG_FILE" 2>&1 &
            disown

            log_success "Sync daemon started (PID $!, interval ${interval}s)"
            log_info "Log: ${SYNC_LOG_FILE}"
            ;;

        stop)
            if [[ ! -f "$SYNC_PID_FILE" ]]; then
                log_info "No sync daemon running."
                return 0
            fi

            local pid
            pid=$(cat "$SYNC_PID_FILE")
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null
                log_success "Sync daemon stopped (PID ${pid})"
            else
                log_info "Sync daemon not running (stale PID file)"
            fi
            rm -f "$SYNC_PID_FILE"
            ;;

        status)
            if [[ -f "$SYNC_PID_FILE" ]]; then
                local pid
                pid=$(cat "$SYNC_PID_FILE")
                if kill -0 "$pid" 2>/dev/null; then
                    log_info "Sync daemon running (PID ${pid})"
                    if [[ -f "$SYNC_LOG_FILE" ]]; then
                        echo -e "  ${COLOR_DIM}Last 5 log entries:${RESET}"
                        tail -5 "$SYNC_LOG_FILE" | while IFS= read -r line; do
                            echo "    $line"
                        done
                    fi
                else
                    log_warn "Sync daemon not running (stale PID ${pid})"
                    rm -f "$SYNC_PID_FILE"
                fi
            else
                log_info "No sync daemon configured. Start with: ${COLOR_STEP}speed sync start${RESET}"
            fi
            ;;

        *)
            log_error "Usage: speed sync <start|stop|status>"
            exit 1
            ;;
    esac
}
