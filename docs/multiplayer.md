---
title: Multi-Player Mode
description: How to run SPEED with multiple operators on the same repository, with conflict-free git merges and shared knowledge.
---

Single-player SPEED stores everything in `.speed/`, gitignored entirely. One person runs `speed plan`, `speed run`, `speed integrate` on one feature at a time. Multi-player mode splits that state into zones, adds an event log for conflict-free merges, and gives the team visibility into who is working on what.

## When You Need It

You have two engineers, each working a different feature on the same repo. Without multi-player mode, both write to `.speed/features/`, `.speed/memory/`, and `.speed/worktrees/`. One pushes, the other gets merge conflicts in gitignored directories. Worse, learnings from one feature silently overwrite learnings from the other.

Multi-player mode fixes three problems:

1. **State conflicts.** Shared state (tasks, contracts, knowledge) lives in committed directories. Runtime state (logs, locks, worktrees) stays local and gitignored.
2. **Concurrent ownership.** Each feature has one claimed owner at a time. Concurrent mutation is prevented by the claim system, not by hoping people communicate.
3. **Knowledge drift.** Learnings go through a proposal pipeline with confidence scoring. No one overwrites shared conventions directly.

## Setup

```bash
# Initialize multi-player mode on an existing project
speed mp-init
```

The command restructures `.speed/` into two zones:

```
.speed/
├── shared/          ← git-tracked, committed
│   ├── events/      ← append-only event log (JSONL files)
│   ├── features/    ← task DAGs, contracts, spec paths
│   ├── knowledge/   ← conventions, learnings, observations
│   ├── proposals/   ← pending knowledge contributions
│   └── roster/      ← per-actor heartbeat files
├── local/           ← gitignored, per-machine
│   ├── features/    ← logs, state.json per feature
│   ├── locks/       ← feature-scoped locks
│   └── worktrees/   ← git worktrees for agent execution
└── context/         ← codebase index (Layer 1 artifacts)
```

Existing features, memory, and worktrees migrate automatically. The project `.gitignore` updates from `.speed/` to `.speed/local/` so shared state becomes trackable.

## Claiming Features

Before running any mutation command (`plan`, `run`, `review`, `integrate`), claim the feature:

```bash
speed claim auth-flow
```

The claim is recorded as an event file in `shared/events/`. A second operator trying to claim the same feature gets a clear rejection:

```
Error: Feature 'auth-flow' is claimed by Alice
```

Claims expire after one hour of inactivity (configurable in `speed.toml`). Release explicitly when you're done:

```bash
speed release auth-flow
```

Running `speed run` without a claim produces a warning that suggests the `claim` command. Running it while someone else holds the claim exits with an error.

## Two-Operator Workflow

```
┌─────────────────────────┐    ┌─────────────────────────┐
│  Alice                  │    │  Bob                    │
│                         │    │                         │
│  speed claim auth-flow  │    │  speed claim dashboard  │
│  speed plan auth.md     │    │  speed plan dash.md     │
│  speed run              │    │  speed run              │
│  speed review           │    │  speed review           │
│  speed integrate        │    │  speed integrate        │
│  speed release auth-flow│    │  speed release dashboard│
│                         │    │                         │
│  git push               │    │  git push               │
└────────────┬────────────┘    └────────────┬────────────┘
             │                              │
             └──────────┬───────────────────┘
                        │
                   git merge
                   (zero conflicts)
```

Event files have unique names (`{timestamp}_{actor}_{type}_{feature}.jsonl`), so git merges them without conflicts. Feature directories are separate. The only shared mutable state is knowledge, which goes through the proposal pipeline.

## Team Visibility

Every `speed` command writes a heartbeat to the roster. Check who's active:

```bash
speed status --team
```

```
  ACTOR                FEATURE              STAGE        LAST SEEN            COMMAND
  Alice                auth-flow            running      2m ago               run
  Bob                  dashboard            idle         15m ago              review
```

Entries older than 24 hours are filtered out.

## Knowledge Proposals

In single-player mode, `speed learn` writes observations and conventions directly to `.speed/memory/`. In multi-player mode, it writes a proposal file to `shared/proposals/` instead.

Merge proposals into shared knowledge:

```bash
# See what's pending
speed learn --pending

# Auto-merge non-conflicting proposals, flag conflicts
speed learn --merge

# Interactively resolve conflicts
speed learn --curate
```

The merge pipeline uses four confidence tiers:

| Tier | Condition | Behavior |
|---|---|---|
| **low** | Single observation, one actor | Auto-merged, may be overwritten |
| **medium** | Multiple observations or actors | Auto-merged, bumped on confirmation |
| **high** | Consistent across 3+ features | Auto-merged, resistant to contradiction |
| **locked** | Human-curated | Never auto-modified |

Conflicting proposals (same convention key, different values) are written to `knowledge/conflicts.json` for human curation. The `--curate` flag walks through each conflict and lets you choose which value to keep, locking it against future auto-modification.

## Cross-Feature Validation

When multiple features are in flight, validate them against each other before anyone integrates:

```bash
# Cross-reference all active feature specs for contradictions
speed validate --all-active

# Check completed branches across features for compatibility
speed coherence --cross-feature
```

