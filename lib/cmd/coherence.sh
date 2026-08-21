#!/usr/bin/env bash
# coherence.sh — Cross-task coherence check command

_print_coherence_delta() {
    local prev_file="$1"
    local new_json="$2"

    # Graceful no-op if prev file missing or unreadable
    [[ -f "$prev_file" ]] || return 0

    local prev_json
    prev_json=$(cat "$prev_file") || return 0

    # Validate both are JSON with critical_issues arrays
    local prev_issues new_issues
    prev_issues=$(echo "$prev_json" | jq -r '.critical_issues[]?' 2>/dev/null) || return 0
    new_issues=$(echo "$new_json" | jq -r '.critical_issues[]?' 2>/dev/null) || return 0

    # Handle empty arrays — if both empty, nothing to show
    [[ -z "$prev_issues" ]] && [[ -z "$new_issues" ]] && return 0
    # If no previous issues but new ones appeared, skip delta (first meaningful failure)
    [[ -z "$prev_issues" ]] && return 0

    # Compute sets: fixed, remaining, new
    local fixed=() remaining=() new_found=()

    # Check each previous issue
    while IFS= read -r issue; do
        [[ -z "$issue" ]] && continue
        if echo "$new_issues" | grep -qxF "$issue"; then
            remaining+=("$issue")
        else
            fixed+=("$issue")
        fi
    done <<< "$prev_issues"

    # Check for new issues (in new but not in prev)
    while IFS= read -r issue; do
        [[ -z "$issue" ]] && continue
        if ! echo "$prev_issues" | grep -qxF "$issue"; then
            new_found+=("$issue")
        fi
    done <<< "$new_issues"

    # Count transition
    local prev_count new_count
    prev_count=$(echo "$prev_json" | jq '.critical_issues | length' 2>/dev/null) || prev_count=0
    new_count=$(echo "$new_json" | jq '.critical_issues | length' 2>/dev/null) || new_count=0

    echo ""
    echo -e "  ${BOLD}Delta (vs. previous run):${RESET}"
    echo -e "  Critical issues: ${prev_count} ${SYM_ARROW} ${new_count}"

    for issue in "${fixed[@]}"; do
        echo -e "    ${COLOR_SUCCESS}${SYM_CHECK} Fixed:${RESET} ${issue}"
    done
    for issue in "${remaining[@]}"; do
        echo -e "    ${COLOR_WARN}${SYM_WARN} Remains:${RESET} ${issue}"
    done
    for issue in "${new_found[@]}"; do
        echo -e "    ${COLOR_ERROR}${SYM_CROSS} New:${RESET} ${issue}"
    done

    echo ""
    echo -e "  ${#fixed[@]} issue(s) fixed, ${#remaining[@]} remaining, ${#new_found[@]} new"

    # Celebratory message if all previous issues resolved and no new ones
    if [[ ${#remaining[@]} -eq 0 ]] && [[ ${#new_found[@]} -eq 0 ]]; then
        echo -e "  ${COLOR_SUCCESS}All previous issues resolved!${RESET}"
    fi

    echo ""
}
cmd_coherence() {
    if [[ "${1:-}" == "--cross-feature" ]]; then
        cmd_coherence_cross_feature
        return $?
    fi

    _require_feature "$GLOBAL_FEATURE"

    if [[ "${1:-}" == "--resolve" ]]; then
        _coherence_resolve
        return
    fi

    log_header "Coherence Check"

    # Archive previous report for delta comparison
    local prev_report=""
    if [[ -f "${LOGS_DIR}/coherence.log" ]]; then
        cp "${LOGS_DIR}/coherence.log" "${LOGS_DIR}/coherence-prev.json"
        prev_report="${LOGS_DIR}/coherence-prev.json"
    fi

    local done_tasks
    done_tasks=$(task_list_by_status "done")

    if [[ -z "$done_tasks" ]]; then
        log_info "No completed tasks to check."
        return
    fi

    # Gather all diffs from completed tasks
    local all_diffs=""
    local task_count=0
    while IFS= read -r tid; do
        local task_json
        task_json=$(task_get "$tid")
        local title branch
        title=$(echo "$task_json" | jq -r '.title')
        branch=$(echo "$task_json" | jq -r '.branch')

        local diff=""
        if git_branch_exists "$branch"; then
            diff=$(git_diff_branch "$branch" 2>/dev/null || echo "No diff")
        fi

        all_diffs+="
--- TASK ${tid}: ${title} (branch: ${branch}) ---
\`\`\`diff
${diff}
\`\`\`

"
        ((task_count++)) || true
    done <<< "$done_tasks"

    # Gather product spec
    local spec_content=""
    local spec_file
    spec_file=$(_get_spec_path)
    if [[ -n "$spec_file" ]] && [[ -f "$spec_file" ]]; then
        spec_content=$(cat "$spec_file")
    fi

    # Gather contract
    local contract_content=""
    if [[ -f "${CONTRACT_FILE}" ]]; then
        contract_content=$(cat "${CONTRACT_FILE}")
    fi

    # Build cross-task analysis and assemble coherence context
    context_build_cross_task "${TASKS_DIR}" "${FEATURE_NAME}" 2>/dev/null || true

    # Build task diffs JSON for assembly
    local task_diffs_json="{}"
    while IFS= read -r tid; do
        local _branch
        _branch=$(jq -r '.branch' "${TASKS_DIR}/${tid}.json" 2>/dev/null)
        local _diff=""
        if [[ -n "$_branch" ]] && git_branch_exists "$_branch"; then
            _diff=$(git_diff_branch "$_branch" 2>/dev/null || echo "")
        fi
        task_diffs_json=$(jq --arg tid "$tid" --rawfile diff <(printf '%s' "$_diff") '. + {($tid): $diff}' <<< "$task_diffs_json")
    done <<< "$done_tasks"

    local coherence_message
    coherence_message=$(context_assemble_coherence \
        "${TASKS_DIR}" \
        "$task_diffs_json" \
        "$spec_content" \
        "${CONTRACT_FILE}" \
        "${FEATURE_NAME}" 2>/dev/null) || coherence_message=""

    # Fallback to inline prompt
    if [[ -z "$coherence_message" ]]; then
        coherence_message="## Coherence Check: ${task_count} completed tasks

### All Task Diffs
${all_diffs}

### Product Specification
${spec_content}

### Data Model Contract
${contract_content}

Check that all these task implementations compose correctly. Focus on interfaces, schemas, naming consistency, duplicates, and missing connections."
    fi

    log_step "Sending ${task_count} task diffs to Coherence Checker..."
    echo ""

    local coherence_output
    if ! coherence_output=$(provider_run \
        "${AGENTS_DIR}/coherence-checker.md" \
        "$coherence_message" \
        "$MODEL_PLANNING" \
        "$AGENT_TOOLS_READONLY" \
        "Coherence"); then
        log_error "Coherence Checker agent failed — check agent CLI connection"
        exit 1
    fi

    if [[ -z "$coherence_output" ]]; then
        log_error "Coherence Checker agent returned empty output"
        exit 1
    fi

    echo "$coherence_output"
    echo ""

    # Parse and save report
    local parsed_coherence
    parsed_coherence=$(parse_agent_json "$coherence_output") || parsed_coherence="$coherence_output"
    echo "$parsed_coherence" > "${LOGS_DIR}/coherence.log"
    log_success "Coherence report saved to ${LOGS_DIR}/coherence.log"

    if ! _require_json "Coherence Checker" "$parsed_coherence"; then
        log_error "Review raw output: ${LOGS_DIR}/coherence.log"
        exit 1
    fi

    # Show delta if a previous report exists
    if [[ -n "$prev_report" ]] && [[ -f "$prev_report" ]]; then
        _print_coherence_delta "$prev_report" "$parsed_coherence"
    fi

    local status
    status=$(echo "$parsed_coherence" | jq -r '.status // "unknown"')

    [[ "${MP_ENABLED:-}" == "true" ]] && event_emit "coherence.completed" "$FEATURE_NAME" "{\"status\":\"$status\"}" || true

    if [[ "$status" == "fail" ]]; then
        echo ""
        log_error "Coherence check FAILED — tasks have compatibility issues"
        local issue_count
        issue_count=$(echo "$parsed_coherence" | jq '.critical_issues | length')
        log_error "${issue_count} critical issue(s) found"
        echo ""
        echo -e "  ${COLOR_STEP}speed coherence --resolve${RESET}  — create fix task from coherence recommendations"
        exit 1
    elif [[ "$status" == "pass" ]]; then
        echo ""
        log_success "Coherence check PASSED — tasks are compatible"
        rm -f "${LOGS_DIR}/coherence-prev.json"
        echo -e "Next: ${COLOR_STEP}speed integrate${RESET}"
    else
        log_warn "Could not parse coherence status. Review the report manually."
    fi

    echo ""
}

# ── Coherence resolution ──────────────────────────────────────
# Creates a fix task from coherence recommendations. Follows the
# cmd_fix_nits pattern (retry.sh:265): new task, not a reset of
# existing tasks. Done tasks stay done; their code stays on the
# feature branch. The fix task branches off the current state and
# patches the seams.

_coherence_resolve() {
    log_header "Coherence Resolution"

    local coh="${LOGS_DIR}/coherence.log"
    [[ -f "$coh" ]] || { log_error "No coherence report. Run ${COLOR_STEP}speed coherence${RESET} first."; exit 1; }

    local coh_status
    coh_status=$(jq -r '.status' "$coh")
    [[ "$coh_status" == "fail" ]] || { log_success "Coherence already passing."; return 0; }

    local rec_count
    rec_count=$(jq '.recommendations | length' "$coh")
    if [[ "$rec_count" == "0" ]] || [[ -z "$rec_count" ]]; then
        log_warn "No recommendations in coherence report. Review ${coh} manually."
        exit 1
    fi

    # Guard: don't create duplicate fix tasks
    for f in "${TASKS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local t_title t_status
        t_title=$(jq -r '.title // ""' "$f")
        t_status=$(jq -r '.status' "$f")
        if [[ "$t_title" == "Fix coherence issues" ]] && [[ "$t_status" == "pending" || "$t_status" == "running" ]]; then
            local t_id
            t_id=$(jq -r '.id' "$f")
            log_warn "Coherence fix task ${t_id} already exists (${t_status}). Run it first."
            exit 1
        fi
    done

    # Compute next task ID (same pattern as cmd_fix_nits:306-316)
    local max_id=0
    for f in "${TASKS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local tid
        tid=$(jq -r '.id' "$f" 2>/dev/null) || continue
        if [[ "$tid" -gt "$max_id" ]] 2>/dev/null; then
            max_id="$tid"
        fi
    done
    local next_id=$((max_id + 1))

    # Build description from recommendations
    local description="Fix the following cross-task coherence issues. Each recommendation is from the coherence checker's analysis of all completed task diffs against the spec.\n"
    local i=1
    while IFS= read -r rec; do
        [[ -z "$rec" ]] && continue
        description+="\n${i}. ${rec}"
        i=$((i + 1))
    done < <(jq -r '.recommendations[]' "$coh")
    description+="\n\nFollow spec schemas exactly for field names, types, and structure. Do not refactor beyond what the recommendations ask for."

    local criteria="- Each coherence recommendation is addressed or has a comment explaining why it was skipped\n- speed coherence passes after these fixes\n- No new lint/typecheck/test failures\n- All quality gates pass"

    # Extract code file paths from all issue locations.
    # Strips :line, :line-range, and (description) suffixes.
    # Filters out spec files — only code files belong in files_touched.
    local files_touched
    files_touched=$(jq -c '[
        (.interface_mismatches[]? | .location_a, .location_b),
        (.schema_inconsistencies[]?.locations[]?),
        (.missing_connections[]?.expected_in // empty)
    ] | map(split(":")[0] | split(" (")[0] | ltrimstr(" ") | rtrimstr(" "))
      | map(select(length > 0))
      | map(select(startswith("specs/") | not))
      | unique' "$coh")

    if [[ "$files_touched" == "[]" ]]; then
        log_warn "No code files found in coherence issues. Review ${coh} manually."
        exit 1
    fi

    # depends_on: done tasks that own the affected files.
    # Only done — pending tasks would block the fix task, and their
    # code isn't on the feature branch yet.
    local depends_on="[]"
    for f_path in $(echo "$files_touched" | jq -r '.[]'); do
        for tf in "${TASKS_DIR}"/*.json; do
            [[ -f "$tf" ]] || continue
            if jq -e --arg f "$f_path" \
                '(.status == "done") and (.files_touched // [] | any(. == $f))' \
                "$tf" >/dev/null 2>&1; then
                depends_on=$(echo "$depends_on" | jq --arg id "$(jq -r '.id' "$tf")" \
                    'if any(. == $id) then . else . + [$id] end')
            fi
        done
    done

    local title="Fix coherence issues"

    # Display plan
    echo ""
    echo -e "${BOLD}${rec_count} recommendation(s) from coherence report:${RESET}"
    echo ""
    jq -r '.recommendations[]' "$coh" | while IFS= read -r rec; do
        echo "  - ${rec}"
    done
    echo ""
    echo -e "Files: $(echo "$files_touched" | jq -r 'join(", ")')"
    echo -e "Depends on tasks: $(echo "$depends_on" | jq -r 'join(", ")')"
    echo ""

    read -p "Create task ${next_id}? [Y/n] " confirm
    [[ "$confirm" == "n" || "$confirm" == "N" ]] && { log_info "Aborted."; return 0; }

    task_create "$next_id" "$title" "$(echo -e "$description")" "$(echo -e "$criteria")" "$depends_on" "$MODEL_SUPPORT"
    task_update_raw "$next_id" "files_touched" "$files_touched"

    echo ""
    log_success "Created task ${next_id}: ${title}"
    log_step "${rec_count} recommendation(s), $(echo "$files_touched" | jq 'length') file(s)"
    echo ""
    echo -e "  ${COLOR_DIM}Next: ${COLOR_STEP}speed run${COLOR_DIM} && ${COLOR_STEP}speed coherence${RESET}"
    echo ""
}
