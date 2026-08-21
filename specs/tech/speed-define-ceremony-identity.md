# RFC: Define Ceremony — Actor Identity

> See [product spec](../product/speed-define-ceremony.md) for product context.
> See [foundation reference](speed-define-ceremony-foundation.md) for shared types, API index, validation rules.
> Parent RFC: [speed-define-ceremony](speed-define-ceremony.md)
> Depends on: (none — this is the first RFC in the build order)

This RFC adds email-based actor identity to SPEED's multiplayer system. The existing ownership system (`lib/ownership.sh`, `lib/serve/server.py`) compares actors by display name, which collides when two developers share the same `git config user.name`. The ceremony system requires unique identity for spec authorship, contributor suggestions, and ratification votes. This RFC fixes the identity layer so the ceremony (and all existing multiplayer features) can rely on it.

## PRD & Design Traceability

**User Stories**: Supports all ceremony user stories that involve ownership (S1 author claim, S5 author-only commit, S7 contributor identity, S9 approver identity). Also retroactively fixes ownership for existing multiplayer features (`speed claim`, `speed release`).

**Success Criteria**: Two actors with identical `git config user.name` but different `git config user.email` are distinguished by the ownership system. Old events without `actor_email` continue to work via name fallback.

## Basic Example

Before this RFC, ownership matching uses display name:

```bash
# lib/ownership.sh (before)
me=$(actor_get)                          # "John Smith"
if [[ "$OWNERSHIP_OWNER" == "$me" ]]; then  # string compare on name
    return 0  # owned by me
fi
```

Two developers named "John Smith" are indistinguishable.

After this RFC, matching uses email:

```bash
# lib/ownership.sh (after)
me_email=$(actor_email_resolve)          # "john.smith@company.com"
if [[ "$OWNERSHIP_OWNER_EMAIL" == "$me_email" ]]; then
    return 0  # owned by me
fi
# Fallback for old events without actor_email:
if [[ -z "$OWNERSHIP_OWNER_EMAIL" ]]; then
    me=$(actor_get)
    [[ "$OWNERSHIP_OWNER" == "$me" ]] && return 0
fi
```

## Interface Contract

### Consumes (from prerequisite RFCs)

None. This is the first RFC in the build order.

External dependencies consumed:

- `lib/actor.sh`: `actor_resolve()`, `actor_get()`, `actor_slug()` (existing). This RFC adds `actor_email_resolve()` and `actor_email_get()` following the same patterns.
- `lib/events.sh`: `event_emit()` (existing). This RFC adds one field to its output.
- `lib/ownership.sh`: `ownership_check()` (existing). This RFC changes its matching logic.
- `lib/serve/server.py`: `_arbitrate_claim()` and `do_POST` handler (existing). This RFC changes both.
- `lib/cmd/claim.sh`: `cmd_claim()` (existing). This RFC adds one field to its event payload.
- `lib/roster.sh`: `roster_heartbeat()` (existing). This RFC adds one field to its output.

### Produces (for downstream RFCs)

All ceremony RFCs (parent + five children) consume these outputs:

```bash
# lib/actor.sh — new functions
actor_email_resolve()   # Returns email. Never fails. $SPEED_ACTOR_EMAIL -> git config -> {name}@local
actor_email_get()       # Cached variant. Resolves on first call per process.
```

```bash
# lib/ownership.sh — new global
OWNERSHIP_OWNER_EMAIL   # Set by ownership_check() alongside OWNERSHIP_OWNER. Empty when unclaimed/stale.
```

The parent RFC's `get_current_actor()` calls `actor_get()` + `actor_email_get()` to return `(name, email)`. The parent RFC's `assert_ceremony_author()` compares on `ceremony.author_email` using the email returned by `get_current_actor()`.

## Data Model

### Event payload (modified)

Events gain one new field. All existing fields are preserved. (Shown as Python dataclass for readability; actual format is JSONL written by jq in bash.)

```python
@dataclass
class EventPayload:
    timestamp: str        # ISO 8601 (existing)
    type: str             # event type (existing)
    feature: str          # feature name (existing)
    actor: str            # display name from actor_get() (existing)
    actor_email: str      # NEW: email from actor_email_resolve()
    data: dict            # event-specific payload (existing)
```

#### JSON Schema (event payload addition)

Only the new field is shown. The existing event schema is unchanged.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "EventPayload_actor_email_addition",
  "description": "New field added to the existing event JSONL payload.",
  "type": "object",
  "properties": {
    "actor_email": {
      "type": "string",
      "pattern": ".+@.+",
      "description": "Resolved email from actor_email_resolve(). May be {name}@local synthetic fallback."
    }
  }
}
```

### Roster entry (modified)

Roster entries gain one new field. (Shown as Python dataclass for readability; actual format is JSON written by jq in bash.)

```python
@dataclass
class RosterEntry:
    name: str             # display name (existing)
    email: str            # NEW: from actor_email_resolve()
    active_feature: str   # (existing)
    active_stage: str     # (existing)
    last_seen: str        # ISO 8601 (existing)
    last_command: str     # (existing)
```

#### JSON Schema (roster entry addition)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "RosterEntry_email_addition",
  "description": "New field added to the existing roster JSON.",
  "type": "object",
  "properties": {
    "email": {
      "type": "string",
      "pattern": ".+@.+",
      "description": "Resolved email from actor_email_resolve()."
    }
  }
}
```

