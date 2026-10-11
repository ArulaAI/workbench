#!/usr/bin/env bash
# verify.sh — Blind verification command

_print_verify_report() {
    local json="$1"

    echo ""
    echo -e "  ${BOLD}Verification Report:${RESET}"

    # 1. Core question
    local answerable
    answerable=$(echo "$json" | jq -r '.core_question_answerable // empty' 2>/dev/null)
    if [[ "$answerable" == "true" ]]; then
        echo -e "    ${COLOR_SUCCESS}${SYM_CHECK} Core question: answerable${RESET}"
    elif [[ "$answerable" == "false" ]]; then
        echo -e "    ${COLOR_ERROR}${SYM_CROSS} Core question: not answerable${RESET}"
    fi

    # 2. Spec requirements
    local total_reqs covered_reqs
    total_reqs=$(echo "$json" | jq '[.spec_requirements // [] | .[] ] | length' 2>/dev/null) || total_reqs=0
    covered_reqs=$(echo "$json" | jq '[.spec_requirements // [] | .[] | select(.status == "covered")] | length' 2>/dev/null) || covered_reqs=0

    if [[ "$total_reqs" -gt 0 ]]; then
        echo -e "    ${BOLD}Spec requirements:${RESET} ${covered_reqs} of ${total_reqs} covered"

        # Print non-covered requirements
        local non_covered
        non_covered=$(echo "$json" | jq -c '.spec_requirements // [] | .[] | select(.status == "covered" | not)' 2>/dev/null)
        while IFS= read -r req; do
            [[ -z "$req" ]] && continue
            local req_text req_status spec_says plan_says task_id
            req_text=$(echo "$req" | jq -r '.requirement // "unknown"')
            req_status=$(echo "$req" | jq -r '.status // "unknown"')
            spec_says=$(echo "$req" | jq -r '.spec_says // empty')
            plan_says=$(echo "$req" | jq -r '.plan_says // empty')
            task_id=$(echo "$req" | jq -r '.task // empty')

            echo -e "    ${COLOR_ERROR}${SYM_CROSS} ${req_text} ${COLOR_DIM}(status: ${req_status})${RESET}"
            if [[ -n "$spec_says" ]] || [[ -n "$plan_says" ]] || [[ -n "$task_id" ]]; then
                local detail=""
                [[ -n "$spec_says" ]] && detail+="Spec says: ${spec_says}"
                [[ -n "$plan_says" ]] && { [[ -n "$detail" ]] && detail+=" | "; detail+="Plan says: ${plan_says}"; }
                [[ -n "$task_id" ]] && { [[ -n "$detail" ]] && detail+=" | "; detail+="Task: ${task_id}"; }
                echo -e "      ${COLOR_DIM}${detail}${RESET}"
            fi
        done <<< "$non_covered"
    fi

    # 3. Semantic drift
    local drift_count
    drift_count=$(echo "$json" | jq '[.semantic_drift // [] | .[]] | length' 2>/dev/null) || drift_count=0
    if [[ "$drift_count" -gt 0 ]]; then
        echo "$json" | jq -c '.semantic_drift[] ' 2>/dev/null | while IFS= read -r drift; do
            [[ -z "$drift" ]] && continue
            local spec_term plan_term risk
            spec_term=$(echo "$drift" | jq -r '.spec_term // "?"')
            plan_term=$(echo "$drift" | jq -r '.plan_term // "?"')
            risk=$(echo "$drift" | jq -r '.risk // ""')
            echo -e "    ${COLOR_WARN}${SYM_WARN} \"${spec_term}\" ${SYM_ARROW} \"${plan_term}\": ${risk}${RESET}"
        done
    fi

    # 4. Critical failures
    local failure_count
    failure_count=$(echo "$json" | jq '[.critical_failures // [] | .[]] | length' 2>/dev/null) || failure_count=0
    if [[ "$failure_count" -gt 0 ]]; then
        echo "$json" | jq -c '.critical_failures[]' 2>/dev/null | while IFS= read -r failure; do
            [[ -z "$failure" ]] && continue
            local desc spec_ref plan_gap
            desc=$(echo "$failure" | jq -r '.description // "unknown"')
            spec_ref=$(echo "$failure" | jq -r '.spec_reference // empty')
            plan_gap=$(echo "$failure" | jq -r '.plan_gap // empty')

            echo -e "    ${COLOR_ERROR}${SYM_CROSS} ${desc}${RESET}"
            if [[ -n "$spec_ref" ]] || [[ -n "$plan_gap" ]]; then
                local detail=""
                [[ -n "$spec_ref" ]] && detail+="Spec: ${spec_ref}"
                [[ -n "$plan_gap" ]] && { [[ -n "$detail" ]] && detail+=" | "; detail+="Gap: ${plan_gap}"; }
                echo -e "      ${COLOR_DIM}${detail}${RESET}"
            fi
        done
    fi

    # 5. Recommendations
    local rec_count
    rec_count=$(echo "$json" | jq '[.recommendations // [] | .[]] | length' 2>/dev/null) || rec_count=0
    if [[ "$rec_count" -gt 0 ]]; then
        echo "$json" | jq -r '.recommendations[]' 2>/dev/null | while IFS= read -r rec; do
            [[ -z "$rec" ]] && continue
            echo -e "    ${COLOR_INFO}${SYM_ARROW} ${rec}${RESET}"
        done
    fi

    # 6. Summary line
    local warn_count="$drift_count"
    echo ""
    echo -e "  ${BOLD}Summary:${RESET} ${failure_count} critical, ${warn_count} warnings, ${rec_count} recommendations"
    echo ""
}

