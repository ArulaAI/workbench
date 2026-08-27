#!/usr/bin/env bash
# skills.sh — project and inspect the SPEED canonical skill catalog.
#
# Thin wrapper: resolve the interpreter and catalog version, then delegate to the
# `skills` Python package. `lib/` is not a package, so `skills` is imported with
# lib/ on PYTHONPATH.

_skills_python() {
    if [[ -n "${SPEED_PYTHON:-}" ]]; then
        echo "$SPEED_PYTHON"
    elif [[ -x "${SPEED_DIR}/.venv/bin/python3" ]]; then
        echo "${SPEED_DIR}/.venv/bin/python3"
    elif [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
        echo "${PROJECT_ROOT}/.venv/bin/python3"
    else
        echo "python3"
    fi
}

_skills_catalog_version() {
    local v=""
    if command -v jq &>/dev/null; then
        v=$(jq -r '.version // empty' "${SPEED_HOME:-$HOME/.speed}/receipt.json" 2>/dev/null)
    fi
    [[ -z "$v" ]] && v="dev"
    echo "$v"
}

# Print a one-line temporary-alias notice to stderr when a command is invoked
# via `speed` rather than the canonical `workbench` namespace. The `workbench`
# dispatcher sets WORKBENCH_NS=1, which suppresses this.
_speed_alias_notice() {
    [[ -n "${WORKBENCH_NS:-}" ]] && return 0
    echo "note: 'speed $1' is a temporary alias for the canonical 'workbench $1'" >&2
}

cmd_skills() {
    local sub="${1:-status}"
    [[ $# -gt 0 ]] && shift

    case "$sub" in
        sync|status|doctor) ;;
        *)
            log_error "Unknown skills subcommand: ${sub} (expected: sync | status | doctor)"
            return 1
            ;;
    esac

    if [[ "${JSON_OUTPUT:-false}" == "true" ]]; then
        set -- "$@" --json
    fi

    _speed_alias_notice skills
    PYTHONPATH="${SPEED_DIR}/lib" "$(_skills_python)" -m skills "$sub" \
        --project-root "${PROJECT_ROOT}" \
        --skills-dir "${SPEED_DIR}/skills" \
        --catalog-version "$(_skills_catalog_version)" \
        "$@"
}
