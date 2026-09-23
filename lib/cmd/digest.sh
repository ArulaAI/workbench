#!/usr/bin/env bash
# digest.sh — Repository Digest command
#
# speed digest [--refresh] [--rebuild-discovery] [--json]
# See specs/tech/speed-repository-digest-dashboard.md > API Surface > Optional CLI surface.
#
# Owns Repository Digest shell integration and provider invocation.
# CLI and dashboard reuse the Python refresh owner for extraction,
# validation, caching, budgets, locking and publication.
#
# Repository content (README prose, domain labels, evidence descriptions)
# is arbitrary UTF-8 and can be large. It's deliberately never captured
# into a bash variable via $() below — under a non-UTF-8-aware locale
# (LC_CTYPE=C, which this environment defaults to and SPEED does not
# override), bash's own multi-byte handling during command substitution
# can corrupt a large non-ASCII byte stream. Everything content-bearing is
# routed through a temp file and read back with jq/cat, which handle bytes
# correctly regardless of locale; only small, ASCII-safe status fields
# (load_status, build status, warning count) are ever assigned to a
# bash variable.

digest_status() {
    # Prints {"load_status": "missing"|"malformed"|"ok", "digest": {...}|null, "reason": str|null}
    PROJECT_ROOT="$PROJECT_ROOT" $(_context_python) - <<'PYTHON_EOF'
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))
from lib.context.repository_digest import load_repository_digest_with_status

project_root = os.environ.get("PROJECT_ROOT", ".")
load_status, digest, reason = load_repository_digest_with_status(project_root)
print(json.dumps({"load_status": load_status, "digest": digest, "reason": reason}))
PYTHON_EOF
}

digest_build() {
    local narrative="${1:-false}"
    local rebuild_discovery="${2:-false}"

    PROJECT_ROOT="$PROJECT_ROOT" $(_context_python) - "$narrative" "$rebuild_discovery" <<'PYTHON_EOF'
import sys, os, json
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))
from lib.context.repository_digest_build import refresh_digest
from lib.context.utils import load_speed_toml

project_root = os.environ.get("PROJECT_ROOT", ".")
narrative = sys.argv[1] == "true"
config = load_speed_toml(project_root)
def progress(event):
    print("__SPEED_DISCOVERY_EVENT__" + json.dumps(
        event, separators=(",", ":")), file=sys.stderr, flush=True)
result = refresh_digest(project_root, config=config, narrative=narrative,
                        rebuild_discovery=sys.argv[2] == "true",
                        progress=progress)
print(json.dumps(result))
if result['outcome'] == 'cancelled':
    sys.exit(130)
if not result['ok']:
    code = (result.get('error') or {}).get('code')
    sys.exit(3 if code in ('INVALID_CONFIG','INVALID_ROOT','PROVIDER_UNAVAILABLE','PROVIDER_CAPABILITY_UNAVAILABLE') else 1)
PYTHON_EOF
}

digest_markdown() {
    local token_budget="${1:-4000}"
    PROJECT_ROOT="$PROJECT_ROOT" $(_context_python) - "$token_budget" <<'PYTHON_EOF'
import sys, os
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))
from lib.context.repository_digest import attach_effective_state, load_repository_digest, project_digest_for_agent
from lib.context.utils import load_speed_toml

project_root = os.environ.get("PROJECT_ROOT", ".")
token_budget = int(sys.argv[1])
digest = load_repository_digest(project_root)
if digest is None:
    sys.exit(1)
digest = attach_effective_state(project_root, digest, config=load_speed_toml(project_root))
sys.stdout.write(project_digest_for_agent(digest, token_budget=token_budget))
PYTHON_EOF
}

cmd_digest() {
    local do_refresh=false
    local rebuild_discovery=false
    # --json is one of speed's global flags (see main()'s "Extract global
    # flags before dispatching" loop in ./speed) — it's already stripped
    # out of "$@" and JSON_OUTPUT is already set by the time cmd_digest
    # runs, same as every other command's --json handling.
    local json_output="${JSON_OUTPUT:-false}"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --refresh)           do_refresh=true; shift ;;
            --rebuild-discovery) do_refresh=true; rebuild_discovery=true; shift ;;
            *)
                log_error "Unknown option: $1"
                log_error "Usage: speed digest [--refresh] [--rebuild-discovery] [--json]"
                exit "$EXIT_CONFIG_ERROR"
                ;;
        esac
    done

    local tmp_result
    local build_exit=0
    tmp_result=$(mktemp)
    cleanup_register_file "$tmp_result"

    if [[ "$do_refresh" == "true" ]]; then
        log_header "Repository Digest" >&2
        log_step "Building repository-digest.json; changed evidence may invoke the configured model..." >&2

        _digest_progress() {
            local line payload level message
            while IFS= read -r line; do
                if [[ "$line" == __SPEED_DISCOVERY_EVENT__* ]]; then
                    payload="${line#__SPEED_DISCOVERY_EVENT__}"
                    level=$(jq -r '.level // "step"' <<<"$payload" 2>/dev/null || echo step)
                    message=$(jq -r '.message // empty' <<<"$payload" 2>/dev/null || true)
                    [[ -n "$message" ]] || continue
                    case "$level" in
                        success) log_success "$message" >&2 ;;
                        warning) log_warn "$message" >&2 ;;
                        error)   log_error "$message" >&2 ;;
                        *)       log_step "$message" >&2 ;;
                    esac
                else
                    echo "$line" >&2
                fi
            done
        }

        digest_build "false" "$rebuild_discovery" \
            > "$tmp_result" 2> >(_digest_progress) || build_exit=$?

        if [[ "$build_exit" -ne 0 ]]; then
            local err
            err=$(jq -r 'if (.error | type) == "object" then .error.message else .error // "unknown error" end' "$tmp_result" 2>/dev/null || echo "unknown error")
            log_error "Digest build failed: ${err}" >&2
        fi

        local build_status
        build_status=$(jq -r '.outcome // .status // "unknown"' "$tmp_result" 2>/dev/null || echo "unknown")
        if [[ "$build_exit" -eq 0 ]]; then
            log_success "Digest ${build_status}." >&2
        fi

        local warning_count
        warning_count=$(jq '.warnings | length' "$tmp_result" 2>/dev/null || echo "0")
        if [[ "$warning_count" -gt 0 ]]; then
            jq -r '.warnings[]' "$tmp_result" 2>/dev/null | while IFS= read -r w; do
                log_warn "$w" >&2
            done
        fi
    fi

    if [[ "$json_output" == "true" ]]; then
        digest_status > "$tmp_result" || true
        local load_status
        load_status=$(jq -r '.load_status' "$tmp_result" 2>/dev/null || echo "missing")
        if [[ "$load_status" != "ok" ]]; then
            local reason
            reason=$(jq -r '.reason // "not built yet"' "$tmp_result" 2>/dev/null || echo "not built yet")
            log_error "No usable repository digest (${reason})."
            if [[ "$build_exit" -ne 0 ]]; then exit "$build_exit"; fi
            exit "$EXIT_CONFIG_ERROR"
        fi
        jq -c '.digest' "$tmp_result"
        exit "$build_exit"
    fi

    # Default: bounded Markdown, or report that none exists. Guarded with
    # `|| true` — under set -e (this script's default), an unguarded
    # command that exits 1 (which the underlying Python does when no
    # digest exists) would abort the whole process before the -s check
    # below ever ran.
    digest_markdown 4000 > "$tmp_result" || true
    if [[ ! -s "$tmp_result" ]]; then
        log_info "No repository digest exists yet. Run 'speed digest --refresh' to build one." >&2
        if [[ "$build_exit" -ne 0 ]]; then exit "$build_exit"; fi
        exit "$EXIT_CONFIG_ERROR"
    fi
    cat "$tmp_result"
    exit "$build_exit"
}

