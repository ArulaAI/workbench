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

# True when task $1 depends on task $2, directly or through other tasks.
# Reads depends_on from the task files in TASKS_DIR.
_plan_task_depends_on() {
    local start="$1" target="$2"
    local -a queue=("$start")
    local seen=" " current dep
    while [[ ${#queue[@]} -gt 0 ]]; do
        current="${queue[0]}"
        queue=("${queue[@]:1}")
        [[ "$seen" == *" ${current} "* ]] && continue
        seen+="${current} "
        [[ -f "${TASKS_DIR}/${current}.json" ]] || continue
        while IFS= read -r dep; do
            [[ -z "$dep" ]] && continue
            [[ "$dep" == "$target" ]] && return 0
            queue+=("$dep")
        done < <(jq -r '.depends_on[]? | tostring' "${TASKS_DIR}/${current}.json" 2>/dev/null)
    done
    return 1
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

# Cache key for the pre-plan Guardian: everything its verdict depends on, not
# just the specs (S3.5-TR2): product vision, injected learnings, the Guardian
# prompt and the model. A changed prompt reused a stale rejection.
_plan_guardian_cache_key() {
    local spec_hash="$1" mem="${STATE_DIR}/memory"
    [[ "${MP_ENABLED:-}" == "true" ]] && mem="$(mp_knowledge_dir 2>/dev/null || echo "$mem")"
    {
        printf 'spec:%s\nmodel:%s\n' "$spec_hash" "${MODEL_SUPPORT:-}"
        cat "${PROJECT_ROOT}/${VISION_FILE}" 2>/dev/null
        cat "${mem}/learnings/guardian-learnings.json" 2>/dev/null
        cat "${AGENTS_DIR}/product-guardian.md" 2>/dev/null
    } | shasum -a 256 | cut -d' ' -f1
}

_plan_cache_read() {
    cat "$(_plan_cache_dir)/${1}.dat"
}

# Cache key for one spec's audit. The audit reads the spec, its type template,
# the vision, linked and parent specs and the list of every spec, so the key
# hashes the whole specs/ tree with the prompt, templates and model. Re-planning
# unchanged specs no longer re-runs an audit agent per document.
_plan_audit_cache_key() {
    local spec_path="$1"
    {
        printf 'spec:%s\nmodel:%s\n' "${spec_path#${PROJECT_ROOT}/}" "${MODEL_SUPPORT:-}"
        cat "$spec_path" 2>/dev/null
        cat "${AGENTS_DIR}/audit.md" "${PROJECT_ROOT}/${VISION_FILE}" "${AGENT_FILE_PATH:-/dev/null}" 2>/dev/null
        cat "${TEMPLATES_DIR}"/{prd,rfc,design,architecture,defect}.md 2>/dev/null
        if [[ -d "${PROJECT_ROOT}/specs" ]]; then
            find "${PROJECT_ROOT}/specs" -name '*.md' -type f -print0 | sort -z \
                | xargs -0 shasum -a 256 2>/dev/null | sed "s|${PROJECT_ROOT}/||"
        fi
    } | shasum -a 256 | cut -d' ' -f1
}

# Two-pass planning (default): the planning model writes a skeleton (task
# boundaries, files, dependencies), the decomposition gate checks it, then the
# support model enriches it with criteria, spec references and the contract.
# --single-call or SPEED_PLAN_SINGLE_CALL=true keeps one Architect call.
_plan_two_pass() {
    [[ "${single_call:-false}" != "true" && "${SPEED_PLAN_SINGLE_CALL:-}" != "true" ]]
}

# Architect failure diagnostic (G2: failure is informative)
# Parses the JSONL event log and classifies the failure mode.
_diagnose_architect_failure() {
    local phase_label="$1"
    local raw_log="$2"

    log_error "Raw output saved to ${raw_log}"
    provider_diagnose_failure "$phase_label" "$raw_log" "$LOGS_DIR"
}

# Args: label message [agent_file] [schema_file] [model]
# Defaults to the one-call Architect. The skeleton pass and coverage repair also
# assign agent_model, so they get the model tiers; enrichment does not.
_run_architect_phase() {
    local phase_label="$1"
    local message="$2"
    local agent_file="${3:-${AGENTS_DIR}/architect.md}"
    local schema_file="${4:-${TEMPLATES_DIR}/architect-output.json}"
    local model="${5:-$MODEL_PLANNING}"

    # Inject model tier names so the architect uses the active provider's vocabulary
    [[ "$(basename "$agent_file")" != "architect-enrich.md" ]] && \
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
        "$agent_file" \
        "$message" \
        "$schema_file" \
        "$model" \
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

    local task_summary
    task_summary=$(echo "$parsed_architect" | jq -c '[.tasks[] | {
        id, title, description, spec_references,
        acceptance_criteria: (.acceptance_criteria
            | if type == "array" then map(if type == "object" then .criterion else . end) else . end)
    }]')

    # The verdict depends only on the specs, the tasks, the prompt and the
    # model, so an unchanged plan reuses it instead of paying for another read
    # of every spec. Only a parsed verdict is cached.
    local cov_key
    cov_key=$({
        printf '%s:%s\n' "${spec_hash:-}" "${MODEL_SUPPORT:-}"
        printf '%s' "$task_summary"
        cat "${AGENTS_DIR}/coverage-verifier.md" 2>/dev/null
    } | shasum -a 256 | cut -d' ' -f1)
    if [[ "${force_plan:-false}" != "true" ]] && _plan_cache_valid "coverage" "$cov_key"; then
        _cov_parsed=$(_plan_cache_read "coverage")
        log_step "Coverage: ${COLOR_DIM}cached (specs and tasks unchanged)${RESET}"
        _plan_coverage_evaluate
        return
    fi

    log_step "Verifying task coverage against full specs..."

    local msg=""
    [[ -n "$product_spec_content" ]] && msg+="## Product Spec\n\n${product_spec_content}\n\n"
    msg+="## Tech Spec\n\n${tech_spec_content}"
    [[ -n "$design_spec_content" ]] && msg+="\n\n## Design Spec\n\n${design_spec_content}"
    [[ -n "${architecture_spec_content:-}" ]] && msg+="\n\n## Architecture Spec\n\n${architecture_spec_content}"
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
    _plan_cache_write "coverage" "$cov_key" "$_cov_parsed"
    _plan_coverage_evaluate
}

# Set _cov_status, _cov_critical, _cov_minor and _cov_gaps from _cov_parsed and
# print the gaps. WARNING: Do not call inside $().
_plan_coverage_evaluate() {
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

# File Impact paths in $tech_spec_content that no task in $parsed_architect owns,
# as a JSON array. Prints [] when the check cannot run.
_plan_unowned_file_impact() {
    local spec_tmp tasks_tmp out
    spec_tmp=$(mktemp); tasks_tmp=$(mktemp)
    printf '%s' "$tech_spec_content" > "$spec_tmp"
    printf '%s' "$parsed_architect" > "$tasks_tmp"
    out=$("$(_context_python)" "${SPEED_DIR}/lib/file_impact.py" "$spec_tmp" "$tasks_tmp" 2>/dev/null) || out="[]"
    rm -f "$spec_tmp" "$tasks_tmp"
    echo "$out" | jq -e 'type == "array"' >/dev/null 2>&1 || out="[]"
    echo "$out"
}

# Planned tasks as markdown with full descriptions and acceptance criteria, so a
# later Architect call (Phase 2, coverage repair) builds on the same interfaces.
# A one-line summary hid them and the two halves of a phased plan disagreed.
# Skeleton tasks have no criteria yet, so the block is left out for them.
_plan_task_details() {
    echo "$1" | jq -r '.[] |
        ((.acceptance_criteria // [])
            | if type == "string" then .
              else map("- " + (if type == "object" then (.criterion // "") else tostring end)) | join("\n") end) as $criteria |
        "#### Task \(.id): \(.title)\n" +
        "Depends on: [\((.depends_on // []) | map(tostring) | join(", "))] | Files: \((.files_touched // []) | join(", "))\n\n" +
        "\(.description // "")\n" +
        (if $criteria != "" then "\nAcceptance criteria:\n" + $criteria + "\n" else "" end)'
}

# Stable context shared by every Architect call of one plan. It goes first in
# each message so Phase 1 and Phase 2 share a prompt prefix the provider can
# cache; the spec content that differs per phase follows it.
_plan_stable_context() {
    local ctx=""
    [[ -n "${shared_context_content:-}" ]] && \
        ctx+="## Shared Platform Architecture (constraints, not feature scope)\n\n${shared_context_content}\n\n"
    [[ -n "${SPEC_CODEBASE_CONTEXT:-}" ]] && \
        ctx+="## Codebase Context (ground truth from automated scan)\n\n${SPEC_CODEBASE_CONTEXT}\n\n"
    [[ -n "${related_specs:-}" ]] && \
        ctx+="## Related Specs (cross-reference for entity relationships)\n${related_specs}\n\n"
    printf '%s' "$ctx"
}

# Run the decomposition gate on the task files in $1, auto-patching missing
# bridge-symbol dependency edges. Prints warnings and violations.
# Returns 0 on pass or warn, 1 on fail (report in decomposition-gate.json),
# 2 when the gate is unavailable.
# WARNING: Do not call inside $(). Uses log_* which write to stdout.
_plan_decomposition_gate() {
    # _plan_task_depends_on reads TASKS_DIR; point it at the directory under check
    local TASKS_DIR="$1"
    local decomp_result
    decomp_result=$(context_decomposition_gate "${TASKS_DIR}" 2>/dev/null) || decomp_result=""

    if [[ -z "$decomp_result" ]]; then
        log_warn "Decomposition gate unavailable — skipping"
        return 2
    fi

    local decomp_overall
    decomp_overall=$(echo "$decomp_result" | jq -r '.overall // "pass"' 2>/dev/null)

    # ── Bridge symbol auto-patch ──────────────────────────────
    # If the gate failed, check whether the failures are exclusively
    # bridge-symbol missing-dependency edges. If so, patch depends_on
    # in the task JSON files and re-run the gate. Widening a bridge task can
    # expose new edges, so repeat for a few rounds until the plan settles.
    local patch_round=0
    while [[ "$decomp_overall" == "fail" ]] && (( patch_round < 3 )); do
        ((patch_round++)) || true
        # Collect all missing bridge deps: affected_task needs depends_on → source_task
        # Source task = the task that modifies the bridge symbol (from per_task[].task_id)
        local bridge_patches
        bridge_patches=$(echo "$decomp_result" | jq -c '
            [.per_task[]? |
             . as $pt |
             .checks[]? |
             select(.check == "bridge_symbols" and .verdict == "fail") |
             .missing_dependencies[]? |
             {affected_task: .affected_task, source_task: $pt.task_id,
              affected_files: (.affected_files // [])}
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
            # One patch per edge, applied in a fixed order: edges that point to an
            # earlier task first, so tasks sharing a file are chained by ID.
            bridge_patches=$(echo "$bridge_patches" | jq -c '
                group_by([.affected_task, .source_task])
                | map(.[0] + {affected_files: (map(.affected_files[]) | unique)})
                | sort_by([
                    ((.affected_task | tonumber? // 0) < (.source_task | tonumber? // 0)),
                    (.source_task | tonumber? // 0),
                    (.affected_task | tonumber? // 0)
                  ])')
            patch_count=$(echo "$bridge_patches" | jq 'length')
            log_warn "Auto-patching ${patch_count} missing bridge-symbol dependency edge(s)..."

            echo "$bridge_patches" | jq -c '.[]' | while IFS= read -r patch; do
                local affected_task source_task
                affected_task=$(echo "$patch" | jq -r '.affected_task')
                source_task=$(echo "$patch" | jq -r '.source_task')
                local task_file="${TASKS_DIR}/${affected_task}.json"

                # Never add an edge that closes a loop: if the source already
                # waits on the affected task, the pair is ordered the other way.
                # The bridge change then runs last, so it may edit the caller
                # files to update the call sites the earlier task wrote.
                if [[ "$affected_task" == "$source_task" ]] || \
                   _plan_task_depends_on "$source_task" "$affected_task"; then
                    local source_file="${TASKS_DIR}/${source_task}.json"
                    local caller_files
                    caller_files=$(echo "$patch" | jq -c '.affected_files')
                    if [[ "$affected_task" != "$source_task" ]] && [[ -f "$source_file" ]] && \
                       [[ "$caller_files" != "[]" ]]; then
                        local widened
                        widened=$(jq --argjson add "$caller_files" '
                            .files_touched = ((.files_touched // []) + ($add - (.files_touched // [])))
                        ' "$source_file")
                        echo "$widened" > "$source_file"
                        echo -e "    ${COLOR_STEP}${SYM_DOT} Task ${source_task}: already runs after ${affected_task}; may now update callers in $(echo "$caller_files" | jq -r 'join(", ")')${RESET}"
                    else
                        echo -e "    ${COLOR_DIM}${SYM_DOT} Task ${affected_task} → ${source_task}: skipped (already ordered the other way)${RESET}"
                    fi
                    continue
                fi

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
            else
                break
            fi
        else
            break
        fi
    done

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
        echo "$decomp_result" | jq '.' > "${LOGS_DIR}/decomposition-gate.json"
        return 1
    elif [[ "$decomp_overall" == "warn" ]]; then
        log_warn "Decomposition quality gate passed with warnings"
    else
        log_success "Decomposition quality gate passed"
    fi
    return 0
}

# Gate the skeleton before paying for enrichment: write its tasks to a scratch
# directory, run the decomposition gate (with bridge auto-patching) and read
# the patched depends_on and files_touched back into $parsed_architect.
# Exits when the skeleton fails the gate. WARNING: Do not call inside $().
_plan_gate_skeleton() {
    if [[ "${SKIP_DECOMP:-}" == "true" ]]; then
        return 0
    fi
    log_step "Running decomposition gate on the skeleton..."
    local skel_dir
    skel_dir=$(mktemp -d)
    echo "$parsed_architect" | jq -c '.tasks[]' | while IFS= read -r t; do
        printf '%s\n' "$t" > "${skel_dir}/$(echo "$t" | jq -r '.id').json"
    done

    local gate_rc=0
    _plan_decomposition_gate "$skel_dir" || gate_rc=$?
    if [[ $gate_rc -eq 1 ]]; then
        echo "$parsed_architect" | jq '.' > "${LOGS_DIR}/architect-skeleton-rejected.json"
        rm -rf "$skel_dir"
        log_error "Decomposition quality gate FAILED on the skeleton — enrichment not run"
        echo -e "Skeleton: ${LOGS_DIR}/architect-skeleton-rejected.json"
        echo -e "Full report: ${LOGS_DIR}/decomposition-gate.json"
        echo -e "Fix the spec (or task boundaries it implies) and re-run ${COLOR_STEP}speed plan --force${RESET}"
        exit 1
    fi

    local patched
    patched=$(jq -s 'map({key: (.id | tostring), value: {depends_on, files_touched}}) | from_entries' \
        "$skel_dir"/*.json 2>/dev/null) || patched="{}"
    rm -rf "$skel_dir"
    parsed_architect=$(echo "$parsed_architect" | jq --argjson p "$patched" \
        '.tasks |= map(. + ($p[.id | tostring] // {}))')
}

# Enrich the skeleton in $parsed_architect with acceptance criteria, spec
# references, rationale, assumptions and the contract. The support model does
# this: the boundaries are already decided. Tasks it skips get one retry.
# Exits when any task stays unenriched. WARNING: Do not call inside $().
_plan_enrich_skeleton() {
    local specs_msg=""
    local spec_index
    for spec_index in "${!plan_spec_paths[@]}"; do
        specs_msg+="## ${plan_spec_labels[$spec_index]}\n\n${plan_spec_contents[$spec_index]}\n\n"
    done

    local pending enriched='[]' contract='{"entities":[],"relationships":[],"core_queries":[]}'
    pending=$(echo "$parsed_architect" | jq -c '{tasks: [.tasks[] | {id, title, description, files_touched, depends_on}],
        cross_cutting_concerns: (.cross_cutting_concerns // [])}')

    local attempt
    for attempt in 1 2; do
        local msg="${specs_msg}## Skeleton Plan\n\nEnrich every task below. Use these task IDs exactly.\n\n\`\`\`json\n${pending}\n\`\`\`"
        local label="Architect (enrich)"
        [[ $attempt -gt 1 ]] && label="Architect (enrich retry)"
        log_step "Enriching $(echo "$pending" | jq '.tasks | length') task(s) with ${MODEL_SUPPORT}..."

        local parsed_enrich
        parsed_enrich=$(_run_architect_phase "$label" "$msg" \
            "${AGENTS_DIR}/architect-enrich.md" "${TEMPLATES_DIR}/architect-enrich-output.json" \
            "$MODEL_SUPPORT") || exit 1

        enriched=$(jq -n --argjson a "$enriched" --argjson b "$parsed_enrich" \
            '$a + [($b.tasks // [])[] | select((.acceptance_criteria // []) | length > 0)
                   | {id: (.id | tostring), acceptance_criteria, spec_references, rationale, assumptions}]')
        contract=$(jq -n --argjson a "$contract" --argjson b "$parsed_enrich" '
            ($b.contract // {}) as $c
            | {core_question: ($a.core_question // $c.core_question),
               entities: ($a.entities + ($c.entities // [])),
               relationships: ($a.relationships + ($c.relationships // [])),
               core_queries: ($a.core_queries + ($c.core_queries // []))}')

        pending=$(echo "$pending" | jq -c --argjson done "$enriched" \
            '($done | map(.id)) as $ids | .tasks |= map(select((.id | tostring) as $i | $ids | index($i) | not))')
        [[ $(echo "$pending" | jq '.tasks | length') -eq 0 ]] && break
        log_warn "Enrichment skipped task(s): $(echo "$pending" | jq -r '[.tasks[].id] | join(", ")')"
    done

    if [[ $(echo "$pending" | jq '.tasks | length') -gt 0 ]]; then
        log_error "Enrichment left task(s) without acceptance criteria: $(echo "$pending" | jq -r '[.tasks[].id] | join(", ")')"
        log_error "Re-run speed plan (the skeleton is cached), or plan with --single-call"
        exit 1
    fi

    parsed_architect=$(echo "$parsed_architect" | jq --argjson e "$enriched" --argjson c "$contract" '
        ($e | map({key: .id, value: (. | del(.id))}) | from_entries) as $m
        | .tasks |= map(. + ($m[.id | tostring] // {}))
        | .contract = $c')
    log_success "Enriched $(echo "$enriched" | jq 'length') task(s)"
}

# Decide whether to repair critical coverage gaps (S3.4-TR2): in a terminal,
# ask; with SKIP_COVERAGE=true, proceed without repair and log the bypass;
# otherwise stop. Returns 0 to repair, 1 to proceed without repair.
_plan_confirm_repair() {
    local question="$1" _reply
    if [[ "${SKIP_COVERAGE:-}" == "true" ]]; then
        log_warn "SKIP_COVERAGE=true — proceeding with ${_cov_critical} coverage gap(s)"
        _log_gate_skip "coverage" "plan"
        return 1
    fi
    if [[ -t 0 ]]; then
        read -rp "${question} [y/N] " _reply
        [[ "$_reply" =~ ^[Yy] ]] && return 0
        log_warn "Proceeding without adding tasks"
        return 1
    fi
    log_error "Plan has ${_cov_critical} critical coverage gap(s) and no terminal to confirm adding tasks"
    log_error "Run speed plan in a terminal and answer y to add them, or set SKIP_COVERAGE=true to proceed with the gaps"
    exit "$EXIT_GATE_FAILURE"
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
    task_summary=$(_plan_task_details "$(echo "$parsed_architect" | jq -c '.tasks // []')")

    local gap_text
    gap_text=$(echo "$_cov_gaps" | jq -r '.[] | "- [\(.severity)] \(.spec): \(.section) — \(.requirement)\n  Explanation: \(.explanation)"')

    # Specs first: they are the same in every repair call, the plan is not
    local msg=""
    [[ -n "$product_spec_content" ]] && msg+="## Product Spec\n\n${product_spec_content}\n\n"
    msg+="## Tech Spec\n\n${tech_spec_content}\n\n"
    [[ -n "$design_spec_content" ]] && msg+="## Design Spec\n\n${design_spec_content}\n\n"
    [[ -n "${architecture_spec_content:-}" ]] && msg+="## Architecture Spec\n\n${architecture_spec_content}\n\n"
    msg+="## Existing Plan\n\n${task_summary}\n\n"
    msg+="## Coverage Gaps\n\n${gap_text}\n\n"
    msg+="## Instructions\n\nAdd task(s) for the gaps above. "
    msg+="IDs start at ${start_id}. Do not recreate existing tasks. "
    msg+="Set depends_on where needed. Only output NEW tasks. "
    msg+="Use the functions, types, fields and error names the existing tasks define.\n"

    log_step "Generating task(s) for ${_cov_critical} gap(s)..."
    echo ""

    # The one-call Architect writes complete tasks; a few gap tasks are small
    # enough that a skeleton/enrich split would cost more than it saves.
    local parsed_add
    parsed_add=$(_run_architect_phase "Architect (add-task)" "$msg") || {
        log_error "Add-task call failed"
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
    # The first argument is the spec file unless it is an option, so
    # `speed plan --feature NAME --skip-audit` works without a file.
    local spec_file=""
    if [[ -n "${1:-}" && "${1}" != -* ]]; then
        spec_file="$1"
        shift
    fi
    local specs_dir=""
    local force_plan=false
    local skip_audit=false
    local single_pass=false
    local single_call=false

    # Parse options
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --specs-dir) _need_value "$@"; specs_dir="$2"; shift 2 ;;
            --force) force_plan=true; shift ;;
            --skip-audit) skip_audit=true; shift ;;
            --single-pass) single_pass=true; shift ;;
            --single-call) single_call=true; shift ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    # ── Feature mode: plan every document of one feature ──────────
    # `speed plan --feature NAME` with no file discovers all of the
    # feature's product, architecture, design and tech documents.
    local feature_mode=false
    local -a feature_doc_kinds=() feature_doc_paths=()
    local architecture_spec_content="" shared_context_content=""
    if [[ -z "$spec_file" && -n "${GLOBAL_FEATURE:-}" ]]; then
        feature_mode=true

        # `--feature specs/<kind>/<feature>/<doc>.md` names the feature through
        # one of its documents. The whole feature is planned, not just that file.
        if [[ "$GLOBAL_FEATURE" == */* || "$GLOBAL_FEATURE" == *.md ]]; then
            local _doc_arg="$GLOBAL_FEATURE" _doc_path=""
            if [[ -f "$_doc_arg" ]]; then
                _doc_path="$_doc_arg"
            elif [[ -f "${PROJECT_ROOT}/${_doc_arg}" ]]; then
                _doc_path="${PROJECT_ROOT}/${_doc_arg}"
            fi
            if [[ -z "$_doc_path" ]]; then
                log_error_block \
                    "Spec file not found: ${_doc_arg}" \
                    "--feature takes a feature name or a path to one of the feature's documents" \
                    "Check the path, or use the name, e.g. speed plan --feature adaptive-auth"
                exit $EXIT_CONFIG_ERROR
            fi
            if [[ -L "$_doc_path" ]]; then
                log_error_block \
                    "Spec file is a symlink: ${_doc_arg}" \
                    "Feature documents are identified by their real path" \
                    "Pass the file the link points to"
                exit $EXIT_CONFIG_ERROR
            fi
            _doc_path="$(speed_abs_dir "$(dirname "$_doc_path")")/$(basename "$_doc_path")"
            if [[ "$_doc_path" != "${PROJECT_ROOT}/specs/"* ]] || \
               ! [[ "$_doc_path" =~ /specs/(product|design|tech|architecture)/ ]]; then
                log_error_block \
                    "Not a feature document: ${_doc_arg}" \
                    "Expected a file under specs/product, specs/design, specs/tech or specs/architecture in this project" \
                    "Use e.g. speed plan --feature specs/design/adaptive-auth/2-risk-review-queue.md"
                exit $EXIT_CONFIG_ERROR
            fi
            GLOBAL_FEATURE=$(feature_name_from_spec "$_doc_path")
            log_info "Feature ${COLOR_STEP}${GLOBAL_FEATURE}${RESET} from ${_doc_path#${PROJECT_ROOT}/} (planning the whole feature)"
        fi

        if ! [[ "$GLOBAL_FEATURE" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || [[ "$GLOBAL_FEATURE" == "overview" ]]; then
            log_error_block \
                "Invalid feature name: ${GLOBAL_FEATURE}" \
                "Feature names use lowercase letters, digits and hyphens; 'overview' is reserved for shared documents" \
                "Use e.g. speed plan --feature adaptive-auth"
            exit $EXIT_CONFIG_ERROR
        fi
        local _kind _path
        while IFS=$'\t' read -r _kind _path; do
            [[ -z "$_path" ]] && continue
            feature_doc_kinds+=("$_kind")
            feature_doc_paths+=("$_path")
        done < <(feature_discover_specs "$GLOBAL_FEATURE")

        if [[ ${#feature_doc_paths[@]} -eq 0 ]]; then
            log_error_block \
                "No documents found for feature '${GLOBAL_FEATURE}'" \
                "Looked in specs/{product,architecture,design,tech}/${GLOBAL_FEATURE}/ and specs/<kind>/${GLOBAL_FEATURE}.md" \
                "Check the feature name or create its specs"
            exit $EXIT_CONFIG_ERROR
        fi
        # The entry document is the first tech spec; at least one is required.
        local _i
        for _i in "${!feature_doc_kinds[@]}"; do
            if [[ "${feature_doc_kinds[$_i]}" == "tech" ]]; then
                spec_file="${feature_doc_paths[$_i]}"
                break
            fi
        done
        if [[ -z "$spec_file" ]]; then
            log_error_block \
                "Feature '${GLOBAL_FEATURE}' has no tech spec" \
                "Plan needs at least one RFC in specs/tech/${GLOBAL_FEATURE}/" \
                "Write the tech spec (e.g. speed new rfc ${GLOBAL_FEATURE}) and re-run"
            exit $EXIT_CONFIG_ERROR
        fi
    fi

    if [[ -z "$spec_file" ]]; then
        log_error "Usage: speed plan <tech-spec-file> [--specs-dir DIR]"
        log_error "       speed plan --feature NAME [--specs-dir DIR]"
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

    # plan decomposes a tech spec. A product, design or architecture document
    # was planned as if it were the RFC, with nonsense sibling lookups.
    if [[ "$feature_mode" != "true" ]] && [[ "$spec_file" =~ (^|/)specs/(product|design|architecture)/ ]]; then
        local _kind="${BASH_REMATCH[2]}" _rfc
        _rfc=$(echo "$spec_file" | sed -E "s#(^|/)specs/${_kind}/#\1specs/tech/#")
        log_error_block \
            "Not a tech spec: ${spec_file#${PROJECT_ROOT}/}" \
            "speed plan takes a tech spec (specs/tech/...); this is a ${_kind} document" \
            "$( if [[ "$(basename "$spec_file")" == "overview.md" ]]; then echo "This is a shared overview, not a feature document: plan a feature's tech spec, or speed plan --feature NAME"
                elif [[ -f "$_rfc" ]]; then echo "Plan the RFC: speed plan ${_rfc#${PROJECT_ROOT}/}, or the whole feature: speed plan --feature ${spec_file#${PROJECT_ROOT}/}"
                else echo "Plan the whole feature: speed plan --feature ${spec_file#${PROJECT_ROOT}/}"; fi )"
        exit $EXIT_CONFIG_ERROR
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

    # Fallback: follow the spec's "> See [...](path)" links when the filename
    # convention finds nothing, e.g. specs/tech/payments-v2.md linking to
    # ../product/payments.md. Audit already resolves the PRD this way.
    if [[ -z "$product_spec_file" ]] || [[ -z "$design_spec_file" ]]; then
        local _see_link _see_path _spec_dir
        _spec_dir=$(dirname "$spec_file")
        while IFS= read -r _see_link; do
            [[ -z "$_see_link" ]] && continue
            _see_path=""
            if [[ "$_see_link" == /* ]] && [[ -f "$_see_link" ]]; then
                _see_path="$_see_link"
            elif [[ -f "${_spec_dir}/${_see_link}" ]]; then
                _see_path="${_spec_dir}/${_see_link}"
            elif [[ -f "${PROJECT_ROOT}/${_see_link}" ]]; then
                _see_path="${PROJECT_ROOT}/${_see_link}"
            fi
            [[ -n "$_see_path" ]] || continue
            # Normalise ../ segments so the directory check sees the real location
            _see_path="$(speed_abs_dir "$(dirname "$_see_path")")/$(basename "$_see_path")"
            # The product vision is Guardian input, not this feature's PRD
            [[ "$(basename "$_see_path")" == "overview.md" ]] && continue
            case "$_see_path" in
                */specs/product/*)
                    if [[ -z "$product_spec_file" ]]; then product_spec_file="$_see_path"; fi ;;
                */specs/design/*)
                    if [[ -z "$design_spec_file" ]]; then design_spec_file="$_see_path"; fi ;;
            esac
        done < <(grep -E '^> See ' "$spec_file" | grep -oE '\]\([^)#]+' | sed 's/^](//' || true)
    fi

    # Feature mode registers every discovered document itself
    if [[ "$feature_mode" == "true" ]]; then
        product_spec_file=""
        design_spec_file=""
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

    # Feature mode also records every planned document so verify checks the
    # plan against the whole feature. A single-file plan removes any list left
    # by an earlier feature-mode plan, so verify falls back to spec_path.
    local _spec_docs_file="${FEATURE_DIR:-${STATE_DIR}}/spec_documents"
    if [[ "$feature_mode" == "true" ]]; then
        local _i
        : > "$_spec_docs_file"
        for _i in "${!feature_doc_paths[@]}"; do
            printf '%s\t%s\n' "${feature_doc_kinds[$_i]}" "${feature_doc_paths[$_i]#${PROJECT_ROOT}/}" >> "$_spec_docs_file"
        done
    else
        rm -f "$_spec_docs_file"
    fi

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
    local tech_spec_content="" product_spec_content="" design_spec_content=""

    if [[ "$feature_mode" == "true" ]]; then
        # Every document is labelled with its path, so agents can tell
        # 1-….md from 2-….md and cite the right file.
        local _i _rel _body
        for _i in "${!feature_doc_paths[@]}"; do
            _rel="${feature_doc_paths[$_i]#${PROJECT_ROOT}/}"
            _body="### ${_rel}"$'\n\n'"$(cat "${feature_doc_paths[$_i]}")"$'\n\n'
            case "${feature_doc_kinds[$_i]}" in
                product)      product_spec_content+="$_body" ;;
                architecture) architecture_spec_content+="$_body" ;;
                design)       design_spec_content+="$_body" ;;
                tech)         tech_spec_content+="$_body" ;;
            esac
            log_step "$(printf '%-13s' "${feature_doc_kinds[$_i]}:") ${COLOR_STEP}${_rel}${RESET}"
        done
        # Shared platform architecture: constraints, not feature scope
        if [[ -f "${PROJECT_ROOT}/specs/architecture/overview.md" ]]; then
            shared_context_content="### specs/architecture/overview.md"$'\n\n'"$(cat "${PROJECT_ROOT}/specs/architecture/overview.md")"
            log_step "$(printf '%-13s' "shared:") ${COLOR_STEP}specs/architecture/overview.md${RESET} ${COLOR_DIM}(constraints)${RESET}"
        else
            log_warn "No shared architecture overview (specs/architecture/overview.md)"
        fi
        [[ -z "$product_spec_content" ]] && log_warn "Feature '${feature_name}' has no product spec"
        [[ -z "$design_spec_content" ]] && log_warn "Feature '${feature_name}' has no design spec"
        [[ -z "$architecture_spec_content" ]] && log_warn "Feature '${feature_name}' has no architecture spec"
    else
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
        tech_spec_content=$(cat "$spec_file")
        if [[ -n "$product_spec_file" ]]; then
            product_spec_content=$(cat "$product_spec_file")
        fi
        if [[ -n "$design_spec_file" ]]; then
            design_spec_content=$(cat "$design_spec_file")
        fi
    fi

    # ── Spec hash for stage caching ───────────────────────────────
    # Architecture and shared context are empty outside feature mode, so
    # single-file cache keys are unchanged.
    local spec_hash
    spec_hash=$(printf '%s' "${tech_spec_content}${product_spec_content}${design_spec_content}${architecture_spec_content}${shared_context_content}" | shasum -a 256 | cut -d' ' -f1)

    # ── Pre-Plan Guardian Gate ─────────────────────────────────────
    # Check: does this spec belong in the product?
    local guardian_rc=0 guardian_key
    guardian_key=$(_plan_guardian_cache_key "$spec_hash")
    if [[ "$force_plan" != "true" ]] && _plan_cache_valid "guardian" "$guardian_key"; then
        guardian_rc=$(_plan_cache_read "guardian")
        log_step "Guardian: ${COLOR_DIM}cached (specs, vision, learnings and Guardian prompt unchanged)${RESET}"
        if [[ "$guardian_rc" != "0" ]]; then
            local _cached_report
            _cached_report=$(ls -t "${LOGS_DIR}"/guardian-pre-plan-*.json 2>/dev/null | head -1) || true
            [[ -n "$_cached_report" ]] && log_step "Cached Guardian report: ${_cached_report}"
        fi
    else
        log_step "Running pre-plan vision check..."
        local _guardian_input="$tech_spec_content"
        if [[ "$feature_mode" == "true" ]]; then
            _guardian_input="## Feature: ${feature_name} (all documents)"$'\n\n'
            [[ -n "$product_spec_content" ]] && _guardian_input+="## Product Specs"$'\n\n'"${product_spec_content}"
            [[ -n "$architecture_spec_content" ]] && _guardian_input+="## Architecture Specs"$'\n\n'"${architecture_spec_content}"
            [[ -n "$design_spec_content" ]] && _guardian_input+="## Design Specs"$'\n\n'"${design_spec_content}"
            _guardian_input+="## Tech Specs"$'\n\n'"${tech_spec_content}"
            [[ -n "$shared_context_content" ]] && \
                _guardian_input+=$'\n\n'"## Shared Platform Architecture (constraints, not feature scope)"$'\n\n'"${shared_context_content}"
        fi
        local _guardian_out
        _guardian_out=$(_run_guardian "pre-plan" "$_guardian_input" "$spec_file") || guardian_rc=$?
        # An unparseable verdict (3) is not a decision; never reuse it.
        [[ "$guardian_rc" != "3" ]] && _plan_cache_write "guardian" "$guardian_key" "$guardian_rc"
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

    if [[ "$feature_mode" == "true" ]]; then
        # One entry per document, labelled with kind and path
        local _i _label
        for _i in "${!feature_doc_paths[@]}"; do
            case "${feature_doc_kinds[$_i]}" in
                product)      _label="Product Spec" ;;
                architecture) _label="Architecture Spec" ;;
                design)       _label="Design Spec" ;;
                tech)         _label="Tech Spec" ;;
            esac
            _register_plan_spec "${feature_doc_paths[$_i]}" "$(cat "${feature_doc_paths[$_i]}")" \
                "${_label}: ${feature_doc_paths[$_i]#${PROJECT_ROOT}/}"
        done
    else
        _register_plan_spec "$spec_file" "$tech_spec_content" "Tech Spec (backend implementation)"

        [[ -n "$product_spec_file" ]] && \
            _register_plan_spec "$product_spec_file" "$product_spec_content" "Product Spec (what to build)"
        [[ -n "$design_spec_file" ]] && \
            _register_plan_spec "$design_spec_file" "$design_spec_content" "Design Spec (frontend implementation)"
    fi

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
        # Keep the plan-audit-{type}-{number}.json shape the dashboard reads,
        # but never reuse a name: two tech specs can be audited in one second.
        local _audit_stamp
        _audit_stamp=$(date +%s)
        while [[ -e "${LOGS_DIR}/plan-audit-${spec_type:-spec${spec_index}}-${_audit_stamp}.json" ]]; do
            _audit_stamp=$((_audit_stamp + 1))
        done
        local spec_audit_file="${LOGS_DIR}/plan-audit-${spec_type:-spec${spec_index}}-${_audit_stamp}.json"

        # A passing audit of unchanged inputs is reused; a failing one is not,
        # so a fixed spec is always audited again.
        local audit_rc=0 audit_key audit_stage="audit-${spec_index}"
        audit_key=$(_plan_audit_cache_key "$spec_path")
        if [[ "$force_plan" != "true" ]] && _plan_cache_valid "$audit_stage" "$audit_key"; then
            _plan_cache_read "$audit_stage" > "$spec_audit_file"
            log_step "Audit (${spec_label}): ${COLOR_DIM}cached (spec, linked specs and audit prompt unchanged)${RESET}"
        else
            (AUDIT_OUTPUT_FILE="$spec_audit_file"; cmd_audit "$spec_path") || audit_rc=$?
            [[ $audit_rc -eq 0 && -s "$spec_audit_file" ]] && \
                _plan_cache_write "$audit_stage" "$audit_key" "$(cat "$spec_audit_file")"
        fi

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
                # S3.4-TR1: an audit that cannot complete stops Plan.
                log_error "Audit could not complete for ${spec_label} (exit ${audit_rc}) — Plan stops"
                log_error "Re-run speed plan, or bypass the audit explicitly with --skip-audit"
                exit "$EXIT_GATE_FAILURE"
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
    if [[ "$feature_mode" == "true" ]]; then
        local _doc _doc_escaped
        for _doc in "${feature_doc_paths[@]}"; do
            _doc_escaped=$(jq -Rs '.' < "$_doc")
            spec_files_for_l1=$(echo "$spec_files_for_l1" | jq --arg path "$_doc" --argjson content "$_doc_escaped" '. + {($path): $content}')
        done
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
    # Skeleton pass or one-call Architect: the prompt and schema for the
    # planning-model call(s) below
    local arch_mode="single-call"
    local arch_agent="${AGENTS_DIR}/architect.md"
    local arch_schema="${TEMPLATES_DIR}/architect-output.json"
    if _plan_two_pass; then
        arch_mode="two-pass"
        arch_agent="${AGENTS_DIR}/architect-skeleton.md"
        arch_schema="${TEMPLATES_DIR}/architect-skeleton.json"
    fi

    local architect_cache_hash
    # Key on everything the plan depends on: specs, phase count, planning mode,
    # Architect prompts, schemas and models. Prompt changes must not reuse a
    # plan made with the old prompts.
    architect_cache_hash=$({
        printf '%s:%s:%s:%s:%s\n' "$spec_hash" "$phase_count" "$arch_mode" "${MODEL_PLANNING:-}" "${MODEL_SUPPORT:-}"
        if [[ "$arch_mode" == "two-pass" ]]; then
            cat "${AGENTS_DIR}/architect-skeleton.md" "${AGENTS_DIR}/architect-enrich.md" \
                "${TEMPLATES_DIR}/architect-skeleton.json" "${TEMPLATES_DIR}/architect-enrich-output.json" 2>/dev/null
        else
            cat "${AGENTS_DIR}/architect.md" "${TEMPLATES_DIR}/architect-output.json" 2>/dev/null
        fi
    } | shasum -a 256 | cut -d' ' -f1)

    if [[ "$force_plan" != "true" ]] && _plan_cache_valid "architect" "$architect_cache_hash"; then
        parsed_architect=$(_plan_cache_read "architect")
        log_step "Architect: ${COLOR_DIM}cached (specs unchanged)${RESET}"
        echo ""
    elif [[ "$arch_mode" == "two-pass" && "$force_plan" != "true" ]] && \
         _plan_cache_valid "architect-skeleton" "$architect_cache_hash"; then
        # The skeleton passed the gate last time; only enrichment is left
        parsed_architect=$(_plan_cache_read "architect-skeleton")
        log_step "Skeleton: ${COLOR_DIM}cached (specs unchanged)${RESET}"
        _plan_enrich_skeleton
        _plan_cache_write "architect" "$architect_cache_hash" "$parsed_architect"
        echo ""
    else
        # Stable context first so every Architect call shares the prefix
        local stable_context
        stable_context=$(_plan_stable_context)

        # Build base architect message (single-phase)
        local base_message="$stable_context"

        if [[ -n "$product_spec_content" ]]; then
            base_message+="## Product Spec (what to build)\n\n${product_spec_content}\n\n"
        fi

        base_message+="## Tech Spec (backend implementation)\n\n${tech_spec_content}"

        if [[ -n "$design_spec_content" ]]; then
            base_message+="\n\n## Design Spec (frontend implementation)\n\n${design_spec_content}"
        fi

        # Feature mode only: empty for single-file plans
        if [[ -n "$architecture_spec_content" ]]; then
            base_message+="\n\n## Architecture Spec (boundaries and quality constraints)\n\n${architecture_spec_content}"
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
                local _split_rc=0
                phase1_split=$(context_split_spec_for_phase "$spec_content" "$phase2_sections" 2>&1) || _split_rc=$?
                if [[ $_split_rc -ne 0 ]]; then
                    log_error "Spec split failed for $(basename "$spec_path") Phase 1 (exit ${_split_rc}): $(printf '%s' "$phase1_split" | tail -1)"
                    _split_failed=true
                    continue
                fi
                phase2_split=$(context_split_spec_for_phase "$spec_content" "$phase1_sections" 2>&1) || _split_rc=$?
                if [[ $_split_rc -ne 0 ]]; then
                    log_error "Spec split failed for $(basename "$spec_path") Phase 2 (exit ${_split_rc}): $(printf '%s' "$phase2_split" | tail -1)"
                    _split_failed=true
                    continue
                fi

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
                    log_warn "Spec split failed but FORCE_NO_SPLIT=true — proceeding with full specs"
                else
                    log_error "Audit recommended phased planning but spec split failed."
                    log_error "The unsplit spec will likely timeout the architect (this is what caused the previous failure)."
                    log_error "Re-run the plan (the audit assigns sections again), or plan in one pass with --single-pass."
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
            local phase1_message="$stable_context"
            for spec_index in "${!plan_spec_paths[@]}"; do
                local spec_path="${plan_spec_paths[$spec_index]}"
                local spec_label="${plan_spec_labels[$spec_index]}"
                local content="${_phase1_content[$spec_path]:-${plan_spec_contents[$spec_index]}}"
                phase1_message+="## ${spec_label}\n\n${content}\n\n"
            done
            phase1_message+="## Phase Scope\n\n"
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
                parsed_phase1=$(_run_architect_phase "Architect (Phase 1)" "$phase1_message" "$arch_agent" "$arch_schema") || exit 1
                _plan_cache_write "architect-phase1" "$architect_cache_hash" "$parsed_phase1"
            fi

            # Extract Phase 1 task summaries — outside cache block, runs on both paths
            local phase1_tasks
            phase1_tasks=$(echo "$parsed_phase1" | jq -c '.tasks // []')
            local phase1_max_id
            phase1_max_id=$(echo "$phase1_tasks" | jq '[.[].id | tonumber] | max // 0')
            local phase1_start_id=1
            local phase2_start_id=$((phase1_max_id + 1))

            local p1_len phase1_summary
            p1_len=$(echo "$phase1_tasks" | jq 'length')
            phase1_summary=$(_plan_task_details "$phase1_tasks")

            log_success "Phase 1: ${p1_len} tasks (IDs ${phase1_start_id}-${phase1_max_id})"
            echo ""

            # ── Step 4: Phase 2 message ───────────────────────────────────
            local phase2_message="$stable_context"
            for spec_index in "${!plan_spec_paths[@]}"; do
                local spec_path="${plan_spec_paths[$spec_index]}"
                local spec_label="${plan_spec_labels[$spec_index]}"
                local content="${_phase2_content[$spec_path]:-${plan_spec_contents[$spec_index]}}"
                phase2_message+="## ${spec_label}\n\n${content}\n\n"
            done
            phase2_message+="## Phase Scope\n\n"
            phase2_message+="You are generating Phase 2 (features and integration). "
            phase2_message+="Phase 1 tasks are already planned. Do NOT recreate them.\n\n"
            phase2_message+="Audit sizing rationale:\n${audit_sizing_rationale}\n\n"
            phase2_message+="### Phase 1 Tasks (already planned)\n\n${phase1_summary}\n"
            phase2_message+="**Starting task ID: ${phase2_start_id}**. All your task IDs must be >= ${phase2_start_id}.\n\n"
            phase2_message+="Set \`depends_on\` edges to Phase 1 tasks where your work needs their output.\n\n"
            phase2_message+="Build on the functions, types, fields and error names exactly as the Phase 1 tasks above define them. Where a Phase 1 task differs from the spec, follow the Phase 1 task and record the difference in \`assumptions\`.\n\n"
            phase2_message+="Focus on: API endpoints, higher-level services, frontend components, integration, tests."

            local parsed_phase2
            parsed_phase2=$(_run_architect_phase "Architect (Phase 2)" "$phase2_message" "$arch_agent" "$arch_schema") || exit 1

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

            parsed_architect=$(_run_architect_phase "Architect" "$base_message" "$arch_agent" "$arch_schema") || exit 1
        fi

        if [[ "$arch_mode" == "two-pass" ]]; then
            log_success "Skeleton: $(echo "$parsed_architect" | jq '.tasks | length') tasks"
            _plan_gate_skeleton
            _plan_cache_write "architect-skeleton" "$architect_cache_hash" "$parsed_architect"
            _plan_enrich_skeleton
            echo ""
        fi

        # Cache successful architect output
        _plan_cache_write "architect" "$architect_cache_hash" "$parsed_architect"
    fi

    # ── File Impact ownership (deterministic) ──────────────────────
    # Every file the tech spec's File Impact section names must be owned by a
    # task. Unowned files become coverage gaps and get task(s) added once.
    local _unowned
    _unowned=$(_plan_unowned_file_impact)
    if [[ "$_unowned" != "[]" ]]; then
        log_warn "File Impact lists $(echo "$_unowned" | jq 'length') file(s) no task owns: $(echo "$_unowned" | jq -r 'join(", ")')"
        _cov_gaps=$(echo "$_unowned" | jq -c '[.[] | {severity: "critical", spec: "tech", section: "File Impact",
            requirement: ("File Impact lists " + . + ", but no task has it in files_touched"),
            explanation: "Add it to the task that changes or verifies it, or add a task that owns it."}]')
        _cov_critical=$(echo "$_unowned" | jq 'length')
        if _plan_confirm_repair "Add task(s) for the unowned File Impact file(s)?"; then
            _repair_coverage_gaps
            _plan_cache_write "architect" "$architect_cache_hash" "$parsed_architect"
            _unowned=$(_plan_unowned_file_impact)
            if [[ "$_unowned" != "[]" ]]; then
                log_warn "Still unowned after repair: $(echo "$_unowned" | jq -r 'join(", ")') — speed verify will report it"
            else
                log_success "File Impact: every listed file is owned by a task"
            fi
        fi
    fi

    # ── Coverage verification gate (G1: never silently wrong) ──────
    # Independent agent checks the merged task DAG against full specs, on every
    # new plan, single-pass or phased (S3.4-TR2). Single-pass plans used to skip
    # it, so requirement gaps surfaced only in speed verify.
    if [[ "${SKIP_COVERAGE:-}" != "true" ]]; then
    _run_coverage_check
    if [[ $_cov_critical -gt 0 ]]; then
        log_error "Coverage: ${_cov_critical} critical gap(s)"
        if _plan_confirm_repair "Add missing task(s)?"; then
            _repair_coverage_gaps
            _plan_cache_write "architect" \
                "$architect_cache_hash" "$parsed_architect"
            _run_coverage_check
        fi
        [[ $_cov_critical -gt 0 ]] && \
            log_warn "Proceeding with ${_cov_critical} unresolved gap(s)"
    elif [[ $_cov_minor -gt 0 ]]; then
        log_warn "Coverage passed with ${_cov_minor} minor gap(s)"
    elif [[ -n "$_cov_parsed" ]]; then
        log_success "Coverage: $(echo "$_cov_parsed" | jq -r '.summary // "All requirements covered"')"
    fi
    else
        log_warn "SKIP_COVERAGE=true — coverage verifier skipped"
        _log_gate_skip "coverage" "plan"
    fi  # end coverage gate
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
    # A new plan starts a new run, which records its own base branch.
    rm -f "${FEATURE_DIR}/base_branch"

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

        # Keep structured criteria as an array, so criteria verification gets
        # each criterion's verify_by instead of one manual string
        if echo "$task" | jq -e '.acceptance_criteria | type == "array"' >/dev/null 2>&1; then
            task_update_raw "$id" "acceptance_criteria" "$(echo "$task" | jq -c '.acceptance_criteria')"
        fi

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
    # exposure, and file ownership before proceeding. Two-pass plans were
    # gated as a skeleton already; this run also covers repair-added tasks.
    if [[ "${SKIP_DECOMP:-}" == "true" ]]; then
        log_warn "Decomposition gate skipped (SKIP_DECOMP=true)"
        _log_gate_skip "decomposition" "plan"
    else
        log_step "Running decomposition quality gate..."
        local decomp_rc=0
        _plan_decomposition_gate "${TASKS_DIR}" || decomp_rc=$?
        if [[ $decomp_rc -eq 1 ]]; then
            log_error "Decomposition quality gate FAILED"
            echo -e "The task plan has structural issues that will cause problems during execution."
            echo -e "Fix the plan and re-run ${COLOR_STEP}speed plan${RESET}"
            echo ""
            log_step "Full report: ${LOGS_DIR}/decomposition-gate.json"
            exit 1
        fi
    fi # SKIP_DECOMP
    echo ""

    # A plan with a dependency loop can never run: `speed run` rejects it.
    # Stop here with the loop named, instead of reporting a passed plan.
    # The unusable plan is moved aside, not left installed.
    if ! task_topo_sort > /dev/null; then
        local _rejected
        _rejected="${LOGS_DIR}/rejected-plan-$(date +%s)"
        mkdir -p "$_rejected"
        mv "${TASKS_DIR}"/*.json "$_rejected"/ 2>/dev/null || true
        rm -f "${FEATURE_DIR}/base_branch"
        log_error "The task plan cannot be executed: its dependencies do not resolve (see above)"
        log_error "No plan was installed. The rejected tasks are in ${_rejected}"
        echo -e "Re-run ${COLOR_STEP}speed plan --force${RESET} to plan again"
        exit "$EXIT_GATE_FAILURE"
    fi

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
