#!/usr/bin/env bash
# codex-cli.sh — OpenAI Codex CLI provider for SPEED
#
# Implements the provider interface:
#   provider_run, provider_run_json, provider_spawn_bg,
#   provider_is_running, provider_wait
#
# Requires provider.sh (for _TIMEOUT_CMD, require_timeout_cmd)
# and config.sh to be sourced first.
#
# Codex CLI differences from Claude Code:
#   - Binary: codex exec (not claude -p)
#   - System prompt: -c developer_instructions="..." (not --system-prompt)
#   - Model: --model o3 (not --model opus)
#   - Tools: --sandbox workspace-write | read-only (coarser, 3 tiers)
#   - JSON: --json --output-schema <file> (not --output-format json --json-schema)
#   - Working dir: --cd $dir (not subshell cd)
#   - Max turns: not exposed (omit)
#   - Output: raw (no envelope unwrapping needed)

# ── Provider setup ───────────────────────────────────────────────

PROVIDER_BIN="${CODEX_BIN:-$(which codex 2>/dev/null || echo "codex")}"

# ── Tool access mapping ─────────────────────────────────────────
# Codex CLI has coarser tool granularity: 3 sandbox tiers instead of per-tool.
#   AGENT_TOOLS_FULL     → --sandbox workspace-write
#   AGENT_TOOLS_READONLY → --sandbox read-only

_codex_sandbox() {
    local tools="$1"
    if [[ "$tools" == "$AGENT_TOOLS_READONLY" ]]; then
        echo "read-only"
    else
        echo "workspace-write"
    fi
}

# ── Provider interface implementation ────────────────────────────

provider_run() {
    local system_prompt_file="$1"
    local user_message="$2"
    local model="${3:-$MODEL_SUPPORT}"
    local allowed_tools="${4:-$AGENT_TOOLS_FULL}"

    local system_prompt
    system_prompt="$(cat "$system_prompt_file")"

    # Prepend agent file content if it exists
    if [[ -n "$AGENT_FILE_PATH" ]] && [[ -f "$AGENT_FILE_PATH" ]]; then
        system_prompt="$(cat "$AGENT_FILE_PATH")"$'\n\n---\n\n'"${system_prompt}"
    fi

    require_timeout_cmd || return 1

    local agent_timeout="${DEFAULT_AGENT_TIMEOUT:-600}"
    local kill_grace="${AGENT_KILL_GRACE:-10}"
    local sandbox
    sandbox=$(_codex_sandbox "$allowed_tools")

    local stderr_file
    stderr_file=$(mktemp)

    local raw_output
    local rc=0
    raw_output=$("$_TIMEOUT_CMD" --kill-after="$kill_grace" "$agent_timeout" \
        "$PROVIDER_BIN" exec \
        --model "$model" \
        --sandbox "$sandbox" \
        -c developer_instructions="$system_prompt" \
        "$user_message" \
        2>"$stderr_file") || rc=$?

    local stderr_content
    stderr_content=$(cat "$stderr_file" 2>/dev/null)
    rm -f "$stderr_file"

    if [[ $rc -eq 124 || $rc -eq 137 ]]; then
        log_error "Agent timed out after ${agent_timeout}s (exit code ${rc})"
        [[ -n "$stderr_content" ]] && log_error "stderr: ${stderr_content}"
        return 1
    fi

    if [[ $rc -ne 0 ]]; then
        log_error "Codex CLI exited with code ${rc}"
        [[ -n "$stderr_content" ]] && log_error "stderr: ${stderr_content}"
        [[ -z "$raw_output" ]] && return 1
        log_warn "CLI returned non-zero exit but produced output, proceeding"
    fi

    if [[ -z "$raw_output" ]]; then
        log_error "Agent returned empty output"
        [[ -n "$stderr_content" ]] && log_error "stderr: ${stderr_content}"
        return 1
    fi

    echo "$raw_output"
}

