#!/usr/bin/env bash
#
# test_install_inner.sh — Runs inside the Docker container.
# Called by test_install.sh. Do not run directly on the host.

set -euo pipefail

PASS=0
FAIL=0
TOTAL=0

pass() { ((PASS++)) || true; ((TOTAL++)) || true; printf "  \033[0;32mPASS\033[0m %s\n" "$1"; }
fail() { ((FAIL++)) || true; ((TOTAL++)) || true; printf "  \033[0;31mFAIL\033[0m %s\n" "$1"; if [[ -n "${2:-}" ]]; then printf "       %s\n" "$2"; fi; }
info() { printf "\033[1m==> %s\033[0m\n" "$*"; }

# ── Setup: create a local "remote" git repo from mounted source ──
info "Setting up local git remote from mounted source..."

mkdir -p /speed-remote
cp -a /speed-src/. /speed-remote/
cd /speed-remote
git init --quiet
git add -A
git commit -m "initial" --quiet

export SPEED_REPO="/speed-remote"
export HOME="/root"


# ── Test 0: Provider check rejects missing provider ───────────
info "Test 0: Provider check (no provider installed)"

rm -rf "$HOME/.speed" "$HOME/.bashrc" "$HOME/.zshrc"
touch "$HOME/.bashrc"

# Ensure no claude/codex stub exists yet
rm -f /usr/local/bin/claude /usr/local/bin/codex

install_output=$(bash /speed-remote/install.sh -q 2>&1 || true)
if echo "$install_output" | grep -qi "no agent provider"; then
    pass "0a: Installer rejects missing provider"
else
    fail "0a: Provider check" "Installer did not reject missing provider. Output: ${install_output:0:200}"
fi

# Verify install did NOT proceed (no receipt)
if [[ ! -f "$HOME/.speed/receipt.json" ]]; then
    pass "0b: Install aborted (no receipt written)"
else
    fail "0b: Install abort" "Receipt exists despite missing provider"
    rm -rf "$HOME/.speed"
fi


# ── Setup: install stub provider for remaining tests ───────────
info "Installing stub claude provider for tests..."

cat > /usr/local/bin/claude <<'STUB'
#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then
    echo "claude-stub 1.0.0 (test)"
    exit 0
fi
echo "stub provider"
STUB
chmod +x /usr/local/bin/claude


# ── Test 1: Fresh install ──────────────────────────────────────
info "Test 1: Fresh install"

# Clear any previous state
rm -rf "$HOME/.speed" "$HOME/.bashrc" "$HOME/.zshrc"
touch "$HOME/.bashrc"

bash /speed-remote/install.sh -q 2>/dev/null

# 1a: ~/.speed/ structure exists
if [[ -d "$HOME/.speed/versions" && -d "$HOME/.speed/bin" && -d "$HOME/.speed/venv" ]]; then
    pass "1a: Install directory structure created"
else
    fail "1a: Install directory structure" "Missing directories under ~/.speed/"
fi

# 1b: current symlink points to a version dir
if [[ -L "$HOME/.speed/current" ]] && [[ -d "$(readlink -f "$HOME/.speed/current")" ]]; then
    pass "1b: current symlink valid"
else
    fail "1b: current symlink" "~/.speed/current is not a valid symlink"
fi

# 1c: bin/speed symlink exists and is executable
if [[ -L "$HOME/.speed/bin/speed" ]] && [[ -x "$(readlink -f "$HOME/.speed/bin/speed")" ]]; then
    pass "1c: bin/speed symlink executable"
else
    fail "1c: bin/speed symlink" "~/.speed/bin/speed missing or not executable"
fi

# 1c2: bin/workbench symlink exists and is executable
if [[ -L "$HOME/.speed/bin/workbench" ]] && [[ -x "$(readlink -f "$HOME/.speed/bin/workbench")" ]]; then
    pass "1c2: bin/workbench symlink executable"
else
    fail "1c2: bin/workbench symlink" "~/.speed/bin/workbench missing or not executable"
fi

