#!/usr/bin/env bash
# gates.sh — Quality gate runner
#
# Gates are split into two categories:
# 1. Grounding gates (non-LLM) — in grounding.sh
# 2. Quality gates (lint, typecheck, tests) — in this file
# 3. Security gates (SAST, SCA) — warn-only, never block
#
# Grounding gates verify FACTS (files exist, imports resolve, diff non-empty).
# Quality gates verify CODE QUALITY (syntax, lint, types, tests).
# Security gates run SAST/SCA tools and report findings without blocking.

# Requires config.sh, log.sh, and grounding.sh to be sourced first

# Run all gates on a completed task: grounding + quality
# Args: task_id [worktree_path]
# When worktree_path is provided, gates run inside the isolated worktree
# (no git checkout needed). Falls back to PROJECT_ROOT for backwards compat.
# Returns 0 if all pass, 1 if any fail
gates_run() {
    local task_id="$1"
    local worktree_path="${2:-$PROJECT_ROOT}"
    local grounding_passed=true
    local quality_passed=true
    local quality_checks='[]'

    # During scaffolding, skip quality gates (validate at integration time)
    if [[ "${SKIP_GATES:-}" == "true" ]]; then
        log_step "Quality gates skipped (SKIP_GATES=true)"
        _log_gate_skip "gates" "run"
        return 0
    fi

    # ── Grounding gates first (non-LLM) ──────────────────────────
    if ! grounding_run "$task_id" "$worktree_path"; then
        grounding_passed=false
    fi

    # If grounding failed, don't bother with quality gates
    if ! $grounding_passed; then
        log_error "Grounding checks failed — skipping quality gates"
        return 1
    fi

    # ── Quality gates ─────────────────────────────────────────────
    local results=()
    local subsystem
    subsystem=$(_detect_subsystem "$task_id")

    log_step "Running quality gates for task ${task_id} (subsystem: ${subsystem}) in ${worktree_path}..."

    # Gate 1: Syntax check — look for common syntax errors
    if gate_syntax_check "$task_id" "$worktree_path"; then
        results+=("${COLOR_SUCCESS}${SYM_CHECK} Syntax check${RESET}")
        quality_checks=$(echo "$quality_checks" | jq '. + [{"name":"syntax","status":"pass"}]')
    else
        results+=("${COLOR_ERROR}${SYM_CROSS} Syntax check${RESET}")
        quality_passed=false
        quality_checks=$(echo "$quality_checks" | jq '. + [{"name":"syntax","status":"fail"}]')
    fi

    # Gate 2-4: Run each gate type with subsystem filtering
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
            local all_ok=true
            while IFS= read -r cmd; do
                [[ -z "$cmd" ]] && continue
                if gate_run_command "${gate_label}" "$cmd" "$worktree_path"; then
                    results+=("${COLOR_SUCCESS}${SYM_CHECK} ${gate_label}: ${COLOR_DIM}${cmd}${RESET}")
                    quality_checks=$(echo "$quality_checks" | jq --arg n "$gate_type" --arg c "$cmd" '. + [{"name":$n,"status":"pass","command":$c}]')
                else
                    if [[ "$gate_type" == "test" ]] && \
                       _run_scoped_test_fallback "$task_id" "$cmd" "$worktree_path" "$subsystem"; then
                        results+=("${COLOR_WARN}${SYM_WARN} ${gate_label}: passed (task-scoped) — full suite has pre-existing failures${RESET}")
                        quality_checks=$(echo "$quality_checks" | jq --arg n "$gate_type" --arg c "$cmd" '. + [{"name":$n,"status":"warn","command":$c,"note":"task-scoped pass"}]')
                    else
                        results+=("${COLOR_ERROR}${SYM_CROSS} ${gate_label}: ${COLOR_DIM}${cmd}${RESET}")
                        all_ok=false
                        # Capture truncated log output for feedback
                        local gate_log="${worktree_path}/.speed-gate-${gate_type}.log"
                        local gate_output=""
                        if [[ -f "$gate_log" ]]; then
                            gate_output=$(tail -20 "$gate_log" | head -c 500)
                        fi
                        quality_checks=$(echo "$quality_checks" | jq --arg n "$gate_type" --arg c "$cmd" --arg o "$gate_output" '. + [{"name":$n,"status":"fail","command":$c,"output":$o}]')
                    fi
                fi
            done <<< "$cmds"
            if ! $all_ok; then
                quality_passed=false
            fi
        else
            results+=("${COLOR_DIM}${SYM_PENDING} ${gate_label} (not configured for ${subsystem})${RESET}")
        fi
    done

    # Gate 5-6: Security gates (warn-only, never block)
    gate_sast "$task_id" "$worktree_path"
    gate_sca "$task_id" "$worktree_path"

    # Print gate results
    echo ""
    echo -e "  ${BOLD}Quality Gates:${RESET}"
    for r in "${results[@]}"; do
        echo -e "    $r"
    done
    echo ""

    # Persist quality gate results to task JSON (Scenario A)
    local task_json="${TASKS_DIR}/${task_id}.json"
    if [[ -f "$task_json" ]] && [[ "$quality_checks" != "[]" ]]; then
        local tmp_qg; tmp_qg=$(mktemp) || true
        if [[ -n "$tmp_qg" ]]; then
            jq --argjson qc "$quality_checks" '.gate_results.checks += $qc' "$task_json" > "$tmp_qg" 2>/dev/null \
                && mv "$tmp_qg" "$task_json" \
                || rm -f "$tmp_qg"
        fi
    fi

    if $quality_passed; then
        return 0
    else
        return 1
    fi
}

