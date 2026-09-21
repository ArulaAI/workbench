#!/usr/bin/env bash
#
# install.sh — Bootstrap installer for SPEED
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/<org>/speed/main/install.sh | bash
#
# Options:
#   --proxy URL     Route all network traffic through this proxy
#   -q, --quiet     Suppress non-error output (for CI)
#
# Installs SPEED to ~/.speed/ with:
#   - uv-managed Python 3.12 venv
#   - Atomic versioned directory layout
#   - Shell rc integration (PATH + SPEED_PYTHON)
#
# Requirements: bash >= 4.3, curl, git, jq, coreutils (timeout), claude or codex CLI
#
# Proxy support:
#   The installer respects HTTP_PROXY, HTTPS_PROXY, and NO_PROXY from
#   the environment. Use --proxy to set all three transport variables
#   for curl and git in one shot.

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
SPEED_HOME="${HOME}/.speed"
SPEED_REPO="${SPEED_REPO:-https://github.com/<org>/speed.git}"   # Override for internal mirrors
SPEED_TARBALL_URL="${SPEED_TARBALL_URL:-}"   # Override for tarball download
MIN_BASH_VERSION="4.3"
REQUIRED_PYTHON="3.12"
MARKER_COMMENT="# Added by SPEED installer"
INSTALLER_VERSION="1.0.0"

# Directories stripped from the install (not needed at runtime)
STRIP_DIRS=(".git" "site" "working-docs" "tests" "example" ".github" ".claude")

# Staging directory (set by main, cleaned up by trap)
STAGING_DIR=""

# Output control
QUIET=false

# ── Helpers ────────────────────────────────────────────────────

info() {
    [[ "$QUIET" == "true" ]] && return 0
    printf '\033[0;34m==>\033[0m %s\n' "$*"
}

warn() {
    printf '\033[0;33mWarning:\033[0m %s\n' "$*" >&2
}

error() {
    printf '\033[0;31mError:\033[0m %s\n' "$*" >&2
    exit 1
}

command_exists() { command -v "$1" &>/dev/null; }

version_gte() {
    local IFS='.'
    local i ver1=($1) ver2=($2)
    for ((i = 0; i < ${#ver2[@]}; i++)); do
        local v1="${ver1[i]:-0}"
        local v2="${ver2[i]:-0}"
        if ((v1 > v2)); then return 0; fi
        if ((v1 < v2)); then return 1; fi
    done
    return 0
}

# Retry a command with exponential backoff (for network operations)
retry() {
    local max_attempts="$1"
    local base_delay="$2"
    shift 2

    local attempt=1
    while true; do
        if "$@"; then
            return 0
        fi
        if ((attempt >= max_attempts)); then
            return 1
        fi
        local delay=$((base_delay * (2 ** (attempt - 1))))
        warn "Attempt ${attempt}/${max_attempts} failed. Retrying in ${delay}s..."
        sleep "$delay"
        ((attempt++))
    done
}

# ── Cleanup Trap ───────────────────────────────────────────────

cleanup() {
    local exit_code=$?
    if [[ -n "$STAGING_DIR" && -d "$STAGING_DIR" ]]; then
        rm -rf "$STAGING_DIR"
    fi
    exit "$exit_code"
}

trap cleanup EXIT INT TERM

# ── Argument Parsing ──────────────────────────────────────────

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --proxy)
                if [[ -z "${2:-}" ]]; then
                    error "--proxy requires a URL argument (e.g., --proxy https://proxy.corp:8080)"
                fi
                export HTTP_PROXY="$2"
                export HTTPS_PROXY="$2"
                export http_proxy="$2"
                export https_proxy="$2"
                # Configure git to use the proxy
                git config --global http.proxy "$2" 2>/dev/null || true
                info "Proxy configured: $2"
                shift 2
                ;;
            -q|--quiet)
                QUIET=true
                shift
                ;;
            -h|--help)
                echo "Usage: install.sh [--proxy URL] [-q|--quiet]"
                echo ""
                echo "Options:"
                echo "  --proxy URL     Route network traffic through this proxy"
                echo "  -q, --quiet     Suppress non-error output"
                echo ""
                echo "Environment:"
                echo "  SPEED_REPO          Git repo URL (for internal mirrors)"
                echo "  SPEED_TARBALL_URL   Tarball URL (alternative to git clone)"
                echo "  HTTP_PROXY          HTTP proxy (inherited by curl/git)"
                echo "  HTTPS_PROXY         HTTPS proxy (inherited by curl/git)"
                exit 0
                ;;
            *)
                error "Unknown option: $1. Run with --help for usage."
                ;;
        esac
    done
}

# ── Platform Detection ─────────────────────────────────────────

