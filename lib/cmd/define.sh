#!/usr/bin/env bash
# define.sh — Generate derived technical specs from a feature's input specs

cmd_define() {
    local subject="${1:-}"
    shift || true

    case "$subject" in
        authorisation-risk|authorization-risk)
            _define_authorisation_risk "$@"
            ;;
        "")
            log_error "Usage: speed define authorisation-risk <feature> [options]"
            exit 1
            ;;
        *)
            log_error_block \
                "Unknown define subject: ${subject}" \
                "speed define generates derived technical specs" \
                "Use: speed define authorisation-risk <feature>"
            exit 1
            ;;
    esac
}

# ── Input discovery ──────────────────────────────────────────────

# Resolve a user-supplied path against cwd, then PROJECT_ROOT.
# Prints the resolved path, or nothing if the file does not exist.
_define_resolve_path() {
    local path="$1"
    if [[ -f "$path" ]]; then
        echo "$path"
    elif [[ -f "${PROJECT_ROOT}/${path}" ]]; then
        echo "${PROJECT_ROOT}/${path}"
    fi
}

# Print the input files for one spec category, one per line.
# Explicit flag values win. Otherwise prefer <dir>/<feature>.md, and fall
# back to every .md file in <dir> (project-wide architecture, threat model,
# or compliance specs are usually not feature-scoped).
#
# Args: label dir feature [explicit paths...]
_define_discover_inputs() {
    local label="$1" dir="$2" feature="$3"
    shift 3

    if [[ $# -gt 0 ]]; then
        local path resolved
        for path in "$@"; do
            resolved=$(_define_resolve_path "$path")
            if [[ -z "$resolved" ]]; then
                log_error_block \
                    "${label} spec not found: ${path}" \
                    "Every file passed as a ${label} input must exist" \
                    "Check the path, or omit the flag to use ${dir}/"
                return 1
            fi
            echo "$resolved"
        done
        return 0
    fi

    local abs_dir="${PROJECT_ROOT}/${dir}"
    [[ -d "$abs_dir" ]] || return 0

    if [[ -f "${abs_dir}/${feature}.md" ]]; then
        echo "${abs_dir}/${feature}.md"
        return 0
    fi

    find "$abs_dir" -maxdepth 1 -name '*.md' -type f | sort
}

# Print a labelled block of spec contents for the agent prompt.
# Args: heading files_newline_separated
_define_spec_block() {
    local heading="$1" files="$2"

    printf '## %s\n\n' "$heading"
    if [[ -z "$files" ]]; then
        printf 'Not provided.\n\n'
        return 0
    fi

    local file
    while IFS= read -r file; do
        [[ -n "$file" ]] || continue
        printf '### %s\n\n' "${file#${PROJECT_ROOT}/}"
        cat "$file"
        printf '\n\n'
    done <<< "$files"
}

# Print a tracked-file inventory split into source and test files.
# Specs, docs, and SPEED state are excluded; each list is capped so large
# repos do not blow the prompt budget (the agent can still Glob/Grep).
_define_code_inventory() {
    local cap="${DEFINE_INVENTORY_CAP:-400}"
    local all_files=""
    all_files=$(git -C "$PROJECT_ROOT" ls-files 2>/dev/null \
        | grep -vE '^(specs|docs|working-docs|\.speed|node_modules)/|\.md$' || true)

    if [[ -z "$all_files" ]]; then
        echo "No tracked files found. Use Glob and Grep to explore the project."
        return 0
    fi

    local test_re='(^|/)(tests?|__tests__|spec)/|[._-](test|spec)\.[a-z]+$|_test\.[a-z]+$'
    local tests sources test_count source_count
    tests=$(echo "$all_files" | grep -E "$test_re" || true)
    sources=$(echo "$all_files" | grep -vE "$test_re" || true)
    test_count=$(echo -n "$tests" | grep -c '' || true)
    source_count=$(echo -n "$sources" | grep -c '' || true)

    echo "### Source files (${source_count})"
    echo ""
    echo "$sources" | head -n "$cap"
    [[ "$source_count" -gt "$cap" ]] && echo "... and $((source_count - cap)) more"
    echo ""
    echo "### Test files (${test_count})"
    echo ""
    if [[ "$test_count" -eq 0 ]]; then
        echo "None found."
    else
        echo "$tests" | head -n "$cap"
        [[ "$test_count" -gt "$cap" ]] && echo "... and $((test_count - cap)) more"
    fi
    return 0
}

# ── Output handling ──────────────────────────────────────────────

# Strip code fences and any preamble before the first H1.
_define_clean_markdown() {
    local content="$1"
    content=$(echo "$content" | tr -d '\r' | sed -e '1{/^```[a-z]*$/d}' -e '${/^```$/d}')
    echo "$content" | awk 'found || /^# / { found=1; print }'
}

# Print template H2 headings missing from the content, one per line.
_define_missing_sections() {
    local content="$1" template_file="$2"
    local heading
    while IFS= read -r heading; do
        heading="${heading%$'\r'}"
        if ! echo "$content" | grep -qxF "$heading"; then
            echo "${heading#\#\# }"
        fi
    done < <(grep -E '^## ' "$template_file")
}

# ── speed define authorisation-risk ──────────────────────────────

_define_authorisation_risk() {
    local feature="" product_flag="" design_flag="" output_flag="" force=false
    local -a arch_flags=() threat_flags=() compliance_flags=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --product)       product_flag="$2"; shift 2 ;;
            --design)        design_flag="$2"; shift 2 ;;
            --architecture)  arch_flags+=("$2"); shift 2 ;;
            --threat-model)  threat_flags+=("$2"); shift 2 ;;
            --compliance)    compliance_flags+=("$2"); shift 2 ;;
            --output|-o)     output_flag="$2"; shift 2 ;;
            --force)         force=true; shift ;;
            -*)
                log_error "Unknown option: $1"
                exit 1
                ;;
            *)
                if [[ -z "$feature" ]]; then
                    feature="$1"; shift
                else
                    log_error "Unexpected argument: $1"
                    exit 1
                fi
                ;;
        esac
    done

    feature="${feature:-${GLOBAL_FEATURE:-}}"
    if [[ -z "$feature" ]]; then
        log_error "Usage: speed define authorisation-risk <feature> [options]"
        exit 1
    fi

    log_header "Define: Authorisation Risk"

    local template_file="${TEMPLATES_DIR}/authorisation-risk.md"
    if [[ ! -f "$template_file" ]]; then
        log_error_block \
            "Template not found: ${template_file}" \
            "The authorisation-risk spec is generated from this template" \
            "Ensure SPEED templates are installed"
        exit $EXIT_CONFIG_ERROR
    fi

    # ── Product spec (required) ────────────────────────────────
    local product_file
    product_file=$(_define_resolve_path "${product_flag:-specs/product/${feature}.md}")
    if [[ -z "$product_file" ]]; then
        log_error_block \
            "Product spec not found: ${product_flag:-specs/product/${feature}.md}" \
            "The authorisation-risk spec is derived from the feature's Product spec" \
            "Create it with: speed new prd ${feature}, or pass --product <file>"
        exit $EXIT_CONFIG_ERROR
    fi

    # ── Optional inputs ────────────────────────────────────────
    local design_files="" arch_files="" threat_files="" compliance_files="" tech_files=""

    if [[ -n "$design_flag" ]]; then
        design_files=$(_define_discover_inputs "Design" "specs/design" "$feature" "$design_flag") \
            || exit $EXIT_CONFIG_ERROR
    elif [[ -f "${PROJECT_ROOT}/specs/design/${feature}.md" ]]; then
        design_files="${PROJECT_ROOT}/specs/design/${feature}.md"
    fi

    arch_files=$(_define_discover_inputs "Architecture" "specs/architecture" "$feature" \
        "${arch_flags[@]+"${arch_flags[@]}"}") || exit $EXIT_CONFIG_ERROR
    threat_files=$(_define_discover_inputs "Threat Model" "specs/threat-model" "$feature" \
        "${threat_flags[@]+"${threat_flags[@]}"}") || exit $EXIT_CONFIG_ERROR
    compliance_files=$(_define_discover_inputs "Compliance" "specs/compliance" "$feature" \
        "${compliance_flags[@]+"${compliance_flags[@]}"}") || exit $EXIT_CONFIG_ERROR

    [[ -f "${PROJECT_ROOT}/specs/tech/${feature}.md" ]] \
        && tech_files="${PROJECT_ROOT}/specs/tech/${feature}.md"

    # ── Output path ────────────────────────────────────────────
    local output_rel="${output_flag:-specs/tech/${feature}-authorisation-risk.md}"
    output_rel="${output_rel#${PROJECT_ROOT}/}"
    local output_file="${PROJECT_ROOT}/${output_rel}"

    if [[ -f "$output_file" && "$force" != true ]]; then
        log_error_block \
            "Spec already exists: ${output_rel}" \
            "define will not overwrite an existing authorisation-risk spec" \
            "Re-run with --force to regenerate it, or audit it: speed audit ${output_rel}"
        exit $EXIT_CONFIG_ERROR
    fi

    # Link from the output spec back to the Product spec, relative when both
    # live under specs/ (matches the "../product/x.md" convention).
    local product_rel="${product_file#${PROJECT_ROOT}/}"
    local product_link="$product_rel"
    if [[ "$product_rel" == specs/* && "$output_rel" == specs/*/* && "$output_rel" != specs/*/*/* ]]; then
        product_link="../${product_rel#specs/}"
    fi

    _define_log_input "Product" "$product_file"
    _define_log_input "Design" "$design_files"
    _define_log_input "Architecture" "$arch_files"
    _define_log_input "Threat Model" "$threat_files"
    _define_log_input "Compliance" "$compliance_files"
    [[ -n "$tech_files" ]] && _define_log_input "Tech" "$tech_files"
    log_step "Output:       ${COLOR_STEP}${output_rel}${RESET}"

    # ── Agent context assembly ─────────────────────────────────
    local message
    message=$(
        printf '## Feature\n\n%s\n\n' "$feature"
        printf '## Output\n\nPath: %s\nProduct spec link for the `> See` header: %s\n\n' \
            "$output_rel" "$product_link"
        _define_spec_block "Product Spec" "$product_file"
        _define_spec_block "Design Spec" "$design_files"
        _define_spec_block "Architecture Specs" "$arch_files"
        _define_spec_block "Threat Model Specs" "$threat_files"
        _define_spec_block "Compliance Specs" "$compliance_files"
        [[ -n "$tech_files" ]] && _define_spec_block "Existing Tech Spec" "$tech_files"
        printf '## Codebase Inventory\n\n'
        _define_code_inventory
        printf '\n## Template\n\n'
        cat "$template_file"
        printf '\n\nWrite the complete authorisation-risk spec now.\n'
    )

    mkdir -p "$LOGS_DIR"
    log_step "Sending to Authorisation Risk agent..."
    echo ""

    local raw_output content missing=""
    if ! raw_output=$(provider_run \
        "${AGENTS_DIR}/authorisation-risk.md" \
        "$message" \
        "$MODEL_PLANNING" \
        "$AGENT_TOOLS_READONLY" \
        "AuthorisationRisk"); then
        log_error "Authorisation Risk agent failed — check agent CLI connection"
        exit 1
    fi

    content=$(_define_clean_markdown "$raw_output")
    [[ -n "$content" ]] && missing=$(_define_missing_sections "$content" "$template_file")

    # One retry with targeted feedback when the draft is empty or incomplete.
    if [[ -z "$content" || -n "$missing" ]]; then
        local feedback="Your previous draft was incomplete."
        [[ -n "$missing" ]] && feedback+=" It was missing these sections: $(echo "$missing" | paste -sd ',' - | sed 's/,/, /g')."
        feedback+=" Regenerate the complete spec with every template section, starting with the '# Authorisation Risk:' heading."
        log_warn "Draft incomplete, retrying once"

        local retry_output
        if retry_output=$(provider_run \
            "${AGENTS_DIR}/authorisation-risk.md" \
            "$message"$'\n\n'"## Feedback"$'\n\n'"${feedback}" \
            "$MODEL_PLANNING" \
            "$AGENT_TOOLS_READONLY" \
            "AuthorisationRisk"); then
            local retry_content retry_missing=""
            retry_content=$(_define_clean_markdown "$retry_output")
            if [[ -n "$retry_content" ]]; then
                retry_missing=$(_define_missing_sections "$retry_content" "$template_file")
                local before_count after_count
                before_count=$(echo -n "$missing" | grep -c '' || true)
                after_count=$(echo -n "$retry_missing" | grep -c '' || true)
                if [[ -z "$content" || "$after_count" -le "$before_count" ]]; then
                    content="$retry_content"
                    missing="$retry_missing"
                fi
            fi
        fi
    fi

    if [[ -z "$content" ]]; then
        log_error "Authorisation Risk agent returned no markdown document"
        exit 1
    fi

    # The auditor resolves the Product spec through the "> See" header, so
    # guarantee it exists even if the agent dropped it.
    if ! echo "$content" | grep -qE '^> See \[[^]]*\]\([^)]+\)'; then
        content=$(echo "$content" | awk -v link="$product_link" '
            !done && /^# / { print; print ""; print "> See [product spec](" link ") for product context."; print "> Spec type: authorisation-risk"; done=1; next }
            { print }')
    fi

    mkdir -p "$(dirname "$output_file")"
    printf '%s\n' "$content" > "$output_file"

    echo ""
    if [[ -n "$missing" ]]; then
        log_warn "Wrote ${output_rel} with missing sections: $(echo "$missing" | paste -sd ',' - | sed 's/,/, /g')"
    else
        log_success "Wrote ${output_rel}"
    fi
    log_step "Next: ${COLOR_STEP}speed audit ${output_rel}${RESET}"
}

_define_log_input() {
    local label="$1" files="$2"
    local padded
    padded=$(printf '%-13s' "${label}:")
    if [[ -z "$files" ]]; then
        log_step "${padded} ${COLOR_DIM}not provided${RESET}"
        return 0
    fi
    local file
    while IFS= read -r file; do
        [[ -n "$file" ]] && log_step "${padded} ${COLOR_STEP}${file#${PROJECT_ROOT}/}${RESET}"
    done <<< "$files"
}
