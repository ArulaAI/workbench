#!/usr/bin/env bash
# test_multiplayer_ws6_ws7_ws8.sh — Tests for cross-feature, ceremonies, and progressive enhancement
#
# Run: bash tests/test_multiplayer_ws6_ws7_ws8.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDIR_BASE="${TMPDIR:-/tmp}"
TEST_DIR=$(mktemp -d "${TMPDIR_BASE}/speed-mp-ws678-XXXXXX")
PASS=0
FAIL=0

cleanup() { rm -rf "$TEST_DIR"; }
trap cleanup EXIT

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  PASS: $label"; ((PASS++)) || true
    else
        echo "  FAIL: $label (expected '$expected', got '$actual')"; ((FAIL++)) || true
    fi
}
assert_exists() {
    local label="$1" path="$2"
    if [[ -e "$path" ]]; then
        echo "  PASS: $label"; ((PASS++)) || true
    else
        echo "  FAIL: $label ($path missing)"; ((FAIL++)) || true
    fi
}
assert_not_empty() {
    local label="$1" val="$2"
    if [[ -n "$val" ]]; then
        echo "  PASS: $label"; ((PASS++)) || true
    else
        echo "  FAIL: $label (empty)"; ((FAIL++)) || true
    fi
}
assert_gt() {
    local label="$1" a="$2" b="$3"
    if [[ "$a" -gt "$b" ]]; then
        echo "  PASS: $label"; ((PASS++)) || true
    else
        echo "  FAIL: $label ($a not > $b)"; ((FAIL++)) || true
    fi
}

# ── Setup ─────────────────────────────────────────────────────
echo "Setting up test project in $TEST_DIR"
cd "$TEST_DIR"
git init -q
git commit --allow-empty -m "init" -q
mkdir -p specs/tech

# Create two spec files
cat > specs/tech/auth.md <<'EOF'
---
title: Auth Flow
---
## Goal
Add authentication with JWT tokens.
## Data Model
| Entity | Field | Type |
|--------|-------|------|
| users  | email | TEXT |
## Acceptance Criteria
- AC1: Login endpoint returns JWT
EOF

cat > specs/tech/dashboard.md <<'EOF'
---
title: Dashboard
---
## Goal
Build analytics dashboard.
## Data Model
| Entity | Field | Type |
|--------|-------|------|
| metrics | name | TEXT |
## Acceptance Criteria
- AC1: Dashboard shows chart
EOF

# Create MP structure
mkdir -p .speed/shared/{events,features/auth/tasks,features/dashboard/tasks,knowledge,proposals,roster}
mkdir -p .speed/local/{locks,features/auth/logs,features/dashboard/logs}
echo "local/" > .speed/.gitignore

# Create task files with files_touched
echo '{"id":"1","title":"Auth endpoint","status":"done","depends_on":[],"branch":"speed/auth/task-1","files_touched":["src/auth.ts","src/middleware.ts"]}' > .speed/shared/features/auth/tasks/1.json
echo '{"id":"1","title":"Dashboard page","status":"done","depends_on":[],"branch":"speed/dashboard/task-1","files_touched":["src/dashboard.ts","src/middleware.ts"]}' > .speed/shared/features/dashboard/tasks/1.json

# Write spec_path files
echo "specs/tech/auth.md" > .speed/shared/features/auth/spec_path
echo "specs/tech/dashboard.md" > .speed/shared/features/dashboard/spec_path

# Source libs
export SPEED_DIR="$SCRIPT_DIR" SPEED_PROJECT_ROOT="$TEST_DIR" PROJECT_ROOT="$TEST_DIR"
export SPEED_ACTOR="Alice"
STATE_DIR="${PROJECT_ROOT}/.speed"
LIB_DIR="${SCRIPT_DIR}/lib"
FEATURES_DIR="${STATE_DIR}/features"
SHARED_DIR="${STATE_DIR}/shared"
LOCAL_DIR="${STATE_DIR}/local"
SHARED_FEATURES_DIR="${SHARED_DIR}/features"
EVENTS_DIR="${SHARED_DIR}/events"
ROSTER_DIR="${SHARED_DIR}/roster"
PROPOSALS_DIR="${SHARED_DIR}/proposals"
MP_ENABLED=true

source "$SCRIPT_DIR/lib/colors.sh"
source "$SCRIPT_DIR/lib/log.sh"
source "$SCRIPT_DIR/lib/actor.sh"
source "$SCRIPT_DIR/lib/multiplayer.sh"
source "$SCRIPT_DIR/lib/events.sh"
source "$SCRIPT_DIR/lib/ownership.sh"
source "$SCRIPT_DIR/lib/features.sh"