## API Surface

No new GraphQL operations. This RFC modifies shell functions and one Python function.

### `actor_email_resolve()` (new, in `lib/actor.sh`)

Added after `actor_get()` at the end of the file (after line 43):

```bash
# Resolve the current actor's email address.
# Resolution order: $SPEED_ACTOR_EMAIL env → git config user.email → {name}@local
# Never fails. Always returns a string containing @.
actor_email_resolve() {
    if [[ -n "${SPEED_ACTOR_EMAIL:-}" ]]; then
        echo "$SPEED_ACTOR_EMAIL"
        return 0
    fi

    local email
    email=$(git config user.email 2>/dev/null || true)
    if [[ -n "$email" ]]; then
        echo "$email"
        return 0
    fi

    echo "$(actor_get)@local"
}
```

Also add a cached variant, following the `actor_get` pattern:

```bash
_ACTOR_EMAIL_CACHE=""

# Return cached actor email. Resolves on first call.
actor_email_get() {
    if [[ -z "$_ACTOR_EMAIL_CACHE" ]]; then
        _ACTOR_EMAIL_CACHE=$(actor_email_resolve)
    fi
    echo "$_ACTOR_EMAIL_CACHE"
}
```

### `event_emit()` (modified, in `lib/events.sh`)

**Signature**: Unchanged. `event_emit event_type feature data_json`
**Returns**: Writes JSONL file to `.speed/shared/events/`. No stdout. No-ops when `MP_ENABLED != true`.
**Error cases**: None new.
**Consumers affected**: None. `event_list()`, `event_replay()`, and `event_prune()` use jq to read known fields; unknown sibling fields are ignored.

Current code (lines 35-42):

```bash
    jq -nc \
        --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg type "$event_type" \
        --arg feature "$feature" \
        --arg actor "$(actor_get)" \
        --argjson data "$data_json" \
        '{timestamp: $ts, type: $type, feature: $feature, actor: $actor, data: $data}' \
        > "$tmp" 2>/dev/null
```

After this RFC (lines 35-43):

```bash
    jq -nc \
        --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg type "$event_type" \
        --arg feature "$feature" \
        --arg actor "$(actor_get)" \
        --arg actor_email "$(actor_email_get)" \
        --argjson data "$data_json" \
        '{timestamp: $ts, type: $type, feature: $feature, actor: $actor, actor_email: $actor_email, data: $data}' \
        > "$tmp" 2>/dev/null
```

Two changes: add `--arg actor_email` parameter, add `actor_email: $actor_email` to the output object.

### `ownership_check()` (modified, in `lib/ownership.sh`)

**Signature**: Unchanged. `ownership_check feature`
**Returns**: Exit code 0 (owned by me), 1 (owned by someone else), 2 (unclaimed/stale). Sets globals `OWNERSHIP_OWNER` (display name) and `OWNERSHIP_OWNER_EMAIL` (email, **new**).
**New global**: `OWNERSHIP_OWNER_EMAIL` — set when a claim is found. Empty when unclaimed or stale.
**Matching logic**: If claim event has `actor_email` and the local actor has one: compare emails. Otherwise: fall back to name comparison (pre-existing behavior).
**Error cases**: None new. Malformed event JSON is silently skipped (existing `2>/dev/null`).
**Callers affected**: `ownership_require()` and `ownership_current_owner()` delegate to this function and are unchanged.

Current code extracts `actor` from events and compares by name (lines 26-79). The full modified function:

```bash
ownership_check() {
    local feature="$1"
    OWNERSHIP_OWNER=""
    OWNERSHIP_OWNER_EMAIL=""                       # NEW: track email alongside name

    [[ "${MP_ENABLED:-}" == "true" ]] || return 0

    local events_dir
    events_dir=$(mp_events_dir)
    [[ -d "$events_dir" ]] || return 2

    local latest_claim="" latest_release="" latest_claim_actor="" latest_claim_email="" latest_claim_ts=""

    for f in "${events_dir}"/*_feature-claimed_"${feature}".jsonl "${events_dir}"/*_feature-released_"${feature}".jsonl; do
        [[ -f "$f" ]] || continue
        local etype actor actor_email ts
        etype=$(jq -r '.type // ""' "$f" 2>/dev/null)
        actor=$(jq -r '.actor // ""' "$f" 2>/dev/null)
        actor_email=$(jq -r '.actor_email // ""' "$f" 2>/dev/null)  # NEW: extract email (empty for old events)
        ts=$(jq -r '.timestamp // ""' "$f" 2>/dev/null)

        if [[ "$etype" == "feature.claimed" ]]; then
            if [[ -z "$latest_claim" ]] || [[ "$ts" > "$latest_claim_ts" ]]; then
                latest_claim="$f"
                latest_claim_actor="$actor"
                latest_claim_email="$actor_email"  # NEW
                latest_claim_ts="$ts"
            fi
        elif [[ "$etype" == "feature.released" ]]; then
            if [[ -z "$latest_release" ]] || [[ "$ts" > "$latest_release" ]]; then
                latest_release="$ts"
            fi
        fi
    done

    if [[ -z "$latest_claim" ]]; then
        return 2
    fi

    if [[ -n "$latest_release" ]] && [[ "$latest_release" > "$latest_claim_ts" ]]; then
        return 2
    fi

    # Staleness check (unchanged)
    local now_epoch claim_epoch
    now_epoch=$(date +%s)
    claim_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$latest_claim_ts" +%s 2>/dev/null || \
                  date -d "$latest_claim_ts" +%s 2>/dev/null || echo "0")
    local age=$(( now_epoch - claim_epoch ))
    if [[ $age -gt $OWNERSHIP_STALE_WINDOW ]]; then
        return 2
    fi

    OWNERSHIP_OWNER="$latest_claim_actor"
    OWNERSHIP_OWNER_EMAIL="$latest_claim_email"    # NEW

    # --- NEW: email-based comparison with name fallback ---
    local me_email
    me_email=$(actor_email_get)

    # Primary: compare on email (when both sides have it)
    if [[ -n "$OWNERSHIP_OWNER_EMAIL" ]] && [[ -n "$me_email" ]]; then
        if [[ "$OWNERSHIP_OWNER_EMAIL" == "$me_email" ]]; then
            return 0
        fi
        return 1
    fi

    # Fallback: old event has no actor_email, compare on name (pre-existing behavior)
    local me
    me=$(actor_get)
    if [[ "$OWNERSHIP_OWNER" == "$me" ]]; then
        return 0
    fi

    return 1
}
```

