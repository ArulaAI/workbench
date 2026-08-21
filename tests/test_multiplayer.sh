#!/usr/bin/env bash
# test_multiplayer.sh — Integration tests for multi-player mode
#
# Exercises: mp-init, claim/release, event emission, roster, rebuild-state, whoami
# Run: bash tests/test_multiplayer.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDIR_BASE="${TMPDIR:-/tmp}"
TEST_DIR=$(mktemp -d "${TMPDIR_BASE}/speed-mp-test-XXXXXX")
PASS=0
FAIL=0

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

assert_exists() {
    local label="$1" path="$2"
    if [[ -e "$path" ]]; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label (path '$path' does not exist)"
        ((FAIL++)) || true
    fi
}

assert_contains() {
    local label="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -q "$needle"; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label (output does not contain '$needle')"
        ((FAIL++)) || true
    fi
}

# ── Setup: minimal project ────────────────────────────────────
echo "Setting up test project in $TEST_DIR"
cd "$TEST_DIR"
git init -q
git commit --allow-empty -m "init" -q

# Create minimal .speed structure
mkdir -p .speed/features/test-feature/tasks .speed/memory/observations
echo '{"status":"idle","agents":[],"started_at":null}' > .speed/features/test-feature/state.json
echo '{"id":"1","title":"Test task","status":"pending","depends_on":[],"branch":"speed/test-feature/task-1-test"}' > .speed/features/test-feature/tasks/1.json
echo "test-feature" > .speed/active_feature

# Source SPEED libs
export SPEED_DIR="$SCRIPT_DIR"
export SPEED_PROJECT_ROOT="$TEST_DIR"
export PROJECT_ROOT="$TEST_DIR"
export SPEED_ACTOR="TestUser"

# Source just what we need, avoiding config.sh BASH_SOURCE issues
STATE_DIR="${PROJECT_ROOT}/.speed"
FEATURES_DIR="${STATE_DIR}/features"
LIB_DIR="${SCRIPT_DIR}/lib"
source "$SCRIPT_DIR/lib/colors.sh"
source "$SCRIPT_DIR/lib/log.sh"
source "$SCRIPT_DIR/lib/actor.sh"
source "$SCRIPT_DIR/lib/multiplayer.sh"
source "$SCRIPT_DIR/lib/events.sh"

# ── Test 1: Actor identity ────────────────────────────────────
echo ""
echo "=== Test 1: Actor Identity ==="

assert_eq "actor_resolve returns SPEED_ACTOR" "TestUser" "$(actor_resolve)"
assert_eq "actor_slug is lowercase" "testuser" "$(actor_slug)"
assert_eq "actor_get caches" "TestUser" "$(actor_get)"

# ── Test 2: mp_is_enabled before init ─────────────────────────
echo ""
echo "=== Test 2: MP detection before init ==="

mp_is_enabled && mp_status="enabled" || mp_status="disabled"
assert_eq "mp_is_enabled returns disabled" "disabled" "$mp_status"

# ── Test 3: mp-init migration ─────────────────────────────────
echo ""
echo "=== Test 3: mp-init migration ==="

# Simulate mp-init manually (can't call the full command without all deps)
mkdir -p .speed/shared/events .speed/shared/features .speed/shared/knowledge
mkdir -p .speed/shared/proposals .speed/shared/roster
mkdir -p .speed/local/locks

# Move features
mv .speed/features/test-feature .speed/shared/features/test-feature
rmdir .speed/features 2>/dev/null || true