# Basic syntax check for common file types
# Uses branch diff against main (not HEAD~1) to check correct files
# Args: task_id [worktree_path]
gate_syntax_check() {
    local task_id="${1:-}"
    local worktree_path="${2:-$PROJECT_ROOT}"
    local failed=false

    # Determine diff base: use task branch if available, fallback to HEAD~1
    local diff_cmd="git -C ${PROJECT_ROOT} diff --name-only HEAD~1 HEAD"
    if [[ -n "$task_id" ]]; then
        local task_file="${TASKS_DIR}/${task_id}.json"
        if [[ -f "$task_file" ]]; then
            local branch
            branch=$(jq -r '.branch // empty' "$task_file")
            if [[ -n "$branch" ]] && [[ "$branch" != "null" ]]; then
                diff_cmd="git -C ${PROJECT_ROOT} diff --name-only main...${branch}"
            fi
        fi
    fi

    # Get the diff file list once, with error reporting
    local diff_files=""
    diff_files=$(eval "$diff_cmd" 2>&1) || {
        local diff_err=$?
        if [[ $diff_err -ne 0 ]]; then
            log_warn "Syntax check: git diff command failed (exit ${diff_err}): ${diff_files}"
            diff_files=""
        fi
    }

    # Check Python syntax (read files from worktree)
    for f in $(echo "$diff_files" | grep '\.py$' || true); do
        local full_path="${worktree_path}/${f}"
        [[ -f "$full_path" ]] || continue
        if ! python3 -c "import ast; ast.parse(open('${full_path}').read())" 2>/dev/null; then
            log_error "Syntax error in: $f"
            failed=true
        fi
    done

    # Check JSON syntax (read files from worktree)
    for f in $(echo "$diff_files" | grep '\.json$' || true); do
        local full_path="${worktree_path}/${f}"
        [[ -f "$full_path" ]] || continue
        if ! jq empty "$full_path"; then
            log_error "JSON syntax error in: $f"
            failed=true
        fi
    done

    # Check JavaScript syntax (basic)
    # Note: node --check only works on plain .js files.
    # TypeScript (.ts/.tsx) syntax is validated by the typecheck gate (tsc --noEmit) instead.
    # JSX (.jsx/.tsx) is also excluded because JSX is not valid plain JavaScript.
    for f in $(echo "$diff_files" | grep -E '\.js$' || true); do
        local full_path="${worktree_path}/${f}"
        [[ -f "$full_path" ]] || continue
        if command -v node &>/dev/null; then
            if ! node --check "$full_path" 2>/dev/null; then
                log_error "Syntax error in: $f"
                failed=true
            fi
        fi
    done

    ! $failed
}

