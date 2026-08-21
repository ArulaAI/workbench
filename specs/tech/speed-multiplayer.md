# RFC: Multi-Player Mode

> See [product spec](../product/speed-multiplayer.md) for product context.
> Design context: `working-docs/design-multiplayer-mode.md`
> Depends on: [Continuous Learning](speed-feedback-loop.md)

## Basic Example

Two engineers working the same repo, different features, zero coordination friction:

```bash
# One-time setup (restructures .speed/ into shared/local zones)
speed mp-init

# Alice's session
speed claim auth-flow
speed spec propose specs/tech/auth.md
# ... team reviews and ratifies ...
speed plan specs/tech/auth.md
speed run
speed review
speed learn
speed release auth-flow
git push

# Bob's session (concurrent)
speed claim dashboard
speed plan specs/tech/dashboard.md
speed run
speed learn
speed release dashboard
git push

# Merge: zero conflicts (events are unique files)
git merge

# Cross-feature validation
speed validate --all-active
speed coherence --cross-feature
speed learn --merge
```

## Data Model

### State zones

```
.speed/
├── shared/              ← committed to git
│   ├── events/          ← append-only JSONL (source of truth)
│   ├── features/{name}/
│   │   ├── tasks/*.json ← task DAG
│   │   ├── contract.json
│   │   └── spec_path
│   ├── knowledge/       ← merged conventions, learnings, observations
│   ├── proposals/       ← pending knowledge contributions
│   └── roster/{slug}.json
├── local/               ← gitignored
│   ├── features/{name}/
│   │   ├── logs/        ← agent output
│   │   └── state.json   ← runtime state (idle/running)
│   ├── locks/           ← feature-scoped + main branch
│   ├── worktrees/       ← git worktrees
│   ├── sync.pid         ← daemon PID
│   └── serve.pid        ← server PID
└── context/             ← Layer 1 artifacts
```

### Event schema

One file per event. Filename: `{ISO8601}_{actor-slug}_{event-type}_{feature}.jsonl`

```json
{
  "timestamp": "2026-03-22T14:30:22Z",
  "type": "task.completed",
  "feature": "auth",
  "actor": "Alice Chen",
  "data": {"id": "3"}
}
```

### Event types (18)

| Category | Events |
|---|---|
| Feature lifecycle | `feature.claimed`, `feature.released`, `feature.planned` |
| Task state machine | `task.created`, `task.started`, `task.completed`, `task.failed`, `task.blocked`, `task.reset` |
| Pipeline stages | `review.completed`, `coherence.completed`, `run.started`, `run.completed`, `integrate.completed`, `learn.extracted` |
| Defect pipeline | `defect.filed`, `defect.transitioned`, `defect.triaged`, `defect.escalated` |
| Ceremonies | `spec.proposed`, `spec.reviewed`, `spec.ratified`, `outcome.review_requested`, `outcome.judged` |
| Cross-feature | `validate.cross_feature`, `coherence.cross_feature` |

### Actor attribution fields

| Object | Fields added (MP only) |
|---|---|
| Task JSON | `claimed_by`, `started_by`, `reviewed_by` |
| Defect state | `created_by`, `modified_by` |
| Lock directory | `actor` file alongside `pid` |

### Roster entry

```json
{
  "name": "Alice Chen",
  "active_feature": "auth",
  "active_stage": "running",
  "last_seen": "2026-03-22T14:30:22Z",
  "last_command": "run"
}
```

### Knowledge proposal

```json
{
  "timestamp": "2026-03-22T15:00:00Z",
  "actor": "Alice Chen",
  "feature": "auth",
  "observations": [...],
  "conventions": [...],
  "status": "pending"
}
```

### Confidence tiers

| Tier | Condition | Auto-modifiable |
|---|---|---|
| low | 1 observation, 1 actor | Yes |
| medium | 2+ observations or 2+ actors | Yes |
| high | 3+ features | Yes (resistant) |
| locked | Human-curated | No |

