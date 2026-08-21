#!/usr/bin/env bash
# defect_triage.sh — Orchestration logic for the defect triage stage
#
# Sources lib/defects.sh for state management and lib/provider.sh for
# agent invocation. Implements the two-phase triage pipeline:
# investigation (free-form) then classification (structured JSON).
#
# Requires config.sh, log.sh, defects.sh, and provider.sh to be
# sourced first.

# ── JSON helper for boolean fields ─────────────────────────────────
# _defect_json_get uses jq's // empty which discards boolean false.
# This helper reads a value preserving false/null as literal strings.
# Args: file key

_triage_json_get_raw() {
    local file="$1" key="$2"
    _defect_ensure_json
    if [[ "$_defect_json_tool" == "jq" ]]; then
        jq -r "if .${key} == null then \"null\" elif .${key} == false then \"false\" elif .${key} == true then \"true\" else .${key} end" "$file"
    else
        python3 -c "
import json
with open('$file') as f:
    d = json.load(f)
v = d.get('$key')
if v is None:
    print('null')
elif isinstance(v, bool):
    print(str(v).lower())
else:
    print(v)
"
    fi
}

# ── resolve_related_specs ──────────────────────────────────────────
# Given a feature name from the defect report's Related Feature field,
# check for product and tech specs. Print found paths to stdout,
# warn to stderr if either is missing.
# Args: feature_name

resolve_related_specs() {
    local feature_name="$1"

    if [[ -z "$feature_name" ]]; then
        log_warn "No feature name provided for spec resolution" >&2
        return 0
    fi

    local product_spec="${PROJECT_ROOT}/specs/product/${feature_name}.md"
    local tech_spec="${PROJECT_ROOT}/specs/tech/${feature_name}.md"

    if [[ -f "$product_spec" ]]; then
        echo "$product_spec"
    else
        log_warn "Product spec not found: ${product_spec}" >&2
    fi

    if [[ -f "$tech_spec" ]]; then
        echo "$tech_spec"
    else
        log_warn "Tech spec not found: ${tech_spec}" >&2
    fi
}

# ── build_investigation_prompt ─────────────────────────────────────
# Assemble the investigation phase prompt by combining the triage
# agent definition (investigation section), the defect report,
# related specs, and agent file.
# Args: defect_report product_spec tech_spec
# Output: assembled prompt to stdout

build_investigation_prompt() {
    local defect_report="$1"
    local product_spec="${2:-}"
    local tech_spec="${3:-}"

    local prompt=""

    # Triage agent definition
    if [[ -f "${AGENTS_DIR}/triage.md" ]]; then
        prompt+="$(cat "${AGENTS_DIR}/triage.md")"
        prompt+=$'\n\n---\n\n'
    fi

    # Project conventions
    if [[ -n "$AGENT_FILE_PATH" ]] && [[ -f "$AGENT_FILE_PATH" ]]; then
        prompt+="## Project Conventions (${AGENT_FILE})"$'\n\n'
        prompt+="$(cat "$AGENT_FILE_PATH")"
        prompt+=$'\n\n---\n\n'
    fi

    # Defect report
    prompt+="## Defect Report"$'\n\n'
    if [[ -f "$defect_report" ]]; then
        prompt+="$(cat "$defect_report")"
    else
        prompt+="(defect report file not found: ${defect_report})"
    fi
    prompt+=$'\n\n---\n\n'

    # Related product spec
    if [[ -n "$product_spec" && -f "$product_spec" ]]; then
        prompt+="## Related Product Spec"$'\n\n'
        prompt+="$(cat "$product_spec")"
        prompt+=$'\n\n---\n\n'
    fi

    # Related tech spec
    if [[ -n "$tech_spec" && -f "$tech_spec" ]]; then
        prompt+="## Related Tech Spec"$'\n\n'
        prompt+="$(cat "$tech_spec")"
        prompt+=$'\n\n---\n\n'
    fi

    prompt+="Begin Phase 1 investigation. Read the defect report, related specs, and trace through the codebase to locate the root cause."

    echo "$prompt"
}

# ── build_classification_prompt ────────────────────────────────────
# Assemble the classification phase prompt from the investigation
# transcript and the triage agent's classification section.
# Args: investigation_transcript
# Output: prompt to stdout

build_classification_prompt() {
    local investigation_transcript="$1"

    local prompt=""

    # Triage agent definition (classification section)
    if [[ -f "${AGENTS_DIR}/triage.md" ]]; then
        prompt+="$(cat "${AGENTS_DIR}/triage.md")"
        prompt+=$'\n\n---\n\n'
    fi

    # Investigation transcript
    prompt+="## Investigation Transcript"$'\n\n'
    prompt+="$investigation_transcript"
    prompt+=$'\n\n---\n\n'

    prompt+="Phase 1 investigation is complete above. Now produce the Phase 2 classification JSON. Output only the triage JSON object matching the schema from the agent definition."

    echo "$prompt"
}

