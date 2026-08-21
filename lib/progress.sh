#!/usr/bin/env bash
# progress.sh — Real-time agent progress display for SPEED
#
# Parses stream-json events from the Claude CLI and renders
# context-aware progress in SPEED's visual language.
#
# Two modes based on environment:
#   TTY:     single updating line with elapsed time (on stderr)
#   non-TTY: timestamped log lines, one per significant event (on stderr)
#
# ALL output goes to stderr. Provider stdout is reserved for the
# agent's result, which callers capture via command substitution.
#
# Requires config.sh, colors.sh, and log.sh to be sourced first.

# ── TTY detection ───────────────────────────────────────────────
# Check stderr (fd 2) since that's where progress goes.
# Stdout may be captured by the caller — don't check it.
_PROGRESS_IS_TTY=false
[[ -t 2 ]] && _PROGRESS_IS_TTY=true

# Track state for the current progress display
_PROGRESS_LABEL=""
_PROGRESS_START=0
_PROGRESS_LINE_ACTIVE=false

# ── Elapsed time formatting ────────────────────────────────────

_progress_elapsed() {
    local now
    now=$(date +%s)
    local elapsed=$(( now - _PROGRESS_START ))
    format_duration "$elapsed"
}

# ── TTY line management ────────────────────────────────────────
# Write a status line that overwrites the previous one.
# Uses \r + \033[K (clear to end of line) to avoid artifacts.
# Always writes to stderr.

_progress_update_line() {
    local status_text="$1"
    if [[ "$_PROGRESS_IS_TTY" == "true" ]]; then
        local elapsed
        elapsed=$(_progress_elapsed)
        printf "\r\033[K  ${COLOR_ACCENT}${SYM_RUNNING}${RESET} %-14s ${COLOR_DIM}%s${RESET}  %s" \
            "$_PROGRESS_LABEL" "$status_text" "${elapsed}" >&2
        _PROGRESS_LINE_ACTIVE=true
    fi
}

# Finalize the TTY line — print a permanent line and newline.
_progress_finish_line() {
    local symbol="$1" color="$2" suffix="$3"
    if [[ "$_PROGRESS_IS_TTY" == "true" && "$_PROGRESS_LINE_ACTIVE" == "true" ]]; then
        printf "\r\033[K" >&2
    fi
    echo -e "  ${color}${symbol}${RESET} ${_PROGRESS_LABEL}  ${COLOR_DIM}${suffix}${RESET}" >&2
    _PROGRESS_LINE_ACTIVE=false
}

# ── Public API ──────────────────────────────────────────────────

# Call once before polling begins.
# Args: label
progress_start() {
    _PROGRESS_LABEL="$1"
    _PROGRESS_START=$(date +%s)
    _PROGRESS_LINE_ACTIVE=false

    if [[ "$_PROGRESS_IS_TTY" == "true" ]]; then
        _progress_update_line "starting..."
    else
        echo -e "${COLOR_DIM}[$(_log_timestamp)]${RESET} ${COLOR_ACCENT}${SYM_RUNNING}${RESET} ${_PROGRESS_LABEL}: started" >&2
    fi
}

# Call for each stream-json event line.
# Args: json_line
# Parses the event type and updates the display.
progress_event() {
    local line="$1"

    # Skip empty / unparseable lines
    [[ -z "$line" ]] && return 0
    local event_type
    event_type=$(echo "$line" | jq -r '.type // empty' 2>/dev/null) || return 0
    [[ -z "$event_type" ]] && return 0

    case "$event_type" in
        system)
            # Init event — extract model for display
            local model
            model=$(echo "$line" | jq -r '.model // empty' 2>/dev/null)
            if [[ -n "$model" ]]; then
                if [[ "$_PROGRESS_IS_TTY" == "true" ]]; then
                    _progress_update_line "connected (${model})"
                else
                    echo -e "${COLOR_DIM}[$(_log_timestamp)]${RESET} ${COLOR_ACCENT}${SYM_RUNNING}${RESET} ${_PROGRESS_LABEL}: connected (${model})" >&2
                fi
            fi
            ;;

        assistant)
            # Parse content blocks for tool_use, thinking, text
            local content_types
            content_types=$(echo "$line" | jq -r '
                .message.content[]? |
                if .type == "tool_use" then "tool_use:" + .name
                elif .type == "thinking" then "thinking"
                elif .type == "text" then "text"
                else empty end
            ' 2>/dev/null)

            while IFS= read -r ct; do
                [[ -z "$ct" ]] && continue
                case "$ct" in
                    tool_use:*)
                        local tool_name tool_detail display
                        tool_name="${ct#tool_use:}"
                        tool_detail=$(_extract_tool_detail "$line" "$tool_name")
                        display="${tool_name}"
                        [[ -n "$tool_detail" ]] && display="${tool_name} ${SYM_ARROW} ${tool_detail}"

                        if [[ "$_PROGRESS_IS_TTY" == "true" ]]; then
                            _progress_update_line "${SYM_DOT} ${display}"
                        else
                            echo -e "${COLOR_DIM}[$(_log_timestamp)]${RESET} ${COLOR_ACCENT}${SYM_RUNNING}${RESET} ${_PROGRESS_LABEL}: ${display}" >&2
                        fi
                        ;;
                    thinking)
                        if [[ "$_PROGRESS_IS_TTY" == "true" ]]; then
                            _progress_update_line "thinking..."
                        elif [[ "${VERBOSITY:-1}" -ge 2 ]]; then
                            echo -e "${COLOR_DIM}[$(_log_timestamp)]${RESET} ${COLOR_ACCENT}${SYM_RUNNING}${RESET} ${_PROGRESS_LABEL}: thinking..." >&2
                        fi
                        ;;
                    text)
                        if [[ "$_PROGRESS_IS_TTY" == "true" ]]; then
                            _progress_update_line "responding..."
                        fi
                        ;;
                esac
            done <<< "$content_types"
            ;;

        rate_limit_event)
            local rl_status
            rl_status=$(echo "$line" | jq -r '.rate_limit_info.status // "allowed"' 2>/dev/null)
            if [[ "$rl_status" != "allowed" ]]; then
                if [[ "$_PROGRESS_IS_TTY" == "true" ]]; then
                    _progress_update_line "${COLOR_WARN}rate limited${RESET}"
                else
                    echo -e "${COLOR_DIM}[$(_log_timestamp)]${RESET} ${COLOR_WARN}${SYM_WARN}${RESET} ${_PROGRESS_LABEL}: rate limited" >&2
                fi
            fi
            ;;

        result)
            # Handled by progress_complete / progress_error — not here.
            ;;
    esac
}

