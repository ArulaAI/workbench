#!/usr/bin/env bash
# define.sh — Read feature findings and the defect portfolio.

_define_open_url() {
    local url="$1"
    case "$(uname -s 2>/dev/null || true)" in
        Darwin*)
            command -v open >/dev/null 2>&1 || return 1
            open "$url" >/dev/null 2>&1
            ;;
        MINGW*|MSYS*|CYGWIN*)
            command -v cmd.exe >/dev/null 2>&1 || return 1
            MSYS2_ARG_CONV_EXCL='*' cmd.exe /c start "" "$url" >/dev/null 2>&1
            ;;
        *)
            command -v xdg-open >/dev/null 2>&1 || return 1
            xdg-open "$url" >/dev/null 2>&1
            ;;
    esac
}

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
            && kill -0 "$(cat "$frontend_pid")" 2>/dev/null; then
            _define_open_url "http://localhost:${DASHBOARD_FRONTEND_PORT:-3000}/define/${feature}/findings" || true
        fi
    fi
}
