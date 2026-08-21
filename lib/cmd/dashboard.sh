#!/usr/bin/env bash
# dashboard.sh — Start/stop/status the SPEED dashboard

DASHBOARD_DIR="${STATE_DIR}/.dashboard"
DASHBOARD_API_PORT="${SPEED_DASHBOARD_PORT:-4440}"
DASHBOARD_FRONTEND_PORT=3000

cmd_dashboard() {
    local subcmd="${1:-help}"
    shift || true

    case "$subcmd" in
        start)  _dashboard_start "$@" ;;
        stop)   _dashboard_stop ;;
        status) _dashboard_status ;;
        ingest) _dashboard_ingest ;;
        help|--help|-h) _dashboard_help ;;
        *)
            log_error "Unknown dashboard subcommand: ${subcmd}"
            _dashboard_help
            exit 1
            ;;
    esac
}

_dashboard_help() {
    echo ""
    echo -e "${BOLD}speed dashboard${RESET} — Launch the SPEED dashboard"
    echo ""
    echo -e "${BOLD}SUBCOMMANDS${RESET}"
    echo -e "    ${COLOR_STEP}start${RESET}   [--port PORT] [--api-only]  Start API + frontend"
    echo -e "    ${COLOR_STEP}stop${RESET}                                Stop all dashboard processes"
    echo -e "    ${COLOR_STEP}status${RESET}                              Show running processes"
    echo -e "    ${COLOR_STEP}ingest${RESET}                              Run backfill without starting server"
    echo ""
}

_dashboard_start() {
    local port="$DASHBOARD_API_PORT"
    local api_only=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --port)     port="$2"; shift 2 ;;
            --api-only) api_only=true; shift ;;
            *) shift ;;
        esac
    done

    mkdir -p "$DASHBOARD_DIR"

    # Check if already running
    if _dashboard_api_alive; then
        log_warn "Dashboard API already running (PID $(cat "$DASHBOARD_DIR/api.pid"))"
        return 0
    fi

    local py_bin
    py_bin=$(_context_python)

    # Check Python dependencies
    if ! "$py_bin" -c "import fastapi, strawberry, uvicorn, watchdog" 2>/dev/null; then
        log_error "Missing Python dependencies. Install with:"
        echo "  $py_bin -m pip install 'fastapi>=0.115,<1.0' 'strawberry-graphql[fastapi]>=0.260' 'uvicorn[standard]>=0.34' 'watchdog>=6.0'"
        exit "$EXIT_CONFIG_ERROR"
    fi

    log_step "Starting SPEED Dashboard API on port ${port}..."

    # Start the FastAPI backend
    PYTHONPATH="${SPEED_DIR}" "$py_bin" -m dashboard.backend \
        --port "$port" \
        --project-root "$PROJECT_ROOT" \
        --log-level INFO &
    local api_pid=$!
    echo "$api_pid" > "$DASHBOARD_DIR/api.pid"

    # Wait for healthcheck
    local attempts=0
    while [[ $attempts -lt 30 ]]; do
        if curl -sf "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
            break
        fi
        sleep 0.5
        attempts=$((attempts + 1))
    done

    if [[ $attempts -ge 30 ]]; then
        log_error "Dashboard API failed to start within 15 seconds"
        kill "$api_pid" 2>/dev/null
        rm -f "$DASHBOARD_DIR/api.pid"
        exit 1
    fi

    log_success "Dashboard API running at http://127.0.0.1:${port}/graphql"

    if [[ "$api_only" == true ]]; then
        return 0
    fi

    # Start Next.js frontend (if node/npm available)
    local frontend_dir="${SPEED_DIR}/dashboard/frontend"
    if [[ -d "$frontend_dir" ]] && command -v npm &>/dev/null; then
        if [[ ! -d "$frontend_dir/node_modules" ]]; then
            log_step "Installing frontend dependencies..."
            (cd "$frontend_dir" && npm install --silent) || {
                log_warn "Frontend npm install failed. API is still running."
                return 0
            }
        fi

        log_step "Starting frontend dev server..."
        NEXT_PUBLIC_GRAPHQL_URL="http://127.0.0.1:${port}/graphql" \
            NEXT_PUBLIC_WS_URL="ws://127.0.0.1:${port}/graphql" \
            npm --prefix "$frontend_dir" run dev -- --port "$DASHBOARD_FRONTEND_PORT" &
        local fe_pid=$!
        echo "$fe_pid" > "$DASHBOARD_DIR/frontend.pid"
        sleep 2
        log_success "Frontend running at http://localhost:${DASHBOARD_FRONTEND_PORT}"
    else
        log_warn "Frontend not available (missing $frontend_dir or npm). API-only mode."
    fi

    echo ""
    echo -e "  ${BOLD}GraphiQL:${RESET}   http://127.0.0.1:${port}/graphql"
    [[ "$api_only" != true ]] && echo -e "  ${BOLD}Dashboard:${RESET}  http://localhost:${DASHBOARD_FRONTEND_PORT}"
    echo ""
}

