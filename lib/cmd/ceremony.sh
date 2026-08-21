#!/usr/bin/env bash
# ceremony.sh — Async multi-player ceremony commands
#
# Three ceremony flows, all event-driven:
#
# 1. Spec Review:  speed spec propose → speed spec review → speed spec ratify
# 2. Outcome Review: speed review request → speed review judge → speed review status
#
# Each command emits or queries events. No meetings required.
#
# Requires: events.sh, actor.sh, multiplayer.sh, config.sh

# ── Approval threshold (configurable via speed.toml) ──────────
SPEC_APPROVAL_THRESHOLD="${TOML_MULTIPLAYER_APPROVAL_THRESHOLD:-1}"

# ══════════════════════════════════════════════════════════════
# Spec Review Ceremony
# ══════════════════════════════════════════════════════════════

# speed spec propose <spec-path>
# Creates a review request for a spec. Blocks plan until ratified.
cmd_spec_propose() {
    local spec_path="${1:-}"

    if [[ -z "$spec_path" ]]; then
        log_error "Usage: speed spec propose <spec-path>"
        exit 1
    fi

    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Spec ceremonies require multi-player mode. Run 'speed mp-init' first."
        exit 1
    fi

    if [[ ! -f "$spec_path" ]]; then
        log_error "Spec file not found: $spec_path"
        exit 1
    fi

    local feature
    feature=$(feature_name_from_spec "$spec_path")

    # Compute spec hash for change tracking
    local spec_hash
    spec_hash=$(shasum -a 256 "$spec_path" | cut -d' ' -f1)

    event_emit "spec.proposed" "$feature" "{\"spec_path\":$(jq -n --arg p "$spec_path" '$p'),\"spec_hash\":\"${spec_hash}\"}"

    log_success "Spec proposed for review: ${spec_path}"
    log_info "Waiting for ${SPEC_APPROVAL_THRESHOLD} approval(s) before plan is unlocked"
    log_info "Reviewers: run ${COLOR_STEP}speed spec review${RESET} to see pending specs"
}