# ── escalate_to_feature ────────────────────────────────────────────
# When complexity=complex, generate a draft PRD from the defect report.
# Args: name

escalate_to_feature() {
    local name="$1"

    local prd_path
    prd_path=$(defect_escalate_to_prd "$name")
    local rc=$?

    if [[ $rc -ne 0 ]]; then
        log_error "Failed to escalate defect '${name}' to feature PRD"
        return 1
    fi

    echo "$prd_path"
}

# ── print_triage_summary ──────────────────────────────────────────
# Format and print triage results to stdout.
# Args: name

print_triage_summary() {
    local name="$1"

    _defect_ensure_json

    local triage_file
    triage_file="$(_defect_dir "$name")/triage.json"

    if [[ ! -f "$triage_file" ]]; then
        log_error "No triage.json found for defect '${name}'"
        return 1
    fi

    local is_defect complexity defect_type root_cause
    local blast_radius suggested_approach

    is_defect=$(_triage_json_get_raw "$triage_file" "is_defect")
    complexity=$(_defect_json_get "$triage_file" "complexity")
    defect_type=$(_defect_json_get "$triage_file" "defect_type")
    root_cause=$(_defect_json_get "$triage_file" "root_cause_hypothesis")
    blast_radius=$(_defect_json_get "$triage_file" "blast_radius")
    suggested_approach=$(_defect_json_get "$triage_file" "suggested_approach")

    echo ""
    log_header "Triage Summary: ${name}"

    if [[ "$is_defect" == "false" ]]; then
        local explanation
        explanation=$(_defect_json_get "$triage_file" "root_cause_hypothesis")
        log_info "Not a defect: ${explanation}"
        return 0
    fi

    log_info "Complexity:        ${complexity}"
    log_info "Defect type:       ${defect_type}"
    log_info "Root cause:        ${root_cause}"
    log_info "Blast radius:      ${blast_radius}"
    log_info "Suggested approach: ${suggested_approach}"

    # Affected files
    if [[ "$_defect_json_tool" == "jq" ]]; then
        local affected_files
        affected_files=$(jq -r '.affected_files[]? // empty' "$triage_file" 2>/dev/null)
        if [[ -n "$affected_files" ]]; then
            log_info "Affected files:"
            echo "$affected_files" | while IFS= read -r f; do
                echo "    ${f}"
            done
        fi
    else
        local affected_files
        affected_files=$(python3 -c "
import json
with open('$triage_file') as f:
    d = json.load(f)
for af in d.get('affected_files', []):
    print(af)
" 2>/dev/null)
        if [[ -n "$affected_files" ]]; then
            log_info "Affected files:"
            echo "$affected_files" | while IFS= read -r f; do
                echo "    ${f}"
            done
        fi
    fi
}

# ── route_by_complexity ────────────────────────────────────────────
# Read triage.json complexity field and route accordingly.
# Returns 0 for trivial (caller continues), 1 for moderate/complex (caller stops).
# Args: name

route_by_complexity() {
    local name="$1"

    _defect_ensure_json

    local triage_file
    triage_file="$(_defect_dir "$name")/triage.json"

    if [[ ! -f "$triage_file" ]]; then
        log_error "No triage.json found for defect '${name}'"
        return 1
    fi

    local is_defect complexity
    is_defect=$(_triage_json_get_raw "$triage_file" "is_defect")
    complexity=$(_defect_json_get "$triage_file" "complexity")

    # Not a defect — rejected
    if [[ "$is_defect" == "false" ]]; then
        local explanation
        explanation=$(_defect_json_get "$triage_file" "root_cause_hypothesis")
        log_info "Rejected: ${explanation}"
        return 1
    fi

    case "$complexity" in
        trivial)
            log_step "Proceeding to fix automatically"
            return 0
            ;;
        moderate)
            log_step "Human review required. Run: speed run --defect ${name}"
            return 1
            ;;
        complex)
            local prd_path
            prd_path=$(escalate_to_feature "$name")
            if [[ -n "$prd_path" ]]; then
                log_step "Escalated to feature. PRD draft: ${prd_path}"
            fi
            return 1
            ;;
        *)
            log_error "Unknown complexity '${complexity}' for defect '${name}'"
            return 1
            ;;
    esac
}

# ── triage_defect ──────────────────────────────────────────────────
# Main orchestrator for the triage stage.
# Args: spec_path

