---
title: Multi-Player Reference
description: Command reference, event log, directory structure, and configuration for SPEED multi-player mode.
---

Single-player SPEED stores everything in `.speed/`, gitignored entirely. One person runs `speed plan`, `speed run`, `speed integrate` on one feature at a time. Each feature run extracts what went wrong and what worked, and that knowledge feeds into the next run. Feature 10's agents are smarter than feature 1's because nine features of accumulated learnings live in `.speed/memory/` on that machine.

With two operators on the same repo, that breaks. Both write to `.speed/features/`, `.speed/memory/`, and `.speed/worktrees/`. One pushes, the other gets merge conflicts in gitignored directories. Learnings from one feature silently overwrite learnings from the other. Worse, Alice's agents never benefit from what Bob's features discovered, and nobody sees overlapping file ownership until integration fails.

Multi-player mode fixes three problems:

1. **State conflicts.** Shared state (tasks, contracts, knowledge) lives in committed directories with unique filenames, so git merges are always conflict-free. Runtime state (logs, locks, worktrees) stays local and gitignored.
2. **Concurrent ownership.** Each feature has one claimed owner at a time. Concurrent mutation is prevented by the claim system, not by hoping people communicate.
3. **Knowledge drift.** Learnings go through a proposal pipeline with confidence scoring. Alice's observations from auth-flow and Bob's observations from dashboard both feed into shared conventions. Feature 15 benefits from every feature the team has shipped, not just the ones one person ran. No one overwrites shared conventions directly.

This page is the technical reference for all multi-player commands, events, and configuration. For the setup walkthrough, see [Multi-Player Mode](/docs/multiplayer/). For the system design, see [Multi-Player Architecture](/docs/architecture/multiplayer/).

## Setup

### `mp-init`

Initializes multi-player mode on an existing SPEED project. Safe to run on an already-initialized project (no-op).

**What it does:**
- Creates the `shared/` and `local/` zone split under `.speed/`
- Migrates existing features: task JSONs and contracts go to `shared/features/`, logs and state go to `local/features/`
- Migrates `.speed/memory/` to `.speed/shared/knowledge/`
- Updates `.speed/.gitignore` to allowlist `shared/` and ignore everything else
- Updates the project `.gitignore` from `.speed/` to `.speed/local/`
- Emits a `system.initialized` event
- Writes an initial roster heartbeat

## Directory Structure

```
.speed/
├── shared/                              git-tracked, committed
│   ├── events/                          append-only event log
│   │   └── {ts}_{actor}_{type}_{feature}.jsonl
│   ├── features/
│   │   └── {feature}/
│   │       ├── tasks/*.json             task definitions (DAG)
│   │       ├── contract.json            data model contract
│   │       └── spec_path                pointer to source spec
│   ├── knowledge/                       merged learning artifacts
│   │   ├── conventions.json             conventions with confidence tiers
│   │   ├── conventions-meta.json        discovery metadata
│   │   ├── conflicts.json               unresolved conflicts
│   │   ├── observations.jsonl           merged observations
│   │   ├── {agent}-learnings.json       per-agent synthesized learnings
│   │   ├── project-knowledge.json       promoted knowledge entries
│   │   └── models/review_classifier.pkl trained classifier
│   ├── proposals/                       pending knowledge contributions
│   │   └── {ts}_{actor}_{feature}.json
│   └── roster/                          per-actor heartbeat files
│       └── {actor-slug}.json
│
├── local/                               gitignored, per-machine
│   ├── features/
│   │   └── {feature}/
│   │       ├── logs/                    agent output, gate logs
│   │       └── state.json               runtime state
│   ├── locks/
│   │   └── claim-{feature}/             atomic claim locks (dirs)
│   ├── worktrees/                       git worktrees
│   ├── sync.pid, sync.log              sync daemon
│   ├── serve.pid, serve.log            HTTP server
│   └── dashboard.db                     dashboard database
│
└── context/                             Layer 1 artifacts
    ├── semantic-graph.json              codebase semantic graph
    └── project-map.json                 project symbol map
```

**Zone split principle:** If two operators need the same data, it goes in `shared/` (git-tracked). Machine-specific runtime state (logs, locks, worktrees, PIDs) goes in `local/` (gitignored).

### Path Resolution

The same commands work in both modes. `feature_activate()` resolves paths based on `MP_ENABLED`:

| Artifact | Single-player | Multi-player |
|----------|--------------|-------------|
| Task JSONs | `.speed/features/{name}/tasks/` | `.speed/shared/features/{name}/tasks/` |
| Contract | `.speed/features/{name}/contract.json` | `.speed/shared/features/{name}/contract.json` |
| Logs | `.speed/features/{name}/logs/` | `.speed/local/features/{name}/logs/` |
| Runtime state | `.speed/features/{name}/state.json` | `.speed/local/features/{name}/state.json` |
| Locks | `.speed/features/{name}/speed.lock` | `.speed/local/locks/{name}.lock` |
| Worktrees | `.speed/worktrees/{name}/` | `.speed/local/worktrees/{name}/` |
| Knowledge | `.speed/memory/` | `.speed/shared/knowledge/` |

