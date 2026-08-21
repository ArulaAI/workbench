#!/usr/bin/env bash
# actor.sh — Actor identity for multi-player mode
#
# Resolution order: $SPEED_ACTOR env → git config user.name → $(whoami)
# Cached after first resolution for the duration of the process.
#
# Requires: config.sh

_ACTOR_CACHE=""

# Resolve the current actor name.
# Returns the display name (may contain spaces, mixed case).
actor_resolve() {
    if [[ -n "${SPEED_ACTOR:-}" ]]; then
        echo "$SPEED_ACTOR"
        return 0
    fi

    local name
    name=$(git config user.name 2>/dev/null || true)
    if [[ -n "$name" ]]; then
        echo "$name"
        return 0
    fi

    whoami
}

# Convert a display name to a filesystem-safe slug.
# Lowercase, hyphens instead of spaces, no special chars.
actor_slug() {
    local name="${1:-}"
    [[ -z "$name" ]] && name=$(actor_get)
    echo "$name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | sed 's/[^a-z0-9-]//g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//'
}

# Return cached actor name. Resolves on first call.
actor_get() {
    if [[ -z "$_ACTOR_CACHE" ]]; then
        _ACTOR_CACHE=$(actor_resolve)
    fi
    echo "$_ACTOR_CACHE"
}

_ACTOR_EMAIL_CACHE=""

# Resolve the current actor's email address.
# Resolution order: $SPEED_ACTOR_EMAIL env → git config user.email → {name}@local
# Never fails. Always returns a string containing @.
actor_email_resolve() {
    if [[ -n "${SPEED_ACTOR_EMAIL:-}" ]]; then
        echo "$SPEED_ACTOR_EMAIL"
        return 0
    fi

    local email
    email=$(git config user.email 2>/dev/null || true)
    if [[ -n "$email" ]]; then
        echo "$email"
        return 0
    fi

    echo "$(actor_get)@local"
}

# Return cached actor email. Resolves on first call.
actor_email_get() {
    if [[ -z "$_ACTOR_EMAIL_CACHE" ]]; then
        _ACTOR_EMAIL_CACHE=$(actor_email_resolve)
    fi
    echo "$_ACTOR_EMAIL_CACHE"
}