# Call on successful completion.
# Args: duration_s num_turns [cost_usd]
progress_complete() {
    local duration_s="$1" num_turns="${2:-}" cost="${3:-}"
    local suffix
    suffix=$(format_duration "$duration_s")
    [[ -n "$num_turns" && "$num_turns" != "null" ]] && suffix="${suffix} ${SYM_DOT} ${num_turns} turns"
    [[ -n "$cost" && "$cost" != "null" && "${VERBOSITY:-1}" -ge 2 ]] && suffix="${suffix} ${SYM_DOT} \$${cost}"
    _progress_finish_line "$SYM_CHECK" "$COLOR_SUCCESS" "$suffix"
}

# Call on failure.
# Args: error_message [duration_s]
progress_error() {
    local error_msg="$1"
    local duration_s="${2:-}"
    local suffix="$error_msg"
    [[ -n "$duration_s" ]] && suffix="${suffix}  $(format_duration "$duration_s")"
    _progress_finish_line "$SYM_CROSS" "$COLOR_ERROR" "$suffix"
}

# ── Helpers ─────────────────────────────────────────────────────

# Extract a human-readable detail from a tool_use input.
_extract_tool_detail() {
    local json_line="$1" tool_name="$2"
    local detail=""

    case "$tool_name" in
        Read)
            detail=$(echo "$json_line" | jq -r '
                .message.content[]? | select(.type == "tool_use" and .name == "Read") |
                .input.file_path // empty
            ' 2>/dev/null)
            # Shorten to relative path
            if [[ -n "$detail" && -n "${PROJECT_ROOT:-}" ]]; then
                detail="${detail#${PROJECT_ROOT}/}"
            fi
            ;;
        Bash)
            detail=$(echo "$json_line" | jq -r '
                .message.content[]? | select(.type == "tool_use" and .name == "Bash") |
                .input.command // empty
            ' 2>/dev/null)
            # Truncate long commands
            if [[ ${#detail} -gt 60 ]]; then
                detail="${detail:0:57}..."
            fi
            ;;
        Grep)
            detail=$(echo "$json_line" | jq -r '
                .message.content[]? | select(.type == "tool_use" and .name == "Grep") |
                .input.pattern // empty
            ' 2>/dev/null)
            ;;
        Glob)
            detail=$(echo "$json_line" | jq -r '
                .message.content[]? | select(.type == "tool_use" and .name == "Glob") |
                .input.pattern // empty
            ' 2>/dev/null)
            ;;
        Edit|Write)
            detail=$(echo "$json_line" | jq -r '
                .message.content[]? | select(.type == "tool_use" and .name == "'"$tool_name"'") |
                .input.file_path // empty
            ' 2>/dev/null)
            if [[ -n "$detail" && -n "${PROJECT_ROOT:-}" ]]; then
                detail="${detail#${PROJECT_ROOT}/}"
            fi
            ;;
        *)
            detail=$(echo "$json_line" | jq -r '
                .message.content[]? | select(.type == "tool_use" and .name == "'"$tool_name"'") |
                .input | to_entries[0].value // empty
            ' 2>/dev/null)
            if [[ ${#detail} -gt 50 ]]; then
                detail="${detail:0:47}..."
            fi
            ;;
    esac

    echo "$detail"
}