Changes from current (all marked with `# NEW` inline comments):
- New global `OWNERSHIP_OWNER_EMAIL=""` initialized at function top
- Extract `actor_email` from event JSON via jq inside the for loop
- Track `latest_claim_email` alongside `latest_claim_actor`
- Set `OWNERSHIP_OWNER_EMAIL` alongside `OWNERSHIP_OWNER`
- Replace the old 3-line name comparison (old lines 72-79) with email-first + name-fallback block

### `_arbitrate_claim()` (modified, in `lib/serve/server.py`)

**Signature change**: Adds `actor_email: str` parameter. `_arbitrate_claim(feature, actor, actor_email)`.
**Returns**: `{"success": bool, "owner": str | None, "message": str}` (unchanged shape).
**Matching logic**: Same email-first, name-fallback pattern as `ownership_check()`.
**Event emission**: Written claim events now include `"actor_email": actor_email` at the top level.
**Error cases**: None new. Existing error paths (lock contention, JSON parse) unchanged.
**Callers affected**: The HTTP handler must pass `actor_email` from the request body. The CLI sets this via `actor_email_get()`.

Current signature: `_arbitrate_claim(feature: str, actor: str)`. New signature adds email:

```python
def _arbitrate_claim(feature: str, actor: str, actor_email: str) -> dict:
    """Atomic claim arbitration. Returns {success, owner, message}."""
    lock_dir = STATE_DIR / "local" / "locks" / f"claim-{feature}"

    try:
        lock_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        return {"success": False, "owner": None, "message": "Claim in progress by another request"}

    try:
        # Check current ownership
        current_owner = None
        current_owner_email = None                          # NEW
        for ef in sorted(EVENTS_DIR.glob(f"*_feature-claimed_{feature}.jsonl"), reverse=True):
            try:
                ev = json.loads(ef.read_text().strip())
                current_owner = ev.get("actor")
                current_owner_email = ev.get("actor_email")  # NEW (None for old events)
                break
            except (json.JSONDecodeError, OSError):
                continue

        # Check if released (unchanged)
        if current_owner:
            for ef in sorted(EVENTS_DIR.glob(f"*_feature-released_{feature}.jsonl"), reverse=True):
                try:
                    ev = json.loads(ef.read_text().strip())
                    current_owner = None
                    current_owner_email = None               # NEW
                    break
                except (json.JSONDecodeError, OSError):
                    continue

        # --- NEW: email-based comparison with name fallback ---
        if current_owner:
            is_same_actor = False
            if current_owner_email and actor_email:
                is_same_actor = (current_owner_email == actor_email)
            else:
                # Fallback for old events without actor_email
                is_same_actor = (current_owner == actor)

            if not is_same_actor:
                return {
                    "success": False,
                    "owner": current_owner,
                    "message": f"Feature claimed by {current_owner}",
                }

        # Write claim event
        ts = datetime.now(timezone.utc)
        ts_file = ts.strftime("%Y%m%dT%H%M%SZ")
        slug = actor.lower().replace(" ", "-")
        filename = f"{ts_file}_{slug}_feature-claimed_{feature}.jsonl"
        event = {
            "timestamp": ts.isoformat(),
            "type": "feature.claimed",
            "feature": feature,
            "actor": actor,
            "actor_email": actor_email,              # NEW
            "data": {"actor": actor},
        }
        event_path = EVENTS_DIR / filename
        tmp = event_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(event))
        tmp.rename(event_path)

        return {"success": True, "owner": actor, "message": "Claimed"}
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass
```

### `do_POST` handler (modified, in `lib/serve/server.py`)

**Signature**: Unchanged. `do_POST(self)`.
**Change**: Reads `actor_email` from the request body and passes it to `_arbitrate_claim()`. Backward-compatible: if the request omits `actor_email` (old CLI client), passes empty string, which triggers the name-fallback path in `_arbitrate_claim`.
**Error cases**: None new. The existing validation (`feature and actor required`) is unchanged. `actor_email` is optional in the request body for backward compatibility.

Current code (server.py lines 225-235):