# Print human escalation for needs_human items from Fix Agent output.
# Usage: _print_human_escalation "$fix_json"
_print_human_escalation() {
    local fix_json="$1"

    echo ""
    echo -e "  ${COLOR_WARN}Cannot auto-fix — requires your judgment:${RESET}"
    echo ""

    echo "$fix_json" | jq -c '.needs_human // [] | .[]' 2>/dev/null | while IFS= read -r item; do
        [[ -z "$item" ]] && continue
        local task_id file issue spec_says plan_says
        task_id=$(echo "$item" | jq -r '.task_id // "?"')
        file=$(echo "$item" | jq -r '.file // "?"')
        issue=$(echo "$item" | jq -r '.issue // "unknown"')
        spec_says=$(echo "$item" | jq -r '.spec_says // empty')
        plan_says=$(echo "$item" | jq -r '.plan_says // empty')

        echo -e "  Task ${task_id} (${COLOR_DIM}${file}${RESET}):"
        echo -e "    ${COLOR_DIM}Issue: ${issue}${RESET}"
        [[ -n "$spec_says" ]] && echo -e "    ${COLOR_DIM}Spec says: ${spec_says}${RESET}"
        [[ -n "$plan_says" ]] && echo -e "    ${COLOR_DIM}Plan says: ${plan_says}${RESET}"

        local options
        options=$(echo "$item" | jq -r '.options // [] | .[]' 2>/dev/null)
        if [[ -n "$options" ]]; then
            local opt_num=0
            echo -e "    ${COLOR_DIM}Options:${RESET}"
            echo "$options" | while IFS= read -r opt; do
                ((opt_num++)) || true
                echo -e "      ${COLOR_DIM}${opt_num}. ${opt}${RESET}"
            done
        fi
        echo ""
    done

    echo -e "  After fixing, run: ${COLOR_STEP}speed verify${RESET}"
    echo ""
}