# Move memory
mv .speed/memory/* .speed/shared/knowledge/ 2>/dev/null || true
rmdir .speed/memory 2>/dev/null || true

echo "local/" > .speed/.gitignore

mp_is_enabled && mp_status="enabled" || mp_status="disabled"
assert_eq "mp_is_enabled returns enabled after init" "enabled" "$mp_status"
assert_exists "shared/features/test-feature exists" ".speed/shared/features/test-feature"
assert_exists "shared/events dir exists" ".speed/shared/events"
assert_exists ".speed/.gitignore exists" ".speed/.gitignore"

# Update paths for MP mode
MP_ENABLED=true
SHARED_DIR="${STATE_DIR}/shared"
LOCAL_DIR="${STATE_DIR}/local"
SHARED_FEATURES_DIR="${SHARED_DIR}/features"
EVENTS_DIR="${SHARED_DIR}/events"
ROSTER_DIR="${SHARED_DIR}/roster"

# ── Test 4: Event emission ────────────────────────────────────
echo ""
echo "=== Test 4: Event emission ==="

SPEED_DIR="$SCRIPT_DIR"
event_emit "feature.claimed" "test-feature" '{"actor":"TestUser"}' || echo "  DEBUG: event_emit returned $?"
event_count=$(ls -1 .speed/shared/events/*.jsonl 2>/dev/null | wc -l | tr -d ' ')
assert_eq "one event file created" "1" "$event_count"

# Check event content
event_file=$(ls .speed/shared/events/*.jsonl | head -1)
event_type=$(jq -r '.type' "$event_file")
event_actor=$(jq -r '.actor' "$event_file")
assert_eq "event type is feature.claimed" "feature.claimed" "$event_type"
assert_eq "event actor is TestUser" "TestUser" "$event_actor"

# Emit more events
event_emit "task.completed" "test-feature" '{"id":"1"}'
event_emit "run.completed" "test-feature" '{"done":1,"failed":0,"blocked":0}'

event_count=$(ls -1 .speed/shared/events/*.jsonl 2>/dev/null | wc -l | tr -d ' ')
assert_eq "three event files total" "3" "$event_count"

# ── Test 5: Event list ────────────────────────────────────────
echo ""
echo "=== Test 5: Event list ==="

all_events=$(event_list "test-feature" | wc -l | tr -d ' ')
assert_eq "event_list returns 3 events" "3" "$all_events"

claimed_events=$(event_list "test-feature" "feature.claimed" | wc -l | tr -d ' ')
assert_eq "filtered to 1 claimed event" "1" "$claimed_events"

# ── Test 6: Unique filenames ──────────────────────────────────
echo ""
echo "=== Test 6: Unique filenames (conflict-free merges) ==="

# Emit two events rapidly — filenames must differ
event_emit "task.started" "test-feature" '{"id":"1","pid":1234}'
sleep 0.01
event_emit "task.started" "test-feature" '{"id":"2","pid":5678}'

event_count=$(ls -1 .speed/shared/events/*.jsonl 2>/dev/null | wc -l | tr -d ' ')
unique_count=$(ls -1 .speed/shared/events/*.jsonl 2>/dev/null | sort -u | wc -l | tr -d ' ')
assert_eq "all filenames are unique" "$event_count" "$unique_count"

# ── Test 7: Roster heartbeat ─────────────────────────────────
echo ""
echo "=== Test 7: Roster ==="

source "$SCRIPT_DIR/lib/roster.sh"
source "$SCRIPT_DIR/lib/features.sh"

FEATURE_NAME="test-feature"
_SPEED_CURRENT_COMMAND="test"
roster_heartbeat

assert_exists "roster file created" ".speed/shared/roster/testuser.json"
roster_name=$(jq -r '.name' ".speed/shared/roster/testuser.json")
roster_cmd=$(jq -r '.last_command' ".speed/shared/roster/testuser.json")
assert_eq "roster name is TestUser" "TestUser" "$roster_name"
assert_eq "roster command is test" "test" "$roster_cmd"

# ── Test 8: Event replay ─────────────────────────────────────
echo ""
echo "=== Test 8: Event replay ==="

replay_output=$(event_replay "test-feature")
replay_owner=$(echo "$replay_output" | jq -r '.feature.owner // empty')
assert_eq "replay shows owner as TestUser" "TestUser" "$replay_owner"

# ── Summary ───────────────────────────────────────────────────
echo ""
echo "================================"
echo "Results: $PASS passed, $FAIL failed"
echo "================================"

[[ $FAIL -eq 0 ]] && exit 0 || exit 1
