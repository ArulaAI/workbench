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

cmd_skills() {
    local sub="${1:-status}"
    [[ $# -gt 0 ]] && shift

    case "$sub" in
        sync|status) ;;
        doctor)
            # Phase 2 delivers a dedicated doctor; alias to status for now so the
            # verb exists without overpromising a repair engine.
            sub="status"
            ;;
        *)
            log_error "Unknown skills subcommand: ${sub} (expected: sync | status | doctor)"
            return 1
            ;;
    esac

    PYTHONPATH="${SPEED_DIR}/lib" "$(_skills_python)" -m skills "$sub" \
        --project-root "${PROJECT_ROOT}" \
        --skills-dir "${SPEED_DIR}/skills" \
        --catalog-version "$(_skills_catalog_version)" \
        "$@"
}