# ── Test 1: Claim two features by two actors ──────────────────
echo ""
echo "=== Test 1: Multi-actor claims ==="

event_emit "feature.claimed" "auth" '{"actor":"Alice"}'
SPEED_ACTOR="Bob" _ACTOR_CACHE="" event_emit "feature.claimed" "dashboard" '{"actor":"Bob"}'

auth_events=$(ls -1 .speed/shared/events/*_auth.jsonl 2>/dev/null | wc -l | tr -d ' ')
dash_events=$(ls -1 .speed/shared/events/*_dashboard.jsonl 2>/dev/null | wc -l | tr -d ' ')
assert_eq "auth has 1 claim event" "1" "$auth_events"
assert_eq "dashboard has 1 claim event" "1" "$dash_events"

# ── Test 2: Cross-feature file overlap detection ──────────────
echo ""
echo "=== Test 2: File ownership overlap ==="

source "$SCRIPT_DIR/lib/cmd/cross_feature.sh"

overlap_output=$(_cross_feature_file_overlap "auth
dashboard" 2>&1)

# src/middleware.ts is touched by both
echo "$overlap_output" | grep -q "middleware" && overlap_found=true || overlap_found=false
assert_eq "middleware.ts overlap detected" "true" "$overlap_found"

# ── Test 3: Integration order ─────────────────────────────────
echo ""
echo "=== Test 3: Integration order ==="

order_output=$(_cross_feature_integration_order "auth
dashboard" 2>&1)
assert_not_empty "integration order has output" "$order_output"

# ── Test 4: Spec propose/review/ratify flow ───────────────────
echo ""
echo "=== Test 4: Ceremony — Spec Review ==="

source "$SCRIPT_DIR/lib/cmd/ceremony.sh"
SPEC_APPROVAL_THRESHOLD=1

# Propose
event_emit "spec.proposed" "auth" '{"spec_path":"specs/tech/auth.md","spec_hash":"abc123"}'
proposed_events=$(ls -1 .speed/shared/events/*_spec-proposed_auth.jsonl 2>/dev/null | wc -l | tr -d ' ')
assert_eq "spec proposed event exists" "1" "$proposed_events"

# Review (approve)
event_emit "spec.reviewed" "auth" '{"spec_path":"specs/tech/auth.md","verdict":"approve","comment":""}'
reviewed_events=$(ls -1 .speed/shared/events/*_spec-reviewed_auth.jsonl 2>/dev/null | wc -l | tr -d ' ')
assert_eq "spec reviewed event exists" "1" "$reviewed_events"

# Count approvals
approvals=0
for f in .speed/shared/events/*_spec-reviewed_auth.jsonl; do
    [[ -f "$f" ]] || continue
    v=$(jq -r '.data.verdict // ""' "$f" 2>/dev/null)
    [[ "$v" == "approve" ]] && ((approvals++)) || true
done
assert_eq "1 approval counted" "1" "$approvals"

# Ratify
event_emit "spec.ratified" "auth" '{"spec_path":"specs/tech/auth.md","approvals":1}'
ratified_events=$(ls -1 .speed/shared/events/*_spec-ratified_auth.jsonl 2>/dev/null | wc -l | tr -d ' ')
assert_eq "spec ratified event exists" "1" "$ratified_events"

# ── Test 5: Outcome review flow ───────────────────────────────
echo ""
echo "=== Test 5: Ceremony — Outcome Review ==="

event_emit "outcome.review_requested" "auth" '{"tasks":{"total":1,"done":1}}'
requested=$(ls -1 .speed/shared/events/*_outcome-review*_auth.jsonl 2>/dev/null | wc -l | tr -d ' ')
assert_eq "outcome review requested" "1" "$requested"

event_emit "outcome.judged" "auth" '{"verdict":"approve","comment":"looks good"}'
judged=$(ls -1 .speed/shared/events/*_outcome-judged_auth.jsonl 2>/dev/null | wc -l | tr -d ' ')
assert_eq "outcome judged" "1" "$judged"

# ── Test 6: Defect event emissions ────────────────────────────
echo ""
echo "=== Test 6: Defect events ==="

event_emit "defect.filed" "login-bug" '{"severity":"P1"}'
event_emit "defect.transitioned" "login-bug" '{"from":"filed","to":"triaging"}'
event_emit "defect.triaged" "login-bug" '{"complexity":"moderate"}'

defect_events=$(ls -1 .speed/shared/events/*_login-bug.jsonl 2>/dev/null | wc -l | tr -d ' ')
assert_eq "3 defect events" "3" "$defect_events"

# ── Test 7: Event pruning ────────────────────────────────────
echo ""
echo "=== Test 7: Event pruning ==="

# Create an old event (fake the filename with an old timestamp)
echo '{"timestamp":"2025-01-01T00:00:00Z","type":"test.old","feature":"auth","actor":"test","data":{}}' > ".speed/shared/events/20250101T000000Z_test_test-old_auth.jsonl"

before_count=$(ls -1 .speed/shared/events/*.jsonl 2>/dev/null | wc -l | tr -d ' ')
event_prune 1  # prune events older than 1 day
after_count=$(ls -1 .speed/shared/events/*.jsonl 2>/dev/null | grep -v archive | wc -l | tr -d ' ')

assert_gt "pruning reduced event count" "$before_count" "$after_count"
assert_exists "archive file created" ".speed/shared/events/auth-archive.jsonl"

# ── Test 8: Actor fields on task JSON ─────────────────────────
echo ""
echo "=== Test 8: Actor attribution ==="

# Simulate task_create with actor
local_task_dir=$(mktemp -d)
TASKS_DIR="$local_task_dir"
BRANCH_PREFIX="speed/test"
FEATURE_NAME="test"
source "$SCRIPT_DIR/lib/tasks.sh"

task_file=$(task_create "99" "Test task" "desc" "criteria" "[]" "sonnet")
claimed_by=$(jq -r '.claimed_by // empty' "$task_file" 2>/dev/null)
assert_eq "task has claimed_by" "Alice" "$claimed_by"

rm -rf "$local_task_dir"

# ── Test 9: Server health endpoint ────────────────────────────
echo ""
echo "=== Test 9: HTTP server ==="

SPEED_SERVE_PORT=44599 \
SPEED_STATE_DIR="$STATE_DIR" \
SPEED_SHARED_DIR="$SHARED_DIR" \
SPEED_LOCAL_DIR="$LOCAL_DIR" \
SPEED_EVENTS_DIR="$EVENTS_DIR" \
SPEED_ROSTER_DIR="$ROSTER_DIR" \
SPEED_PROJECT_ROOT="$PROJECT_ROOT" \
    python3 "$SCRIPT_DIR/lib/serve/server.py" &
SERVER_PID=$!
sleep 1

if kill -0 "$SERVER_PID" 2>/dev/null; then
    # Test health endpoint
    health=$(curl -s http://localhost:44599/api/health 2>/dev/null)
    health_status=$(echo "$health" | jq -r '.status // empty' 2>/dev/null)
    assert_eq "health endpoint returns ok" "ok" "$health_status"

    # Test features endpoint
    features=$(curl -s http://localhost:44599/api/features 2>/dev/null)
    feat_count=$(echo "$features" | jq 'length' 2>/dev/null)
    assert_eq "features endpoint returns 2" "2" "$feat_count"

    # Test roster endpoint
    roster=$(curl -s http://localhost:44599/api/roster 2>/dev/null)
    roster_type=$(echo "$roster" | jq 'type' 2>/dev/null)
    assert_eq "roster returns array" '"array"' "$roster_type"

    # Test events endpoint
    events=$(curl -s "http://localhost:44599/api/events?limit=5" 2>/dev/null)
    events_type=$(echo "$events" | jq 'type' 2>/dev/null)
    assert_eq "events returns array" '"array"' "$events_type"

    # Test claim arbitration
    claim_result=$(curl -s -X POST http://localhost:44599/api/claim \
        -H "Content-Type: application/json" \
        -d '{"feature":"new-feat","actor":"Charlie"}' 2>/dev/null)
    claim_success=$(echo "$claim_result" | jq -r '.success // false' 2>/dev/null)
    assert_eq "claim arbitration succeeds" "true" "$claim_success"

    # Second claim should fail
    sleep 0.5
    claim_result2=$(curl -s -X POST http://localhost:44599/api/claim \
        -H "Content-Type: application/json" \
        -d '{"feature":"new-feat","actor":"Dave"}' 2>/dev/null)
    claim_success2=$(echo "$claim_result2" | jq -r '.success' 2>/dev/null)
    assert_eq "duplicate claim rejected" "false" "$claim_success2"

    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
else
    echo "  SKIP: server failed to start"
    ((FAIL++)) || true
fi

# ── Summary ───────────────────────────────────────────────────
echo ""
echo "================================"
echo "Results: $PASS passed, $FAIL failed"
echo "================================"

[[ $FAIL -eq 0 ]] && exit 0 || exit 1
