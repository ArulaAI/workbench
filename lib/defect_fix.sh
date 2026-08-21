#!/usr/bin/env bash
# defect_fix.sh — Orchestration logic for defect reproduce and fix stages
#
# Provides branch creation, reproduce/fix workflows, quality gates, and
# grounding checks for the defect pipeline. Sources lib/defects.sh for
# state management.
#
# Requires config.sh, log.sh, git.sh, provider.sh, gates.sh, grounding.sh,
# and defects.sh to be sourced first.

# ── Shared helpers ───────────────────────────────────────────────

# Check whether a file is exempt from scope enforcement.
# Exempt: test files, pipeline-internal files, package manifests.
# Uses _is_test_file from grounding.sh (speed.toml patterns + go-enry).
# Args: file_path
# Returns: 0 if exempt, 1 if subject to scope check
_defect_file_is_exempt() {
    local file="$1"

    if _is_test_file "$file"; then
        return 0
    fi

    if [[ "$file" == .speed/* ]] || [[ "$file" == *specs/defects/* ]]; then
        return 0
    fi

    case "$file" in
        */package.json|*/package-lock.json|package.json|package-lock.json|\
        */yarn.lock|yarn.lock|*/pnpm-lock.yaml|pnpm-lock.yaml|\
        */requirements.txt|requirements.txt|*/Gemfile.lock|*/go.sum)
            return 0
            ;;
    esac

    return 1
}

# ── Scope enforcement ────────────────────────────────────────────
# Mechanically revert out-of-scope changes the agent made (committed
# or uncommitted). Runs BEFORE quality gates so tests evaluate only
# the in-scope fix. If the fix depends on out-of-scope changes,
# quality gates will fail, surfacing that affected_files is too narrow.
# Args: name

_defect_revert_out_of_scope() {
    local name="$1"
    local defect_dir
    defect_dir=$(get_defect_dir "$name")
    local branch="speed/defect-${name}"

    if [[ ! -f "${defect_dir}/triage.json" ]]; then
        return 0
    fi

    _defect_ensure_json

    local affected_files
    affected_files=$(jq -r '.affected_files[]?' "${defect_dir}/triage.json" 2>/dev/null)

    if [[ -z "$affected_files" ]]; then
        return 0
    fi

    local main_branch
    main_branch=$(git_main_branch)

    # Collect ALL changed files: committed + uncommitted + staged + untracked
    local committed_files uncommitted_files staged_files untracked_files
    committed_files=$(_git diff "${main_branch}...${branch}" --name-only 2>/dev/null)
    uncommitted_files=$(_git diff --name-only 2>/dev/null)
    staged_files=$(_git diff --cached --name-only 2>/dev/null)
    untracked_files=$(_git ls-files --others --exclude-standard 2>/dev/null)

    local all_changed
    all_changed=$(printf '%s\n' "$committed_files" "$uncommitted_files" "$staged_files" "$untracked_files" \
        | sort -u | grep -v '^$' || true)

    if [[ -z "$all_changed" ]]; then
        return 0
    fi

    local reverted=""
    local has_reverts=false

    while IFS= read -r file; do
        [[ -z "$file" ]] && continue

        if _defect_file_is_exempt "$file"; then
            continue
        fi

        local in_scope=false
        while IFS= read -r af; do
            [[ -z "$af" ]] && continue
            if [[ "$file" == "$af" ]]; then
                in_scope=true
                break
            fi
        done <<< "$affected_files"

        if $in_scope; then
            continue
        fi

        # Out of scope — revert
        if _git cat-file -e "${main_branch}:${file}" 2>/dev/null; then
            _git checkout "$main_branch" -- "$file" 2>/dev/null || {
                log_warn "Failed to revert out-of-scope file: ${file}"
                continue
            }
        elif [[ -f "${PROJECT_ROOT}/${file}" ]]; then
            _git rm -f "$file" >/dev/null 2>&1 || rm -f "${PROJECT_ROOT}/${file}"
        fi

        [[ -n "$reverted" ]] && reverted+=", "
        reverted+="$file"
        has_reverts=true
    done <<< "$all_changed"

    if $has_reverts; then
        log_step "Reverted out-of-scope files: ${reverted}"
        _git add -A >/dev/null 2>&1
        if ! _git diff --cached --quiet 2>/dev/null; then
            _git commit -m "speed: revert out-of-scope changes [${reverted}]" >/dev/null 2>&1
        fi
    fi

    return 0
}

# ── create_defect_branch ─────────────────────────────────────────
# Create git branch speed/defect-<name> from current HEAD.
# Exits with error if branch already exists.
# Updates state.json branch field via set_defect_branch.
# Args: name

create_defect_branch() {
    local name="$1"
    local branch="speed/defect-${name}"

    if git_branch_exists "$branch"; then
        _git checkout "$branch" >/dev/null 2>&1
        log_step "Checked out existing defect branch: ${branch}"
    else
        _git checkout -b "$branch" >/dev/null 2>&1
        log_step "Created defect branch: ${branch}"
    fi

    set_defect_branch "$name" "$branch"
}

# ── reproduce_defect ─────────────────────────────────────────────
# Moderate defects only. Creates branch, runs Developer Agent to write
# a failing test, commits the result.
# Args: name

reproduce_defect() {
    local name="$1"
    local defect_dir
    defect_dir=$(get_defect_dir "$name")

    # 1. Create branch
    create_defect_branch "$name" || return 1

    # 2. Transition to reproducing
    transition_defect_state "$name" "reproducing" || return 1

    # 3. Read triage.json
    local triage_json
    triage_json=$(read_triage_output "$name") || return 1

    _defect_ensure_json

    local defect_type affected_files test_coverage_detail
    defect_type=$(_defect_json_get "${defect_dir}/triage.json" "defect_type")
    affected_files=$(jq -r '.affected_files // [] | join(", ")' "${defect_dir}/triage.json" 2>/dev/null)
    test_coverage_detail=$(_defect_json_get "${defect_dir}/triage.json" "test_coverage_detail")

    # 4. Build Developer Agent prompt
    local report_content=""
    if [[ -f "${defect_dir}/report.md" ]]; then
        report_content=$(cat "${defect_dir}/report.md")
    fi

    # Load related specs
    local related_specs=""
    if [[ -f "${defect_dir}/report.md" ]]; then
        local spec_paths
        spec_paths=$(defect_resolve_specs "${defect_dir}/report.md")
        while IFS= read -r spec_path; do
            [[ -z "$spec_path" ]] && continue
            [[ -f "$spec_path" ]] || continue
            related_specs+="
--- $(basename "$spec_path") ---
$(cat "$spec_path")
"
        done <<< "$spec_paths"
    fi

    local agent_message="## Defect: Reproduce

### Defect Report
${report_content}

### Triage Output
\`\`\`json
${triage_json}
\`\`\`

### Defect Type: ${defect_type}
### Affected Files: ${affected_files}
### Test Coverage Detail
${test_coverage_detail}

### Test Strategy
Write a failing test for this **${defect_type}** defect. Follow the test strategy instructions from the reproduce mode section of the developer agent prompt.
"

    if [[ -n "$related_specs" ]]; then
        agent_message+="
### Related Specs
${related_specs}
"
    fi

    agent_message+="
### Working Directory
$(pwd)

### Git Branch
You are working on branch: \`speed/defect-${name}\`
"

    # Inject operator context from retries
    local context_file="${defect_dir}/context.md"
    if [[ -f "$context_file" ]]; then
        agent_message+="
### Additional Context (from operator)
$(cat "$context_file")
"
    fi

    # 5. Run Developer Agent
    log_step "Running Developer Agent to reproduce defect '${name}'..."
    local output_file="${defect_dir}/logs/reproduce.log"
    mkdir -p "${defect_dir}/logs"

    local agent_output
    agent_output=$(provider_run \
        "${AGENTS_DIR}/developer.md" \
        "$agent_message" \
        "$MODEL_SUPPORT" \
        "$AGENT_TOOLS_FULL" \
        "reproduce-${name}")

    echo "$agent_output" > "$output_file"

    # 6. Run quality gates: lint + typecheck only (skip tests)
    local gate_failed=false
    local gate_type gate_label
    for gate_type in lint typecheck; do
        case "$gate_type" in
            lint)      gate_label="Lint" ;;
            typecheck) gate_label="Type check" ;;
        esac

        local cmds
        cmds=$(gates_get_config "$gate_type" "both")
        if [[ -n "$cmds" ]]; then
            while IFS= read -r cmd; do
                [[ -z "$cmd" ]] && continue
                if ! gate_run_command "${gate_label}" "$cmd"; then
                    gate_failed=true
                fi
            done <<< "$cmds"
        fi
    done

    # 7. On gate failure, exit (state stays at reproducing)
    if $gate_failed; then
        log_error "Quality gates failed during reproduce stage for '${name}'"
        return "$EXIT_GATE_FAILURE"
    fi

    # 8. Commit the failing test
    _git add -A >/dev/null 2>&1
    if ! _git diff --cached --quiet 2>/dev/null; then
        _git commit -m "test: reproduce ${name} defect" >/dev/null 2>&1
        log_success "Committed failing test for defect '${name}'"
    else
        log_warn "No changes to commit after reproduce stage for '${name}'"
    fi

    # 9. Transition to reproduced
    transition_defect_state "$name" "reproduced" || return 1

    log_success "Defect '${name}' reproduced successfully"
}

# ── fix_defect ───────────────────────────────────────────────────
# Fix a defect. For trivial: creates branch first. For moderate:
# continues on existing branch with failing test already committed.
# Args: name

fix_defect() {
    local name="$1"
    local defect_dir
    defect_dir=$(get_defect_dir "$name")

    _defect_ensure_json

    # Read complexity from state
    local state_file="${defect_dir}/state.json"
    local complexity
    complexity=$(_defect_json_get "$state_file" "complexity")

    # 1. For trivial: create branch (no reproduce stage preceded it)
    #    For moderate: continue on existing branch
    if [[ "$complexity" == "trivial" ]]; then
        create_defect_branch "$name" || return 1
    fi

    # 2. Transition to fixing
    transition_defect_state "$name" "fixing" || return 1

    # 3. Read triage.json
    local triage_json
    triage_json=$(read_triage_output "$name") || return 1

    local root_cause affected_files suggested_approach
    root_cause=$(_defect_json_get "${defect_dir}/triage.json" "root_cause_hypothesis")
    affected_files=$(jq -r '.affected_files // [] | join(", ")' "${defect_dir}/triage.json" 2>/dev/null)
    suggested_approach=$(_defect_json_get "${defect_dir}/triage.json" "suggested_approach")

    # 4. Build Developer Agent prompt
    local report_content=""
    if [[ -f "${defect_dir}/report.md" ]]; then
        report_content=$(cat "${defect_dir}/report.md")
    fi

    local agent_message="## Defect: Fix

### Defect Report
${report_content}

### Triage Output
\`\`\`json
${triage_json}
\`\`\`

### Root Cause
${root_cause}

### Affected Files: ${affected_files}
### Suggested Approach
${suggested_approach}
"

    if [[ "$complexity" == "moderate" ]]; then
        agent_message+="
### Important
The failing test on this branch defines \"done\". Make it pass. Do not change the test.
"
    fi

    agent_message+="
### Working Directory
$(pwd)

### Git Branch
You are working on branch: \`speed/defect-${name}\`
"

    # Inject operator context from retries
    local context_file="${defect_dir}/context.md"
    if [[ -f "$context_file" ]]; then
        agent_message+="
### Additional Context (from operator)
$(cat "$context_file")
"
    fi

    # 5. Run Developer Agent
    log_step "Running Developer Agent to fix defect '${name}'..."
    local output_file="${defect_dir}/logs/fix.log"
    mkdir -p "${defect_dir}/logs"

    local agent_output
    agent_output=$(provider_run \
        "${AGENTS_DIR}/developer.md" \
        "$agent_message" \
        "$MODEL_SUPPORT" \
        "$AGENT_TOOLS_FULL" \
        "fix-${name}")

    echo "$agent_output" > "$output_file"

    # 6. Revert out-of-scope changes (mechanical enforcement)
    if [[ "${SKIP_GATES:-}" != "true" ]]; then
        _defect_revert_out_of_scope "$name"
    fi

    # 7. Run quality gates (on the cleaned working tree)
    if [[ "${SKIP_GATES:-}" == "true" ]]; then
        log_warn "Quality gates skipped (SKIP_GATES=true)"
        _log_gate_skip "defect_quality" "fix"
    elif ! run_defect_quality_gates "$name"; then
        log_error "Quality gates failed during fix stage for '${name}'"
        return "$EXIT_GATE_FAILURE"
    fi

    # 8. Commit in-scope changes
    _git add -A >/dev/null 2>&1
    if ! _git diff --cached --quiet 2>/dev/null; then
        _git commit -m "fix: resolve ${name} defect" >/dev/null 2>&1
        log_success "Committed fix for defect '${name}'"
    fi

    # 9. Check grounding gates (safety net on committed state)
    if [[ "${SKIP_GATES:-}" == "true" ]]; then
        log_warn "Grounding gates skipped (SKIP_GATES=true)"
        _log_gate_skip "defect_grounding" "fix"
    elif ! check_grounding_gates "$name"; then
        log_error "Grounding gates failed during fix stage for '${name}'"
        return "$EXIT_GATE_FAILURE"
    fi

    # 10. Transition to fixed
    transition_defect_state "$name" "fixed" || return 1

    log_success "Defect '${name}' fixed successfully"
}

# ── run_defect_quality_gates ─────────────────────────────────────
# Run quality gates scoped to a defect: lint, typecheck, and test
# for the affected subsystem. If a related feature is identified,
# also runs that feature's test suite.
# Args: name
# Returns: 0 on pass, 1 on failure

run_defect_quality_gates() {
    local name="$1"
    local defect_dir
    defect_dir=$(get_defect_dir "$name")

    _defect_ensure_json

    # Determine subsystem from affected_files paths
    local subsystem="both"
    if [[ -f "${defect_dir}/triage.json" ]]; then
        local affected_files_json
        affected_files_json=$(jq -r '.affected_files[]?' "${defect_dir}/triage.json" 2>/dev/null)

        if [[ -n "$affected_files_json" ]]; then
            local has_frontend=false has_backend=false
            while IFS= read -r f; do
                [[ -z "$f" ]] && continue
                if [[ -n "${TOML_SUBSYSTEMS:-}" ]]; then
                    # Config-driven detection: match against TOML_SUBSYSTEMS
                    local entry
                    for entry in $TOML_SUBSYSTEMS; do
                        local sub_name="${entry%%:*}"
                        local globs="${entry##*:}"
                        IFS=',' read -ra glob_array <<< "$globs"
                        for glob in "${glob_array[@]}"; do
                            local prefix="${glob%%/\*\*}"
                            prefix="${prefix%%\*}"
                            if [[ "$f" == ${prefix}* ]]; then
                                case "$sub_name" in
                                    frontend) has_frontend=true ;;
                                    backend)  has_backend=true ;;
                                esac
                                break 2
                            fi
                        done
                    done
                else
                    # Hardcoded detection
                    if [[ "$f" == src/frontend/* ]]; then
                        has_frontend=true
                    elif [[ "$f" == src/backend/* ]]; then
                        has_backend=true
                    fi
                fi
            done <<< "$affected_files_json"

            if $has_frontend && $has_backend; then
                subsystem="both"
            elif $has_frontend; then
                subsystem="frontend"
            elif $has_backend; then
                subsystem="backend"
            fi
        fi
    fi

    log_step "Running defect quality gates for '${name}' (subsystem: ${subsystem})..."

    local all_passed=true
    local gate_type gate_label
    for gate_type in lint typecheck test; do
        case "$gate_type" in
            lint)      gate_label="Lint" ;;
            typecheck) gate_label="Type check" ;;
            test)      gate_label="Tests" ;;
        esac

        local cmds
        cmds=$(gates_get_config "$gate_type" "$subsystem")
        if [[ -n "$cmds" ]]; then
            while IFS= read -r cmd; do
                [[ -z "$cmd" ]] && continue
                if ! gate_run_command "${gate_label}" "$cmd"; then
                    all_passed=false
                fi
            done <<< "$cmds"
        fi
    done

    # If related_spec identifies a feature, also run that feature's test suite
    if [[ -f "${defect_dir}/report.md" ]]; then
        local related_feature
        related_feature=$(grep -i '^Related Feature:' "${defect_dir}/report.md" 2>/dev/null | head -1 | sed 's/^[Rr]elated[[:space:]]*[Ff]eature:[[:space:]]*//' | tr -d '[:space:]')
        if [[ -n "$related_feature" ]]; then
            local feature_test_cmds
            feature_test_cmds=$(gates_get_config "test" "both")
            if [[ -n "$feature_test_cmds" ]]; then
                log_step "Running feature '${related_feature}' test suite..."
                while IFS= read -r cmd; do
                    [[ -z "$cmd" ]] && continue
                    if ! gate_run_command "Feature Tests" "$cmd"; then
                        all_passed=false
                    fi
                done <<< "$feature_test_cmds"
            fi
        fi
    fi

    if $all_passed; then
        log_success "Defect quality gates passed for '${name}'"
        return 0
    else
        log_error "Defect quality gates failed for '${name}'"
        return 1
    fi
}

# ── check_grounding_gates ────────────────────────────────────────
# Verify the fix diff is properly scoped:
# - Non-empty diff check
# - Scope check: files in diff vs affected_files from triage.json
# Args: name
# Returns: 0 on pass, 1 on violation

check_grounding_gates() {
    local name="$1"
    local defect_dir
    defect_dir=$(get_defect_dir "$name")
    local branch="speed/defect-${name}"

    # Collect all changed files: committed + uncommitted + staged + untracked
    local main_branch
    main_branch=$(git_main_branch)

    local committed_files uncommitted_files staged_files untracked_files
    committed_files=$(_git diff "${main_branch}...${branch}" --name-only 2>/dev/null)
    uncommitted_files=$(_git diff --name-only 2>/dev/null)
    staged_files=$(_git diff --cached --name-only 2>/dev/null)
    untracked_files=$(_git ls-files --others --exclude-standard 2>/dev/null)

    local diff_files
    diff_files=$(printf '%s\n' "$committed_files" "$uncommitted_files" "$staged_files" "$untracked_files" \
        | sort -u | grep -v '^$' || true)

    if [[ -z "$diff_files" ]]; then
        log_error "No changes produced"
        return 1
    fi

    # Scope check: compare files in diff against affected_files from triage
    if [[ ! -f "${defect_dir}/triage.json" ]]; then
        log_warn "No triage.json found for scope check"
        return 0
    fi

    _defect_ensure_json

    local affected_files
    affected_files=$(jq -r '.affected_files[]?' "${defect_dir}/triage.json" 2>/dev/null)

    if [[ -z "$affected_files" ]]; then
        # No affected files declared in triage, skip scope check
        return 0
    fi

    local out_of_scope=""
    while IFS= read -r changed_file; do
        [[ -z "$changed_file" ]] && continue

        if _defect_file_is_exempt "$changed_file"; then
            continue
        fi

        local in_scope=false
        while IFS= read -r af; do
            [[ -z "$af" ]] && continue
            if [[ "$changed_file" == "$af" ]]; then
                in_scope=true
                break
            fi
        done <<< "$affected_files"

        if ! $in_scope; then
            if [[ -n "$out_of_scope" ]]; then
                out_of_scope+=", "
            fi
            out_of_scope+="$changed_file"
        fi
    done <<< "$diff_files"

    if [[ -n "$out_of_scope" ]]; then
        log_error "Files modified outside affected scope: ${out_of_scope}"
        return 1
    fi

    log_success "Grounding gates passed for defect '${name}'"
    return 0
}