```python
        if path == "/api/claim":
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length > 0 else {}
            feature = body.get("feature", "")
            actor = body.get("actor", "")
            if not feature or not actor:
                self._json_response({"error": "feature and actor required"}, 400)
                return
            result = _arbitrate_claim(feature, actor)
            status = 200 if result["success"] else 409
            self._json_response(result, status)
```

After this RFC:

```python
        if path == "/api/claim":
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length > 0 else {}
            feature = body.get("feature", "")
            actor = body.get("actor", "")
            actor_email = body.get("actor_email", "")  # NEW: optional for backward compat
            if not feature or not actor:
                self._json_response({"error": "feature and actor required"}, 400)
                return
            result = _arbitrate_claim(feature, actor, actor_email)
            status = 200 if result["success"] else 409
            self._json_response(result, status)
```

Two changes: read `actor_email` from body (empty string default for old clients), pass to `_arbitrate_claim`.

### `cmd_claim()` (modified, in `lib/cmd/claim.sh`)

**Signature**: Unchanged. `cmd_claim feature`
**Change**: Event data payload includes `actor_email` alongside `actor`.
**Error cases**: None new.

Current line 38:

```bash
    event_emit "feature.claimed" "$feature" "{\"actor\":$(jq -n --arg a "$(actor_get)" '$a')}"
```

After this RFC:

```bash
    event_emit "feature.claimed" "$feature" \
        "{\"actor\":$(jq -n --arg a "$(actor_get)" '$a'),\"actor_email\":$(jq -n --arg e "$(actor_email_get)" '$e')}"
```

The `event_emit` function already adds `actor` and `actor_email` at the top level. The data payload here is redundant for `actor` (existing behavior, kept for backward compat) and now also includes `actor_email`.

### `roster_heartbeat()` (modified, in `lib/roster.sh`)

**Signature**: Unchanged. `roster_heartbeat` (no args).
**Change**: Roster JSON gains `email` field from `actor_email_get()`.
**Returns**: Writes JSON file to `.speed/shared/roster/{slug}.json`. No stdout.
**Error cases**: None new.
**Consumers affected**: `roster_list()` and `roster_format_table()` are unchanged. `roster_list()` reads fields with jq; unknown fields ignored. `roster_format_table()` formats a fixed column set (name, feature, stage, last_seen, command); `email` is not displayed.

Current jq call (lines 36-43):

```bash
    jq -nc \
        --arg name "$(actor_get)" \
        --arg feature "${active_feature:-}" \
        --arg stage "${active_stage:-}" \
        --arg last_seen "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg last_command "${_SPEED_CURRENT_COMMAND:-unknown}" \
        '{name: $name, active_feature: $feature, active_stage: $stage, last_seen: $last_seen, last_command: $last_command}' \
        > "$tmp" 2>/dev/null && mv "$tmp" "$roster_file"
```

After this RFC:

```bash
    jq -nc \
        --arg name "$(actor_get)" \
        --arg email "$(actor_email_get)" \
        --arg feature "${active_feature:-}" \
        --arg stage "${active_stage:-}" \
        --arg last_seen "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg last_command "${_SPEED_CURRENT_COMMAND:-unknown}" \
        '{name: $name, email: $email, active_feature: $feature, active_stage: $stage, last_seen: $last_seen, last_command: $last_command}' \
        > "$tmp" 2>/dev/null && mv "$tmp" "$roster_file"
```

Two changes: add `--arg email` parameter, add `email: $email` to the output object.

## Validation Rules

| Rule | Where enforced | Input | Constraint | Error behavior |
|------|---------------|-------|------------|----------------|
| `actor_email_resolve()` always returns a value | `lib/actor.sh` | None (reads env/git/whoami) | Return value is non-empty and contains `@` | Cannot fail. The three-level fallback guarantees a return. The synthetic fallback `{name}@local` always contains `@` because `actor_get()` always returns a non-empty name. |
| `$SPEED_ACTOR_EMAIL` passthrough | `actor_email_resolve()` | Env var | If set, used as-is. No format validation in shell. | If a user sets `SPEED_ACTOR_EMAIL=garbage`, it passes through. Downstream consumers (ceremony.json JSON Schema) validate the stored value. Shell does not gate on format. |
| Event `actor_email` field | `event_emit()` in `lib/events.sh` | Output of `actor_email_get()` | Always present in new events. String type. | Cannot be absent in new events (jq template includes it unconditionally). Old events lack the field; consumers must handle `null`/absent. |
| Ownership email comparison | `ownership_check()` in `lib/ownership.sh` | `actor_email` from event JSON + `actor_email_get()` | When both sides have email, compare on email. When the event lacks `actor_email` (old event), fall back to name. | No error. Silent fallback. The name comparison path is the pre-existing behavior. |
| Claim arbitration email comparison | `_arbitrate_claim()` in `lib/serve/server.py` | `actor_email` from event JSON + `actor_email` from request | Same logic as ownership: email-first, name-fallback. | Returns `{"success": false, "owner": ..., "message": ...}` on mismatch. No exception. |
| Roster `email` field | `roster_heartbeat()` in `lib/roster.sh` | Output of `actor_email_get()` | Always present in new roster entries. Optional in reads (old entries lack it). | `roster_list()` does not read or filter on `email`. The field is informational for team awareness. |

