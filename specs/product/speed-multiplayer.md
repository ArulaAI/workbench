# Multi-Player Mode

> Design context: `working-docs/design-multiplayer-mode.md`
> Depends on: [Continuous Learning](speed-feedback-loop.md) (knowledge pipeline)

## Problem

SPEED stores all state in `.speed/`, gitignored entirely. One operator, one machine, one feature at a time. When a second person clones the repo and runs `speed plan`, their state collides with the first person's. Learnings from one feature silently overwrite learnings from another. Two people running `speed run` on the same feature corrupt task JSON with interleaved writes. There's no record of who did what.

Teams using SPEED today work around this by taking turns. One person finishes their feature before the next person starts. That's single-player with a queue, not collaboration.

## Users

### Engineering Lead
Runs multiple features in parallel across the team. Needs to see who's working on what, whether features will conflict at integration time, and which learnings the system has accumulated. Decides integration order.

### Engineer (Feature Owner)
Claims a feature, runs the full pipeline (plan → run → review → integrate), and releases when done. Wants the system to prevent someone else from mutating their feature mid-flight. Wants their learnings to reach the team without manual wiki updates.

### Product Manager
Proposes specs for review, tracks approval status, reviews outcome evidence after execution. Doesn't run the pipeline directly. Needs visibility into what's happening and confidence that specs are reviewed before agents execute them.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As an engineer, I want to claim exclusive ownership of a feature | Given I run `speed claim auth`, then no other actor can mutate auth's state until I release or my claim goes stale | Must |
| S2 | As a lead, I want to see who's working on what | Given two engineers are active, when I run `speed status --team`, then I see both actors, their features, stages, and last activity | Must |
| S3 | As an engineer, I want my state to merge cleanly with teammates' state | Given Alice pushes auth events and Bob pushes dashboard events, when they merge, then zero git conflicts occur | Must |
| S4 | As a PM, I want specs reviewed before agents execute them | Given I propose a spec, when fewer than N approvals exist, then `speed plan` blocks with a message showing the missing approvals | Must |
| S5 | As an engineer, I want learnings from my feature to reach the team | Given I run `speed learn` after a feature, when another engineer runs `speed learn --merge`, then non-conflicting conventions are auto-merged into shared knowledge | Must |
| S6 | As a lead, I want to catch cross-feature conflicts before integration | Given two features modify the same module, when I run `speed validate --all-active`, then the overlap is flagged with affected files and owners | Must |
| S7 | As an engineer, I want to rebuild state if something gets out of sync | Given events and materialized task files diverge, when I run `speed rebuild-state --apply`, then task files are corrected from the event log | Should |
| S8 | As a lead, I want to see outcome evidence before approving integration | Given a feature's pipeline is complete, when the owner runs `speed review request`, then I can submit a verdict via `speed review judge` | Should |
| S9 | As a team, we want automatic sync without manual push/pull | Given the sync daemon is running, when I emit an event, then teammates see it within the sync interval without git commands | Nice |
| S10 | As a larger team, we want claim arbitration that prevents race conditions | Given two engineers claim the same feature within one second, when using `speed serve`, then only one claim succeeds | Nice |

## User Flows

### Two engineers, different features (happy path)

1. Both run `speed mp-init` (one-time setup, restructures `.speed/`)
2. Alice: `speed claim auth-flow && speed plan specs/tech/auth.md && speed run`
3. Bob: `speed claim dashboard && speed plan specs/tech/dashboard.md && speed run`
4. Both push. `git merge` has zero conflicts.
5. `speed status --team` shows both actors and progress.
6. `speed validate --all-active` checks for cross-feature problems.
7. `speed learn --merge` combines learnings from both features.

### Spec review ceremony

1. PM runs `speed spec propose specs/tech/auth.md`
2. Engineers run `speed spec review` to see pending proposals
3. Engineer runs `speed spec review --approve specs/tech/auth.md`
4. PM runs `speed spec ratify specs/tech/auth.md` (checks threshold)
5. Planning unlocked: `speed plan specs/tech/auth.md` proceeds

### Outcome review ceremony

1. Feature owner: `speed review request` (posts task counts, review results, guardian verdicts)
2. Lead: `speed review judge --approve` or `--reject --comment "..."`
3. Owner: `speed review status` shows consolidated feedback
4. If approved: `speed integrate`

### Knowledge convergence

1. `speed learn` writes a proposal to `shared/proposals/` (not directly to knowledge)
2. `speed learn --merge` auto-merges non-conflicting conventions, flags conflicts
3. `speed learn --curate` walks through conflicts, human resolves, result locked

### Progressive enhancement

1. 1-3 people: git push/pull. Events merge cleanly.
2. 3-8 people: `speed sync start` runs a background push/pull daemon.
3. 8-20 people: `speed serve` adds HTTP API with claim arbitration.

## Scope

### In Scope
- State zone split (shared/ committed, local/ gitignored)
- Actor identity (`$SPEED_ACTOR` → `git config user.name` → `whoami`)
- Append-only event log with 18 event types
- Feature ownership (claim/release/stale window)
- Team roster (heartbeat on every command)
- Knowledge proposal pipeline with confidence scoring
- Cross-feature validation (spec contradictions, file overlap, branch coherence)
- Ceremony commands (spec propose/review/ratify, outcome request/judge/status)
- Sync daemon and HTTP server for larger teams
- Actor attribution on tasks, defects, and locks
- Event pruning and state reconstruction

### Out of Scope
- Real-time collaborative editing (Yjs/CRDT) — deferred to spec editor
- Role-based access control — all actors are peers
- Hosted infrastructure (database, message queue) — git is the coordination layer
- Cross-repo coordination — multi-player is within a single repository
- Automated conflict resolution for knowledge — conflicts require human curation

## Success Criteria

| Criterion | Measurement |
|---|---|
| Zero git merge conflicts from `.speed/` | Two actors push events for different features, merge produces no conflicts |
| Claim prevents concurrent mutation | Second `speed claim` on an owned feature exits with error |
| Knowledge scales with contributors | Conventions from 3+ actors across 3+ features reach "high" confidence |
| Cross-feature catches real overlaps | `validate --all-active` flags shared file ownership before integration |
| Ceremonies are async | Spec review and outcome review complete through events, no synchronous meetings |
| Backward compatible | Single-player projects that never run `mp-init` see zero behavior change |

## Security Considerations

- Actor identity is self-reported (`$SPEED_ACTOR`, git config, whoami). No authentication.
- Claim arbitration via the HTTP server uses `mkdir` atomicity, not cryptographic verification.
- Event files are world-readable in the repo. No encryption of actor names or event data.
- The sync daemon runs `git push` with the caller's credentials. No credential management.

These are acceptable for a team tool running on trusted machines. SPEED is not a SaaS product.

## Related Specs

- [Continuous Learning](speed-feedback-loop.md) — knowledge pipeline that proposals build on
- [Conventions](speed-conventions.md) — convention discovery that confidence scoring extends
- [Observations](speed-observations.md) — observation extraction that proposals wrap
