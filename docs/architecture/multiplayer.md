---
title: Multi-Player Architecture
description: Zone split design, append-only event log, ownership model, and knowledge pipeline for concurrent SPEED operators.
---

Single-player SPEED treats `.speed/` as a flat runtime directory, fully gitignored. Multi-player mode introduces structure: shared state that commits to git, local state that stays per-machine, and an event log that makes concurrent work mergeable.

## Zone Split

```
.speed/
├── shared/              ← committed to git
│   ├── events/          ← append-only JSONL files
│   ├── features/
│   │   └── auth/
│   │       ├── tasks/   ← task DAG (JSON per task)
│   │       └── contract.json
│   ├── knowledge/       ← merged conventions, learnings
│   ├── proposals/       ← pending knowledge contributions
│   └── roster/          ← actor heartbeat files
├── local/               ← gitignored
│   ├── features/
│   │   └── auth/
│   │       ├── logs/    ← agent output, gate logs
│   │       └── state.json
│   ├── locks/           ← feature-scoped locks
│   ├── worktrees/       ← git worktrees
│   └── main.lock        ← main-branch merge serializer
└── context/             ← Layer 1 artifacts (CSG, project map)
```

The split follows one rule: **if two operators need to see the same data, it goes in shared/; if it's machine-specific runtime state, it goes in local/**. Task definitions, contracts, events, and knowledge are shared. Logs, locks, PID tracking, and worktrees are local.

`feature_activate()` in `lib/features.sh` routes paths based on the `MP_ENABLED` flag:

| Path | Single-player | Multi-player |
|---|---|---|
| `TASKS_DIR` | `.speed/features/{name}/tasks/` | `.speed/shared/features/{name}/tasks/` |
| `CONTRACT_FILE` | `.speed/features/{name}/contract.json` | `.speed/shared/features/{name}/contract.json` |
| `LOGS_DIR` | `.speed/features/{name}/logs/` | `.speed/local/features/{name}/logs/` |
| `STATE_FILE` | `.speed/features/{name}/state.json` | `.speed/local/features/{name}/state.json` |
| `SPEED_LOCK` | `.speed/features/{name}/speed.lock` | `.speed/local/locks/{name}.lock` |
| `WORKTREES_DIR` | `.speed/worktrees/{name}/` | `.speed/local/worktrees/{name}/` |

When `MP_ENABLED` is false, every path resolves identically to the single-player layout. The conditional is evaluated once at bootstrap in the `speed` entry point.

## Event Log

Every state mutation emits a JSONL event file to `shared/events/`. File naming guarantees uniqueness across actors and timestamps:

```
{ISO8601}_{actor-slug}_{event-type}_{feature}.jsonl
```

Example: `20260322T143022Z_alice-chen_task-completed_auth.jsonl`

Each file contains a single JSON line:

```json
{
  "timestamp": "2026-03-22T14:30:22Z",
  "type": "task.completed",
  "feature": "auth",
  "actor": "Alice Chen",
  "data": {"id": "3"}
}
```

### Event Types

**Feature lifecycle:**

| Event | Emitted by | Data fields |
|---|---|---|
| `feature.claimed` | `speed claim` | `actor` |
| `feature.released` | `speed release` | |
| `feature.planned` | `cmd_plan` | `task_count`, `spec_path` |

**Task state machine:**

| Event | Emitted by | Data fields |
|---|---|---|
| `task.created` | `task_create()` | `id`, `title`, `branch`, `depends_on` |
| `task.started` | `task_set_running()` | `id`, `pid` |
| `task.completed` | `task_set_done()` | `id` |
| `task.failed` | `task_set_failed()` | `id`, `error` |
| `task.blocked` | `task_set_blocked()` | `id`, `reason` |
| `task.reset` | `task_reset_pending()` | `id` |

**Pipeline stages:**

| Event | Emitted by | Data fields |
|---|---|---|
| `review.completed` | `task_set_reviewed()` | `task_id`, `verdict` |
| `coherence.completed` | `cmd_coherence` | `status` |
| `run.started` | `cmd_run` | `max_parallel` |
| `run.completed` | `cmd_run` | `done`, `failed`, `blocked` |
| `integrate.completed` | `cmd_integrate` | `branches_merged` |
| `learn.extracted` | `cmd_learn` | |

**Defect pipeline:**