detect_platform() {
    local os arch
    os="$(uname -s)"
    arch="$(uname -m)"

    case "$os" in
        Linux)  PLATFORM_OS="linux" ;;
        Darwin) PLATFORM_OS="macos" ;;
        *)      error "Unsupported OS: ${os}. SPEED requires Linux or macOS." ;;
    esac

    case "$arch" in
        x86_64|amd64)  PLATFORM_ARCH="x64" ;;
        arm64|aarch64) PLATFORM_ARCH="arm64" ;;
        *)             error "Unsupported architecture: ${arch}" ;;
    esac

    info "Platform: ${PLATFORM_OS} ${PLATFORM_ARCH}"
}

# ── Prerequisite Checks ───────────────────────────────────────

check_bash_version() {
    local current="${BASH_VERSION%%(*}"
    current="${current%%-*}"
    if ! version_gte "$current" "$MIN_BASH_VERSION"; then
        if [[ "$PLATFORM_OS" == "macos" ]]; then
            error "bash ${current} is too old (need >= ${MIN_BASH_VERSION}). Run: brew install bash"
        else
            error "bash ${current} is too old (need >= ${MIN_BASH_VERSION}). Update bash via your package manager."
        fi
    fi
}

check_system_deps() {
    local missing=()

    command_exists curl || missing+=("curl")
    command_exists git  || missing+=("git")
    command_exists jq   || missing+=("jq")

    if ! command_exists timeout && ! command_exists gtimeout; then
        missing+=("coreutils")
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        local install_hint=""
        if [[ "$PLATFORM_OS" == "macos" ]]; then
            install_hint="brew install ${missing[*]}"
        elif command_exists apt-get; then
            install_hint="sudo apt-get install ${missing[*]}"
        elif command_exists dnf; then
            install_hint="sudo dnf install ${missing[*]}"
        elif command_exists pacman; then
            install_hint="sudo pacman -S ${missing[*]}"
        else
            install_hint="Install via your package manager: ${missing[*]}"
        fi
        error "Missing required dependencies: ${missing[*]}. Run: ${install_hint}"
    fi

    info "System dependencies satisfied: curl, git, jq, timeout"
}

# ── Provider Check ────────────────────────────────────────────

check_provider() {
    if command_exists claude; then
        local ver
        ver="$(claude --version 2>/dev/null | head -1 || echo "unknown")"
        info "Provider found: claude (${ver})"
    elif command_exists codex; then
        local ver
        ver="$(codex --version 2>/dev/null | head -1 || echo "unknown")"
        info "Provider found: codex (${ver})"
    else
        error "No agent provider found. SPEED requires one of:
  - Claude Code: npm install -g @anthropic-ai/claude-code
  - Codex CLI:   npm install -g @openai/codex
Install a provider and re-run this installer."
    fi
}

# ── Existing Install Detection ─────────────────────────────────

check_existing_install() {
    if [[ -d "$SPEED_HOME" ]]; then
        if [[ -f "${SPEED_HOME}/receipt.json" ]]; then
            local version
            version=$(jq -r '.version // "unknown"' "${SPEED_HOME}/receipt.json" 2>/dev/null || echo "unknown")
            error "SPEED is already installed (version: ${version}). Run 'speed self-update' to update, or remove ${SPEED_HOME} and re-run this installer."
        else
            warn "Directory ${SPEED_HOME} exists but has no SPEED receipt."
            if [[ -t 0 ]]; then
                warn "This installer will overwrite it in 3 seconds. Press Ctrl+C to abort."
                sleep 3
            else
                warn "Running non-interactively. Overwriting existing ${SPEED_HOME}."
            fi
        fi
    fi
}

# ── uv Installation ───────────────────────────────────────────

ensure_uv() {
    if command_exists uv; then
        local uv_version
        uv_version="$(uv --version 2>/dev/null | head -1)"
        info "uv already installed: ${uv_version}"
        return 0
    fi

    info "Installing uv (Python package manager)..."
    if ! retry 3 2 bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'; then
        error "uv installation failed after 3 attempts. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
    fi

    # uv installs to ~/.local/bin or ~/.cargo/bin
    export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

    if ! command_exists uv; then
        error "uv binary not found on PATH after installation. Check ~/.local/bin or ~/.cargo/bin."
    fi

    info "uv installed: $(uv --version 2>/dev/null | head -1)"
}

# ── Repository Download ───────────────────────────────────────