_digest_provider_config() {
    local support_caps planning_caps

    support_caps=$(provider_model_capabilities "$MODEL_SUPPORT") \
        || return "$EXIT_CONFIG_ERROR"
    if [[ "$MODEL_PLANNING" == "$MODEL_SUPPORT" ]]; then
        planning_caps="$support_caps"
    else
        planning_caps=$(provider_model_capabilities "$MODEL_PLANNING") \
            || return "$EXIT_CONFIG_ERROR"
    fi

    jq -n \
        --arg provider "$_PROVIDER_NAME" \
        --arg model "$MODEL_SUPPORT" \
        --arg planning_model "$MODEL_PLANNING" \
        --arg agent_file "$AGENT_FILE_PATH" \
        --argjson agent_timeout "$DEFAULT_AGENT_TIMEOUT" \
        --argjson kill_grace "$AGENT_KILL_GRACE" \
        --argjson support_caps "$support_caps" \
        --argjson planning_caps "$planning_caps" \
        '{
            provider: $provider,
            model: $model,
            planning_model: $planning_model,
            agent_file: $agent_file,
            agent_timeout: $agent_timeout,
            kill_grace: $kill_grace,
            models: {
                ($model): $support_caps,
                ($planning_model): $planning_caps
            }
        } + $support_caps'
}

_digest_retry_model() {
    local current_model="$1"
    local retry_count="$2"

    if [[ "$retry_count" -eq 0 ]] \
        && [[ "$current_model" != "$MODEL_PLANNING" ]]; then
        jq -n --arg model "$MODEL_PLANNING" '{model: $model}'
    else
        printf 'null\n'
    fi
}

# Internal provider entry point shared by CLI and dashboard discovery.
# Sourcing the command module defines functions without bootstrapping again.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    source "${SCRIPT_DIR}/lib/config.sh"
    source "${SCRIPT_DIR}/lib/log.sh"
    source "${SCRIPT_DIR}/lib/cleanup.sh"
    source "${SCRIPT_DIR}/lib/progress.sh"
    source "${SCRIPT_DIR}/lib/provider.sh"
    trap cleanup_all EXIT
    case "${1:-}" in
        config)
            _digest_provider_config
            ;;
        retry-model)
            shift
            _digest_retry_model "$@"
            ;;
        agent)
            shift
            failure_file=$(mktemp "${TMPDIR:-/tmp}/_speed_provider_failure_XXXXXX")
            export SPEED_PROVIDER_FAILURE_FILE="$failure_file"
            provider_failure_clear
            provider_rc=0
            output=$(provider_run_json "$1" "$(cat "$2")" "$3" "$4" \
                "$DEFAULT_JSON_MAX_TURNS" "" "$(basename "$1" .md)-$$" "$5") || provider_rc=$?
            if [[ $provider_rc -ne 0 ]]; then
                if ! envelope=$(provider_failure_read); then
                    provider_failure_record "unknown" "provider" "true" "exit_${provider_rc}" \
                        "Provider invocation failed" ""
                    envelope=$(provider_failure_read)
                fi
                printf '%s\n' "$envelope"
                rm -f "$failure_file"
                exit "$provider_rc"
            fi
            if ! parsed=$(parse_agent_json "$output"); then
                provider_failure_record "response_invalid" "request" "false" "invalid_json" \
                    "Provider final response is not valid JSON" ""
                envelope=$(provider_failure_read)
                printf '%s\n' "$envelope"
                rm -f "$failure_file"
                exit 1
            fi
            rm -f "$failure_file"
            printf '%s\n' "$parsed"
            ;;
        *) exit "$EXIT_CONFIG_ERROR" ;;
    esac
fi