## Testing

### Acceptance Criteria

- Given two actors with `git config user.name = "John Smith"` but different emails, when actor A claims a feature and actor B checks ownership, then B is identified as a non-owner
- Given two actors with `git config user.name = "John Smith"` but different emails, when actor A claims via the HTTP server and actor B attempts to claim, then B's claim is rejected with "Feature claimed by John Smith"
- Given an old claim event without `actor_email`, when ownership is checked by a new actor (who has email), then the system falls back to name comparison without error
- Given a mix of old events (no email) and new events (with email), when ownership is determined, the latest event's format dictates the comparison method
- Given `$SPEED_ACTOR_EMAIL` is set, when an event is emitted, the event JSONL contains the env var value in the `actor_email` field
- Given `$SPEED_ACTOR_EMAIL` is set and `git config user.email` is also set, when `actor_email_resolve()` runs, the env var takes precedence
- Given no `$SPEED_ACTOR_EMAIL` and no `git config user.email`, when `actor_email_resolve()` runs, it returns `{name}@local` where `{name}` is the resolved actor name
- Given `git config user.email` returns an empty string (configured but blank), when `actor_email_resolve()` runs, it falls through to the `{name}@local` fallback
- Given a roster heartbeat runs after this RFC, the roster JSON file contains an `email` field alongside the existing `name` field
- Given an old roster entry without `email`, when `roster_list()` reads it, no error occurs and the entry is included in results

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| Two actors with same display name collide on ownership (the bug this RFC fixes) | High | Integration test: emit two claim events with same `actor` but different `actor_email`, verify `ownership_check` distinguishes them. Repeat for `_arbitrate_claim` via HTTP. |
| Old events without `actor_email` break ownership matching | Medium | Unit test: construct event JSON without `actor_email` field, run `ownership_check`, verify it falls back to name comparison and returns correct result |
| `actor_email_resolve` fails in CI (no git, no env var) | Medium | Unit test: unset `SPEED_ACTOR_EMAIL`, mock `git config user.email` to return empty, verify `{whoami}@local` is returned |
| `actor_email_resolve` returns empty string | Medium | Unit test: verify all three fallback paths return non-empty. Verify synthetic fallback contains `@`. Edge case: `actor_get()` returns empty (shouldn't happen since `whoami` is the final fallback, but test defensively). |
| Event payload schema breaks jq consumers that don't expect `actor_email` | Low | Integration test: emit event with `actor_email`, pipe through existing `event_list` and `event_replay` functions, verify they work unchanged (jq ignores unknown fields by default) |
| Rollback scenario: events with `actor_email` persist after code is rolled back | Low | Unit test: verify `ownership_check` (old code path, name-only) works correctly when event JSON contains an extra `actor_email` field. jq's `.actor // ""` ignores unknown siblings. |
| Roster reader breaks on new `email` field | Low | Unit test: verify `roster_list` and `roster_format_table` work with roster entries that include `email` field (jq ignores unknown fields) |

### Test Plan

**Unit tests — `lib/actor.sh`**

These test `actor_email_resolve()` and `actor_email_get()` in isolation.

- `test_email_resolve_env_precedence`: Set `SPEED_ACTOR_EMAIL=test@env.com` and `git config user.email` to `other@git.com`. Verify `actor_email_resolve` returns `test@env.com`.
- `test_email_resolve_git_fallback`: Unset `SPEED_ACTOR_EMAIL`. Set `git config user.email` to `dev@company.com`. Verify returns `dev@company.com`.
- `test_email_resolve_synthetic_fallback`: Unset `SPEED_ACTOR_EMAIL`. Ensure `git config user.email` is unset or empty. Verify returns `{actor_get}@local` (e.g., `sanjay@local`).
- `test_email_resolve_empty_git_email`: Set `git config user.email` to `""` (empty string). Verify falls through to synthetic fallback, not returning empty.
- `test_email_resolve_always_contains_at`: Run `actor_email_resolve` under all three fallback scenarios. Verify every return value contains `@`.
- `test_email_resolve_never_empty`: Run under all scenarios. Verify return value has length > 0.
- `test_email_get_caches`: Call `actor_email_get` twice. Verify the underlying `actor_email_resolve` is only called once (check `$_ACTOR_EMAIL_CACHE` is set after first call).
- `test_email_get_consistent`: Call `actor_email_get` twice in the same process. Verify same value both times.

**Unit tests — `lib/events.sh`**

- `test_event_payload_has_actor_email`: Call `event_emit "test.event" "test-feature" '{}'`. Read the written JSONL file. Verify it has `actor_email` field. Verify `actor_email` value matches `actor_email_get`.
- `test_event_payload_preserves_existing_fields`: Emit an event. Verify `timestamp`, `type`, `feature`, `actor`, `data` fields are all present and unchanged in format.
- `test_event_payload_actor_email_from_env`: Set `SPEED_ACTOR_EMAIL=ci@runner.local`. Emit event. Verify `actor_email` is `ci@runner.local`.

**Unit tests — `lib/ownership.sh`**

- `test_ownership_email_match`: Write a claim event with `actor_email: "alice@co.com"`. Set local actor email to `alice@co.com`. Run `ownership_check`. Verify returns 0 (owned by me).
- `test_ownership_email_mismatch`: Write a claim event with `actor_email: "alice@co.com"`. Set local actor email to `bob@co.com`. Run `ownership_check`. Verify returns 1 (owned by someone else). Verify `OWNERSHIP_OWNER` is set to the claimant's display name.
- `test_ownership_name_collision_resolved`: Write a claim event with `actor: "John Smith"`, `actor_email: "john.s@teamA.com"`. Set local actor to name `"John Smith"`, email `"john.s@teamB.com"`. Run `ownership_check`. Verify returns 1 (different person despite same name).
- `test_ownership_same_email_different_name`: Write a claim event with `actor: "Johnny"`, `actor_email: "john@co.com"`. Set local actor to name `"John Smith"`, email `"john@co.com"`. Run `ownership_check`. Verify returns 0 (same person, display name changed).
- `test_ownership_fallback_old_event`: Write a claim event WITHOUT `actor_email` field (simulating pre-RFC event). Set local actor name to match event's `actor`. Run `ownership_check`. Verify returns 0 (falls back to name matching).
- `test_ownership_fallback_old_event_mismatch`: Write a claim event WITHOUT `actor_email`. Set local actor name to something different. Run `ownership_check`. Verify returns 1.
- `test_ownership_owner_email_exposed`: Write a claim event with `actor_email`. Run `ownership_check`. Verify `$OWNERSHIP_OWNER_EMAIL` global is set to the event's email value.
- `test_ownership_release_clears_email`: Write claim then release events. Run `ownership_check`. Verify returns 2 (unclaimed) and `$OWNERSHIP_OWNER_EMAIL` is empty.
- `test_ownership_stale_claim_with_email`: Write claim event with timestamp older than `OWNERSHIP_STALE_WINDOW`. Run `ownership_check`. Verify returns 2 regardless of email match.

**Unit tests — `lib/serve/server.py`**

- `test_arbitrate_new_claim_with_email`: Call `_arbitrate_claim("feat", "Alice", "alice@co.com")` with no prior claims. Verify `success=True`. Read the written event file. Verify `actor_email` field is `"alice@co.com"`.
- `test_arbitrate_same_actor_reclaim`: Claim as Alice with email A. Claim again as Alice with email A. Verify `success=True` (re-claiming own feature).
- `test_arbitrate_different_email_same_name`: Claim as `("John Smith", "john@A.com")`. Attempt claim as `("John Smith", "john@B.com")`. Verify `success=False`, `owner="John Smith"`.
- `test_arbitrate_fallback_old_claim`: Write an old claim event (no `actor_email`). Attempt claim as `("John Smith", "john@B.com")`. Since old event has no email, fallback to name: names match, so `success=True`.
- `test_arbitrate_fallback_old_claim_different_name`: Write an old claim event for `actor: "Alice"`. Attempt claim as `("Bob", "bob@co.com")`. Names don't match, `success=False`.
- `test_arbitrate_event_includes_email`: After a successful claim, read the event file. Verify the JSON has `"actor_email"` at the top level.
- `test_handler_reads_actor_email`: POST to `/api/claim` with `{"feature": "f", "actor": "A", "actor_email": "a@b.com"}`. Verify `_arbitrate_claim` receives `actor_email="a@b.com"`.
- `test_handler_missing_actor_email`: POST to `/api/claim` without `actor_email` field (old CLI client). Verify `_arbitrate_claim` receives empty string and falls back to name matching without error.

**Unit tests — `lib/cmd/claim.sh`**

- `test_claim_event_has_email`: Run `cmd_claim "test-feature"`. Read the emitted event. Verify top-level `actor_email` field is present and matches `actor_email_get` (this is the field `ownership_check` reads). Also verify `data.actor_email` is present (redundant with top-level, kept for backward compat).

**Unit tests — `lib/roster.sh`**

- `test_roster_heartbeat_includes_email`: Run `roster_heartbeat`. Read the roster JSON file. Verify `email` field is present and matches `actor_email_get`.
- `test_roster_list_with_email`: Write a roster entry with `email` field. Run `roster_list`. Verify output includes the entry without error.
- `test_roster_list_without_email`: Write a roster entry WITHOUT `email` field (old format). Run `roster_list`. Verify output includes the entry without error.
- `test_roster_format_table_unchanged`: Run `roster_format_table` with entries that have `email`. Verify the table output format is unchanged (email is not displayed in the table — it's for internal use only).

**Integration tests**

- `test_full_claim_ownership_cycle_email`: Actor A claims a feature (with email). Actor B (different email, same name) attempts to claim. Verify B is rejected. Actor A releases. Actor B claims successfully. Verify the full cycle through `ownership_check`, `cmd_claim`, and `ownership_require`.
- `test_http_claim_email`: POST a claim to the HTTP server with `actor` and `actor_email`. Verify the response and the written event file.
- `test_mixed_event_timeline`: Emit old-format events (no email), then new-format events (with email). Run `event_replay` and `ownership_check` across the timeline. Verify correct behavior at every point.
- `test_event_replay_ignores_email`: Run `event_replay` (which reconstructs task state from events). Verify it works identically with events that have `actor_email` (the field is ignored by the replay logic, which only cares about `type` and `data`).
- `test_backward_compat_event_list`: Pipe events through `event_list` with filtering. Verify `actor_email` doesn't interfere with type or feature filtering (filename-based, not payload-based).

### Edge Cases

- `git config user.email` returns empty string (configured but blank): treated as absent, falls through to `{name}@local`.
- `$SPEED_ACTOR_EMAIL` set to a string without `@` (e.g., `"garbage"`): passes through. No shell validation. Downstream JSON Schema on `ceremony.json` would catch it if stored, but events accept it.
- Actor changes `git config user.email` between sessions: new events carry the new email. Old events retain the old email. Ownership of features claimed under the old email is retained correctly (the claim event's `actor_email` matches the email at claim time).
- Two developers sharing a CI runner with the same OS user and no git config: both get `{whoami}@local` as their fallback email. They would collide. This is acceptable because CI runners don't run interactive multiplayer sessions.
- `actor_get()` returns a name with special characters (e.g., `"José García"`): the synthetic email becomes `José García@local`. This is not RFC 5322 compliant but functions correctly as a comparison key (string equality).
- Roster entry written by old code (no `email`), then read by new code: `roster_list` uses jq to read fields; absent fields produce `null` in jq, which is filtered or ignored. No error.
- Event file with `actor_email: null` (explicitly null, not absent): treated the same as absent. The ownership fallback checks for empty string (`[[ -z "$actor_email" ]]`), and jq's `// ""` converts null to empty.
- `event_prune` archives old events: archived events retain whatever fields they had. The archive format is unchanged (concatenated JSONL). No enrichment during prune.
- `$SPEED_ACTOR` set but `$SPEED_ACTOR_EMAIL` not set: name comes from the env var, email falls through to `git config user.email` or `{name}@local`. The two resolution chains are independent. If git email is also unset, the synthetic fallback uses the env var name (e.g., `CustomName@local`). This is deterministic and probably desired.
- Old CLI client calls new server without `actor_email` in request body: `do_POST` handler defaults to empty string, `_arbitrate_claim` falls back to name comparison. Same collision risk as before this RFC, but only for the duration of the old client being in use.

### Out of Scope

- Email validation (RFC 5322 compliance). The `@` check is sufficient for distinguishing actors.
- Email notification or display in the dashboard. Email is an internal matching key, not a user-facing feature.
- Migrating existing events to add `actor_email` retroactively. Events are append-only; old events age out via `event_prune`.
- Displaying email in `roster_format_table`. The table already has 5 columns; adding email would break alignment on 80-char terminals. Email is available in the roster JSON for programmatic consumers.
- Updating `_read_features()` in `lib/serve/server.py`. This read-only function (populates the `/api/features` dashboard endpoint) determines feature ownership by name from claim events. It has the same name-collision issue this RFC fixes in `_arbitrate_claim` and `ownership_check`. Not updated here because it is a display function (shows who owns what in the feature list), not an enforcement function (it doesn't grant or deny access). The displayed owner name would still be correct (both "John Smith" developers see "John Smith" as owner); only the identity behind the name is ambiguous. Fixing it requires adding `owner_email` to the API response, which is a dashboard change outside this RFC's scope.
- Pre-existing bug in `_read_features` release check: the release timestamp comparison (`ev.get("timestamp", "") > ""`) is always true for any non-empty string, so any release event clears ownership regardless of whether it's newer than the claim. This bug predates this RFC and is not introduced or worsened by it.

## Security & Controls

**Data sensitivity**: `actor_email` contains the developer's git email. This is the same information in every git commit (`git log --format='%ae'`). No new PII surface.

**Spoofing**: `actor_email_resolve()` reads from server-side env/git config, not from user input. Cannot be spoofed through API calls. The HTTP server receives `actor_email` from the request body (set by the CLI, which calls `actor_email_get()`), not from an unauthenticated external source.

**Audit trail**: Events are append-only JSONL. The `actor_email` field in each event creates a verifiable identity trail that is harder to forge than display names (email requires git config or env var access on the authoring machine).

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Email as unique key | `actor_email` for matching, `actor` name for display | Display name only (status quo); actor slug; composite `name:email`; prompted unique ID at `mp-init` | Display name collides ("John Smith" x 2). Slug has the same collision. Composite is awkward in comparisons. Prompted ID breaks the git config convention. Email is available, unique per team member, and requires no additional setup. |
| Fallback to name for old events | Graceful degradation | Reject events without `actor_email`; require migration | Rejecting breaks backward compatibility. Migration rewrites append-only events (breaks git history). Fallback is safe: the name collision risk existed before this RFC and isn't worsened by falling back to it for old events. |
| Synthetic `{name}@local` for no-git environments | Deterministic fallback | Error and refuse to proceed; random UUID | Erroring blocks CI and containers. UUID changes per session (breaks ownership). `{name}@local` is stable per machine (same whoami = same fallback email). |
| No shell-level email format validation | Passthrough | Validate `@` in `actor_email_resolve`; reject `$SPEED_ACTOR_EMAIL` without `@` | Shell string validation is fragile and easy to get wrong (locale issues, special chars). The resolution chain's three levels all naturally produce `@`-containing strings. The one exception (`$SPEED_ACTOR_EMAIL` set to garbage) is a user configuration error that downstream JSON Schema catches when the value is stored. |
| Cached `actor_email_get()` alongside uncached `actor_email_resolve()` | Cached + uncached variants | Cache only; uncached only | Follows the existing `actor_get()` / `actor_resolve()` pattern. `actor_email_get()` avoids redundant subprocess calls within a single speed command invocation. `actor_email_resolve()` is available for cases that need a fresh value. |

## Drawbacks

- **Email can change.** A developer who changes their `git config user.email` will appear as a different actor for ownership purposes. Features claimed under the old email remain owned by that email. The developer would need to re-claim or have the old claim go stale. This matches git's own model (commits have the email at commit time, not current email).

- **Synthetic fallback is per-machine, not per-person.** Two developers sharing a CI runner with the same OS user get the same `{whoami}@local` fallback. In practice, CI runners don't run interactive multiplayer sessions, so this is unlikely to matter.

- **Backward compatibility window.** During the transition period (before old events are pruned), some ownership checks fall back to name matching. The collision risk from the old system persists for up to 30 days (the default prune window) after deployment.

- **Additional subprocess call.** `actor_email_resolve()` calls `git config user.email` (one subprocess). Combined with the existing `actor_resolve()` call for names, each speed invocation now spawns two git subprocesses instead of one. Both are cached, so the overhead is ~50ms on first call, zero after. Negligible for a CLI tool.

## Migration Strategy

**Approach: gradual, no migration script.**

1. **New events** include `actor_email` alongside `actor`. The schema is additive (new field, all existing fields preserved).
2. **Old events** without `actor_email` still work. `ownership.sh` falls back to name matching when `actor_email` is absent in the event JSON: if `jq -r '.actor_email // ""'` returns empty, compare on `.actor` instead. Same fallback in `server.py`.
3. **Roster entries** gain an `email` field on the next heartbeat. Old entries without it are valid; the field is optional in reads.
4. **No rewriting of existing events.** Events are append-only JSONL with unique filenames. Rewriting would break git history and the conflict-free merge guarantee.
5. **Rollback:** Remove the `actor_email` additions from `event_emit` and `ownership_check`. Old code ignores unknown fields, so events written with `actor_email` are harmless to a rolled-back system. Ownership falls back to name matching automatically when the field is absent.

**Timeline:** After this RFC lands, all new events carry `actor_email`. Old events age out naturally via `event_prune` (default 30 days). Within one prune cycle, the system is fully migrated without any explicit migration step.

## File Impact

**New files:** None.

**Modified files:**

| File | Change | Lines Changed |
|------|--------|--------------|
| `lib/actor.sh` | Add `actor_email_resolve()` and `actor_email_get()` functions after line 43. | ~23 lines added |
| `lib/events.sh` | Add `--arg actor_email` and `actor_email: $actor_email` to `event_emit()` jq call (lines 35-42). | ~2 lines changed |
| `lib/ownership.sh` | Add `OWNERSHIP_OWNER_EMAIL` global, extract `actor_email` from events, email-first comparison with name fallback. Full function rewrite of `ownership_check()`. | ~15 lines changed |
| `lib/serve/server.py` | Add `actor_email` parameter to `_arbitrate_claim()`, extract from events, email-first comparison, include in emitted events. Update `do_POST` handler to read `actor_email` from request body. | ~15 lines changed |
| `lib/cmd/claim.sh` | Add `actor_email` to claim event data payload (line 38). | ~1 line changed |
| `lib/roster.sh` | Add `--arg email` and `email: $email` to `roster_heartbeat()` jq call (lines 36-43). | ~2 lines changed |

**Total: ~58 lines changed across 6 files. No new files.**

## Dependencies

| Dependency | What It Provides | Where It Lives |
|------------|-----------------|----------------|
| `lib/actor.sh` | `actor_resolve()`, `actor_get()`, `actor_slug()` (existing). This RFC adds `actor_email_resolve()` and `actor_email_get()`. | `lib/actor.sh` |
| `lib/events.sh` | `event_emit()` (existing). This RFC adds `actor_email` to the payload. | `lib/events.sh` |
| `lib/ownership.sh` | `ownership_check()`, `ownership_require()`, `ownership_current_owner()` (existing). This RFC changes the matching key in `ownership_check()`. `ownership_require()` and `ownership_current_owner()` are unchanged (they delegate to `ownership_check()`). | `lib/ownership.sh` |
| `lib/serve/server.py` | `_arbitrate_claim()` (existing). This RFC adds `actor_email` parameter and changes the matching key. | `lib/serve/server.py` |
| Git config | `user.email` for email resolution. Optional (fallback exists). | Local git config |
| `jq` | JSON processing in shell. Already a dependency of events.sh, ownership.sh, roster.sh. | System binary |

## Unresolved Questions

| Question | Blocks | Proposed Resolution |
|----------|--------|---------------------|
| Should `actor_email_resolve()` validate that the email contains `@`? | Edge case handling | No. The resolution chain guarantees it: git emails have `@`, the synthetic fallback has `@`. Only `$SPEED_ACTOR_EMAIL` could violate this, and validating env vars in shell is fragile. The JSON Schema on `ceremony.json` validates the stored value. |
| Should old events be enriched with `actor_email` during `event_prune`? | Migration completeness | No. Pruning archives and deletes old events. Adding fields during prune adds complexity for a problem that solves itself (old events age out). |
| Should the HTTP server validate `actor_email` from the request body? | Input validation | Yes, minimally. Check non-empty and contains `@`. But this is the CLI talking to a local server, not an external API. The risk of malformed input is low. Defer until remote server scenarios emerge. |