# Print human escalation from verification JSON (critical failures + needs_human items).
# Usage: _print_human_escalation_from_verify "$verify_json"
_print_human_escalation_from_verify() {
    local verify_json="$1"

    local cf_count nh_count
    cf_count=$(echo "$verify_json" | jq '[.critical_failures // [] | .[]] | length' 2>/dev/null) || cf_count=0
    nh_count=$(echo "$verify_json" | jq '[.needs_human // [] | .[]] | length' 2>/dev/null) || nh_count=0
    [[ "$cf_count" -eq 0 ]] && [[ "$nh_count" -eq 0 ]] && return

    echo ""
    echo -e "  ${COLOR_WARN}Cannot auto-fix — requires your judgment:${RESET}"
    echo ""

    # Print critical failures
    echo "$verify_json" | jq -c '.critical_failures // [] | .[]' 2>/dev/null | while IFS= read -r failure; do
        [[ -z "$failure" ]] && continue
        local desc spec_ref plan_gap
        desc=$(echo "$failure" | jq -r '.description // "unknown"')
        spec_ref=$(echo "$failure" | jq -r '.spec_reference // empty')
        plan_gap=$(echo "$failure" | jq -r '.plan_gap // empty')

        echo -e "    ${COLOR_DIM}Issue: ${desc}${RESET}"
        [[ -n "$spec_ref" ]] && echo -e "    ${COLOR_DIM}Spec says: ${spec_ref}${RESET}"
        [[ -n "$plan_gap" ]] && echo -e "    ${COLOR_DIM}Plan says: ${plan_gap}${RESET}"
        echo ""
    done

    # Print needs_human items (if verifier classified them separately)
    echo "$verify_json" | jq -c '.needs_human // [] | .[]' 2>/dev/null | while IFS= read -r item; do
        [[ -z "$item" ]] && continue
        local desc spec_ref plan_gap
        desc=$(echo "$item" | jq -r '.description // "unknown"')
        spec_ref=$(echo "$item" | jq -r '.spec_reference // empty')
        plan_gap=$(echo "$item" | jq -r '.plan_gap // empty')

        echo -e "    ${COLOR_DIM}Issue: ${desc}${RESET}"
        [[ -n "$spec_ref" ]] && echo -e "    ${COLOR_DIM}Spec says: ${spec_ref}${RESET}"
        [[ -n "$plan_gap" ]] && echo -e "    ${COLOR_DIM}Plan says: ${plan_gap}${RESET}"
        echo ""
    done

    echo -e "  After fixing, run: ${COLOR_STEP}speed verify${RESET}"
    echo ""
}

# Print fix summary after auto-fix loop completes.
# Usage: _print_fix_summary "$all_fixes_json" "$total_fixes"
_print_fix_summary() {
    local fixes_json="$1"
    local count="$2"

    echo ""
    echo -e "  ${BOLD}Auto-fixed ${count} issue(s):${RESET}"

    echo "$fixes_json" | jq -c '.[]' 2>/dev/null | while IFS= read -r fix; do
        [[ -z "$fix" ]] && continue
        local task_id field before after
        task_id=$(echo "$fix" | jq -r '.task_id // "?"')
        field=$(echo "$fix" | jq -r '.field // "?"')
        before=$(echo "$fix" | jq -r '.before // "?"')
        after=$(echo "$fix" | jq -r '.after // "?"')
        local reason
        reason=$(echo "$fix" | jq -r '.reason // empty')
        echo -e "    Task ${task_id}: ${field} ${before} ${SYM_ARROW} ${after}${reason:+ (${reason})}"
    done
    echo ""
}

# Build the verification message from current task plan + spec + contract.
# IMPORTANT (load-bearing): This function intentionally sets variables in caller scope — no 'local'
# inside. The caller MUST declare these as local before calling, e.g.:
#   local task_plan="" contract_section="" verify_message=""
#   _build_verify_message
# Sets variables: task_plan, contract_section, verify_message
# Requires: spec_content (set by caller), TASKS_DIR, CONTRACT_FILE
_build_verify_message() {
    task_plan=""
    for f in "${TASKS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        local id title desc criteria deps files
        id=$(jq -r '.id' "$f")
        title=$(jq -r '.title' "$f")
        desc=$(jq -r '.description' "$f")
        criteria=$(jq -r '.acceptance_criteria' "$f")
        deps=$(jq -r '.depends_on | join(", ")' "$f")
        files=$(jq -r '.files_touched // [] | join(", ")' "$f")

        task_plan+="### Task ${id}: ${title}
Description: ${desc}
Acceptance Criteria: ${criteria}
Depends On: ${deps}
Files: ${files}

"
    done

    contract_section=""
    if [[ -f "${CONTRACT_FILE}" ]]; then
        contract_section="
## Data Model Contract
$(cat "${CONTRACT_FILE}")
"
    fi

    verify_message="## Product Specification

${spec_content}

## Task Plan

${task_plan}
${contract_section}

Verify this plan against the product specification. Read the spec FIRST, form your own understanding, THEN check the plan."
}

