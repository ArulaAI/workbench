#!/usr/bin/env bash
# domains.sh — Business-domain discovery
#
# speed discover domains [--facts-only | --status | --cancel] [--json]
#
# Two roles:
#   1. `_discover_domains`, the `speed discover domains` handler. It calls
#      lib/context/business_domain_cli.py, which owns extraction, locking,
#      synthesis and publication, and renders its one JSON result.
#   2. Internal provider entry point for business-domain synthesis and
#      verification (lib/context/business_domain_synthesis.py). Python
#      invokes this script as `domains.sh config|retry-model|agent ...`; the
#      shared provider layer (lib/provider.sh) owns provider selection,
#      authentication, permissions and native failure normalization.
#
# Repository content in results is arbitrary UTF-8, so results are routed
# through a temp file and read with jq, never captured into a variable.

_domains_render_progress() {
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

_domains_render_facts() {
    jq -r '
        .measurements.traces as $t
        | .coverage as $c
        | "Traces:          \($t.resolved)/\($t.total) resolved (\($t.ambiguous) ambiguous, \($t.unresolved) unresolved)",
          "Relationships:   \($c.edges_resolved) resolved, \($c.edges_unresolved) unresolved, \($c.edges_ambiguous) ambiguous",
          "Unresolved calls: \(.measurements.call_targets.unresolved)"
            + (if (.measurements.call_targets.unresolved_by_language | length) > 0
               then " (" + ([.measurements.call_targets.unresolved_by_language | to_entries[] | "\(.key) \(.value)"] | join(", ")) + ")"
               else "" end),
          "Warnings:        \(.warnings | length)"
            + (if (.warnings | length) > 0
               then " (" + ([.warnings | group_by(.code)[] | "\(.[0].code) \(length)"] | join(", ")) + ")"
               else "" end),
          "Facts written to \(.artifact)"
    ' "$1"
}

_domains_render_status() {
    jq -r '
        if .status == null then "No domain discovery has run yet. Run: speed discover domains"
        else
          .status as $s
          | "Phase:       \($s.phase)",
            "Started:     \($s.started_at // "-")",
            "Completed:   \($s.completed_at // "-")",
            "Published:   \(if .published then "yes (build \(.published_build_id))" else "no" end)",
            (if $s.coverage then "Anchors:     \($s.coverage.anchors_processed)/\($s.coverage.anchors_total) processed" else empty end),
            "Warnings:    \($s.warnings | length)",
            (if $s.error then "Error:       \($s.error.message // $s.error.code // $s.error)" else empty end)
        end
    ' "$1"
}

_discover_domains() {
    local mode_flag=""
    local json_output="${JSON_OUTPUT:-false}"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --facts-only|--status|--cancel)
                if [[ -n "$mode_flag" ]]; then
                    log_error "Use only one of --facts-only, --status, --cancel"
                    exit "$EXIT_CONFIG_ERROR"
                fi
                mode_flag="$1"; shift ;;
            *)
                log_error "Unknown option: $1"
                _discover_usage
                exit "$EXIT_CONFIG_ERROR"
                ;;
        esac
    done

    local tmp_result
    local rc=0
    tmp_result=$(mktemp)
    cleanup_register_file "$tmp_result"

    case "$mode_flag" in
        "")           log_header "Business-domain discovery" >&2
                      log_step "Full pipeline: extraction, then model synthesis and verification..." >&2 ;;
        --facts-only) log_header "Business-domain facts" >&2 ;;
    esac

    PYTHONPATH="${SPEED_DIR:-$(cd "${LIB_DIR}/.." && pwd)}" "$(_context_python)" \
        -m lib.context.business_domain_cli --root "$PROJECT_ROOT" ${mode_flag:+"$mode_flag"} \
        > "$tmp_result" 2> >(_domains_render_progress) || rc=$?

    if [[ "$json_output" == "true" ]]; then
        cat "$tmp_result"
        exit "$rc"
    fi

    if [[ "$(jq -r '.ok' "$tmp_result" 2>/dev/null)" != "true" ]] \
        && jq -e '.error' "$tmp_result" >/dev/null 2>&1; then
        log_error "$(jq -r '"\(.error.code): \(.error.message)"' "$tmp_result")"
        exit "$rc"
    fi

    case "$mode_flag" in
        --facts-only) _domains_render_facts "$tmp_result" ;;
        --status)     _domains_render_status "$tmp_result" ;;
        --cancel)     log_success "Cancellation requested for build $(jq -r '.build_id' "$tmp_result")." ;;
        "")
            _domains_render_status "$tmp_result"
            log_info "Run log: $(jq -r '.log' "$tmp_result")" >&2
            ;;
    esac
    exit "$rc"
}

_domains_provider_config() {
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

_domains_retry_model() {
    local current_model="$1"
    local retry_count="$2"

    if [[ "$retry_count" -eq 0 ]] \
        && [[ "$current_model" != "$MODEL_PLANNING" ]]; then
        jq -n --arg model "$MODEL_PLANNING" '{model: $model}'
    else
        printf 'null\n'
    fi
}

# Sourcing the module defines functions without bootstrapping.
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
            _domains_provider_config
            ;;
        retry-model)
            shift
            _domains_retry_model "$@"
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