# speed spec review [--approve|--reject] [spec-path]
# List pending specs or submit a verdict.
cmd_spec_review() {
    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Spec ceremonies require multi-player mode."
        exit 1
    fi

    local verdict="" spec_path="" comment=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --approve) verdict="approve"; shift ;;
            --reject)  verdict="reject"; shift ;;
            --comment) comment="$2"; shift 2 ;;
            *) spec_path="$1"; shift ;;
        esac
    done

    # List mode: show all pending proposals
    if [[ -z "$verdict" ]]; then
        log_header "Pending Spec Reviews"

        local events_dir
        events_dir=$(mp_events_dir)
        local proposals=0

        for f in "${events_dir}"/*_spec-proposed_*.jsonl; do
            [[ -f "$f" ]] || continue
            local feat sp actor ts
            feat=$(jq -r '.feature // "?"' "$f" 2>/dev/null)
            sp=$(jq -r '.data.spec_path // "?"' "$f" 2>/dev/null)
            actor=$(jq -r '.actor // "?"' "$f" 2>/dev/null)
            ts=$(jq -r '.timestamp // "?"' "$f" 2>/dev/null)

            # Count approvals for this spec
            local approvals=0
            for vf in "${events_dir}"/*_spec-reviewed_"${feat}".jsonl; do
                [[ -f "$vf" ]] || continue
                local v
                v=$(jq -r '.data.verdict // ""' "$vf" 2>/dev/null)
                [[ "$v" == "approve" ]] && ((approvals++)) || true
            done

            # Check if already ratified
            local ratified=false
            for rf in "${events_dir}"/*_spec-ratified_"${feat}".jsonl; do
                [[ -f "$rf" ]] && ratified=true && break
            done

            if $ratified; then
                echo -e "  ${COLOR_SUCCESS}${SYM_CHECK}${RESET} ${feat} — ${sp} ${COLOR_DIM}(ratified)${RESET}"
            elif [[ $approvals -ge $SPEC_APPROVAL_THRESHOLD ]]; then
                echo -e "  ${COLOR_SUCCESS}${SYM_CHECK}${RESET} ${feat} — ${sp} ${COLOR_DIM}(${approvals} approvals, ready to ratify)${RESET}"
            else
                echo -e "  ${COLOR_WARN}${SYM_PENDING}${RESET} ${feat} — ${sp} by ${actor} ${COLOR_DIM}(${approvals}/${SPEC_APPROVAL_THRESHOLD} approvals, ${ts})${RESET}"
            fi
            ((proposals++)) || true
        done

        if [[ $proposals -eq 0 ]]; then
            log_info "No pending spec proposals."
        fi
        return 0
    fi

    # Verdict mode
    if [[ -z "$spec_path" ]]; then
        log_error "Usage: speed spec review --approve|--reject <spec-path>"
        exit 1
    fi

    local feature
    feature=$(feature_name_from_spec "$spec_path")

    event_emit "spec.reviewed" "$feature" "{\"spec_path\":$(jq -n --arg p "$spec_path" '$p'),\"verdict\":\"$verdict\",\"comment\":$(jq -n --arg c "$comment" '$c')}"

    if [[ "$verdict" == "approve" ]]; then
        log_success "Approved: ${spec_path}"
    else
        log_warn "Rejected: ${spec_path}"
        [[ -n "$comment" ]] && log_info "Comment: ${comment}"
    fi
}

# speed spec ratify [spec-path]
# Check approval threshold and unlock feature for planning.
cmd_spec_ratify() {
    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Spec ceremonies require multi-player mode."
        exit 1
    fi

    local spec_path="${1:-}"
    if [[ -z "$spec_path" ]]; then
        log_error "Usage: speed spec ratify <spec-path>"
        exit 1
    fi

    local feature
    feature=$(feature_name_from_spec "$spec_path")

    # Count approvals
    local events_dir
    events_dir=$(mp_events_dir)
    local approvals=0 rejections=0

    for f in "${events_dir}"/*_spec-reviewed_"${feature}".jsonl; do
        [[ -f "$f" ]] || continue
        local v
        v=$(jq -r '.data.verdict // ""' "$f" 2>/dev/null)
        case "$v" in
            approve) ((approvals++)) || true ;;
            reject)  ((rejections++)) || true ;;
        esac
    done

    log_step "Spec '${feature}': ${approvals} approval(s), ${rejections} rejection(s) (threshold: ${SPEC_APPROVAL_THRESHOLD})"

    if [[ $rejections -gt 0 ]]; then
        log_error "Cannot ratify: ${rejections} rejection(s) outstanding"
        log_info "Address feedback and re-propose with ${COLOR_STEP}speed spec propose ${spec_path}${RESET}"
        return 1
    fi

    if [[ $approvals -lt $SPEC_APPROVAL_THRESHOLD ]]; then
        log_error "Cannot ratify: ${approvals}/${SPEC_APPROVAL_THRESHOLD} approvals"
        return 1
    fi

    event_emit "spec.ratified" "$feature" "{\"spec_path\":$(jq -n --arg p "$spec_path" '$p'),\"approvals\":$approvals}"
    log_success "Spec ratified for '${feature}' — planning unlocked"
    log_info "Run ${COLOR_STEP}speed plan ${spec_path}${RESET}"
}

# ══════════════════════════════════════════════════════════════
# Outcome Review Ceremony
# ══════════════════════════════════════════════════════════════

# speed review request [--feature name]
# Post outcome evidence for team review after run+review complete.
cmd_review_request() {
    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Outcome review requires multi-player mode."
        exit 1
    fi

    _require_feature "$GLOBAL_FEATURE"

    # Gather evidence summary
    local total done failed blocked
    total=$(task_count_total)
    done=$(task_count_by_status "done")
    failed=$(task_count_by_status "failed")
    blocked=$(task_count_by_status "blocked")

    # Check for review results
    local reviewed=0
    for f in "${LOGS_DIR}"/review-*.json; do
        [[ -f "$f" ]] && ((reviewed++)) || true
    done

    # Guardian results
    local guardian_pass=0 guardian_fail=0
    for f in "${LOGS_DIR}"/guardian-*.json; do
        [[ -f "$f" ]] || continue
        local gv
        gv=$(jq -r '.verdict // ""' "$f" 2>/dev/null)
        case "$gv" in
            approve|pass) ((guardian_pass++)) || true ;;
            reject|fail) ((guardian_fail++)) || true ;;
        esac
    done

    local evidence="{\"tasks\":{\"total\":$total,\"done\":$done,\"failed\":$failed,\"blocked\":$blocked},\"reviews\":$reviewed,\"guardian\":{\"pass\":$guardian_pass,\"fail\":$guardian_fail}}"

    event_emit "outcome.review_requested" "$FEATURE_NAME" "$evidence"

    log_success "Outcome review requested for '${FEATURE_NAME}'"
    echo ""
    echo -e "  Tasks: ${done}/${total} done, ${failed} failed, ${blocked} blocked"
    echo -e "  Reviews: ${reviewed} completed"
    echo -e "  Guardian: ${guardian_pass} pass, ${guardian_fail} fail"
    echo ""
    log_info "Team: run ${COLOR_STEP}speed review judge --feature ${FEATURE_NAME}${RESET} to submit verdict"
}

# speed review judge [--feature name] [--approve|--reject] [--comment "..."]
# Submit a verdict on an outcome review.
cmd_review_judge() {
    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Outcome review requires multi-player mode."
        exit 1
    fi

    local verdict="" comment=""
    local judge_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --approve) verdict="approve"; shift ;;
            --reject)  verdict="reject"; shift ;;
            --comment) comment="$2"; shift 2 ;;
            *) judge_args+=("$1"); shift ;;
        esac
    done

    _require_feature "$GLOBAL_FEATURE"

    if [[ -z "$verdict" ]]; then
        log_error "Usage: speed review judge --approve|--reject [--comment \"...\"]"
        exit 1
    fi

    event_emit "outcome.judged" "$FEATURE_NAME" "{\"verdict\":\"$verdict\",\"comment\":$(jq -n --arg c "$comment" '$c')}"

    if [[ "$verdict" == "approve" ]]; then
        log_success "Approved outcome for '${FEATURE_NAME}'"
    else
        log_warn "Rejected outcome for '${FEATURE_NAME}'"
        [[ -n "$comment" ]] && log_info "Comment: ${comment}"
    fi
}

# speed review status [--feature name]
# Show consolidated feedback from outcome review.
cmd_review_status() {
    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Outcome review requires multi-player mode."
        exit 1
    fi

    _require_feature "$GLOBAL_FEATURE"

    log_header "Outcome Review: ${FEATURE_NAME}"

    local events_dir
    events_dir=$(mp_events_dir)

    # Find the review request
    local requested=false
    for f in "${events_dir}"/*_outcome-review-requested_"${FEATURE_NAME}".jsonl; do
        [[ -f "$f" ]] || continue
        requested=true
        local req_actor req_ts
        req_actor=$(jq -r '.actor // "?"' "$f" 2>/dev/null)
        req_ts=$(jq -r '.timestamp // "?"' "$f" 2>/dev/null)
        local evidence
        evidence=$(jq -r '.data' "$f" 2>/dev/null)
        echo -e "  Requested by: ${req_actor} at ${req_ts}"
        echo -e "  Evidence: $(echo "$evidence" | jq -c '.' 2>/dev/null)"
        echo ""
    done

    if ! $requested; then
        log_info "No outcome review requested for '${FEATURE_NAME}'"
        log_info "Run ${COLOR_STEP}speed review request${RESET} to start"
        return 0
    fi

    # Collect verdicts
    local approvals=0 rejections=0
    echo -e "${BOLD}Verdicts:${RESET}"
    for f in "${events_dir}"/*_outcome-judged_"${FEATURE_NAME}".jsonl; do
        [[ -f "$f" ]] || continue
        local actor verdict ts comment_text
        actor=$(jq -r '.actor // "?"' "$f" 2>/dev/null)
        verdict=$(jq -r '.data.verdict // "?"' "$f" 2>/dev/null)
        ts=$(jq -r '.timestamp // "?"' "$f" 2>/dev/null)
        comment_text=$(jq -r '.data.comment // ""' "$f" 2>/dev/null)

        local icon="${COLOR_DIM}?${RESET}"
        case "$verdict" in
            approve) icon="${COLOR_SUCCESS}${SYM_CHECK}${RESET}"; ((approvals++)) || true ;;
            reject)  icon="${COLOR_ERROR}${SYM_CROSS}${RESET}"; ((rejections++)) || true ;;
        esac

        echo -e "  ${icon} ${actor}: ${verdict} ${COLOR_DIM}(${ts})${RESET}"
        [[ -n "$comment_text" ]] && echo -e "    ${COLOR_DIM}${comment_text}${RESET}"
    done

    echo ""
    echo -e "  Total: ${approvals} approve, ${rejections} reject"

    if [[ $rejections -gt 0 ]]; then
        echo ""
        log_warn "Outcome has rejections. Address feedback before integrating."
    elif [[ $approvals -gt 0 ]]; then
        echo ""
        log_success "Outcome approved. Ready for ${COLOR_STEP}speed integrate${RESET}"
    fi
}

# ── Dispatch for speed spec subcommand ────────────────────────
cmd_spec() {
    local subcmd="${1:-}"
    shift || true

    case "$subcmd" in
        propose) cmd_spec_propose "$@" ;;
        review)  cmd_spec_review "$@" ;;
        ratify)  cmd_spec_ratify "$@" ;;
        *)
            log_error "Usage: speed spec <propose|review|ratify>"
            exit 1
            ;;
    esac
}
