#!/usr/bin/env bash
# skills.sh — project and inspect the Workbench canonical skill catalog.
#
# Thin wrapper: resolve the interpreter and the catalog version, then delegate
# to the `skills` Python package. `lib/` is not a package, so `skills` is
# imported with lib/ on PYTHONPATH.
#
# Two things this file resolves before delegating:
#
#   interpreter  SPEED_PYTHON, then the install venv, then the project venv.
#   catalog      the installation receipt, parsed through the same interpreter.
#
# `workbench skills` is the only supported entrance to the engine. `python -m
# skills` is private plumbing, and its `--project-root`, `--skills-dir` and
# `--catalog-version` arguments are internal context: this wrapper resolves that
# context and passes it in, which is why the engine has no project-root default
# of its own the way user-facing commands do. The option loop below therefore
# accepts only the public flags, so no caller can reach through this file to
# redirect the project or swap the canonical catalog.
#
# Exit codes follow the engine: 0 converged/current/no findings, 1 drift or
# doctor findings, 2 conflicts remain after a sync, 3 error. Usage and
# configuration problems detected here are errors, so they exit 3 as well; a
# caller must never read a mistyped flag as drift.

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

# Read the installed catalog version, keeping three outcomes distinct that used
# to collapse into the single string "dev": a source checkout is a development
# build, a receipt naming a version is a managed install, and a receipt that
# cannot be read is a broken install. Projecting "dev" from a broken install
# would stamp false provenance into the manifest and report invented drift on
# the next sync, so that case fails instead. Parsing runs through the same
# interpreter the engine uses rather than jq, which may not be installed.
_skills_catalog_version() {
    if [[ -e "${SPEED_DIR}/.git" ]]; then
        echo "dev"
        return 0
    fi

    local receipt="${SPEED_HOME:-$HOME/.speed}/receipt.json"
    if [[ ! -f "$receipt" ]]; then
        log_error "Installation receipt not found: ${receipt}"
        log_error "SPEED is neither a source checkout nor a complete installation. Reinstall SPEED or run: speed self-update"
        return 3
    fi

    local version
    if ! version=$("$(_skills_python)" -c '
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        receipt = json.load(handle)
except (OSError, ValueError):
    raise SystemExit(1)
value = receipt.get("version") if isinstance(receipt, dict) else None
if not isinstance(value, str) or not value.strip():
    raise SystemExit(1)
print(value.strip())
' "$receipt" 2>/dev/null); then
        log_error "Installation receipt is unreadable or has no version: ${receipt}"
        log_error "Reinstall SPEED or run: speed self-update"
        return 3
    fi
    echo "$version"
}

# Print a one-line temporary-alias notice to stderr when a command is invoked
# via `speed` rather than the canonical `workbench` namespace. The `workbench`
# dispatcher sets WORKBENCH_NS=1, which suppresses this.
_speed_alias_notice() {
    [[ -n "${WORKBENCH_NS:-}" ]] && return 0
    echo "note: 'speed $1' is a temporary alias for the canonical 'workbench $1'" >&2
}

_skills_usage() {
    cat <<USAGE
Usage: workbench skills <sync|status|doctor> [options]

  sync     Import the built-in catalog into every detected agent surface
  status   Show the managed state of each projected skill (read-only)
  doctor   Diagnose every non-current skill with one repair path (read-only)

Options:
$(printf '  %-32s  %s' "--surface <claude|codex|copilot>" "Limit the command to one agent surface")
  --force                           sync only: overwrite conflicting projections
  --json                            Emit machine-readable output

Exit codes: 0 ok · 1 drift or findings · 2 conflicts remain after sync · 3 error
USAGE
}

cmd_skills() {
    local sub="${1:-}"
    [[ $# -gt 0 ]] && shift

    case "$sub" in
        sync|status|doctor) ;;
        --help|-h|help)
            _skills_usage
            return 0
            ;;
        "")
            log_error "Missing skills subcommand (expected: sync | status | doctor)"
            _skills_usage >&2
            return 3
            ;;
        *)
            log_error "Unknown skills subcommand: ${sub} (expected: sync | status | doctor)"
            return 3
            ;;
    esac

    # Accept only the documented public options. --project-root, --skills-dir
    # and --catalog-version are Workbench's own resolved context: argparse takes
    # the last occurrence of a flag, so passing them through from the tail would
    # let any caller redirect the project or swap the canonical catalog.
    local user_args=()
    local want_json="${JSON_OUTPUT:-false}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --json)
                want_json=true
                shift
                ;;
            --force)
                if [[ "$sub" != "sync" ]]; then
                    log_error "--force applies to 'skills sync' only, not 'skills ${sub}'"
                    return 3
                fi
                user_args+=(--force)
                shift
                ;;
            --surface)
                if [[ $# -lt 2 || -z "${2:-}" || "${2}" == -* ]]; then
                    log_error "--surface requires one of: claude, codex, copilot"
                    return 3
                fi
                user_args+=(--surface "$2")
                shift 2
                ;;
            --surface=*)
                local value="${1#--surface=}"
                if [[ -z "$value" || "$value" == -* ]]; then
                    log_error "--surface requires one of: claude, codex, copilot"
                    return 3
                fi
                user_args+=(--surface "$value")
                shift
                ;;
            --help|-h)
                _skills_usage
                return 0
                ;;
            *)
                log_error "Unknown option for 'skills ${sub}': $1 (supported: --surface, --force, --json)"
                _skills_usage >&2
                return 3
                ;;
        esac
    done
    [[ "$want_json" == "true" ]] && user_args+=(--json)

    local catalog_version
    catalog_version=$(_skills_catalog_version) || return 3

    # `--debug` raises the shell's verbosity; the engine is a separate process
    # that reads an env var, so carry the intent across.
    local verbosity="${VERBOSITY:-1}"
    if [[ "$verbosity" =~ ^[0-9]+$ ]] && (( verbosity >= 3 )); then
        export WORKBENCH_DEBUG=1
    fi

    _speed_alias_notice skills
    PYTHONPATH="${SPEED_DIR}/lib" "$(_skills_python)" -m skills "$sub" \
        ${user_args[@]+"${user_args[@]}"} \
        --project-root "${PROJECT_ROOT}" \
        --skills-dir "${SPEED_DIR}/skills" \
        --catalog-version "$catalog_version"
}