## Implementation

### New files

| File | Lines | Purpose |
|---|---|---|
| `lib/actor.sh` | ~45 | Identity resolution + caching |
| `lib/multiplayer.sh` | ~25 | MP detection + path helpers |
| `lib/events.sh` | ~245 | Event emit/list/replay/prune |
| `lib/ownership.sh` | ~110 | Claim check/require from events |
| `lib/roster.sh` | ~110 | Heartbeat/list/format |
| `lib/cmd/mp_init.sh` | ~115 | Zone split migration |
| `lib/cmd/claim.sh` | ~40 | Claim command |
| `lib/cmd/release.sh` | ~35 | Release command |
| `lib/cmd/rebuild.sh` | ~90 | State reconstruction |
| `lib/cmd/learn_mp.sh` | ~195 | Merge/curate/pending |
| `lib/cmd/ceremony.sh` | ~360 | Spec + outcome review ceremonies |
| `lib/cmd/cross_feature.sh` | ~350 | Cross-feature validate + coherence |
| `lib/cmd/sync.sh` | ~145 | Background sync daemon |
| `lib/cmd/serve.sh` | ~125 | HTTP server launcher |
| `lib/learn/proposals.py` | ~65 | Proposal writer |
| `lib/learn/merge.py` | ~195 | Proposal merger + confidence scoring |
| `lib/serve/server.py` | ~260 | HTTP server (roster, events, features, claim arbitration) |

### Modified files

| File | Change |
|---|---|
| `speed` | Source new libs, dispatch new commands, set `MP_ENABLED`, roster heartbeat |
| `lib/config.sh` | Add `LOCAL_DIR`, `SHARED_DIR`, `EVENTS_DIR`, etc. |
| `lib/features.sh` | Route `feature_activate()` paths, ownership check in `_require_feature()`, MP-aware `feature_resolve/list/set_active/get_active` |
| `lib/lock.sh` | Route `MAIN_BRANCH_LOCK` through `LOCAL_DIR`, write actor to lock files |
| `lib/tasks.sh` | Event emission on all 10 mutation functions, actor fields (`claimed_by`, `started_by`, `reviewed_by`) |
| `lib/defects.sh` | Route `DEFECTS_DIR` through `SHARED_DIR`, actor fields, 4 event emissions |
| `lib/shared.sh` | Guardian learnings path → `SPEED_MEMORY_DIR` |
| `lib/learn_bridge.sh` | Proposal write path in `learn_extract()`, MP-aware `learn_conventions()` and `learn_seed_knowledge()` |
| `lib/context_bridge.sh` | `SPEED_MEMORY_DIR` env var on all 5 assembly functions |
| `lib/learn/conventions.py` | Confidence-weighted sort + prefix in `format_conventions_for_agent()` |
| `lib/cmd/run.sh` | `run.started` and `run.completed` events |
| `lib/cmd/integrate.sh` | `integrate.completed` event |
| `lib/cmd/plan.sh` | `feature.planned` event, ratification gate |
| `lib/cmd/learn.sh` | `--merge`, `--curate`, `--pending`, `--prune` flags |
| `lib/cmd/status.sh` | `--team` flag, MP-aware feature root |
| `lib/cmd/coherence.sh` | `--cross-feature` flag, `coherence.completed` event |
| `lib/cmd/project.sh` | `--all-active` flag on validate |

### Backward compatibility

Every path change and event emission is gated on `MP_ENABLED`, which is only set when `.speed/shared/` exists. The flag is evaluated once at bootstrap:

```bash
MP_ENABLED=""
if mp_is_enabled; then
    MP_ENABLED=true
fi
```

Single-player projects that never run `speed mp-init` see zero behavior change. All path resolutions fall through to their original values. Event emission guards are zero-cost string comparisons.

### Conflict-free merge guarantee

