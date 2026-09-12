#!/usr/bin/env bash
# provider.sh — Provider abstraction layer for SPEED agents
#
# Resolves the active provider, sources its implementation, and creates
# Exports provider_* functions via the loaded provider file.
#
# Requires config.sh and log.sh to be sourced first.

# ── Resolve timeout command ──────────────────────────────────────
_TIMEOUT_CMD=""
if command -v timeout &>/dev/null; then
    _TIMEOUT_CMD="timeout"
elif command -v gtimeout &>/dev/null; then
    _TIMEOUT_CMD="gtimeout"
fi

# Hard gate: refuse to run agents without a timeout command.
require_timeout_cmd() {
    if [[ -z "$_TIMEOUT_CMD" ]]; then
        log_error_block \
            "Cannot find 'timeout' or 'gtimeout' command" \
            "SPEED requires GNU timeout to enforce agent time limits" \
            "macOS: brew install coreutils  |  Linux: apt install coreutils"
        return 1
    fi
}

# Fail fast at source time — don't wait until the first agent call
require_timeout_cmd || exit "$EXIT_CONFIG_ERROR"

# ── JSON extraction from agent output ────────────────────────────
# Agent output is free-form text that may contain JSON. This function
# applies a consistent extraction pipeline so every call site doesn't
# reinvent its own fragile parser.
#
# Pipeline (stops at first success):
#   1. Direct jq parse — output is already valid JSON
#   2. Code-fence extraction — ```json ... ``` or ``` ... ```
#   3. Brace/bracket scanning — find outermost { } or [ ]
#      Falls back to last { } if the outermost span is invalid
#      (handles JSON appended to end of long output, e.g. blocked status)
#
# Usage:
#   parsed=$(parse_agent_json "$agent_output")
#   cat file.log | parse_agent_json
#
# Returns 0 + prints JSON on success, returns 1 on failure.

