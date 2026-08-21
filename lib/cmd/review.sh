#!/usr/bin/env bash
# review.sh — Code review command

_load_relevant_specs() {
    local diff_text="$1"
    local primary_spec="$2"
    local specs_dir="${PROJECT_ROOT}/speed/specs"
    local result=""

    # Always include primary spec
    if [[ -n "$primary_spec" ]] && [[ -f "$primary_spec" ]]; then
        result="$primary_spec"
    fi

    [[ ! -d "$specs_dir" ]] && echo "$result" && return 0

    # Layer 1: file paths from diff
    local diff_paths
    diff_paths=$(echo "$diff_text" | grep -oE '(src|speed|lib)/[^ ]+' | sort -u 2>/dev/null || true)

    # Layer 2: identifiers (function names, class names) — 5+ chars, capped at 100
    local identifiers
    identifiers=$(echo "$diff_text" | grep -oE '[a-zA-Z_][a-zA-Z0-9_]{4,}' | sort -u | head -100 2>/dev/null || true)

    while IFS= read -r -d '' sf; do
        # Skip primary spec (already included)
        if [[ -n "$primary_spec" ]] && [[ "$(realpath "$sf" 2>/dev/null)" == "$(realpath "$primary_spec" 2>/dev/null)" ]]; then
            continue
        fi

        local matched=false

        # Layer 1: check if any diff file path appears in spec
        if [[ -n "$diff_paths" ]]; then
            while IFS= read -r dp; do
                [[ -z "$dp" ]] && continue
                if grep -q "$dp" "$sf" 2>/dev/null; then
                    matched=true
                    break
                fi
            done <<< "$diff_paths"
        fi

        # Layer 2: check if any identifier appears in spec (only if Layer 1 didn't match)
        if [[ "$matched" == "false" ]] && [[ -n "$identifiers" ]]; then
            while IFS= read -r id; do
                [[ -z "$id" ]] && continue
                if grep -q "$id" "$sf" 2>/dev/null; then
                    matched=true
                    break
                fi
            done <<< "$identifiers"
        fi

        [[ "$matched" == "true" ]] && result+=$'\n'"$sf"
    done < <(find "$specs_dir" -name '*.md' -type f -print0 | sort -z)

    echo "$result"
}
_print_review_nits() {
    local nits_json="$1"
    local count
    count=$(echo "$nits_json" | jq 'length' 2>/dev/null) || count=0

    [[ "$count" == "0" ]] || [[ -z "$count" ]] && return 0

    # Save to file
    echo "$nits_json" | jq '.' > "${LOGS_DIR}/review-nits.json"

    # Print summary
    echo ""
    echo -e "  ${BOLD}Review Nits (${count} items across approved tasks):${RESET}"
    echo ""

    echo "$nits_json" | jq -r '.[] | "\(.task_id): \(.severity) — \(.message // .description // "no message") (\(.file // "?"):\(.line // "?"))"' 2>/dev/null | while IFS= read -r line; do
        echo -e "    ${COLOR_WARN}${SYM_WARN}${RESET} ${line}"
    done

    echo ""
    echo -e "  ${COLOR_DIM}Full details: ${LOGS_DIR}/review-nits.json${RESET}"
}
cmd_review() {
    _require_feature "$GLOBAL_FEATURE"
    local task_id=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --task-id) task_id="$2"; shift 2 ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    log_header "Code Review"

    # If no task specified, review all done tasks
    local tasks_to_review
    if [[ -n "$task_id" ]]; then
        tasks_to_review="$task_id"
    else
        tasks_to_review=$(task_list_by_status "done")
    fi

    if [[ -z "$tasks_to_review" ]]; then
        log_info "No completed tasks to review."
        return
    fi

    # Filter out tasks that were already approved (prevent re-review)
    local filtered_tasks=""
    while IFS= read -r tid; do
        [[ -z "$tid" ]] && continue
        local rv
        rv=$(jq -r '.review_verdict // empty' "${TASKS_DIR}/${tid}.json" 2>/dev/null)
        if [[ "$rv" == "approve" ]]; then
            log_info "Task ${tid}: already approved, skipping"
        else
            filtered_tasks+="${tid}"$'\n'
        fi
    done <<< "$tasks_to_review"
    # Trim trailing newline
    filtered_tasks=$(echo "$filtered_tasks" | sed '/^$/d')

    if [[ -z "$filtered_tasks" ]]; then
        log_info "All completed tasks already reviewed."
        return
    fi
    tasks_to_review="$filtered_tasks"

    local all_nits="[]"

    while IFS= read -r tid; do
        local task_json
        task_json=$(task_get "$tid")
        local title branch criteria
        title=$(echo "$task_json" | jq -r '.title')
        branch=$(echo "$task_json" | jq -r '.branch')
        criteria=$(echo "$task_json" | jq -r '.acceptance_criteria')

        log_step "Reviewing task ${tid}: ${COLOR_STEP}${title}${RESET}"

        # Get the diff
        local diff=""
        if git_branch_exists "$branch"; then
            local fork_point
            fork_point=$(_git merge-base "$(git_main_branch)" "$branch" 2>/dev/null) || true
            diff=$(_git diff "${fork_point}..${branch}" 2>/dev/null || echo "No diff available")
        else
            log_warn "Branch ${branch} not found, skipping"
            continue
        fi

        # Truncate diff if too long
        local diff_lines
        diff_lines=$(echo "$diff" | wc -l | tr -d ' ')
        if [[ $diff_lines -gt $DIFF_HEAD_LINES ]]; then
            diff=$(head -n "$DIFF_HEAD_LINES" <<< "$diff")
            diff+=$'\n'"... (truncated at ${DIFF_HEAD_LINES} lines — full diff on branch ${branch})"
        fi

        # Gather relevant specs (smart loader — not all specs)
        local spec_context=""
        local spec_file
        spec_file=$(_get_spec_path)
        local relevant_specs
        relevant_specs=$(_load_relevant_specs "$diff" "$spec_file")
        while IFS= read -r sf; do
            [[ -z "$sf" ]] && continue
            local relpath="${sf#${PROJECT_ROOT}/}"
            if [[ -n "$spec_file" ]] && [[ "$(realpath "$sf" 2>/dev/null)" == "$(realpath "$spec_file" 2>/dev/null)" ]]; then
                spec_context+="
