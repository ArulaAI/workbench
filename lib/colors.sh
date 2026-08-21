#!/usr/bin/env bash
# colors.sh — Color/theme system with NO_COLOR support and semantic layers
#
# Supports:
#   - NO_COLOR standard (https://no-color.org/)
#   - Semantic color aliases (COLOR_SUCCESS, COLOR_ERROR, etc.)
#   - Colorblind theme (SPEED_THEME=colorblind or [ui].theme = "colorblind")
#   - ASCII symbol fallback (SPEED_ASCII=true or [ui].ascii = true)
#
# Requires: TOML_UI_THEME, TOML_UI_ASCII may be set by config.sh before sourcing.

# ── Raw ANSI colors ───────────────────────────────────────────────
# Disabled when: NO_COLOR is set (any value), or either stdout/stderr is not a tty.

if [[ -z "${NO_COLOR:-}" ]] && [[ -t 1 ]] && [[ -t 2 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    MAGENTA='\033[0;35m'
    CYAN='\033[0;36m'
    WHITE='\033[1;37m'
    DIM='\033[0;90m'
    BOLD='\033[1m'
    RESET='\033[0m'
    # Extended colors for colorblind theme
    BRIGHT_RED='\033[1;31m'
    ORANGE='\033[0;33m'  # closest ANSI to orange (same as yellow)
else
    RED='' GREEN='' YELLOW='' BLUE='' MAGENTA='' CYAN='' WHITE='' DIM='' BOLD='' RESET=''
    BRIGHT_RED='' ORANGE=''
fi

# ── Semantic color layer ──────────────────────────────────────────
# Resolve theme: env > toml > default
_SPEED_THEME="${SPEED_THEME:-${TOML_UI_THEME:-default}}"

case "$_SPEED_THEME" in
    colorblind)
        COLOR_SUCCESS="$BLUE"
        COLOR_ERROR="${BRIGHT_RED}"
        COLOR_WARN="$ORANGE"
        COLOR_INFO="$CYAN"
        COLOR_STEP="$CYAN"
        COLOR_HEADER="$WHITE"
        COLOR_ACCENT="$MAGENTA"
        COLOR_DIM="$DIM"
        ;;
    *)
        COLOR_SUCCESS="$GREEN"
        COLOR_ERROR="$RED"
        COLOR_WARN="$YELLOW"
        COLOR_INFO="$BLUE"
        COLOR_STEP="$CYAN"
        COLOR_HEADER="$WHITE"
        COLOR_ACCENT="$MAGENTA"
        COLOR_DIM="$DIM"
        ;;
esac

# ── Symbols ───────────────────────────────────────────────────────
# Resolve ASCII mode: env > toml > default (Unicode)
_SPEED_ASCII="${SPEED_ASCII:-${TOML_UI_ASCII:-false}}"

if [[ "$_SPEED_ASCII" == "true" ]]; then
    SYM_CHECK="[ok]"
    SYM_CROSS="[FAIL]"
    SYM_ARROW="->"
    SYM_DOT="*"
    SYM_PENDING="o"
    SYM_RUNNING="@"
    SYM_WARN="[!]"
else
    SYM_CHECK="✓"
    SYM_CROSS="✗"
    SYM_ARROW="→"
    SYM_DOT="●"
    SYM_PENDING="○"
    SYM_RUNNING="◉"
    SYM_WARN="⚠"
fi