parse_agent_json() {
    local raw="${1:-$(cat)}"

    [[ -z "$raw" ]] && return 1

    # 1. Direct parse
    if echo "$raw" | jq -e '.' &>/dev/null; then
        echo "$raw" | jq -c '.'
        return 0
    fi

    # 2. Code-fence extraction (```json ... ``` or ``` ... ```)
    local fenced
    fenced=$(echo "$raw" | sed -n '/^```/,/^```/{/^```/d;p;}')
    if [[ -n "$fenced" ]] && echo "$fenced" | jq -e '.' &>/dev/null; then
        echo "$fenced" | jq -c '.'
        return 0
    fi

    # 3. Brace/bracket scanning via Python (handles nested structures reliably)
    local py_result
    py_result=$(python3 -c '
import sys, json

text = sys.stdin.read()

def try_parse(s):
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None

for sc, ec in [("{", "}"), ("[", "]")]:
    # Strategy A: outermost span (first sc to last ec)
    start = text.find(sc)
    end = text.rfind(ec)
    if start >= 0 and end > start:
        parsed = try_parse(text[start:end+1])
        if parsed is not None:
            print(json.dumps(parsed))
            sys.exit(0)

    # Strategy B: last valid block (for JSON appended to long output)
    pos = len(text)
    while True:
        end = text.rfind(ec, 0, pos)
        if end < 0:
            break
        depth = 0
        for i in range(end, -1, -1):
            if text[i] == ec:
                depth += 1
            elif text[i] == sc:
                depth -= 1
                if depth == 0:
                    parsed = try_parse(text[i:end+1])
                    if parsed is not None:
                        print(json.dumps(parsed))
                        sys.exit(0)
                    break
        pos = end  # try earlier occurrence

sys.exit(1)
' <<< "$raw" 2>&1)
    local py_rc=$?

    if [[ $py_rc -eq 0 ]] && [[ -n "$py_result" ]]; then
        echo "$py_result"
        return 0
    fi

    return 1
}

# Validate that a string is valid JSON. Logs an error with the agent
# name and a preview of the raw output if not.
# Usage: _require_json "Guardian" "$output" || return 1
_require_json() {
    local label="$1" json="$2"
    if [[ -z "$json" ]]; then
        log_error "${label} returned empty output"
        return 1
    fi
    if ! echo "$json" | jq empty 2>/dev/null; then
        log_error "${label} returned invalid JSON"
        log_verbose "  First 300 chars: ${json:0:300}"
        return 1
    fi
    return 0
}

# ── Resolve and load provider ────────────────────────────────────
# Priority: SPEED_PROVIDER env > speed.toml [agent].provider > default (claude-code)

# Default "claude-code" is overridable via SPEED_PROVIDER or speed.toml [agent].provider
_PROVIDER_NAME="${SPEED_PROVIDER:-${TOML_AGENT_PROVIDER:-claude-code}}"
_PROVIDERS_DIR="${SCRIPT_DIR}/providers"
_PROVIDER_FILE="${_PROVIDERS_DIR}/${_PROVIDER_NAME}.sh"

if [[ ! -f "$_PROVIDER_FILE" ]]; then
    _available=""
    for f in "${_PROVIDERS_DIR}"/*.sh; do
        [[ -f "$f" ]] || continue
        _available+="  - $(basename "$f" .sh)"$'\n'
    done
    log_error_block \
        "Unknown provider '${_PROVIDER_NAME}'" \
        "Set via: SPEED_PROVIDER env var or speed.toml [agent].provider (default: claude-code)" \
        "Available providers:" \
        "${_available% }"
    exit "$EXIT_CONFIG_ERROR"
fi

# Default failure diagnostic — providers override with format-specific parsing.
# Args: label raw_log_path logs_dir
provider_diagnose_failure() {
    local raw_log="$2"
    log_warn "Check the raw log manually: ${raw_log}"
}

# ── Machine-readable failure contract ───────────────────────────
# Provider adapters classify their own native output, then use this shared
# owner to serialize one stable, provider-agnostic envelope.  The optional
# file transport survives command substitutions without mixing diagnostics
# into a successful provider response.
PROVIDER_FAILURE_CONTRACT_VERSION=1

provider_failure_clear() {
    [[ -n "${SPEED_PROVIDER_FAILURE_FILE:-}" ]] || return 0
    : > "$SPEED_PROVIDER_FAILURE_FILE"
}

provider_failure_record() {
    local category="$1" scope="$2" retryable="$3" native_status="${4:-}"
    local message="$5" diagnostic_log="${6:-}"
    case "$category" in
        authentication_required|authorization_denied|capability_unavailable|rate_limited|transport_unavailable|timeout|process_failed|response_incomplete|response_invalid|unknown) ;;
        *) category="unknown" ;;
    esac
    case "$scope" in provider|request) ;; *) scope="provider" ;; esac
    case "$retryable" in true|false) ;; *) retryable="false" ;; esac
    native_status=$(printf '%s' "$native_status" | tr -cd '[:alnum:]_.:-' | cut -c1-64)
    message=$(printf '%s' "$message" | tr '\r\n' '  ' | cut -c1-256)
    diagnostic_log=$(printf '%s' "$diagnostic_log" | tr -cd '[:alnum:]_./:-' | cut -c1-512)
    local envelope
    envelope=$(jq -cn \
        --argjson schema_version "$PROVIDER_FAILURE_CONTRACT_VERSION" \
        --arg category "$category" --arg scope "$scope" \
        --argjson retryable "$retryable" --arg native_status "$native_status" \
        --arg message "$message" --arg diagnostic_log "$diagnostic_log" \
        '{schema_version:$schema_version,category:$category,scope:$scope,retryable:$retryable,
          native_status:(if $native_status=="" then null else $native_status end),
          message:$message,diagnostic_log:(if $diagnostic_log=="" then null else $diagnostic_log end)}') || return 1
    if [[ -n "${SPEED_PROVIDER_FAILURE_FILE:-}" ]]; then
        printf '%s\n' "$envelope" > "$SPEED_PROVIDER_FAILURE_FILE"
    fi
}

provider_failure_record_if_absent() {
    if [[ -n "${SPEED_PROVIDER_FAILURE_FILE:-}" && -s "$SPEED_PROVIDER_FAILURE_FILE" ]]; then
        return 0
    fi
    provider_failure_record "$@"
}

provider_failure_read() {
    [[ -n "${SPEED_PROVIDER_FAILURE_FILE:-}" && -s "$SPEED_PROVIDER_FAILURE_FILE" ]] || return 1
    jq -ce 'select(
        .schema_version == 1 and
        (.category | IN("authentication_required","authorization_denied","capability_unavailable",
          "rate_limited","transport_unavailable","timeout","process_failed","response_incomplete",
          "response_invalid","unknown")) and
        (.scope | IN("provider","request")) and
        (.retryable | type == "boolean") and
        (.native_status == null or (.native_status | type == "string" and length <= 64)) and
        (.message | type == "string" and length > 0 and length <= 256) and
        (.diagnostic_log == null or (.diagnostic_log | type == "string" and length <= 512))
    )' "$SPEED_PROVIDER_FAILURE_FILE" 2>/dev/null
}

# Provider/model limits share this owner with provider selection. Adapters may
# override the hook for stable aliases; unknown explicit model IDs remain
# unknown. Operators can supply authoritative caps without adding a discovery
# configuration path or a provider-name branch to Python orchestration.
_provider_model_capabilities() {
    printf '%s\n' '{"provider_context_tokens":null,"provider_max_output_tokens":null,"output_limit_enforcement":"unknown"}'
}

provider_model_capabilities() {
    local model="$1" capabilities context_override output_override
    capabilities=$(_provider_model_capabilities "$model") || return 1
    if ! printf '%s' "$capabilities" | jq -e '
        (keys == ["output_limit_enforcement","provider_context_tokens","provider_max_output_tokens"]) and
        (.provider_context_tokens == null or
         (.provider_context_tokens | type == "number" and floor == . and . > 0)) and
        (.provider_max_output_tokens == null or
         (.provider_max_output_tokens | type == "number" and floor == . and . > 0)) and
        (.output_limit_enforcement | IN("unknown","provider","local_estimate"))
    ' >/dev/null 2>&1; then
        log_error "Provider returned invalid model capability metadata"
        return 1
    fi
    context_override="${SPEED_PROVIDER_CONTEXT_TOKENS:-}"
    output_override="${SPEED_PROVIDER_MAX_OUTPUT_TOKENS:-}"
    if [[ -n "$context_override" && ! "$context_override" =~ ^[1-9][0-9]*$ ]]; then
        log_error "SPEED_PROVIDER_CONTEXT_TOKENS must be a positive integer"
        return 1
    fi
    if [[ -n "$output_override" && ! "$output_override" =~ ^[1-9][0-9]*$ ]]; then
        log_error "SPEED_PROVIDER_MAX_OUTPUT_TOKENS must be a positive integer"
        return 1
    fi
    printf '%s' "$capabilities" | jq -c \
        --arg context "$context_override" --arg output "$output_override" '
        if $context != "" then .provider_context_tokens=($context|tonumber) else . end |
        if $output != "" then
          .provider_max_output_tokens=($output|tonumber) | .output_limit_enforcement="provider"
        else . end'
}

# Default chat — providers override with their own implementation.
# Args: prompt_file
provider_chat() {
    local prompt_file="$1"
    log_warn "provider_chat not implemented for provider '${_PROVIDER_NAME}'"
    return 1
}

source "$_PROVIDER_FILE"

# ── Validate provider binary ────────────────────────────────────
# The provider file sets PROVIDER_BIN. Validate it resolves to a
# real binary before any agent calls. Catches missing installs early
# with a clear message instead of a cryptic failure at first agent call.

if ! command -v "$PROVIDER_BIN" &>/dev/null; then
    log_error_block \
        "Provider '${_PROVIDER_NAME}' binary not found: ${PROVIDER_BIN}" \
        "Install the binary or set the path via the provider's env var"
    exit "$EXIT_CONFIG_ERROR"
fi

# ── Token budget & rate limit handling ────────────────────────────
# Tracks token usage per pipeline run and paces API calls to stay
# within TPM/RPM budgets. Retries on rate limit with exp backoff.

_TOKEN_TRACKER="${TMPDIR:-/tmp}/_speed_tokens_$$"

# Rough token estimate from character count (~4 chars per token)
_estimate_tokens() {
    local text="$1"
    local chars=${#text}
    echo $(( (chars + 3) / 4 ))
}

# Record a token usage event
_track_tokens() {
    local estimated="$1"
    local now
    now=$(date +%s)
    echo "${now} ${estimated}" >> "$_TOKEN_TRACKER"
}

# Sum tokens used in the last 60 seconds
_tokens_used_last_minute() {
    local now cutoff total=0
    now=$(date +%s)
    cutoff=$((now - 60))
    [[ ! -f "$_TOKEN_TRACKER" ]] && echo 0 && return 0
    while IFS=' ' read -r ts tokens; do
        [[ -z "$ts" ]] && continue
        [[ $ts -ge $cutoff ]] && total=$((total + tokens))
    done < "$_TOKEN_TRACKER"
    echo "$total"
}

# Count requests in the last 60 seconds
_requests_last_minute() {
    local now cutoff count=0
    now=$(date +%s)
    cutoff=$((now - 60))
    [[ ! -f "$_TOKEN_TRACKER" ]] && echo 0 && return 0
    while IFS=' ' read -r ts _; do
        [[ -z "$ts" ]] && continue
        [[ $ts -ge $cutoff ]] && count=$((count + 1))
    done < "$_TOKEN_TRACKER"
    echo "$count"
}

# Wait until we have budget for the next API call
_pace_api_call() {
    local estimated_tokens="$1"

    while true; do
        local used rpm
        used=$(_tokens_used_last_minute)
        rpm=$(_requests_last_minute)
        local headroom=$(( TPM_BUDGET * 80 / 100 ))  # 80% threshold

        if [[ $((used + estimated_tokens)) -lt $headroom ]] && [[ $rpm -lt $RPM_BUDGET ]]; then
            return 0  # safe to proceed
        fi

        local wait_secs=15
        log_info "Pacing: ${used}/${TPM_BUDGET} TPM, ${rpm}/${RPM_BUDGET} RPM — waiting ${wait_secs}s"
        sleep "$wait_secs"
    done
}

# Retry wrapper for rate-limited API calls
_call_with_retry() {
    local attempt=0
    local delay=$RATE_LIMIT_BASE_DELAY

    while true; do
        local output=""
        local rc=0
        output=$("$@") || rc=$?

        # Check for rate limit in output
        if echo "$output" | grep -qi "rate limit" 2>/dev/null; then
            attempt=$((attempt + 1))
            if [[ $attempt -ge $RATE_LIMIT_MAX_RETRIES ]]; then
                echo "$output"
                return 1
            fi
            log_warn "Rate limit reached — waiting ${delay}s before retry (attempt ${attempt}/${RATE_LIMIT_MAX_RETRIES})"
            sleep "$delay"
            delay=$(( delay * 2 ))
            [[ $delay -gt $RATE_LIMIT_MAX_DELAY ]] && delay=$RATE_LIMIT_MAX_DELAY
            continue
        fi

        # Prompt too long is not retryable
        if echo "$output" | grep -qi "prompt.*too long\|too long.*prompt" 2>/dev/null; then
            log_error "Prompt too long — reduce context size"
            echo "$output"
            return 1
        fi

        echo "$output"
        return $rc
    done
}
