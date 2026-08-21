#!/usr/bin/env bash
# mp_init.sh — Initialize multi-player mode for an existing SPEED project
#
# Creates the shared/local directory split, migrates existing state,
# and updates .gitignore so shared/ is trackable and local/ is ignored.

# Move logs/ and state.json from shared/features/ to local/features/.
# Handles both fresh migration and repair of previously botched init.
_mp_repair_zones() {
    local shared_dir="$1"
    local local_dir="$2"
    local repaired=0

    for feat_dir in "${shared_dir}/features"/*/; do
        [[ -d "$feat_dir" ]] || continue
        local feat_name
        feat_name=$(basename "$feat_dir")
        local local_feat="${local_dir}/features/${feat_name}"

        # Move logs/ to local if sitting in shared
        if [[ -d "${feat_dir}/logs" ]]; then
            mkdir -p "${local_feat}"
            if [[ -d "${local_feat}/logs" ]]; then
                # Merge: move individual files, skip conflicts
                for logfile in "${feat_dir}/logs"/*; do
                    [[ -e "$logfile" ]] || continue
                    local base
                    base=$(basename "$logfile")
                    [[ ! -e "${local_feat}/logs/${base}" ]] && mv "$logfile" "${local_feat}/logs/${base}"
                done
                rmdir "${feat_dir}/logs" 2>/dev/null || true
            else
                mv "${feat_dir}/logs" "${local_feat}/logs"
            fi
            ((repaired++)) || true
        fi

        # Move state.json to local if sitting in shared
        if [[ -f "${feat_dir}/state.json" ]]; then
            mkdir -p "${local_feat}"
            if [[ ! -f "${local_feat}/state.json" ]]; then
                mv "${feat_dir}/state.json" "${local_feat}/state.json"
            else
                mv "${feat_dir}/state.json" "${local_feat}/state.json.from-shared"
            fi
            ((repaired++)) || true
        fi
    done

    if [[ $repaired -gt 0 ]]; then
        log_step "Repaired ${repaired} zone violation(s): moved logs/state from shared → local"
    fi
}

cmd_mp_init() {
    if [[ ! -d "$STATE_DIR" ]]; then
        log_error "No .speed/ directory found. Run 'speed init' first."
        exit 1
    fi

    local shared_dir="${STATE_DIR}/shared"
    local local_dir="${STATE_DIR}/local"

    if mp_is_enabled; then
        log_info "Multi-player mode already initialized — checking zone integrity..."
        mkdir -p "${local_dir}/features"
        _mp_repair_zones "$shared_dir" "$local_dir"

        # Ensure roster and event exist even on repair runs
        MP_ENABLED=true
        _SPEED_CURRENT_COMMAND="mp-init"
        if [[ ! -f "$(mp_roster_dir)/$(actor_slug).json" ]]; then
            roster_heartbeat
            log_step "Wrote missing roster entry"
        fi

        # Emit init event if none exists (original init may have failed to write one)
        local events_dir
        events_dir=$(mp_events_dir)
        local has_init_event=false
        for f in "${events_dir}"/*system-initialized*.jsonl; do
            [[ -f "$f" ]] && has_init_event=true && break
        done
        if [[ "$has_init_event" == "false" ]]; then
            event_emit "system.initialized" "system" '{}'
            log_step "Wrote missing init event"
        fi

        # Update .speed/.gitignore to allowlist if still using old denylist
        if ! grep -q '^\*$' "${STATE_DIR}/.gitignore" 2>/dev/null; then
            cat > "${STATE_DIR}/.gitignore" <<'INNER_GITIGNORE'
# Multi-player mode: only shared/ is committed, everything else is local
*
!shared/
!shared/**
!.gitignore
INNER_GITIGNORE
            log_step "Updated .speed/.gitignore to allowlist"
        fi

        # Remove .speed/ from project .gitignore if still present
        local project_gitignore="${PROJECT_ROOT}/.gitignore"
        if [[ -f "$project_gitignore" ]] && grep -qE '^\.(speed|speed/)$' "$project_gitignore"; then
            local tmp
            tmp=$(mktemp)
            sed -E '/^\.speed\/?$/d' "$project_gitignore" > "$tmp"
            mv "$tmp" "$project_gitignore"
            log_step "Removed .speed/ from .gitignore"
        fi

        return 0
    fi

    log_warn "This will convert the project to multi-player mode. This cannot be undone."
    log_info "Features, memory, and worktrees will be split into shared/ (committed) and local/ (gitignored) zones."
    echo ""
    printf "  Continue? [y/N] "
    read -r confirm
    if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
        log_info "Aborted."
        return 0
    fi

    log_header "Initializing Multi-Player Mode"

    # ── Create directory structure ─────────────────────────────────
    log_step "Creating shared/local directory structure..."
    mkdir -p "${shared_dir}/events"
    mkdir -p "${shared_dir}/features"
    mkdir -p "${shared_dir}/knowledge"
    mkdir -p "${shared_dir}/proposals"
    mkdir -p "${shared_dir}/roster"
    mkdir -p "${local_dir}/features"
    mkdir -p "${local_dir}/locks"

    # ── Migrate features/ → shared/features/ + local/features/ ───
    if [[ -d "${STATE_DIR}/features" ]]; then
        local feat_count=0
        for feat_dir in "${STATE_DIR}/features"/*/; do
            [[ -d "$feat_dir" ]] || continue
            local feat_name
            feat_name=$(basename "$feat_dir")

            if [[ ! -d "${shared_dir}/features/${feat_name}" ]]; then
                mkdir -p "${shared_dir}/features/${feat_name}"
                mkdir -p "${local_dir}/features/${feat_name}"

                # Shared: tasks/, contract.json, spec_path
                [[ -d "${feat_dir}/tasks" ]] && mv "${feat_dir}/tasks" "${shared_dir}/features/${feat_name}/tasks"
                [[ -f "${feat_dir}/contract.json" ]] && mv "${feat_dir}/contract.json" "${shared_dir}/features/${feat_name}/contract.json"
                [[ -f "${feat_dir}/spec_path" ]] && mv "${feat_dir}/spec_path" "${shared_dir}/features/${feat_name}/spec_path"

                # Local: logs/, state.json
                [[ -d "${feat_dir}/logs" ]] && mv "${feat_dir}/logs" "${local_dir}/features/${feat_name}/logs"
                [[ -f "${feat_dir}/state.json" ]] && mv "${feat_dir}/state.json" "${local_dir}/features/${feat_name}/state.json"

                # Move anything remaining to shared (never delete unknown files)
                for leftover in "${feat_dir}"*; do
                    [[ -e "$leftover" ]] || continue
                    local lbase
                    lbase=$(basename "$leftover")
                    [[ ! -e "${shared_dir}/features/${feat_name}/${lbase}" ]] && \
                        mv "$leftover" "${shared_dir}/features/${feat_name}/${lbase}"
                done
                # Only remove if truly empty — never rm -rf
                rmdir "$feat_dir" 2>/dev/null || true
                ((feat_count++)) || true
            fi
        done
        # Remove old features dir if empty
        rmdir "${STATE_DIR}/features" 2>/dev/null || true
        if [[ $feat_count -gt 0 ]]; then
            log_step "Migrated ${feat_count} feature(s) — tasks/contracts to shared, logs/state to local"
        fi
    fi

    # ── Migrate memory/ → shared/knowledge/ ───────────────────────
    if [[ -d "${STATE_DIR}/memory" ]]; then
        # Move contents, not the directory itself (knowledge/ already exists)
        local mem_count=0
        for item in "${STATE_DIR}/memory"/*; do
            [[ -e "$item" ]] || continue
            local base
            base=$(basename "$item")
            if [[ ! -e "${shared_dir}/knowledge/${base}" ]]; then
                mv "$item" "${shared_dir}/knowledge/${base}"
                ((mem_count++)) || true
            fi
        done
        rmdir "${STATE_DIR}/memory" 2>/dev/null || true
        if [[ $mem_count -gt 0 ]]; then
            log_step "Migrated ${mem_count} memory item(s) to shared/knowledge/"
        fi
    fi

    # ── Migrate worktrees/ → local/worktrees/ ─────────────────────
    if [[ -d "${STATE_DIR}/worktrees" ]]; then
        mv "${STATE_DIR}/worktrees" "${local_dir}/worktrees"
        log_step "Migrated worktrees/ to local/worktrees/"
    fi

    # ── Migrate dashboard.db → local/dashboard.db ─────────────────
    if [[ -f "${STATE_DIR}/dashboard.db" ]]; then
        mv "${STATE_DIR}/dashboard.db" "${local_dir}/dashboard.db"
        log_step "Migrated dashboard.db to local/"
    fi

    # ── Write .speed/.gitignore (ignore local/ only) ──────────────
    cat > "${STATE_DIR}/.gitignore" <<'INNER_GITIGNORE'
# Multi-player mode: only shared/ is committed, everything else is local
*
!shared/
!shared/**
!.gitignore
INNER_GITIGNORE
    log_step "Wrote .speed/.gitignore"

    # ── Update project .gitignore ─────────────────────────────────
    # Remove the .speed/ entry entirely — .speed/.gitignore allowlist handles the rest
    local project_gitignore="${PROJECT_ROOT}/.gitignore"
    if [[ -f "$project_gitignore" ]]; then
        if grep -qE '^\.(speed|speed/)$' "$project_gitignore"; then
            local tmp
            tmp=$(mktemp)
            sed -E '/^\.speed\/?$/d' "$project_gitignore" > "$tmp"
            mv "$tmp" "$project_gitignore"
            log_step "Removed .speed/ from .gitignore (nested .gitignore handles filtering)"
        fi
    fi

    # ── Migrate active_feature to shared/ ─────────────────────────
    if [[ -f "${STATE_DIR}/active_feature" ]]; then
        mv "${STATE_DIR}/active_feature" "${shared_dir}/active_feature"
        log_step "Migrated active_feature to shared/"
    fi

    # ── Enable MP and write roster + init event ───────────────────
    MP_ENABLED=true
    _SPEED_CURRENT_COMMAND="mp-init"
    event_emit "system.initialized" "system" '{}'
    roster_heartbeat

    echo ""
    log_success "Multi-player mode initialized"
    log_info "shared/ is git-trackable, local/ is gitignored"
    log_info "Run 'speed claim <feature>' to claim ownership of a feature"
}