# Files the Fix Agent may edit: every task JSON, then the plan's contract.
_verify_fix_files_content() {
    local f
    for f in "${TASKS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        printf -- '--- FILE: %s ---\n%s\n\n' "$f" "$(cat "$f")"
    done
    if [[ -n "${CONTRACT_FILE:-}" && -f "$CONTRACT_FILE" ]]; then
        printf -- '--- FILE: %s (contract) ---\n%s\n\n' "$CONTRACT_FILE" "$(cat "$CONTRACT_FILE")"
    fi
}

# Snapshot the files the Fix Agent may edit: task JSONs and the contract.
# Prints the snapshot directory.
_verify_snapshot_plan_files() {
    local snap
    snap=$(mktemp -d)
    mkdir -p "${snap}/tasks"
    cp "${TASKS_DIR}"/*.json "${snap}/tasks/" 2>/dev/null || true
    [[ -n "${CONTRACT_FILE:-}" && -f "$CONTRACT_FILE" ]] && cp "$CONTRACT_FILE" "${snap}/contract.json"
    echo "$snap"
}

# Put back any task file or contract the Fix Agent left unreadable, keeping its
# valid edits. An invalid task file made the next jq call end verify with jq's
# own exit code.
_verify_restore_invalid_files() {
    local snap="$1" f name
    [[ -n "$snap" && -d "$snap" ]] || return 0
    for f in "${TASKS_DIR}"/*.json; do
        [[ -f "$f" ]] || continue
        jq -e 'type == "object"' "$f" >/dev/null 2>&1 && continue
        name=$(basename "$f")
        if [[ -f "${snap}/tasks/${name}" ]]; then
            cp "${snap}/tasks/${name}" "$f"
            log_warn "Fix Agent left ${name} invalid; restored the previous version"
        else
            rm -f "$f"
            log_warn "Fix Agent created an invalid ${name}; removed it"
        fi
    done
    if [[ -n "${CONTRACT_FILE:-}" && -f "${snap}/contract.json" ]] && ! jq empty "$CONTRACT_FILE" 2>/dev/null; then
        cp "${snap}/contract.json" "$CONTRACT_FILE"
        log_warn "Fix Agent left the contract invalid; restored the previous version"
    fi
    rm -rf "$snap"
}

cmd_verify() {
    _require_feature "$GLOBAL_FEATURE"
    _require_readable_tasks
    log_header "Verifying Plan Against Spec"

    # Check prerequisites
    local total
    total=$(task_count_total)
    if [[ "$total" -eq 0 ]]; then
        log_error "No tasks found. Run 'speed plan <spec>' first."
        exit 1
    fi

    local spec_file
    spec_file=$(_get_spec_path)
    if [[ -z "$spec_file" ]] || [[ ! -f "$spec_file" ]]; then
        log_error "Product spec not found. Run 'speed plan <spec-file>' first."
        exit 1
    fi

    local spec_content spec_documents_file
    spec_documents_file=$(_get_spec_documents_file)
    if [[ -n "$spec_documents_file" ]]; then
        # Plan was made with --feature: verify against every planned document
        local _kind _rel
        log_step "Reading feature specs ($(grep -c . "$spec_documents_file") documents):"
        while IFS=$'\t' read -r _kind _rel; do
            [[ -n "$_rel" ]] && log_step "  $(printf '%-13s' "${_kind}:") ${COLOR_STEP}${_rel}${RESET}"
        done < "$spec_documents_file"
        if ! spec_content=$(_get_spec_documents_content "$spec_documents_file"); then
            log_error "The plan's documents have changed. Re-run 'speed plan --feature ${FEATURE_NAME}' first."
            exit "$EXIT_CONFIG_ERROR"
        fi
    else
        log_step "Reading product spec: ${COLOR_STEP}${spec_file}${RESET}"
        spec_content=$(cat "$spec_file")
    fi

    # Build verification message — structured assembly with fallback
    log_step "Gathering task plan (${total} tasks)..."

    # Load cross-cutting concerns
    local cc_json_verify=""
    if [[ -f "${FEATURE_DIR}/cross_cutting_concerns.json" ]]; then
        cc_json_verify=$(cat "${FEATURE_DIR}/cross_cutting_concerns.json")
    fi

    local task_plan="" contract_section="" verify_message=""
    verify_message=$(context_assemble_verifier \
        "$spec_content" \
        "${TASKS_DIR}" \
        "$cc_json_verify" \
        "${CONTRACT_FILE}" 2>/dev/null) || verify_message=""

    # Fallback to inline message
    if [[ -z "$verify_message" ]]; then
        _build_verify_message
    fi

    # ── Spec traceability: check spec-to-task coverage ────────────
    # Identifies spec requirements not covered by any task and injects
    # the gaps into the verifier's context.
    local traceability_output
    traceability_output=$(context_spec_traceability "$spec_content" "${TASKS_DIR}" 2>/dev/null) || traceability_output=""

    if [[ -n "$traceability_output" ]]; then
        # Append coverage data to verifier message
        verify_message+=$'\n\n'"${traceability_output}"
        # Show coverage summary
        if echo "$traceability_output" | grep -q "uncovered"; then
            log_warn "Spec traceability found uncovered requirements — included in verifier context"
        else
            log_success "Spec traceability: all requirements covered"
        fi
    fi

    log_step "Sending to Plan Verifier agent (blind check)..."
    echo ""

    local verify_output
    if ! verify_output=$(provider_run \
        "${AGENTS_DIR}/plan-verifier.md" \
        "$verify_message" \
        "$MODEL_PLANNING" \
        "$AGENT_TOOLS_READONLY" \
        "Verifier"); then
        log_error "Plan Verifier agent failed — check agent CLI connection"
        exit 1
    fi

    if [[ -z "$verify_output" ]]; then
        log_error "Plan Verifier agent returned empty output"
        exit 1
    fi

    # Save raw output to log
    echo "$verify_output" > "${LOGS_DIR}/plan-verification.log"
    log_success "Verification report saved to ${LOGS_DIR}/plan-verification.log"

    # Parse JSON from agent output (handles markdown, code fences, prose)
    local verify_json
    verify_json=$(parse_agent_json "$verify_output") || {
        log_error "Plan Verifier returned unparseable output"
        log_error "Review raw output: ${LOGS_DIR}/plan-verification.log"
        exit 1
    }

    # Print human-readable report
    _print_verify_report "$verify_json"

    # Extract status and act on it
    local status
    status=$(echo "$verify_json" | jq -r '.status // "unknown"')
    # A "pass" that still lists critical failures is not a pass.
    if [[ "$status" == "pass" ]] && [[ "$(echo "$verify_json" | jq '[.critical_failures // [] | .[]] | length')" -gt 0 ]]; then
        log_warn "Verifier said pass but listed critical failures; treating it as a failure"
        status="fail"
    fi

    if [[ "$status" == "pass" ]]; then
        log_success "Plan verification PASSED"
        echo -e "Next: ${COLOR_STEP}speed run${RESET} to execute tasks"
        echo ""
        return
    elif [[ "$status" != "fail" ]]; then
        log_error "Verifier gave no pass or fail verdict (status: ${status}); verification did not complete"
        log_error "Review ${LOGS_DIR}/plan-verification.log and re-run speed verify"
        exit 1
    fi

    # ── Status is "fail" — attempt auto-fix loop ─────────────────
    local failure_count rec_count_init verify_needs_human_count
    failure_count=$(echo "$verify_json" | jq '[.critical_failures // [] | .[]] | length' 2>/dev/null) || failure_count=0
    rec_count_init=$(echo "$verify_json" | jq '[.recommendations // [] | .[]] | length' 2>/dev/null) || rec_count_init=0
    verify_needs_human_count=$(echo "$verify_json" | jq '[.needs_human // [] | .[]] | length' 2>/dev/null) || verify_needs_human_count=0
    log_error "Plan verification FAILED — ${failure_count} critical issue(s) found"

    # If verifier classified all issues as needing human judgment, skip the fix loop (AC #14)
    if [[ "$verify_needs_human_count" -gt 0 ]] && [[ "$failure_count" -eq 0 ]] && [[ "$rec_count_init" -eq 0 ]]; then
        log_warn "All issues require human judgment — skipping auto-fix"
        _print_human_escalation_from_verify "$verify_json"
        exit 1
    fi

    # Gather task file contents for the Fix Agent
    local task_files_content
    task_files_content=$(_verify_fix_files_content)

    # Build the issues payload (critical_failures + recommendations)
    local issues_json
    issues_json=$(echo "$verify_json" | jq -c '{
        critical_failures: (.critical_failures // []),
        recommendations: (.recommendations // [])
    }' 2>/dev/null)

    # Track all fixes across iterations for the final summary
    local all_fixes_json="[]"
    local total_fixes=0
    local iteration=0
    local prev_failure_keys=""

    while [[ $iteration -lt $MAX_VERIFY_FIX_ITERATIONS ]]; do
        ((iteration++)) || true

        # Check if there are any auto-fixable issues
        local cf_count rec_count
        cf_count=$(echo "$issues_json" | jq '[.critical_failures // [] | .[]] | length' 2>/dev/null) || cf_count=0
        rec_count=$(echo "$issues_json" | jq '[.recommendations // [] | .[]] | length' 2>/dev/null) || rec_count=0

        if [[ "$cf_count" -eq 0 ]] && [[ "$rec_count" -eq 0 ]]; then
            break
        fi

        log_step "Fix attempt ${iteration}/${MAX_VERIFY_FIX_ITERATIONS}..."

        # Build Fix Agent system prompt (inline — no agent .md file)
        local fix_system_prompt
        fix_system_prompt=$(mktemp)
        cat > "$fix_system_prompt" << 'FIXPROMPT'
# Role: Plan Fix Agent

You are a mechanical fix agent. You receive a verification report listing issues with task JSON files, and the task files themselves. Your job is to apply ONLY the fixes described. Do NOT change anything else.

## Rules

- Read each issue in the verification report
- Determine if it can be fixed by editing a task JSON file (e.g., adjusting a threshold, adding missing detail, fixing a field value)
- The specification is included. Use it to decide what the spec actually says before editing; never add a requirement it does not state
- If an issue requires human judgment (ambiguous spec interpretation, architectural decisions, trade-offs between approaches), do NOT fix it — add it to `needs_human`
- Apply fixes by editing the task JSON files directly with the Edit or Write tool. You have no shell; do not try to run scripts
- The plan's contract file is listed with the task files. When a fix changes what a task builds, update the matching contract entry in the same pass, so task files and contract never disagree. Fix an issue about the contract alone by editing the contract file. Keep it valid JSON with the same structure
- Report exactly what you changed

## Output Format

```json
{
  "fixes_applied": [
    {
      "task_id": "1",
      "file": "path/to/task-1.json",
      "field": "field_name",
      "before": "old value",
      "after": "new value",
      "reason": "why this fix"
    }
  ],
  "needs_human": [
    {
      "task_id": "1",
      "file": "path/to/task-1.json",
      "issue": "description of the issue",
      "spec_says": "what the spec requires",
      "plan_says": "what the plan currently has",
      "options": ["option 1", "option 2"]
    }
  ]
}
```
FIXPROMPT

        local fix_message="## Verification Issues to Fix

${issues_json}

## Specification (ground truth the plan is checked against)

${spec_content}

## Task Files

${task_files_content}

Apply ONLY the fixes described above. Do NOT change anything else."

        local plan_snapshot
        plan_snapshot=$(_verify_snapshot_plan_files)

        local fix_output
        if ! fix_output=$(provider_run \
            "$fix_system_prompt" \
            "$fix_message" \
            "$MODEL_SUPPORT" \
            "$AGENT_TOOLS_WRITE" \
            "FixAgent"); then
            rm -f "$fix_system_prompt"
            _verify_restore_invalid_files "$plan_snapshot"
            log_error "Fix Agent failed — skipping auto-fix"
            break
        fi
        rm -f "$fix_system_prompt"
        _verify_restore_invalid_files "$plan_snapshot"

        if [[ -z "$fix_output" ]]; then
            log_error "Fix Agent returned empty output — skipping"
            break
        fi

        # Parse Fix Agent output
        local fix_json
        fix_json=$(parse_agent_json "$fix_output") || {
            log_error "Fix Agent returned unparseable output — skipping"
            break
        }

        # Log applied fixes
        local fix_count
        fix_count=$(echo "$fix_json" | jq '[.fixes_applied // [] | .[]] | length' 2>/dev/null) || fix_count=0

        if [[ "$fix_count" -gt 0 ]]; then
            echo "$fix_json" | jq -c '.fixes_applied[]' 2>/dev/null | while IFS= read -r fix; do
                [[ -z "$fix" ]] && continue
                local fix_task fix_field fix_before fix_after
                fix_task=$(echo "$fix" | jq -r '.task_id // "?"')
                fix_field=$(echo "$fix" | jq -r '.field // "?"')
                fix_before=$(echo "$fix" | jq -r '.before // "?"')
                fix_after=$(echo "$fix" | jq -r '.after // "?"')
                echo -e "  ${COLOR_SUCCESS}Auto-fixed: Task ${fix_task} — ${fix_field}: ${fix_before} ${SYM_ARROW} ${fix_after}${RESET}"
            done
            # Accumulate fixes for summary
            all_fixes_json=$(echo "$all_fixes_json" "$fix_json" | jq -s '.[0] + (.[1].fixes_applied // [])' 2>/dev/null)
            total_fixes=$((total_fixes + fix_count))
        fi

        # Print human escalation for needs_human items
        local human_count
        human_count=$(echo "$fix_json" | jq '[.needs_human // [] | .[]] | length' 2>/dev/null) || human_count=0

        if [[ "$human_count" -gt 0 ]]; then
            _print_human_escalation "$fix_json"
        fi

        # If no fixes were applied and all issues need human judgment, stop
        if [[ "$fix_count" -eq 0 ]]; then
            log_warn "No auto-fixable issues — all require human judgment"
            break
        fi

        # Re-run Plan Verifier
        log_step "Re-verifying plan after fixes..."
        echo ""

        # Re-build verification message (task files may have been edited by Fix Agent)
        _build_verify_message

        # Intentionally reuses verify_output (same local declared at top of function),
        # overwriting the initial verification result — correct, as only the latest
        # verification result matters within this loop.
        if ! verify_output=$(provider_run \
            "${AGENTS_DIR}/plan-verifier.md" \
            "$verify_message" \
            "$MODEL_PLANNING" \
            "$AGENT_TOOLS_READONLY" \
            "Verifier"); then
            log_error "Re-verification failed — check agent CLI connection"
            break
        fi

        if [[ -z "$verify_output" ]]; then
            log_error "Re-verification returned empty output"
            break
        fi

        # Save and parse re-verification
        echo "$verify_output" > "${LOGS_DIR}/plan-verification.log"

        verify_json=$(parse_agent_json "$verify_output") || {
            log_error "Re-verification returned unparseable output"
            break
        }

        _print_verify_report "$verify_json"

        status=$(echo "$verify_json" | jq -r '.status // "unknown"')
        if [[ "$status" == "pass" ]] && [[ "$(echo "$verify_json" | jq '[.critical_failures // [] | .[]] | length')" -gt 0 ]]; then
            status="fail"
        fi

        if [[ "$status" == "pass" ]]; then
            _print_fix_summary "$all_fixes_json" "$total_fixes"
            log_success "Plan verification PASSED (${total_fixes} issues auto-fixed)"
            echo -e "Next: ${COLOR_STEP}speed run${RESET} to execute tasks"
            echo ""
            return
        fi

        # Convergence check: extract current failure keys and compare
        local current_failure_keys
        current_failure_keys=$(echo "$verify_json" | jq -r '[.critical_failures // [] | .[] | .description] | sort | join("|||")' 2>/dev/null)

        if [[ "$current_failure_keys" == "$prev_failure_keys" ]] && [[ -n "$current_failure_keys" ]]; then
            log_warn "Same critical failures persist after fix — escalating to human"
            _print_human_escalation_from_verify "$verify_json"
            break
        fi

        prev_failure_keys="$current_failure_keys"

        # Update issues for next iteration
        issues_json=$(echo "$verify_json" | jq -c '{
            critical_failures: (.critical_failures // []),
            recommendations: (.recommendations // [])
        }' 2>/dev/null)

        # Re-gather task files (they may have been edited)
        task_files_content=$(_verify_fix_files_content)
    done

    # Loop exhausted or broke — print final summary
    if [[ "$total_fixes" -gt 0 ]]; then
        _print_fix_summary "$all_fixes_json" "$total_fixes"
    fi

    if [[ "$status" == "fail" ]]; then
        failure_count=$(echo "$verify_json" | jq '[.critical_failures // [] | .[]] | length' 2>/dev/null) || failure_count=0
        log_error "Plan verification FAILED — ${failure_count} critical issue(s) remain after ${iteration} fix attempt(s)"
        _print_human_escalation_from_verify "$verify_json"
        echo ""
        exit 1
    fi
}
