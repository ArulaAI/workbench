#!/usr/bin/env bash

# The Sessionizer: fzf-powered project switcher
# Jumps between ~/Documents/code and identifying the current project

if [[ $# -eq 1 ]]; then
    selected=$1
else
    # Dynamically resolve paths relative to this script
    PROJECT_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
    
    SEARCH_DIRS=(
        "$PROJECT_ROOT"
        "$(cd "$PROJECT_ROOT/.." && pwd)" # Also check for sibling projects/worktrees
    )

    selected=$(find "${SEARCH_DIRS[@]}" -mindepth 1 -maxdepth 2 -type d 2>/dev/null | fzf)
fi

if [[ -z $selected ]]; then
    exit 0
fi

selected_name=$(basename "$selected" | tr . _)
tmux_running=$(pgrep tmux)

if [[ -z $TMUX ]] && [[ -z $tmux_running ]]; then
    tmux new-session -s "$selected_name" -c "$selected"
    exit 0
fi

if ! tmux has-session -t="$selected_name" 2> /dev/null; then
    tmux new-session -ds "$selected_name" -c "$selected"
fi

tmux switch-client -t "$selected_name"
