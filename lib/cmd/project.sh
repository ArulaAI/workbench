#!/usr/bin/env bash
# project.sh — Project lifecycle commands (init, validate, clean, new)

cmd_init() {
    local harness=""
    local skill_surface=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --harness)
                if [[ $# -lt 2 || -z "${2:-}" ]]; then
                    log_error "--harness requires one of: claude, codex, copilot"
                    return 3
                fi
                harness=$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')
                shift 2
                ;;
            --help|-h)
                echo "Usage: workbench init [--harness <claude|codex|copilot>]"
                return 0
                ;;
            *)
                log_error "Unknown init option: $1"
                return 3
                ;;
        esac
    done

    case "$harness" in
        "") ;;
        claude|codex|copilot) skill_surface="$harness" ;;
        *)
            log_error "Unknown harness '${harness}' (expected: claude, codex, copilot)"
            return 3
            ;;
    esac

    log_header "Initializing SPEED"

    # 1. Git repo
    git_ensure_repo
    log_success "Git repository ready"

    # 2. Directory structure
    mkdir -p "$FEATURES_DIR" "$LOGS_DIR" src tests
    log_success "Directory structure created"

    # 3. .gitignore
    if ! grep -q '.speed/features/' "$PROJECT_ROOT/.gitignore" 2>/dev/null; then
        cat >> "$PROJECT_ROOT/.gitignore" << 'EOF'

# SPEED runtime state
.speed/logs/
.speed/features/*/logs/
.speed/features/*/state.json
.speed/features/*/failure_history.jsonl
.speed/active_feature
.speed/state.json
.speed/running/
.speed/worktrees/
.speed/skills/events.jsonl
EOF
        log_success "Updated .gitignore"
    fi

    # 4. Runtime state (global — for validate and cross-feature use)
    echo '{"status":"idle","agents":[],"started_at":null}' | jq '.' > "${STATE_DIR}/state.json"
    log_success "Runtime state initialized"

    # 5. Project agent file
    if [[ -n "$AGENT_FILE_PATH" ]] && [[ -f "$AGENT_FILE_PATH" ]]; then
        log_info "${AGENT_FILE} already exists, skipping"
    else
        AGENT_FILE="${AGENT_FILE:-AGENTS.md}"
        AGENT_FILE_PATH="${PROJECT_ROOT}/${AGENT_FILE}"
        local project_name
        project_name=$(basename "$PROJECT_ROOT")
        sed "s/{{PROJECT_NAME}}/${project_name}/g" "${TEMPLATES_DIR}/agents-file.md" > "$AGENT_FILE_PATH"
        log_success "Created ${AGENT_FILE} — ${COLOR_DIM}customize this file!${RESET}"
    fi

    # 6. speed.toml
    local speed_toml="${PROJECT_ROOT}/speed.toml"
    if [[ ! -f "$speed_toml" ]]; then
        cp "${TEMPLATES_DIR}/speed-toml.toml" "$speed_toml"
        log_success "Created speed.toml — ${COLOR_DIM}configure providers and settings${RESET}"
    else
        log_info "speed.toml already exists, skipping"
    fi

    # 7. Vision file template
    local vision_path="${PROJECT_ROOT}/${VISION_FILE}"
    local vision_dir
    vision_dir=$(dirname "$vision_path")
    if [[ ! -f "$vision_path" ]]; then
        mkdir -p "$vision_dir"
        cp "${TEMPLATES_DIR}/overview.md" "$vision_path"
        log_success "Created ${VISION_FILE} — ${COLOR_DIM}define your product vision${RESET}"
    else
        log_info "${VISION_FILE} already exists, skipping"
    fi

    # 8. Project the built-in catalog into one selected harness, or all detected
    # harnesses when --harness is omitted. Explicit selection creates its root.
    if [[ -d "${SPEED_DIR}/skills" ]]; then
        local sync_args=(sync)
        if [[ -n "$skill_surface" ]]; then
            sync_args+=(--surface "$skill_surface")
        fi
        local sync_out sync_err sync_status
        sync_err=$(mktemp)
        sync_out=$(cmd_skills "${sync_args[@]}" --json 2>"$sync_err")
        sync_status=$?

        case "$sync_status" in
            0)
                if printf '%s' "$sync_out" | jq -e 'length > 0 and all(.[]; .state == "unsupported")' >/dev/null 2>&1; then
                    log_info "No supported agent skill surface found — run: ${COLOR_STEP}workbench skills sync${RESET} once the project is open in an agent"
                elif [[ -n "$harness" ]]; then
                    log_success "Skills projected for ${harness}"
                else
                    log_success "Skill projection completed for detected harnesses"
                fi
                ;;
            2)
                log_info "Skill projection preserved local edits — run: ${COLOR_STEP}workbench skills doctor${RESET}"
                ;;
            *)
                log_warn "Skill projection failed: $(tr '\n' ' ' < "$sync_err")"
                log_info "Run: ${COLOR_STEP}workbench skills doctor${RESET}"
                ;;
        esac
        rm -f "$sync_err"
    fi

    # 9. Initial commit
    (cd "$PROJECT_ROOT" && git add -A && git commit -m "speed init: project scaffold" 2>/dev/null) || true

    echo ""
    log_success "SPEED initialized! Next steps:"
    echo -e "  1. Edit ${COLOR_STEP}${AGENT_FILE}${RESET} with your project conventions"
    echo -e "  2. Edit ${COLOR_STEP}speed.toml${RESET} to configure your provider and settings"
    echo -e "  3. Edit ${COLOR_STEP}${VISION_FILE}${RESET} with your product vision"
    echo -e "  4. Create a product spec: ${COLOR_STEP}speed new prd my-feature${RESET}"
    echo -e "  5. Plan your tasks: ${COLOR_STEP}speed plan specs/tech/my-feature.md${RESET}"
    echo ""
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