Two properties:

1. **Unique filenames.** Event filenames include millisecond timestamps, actor slug, and feature name. Collision requires the same actor emitting the same event type for the same feature at the same millisecond.
2. **Append-only.** Events are never modified or deleted. Git sees only file additions.

Task JSON files live in feature-scoped directories (`shared/features/{name}/tasks/`). Two actors working different features write to different directories. The claim system prevents two actors from working the same feature.

### Claim arbitration

Git-based claims (the default) have a race window: two actors push claim events for the same feature simultaneously. Both events merge cleanly, but both actors think they own the feature. The window is seconds.

The HTTP server (`speed serve`) closes this window with `mkdir`-based atomicity. The `/api/claim` endpoint serializes concurrent requests. One `mkdir` succeeds, the other gets `FileExistsError`.

For teams of 1-3 where the race window is irrelevant, the server is unnecessary.

### Knowledge pipeline changes

In single-player mode, `learn_extract()` calls `write_observations()` to append directly to `memory/observations/{feature}.jsonl`. In MP mode, the same function detects `_SPEED_MP_ENABLED` and calls `proposals.write_proposal()` instead. Observations are wrapped in a proposal JSON with actor attribution.

`format_conventions_for_agent()` sorts conventions by confidence tier (locked > high > medium > low). Under the 2,000-token convention budget, low-confidence entries are truncated first. Locked and high entries receive a `[LOCKED]` or `[HIGH]` prefix so agents treat them as authoritative.

### HTTP server

Stdlib `http.server`, no external dependencies. Five endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/roster` | All roster entries |
| GET | `/api/events?feature=X&type=Y&limit=N` | Filtered events |
| GET | `/api/features` | Active features with task counts and owners |
| POST | `/api/claim` | Atomic claim arbitration |
| GET | `/api/health` | Server health check |

Stateless. Reads the same files the CLI reads. One write operation (claim).

## Acceptance Criteria

- AC1: `speed mp-init` restructures `.speed/` into shared/local zones. Existing features and memory migrate.
- AC2: `speed claim X` prevents another actor from running mutation commands on feature X.
- AC3: Two actors pushing events for different features produce zero git merge conflicts.
- AC4: `speed rebuild-state --apply` reconstructs task files from the event log.
- AC5: `speed learn` in MP mode writes proposals to `shared/proposals/`, not directly to knowledge.
- AC6: `speed learn --merge` auto-merges non-conflicting proposals and flags conflicts.
- AC7: `speed validate --all-active` detects file ownership overlaps across features.
- AC8: `speed spec propose/review/ratify` gates planning behind N approvals.
- AC9: `speed serve` provides `/api/claim` with atomic arbitration.
- AC10: Single-player projects that never run `mp-init` have zero behavior change.

## Tests

- `tests/test_multiplayer.sh` — 19 tests: actor identity, MP detection, zone migration, event emission/list/replay, roster, unique filenames
- `tests/test_multiplayer_ws6_ws7_ws8.sh` — 20 tests: multi-actor claims, file overlap, integration order, ceremony flows, defect events, pruning, actor attribution, HTTP server endpoints, claim arbitration
- `tests/test_multiplayer_python.py` — 6 tests: proposal writing, auto-merge, conflicts, locked skip, confidence scoring, proposal status marking

## Configuration

```toml
[multiplayer]
stale_window = 3600           # seconds before claim expires (default: 1h)
approval_threshold = 1        # approvals required before plan (default: 1)
prune_days = 30               # days before events archived (default: 30)
sync_interval = 30            # seconds between sync cycles (default: 30)
serve_port = 4450             # HTTP server port (default: 4450)
```

## Out of Scope

- Real-time collaborative editing (CRDT/Yjs) — belongs in the spec editor
- Role-based access control — all actors are peers
- Cross-repository coordination
- Hosted infrastructure beyond the optional local HTTP server
