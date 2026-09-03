#!/usr/bin/env bash
# config.sh — Shared constants, paths, defaults, exit codes

set -euo pipefail

# ── Paths ────────────────────────────────────────────────────────
SPEED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export SPEED_DIR    # Available to Python subprocesses
PROJECT_ROOT="${SPEED_PROJECT_ROOT:-$(pwd)}"
LIB_DIR="${SPEED_DIR}/lib"
AGENTS_DIR="${SPEED_DIR}/agents"
TEMPLATES_DIR="${SPEED_DIR}/templates"

STATE_DIR="${PROJECT_ROOT}/.speed"
FEATURES_DIR="${STATE_DIR}/features"
# Resolve agent instructions file.
# Priority: env var > speed.toml > auto-detect > none (speed project init creates one)
AGENT_FILE="${SPEED_AGENT_FILE:-${TOML_PROJECT_AGENT_FILE:-}}"

if [[ -z "$AGENT_FILE" ]]; then
    if [[ -f "${PROJECT_ROOT}/AGENTS.md" ]]; then
        AGENT_FILE="AGENTS.md"
    elif [[ -f "${PROJECT_ROOT}/CLAUDE.md" ]]; then
        AGENT_FILE="CLAUDE.md"
    fi
fi

if [[ -n "$AGENT_FILE" ]] && [[ "$AGENT_FILE" == */* ]]; then
    echo "Error: SPEED_AGENT_FILE must be a filename, not a path: '${AGENT_FILE}'" >&2
    exit "${EXIT_CONFIG_ERROR:-3}"
fi

AGENT_FILE_PATH="${AGENT_FILE:+${PROJECT_ROOT}/${AGENT_FILE}}"
export SPEED_AGENT_FILE="${AGENT_FILE:-}"

# ── Multi-player zone paths (populated after mp-init) ──────────────
LOCAL_DIR="${STATE_DIR}/local"
SHARED_DIR="${STATE_DIR}/shared"
CONTEXT_DIR="${STATE_DIR}/context"
EVENTS_DIR="${SHARED_DIR}/events"
ROSTER_DIR="${SHARED_DIR}/roster"
PROPOSALS_DIR="${SHARED_DIR}/proposals"
SHARED_KNOWLEDGE_DIR="${SHARED_DIR}/knowledge"
SHARED_FEATURES_DIR="${SHARED_DIR}/features"

# ── Feature-scoped paths (defaults — overridden by feature_activate) ──
# Commands that require a feature call feature_activate() which updates
# these globals to point at the feature's namespace directory.
TASKS_DIR="${STATE_DIR}/tasks"
LOGS_DIR="${STATE_DIR}/logs"
WORKTREES_DIR="${STATE_DIR}/worktrees"
STATE_FILE="${STATE_DIR}/state.json"
CONTRACT_FILE="${STATE_DIR}/contract.json"
FEATURE_NAME=""
FEATURE_DIR=""

# ── Read speed.toml (if present) ──────────────────────────────────
# Note: colors.sh isn't sourced yet, so use plain echo for warnings.
SPEED_TOML="${PROJECT_ROOT}/speed.toml"
if [[ -f "$SPEED_TOML" ]]; then
    if ! command -v python3 &>/dev/null; then
        echo "Warning: python3 not found — speed.toml ignored, using defaults" >&2
    else
        _toml_err_file=$(mktemp "${TMPDIR:-/tmp}/_speed_toml_XXXXXX")
        _toml_rc=0
        _toml_out=$(python3 "${LIB_DIR}/toml.py" "$SPEED_TOML" 2>"$_toml_err_file") || _toml_rc=$?
        _toml_err=$(cat "$_toml_err_file" 2>/dev/null)
        rm -f "$_toml_err_file"

        if [[ $_toml_rc -ne 0 ]]; then
            echo "Error: could not parse ${SPEED_TOML}${_toml_err:+: ${_toml_err}}" >&2
            exit "${EXIT_CONFIG_ERROR:-3}"
        elif [[ -n "$_toml_err" ]]; then
            echo "Warning: ${_toml_err}" >&2
            eval "$_toml_out"
        else
            eval "$_toml_out"
        fi
        unset _toml_out _toml_err _toml_err_file _toml_rc
    fi
fi

# ── PATH ──────────────────────────────────────────────────────────
export PATH="${PATH}:${HOME}/.local/bin"

# ── Defaults (env > toml > built-in) ─────────────────────────────
DEFAULT_MAX_PARALLEL=3
DEFAULT_AGENT_TIMEOUT="${SPEED_TIMEOUT:-${TOML_AGENT_TIMEOUT:-600}}"
AGENT_KILL_GRACE=10          # seconds after SIGTERM before SIGKILL
BRANCH_PREFIX="speed"

# ── Model Tiers ──────────────────────────────────────────────────
# Planning tier: high-stakes reasoning where quality cascades.
#   Used by: architect, plan verifier, coherence checker
MODEL_PLANNING="${SPEED_PLANNING_MODEL:-${TOML_AGENT_PLANNING_MODEL:-opus}}"

# Support tier: structured tasks applying frameworks to known inputs.
#   Used by: debugger, supervisor, guardian, reviewer, validator, integrator
MODEL_SUPPORT="${SPEED_SUPPORT_MODEL:-${TOML_AGENT_SUPPORT_MODEL:-sonnet}}"

# Developer tier: set per-task by the architect, defaults to MODEL_SUPPORT.
#   Escalated automatically by timeout (sonnet → opus).

# ── Agent Turns ──────────────────────────────────────────────────
DEFAULT_MAX_TURNS="${SPEED_MAX_TURNS:-${TOML_AGENT_MAX_TURNS:-50}}"
DEFAULT_JSON_MAX_TURNS=3       # max turns for simple JSON-producing agents
ARCHITECT_MAX_TURNS=30         # architect needs many turns for large specs

# ── Architect Timeout Scaling ────────────────────────────────────
ARCHITECT_TIMEOUT_BASE=300          # base seconds before token scaling
ARCHITECT_TIMEOUT_PER_1K_TOKENS=12  # additional seconds per 1K input tokens
ARCHITECT_TIMEOUT_MAX=1800           # hard cap (30 minutes)
ARCHITECT_TIMEOUT_MIN=900            # floor (15 minutes)
ARCHITECT_TIMEOUT_PHASED_MIN=900     # floor for phased plans (large specs by definition)

# ── Agent Tool Sets ──────────────────────────────────────────────
AGENT_TOOLS_FULL="Bash Edit Read Write Glob Grep"
AGENT_TOOLS_WRITE="Read Write Glob"
AGENT_TOOLS_READONLY="Read Glob Grep"

# ── Orchestration Tuning ─────────────────────────────────────────
POLL_INTERVAL=5                # seconds between main loop iterations
COMPLETION_FLUSH_WAIT=1        # seconds to wait for file writes after completion
STALE_STATE_PAUSE=3            # seconds to pause on stale state warning
HALT_FAILURE_PCT=30            # halt SPEED if this % of tasks fail
PATTERN_FAILURE_THRESHOLD=3    # invoke supervisor after this many failures
ARCHITECT_PHASE_TASK_THRESHOLD=10   # phase the architect when audit estimates more tasks
MAX_VERIFY_FIX_ITERATIONS=3    # max fix → re-verify cycles in speed verify
MERGE_CONFLICT_MAX_RETRIES=3   # max merge-conflict retries before blocking task

# ── Context Limits ───────────────────────────────────────────────
AGENT_OUTPUT_TAIL=1000         # lines of agent output to send to debugger
DIFF_HEAD_LINES=500            # lines of diff to send to debugger/reviewer

# ── Token Budget & Rate Limiting ─────────────────────────────────
TPM_BUDGET="${SPEED_TPM_BUDGET:-${TOML_RATE_TPM_BUDGET:-200000}}"    # tokens per minute
RPM_BUDGET="${SPEED_RPM_BUDGET:-${TOML_RATE_RPM_BUDGET:-5}}"         # requests per minute
RATE_LIMIT_MAX_RETRIES=3       # max retries on rate limit error
RATE_LIMIT_BASE_DELAY=60       # base delay in seconds for exponential backoff
RATE_LIMIT_MAX_DELAY=300       # max delay cap (5 minutes)

# ── Vision File ──────────────────────────────────────────────────
VISION_FILE="${TOML_SPECS_VISION_FILE:-specs/product/overview.md}"

# ── Log Retention ───────────────────────────────────────────────
LOG_RETAIN_PER_CATEGORY=3      # keep last N logs per category (gate, supervisor, etc.)

# ── Verbosity ──────────────────────────────────────────────────
# Resolved later by flag parsing (--quiet/--verbose/--debug).
# Set default here; flags override in speed/speed main().
VERBOSITY="${SPEED_VERBOSITY:-${TOML_UI_VERBOSITY:-1}}"

# ── Exit Codes ─────────────────────────────────────────────────
EXIT_OK=0
EXIT_TASK_FAILURE=1       # one or more tasks failed
EXIT_GATE_FAILURE=2       # quality gates failed
EXIT_CONFIG_ERROR=3       # bad config, missing binary, missing file
EXIT_MERGE_CONFLICT=4     # integration merge conflict
EXIT_HALTED=5             # >30% tasks failed, supervisor halted
EXIT_USER_ABORT=130       # Ctrl+C (convention: 128 + SIGINT)

# ── Colors & Symbols (delegated to colors.sh) ─────────────────
source "${LIB_DIR}/colors.sh"