_dashboard_stop() {
    local stopped=false

    for pidfile in "$DASHBOARD_DIR"/*.pid; do
        [[ -f "$pidfile" ]] || continue
        local pid
        pid=$(cat "$pidfile")
        local name
        name=$(basename "$pidfile" .pid)

        if kill -0 "$pid" 2>/dev/null; then
            log_step "Stopping ${name} (PID ${pid})..."
            kill "$pid" 2>/dev/null

            # Wait up to 5 seconds for graceful shutdown
            local wait=0
            while kill -0 "$pid" 2>/dev/null && [[ $wait -lt 5 ]]; do
                sleep 1
                wait=$((wait + 1))
            done

            # Force kill if still alive
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid" 2>/dev/null
            fi
            stopped=true
        fi
        rm -f "$pidfile"
    done

    # Kill any orphaned processes on dashboard ports
    for port in "$DASHBOARD_API_PORT" "$DASHBOARD_FRONTEND_PORT"; do
        local orphan_pids
        orphan_pids=$(lsof -ti:"$port" 2>/dev/null || true)
        if [[ -n "$orphan_pids" ]]; then
            log_step "Killing orphaned process on port ${port}..."
            echo "$orphan_pids" | xargs kill -9 2>/dev/null || true
            stopped=true
        fi
    done

    if [[ "$stopped" == true ]]; then
        log_success "Dashboard stopped"
    else
        log_dim "No dashboard processes found"
    fi
}

_dashboard_status() {
    local any_running=false

    for pidfile in "$DASHBOARD_DIR"/*.pid; do
        [[ -f "$pidfile" ]] || continue
        local pid
        pid=$(cat "$pidfile")
        local name
        name=$(basename "$pidfile" .pid)

        if kill -0 "$pid" 2>/dev/null; then
            echo -e "  ${COLOR_DONE}●${RESET} ${name}: running (PID ${pid})"
            any_running=true
        else
            echo -e "  ${COLOR_ERROR}●${RESET} ${name}: dead (stale PID ${pid})"
            rm -f "$pidfile"
        fi
    done

    if [[ "$any_running" == false ]]; then
        echo -e "  ${COLOR_DIM}No dashboard processes running${RESET}"
    fi
}

_dashboard_ingest() {
    local py_bin
    py_bin=$(_context_python)

    log_step "Running backfill ingestion..."
    PYTHONPATH="${SPEED_DIR}" "$py_bin" -c "
import sys
sys.path.insert(0, '${SPEED_DIR}')
from dashboard.backend.db import connect, migrate
from dashboard.backend.ingest import register_project, backfill
conn = connect('${PROJECT_ROOT}')
migrate(conn)
register_project(conn, '${PROJECT_ROOT}')
count = backfill(conn, '${PROJECT_ROOT}')
print(f'Ingested {count} files')
conn.close()
"
}

_dashboard_api_alive() {
    local pidfile="$DASHBOARD_DIR/api.pid"
    [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}