# 1d: receipt.json exists and has valid content
if [[ -f "$HOME/.speed/receipt.json" ]]; then
    version=$(jq -r ".version" "$HOME/.speed/receipt.json" 2>/dev/null || echo "")
    if [[ -n "$version" && "$version" != "null" ]]; then
        pass "1d: receipt.json valid (version: ${version})"
    else
        fail "1d: receipt.json" "Missing or null version field"
    fi
else
    fail "1d: receipt.json" "File does not exist"
fi

# 1e: shell rc was patched
if grep -qF "Added by SPEED installer" "$HOME/.bashrc" 2>/dev/null; then
    pass "1e: Shell rc patched"
else
    fail "1e: Shell rc" "SPEED marker not found in ~/.bashrc"
fi

# 1f: SPEED_DIR is exported and resolves
export PATH="$HOME/.speed/bin:$PATH"
export SPEED_PYTHON="$HOME/.speed/venv/bin/python3"

speed_dir_val=$(bash -c 'source '"$HOME"'/.speed/current/lib/config.sh && echo "$SPEED_DIR"' 2>/dev/null || echo "")
if [[ -n "$speed_dir_val" ]]; then
    pass "1f: SPEED_DIR resolves (${speed_dir_val})"
else
    fail "1f: SPEED_DIR" "Failed to resolve SPEED_DIR from config.sh"
fi

# 1g: SPEED_DIR is exported (visible to subprocesses)
if bash -c 'source '"$HOME"'/.speed/current/lib/config.sh && env | grep -q SPEED_DIR' 2>/dev/null; then
    pass "1g: SPEED_DIR is exported"
else
    fail "1g: SPEED_DIR export" "SPEED_DIR not visible in env"
fi

# 1h: speed help runs and shows self-update
if "$HOME/.speed/bin/speed" help 2>/dev/null | grep -q "self-update"; then
    pass "1h: speed help shows self-update"
else
    fail "1h: speed help" "self-update not found in help output"
fi

# 1i: speed help shows self-uninstall
if "$HOME/.speed/bin/speed" help 2>/dev/null | grep -q "self-uninstall"; then
    pass "1i: speed help shows self-uninstall"
else
    fail "1i: speed help" "self-uninstall not found in help output"
fi

# 1j: Python venv works and can import core modules
current_real=$(readlink -f "$HOME/.speed/current")
if "$HOME/.speed/venv/bin/python3" -c "
import sys
sys.path.insert(0, '${current_real}')
from lib.context.layer1 import build_layer1
print('ok')
" 2>/dev/null | grep -q "ok"; then
    pass "1j: Python core imports work"
else
    fail "1j: Python imports" "Failed to import lib.context.layer1"
fi

# 1k: Non-runtime dirs were stripped
stripped_ok=true
for dir in .git site working-docs tests .github .claude; do
    if [[ -d "$HOME/.speed/current/${dir}" ]]; then
        fail "1k: Strip dirs" "${dir}/ still present in install"
        stripped_ok=false
        break
    fi
done
if [[ "$stripped_ok" == "true" ]]; then
    pass "1k: Non-runtime directories stripped"
fi


# ── Test 2: Reinstall blocked ─────────────────────────────────
info "Test 2: Reinstall blocked by existing install"

reinstall_output=$(bash /speed-remote/install.sh -q 2>&1 || true)
if echo "$reinstall_output" | grep -qi "already installed\|self-update"; then
    pass "2a: Reinstall detected existing install"
else
    fail "2a: Reinstall guard" "Installer did not detect existing install. Output: ${reinstall_output:0:200}"
fi


# ── Test 3: self-update (same version = no-op) ────────────────
info "Test 3: Self-update (same version)"

update_output=$("$HOME/.speed/bin/speed" self-update 2>&1 || true)
if echo "$update_output" | grep -qi "up to date\|already"; then
    pass "3a: Self-update reports already up to date"
else
    fail "3a: Self-update no-op" "Did not report up-to-date status. Output: ${update_output:0:200}"
fi


# ── Test 4: self-update with new version ──────────────────────
info "Test 4: Self-update with new commit"

cd /speed-remote
echo "# update marker" >> README.md 2>/dev/null || echo "# update marker" > README.md
git add -A
git commit -m "simulate update" --quiet

