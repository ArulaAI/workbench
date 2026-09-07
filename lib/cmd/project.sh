#!/usr/bin/env bash
# project.sh — Project lifecycle commands (init, validate, clean, new)

# Importing the built-in catalog is part of the documented init contract, and
# the catalog ships with the installation rather than with the project. A
# missing one is therefore a broken install, not a project that opted out, and
# skipping the step silently produced a project that reported success while no
# skill was ever imported and no manifest was ever written.
#
# Init checks this before it touches anything, as part of the read-only
# bootstrap plan. Projection conflicts and operational failures stop before
# verification, Git-policy application, and the optional commit phase.
_init_require_skill_catalog() {
    [[ -d "${SPEED_DIR}/skills" ]] && return 0
    log_error "Built-in skill catalog not found: ${SPEED_DIR}/skills"
    log_error "This SPEED installation is incomplete. Reinstall SPEED or run: speed self-update"
    return 3
}

# Apply the Git policy through the versioned managed block in
# `skills.bootstrap`, which rewrites the delimited region and preserves every
# line around it. Testing for a header comment and appending behind it, which
# this replaced, could neither retire a rule nor deliver a new one: a project
# initialized before a rule existed already carried the header, so nothing was
# ever added to it again.
#
# Returns 0 when the file changed, 1 when the block was already current, and 3
# when the policy could not be applied at all.
_init_reconcile_gitignore() {
    local outcome ignore_error
    ignore_error=$(mktemp)
    if ! outcome=$(PYTHONPATH="${SPEED_DIR}/lib" "$(_context_python)" \
        -m skills.bootstrap ignore \
        --project-root "$PROJECT_ROOT" --scope project 2>"$ignore_error"); then
        log_error "Could not apply the Git ignore policy: $(tr '\n' ' ' < "$ignore_error")"
        rm -f "$ignore_error"
        return 3
    fi
    rm -f "$ignore_error"
    [[ "$outcome" == "changed" ]]
}

# A rule outside the managed block can still exclude the manifest, and git
# cannot re-include a path whose parent directory is excluded, so the block's
# `!.speed/skills/manifest.json` is inert under a blanket `.speed/`. That rule
# belongs to the user, so it is reported rather than rewritten: leaving it
# silent ships a project whose teammates clone projections with no recorded
# hashes and see every skill as conflicted.
_init_warn_untracked_manifest() {
    local manifest_rel=".speed/skills/manifest.json"
    local culprit
    (cd "$PROJECT_ROOT" && git rev-parse --git-dir &>/dev/null) || return 0
    (cd "$PROJECT_ROOT" && git check-ignore -q -- "$manifest_rel" 2>/dev/null) || return 0
    culprit=$(cd "$PROJECT_ROOT" && git check-ignore -v -- "$manifest_rel" 2>/dev/null | cut -f1)
    log_warn "${manifest_rel} is excluded by ${culprit:-an ignore rule} and will not be committed"
    log_warn "Teammates cloning this repo will see every projected skill as conflicted"
    log_warn "Narrow that rule (for example to .speed/local/) so the manifest can be tracked"
}

