#!/usr/bin/env bash
# audit.sh — Spec audit command

cmd_audit() {
    local spec_file="${1:-}"

    # ── Argument validation ────────────────────────────────────
    if [[ -z "$spec_file" ]]; then
        log_error "Usage: speed audit <spec-file>"
        exit 1
    fi

    # Resolve file path (PROJECT_ROOT fallback)
    if [[ ! -f "$spec_file" ]]; then
        if [[ -f "${PROJECT_ROOT}/${spec_file}" ]]; then
            spec_file="${PROJECT_ROOT}/${spec_file}"
        else
            log_error_block \
                "Spec file not found: ${spec_file}" \
                "The audit command requires a spec file" \
                "Create the spec or check the path"
            exit $EXIT_CONFIG_ERROR
        fi
    fi

    log_header "Spec Audit"

    # ── Spec type detection ────────────────────────────────────
    # Strip everything up to "specs/" so both specs/tech/foo.md
    # and speed/specs/tech/foo.md resolve to the same type.
    local spec_type="" template_file=""
    local rel_path="${spec_file#${PROJECT_ROOT}/}"
    local after_specs="${rel_path#*specs/}"

    case "$after_specs" in
        product/*)  spec_type="prd";    template_file="${TEMPLATES_DIR}/prd.md" ;;
        tech/*)     spec_type="rfc";    template_file="${TEMPLATES_DIR}/rfc.md" ;;
        design/*)   spec_type="design"; template_file="${TEMPLATES_DIR}/design.md" ;;
        defects/*)  spec_type="defect"; template_file="${TEMPLATES_DIR}/defect.md" ;;
        *)
            log_error_block \
                "Unrecognized spec path: ${rel_path}" \
                "Cannot determine spec type from file location" \
                "Spec must be under a specs/ directory with product/, tech/, design/, or defects/ subdirs"
            exit $EXIT_CONFIG_ERROR
            ;;
    esac

    # ── Template loading ───────────────────────────────────────
    if [[ ! -f "$template_file" ]]; then
        log_error_block \
            "Template not found: ${template_file}" \
            "Cannot load structural template for ${spec_type} spec" \
            "Ensure SPEED templates are installed"
        exit $EXIT_CONFIG_ERROR
    fi

    local template_content
    template_content=$(cat "$template_file")

    log_step "Spec type: ${COLOR_STEP}${spec_type}${RESET}"
    log_step "Spec file: ${COLOR_STEP}${rel_path}${RESET}"
    log_step "Template:  ${COLOR_STEP}${template_file}${RESET}"

    # Read spec content
    local spec_content
    spec_content=$(cat "$spec_file")

    # ── Cross-reference resolution ─────────────────────────────
    local linked_prd_content=""
    local spec_dir
    spec_dir=$(dirname "$spec_file")

    # Look for "> See [...](...)" markdown links in the spec
    local linked_path=""
    linked_path=$(grep -oE '> See \[[^]]*\]\([^)]+\)' "$spec_file" \
        | sed 's/.*(\(.*\))/\1/' \
        | head -1 || true)

    if [[ -n "$linked_path" ]]; then
        # Resolve relative path against the spec file's directory
        local resolved_path=""
        if [[ "$linked_path" == /* ]]; then
            resolved_path="$linked_path"
        elif [[ -f "${spec_dir}/${linked_path}" ]]; then
            resolved_path="${spec_dir}/${linked_path}"
        elif [[ -f "${PROJECT_ROOT}/${linked_path}" ]]; then
            resolved_path="${PROJECT_ROOT}/${linked_path}"
        fi

        if [[ -n "$resolved_path" ]] && [[ -f "$resolved_path" ]]; then
            linked_prd_content=$(cat "$resolved_path")
            log_step "Linked spec: ${COLOR_STEP}${resolved_path}${RESET}"
        else
            log_warn "Linked spec not found: ${linked_path}"
        fi
    fi

    # For defects: parse "**Related Feature:**" field
    if [[ "$spec_type" == "defect" ]]; then
        local related_feature=""
        related_feature=$(grep -E '^\*\*Related Feature:\*\*' "$spec_file" \
            | sed 's/\*\*Related Feature:\*\*[[:space:]]*//' \
            | head -1 || true)

        if [[ -n "$related_feature" ]]; then
            local related_path=""
            if [[ -f "${PROJECT_ROOT}/${related_feature}" ]]; then
                related_path="${PROJECT_ROOT}/${related_feature}"
            elif [[ -f "${spec_dir}/${related_feature}" ]]; then
                related_path="${spec_dir}/${related_feature}"
            fi

            if [[ -n "$related_path" ]] && [[ -f "$related_path" ]]; then
                local related_content
                related_content=$(cat "$related_path")
                linked_prd_content+="\n\n### Related Feature: ${related_feature}\n\n${related_content}"
                log_step "Related feature: ${COLOR_STEP}${related_path}${RESET}"
            else
                log_warn "Related feature spec not found: ${related_feature}"
            fi
        fi
    fi

    # ── Vision file ────────────────────────────────────────────
    local vision_content="No product vision found"
    local overview_file="${PROJECT_ROOT}/${VISION_FILE}"
    if [[ -f "$overview_file" ]]; then
        vision_content=$(cat "$overview_file")
        log_step "Vision:    ${COLOR_STEP}${overview_file}${RESET}"
    else
        log_warn "Product vision not found at ${overview_file}"
    fi

    # ── Existing specs list ────────────────────────────────────
    local existing_specs=""
    if [[ -d "${PROJECT_ROOT}/specs" ]]; then
        existing_specs=$(find "${PROJECT_ROOT}/specs/" -name '*.md' -type f \
            | sort \
            | sed "s|${PROJECT_ROOT}/||")
    fi

    # ── Parent RFC resolution (RFC specs only) ──────────────────
    local parent_rfc_content=""
    local parent_rfc_path=""
    local child_rfc_list=""

    if [[ "$spec_type" == "rfc" ]]; then
        # Check if this RFC has a "> Parent RFC:" header
        parent_rfc_path=$(grep -oE '> Parent RFC: \[[^]]*\]\([^)]+\)' "$spec_file" \
            | sed 's/.*(\(.*\))/\1/' \
            | head -1 || true)

        if [[ -n "$parent_rfc_path" ]]; then
            local resolved_parent=""
            if [[ -f "${spec_dir}/${parent_rfc_path}" ]]; then
                resolved_parent="${spec_dir}/${parent_rfc_path}"
            elif [[ -f "${PROJECT_ROOT}/${parent_rfc_path}" ]]; then
                resolved_parent="${PROJECT_ROOT}/${parent_rfc_path}"
            fi

            if [[ -n "$resolved_parent" ]] && [[ -f "$resolved_parent" ]]; then
                parent_rfc_content=$(cat "$resolved_parent")
                log_step "Parent RFC: ${COLOR_STEP}${resolved_parent}${RESET}"
            else
                log_warn "Parent RFC not found: ${parent_rfc_path}"
            fi
        fi

        # Check if this RFC IS a parent (other specs reference it)
        local this_basename
        this_basename=$(basename "$spec_file")
        if [[ -n "$existing_specs" ]]; then
            child_rfc_list=$(echo "$existing_specs" \
                | while read -r candidate; do
                    if [[ -f "${PROJECT_ROOT}/${candidate}" ]]; then
                        if grep -q "Parent RFC:.*${this_basename}" "${PROJECT_ROOT}/${candidate}" 2>/dev/null; then
                            echo "$candidate"
                        fi
                    fi
                done || true)

            if [[ -n "$child_rfc_list" ]]; then
                local child_count
                child_count=$(echo "$child_rfc_list" | wc -l | tr -d ' ')
                log_step "Child RFCs: ${COLOR_STEP}${child_count} found${RESET}"
            fi
        fi
    fi

    # ── Agent context assembly ─────────────────────────────────
    local audit_message=""
    audit_message+="## Spec Under Audit\n\n${spec_content}"
    audit_message+="\n\n## Template (structural contract)\n\n${template_content}"
    audit_message+="\n\n## Product Vision\n\n${vision_content}"

    if [[ -n "$linked_prd_content" ]]; then
        audit_message+="\n\n## Linked Specs\n\n### PRD\n${linked_prd_content}"
    else
        audit_message+="\n\n## Linked Specs\n\nNo linked PRD found"
    fi

    if [[ -n "$parent_rfc_content" ]]; then
        audit_message+="\n\n### Parent RFC\n${parent_rfc_content}"
    fi

    if [[ -n "$child_rfc_list" ]]; then
        audit_message+="\n\n### Child RFCs\n${child_rfc_list}"
    fi

    if [[ -n "$existing_specs" ]]; then
        audit_message+="\n\n## Existing Specs\n\n${existing_specs}"
    fi

    # Ensure logs directory exists
    mkdir -p "$LOGS_DIR"

    log_step "Sending to Audit agent..."
    echo ""

    # ── Agent invocation ───────────────────────────────────────
    # Uses provider_run (not provider_run_json) — the audit agent definition
    # specifies its own JSON output format, no external schema needed.
    local raw_audit_output
    if ! raw_audit_output=$(provider_run \
        "${AGENTS_DIR}/audit.md" \
        "$audit_message" \
        "$MODEL_SUPPORT" \
        "$AGENT_TOOLS_READONLY" \
        "Audit"); then
        log_error "Audit agent failed — check agent CLI connection"
        exit 1
    fi

    if [[ -z "$raw_audit_output" ]]; then
        log_error "Audit agent returned empty output"
        exit 1
    fi

    # Save raw output
    local timestamp
    timestamp=$(date +%s)
    local log_file="${AUDIT_OUTPUT_FILE:-${LOGS_DIR}/audit-${timestamp}.json}"
    echo "$raw_audit_output" > "$log_file"
    _prune_logs "audit-" ".json"

    # ── Response parsing ───────────────────────────────────────
    local audit_output
    audit_output=$(parse_agent_json "$raw_audit_output") || {
        log_error "Could not extract valid JSON from audit output"
        log_error "Raw output saved to ${log_file}"
        exit 1
    }

    if ! _require_json "Audit" "$audit_output"; then
        log_error "Review raw output: ${log_file}"
        exit 1
    fi

    # ── Report formatting ──────────────────────────────────────
    echo ""
    log_header "Audit Report"

    local status
    status=$(echo "$audit_output" | jq -r '.status // "unknown"')

    # Parse and display issues
    local issue_count
    issue_count=$(echo "$audit_output" | jq '.issues | length' 2>/dev/null || echo "0")

    local error_count=0
    local warn_count=0

    if [[ "$issue_count" -gt 0 ]]; then
        local i=0
        while [[ $i -lt $issue_count ]]; do
            local severity level section message
            severity=$(echo "$audit_output" | jq -r ".issues[$i].severity")
            level=$(echo "$audit_output" | jq -r ".issues[$i].level")
            section=$(echo "$audit_output" | jq -r ".issues[$i].section")
            message=$(echo "$audit_output" | jq -r ".issues[$i].message")

            # L1 = blocker (cross icon), L2+ = warning (warn icon)
            if [[ "$level" == "1" ]]; then
                echo -e "  ${COLOR_ERROR}${SYM_CROSS} [L${level}] ${section} — ${message}${RESET}"
                ((error_count++)) || true
            else
                echo -e "  ${COLOR_WARN}${SYM_WARN} [L${level}] ${section} — ${message}${RESET}"
                ((warn_count++)) || true
            fi
            ((i++)) || true
        done
        echo ""
    fi

    # Sizing recommendation
    local has_sizing
    has_sizing=$(echo "$audit_output" | jq 'has("sizing") and .sizing != null' 2>/dev/null || echo "false")

    if [[ "$has_sizing" == "true" ]]; then
        local sizing_rec
        sizing_rec=$(echo "$audit_output" | jq -r '.sizing.recommendation // "ok"')
        local sizing_rationale
        sizing_rationale=$(echo "$audit_output" | jq -r '.sizing.rationale // "No rationale provided"')
        local estimated_tasks
        estimated_tasks=$(echo "$audit_output" | jq -r '.sizing.estimated_tasks // "?"')

        if [[ "$sizing_rec" == "multi_rfc" ]]; then
            echo -e "  ${COLOR_WARN}${SYM_WARN} Sizing: Consider splitting into multiple child RFCs (~${estimated_tasks} tasks)${RESET}"
            echo -e "    ${COLOR_DIM}${sizing_rationale}${RESET}"

            # Show suggested children if present
            local child_count
            child_count=$(echo "$audit_output" | jq '.sizing.suggested_children | length' 2>/dev/null || echo "0")
            if [[ "$child_count" -gt 0 ]]; then
                echo -e "    ${COLOR_DIM}Suggested child RFCs:${RESET}"
                local c=0
                while [[ $c -lt $child_count ]]; do
                    local child_name child_output
                    child_name=$(echo "$audit_output" | jq -r ".sizing.suggested_children[$c].name")
                    child_output=$(echo "$audit_output" | jq -r ".sizing.suggested_children[$c].testable_output")
                    echo -e "      ${COLOR_DIM}${child_name} — ${child_output}${RESET}"
                    ((c++)) || true
                done
            fi
            echo ""
        elif [[ "$sizing_rec" == "split" ]]; then
            echo -e "  ${COLOR_WARN}${SYM_WARN} Sizing: Consider phasing this spec (~${estimated_tasks} tasks)${RESET}"
            echo -e "    ${COLOR_DIM}${sizing_rationale}${RESET}"
            echo ""
        fi
    fi

    # ── Final status ───────────────────────────────────────────
    log_step "Report saved to ${COLOR_STEP}${log_file}${RESET}"
    echo ""

    case "$status" in
        pass)
            log_success "Audit: PASS"
            exit $EXIT_OK
            ;;
        warn)
            log_warn "Audit: WARN (${warn_count} warning(s))"
            exit $EXIT_OK
            ;;
        fail)
            log_error "Audit: FAIL (${error_count} error(s), ${warn_count} warning(s))"
            exit $EXIT_GATE_FAILURE
            ;;
        *)
            log_warn "Audit returned unknown status: ${status}"
            exit $EXIT_OK
            ;;
    esac
}
