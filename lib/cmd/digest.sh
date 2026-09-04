#!/usr/bin/env bash
# digest.sh — Repository Digest command
#
# speed digest [--refresh] [--rebuild-discovery] [--json]
# See specs/tech/speed-repository-digest-dashboard.md > API Surface > Optional CLI surface.
#
# This is a Should-level deliverable — the dashboard and artifact contract
# do not depend on it. It's a thin wrapper over lib/context/repository_digest.py
# via context_bridge.sh, reusing the same builder the dashboard's refresh
# mutation calls.
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
    tmp_result=$(mktemp)
    # cmd_digest exits directly (matching every other cmd_* function in
    # lib/cmd/), so cleanup has to hang off EXIT rather than RETURN.
    trap 'rm -f "$tmp_result"' EXIT

    if [[ "$do_refresh" == "true" ]]; then
        log_header "Repository Digest"
        log_step "Building repository-digest.json..."

        local build_ok=true
        context_build_repository_digest "false" "$rebuild_discovery" > "$tmp_result" || build_ok=false

        if [[ "$build_ok" != "true" ]]; then
            local err
            err=$(jq -r '.error // "unknown error"' "$tmp_result" 2>/dev/null || cat "$tmp_result")
            log_error "Digest build failed: ${err}"
            exit "$EXIT_CONFIG_ERROR"
        fi

        local build_status
        build_status=$(jq -r '.status // "unknown"' "$tmp_result" 2>/dev/null || echo "unknown")
        log_success "Digest ${build_status}."

        local warning_count
        warning_count=$(jq '.warnings | length' "$tmp_result" 2>/dev/null || echo "0")
        if [[ "$warning_count" -gt 0 ]]; then
            jq -r '.warnings[]' "$tmp_result" 2>/dev/null | while IFS= read -r w; do
                log_warn "$w"
            done
        fi
    fi

    if [[ "$json_output" == "true" ]]; then
        context_repository_digest_status > "$tmp_result" || true
        local load_status
        load_status=$(jq -r '.load_status' "$tmp_result" 2>/dev/null || echo "missing")
        if [[ "$load_status" != "ok" ]]; then
            local reason
            reason=$(jq -r '.reason // "not built yet"' "$tmp_result" 2>/dev/null || echo "not built yet")
            log_error "No usable repository digest (${reason})."
            exit "$EXIT_CONFIG_ERROR"
        fi
        jq -c '.digest' "$tmp_result"
        exit "$EXIT_OK"
    fi

    # Default: bounded Markdown, or report that none exists. Guarded with
    # `|| true` — under set -e (this script's default), an unguarded
    # command that exits 1 (which the underlying Python does when no
    # digest exists) would abort the whole process before the -s check
    # below ever ran.
    context_project_repository_digest_markdown 4000 > "$tmp_result" || true
    if [[ ! -s "$tmp_result" ]]; then
        log_info "No repository digest exists yet. Run 'speed digest --refresh' to build one."
        exit "$EXIT_CONFIG_ERROR"
    fi
    cat "$tmp_result"
    exit "$EXIT_OK"
}