download_speed() {
    local version_hash

    if command_exists git; then
        info "Cloning SPEED repository..."
        if ! retry 3 3 git clone --depth 1 "$SPEED_REPO" "${STAGING_DIR}/repo" 2>/dev/null; then
            error "Failed to clone ${SPEED_REPO} after 3 attempts. Check your network connection and proxy settings."
        fi

        version_hash=$(git -C "${STAGING_DIR}/repo" rev-parse --short HEAD 2>/dev/null || echo "unknown")
    elif [[ -n "$SPEED_TARBALL_URL" ]]; then
        info "git not found, downloading tarball..."
        local tmp_tar="${STAGING_DIR}/speed.tar.gz"

        if ! retry 3 3 curl -fsSL "$SPEED_TARBALL_URL" -o "$tmp_tar"; then
            error "Failed to download tarball after 3 attempts. Check your network connection and proxy settings."
        fi

        version_hash="tarball-$(date +%s)"
        mkdir -p "${STAGING_DIR}/repo"
        tar xzf "$tmp_tar" -C "${STAGING_DIR}/repo" --strip-components=1
        rm -f "$tmp_tar"
    else
        error "git is not installed and SPEED_TARBALL_URL is not set. Install git or set SPEED_TARBALL_URL."
    fi

    # Strip non-runtime directories
    for dir in "${STRIP_DIRS[@]}"; do
        rm -rf "${STAGING_DIR:?}/repo/${dir}"
    done

    chmod +x "${STAGING_DIR}/repo/speed"

    INSTALLED_VERSION_HASH="$version_hash"

    info "Downloaded SPEED ${version_hash}"
}

# ── Python Environment ────────────────────────────────────────

setup_python_env() {
    local venv_dir="${STAGING_DIR}/venv"
    local req_file="${STAGING_DIR}/repo/requirements.txt"

    info "Creating Python ${REQUIRED_PYTHON} environment..."
    if ! uv venv --python "$REQUIRED_PYTHON" "$venv_dir" 2>/dev/null; then
        error "Failed to create Python ${REQUIRED_PYTHON} venv. Ensure uv can fetch Python ${REQUIRED_PYTHON}."
    fi

    if [[ -f "$req_file" ]]; then
        info "Installing Python dependencies..."
        if ! uv pip install -r "$req_file" --python "${venv_dir}/bin/python3" 2>/dev/null; then
            error "Failed to install Python dependencies from ${req_file}."
        fi
    else
        error "requirements.txt not found in downloaded SPEED. The download may be corrupted."
    fi

    info "Python environment ready"
}

# ── Post-Install Verification ─────────────────────────────────

verify_installation() {
    local venv_python="${STAGING_DIR}/venv/bin/python3"
    local failed=()

    # Verify Python can import core SPEED modules
    info "Verifying Python modules..."
    if ! "$venv_python" -c "
import sys
sys.path.insert(0, '${STAGING_DIR}/repo')
from lib.context.layer1 import build_layer1
from lib.context.layer2 import build_task_context_package
from lib.context.assembly import assemble_architect
" 2>/dev/null; then
        failed+=("python-core-modules")
    fi

    # Verify tree-sitter grammar imports
    if ! "$venv_python" -c "
import tree_sitter
import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_typescript
" 2>/dev/null; then
        failed+=("tree-sitter-grammars")
    fi

    # Verify ast-grep CLI is available via pip install
    if ! "$venv_python" -m ast_grep_cli --help &>/dev/null; then
        # ast-grep-cli may install as a binary in the venv
        if ! "${STAGING_DIR}/venv/bin/ast-grep" --help &>/dev/null 2>&1; then
            failed+=("ast-grep-cli")
        fi
    fi

    # Verify tree-sitter CLI (system-level, optional but checked)
    if ! command_exists tree-sitter; then
        warn "tree-sitter CLI not found on system PATH. Some language analysis features may be limited."
        warn "Install with: cargo install tree-sitter-cli (or: npm install -g tree-sitter-cli)"
    fi

    # Verify jq works (already checked, but confirm after venv setup)
    if ! echo '{}' | jq . &>/dev/null; then
        failed+=("jq-runtime")
    fi

    if [[ ${#failed[@]} -gt 0 ]]; then
        error "Verification failed for: ${failed[*]}. The install may be incomplete. Check the output above for details."
    fi

    info "All components verified"
}

# ── Finalize (move staging to permanent location) ─────────────

finalize_install() {
    local version_dir="${SPEED_HOME}/versions/${INSTALLED_VERSION_HASH}"

    mkdir -p "${SPEED_HOME}/versions" "${SPEED_HOME}/bin"

    # Move repo and venv from staging to permanent location
    if [[ -d "$version_dir" ]]; then
        rm -rf "$version_dir"
    fi
    mv "${STAGING_DIR}/repo" "$version_dir"
    mv "${STAGING_DIR}/venv" "${SPEED_HOME}/venv"

    # Atomic symlinks
    ln -sfn "$version_dir" "${SPEED_HOME}/current"
    ln -sf "../current/speed" "${SPEED_HOME}/bin/speed"

    INSTALLED_VERSION_DIR="$version_dir"

    info "Installed to ${version_dir}"
}

# ── Shell RC Integration ──────────────────────────────────────

patch_shell_rc() {
    local rc_files=()
    local shell_name=""

    # Detect shell and pick rc files
    case "${SHELL:-/bin/bash}" in
        */zsh)
            rc_files=("${HOME}/.zshrc")
            shell_name="zsh"
            ;;
        */bash)
            rc_files=("${HOME}/.bashrc")
            [[ "$PLATFORM_OS" == "macos" && -f "${HOME}/.bash_profile" ]] && rc_files+=("${HOME}/.bash_profile")
            shell_name="bash"
            ;;
        */fish)
            shell_name="fish"
            ;;
        *)
            rc_files=("${HOME}/.bashrc")
            shell_name="bash"
            ;;
    esac

    local speed_block
    read -r -d '' speed_block <<EOF || true
