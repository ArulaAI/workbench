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

# The --facts-only summary. It leads with the answer a reader wants first
# (was every entry point followed to an end this tool can name?), then shows
# where each call on a trace went, the evidence gathered, and anything not
# analyzed. Every number comes from the result's report; nothing here counts.
_domains_render_facts() {
    local ok="" warn="" dim="" bold="" accent="" reset=""
    if [[ -n "${RESET:-}" ]]; then
        ok=$(printf '%b' "${COLOR_SUCCESS:-}"); warn=$(printf '%b' "${COLOR_WARN:-}")
        dim=$(printf '%b' "${COLOR_DIM:-}"); bold=$(printf '%b' "${BOLD:-}")
        accent=$(printf '%b' "${COLOR_ACCENT:-}"); reset=$(printf '%b' "${RESET:-}")
    fi
    jq -r --arg ok "$ok" --arg warn "$warn" --arg dim "$dim" --arg bold "$bold" \
          --arg accent "$accent" --arg reset "$reset" '
        def plural($n; $word): "\($n) \($word)\(if $n == 1 then "" else "s" end)";
        def lpad($n): tostring | (" " * ([$n - length, 0] | max)) + .;
        def rpad($n): tostring | . + (" " * ([$n - length, 1] | max));
        def heading($text): "  " + ($text | rpad(18));
        def title($text): "  " + $text;
        def row($name; $count; $note): "    " + ($name | rpad(14)) + ($count | lpad(4))
            + (if $note != "" then "   " + $dim + $note + $reset else "" end);
        def short: if test("^[\\w$]+(\\.[\\w$]+)+$") then split(".") | last else . end;
        def listed($items; $limit):
            ($items[:$limit] | map("\(.name | short) \(.sites)") | join(" · "))
            + (if ($items | length) > $limit then " · +\(($items | length) - $limit) more" else "" end);
        def seconds: if . == null then empty
            elif . < 1000 then "\(.) ms" else "\((. / 100 | round) / 10) s" end;

        .report as $r
        | .measurements.traces as $mt
        | ($r.traces // {total: $mt.total, complete: ($mt.complete // $mt.resolved),
                         bounded: ($mt.bounded // 0),
                         incomplete: ($mt.incomplete // ($mt.total - $mt.resolved))}) as $t
        | ([(.entry_points // [])[].total] | add // 0) as $entries
        | ($t.complete + $t.bounded) as $ended
        | ($r.calls // {}) as $calls
        | (.trace_blockers // []) as $blockers

        # ── Headline ────────────────────────────────────────────────────
        | (if $r.repository then "  " + $bold + $r.repository + $reset else empty end),
          (if $r then "  " + $dim
                + ([($r.files // [])[:5][] | "\(.files) \(.language)"] | join(" · "))
                + (if ($r.files // [] | length) > 5 then " · +\(($r.files | length) - 5) more" else "" end)
                + " files · \($r.symbols) symbols"
                + ($r.elapsed_ms | seconds | " · " + .) + $reset
           else empty end),
          "",
          (if $t.total == 0 and $entries == 0 then "  " + $warn + "No entry points found" + $reset
           elif $t.total == 0 then "  " + $warn + "▲ " + plural($entries; "entry point")
                + " found, none traced" + $reset
           elif $ended == $t.total
           then "  " + $ok + "✓ " + (if $t.total == 1 then "The entry point was"
                                   else "All \($t.total) entry points were" end)
                + " traced to a known end" + $reset
           else "  " + $warn + "▲ \($ended) of \(plural($t.total; "entry point")) traced to a known end · "
                + "\($t.incomplete) stop\(if $t.incomplete == 1 then "s" else "" end) at an open call"
                + $reset end),
          "",

        # ── Traces ──────────────────────────────────────────────────────
          (if $entries > 0
           then heading("Entry points") + ($entries | tostring) + "   " + $dim
                + ([.entry_points[] | "\(.kind) \(.resolved)/\(.total)"] | join(" · "))
                + " identified" + $reset
           else empty end),
          heading("Traces") + ($t.total | tostring),
          row("complete"; $t.complete; "every call resolves inside this repository"),
          row("bounded"; $t.bounded; "ends only at boundaries the facts name"),
          row("open"; $t.incomplete; if $t.incomplete > 0 then "stops at a call with no known target" else "" end),

        # ── Where traces stop: shown when a reader has something to act on ─
          (if ($t.incomplete > 0 and ($blockers | length) > 0)
              or ([$blockers[] | select(.class == "boundary")] | length) > 1
           then "",
                title("Where traces end"),
                ($blockers[] | select(.class == "boundary")
                 | "    " + (.label | rpad(46)) + (.traces | lpad(4))
                   + "   " + $dim + "boundary" + $reset),
                ($blockers[] | select(.class != "boundary")
                 | "    " + $warn + (.label | rpad(46)) + $reset
                   + (.traces | lpad(4)) + "   " + $dim + "gap" + $reset),
                (if ($blockers | length) > 1
                 then "    " + $dim + "A trace can appear in several rows." + $reset else empty end)
           else empty end),

        # ── Calls on traces ─────────────────────────────────────────────
          (if $calls.sites != null
           then "",
                heading("Calls on traces") + plural($calls.sites; "site"),
                row("repository"; $calls.repository; "resolved to a declaration in this repository"),
                row("platform"; $calls.platform; listed($r.platforms // []; 5)),
                (if $calls.library > 0 then row("library"; $calls.library; listed($r.libraries // []; 4)) else empty end),
                (if $calls.ambiguous > 0 then row("ambiguous"; $calls.ambiguous; "several declarations match") else empty end),
                "    " + (if $calls.open > 0 then $warn else "" end) + ("unresolved" | rpad(14))
                  + ($calls.open | lpad(4)) + $reset
                  + "   " + $dim + (if $calls.open == 0 then "every call on a trace has a known target"
                                  else "calls with no known target" end) + $reset,
                (if ($r.open_sites // []) | length > 0
                 then ($r.open_sites[]
                       | "      " + $dim + ("\(.path):\(.line)" | rpad(48)) + $reset
                         + (.excerpt | if length > 44 then .[:43] + "…" else . end)),
                      (if $r.open_sites_more > 0 then "      " + $dim + "+\($r.open_sites_more) more" + $reset else empty end)
                 else empty end)
           else
             # A result without a report (an older producer): the trace counts.
             (.measurements.call_targets as $c
              | if $c.unresolved_sites != null
                then "",
                     heading("Calls on traces") + "\($c.unresolved_sites) unresolved call sites"
                     + (if ($c.unresolved_sites_by_language | length) > 0
                        then " (" + ([$c.unresolved_sites_by_language | to_entries[] | "\(.key) \(.value)"]
                                     | join(", ")) + ")"
                        else "" end)
                     + (if $c.unresolved != $c.unresolved_sites
                        then "; \($c.unresolved) counted once per trace" else "" end)
                else empty end)
           end),

        # ── Data on traces ──────────────────────────────────────────────
          (($r.data // {stores: 0}) as $d
           | if $d.stores > 0
             then "",
                  heading("Data on traces") + plural($d.stores; "store") + " · "
                    + plural($d.reads; "read") + " · " + plural($d.writes; "write")
                    + (if $d.in_memory then "   " + $dim + "in-process memory" + $reset else "" end),
                  ($d.top[]
                   | "    " + (.name | rpad(34))
                     + $dim + ([(if .reads > 0 then plural(.reads; "read") else empty end),
                                (if .writes > 0 then plural(.writes; "write") else empty end)]
                               | join(" · ")) + $reset),
                  (if $d.more > 0 then "    " + $dim + "+\($d.more) more" + $reset else empty end)
             else empty end),

        # ── Evidence ────────────────────────────────────────────────────
          (if $r.evidence
           then "",
                heading("Evidence") + ([
                    (if $r.evidence.tests > 0 then plural($r.evidence.tests; "test link") else empty end),
                    (if $r.evidence.documentation > 0 then plural($r.evidence.documentation; "doc section") else empty end),
                    (if $r.evidence.inputs > 0 then plural($r.evidence.inputs; "input") else empty end),
                    (if $r.evidence.rule_observations > 0 then plural($r.evidence.rule_observations; "rule observation") else empty end)
                  ] | if length == 0 then "none" else join(" · ") end)
           else empty end),

        # ── Screen actions and generated declarations (when present) ────
          (if (.screen_actions // []) | length > 0
           then "",
                title("Screen actions"),
                (.screen_actions[]
                 | "    \(.route)"
                   + (if (.route | length) > 40 then "\n      " else " " * (42 - (.route | length)) end)
                   + (if .state == "labeled" then .label
                      elif .state == "ambiguous" then "ambiguous: " + ([.candidates[] | "\u0027\(.)\u0027"] | join(" or "))
                      elif .state == "labeled_unresolved" then "\(.label) (unresolved: \(.reason // "identity not established"))"
                      else "unlabeled: \(.reason // "label not statically determined")" end))
           else empty end),
          (if (.generated_declarations // []) | length > 0
           then "",
                heading("Generated") + $dim + "declarations modelled from build-time generators" + $reset,
                (.generated_declarations[]
                 | "    \(.kind): " + plural(.types; "type")
                   + (if .members > 0 then ", " + plural(.members; "member") else "" end)
                   + (if .calls > 0 then "; \(.calls) call\(if .calls == 1 then " resolves" else "s resolve" end) to them" else "" end))
           else empty end),

        # ── Relationships ───────────────────────────────────────────────
          "",
          ($r.relationships // {resolved: .coverage.edges_resolved, open: .coverage.edges_unresolved}) as $rel
          | heading("Relationships") + "\($rel.resolved) resolved · \($rel.open) unresolved",
          (if $rel.outside_traces != null and $rel.open > 0
             then ((if $rel.outside_traces > 0 then [$rel.outside_traces, "outside every trace"] else empty end),
                   (if $rel.on_traces_at_boundaries > 0 then [$rel.on_traces_at_boundaries, "on traces, ending at boundaries the facts name"] else empty end),
                   (if $rel.on_traces_open > 0 then [$rel.on_traces_open, "on traces, with no known target"] else empty end))
                  | "    " + ("" | rpad(14)) + (.[0] | lpad(4)) + "   " + $dim + .[1] + $reset
             else empty end),

        # ── Not analysed ────────────────────────────────────────────────
          ($r.unanalyzed // {files: 0}) as $u
          | (if $u.files > 0
             then "",
                  heading("Not analysed") + plural($u.files; "file")
                    + " (" + ($u.languages | join(", ")) + ")"
                    + (if ($u.causes | index("owner_not_installed")) then ": no analyser installed" else "" end)
                    + " · " + (if $u.facts_lost == 0 then $ok + "no facts lost" + $reset
                               else $warn + "facts lost in \($u.facts_lost)" + $reset end),
                  ([range(0; ($u.paths | length); 2) as $i | $u.paths[$i:$i + 2] | join(", ")]) as $lines
                  | range(0; $lines | length) as $k
                  | "                    " + $dim + $lines[$k]
                    + (if $k == ($lines | length) - 1 and $u.more > 0 then ", +\($u.more) more" else "" end)
                    + $reset
             else empty end),

        # ── Warnings and entry-point coverage ───────────────────────────
          "",
          heading("Warnings") + (.warnings | length | tostring),
          ((.warning_counts // [.warnings | group_by(.code)[] | {code: .[0].code, count: length}])[]
           | "    \(.code | rpad(42))\(.count | lpad(4))"
             + (if .boundary then "  " + $dim + "known boundary" + $reset
                elif .code == "SOURCE_CAPABILITY_UNAVAILABLE" then "  " + $dim + "see Not analysed" + $reset
                else "" end)),
          ((.coverage.entrypoint_gaps // []) as $g
           | if ($g | length) > 0
             then "",
                  "Entry-point coverage:",
                  ($g[] | select(.kind != "likely_missed") | "  \(.message)"),
                  ([$g[] | select(.kind == "likely_missed")] as $m
                   | if ($m | length) > 0
                     then "  Likely missed entry points: \($m | length) ("
                          + ([$m | group_by(.marker_kind)[] | "\(length) \(.[0].marker_kind)"] | join(", ")) + ")",
                          ($m | group_by(.marker_kind)[]
                           | "    \(.[0].marker_kind): "
                             + ([group_by(.framework)[] | "\(.[0].framework) \(length)"] | join(", ")))
                     else empty end),
                  (if (.coverage.entrypoint_markers_matched // 0) > 0
                   then "    of which \(.coverage.entrypoint_markers_matched) also declared by a known entry point"
                        + " (same method and route, e.g. an OpenAPI contract)"
                   else empty end)
             else empty end),
          "",
          "Facts written to:",
          "\(.artifact)"
    ' "$1"
}

_domains_render_status() {
    jq -r '
        if .status == null then "No domain discovery has run yet. Run: speed discover domains"
        else
          .status as $s
          | "Started:     \($s.started_at // "-")",
            "Completed:   \($s.completed_at // "-")",
            "Outcome:     \($s.phase) (attempt \($s.attempt_build_id))",
            (if $s.execution_mode == "hierarchical"
             then "Mode:        hierarchical: \($s.limits.semantic_units_total - 1) entry-point bundles, then root reconciliation (\($s.limits.semantic_units_validated)/\($s.limits.semantic_units_total) validated\(if $s.root_reconciled then "" else ", root not reconciled" end))"
             elif $s.execution_mode == "whole_graph" then "Mode:        whole graph (one scope)"
             else empty end),
            "Published:   \(if .published then "yes (build \(.published_build_id))" else "no" end)",
            (if .preserved_build_id then "Preserved:   build \(.preserved_build_id) is still the published model; this attempt did not replace it" else empty end),
            (if $s.coverage then "Anchors:     \($s.coverage.anchors_processed)/\($s.coverage.anchors_total) processed" else empty end),
            "Warnings:    \($s.warnings | length)",
            (if $s.error then "Error:       \($s.error.code // "-"): \($s.error.message // $s.error)" else empty end)
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
        --facts-only) echo; _domains_render_facts "$tmp_result" ;;
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
