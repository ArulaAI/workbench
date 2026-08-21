#!/usr/bin/env bash
# plan.sh — Task planning command

_gather_related_specs() {
    local specs_dir="$1"
    shift
    local exclude_files=("$@")

    if [[ -z "$specs_dir" ]] || [[ ! -d "$specs_dir" ]]; then
        echo "{}"
        return
    fi

    # Collect non-excluded file paths
    local -a spec_files=()
    while IFS= read -r -d '' f; do
        local skip=false
        local f_real
        f_real=$(realpath "$f")
        for exclude in "${exclude_files[@]}"; do
            if [[ -n "$exclude" ]] && [[ "$f_real" == "$(realpath "$exclude")" ]]; then
                skip=true
                break
            fi
        done
        if [[ "$skip" == "false" ]]; then
            spec_files+=("$f")
        fi
    done < <(find "$specs_dir" -name '*.md' -type f -print0 | sort -z)

    if [[ ${#spec_files[@]} -eq 0 ]]; then
        echo "{}"
        return
    fi

    # Build JSON in a single jq call: {path: content, ...}
    # --rawfile reads file content as raw string (no quoting issues)
    # --arg passes the relative path as a jq variable
    local jq_args=()
    local jq_expr="{"
    local i=0
    for f in "${spec_files[@]}"; do
        local relpath="${f#${PROJECT_ROOT}/}"
        jq_args+=(--rawfile "c${i}" "$f" --arg "p${i}" "$relpath")
        [[ $i -gt 0 ]] && jq_expr+=","
        jq_expr+='($p'"${i}"'):$c'"${i}"
        ((i++)) || true
    done
    jq_expr+="}"

    jq -n "${jq_args[@]}" "$jq_expr"
}

# ── Store the primary spec file path for downstream commands ──
# Uses FEATURE_DIR when a feature is active, otherwise STATE_DIR fallback.

_save_spec_path() {
    local spec_file="$1"
    local dir="${FEATURE_DIR:-${STATE_DIR}}"
    echo "$spec_file" > "${dir}/spec_path"
}

# ── Plan stage caching ─────────────────────────────────────────
# Caches expensive stages (Guardian, Architect) keyed by a hash of
# spec inputs. Auto-invalidates when specs change. --force bypasses.

_plan_cache_dir() { echo "${FEATURE_DIR}/cache"; }

_plan_cache_valid() {
    local stage="$1" hash="$2"
    local cache_dir
    cache_dir=$(_plan_cache_dir)
    [[ -f "${cache_dir}/${stage}.hash" && -f "${cache_dir}/${stage}.dat" ]] \
        && [[ "$(cat "${cache_dir}/${stage}.hash")" == "$hash" ]]
}

_plan_cache_write() {
    local stage="$1" hash="$2" data="$3"
    local cache_dir
    cache_dir=$(_plan_cache_dir)
    mkdir -p "$cache_dir"
    echo "$hash" > "${cache_dir}/${stage}.hash"
    echo "$data" > "${cache_dir}/${stage}.dat"
}

_plan_cache_read() {
    cat "$(_plan_cache_dir)/${1}.dat"
}

# Architect failure diagnostic (G2: failure is informative)
# Parses the JSONL event log and classifies the failure mode.
_diagnose_architect_failure() {
    local phase_label="$1"
    local raw_log="$2"

    log_error "Raw output saved to ${raw_log}"
    provider_diagnose_failure "$phase_label" "$raw_log" "$LOGS_DIR"
}

_run_architect_phase() {
    local phase_label="$1"
    local message="$2"

    # Inject model tier names so the architect uses the active provider's vocabulary
    message+="\n\n## Model Tiers\n\nSupport model: ${MODEL_SUPPORT}\nPlanning model: ${MODEL_PLANNING}\nUse \`${MODEL_SUPPORT}\` as the default \`agent_model\`. Use \`${MODEL_PLANNING}\` only for architecturally complex tasks."

    # Scale timeout: base + per-token scaling, with floor and cap
    local msg_chars=${#message}
    local msg_tokens_approx=$(( (msg_chars + 3) / 4 ))
    local architect_timeout=$(( ARCHITECT_TIMEOUT_BASE + (msg_tokens_approx * ARCHITECT_TIMEOUT_PER_1K_TOKENS / 1000) ))
    [[ $architect_timeout -gt $ARCHITECT_TIMEOUT_MAX ]] && architect_timeout=$ARCHITECT_TIMEOUT_MAX
    # Phased plans get a higher floor (large specs by definition)
    local timeout_floor=$ARCHITECT_TIMEOUT_MIN
    [[ "$phase_label" == *"Phase"* ]] && timeout_floor=$ARCHITECT_TIMEOUT_PHASED_MIN
    [[ $architect_timeout -lt $timeout_floor ]] && architect_timeout=$timeout_floor

    local safe_label
    safe_label=$(echo "$phase_label" | tr ' ()' '---')

    local output rc=0
    output=$(provider_run_json \
        "${AGENTS_DIR}/architect.md" \
        "$message" \
        "${TEMPLATES_DIR}/architect-output.json" \
        "$MODEL_PLANNING" \
        "$ARCHITECT_MAX_TURNS" \
        "" \
        "$phase_label" \
        "$architect_timeout") || rc=$?

    echo "$output" > "${LOGS_DIR}/architect-raw-${safe_label}.log"

    if [[ $rc -ne 0 ]]; then
        log_error "${phase_label} failed (exit code ${rc})"
        if [[ $rc -eq 2 ]]; then
            log_error "The architect returned an error envelope"
        fi
        _diagnose_architect_failure "$phase_label" "${LOGS_DIR}/architect-raw-${safe_label}.log"
        return 1
    fi

    parse_agent_json "$output" || {
        log_error "Could not extract valid JSON from ${phase_label} output"
        _diagnose_architect_failure "$phase_label" "${LOGS_DIR}/architect-raw-${safe_label}.log"
        return 1
    }
}

# Run the coverage verifier. Sets _cov_status, _cov_critical, _cov_minor,
# _cov_gaps, _cov_parsed in caller scope.
# Reads: $parsed_architect, $tech_spec_content, $product_spec_content,
#         $design_spec_content (from cmd_plan scope)
# WARNING: Do not call inside $(). Uses log_* which write to stdout.
_run_coverage_check() {
    _cov_status="complete"
    _cov_critical=0
    _cov_minor=0
    _cov_gaps="[]"
    _cov_parsed=""

    log_step "Verifying task coverage against full specs..."

    local task_summary
    task_summary=$(echo "$parsed_architect" | jq -c '[.tasks[] | {
        id, title, description, spec_references,
        acceptance_criteria: [.acceptance_criteria[]? | .criterion]
    }]')

    local msg=""
    [[ -n "$product_spec_content" ]] && msg+="## Product Spec\n\n${product_spec_content}\n\n"
    msg+="## Tech Spec\n\n${tech_spec_content}"
    [[ -n "$design_spec_content" ]] && msg+="\n\n## Design Spec\n\n${design_spec_content}"
    msg+="\n\n## Planned Tasks\n\n\`\`\`json\n${task_summary}\n\`\`\`"

    local output rc=0
    output=$(provider_run_json \
        "${AGENTS_DIR}/coverage-verifier.md" \
        "$msg" \
        "${TEMPLATES_DIR}/coverage-output.json" \
        "$MODEL_SUPPORT" \
        "$DEFAULT_JSON_MAX_TURNS" \
        "" \
        "Coverage Verifier") || rc=$?

    if [[ $rc -ne 0 ]]; then
        log_warn "Coverage verifier failed to run (exit ${rc})"
        return
    fi

    _cov_parsed=$(parse_agent_json "$output" 2>/dev/null) || return 0
    _cov_status=$(echo "$_cov_parsed" | jq -r '.coverage // "complete"')

    [[ "$_cov_status" != "gaps_found" ]] && return

    _cov_critical=$(echo "$_cov_parsed" | jq '[.gaps[] | select(.severity == "critical")] | length')
    _cov_minor=$(echo "$_cov_parsed" | jq '[.gaps[] | select(.severity == "minor")] | length')
    _cov_gaps=$(echo "$_cov_parsed" | jq -c '[.gaps[] | select(.severity == "critical")]')

    echo ""
    echo "$_cov_parsed" | jq -c '.gaps[]' | while IFS= read -r gap; do
        local sev spec sect req
        sev=$(echo "$gap" | jq -r '.severity')
        spec=$(echo "$gap" | jq -r '.spec')
        sect=$(echo "$gap" | jq -r '.section')
        req=$(echo "$gap" | jq -r '.requirement')
        if [[ "$sev" == "critical" ]]; then
            echo -e "  ${SYM_CROSS} [${sev}] ${spec}:${sect} — ${req}"
        else
            echo -e "  ${SYM_WARN} [${sev}] ${spec}:${sect} — ${req}"
        fi
    done
    echo ""
    echo "$_cov_parsed" | jq '.' > "${LOGS_DIR}/coverage-report.json"
    log_step "Coverage report: ${LOGS_DIR}/coverage-report.json"
}

# Add tasks for critical coverage gaps. Modifies $parsed_architect in caller scope.
# Reads: $parsed_architect, $_cov_gaps, $_cov_critical, $tech_spec_content,
#         $product_spec_content, $design_spec_content (from cmd_plan scope)
# WARNING: Do not call inside $(). Uses log_* which write to stdout.
_repair_coverage_gaps() {
    local max_id start_id
    max_id=$(echo "$parsed_architect" | jq '[.tasks[].id | (tonumber? // 0)] | max // 0')
    start_id=$((max_id + 1))

    local task_summary
    task_summary=$(echo "$parsed_architect" | jq -c '[.tasks[] | {id, title, files_touched, depends_on}]')

    local gap_text
    gap_text=$(echo "$_cov_gaps" | jq -r '.[] | "- [\(.severity)] \(.spec): \(.section) — \(.requirement)\n  Explanation: \(.explanation)"')

    local msg=""
    msg+="## Existing Plan\n\n\`\`\`json\n${task_summary}\n\`\`\`\n\n"
    [[ -n "$product_spec_content" ]] && msg+="## Product Spec\n\n${product_spec_content}\n\n"
    msg+="## Tech Spec\n\n${tech_spec_content}\n\n"
    [[ -n "$design_spec_content" ]] && msg+="## Design Spec\n\n${design_spec_content}\n\n"
    msg+="## Coverage Gaps\n\n${gap_text}\n\n"
    msg+="## Instructions\n\nAdd task(s) for the gaps above. "
    msg+="IDs start at ${start_id}. Do not recreate existing tasks. "
    msg+="Set depends_on where needed. Only output NEW tasks.\n"

    log_step "Generating task(s) for ${_cov_critical} gap(s)..."
    echo ""

    local output rc=0
    output=$(provider_run_json \
        "${AGENTS_DIR}/architect.md" \
        "$msg" \
        "${TEMPLATES_DIR}/architect-output.json" \
        "$MODEL_PLANNING" \
        "$ARCHITECT_MAX_TURNS" \
        "" \
        "Architect (add-task)") || rc=$?

    if [[ $rc -ne 0 ]]; then
        log_error "Add-task call failed (exit ${rc})"
        return
    fi

    local parsed_add
    parsed_add=$(parse_agent_json "$output") || {
        log_error "Could not parse add-task output"
        return
    }

    local new_tasks new_count
    new_tasks=$(echo "$parsed_add" | jq -c '.tasks // []')
    new_count=$(echo "$new_tasks" | jq 'length')

    if [[ "$new_count" -eq 0 ]]; then
        log_error "Architect produced 0 new tasks"
        return
    fi

    # Append tasks
    parsed_architect=$(echo "$parsed_architect" | jq --argjson new "$new_tasks" '.tasks += $new')

    # Append contract entities
    local new_contract
    new_contract=$(echo "$parsed_add" | jq '.contract // empty' 2>/dev/null)
    if [[ -n "$new_contract" && "$new_contract" != "null" ]]; then
        parsed_architect=$(echo "$parsed_architect" | jq --argjson nc "$new_contract" '
            .contract.entities += ($nc.entities // []) |
            .contract.relationships += ($nc.relationships // [])')
    fi

    # Append validation and cross-cutting concerns
    local new_validation
    new_validation=$(echo "$parsed_add" | jq -c '.validation // []' 2>/dev/null)
    if [[ "$new_validation" != "[]" ]]; then
        parsed_architect=$(echo "$parsed_architect" | jq --argjson nv "$new_validation" \
            '.validation += $nv')
    fi

    local new_cc
    new_cc=$(echo "$parsed_add" | jq -c '.cross_cutting_concerns // []' 2>/dev/null)
    if [[ "$new_cc" != "[]" ]]; then
        parsed_architect=$(echo "$parsed_architect" | jq --argjson ncc "$new_cc" \
            '.cross_cutting_concerns += $ncc')
    fi

    log_success "Added ${new_count} task(s)"
}

cmd_plan() {
    local spec_file="${1:-}"
    shift || true
    local specs_dir=""
    local force_plan=false
    local skip_audit=false
    local single_pass=false

    # Parse options
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --specs-dir) specs_dir="$2"; shift 2 ;;
            --force) force_plan=true; shift ;;
            --skip-audit) skip_audit=true; shift ;;
            --single-pass) single_pass=true; shift ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    if [[ -z "$spec_file" ]]; then
        log_error "Usage: speed plan <tech-spec-file> [--specs-dir DIR]"
        exit 1
    fi

    if [[ ! -f "$spec_file" ]]; then
        # Try relative to PROJECT_ROOT
        if [[ -f "${PROJECT_ROOT}/${spec_file}" ]]; then
            spec_file="${PROJECT_ROOT}/${spec_file}"
        else
            log_error_block \
                "Spec file not found: ${spec_file}" \
                "The plan command requires a spec file" \
                "Create the spec or check the path"
            exit $EXIT_CONFIG_ERROR
        fi
    fi

    # Resolve specs_dir
    if [[ -n "$specs_dir" ]] && [[ ! -d "$specs_dir" ]]; then
        if [[ -d "${PROJECT_ROOT}/${specs_dir}" ]]; then
            specs_dir="${PROJECT_ROOT}/${specs_dir}"
        else
            log_warn "Specs directory not found: $specs_dir — proceeding without cross-references"
            specs_dir=""
        fi
    fi

    # ── Auto-derive sibling specs ──────────────────────────────────
    # Convention: specs/tech/<name>.md → specs/product/<name>.md
    #                                  → specs/design/<name>.md
    local product_spec_file=""
    local design_spec_file=""
    local derived_product
    local derived_design
    derived_product=$(echo "$spec_file" | sed 's|/tech/|/product/|')
    derived_design=$(echo "$spec_file" | sed 's|/tech/|/design/|')

    if [[ "$derived_product" != "$spec_file" ]] && [[ -f "$derived_product" ]]; then
        product_spec_file="$derived_product"
    fi
    if [[ "$derived_design" != "$spec_file" ]] && [[ -f "$derived_design" ]]; then
        design_spec_file="$derived_design"
    fi

    # ── Activate feature namespace ────────────────────────────────
    local feature_name="${GLOBAL_FEATURE:-}"
    if [[ -z "$feature_name" ]]; then
        feature_name=$(feature_name_from_spec "$spec_file")
    fi
    feature_activate "$feature_name"
    feature_set_active "$feature_name"
    log_info "Feature: ${COLOR_STEP}${feature_name}${RESET}"

    # Save spec path for verify and review commands
    _save_spec_path "$spec_file"

    # Ratification gate: in MP mode, spec must be ratified before planning
    if [[ "${MP_ENABLED:-}" == "true" ]]; then
        local _events_dir
        _events_dir=$(mp_events_dir)
        local _ratified=false
        for _rf in "${_events_dir}"/*_spec-ratified_"${feature_name}".jsonl; do
            [[ -f "$_rf" ]] && _ratified=true && break
        done
        if ! $_ratified; then
            # Check if any proposal exists at all
            local _proposed=false
            for _pf in "${_events_dir}"/*_spec-proposed_"${feature_name}".jsonl; do
                [[ -f "$_pf" ]] && _proposed=true && break
            done
            if $_proposed; then
                log_error "Spec for '${feature_name}' is proposed but not yet ratified"
                log_error "Run ${COLOR_STEP}speed spec ratify ${spec_file}${RESET} after collecting approvals"
                exit 1
            fi
            # No proposal at all — warn but allow (backward compat, solo operator)
            log_warn "Spec not proposed for review. In multi-player, run ${COLOR_STEP}speed spec propose ${spec_file}${RESET} first."
        fi
    fi

    log_header "Planning Task DAG"
    log_step "Tech spec:    ${COLOR_STEP}${spec_file}${RESET}"
    if [[ -n "$product_spec_file" ]]; then
        log_step "Product spec: ${COLOR_STEP}${product_spec_file}${RESET}"
    else
        log_warn "No product spec found (expected: ${derived_product})"
    fi
    if [[ -n "$design_spec_file" ]]; then
        log_step "Design spec:  ${COLOR_STEP}${design_spec_file}${RESET}"
    else
        log_warn "No design spec found (expected: ${derived_design})"
    fi

    # Read all specs
    local tech_spec_content
    tech_spec_content=$(cat "$spec_file")

    local product_spec_content=""
    if [[ -n "$product_spec_file" ]]; then
        product_spec_content=$(cat "$product_spec_file")
    fi

    local design_spec_content=""
    if [[ -n "$design_spec_file" ]]; then
        design_spec_content=$(cat "$design_spec_file")
    fi

    # ── Spec hash for stage caching ───────────────────────────────
    local spec_hash
    spec_hash=$(printf '%s' "${tech_spec_content}${product_spec_content}${design_spec_content}" | shasum -a 256 | cut -d' ' -f1)

    # ── Pre-Plan Guardian Gate ─────────────────────────────────────
    # Check: does this spec belong in the product?
    local guardian_rc=0
    if [[ "$force_plan" != "true" ]] && _plan_cache_valid "guardian" "$spec_hash"; then
        guardian_rc=$(_plan_cache_read "guardian")
        log_step "Guardian: ${COLOR_DIM}cached (specs unchanged)${RESET}"
    else
        log_step "Running pre-plan vision check..."
        local _guardian_out
        _guardian_out=$(_run_guardian "pre-plan" "$tech_spec_content" "$spec_file") || guardian_rc=$?
        _plan_cache_write "guardian" "$spec_hash" "$guardian_rc"
    fi

    if [[ $guardian_rc -eq 1 ]]; then
        log_error "Product Guardian REJECTED this spec — it conflicts with the product vision"
        echo -e "Review the guardian report and either:"
        echo -e "  1. Fix the spec to align with the vision"
        echo -e "  2. Override with ${COLOR_STEP}SKIP_GUARDIAN=true speed plan ...${RESET} (use with caution)"
        if [[ "${SKIP_GUARDIAN:-}" != "true" ]]; then
            exit 1
        else
            log_warn "SKIP_GUARDIAN=true — proceeding despite rejection"
            _log_gate_skip "guardian_pre_plan" "plan"
        fi
    elif [[ $guardian_rc -eq 3 ]]; then
        log_warn "Guardian returned unparseable output — proceeding but review the log"
    fi
    # guardian_rc == 2 means flagged — warn but continue
    echo ""

    # ── Step 1: Spec Registration ────────────────────────────────────
    # Synchronized arrays: path, content, label. All downstream steps iterate these.
    _register_plan_spec() {
        plan_spec_paths+=("$1")
        plan_spec_contents+=("$2")
        plan_spec_labels+=("$3")
    }

    local -a plan_spec_paths=()
    local -a plan_spec_contents=()
    local -a plan_spec_labels=()

    _register_plan_spec "$spec_file" "$tech_spec_content" "Tech Spec (backend implementation)"

    [[ -n "$product_spec_file" ]] && \
        _register_plan_spec "$product_spec_file" "$product_spec_content" "Product Spec (what to build)"
    [[ -n "$design_spec_file" ]] && \
        _register_plan_spec "$design_spec_file" "$design_spec_content" "Design Spec (frontend implementation)"

    # ── Step 2: Audit Loop ────────────────────────────────────────────
    # Each registered spec audited independently. Caller-controlled output path.
    declare -A _audit_phase1_sections
    declare -A _audit_phase2_sections
    local audit_sizing_rec=""
    local audit_sizing_rationale=""

    if [[ "$skip_audit" == "true" ]]; then
        log_step "Audit: ${COLOR_DIM}skipped (--skip-audit)${RESET}"
        _log_gate_skip "audit" "plan"
    else
    for spec_index in "${!plan_spec_paths[@]}"; do
        local spec_path="${plan_spec_paths[$spec_index]}"
        local spec_label="${plan_spec_labels[$spec_index]}"
        local spec_type
        spec_type=$(echo "$spec_path" | sed -n 's|.*specs/\([^/]*\)/.*|\1|p')
        local spec_audit_file="${LOGS_DIR}/plan-audit-${spec_type:-spec${spec_index}}-$(date +%s).json"

        local audit_rc=0
        (AUDIT_OUTPUT_FILE="$spec_audit_file"; cmd_audit "$spec_path") || audit_rc=$?

        case $audit_rc in
            0) ;;
            $EXIT_GATE_FAILURE)
                log_error "Audit gate failed for ${spec_label} — fix spec issues and re-run"
                exit $EXIT_GATE_FAILURE
                ;;
            $EXIT_CONFIG_ERROR)
                log_error "Audit config error for ${spec_label} — check path and format"
                exit $EXIT_CONFIG_ERROR
                ;;
            *)
                log_warn "Audit returned exit code $audit_rc for ${spec_label} — continuing without audit data"
                continue
                ;;
        esac

        # Extract sizing and phase_sections from this spec's audit output
        if [[ -f "$spec_audit_file" ]]; then
            local parsed_audit
            parsed_audit=$(parse_agent_json "$(cat "$spec_audit_file")" 2>/dev/null) || parsed_audit=""
            if [[ -n "$parsed_audit" ]]; then
                local estimated_tasks
                estimated_tasks=$(echo "$parsed_audit" | jq -r '.sizing.estimated_tasks // 0' 2>/dev/null)
                if [[ "$estimated_tasks" -gt "$ARCHITECT_PHASE_TASK_THRESHOLD" ]] 2>/dev/null; then
                    audit_sizing_rec="split"
                    [[ -z "$audit_sizing_rationale" ]] && \
                        audit_sizing_rationale=$(echo "$parsed_audit" | jq -r '.sizing.rationale // ""' 2>/dev/null)
                    log_step "Audit sizing: ${COLOR_STEP}~${estimated_tasks} tasks${RESET} (${spec_label}) — will phase the architect"
                fi
                _audit_phase1_sections["$spec_path"]=$(echo "$parsed_audit" | jq -c '.sizing.phase_sections.phase_1 // []' 2>/dev/null)
                _audit_phase2_sections["$spec_path"]=$(echo "$parsed_audit" | jq -c '.sizing.phase_sections.phase_2 // []' 2>/dev/null)
            fi
        fi
    done
    _prune_logs "plan-audit-" ".json"
    fi

    if [[ "$single_pass" == "true" && "$audit_sizing_rec" == "split" ]]; then
        log_step "Phase splitting: ${COLOR_DIM}skipped (--single-pass)${RESET}"
        audit_sizing_rec="single"
    fi
    echo ""

    # ── Layer 1: Pre-Computed Context ────────────────────────────────
    # Build the codebase index (project map, CSG, skeletons, spec-alignment).
    # Replaces spec_grounding_check with structured, queryable context.
    log_step "Building Layer 1 context index..."

    # Collect spec files for alignment
    local spec_files_for_l1="{}"
    if [[ -f "$spec_file" ]]; then
        local spec_content_escaped
        spec_content_escaped=$(jq -Rs '.' < "$spec_file")
        spec_files_for_l1=$(jq -n --arg path "$spec_file" --argjson content "$spec_content_escaped" '{($path): $content}')
    fi
    if [[ -n "$product_spec_file" ]] && [[ -f "$product_spec_file" ]]; then
        local product_escaped
        product_escaped=$(jq -Rs '.' < "$product_spec_file")
        spec_files_for_l1=$(echo "$spec_files_for_l1" | jq --arg path "$product_spec_file" --argjson content "$product_escaped" '. + {($path): $content}')
    fi

    local l1_result
    l1_result=$(context_build_layer1 "false" "$spec_files_for_l1") || {
        log_warn "Layer 1 build failed — falling back to legacy spec grounding"
        SPEC_CODEBASE_CONTEXT=""
        spec_grounding_check "$spec_file"
        l1_result=""
    }

    if [[ -n "$l1_result" ]]; then
        local l1_status
        l1_status=$(echo "$l1_result" | jq -r '.status // "unknown"' 2>/dev/null)
        if [[ "$l1_status" == "built" ]] || [[ "$l1_status" == "cached" ]]; then
            log_success "Layer 1: ${l1_status}"
        fi

        # Assemble structured architect context from Layer 1
        SPEC_CODEBASE_CONTEXT=$(context_assemble_architect 2>/dev/null) || SPEC_CODEBASE_CONTEXT=""
    fi

    # Score and compress related specs
    local related_specs=""
    if [[ -n "$specs_dir" ]]; then
        log_step "Scoring related specs from: ${COLOR_STEP}${specs_dir}${RESET}"

        # Build primary spec JSON
        local primary_specs_json
        primary_specs_json=$(jq -n \
            --arg tech_path "$spec_file" --arg tech "$tech_spec_content" \
            --arg prod_path "${product_spec_file:-}" --arg prod "${product_spec_content:-}" \
            --arg design_path "${design_spec_file:-}" --arg design "${design_spec_content:-}" \
            '{($tech_path): $tech}
             + (if $prod_path != "" then {($prod_path): $prod} else {} end)
             + (if $design_path != "" then {($design_path): $design} else {} end)')

        local related_specs_json
        related_specs_json=$(_gather_related_specs "$specs_dir" "$spec_file" "$product_spec_file" "$design_spec_file")

        local rs_budget="${SPEED_RELATED_SPEC_BUDGET:-${TOML_CONTEXT_RELATED_SPEC_BUDGET:-15000}}"
        local rs_threshold="${SPEED_RELATED_SPEC_THRESHOLD:-${TOML_CONTEXT_RELATED_SPEC_THRESHOLD:-0.05}}"
        local rs_cap="${SPEED_RELATED_SPEC_CANDIDATE_CAP:-${TOML_CONTEXT_RELATED_SPEC_CANDIDATE_CAP:-50}}"

        local filtered_specs
        if ! filtered_specs=$(context_score_and_compress_specs \
            "$primary_specs_json" \
            "$related_specs_json" \
            "$PROJECT_ROOT" \
            "$rs_budget" \
            "$rs_threshold" \
            "$rs_cap"); then
            # Hard stop: scoring detected a failure condition (see Section 2: Hard Stops)
            # Error details already logged to stderr by the bridge function
            log_error "Related spec scoring failed. See diagnostics above."
            log_error "Remediation: add 'related:' front-matter to your primary spec, adjust threshold/budget, or narrow --specs-dir."
            return "$EXIT_GATE_FAILURE"
        fi

        related_specs="$filtered_specs"
        log_step "Related specs scored and compressed (budget: ${rs_budget} tokens)"
    fi

    # ── Architect agent ───────────────────────────────────────────
    local parsed_architect

    # Include phase count in cache key so re-runs with different sizing don't serve stale results
    local phase_count=1
    [[ "$audit_sizing_rec" == "split" ]] && phase_count=2
    local architect_cache_hash
    architect_cache_hash=$(printf '%s:%s' "$spec_hash" "$phase_count" | shasum -a 256 | cut -d' ' -f1)

    if [[ "$force_plan" != "true" ]] && _plan_cache_valid "architect" "$architect_cache_hash"; then
        parsed_architect=$(_plan_cache_read "architect")
        log_step "Architect: ${COLOR_DIM}cached (specs unchanged)${RESET}"
        echo ""
    else
        # Build base architect message (shared across phases)
        local base_message=""

        if [[ -n "$product_spec_content" ]]; then
            base_message+="## Product Spec (what to build)\n\n${product_spec_content}"
        fi

        base_message+="\n\n## Tech Spec (backend implementation)\n\n${tech_spec_content}"

        if [[ -n "$design_spec_content" ]]; then
            base_message+="\n\n## Design Spec (frontend implementation)\n\n${design_spec_content}"
        fi

        if [[ -n "$SPEC_CODEBASE_CONTEXT" ]]; then
            base_message+="\n\n## Codebase Context (ground truth from automated scan)\n\n${SPEC_CODEBASE_CONTEXT}"
        fi

        if [[ -n "$related_specs" ]]; then
            base_message+="\n\n## Related Specs (cross-reference for entity relationships)\n${related_specs}"
        fi

        if [[ "$audit_sizing_rec" == "split" ]]; then
            # ── Multi-phase architect ──────────────────────────────────
            log_step "Phased planning: splitting architect into 2 phases"
            echo ""

            # ── Step 3: Split specs the audit assigned to phases ─────────
            declare -A _phase1_content
            declare -A _phase2_content
            local _split_failed=false

            for spec_index in "${!plan_spec_paths[@]}"; do
                local spec_path="${plan_spec_paths[$spec_index]}"
                local spec_content="${plan_spec_contents[$spec_index]}"
                local phase1_sections="${_audit_phase1_sections[$spec_path]:-[]}"
                local phase2_sections="${_audit_phase2_sections[$spec_path]:-[]}"

                [[ "$phase1_sections" == "[]" && "$phase2_sections" == "[]" ]] && continue

                local phase1_split phase2_split
                phase1_split=$(context_split_spec_for_phase "$spec_content" "$phase2_sections") || {
                    log_error "Spec split failed for $(basename "$spec_path") Phase 1: context_split_spec_for_phase returned $?"
                    _split_failed=true
                    continue
                }
                phase2_split=$(context_split_spec_for_phase "$spec_content" "$phase1_sections") || {
                    log_error "Spec split failed for $(basename "$spec_path") Phase 2: context_split_spec_for_phase returned $?"
                    _split_failed=true
                    continue
                }

                local split_verify
                split_verify=$(context_verify_spec_split "$spec_content" "$phase1_split" "$phase2_split" "$phase1_sections" "$phase2_sections") \
                    || split_verify='{"pass":false,"errors":["verify script failed"]}'

                if [[ $(echo "$split_verify" | jq -r '.pass') != "true" ]]; then
                    echo "$split_verify" | jq -r '.errors[]' 2>/dev/null | while IFS= read -r err; do
                        log_error "Spec split verify ($(basename "$spec_path")): ${err}"
                    done
                    _split_failed=true
                else
                    echo "$split_verify" | jq -r '.warnings[] // empty' 2>/dev/null | while IFS= read -r warn; do
                        [[ -n "$warn" ]] && log_warn "Spec split ($(basename "$spec_path")): ${warn}"
                    done
                    log_step "$(basename "$spec_path"): Phase 1 $(printf '%s' "$phase1_split" | wc -c | tr -d ' ')c, Phase 2 $(printf '%s' "$phase2_split" | wc -c | tr -d ' ')c (original $(printf '%s' "$spec_content" | wc -c | tr -d ' ')c)"
                    _phase1_content["$spec_path"]="$phase1_split"
                    _phase2_content["$spec_path"]="$phase2_split"
                fi
            done

            # Hard stop: audit said split, but split failed
            if [[ "$_split_failed" == "true" ]]; then
                if [[ "${FORCE_NO_SPLIT:-}" == "true" ]] || [[ "${skip_split:-}" == "true" ]]; then
                    log_warn "Spec split failed but --skip-split is set — proceeding with full specs"
                else
                    log_error "Audit recommended phased planning but spec split failed."
                    log_error "The unsplit spec will likely timeout the architect (this is what caused the previous failure)."
                    log_error "Fix the audit's phase_sections, or re-run with --skip-split to force full spec."
                    exit $EXIT_GATE_FAILURE
                fi
            fi

            # ── Step 5: Feedback ──────────────────────────────────────────
            for spec_index in "${!plan_spec_paths[@]}"; do
                local spec_path="${plan_spec_paths[$spec_index]}"
                local spec_label="${plan_spec_labels[$spec_index]}"
                local phase1_sections="${_audit_phase1_sections[$spec_path]:-[]}"
                local phase2_sections="${_audit_phase2_sections[$spec_path]:-[]}"
                if [[ "$phase1_sections" == "[]" && "$phase2_sections" == "[]" ]]; then
                    log_step "${spec_label}: no phase_sections — full spec for both phases"
                else
                    log_step "${spec_label}: splitting (Phase 1 excludes $(echo "$phase2_sections" | jq length) sections, Phase 2 excludes $(echo "$phase1_sections" | jq length) sections)"
                fi
            done

            # ── Step 4: Phase 1 message ───────────────────────────────────
            local phase1_message=""
            for spec_index in "${!plan_spec_paths[@]}"; do
                local spec_path="${plan_spec_paths[$spec_index]}"
                local spec_label="${plan_spec_labels[$spec_index]}"
                local content="${_phase1_content[$spec_path]:-${plan_spec_contents[$spec_index]}}"
                phase1_message+="\n\n## ${spec_label}\n\n${content}"
            done
            if [[ -n "$SPEC_CODEBASE_CONTEXT" ]]; then
                phase1_message+="\n\n## Codebase Context (ground truth from automated scan)\n\n${SPEC_CODEBASE_CONTEXT}"
            fi
            if [[ -n "$related_specs" ]]; then
                phase1_message+="\n\n## Related Specs (cross-reference for entity relationships)\n${related_specs}"
            fi
            phase1_message+="\n\n## Phase Scope\n\n"
            phase1_message+="The audit estimated this spec will produce more than ${ARCHITECT_PHASE_TASK_THRESHOLD} tasks. "
            phase1_message+="You are generating Phase 1 (foundation tasks). "
            phase1_message+="Plan ONLY the foundation and core infrastructure sections.\n\n"
            phase1_message+="Audit sizing rationale:\n${audit_sizing_rationale}\n\n"
            phase1_message+="Focus on: data models, core services, base infrastructure. "
            phase1_message+="Leave higher-level features (API endpoints, UI, integration) for Phase 2."

            # Check for cached Phase 1 result
            local parsed_phase1=""

            if _plan_cache_valid "architect-phase1" "$architect_cache_hash"; then
                parsed_phase1=$(_plan_cache_read "architect-phase1")
                log_step "Phase 1: ${COLOR_DIM}restored from cache${RESET}"
            fi

            if [[ -z "$parsed_phase1" ]]; then
                log_step "Sending to Architect (Phase 1)..."
                echo ""
                parsed_phase1=$(_run_architect_phase "Architect (Phase 1)" "$phase1_message") || exit 1
                _plan_cache_write "architect-phase1" "$architect_cache_hash" "$parsed_phase1"
            fi

            # Extract Phase 1 task summaries — outside cache block, runs on both paths
            local phase1_tasks
            phase1_tasks=$(echo "$parsed_phase1" | jq -c '.tasks // []')
            local phase1_max_id
            phase1_max_id=$(echo "$phase1_tasks" | jq '[.[].id | tonumber] | max // 0')
            local phase1_start_id=1
            local phase2_start_id=$((phase1_max_id + 1))

            local phase1_summary=""
            local p1_len
            p1_len=$(echo "$phase1_tasks" | jq 'length')
            local p1_i=0
            while [[ $p1_i -lt $p1_len ]]; do
                local p1_id p1_title p1_files p1_deps p1_desc
                p1_id=$(echo "$phase1_tasks" | jq -r ".[$p1_i].id")
                p1_title=$(echo "$phase1_tasks" | jq -r ".[$p1_i].title")
                p1_deps=$(echo "$phase1_tasks" | jq -r ".[$p1_i].depends_on | join(\",\")")
                p1_files=$(echo "$phase1_tasks" | jq -r ".[$p1_i].files_touched | join(\", \")")
                p1_desc=$(echo "$phase1_tasks" | jq -r ".[$p1_i].description | split(\"\n\")[0]" | cut -c1-120)
                phase1_summary+="- Task ${p1_id}: ${p1_title} — depends on: [${p1_deps}] — files: ${p1_files}\n  ${p1_desc}\n"
                ((p1_i++)) || true
            done

            log_success "Phase 1: ${p1_len} tasks (IDs ${phase1_start_id}-${phase1_max_id})"
            echo ""

            # ── Step 4: Phase 2 message ───────────────────────────────────
            local phase2_message=""
            for spec_index in "${!plan_spec_paths[@]}"; do
                local spec_path="${plan_spec_paths[$spec_index]}"
                local spec_label="${plan_spec_labels[$spec_index]}"
                local content="${_phase2_content[$spec_path]:-${plan_spec_contents[$spec_index]}}"
                phase2_message+="\n\n## ${spec_label}\n\n${content}"
            done
            if [[ -n "$SPEC_CODEBASE_CONTEXT" ]]; then
                phase2_message+="\n\n## Codebase Context (ground truth from automated scan)\n\n${SPEC_CODEBASE_CONTEXT}"
            fi
            if [[ -n "$related_specs" ]]; then
                phase2_message+="\n\n## Related Specs (cross-reference for entity relationships)\n${related_specs}"
            fi
            phase2_message+="\n\n## Phase Scope\n\n"
            phase2_message+="You are generating Phase 2 (features and integration). "
            phase2_message+="Phase 1 tasks are already planned. Do NOT recreate them.\n\n"
            phase2_message+="Audit sizing rationale:\n${audit_sizing_rationale}\n\n"
            phase2_message+="### Phase 1 Tasks (already planned)\n\n${phase1_summary}\n"
            phase2_message+="**Starting task ID: ${phase2_start_id}**. All your task IDs must be >= ${phase2_start_id}.\n\n"
            phase2_message+="Set \`depends_on\` edges to Phase 1 tasks where your work needs their output.\n\n"
            phase2_message+="Focus on: API endpoints, higher-level services, frontend components, integration, tests."

            local parsed_phase2
            parsed_phase2=$(_run_architect_phase "Architect (Phase 2)" "$phase2_message") || exit 1

            local phase2_tasks
            phase2_tasks=$(echo "$parsed_phase2" | jq -c '.tasks // []')
            local p2_len
            p2_len=$(echo "$phase2_tasks" | jq 'length')
            log_success "Phase 2 complete: ${p2_len} tasks"
            echo ""

            # Merge phases into single parsed_architect
            local merged_tasks
            merged_tasks=$(jq -n --argjson p1 "$phase1_tasks" --argjson p2 "$phase2_tasks" '$p1 + $p2')

            # Merge contracts: concatenate entities and relationships
            local p1_contract p2_contract merged_contract
            p1_contract=$(echo "$parsed_phase1" | jq '.contract // {"entities":[],"relationships":[]}')
            p2_contract=$(echo "$parsed_phase2" | jq '.contract // {"entities":[],"relationships":[]}')
            merged_contract=$(jq -n \
                --argjson c1 "$p1_contract" \
                --argjson c2 "$p2_contract" \
                '{entities: ($c1.entities + $c2.entities), relationships: ($c1.relationships + $c2.relationships)}')

            # Merge validation arrays
            local p1_validation p2_validation merged_validation
            p1_validation=$(echo "$parsed_phase1" | jq -c '.validation // []')
            p2_validation=$(echo "$parsed_phase2" | jq -c '.validation // []')
            merged_validation=$(jq -n --argjson v1 "$p1_validation" --argjson v2 "$p2_validation" '$v1 + $v2')

            # Merge cross-cutting concerns (deduplicate by description)
            local p1_cc p2_cc merged_cc
            p1_cc=$(echo "$parsed_phase1" | jq -c '.cross_cutting_concerns // []')
            p2_cc=$(echo "$parsed_phase2" | jq -c '.cross_cutting_concerns // []')
            merged_cc=$(jq -n --argjson c1 "$p1_cc" --argjson c2 "$p2_cc" '$c1 + $c2 | unique_by(.description // .)')

            # Assemble merged result
            parsed_architect=$(jq -n \
                --argjson tasks "$merged_tasks" \
                --argjson contract "$merged_contract" \
                --argjson validation "$merged_validation" \
                --argjson cc "$merged_cc" \
                '{tasks: $tasks, contract: $contract, validation: $validation, cross_cutting_concerns: $cc}')

        else
            # ── Single-phase architect ─────────────────────────────────
            log_step "Sending to Architect agent..."
            echo ""

            parsed_architect=$(_run_architect_phase "Architect" "$base_message") || exit 1
        fi

        # Cache successful architect output
        _plan_cache_write "architect" "$architect_cache_hash" "$parsed_architect"
    fi

    # ── Coverage verification gate (G1: never silently wrong) ──────
    # Independent agent checks the merged task DAG against full specs.
    # Gated to phased planning for v1.
    if [[ "$audit_sizing_rec" == "split" ]] || [[ "${FORCE_COVERAGE:-}" == "true" ]]; then
    _run_coverage_check
    if [[ $_cov_critical -gt 0 ]]; then
        log_error "Coverage: ${_cov_critical} critical gap(s)"
        if [[ "${SKIP_COVERAGE:-}" == "true" ]]; then
            log_warn "SKIP_COVERAGE=true — proceeding"
            _log_gate_skip "coverage" "plan"
        elif [[ -t 0 ]]; then
            read -rp "Add missing task(s)? [y/N] " _reply
            if [[ "$_reply" =~ ^[Yy] ]]; then
                _repair_coverage_gaps
                _plan_cache_write "architect" \
                    "$architect_cache_hash" "$parsed_architect"
                _run_coverage_check
            fi
        else
            log_error "Override: SKIP_COVERAGE=true"
            exit 1
        fi
        [[ $_cov_critical -gt 0 ]] && \
            log_warn "Proceeding with ${_cov_critical} unresolved gap(s)"
    elif [[ $_cov_minor -gt 0 ]]; then
        log_warn "Coverage passed with ${_cov_minor} minor gap(s)"
    elif [[ -n "$_cov_parsed" ]]; then
        log_success "Coverage: $(echo "$_cov_parsed" | jq -r '.summary // "All requirements covered"')"
    fi
    fi  # end coverage gate (audit_sizing_rec == "split")
    echo ""

    # ── Validation gate ────────────────────────────────────────────
    # The architect validates coverage across product, tech, and design specs.
    # Critical issues = hard block. Warnings/notes = proceed with logging.
    local validation_json
    validation_json=$(echo "$parsed_architect" | jq '.validation // []')
    local validation_count
    validation_count=$(echo "$validation_json" | jq 'length')

    if [[ "$validation_count" -gt 0 ]]; then
        echo ""
        log_header "Validation Report"
        local has_critical=false
        local i=0
        while [[ $i -lt $validation_count ]]; do
            local severity issue product_req recommendation
            severity=$(echo "$validation_json" | jq -r ".[$i].severity")
            issue=$(echo "$validation_json" | jq -r ".[$i].issue")
            product_req=$(echo "$validation_json" | jq -r ".[$i].product_requirement")
            recommendation=$(echo "$validation_json" | jq -r ".[$i].recommendation")

            case "$severity" in
                critical)
                    echo -e "  ${COLOR_ERROR}${SYM_CROSS} CRITICAL:${RESET} ${issue}"
                    echo -e "    ${COLOR_DIM}Requirement:${RESET} ${product_req}"
                    echo -e "    ${COLOR_DIM}Fix:${RESET} ${recommendation}"
                    has_critical=true
                    ;;
                warning)
                    echo -e "  ${COLOR_WARN}${SYM_WARN} WARNING:${RESET} ${issue}"
                    echo -e "    ${COLOR_DIM}Requirement:${RESET} ${product_req}"
                    echo -e "    ${COLOR_DIM}Suggestion:${RESET} ${recommendation}"
                    ;;
                note)
                    echo -e "  ${COLOR_STEP}${SYM_DOT} NOTE:${RESET} ${issue}"
                    echo -e "    ${COLOR_DIM}${recommendation}${RESET}"
                    ;;
            esac
            echo ""
            ((i++)) || true
        done

        # Persist validation report
        echo "$validation_json" | jq '.' > "${LOGS_DIR}/validation-report.json"
        log_step "Validation report saved to ${LOGS_DIR}/validation-report.json"

        # Hard gate: critical issues block task creation
        if [[ "$has_critical" == "true" ]]; then
            log_error "Architect found CRITICAL validation issues — cannot create tasks"
            echo -e "Fix the spec issues above and re-run ${COLOR_STEP}speed plan${RESET}"
            exit 1
        fi
    else
        log_success "Validation clean — no issues found"
    fi
    echo ""

    # ── Extract tasks, contract, and cross-cutting concerns ─────────
    local tasks_json=""
    local contract_json=""
    local cross_cutting_json=""

    if echo "$parsed_architect" | jq -e '.tasks | type == "array"' &>/dev/null; then
        tasks_json=$(echo "$parsed_architect" | jq '.tasks')
        contract_json=$(echo "$parsed_architect" | jq '.contract // empty')
        cross_cutting_json=$(echo "$parsed_architect" | jq -c '.cross_cutting_concerns // []')
    else
        log_error "Architect output missing 'tasks' array"
        log_error "Raw output saved to ${LOGS_DIR}/architect-raw.log"
        exit 1
    fi

    # Save contract
    if [[ -n "$contract_json" ]] && echo "$contract_json" | jq -e '.' &>/dev/null; then
        echo "$contract_json" | jq '.' > "${CONTRACT_FILE}"
        log_success "Contract saved to ${CONTRACT_FILE}"
    else
        log_warn "No contract produced — verification will be limited"
    fi

    # Save cross-cutting concerns at feature level
    if [[ -n "$cross_cutting_json" ]] && [[ "$cross_cutting_json" != "[]" ]]; then
        echo "$cross_cutting_json" | jq '.' > "${FEATURE_DIR}/cross_cutting_concerns.json"
        local cc_count
        cc_count=$(echo "$cross_cutting_json" | jq 'length')
        log_step "Saved ${cc_count} cross-cutting concern(s)"
    fi

    # Clear existing tasks
    rm -f "${TASKS_DIR}"/*.json

    # Parse and create task files
    local task_count
    task_count=$(echo "$tasks_json" | jq 'length')

    if [[ "$task_count" -eq 0 ]]; then
        log_error "Architect produced 0 tasks"
        log_error "Raw output saved to ${LOGS_DIR}/architect-raw.log"
        exit 1
    fi

    log_step "Creating ${task_count} tasks..."
    echo ""

    local i=0
    while [[ $i -lt $task_count ]]; do
        local task
        task=$(echo "$tasks_json" | jq ".[$i]")

        local id title description criteria depends_on model files_touched
        id=$(echo "$task" | jq -r '.id')
        title=$(echo "$task" | jq -r '.title')
        description=$(echo "$task" | jq -r '.description')
        criteria=$(echo "$task" | jq -r '.acceptance_criteria')
        depends_on=$(echo "$task" | jq -c '.depends_on // []')
        model=$(echo "$task" | jq -r --arg def "$MODEL_SUPPORT" '.agent_model // $def')
        files_touched=$(echo "$task" | jq -c '.files_touched // []')

        task_create "$id" "$title" "$description" "$criteria" "$depends_on" "$model"

        # Store the current HEAD so diffs use the correct base
        task_update "$id" "base_commit" "$(_git rev-parse HEAD 2>/dev/null)"

        # Store files_touched in the task file
        if [[ "$files_touched" != "[]" ]]; then
            task_update_raw "$id" "files_touched" "$files_touched"
        fi

        # Store expanded schema fields (spec_references, rationale, assumptions)
        local spec_refs rationale assumptions
        spec_refs=$(echo "$task" | jq -c '.spec_references // []')
        rationale=$(echo "$task" | jq -r '.rationale // empty')
        assumptions=$(echo "$task" | jq -c '.assumptions // []')

        if [[ "$spec_refs" != "[]" ]]; then
            task_update_raw "$id" "spec_references" "$spec_refs"
        fi
        if [[ -n "$rationale" ]]; then
            task_update "$id" "rationale" "$rationale"
        fi
        if [[ "$assumptions" != "[]" ]]; then
            task_update_raw "$id" "assumptions" "$assumptions"
        fi

        ((i++)) || true
    done

    [[ "${MP_ENABLED:-}" == "true" ]] && event_emit "feature.planned" "$FEATURE_NAME" "{\"task_count\":$task_count,\"spec_path\":$(jq -n --arg p "$spec_file" '$p')}" || true

    log_success "Task DAG created with ${task_count} tasks"
    echo ""

    # ── Decomposition quality gate ────────────────────────────────
    # Validates task size, cross-cluster coordination, bridge symbol
    # exposure, and file ownership before proceeding.
    # Bridge symbol auto-patch: if the gate fails only on missing bridge
    # dependency edges, patch the task files and re-run the gate.
    if [[ "${SKIP_DECOMP:-}" == "true" ]]; then
        log_warn "Decomposition gate skipped (SKIP_DECOMP=true)"
        _log_gate_skip "decomposition" "plan"
    else
    log_step "Running decomposition quality gate..."
    local decomp_result
    decomp_result=$(context_decomposition_gate "${TASKS_DIR}" 2>/dev/null) || decomp_result=""

    if [[ -n "$decomp_result" ]]; then
        local decomp_overall
        decomp_overall=$(echo "$decomp_result" | jq -r '.overall // "pass"' 2>/dev/null)

        # ── Bridge symbol auto-patch ──────────────────────────────
        # If the gate failed, check whether the failures are exclusively
        # bridge-symbol missing-dependency edges. If so, patch depends_on
        # in the task JSON files and re-run the gate.
        if [[ "$decomp_overall" == "fail" ]]; then
            # Collect all missing bridge deps: affected_task needs depends_on → source_task
            # Source task = the task that modifies the bridge symbol (from per_task[].task_id)
            local bridge_patches
            bridge_patches=$(echo "$decomp_result" | jq -c '
                [.per_task[]? |
                 . as $pt |
                 .checks[]? |
                 select(.check == "bridge_symbols" and .verdict == "fail") |
                 .missing_dependencies[]? |
                 {affected_task: .affected_task, source_task: $pt.task_id}
                ] // []' 2>/dev/null) || bridge_patches="[]"

            local patch_count
            patch_count=$(echo "$bridge_patches" | jq 'length' 2>/dev/null) || patch_count=0

            # Check if there are non-bridge failures
            local non_bridge_failures
            non_bridge_failures=$(echo "$decomp_result" | jq '
                [.per_task[]? | .checks[]? |
                 select(.verdict == "fail" and .check != "bridge_symbols")
                ] + [.file_ownership | select(.violations | length > 0) | .violations[]?]
                | length' 2>/dev/null) || non_bridge_failures=0

            if [[ "$patch_count" -gt 0 ]] && [[ "$non_bridge_failures" -eq 0 ]]; then
                log_warn "Auto-patching ${patch_count} missing bridge-symbol dependency edge(s)..."

                echo "$bridge_patches" | jq -c '.[]' | while IFS= read -r patch; do
                    local affected_task source_task
                    affected_task=$(echo "$patch" | jq -r '.affected_task')
                    source_task=$(echo "$patch" | jq -r '.source_task')
                    local task_file="${TASKS_DIR}/${affected_task}.json"

                    if [[ -f "$task_file" ]]; then
                        # Add source_task to depends_on if not already present
                        local updated
                        updated=$(jq --arg dep "$source_task" '
                            .depends_on = ((.depends_on // []) + [$dep] | unique)
                        ' "$task_file")
                        echo "$updated" > "$task_file"
                        echo -e "    ${COLOR_STEP}${SYM_DOT} Task ${affected_task}: added depends_on → ${source_task}${RESET}"
                    fi
                done

                # Re-run the gate after patching
                log_step "Re-running decomposition gate after auto-patch..."
                decomp_result=$(context_decomposition_gate "${TASKS_DIR}" 2>/dev/null) || decomp_result=""
                if [[ -n "$decomp_result" ]]; then
                    decomp_overall=$(echo "$decomp_result" | jq -r '.overall // "pass"' 2>/dev/null)
                fi
            fi
        fi

        # Show per-task warnings
        local decomp_warnings
        decomp_warnings=$(echo "$decomp_result" | jq -r '.warnings[]? // empty' 2>/dev/null)
        if [[ -n "$decomp_warnings" ]]; then
            while IFS= read -r warn; do
                [[ -z "$warn" ]] && continue
                echo -e "    ${COLOR_WARN}${SYM_WARN} ${warn}${RESET}"
            done <<< "$decomp_warnings"
        fi

        # Show file ownership violations
        local ownership_violations
        ownership_violations=$(echo "$decomp_result" | jq -r '.file_ownership.violations[]? // empty' 2>/dev/null)
        if [[ -n "$ownership_violations" ]]; then
            while IFS= read -r v; do
                [[ -z "$v" ]] && continue
                echo -e "    ${COLOR_ERROR}${SYM_CROSS} File ownership: ${v}${RESET}"
            done <<< "$ownership_violations"
        fi

        if [[ "$decomp_overall" == "fail" ]]; then
            log_error "Decomposition quality gate FAILED"
            echo -e "The task plan has structural issues that will cause problems during execution."
            echo -e "Fix the plan and re-run ${COLOR_STEP}speed plan${RESET}"
            echo ""
            echo "$decomp_result" | jq '.' > "${LOGS_DIR}/decomposition-gate.json"
            log_step "Full report: ${LOGS_DIR}/decomposition-gate.json"
            exit 1
        elif [[ "$decomp_overall" == "warn" ]]; then
            log_warn "Decomposition quality gate passed with warnings"
        else
            log_success "Decomposition quality gate passed"
        fi
    else
        log_warn "Decomposition gate unavailable — skipping"
    fi
    fi # SKIP_DECOMP
    echo ""

    # Display task graph
    log_header "Task Graph"
    task_print_graph
    echo ""
    task_print_summary
    echo ""

    echo -e "${COLOR_DIM}Review tasks in ${TASKS_DIR}/${RESET}"
    echo -e "${COLOR_DIM}Next: ${COLOR_STEP}speed verify${RESET} to validate the plan against the spec${RESET}"
    echo ""
}
