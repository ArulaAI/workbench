#!/usr/bin/env bash
# self.sh — Self-management commands: self-update, self-uninstall
#
# Both commands operate on the global ~/.speed/ installation.
# Update uses a staging directory and atomic symlink swap to prevent
# partial corruption. A lockfile prevents concurrent updates.
# Running SPEED processes are safe: they hold open file handles to the
# old version, and the symlink swap is atomic on POSIX.

SPEED_HOME="${HOME}/.speed"
SPEED_REPO="${SPEED_REPO:-https://github.com/<org>/speed.git}"   # Override for internal mirrors
MARKER_COMMENT="# Added by SPEED installer"
STRIP_DIRS=(".git" "site" "working-docs" "tests" "example" ".github" ".claude")

UPDATE_LOCK="${SPEED_HOME}/.update-lock"

# ── Helpers (self-contained, no dependency on log.sh working) ──

_self_info()    { printf '\033[0;34m==>\033[0m %s\n' "$*"; }
_self_warn()    { printf '\033[0;33mWarning:\033[0m %s\n' "$*" >&2; }
_self_error()   { printf '\033[0;31mError:\033[0m %s\n' "$*" >&2; }

# Acquire the global update lock (mkdir-based, same pattern as lock.sh)
_update_acquire_lock() {
    if mkdir "$UPDATE_LOCK" 2>/dev/null; then
        echo $$ > "$UPDATE_LOCK/pid"
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$UPDATE_LOCK/acquired_at"
        return 0
    fi

    # Check for stale lock
    if [[ -f "$UPDATE_LOCK/pid" ]]; then
        local lock_pid
        lock_pid=$(cat "$UPDATE_LOCK/pid" 2>/dev/null || echo "")
        if [[ -n "$lock_pid" ]] && ! kill -0 "$lock_pid" 2>/dev/null; then
            _self_warn "Breaking stale update lock (PID ${lock_pid})"
            rm -rf "$UPDATE_LOCK"
            if mkdir "$UPDATE_LOCK" 2>/dev/null; then
                echo $$ > "$UPDATE_LOCK/pid"
                echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$UPDATE_LOCK/acquired_at"
                return 0
            fi
        fi
        _self_error "Another update is in progress (PID ${lock_pid})."
    else
        # Lock dir without PID file — broken state
        rm -rf "$UPDATE_LOCK"
        if mkdir "$UPDATE_LOCK" 2>/dev/null; then
            echo $$ > "$UPDATE_LOCK/pid"
            return 0
        fi
    fi

    return 1
}

_update_release_lock() {
    if [[ -d "$UPDATE_LOCK" ]]; then
        local lock_pid
        lock_pid=$(cat "$UPDATE_LOCK/pid" 2>/dev/null || echo "")
        if [[ "$lock_pid" == "$$" ]]; then
            rm -rf "$UPDATE_LOCK"
        fi
    fi
}

# ── self-update ───────────────────────────────────────────────