| Event | Emitted by | Data fields |
|---|---|---|
| `defect.filed` | `defect_init()` | `severity`, `source` |
| `defect.transitioned` | `defect_state_transition()` | `from`, `to` |
| `defect.triaged` | `defect_triage_write()` | `complexity` |
| `defect.escalated` | `defect_escalate_to_prd()` | `prd_path` |

Events are guarded: `[[ "${MP_ENABLED:-}" == "true" ]] && event_emit ...`. In single-player mode, no events are written.

### Conflict-Free Merges

Two properties make the event log merge cleanly in git:

1. **Unique filenames.** Timestamps include milliseconds, combined with actor slug and feature name. Two actors producing the same event type for different features at the same second still get different filenames.
2. **Append-only.** Events are never modified or deleted. Git sees only file additions, which merge without conflict.

### State Reconstruction

`speed rebuild-state` replays events chronologically through a Python state machine that applies each event type to reconstruct the expected task statuses. The output is compared against materialized task JSON files. With `--apply`, diverged files are overwritten.

The replay state machine handles the full lifecycle: `created → started → completed/failed/blocked → reset → started → ...`. Ownership is reconstructed from `feature.claimed`/`feature.released` pairs with staleness applied.

## Actor Attribution

Beyond events, actor identity is stamped directly onto state objects so attribution survives without replaying the log.

**Task JSON** gains three fields when `MP_ENABLED` is true:

| Field | Set by | Value |
|---|---|---|
| `claimed_by` | `task_create()` | Actor who created the task |
| `started_by` | `task_set_running()` | Actor who launched the agent |
| `reviewed_by` | `task_set_reviewed()` | Actor who reviewed |

**Defect state** gains two fields:

| Field | Set by | Value |
|---|---|---|
| `created_by` | `defect_init()` | Actor who filed the defect |
| `modified_by` | `defect_state_write()` | Actor who last modified state |

**Lock files** include an `actor` file alongside `pid`, `command`, and `acquired_at`. Stale lock warnings and blocked-by messages include the actor name so operators know who to contact.

All fields are conditionally written via the `${MP_ENABLED:+$(actor_get)}` pattern. When empty (single-player), jq's conditional `if $field != "" then .field = $field else . end` leaves the JSON unchanged.

## Ownership Model

Ownership is derived from events, not from a lock file. `ownership_check()` scans event files matching `*_feature-claimed_{feature}.jsonl` and `*_feature-released_{feature}.jsonl`, finds the latest of each, and applies three rules:

1. **No claim events** → unclaimed (return code 2)
2. **Latest release is newer than latest claim** → unclaimed
3. **Claim age exceeds stale window** → treated as unclaimed

The stale window defaults to 3600 seconds (one hour) and is configurable via `speed.toml`. Staleness prevents abandoned claims from blocking the team.

`_require_feature()` calls `ownership_check()` in multi-player mode. A feature owned by another actor exits with an error. An unclaimed feature produces a warning suggesting `speed claim`. Single-player mode skips all ownership checks.

## Roster

`roster_heartbeat()` runs at the start of every `speed` command when multi-player is enabled. It writes a JSON file to `shared/roster/{actor-slug}.json`:

```json
{
  "name": "Alice Chen",
  "active_feature": "auth",
  "active_stage": "running",
  "last_seen": "2026-03-22T14:30:22Z",
  "last_command": "run"
}
```

`speed status --team` reads all roster files, filters entries older than 24 hours, and formats the result as an aligned table. Roster files are small, infrequently written, and merge cleanly because each actor writes to their own file.

## Knowledge Pipeline

```
speed learn (extract)
       │
       ▼
  shared/proposals/{ts}_{actor}_{feature}.json     ← pending
       │
       ▼
  speed learn --merge
       │
       ├── non-conflicting ──→ shared/knowledge/conventions.json
       │                       (confidence: low → medium → high)
       │
       └── conflicting ──────→ shared/knowledge/conflicts.json
                                      │
                                      ▼
                               speed learn --curate
                                      │
                                      ▼
                               shared/knowledge/conventions.json
                               (confidence: locked)
```

Each proposal contains observations and conventions extracted from a single feature by a single actor. The merge step applies confidence scoring:

- **low**: one observation, one actor
- **medium**: confirmed by multiple observations or multiple actors
- **high**: consistent across three or more features
- **locked**: set by human curation, immune to auto-modification

Proposals that agree with existing conventions bump the confidence tier. Proposals that contradict existing conventions (same key, different value) become conflicts. Locked conventions are never auto-modified.

