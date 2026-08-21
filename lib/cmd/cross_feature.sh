#!/usr/bin/env bash
# cross_feature.sh — Cross-feature validation and coherence
#
# Compares all active (claimed) features against each other:
# - Spec contradiction detection
# - File ownership overlap
# - Cross-feature coherence (branch compatibility)
# - Integration order recommendation
#
# Requires: multiplayer.sh, ownership.sh, features.sh, events.sh

# ── Discover active features ─────────────────────────────────
# Returns feature names that have a current (non-stale) claim.
_cross_feature_active() {
    local events_dir
    events_dir=$(mp_events_dir)
    [[ -d "$events_dir" ]] || return 0

    local features=""
    for f in "${events_dir}"/*_feature-claimed_*.jsonl; do
        [[ -f "$f" ]] || continue
        local feat
        feat=$(jq -r '.feature // empty' "$f" 2>/dev/null)
        [[ -n "$feat" ]] && features+="${feat}"$'\n'
    done

    # Deduplicate, then filter to currently claimed (not released/stale)
    features=$(echo "$features" | sort -u | sed '/^$/d')
    while IFS= read -r feat; do
        [[ -z "$feat" ]] && continue
        local rc=0
        ownership_check "$feat" || rc=$?
        # rc=0 (owned by me) or rc=1 (owned by someone else) = active
        if [[ $rc -le 1 ]]; then
            echo "$feat"
        fi
    done <<< "$features"
}

# ── File ownership overlap ────────────────────────────────────
# For each active feature, reads files_touched from task JSONs.
# Detects when two features plan to modify the same file.
_cross_feature_file_overlap() {
    local features="$1"
    local feat_root="$SHARED_FEATURES_DIR"

    # Build a map: file → [features that touch it]
    local tmpdir
    tmpdir=$(mktemp -d)

    while IFS= read -r feat; do
        [[ -z "$feat" ]] && continue
        local tasks_dir="${feat_root}/${feat}/tasks"
        [[ -d "$tasks_dir" ]] || continue
        for tf in "${tasks_dir}"/*.json; do
            [[ -f "$tf" ]] || continue
            jq -r '.files_touched[]? // empty' "$tf" 2>/dev/null | while IFS= read -r file; do
                [[ -z "$file" ]] && continue
                echo "$feat" >> "${tmpdir}/${file//\//__}"
            done
        done
    done <<< "$features"

    # Find files touched by 2+ features
    local overlaps=0
    local overlap_report=""
    for f in "${tmpdir}"/*; do
        [[ -f "$f" ]] || continue
        local count
        count=$(sort -u "$f" | wc -l | tr -d ' ')
        if [[ $count -gt 1 ]]; then
            local file_path
            file_path=$(basename "$f" | sed 's/__/\//g')
            local owners
            owners=$(sort -u "$f" | tr '\n' ', ' | sed 's/,$//')
            overlap_report+="  ${COLOR_WARN}${SYM_WARN}${RESET} ${file_path} → ${owners}"$'\n'
            ((overlaps++)) || true
        fi
    done

    rm -rf "$tmpdir"

    if [[ $overlaps -gt 0 ]]; then
        echo -e "${BOLD}File Ownership Overlaps (${overlaps}):${RESET}"
        echo "$overlap_report"
    else
        echo -e "${COLOR_SUCCESS}${SYM_CHECK}${RESET} No file ownership overlaps detected"
    fi
    echo ""
    return $overlaps
}

# ── Integration order ─────────────────────────────────────────
# Recommends merge order based on file overlap density.
# Features with fewer cross-feature dependencies go first.
_cross_feature_integration_order() {
    local features="$1"
    local feat_root="$SHARED_FEATURES_DIR"

    # Count cross-feature file overlaps per feature
    local tmpdir
    tmpdir=$(mktemp -d)
    mkdir -p "${tmpdir}/counts"

    # Collect all files per feature
    while IFS= read -r feat; do
        [[ -z "$feat" ]] && continue
        local tasks_dir="${feat_root}/${feat}/tasks"
        [[ -d "$tasks_dir" ]] || continue
        local files=""
        for tf in "${tasks_dir}"/*.json; do
            [[ -f "$tf" ]] || continue
            files+=$(jq -r '.files_touched[]? // empty' "$tf" 2>/dev/null)$'\n'
        done
        echo "$files" | sort -u | sed '/^$/d' > "${tmpdir}/${feat}.files"
        echo "0" > "${tmpdir}/counts/${feat}"
    done <<< "$features"

    # Count overlaps per feature
    while IFS= read -r feat_a; do
        [[ -z "$feat_a" ]] && continue
        while IFS= read -r feat_b; do
            [[ -z "$feat_b" ]] && continue
            [[ "$feat_a" == "$feat_b" ]] && continue
            if [[ -f "${tmpdir}/${feat_a}.files" ]] && [[ -f "${tmpdir}/${feat_b}.files" ]]; then
                local shared
                shared=$(comm -12 "${tmpdir}/${feat_a}.files" "${tmpdir}/${feat_b}.files" | wc -l | tr -d ' ')
                if [[ $shared -gt 0 ]]; then
                    local cur
                    cur=$(cat "${tmpdir}/counts/${feat_a}")
                    echo "$(( cur + shared ))" > "${tmpdir}/counts/${feat_a}"
                fi
            fi
        done <<< "$features"
    done <<< "$features"

    # Sort by overlap count ascending (fewest overlaps first)
    echo -e "${BOLD}Recommended Integration Order:${RESET}"
    local order=1
    while IFS= read -r feat; do
        [[ -z "$feat" ]] && continue
        local overlaps
        overlaps=$(cat "${tmpdir}/counts/${feat}" 2>/dev/null || echo "0")
        local owner
        owner=$(ownership_current_owner "$feat")
        echo -e "  ${order}. ${COLOR_STEP}${feat}${RESET} ${COLOR_DIM}(${overlaps} shared files, owner: ${owner:-unclaimed})${RESET}"
        ((order++)) || true
    done < <(
        while IFS= read -r feat; do
            [[ -z "$feat" ]] && continue
            local c
            c=$(cat "${tmpdir}/counts/${feat}" 2>/dev/null || echo "0")
            echo "${c} ${feat}"
        done <<< "$features" | sort -n | awk '{print $2}'
    )

    rm -rf "$tmpdir"
    echo ""
}

# ── speed validate --all-active ───────────────────────────────
cmd_validate_cross_feature() {
    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Cross-feature validation requires multi-player mode. Run 'speed mp-init' first."
        exit 1
    fi

    log_header "Cross-Feature Validation"

    local active_features
    active_features=$(_cross_feature_active)

    if [[ -z "$active_features" ]]; then
        log_info "No active (claimed) features found."
        return 0
    fi

    local feat_count
    feat_count=$(echo "$active_features" | wc -l | tr -d ' ')
    log_step "Found ${feat_count} active feature(s)"
    echo ""

    # 1. Gather all specs from active features
    local all_specs=""
    local spec_count=0
    while IFS= read -r feat; do
        [[ -z "$feat" ]] && continue
        local spec_path_file="${SHARED_FEATURES_DIR}/${feat}/spec_path"
        if [[ -f "$spec_path_file" ]]; then
            local sp
            sp=$(cat "$spec_path_file")
            if [[ -n "$sp" ]] && [[ -f "$sp" ]]; then
                all_specs+=$'\n\n'"--- FEATURE: ${feat} | SPEC: ${sp} ---"$'\n'"$(cat "$sp")"
                ((spec_count++)) || true
            fi
        fi
    done <<< "$active_features"

    # 2. Cross-validate specs
    if [[ $spec_count -ge 2 ]]; then
        log_step "Cross-validating ${spec_count} specs..."
        echo ""

        local validator_output
        if validator_output=$(provider_run \
            "${AGENTS_DIR}/validator.md" \
            "Cross-validate the following ${spec_count} active feature specifications. Focus on:
1. Contradictory requirements between features
2. Incompatible data model changes (same table, different schemas)
3. Overlapping scope (two features claiming the same behavior)
4. Missing coordination points (feature A assumes something feature B changes)

${all_specs}" \
            "$MODEL_SUPPORT" \
            "$AGENT_TOOLS_READONLY" \
            "Validator" 2>/dev/null); then
            echo "$validator_output"
            echo ""
            echo "$validator_output" > "${STATE_DIR}/local/cross-feature-validation.log"
            log_success "Cross-feature validation saved to .speed/local/cross-feature-validation.log"
        else
            log_warn "Validator agent unavailable, skipping spec cross-validation"
        fi
    else
        log_info "Only ${spec_count} spec(s) found, skipping cross-validation (need 2+)"
    fi

    # 3. File ownership overlap
    echo ""
    local overlap_rc=0
    _cross_feature_file_overlap "$active_features" || overlap_rc=$?

    # 4. Integration order
    _cross_feature_integration_order "$active_features"

    [[ "${MP_ENABLED:-}" == "true" ]] && event_emit "validate.cross_feature" "all" "{\"features\":$feat_count,\"overlaps\":$overlap_rc}" || true
}

# ── speed coherence --cross-feature ───────────────────────────
cmd_coherence_cross_feature() {
    if [[ "${MP_ENABLED:-}" != "true" ]]; then
        log_error "Cross-feature coherence requires multi-player mode. Run 'speed mp-init' first."
        exit 1
    fi

    log_header "Cross-Feature Coherence"

    local active_features
    active_features=$(_cross_feature_active)

    if [[ -z "$active_features" ]]; then
        log_info "No active features to check."
        return 0
    fi

    local feat_count
    feat_count=$(echo "$active_features" | wc -l | tr -d ' ')

    if [[ $feat_count -lt 2 ]]; then
        log_info "Only ${feat_count} active feature. Cross-feature coherence needs 2+."
        return 0
    fi

    log_step "Checking ${feat_count} features for branch compatibility..."
    echo ""

    # Gather diffs from all active features' done tasks
    local all_feature_diffs=""
    while IFS= read -r feat; do
        [[ -z "$feat" ]] && continue
        local tasks_dir="${SHARED_FEATURES_DIR}/${feat}/tasks"
        [[ -d "$tasks_dir" ]] || continue

        local feat_diff=""
        for tf in "${tasks_dir}"/*.json; do
            [[ -f "$tf" ]] || continue
            local status branch tid
            status=$(jq -r '.status // "unknown"' "$tf")
            [[ "$status" != "done" ]] && continue
            branch=$(jq -r '.branch' "$tf")
            tid=$(jq -r '.id' "$tf")
            if git_branch_exists "$branch"; then
                local diff
                diff=$(git_diff_branch "$branch" 2>/dev/null | head -200 || echo "")
                feat_diff+="Task ${tid} (${branch}):"$'\n'"${diff}"$'\n\n'
            fi
        done

        if [[ -n "$feat_diff" ]]; then
            all_feature_diffs+="
=== FEATURE: ${feat} ===
${feat_diff}
"
        fi
    done <<< "$active_features"

    if [[ -z "$all_feature_diffs" ]]; then
        log_info "No completed task branches to compare."
        return 0
    fi

    local coherence_message="## Cross-Feature Coherence Check

${feat_count} active features with completed branches. Check whether independently-developed features will compose correctly when integrated.

Focus on:
1. Interface mismatches (feature A exports X, feature B imports a different X)
2. Conflicting modifications to shared files
3. Incompatible database migrations or schema assumptions
4. Contradictory configuration changes

### Feature Diffs
${all_feature_diffs}

Respond with JSON: {status: 'pass'|'fail', cross_feature_issues: [{features: [a, b], description, severity, files}]}"

    local output
    if output=$(provider_run \
        "${AGENTS_DIR}/coherence-checker.md" \
        "$coherence_message" \
        "$MODEL_SUPPORT" \
        "$AGENT_TOOLS_READONLY" \
        "Coherence Checker" 2>/dev/null); then

        echo "$output"
        echo ""

        local parsed
        parsed=$(parse_agent_json "$output") || parsed="$output"
        echo "$parsed" > "${STATE_DIR}/local/cross-feature-coherence.log"
        log_success "Cross-feature coherence saved to .speed/local/cross-feature-coherence.log"

        local status
        status=$(echo "$parsed" | jq -r '.status // "unknown"' 2>/dev/null)
        if [[ "$status" == "fail" ]]; then
            local issue_count
            issue_count=$(echo "$parsed" | jq '.cross_feature_issues | length' 2>/dev/null || echo "0")
            log_error "Cross-feature coherence FAILED — ${issue_count} issue(s) found"
        elif [[ "$status" == "pass" ]]; then
            log_success "Cross-feature coherence PASSED"
        fi

        [[ "${MP_ENABLED:-}" == "true" ]] && event_emit "coherence.cross_feature" "all" "{\"status\":\"$status\",\"features\":$feat_count}" || true
    else
        log_error "Coherence checker agent unavailable"
        return 1
    fi
}
