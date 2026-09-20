#!/usr/bin/env bash
# Evaluate a feature using validated inputs, recorded test outcomes, and an
# immutable attempt directory. The Python runtime owns runner evidence and
# reports; this command retains provider dispatch and the normal CLI display.

_eval_build_report() {
    local output_dir="$1" judgment="${2:-}"
    local args=("${LIB_DIR}/eval_report.py"
        --feature "$FEATURE_NAME" --project-root "$PROJECT_ROOT"
        --tasks-dir "${output_dir}/tasks" --test-spec "${output_dir}/test-spec.md"
        --output-dir "$output_dir" --test-plan "${output_dir}/test-plan.json"
        --scenario-results "${output_dir}/scenario-results.json"
        --context "${output_dir}/context.json" --runner-config "${output_dir}/runner-config.json")
    [[ -n "${_eval_task_filter:-}" ]] && args+=(--task-id "$_eval_task_filter")
    [[ -n "$judgment" ]] && args+=(--judgment "$judgment")
    "$(_context_python)" "${args[@]}"
}

# Terminal report: individual scenario/test evidence first, followed by gaps,
# failures and artifact paths. Criterion rows must not look like extra tests.
_eval_print_summary() {
    local report="$1"
    local test_spec="$2"
    local output_dir="$3"
    local commit branch spec_rel
    # Only a real SHA is shortened; the dirty-tree label must survive intact.
    commit=$(jq -r '(.commit // "uncommitted-working-tree")
                   | if test("^[0-9a-f]{40}$") then .[0:7] else . end' "$report")
    branch=$(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || true)
    [[ -n "$branch" && "$branch" != "HEAD" ]] || branch="detached"
    spec_rel="${test_spec#"${PROJECT_ROOT}/"}"

    echo ""
    log_step "Change: ${branch} @ ${commit}   spec: ${spec_rel}"
    "$(_context_python)" "${LIB_DIR}/eval_display.py" "$report" --evidence-root "$output_dir"

    local rows
    rows=$(jq -r '.results[] | select(.status == "unverifiable")
                  | [.id, (((.traces // []) | join(", ")) | if . == "" then "-" else . end), .evidence] | @tsv' "$report")
    if [[ -n "$rows" ]]; then
        echo ""
        echo "    not examined"
        while IFS=$'\t' read -r id trace reason; do
            printf '      %-10s %-40s %s\n' "$id" "$trace" "$reason"
        done <<< "$rows"
    fi

    rows=$(jq -r '.out_of_scope[]? | [(.id // "-"), .disposition, (.owner // "-")] | @tsv' "$report")
    if [[ -n "$rows" ]]; then
        echo ""
        echo "    not examined by decision"
        while IFS=$'\t' read -r id disposition owner; do
            printf '      %-10s %-26s %s\n' "$id" "$disposition" "$owner"
        done <<< "$rows"
    fi

    rows=$(jq -r '.results[] | select(.status == "fail" or .status == "partial" or .status == "blocked_upstream")
                  | [.id, .evidence_type, .evidence] | @tsv' "$report")
    if [[ -n "$rows" ]]; then
        echo ""
        echo "    failed"
        while IFS=$'\t' read -r id evidence_type reason; do
            printf '      %-10s %-15s %s\n' "$id" "$evidence_type" "$reason"
        done <<< "$rows"
    fi

    echo ""
    log_step "Report written to ${COLOR_STEP}${output_dir}/summary.md${RESET}"
    local handoff="${FEATURE_DIR}/evaluation.yaml"
    [[ -z "${_eval_task_filter:-}" ]] || handoff="${FEATURE_DIR}/evaluation-task-${_eval_task_filter}.yaml"
    log_step "Evaluation written to ${COLOR_STEP}${handoff}${RESET}"
}

# One line that says what the report supports, without a percentage.
# eval_report.py refuses acceptance with every count at zero when no applicable
# result exists, so the empty case is real and needs its own wording. Built as
# a string rather than an array: bash 3.2 treats an empty array as unbound
# under `set -u`, and IFS joins with only the first character of the separator.
_eval_verdict_line() {
    local report="$1"
    local failed silent line=""
    failed=$(jq '.summary.fail + .summary.partial + .summary.blocked_upstream' "$report")
    silent=$(jq '.summary.unverifiable' "$report")
    [[ "$failed" -gt 0 ]] && line="${failed} failed"
    if [[ "$silent" -gt 0 ]]; then
        [[ -z "$line" ]] || line="${line}; "
        line="${line}${silent} never examined"
    fi
    [[ -n "$line" ]] || line="nothing applicable was examined"
    printf '%s' "$line"
}

_eval_run_semantic_judge() {
    local test_spec="$1"
    local output_dir="$2"
    local residue_file="${output_dir}/residue.json"
    local judgment_file="${output_dir}/judgment.json"
    local residue_count
    residue_count=$(jq '.results | length' "$residue_file")
    [[ "$residue_count" -gt 0 ]] || return 2

    local rfc_content=""
    local spec_file
    spec_file=$(_get_spec_path)
    [[ -n "$spec_file" ]] && [[ -f "$spec_file" ]] && rfc_content=$(cat "$spec_file")

    local prompt="## Semantic Acceptance Residue

Project root: ${PROJECT_ROOT}
Feature: ${FEATURE_NAME}

### RFC
${rfc_content}

### Test Spec
$(cat "$test_spec")

### Criteria Requiring Judgment
$(cat "$residue_file")

Inspect the read-only project when evidence is available. Return one result for
each supplied criterion ID. Do not judge or override executable scenarios."

    local output parsed
    if ! output=$(provider_run_json \
        "${AGENTS_DIR}/evaluator.md" \
        "$prompt" \
        "${TEMPLATES_DIR}/evaluator-output.json" \
        "$MODEL_SUPPORT" \
        "$DEFAULT_JSON_MAX_TURNS" \
        "$AGENT_TOOLS_READONLY" \
        "Evaluator" \
        "$DEFAULT_AGENT_TIMEOUT"); then
        log_warn "Evaluator agent failed; semantic criteria remain unverifiable"
        return 1
    fi
    if ! parsed=$(parse_agent_json "$output"); then
        log_warn "Evaluator returned invalid JSON; semantic criteria remain unverifiable"
        return 1
    fi
    if ! echo "$parsed" | jq -e '
        type == "object" and (.results | type == "array") and
        all(.results[]; type == "object" and (.id | type == "string") and
            (.status == "pass" or .status == "partial" or .status == "fail" or .status == "unverifiable") and
            (.evidence | type == "string" and length > 0))' >/dev/null; then
        log_warn "Evaluator returned invalid result records; semantic criteria remain unverifiable"
        return 1
    fi
    echo "$parsed" | jq '.' > "$judgment_file"
    printf '%s\n' "$judgment_file"
}

_eval_file_defects() {
    local report_file="$1"
    local count=0
    mkdir -p "${PROJECT_ROOT}/specs/defects"

    while IFS= read -r result; do
        [[ -n "$result" ]] || continue
        local id title status evidence slug defect_file
        id=$(echo "$result" | jq -r '.id')
        title=$(echo "$result" | jq -r '.title')
        status=$(echo "$result" | jq -r '.status')
        evidence=$(echo "$result" | jq -r '.evidence')
        slug=$(printf 'eval-%s-%s' "$FEATURE_NAME" "$id" \
            | tr '[:upper:]' '[:lower:]' \
            | sed 's/[^a-z0-9-]/-/g; s/--*/-/g' \
            | cut -c1-80)
        defect_file="${PROJECT_ROOT}/specs/defects/${slug}.md"

        if [[ -d "$(_defect_dir "$slug")" ]]; then
            continue
        fi

        if [[ -e "$defect_file" || -L "$defect_file" ]]; then
            log_warn "Existing defect spec preserved: ${defect_file}"
            continue
        fi
        if ! (set -C; printf '%s\n' \
            "Severity: P2" \
            "Related Feature: ${FEATURE_NAME}" \
            "Tags: evaluation, acceptance" \
            "Classification-Override: moderate" \
            "" \
            "Observed: Evaluation result ${id} is ${status}. ${evidence}" \
            "Expected: ${title}" \
            "Repro: Run speed eval --feature ${FEATURE_NAME} and inspect ${report_file}" \
            > "$defect_file"); then
            log_warn "Could not create defect spec without overwriting: ${defect_file}"
            continue
        fi

        if defect_init "$slug" "$defect_file"; then
            count=$((count + 1))
        fi
    done < <(jq -c '.results[] | select(.status == "fail" or .status == "partial")' "$report_file")

    [[ "$count" -gt 0 ]] && log_warn "Filed ${count} evaluation defect(s)"
    return 0
}

_eval_test_spec_path() {
    local override="${1:-}"
    local path=""
    if [[ -n "$override" ]]; then
        path="$override"
    elif [[ -f "${FEATURE_DIR}/test_spec_path" ]]; then
        path=$(cat "${FEATURE_DIR}/test_spec_path")
    else
        local rfc=""
        rfc=$(_get_spec_path 2>/dev/null) || rfc=""
        if [[ "$rfc" == *"/tech/"* ]]; then
            # Rewrite the last '/tech/' only. sed would take the leftmost
            # match and derive a bogus path for a checkout under a directory
            # that happens to be named 'tech'.
            path="${rfc%/tech/*}/tests/${rfc##*/tech/}"
            # A derived sibling is optional; explicit paths above are not.
            if [[ "$path" == /* ]]; then
                [[ -f "$path" ]] || path=""
            else
                [[ -f "${PROJECT_ROOT}/${path}" ]] || path=""
            fi
        fi
    fi
    if [[ -z "$path" && -n "${FEATURE_NAME:-}" && -f "${PROJECT_ROOT}/specs/tests/${FEATURE_NAME}.md" ]]; then
        # The default the help text and the error message promise.
        path="specs/tests/${FEATURE_NAME}.md"
    fi
    [[ -n "$path" ]] || return 1
    [[ "$path" == /* ]] || path="${PROJECT_ROOT}/${path}"
    [[ -f "$path" ]] || return 1
    printf '%s\n' "$path"
}

# Validate a user-supplied path with the rule the Python runtime enforces for
# evaluation state: inside the project root, reached without traversing a
# symlink. A committed spec symlinked at a private key needs no '../' to leak
# it, and the spec text is pasted verbatim into the evaluator prompt.
_eval_guard_path() {
    local py="$1" path="$2"
    [[ "$path" == /* ]] || path="${PROJECT_ROOT}/${path}"
    "$py" "${LIB_DIR}/eval_runtime.py" guard --root "$PROJECT_ROOT" --path "$path"
}

# Every --json exit owes stdout exactly one object. Error objects name the
# reason and state non-acceptance explicitly so no consumer can read one as a
# pass. Always returns 0; the caller decides the exit code.
_eval_reject() {
    local code="$1" reason="$2"
    log_error "$reason"
    if [[ "${JSON_OUTPUT:-false}" == true ]]; then
        jq -n --arg reason "$reason" \
              --arg feature "${FEATURE_NAME:-${GLOBAL_FEATURE:-}}" \
              --argjson code "$code" \
              '{accepted: false, evaluated: false, error: $reason,
                feature: $feature, exit_code: $code, results: [], out_of_scope: [],
                summary: {total: 0, pass: 0, partial: 0, fail: 0, unverifiable: 0,
                          not_applicable: 0, blocked_upstream: 0, applicable: 0,
                          examined: 0, not_examined: 0}}' >&3
    fi
    return 0
}

# eval_runtime already printed the detail on stderr; replay it for humans and
# fold it into one line so the JSON error object carries the same reason.
_eval_runtime_reason() {
    local err_file="$1" fallback="$2" reason=""
    if [[ -s "$err_file" ]]; then
        cat "$err_file" >&2
        # Drop the runtime's own "Evaluation: " prefix so the wrapped
        # message does not say it twice.
        reason=$(tr '\n' ' ' < "$err_file" \
            | sed 's/^Evaluation: //; s/  */ /g; s/^ *//; s/ *$//')
    fi
    printf '%s' "${reason:-$fallback}"
}

# Run in a subshell so lock/signal cleanup is scoped to this invocation and
# does not replace the caller's cleanup traps.
cmd_eval() (
    # Logs and summaries must never contaminate machine-readable stdout. The
    # swap happens before argument parsing so even a bad option can answer on
    # fd 3 instead of leaving `speed eval --json | jq .` with empty input.
    if [[ "${JSON_OUTPUT:-false}" == true ]]; then
        exec 3>&1
        exec 1>&2
    fi
    local strict="${SPEED_EVAL_STRICT:-false}"
    local file_defects="${SPEED_EVAL_FILE_DEFECTS:-true}"
    local skip_judge=false _eval_task_filter="" test_spec_override="" test_plan_override="" manual_results=""
    local _eval_run_dir="" _eval_complete=false _eval_runtime_err=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --strict) strict=true; shift ;;
            --no-defects) file_defects=false; shift ;;
            --skip-judge) skip_judge=true; shift ;;
            --task|--task-id|--test-spec|--test-plan|--manual-results)
                if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
                    _eval_reject "$EXIT_CONFIG_ERROR" "${1} requires a value"
                    return "$EXIT_CONFIG_ERROR"
                fi
                case "$1" in
                    --task|--task-id) _eval_task_filter="$2" ;;
                    --test-spec) test_spec_override="$2" ;;
                    --test-plan) test_plan_override="$2" ;;
                    --manual-results) manual_results="$2" ;;
                esac
                shift 2 ;;
            *) _eval_reject "$EXIT_CONFIG_ERROR" "Unknown eval option: $1"
               return "$EXIT_CONFIG_ERROR" ;;
        esac
    done
    if [[ -n "$_eval_task_filter" && ! "$_eval_task_filter" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$ ]]; then
        _eval_reject "$EXIT_CONFIG_ERROR" "Invalid task ID: $_eval_task_filter"
        return "$EXIT_CONFIG_ERROR"
    fi
    local feature_name feature_root py expected_state expected_logs
    feature_name=$(feature_resolve "${GLOBAL_FEATURE:-}") || {
        _eval_reject "$EXIT_CONFIG_ERROR" "No feature context; use --feature NAME"
        return "$EXIT_CONFIG_ERROR"
    }
    if [[ ! "$feature_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$ ]]; then
        _eval_reject "$EXIT_CONFIG_ERROR" "Invalid feature ID: $feature_name"
        return "$EXIT_CONFIG_ERROR"
    fi
    feature_root="$FEATURES_DIR"
    [[ "${MP_ENABLED:-}" == true ]] && feature_root="$SHARED_FEATURES_DIR"
    expected_state="${feature_root}/${feature_name}/state.json"
    expected_logs="${feature_root}/${feature_name}/logs"
    if [[ "${MP_ENABLED:-}" == true ]]; then
        expected_state="${LOCAL_DIR}/features/${feature_name}/state.json"
        expected_logs="${LOCAL_DIR}/features/${feature_name}/logs"
    fi
    py=$(_context_python)
    if ! "$py" "${LIB_DIR}/eval_runtime.py" guard --root "$PROJECT_ROOT" \
        --path "${feature_root}/${feature_name}" --path "${feature_root}/${feature_name}/tasks" \
        --path "${feature_root}/${feature_name}/eval" --path "${LOCAL_DIR}/locks" \
        --path "$expected_state" --path "$expected_logs"; then
        _eval_reject "$EXIT_CONFIG_ERROR" "Feature evaluation paths failed validation"
        return "$EXIT_CONFIG_ERROR"
    fi
    # _require_feature exits the shell when the feature is missing or claimed
    # by someone else, which would skip the reject handler and break the JSON
    # contract. Check once in a subshell, then restore the selected paths.
    if ! ( _require_feature "$feature_name" ) >/dev/null 2>&1; then
        _eval_reject "$EXIT_CONFIG_ERROR" "Feature ${feature_name} is not available for evaluation"
        return "$EXIT_CONFIG_ERROR"
    fi
    feature_activate "$feature_name"
    if ! "$py" "${LIB_DIR}/eval_runtime.py" guard --root "$PROJECT_ROOT" \
        --path "$STATE_FILE" --path "$SPEED_LOCK"; then
        _eval_reject "$EXIT_CONFIG_ERROR" "Feature state or lock path failed validation"
        return "$EXIT_CONFIG_ERROR"
    fi
    if ! speed_acquire_lock "eval"; then
        _eval_reject "$EXIT_CONFIG_ERROR" "Could not acquire the SPEED lock; another command is running"
        return "$EXIT_CONFIG_ERROR"
    fi
    _eval_runtime_err=$(mktemp)
    _eval_cleanup() {
        [[ -z "$_eval_runtime_err" ]] || rm -f "$_eval_runtime_err"
        if [[ -n "$_eval_run_dir" && "$_eval_complete" != true ]]; then
            "$py" "${LIB_DIR}/eval_runtime.py" abort "$_eval_run_dir" || true
        fi
        speed_release_lock
    }
    trap '_eval_cleanup' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    local test_spec
    test_spec=$(_eval_test_spec_path "$test_spec_override") || {
        _eval_reject "$EXIT_CONFIG_ERROR" "No test spec found; pass --test-spec PATH or create specs/tests/<name>.md"
        return "$EXIT_CONFIG_ERROR"
    }
    # Every path the caller supplied is validated before anything reads it.
    if ! _eval_guard_path "$py" "$test_spec"; then
        _eval_reject "$EXIT_CONFIG_ERROR" "Test spec path is outside the project or crosses a symlink: ${test_spec}"
        return "$EXIT_CONFIG_ERROR"
    fi
    local prepare=("${LIB_DIR}/eval_runtime.py" prepare --root "$PROJECT_ROOT"
        --feature-dir "$FEATURE_DIR" --state-file "$STATE_FILE" --test-spec "$test_spec")
    [[ -n "$_eval_task_filter" ]] && prepare+=(--task-id "$_eval_task_filter")
    if [[ -n "$test_plan_override" ]]; then
        [[ "$test_plan_override" == /* ]] || test_plan_override="${PROJECT_ROOT}/${test_plan_override}"
        if ! _eval_guard_path "$py" "$test_plan_override"; then
            _eval_reject "$EXIT_CONFIG_ERROR" "Test plan path is outside the project or crosses a symlink: ${test_plan_override}"
            return "$EXIT_CONFIG_ERROR"
        fi
        prepare+=(--test-plan "$test_plan_override")
    fi
    if [[ -n "$manual_results" ]]; then
        [[ "$manual_results" == /* ]] || manual_results="${PROJECT_ROOT}/${manual_results}"
        if ! _eval_guard_path "$py" "$manual_results"; then
            _eval_reject "$EXIT_CONFIG_ERROR" "Manual results path is outside the project or crosses a symlink: ${manual_results}"
            return "$EXIT_CONFIG_ERROR"
        fi
        prepare+=(--manual-results "$manual_results")
    fi
    # An evaluation that could not run is not a failed acceptance. eval_runtime
    # exits 2 on RuntimeError (an operational stop such as "requires done
    # tasks") and 3 on invalid input; both mean "did not evaluate", so both
    # surface as EXIT_CONFIG_ERROR and EXIT_GATE_FAILURE keeps its single
    # meaning: evaluation ran and the result was not accepted.
    local reason=""
    if ! _eval_run_dir=$("$py" "${prepare[@]}" 2>"$_eval_runtime_err"); then
        reason=$(_eval_runtime_reason "$_eval_runtime_err" "evaluation inputs were rejected")
        _eval_reject "$EXIT_CONFIG_ERROR" "Evaluation did not run: ${reason}"
        return "$EXIT_CONFIG_ERROR"
    fi
    log_header "Eval: ${FEATURE_NAME}${_eval_task_filter:+ (task ${_eval_task_filter})}"
    log_step "Evidence: $_eval_run_dir"
    if ! "$py" "${LIB_DIR}/eval_runtime.py" execute "$_eval_run_dir" 2>"$_eval_runtime_err"; then
        reason=$(_eval_runtime_reason "$_eval_runtime_err" "the evidence run failed")
        _eval_reject "$EXIT_CONFIG_ERROR" "Evaluation did not complete: ${reason}"
        return "$EXIT_CONFIG_ERROR"
    fi
    if ! _eval_build_report "$_eval_run_dir" >/dev/null; then
        _eval_reject "$EXIT_CONFIG_ERROR" "Could not build the evaluation report"
        return "$EXIT_CONFIG_ERROR"
    fi
    if [[ "$skip_judge" != true ]]; then
        local judgment=""
        judgment=$(_eval_run_semantic_judge "${_eval_run_dir}/test-spec.md" "$_eval_run_dir") || true
        if [[ -n "$judgment" && -f "$judgment" ]]; then
            if ! _eval_build_report "$_eval_run_dir" "$judgment" >/dev/null; then
                _eval_reject "$EXIT_CONFIG_ERROR" "Could not build the evaluation report with semantic judgment"
                return "$EXIT_CONFIG_ERROR"
            fi
        fi
    fi
    local report_file="${_eval_run_dir}/report.json" accepted
    if ! accepted=$(jq -r '.accepted' "$report_file"); then
        _eval_reject "$EXIT_CONFIG_ERROR" "Evaluation report is unreadable: ${report_file}"
        return "$EXIT_CONFIG_ERROR"
    fi
    if ! "$py" "${LIB_DIR}/eval_runtime.py" finish "$_eval_run_dir"; then
        _eval_reject "$EXIT_CONFIG_ERROR" "Could not record the evaluation attempt"
        return "$EXIT_CONFIG_ERROR"
    fi
    _eval_complete=true
    if [[ "${JSON_OUTPUT:-false}" == true ]]; then
        cat "$report_file" >&3
    else
        _eval_print_summary "$report_file" "$test_spec" "$_eval_run_dir"
        if [[ "$accepted" == true ]]; then
            log_success "Accepted for the declared scenarios, criteria, and recorded gates."
        else
            log_error "Not accepted. $(_eval_verdict_line "$report_file")."
        fi
    fi
    if [[ -z "$_eval_task_filter" ]]; then
        if [[ "$accepted" != true && "$file_defects" == true ]]; then
            if ! "$py" "${LIB_DIR}/eval_runtime.py" guard --root "$PROJECT_ROOT" \
                --path "${PROJECT_ROOT}/specs/defects" --path "$DEFECTS_DIR"; then
                log_error "Defect directory failed validation; no defects filed"
                return "$EXIT_CONFIG_ERROR"
            fi
            _eval_file_defects "$report_file"
        fi
        [[ "${MP_ENABLED:-}" == true ]] && event_emit "eval.completed" "$FEATURE_NAME" "{\"accepted\":${accepted}}" || true
    fi
    [[ "$strict" == true && "$accepted" != true ]] && return "$EXIT_GATE_FAILURE"
    return 0
)
