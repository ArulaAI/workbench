#!/usr/bin/env bash
# guardian.sh — Product Guardian vision check command

# Print the newest ad-hoc report, not a wildcard.
_guardian_report_path() {
    local report
    report=$(ls -t "${LOGS_DIR}"/guardian-ad-hoc-*.json 2>/dev/null | head -1)
    [[ -n "$report" ]] && echo -e "Report saved to ${COLOR_STEP}${report}${RESET}"
    return 0
}

cmd_guardian() {
    local input_file="${1:-}"

    log_header "Product Guardian"

    # If a file is provided, evaluate it (ad-hoc — no feature needed)
    if [[ -n "$input_file" ]]; then
        if [[ ! -f "$input_file" ]]; then
            if [[ -f "${PROJECT_ROOT}/${input_file}" ]]; then
                input_file="${PROJECT_ROOT}/${input_file}"
            else
                log_error "File not found: $input_file"
                exit 1
            fi
        fi

        # Log under the feature the file belongs to when that feature exists,
        # otherwise under the active feature, else the default LOGS_DIR.
        if [[ -z "${GLOBAL_FEATURE:-}" && "$input_file" == *specs/* ]]; then
            local _file_feature
            _file_feature=$(feature_name_from_spec "$input_file" 2>/dev/null || true)
            if [[ -n "$_file_feature" && -d "${FEATURES_DIR}/${_file_feature}" ]]; then
                GLOBAL_FEATURE="$_file_feature"
            fi
        fi
        feature_resolve "$GLOBAL_FEATURE" &>/dev/null && _require_feature "$GLOBAL_FEATURE" || mkdir -p "$LOGS_DIR"

        log_step "Evaluating: ${COLOR_STEP}${input_file}${RESET}"
        local content
        content=$(cat "$input_file")

        local rc=0
        _run_guardian "ad-hoc" "$content" "$input_file" || rc=$?

        echo ""
        _guardian_report_path
        echo ""
        return $rc
    fi

    # No file — evaluate the current task plan + completed work (requires feature)
    _require_feature "$GLOBAL_FEATURE"

    local spec_file
    spec_file=$(_get_spec_path)
    if [[ -z "$spec_file" ]] || [[ ! -f "$spec_file" ]]; then
        log_error "No spec file found. Provide a file or run 'speed plan' first."
        log_error "Usage: speed guardian <spec-or-plan-file>"
        exit 1
    fi

    log_step "Evaluating current spec: ${COLOR_STEP}${spec_file}${RESET}"
    local content
    content=$(cat "$spec_file")

    # Include task plan if it exists
    local total
    total=$(task_count_total 2>/dev/null || echo "0")
    if [[ "$total" -gt 0 ]]; then
        content+="\n\n## Current Task Plan\n"
        for f in "${TASKS_DIR}"/*.json; do
            [[ -f "$f" ]] || continue
            local id title status
            id=$(jq -r '.id' "$f")
            title=$(jq -r '.title' "$f")
            status=$(jq -r '.status' "$f")
            content+="- Task ${id}: ${title} [${status}]\n"
        done
    fi

    local rc=0
    _run_guardian "ad-hoc" "$content" "$spec_file" || rc=$?

    echo ""
    _guardian_report_path
    echo ""
    return $rc
}