All context assembly functions (`context_assemble_architect`, `context_assemble_developer`, `context_assemble_reviewer`, `context_assemble_coherence`, `context_assemble_debugger`) read from `shared/knowledge/` when multi-player is enabled, via the `SPEED_MEMORY_DIR` environment variable passed to the Python layer.

### Confidence in Agent Context

`format_conventions_for_agent()` in `lib/learn/conventions.py` handles the last mile: filtering conventions by scope, sorting by confidence, and formatting for token-limited prompts.

The sort order places locked and high-confidence entries first. Under token pressure (the 2,000-token convention budget), low-confidence entries are truncated before high-confidence ones. Locked and high entries receive a `[LOCKED]` or `[HIGH]` prefix in the formatted output so agents can distinguish authoritative conventions from emerging patterns.

The extraction path also changes in MP mode. `learn_extract()` in `lib/learn_bridge.sh` detects `_SPEED_MP_ENABLED` and calls `proposals.write_proposal()` instead of `write_observations()`. Observations are wrapped in a proposal JSON and written to `shared/proposals/` rather than appended directly to `memory/observations/`. The proposal includes the actor name and feature for attribution during merge.

### Event Pruning

`event_prune()` in `lib/events.sh` archives events older than a configurable threshold (default 30 days). For each expired event file, the content is appended to a per-feature archive (`{feature}-archive.jsonl`) and the individual file is removed. Archives are still readable by `event_replay` but reduce directory clutter.

Triggered via `speed learn --prune`. Configurable in `speed.toml`:

```toml
[multiplayer]
prune_days = 30
```

## Cross-Feature Validation

`cmd_validate_cross_feature()` in `lib/cmd/cross_feature.sh` discovers active features by scanning claim events, then runs three checks:

1. **Spec cross-validation.** Gathers all active features' specs and sends them to the Validator agent as a single prompt. The agent looks for contradictory requirements, incompatible schema changes, overlapping scope.

2. **File ownership overlap.** Reads `files_touched` from every task JSON across all active features. Files claimed by two or more features are flagged with their owners.

3. **Integration order.** Counts shared files per feature pair. Features with fewer cross-feature dependencies are recommended for earlier integration.

`cmd_coherence_cross_feature()` does the same for branches: gathers diffs from all done tasks across all active features and sends them to the Coherence Checker as a cross-feature prompt.

## Ceremony Event Flow

Both ceremonies (spec review and outcome review) are implemented as event queries in `lib/cmd/ceremony.sh`. No persistent state beyond the event log.

**Spec review flow:**

```
spec.proposed → spec.reviewed (N times) → spec.ratified
```

The ratification gate in `cmd_plan` scans for `spec.ratified` events. If a `spec.proposed` event exists but no `spec.ratified`, planning blocks. If no proposal exists at all, planning warns but proceeds (backward compatibility for solo operators).

**Outcome review flow:**

```
outcome.review_requested → outcome.judged (N times)
```

No blocking gate. The outcome review is advisory. `review status` aggregates verdicts for the human to decide when to integrate.

## Progressive Enhancement

### Sync Daemon

`lib/cmd/sync.sh` runs a background loop: fetch, fast-forward merge, check for local shared changes, commit, push. The commit uses `--no-verify` to skip hooks (sync commits are infrastructure, not code). The daemon writes its PID to `local/sync.pid` and logs to `local/sync.log`.

The interval is configurable. At 30 seconds (default), two operators see each other's events within a minute without manual push/pull.

### HTTP Server

`lib/serve/server.py` is a stdlib `http.server` implementation with no external dependencies. It reads the same file-based state that the CLI reads. Five endpoints cover the core coordination needs.

Claim arbitration uses `mkdir` for atomicity (same pattern as `speed_acquire_lock`). When two requests try to claim the same feature simultaneously, one `mkdir` succeeds and the other gets `FileExistsError`. The loser receives a 409 with the current owner's name.

The server is stateless. Kill it and restart it. All state lives in `.speed/shared/`. The server is a convenience read layer with one write operation (claim arbitration).

## Backward Compatibility

Multi-player is opt-in. The `MP_ENABLED` flag is set at bootstrap by checking for the existence of `.speed/shared/`. Every conditional in the codebase follows the pattern:

```bash
if [[ "${MP_ENABLED:-}" == "true" ]]; then
    # multi-player path
else
    # single-player path (unchanged from before)
fi
```

No existing behavior changes for projects that never run `speed mp-init`. The flag defaults to empty (falsy), and all path resolutions fall through to their original values.
