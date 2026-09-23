#!/usr/bin/env bash
# defect.sh — Defect triage entry command

_defect_start_triage() {
    local spec_path="$1" name="$2" triage_rc=0
    triage_defect "$spec_path" || triage_rc=$?
    if [[ $triage_rc -eq 0 ]]; then
        fix_defect "$name" || return $?
        integrate_defect "$name" || return $?
        log_success "Defect '${name}' resolved"
    fi
    return "$triage_rc"
}

cmd_defect() {
    local spec_path="${1:-}"

    if [[ -z "$spec_path" ]]; then
        log_error "Usage: speed defect <path-to-defect-spec>"
        exit 1
    fi

    if [[ ! -f "$spec_path" ]]; then
        log_error "Defect spec not found: ${spec_path}"
        return 1
    fi
    local resolved_path project_root_real
    resolved_path=$(realpath "$spec_path")
    project_root_real=$(realpath "$PROJECT_ROOT")
    if [[ "$resolved_path" != "${project_root_real}/"* ]]; then
        log_error "Invalid spec path: ${spec_path}"
        return 1
    fi

    local name
    name=$(defect_name_from_path "$spec_path")
    local defect_dir
    defect_dir=$(get_defect_dir "$name")

    # Existing state — pick up from current stage
    if [[ -d "$defect_dir" ]] && [[ -f "${defect_dir}/state.json" ]]; then
        if ! PYTHONPATH="${SPEED_DIR}" "$(_defect_python)" -m lib.defect_report_cli \
            readiness "$PROJECT_ROOT" "$DEFECTS_DIR" "$name" "$spec_path"; then
            log_error "Defect '${name}' requires intake repair"
            return 1
        fi
        local status complexity
        status=$(jq -r '.status' "${defect_dir}/state.json")
        complexity=$(jq -r '.complexity // "moderate"' "${defect_dir}/state.json")

        log_info "Defect '${name}' in state '${status}'"

        case "$status" in
            filed)
                _defect_start_triage "$spec_path" "$name"
                return $?
                ;;
            resolved|rejected|escalated)
                log_info "Nothing to do"
                return 0
                ;;
            triaged)
                [[ "$complexity" == "moderate" ]] && reproduce_defect "$name"
                fix_defect "$name"
                [[ "$complexity" == "moderate" ]] && review_defect_fix "$name"
                integrate_defect "$name"
                ;;
            reproduced|fixing)
                # Reset to triaged so fix_defect can transition fixing
                transition_defect_state "$name" "triaged"
                fix_defect "$name"
                [[ "$complexity" == "moderate" ]] && review_defect_fix "$name"
                integrate_defect "$name"
                ;;
            fixed)
                [[ "$complexity" == "moderate" ]] && review_defect_fix "$name"
                integrate_defect "$name"
                ;;
            reviewed)
                integrate_defect "$name"
                ;;
            *)
                log_error "Cannot resume defect '${name}' from unknown state '${status}'"
                return 1
                ;;
        esac

        log_success "Defect '${name}' resolved"
        return 0
    fi

    _defect_start_triage "$spec_path" "$name"
}