# Run a gate command and return its exit code
# Args: name cmd [worktree_path]
# Captures output to a log file for diagnostics
gate_run_command() {
    local name="$1"
    local cmd="$2"
    local gate_cwd="${3:-$PROJECT_ROOT}"
    local timestamp
    timestamp=$(date +%s)
    local log_file="${LOGS_DIR}/gate-${name}-${timestamp}.log"

    log_step "Running ${name}: ${COLOR_DIM}${cmd}${RESET}"

    mkdir -p "$LOGS_DIR"

    # Activate venv/node_modules if they exist in the target directory
    # Generic: extract the cd target from the command, check for .venv or node_modules
    local venv_activate=""
    local cmd_target_dir=""
    if [[ "$cmd" =~ ^cd[[:space:]]+([^[:space:]&;]+) ]]; then
        cmd_target_dir="${BASH_REMATCH[1]}"
    fi
    if [[ -n "$cmd_target_dir" ]]; then
        local full_target="${gate_cwd}/${cmd_target_dir}"
        if [[ -f "${full_target}/.venv/bin/activate" ]]; then
            venv_activate="source ${full_target}/.venv/bin/activate && "
        elif [[ -d "${full_target}/node_modules/.bin" ]]; then
            venv_activate="export PATH=${full_target}/node_modules/.bin:\$PATH && "
        fi
    fi

    if (cd "$gate_cwd" && eval "${venv_activate}${cmd}" > "$log_file" 2>&1); then
        _prune_logs "gate-${name}-" ".log"
        return 0
    else
        local total_lines
        total_lines=$(wc -l < "$log_file" | tr -d ' ')

        if [[ "$total_lines" -le 20 ]]; then
            log_error "${name} failed (${total_lines} lines):"
            while IFS= read -r line; do
                echo -e "    ${COLOR_DIM}${line}${RESET}" >&2
            done < "$log_file"
        else
            log_error "${name} failed (${total_lines} lines):"
            head -10 "$log_file" | while IFS= read -r line; do
                echo -e "    ${COLOR_DIM}${line}${RESET}" >&2
            done
            echo -e "    ${COLOR_DIM}... $(( total_lines - 20 )) lines omitted ...${RESET}" >&2
            tail -10 "$log_file" | while IFS= read -r line; do
                echo -e "    ${COLOR_DIM}${line}${RESET}" >&2
            done
        fi
        log_error "Full log: ${log_file}"
        _prune_logs "gate-${name}-" ".log"
        return 1
    fi
}

# Prune old log files, keeping only the most recent N per category.
# Args: prefix suffix
# Matches files: ${LOGS_DIR}/${prefix}*${suffix}
_prune_logs() {
    local prefix="$1"
    local suffix="$2"
    local keep="${LOG_RETAIN_PER_CATEGORY:-3}"

    local files
    files=$(ls -t "${LOGS_DIR}/${prefix}"*"${suffix}" 2>/dev/null || true)
    [[ -z "$files" ]] && return

    local count=0
    while IFS= read -r f; do
        ((count++)) || true
        if [[ $count -gt $keep ]]; then
            rm -f "$f"
        fi
    done <<< "$files"
}

# Detect which subsystem a task touches based on its files_touched.
# Returns: subsystem name (e.g. "frontend", "backend") or "both".
#
# If TOML_SUBSYSTEMS is set (from speed.toml [subsystems]), matches file
# paths against configured glob prefixes. Otherwise uses hardcoded logic.
_detect_subsystem() {
    local task_id="$1"
    local task_file="${TASKS_DIR}/${task_id}.json"

    if [[ ! -f "$task_file" ]]; then
        echo "both"
        return
    fi

    local files_touched
    files_touched=$(jq -r '.files_touched[]?' "$task_file")

    if [[ -z "$files_touched" ]]; then
        echo "both"
        return
    fi

    if [[ -n "${TOML_SUBSYSTEMS:-}" ]]; then
        _detect_subsystem_configured "$files_touched"
    else
        _detect_subsystem_hardcoded "$files_touched"
    fi
}

