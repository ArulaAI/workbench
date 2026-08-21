#!/usr/bin/env bash
# release.sh — Release ownership of a feature

cmd_release() {
    local feature="${1:-}"

    if [[ -z "$feature" ]]; then
        log_error "Usage: speed release <feature>"
        exit 1
    fi

    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Multi-player mode not enabled. Run 'speed mp-init' first."
        exit 1
    fi

    # Verify current actor owns the feature
    local rc=0
    ownership_check "$feature" || rc=$?

    case $rc in
        0)
            event_emit "feature.released" "$feature" "{}"
            log_success "Released feature '${feature}'"
            ;;
        1)
            log_error "Feature '${feature}' is owned by ${OWNERSHIP_OWNER}, not you"
            return 1
            ;;
        2)
            log_info "Feature '${feature}' is not claimed"
            return 0
            ;;
    esac
}