old_version=$(jq -r ".version" "$HOME/.speed/receipt.json" 2>/dev/null)

new_version=""
update4_output=$("$HOME/.speed/bin/speed" self-update 2>&1) && update4_rc=0 || update4_rc=$?
if [[ $update4_rc -eq 0 ]]; then
    new_version=$(jq -r ".version" "$HOME/.speed/receipt.json" 2>/dev/null || echo "")
    if [[ -n "$new_version" && "$new_version" != "$old_version" ]]; then
        pass "4a: Self-update installed new version (${old_version} -> ${new_version})"
    else
        fail "4a: Self-update version" "Version did not change"
    fi
else
    fail "4a: Self-update" "Command exited with error. Output: ${update4_output:0:300}"
fi

# 4b: updated_from field in receipt
updated_from=$(jq -r '.updated_from // empty' "$HOME/.speed/receipt.json" 2>/dev/null || echo "")
if [[ "$updated_from" == "$old_version" ]]; then
    pass "4b: Receipt tracks previous version"
else
    fail "4b: Receipt updated_from" "Expected ${old_version}, got ${updated_from:-empty}"
fi

# 4b2: both entrypoints still resolve after an update. The bin/ links are
# relative to current/, so repointing current/ must not strand either one.
missing_bin=""
for entrypoint in speed workbench; do
    if [[ ! -x "$(readlink -f "$HOME/.speed/bin/${entrypoint}" 2>/dev/null)" ]]; then
        missing_bin="${missing_bin} ${entrypoint}"
    fi
done
if [[ -z "$missing_bin" ]]; then
    pass "4b2: Self-update keeps bin/speed and bin/workbench executable"
else
    fail "4b2: Self-update bin entrypoints" "Missing after update:${missing_bin}"
fi

# 4c: current symlink points to new version
current_target=$(readlink -f "$HOME/.speed/current" 2>/dev/null || echo "")
if [[ -n "$new_version" && "$current_target" == *"$new_version"* ]]; then
    pass "4c: Current symlink points to new version"
else
    fail "4c: Current symlink" "Expected to contain ${new_version:-unknown}, got ${current_target}"
fi

# 4d: speed help still works after update
help4_output=$("$HOME/.speed/bin/speed" help 2>&1 || true)
if echo "$help4_output" | grep -q "SPEED"; then
    pass "4d: speed help works after update"
else
    fail "4d: Post-update help" "speed help failed. Output: ${help4_output:0:200}"
fi


# ── Test 5: self-update with changed requirements.txt ─────────
info "Test 5: Self-update with requirements.txt change"

cd /speed-remote
echo "# trigger diff" >> requirements.txt
git add requirements.txt
git commit -m "change requirements" --quiet

update5_output=$("$HOME/.speed/bin/speed" self-update 2>&1) && update5_rc=0 || update5_rc=$?
if [[ $update5_rc -eq 0 ]]; then
    if [[ -d "$HOME/.speed/venv.prev" ]]; then
        pass "5a: Previous venv backed up on requirements change"
    else
        fail "5a: Venv backup" "venv.prev not created"
    fi
    if [[ -d "$HOME/.speed/venv" ]]; then
        pass "5b: New venv created"
    else
        fail "5b: New venv" "~/.speed/venv missing"
    fi
else
    fail "5a: Self-update with req change" "Command failed. Output: ${update5_output:0:300}"
    fail "5b: Skipped" "(depends on 5a)"
fi


# ── Test 6: Update lock prevents concurrent updates ───────────
info "Test 6: Update lock"

# Start a long-running background process and use its PID for the lock.
# This PID is alive but NOT in our process ancestry, so the lock
# won't be detected as stale, and _speed_processes_running won't
# exclude it.
sleep 300 &
lock_holder_pid=$!

mkdir -p "$HOME/.speed/.update-lock"
echo "$lock_holder_pid" > "$HOME/.speed/.update-lock/pid"

lock_output=$("$HOME/.speed/bin/speed" self-update 2>&1 || true)
if echo "$lock_output" | grep -qi "lock\|another update"; then
    pass "6a: Concurrent update blocked by lock"
