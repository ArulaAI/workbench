#!/usr/bin/env bash
# ci.sh — speed ci: verify the whole project without calling a model.
#
#   speed ci                 Run evals, lint, typecheck, tests, e2e, custom checks,
#                            security scans, tool integrations and SonarQube
#   speed ci init            Write a GitHub Actions workflow that runs speed ci
#   speed ci --pr            Assemble a feature branch, run the checks, open a PR
#                            and post the result as a commit status
#   speed ci merge DIR...    Combine the reports of checks run as parallel jobs
#
# Exit codes: 0 every check passed, 2 a check failed, 3 the checks could not run,
# 4 a task branch conflicted while assembling the PR branch.

# Files that hold hashes or checksums, which look like secrets to the patterns.
CI_SECRETS_ALWAYS_EXCLUDE=(package-lock.json npm-shrinkwrap.json yarn.lock pnpm-lock.yaml
    poetry.lock Pipfile.lock uv.lock Cargo.lock go.sum composer.lock Gemfile.lock)

# At most this many secret findings are kept in the report (the count is always exact).
CI_SECRETS_KEEP=200

# Lines carrying this mark hold the generated workflow's throwaway database credentials.
CI_TEST_CREDENTIAL_MARK="speed-ci: test service credential"

# The counts line used in summaries, the PR body and the commit status.
_CI_COUNTS='"\(.summary.pass) passed, \(.summary.fail) failed, " + (if (.summary.warn // 0) > 0 then "\(.summary.warn) warning(s), " else "" end) + "\(.summary.skipped) skipped"'

# Replace every provider entry point so nothing reached from speed ci can call a model.
_ci_forbid_models() {
    local fn
    for fn in $(compgen -A function | grep -E '^_?provider_' || true); do
        eval "${fn}() { log_error 'speed ci never calls a model (${fn} was called)'; return ${EXIT_CONFIG_ERROR}; }"
    done
    PROVIDER_BIN=false
    export SPEED_CI=1
}

_ci_reject() {
    local code="$1" reason="$2"
    log_error "$reason"
    if [[ "${JSON_OUTPUT:-false}" == true ]]; then
        jq -n --arg reason "$reason" --argjson code "$code" \
            '{passed:false, error:$reason, exit_code:$code, steps:[]}' >&3
    fi
    return "$code"
}

# Append one step result. Args: name status summary duration [details_json]
_ci_record() {
    local summary
    summary=$(printf '%s' "$3" | tr '\n\r\t' '   ' | _ci_redact_stream)
    jq -nc --arg name "$1" --arg status "$2" --arg summary "$summary" --argjson duration "$4" \
        --argjson details "${5:-{\}}" \
        '{name:$name, status:$status, summary:$summary, duration_s:$duration} + $details' \
        >> "$_CI_STEPS_FILE"
    local mark
    case "$2" in
        pass) mark="${COLOR_SUCCESS}${SYM_CHECK}${RESET}" ;;
        fail) mark="${COLOR_ERROR}${SYM_CROSS}${RESET}" ;;
        warn) mark="${COLOR_WARN}!${RESET}" ;;
        *)    mark="${COLOR_DIM}-${RESET}" ;;
    esac
    printf "  %b %-${_CI_WIDTH:-10}s %s\n" "$mark" "$1" "$summary"
}

# A speed ci --pr step (merge, push, pr, status), printed in the same block as the checks.
_ci_pr_line() {
    local mark
    case "$1" in
        pass) mark="${COLOR_SUCCESS}${SYM_CHECK}${RESET}" ;;
        fail) mark="${COLOR_ERROR}${SYM_CROSS}${RESET}" ;;
        *)    mark="${COLOR_DIM}-${RESET}" ;;
    esac
    printf "  %b %-${_CI_WIDTH:-10}s %s\n" "$mark" "$2" "$3"
}

# The closing PASSED or FAILED line for a report.
_ci_result_line() {
    local report="$1" summary
    summary=$(jq -r "$_CI_COUNTS" "$report")
    if [[ "$(jq -r '.passed' "$report")" == true ]]; then
        echo -e "${COLOR_SUCCESS}${BOLD}PASSED${RESET}  ${summary}  (report: .speed/ci/report.json)"
    else
        echo -e "${COLOR_ERROR}${BOLD}FAILED${RESET}  ${summary}  (report: .speed/ci/report.json)"
    fi
}

