#!/usr/bin/env bash
# define.sh — Read feature findings and the defect portfolio.

cmd_define() {
    local subject="${1:-}"
    if [[ -z "$subject" ]]; then
        log_error "Usage: speed define feature <name> | speed define defects [filters]"
        return 1
    fi

    local -a original_args=("$@")
    local py_bin
    py_bin=$(_context_python)
    PYTHONPATH="${SCRIPT_DIR}" "$py_bin" -m lib.define_cli \
        --project-root "$PROJECT_ROOT" "${original_args[@]}" || return $?

    # A read-only invocation may open an already-running frontend. It never
    # starts the dashboard or edits its PID files.
    if [[ "$subject" == "feature" && -t 1 ]]; then
        local arg no_open=false machine=false feature="${2:-}"
        for arg in "${original_args[@]}"; do
            [[ "$arg" == "--no-open" ]] && no_open=true
            [[ "$arg" == "--json" ]] && machine=true
        done
        local frontend_pid="${DASHBOARD_DIR:-${STATE_DIR}/.dashboard}/frontend.pid"
        if [[ "$no_open" == false && "$machine" == false && -f "$frontend_pid" ]] \
            && kill -0 "$(cat "$frontend_pid")" 2>/dev/null && command -v open >/dev/null 2>&1; then
            open "http://localhost:${DASHBOARD_FRONTEND_PORT:-3000}/define/${feature}/findings" >/dev/null 2>&1 || true
        fi
    fi
}