${MARKER_COMMENT}
export PATH="\$HOME/.speed/bin:\$PATH"
export SPEED_PYTHON="\$HOME/.speed/venv/bin/python3"
EOF

    if [[ "$shell_name" == "fish" ]]; then
        local fish_conf_dir="${HOME}/.config/fish/conf.d"
        local fish_conf="${fish_conf_dir}/speed.fish"
        if [[ -f "$fish_conf" ]] && grep -qF "SPEED" "$fish_conf" 2>/dev/null; then
            info "Fish config already has SPEED PATH entry, skipping."
        else
            mkdir -p "$fish_conf_dir"
            cat > "$fish_conf" <<FISH
${MARKER_COMMENT}
set -gx PATH \$HOME/.speed/bin \$PATH
set -gx SPEED_PYTHON \$HOME/.speed/venv/bin/python3
FISH
            info "Added SPEED to fish config: ${fish_conf}"
        fi
        return 0
    fi

    local patched=false
    for rc_file in "${rc_files[@]}"; do
        [[ -f "$rc_file" ]] || touch "$rc_file"

        if grep -qF "$MARKER_COMMENT" "$rc_file" 2>/dev/null; then
            info "Shell rc already has SPEED entry: ${rc_file}, skipping."
            continue
        fi

        printf '\n%s\n' "$speed_block" >> "$rc_file"
        patched=true
        info "Added SPEED to PATH in ${rc_file}"
    done

    if [[ "$patched" == "false" ]]; then
        info "Shell rc files already configured."
    fi
}

# ── Receipt ───────────────────────────────────────────────────

write_receipt() {
    local receipt="${SPEED_HOME}/receipt.json"
    local install_date
    install_date="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    cat > "$receipt" <<EOF
{
  "version": "${INSTALLED_VERSION_HASH}",
  "installed_at": "${install_date}",
  "platform_os": "${PLATFORM_OS}",
  "platform_arch": "${PLATFORM_ARCH}",
  "python": "${REQUIRED_PYTHON}",
  "install_dir": "${SPEED_HOME}",
  "installer_version": "${INSTALLER_VERSION}"
}
EOF

    info "Receipt written: ${receipt}"
}

# ── Main ──────────────────────────────────────────────────────

main() {
    parse_args "$@"

    # Auto-detect CI / non-interactive
    if [[ -n "${CI:-}" ]] || [[ ! -t 0 ]]; then
        QUIET="${QUIET:-false}"  # Respect explicit -q, but don't force it
    fi

    if [[ "$QUIET" != "true" ]]; then
        echo ""
        echo "  ╔═══════════════════════════════════════╗"
        echo "  ║     SPEED Installer v${INSTALLER_VERSION}          ║"
        echo "  ╚═══════════════════════════════════════╝"
        echo ""
    fi

    # Create staging directory (cleaned up by trap on any exit)
    STAGING_DIR=$(mktemp -d "${TMPDIR:-/tmp}/speed-install-XXXXXX")

    detect_platform
    check_bash_version
    check_system_deps
    check_provider
    check_existing_install
    ensure_uv
    download_speed
    setup_python_env
    verify_installation
    finalize_install
    patch_shell_rc
    write_receipt

    if [[ "$QUIET" != "true" ]]; then
        echo ""
        echo "  ┌───────────────────────────────────────┐"
        echo "  │  SPEED installed successfully!         │"
        echo "  │                                        │"
        echo "  │  Restart your shell, then run:         │"
        echo "  │    speed help                          │"
        echo "  │                                        │"
        echo "  │  To update later:  speed self-update   │"
        echo "  │  To remove:        speed self-uninstall│"
        echo "  └───────────────────────────────────────┘"
        echo ""
    fi
}

main "$@"