# 0 when the check should run; otherwise records why it does not run.
_ci_selected() {
    local name="$1" step wanted=false
    if [[ ${#_CI_ONLY[@]} -gt 0 ]]; then
        for step in "${_CI_ONLY[@]}"; do
            [[ "$step" == "$name" ]] && wanted=true
        done
        if [[ "$wanted" != true ]]; then
            # Another job runs this check; speed ci merge takes its result from there.
            _ci_record "$name" skipped "Not selected with --only" 0 '{"selected":false}'
            return 1
        fi
    fi
    for step in "${_CI_SKIP[@]:-}"; do
        if [[ "$step" == "$name" ]]; then
            _ci_record "$name" skipped "skipped with --skip" 0
            return 1
        fi
    done
}

_ci_python() {
    "$(_context_python)" "${LIB_DIR}/ci_tools.py" "$@"
}

# The secret patterns, plus the exact values of the tokens this run holds, for redaction.
_ci_redaction_patterns() {
    _secrets_pattern_pairs
    local name value
    for name in "${_CI_SECRET_VARS[@]+"${_CI_SECRET_VARS[@]}"}" SPEED_REPO_TOKEN GITHUB_TOKEN GH_TOKEN; do
        value=$(printenv -- "$name" 2>/dev/null || true)
        [[ -n "$value" ]] && printf '=literal\t%s\n' "$value"
    done
    return 0
}

# Scanners print what they found; their logs keep it only with secret-pattern matches removed.
_ci_redact_log() {
    _ci_redaction_patterns | _ci_python redact "$1" 2>/dev/null || true
}

# Text on its way to the terminal or a report, with secret-pattern matches removed.
_ci_redact_stream() {
    if [[ -z "${_CI_PATTERNS_FILE:-}" || ! -s "${_CI_PATTERNS_FILE}" ]]; then
        cat
        return
    fi
    _ci_python redact-text "$_CI_PATTERNS_FILE" 2>/dev/null || echo "[output not shown: it could not be redacted]"
}

# Stop the running command and remove raw scanner output, then exit (Ctrl+C or kill).
_ci_on_signal() {
    if [[ -n "${_CI_CHILD:-}" ]]; then
        kill -TERM "$_CI_CHILD" 2>/dev/null || true
        wait "$_CI_CHILD" 2>/dev/null || true
    fi
    rm -f "${_CI_RAW:-}" "${_CI_RAW_ERR:-}" "${_CI_STEPS_FILE:-}" "${_CI_PATTERNS_FILE:-}"
    exit "$1"
}

# The check name matching $1 without regard to case, or nothing.
_ci_canonical() {
    local want step
    want=$(_ci_lower "$1")
    for step in "${_CI_AVAILABLE[@]}"; do
        if [[ "$(_ci_lower "$step")" == "$want" ]]; then
            echo "$step"
            return 0
        fi
    done
    return 1
}

# Run a project command in the project root with a time limit. The JSON output
# descriptor is closed so a command can never write into the report stream.
# Args: command stdout_file stderr_file. Returns the command's exit code (124 on timeout).
_ci_run_command() {
    local cmd="$1" out="$2" err="$3" rc=0 started=$SECONDS
    local -a limit=() hide=()
    [[ -n "${_TIMEOUT_CMD:-}" ]] && limit=("$_TIMEOUT_CMD" -k 10 "$_CI_TIMEOUT")
    # Project commands (gates, evals) never see the tokens meant for scanners.
    if [[ "${_CI_HIDE_SECRETS:-}" == true ]]; then
        local name
        for name in "${_CI_SECRET_VARS[@]+"${_CI_SECRET_VARS[@]}"}"; do
            hide+=(-u "$name")
        done
    fi
    _CI_TIMED_OUT=false
    # timeout puts the command in its own process group, where Ctrl+C does not reach it,
    # so the command runs in the background and an interrupt stops it explicitly.
    ( cd "$PROJECT_ROOT" && exec env "${hide[@]+"${hide[@]}"}" "${limit[@]+"${limit[@]}"}" bash -c "$cmd" ) \
        > "$out" 2> "$err" < /dev/null 3>&- &
    _CI_CHILD=$!
    trap '_ci_on_signal 130' INT
    trap '_ci_on_signal 143' TERM
    wait "$_CI_CHILD" || rc=$?
    _CI_CHILD=""
    # A timeout is a 124 (or a KILL, 137, for a command that ignores TERM) after the limit;
    # a command that exits 124 by itself before then is just a failure.
    if [[ -n "${limit[*]:-}" && ( "$rc" -eq 124 || "$rc" -eq 137 ) && $((SECONDS - started)) -ge "$_CI_TIMEOUT" ]]; then
        rc=124
        _CI_TIMED_OUT=true
    fi
    return "$rc"
}

# Run one quality-gate command. Prints "exit_code log_path".
_ci_exec() {
    local name="$1" cmd="$2"
    local log="${_CI_DIR}/logs/${name}.log"
    local rc=0 _CI_HIDE_SECRETS=true
    # A gate can delete .speed (git clean -fdx); the next command still gets its log.
    mkdir -p "${_CI_DIR}/logs"
    _ci_run_command "$cmd" "$log" "$log.err" || rc=$?
    mkdir -p "${_CI_DIR}/logs"
    cat "$log.err" >> "$log" 2>/dev/null; rm -f "$log.err"
    # Failure details are printed under the check's line, once the check is recorded.
    if [[ "$_CI_TIMED_OUT" == true ]]; then
        echo "    ${cmd} timed out after ${_CI_TIMEOUT}s" >> "${_CI_DIR}/logs/.details"
    elif [[ "$rc" -ne 0 ]]; then
        {
            echo "    ${cmd} exited ${rc}; last lines of ${log#"${PROJECT_ROOT}"/}:"
            tail -n 20 "$log" | sed 's/^/      /'
        } >> "${_CI_DIR}/logs/.details"
    fi
    echo "$rc $_CI_TIMED_OUT $log"
}

# lint, typecheck, test, e2e and any custom check come from the project's ## Quality Gates section.
_ci_gate_step() {
    local gate="$1" started=$SECONDS
    _ci_selected "$gate" || return 0
    local cmds
    cmds=$(gates_get_config "$gate" both)
    if [[ -z "$cmds" ]]; then
        if [[ "$gate" == test ]]; then
            _ci_record test fail "No test command in the Quality Gates section of ${AGENT_FILE:-AGENTS.md}" 0
            return 1
        fi
        _ci_record "$gate" skipped "No ${gate} command in the Quality Gates section" 0
        return 0
    fi
    local runs="[]" failed=0 count=0 cmd rc log
    while IFS= read -r cmd; do
        [[ -z "$cmd" ]] && continue
        count=$((count + 1))
        local timed_out
        read -r rc timed_out log < <(_ci_exec "${gate}-${count}" "$cmd")
        runs=$(jq -c --arg cmd "$cmd" --argjson rc "${rc:-1}" --arg log "${log#"${PROJECT_ROOT}"/}" --arg to "$timed_out" \
            '. + [{command:$cmd, exit_code:$rc, log:$log} + (if $to == "true" then {timed_out:true} else {} end)]' <<< "$runs")
        [[ "$rc" -ne 0 ]] && failed=$((failed + 1))
    done <<< "$cmds"
    local details
    details=$(jq -c '{commands:.}' <<< "$runs")
    if [[ "$failed" -gt 0 ]]; then
        _ci_record "$gate" fail "${failed} of ${count} command(s) failed" $((SECONDS - started)) "$details"
        _ci_redact_stream < "${_CI_DIR}/logs/.details" >&2 2>/dev/null || true
        rm -f "${_CI_DIR}/logs/.details"
        return 1
    fi
    _ci_record "$gate" pass "${count} command(s) passed" $((SECONDS - started)) "$details"
}

# Whole-repository secrets scan over tracked files. Matched text is never printed.
_ci_secrets_step() {
    local started=$SECONDS
    _ci_selected secrets || return 0
    # A committed .env is the most common leak, so unlike the task-diff scan this
    # one does not exclude .env files unless the project says so.
    local -a pathspec=(.)
    local pattern
    set -f
    # shellcheck disable=SC2206
    local -a excludes=(${TOML_SECURITY_SECRETS_EXCLUDE:-*.example tests/fixtures/**} "${CI_SECRETS_ALWAYS_EXCLUDE[@]}")
    set +f
    for pattern in "${excludes[@]}"; do
        if [[ "$pattern" == */* ]]; then
            pathspec+=(":(exclude,glob)${pattern}")
        else
            pathspec+=(":(exclude,glob)**/${pattern}")
        fi
    done
    # --text searches files git would call binary (a NUL byte or a .gitattributes
    # entry must not hide a key). -z keeps file names exact; -h on the second pass
    # leaves only line numbers, so the matched text is never read back.
    local -a grep_opts=(-c color.grep=never -c core.quotePath=false grep --no-color --text -E)
    # The generated workflow's database settings carry a mark; it is honoured in that file only.
    local workflow_file=".github/workflows/speed-ci.yml"
    local -a skip_mark=(--and --not -e "$CI_TEST_CREDENTIAL_MARK")
    if [[ -n "$(_git rev-parse --show-prefix 2>/dev/null)" ]] \
            || ! _git ls-files -- . "${pathspec[@]:1}" 2>/dev/null | grep -Fxq -- "$workflow_file"; then
        # A project in a subdirectory has no generated workflow there; an excluded one is not scanned.
        # (git 2.39 ls-files drops files under a dot directory when a literal path meets an exclude, so list "." instead.)
        workflow_file=""
    fi
    local -a workflow_spec=()
    if [[ -n "$workflow_file" ]]; then
        workflow_spec=(":(literal)${workflow_file}")
        pathspec+=(":(exclude,literal)${workflow_file}")
    fi
    local name regex rc file count line
    local listing="${_CI_DIR}/secrets-files.tmp" hits="${_CI_DIR}/secrets-hits.jsonl"
    : > "$hits"
    while IFS=$'\t' read -r name regex; do
        [[ -n "$name" && -n "$regex" ]] || continue
        rc=0
        # Output is "<file>\0<count>\n" per matching file.
        _git "${grep_opts[@]}" -z -c -e "$regex" -- "${pathspec[@]}" > "$listing" 2>/dev/null || rc=$?
        if [[ "$rc" -le 1 && -n "$workflow_file" ]]; then
            local wf_rc=0
            _git "${grep_opts[@]}" -z -c -e "$regex" "${skip_mark[@]}" -- "${workflow_spec[@]}" >> "$listing" 2>/dev/null \
                || wf_rc=$?
            [[ "$wf_rc" -gt 1 ]] && rc=$wf_rc
        fi
        if [[ "$rc" -gt 1 ]]; then
            rm -f "$listing" "$hits"
            _ci_record secrets fail "Secret pattern '${name}' could not be searched" $((SECONDS - started))
            return 1
        fi
        while IFS= read -r -d '' file && IFS= read -r count; do
            [[ -n "$file" ]] || continue
            local -a line_filter=()
            if [[ "$file" == "$workflow_file" ]]; then line_filter=("${skip_mark[@]}"); fi
            while IFS= read -r line; do
                jq -nc --arg name "$name" --arg file "$file" --argjson line "${line:-0}" \
                    '{pattern:$name, file:$file, line:$line}' >> "$hits"
            done < <(_git "${grep_opts[@]}" -h -n -e "$regex" "${line_filter[@]+"${line_filter[@]}"}" -- ":(literal)${file}" 2>/dev/null | cut -d: -f1 \
                     | grep -E '^[0-9]+$' || echo 0)
        done < "$listing"
    done < <(_secrets_pattern_pairs)
    rm -f "$listing"
    local total details
    total=$(wc -l < "$hits" | tr -d ' ')
    details=$(jq -sc --argjson keep "$CI_SECRETS_KEEP" '{total_findings:length, findings:.[:$keep]}' "$hits")
    jq -sc 'map(. + {severity:"high", title:("Secret: " + .pattern)})' "$hits" > "${_CI_DIR}/secrets-findings.json"
    if [[ "$total" -gt 0 ]]; then
        _ci_record secrets fail "${total} possible secret(s) in tracked files" $((SECONDS - started)) "$details"
        jq -r '"    \(.pattern) at \(.file):\(.line)"' "$hits" | head -n 50 >&2
        rm -f "$hits"
        return 1
    fi
    rm -f "$hits"
    _ci_record secrets pass "No secrets in tracked files" $((SECONDS - started))
}

# The JSON shape each parser understands. Anything else is reported, never read as zero findings.
_ci_scan_format_ok() {
    local kind="$1" raw="$2"
    if [[ "$kind" == sast ]]; then
        # Semgrep and Bandit both put findings in a top-level results array.
        jq -e 'type == "object" and (.results | type == "array")' "$raw" > /dev/null 2>&1
    else
        # npm audit 7+, pip-audit 2.x, pip-audit 1.x.
        jq -e '(type == "object" and ((.vulnerabilities | type == "object") or (.dependencies | type == "array")))
               or (type == "array" and all(.[]; type == "object" and has("name")))' "$raw" > /dev/null 2>&1
    fi
}

# SAST or SCA: run the configured scanner and fail on findings at or above the threshold.
_ci_scan_step() {
    local kind="$1" cmd="$2" parser="$3" started=$SECONDS
    _ci_selected "$kind" || return 0
    if [[ -z "$cmd" ]]; then
        _ci_record "$kind" skipped "No ${kind}_cmd in the [security] section of speed.toml" 0
        return 0
    fi
    # Raw scanner output can hold code snippets and secrets, so it is written outside
    # .speed/ci (which CI uploads) and deleted on every path; the findings are kept.
    local raw step_rc=0
    raw=$(mktemp "${TMPDIR:-/tmp}/speed-ci-${kind}.XXXXXX")
    _CI_RAW="$raw"
    _ci_scan_read "$kind" "$cmd" "$parser" "$started" "$raw" || step_rc=$?
    rm -f "$raw"
    _CI_RAW=""
    return "$step_rc"
}

_ci_scan_read() {
    local kind="$1" cmd="$2" parser="$3" started="$4" raw="$5"
    local normalized="${_CI_DIR}/${kind}-findings.json"
    local log="${_CI_DIR}/logs/${kind}.log" rc=0 elapsed
    rm -f "$normalized"
    _ci_run_command "$cmd" "$raw" "$log" || rc=$?
    _ci_redact_log "$log"
    elapsed() { echo $((SECONDS - started)); }
    if [[ "$_CI_TIMED_OUT" == true ]]; then
        _ci_record "$kind" fail "The scanner timed out after ${_CI_TIMEOUT}s" "$(elapsed)"
        return 1
    fi
    if ! jq -s -e 'length == 1 and (.[0] | type == "object" or type == "array")' "$raw" > /dev/null 2>&1; then
        _ci_record "$kind" fail "The scanner did not print exactly one JSON document (exit ${rc}); see ${log#"${PROJECT_ROOT}"/}" \
            "$(elapsed)"
        return 1
    fi
    # Fatal scanner errors: npm audit's {"error": ...}, or a Semgrep error with level "error".
    # Per-file warnings (Semgrep level "warn", Bandit parse errors) are kept as notes.
    if jq -e 'type == "object" and (.error != null or any((.errors // [])[]; (.level // "") == "error"))' \
            "$raw" > /dev/null 2>&1; then
        _ci_record "$kind" fail "The scanner reported an error (exit ${rc}): $(jq -r '[.error.summary? // .error.code? // .error?, (.errors // [])[]?.message?] | map(select(. != null and . != "")) | map(tostring) | .[0] // "see its output"' "$raw" 2>/dev/null | head -c 200)" "$(elapsed)"
        return 1
    fi
    if ! _ci_scan_format_ok "$kind" "$raw"; then
        _ci_record "$kind" fail "Unsupported scanner output (exit ${rc}); ${kind} supports $(
            [[ "$kind" == sast ]] && echo "Semgrep and Bandit JSON" || echo "npm audit 7+ and pip-audit JSON")" "$(elapsed)"
        return 1
    fi
    if ! "$parser" "$raw" "$normalized" > /dev/null 2>> "$log" || ! jq -e 'type == "array"' "$normalized" > /dev/null 2>&1; then
        _ci_record "$kind" fail "Could not read the scanner output; see ${log#"${PROJECT_ROOT}"/}" "$(elapsed)"
        return 1
    fi
    local total warnings
    total=$(jq 'length' "$normalized")
    warnings=$(jq 'if type == "object" then ((.errors // []) | length) else 0 end' "$raw")
    # Scanners exit non-zero when they find something; a non-zero exit with nothing
    # SPEED can read means the scan itself failed.
    if [[ "$rc" -ne 0 && "$total" -eq 0 ]]; then
        _ci_record "$kind" fail "The scanner exited ${rc} without reporting any finding" "$(elapsed)"
        return 1
    fi
    _ci_judge "$kind" "$normalized" "$total" "$started" "$warnings"
}

# Judge normalised findings against the threshold. In report mode they warn; in strict
# mode (the default) they fail. A severity SPEED does not recognise counts as blocking.
_ci_judge() {
    local kind="$1" normalized="$2" total="$3" started="$4" warnings="${5:-0}"
    local threshold="$_CI_THRESHOLD" blocking count details
    blocking=$(jq -c --arg threshold "$threshold" '
        {critical:5, high:4, medium:3, low:2, info:1} as $rank
        | [.[] | select(($rank[.severity // ""] // 5) >= $rank[$threshold])
               | {severity, title, file, line, package} | with_entries(select(.value != null))]' "$normalized")
    count=$(jq 'length' <<< "$blocking")
    details=$(jq -c --argjson total "$total" --argjson warnings "$warnings" --arg threshold "$threshold" \
        --arg mode "$_CI_MODE" \
        '{threshold:$threshold, security_mode:$mode, total_findings:$total, scanner_warnings:$warnings,
          blocking_findings:.[:50]}' <<< "$blocking")
    if [[ "$count" -gt 0 ]]; then
        if [[ "$_CI_MODE" == report ]]; then
            _ci_record "$kind" warn "${count} finding(s) at or above ${threshold}, not blocking in report mode (${total} in all)" \
                $((SECONDS - started)) "$details"
        else
            _ci_record "$kind" fail "${count} finding(s) at or above ${threshold} (${total} in all)" $((SECONDS - started)) "$details"
        fi
        jq -r '.[:20][] | "    [\(.severity)] \(.title) \(.file // .package // "")\(if .line then ":\(.line)" else "" end)"' \
            <<< "$blocking" | _ci_redact_stream >&2
        [[ "$_CI_MODE" == report ]]
        return
    fi
    _ci_record "$kind" pass "No findings at or above ${threshold} (${total} in all)" $((SECONDS - started)) "$details"
}

# Record a check that needs a secret the run does not have. Pull requests from forks and
# Dependabot get no repository secrets, so there the check is skipped rather than failed.
_ci_missing_secret() {
    local name="$1" secret="$2"
    if [[ "${SPEED_CI_SECRETS_UNAVAILABLE:-}" == true ]]; then
        _ci_record "$name" skipped "${secret} is not available to pull requests from forks or Dependabot" 0
        return 0
    fi
    _ci_record "$name" fail "${secret} is not set; ${name} needs it to run" 0
    return 1
}

# A plugged-in tool ([ci.tools.NAME]): Trivy, Gitleaks, Snyk, or any SARIF producer such as CodeQL.
_ci_tool_step() {
    local name="$1" started=$SECONDS
    _ci_selected "$name" || return 0
    local fmt cmd token
    fmt=$(jq -r --arg n "$name" '.tools[$n].format' <<< "$_CI_CONFIG")
    cmd=$(jq -r --arg n "$name" '.tools[$n].cmd' <<< "$_CI_CONFIG")
    token=$(jq -r --arg n "$name" '.tools[$n].token_env' <<< "$_CI_CONFIG")
    # token_env is checked to be a variable name when speed.toml is read.
    if [[ -n "$token" && -z "$(printenv -- "$token" 2>/dev/null)" ]]; then
        _ci_missing_secret "$name" "$token"
        return
    fi
    # Raw tool output can hold code snippets and the secrets a tool found, so it is written
    # outside .speed/ci (which CI uploads) and deleted; only the normalised findings are kept.
    local raw normalized="${_CI_DIR}/${name}-findings.json"
    local log="${_CI_DIR}/logs/${name}.log" rc=0 err
    raw=$(mktemp "${TMPDIR:-/tmp}/speed-ci-${name}.XXXXXX")
    _CI_RAW="$raw"
    rm -f "$normalized"
    if [[ "$fmt" == gitleaks ]]; then
        # Verbose gitleaks prints each secret to stderr, so its stderr is not kept at all.
        _CI_RAW_ERR=$(mktemp "${TMPDIR:-/tmp}/speed-ci-${name}-err.XXXXXX")
        _ci_run_command "$cmd" "$raw" "$_CI_RAW_ERR" || rc=$?
        echo "gitleaks exited ${rc}; its stderr ($(wc -l < "$_CI_RAW_ERR" | tr -d ' ') lines) is not kept" > "$log"
        rm -f "$_CI_RAW_ERR"
        _CI_RAW_ERR=""
    else
        _ci_run_command "$cmd" "$raw" "$log" || rc=$?
        _ci_redact_log "$log"
    fi
    if [[ "$_CI_TIMED_OUT" == true ]]; then
        rm -f "$raw"
        _CI_RAW=""
        _ci_record "$name" fail "${name} timed out after ${_CI_TIMEOUT}s" $((SECONDS - started))
        return 1
    fi
    if ! err=$(_ci_python parse "$fmt" "$raw" "$normalized" 2>&1); then
        rm -f "$raw"
        _CI_RAW=""
        _ci_record "$name" fail "Could not read the ${name} output (exit ${rc}): ${err}; see ${log#"${PROJECT_ROOT}"/}" \
            $((SECONDS - started))
        return 1
    fi
    rm -f "$raw"
    _CI_RAW=""
    local total
    total=$(jq 'length' "$normalized")
    if [[ "$rc" -ne 0 && "$total" -eq 0 ]]; then
        _ci_record "$name" fail "${name} exited ${rc} without reporting any finding; see ${log#"${PROJECT_ROOT}"/}" \
            $((SECONDS - started))
        return 1
    fi
    _ci_judge "$name" "$normalized" "$total" "$started"
}

# SonarQube or SonarCloud: run the scanner, wait for the analysis, read the quality gate.
_ci_sonar_step() {
    local started=$SECONDS
    _ci_selected sonarqube || return 0
    local host key org scanner blocking wait task
    host=$(jq -r '.sonarqube.host_url' <<< "$_CI_CONFIG")
    key=$(jq -r '.sonarqube.project_key' <<< "$_CI_CONFIG")
    org=$(jq -r '.sonarqube.organization' <<< "$_CI_CONFIG")
    scanner=$(jq -r '.sonarqube.scanner_cmd' <<< "$_CI_CONFIG")
    blocking=$(jq -r '.sonarqube.blocking' <<< "$_CI_CONFIG")
    wait=$(jq -r '.sonarqube.wait_timeout' <<< "$_CI_CONFIG")
    task="${PROJECT_ROOT}/$(jq -r '.sonarqube.report_task' <<< "$_CI_CONFIG")"
    if [[ -z "${SONAR_TOKEN:-}" ]]; then
        _ci_missing_secret sonarqube SONAR_TOKEN
        return
    fi
    # speed ci waits for the quality gate itself, so the scanner must not wait and exit 1 on a failed gate.
    local -a args=("-Dsonar.host.url=${host}" "-Dsonar.projectKey=${key}" "-Dsonar.qualitygate.wait=false")
    [[ -n "$org" ]] && args+=("-Dsonar.organization=${org}")
    local log="${_CI_DIR}/logs/sonarqube.log" rc=0 result
    rm -f "$task"
    _ci_run_command "${scanner} $(printf '%q ' "${args[@]}")" "$log" "${log}.err" || rc=$?
    cat "${log}.err" >> "$log" 2>/dev/null && rm -f "${log}.err"
    _ci_redact_log "$log"
    if [[ "$_CI_TIMED_OUT" == true ]]; then
        _ci_record sonarqube fail "The SonarQube scanner timed out after ${_CI_TIMEOUT}s" $((SECONDS - started))
        return 1
    fi
    if [[ "$rc" -ne 0 ]]; then
        _ci_record sonarqube fail "The SonarQube scanner exited ${rc}; see ${log#"${PROJECT_ROOT}"/}" $((SECONDS - started))
        return 1
    fi
    if ! result=$(_ci_python sonar-wait "$host" "$task" "$wait" 2>&1); then
        _ci_record sonarqube fail "Could not read the SonarQube result: ${result}" $((SECONDS - started))
        return 1
    fi
    local status details failed
    status=$(jq -r '.status' <<< "$result")
    details=$(jq -c '{dashboard_url, failed_conditions}' <<< "$result")
    # SonarQube's comparator names the failing side: LT 80 fails below 80, so the metric needs at least 80.
    failed=$(jq -r '[.failed_conditions[] | "\(.metric) \(.actual) (needs " +
        ({"LT": "at least", "GT": "at most", "EQ": "not", "NE": "exactly"}[.comparator] // .comparator) +
        " \(.threshold))"] | join(", ")' <<< "$result")
    case "$status" in
        OK)
            _ci_record sonarqube pass "Quality gate passed" $((SECONDS - started)) "$details" ;;
        WARN)
            _ci_record sonarqube warn "Quality gate passed with warnings" $((SECONDS - started)) "$details" ;;
        ERROR)
            if [[ "$blocking" == true ]]; then
                _ci_record sonarqube fail "Quality gate failed: ${failed:-see the dashboard}" $((SECONDS - started)) "$details"
                return 1
            fi
            _ci_record sonarqube warn "Quality gate failed, not blocking: ${failed:-see the dashboard}" \
                $((SECONDS - started)) "$details" ;;
        *)
            _ci_record sonarqube fail "SonarQube returned no quality gate result (${status})" $((SECONDS - started)) "$details"
            return 1 ;;
    esac
}

# One feature's task statuses, whether a test spec is configured, and where its
# evaluation summary goes: "<statuses> <configured> <summary_path>".
_ci_feature_state() (
    feature_activate "$1" > /dev/null 2>&1 || exit 1
    # In a fresh multi-player checkout the local lock directory does not exist yet.
    mkdir -p "$(dirname "$SPEED_LOCK")" 2>/dev/null || true
    local statuses="" file
    if compgen -G "${TASKS_DIR}/*.json" > /dev/null; then
        for file in "${TASKS_DIR}"/*.json; do
            if ! jq -e 'type == "object" and (.status | type == "string")' "$file" > /dev/null 2>&1; then
                echo "invalid false -"
                exit 0
            fi
        done
        statuses=$(jq -r '.status' "${TASKS_DIR}"/*.json | sort -u | tr '\n' ',')
    fi
    local configured=false
    [[ -s "${FEATURE_DIR}/test_spec_path" ]] && configured=true
    echo "${statuses:-none} ${configured} ${FEATURE_DIR#"${PROJECT_ROOT}"/}/eval/summary.md"
)

# Run speed eval for every feature (or the one given with --feature).
_ci_eval_step() {
    local started=$SECONDS
    _ci_selected eval || return 0
    local -a features=()
    if [[ -n "${GLOBAL_FEATURE:-}" ]]; then
        features=("$GLOBAL_FEATURE")
    else
        local name
        while IFS= read -r name; do
            [[ -n "$name" ]] && features+=("$name")
        done < <(feature_list)
    fi
    if [[ ${#features[@]} -eq 0 ]]; then
        _ci_record eval skipped "No SPEED features in this checkout" 0
        return 0
    fi
    local results="[]" feature out rc status reason passed=0 failed=0 statuses configured summary
    local log="${_CI_DIR}/logs/eval.log"
    for feature in "${features[@]}"; do
        reason=""
        read -r statuses configured summary < <(_ci_feature_state "$feature" || echo "missing false -")
        if [[ "$statuses" == missing ]]; then
            status=fail; reason="Feature ${feature} could not be loaded"
        elif [[ "$statuses" == invalid ]]; then
            status=fail; reason="A task file of ${feature} is not valid JSON with a status"
        elif [[ -n "$(tr ',' '\n' <<< "$statuses" | grep -v '^$' | grep -vxE 'pending|running|done|failed|blocked' || true)" ]]; then
            status=fail; reason="A task of ${feature} has an unknown status (${statuses%,})"
        elif [[ "$statuses" == none ]]; then
            status=skipped; reason="No tasks yet"
        elif [[ ",${statuses}" == *",failed,"* || ",${statuses}" == *",blocked,"* ]]; then
            status=fail; reason="Some tasks are failed or blocked (${statuses%,})"
        elif [[ "$statuses" != "done," ]]; then
            status=skipped; reason="Work in progress (${statuses%,})"
        else
            rc=0
            # Evals run the project's tests: no scanner tokens, no stdin, and the CI time limit.
            out=$(for name in "${_CI_SECRET_VARS[@]+"${_CI_SECRET_VARS[@]}"}"; do unset "$name"; done
                  SPEED_CI_COMMAND_TIMEOUT="$_CI_TIMEOUT" JSON_OUTPUT=true GLOBAL_FEATURE="$feature" \
                      cmd_eval < /dev/null 2>> "$log") || rc=$?
            reason=$(jq -r '.error // empty' <<< "$out" 2>/dev/null || true)
            # Keep each evaluated feature's summary with the CI report, which outlives a --pr worktree.
            mkdir -p "${_CI_DIR}/eval"
            cp "${PROJECT_ROOT}/${summary}" "${_CI_DIR}/eval/${feature}-summary.md" 2>/dev/null || true
            if [[ "$rc" -eq 0 ]]; then
                status=pass
            elif [[ "$rc" -eq "$EXIT_CONFIG_ERROR" && "$reason" == "No test spec found"* && "$configured" != true ]]; then
                status=skipped; reason="No test spec for this feature"
            elif [[ "$reason" == "No test spec found"* ]]; then
                reason="Its test spec is missing; create specs/tests/${feature}.md or fix test_spec_path"
            else
                status=fail
                if [[ -z "$reason" ]]; then
                    if [[ -f "${_CI_DIR}/eval/${feature}-summary.md" ]]; then
                        reason="Not accepted; see .speed/ci/eval/${feature}-summary.md"
                    else
                        reason="Not accepted"
                    fi
                fi
            fi
        fi
        case "$status" in
            pass) passed=$((passed + 1)) ;;
            fail) failed=$((failed + 1)) ;;
        esac
        results=$(jq -c --arg f "$feature" --arg s "$status" --arg r "$reason" \
            '. + [{feature:$f, status:$s} + (if $r == "" then {} else {reason:$r} end)]' <<< "$results")
    done
    local details
    details=$(jq -c '{features:.}' <<< "$results")
    if [[ "$failed" -gt 0 ]]; then
        _ci_record eval fail "${failed} feature(s) failed, ${passed} accepted" $((SECONDS - started)) "$details"
        jq -r '.[] | select(.status == "fail") | "    \(.feature): \(.reason)"' <<< "$results" | _ci_redact_stream >&2
        return 1
    fi
    if [[ "$passed" -eq 0 ]]; then
        _ci_record eval skipped "No feature is ready to evaluate" $((SECONDS - started)) "$details"
        return 0
    fi
    _ci_record eval pass "${passed} feature(s) accepted" $((SECONDS - started)) "$details"
}

# Fail when the checks changed tracked files: the commit being reported on is then
# not the tree that was checked (for example a formatter run as lint).
_ci_clean_tree_step() {
    local changed
    changed=$(_git status --porcelain --untracked-files=no -- . ':(exclude).speed' 2>/dev/null | cut -c4- | head -n 20)
    if [[ -n "$changed" ]]; then
        _ci_record clean-tree fail "The checks changed tracked files: $(tr '\n' ' ' <<< "$changed")" 0
        return 1
    fi
    _ci_record clean-tree pass "The checks left tracked files unchanged" 0
}

# Only one speed ci run may use .speed/ci at a time.
_ci_lock() {
    local lock="${_CI_DIR}/.lock"
    if ! mkdir -p "$_CI_DIR" 2>/dev/null || [[ ! -w "$_CI_DIR" ]]; then
        return 2
    fi
    if ! mkdir "$lock" 2>/dev/null; then
        local holder
        holder=$(cat "${lock}/pid" 2>/dev/null || echo "")
        if [[ -z "$holder" ]]; then
            # The owner writes its pid right after creating the lock; give it a moment.
            sleep 1
            holder=$(cat "${lock}/pid" 2>/dev/null || echo "")
        fi
        if [[ -n "$holder" ]] && kill -0 "$holder" 2>/dev/null; then
            return 1
        fi
        # Only one run can move the stale lock away, so two runs never both take it over.
        mv "$lock" "${lock}.stale.$$" 2>/dev/null || return 1
        rm -rf "${lock}.stale.$$"
        mkdir "$lock" 2>/dev/null || return 1
    fi
    echo "$BASHPID" > "${lock}/pid"
}

_ci_unlock() {
    rm -rf "${_CI_DIR}/.lock"
}

# Run every check and write .speed/ci/report.json. Returns 0, EXIT_GATE_FAILURE,
# or EXIT_CONFIG_ERROR when another run holds the lock.
_ci_run_checks() {
    _CI_DIR="${STATE_DIR}/ci"
    local lock_rc=0
    _ci_lock || lock_rc=$?
    if [[ "$lock_rc" -eq 2 ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Cannot write ${_CI_DIR#"${PROJECT_ROOT}"/}"
        return
    elif [[ "$lock_rc" -ne 0 ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Another speed ci is running in this project"
        return
    fi
    trap '_ci_unlock; rm -f "${_CI_STEPS_FILE:-}" "${_CI_PATTERNS_FILE:-}"' EXIT
    trap '_ci_on_signal 130' INT
    trap '_ci_on_signal 143' TERM
    rm -rf "${_CI_DIR}/logs" "${_CI_DIR}/eval"
    rm -f "${_CI_DIR}"/*-findings.json "${_CI_DIR}"/*-output.json
    mkdir -p "${_CI_DIR}/logs"
    # Kept outside .speed, so a gate that deletes .speed cannot lose the results so far.
    _CI_STEPS_FILE=$(mktemp "${TMPDIR:-/tmp}/speed-ci-steps.XXXXXX")
    _CI_PATTERNS_FILE=$(mktemp "${TMPDIR:-/tmp}/speed-ci-patterns.XXXXXX")
    _ci_redaction_patterns > "$_CI_PATTERNS_FILE"
    local started_at
    started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    # speed ci --pr prints the header itself, above its merge step.
    [[ "${SPEED_CI_PR_MODE:-}" == 1 ]] || echo -e "${BOLD}SPEED CI${RESET}  (no model calls)"
    # Evals run first, on the tree exactly as checked out: later commands can leave
    # files behind, and an evaluation must describe a clean tree.
    _ci_eval_step || true
    local gate tool
    for gate in lint typecheck test e2e "${_CI_CUSTOM[@]+"${_CI_CUSTOM[@]}"}"; do
        _ci_gate_step "$gate" || true
    done
    _ci_secrets_step || true
    _ci_scan_step sast "${TOML_SECURITY_SAST_CMD:-}" security_sast_parse || true
    _ci_scan_step sca "${TOML_SECURITY_SCA_CMD:-}" security_sca_parse || true
    for tool in "${_CI_TOOLS[@]+"${_CI_TOOLS[@]}"}"; do
        _ci_tool_step "$tool" || true
    done
    if [[ "$(jq -r '.sonarqube != null' <<< "$_CI_CONFIG")" == true ]]; then
        _ci_sonar_step || true
    fi
    if [[ "${SPEED_CI_REQUIRE_CLEAN:-}" == 1 ]]; then
        _ci_clean_tree_step || true
    fi
    local commit branch
    commit=$(_git rev-parse HEAD 2>/dev/null || echo "")
    branch=$(_git symbolic-ref -q --short HEAD 2>/dev/null || echo "")
    if ! mkdir -p "$_CI_DIR" 2>/dev/null; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Cannot write ${_CI_DIR#"${PROJECT_ROOT}"/}/report.json"
        return
    fi
    jq -s --arg started "$started_at" --arg finished "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg commit "$commit" --arg branch "$branch" \
        '{passed: (map(select(.status == "fail")) | length == 0),
          commit:$commit, branch:$branch, started_at:$started, finished_at:$finished,
          summary:{pass: map(select(.status == "pass")) | length,
                   fail: map(select(.status == "fail")) | length,
                   warn: map(select(.status == "warn")) | length,
                   skipped: map(select(.status == "skipped")) | length},
          steps:.}' "$_CI_STEPS_FILE" > "${_CI_DIR}/report.json.tmp" 2>/dev/null \
        && mv "${_CI_DIR}/report.json.tmp" "${_CI_DIR}/report.json" || {
            _ci_reject "$EXIT_CONFIG_ERROR" "Cannot write ${_CI_DIR#"${PROJECT_ROOT}"/}/report.json"
            return
        }
    rm -f "$_CI_STEPS_FILE"
    # Last line of defence for secrets: everything speed ci wrote is redacted before the
    # SARIF, JUnit and summary files are derived from it.
    _ci_python redact-tree "$_CI_DIR" < "$_CI_PATTERNS_FILE" 2>/dev/null || log_warn "Could not redact .speed/ci"
    # Reports for other tools: SARIF for GitHub's Security tab, JUnit for test dashboards,
    # and a Markdown summary on the GitHub Actions run page.
    _ci_python sarif "$_CI_DIR" "${_CI_DIR}/speed-ci.sarif" 2>/dev/null || log_warn "Could not write the SARIF report"
    _ci_python junit "${_CI_DIR}/report.json" "${_CI_DIR}/junit.xml" 2>/dev/null || log_warn "Could not write the JUnit report"
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        _ci_python summary "${_CI_DIR}/report.json" >> "$GITHUB_STEP_SUMMARY" 2>/dev/null || true
    fi
    # Under speed ci --pr the result line comes after the push, PR and status steps.
    [[ "${SPEED_CI_PR_MODE:-}" == 1 ]] || _ci_result_line "${_CI_DIR}/report.json"
    if [[ "$(jq -r '.passed' "${_CI_DIR}/report.json")" == true ]]; then
        return 0
    fi
    return "$EXIT_GATE_FAILURE"
}

# ── speed ci init ──────────────────────────────────────────────────────────────

# Setup steps for the project's own toolchain, detected from its files.
_ci_project_setup() {
    local root="$PROJECT_ROOT"
    if [[ -f "${root}/package.json" ]]; then
        if [[ -f "${root}/pnpm-lock.yaml" ]]; then
            printf '      - run: npm install -g pnpm && pnpm install --frozen-lockfile\n'
        elif [[ -f "${root}/yarn.lock" ]]; then
            printf '      - run: yarn install --frozen-lockfile\n'
        elif [[ -f "${root}/package-lock.json" ]]; then
            printf '      - run: npm ci\n'
        else
            # Without a lockfile, do not create one: an untracked file would make the tree dirty.
            printf '      - run: npm install --no-package-lock\n'
        fi
    fi
    if [[ -f "${root}/requirements.txt" || -f "${root}/pyproject.toml" ]]; then
        local install="python -m pip install -q --upgrade pip"
        [[ -f "${root}/requirements.txt" ]] && install+=" && pip install -q -r requirements.txt"
        [[ -f "${root}/requirements-dev.txt" ]] && install+=" && pip install -q -r requirements-dev.txt"
        [[ ! -f "${root}/requirements.txt" ]] && install+=" && pip install -q ."
        printf '      - run: %s\n' "$install"
    fi
    if [[ -f "${root}/go.mod" ]]; then
        printf '      - uses: actions/setup-go@v5\n        with:\n          go-version-file: go.mod\n'
        printf '      - run: go mod download\n'
    fi
}

# OWNER/REPO from a GitHub remote URL (https, ssh or git@ form).
_ci_github_repo() {
    local url="${1%.git}"
    if [[ "$url" =~ github\.com[:/]+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/?$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi
    return 1
}

# The SPEED ref the workflow installs: the current branch's upstream, else the
# remote's default branch. Both exist on the remote, unlike a local-only branch.
_ci_speed_ref() {
    local upstream
    if upstream=$(git -C "$SPEED_DIR" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null); then
        echo "${upstream#*/}"
        return 0
    fi
    if upstream=$(git -C "$SPEED_DIR" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null); then
        echo "${upstream#*/}"
        return 0
    fi
    echo main
}

_ci_init() {
    _ci_settings || return
    local force=false repo="" ref="" name
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --force) force=true; shift ;;
            --speed-repo|--speed-ref)
                [[ $# -ge 2 && "$2" != --* ]] || { _ci_reject "$EXIT_CONFIG_ERROR" "$1 requires a value"; return; }
                if [[ "$1" == --speed-repo ]]; then repo="$2"; else ref="$2"; fi
                shift 2 ;;
            *) _ci_reject "$EXIT_CONFIG_ERROR" "Unknown ci init option: $1"; return ;;
        esac
    done
    # GitHub only reads workflows from the repository root.
    local toplevel
    toplevel=$(_git rev-parse --show-toplevel 2>/dev/null || echo "")
    if [[ -z "$toplevel" ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "speed ci init must run inside a git repository"
        return
    fi
    if [[ "$(cd "$toplevel" && pwd -P)" != "$(cd "$PROJECT_ROOT" && pwd -P)" ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "speed ci init must run at the repository root (${toplevel}); GitHub does not read workflows from subdirectories"
        return
    fi
    local target="${PROJECT_ROOT}/.github/workflows/speed-ci.yml"
    if [[ -e "$target" && "$force" != true ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" ".github/workflows/speed-ci.yml already exists; pass --force to replace it"
        return
    fi
    if [[ -z "$repo" ]] && ! repo=$(_ci_github_repo "$(git -C "$SPEED_DIR" config --get remote.origin.url 2>/dev/null)"); then
        _ci_reject "$EXIT_CONFIG_ERROR" "Cannot tell which GitHub repository SPEED comes from; pass --speed-repo OWNER/REPO"
        return
    fi
    if [[ ! "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Invalid --speed-repo: ${repo} (expected OWNER/REPO)"
        return
    fi
    local defaulted=false
    if [[ -z "$ref" ]]; then
        ref=$(_ci_speed_ref)
        defaulted=true
    fi
    if [[ ! "$ref" =~ ^[A-Za-z0-9_./-]+$ ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Invalid --speed-ref: ${ref}"
        return
    fi
    local codecov_check
    codecov_check=$(jq -r '.codecov.check // empty' <<< "$_CI_CONFIG")
    if [[ -n "$codecov_check" && "$(jq -r '.parallel' <<< "$_CI_CONFIG")" == true \
            && " ${_CI_AVAILABLE[*]} " != *" ${codecov_check} "* ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "[ci.codecov] check '${codecov_check}' is not one of this project's checks (${_CI_AVAILABLE[*]})"
        return
    fi
    local main_branch setup
    main_branch=$(git_main_branch)
    setup=$(_ci_project_setup)
    if ! mkdir -p "$(dirname "$target")" 2>/dev/null; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Cannot create .github/workflows in ${PROJECT_ROOT}"
        return
    fi
    local settings checks
    checks=$(printf '%s\n' "${_CI_AVAILABLE[@]}" | jq -R . | jq -sc .)
    settings=$(jq -n --arg main "$main_branch" --arg repo "$repo" --arg ref "$ref" --arg setup "$setup" \
        --argjson config "$_CI_CONFIG" --argjson checks "$checks" \
        '{main_branch:$main, speed_repository:$repo, speed_ref:$ref, project_setup:$setup, config:$config, checks:$checks}')
    if ! _ci_python workflow <<< "$settings" > "${target}.tmp" 2>/dev/null || ! mv "${target}.tmp" "$target"; then
        rm -f "${target}.tmp"
        _ci_reject "$EXIT_CONFIG_ERROR" "Could not write .github/workflows/speed-ci.yml"
        return
    fi
    log_success "Wrote .github/workflows/speed-ci.yml (SPEED ${repo}@${ref}, runs on pull requests and pushes to ${main_branch})"
    if [[ "$defaulted" == true ]] \
            && ! git -C "$SPEED_DIR" cat-file -e "origin/${ref}:lib/cmd/ci.sh" 2>/dev/null; then
        log_warn "SPEED ${ref} on the remote may not include speed ci yet; pass --speed-ref with a branch or tag that does"
    fi
    if [[ -z "$setup" ]]; then
        log_warn "No package.json, requirements.txt, pyproject.toml or go.mod found; add the project's setup steps to the workflow"
    fi
    local -a secrets=()
    [[ "$(jq -r '.sonarqube != null' <<< "$_CI_CONFIG")" == true ]] && secrets+=(SONAR_TOKEN)
    [[ "$(jq -r '.codecov != null' <<< "$_CI_CONFIG")" == true ]] && secrets+=(CODECOV_TOKEN)
    while IFS= read -r name; do
        [[ -n "$name" ]] && secrets+=("$name")
    done < <(jq -r '[.tools[].token_env | select(. != "")] | unique[]' <<< "$_CI_CONFIG")
    if [[ ${#secrets[@]} -gt 0 ]]; then
        log_info "Add these repository secrets on GitHub: $(printf '%s\n' "${secrets[@]}" | awk '!seen[$0]++' | tr '\n' ' ')"
    fi
    if [[ "$(jq -r '.parallel' <<< "$_CI_CONFIG")" == true ]]; then
        log_info "Checks run as ${#_CI_AVAILABLE[@]} parallel jobs; require the speed-ci status check, which combines them"
    fi
    # The workflow installs Trivy, Gitleaks, Snyk and sonar-scanner for their default commands only.
    local unmanaged
    unmanaged=$(jq -r '[(.tools | to_entries[] | select((.value.default_cmd | not) or (.key | IN("trivy","gitleaks","snyk") | not)) | .key),
                         (if .sonarqube != null and .sonarqube.scanner_cmd != "sonar-scanner" then "sonarqube" else empty end)]
                        | join(", ")' <<< "$_CI_CONFIG")
    if [[ -n "$unmanaged" ]]; then
        log_warn "Add an install step for ${unmanaged} to the workflow's project setup; it runs a custom command"
    fi
    log_info "Commit the file to turn it on. For a private SPEED repository, add a SPEED_REPO_TOKEN secret that can read it."
    if [[ "${JSON_OUTPUT:-false}" == true ]]; then
        jq -n --arg path ".github/workflows/speed-ci.yml" --arg repo "$repo" --arg ref "$ref" \
            --arg branch "$main_branch" --arg unmanaged "$unmanaged" \
            --argjson secrets "$(printf '%s\n' "${secrets[@]+"${secrets[@]}"}" | awk 'NF && !seen[$0]++' | jq -R . | jq -sc .)" \
            '{written:$path, speed_repository:$repo, speed_ref:$ref, main_branch:$branch, secrets_to_add:$secrets,
              tools_to_install:($unmanaged | split(", ") | map(select(. != "")))}' >&3
    fi
}

# ── speed ci --pr ──────────────────────────────────────────────────────────────

_ci_pr_body() {
    local feature="$1" tasks_json="$2" report="$3"
    {
        echo "## SPEED feature: ${feature}"
        echo ""
        echo "### Tasks"
        jq -r '.[] | "- \(.id): \(.title) (`\(.branch)`)"' <<< "$tasks_json"
        echo ""
        echo "### speed ci"
        echo ""
        if [[ "$(jq -r '.passed' "$report")" == true ]]; then
            echo "**Passed**: $(jq -r "$_CI_COUNTS" "$report")"
        else
            echo "**Failed**: $(jq -r "$_CI_COUNTS" "$report")"
        fi
        if [[ "$(jq -r '.summary.warn // 0' "$report")" -gt 0 ]]; then
            echo ""
            echo "Warnings do not fail the check (security_mode = \"report\", or a non-blocking SonarQube gate); review them before merging."
        fi
        echo ""
        echo "| Check | Result | Detail |"
        echo "|---|---|---|"
        jq -r '.steps[] | "| \(.name) | \(.status) | \(.summary | gsub("\\|"; "/"))\(if (.dashboard_url // "") != "" then " ([dashboard](\(.dashboard_url | gsub("\\|"; "%7C") | gsub(" "; "%20"))))" else "" end) |"' "$report"
        echo ""
        echo "Checked at commit \`$(jq -r '.commit' "$report")\`. Opened by \`speed ci --pr\`; the checks made no model calls."
    }
}

# Commits on a tip that are not on the base or a task branch and are not merges.
# speed ci --pr only ever adds merge commits, so anything here is someone's work.
_ci_foreign_commits() {
    local tip="$1" base="$2"
    shift 2
    local -a exclude=("^${base}")
    local branch
    for branch in "$@"; do
        exclude+=("^${branch}")
    done
    # Only merges speed ci made itself ("Merge <branch> (task N)") are not someone's work.
    _git log --format='%H%x09%P%x09%s' "$tip" "${exclude[@]}" -- 2>/dev/null \
        | awk -F'\t' '{ n = split($2, parents, " "); if (!(n > 1 && $3 ~ /^Merge .* \(task [^)]+\)$/)) print $1 }' \
        | head -n 5 || true
}

_ci_lower() {
    tr '[:upper:]' '[:lower:]' <<< "$1"
}

# Put the feature's SPEED state, as --pr checked it, into the assembly worktree. It
# replaces any committed copy from the base, which can be behind the local state.
_ci_copy_feature_state() {
    local root="$1" dir rel name
    for dir in "$FEATURE_DIR" "$TASKS_DIR"; do
        rel="${dir#"${PROJECT_ROOT}"/}"
        [[ "$rel" == "$dir" ]] && continue
        rm -rf "${root:?}/${rel}"
        mkdir -p "$(dirname "${root}/${rel}")"
        cp -R "$dir" "${root}/${rel}"
        rm -rf "${root}/${rel}/eval" "${root}/${rel}/logs" "${root}/${rel}/speed.lock"
        # Absolute spec paths would point back into the user's checkout.
        for name in spec_path test_spec_path; do
            if [[ -f "${root}/${rel}/${name}" ]]; then
                sed -i.bak "s|^${PROJECT_ROOT}/|${root}/|" "${root}/${rel}/${name}" && rm -f "${root}/${rel}/${name}.bak"
            fi
        done
    done
}

# Link dependencies such as node_modules into the worktree, and write a git excludes
# file that hides the links, so evals do not see them as uncommitted files.
_ci_link_dependencies() {
    local root="$1" top="$2" excludes="$3" link global
    git_setup_worktree_deps "$root"
    global=$(git config --path --get core.excludesFile 2>/dev/null || echo "${XDG_CONFIG_HOME:-$HOME/.config}/git/ignore")
    { [[ -f "$global" ]] && cat "$global"; echo; } > "$excludes"
    while IFS= read -r -d '' link; do
        echo "/${link#"${top}"/}" >> "$excludes"
    done < <(find "$top" -path "${top}/.git" -prune -o -type l -lname "${PROJECT_ROOT}/*" -print0 2>/dev/null)
}

# Threshold and command timeout, read from the project's speed.toml.
_ci_settings() {
    if [[ "${SPEED_TOML_INVALID:-}" == 1 ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "speed.toml could not be parsed; fix it so CI does not run on default settings"
        return
    fi
    local threshold
    threshold=$(tr '[:upper:]' '[:lower:]' <<< "${TOML_SECURITY_SEVERITY_THRESHOLD:-high}")
    [[ "$threshold" == moderate ]] && threshold=medium
    case "$threshold" in
        critical|high|medium|low|info) _CI_THRESHOLD="$threshold" ;;
        *) _ci_reject "$EXIT_CONFIG_ERROR" "Invalid [security] severity_threshold: ${TOML_SECURITY_SEVERITY_THRESHOLD} (use critical, high, medium, low or info)"; return ;;
    esac
    _CI_TIMEOUT="${TOML_CI_COMMAND_TIMEOUT-1800}"
    if [[ ! "$_CI_TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Invalid [ci] command_timeout: ${_CI_TIMEOUT} (seconds)"
        return
    fi
    if ! _CI_CONFIG=$(_ci_python config "${PROJECT_ROOT}/speed.toml" 2>&1); then
        _ci_reject "$EXIT_CONFIG_ERROR" "Invalid speed.toml: ${_CI_CONFIG}"
        return
    fi
    _CI_MODE=$(jq -r '.security_mode' <<< "$_CI_CONFIG")
    # Tokens meant for scanners; project commands run without them.
    _CI_SECRET_VARS=()
    while IFS= read -r name; do
        if [[ -n "$name" ]]; then _CI_SECRET_VARS+=("$name"); fi
    done < <(jq -r '([.tools[].token_env] + (if .sonarqube != null then ["SONAR_TOKEN"] else [] end))
                    | map(select(. != "")) | unique[]' <<< "$_CI_CONFIG")
    local name gates problems
    if ! gates=$(_ci_python gates "${AGENT_FILE_PATH:-}" "$(jq -c '.ignore_gates' <<< "$_CI_CONFIG")" \
            "$(jq -c '.tools | keys' <<< "$_CI_CONFIG")" 2>&1); then
        _ci_reject "$EXIT_CONFIG_ERROR" "Could not read the Quality Gates: ${gates}"
        return
    fi
    problems=$(jq -r '.problems | join("; ")' <<< "$gates")
    if [[ -n "$problems" ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Quality Gates names that cannot run as checks: ${problems} (rename them, or list them in [ci] ignore_gates)"
        return
    fi
    _CI_CUSTOM=()
    while IFS= read -r name; do
        [[ -n "$name" ]] && _CI_CUSTOM+=("$name")
    done < <(jq -r '.gates[]' <<< "$gates")
    _CI_TOOLS=()
    while IFS= read -r name; do
        [[ -n "$name" ]] && _CI_TOOLS+=("$name")
    done < <(jq -r '.tools | keys_unsorted[]' <<< "$_CI_CONFIG")
    _CI_AVAILABLE=(eval lint typecheck test e2e "${_CI_CUSTOM[@]+"${_CI_CUSTOM[@]}"}" secrets sast sca
                   "${_CI_TOOLS[@]+"${_CI_TOOLS[@]}"}")
    if [[ "$(jq -r '.sonarqube != null' <<< "$_CI_CONFIG")" == true ]]; then
        _CI_AVAILABLE+=(sonarqube)
    fi
    _CI_WIDTH=10
    for name in "${_CI_AVAILABLE[@]}" clean-tree; do
        if [[ ${#name} -ge $_CI_WIDTH ]]; then
            _CI_WIDTH=$((${#name} + 1))
        fi
    done
    return 0
}

# Names given to --skip or --only must be checks this project has; they match without case.
# Prints the matching check names, one per line.
_ci_check_names() {
    local option="$1" step found
    shift
    for step in "$@"; do
        if ! found=$(_ci_canonical "$step"); then
            _ci_reject "$EXIT_CONFIG_ERROR" "Unknown check for ${option}: ${step} (checks: ${_CI_AVAILABLE[*]})" >&2
            return
        fi
        echo "$found"
    done
}

# Run the checks inside the assembly worktree, with every project path and setting
# taken from there, as a fresh CI checkout would.
_ci_check_worktree() (
    local root="$1" excludes="$2"
    # The parent reports any refusal once; this subshell only logs it.
    JSON_OUTPUT=false
    unset $(compgen -v TOML_ || true) SPEED_TOML_INVALID
    [[ -z "${_SPEED_USER_AGENT_FILE:-}" ]] && unset SPEED_AGENT_FILE
    export SPEED_PROJECT_ROOT="$root"
    # shellcheck source=/dev/null
    source "${LIB_DIR}/config.sh"
    MP_ENABLED=false
    mp_is_enabled && MP_ENABLED=true
    _ci_settings || exit
    export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.excludesFile GIT_CONFIG_VALUE_0="$excludes"
    SPEED_CI_REQUIRE_CLEAN=1 SPEED_CI_PR_MODE=1 _ci_run_checks
)

_ci_cleanup_worktree() {
    rm -f "${_CI_EXCLUDES:-}"
    [[ -n "${_CI_WORKTREE:-}" ]] || return 0
    _git worktree remove --force "$_CI_WORKTREE" > /dev/null 2>&1 || rm -rf "$_CI_WORKTREE"
    _git worktree prune > /dev/null 2>&1 || true
}

_ci_pr() {
    local draft=false dry_run=false force=false base="" pr_branch="" remote="origin" repo=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --draft) draft=true; shift ;;
            --dry-run) dry_run=true; shift ;;
            --force) force=true; shift ;;
            --base|--branch|--remote|--repo)
                [[ $# -ge 2 && "$2" != --* ]] || { _ci_reject "$EXIT_CONFIG_ERROR" "$1 requires a value"; return; }
                case "$1" in
                    --base) base="$2" ;;
                    --branch) pr_branch="$2" ;;
                    --remote) remote="$2" ;;
                    --repo) repo="$2" ;;
                esac
                shift 2 ;;
            *) _ci_reject "$EXIT_CONFIG_ERROR" "Unknown ci --pr option: $1"; return ;;
        esac
    done
    local feature
    if ! feature=$(feature_resolve "${GLOBAL_FEATURE:-}"); then
        _ci_reject "$EXIT_CONFIG_ERROR" "No feature context; use --feature NAME"
        return
    fi
    feature_activate "$feature"
    base="${base:-$(git_main_branch)}"
    pr_branch="${pr_branch:-speed-ci/${feature}}"
    if ! _git check-ref-format --branch "$pr_branch" > /dev/null 2>&1 \
            || [[ "$pr_branch" =~ ^(refs|heads|remotes|tags)/ || "$pr_branch" == "${remote}/"* ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Invalid PR branch name: ${pr_branch}"
        return
    fi
    if ! git_branch_exists "$base"; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Base branch not found: ${base}"
        return
    fi
    local pushed_repo=""
    if [[ "$dry_run" != true ]]; then
        if ! _git remote get-url "$remote" > /dev/null 2>&1; then
            _ci_reject "$EXIT_CONFIG_ERROR" "Git remote not found: ${remote}"
            return
        fi
        pushed_repo=$(_ci_github_repo "$(_git config --get "remote.${remote}.url")" || true)
        if [[ -z "$pushed_repo" && -n "$repo" ]]; then
            _ci_reject "$EXIT_CONFIG_ERROR" "Cannot tell which GitHub repository ${remote} is, so the PR head is unknown; use a github.com URL for ${remote}"
            return
        fi
        repo="${repo:-$pushed_repo}"
        if [[ -z "$repo" ]]; then
            _ci_reject "$EXIT_CONFIG_ERROR" "Remote ${remote} is not a GitHub repository; pass --repo OWNER/REPO"
            return
        fi
        if [[ ! "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
            _ci_reject "$EXIT_CONFIG_ERROR" "Invalid --repo: ${repo} (expected OWNER/REPO)"
            return
        fi
        if ! command -v gh > /dev/null 2>&1; then
            _ci_reject "$EXIT_CONFIG_ERROR" "The GitHub CLI (gh) is not installed; it is needed to open the PR"
            return
        fi
        if ! gh auth status > /dev/null 2>&1; then
            _ci_reject "$EXIT_CONFIG_ERROR" "gh is not logged in; run 'gh auth login'"
            return
        fi
    fi

    local ordered task_id status branch title tasks_json="[]" not_done=() task_file
    local -a task_branches=()
    if ! ordered=$(task_topo_sort); then
        _ci_reject "$EXIT_CONFIG_ERROR" "The task graph has a dependency cycle"
        return
    fi
    for task_id in $ordered; do
        task_file="${TASKS_DIR}/${task_id}.json"
        if ! status=$(jq -r '.status // "unknown"' "$task_file" 2>/dev/null) \
                || ! branch=$(jq -r '.branch // empty' "$task_file") || ! title=$(jq -r '.title // ""' "$task_file"); then
            _ci_reject "$EXIT_CONFIG_ERROR" "Task file is unreadable: ${task_file}"
            return
        fi
        if [[ "$status" != done ]]; then
            not_done+=("${task_id} (${status})")
            continue
        fi
        if [[ -z "$branch" ]] || ! git_branch_exists "$branch"; then
            _ci_reject "$EXIT_CONFIG_ERROR" "Task ${task_id} is done but its branch is missing: ${branch:-none}"
            return
        fi
        task_branches+=("$branch")
        tasks_json=$(jq -c --arg id "$task_id" --arg t "$title" --arg b "$branch" \
            '. + [{id:$id, title:$t, branch:$b}]' <<< "$tasks_json")
    done
    if [[ ${#not_done[@]} -gt 0 ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Every task must be done before opening a PR; not done: ${not_done[*]}"
        return
    fi
    if [[ ${#task_branches[@]} -eq 0 ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Feature ${feature} has no tasks"
        return
    fi
    # The remote branch is rebuilt from scratch, so it must never be one that holds other work.
    # Names are compared without case: on macOS refs/heads/MAIN is refs/heads/main.
    local candidate current
    current=$(_git symbolic-ref -q --short HEAD || echo "")
    for candidate in "$base" "$current" "${task_branches[@]}"; do
        if [[ -n "$candidate" && "$(_ci_lower "$pr_branch")" == "$(_ci_lower "$candidate")" ]]; then
            _ci_reject "$EXIT_CONFIG_ERROR" "The PR branch cannot be ${pr_branch}: it is the base, the current branch or a task branch"
            return
        fi
    done
    if [[ -n "$(_git status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
        log_warn "Uncommitted changes are not part of the PR; only committed task branches are used"
    fi

    local base_ref="$base" remote_sha="" fetch_err foreign
    if [[ "$dry_run" != true ]]; then
        if ! fetch_err=$(_git fetch -q "$remote" "+refs/heads/${base}:refs/remotes/${remote}/${base}" 2>&1); then
            _ci_reject "$EXIT_CONFIG_ERROR" "Could not fetch ${base} from ${remote}: ${fetch_err}"
            return
        fi
        # The PR is built on the published base, never on unpushed local commits.
        base_ref="refs/remotes/${remote}/${base}"
        remote_sha=$(_git ls-remote --heads "$remote" "refs/heads/${pr_branch}" 2>/dev/null | cut -f1)
        if [[ -n "$remote_sha" ]]; then
            if ! fetch_err=$(_git fetch -q "$remote" "+refs/heads/${pr_branch}:refs/remotes/${remote}/${pr_branch}" 2>&1); then
                _ci_reject "$EXIT_CONFIG_ERROR" "Could not fetch ${pr_branch} from ${remote}: ${fetch_err}"
                return
            fi
            foreign=$(_ci_foreign_commits "$remote_sha" "$base_ref" "${task_branches[@]}")
            if [[ -n "$foreign" && "$force" != true ]]; then
                _ci_reject "$EXIT_CONFIG_ERROR" "${remote}/${pr_branch} has commits that did not come from the task branches ($(tr '\n' ' ' <<< "$foreign")); pass --force to replace them"
                return
            fi
        fi
    fi

    # Assemble and check in a temporary worktree, so the user's checkout, uncommitted
    # work and local branches are never touched.
    _CI_DIR="${STATE_DIR}/ci"
    if ! _ci_lock; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Another speed ci is running in this project"
        return
    fi
    _CI_WORKTREE=$(mktemp -d "${TMPDIR:-/tmp}/speed-ci-pr.XXXXXX")
    _CI_EXCLUDES=$(mktemp "${TMPDIR:-/tmp}/speed-ci-excludes.XXXXXX")
    trap '_ci_cleanup_worktree; _ci_unlock' EXIT
    local wt_err
    if ! wt_err=$(_git worktree add -q --detach "$_CI_WORKTREE" "$base_ref" 2>&1); then
        _ci_reject "$EXIT_CONFIG_ERROR" "Could not create a worktree for ${pr_branch}: ${wt_err}"
        return
    fi
    echo -e "${BOLD}SPEED CI${RESET}  (no model calls)"
    local merge_err
    while IFS=$'\t' read -r task_id branch; do
        if git -C "$_CI_WORKTREE" merge-base --is-ancestor "$branch" HEAD 2>/dev/null; then
            continue
        fi
        if ! merge_err=$(git -C "$_CI_WORKTREE" merge -q --no-ff "$branch" -m "Merge ${branch} (task ${task_id})" 2>&1); then
            local conflicting
            conflicting=$(git -C "$_CI_WORKTREE" diff --name-only --diff-filter=U 2>/dev/null | tr '\n' ' ')
            if [[ -n "$conflicting" ]]; then
                _ci_reject "$EXIT_MERGE_CONFLICT" "Task ${task_id} (${branch}) conflicts with the branches merged before it: ${conflicting}"
            else
                _ci_reject "$EXIT_CONFIG_ERROR" "Could not merge ${branch}: $(head -n 3 <<< "$merge_err" | tr '\n' ' ')"
            fi
            return
        fi
    done < <(jq -r '.[] | [.id, .branch] | @tsv' <<< "$tasks_json")
    _ci_pr_line pass merge "Merged ${#task_branches[@]} task branch(es) of ${feature} onto ${base} as ${pr_branch}"

    # A project in a subdirectory of the repository is checked in the same subdirectory.
    local prefix check_root
    prefix=$(_git rev-parse --show-prefix 2>/dev/null || echo "")
    check_root="${_CI_WORKTREE}/${prefix%/}"
    check_root="${check_root%/}"
    _ci_copy_feature_state "$check_root"
    _ci_link_dependencies "$check_root" "$_CI_WORKTREE" "$_CI_EXCLUDES"
    local checks_rc=0
    _ci_check_worktree "$check_root" "$_CI_EXCLUDES" || checks_rc=$?
    local report="${check_root}/.speed/ci/report.json"
    if [[ "$checks_rc" -eq "$EXIT_CONFIG_ERROR" || ! -f "$report" ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "The checks could not run in the assembly worktree"
        return
    fi
    # Keep the report and logs in the user's project, where speed ci always writes them.
    # This run holds the project's lock, so only its own lock entry is kept.
    find "$_CI_DIR" -mindepth 1 -maxdepth 1 ! -name .lock -exec rm -rf {} +
    rm -rf "${check_root}/.speed/ci/.lock"
    cp -R "${check_root}/.speed/ci/." "$_CI_DIR/"
    report="${_CI_DIR}/report.json"
    local sha passed
    sha=$(git -C "$_CI_WORKTREE" rev-parse HEAD)
    passed=$(jq -r '.passed' "$report")

    local body_file="${_CI_DIR}/pr-body.md"
    _ci_pr_body "$feature" "$tasks_json" "$report" > "$body_file"
    local state description pr_url="" title="SPEED: ${feature}"
    if [[ "$passed" == true ]]; then
        state=success; description="speed ci passed: $(jq -r "$_CI_COUNTS" "$report")"
    else
        state=failure; description="speed ci failed: $(jq -r "$_CI_COUNTS" "$report")"
        draft=true
    fi
    local context="${TOML_CI_STATUS_CONTEXT:-speed/ci}"

    if [[ "$dry_run" == true ]]; then
        _ci_pr_line skipped push "Dry run: ${pr_branch} not pushed"
        _ci_pr_line skipped pr "Dry run: no PR opened (would post ${context}: ${state} on ${sha:0:12})"
    else
        local push_err
        if ! push_err=$(git -C "$_CI_WORKTREE" push -q "--force-with-lease=refs/heads/${pr_branch}:${remote_sha}" \
                "$remote" "HEAD:refs/heads/${pr_branch}" 2>&1); then
            _ci_reject "$EXIT_CONFIG_ERROR" "Could not push ${pr_branch} to ${remote}: $(head -n 3 <<< "$push_err" | tr '\n' ' ')"
            return
        fi
        _ci_pr_line pass push "Pushed ${pr_branch} to ${remote}"
        # A PR into another repository names its head as OWNER:branch.
        local head="$pr_branch"
        if [[ -n "$pushed_repo" && "$(_ci_lower "$pushed_repo")" != "$(_ci_lower "$repo")" ]]; then
            head="${pushed_repo%%/*}:${pr_branch}"
        fi
        pr_url=$(gh pr view "$head" --repo "$repo" --json url,state --jq 'select(.state == "OPEN") | .url' 2>/dev/null || true)
        if [[ -n "$pr_url" ]]; then
            if ! gh pr edit "$head" --repo "$repo" --base "$base" --body-file "$body_file" > /dev/null 2>&1; then
                _ci_reject "$EXIT_CONFIG_ERROR" "gh pr edit failed for ${pr_url}"
                return
            fi
            local -a ready=(gh pr ready "$head" --repo "$repo")
            [[ "$draft" == true ]] && ready+=(--undo)
            "${ready[@]}" > /dev/null 2>&1 || log_warn "Could not change the draft state of ${pr_url}"
            _ci_pr_line pass pr "Updated ${pr_url}$([[ "$draft" == true ]] && echo " (draft)")"
        else
            local -a create=(gh pr create --repo "$repo" --base "$base" --head "$head" --title "$title"
                             --body-file "$body_file")
            [[ "$draft" == true ]] && create+=(--draft)
            if ! pr_url=$("${create[@]}" 2>/dev/null | tail -n 1) || [[ -z "$pr_url" ]]; then
                _ci_reject "$EXIT_CONFIG_ERROR" "gh pr create failed after pushing ${pr_branch}; open the PR by hand or rerun"
                return
            fi
            _ci_pr_line pass pr "Opened ${pr_url}$([[ "$draft" == true ]] && echo " (draft)")"
        fi
        if ! gh api --method POST "repos/${pushed_repo:-$repo}/statuses/${sha}" -f state="$state" -f context="$context" \
                -f description="${description:0:140}" -f target_url="$pr_url" > /dev/null 2>&1; then
            _ci_reject "$EXIT_CONFIG_ERROR" "Could not post the ${context} status to ${sha:0:12}"
            return
        fi
        _ci_pr_line pass status "Posted ${context}: ${state} on ${sha:0:12}"
    fi
    _ci_result_line "$report"
    if [[ "${JSON_OUTPUT:-false}" == true ]]; then
        jq --arg feature "$feature" --arg branch "$pr_branch" --arg base "$base" --arg url "$pr_url" \
            --arg state "$state" --argjson dry "$dry_run" \
            '. + {feature:$feature, branch:$branch, base:$base, pr_url:$url, status:$state, dry_run:$dry}' \
            "$report" >&3
    fi
    return "$checks_rc"
}

# ── Entry point ────────────────────────────────────────────────────────────────

cmd_ci() (
    if [[ "${JSON_OUTPUT:-false}" == true ]]; then
        exec 3>&1
        exec 1>&2
    fi
    _ci_forbid_models
    if [[ "${1:-}" == init ]]; then
        shift
        _ci_init "$@"
        exit
    fi
    if [[ "${1:-}" == merge ]]; then
        shift
        if [[ $# -eq 0 ]]; then
            _ci_reject "$EXIT_CONFIG_ERROR" "speed ci merge needs the report directories of the parallel jobs"
            exit
        fi
        local merge_rc=0
        # The merge helper writes every output itself; a refused merge keeps the previous report.
        local merge_err
        merge_err=$(_ci_python merge "${STATE_DIR}/ci" "$@" 2>&1 >/dev/null) || merge_rc=$?
        if [[ "$merge_rc" -ne 0 && "$merge_rc" -ne 2 ]]; then
            _ci_reject "$EXIT_CONFIG_ERROR" "The reports could not be combined: ${merge_err:-unknown error}"
            exit
        fi
        cat "${STATE_DIR}/ci/summary.md"
        if [[ "${JSON_OUTPUT:-false}" == true ]]; then
            cat "${STATE_DIR}/ci/report.json" >&3
        fi
        exit "$merge_rc"
    fi
    local pr=false list=false step
    _CI_SKIP=()
    _CI_ONLY=()
    local -a pr_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --pr) pr=true; shift ;;
            --list) list=true; shift ;;
            --skip|--only)
                [[ $# -ge 2 && "$2" != --* ]] || { _ci_reject "$EXIT_CONFIG_ERROR" "$1 requires a value"; exit; }
                local -a names=()
                IFS=, read -ra names <<< "$2"
                local added=0
                for step in "${names[@]+"${names[@]}"}"; do
                    step="${step// /}"
                    [[ -n "$step" ]] || continue
                    added=$((added + 1))
                    if [[ "$1" == --skip ]]; then _CI_SKIP+=("$step"); else _CI_ONLY+=("$step"); fi
                done
                if [[ "$added" -eq 0 ]]; then
                    _ci_reject "$EXIT_CONFIG_ERROR" "$1 requires at least one check name"
                    exit
                fi
                shift 2 ;;
            --draft|--dry-run|--force) pr_args+=("$1"); shift ;;
            --base|--branch|--remote|--repo)
                [[ $# -ge 2 ]] || { _ci_reject "$EXIT_CONFIG_ERROR" "$1 requires a value"; exit; }
                pr_args+=("$1" "$2"); shift 2 ;;
            -h|--help)
                echo "Usage: speed ci [--skip CHECKS | --only CHECKS] [--list] | speed ci init [--force] | speed ci --pr [--draft] [--dry-run] [--base B] [--branch B] | speed ci merge DIR..."
                exit 0 ;;
            *) _ci_reject "$EXIT_CONFIG_ERROR" "Unknown ci option: $1"; exit ;;
        esac
    done
    _ci_settings || exit
    local canonical
    canonical=$(_ci_check_names --skip "${_CI_SKIP[@]+"${_CI_SKIP[@]}"}") || exit
    _CI_SKIP=()
    while IFS= read -r step; do
        if [[ -n "$step" ]]; then _CI_SKIP+=("$step"); fi
    done <<< "$canonical"
    canonical=$(_ci_check_names --only "${_CI_ONLY[@]+"${_CI_ONLY[@]}"}") || exit
    _CI_ONLY=()
    while IFS= read -r step; do
        if [[ -n "$step" ]]; then _CI_ONLY+=("$step"); fi
    done <<< "$canonical"
    if [[ ${#_CI_SKIP[@]} -gt 0 && ${#_CI_ONLY[@]} -gt 0 ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Use --skip or --only, not both"
        exit
    fi
    if [[ "$list" == true ]]; then
        printf '%s\n' "${_CI_AVAILABLE[@]}"
        if [[ "${JSON_OUTPUT:-false}" == true ]]; then
            printf '%s\n' "${_CI_AVAILABLE[@]}" | jq -R . | jq -sc '{checks:.}' >&3
        fi
        exit 0
    fi
    if [[ -z "${_TIMEOUT_CMD:-}" ]]; then
        log_warn "Neither timeout nor gtimeout is installed, so [ci] command_timeout cannot be enforced"
    fi
    if [[ -n "${GLOBAL_FEATURE:-}" ]] && ! feature_list | grep -qxF "$GLOBAL_FEATURE"; then
        _ci_reject "$EXIT_CONFIG_ERROR" "Unknown feature: ${GLOBAL_FEATURE}"
        exit
    fi
    if [[ "$pr" == true ]]; then
        # A PR status must describe every check, so nothing can be left out.
        if [[ ${#_CI_SKIP[@]} -gt 0 || ${#_CI_ONLY[@]} -gt 0 ]]; then
            _ci_reject "$EXIT_CONFIG_ERROR" "--skip and --only cannot be used with --pr; the PR status must cover every check"
            exit
        fi
        _ci_pr "${pr_args[@]+"${pr_args[@]}"}"
        exit
    fi
    if [[ ${#pr_args[@]} -gt 0 ]]; then
        _ci_reject "$EXIT_CONFIG_ERROR" "${pr_args[0]} only applies with --pr"
        exit
    fi
    if ! _git rev-parse --git-dir > /dev/null 2>&1; then
        _ci_reject "$EXIT_CONFIG_ERROR" "speed ci must run inside a git repository"
        exit
    fi
    local rc=0
    _ci_run_checks || rc=$?
    if [[ "${JSON_OUTPUT:-false}" == true && "$rc" -ne "$EXIT_CONFIG_ERROR" ]]; then
        cat "${_CI_DIR}/report.json" >&3
    fi
    exit "$rc"
)
