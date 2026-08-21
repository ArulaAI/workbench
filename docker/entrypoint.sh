#!/bin/bash
# entrypoint.sh — One-command SPEED pipeline runner
#
# Problem: A developer has a repo and a feature. They run one command and
# get working code. The container handles the full pipeline, and critically,
# it handles every failure the pipeline catches. SPEED's quality gates
# (spec audits, plan verification, grounding checks, code review, coherence)
# catch real problems. The orchestrator reads those failures, diagnoses
# the root cause, fixes it, and retries. That catch-diagnose-fix-retry
# loop is what makes it hands-free.
#
# Architecture:
#   1. Pre-baked image: SPEED, deps, grammars, provider CLIs all ready
#   2. This entrypoint: clones repo, handles auth
#   3. Provider CLI launches interactively: same TUI the user knows,
#      full progress visibility, pipeline instructions pre-loaded
#      via system prompt. The user watches it work.

set -euo pipefail

# ── Required inputs ──────────────────────────────────────────
if [[ -z "${REPO_URL:-}" || -z "${FEATURE:-}" ]]; then
    cat <<'MSG'

  ┌──────────────────────────────────────────────────────┐
  │  Usage:                                              │
  │                                                      │
  │  docker run -it --rm \                               │
  │    -e REPO_URL="https://github.com/org/repo" \       │
  │    -e FEATURE="Add dark mode toggle" \               │
  │    speed                                             │
  │                                                      │
  │  Local repo:                                         │
  │    -v ~/code/myproject:/work/myproject \              │
  │    -e REPO_URL=/work/myproject                       │
  │                                                      │
  │  Private repo:                                       │
  │    -e GIT_TOKEN=ghp_... \                            │
  │    -e REPO_URL="https://github.com/org/private"      │
  │                                                      │
  │  FEATURE can be a text description, a GitHub         │
  │  issue URL, or a path to a mounted spec file.        │
  │                                                      │
  │  Auth: log in interactively on first run, or pass    │
  │  an API key (-e ANTHROPIC_API_KEY or OPENAI_API_KEY) │
  └──────────────────────────────────────────────────────┘

MSG
    exit 1
fi

# ── Provider detection ───────────────────────────────────────
# Finds the first authenticated provider CLI. Supports Claude Code,
# Codex, or any custom CLI set via ORCHESTRATOR_CMD.
#
# The provider runs interactively with the pipeline prompt loaded
# as system context. The user sees the normal TUI.

_is_claude_authed() {
    command -v claude &>/dev/null || return 1
    if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then return 0; fi
    echo "say ok" | claude -p --max-turns 1 &>/dev/null 2>&1
}

_is_codex_authed() {
    command -v codex &>/dev/null && [[ -n "${OPENAI_API_KEY:-}" ]]
}

_detect_provider() {
    # User override
    if [[ -n "${ORCHESTRATOR_CMD:-}" ]]; then
        echo "custom"
        return 0
    fi
    if _is_claude_authed; then
        echo "claude"
        return 0
    fi
    if _is_codex_authed; then
        echo "codex"
        return 0
    fi
    return 1
}

PROVIDER=$(_detect_provider) || {
    # No auth found — attempt interactive login if TTY available
    if [[ ! -t 0 ]]; then
        cat <<'MSG'

  ┌──────────────────────────────────────────────────────┐
  │  No authenticated provider detected.                 │
  │                                                      │
  │  Run with -it to log in interactively:               │
  │    docker run -it --rm ...                           │
  │                                                      │
  │  Or pass an API key:                                 │
  │    -e ANTHROPIC_API_KEY=sk-ant-...                   │
  │    -e OPENAI_API_KEY=sk-...                          │
  └──────────────────────────────────────────────────────┘

MSG
        exit 1
    fi

    # Try interactive login with whatever CLI is available
    if command -v claude &>/dev/null; then
        echo ""
        echo "  No credentials found. Opening Claude Code for login."
        echo "  After you authenticate, type /exit to continue."
        echo ""
        claude || true
    fi

    PROVIDER=$(_detect_provider) || {
        echo "  Authentication failed. Exiting."
        exit 1
    }
}

echo "Provider: ${PROVIDER}"

# ── Get the target repo ──────────────────────────────────────
# Three modes:
#   1. Local mount:  -v /path/to/repo:/work/repo  (REPO_URL=/work/repo)
#   2. Private repo: -e GIT_TOKEN=ghp_...  (inserted into HTTPS URL)
#   3. Public repo:  just REPO_URL
GIT_NAME="${GIT_NAME:-SPEED Agent}"
GIT_EMAIL="${GIT_EMAIL:-speed@localhost}"

if [[ -d "$REPO_URL" ]]; then
    # Local path — already mounted into the container
    cd "$REPO_URL"
    REPO_NAME=$(basename "$REPO_URL")
    echo "Using mounted repo at ${REPO_URL}"
else
    REPO_NAME=$(basename "$REPO_URL" .git)
    echo "Cloning ${REPO_URL}..."
    if [[ -n "${GIT_TOKEN:-}" ]]; then
        AUTHED_URL=$(echo "$REPO_URL" | sed "s|https://|https://${GIT_TOKEN}@|")
        git clone "$AUTHED_URL" "/work/${REPO_NAME}" 2>&1
    else
        git clone "$REPO_URL" "/work/${REPO_NAME}" 2>&1
    fi
    cd "/work/${REPO_NAME}"
fi

git config user.name "$GIT_NAME"
git config user.email "$GIT_EMAIL"

echo ""
echo "  Repo:    $(pwd)"
echo "  Feature: ${FEATURE}"
echo ""

# ── Launch the orchestrator ──────────────────────────────────
SYSTEM_PROMPT=$(cat /opt/speed/docker/orchestrator.md)
USER_PROMPT="Implement this feature using SPEED: ${FEATURE}"

case "$PROVIDER" in
    claude)
        exec claude \
            --permission-mode auto \
            --allowedTools "Bash Edit Read Write Glob Grep WebFetch WebSearch Agent" \
            --append-system-prompt "${SYSTEM_PROMPT}" \
            "${USER_PROMPT}"
        ;;
    codex)
        exec codex \
            --approval-mode auto-edit \
            "${SYSTEM_PROMPT}"$'\n\n'"${USER_PROMPT}"
        ;;
    custom)
        exec $ORCHESTRATOR_CMD "${SYSTEM_PROMPT}"$'\n\n'"${USER_PROMPT}"
        ;;
esac
