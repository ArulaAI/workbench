#!/usr/bin/env bash
# serve.sh — Lightweight HTTP server for multi-player real-time visibility
#
# Serves roster, events, and team state as JSON REST endpoints.
# Provides claim arbitration (prevents race on simultaneous claims).
# Optional WebSocket for real-time event push.
#
# Usage: speed serve [--port PORT]
#        speed serve stop
#
# Requires: multiplayer.sh, python3

SERVE_PID_FILE="${STATE_DIR}/local/serve.pid"
SERVE_LOG_FILE="${STATE_DIR}/local/serve.log"
SERVE_DEFAULT_PORT="${TOML_MULTIPLAYER_SERVE_PORT:-4450}"

cmd_serve() {
    local subcmd="${1:-start}"
    shift || true

    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Serve requires multi-player mode. Run 'speed mp-init' first."
        exit 1
    fi

    case "$subcmd" in
        start)
            local port="$SERVE_DEFAULT_PORT"
            while [[ $# -gt 0 ]]; do
                case "$1" in
                    --port) port="$2"; shift 2 ;;
                    *) log_error "Unknown option: $1"; exit 1 ;;
                esac
            done

            # Check if already running
            if [[ -f "$SERVE_PID_FILE" ]]; then
                local existing_pid
                existing_pid=$(cat "$SERVE_PID_FILE")
                if kill -0 "$existing_pid" 2>/dev/null; then
                    log_info "Server already running (PID ${existing_pid}, port ${port})"
                    return 0
                fi
                rm -f "$SERVE_PID_FILE"
            fi

            mkdir -p "$(dirname "$SERVE_PID_FILE")"
            > "$SERVE_LOG_FILE"

            log_step "Starting multi-player server on port ${port}..."

            # Launch Python server in background
            SPEED_SERVE_PORT="$port" \
            SPEED_STATE_DIR="$STATE_DIR" \
            SPEED_SHARED_DIR="$(mp_shared_dir)" \
            SPEED_LOCAL_DIR="$(mp_local_dir)" \
            SPEED_EVENTS_DIR="$(mp_events_dir)" \
            SPEED_ROSTER_DIR="$(mp_roster_dir)" \
            SPEED_PROJECT_ROOT="$PROJECT_ROOT" \
            PYTHONPATH="${SPEED_DIR:-$SCRIPT_DIR}" \
                $(_context_python) "${SPEED_DIR:-$SCRIPT_DIR}/lib/serve/server.py" \
                >> "$SERVE_LOG_FILE" 2>&1 &

            local server_pid=$!
            echo "$server_pid" > "$SERVE_PID_FILE"
            disown

            # Wait briefly and check it started
            sleep 1
            if kill -0 "$server_pid" 2>/dev/null; then
                log_success "Server started (PID ${server_pid}, port ${port})"
                log_info "Endpoints:"
                echo -e "  GET  /api/roster    — team roster"
                echo -e "  GET  /api/events    — event stream"
                echo -e "  GET  /api/features  — active features"
                echo -e "  POST /api/claim     — arbitrated claim"
                echo -e "  WS   /ws/events     — real-time event push"
            else
                log_error "Server failed to start. Check ${SERVE_LOG_FILE}"
                rm -f "$SERVE_PID_FILE"
                return 1
            fi
            ;;

        stop)
            if [[ ! -f "$SERVE_PID_FILE" ]]; then
                log_info "No server running."
                return 0
            fi
            local pid
            pid=$(cat "$SERVE_PID_FILE")
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null
                sleep 1
                kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
                log_success "Server stopped (PID ${pid})"
            else
                log_info "Server not running (stale PID)"
            fi
            rm -f "$SERVE_PID_FILE"
            ;;

        status)
            if [[ -f "$SERVE_PID_FILE" ]]; then
                local pid
                pid=$(cat "$SERVE_PID_FILE")
                if kill -0 "$pid" 2>/dev/null; then
                    log_info "Server running (PID ${pid})"
                else
                    log_warn "Server not running (stale PID ${pid})"
                    rm -f "$SERVE_PID_FILE"
                fi
            else
                log_info "No server running."
            fi
            ;;

        *)
            log_error "Usage: speed serve [start|stop|status]"
            exit 1
            ;;
    esac
}