provider_run_json() {
    local system_prompt_file="$1"
    local user_message="$2"
    local json_schema_file="$3"
    local model="${4:-$MODEL_SUPPORT}"
    local max_turns="${5:-$DEFAULT_JSON_MAX_TURNS}"
    local arg_count=$#

    local system_prompt
    system_prompt="$(cat "$system_prompt_file")"

    if [[ -n "$AGENT_FILE_PATH" ]] && [[ -f "$AGENT_FILE_PATH" ]]; then
        system_prompt="$(cat "$AGENT_FILE_PATH")"$'\n\n---\n\n'"${system_prompt}"
    fi

    require_timeout_cmd || return 1

    local agent_timeout="${8:-${DEFAULT_AGENT_TIMEOUT:-600}}"
    local kill_grace="${AGENT_KILL_GRACE:-10}"

    # Determine sandbox tier
    local sandbox="workspace-write"
    if [[ $arg_count -ge 6 ]] && [[ -z "${6}" ]]; then
        # Empty tools = pure reasoning, use read-only
        sandbox="read-only"
    elif [[ $arg_count -ge 6 ]]; then
        sandbox=$(_codex_sandbox "${6}")
    fi

    local stderr_file
    stderr_file=$(mktemp)

    local raw_output
    local rc=0
    raw_output=$("$_TIMEOUT_CMD" --kill-after="$kill_grace" "$agent_timeout" \
        "$PROVIDER_BIN" exec \
        --model "$model" \
        --sandbox "$sandbox" \
        --json \
        --output-schema "$json_schema_file" \
        -c developer_instructions="$system_prompt" \
        "$user_message" \
        2>"$stderr_file") || rc=$?

    local stderr_content
    stderr_content=$(cat "$stderr_file" 2>/dev/null)
    rm -f "$stderr_file"

    if [[ $rc -eq 124 || $rc -eq 137 ]]; then
        log_error "JSON agent timed out after ${agent_timeout}s (exit code ${rc})"
        [[ -n "$stderr_content" ]] && log_error "stderr: ${stderr_content}"
        return 1
    fi

    if [[ $rc -ne 0 ]]; then
        log_error "Codex CLI (JSON mode) exited with code ${rc}"
        [[ -n "$stderr_content" ]] && log_error "stderr: ${stderr_content}"
        [[ -z "$raw_output" ]] && return 1
        log_warn "CLI returned non-zero exit but produced output, proceeding"
    fi

    if [[ -z "$raw_output" ]]; then
        log_error "JSON agent returned empty output"
        [[ -n "$stderr_content" ]] && log_error "stderr: ${stderr_content}"
        return 1
    fi

    # Codex CLI outputs raw JSON (no envelope), so return as-is
    echo "$raw_output"
}

provider_spawn_bg() {
    local system_prompt_file="$1"
    local user_message="$2"
    local output_file="$3"
    local model="${4:-$MODEL_SUPPORT}"
    local allowed_tools="${5:-$AGENT_TOOLS_FULL}"
    local agent_cwd="${6:-$PROJECT_ROOT}"

    local system_prompt
    system_prompt="$(cat "$system_prompt_file")"

    if [[ -n "$AGENT_FILE_PATH" ]] && [[ -f "$AGENT_FILE_PATH" ]]; then
        system_prompt="$(cat "$AGENT_FILE_PATH")"$'\n\n---\n\n'"${system_prompt}"
    fi

    require_timeout_cmd || return 1

    local done_marker="${output_file}.done"
    local timeout_marker="${output_file}.timeout"
    local error_marker="${output_file}.error"
    rm -f "$done_marker" "$timeout_marker" "$error_marker"

    local agent_timeout="${DEFAULT_AGENT_TIMEOUT:-600}"
    local kill_grace="${AGENT_KILL_GRACE:-10}"
    local sandbox
    sandbox=$(_codex_sandbox "$allowed_tools")

    ( "$_TIMEOUT_CMD" --kill-after="$kill_grace" "$agent_timeout" \
        "$PROVIDER_BIN" exec \
        --model "$model" \
        --sandbox "$sandbox" \
        --cd "$agent_cwd" \
        -c developer_instructions="$system_prompt" \
        "$user_message" \
        > "$output_file" 2>&1
      local rc=$?
      if [[ $rc -eq 124 || $rc -eq 137 ]]; then
          touch "$timeout_marker"
          echo '{"status":"timeout","reason":"Agent timed out after '"$agent_timeout"'s"}' >> "$output_file"
      elif [[ $rc -ne 0 ]]; then
          echo "$rc" > "$error_marker"
          echo '{"status":"error","reason":"Codex CLI exited with code '"$rc"'"}' >> "$output_file"
      fi
      touch "$done_marker"
    ) >/dev/null 2>&1 &

    echo $!
}

provider_is_running() {
    local pid="$1"
    kill -0 "$pid" 2>/dev/null
}

provider_wait() {
    local pid="$1"
    wait "$pid" 2>/dev/null
    return $?
}
