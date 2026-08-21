#!/usr/bin/env bash
# test_actor_identity_e2e.sh — End-to-end CLI test for email-based identity
#
# Runs the real `./speed` binary as a subprocess, exactly as a user would.
# Uses a temporary git repo with multiplayer enabled as the working directory.
#
# Run from project root: bash tests/test_actor_identity_e2e.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEED="$SCRIPT_DIR/speed"
TEST_DIR=$(mktemp -d "${TMPDIR:-/tmp}/speed-e2e-identity-XXXXXX")
PASS=0
FAIL=0
FEATURE="e2e-identity-$$"

cleanup() {
    rm -rf "$TEST_DIR"
}
trap cleanup EXIT

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label (expected '$expected', got '$actual')"
        ((FAIL++)) || true
    fi
}

assert_contains() {
    local label="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -qF "$needle"; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label (output does not contain '$needle')"
        ((FAIL++)) || true
    fi
}

# Run speed from the temp dir, inheriting the real project's SPEED install
run_speed() {
    (cd "$TEST_DIR" && "$SPEED" "$@" 2>&1)
}

# ── Setup: isolated git repo with multiplayer structure ──────

echo "Setting up isolated project in $TEST_DIR"

# Copy just the project skeleton (speed.toml, .venv symlink) so deps pass
cd "$TEST_DIR"
git init -q
git config user.name "TestUser"
git config user.email "testuser@example.com"
git commit --allow-empty -m "init" -q

# Multiplayer structure
mkdir -p .speed/shared/events .speed/shared/features .speed/shared/roster
mkdir -p .speed/local/locks

# Disable staleness so UTC/local timezone mismatch in date parsing
# doesn't cause recent claims to look stale. (Pre-existing bug in
# ownership.sh: event timestamps are UTC but parsed as local time.)
export TOML_MULTIPLAYER_STALE_WINDOW=999999


echo ""
echo "=== E2E: CLI identity through ./speed binary ==="


# ── Step 1: whoami ───────────────────────────────────────────

echo ""
echo "--- Step 1: whoami shows actor name ---"

output=$(SPEED_ACTOR="Alex" SPEED_ACTOR_EMAIL="alex-a@test.com" run_speed whoami)
assert_contains "whoami shows name" "$output" "Alex"


# ── Step 2: Actor A claims ───────────────────────────────────

echo ""
echo "--- Step 2: Actor A claims feature ---"

output=$(SPEED_ACTOR="Alex" SPEED_ACTOR_EMAIL="alex-a@test.com" run_speed claim "$FEATURE")
assert_contains "A claims successfully" "$output" "Claimed"

# Verify event file has actor_email
event_file=$(ls "${TEST_DIR}/.speed/shared/events"/*feature-claimed*"${FEATURE}"*.jsonl 2>/dev/null | tail -1)
if [[ -n "$event_file" ]]; then
    assert_eq "event actor_email" "alex-a@test.com" "$(jq -r '.actor_email' "$event_file")"
    assert_eq "event actor" "Alex" "$(jq -r '.actor' "$event_file")"
else
    echo "  FAIL: claim event file not found"
    ((FAIL++)) || true
fi


# ── Step 3: Actor B (same name, different email) blocked ─────

echo ""
echo "--- Step 3: Actor B blocked (same name, different email) ---"

output=$(SPEED_ACTOR="Alex" SPEED_ACTOR_EMAIL="alex-b@test.com" run_speed claim "$FEATURE") || true
assert_contains "B rejected" "$output" "claimed by"


# ── Step 4: Actor A re-claims ────────────────────────────────

echo ""
echo "--- Step 4: Actor A re-claims (already owns) ---"

output=$(SPEED_ACTOR="Alex" SPEED_ACTOR_EMAIL="alex-a@test.com" run_speed claim "$FEATURE")
assert_contains "A already owns" "$output" "already own"


# ── Step 5: Release then B claims ────────────────────────────

echo ""
echo "--- Step 5: A releases, B claims ---"

output=$(SPEED_ACTOR="Alex" SPEED_ACTOR_EMAIL="alex-a@test.com" run_speed release "$FEATURE")
assert_contains "A releases" "$output" "Released"

sleep 1  # ensure release timestamp > claim timestamp

output=$(SPEED_ACTOR="Alex" SPEED_ACTOR_EMAIL="alex-b@test.com" run_speed claim "$FEATURE")
assert_contains "B claims after release" "$output" "Claimed"


# ── Step 6: Roster has email ─────────────────────────────────

echo ""
echo "--- Step 6: Roster entry has email ---"

roster_file=$(ls "${TEST_DIR}/.speed/shared/roster"/*.json 2>/dev/null | tail -1)
if [[ -n "$roster_file" ]]; then
    roster_email=$(jq -r '.email // "MISSING"' "$roster_file")
    assert_contains "roster has @" "$roster_email" "@"
else
    echo "  FAIL: no roster file found"
    ((FAIL++)) || true
fi


# ── Step 7: Cleanup ──────────────────────────────────────────

echo ""
echo "--- Step 7: B releases (cleanup) ---"

output=$(SPEED_ACTOR="Alex" SPEED_ACTOR_EMAIL="alex-b@test.com" run_speed release "$FEATURE")
assert_contains "final release" "$output" "Released"


# ── Summary ──────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed"
echo "════════════════════════════════════════"

[[ $FAIL -eq 0 ]] && exit 0 || exit 1