`MP_ENABLED` is set at bootstrap by checking for the existence of `.speed/shared/`.

## Claim and Release

Features have exclusive ownership. One actor holds the claim at a time, preventing concurrent mutation of the same task DAG.

### `claim <feature>`

Claims exclusive ownership of a feature. Creates the shared feature directory if it doesn't exist. Emits a `feature.claimed` event.

| Scenario | Behavior |
|----------|----------|
| Feature unclaimed | Claim granted, event emitted |
| Already own it | No-op, return success |
| Owned by another actor | Error with current owner's name |
| Claim older than stale window | Treated as unclaimed, claim granted |

### `release <feature>`

Releases ownership. Emits a `feature.released` event. Only the current owner can release. Releasing an unclaimed feature is a no-op with a warning.

### `whoami`

Prints the resolved actor identity and filesystem slug. Resolution order:
1. `$SPEED_ACTOR` environment variable
2. `git config user.name`
3. `$(whoami)`

Works without multi-player mode enabled.

### Ownership Resolution

Ownership is determined from event files, not lock files. `ownership_check()` scans for the latest `feature.claimed` and `feature.released` events for a given feature and applies three rules:

1. No claim events exist: unclaimed
2. Latest release is newer than latest claim: unclaimed
3. Claim age exceeds `stale_window` (default: 3,600 seconds): unclaimed

The stale window prevents abandoned claims from blocking the team. Configure it via `[multiplayer] stale_window` in `speed.toml`.

### Claim Guard

`_require_feature()` enforces ownership before pipeline commands (plan, run, review, integrate):

- Feature owned by another actor: exit with error
- Feature unclaimed: print warning (non-blocking)
- Single-player mode: all checks skipped

### Race Condition Prevention

File-based claim events merge cleanly in git but don't prevent simultaneous claims at the same second. When running `speed serve`, the HTTP server provides atomic claim arbitration:

- Uses `mkdir` for atomicity (directory creation is atomic on POSIX)
- First request succeeds with 200
- Second request gets 409 with the owner's name
- Requires `speed serve` to be running

## Event Log

All state changes are recorded as append-only event files in `.speed/shared/events/`.

### File Naming

```
{ISO8601}_{actor-slug}_{event-type-dashes}_{feature}.jsonl
```

Example: `20260322T143022Z_alice-chen_feature-claimed_auth.jsonl`

Timestamps include milliseconds. Combined with actor slug and feature name, filenames are guaranteed unique. Since events are individual files that are never modified or deleted, git merges are always conflict-free.

### Event Format

Each file contains a single JSON line:

```json
{
  "timestamp": "2026-03-22T14:30:22Z",
  "type": "feature.claimed",
  "feature": "auth-flow",
  "actor": "Alice Chen",
  "data": {}
}
```

### Event Types

#### System

| Event | Emitted by | Data fields |
|-------|-----------|-------------|
| `system.initialized` | `mp-init` | -- |

#### Feature Lifecycle

| Event | Emitted by | Data fields |
|-------|-----------|-------------|
| `feature.claimed` | `speed claim` | `actor` |
| `feature.released` | `speed release` | -- |
| `feature.planned` | `speed plan` | `task_count`, `spec_path` |

#### Task State Machine

| Event | Emitted by | Data fields |
|-------|-----------|-------------|
| `task.created` | task creation | `id`, `title`, `branch`, `depends_on[]` |
| `task.started` | task execution | `id`, `pid` |
| `task.completed` | task completion | `id` |
| `task.failed` | task failure | `id`, `error` |
| `task.blocked` | dependency block | `id`, `reason` |
| `task.reset` | retry/reset | `id` |

#### Pipeline Stages

| Event | Emitted by | Data fields |
|-------|-----------|-------------|
| `review.completed` | `speed review` | `task_id`, `verdict` |
| `coherence.completed` | `speed coherence` | `status` |
| `run.started` | `speed run` | `max_parallel` |
| `run.completed` | `speed run` | `done`, `failed`, `blocked` |
| `integrate.completed` | `speed integrate` | `branches_merged` |
| `learn.extracted` | `speed learn` | -- |

#### Defect Pipeline

| Event | Emitted by | Data fields |
|-------|-----------|-------------|
| `defect.filed` | defect init | `severity`, `source` |
| `defect.transitioned` | state transition | `from`, `to` |
| `defect.triaged` | triage | `complexity` |
| `defect.escalated` | escalation | `prd_path` |

