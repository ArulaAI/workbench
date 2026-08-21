#!/usr/bin/env bash
# defect.sh — Defect triage entry command

cmd_defect() {
    local spec_path="${1:-}"

    if [[ -z "$spec_path" ]]; then
        log_error "Usage: speed defect <path-to-defect-spec>"
        exit 1
    fi

    local name
    name=$(defect_name_from_path "$spec_path")
    local defect_dir
    defect_dir=$(get_defect_dir "$name")

    # Existing state — pick up from current stage
    if [[ -d "$defect_dir" ]] && [[ -f "${defect_dir}/state.json" ]]; then
        local status complexity
        status=$(jq -r '.status' "${defect_dir}/state.json")
        complexity=$(jq -r '.complexity // "moderate"' "${defect_dir}/state.json")

        log_info "Defect '${name}' in state '${status}'"

        case "$status" in
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
        esac

        log_success "Defect '${name}' resolved"
        return 0
    fi

    # No state — fresh run, validate spec file
    if [[ ! -f "$spec_path" ]]; then
        log_error "Defect spec not found: ${spec_path}"
        exit 1
    fi

    local resolved_path project_root_real
    resolved_path=$(realpath "$spec_path")
    project_root_real=$(realpath "$PROJECT_ROOT")
    if [[ "$resolved_path" != "${project_root_real}"* ]]; then
        log_error "Invalid spec path: ${spec_path}"
        exit 1
    fi

    local triage_rc=0
    triage_defect "$spec_path" || triage_rc=$?

    if [[ $triage_rc -eq 0 ]]; then
        fix_defect "$name"
        integrate_defect "$name"
        log_success "Defect '${name}' resolved"
    fi
}
