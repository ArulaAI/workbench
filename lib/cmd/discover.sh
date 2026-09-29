#!/usr/bin/env bash
# discover.sh — Repository discovery commands
#
# speed discover <target> [options]
#
# Each target owns its own handler; this module only routes.
#   domains    Business-domain discovery (lib/cmd/domains.sh)

_discover_usage() {
    echo "Usage: speed discover domains [--facts-only | --status | --cancel] [--json]" >&2
}

cmd_discover() {
    local target="${1:-}"
    case "$target" in
        domains) shift; _discover_domains "$@" ;;
        ""|-h|--help|help) _discover_usage; exit 0 ;;
        *)
            log_error "Unknown discovery target: ${target}"
            _discover_usage
            exit "$EXIT_CONFIG_ERROR"
            ;;
    esac
}
