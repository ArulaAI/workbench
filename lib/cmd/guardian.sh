#!/usr/bin/env bash
# guardian.sh — Product Guardian vision check command

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

        # Use feature context for log output if available, else default LOGS_DIR
        feature_resolve "$GLOBAL_FEATURE" &>/dev/null && _require_feature "$GLOBAL_FEATURE" || mkdir -p "$LOGS_DIR"

        log_step "Evaluating: ${COLOR_STEP}${input_file}${RESET}"
        local content
        content=$(cat "$input_file")

        _run_guardian "ad-hoc" "$content" "$input_file"
        local rc=$?

        echo ""
        echo -e "Report saved to ${COLOR_STEP}${LOGS_DIR}/guardian-ad-hoc-*.json${RESET}"
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

    _run_guardian "ad-hoc" "$content" "$spec_file"
    local rc=$?

    echo ""
    echo -e "Report saved to ${COLOR_STEP}${LOGS_DIR}/guardian-ad-hoc-*.json${RESET}"
    echo ""
    return $rc
}
