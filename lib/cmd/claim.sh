#!/usr/bin/env bash
# claim.sh — Claim ownership of a feature

cmd_claim() {
    local feature="${1:-}"

    if [[ -z "$feature" ]]; then
        log_error "Usage: speed claim <feature>"
        exit 1
    fi

    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Multi-player mode not enabled. Run 'speed mp-init' first."
        exit 1
    fi

    # Check current ownership
    local rc=0
    ownership_check "$feature" || rc=$?

    case $rc in
        0)
            log_info "You already own feature '${feature}'"
            return 0
            ;;
        1)
            log_error "Feature '${feature}' is claimed by ${OWNERSHIP_OWNER}"
            return 1
            ;;
        2)
            # Unclaimed or stale — proceed
            ;;
    esac

    # Ensure the feature directory exists in shared/
    mkdir -p "${SHARED_FEATURES_DIR}/${feature}/tasks"

    event_emit "feature.claimed" "$feature" \
        "$(jq -nc --arg a "$(actor_get)" --arg e "$(actor_email_get)" '{actor: $a, actor_email: $e}')"
    log_success "Claimed feature '${feature}' as $(actor_get)"
}