triage_defect() {
    local spec_path="$1"

    # 1. Validate defect report
    if ! validate_defect_report "$spec_path"; then
        log_error "Defect report validation failed: ${spec_path}"
        return 1
    fi

    # 2. Extract defect name from filename
    local name
    name=$(defect_name_from_path "$spec_path")

    # 3. Initialize defect directory and state
    if ! init_defect_dir "$name" "$spec_path"; then
        log_error "Failed to initialize defect directory for '${name}'"
        return 1
    fi

    if ! create_defect_state "$name" "$spec_path"; then
        log_error "Failed to create defect state for '${name}'"
        return 1
    fi

    # 4. Transition to triaging
    if ! transition_defect_state "$name" "triaging"; then
        log_error "State transition to 'triaging' failed for '${name}'"
        return 1
    fi

    # 5. Resolve related specs
    local product_spec="" tech_spec=""
    local feature_name
    feature_name=$(grep -i '^Related Feature:' "$spec_path" | head -1 \
        | sed 's/^[Rr]elated[[:space:]]*[Ff]eature:[[:space:]]*//' | tr -d '[:space:]')

    if [[ -n "$feature_name" ]]; then
        local spec_paths
        spec_paths=$(resolve_related_specs "$feature_name" 2>/dev/null)

        # Parse found paths (product spec and tech spec)
        while IFS= read -r resolved_path; do
            [[ -z "$resolved_path" ]] && continue
            if echo "$resolved_path" | grep -q "specs/product/"; then
                product_spec="$resolved_path"
            elif echo "$resolved_path" | grep -q "specs/tech/"; then
                tech_spec="$resolved_path"
            fi
        done <<< "$spec_paths"
    fi

    # 6. Build and run investigation phase
    local defect_dir
    defect_dir="$(_defect_dir "$name")"
    local report_file="${defect_dir}/report.md"

    log_step "Starting triage investigation for '${name}'..."

    local investigation_prompt
    investigation_prompt=$(build_investigation_prompt "$report_file" "$product_spec" "$tech_spec")

    local investigation_output
    local investigation_rc=0

    # Write prompt to temp file for provider_run
    local prompt_file
    prompt_file=$(mktemp)
    echo "$investigation_prompt" > "$prompt_file"

    investigation_output=$(provider_run \
        "${AGENTS_DIR}/triage.md" \
        "$investigation_prompt" \
        "$MODEL_SUPPORT" \
        "$AGENT_TOOLS_READONLY" \
        "Triage") || investigation_rc=$?

    rm -f "$prompt_file"

    if [[ $investigation_rc -ne 0 || -z "$investigation_output" ]]; then
        log_error "Triage investigation failed for '${name}'"
        echo "$investigation_output" > "${defect_dir}/logs/triage.log" 2>/dev/null
        return 1
    fi

    # Save investigation transcript
    echo "$investigation_output" > "${defect_dir}/logs/investigation.log"

    # 7. Build and run classification phase
    log_step "Running triage classification..."

    local classification_prompt
    classification_prompt=$(build_classification_prompt "$investigation_output")

    local classification_output
    local classification_rc=0

    classification_output=$(provider_run \
        "${AGENTS_DIR}/triage.md" \
        "$classification_prompt" \
        "$MODEL_SUPPORT" \
        "" \
        "Classify") || classification_rc=$?

    if [[ $classification_rc -ne 0 || -z "$classification_output" ]]; then
        log_error "Triage classification failed for '${name}'"
        echo "$classification_output" > "${defect_dir}/logs/triage.log" 2>/dev/null
        return 1
    fi

    # 8. Parse and validate triage JSON output
    local triage_json
    triage_json=$(parse_agent_json "$classification_output")
    local parse_rc=$?

    if [[ $parse_rc -ne 0 || -z "$triage_json" ]]; then
        log_error "Triage output parse error"
        echo "$classification_output" > "${defect_dir}/logs/triage.log"
        return 1
    fi

    # Write triage output (validates required fields and updates state.json)
    if ! echo "$triage_json" | write_triage_output "$name"; then
        log_error "Triage output validation failed for '${name}'"
        echo "$classification_output" > "${defect_dir}/logs/triage.log"
        return 1
    fi

    # 9. Transition to triaged (or rejected/escalated)
    local is_defect complexity
    is_defect=$(_triage_json_get_raw "${defect_dir}/triage.json" "is_defect")
    complexity=$(_defect_json_get "${defect_dir}/triage.json" "complexity")

    local target_state="triaged"
    if [[ "$is_defect" == "false" ]]; then
        target_state="rejected"
    elif [[ "$complexity" == "complex" ]]; then
        target_state="escalated"
    fi

    if ! transition_defect_state "$name" "$target_state"; then
        log_error "State transition to '${target_state}' failed for '${name}'"
        return 1
    fi

    # 10. Print triage summary
    print_triage_summary "$name"

    # 11. Route by complexity
    route_by_complexity "$name"
}