cmd_self_update() {
    log_header "Updating SPEED"

    # ── Guard: managed install? ────────────────────────────────
    if [[ ! -f "${SPEED_HOME}/receipt.json" ]]; then
        log_error "No managed SPEED installation found at ${SPEED_HOME}."
        log_error "If you installed from git, pull the latest changes manually."
        return 1
    fi

    # ── Guard: concurrent update? ──────────────────────────────
    if ! _update_acquire_lock; then
        log_error "Could not acquire update lock. If no update is running, remove ${UPDATE_LOCK} and retry."
        return 1
    fi

    # Release lock on any exit from this function
    trap '_update_release_lock' RETURN

    # ── Read current state ─────────────────────────────────────
    local old_version platform_os platform_arch
    old_version=$(jq -r '.version // "unknown"' "${SPEED_HOME}/receipt.json" 2>/dev/null || echo "unknown")
    platform_os=$(jq -r '.platform_os // "unknown"' "${SPEED_HOME}/receipt.json" 2>/dev/null || echo "unknown")
    platform_arch=$(jq -r '.platform_arch // "unknown"' "${SPEED_HOME}/receipt.json" 2>/dev/null || echo "unknown")
    log_info "Current version: ${old_version}"

    # ── Stage: clone to temp dir ───────────────────────────────
    local staging_dir
    staging_dir=$(mktemp -d "${TMPDIR:-/tmp}/speed-update-XXXXXX")

    # Clean staging on failure (but not on success — we move it)
    local staging_cleaned=false
    _cleanup_staging() {
        if [[ "$staging_cleaned" == "false" && -d "$staging_dir" ]]; then
            rm -rf "$staging_dir"
        fi
    }
    trap '_cleanup_staging; _update_release_lock' RETURN

    log_info "Fetching latest..."
    if ! git clone --depth 1 "$SPEED_REPO" "${staging_dir}/repo" 2>/dev/null; then
        log_error "Failed to fetch latest SPEED. Check your network connection."
        return 1
    fi

    local new_hash
    new_hash=$(git -C "${staging_dir}/repo" rev-parse --short HEAD 2>/dev/null || echo "unknown")

    if [[ "$new_hash" == "$old_version" ]]; then
        log_success "Already up to date (${old_version})."
        return 0
    fi

    log_info "New version available: ${new_hash}"

    # ── Stage: strip non-runtime dirs ──────────────────────────
    for dir in "${STRIP_DIRS[@]}"; do
        rm -rf "${staging_dir:?}/repo/${dir}"
    done
    chmod +x "${staging_dir}/repo/speed"

    # ── Stage: handle venv if requirements changed ─────────────
    local old_req="${SPEED_HOME}/current/requirements.txt"
    local new_req="${staging_dir}/repo/requirements.txt"
    local venv_needs_update=false

    if [[ -f "$new_req" ]]; then
        if [[ ! -f "$old_req" ]] || ! diff -q "$old_req" "$new_req" &>/dev/null; then
            venv_needs_update=true
        fi
    fi

    if [[ "$venv_needs_update" == "true" ]]; then
        log_info "requirements.txt changed. Building new Python environment..."

        if ! command -v uv &>/dev/null; then
            log_error "uv not found. Cannot update Python dependencies. Install uv: https://docs.astral.sh/uv/"
            return 1
        fi

        # Create a fresh venv in staging (not touching the live one)
        if ! uv venv --python 3.12 "${staging_dir}/venv" 2>/dev/null; then
            log_error "Failed to create new Python venv."
            return 1
        fi

        if ! uv pip install -r "$new_req" --python "${staging_dir}/venv/bin/python3" 2>/dev/null; then
            log_error "Failed to install Python dependencies into new venv."
            return 1
        fi

        log_info "New Python environment ready."
    fi

    # ── Finalize: atomic swap ──────────────────────────────────
    # At this point, staging is fully built. Move to permanent location.
    # Running SPEED processes are safe: they hold open file handles to the
    # old version directory. The symlink swap is atomic on POSIX.
    local new_version_dir="${SPEED_HOME}/versions/${new_hash}"

    if [[ -d "$new_version_dir" ]]; then
        rm -rf "$new_version_dir"
    fi
    mv "${staging_dir}/repo" "$new_version_dir"

    # Swap venv if it was rebuilt
    if [[ "$venv_needs_update" == "true" ]]; then
        local old_venv="${SPEED_HOME}/venv"
        local backup_venv="${SPEED_HOME}/venv.prev"

        # Keep one previous venv for manual rollback
        rm -rf "$backup_venv"
        if [[ -d "$old_venv" ]]; then
            mv "$old_venv" "$backup_venv"
        fi
        mv "${staging_dir}/venv" "$old_venv"
        log_info "Python environment updated (previous saved as venv.prev)."
    fi

    staging_cleaned=true
    rm -rf "$staging_dir"

    # Swap the current symlink (atomic on POSIX)
    ln -sfn "$new_version_dir" "${SPEED_HOME}/current"

    # ── Update receipt ─────────────────────────────────────────
    local install_date
    install_date="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    cat > "${SPEED_HOME}/receipt.json" <<EOF
{
  "version": "${new_hash}",
  "installed_at": "${install_date}",
  "updated_from": "${old_version}",
  "platform_os": "${platform_os}",
  "platform_arch": "${platform_arch}",
  "python": "3.12",
  "install_dir": "${SPEED_HOME}",
  "installer_version": "1.0.0"
}
EOF

    # ── Clean old versions (keep current + 1 previous) ─────────
    local versions_to_clean
    versions_to_clean=$(ls -1dt "${SPEED_HOME}/versions"/*/ 2>/dev/null | tail -n +3)
    if [[ -n "$versions_to_clean" ]]; then
        echo "$versions_to_clean" | while IFS= read -r old_dir; do
            rm -rf "$old_dir"
        done
        log_info "Cleaned old versions (kept current + 1 previous)."
    fi

    # Clear the RETURN trap before returning. Bash RETURN traps are global,
    # not function-scoped — without this, the trap fires again when main()
    # returns, at which point our locals are out of scope and set -u kills
    # the script.
    trap - RETURN

    log_success "Updated: ${old_version} → ${new_hash}"
}

# ── self-uninstall ────────────────────────────────────────────

cmd_self_uninstall() {
    # Use self-contained output functions — if SPEED is broken,
    # log_header/log_info may not work.
    _self_info "SPEED Uninstaller"

    echo ""
    echo "This will remove:"
    echo "  - ${SPEED_HOME}/ (installation directory)"
    echo "  - SPEED entries from shell rc files"
    if [[ -d "${SPEED_HOME}/venv.prev" ]]; then
        echo "  - Previous venv backup"
    fi
    echo ""

    if [[ -t 0 ]]; then
        printf "Continue? [y/N] "
        read -r confirm
        if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
            _self_info "Aborted."
            return 0
        fi
    else
        _self_warn "Running non-interactively. Proceeding with uninstall."
    fi

    # ── Clean shell rc files ───────────────────────────────────
    local rc_files=(
        "${HOME}/.zshrc"
        "${HOME}/.bashrc"
        "${HOME}/.bash_profile"
    )
    local fish_conf="${HOME}/.config/fish/conf.d/speed.fish"

    for rc_file in "${rc_files[@]}"; do
        [[ -f "$rc_file" ]] || continue

        if grep -qF "$MARKER_COMMENT" "$rc_file" 2>/dev/null; then
            local tmp_rc
            tmp_rc=$(mktemp "${TMPDIR:-/tmp}/speed-rc-XXXXXX")
            # Remove the marker line and the two lines following it
            awk -v marker="$MARKER_COMMENT" '
                $0 == marker { skip = 3; next }
                skip > 0 { skip--; next }
                { print }
            ' "$rc_file" > "$tmp_rc"
            mv "$tmp_rc" "$rc_file"
            _self_info "Cleaned SPEED entries from ${rc_file}"
        fi
    done

    if [[ -f "$fish_conf" ]]; then
        rm -f "$fish_conf"
        _self_info "Removed fish config: ${fish_conf}"
    fi

    # ── Remove installation directory ──────────────────────────
    if [[ -d "$SPEED_HOME" ]]; then
        rm -rf "$SPEED_HOME"
        _self_info "Removed ${SPEED_HOME}"
    fi

    echo ""
    _self_info "SPEED has been uninstalled. Restart your shell to complete cleanup."
}