#### Spec Review Ceremony

| Event | Emitted by | Data fields |
|-------|-----------|-------------|
| `spec.proposed` | `speed spec propose` | `spec_path`, `content_hash` |
| `spec.reviewed` | `speed spec review` | `spec_path`, `verdict`, `comment` |
| `spec.ratified` | `speed spec ratify` | `spec_path` |

#### Outcome Review

| Event | Emitted by | Data fields |
|-------|-----------|-------------|
| `outcome.review_requested` | `speed review request` | `feature`, `task_count`, `passed`, `rejected` |
| `outcome.judged` | `speed review judge` | `feature`, `verdict`, `comment` |

### Event Guarding

All `event_emit()` calls are guarded by `[[ "${MP_ENABLED:-}" == "true" ]]`. In single-player mode, no events are written.

### Event Replay

`speed rebuild-state` replays the event log to reconstruct task state. Compares the reconstructed state against materialized task JSON files:

- **Default (dry-run):** Reports matches and divergences without modifying files
- **`--apply`:** Overwrites materialized state where it diverges from the event log

`event_replay()` scans all event files for a feature, sorts by timestamp, and applies a state machine: `pending` to `running`/`blocked` to `done`/`failed`.

### Event Pruning

`speed learn --prune` archives events older than the configured threshold:

- Default: 30 days (set via `[multiplayer] prune_days` in `speed.toml`)
- Old events are appended to `{feature}-archive.jsonl` per feature
- Original event files are deleted
- Archive files are never re-pruned (detected by filename pattern)

## Knowledge Pipeline

After agents complete work, observations are extracted and reconciled across operators through a proposal-based pipeline. The commands below are documented here in the context of team collaboration. For the full learning system (extraction pipeline, observation types, synthesis algorithm), see the [Learning System](/docs/api/learn/) reference.

### How It Works

```
Actor A: speed learn → writes proposal to shared/proposals/
Actor B: speed learn → writes proposal to shared/proposals/
                  ↓
Curator:  speed learn --pending   (review incoming proposals)
          speed learn --merge     (auto-merge, flag conflicts)
          speed learn --curate    (resolve conflicts interactively)
```

In single-player mode, `speed learn` writes directly to `memory/observations/`. In multi-player mode, it writes a proposal file instead:

```
.speed/shared/proposals/{timestamp}_{actor-slug}_{feature}.json
```

Proposals contain observation objects and proposed convention entries, tagged with actor and feature name.

### `learn --pending`

Lists all pending (unmerged) proposals. Shows actor, feature, observation count, convention count, and timestamp.

### `learn --merge`

Reads all pending proposals and reconciles them against `shared/knowledge/conventions.json`:

| Situation | Result |
|-----------|--------|
| New key, consistent values | Auto-merged with `low` or `medium` confidence |
| Existing key, same value | Confidence tier bumped (low to medium, medium to high) |
| Existing key, different value | Written to `conflicts.json` |
| Existing key with `locked` confidence | Proposal skipped |

Processed proposals are marked `status: "merged"` and their observations are appended to `knowledge/observations.jsonl`.

### `learn --curate`

Interactive conflict resolution. Walks through each entry in `conflicts.json` with three options:

- **Keep existing** -- retain the current convention, discard the proposal
- **Accept proposed** -- replace with the proposal
- **Skip** -- leave unresolved for later

Resolved entries are set to `locked` confidence, which prevents all future auto-modification.

### Confidence Tiers

| Tier | Condition | Auto-modified? |
|------|-----------|----------------|
| `low` | Single observation, one actor | Yes |
| `medium` | Multiple observations or multiple actors | Yes |
| `high` | Consistent across 3+ features | Yes (resistant to contradiction) |
| `locked` | Human-curated via `--curate` | Never |

When formatting conventions for agent context, entries are sorted by confidence (locked first, then high, medium, low). Under token pressure, low-confidence entries are truncated first.

### `learn --prune`