cmd_init() {
    # The dispatcher has loaded skills.sh by call time. Keep project.sh
    # sourceable on its own for lifecycle preflight tests and embedders.
    if declare -F _speed_alias_notice >/dev/null; then
        _speed_alias_notice init
    fi
    local requested_harnesses=()
    local commit_requested=false
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --harness)
                if [[ $# -lt 2 || -z "${2:-}" || "${2}" == -* ]]; then
                    log_error "--harness requires one of: $(workbench_harness_list)"
                    return 3
                fi
                requested_harnesses+=("$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')")
                shift 2
                ;;
            --commit)
                commit_requested=true
                shift
                ;;
            --help|-h)
                echo "Usage: workbench init [--harness <$(workbench_harness_choices)>]... [--commit]"
                return 0
                ;;
            *)
                log_error "Unknown init option: $1"
                return 3
                ;;
        esac
    done

    # Phase 1: preflight and policy resolution are read-only. The bootstrap
    # planner validates the catalog and config, then applies the documented
    # precedence before Git initialization or any scaffold write can run.
    _init_require_skill_catalog || return 3
    local plan_args=(
        plan
        --project-root "$PROJECT_ROOT"
        --skills-dir "${SPEED_DIR}/skills"
        --config "${PROJECT_ROOT}/speed.toml"
    )
    local harness
    for harness in ${requested_harnesses[@]+"${requested_harnesses[@]}"}; do
        plan_args+=(--harness "$harness")
    done
    if [[ -n "${WORKBENCH_HARNESSES:-}" ]]; then
        plan_args+=(--environment "$WORKBENCH_HARNESSES")
    fi
    local init_plan plan_error
    plan_error=$(mktemp)
    if ! init_plan=$(PYTHONPATH="${SPEED_DIR}/lib" "$(_context_python)" \
        -m skills.bootstrap "${plan_args[@]}" 2>"$plan_error"); then
        log_error "Initialization preflight failed: $(tr '\n' ' ' < "$plan_error")"
        rm -f "$plan_error"
        return 3
    fi
    rm -f "$plan_error"

    local selected_harnesses=()
    while IFS= read -r harness; do
        [[ -n "$harness" ]] && selected_harnesses+=("$harness")
    done < <(printf '%s' "$init_plan" | jq -r '.harnesses[]')
    # Fail here rather than downstream. Every use below expands the array, and
    # an empty one is an unbound-variable abort under `set -u` on bash before
    # 4.4 (the floor lib/deps.sh declares) and a silent no-op init on newer
    # shells. Neither says that the plan's harness list could not be read,
    # which is what actually went wrong: no jq, or output of another shape.
    # Checking once keeps the expansions below correct by construction.
    if (( ${#selected_harnesses[@]} == 0 )); then
        log_error "Could not read the skill harness policy from the initialization plan"
        log_error "Check that jq is installed, or pass --harness explicitly (one of: $(workbench_harness_list))"
        return 3
    fi
    local policy_source
    policy_source=$(printf '%s' "$init_plan" | jq -r '.source')
    local persist_required
    persist_required=$(printf '%s' "$init_plan" | jq -r '.persist_required')

    # Serialize the write phases. Preflight runs first so an invalid request
    # still leaves a fresh directory untouched; once policy is valid, the
    # project lock prevents two initializers from applying competing plans.
    speed_acquire_lock "init" || return 3

    log_header "Initializing SPEED"
    log_info "Skill harness policy: ${selected_harnesses[*]} (${policy_source})"

    # Phase 2: apply the general project scaffold. Repeated init does not
    # overwrite runtime state or user-owned files.
    # Inlining this once dropped its second half, leaving fresh projects with
    # an unborn HEAD that `git worktree add` refuses, so the shared helper is
    # the single implementation again.
    if ! git_ensure_repo; then
        return 3
    fi
    log_success "Git repository ready"

    mkdir -p "$FEATURES_DIR" "$LOGS_DIR" src tests
    log_success "Directory structure created"

    if [[ ! -f "${STATE_DIR}/state.json" ]]; then
        echo '{"status":"idle","agents":[],"started_at":null}' | jq '.' > "${STATE_DIR}/state.json"
        log_success "Runtime state initialized"
    else
        log_info "Runtime state already exists, preserving"
    fi

    local created_agent_file=false
    if [[ -n "$AGENT_FILE_PATH" ]] && [[ -f "$AGENT_FILE_PATH" ]]; then
        log_info "${AGENT_FILE} already exists, skipping"
    else
        AGENT_FILE="${AGENT_FILE:-AGENTS.md}"
        AGENT_FILE_PATH="${PROJECT_ROOT}/${AGENT_FILE}"
        local project_name
        project_name=$(basename "$PROJECT_ROOT")
        sed "s/{{PROJECT_NAME}}/${project_name}/g" "${TEMPLATES_DIR}/agents-file.md" > "$AGENT_FILE_PATH"
        created_agent_file=true
        log_success "Created ${AGENT_FILE} — ${COLOR_DIM}customize this file!${RESET}"
    fi

    # Phase 3: persist the resolved harness policy. This is intentionally
    # separate from [agent].provider: provider selects execution, harnesses
    # select skill hosts. Persist also retires the legacy manifest selection.
    local speed_toml="${PROJECT_ROOT}/speed.toml"
    local persist_args=(
        persist
        --project-root "$PROJECT_ROOT"
        --config "$speed_toml"
        --template "${TEMPLATES_DIR}/speed-toml.toml"
    )
    for harness in "${selected_harnesses[@]}"; do
        persist_args+=(--harness "$harness")
    done
    if [[ "$persist_required" == "true" ]]; then
        if ! PYTHONPATH="${SPEED_DIR}/lib" "$(_context_python)" \
            -m skills.bootstrap "${persist_args[@]}"; then
            log_error "Could not persist the skill harness policy"
            return 3
        fi
        log_success "Recorded skill harness policy in speed.toml"
    else
        log_info "Skill harness policy already recorded in speed.toml"
    fi

    local created_vision=false
    local vision_path="${PROJECT_ROOT}/${VISION_FILE}"
    local vision_dir
    vision_dir=$(dirname "$vision_path")
    if [[ ! -f "$vision_path" ]]; then
        mkdir -p "$vision_dir"
        cp "${TEMPLATES_DIR}/overview.md" "$vision_path"
        created_vision=true
        log_success "Created ${VISION_FILE} — ${COLOR_DIM}define your product vision${RESET}"
    else
        log_info "${VISION_FILE} already exists, skipping"
    fi

    # Phase 4: project the catalog into exactly the resolved policy. Passing
    # every harness explicitly prevents later directory detection from changing
    # this initialization run.
    local sync_args=(sync)
    for harness in "${selected_harnesses[@]}"; do
        sync_args+=(--harness "$harness")
    done
    local sync_out sync_err
    local sync_status=0
    sync_err=$(mktemp)
    sync_out=$(WORKBENCH_NS=1 cmd_skills "${sync_args[@]}" --json 2>"$sync_err") || sync_status=$?

    case "$sync_status" in
        0)
            log_success "Skills projected for ${selected_harnesses[*]}"
            ;;
        2)
            log_error "Skill projection preserved local edits; initialization did not converge"
            log_info "Run: ${COLOR_STEP}workbench skills doctor${RESET}"
            rm -f "$sync_err"
            return 2
            ;;
        *)
            log_error "Skill projection failed: $(tr '\n' ' ' < "$sync_err")"
            log_info "Run: ${COLOR_STEP}workbench skills doctor${RESET}"
            rm -f "$sync_err"
            return 3
            ;;
    esac
    rm -f "$sync_err"

    # Phase 5: verify the post-operation state independently from sync's return
    # value. A project is initialized only when every selected projection is
    # current.
    local catalog_version verify_args
    catalog_version=$(_skills_catalog_version) || return 3
    verify_args=(
        verify
        --project-root "$PROJECT_ROOT"
        --skills-dir "${SPEED_DIR}/skills"
        --catalog-version "$catalog_version"
    )
    for harness in "${selected_harnesses[@]}"; do
        verify_args+=(--harness "$harness")
    done
    if ! PYTHONPATH="${SPEED_DIR}/lib" "$(_context_python)" \
        -m skills.bootstrap "${verify_args[@]}" >/dev/null; then
        log_error "Skill installation verification failed"
        log_info "Run: ${COLOR_STEP}workbench skills doctor${RESET}"
        return 3
    fi
    log_success "Skill installation verified"

    # Phase 6: apply the explicit Git policy only after convergence. Durable
    # projections and manifest are trackable; local runtime events are ignored.
    local ignore_status=0
    _init_reconcile_gitignore || ignore_status=$?
    case "$ignore_status" in
        0) log_success "Updated .gitignore" ;;
        1) log_info "Git ignore policy already current" ;;
        *) return 3 ;;
    esac
    _init_warn_untracked_manifest

    # Phase 7: committing is explicit. Stage only files this initializer owns;
    # never `git add -A`, which can capture unrelated work in an existing repo.
    if [[ "$commit_requested" == "true" ]]; then
        local commit_paths=(".gitignore" "speed.toml" ".speed/skills/manifest.json")
        [[ "$created_agent_file" == "true" ]] && commit_paths+=("$AGENT_FILE")
        [[ "$created_vision" == "true" ]] && commit_paths+=("$VISION_FILE")
        local harness_registry projected_root skill
        if ! harness_registry=$(PYTHONPATH="${SPEED_DIR}/lib" "$(_context_python)" \
            -m skills harnesses --json); then
            log_error "Could not read the canonical harness registry"
            return 3
        fi
        while IFS=$'\t' read -r harness skill; do
            projected_root=$(printf '%s' "$harness_registry" | jq -r \
                --arg harness "$harness" '.[] | select(.id == $harness) | .skills_root')
            if [[ -z "$projected_root" || "$projected_root" == "null" ]]; then
                log_error "Sync returned an unknown harness: ${harness}"
                return 3
            fi
            commit_paths+=("${projected_root}/${skill}")
        done < <(printf '%s' "$sync_out" | jq -r '.[] | select(.skill != "*") | [.harness, .skill] | @tsv')
        # `git add` refuses the entire invocation on an ignored pathspec, or on
        # a path that is neither in the worktree nor the index, and it stages
        # the acceptable paths before refusing. So one gitignored harness root
        # used to leave a fully staged index, no commit, and exit 3 after every
        # other phase had succeeded.
        #
        # Ignored projections are dropped rather than forced in: the rule is the
        # user's, and a clone carrying the manifest without its projections
        # classifies them `absent`, which the next sync re-projects without
        # --force. The reverse, projections with no manifest, is the damaging
        # one, and the manifest is warned about separately above.
        local -a stageable=()
        local -a ignored=()
        local path
        for path in "${commit_paths[@]}"; do
            if (cd "$PROJECT_ROOT" && git check-ignore -q -- "$path" 2>/dev/null); then
                ignored+=("$path")
                continue
            fi
            # A removed skill leaves a path that never entered the index. Its
            # deletion is already recorded in the manifest, so there is nothing
            # for git to stage and nothing to report.
            if [[ ! -e "${PROJECT_ROOT}/${path}" ]] \
                && ! (cd "$PROJECT_ROOT" && git ls-files --error-unmatch -- "$path" &>/dev/null); then
                continue
            fi
            stageable+=("$path")
        done
        if (( ${#ignored[@]} > 0 )); then
            log_warn "Not committing ${#ignored[@]} ignored path(s): ${ignored[*]}"
            log_warn "Teammates can restore them with: workbench skills sync"
        fi
        if (( ${#stageable[@]} > 0 )) \
            && ! (cd "$PROJECT_ROOT" && git add -A -- "${stageable[@]}"); then
            log_error "Could not stage the Workbench initialization files"
            return 3
        fi
        if (cd "$PROJECT_ROOT" && git diff --cached --quiet); then
            log_info "No Workbench initialization changes to commit"
        elif ! (cd "$PROJECT_ROOT" && git commit -m "workbench init: project scaffold"); then
            log_error "Could not commit the Workbench initialization files"
            return 3
        else
            log_success "Committed Workbench initialization files"
        fi
    else
        log_info "Initialization files were not committed; use --commit to create a commit"
    fi

    echo ""
    log_success "SPEED initialized! Next steps:"
    echo -e "  1. Edit ${COLOR_STEP}${AGENT_FILE}${RESET} with your project conventions"
    echo -e "  2. Edit ${COLOR_STEP}speed.toml${RESET} to configure your provider and settings"
    echo -e "  3. Edit ${COLOR_STEP}${VISION_FILE}${RESET} with your product vision"
    echo -e "  4. Create a product spec: ${COLOR_STEP}speed new prd my-feature${RESET}"
    echo -e "  5. Plan your tasks: ${COLOR_STEP}speed plan specs/tech/my-feature.md${RESET}"
    echo ""
    speed_release_lock
}

cmd_validate() {
    # Handle --all-active flag for cross-feature validation
    if [[ "${1:-}" == "--all-active" ]]; then
        cmd_validate_cross_feature
        return $?
    fi

    local specs_dir="${1:-}"

    if [[ -z "$specs_dir" ]]; then
        log_error "Usage: speed validate <specs-dir> | --all-active"
        exit 1
    fi

    if [[ ! -d "$specs_dir" ]]; then
        if [[ -d "${PROJECT_ROOT}/${specs_dir}" ]]; then
            specs_dir="${PROJECT_ROOT}/${specs_dir}"
        else
            log_error "Specs directory not found: $specs_dir"
            exit 1
        fi
    fi

    log_header "Validating Specs"

    # Gather all spec files
    local spec_files=""
    local file_count=0
    while IFS= read -r -d '' f; do
        local relpath="${f#${PROJECT_ROOT}/}"
        spec_files+=$'\n\n'"--- FILE: ${relpath} ---"$'\n'"$(cat "$f")"
        ((file_count++)) || true
    done < <(find "$specs_dir" -name '*.md' -type f -print0 | sort -z)

    if [[ $file_count -eq 0 ]]; then
        log_error "No .md files found in $specs_dir"
        exit 1
    fi

    log_step "Found ${file_count} spec files"
    log_step "Sending to Validator agent..."
    echo ""

    local validator_output
    if ! validator_output=$(provider_run \
        "${AGENTS_DIR}/validator.md" \
        "Cross-validate the following ${file_count} specification files for consistency, completeness, and missing relationships:${spec_files}" \
        "$MODEL_SUPPORT" \
        "$AGENT_TOOLS_READONLY" \
        "Validator"); then
        log_error "Validator agent failed — check agent CLI connection and authentication"
        exit 1
    fi

    if [[ -z "$validator_output" ]]; then
        log_error "Validator agent returned empty output — check agent CLI connection and authentication"
        exit 1
    fi

    echo "$validator_output"
    echo ""

    # Save validation report
    echo "$validator_output" > "${LOGS_DIR}/validation.log"
    log_success "Validation report saved to ${LOGS_DIR}/validation.log"

    # Check status
    if ! _require_json "Validator" "$validator_output"; then
        log_error "Review raw output: ${LOGS_DIR}/validation.log"
        exit 1
    fi

    local status
    status=$(echo "$validator_output" | jq -r '.status // "unknown"')

    if [[ "$status" == "fail" ]]; then
        echo ""
        log_error "Validation FAILED — fix critical gaps before running 'speed plan'"
        local gap_count
        gap_count=$(echo "$validator_output" | jq '.critical_gaps | length')
        log_error "${gap_count} critical gap(s) found"
        exit 1
    elif [[ "$status" == "pass" ]]; then
        echo ""
        log_success "Validation PASSED — specs are consistent"
    else
        log_warn "Could not parse validation status. Review the report manually."
    fi

    echo ""
}

cmd_clean() {
    local what="${1:-logs}"

    case "$what" in
        logs)
            # If a feature is specified or active, clean that feature's logs
            if feature_resolve "$GLOBAL_FEATURE" &>/dev/null; then
                _require_feature "$GLOBAL_FEATURE"
                local file_count size_before
                file_count=$(ls -1 "$LOGS_DIR" 2>/dev/null | wc -l | tr -d ' ')
                size_before=$(du -sh "$LOGS_DIR" 2>/dev/null | cut -f1)
                rm -rf "$LOGS_DIR"
                mkdir -p "$LOGS_DIR"
                log_success "Cleaned ${file_count} log files (${size_before}) for feature ${FEATURE_NAME}"
            else
                # Clean logs across all features
                local total_cleaned=0
                for feat_dir in "${FEATURES_DIR}"/*/logs; do
                    [[ -d "$feat_dir" ]] || continue
                    local fc
                    fc=$(ls -1 "$feat_dir" 2>/dev/null | wc -l | tr -d ' ')
                    total_cleaned=$((total_cleaned + fc))
                    rm -rf "$feat_dir"
                    mkdir -p "$feat_dir"
                done
                # Also clean top-level logs
                if [[ -d "${STATE_DIR}/logs" ]]; then
                    local fc
                    fc=$(ls -1 "${STATE_DIR}/logs" 2>/dev/null | wc -l | tr -d ' ')
                    total_cleaned=$((total_cleaned + fc))
                    rm -rf "${STATE_DIR}/logs"
                    mkdir -p "${STATE_DIR}/logs"
                fi
                log_success "Cleaned ${total_cleaned} log files across all features"
            fi
            ;;

        feature)
            local feat_name="${2:-}"
            if [[ -z "$feat_name" ]]; then
                log_error "Usage: speed clean feature <name>"
                echo ""
                echo "Available features:"
                feature_list | while IFS= read -r f; do echo "  - $f"; done
                exit 1
            fi
            local feat_dir="${FEATURES_DIR}/${feat_name}"
            if [[ ! -d "$feat_dir" ]]; then
                log_error "Feature '${feat_name}' not found"
                exit 1
            fi
            # Clean worktrees for this feature
            local wt_dir="${STATE_DIR}/worktrees/${feat_name}"
            if [[ -d "$wt_dir" ]]; then
                for wt in "$wt_dir"/task-*; do
                    [[ -d "$wt" ]] || continue
                    git -C "$PROJECT_ROOT" worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
                done
                git -C "$PROJECT_ROOT" worktree prune 2>/dev/null || true
            fi
            local size_before
            size_before=$(du -sh "$feat_dir" 2>/dev/null | cut -f1)
            rm -rf "$feat_dir" "$wt_dir"
            # Clear active feature if it was the one we deleted
            if [[ "$(feature_get_active)" == "$feat_name" ]]; then
                rm -f "${STATE_DIR}/active_feature"
            fi
            log_success "Cleaned feature '${feat_name}' (${size_before})"
            ;;

        all)
            if [[ ! -d "$STATE_DIR" ]]; then
                log_info "No .speed directory — nothing to clean"
                return 0
            fi

            # Clean all worktrees (iterate all feature worktree dirs)
            if [[ -d "${STATE_DIR}/worktrees" ]]; then
                for wt_dir in "${STATE_DIR}"/worktrees/*/task-* "${STATE_DIR}"/worktrees/task-*; do
                    [[ -d "$wt_dir" ]] || continue
                    git -C "$PROJECT_ROOT" worktree remove --force "$wt_dir" 2>/dev/null || rm -rf "$wt_dir"
                done
                git -C "$PROJECT_ROOT" worktree prune 2>/dev/null || true
            fi

            local size_before
            size_before=$(du -sh "$STATE_DIR" 2>/dev/null | cut -f1)

            rm -rf "$STATE_DIR"
            log_success "Cleaned entire .speed/ directory (${size_before})"
            ;;

        *)
            echo -e "Usage: ${COLOR_STEP}speed clean${RESET} [logs|feature <name>|all]"
            echo ""
            echo -e "  ${COLOR_STEP}logs${RESET}               Remove log files (active feature or all)"
            echo -e "  ${COLOR_STEP}feature <name>${RESET}      Remove a specific feature's state and worktrees"
            echo -e "  ${COLOR_STEP}all${RESET}                Remove entire .speed/ directory"
            ;;
    esac
}

cmd_new() {
    local subcommand="${1:-}"
    local name="${2:-}"

    log_header "Creating new ${subcommand:-spec} spec"

    # Validate subcommand
    case "$subcommand" in
        prd|rfc|design|defect) ;;
        *)
            log_error "Invalid subcommand: '${subcommand}'"
            echo "" >&2
            echo -e "  Valid types: ${COLOR_STEP}prd${RESET}  ${COLOR_STEP}rfc${RESET}  ${COLOR_STEP}design${RESET}  ${COLOR_STEP}defect${RESET}" >&2
            echo "" >&2
            exit "$EXIT_CONFIG_ERROR"
            ;;
    esac

    # Validate name (required)
    if [[ -z "$name" ]]; then
        log_error "Usage: speed new <type> <name>"
        echo "" >&2
        echo -e "  Example: ${COLOR_STEP}speed new ${subcommand} my-feature${RESET}" >&2
        echo "" >&2
        exit "$EXIT_CONFIG_ERROR"
    fi

    # Validate name format: lowercase alphanumeric + hyphens, no leading/trailing hyphens
    if ! echo "$name" | grep -qE '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'; then
        log_error "Invalid name: '${name}'"
        echo "" >&2
        echo -e "  Name must be lowercase alphanumeric with hyphens (no leading/trailing hyphens)" >&2
        echo -e "  Example: ${COLOR_STEP}my-feature${RESET}, ${COLOR_STEP}fix-login-bug${RESET}, ${COLOR_STEP}auth${RESET}" >&2
        echo "" >&2
        exit "$EXIT_CONFIG_ERROR"
    fi

    # Map subcommand to template and output directory
    local template output_dir
    case "$subcommand" in
        prd)    template="${TEMPLATES_DIR}/prd.md";    output_dir="specs/product" ;;
        rfc)    template="${TEMPLATES_DIR}/rfc.md";    output_dir="specs/tech" ;;
        design) template="${TEMPLATES_DIR}/design.md"; output_dir="specs/design" ;;
        defect) template="${TEMPLATES_DIR}/defect.md"; output_dir="specs/defects" ;;
    esac

    # Check template exists
    if [[ ! -f "$template" ]]; then
        log_error "Template not found: ${template}"
        echo "" >&2
        echo -e "  This may indicate an incomplete SPEED installation." >&2
        echo -e "  Expected template at: ${COLOR_STEP}${template}${RESET}" >&2
        echo "" >&2
        exit "$EXIT_CONFIG_ERROR"
    fi

    local output="${PROJECT_ROOT}/${output_dir}/${name}.md"

    # Check output file does not already exist
    if [[ -f "$output" ]]; then
        log_error "File already exists: ${output}"
        echo "" >&2
        echo -e "  To avoid overwriting, the existing file was left unchanged." >&2
        echo "" >&2
        exit "$EXIT_CONFIG_ERROR"
    fi

    # Create output directory
    mkdir -p "${PROJECT_ROOT}/${output_dir}"

    # Humanize name: hyphens → spaces, title case
    local humanized
    humanized=$(echo "$name" | tr '-' ' ' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)} 1')

    # Copy template with placeholder substitution
    sed -e "s/{Feature Name}/${humanized}/g" \
        -e "s/{name}/${name}/g" \
        -e "s|{product-spec}|specs/product/${name}.md|g" \
        "$template" > "$output"

    log_success "Created ${output_dir}/${name}.md"

    # Open in editor if set
    if [[ -n "${EDITOR:-}" ]]; then
        exec "$EDITOR" "$output"
    fi
}
