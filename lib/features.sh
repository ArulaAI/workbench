#!/usr/bin/env bash
# features.sh — Feature namespace management
#
# SPEED supports running multiple features in parallel. Each feature
# gets isolated state: tasks, logs, contract, spec_path, worktrees.
#
# Directory layout:
#   .speed/
#     active_feature        ← name of the last-planned feature
#     features/
#       auth/
#         tasks/            ← task DAG files
#         logs/             ← agent output, gate logs, debugger, etc.
#         contract.json     ← schema contract from architect
#         spec_path         ← path to the source spec file
#         state.json        ← runtime state (idle/running)
#         failure_history.jsonl
#       billing/
#         ...
#     worktrees/
#       auth/               ← git worktrees for auth tasks
#       billing/            ← git worktrees for billing tasks
#
# Branch naming: speed/{feature}/task-{id}-{slug}
#
# Requires config.sh and log.sh to be sourced first

# ── Derive feature name from a spec file path ────────────────────
# specs/tech/auth.md → auth
# specs/product/billing.md → billing
# /absolute/path/to/my-feature.md → my-feature

feature_name_from_spec() {
    local spec_file="$1"
    basename "$spec_file" .md
}

# ── Activate a feature: override global paths ────────────────────
# After this call, TASKS_DIR, LOGS_DIR, CONTRACT_FILE, BRANCH_PREFIX,
# WORKTREES_DIR, and STATE_FILE all point at the feature's namespace.
# Existing code uses these globals unchanged.

feature_activate() {
    local name="$1"

    FEATURE_NAME="$name"
    BRANCH_PREFIX="speed/${name}"

    if [[ "${MP_ENABLED:-}" == "true" ]]; then
        # Multi-player: shared paths for team-visible state
        FEATURE_DIR="${SHARED_FEATURES_DIR}/${name}"
        TASKS_DIR="${FEATURE_DIR}/tasks"
        CONTRACT_FILE="${FEATURE_DIR}/contract.json"
        # Local paths for per-machine runtime state
        LOGS_DIR="${LOCAL_DIR}/features/${name}/logs"
        WORKTREES_DIR="${LOCAL_DIR}/worktrees/${name}"
        STATE_FILE="${LOCAL_DIR}/features/${name}/state.json"
        SPEED_LOCK="${LOCAL_DIR}/locks/${name}.lock"
    else
        # Single-player: everything under .speed/features/
        FEATURE_DIR="${FEATURES_DIR}/${name}"
        TASKS_DIR="${FEATURE_DIR}/tasks"
        LOGS_DIR="${FEATURE_DIR}/logs"
        CONTRACT_FILE="${FEATURE_DIR}/contract.json"
        STATE_FILE="${FEATURE_DIR}/state.json"
        WORKTREES_DIR="${STATE_DIR}/worktrees/${name}"
        SPEED_LOCK="${FEATURE_DIR}/speed.lock"
    fi

    mkdir -p "$TASKS_DIR" "$LOGS_DIR"

    # Initialize state file if it doesn't exist
    if [[ ! -f "$STATE_FILE" ]]; then
        mkdir -p "$(dirname "$STATE_FILE")"
        echo '{"status":"idle","agents":[],"started_at":null}' | jq '.' > "$STATE_FILE"
    fi
}

# ── Set the active feature (persisted across commands) ───────────

feature_set_active() {
    local name="$1"
    if [[ "${MP_ENABLED:-}" == "true" ]]; then
        echo "$name" > "${SHARED_DIR}/active_feature"
    else
        echo "$name" > "${STATE_DIR}/active_feature"
    fi
}

# ── Get the active feature name (or empty string) ────────────────

feature_get_active() {
    if [[ "${MP_ENABLED:-}" == "true" ]]; then
        if [[ -f "${SHARED_DIR}/active_feature" ]]; then
            cat "${SHARED_DIR}/active_feature"
        fi
    else
        if [[ -f "${STATE_DIR}/active_feature" ]]; then
            cat "${STATE_DIR}/active_feature"
        fi
    fi
}

# ── Resolve which feature to use ─────────────────────────────────
# Priority: explicit flag → active feature → single feature auto-detect
# Returns: feature name on stdout
# Exit code: 0 = resolved, 1 = ambiguous/none

feature_resolve() {
    local explicit="${1:-}"
    local feat_root="$FEATURES_DIR"
    [[ "${MP_ENABLED:-}" == "true" ]] && feat_root="$SHARED_FEATURES_DIR"

    # 1. Explicit flag
    if [[ -n "$explicit" ]]; then
        if [[ -d "${feat_root}/${explicit}" ]]; then
            echo "$explicit"
            return 0
        else
            log_error "Feature '${explicit}' not found in ${feat_root}/"
            return 1
        fi
    fi

    # 2. Active feature
    local active
    active=$(feature_get_active)
    if [[ -n "$active" ]] && [[ -d "${feat_root}/${active}" ]]; then
        echo "$active"
        return 0
    fi

    # 3. Auto-detect: exactly one feature → use it
    if [[ -d "$feat_root" ]]; then
        local features
        features=$(ls -1 "$feat_root" 2>/dev/null || true)
        if [[ -n "$features" ]]; then
            local count
            count=$(echo "$features" | wc -l | tr -d ' ')
            if [[ "$count" -eq 1 ]]; then
                echo "$features"
                return 0
            fi
        fi
    fi

    return 1
}

# ── List all feature names ───────────────────────────────────────

feature_list() {
    local feat_root="$FEATURES_DIR"
    [[ "${MP_ENABLED:-}" == "true" ]] && feat_root="$SHARED_FEATURES_DIR"
    if [[ -d "$feat_root" ]]; then
        ls -1 "$feat_root" 2>/dev/null || true
    fi
}

# ── Require a feature to be active ───────────────────────────────
# Resolves and activates. On failure, prints error with available features.
# Args: [explicit_feature_name]

_require_feature() {
    local explicit="${1:-}"
    local feature_name

    if feature_name=$(feature_resolve "$explicit"); then
        feature_activate "$feature_name"
        # In multi-player mode, check ownership
        if [[ "${MP_ENABLED:-}" == "true" ]]; then
            local _orc=0
            ownership_check "$feature_name" || _orc=$?
            if [[ $_orc -eq 1 ]]; then
                log_error "Feature '${feature_name}' is claimed by ${OWNERSHIP_OWNER}"
                log_error "Run 'speed claim ${feature_name}' after they release it"
                exit 1
            elif [[ $_orc -eq 2 ]]; then
                log_warn "Feature '${feature_name}' is unclaimed. Run 'speed claim ${feature_name}' to take ownership."
            fi
        fi
        return 0
    fi

    log_error "No feature context. Use --feature <name> or run 'speed plan' first."
    echo ""
    local features
    features=$(feature_list)
    if [[ -n "$features" ]]; then
        local active
        active=$(feature_get_active)
        echo "Available features:"
        while IFS= read -r f; do
            local marker=""
            if [[ "$f" == "$active" ]]; then
                marker=" ${COLOR_SUCCESS}(active)${RESET}"
            fi
            echo -e "  - ${COLOR_STEP}${f}${RESET}${marker}"
        done <<< "$features"
    else
        echo "No features found. Run: speed plan <spec-file>"
    fi
    exit 1
}