### Product Specification (SOURCE OF TRUTH — verify code satisfies this)
$(cat "$sf")"
            else
                spec_context+=$'\n\n'"--- RELATED SPEC: ${relpath} ---"$'\n'"$(cat "$sf")"
            fi
        done <<< "$relevant_specs"

        # Load cross-cutting concerns for reviewer
        local cc_json_review=""
        if [[ -f "${FEATURE_DIR}/cross_cutting_concerns.json" ]]; then
            cc_json_review=$(cat "${FEATURE_DIR}/cross_cutting_concerns.json")
        fi

        # Build Layer 2 for reviewer stage (if not already built)
        local task_file_path_review="${TASKS_DIR}/${tid}.json"
        context_build_layer2_task "$task_file_path_review" "${TASKS_DIR}" "" "reviewer" 2>/dev/null || true

        # Assemble reviewer prompt with structured context
        local agent_message
        agent_message=$(context_assemble_reviewer \
            "$task_file_path_review" \
            "$diff" \
            "$cc_json_review" 2>/dev/null) || agent_message=""

        # Fallback to inline prompt if assembly fails
        if [[ -z "$agent_message" ]]; then
            agent_message="## Review Task ${tid}: ${title}

### Acceptance Criteria
${criteria}

### Git Diff (branch: ${branch})
\`\`\`diff
${diff}
\`\`\`
${spec_context}

### Instructions
1. Read the Product Specification FIRST — form your understanding of what this code should do
2. Check the diff against the spec — quote specific spec lines for each requirement you verify
3. Flag anything in the diff that doesn't trace to a spec requirement (potential over-engineering)
4. Then do standard code review (quality, conventions, security, tests)
Respond with your review as JSON."
        fi

        # Pace API call based on token budget
        local estimated_tokens
        estimated_tokens=$(_estimate_tokens "$agent_message")
        _pace_api_call "$estimated_tokens"

        local review_output
        if ! review_output=$(_call_with_retry provider_run \
            "${AGENTS_DIR}/reviewer.md" \
            "$agent_message" \
            "$MODEL_SUPPORT" \
            "$AGENT_TOOLS_READONLY" \
            "Reviewer"); then
            log_error "Reviewer agent failed for task ${tid} — check agent CLI connection"
            continue
        fi

        # Track token usage after successful call
        _track_tokens "$estimated_tokens"

        if [[ -z "$review_output" ]]; then
            log_error "Reviewer agent returned empty output for task ${tid}"
            continue
        fi

        echo ""
        echo "$review_output"
        echo ""

        # Parse and save review
        local parsed_review
        parsed_review=$(parse_agent_json "$review_output") || parsed_review="$review_output"
        echo "$parsed_review" > "${LOGS_DIR}/review-${tid}.json"

        # Check verdict
        if ! _require_json "Reviewer" "$parsed_review"; then
            log_warn "Skipping review for task ${tid} — see ${LOGS_DIR}/review-${tid}.json"
            continue
        fi

        local verdict
        verdict=$(echo "$parsed_review" | jq -r '.verdict // "unknown"')
        if [[ "$verdict" == "request_changes" ]]; then
            log_warn "Task ${tid}: changes requested"
            # Atomic: status + review_feedback in one write
            task_request_changes "$tid" "$parsed_review"
        elif [[ "$verdict" == "approve" ]]; then
            log_success "Task ${tid}: approved by Reviewer"
            task_set_reviewed "$tid" "approve"

            # ── Collect nits from approved tasks ──────────────────
            local task_nits
            task_nits=$(echo "$parsed_review" | jq -c --arg tid "$tid" --arg title "$title" \
                '[.issues[]? | select(.severity == "nit" or .severity == "minor") | . + {task_id: $tid, task_title: $title}]' 2>/dev/null) || task_nits="[]"
            if [[ "$task_nits" != "[]" ]] && [[ -n "$task_nits" ]]; then
                all_nits=$(echo "$all_nits" "$task_nits" | jq -s 'add')
            fi

            # ── Post-Review Guardian Gate ──────────────────────────
            # Check: did the implementation drift from the vision?
            if [[ "${SKIP_GUARDIAN:-}" != "true" ]]; then
                local guardian_input="## Task ${tid}: ${title}

### Code Diff (branch: ${branch})
\`\`\`diff
${diff}
\`\`\`

### Task Acceptance Criteria
${criteria}"

                local grc=0
                local _guardian_out
                _guardian_out=$(_run_guardian "post-review" "$guardian_input" "task-${tid}") || grc=$?
                if [[ $grc -eq 1 ]]; then
                    log_error "Task ${tid}: Guardian REJECTED — vision violation in implementation"
                    local guardian_log
                    guardian_log=$(ls -t "${LOGS_DIR}"/guardian-post-review-*.json 2>/dev/null | head -1 || true)
                    # Atomic: status + review_feedback in one write
                    task_request_changes "$tid" "GUARDIAN REJECTED: $(cat "$guardian_log" 2>/dev/null | jq -r '.summary' 2>/dev/null || echo 'See guardian log')"
                    verdict="request_changes"
                elif [[ $grc -eq 3 ]]; then
                    log_warn "Task ${tid}: Guardian returned unparseable output — keeping approved status"
                fi
                # grc == 2 means flagged — warn but keep approved
            else
                _log_gate_skip "guardian_post_review" "review"
            fi
        fi

    done <<< "$tasks_to_review"

    _print_review_nits "$all_nits"

    echo ""
}