Cross-feature validation catches problems that single-feature validation misses: two features changing the same database table with incompatible schemas, overlapping file ownership, contradictory architectural assumptions. The output includes a recommended integration order based on overlap density (fewest cross-feature dependencies go first).

## Spec Review Ceremony

Specs go through propose/review/ratify before planning starts. Replaces ad-hoc "did you look at this?" with an auditable event trail.

```bash
# Propose a spec for team review
speed spec propose specs/tech/auth-flow.md

# Reviewers list pending specs and submit verdicts
speed spec review
speed spec review --approve specs/tech/auth-flow.md
speed spec review --reject specs/tech/auth-flow.md --comment "Missing error handling criteria"

# Check threshold and unlock planning
speed spec ratify specs/tech/auth-flow.md
```

Until a spec is ratified, `speed plan` blocks with a message pointing to the missing approvals. The approval threshold defaults to 1 and is configurable in `speed.toml`.

## Outcome Review Ceremony

After `speed run` and `speed review` complete, post the outcome evidence for team judgment:

```bash
# Owner posts evidence (task counts, review results, guardian verdicts)
speed review request

# Team members submit verdicts
speed review judge --approve
speed review judge --reject --comment "Task 3 guardian rejection needs investigation"

# Check consolidated feedback
speed review status
```

Verdicts are events. Nobody schedules a meeting. The owner checks `review status` and sees consolidated feedback.

## Rebuilding State

The event log is the source of truth. If materialized state (task JSON files) diverges from what the events describe, rebuild it:

```bash
# Dry run: report divergence without changing anything
speed rebuild-state

# Apply: overwrite materialized state from event replay
speed rebuild-state --apply
```

## Configuration

Add to `speed.toml`:

```toml
[multiplayer]
stale_window = 3600   # seconds before a claim expires (default: 1 hour)
```

## Actor Identity

SPEED resolves the current actor in this order:

1. `$SPEED_ACTOR` environment variable
2. `git config user.name`
3. `$(whoami)`

Check your resolved identity:

```bash
speed whoami
# Alice Chen (alice-chen)
```

The slug (parenthesized) is the filesystem-safe form used in event filenames and roster entries. Override with the environment variable when your git name doesn't match across machines:

```bash
export SPEED_ACTOR="Alice Chen"
```

## Actor Attribution

When multi-player is enabled, SPEED stamps actor identity onto state mutations. Task JSON includes `claimed_by` (who created it), `started_by` (who ran it), and `reviewed_by` (who reviewed it). Defect state includes `created_by` and `modified_by`, updated on every state write. Lock files include the actor name alongside the PID, so stale lock messages show who held it:

```
Warning: Breaking stale lock from 'run' (PID 42381, actor Alice Chen, acquired 2026-03-22T10:00:00Z)
```

These fields are only written when `MP_ENABLED` is true. Single-player task JSON is unchanged.

## Confidence in Agent Context

Conventions merged through the proposal pipeline carry a confidence tier. When agents receive conventions in their context, the formatting reflects this:

- **locked** and **high** conventions are prefixed with `[LOCKED]` or `[HIGH]` so agents treat them as authoritative
- Conventions are sorted by confidence tier, highest first
- Under token pressure, low-confidence conventions are truncated before high-confidence ones

## Event Pruning

The event directory grows over time. Prune old events into per-feature archive files:

```bash
speed learn --prune
```

Events older than 30 days (configurable via `speed.toml`) are concatenated into `{feature}-archive.jsonl` and the individual files are removed. The archive is still readable by `event_replay` but no longer clutters the events directory.

```toml
[multiplayer]
prune_days = 30   # days before events are archived (default: 30)
```

## Progressive Enhancement

The base design requires nothing beyond git push/pull. For teams that want less friction:

### Sync Daemon (3-8 people)

```bash
# Start background sync (auto-push events, auto-pull changes)
speed sync start --interval 30

# Check status
speed sync status

# Stop
speed sync stop
```

The daemon watches `.speed/shared/` for changes, auto-commits, and pushes. Pulls remote changes on the configured interval. Conflict-free by design (events are unique files).

### HTTP Server (8-20 people)

```bash
# Start the multi-player server
speed serve --port 4450

# Endpoints:
#   GET  /api/roster    — team roster
#   GET  /api/events    — event stream (filterable by feature/type)
#   GET  /api/features  — active features with task counts
#   POST /api/claim     — arbitrated claim (prevents race conditions)
#   GET  /api/health    — server health check
```

The server provides claim arbitration that git-based coordination cannot: when two people try to claim the same feature in the same second, the server serializes the requests and only one wins. Without the server, both claim events would merge cleanly but both operators would think they own the feature.

```toml
# speed.toml
[multiplayer]
sync_interval = 30      # seconds between sync cycles
serve_port = 4450       # HTTP server port
```

## Next Steps

- [Multi-Player Architecture](/docs/architecture/multiplayer/) for the zone split design, event log format, and state model.
- [CLI Reference](/docs/api/cli/) for the full command set including `mp-init`, `claim`, `release`, and `rebuild-state`.
- [The SPEED Process](/docs/process/) for how multi-player mode maps to the three human ceremonies.