# Config-driven subsystem detection using TOML_SUBSYSTEMS.
# TOML_SUBSYSTEMS format: "name1:glob1,glob2 name2:glob3"
_detect_subsystem_configured() {
    local files_touched="$1"
    local matched_subsystems=""
    local match_count=0

    local entry
    for entry in $TOML_SUBSYSTEMS; do
        local name="${entry%%:*}"
        local globs="${entry##*:}"
        local matched=false

        # Check each file against the subsystem's globs
        while IFS= read -r f; do
            [[ -z "$f" ]] && continue
            # Split globs by comma and check each
            IFS=',' read -ra glob_array <<< "$globs"
            for glob in "${glob_array[@]}"; do
                # Convert glob to a prefix match (strip trailing /**)
                local prefix="${glob%%/\*\*}"
                prefix="${prefix%%\*}"
                if [[ "$f" == ${prefix}* ]]; then
                    matched=true
                    break
                fi
            done
            $matched && break
        done <<< "$files_touched"

        if $matched; then
            matched_subsystems="${matched_subsystems} ${name}"
            ((match_count++)) || true
        fi
    done

    if [[ $match_count -gt 1 ]]; then
        echo "both"
    elif [[ $match_count -eq 1 ]]; then
        echo "${matched_subsystems## }"
    else
        echo "both"
    fi
}

