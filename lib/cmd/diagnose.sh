#!/usr/bin/env bash
# diagnose.sh — First step in the validation workflow.
#
# Runs as soon as an agent's task comes back, before anything judges it.
# Counts mechanical signals for every failure class the project has
# declared in its own classes.yaml (see lib/diagnose_engine.py) and writes
# a risk-surface artifact. It never rules on anything: every class gets
# `plausible: undecided`, no matter how many signals fired, and the
# command always exits 0 on a successful run — a diagnosis is evidence,
# not a verdict.
#
# Usage: speed diagnose -f <feature> --task <id>

cmd_diagnose() {
    _require_feature "$GLOBAL_FEATURE"
    _ensure_jq

    local task_id=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --task) task_id="$2"; shift 2 ;;
            *) log_error "Unknown option: $1"; exit "$EXIT_CONFIG_ERROR" ;;
        esac
    done

    if [[ -z "$task_id" ]]; then
        log_error "Required: --task ID"
        echo "Usage: speed diagnose -f <feature> --task <id>"
        exit "$EXIT_CONFIG_ERROR"
    fi

    # No generic fallback: a project's failure classes are its own
    # knowledge, not SPEED's.
    local classes_file="${TOML_DIAGNOSE_CLASSES_FILE:-.speed/classes.yaml}"
    local classes_path="${PROJECT_ROOT}/${classes_file}"
    if [[ ! -f "$classes_path" ]]; then
        log_error_block \
            "No Diagnose class rules configured for this project." \
            "diagnose has no domain knowledge of its own — a project must declare what to count." \
            "Add [diagnose] classes_file to speed.toml (e.g. classes_file = \".speed/classes.yaml\") and create that file."
        exit "$EXIT_CONFIG_ERROR"
    fi

    # ── Read only branch, files_touched and agent_model from the task.
    # Deliberately NOT description, acceptance_criteria or review_feedback —
    # all three are written about the change, after it exists, and would
    # hand the human the verdict this command must not make.
    local task_json
    task_json=$(task_get "$task_id") || exit "$EXIT_CONFIG_ERROR"

    local branch agent_model files_touched_json
    branch=$(echo "$task_json" | jq -r '.branch // empty')
    agent_model=$(echo "$task_json" | jq -r '.agent_model // "unspecified"')
    files_touched_json=$(echo "$task_json" | jq -c '.files_touched // []')

    if [[ -z "$branch" ]]; then
        log_error "Task ${task_id} has no branch recorded — cannot diff."
        exit "$EXIT_CONFIG_ERROR"
    fi

    local main_branch
    main_branch=$(git_main_branch)

    if ! git_branch_exists "$branch"; then
        log_error "Branch '${branch}' not found — cannot diagnose task ${task_id}."
        exit "$EXIT_CONFIG_ERROR"
    fi

    log_header "Diagnose"
    log_step "Change: ${main_branch}...${branch}"

    local diff_file
    diff_file=$(mktemp)
    if ! git_diff_branch "$branch" "$main_branch" > "$diff_file" 2>/dev/null; then
        rm -f "$diff_file"
        log_error "Could not diff '${main_branch}...${branch}' — verify both refs exist (check MAIN_BRANCH if set)."
        exit "$EXIT_CONFIG_ERROR"
    fi

    # Optional: a spec file for new-names-absent-from-spec. Diagnose-specific
    # config wins; falls back to the project's existing [specs] vision_file
    # rather than inventing a second way to say "here is the spec."
    local spec_file=""
    if [[ -n "${TOML_DIAGNOSE_SPEC_FILE:-}" ]]; then
        spec_file="${PROJECT_ROOT}/${TOML_DIAGNOSE_SPEC_FILE}"
    elif [[ -n "${TOML_SPECS_VISION_FILE:-}" ]]; then
        spec_file="${PROJECT_ROOT}/${TOML_SPECS_VISION_FILE}"
    fi

    local engine_json rc=0
    local engine_err_file engine_err
    engine_err_file=$(mktemp)
    if [[ -n "$spec_file" ]]; then
        engine_json=$(python3 "${LIB_DIR}/diagnose_engine.py" "$classes_path" "$diff_file" "$files_touched_json" "$spec_file" 2>"$engine_err_file") || rc=$?
    else
        engine_json=$(python3 "${LIB_DIR}/diagnose_engine.py" "$classes_path" "$diff_file" "$files_touched_json" 2>"$engine_err_file") || rc=$?
    fi
    engine_err=$(cat "$engine_err_file" 2>/dev/null)
    rm -f "$diff_file" "$engine_err_file"

    if [[ $rc -ne 0 ]]; then
        log_error "diagnose engine failed: ${engine_err:-exit code $rc}"
        exit "$EXIT_CONFIG_ERROR"
    fi

    # ── Console summary. Count = number of signals that fired for that
    # class, not the number of rules declared — a rule with nothing
    # countable contributes no line here, same as it contributes no
    # entry to signals: [] below.
    echo "$engine_json" | jq -r '.classes[] | "\(.id)\t\(.title)\t\(.signals | length)"' \
    | while IFS=$'\t' read -r cid ctitle ccount; do
        printf "  %-3s %-50s %s signal(s)\n" "$cid" "$ctitle" "$ccount"
    done

    local out_file="${FEATURE_DIR}/risk-surface.yaml"
    mkdir -p "$(dirname "$out_file")"
    _diagnose_write_risk_surface "$task_id" "$branch" "$agent_model" "$engine_json" > "$out_file"

    log_result ""
    log_result "Risk surface written to ${out_file#"${PROJECT_ROOT}"/}"
    log_result "Every verdict is undecided. Fill them in before running any check."

    exit "$EXIT_OK"
}

# Renders the engine's JSON as risk-surface YAML.
_diagnose_write_risk_surface() {
    local task_id="$1" branch="$2" agent_model="$3" engine_json="$4"

    echo "# Written by \`speed diagnose\`. The signals are counted. The verdicts are yours."
    echo "task: \"${task_id}\""
    echo "branch: \"${branch}\""
    echo "agent_model: \"${agent_model}\""
    echo "classes:"

    echo "$engine_json" | jq -c '.classes[]' | while IFS= read -r cls_json; do
        local cid ctitle_json sig_count
        cid=$(echo "$cls_json" | jq -r '.id')
        ctitle_json=$(echo "$cls_json" | jq -r '.title | tojson')
        sig_count=$(echo "$cls_json" | jq '.signals | length')

        echo "  - id: ${cid}"
        echo "    failureMode: ${ctitle_json}"
        echo "    plausible: undecided"
        echo "    costOfMissing: undecided"
        echo "    findableByReading: undecided"

        if [[ "$sig_count" -eq 0 ]]; then
            echo "    signals: []   # nothing countable. Not a ruling."
            continue
        fi

        echo "    signals:"
        echo "$cls_json" | jq -c '.signals[]' | while IFS= read -r sig_json; do
            local observed_json where_len
            observed_json=$(echo "$sig_json" | jq -r '.observed | tojson')
            echo "      - observed: ${observed_json}"
            where_len=$(echo "$sig_json" | jq '.where | length')
            if [[ "$where_len" -gt 0 ]]; then
                echo "        where:"
                echo "$sig_json" | jq -r '.where[] | tojson' | while IFS= read -r w_json; do
                    echo "          - ${w_json}"
                done
            fi
        done
    done
}
