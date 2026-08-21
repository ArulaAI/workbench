#!/usr/bin/env bash
# test_actor_identity.sh — Tests for email-based actor identity
#
# 40 test sections covering spec, coverage gaps, and edge cases:
#   actor.sh (8), events.sh (3), ownership.sh (9), cmd/claim.sh (1),
#   roster.sh (4), coverage gaps (6), edge cases (4), integration (5)
#
# The 8 server.py tests are in test_server_identity.py.
#
# Run: bash tests/test_actor_identity.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DIR=$(mktemp -d "${TMPDIR:-/tmp}/speed-identity-test-XXXXXX")
PASS=0
FAIL=0
SERVER_PID=""

cleanup() {
    [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true
    rm -rf "$TEST_DIR"
}
trap cleanup EXIT

# Scope temp files to the test directory
export TMPDIR="$TEST_DIR"

# ── Harness ──────────────────────────────────────────────────

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

assert_not_contains() {
    local label="$1" haystack="$2" needle="$3"
    if ! echo "$haystack" | grep -qF "$needle"; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label (output should not contain '$needle')"
        ((FAIL++)) || true
    fi
}

assert_not_empty() {
    local label="$1" value="$2"
    if [[ -n "$value" ]]; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label (value is empty)"
        ((FAIL++)) || true
    fi
}

assert_empty() {
    local label="$1" value="$2"
    if [[ -z "$value" ]]; then
        echo "  PASS: $label"
        ((PASS++)) || true
    else
        echo "  FAIL: $label (expected empty, got '$value')"
        ((FAIL++)) || true
    fi
}

reset_actor() {
    unset SPEED_ACTOR SPEED_ACTOR_EMAIL 2>/dev/null || true
    _ACTOR_CACHE=""
    _ACTOR_EMAIL_CACHE=""
}

set_actor() {
    export SPEED_ACTOR="$1"
    export SPEED_ACTOR_EMAIL="$2"
    _ACTOR_CACHE=""
    _ACTOR_EMAIL_CACHE=""
}

clean_events() {
    rm -f "${STATE_DIR}/shared/events"/*.jsonl
}

clean_roster() {
    rm -f "${STATE_DIR}/shared/roster"/*.json
}

# Write a claim event with an explicit timestamp (no sleep needed).
write_claim_event() {
    local feature="$1" actor="$2" actor_email="${3:-}" ts="${4:-2099-01-01T00:00:00Z}"
    local events_dir="${STATE_DIR}/shared/events"
    local safe_ts="${ts//:/-}"
    local slug
    slug=$(echo "$actor" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | sed 's/[^a-z0-9-]//g')
    local fname="${safe_ts}_${slug}_feature-claimed_${feature}.jsonl"
    if [[ -n "$actor_email" ]]; then
        jq -nc --arg ts "$ts" --arg a "$actor" --arg e "$actor_email" --arg f "$feature" \
            '{timestamp:$ts,type:"feature.claimed",feature:$f,actor:$a,actor_email:$e,data:{actor:$a,actor_email:$e}}' \
            > "${events_dir}/${fname}"
    else
        jq -nc --arg ts "$ts" --arg a "$actor" --arg f "$feature" \
            '{timestamp:$ts,type:"feature.claimed",feature:$f,actor:$a,data:{actor:$a}}' \
            > "${events_dir}/${fname}"
    fi
}

write_release_event() {
    local feature="$1" actor="$2" ts="${3:-2099-01-02T00:00:00Z}"
    local events_dir="${STATE_DIR}/shared/events"
    local safe_ts="${ts//:/-}"
    local slug
    slug=$(echo "$actor" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | sed 's/[^a-z0-9-]//g')
    local fname="${safe_ts}_${slug}_feature-released_${feature}.jsonl"
    jq -nc --arg ts "$ts" --arg a "$actor" --arg f "$feature" \
        '{timestamp:$ts,type:"feature.released",feature:$f,actor:$a}' \
        > "${events_dir}/${fname}"
}

write_task_event() {
    local event_type="$1" feature="$2" actor="$3" actor_email="${4:-}" task_id="${5:-1}" ts="${6:-2099-01-01T01:00:00Z}"
    local events_dir="${STATE_DIR}/shared/events"
    local safe_ts="${ts//:/-}"
    local safe_type
    safe_type=$(echo "$event_type" | tr '.' '-')
    local slug
    slug=$(echo "$actor" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | sed 's/[^a-z0-9-]//g')
    local fname="${safe_ts}_${slug}_${safe_type}_${feature}.jsonl"
    if [[ -n "$actor_email" ]]; then
        jq -nc --arg t "$event_type" --arg f "$feature" --arg a "$actor" \
              --arg e "$actor_email" --arg ts "$ts" --arg tid "$task_id" \
            '{timestamp:$ts,type:$t,feature:$f,actor:$a,actor_email:$e,data:{id:$tid,title:"task"}}' \
            > "${events_dir}/${fname}"
    else
        jq -nc --arg t "$event_type" --arg f "$feature" --arg a "$actor" \
              --arg ts "$ts" --arg tid "$task_id" \
            '{timestamp:$ts,type:$t,feature:$f,actor:$a,data:{id:$tid,title:"task"}}' \
            > "${events_dir}/${fname}"
    fi
}

# ── Setup ────────────────────────────────────────────────────

echo "Setting up test project in $TEST_DIR"
cd "$TEST_DIR"
git init -q
git config user.name "TestUser"
git config user.email "testuser@example.com"
git commit --allow-empty -m "init" -q

mkdir -p .speed/shared/events .speed/shared/features
mkdir -p .speed/shared/roster .speed/local/locks

export SPEED_DIR="$SCRIPT_DIR"
export SPEED_PROJECT_ROOT="$TEST_DIR"
export PROJECT_ROOT="$TEST_DIR"

STATE_DIR="${PROJECT_ROOT}/.speed"
SHARED_FEATURES_DIR="${STATE_DIR}/shared/features"
LOCAL_DIR="${STATE_DIR}/local"
source "$SCRIPT_DIR/lib/colors.sh"
source "$SCRIPT_DIR/lib/log.sh"
source "$SCRIPT_DIR/lib/actor.sh"
source "$SCRIPT_DIR/lib/multiplayer.sh"
source "$SCRIPT_DIR/lib/events.sh"
source "$SCRIPT_DIR/lib/ownership.sh"
source "$SCRIPT_DIR/lib/roster.sh"
source "$SCRIPT_DIR/lib/cmd/claim.sh"

MP_ENABLED="true"
OWNERSHIP_STALE_WINDOW=999999
_SPEED_CURRENT_COMMAND="test"


# ═══════════════════════════════════════════════════════════════
# Unit tests — lib/actor.sh (8 tests)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "=== actor.sh: actor_email_resolve / actor_email_get ==="

# 1. test_email_resolve_env_precedence
# Spec: set BOTH env AND git email to different values, verify env wins
reset_actor
git config user.email "other@git.com"
result=$(SPEED_ACTOR_EMAIL="test@env.com" actor_email_resolve)
git config user.email "testuser@example.com"
assert_eq "test_email_resolve_env_precedence" "test@env.com" "$result"

# 2. test_email_resolve_git_fallback
reset_actor
result=$(actor_email_resolve)
assert_eq "test_email_resolve_git_fallback" "testuser@example.com" "$result"

# 3. test_email_resolve_synthetic_fallback
# Distinct from #4: git config fails entirely (truly unset), not empty string
reset_actor
export SPEED_ACTOR="SyntheticUser"
_ACTOR_CACHE=""
git() {
    if [[ "${1:-}" == "config" && "${2:-}" == "user.email" ]]; then
        return 1
    fi
    command git "$@"
}
result=$(actor_email_resolve)
unset -f git
assert_eq "test_email_resolve_synthetic_fallback" "SyntheticUser@local" "$result"
unset SPEED_ACTOR
_ACTOR_CACHE=""

# 4. test_email_resolve_empty_git_email
# Distinct from #3: git config succeeds but returns empty string
reset_actor
export SPEED_ACTOR="EmptyEmailUser"
_ACTOR_CACHE=""
git() {
    if [[ "${1:-}" == "config" && "${2:-}" == "user.email" ]]; then
        echo ""
        return 0
    fi
    command git "$@"
}
result=$(actor_email_resolve)
unset -f git
assert_eq "test_email_resolve_empty_git_email" "EmptyEmailUser@local" "$result"
unset SPEED_ACTOR
_ACTOR_CACHE=""

# 5. test_email_resolve_always_contains_at (all three fallback paths)
reset_actor
result_env=$(SPEED_ACTOR_EMAIL="a@env.com" actor_email_resolve)
assert_contains "test_email_resolve_always_contains_at (env)" "$result_env" "@"
reset_actor
result_git=$(actor_email_resolve)
assert_contains "test_email_resolve_always_contains_at (git)" "$result_git" "@"
reset_actor
export SPEED_ACTOR="AtUser"
_ACTOR_CACHE=""
git() { if [[ "${1:-}" == "config" && "${2:-}" == "user.email" ]]; then return 1; fi; command git "$@"; }
result_synth=$(actor_email_resolve)
unset -f git
assert_contains "test_email_resolve_always_contains_at (synthetic)" "$result_synth" "@"
unset SPEED_ACTOR; _ACTOR_CACHE=""

# 6. test_email_resolve_never_empty (all three fallback paths)
reset_actor
result_env=$(SPEED_ACTOR_EMAIL="a@env.com" actor_email_resolve)
assert_not_empty "test_email_resolve_never_empty (env)" "$result_env"
reset_actor
result_git=$(actor_email_resolve)
assert_not_empty "test_email_resolve_never_empty (git)" "$result_git"
reset_actor
export SPEED_ACTOR="NonEmptyUser"; _ACTOR_CACHE=""
git() { if [[ "${1:-}" == "config" && "${2:-}" == "user.email" ]]; then return 1; fi; command git "$@"; }
result_synth=$(actor_email_resolve)
unset -f git
assert_not_empty "test_email_resolve_never_empty (synthetic)" "$result_synth"
unset SPEED_ACTOR; _ACTOR_CACHE=""

# 7. test_email_get_caches (verify resolve called exactly once)
counter_file=$(mktemp)
bash -c '
source "'"$SCRIPT_DIR"'/lib/actor.sh"
counter="'"$counter_file"'"
actor_email_resolve() { echo 1 >> "$counter"; echo "cached@test.com"; }
_ACTOR_EMAIL_CACHE=""
actor_email_get >/dev/null
actor_email_get >/dev/null
' 2>/dev/null
count=$(wc -l < "$counter_file" | tr -d ' ')
rm -f "$counter_file"
assert_eq "test_email_get_caches (resolve called once)" "1" "$count"

# 8. test_email_get_consistent
reset_actor
first=$(actor_email_get)
second=$(actor_email_get)
assert_eq "test_email_get_consistent" "$first" "$second"


# ═══════════════════════════════════════════════════════════════
# Unit tests — lib/events.sh (3 tests)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "=== events.sh: actor_email in event payload ==="

clean_events

# 9. test_event_payload_has_actor_email
reset_actor
set_actor "EventUser" "eventuser@test.com"
event_emit "test.identity" "test-feature" '{"test": true}'
event_files=("${STATE_DIR}/shared/events"/*_test-identity_test-feature.jsonl)
event_file="${event_files[0]:-}"
if [[ -n "$event_file" ]] && [[ -f "$event_file" ]]; then
    ev_email=$(jq -r '.actor_email // "MISSING"' "$event_file")
    expected_email=$(actor_email_get)
    assert_eq "test_event_payload_has_actor_email (value)" "$expected_email" "$ev_email"
else
    echo "  FAIL: test_event_payload_has_actor_email (event file not created)"
    ((FAIL++)) || true
fi

# 10. test_event_payload_preserves_existing_fields
if [[ -n "$event_file" ]] && [[ -f "$event_file" ]]; then
    assert_not_empty "test_event_payload_preserves_existing_fields (timestamp)" "$(jq -r '.timestamp' "$event_file")"
    assert_eq "test_event_payload_preserves_existing_fields (type)" "test.identity" "$(jq -r '.type' "$event_file")"
    assert_eq "test_event_payload_preserves_existing_fields (feature)" "test-feature" "$(jq -r '.feature' "$event_file")"
    assert_eq "test_event_payload_preserves_existing_fields (actor)" "EventUser" "$(jq -r '.actor' "$event_file")"
    assert_eq "test_event_payload_preserves_existing_fields (data.test)" "true" "$(jq -r '.data.test' "$event_file")"
else
    echo "  FAIL: test_event_payload_preserves_existing_fields (event file not created)"
    ((FAIL++)) || true
fi

# 11. test_event_payload_actor_email_from_env
clean_events
reset_actor
set_actor "CIRunner" "ci@runner.local"
event_emit "test.env" "test-feature" '{}'
env_files=("${STATE_DIR}/shared/events"/*_test-env_test-feature.jsonl)
env_file="${env_files[0]:-}"
if [[ -n "$env_file" ]] && [[ -f "$env_file" ]]; then
    assert_eq "test_event_payload_actor_email_from_env" "ci@runner.local" "$(jq -r '.actor_email' "$env_file")"
else
    echo "  FAIL: test_event_payload_actor_email_from_env (event file not created)"
    ((FAIL++)) || true
fi


# ═══════════════════════════════════════════════════════════════
# Unit tests — lib/ownership.sh (9 tests)
# Each test writes its own events (no ordering dependency).
# ═══════════════════════════════════════════════════════════════
echo ""
echo "=== ownership.sh: email-based matching ==="

# 12. test_ownership_email_match
clean_events
write_claim_event "own-12" "Alice" "alice@co.com"
set_actor "Alice" "alice@co.com"
ownership_check "own-12" && rc=0 || rc=$?
assert_eq "test_ownership_email_match" "0" "$rc"

# 13. test_ownership_email_mismatch
clean_events
write_claim_event "own-13" "Alice" "alice@co.com"
set_actor "Bob" "bob@co.com"
ownership_check "own-13" && rc=0 || rc=$?
assert_eq "test_ownership_email_mismatch (returns 1)" "1" "$rc"
assert_eq "test_ownership_email_mismatch (OWNERSHIP_OWNER)" "Alice" "$OWNERSHIP_OWNER"

# 14. test_ownership_name_collision_resolved
clean_events
write_claim_event "own-14" "John Smith" "john.s@teamA.com"
set_actor "John Smith" "john.s@teamB.com"
ownership_check "own-14" && rc=0 || rc=$?
assert_eq "test_ownership_name_collision_resolved" "1" "$rc"

# 15. test_ownership_same_email_different_name
clean_events
write_claim_event "own-15" "Johnny" "john@co.com"
set_actor "John Smith" "john@co.com"
ownership_check "own-15" && rc=0 || rc=$?
assert_eq "test_ownership_same_email_different_name" "0" "$rc"

# 16. test_ownership_fallback_old_event
clean_events
write_claim_event "own-16" "OldUser" ""  # no actor_email
reset_actor
export SPEED_ACTOR="OldUser"
unset SPEED_ACTOR_EMAIL 2>/dev/null || true
_ACTOR_CACHE=""; _ACTOR_EMAIL_CACHE=""
ownership_check "own-16" && rc=0 || rc=$?
assert_eq "test_ownership_fallback_old_event" "0" "$rc"

# 17. test_ownership_fallback_old_event_mismatch
clean_events
write_claim_event "own-17" "OldUser" ""  # no actor_email
reset_actor
export SPEED_ACTOR="DifferentUser"
unset SPEED_ACTOR_EMAIL 2>/dev/null || true
_ACTOR_CACHE=""; _ACTOR_EMAIL_CACHE=""
ownership_check "own-17" && rc=0 || rc=$?
assert_eq "test_ownership_fallback_old_event_mismatch" "1" "$rc"

# 18. test_ownership_owner_email_exposed
clean_events
write_claim_event "own-18" "Alice" "alice@co.com"
set_actor "Alice" "alice@co.com"
OWNERSHIP_OWNER_EMAIL=""
ownership_check "own-18" && rc=0 || rc=$?
assert_eq "test_ownership_owner_email_exposed" "alice@co.com" "$OWNERSHIP_OWNER_EMAIL"

# 19. test_ownership_release_clears_email (explicit timestamps, no sleep)
clean_events
write_claim_event "own-19" "Alice" "alice@co.com" "2099-01-01T00:00:00Z"
write_release_event "own-19" "Alice" "2099-01-02T00:00:00Z"
set_actor "Alice" "alice@co.com"
OWNERSHIP_OWNER_EMAIL="should-be-cleared"
ownership_check "own-19" && rc=0 || rc=$?
assert_eq "test_ownership_release_clears_email (returns 2)" "2" "$rc"
assert_empty "test_ownership_release_clears_email (email empty)" "$OWNERSHIP_OWNER_EMAIL"

# 20. test_ownership_stale_claim_with_email
clean_events
write_claim_event "own-20" "StaleUser" "stale@co.com" "2000-01-01T00:00:00Z"
set_actor "StaleUser" "stale@co.com"
saved_stale=$OWNERSHIP_STALE_WINDOW
OWNERSHIP_STALE_WINDOW=1
ownership_check "own-20" && rc=0 || rc=$?
OWNERSHIP_STALE_WINDOW=$saved_stale
assert_eq "test_ownership_stale_claim_with_email" "2" "$rc"


# ═══════════════════════════════════════════════════════════════
# Unit tests — lib/cmd/claim.sh (1 test)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "=== cmd/claim.sh: actor_email in claim event ==="

# 21. test_claim_event_has_email
clean_events
set_actor "ClaimUser" "claim@test.com"
cmd_claim "claim-email-test"
claim_files=("${STATE_DIR}/shared/events"/*_feature-claimed_claim-email-test.jsonl)
claim_file="${claim_files[-1]:-}"
if [[ -n "$claim_file" ]] && [[ -f "$claim_file" ]]; then
    assert_eq "test_claim_event_has_email (top-level)" "claim@test.com" "$(jq -r '.actor_email' "$claim_file")"
    assert_eq "test_claim_event_has_email (data.actor_email)" "claim@test.com" "$(jq -r '.data.actor_email' "$claim_file")"
else
    echo "  FAIL: test_claim_event_has_email (event file not created)"
    ((FAIL++)) || true
fi


# ═══════════════════════════════════════════════════════════════
# Unit tests — lib/roster.sh (4 tests)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "=== roster.sh: email in roster entries ==="

# 22. test_roster_heartbeat_includes_email
clean_roster
set_actor "RosterUser" "roster@test.com"
roster_heartbeat
roster_files=("${STATE_DIR}/shared/roster"/*.json)
roster_file="${roster_files[0]:-}"
if [[ -n "$roster_file" ]] && [[ -f "$roster_file" ]]; then
    file_email=$(jq -r '.email // "MISSING"' "$roster_file")
    expected_email=$(actor_email_get)
    assert_eq "test_roster_heartbeat_includes_email" "$expected_email" "$file_email"
else
    echo "  FAIL: test_roster_heartbeat_includes_email (file not created)"
    ((FAIL++)) || true
fi

# 23. test_roster_list_with_email
clean_roster
now_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cat > "${STATE_DIR}/shared/roster/actor-with-email.json" <<EOF
{"name":"Actor A","email":"a@example.com","active_feature":"feat-x","active_stage":"plan","last_seen":"${now_ts}","last_command":"plan"}
EOF
result=$(roster_list)
assert_not_empty "test_roster_list_with_email (returns entries)" "$result"
assert_eq "test_roster_list_with_email (name)" "Actor A" "$(echo "$result" | jq -r '.[0].name')"

# 24. test_roster_list_without_email
clean_roster
now_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cat > "${STATE_DIR}/shared/roster/actor-old.json" <<EOF
{"name":"Old Actor","active_feature":"","active_stage":"","last_seen":"${now_ts}","last_command":"status"}
EOF
result=$(roster_list)
assert_not_empty "test_roster_list_without_email (returns entries)" "$result"
assert_eq "test_roster_list_without_email (name)" "Old Actor" "$(echo "$result" | jq -r '.[0].name')"

# 25. test_roster_format_table_unchanged
clean_roster
now_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cat > "${STATE_DIR}/shared/roster/actor-table.json" <<EOF
{"name":"TableUser","email":"table@test.com","active_feature":"feat-y","active_stage":"idle","last_seen":"${now_ts}","last_command":"status"}
EOF
output=$(BOLD="" RESET="" roster_format_table)
assert_contains "test_roster_format_table_unchanged (ACTOR)" "$output" "ACTOR"
assert_contains "test_roster_format_table_unchanged (FEATURE)" "$output" "FEATURE"
assert_not_contains "test_roster_format_table_unchanged (no email in output)" "$output" "table@test.com"


# ═══════════════════════════════════════════════════════════════
# Coverage gap tests (6)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "=== Coverage gaps: ownership_require, ownership_current_owner, event_prune, event_replay_all ==="

# 26. test_ownership_require_rejects_non_owner
clean_events
write_claim_event "req-26" "Alice" "alice@co.com"
set_actor "Bob" "bob@co.com"
rc=0
(ownership_require "req-26") 2>/dev/null || rc=$?
assert_eq "test_ownership_require_rejects_non_owner" "1" "$rc"

# 27. test_ownership_current_owner_returns_name
clean_events
write_claim_event "cur-27" "Alice" "alice@co.com"
set_actor "Bob" "bob@co.com"
owner=$(ownership_current_owner "cur-27")
assert_eq "test_ownership_current_owner_returns_name" "Alice" "$owner"

# 28. test_event_prune_archives_old_events
clean_events
# Create an event with a very old filename timestamp
echo '{"timestamp":"2000-01-01T00:00:00Z","type":"task.created","feature":"prune-feat","actor":"Dev","data":{"id":"1"}}' \
    > "${STATE_DIR}/shared/events/20000101T000000Z_dev_task-created_prune-feat.jsonl"
event_prune 1
# Verify the original was deleted and archive was created
if [[ ! -f "${STATE_DIR}/shared/events/20000101T000000Z_dev_task-created_prune-feat.jsonl" ]] && \
   [[ -f "${STATE_DIR}/shared/events/prune-feat-archive.jsonl" ]]; then
    echo "  PASS: test_event_prune_archives_old_events"
    ((PASS++)) || true
else
    echo "  FAIL: test_event_prune_archives_old_events (old event not archived)"
    ((FAIL++)) || true
fi

# 29. test_event_prune_keeps_recent_events
clean_events
set_actor "Dev" "dev@co.com"
event_emit "task.created" "keep-feat" '{"id":"1"}'
event_prune 1
recent_files=("${STATE_DIR}/shared/events"/*_task-created_keep-feat.jsonl)
if [[ -f "${recent_files[0]:-}" ]]; then
    echo "  PASS: test_event_prune_keeps_recent_events"
    ((PASS++)) || true
else
    echo "  FAIL: test_event_prune_keeps_recent_events (recent event was pruned)"
    ((FAIL++)) || true
fi

# 30. test_event_prune_skips_archive_files
clean_events
echo '{"archived":true}' > "${STATE_DIR}/shared/events/old-feat-archive.jsonl"
event_prune 1
if [[ -f "${STATE_DIR}/shared/events/old-feat-archive.jsonl" ]]; then
    echo "  PASS: test_event_prune_skips_archive_files"
    ((PASS++)) || true
else
    echo "  FAIL: test_event_prune_skips_archive_files (archive file was deleted)"
    ((FAIL++)) || true
fi

# 31. test_event_replay_all_valid_json
clean_events
write_claim_event "replay-x" "Alice" "alice@co.com" "2099-01-01T00:00:00Z"
write_task_event "task.created" "replay-x" "Alice" "alice@co.com" "t1" "2099-01-01T01:00:00Z"
write_claim_event "replay-y" "Bob" "bob@co.com" "2099-01-01T00:00:00Z"
result=$(event_replay_all)
jq_ok=false
echo "$result" | jq . >/dev/null 2>&1 && jq_ok=true
assert_eq "test_event_replay_all_valid_json (parses)" "true" "$jq_ok"
assert_eq "test_event_replay_all_valid_json (has replay-x)" "true" "$(echo "$result" | jq 'has("replay-x")')"
assert_eq "test_event_replay_all_valid_json (has replay-y)" "true" "$(echo "$result" | jq 'has("replay-y")')"


# ═══════════════════════════════════════════════════════════════
# Edge case tests (4)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "=== Edge cases ==="

# 32. test_edge_garbage_email_passthrough
# Spec: SPEED_ACTOR_EMAIL set to string without @ passes through, no shell validation
reset_actor
result=$(SPEED_ACTOR_EMAIL="garbage" actor_email_resolve)
assert_eq "test_edge_garbage_email_passthrough" "garbage" "$result"

# 33. test_edge_null_actor_email_in_event
# Spec: event with actor_email: null treated as absent, falls back to name comparison
clean_events
echo '{"timestamp":"2099-01-01T00:00:00Z","type":"feature.claimed","feature":"null-email","actor":"NullUser","actor_email":null,"data":{}}' \
    > "${STATE_DIR}/shared/events/2099-01-01T00-00-00Z_nulluser_feature-claimed_null-email.jsonl"
reset_actor
export SPEED_ACTOR="NullUser"
unset SPEED_ACTOR_EMAIL 2>/dev/null || true
_ACTOR_CACHE=""; _ACTOR_EMAIL_CACHE=""
ownership_check "null-email" && rc=0 || rc=$?
assert_eq "test_edge_null_actor_email_in_event (name fallback)" "0" "$rc"

# 34. test_edge_special_chars_in_actor_name
# Spec: special chars in actor name produce {name}@local that works as comparison key
reset_actor
export SPEED_ACTOR="José García"
_ACTOR_CACHE=""
git() { if [[ "${1:-}" == "config" && "${2:-}" == "user.email" ]]; then return 1; fi; command git "$@"; }
result=$(actor_email_resolve)
unset -f git
assert_eq "test_edge_special_chars_in_actor_name" "José García@local" "$result"
assert_contains "test_edge_special_chars_in_actor_name (contains @)" "$result" "@"
unset SPEED_ACTOR; _ACTOR_CACHE=""

# 35. test_edge_email_change_between_sessions
# Spec: developer changes git email. Old claim retains old email. Developer is a non-owner now.
clean_events
write_claim_event "email-change" "Dev" "old@company.com"
set_actor "Dev" "new@company.com"
ownership_check "email-change" && rc=0 || rc=$?
assert_eq "test_edge_email_change_between_sessions (different person)" "1" "$rc"


# ═══════════════════════════════════════════════════════════════
# Integration tests (5)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "=== Integration tests ==="

# 36. test_full_claim_ownership_cycle_email
echo "  --- test_full_claim_ownership_cycle_email ---"
clean_events

# Actor A claims (explicit timestamp)
write_claim_event "cycle" "Alex" "alex-a@example.com" "2099-01-01T00:00:00Z"

# A owns it
set_actor "Alex" "alex-a@example.com"
ownership_check "cycle" && rc=0 || rc=$?
assert_eq "test_full_claim_ownership_cycle_email (A owns)" "0" "$rc"

# B (same name, different email) is rejected
set_actor "Alex" "alex-b@example.com"
ownership_check "cycle" && rc=0 || rc=$?
assert_eq "test_full_claim_ownership_cycle_email (B rejected)" "1" "$rc"

# ownership_require also rejects B (subshell to catch exit)
rc=0
(ownership_require "cycle") 2>/dev/null || rc=$?
assert_eq "test_full_claim_ownership_cycle_email (ownership_require rejects B)" "1" "$rc"

# A releases (explicit timestamp, guaranteed after claim)
write_release_event "cycle" "Alex" "2099-01-02T00:00:00Z"

# B claims (explicit timestamp, guaranteed after release)
write_claim_event "cycle" "Alex" "alex-b@example.com" "2099-01-03T00:00:00Z"
set_actor "Alex" "alex-b@example.com"
ownership_check "cycle" && rc=0 || rc=$?
assert_eq "test_full_claim_ownership_cycle_email (B owns after release)" "0" "$rc"

# ownership_require succeeds for B
rc=0
(ownership_require "cycle") 2>/dev/null || rc=$?
assert_eq "test_full_claim_ownership_cycle_email (ownership_require accepts B)" "0" "$rc"


# 37. test_http_claim_email
echo "  --- test_http_claim_email ---"

# Dynamic port allocation
http_port=$(python3 -c "import socket; s=socket.socket(); s.bind(('',0)); print(s.getsockname()[1]); s.close()")

export SPEED_EVENTS_DIR="${STATE_DIR}/shared/events"
export SPEED_STATE_DIR="${STATE_DIR}"
export SPEED_SERVE_PORT="$http_port"
export SPEED_SHARED_DIR="${STATE_DIR}/shared"
export SPEED_ROSTER_DIR="${STATE_DIR}/shared/roster"

python3 -c "
import sys, os
sys.path.insert(0, '$SCRIPT_DIR')
import lib.serve.server as srv
from pathlib import Path
srv.PORT = $http_port
srv.EVENTS_DIR = Path('${STATE_DIR}/shared/events')
srv.STATE_DIR = Path('${STATE_DIR}')
srv.SHARED_DIR = Path('${STATE_DIR}/shared')
srv.ROSTER_DIR = Path('${STATE_DIR}/shared/roster')
srv.main()
" &
SERVER_PID=$!

ready=false
for _i in $(seq 1 20); do
    if curl -s "http://127.0.0.1:${http_port}/api/health" >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 0.2
done

if $ready; then
    response=$(curl -s -X POST "http://127.0.0.1:${http_port}/api/claim" \
        -H "Content-Type: application/json" \
        -d '{"feature":"http-feat","actor":"HttpUser","actor_email":"http@example.com"}')
    kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null || true
    SERVER_PID=""

    assert_eq "test_http_claim_email (success)" "true" "$(echo "$response" | jq -r '.success')"

    http_event_files=("${STATE_DIR}/shared/events"/*feature-claimed*http-feat*.jsonl)
    http_event="${http_event_files[-1]:-}"
    if [[ -n "$http_event" ]] && [[ -f "$http_event" ]]; then
        assert_eq "test_http_claim_email (actor_email)" "http@example.com" "$(jq -r '.actor_email' "$http_event")"
        assert_eq "test_http_claim_email (actor)" "HttpUser" "$(jq -r '.actor' "$http_event")"
    else
        echo "  FAIL: test_http_claim_email (event file not written)"
        ((FAIL++)) || true
    fi
else
    kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null || true
    SERVER_PID=""
    echo "  FAIL: test_http_claim_email (server failed to start)"
    ((FAIL++)) || true
fi


# 38. test_mixed_event_timeline (explicit timestamps, includes event_replay)
echo "  --- test_mixed_event_timeline ---"
clean_events

# Phase 1: old-format claim by Alice (no actor_email)
write_claim_event "timeline" "Alice" "" "2099-01-01T00:00:00Z"

# Alice with email: name fallback matches
set_actor "Alice" "alice@example.com"
ownership_check "timeline" && rc=0 || rc=$?
assert_eq "test_mixed_event_timeline (old event, Alice match)" "0" "$rc"

# Bob rejected via name fallback
set_actor "Bob" "bob@example.com"
ownership_check "timeline" && rc=0 || rc=$?
assert_eq "test_mixed_event_timeline (old event, Bob rejected)" "1" "$rc"

# Phase 2: release, then new-format claim by Bob
write_release_event "timeline" "Alice" "2099-01-02T00:00:00Z"
write_claim_event "timeline" "Bob" "bob@example.com" "2099-01-03T00:00:00Z"

# Bob owns (email match)
set_actor "Bob" "bob@example.com"
ownership_check "timeline" && rc=0 || rc=$?
assert_eq "test_mixed_event_timeline (new event, Bob owns)" "0" "$rc"

# Alice rejected (email mismatch)
set_actor "Alice" "alice@example.com"
ownership_check "timeline" && rc=0 || rc=$?
assert_eq "test_mixed_event_timeline (new event, Alice rejected)" "1" "$rc"

# event_replay across the timeline should still work
replay_result=$(event_replay "timeline")
assert_not_empty "test_mixed_event_timeline (event_replay works)" "$replay_result"
assert_eq "test_mixed_event_timeline (replay owner)" "Bob" "$(echo "$replay_result" | jq -r '.feature.owner')"


# 39. test_event_replay_ignores_email (explicit timestamps, no sleep)
echo "  --- test_event_replay_ignores_email ---"
clean_events

write_claim_event "replay-feat" "Dev" "dev@co.com" "2099-01-01T00:00:00Z"
write_task_event "task.created" "replay-feat" "Dev" "dev@co.com" "t1" "2099-01-01T01:00:00Z"
write_task_event "task.started" "replay-feat" "Dev" "dev@co.com" "t1" "2099-01-01T02:00:00Z"
write_task_event "task.completed" "replay-feat" "Dev" "dev@co.com" "t1" "2099-01-01T03:00:00Z"

result=$(event_replay "replay-feat")
if [[ -n "$result" ]] && [[ "$result" != "{}" ]]; then
    assert_eq "test_event_replay_ignores_email (feature status)" "claimed" "$(echo "$result" | jq -r '.feature.status')"
    assert_eq "test_event_replay_ignores_email (owner)" "Dev" "$(echo "$result" | jq -r '.feature.owner')"
    assert_eq "test_event_replay_ignores_email (task t1 done)" "done" "$(echo "$result" | jq -r '.tasks.t1.status')"
else
    echo "  FAIL: test_event_replay_ignores_email (replay returned empty)"
    ((FAIL++)) || true
fi


# 40. test_backward_compat_event_list
echo "  --- test_backward_compat_event_list ---"
clean_events

write_claim_event "list-a" "Alice" "alice@co.com" "2099-01-01T00:00:00Z"
write_claim_event "list-b" "Bob" "bob@co.com" "2099-01-01T00:01:00Z"
write_task_event "task.created" "list-a" "Alice" "alice@co.com" "t1" "2099-01-01T00:02:00Z"

# Feature filter
feat_events=$(event_list "list-a")
assert_not_empty "test_backward_compat_event_list (feature filter)" "$feat_events"
wrong=$(echo "$feat_events" | jq -r 'select(.feature != "list-a") | .feature' 2>/dev/null)
assert_empty "test_backward_compat_event_list (no wrong features)" "$wrong"

# Type filter
claim_events=$(event_list "list-a" "feature.claimed")
assert_not_empty "test_backward_compat_event_list (type filter)" "$claim_events"
assert_eq "test_backward_compat_event_list (actor_email preserved)" "alice@co.com" "$(echo "$claim_events" | jq -r '.actor_email')"

# Type filter across all features
all_claims=$(event_list "" "feature.claimed")
all_claim_count=$(echo "$all_claims" | jq -r '.type' | grep -c "feature.claimed")
assert_eq "test_backward_compat_event_list (2 claims total)" "2" "$all_claim_count"


# ── Summary ──────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed"
echo "════════════════════════════════════════"

[[ $FAIL -eq 0 ]] && exit 0 || exit 1