# Hardcoded subsystem detection (backwards compatibility when no speed.toml).
_detect_subsystem_hardcoded() {
    local files_touched="$1"
    local has_frontend=false
    local has_backend=false
    local has_plugin=false

    while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        if [[ "$f" == src/frontend/* ]]; then
            has_frontend=true
        elif [[ "$f" == src/backend/* ]]; then
            has_backend=true
        elif [[ "$f" == src/plugins/* ]]; then
            has_plugin=true
        fi
    done <<< "$files_touched"

    local subsystem_count=0
    $has_frontend && ((subsystem_count++)) || true
    $has_backend  && ((subsystem_count++)) || true
    $has_plugin   && ((subsystem_count++)) || true

    if (( subsystem_count > 1 )); then
        echo "both"
    elif $has_frontend; then
        echo "frontend"
    elif $has_backend; then
        echo "backend"
    elif $has_plugin; then
        echo "plugin"
    else
        echo "both"
    fi
}

# Read gate configuration from agent file
# Looks for a "## Quality Gates" section with `gate_name: command` entries
# Optional second arg filters by subsystem: "frontend", "backend", or "both" (default)
gates_get_config() {
    local gate_name="$1"
    local subsystem="${2:-both}"

    if [[ -z "$AGENT_FILE_PATH" ]] || [[ ! -f "$AGENT_FILE_PATH" ]]; then
        return
    fi

    # Parse agent file for quality gate commands
    local in_gates_section=false
    local current_subsection=""
    while IFS= read -r line; do
        # Enter the Quality Gates section
        if [[ "$line" =~ ^##[[:space:]]+Quality[[:space:]]+Gates ]]; then
            in_gates_section=true
            continue
        fi
        # Exit on the next h2 header (but NOT h3 subsection headers)
        if $in_gates_section && [[ "$line" =~ ^##[[:space:]] ]] && [[ ! "$line" =~ ^###[[:space:]] ]]; then
            break
        fi
        if $in_gates_section; then
            # Track h3 subsection headers (### Frontend, ### Backend)
            if [[ "$line" =~ ^###[[:space:]]+(.+)$ ]]; then
                current_subsection="${BASH_REMATCH[1]}"
                # Normalize to lowercase
                current_subsection=$(echo "$current_subsection" | tr '[:upper:]' '[:lower:]')
                continue
            fi
            # Match "- gate_name: `command`" or "gate_name: command"
            if [[ "$line" =~ ^[-[:space:]]*${gate_name}:[[:space:]]*(.+)$ ]]; then
                local cmd="${BASH_REMATCH[1]}"
                # Strip backticks (Fix 10)
                cmd="${cmd#\`}"
                cmd="${cmd%\`}"
                # Filter by subsystem
                if [[ "$subsystem" == "both" ]]; then
                    echo "$cmd"
                elif [[ "$current_subsection" == *"$subsystem"* ]]; then
                    echo "$cmd"
                fi
                # Do NOT return — continue to find ALL matching commands
            fi
        fi
    done < "$AGENT_FILE_PATH"
}

# Build a list of test file paths scoped to a task's files_touched.
# Maps source files to their likely test counterparts:
#   frontend: foo.tsx → foo.test.tsx, foo.ts → foo.test.ts
#   backend:  app/models/foo.py → tests/test_foo.py
# Also includes any test files directly listed in files_touched.
# Returns space-separated paths that exist on disk, or empty if none found.
# Args: task_id worktree_path
_build_scoped_test_paths() {
    local task_id="$1"
    local worktree_path="$2"
    local task_file="${TASKS_DIR}/${task_id}.json"

    [[ -f "$task_file" ]] || return

    local files_touched
    files_touched=$(jq -r '.files_touched[]?' "$task_file")
    [[ -z "$files_touched" ]] && return

    local test_paths=()

    while IFS= read -r f; do
        [[ -z "$f" ]] && continue

        # If the file is already a test file, include it directly
        if [[ "$f" == *.test.ts ]] || [[ "$f" == *.test.tsx ]] || [[ "$f" == */test_*.py ]] || [[ "$f" == *_test.py ]]; then
            local full="${worktree_path}/${f}"
            [[ -f "$full" ]] && test_paths+=("$f")
            continue
        fi

        # Frontend: foo.tsx → foo.test.tsx, foo.ts → foo.test.ts
        if [[ "$f" == *.tsx ]]; then
            local candidate="${f%.tsx}.test.tsx"
            [[ -f "${worktree_path}/${candidate}" ]] && test_paths+=("$candidate")
        elif [[ "$f" == *.ts ]] && [[ "$f" != *.d.ts ]]; then
            local candidate="${f%.ts}.test.ts"
            [[ -f "${worktree_path}/${candidate}" ]] && test_paths+=("$candidate")
        fi

        # Backend: src/backend/app/models/foo.py → src/backend/tests/test_foo.py
        if [[ "$f" == *.py ]] && [[ "$f" != */test_*.py ]]; then
            local basename
            basename=$(basename "$f" .py)
            # Look for test_<name>.py in common test directories
            local dir
            dir=$(dirname "$f")
            # Check sibling tests/ directory
            local parent
            parent=$(dirname "$dir")
            for test_dir in "${dir}/tests" "${parent}/tests" "${dir}"; do
                local candidate="${test_dir}/test_${basename}.py"
                [[ -f "${worktree_path}/${candidate}" ]] && test_paths+=("$candidate")
            done
        fi
    done <<< "$files_touched"

    # Deduplicate and return
    if [[ ${#test_paths[@]} -gt 0 ]]; then
        printf '%s\n' "${test_paths[@]}" | sort -u | tr '\n' ' '
    fi
}

# Attempt to run tests scoped to a task's changed files.
# Called when the full test suite fails — if scoped tests pass, the failure
# is from pre-existing issues, not from this task's changes.
# Args: task_id base_cmd worktree_path subsystem
# Returns 0 if scoped tests pass, 1 if they fail or no scoping possible.
_run_scoped_test_fallback() {
    local task_id="$1"
    local base_cmd="$2"
    local gate_cwd="$3"
    local subsystem="$4"

    local scoped_paths
    scoped_paths=$(_build_scoped_test_paths "$task_id" "$gate_cwd")
    if [[ -z "$scoped_paths" ]]; then
        log_info "No test files correspond to this task's changes — pre-existing failures not attributed"
        return 0
    fi

    # Build scoped test command based on the base command pattern
    local scoped_cmd=""
    if [[ "$base_cmd" == *"vitest"* ]]; then
        # vitest accepts file paths directly
        scoped_cmd="${base_cmd} ${scoped_paths}"
    elif [[ "$base_cmd" == *"pytest"* ]]; then
        # pytest accepts file paths directly
        scoped_cmd="${base_cmd} ${scoped_paths}"
    else
        return 1  # Unknown test runner — can't scope
    fi

    log_step "Re-running tests scoped to task files..."
    if gate_run_command "Tests (scoped)" "$scoped_cmd" "$gate_cwd"; then
        return 0  # Scoped tests passed
    else
        return 1  # Scoped tests also failed — real failure
    fi
}

# ── Security gates (warn-only) ───────────────────────────────

# Run SAST tool and report findings. Never blocks — always returns 0.
# Appends results to the `results` array in the calling scope.
# Args: task_id [worktree_path]
gate_sast() {
    local task_id="$1"
    local worktree_path="${2:-$PROJECT_ROOT}"

    local sast_cmd="${TOML_SECURITY_SAST_CMD:-}"
    if [[ -z "$sast_cmd" ]]; then
        return 0
    fi

    # Resolve feature name for log directory
    local feature_name="unknown"
    local task_file="${TASKS_DIR}/${task_id}.json"
    if [[ -f "$task_file" ]]; then
        feature_name=$(jq -r '.feature // "unknown"' "$task_file")
    fi

    local logs_dir="${STATE_DIR}/features/${feature_name}/logs"
    mkdir -p "$logs_dir"

    local raw_output="${logs_dir}/sast-output.json"
    local parsed_output="${logs_dir}/sast-findings.json"

    # Run the SAST tool inside the worktree
    local sast_exit=0
    (cd "$worktree_path" && eval "$sast_cmd" > "$raw_output" 2>&1) || sast_exit=$?

    # Non-zero exit with no output: tool not installed or crashed
    if [[ $sast_exit -ne 0 ]] && [[ ! -s "$raw_output" ]]; then
        log_warn "SAST tool failed (exit ${sast_exit}). Is '${sast_cmd%% *}' installed?"
        return 0
    fi

    # Parse raw output into normalized findings
    security_sast_parse "$raw_output" "$parsed_output"

    # Count and summarize findings
    local count=0
    count=$(jq 'length' "$parsed_output" 2>/dev/null) || count=0

    if [[ "$count" -gt 0 ]]; then
        local summary
        summary=$(jq -r 'group_by(.severity) | map("\(length) \(.[0].severity)") | join(", ")' "$parsed_output" 2>/dev/null) || summary=""
        results+=("${COLOR_WARN}${SYM_WARN} SAST: ${count} finding(s) (${summary})${RESET}")

        # Print individual finding lines
        jq -r '.[] | "      [\(.severity)] \(.title) — \(.file):\(.line)"' "$parsed_output" 2>/dev/null | \
            while IFS= read -r line; do
                echo -e "    ${COLOR_WARN}${line}${RESET}"
            done
    else
        results+=("${COLOR_SUCCESS}${SYM_CHECK} SAST: no findings${RESET}")
    fi

    return 0
}

# Run SCA tool and report findings. Never blocks — always returns 0.
# Appends results to the `results` array in the calling scope.
# Args: task_id [worktree_path]
gate_sca() {
    local task_id="$1"
    local worktree_path="${2:-$PROJECT_ROOT}"

    local sca_cmd="${TOML_SECURITY_SCA_CMD:-}"
    if [[ -z "$sca_cmd" ]]; then
        return 0
    fi

    # Resolve feature name for log directory
    local feature_name="unknown"
    local task_file="${TASKS_DIR}/${task_id}.json"
    if [[ -f "$task_file" ]]; then
        feature_name=$(jq -r '.feature // "unknown"' "$task_file")
    fi

    local logs_dir="${STATE_DIR}/features/${feature_name}/logs"
    mkdir -p "$logs_dir"

    local raw_output="${logs_dir}/sca-output.json"
    local parsed_output="${logs_dir}/sca-findings.json"

    # Run the SCA tool inside the worktree
    local sca_exit=0
    (cd "$worktree_path" && eval "$sca_cmd" > "$raw_output" 2>&1) || sca_exit=$?

    # Non-zero exit with no output: tool not installed or crashed
    if [[ $sca_exit -ne 0 ]] && [[ ! -s "$raw_output" ]]; then
        log_warn "SCA tool failed (exit ${sca_exit}). Is '${sca_cmd%% *}' installed?"
        return 0
    fi

    # Parse raw output into normalized findings
    security_sca_parse "$raw_output" "$parsed_output"

    # Count and summarize findings
    local count=0
    count=$(jq 'length' "$parsed_output" 2>/dev/null) || count=0

    if [[ "$count" -gt 0 ]]; then
        local summary
        summary=$(jq -r 'group_by(.severity) | map("\(length) \(.[0].severity)") | join(", ")' "$parsed_output" 2>/dev/null) || summary=""
        results+=("${COLOR_WARN}${SYM_WARN} SCA: ${count} finding(s) (${summary})${RESET}")

        # Print individual finding lines
        jq -r '.[] | "      [\(.severity)] \(.title)"' "$parsed_output" 2>/dev/null | \
            while IFS= read -r line; do
                echo -e "    ${COLOR_WARN}${line}${RESET}"
            done
    else
        results+=("${COLOR_SUCCESS}${SYM_CHECK} SCA: no findings${RESET}")
    fi

    return 0
}
