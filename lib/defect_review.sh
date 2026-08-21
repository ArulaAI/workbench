#!/usr/bin/env bash
# defect_review.sh — Orchestration for defect review and integration stages
#
# Provides review_defect_fix, check_guardian_threshold, run_defect_guardian,
# and integrate_defect functions. Sources lib/defects.sh for state management.
#
# Requires config.sh, log.sh, defects.sh, git.sh, and provider.sh to be
# sourced first.

# ── review_defect_fix ──────────────────────────────────────────────
# Review a moderate defect fix via the Reviewer Agent.
# Transitions: fixed → reviewing → reviewed (on pass)
#              fixed → reviewing → fixed (on fail, with logged issues)
# Args: name

review_defect_fix() {
    local name="$1"

    local defect_dir
    defect_dir=$(get_defect_dir "$name")

    # Validate defect exists
    if [[ ! -d "$defect_dir" ]]; then
        log_error "Defect '${name}' not found"
        return 1
    fi

    # Read state and get branch
    local state_json
    state_json=$(read_defect_state "$name") || return 1

    local current_status
    current_status=$(echo "$state_json" | jq -r '.status')
    if [[ "$current_status" != "fixed" ]]; then
        log_error "Defect '${name}' is in state '${current_status}', expected 'fixed'"
        return 1
    fi

    local branch
    branch=$(echo "$state_json" | jq -r '.branch // empty')
    if [[ -z "$branch" ]]; then
        log_error "Defect '${name}' has no branch set"
        return 1
    fi

    # Transition to reviewing
    transition_defect_state "$name" "reviewing" || return 1

    # Generate diff of defect branch against main
    local main_branch
    main_branch=$(git_main_branch)
    local diff
    diff=$(git_diff_branch "$branch" "$main_branch" 2>/dev/null || echo "")

    if [[ -z "$diff" ]]; then
        log_warn "No diff found for branch '${branch}' — empty changeset"
    fi

    # Truncate diff if too long
    local diff_lines
    diff_lines=$(echo "$diff" | wc -l | tr -d ' ')
    if [[ $diff_lines -gt $DIFF_HEAD_LINES ]]; then
        diff=$(head -n "$DIFF_HEAD_LINES" <<< "$diff")
        diff+=$'\n'"... (truncated at ${DIFF_HEAD_LINES} lines — full diff on branch ${branch})"
    fi

    # Read defect report
    local report=""
    if [[ -f "${defect_dir}/report.md" ]]; then
        report=$(cat "${defect_dir}/report.md")
    fi

    # Read triage output
    local triage_json
    triage_json=$(read_triage_output "$name" 2>/dev/null || echo "{}")

    local affected_files regression_risks
    affected_files=$(echo "$triage_json" | jq -r '.affected_files // []' 2>/dev/null)
    regression_risks=$(echo "$triage_json" | jq -r '.regression_risks // "none specified"' 2>/dev/null)

    # Extract the defect fix review section from reviewer.md
    local reviewer_section=""
    local reviewer_md="${AGENTS_DIR}/reviewer.md"
    if [[ -f "$reviewer_md" ]]; then
        reviewer_section=$(sed -n '/<!-- BEGIN: DEFECT FIX REVIEW -->/,/<!-- END: DEFECT FIX REVIEW -->/p' "$reviewer_md")
    fi

    # Build reviewer prompt
    local agent_message="## Defect Fix Review: ${name}

mode: defect_review

### Defect Report
${report}

### Triage Output
\`\`\`json
${triage_json}
\`\`\`

### Affected Files (from triage)
${affected_files}

### Regression Risks
${regression_risks}

### Git Diff (branch: ${branch})
\`\`\`diff
${diff}
\`\`\`

### Review Instructions
${reviewer_section}

Respond with your review as JSON."

    log_step "Reviewing defect fix for '${name}'..."

    # Pace API call
    local estimated_tokens
    estimated_tokens=$(_estimate_tokens "$agent_message")
    _pace_api_call "$estimated_tokens"

    # Run Reviewer Agent
    local review_output
    if ! review_output=$(_call_with_retry provider_run \
        "${AGENTS_DIR}/reviewer.md" \
        "$agent_message" \
        "$MODEL_SUPPORT" \
        "$AGENT_TOOLS_READONLY" \
        "Reviewer"); then
        log_error "Reviewer agent failed for defect '${name}'"
        # State stays at reviewing — transition back to fixed
        transition_defect_state "$name" "reviewed" 2>/dev/null || true
        # Force back to fixed via state write
        _review_revert_to_fixed "$name"
        return 1
    fi

    # Track token usage
    _track_tokens "$estimated_tokens"

    if [[ -z "$review_output" ]]; then
        log_error "Reviewer agent returned empty output for defect '${name}'"
        _review_revert_to_fixed "$name"
        return 1
    fi

    # Parse review output
    local parsed_review
    if ! parsed_review=$(parse_agent_json "$review_output"); then
        # Unparseable output — log raw, state stays fixed, warn human
        log_warn "Reviewer produced unparseable output for defect '${name}'"
        mkdir -p "${defect_dir}/logs"
        echo "$review_output" > "${defect_dir}/logs/review.log"
        log_warn "Raw output saved to ${defect_dir}/logs/review.log"
        log_warn "Human review required"
        _review_revert_to_fixed "$name"
        return 1
    fi

    # Save parsed review
    mkdir -p "${defect_dir}/logs"
    echo "$parsed_review" > "${defect_dir}/logs/review.log"

    # Check verdict
    local verdict
    verdict=$(echo "$parsed_review" | jq -r '.verdict // "unknown"' 2>/dev/null)

    if [[ "$verdict" == "approve" ]]; then
        transition_defect_state "$name" "reviewed" || return 1
        log_success "Defect '${name}' fix approved by Reviewer"
        return 0
    else
        # Review failed — log issues, revert to fixed, print for human
        log_warn "Defect '${name}' fix review: changes requested"

        local issue_count
        issue_count=$(echo "$parsed_review" | jq '.issues | length' 2>/dev/null || echo "0")
        if [[ "$issue_count" -gt 0 ]]; then
            echo ""
            echo -e "  ${BOLD}Review Issues:${RESET}"
            echo "$parsed_review" | jq -r '.issues[] | "    \(.severity): \(.message)"' 2>/dev/null
            echo ""
        fi

        # Check scope violations
        local scope_ok
        scope_ok=$(echo "$parsed_review" | jq -r '.defect_scope_check.scope_ok // true' 2>/dev/null)
        if [[ "$scope_ok" == "false" ]]; then
            echo -e "  ${BOLD}Scope Violations:${RESET}"
            echo "$parsed_review" | jq -r '.scope_violations[]? | "    \(.file): \(.description)"' 2>/dev/null
            echo ""
        fi

        _review_revert_to_fixed "$name"
        log_info "State remains at 'fixed' — address issues and re-run review"
        return 1
    fi
}

# Helper: revert from reviewing back to fixed.
# The state machine does not have a reviewing→fixed transition,
# so we write the state directly.
_review_revert_to_fixed() {
    local name="$1"
    local state_json
    state_json=$(read_defect_state "$name") || return 1
    local updated
    updated=$(echo "$state_json" | jq '.status = "fixed"')
    defect_state_write "$name" "$updated"
}

# ── check_guardian_threshold ───────────────────────────────────────
# Determine if Product Guardian should run based on diff size.
# Returns 0 (should run) if lines > 100 OR files > 3.
# Returns 1 (skip) otherwise.
# Args: name

check_guardian_threshold() {
    local name="$1"

    local state_json
    state_json=$(read_defect_state "$name") || return 1

    local branch
    branch=$(echo "$state_json" | jq -r '.branch // empty')
    if [[ -z "$branch" ]]; then
        log_verbose "Defect '${name}' has no branch — skipping guardian"
        return 1
    fi

    local main_branch
    main_branch=$(git_main_branch)

    # Count lines changed (additions + deletions)
    local lines_changed
    lines_changed=$(_git diff --stat "${main_branch}...${branch}" 2>/dev/null \
        | tail -1 \
        | sed -n 's/.*\([0-9][0-9]*\) insertion.*/\1/p')
    local deletions
    deletions=$(_git diff --stat "${main_branch}...${branch}" 2>/dev/null \
        | tail -1 \
        | sed -n 's/.*\([0-9][0-9]*\) deletion.*/\1/p')

    lines_changed=$(( ${lines_changed:-0} + ${deletions:-0} ))

    # Count files touched
    local files_touched
    files_touched=$(_git diff --name-only "${main_branch}...${branch}" 2>/dev/null | wc -l | tr -d ' ')

    log_verbose "Defect '${name}' diff: ${lines_changed} lines changed, ${files_touched} files"

    if [[ $lines_changed -gt 100 ]] || [[ $files_touched -gt 3 ]]; then
        return 0  # should run guardian
    fi

    return 1  # skip guardian
}

# ── run_defect_guardian ────────────────────────────────────────────
# Conditional Product Guardian execution for defect fixes.
# Checks threshold internally, skips if below.
# Args: name

run_defect_guardian() {
    local name="$1"

    # Check threshold — skip if below
    if ! check_guardian_threshold "$name"; then
        log_verbose "Defect '${name}' below guardian threshold — skipping"
        return 0
    fi

    log_step "Running Product Guardian scope check for defect '${name}'..."

    local state_json
    state_json=$(read_defect_state "$name") || return 1

    local branch
    branch=$(echo "$state_json" | jq -r '.branch // empty')

    local main_branch
    main_branch=$(git_main_branch)

    local diff
    diff=$(git_diff_branch "$branch" "$main_branch" 2>/dev/null || echo "")

    # Truncate diff if too long
    local diff_lines
    diff_lines=$(echo "$diff" | wc -l | tr -d ' ')
    if [[ $diff_lines -gt $DIFF_HEAD_LINES ]]; then
        diff=$(head -n "$DIFF_HEAD_LINES" <<< "$diff")
        diff+=$'\n'"... (truncated at ${DIFF_HEAD_LINES} lines)"
    fi

    local guardian_content="## Defect Fix Scope Check: ${name}

### Git Diff (branch: ${branch})
\`\`\`diff
${diff}
\`\`\`

### Scope Check Question
Is this fix staying in scope? Flag any changes that look like feature additions rather than defect correction."

    # Use the existing guardian infrastructure if available
    local overview_file="${PROJECT_ROOT}/${VISION_FILE}"
    if [[ ! -f "$overview_file" ]]; then
        log_warn "Product overview not found at ${overview_file} — skipping guardian"
        return 0
    fi

    local overview_content
    overview_content=$(cat "$overview_file")

    local guardian_message="## Guardian Check: defect-scope

### Product Vision (source of truth)
${overview_content}

### Input to Evaluate
${guardian_content}

Evaluate whether this defect fix stays in scope. Flag feature additions or scope creep. Respond with JSON."

    local raw_guardian_output
    if ! raw_guardian_output=$(provider_run \
        "${AGENTS_DIR}/product-guardian.md" \
        "$guardian_message" \
        "$MODEL_SUPPORT" \
        "$AGENT_TOOLS_READONLY" \
        "Guardian"); then
        log_warn "Guardian agent failed for defect '${name}'"
        return 0  # non-blocking
    fi

    if [[ -z "$raw_guardian_output" ]]; then
        log_warn "Guardian returned empty output for defect '${name}'"
        return 0  # non-blocking
    fi

    local guardian_output
    guardian_output=$(parse_agent_json "$raw_guardian_output") || guardian_output="$raw_guardian_output"

    # Save guardian report
    local defect_dir
    defect_dir=$(get_defect_dir "$name")
    mkdir -p "${defect_dir}/logs"
    echo "$guardian_output" > "${defect_dir}/logs/guardian.log"

    # Check status and print warnings (non-blocking)
    local status
    status=$(echo "$guardian_output" | jq -r '.status // "unknown"' 2>/dev/null || echo "unknown")
    local summary
    summary=$(echo "$guardian_output" | jq -r '.summary // "No summary"' 2>/dev/null || echo "No summary")

    case "$status" in
        aligned)
            log_success "Guardian: defect fix is in scope — ${summary}"
            ;;
        flagged)
            log_warn "Guardian: scope concerns flagged — ${summary}"
            local flag_count
            flag_count=$(echo "$guardian_output" | jq '.flags | length' 2>/dev/null || echo "0")
            if [[ "$flag_count" -gt 0 ]]; then
                echo ""
                echo -e "  ${BOLD}Guardian Flags:${RESET}"
                echo "$guardian_output" | jq -r '.flags[] | "    \(.severity // "warning"): \(.description // "no detail")"' 2>/dev/null
                echo ""
            fi
            log_info "Guardian flags are non-blocking — human decision required"
            ;;
        *)
            log_warn "Guardian returned status '${status}' — review ${defect_dir}/logs/guardian.log"
            ;;
    esac

    return 0  # always non-blocking
}

# ── integrate_defect ───────────────────────────────────────────────
# Final integration stage. Merges defect branch into main, runs
# regression tests, and transitions to resolved on success.
# Args: name

integrate_defect() {
    local name="$1"

    local defect_dir
    defect_dir=$(get_defect_dir "$name")

    if [[ ! -d "$defect_dir" ]]; then
        log_error "Defect '${name}' not found"
        return 1
    fi

    # Read state and triage
    local state_json
    state_json=$(read_defect_state "$name") || return 1

    local current_status
    current_status=$(echo "$state_json" | jq -r '.status')

    local triage_json
    triage_json=$(read_triage_output "$name" 2>/dev/null || echo "{}")
    local complexity
    complexity=$(echo "$triage_json" | jq -r '.complexity // "moderate"' 2>/dev/null)

    # Validate state based on complexity
    if [[ "$complexity" == "moderate" ]]; then
        if [[ "$current_status" != "reviewed" ]]; then
            log_error "Defect '${name}' is in state '${current_status}', expected 'reviewed' for moderate defect"
            return 1
        fi
    else
        # Trivial defects skip review — accept both fixed and integrating
        if [[ "$current_status" != "fixed" && "$current_status" != "integrating" ]]; then
            log_error "Defect '${name}' is in state '${current_status}', expected 'fixed' for trivial defect"
            return 1
        fi
    fi

    local branch
    branch=$(echo "$state_json" | jq -r '.branch // empty')
    if [[ -z "$branch" ]]; then
        log_error "Defect '${name}' has no branch set"
        return 1
    fi

    # Run guardian check (checks threshold internally)
    run_defect_guardian "$name"

    # Transition to integrating
    transition_defect_state "$name" "integrating" || return 1

    log_step "Integrating defect '${name}' (branch: ${branch})..."

    # Merge defect branch into main
    local main_branch
    main_branch=$(git_main_branch)

    if ! git_safe_merge "$branch" "$main_branch"; then
        log_error "Merge conflict integrating defect '${name}'"
        log_error "Branch '${branch}' could not be merged into '${main_branch}'"
        log_info "State stays at 'integrating' — resolve conflicts and retry"
        return "$EXIT_MERGE_CONFLICT"
    fi

    # Run regression tests
    log_step "Running regression tests after merge..."
    if ! regression_run; then
        log_error "Regression tests FAILED after merging defect '${name}'"
        log_info "State stays at 'integrating' — investigate and retry"
        return "$EXIT_GATE_FAILURE"
    fi

    # Success — transition to resolved
    transition_defect_state "$name" "resolved" || return 1

    # Delete the defect branch
    git_cleanup_branch "$branch"
    log_verbose "Deleted branch '${branch}'"

    # Print completion summary
    echo ""
    log_success "Defect '${name}' resolved"
    echo -e "  ${BOLD}Branch:${RESET}     ${branch} (merged into ${main_branch}, deleted)"
    echo -e "  ${BOLD}Complexity:${RESET} ${complexity}"
    echo -e "  ${BOLD}Status:${RESET}     resolved"
    echo ""
}