Archives events older than the configured threshold. See [Event Pruning](#event-pruning) above.

## Spec Collaboration

The spec review ceremony gates `speed plan` behind team approval.

### `spec propose <spec-path>`

Creates a `spec.proposed` event. Records the spec's content hash for change tracking. Blocks `speed plan` until the spec is ratified.

### `spec review`

Without flags, lists all pending spec proposals with approval counts.

With verdict flags:

```bash
speed spec review --approve specs/tech/auth-flow.md
speed spec review --reject specs/tech/auth-flow.md --comment "Missing error handling"
```

Each verdict is recorded as a `spec.reviewed` event. Multiple reviewers can submit verdicts.

### `spec ratify <spec-path>`

Checks the approval threshold (default: 1, configurable via `[multiplayer] approval_threshold` in `speed.toml`):

| Condition | Result |
|-----------|--------|
| Approvals >= threshold and no outstanding rejections | Emits `spec.ratified`, unlocks planning |
| Approvals < threshold | Error: "Need N more approvals" |
| Outstanding rejections | Error: "Spec has rejections, resolve feedback first" |

### Planning Gate

During `speed plan`, the system checks for unratified proposals:
- `spec.proposed` without `spec.ratified`: exit with message directing to `speed spec review`
- No proposal event (solo/legacy workflow): warning, but proceeds

## Outcome Reviews

The outcome review ceremony provides team oversight after execution, before integration.

### `review request`

Posts outcome evidence for team review. Run after `speed run` and `speed review` complete. Evidence includes task counts (total, passed, rejected, blocked), review results, guardian verdicts, coherence status, and security findings summary. Emits an `outcome.review_requested` event.

### `review judge`

```bash
speed review judge --approve
speed review judge --reject --comment "Task 3 guardian rejection needs investigation"
```

Submits a verdict as an `outcome.judged` event. Multiple judges can submit. This is advisory, not a blocking gate. The feature owner decides whether to proceed with `speed integrate` based on the feedback.

### `review status`

Aggregates all verdicts for the feature from the event log: who requested, evidence summary, all verdicts with comments.

## Cross-Feature Validation

### `validate --all-active`

Cross-references all claimed features' specs against each other:

1. **Spec cross-validation** -- contradictory requirements, incompatible schema changes, overlapping scope
2. **File ownership overlap** -- files claimed by 2+ features
3. **Integration order recommendation** -- sorted by fewest cross-feature dependencies first

### `coherence --cross-feature`

Checks completed branches across all active features for compatibility: interface mismatches, conflicting modifications to shared files, incompatible migrations, duplicate logic.

## Sync Daemon

The sync daemon automates git push/pull for the shared directory.

### `sync start [--interval N]`

Starts a background daemon (default interval: 30 seconds). Each cycle:

1. `git fetch origin`
2. `git merge --ff-only origin/{branch}`
3. Check `.speed/shared/` for local changes
4. If changes: `git add`, `git commit`, `git push`

Writes PID to `.speed/local/sync.pid` and logs to `.speed/local/sync.log`.

Without the daemon, operators push manually after each command. With it, events appear in the team's repo within the sync interval.

### `sync stop`

Kills the daemon by PID and removes the PID file.

### `sync status`

Reports whether the daemon is running and shows recent log entries.

## HTTP Server

The HTTP server provides REST endpoints for team state and atomic claim arbitration.

### `serve start [--port PORT]`

Starts the server (default port: 4450). Reads from the same file-based state as the CLI. Stateless; all state lives in `.speed/shared/`.

#### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Server status (200 OK) |
| `/api/roster` | GET | Team roster (actors active in last 24h) |
| `/api/events` | GET | Event stream, filterable by `?feature=` and `?type=` and `?limit=` |
| `/api/features` | GET | Active features with task counts (done/running/failed) and owner |
| `/api/claim` | POST | Atomic claim arbitration (200 on success, 409 with owner on conflict) |
| `/ws/events` | WS | Real-time event push (requires uvicorn + starlette, falls back to REST-only) |

The `/api/claim` endpoint solves the race condition that event files alone cannot prevent. It uses `mkdir` for atomicity: directory creation is atomic on POSIX, so the first request succeeds and the second gets `FileExistsError`.

### `serve stop`

Graceful shutdown with timeout, then force-kill.

### `serve status`

Reports running state and PID.

## Roster

Every `speed` command writes a heartbeat to `.speed/shared/roster/{actor-slug}.json`:

```json
{
  "name": "Alice Chen",
  "active_feature": "auth-flow",
  "active_stage": "running",
  "last_seen": "2026-03-22T14:30:22Z",
  "last_command": "run"
}
```

Each actor writes to their own file. Since files are per-actor, git merges are conflict-free.

### `status --team`

Reads all roster files, filters entries older than 24 hours, and formats as an aligned table:

```
  ACTOR          FEATURE        STAGE      LAST SEEN      COMMAND
  Alice          auth-flow      running    2m ago         run
  Bob            dashboard      idle       15m ago        review
```

## Configuration

All multiplayer settings live in `speed.toml` under `[multiplayer]`:

| Key | Default | Description |
|-----|---------|-------------|
| `stale_window` | `3600` | Seconds before an unrefreshed claim expires |
| `sync_interval` | `30` | Seconds between sync daemon cycles |
| `serve_port` | `4450` | HTTP server port |
| `prune_days` | `30` | Days before events are archived |
| `approval_threshold` | `1` | Spec review approvals required for ratification |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SPEED_ACTOR` | Override actor identity (bypasses git config and whoami) |
| `MP_ENABLED` | Set automatically at bootstrap by checking for `.speed/shared/` |