else
    fail "6a: Update lock" "Update was not blocked. Output: ${lock_output:0:200}"
fi

kill "$lock_holder_pid" 2>/dev/null || true
wait "$lock_holder_pid" 2>/dev/null || true
rm -rf "$HOME/.speed/.update-lock"


# ── Test 7: sys.path.insert uses SPEED_DIR ────────────────────
info "Test 7: sys.path.insert regression"

# No remaining PROJECT_ROOT in sys.path.insert
if grep "sys.path.insert.*PROJECT_ROOT" "$HOME/.speed/current/lib/context_bridge.sh" 2>/dev/null; then
    fail "7a: sys.path.insert" "Still references PROJECT_ROOT"
else
    pass "7a: All sys.path.insert calls use SPEED_DIR"
fi

# Exactly 13 occurrences
count=$(grep -c "sys.path.insert" "$HOME/.speed/current/lib/context_bridge.sh" 2>/dev/null || echo 0)
if [[ "$count" -eq 13 ]]; then
    pass "7b: Exactly 13 sys.path.insert calls"
else
    fail "7b: sys.path.insert count" "Expected 13, found ${count}"
fi


# ── Test 8: _context_python resolution order ──────────────────
info "Test 8: _context_python resolution"

# 8a: SPEED_PYTHON takes priority
result=$(SPEED_PYTHON="/fake/python" bash -c '
    source '"$HOME"'/.speed/current/lib/config.sh
    source '"$HOME"'/.speed/current/lib/context_bridge.sh
    _context_python
' 2>/dev/null)
if [[ "$result" == "/fake/python" ]]; then
    pass "8a: SPEED_PYTHON env var takes priority"
else
    fail "8a: SPEED_PYTHON priority" "Expected /fake/python, got ${result}"
fi

# 8b: Falls through to SPEED_DIR/.venv when no SPEED_PYTHON
speed_dir=$(readlink -f "$HOME/.speed/current")
mkdir -p "${speed_dir}/.venv/bin"
touch "${speed_dir}/.venv/bin/python3"
chmod +x "${speed_dir}/.venv/bin/python3"

result=$(unset SPEED_PYTHON; bash -c '
    source '"$HOME"'/.speed/current/lib/config.sh
    source '"$HOME"'/.speed/current/lib/context_bridge.sh
    _context_python
' 2>/dev/null)
if [[ "$result" == *"/.venv/bin/python3" ]]; then
    pass "8b: SPEED_DIR/.venv fallback works"
else
    fail "8b: SPEED_DIR/.venv fallback" "Got: ${result}"
fi

rm -rf "${speed_dir}/.venv"


# ── Test 9: self-uninstall ────────────────────────────────────
info "Test 9: Self-uninstall"

echo "y" | "$HOME/.speed/bin/speed" self-uninstall 2>/dev/null

# 9a: ~/.speed/ removed
if [[ ! -d "$HOME/.speed" ]]; then
    pass "9a: Installation directory removed"
else
    fail "9a: Uninstall" "~/.speed/ still exists"
fi

# 9b: Shell rc cleaned
if grep -qF "Added by SPEED installer" "$HOME/.bashrc" 2>/dev/null; then
    fail "9b: Shell rc cleanup" "SPEED marker still in ~/.bashrc"
else
    pass "9b: Shell rc cleaned"
fi


# ── Test 10: Reinstall after uninstall ────────────────────────
info "Test 10: Clean reinstall after uninstall"

export SPEED_REPO="/speed-remote"
if bash /speed-remote/install.sh -q 2>/dev/null; then
    if [[ -f "$HOME/.speed/receipt.json" ]] && [[ -x "$(readlink -f "$HOME/.speed/bin/speed")" ]]; then
        pass "10a: Clean reinstall succeeded"
    else
        fail "10a: Reinstall" "Completed but state incomplete"
    fi
else
    fail "10a: Reinstall" "install.sh exited with error"
fi


# ── Summary ────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
printf "  Total: %d  |  \033[0;32mPass: %d\033[0m  |  \033[0;31mFail: %d\033[0m\n" "$TOTAL" "$PASS" "$FAIL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0
