#!/usr/bin/env bash
# log.sh — Timestamped logging with verbosity levels
#
# Verbosity levels:
#   0 (quiet)   — errors, final result only
#   1 (normal)  — errors, warnings, steps, headers, success (default)
#   2 (verbose) — + info details, gate details, agent commands
#   3 (debug)   — + internal state, timing, PID tracking
#
# Requires config.sh (and colors.sh) to be sourced first.
# VERBOSITY is set in config.sh (env > toml > default=1).

# ── JSON output mode ──────────────────────────────────────────────
# When JSON_OUTPUT=true, all log output goes to stderr so stdout
# remains clean for the final JSON blob.
JSON_OUTPUT="${JSON_OUTPUT:-false}"

_log_fd() {
    # Returns the file descriptor for normal (non-error) log output.
    # In JSON mode, everything goes to stderr to keep stdout clean.
    if [[ "$JSON_OUTPUT" == "true" ]]; then
        echo 2
    else
        echo 1
    fi
}

_log_timestamp() {
    date '+%H:%M:%S'
}

# ── Level 0: always shown ────────────────────────────────────────

log_error() {
    echo -e "${COLOR_DIM}[$(_log_timestamp)]${RESET} ${COLOR_ERROR}${SYM_CROSS} err${RESET}   $*" >&2
}

log_result() {
    # Final output — no timestamp prefix, always shown.
    local fd
    fd=$(_log_fd)
    echo -e "$*" >&"$fd"
}

# ── Level 1: normal (default) ────────────────────────────────────

log_warn() {
    [[ "${VERBOSITY:-1}" -ge 1 ]] || return 0
    echo -e "${COLOR_DIM}[$(_log_timestamp)]${RESET} ${COLOR_WARN}${SYM_WARN} warn${RESET}  $*" >&2
}

log_success() {
    [[ "${VERBOSITY:-1}" -ge 1 ]] || return 0
    local fd
    fd=$(_log_fd)
    echo -e "${COLOR_DIM}[$(_log_timestamp)]${RESET} ${COLOR_SUCCESS}${SYM_CHECK}${RESET}     $*" >&"$fd"
}

log_step() {
    [[ "${VERBOSITY:-1}" -ge 1 ]] || return 0
    local fd
    fd=$(_log_fd)
    echo -e "${COLOR_DIM}[$(_log_timestamp)]${RESET} ${COLOR_STEP}${SYM_ARROW}${RESET}     $*" >&"$fd"
}

log_header() {
    [[ "${VERBOSITY:-1}" -ge 1 ]] || return 0
    local fd
    fd=$(_log_fd)
    echo "" >&"$fd"
    echo -e "${BOLD}${COLOR_HEADER}$*${RESET}" >&"$fd"
    echo -e "${COLOR_DIM}$(printf '─%.0s' $(seq 1 60))${RESET}" >&"$fd"
}

log_info() {
    [[ "${VERBOSITY:-1}" -ge 1 ]] || return 0
    local fd
    fd=$(_log_fd)
    echo -e "${COLOR_DIM}[$(_log_timestamp)]${RESET} ${COLOR_INFO}info${RESET}  $*" >&"$fd"
}

# ── Level 2: verbose ─────────────────────────────────────────────

log_verbose() {
    [[ "${VERBOSITY:-1}" -ge 2 ]] || return 0
    local fd
    fd=$(_log_fd)
    echo -e "${COLOR_DIM}[$(_log_timestamp)] ···${RESET}  $*" >&"$fd"
}

# ── Level 3: debug ───────────────────────────────────────────────

log_debug() {
    [[ "${VERBOSITY:-1}" -ge 3 ]] || return 0
    local fd
    fd=$(_log_fd)
    echo -e "${COLOR_DIM}[$(_log_timestamp)] dbg  $*${RESET}" >&"$fd"
}

# ── Structured error block ────────────────────────────────────────
# Provides actionable what/why/fix output for common failures.

log_error_block() {
    local what="$1" why="$2" fix="$3"
    echo "" >&2
    echo -e "  ${COLOR_ERROR}${SYM_CROSS} ${what}${RESET}" >&2
    echo -e "  ${COLOR_DIM}Why: ${why}${RESET}" >&2
    echo -e "  ${COLOR_STEP}Fix: ${fix}${RESET}" >&2
    echo "" >&2
}

# ── Helpers ───────────────────────────────────────────────────────

# Format seconds into human-readable duration: 90 → "1m30s", 3661 → "1h1m1s"
format_duration() {
    local total="${1:-0}"
    local h=$((total / 3600))
    local m=$(( (total % 3600) / 60 ))
    local s=$((total % 60))

    if [[ $h -gt 0 ]]; then
        echo "${h}h${m}m${s}s"
    elif [[ $m -gt 0 ]]; then
        echo "${m}m${s}s"
    else
        echo "${s}s"
    fi
}

# Log to file (for agent session logs)
log_to_file() {
    local file="$1"
    shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$file"
}
