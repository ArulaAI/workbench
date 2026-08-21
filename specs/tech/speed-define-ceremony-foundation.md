# Define Ceremony — Foundation Reference

> Holistic reference for the Define Ceremony. All RFCs in the ceremony family reference this document for shared types, API surface, artifact flow, validation rules, and event types.
>
> This is not a plannable spec. It defines no tasks. It is the single source of truth that keeps the seven ceremony RFCs aligned: [identity](speed-define-ceremony-identity.md), [parent](speed-define-ceremony.md), [context](speed-define-ceremony-context.md), [editor](speed-define-ceremony-editor.md), [contributor](speed-define-ceremony-contributor.md), [commit](speed-define-ceremony-commit.md), [bootstrap](speed-define-ceremony-bootstrap.md).

## Artifact Flow

The Define Ceremony produces eight durable artifacts. All paths use `SpeedPaths` helpers, which resolve to `.speed/features/{feature}/` in SP and `.speed/shared/features/{feature}/` in MP (see [parent RFC](speed-define-ceremony.md) path helpers).

| Artifact | Format | Location | Produced by | Read by | Events (MP only) |
|----------|--------|----------|-------------|---------|------------------|
| Ceremony state | JSON | `ceremony.json` | [context](speed-define-ceremony-context.md) (`declareIntent` creates), [parent](speed-define-ceremony.md) (`transition_ceremony_state` updates) | All child RFCs (ownership checks, state guards) | — |
| Intent | JSON (text + metadata) | `intent.json` | [context](speed-define-ceremony-context.md) | [context](speed-define-ceremony-context.md), [editor](speed-define-ceremony-editor.md) | `spec.intent_declared` |
| Context package | JSON | `context-package.json` | [context](speed-define-ceremony-context.md) | [editor](speed-define-ceremony-editor.md), [contributor](speed-define-ceremony-contributor.md), [commit](speed-define-ceremony-commit.md) | — |
| Spec draft | Markdown | `specs/{type}/{name}.md` | [editor](speed-define-ceremony-editor.md) | [contributor](speed-define-ceremony-contributor.md), [commit](speed-define-ceremony-commit.md) | — |
| Validation snapshot | JSON | `validation-at-commit.json` | [editor](speed-define-ceremony-editor.md) | [commit](speed-define-ceremony-commit.md) | `spec.validation_completed` |
| Commit record | JSON | `commit.json` | [commit](speed-define-ceremony-commit.md) | Landing page, learning pipeline | `spec.proposed` |
| Suggestions | JSON | `suggestions.json` | [contributor](speed-define-ceremony-contributor.md) | [commit](speed-define-ceremony-commit.md) | `spec.suggestion_created` |
| Ratification verdicts | JSONL | `.speed/shared/events/` (MP only; SP has no ratification) | [commit](speed-define-ceremony-commit.md) | `speed plan` gate, Ratification view | `spec.reviewed`, `spec.ratified` |

## Ceremony State Machine

Defined and implemented by the [parent RFC](speed-define-ceremony.md). Borrows git's data model as a blueprint (immutable snapshots, content-addressed identity, forward-only refs, synchronous gates), but does not wrap or shell out to git. All ceremony state is application-level JSON managed by the SPEED backend. The one place git is touched directly: `commitSpec` runs `git commit` to write spec files to the repo. Everything else (revision chain, reflog, validation, ratification, suggestion anchoring) lives in `ceremony.json` and `suggestions.json`.

Each revision has a forward-only lifecycle; the ceremony itself progresses by creating new revisions and advancing the ref.

### Workflow

```
SINGLE-PLAYER

  bootstrap ──▶ declareIntent
                     │
                     ▼
              Rev 1: drafting ◀── validation fail
                     │
                validation gate (sync)
                     │
                     ▼
              Rev 1: committed
                     │
              auto-ratified (no verdicts needed)
                     │
                     ▼
              Rev 1: ratified ──▶ plan runs ──▶ need changes?
                                                       │
                                                 Rev 1 frozen
                                                 at ratified
                                                       │
                                                       ▼
                                                Rev 2: drafting ──▶ ... (same cycle)


MULTIPLAYER

  bootstrap ──▶ declareIntent
                     │
                     ▼
              Rev 1: drafting ◀── validation fail
                     │
              contributors leave suggestions
              author resolves (accept/dismiss)
                     │
                validation gate (sync)
                     │
                     ▼
              Rev 1: committed (unresolved suggestions warned, not blocked)
                     │
              verdicts accumulate (async)
                     │
               ┌─────┴──────┐
               ▼            ▼
          Rev 1: ratified   Rev 1: rejected
               │                   │
          plan runs          Rev 1 frozen
               │             at rejected
          need changes?            │
               │                   ▼
         Rev 1 frozen       Rev 2: drafting ──▶ ... (same cycle)
         at ratified               │
               │              suggestions on changed sections
               ▼              marked outdated; unchanged ones carry forward
        Rev 2: drafting ──▶ ... (same cycle)
               │
          suggestions on changed sections
          marked outdated; unchanged ones carry forward


ABANDONED (either mode, from drafting only)

              Rev N: drafting ──▶ Rev N: abandoned
                                       │
                                  grace period (90d)
                                       │
                                       ▼
                                 Rev N+1: drafting (recovers ceremony)
```

SP and MP follow the same state path. The difference is how `COMMITTED` resolves: SP auto-ratifies immediately, MP waits for verdicts. `RATIFIED` is the plan-unblocking state in both modes.

### Example

```
feature "add-timeout-handling" (multiplayer, 2-person team)

Rev 1 (initial)
  ├─ drafting    author writes PRD for timeout handling
  │              teammate suggests: "add error budget calculation" on §3 Error Handling
  │              teammate suggests: "clarify retry semantics" on §4 Retry Strategy
  │              author accepts error budget suggestion, dismisses retry ("covered in §2")
  ├─ validation  template conformance passes, cross-spec warns on missing error budget
  ├─ committed   suggestion snapshot: 2 received, 1 accepted, 1 dismissed
  ├─ verdicts    teammate rejects: "no retry backoff strategy"
  └─ rejected    frozen. revision_id: a3f8c012

Rev 2 (parent: a3f8c012, reason: "addressed rejection: added retry backoff section")
  ├─ drafting    author rewrites §4 Retry Strategy with backoff logic
  │              "clarify retry semantics" (dismissed, Rev 1) marked outdated — §4 hash changed
  │              "add error budget calculation" (accepted, Rev 1) unchanged — §3 hash same
  │              teammate suggests: "backoff cap should be configurable" on §4
  │              author accepts
  ├─ validation  all dimensions pass
  ├─ committed   suggestion snapshot: 3 total, 2 accepted, 1 dismissed, 1 outdated
  ├─ verdicts    teammate approves
  └─ ratified    plan unblocked. revision_id: 7e21b4d9

  speed plan runs against Rev 2's committed spec.

Rev 3 (parent: 7e21b4d9, reason: "post-ratification: plan surfaced missing circuit breaker edge case")
  ├─ drafting    author adds new §5 Circuit Breaker (§3, §4 unchanged)
  │              all prior suggestions unchanged — no sections modified
  │              teammate suggests: "circuit breaker should respect error budget from §3"
  │              author accepts
  ├─ validation  passes
  ├─ committed   suggestion snapshot: 4 total, 3 accepted, 1 dismissed, 1 outdated
  ├─ verdicts    teammate approves
  └─ ratified    plan unblocked. revision_id: f4c90a1e

  speed plan runs against Rev 3's committed spec.

ceremony.json at this point:

  current_revision: f4c90a1e
  revision_count: 3
  reflog:
    ┌──────────┬──────────┬────────┬──────────────────────────────────────────────┐
    │ from     │ to       │ actor  │ reason                                       │
    ├──────────┼──────────┼────────┼──────────────────────────────────────────────┤
    │ null     │ a3f8c012 │ sanjay │ initial commit                               │
    │ a3f8c012 │ 7e21b4d9 │ sanjay │ addressed rejection: added retry backoff     │
    │ 7e21b4d9 │ f4c90a1e │ sanjay │ post-ratification: missing circuit breaker   │
    └──────────┴──────────┴────────┴──────────────────────────────────────────────┘
```

### ceremony.json

Every mutation in the ceremony checks ownership, current revision state, and transition validity before proceeding. ceremony.json is where those answers live. Ownership checks, state guards, transition validation, and the `ceremonyInfo` query all read this file. Without it, current state would need to be reconstructed from the event log or scattered artifacts.

To read the current state: dereference `current_revision` into the `revisions` map. `revisions[current_revision].status` is the ceremony's active lifecycle state.

Stored at `SpeedPaths.ceremony_state(feature_name)`, which resolves to `.speed/features/{feature}/ceremony.json` in SP and `.speed/shared/features/{feature}/ceremony.json` in MP (see [Ceremony Path Helpers](#ceremony-path-helpers) below). Created by [context RFC](speed-define-ceremony-context.md) on `declareIntent`, updated by [parent RFC](speed-define-ceremony.md) on state transitions and revision creation.

| Field | Type | Description |
|-------|------|-------------|
| `feature_name` | string | Feature slug |
| `author` | string | Resolved by `get_current_actor()` at creation |
| `author_email` | string | Resolved by `get_current_actor()` at creation |
| `created_at` | ISO 8601 | When `declareIntent` was called |
| `is_multiplayer` | boolean | `MP_ENABLED` at creation time |
| `current_revision` | string | `revision_id` of the active revision |
| `revision_count` | integer | Total revisions created |
| `revisions` | map\<string, Revision\> | Keyed by `revision_id`. Every revision ever created, frozen in place |
| `reflog` | list\<ReflogEntry\> | Append-only log of ref movements |

### Revision

Immutable snapshot. Once a revision leaves `DRAFTING`, its fields are frozen permanently.

```python
@dataclass
class Revision:
    revision_id: str            # SHA-256 content hash (see Revision identity)
    parent_id: str | None       # previous revision's hash (null for first)
    status: CeremonyStatus      # current lifecycle state
    spec_content_hash: str      # SHA-256 of spec markdown
    context_package_hash: str   # SHA-256 of context-package.json
    validation_hash: str        # SHA-256 of validation results
    created_at: str             # ISO 8601
    reason: str | None          # why this revision exists (null for first)
```

**Revision identity** (content-addressed):

```python
revision_id = sha256(
    spec_content_hash    +
    context_package_hash +
    validation_hash      +
    (parent_revision_id or "")
)
```

Short-form: `revision_id[:8]`.

### States

```python
class CeremonyStatus(enum.Enum):
    DRAFTING = "drafting"      # author editing, Tier 1 validation live
    COMMITTED = "committed"    # validation passed, spec sealed. SP: auto-ratifies. MP: verdicts accumulate
    RATIFIED = "ratified"      # threshold met (or auto in SP), plan runs
    REJECTED = "rejected"      # terminal for this revision
    ABANDONED = "abandoned"    # terminal for this revision
```

### Transitions

**Within a revision** (`transition_ceremony_state`):

```python
VALID_TRANSITIONS: dict[CeremonyStatus, list[CeremonyStatus]] = {
    CeremonyStatus.DRAFTING:   [CeremonyStatus.COMMITTED, CeremonyStatus.ABANDONED],
    CeremonyStatus.COMMITTED:  [CeremonyStatus.RATIFIED, CeremonyStatus.REJECTED],
    CeremonyStatus.RATIFIED:   [],
    CeremonyStatus.REJECTED:   [],
    CeremonyStatus.ABANDONED:  [],
}
```

**Across revisions** (`create_revision`):

```
RATIFIED  [Rev N] ──▶ DRAFTING [Rev N+1]
REJECTED  [Rev N] ──▶ DRAFTING [Rev N+1]
ABANDONED [Rev N] ──▶ DRAFTING [Rev N+1]   (within grace period)
COMMITTED [Rev N] ──▶ DRAFTING [Rev N+1]   (SP: already auto-ratified, so this is post-RATIFIED)
```

Rev N is frozen at its terminal state. Rev N+1 starts at `DRAFTING` with `parent_id` pointing to Rev N. The ceremony ref advances to Rev N+1.

**Complete lifecycle:**

```
Rev 1: DRAFTING → COMMITTED → RATIFIED ──┐
                                          │ create_revision
Rev 2: DRAFTING → COMMITTED → REJECTED ──┤
                                          │ create_revision
Rev 3: DRAFTING → COMMITTED → RATIFIED   (current)
```

5 states, 4 within-revision transitions, 3 cross-revision transitions. All forward. Same path for SP and MP.

### Operations

Two operations modify ceremony state. Both implemented in the [parent RFC](speed-define-ceremony.md).

**`create_revision(feature_name: str, reason: str) -> Revision`**

Creates a new revision at `DRAFTING` and advances the ceremony ref.

| Precondition | Error |
|---|---|
| Caller is ceremony author | "Only the ceremony author ({author}) can perform this action" |
| No current revision, or current revision is in a terminal state | "Cannot create new revision: current revision is still in {status}" |

Steps:

1. Snapshot current spec, context, and validation hashes
2. Compute `revision_id` from hashes + parent ID
3. Write revision entry to `ceremony.json` with `status: DRAFTING`
4. Compare section hashes between old and new revision; mark suggestions on changed sections as `outdated`
5. Append reflog entry recording the ref movement
6. Set `current_revision` to the new `revision_id`
7. Increment `revision_count`

**`transition_ceremony_state(feature_name: str, target: CeremonyStatus) -> CeremonyStatus`**

Moves the current revision to `target`. Returns the new status.

| Precondition | Error |
|---|---|
| `target` in `VALID_TRANSITIONS[current_status]` | "Cannot transition from {current} to {target}" |
| `DRAFTING → COMMITTED`: validation gate passes | "Validation failed: {issues}" |
| `DRAFTING → COMMITTED`: all target spec paths unoccupied or owned by this ceremony | "Spec path {path} already exists and is not owned by ceremony '{name}'" |
| `COMMITTED → RATIFIED`: ratification threshold met | "Ratification threshold not met: {count}/{threshold}" |
| `COMMITTED → REJECTED`: at least one rejection verdict | (triggered automatically on rejection verdict) |

### Gates

**Validation** (`DRAFTING → COMMITTED`): synchronous. All six validation dimensions run during the transition. Errors block; warnings are recorded but allowed. On failure the transition is rejected, the ceremony stays in `DRAFTING`, and failures are written to the validation snapshot. No artifacts are sealed.

**Ratification** (`COMMITTED → RATIFIED` or `COMMITTED → REJECTED`): in SP, `commitSpec` auto-transitions to `RATIFIED` immediately after `COMMITTED` (the author's commit is sufficient ratification). In MP, the ceremony sits in `COMMITTED` while approvers call `submitRatification`. Each verdict is appended to the event log. When the approval threshold is met, `transition_ceremony_state` fires with target `RATIFIED`. A single rejection verdict triggers target `REJECTED`. Verdicts accumulate on the revision until one condition is met.

### Suggestions across revisions

Suggestions are per-ceremony, not per-revision. Stored in `suggestions.json` at `SpeedPaths.ceremony_suggestions(feature_name)`. Each suggestion is anchored to the revision and section it was created against.

When `create_revision` runs, it compares section content hashes between the old and new spec. Suggestions on sections whose hash changed are marked `outdated`. Suggestions on unchanged sections carry forward as-is.

`outdated` is a display-layer indicator, not a status change. A suggestion can be `accepted` and `outdated` at the same time (the section changed after the author accepted it). Only suggestions that are both `unresolved` and not `outdated` count as active at commit time.

Full suggestion data model (stored in `suggestions.json`, one entry per suggestion):

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique suggestion ID |
| `author` | string | Who created the suggestion (resolved by `get_current_actor()`) |
| `author_email` | string | Suggestion author's email |
| `revision_id` | string | Revision the suggestion was created against |
| `section_id` | string | Section the suggestion targets |
| `section_title` | string | Human-readable section name at creation time |
| `section_content_hash` | string | SHA-256 of the section content at creation time |
| `text` | string | Suggestion body (10-2000 chars) |
| `status` | string | `"unresolved"` / `"accepted"` / `"dismissed"` |
| `outdated` | boolean | `true` if `section_content_hash` no longer matches current revision's section |
| `created_at` | ISO 8601 | When the suggestion was created |
| `updated_at` | ISO 8601 or null | Last edit timestamp |
| `resolution` | SuggestionResolution or null | Who resolved it, when, and why (reason required for dismiss) |
| `thread` | list\<SuggestionReply\> | Conversation between author and ceremony owner |

The [contributor RFC](speed-define-ceremony-contributor.md) owns the `Suggestion` type and CRUD operations. The state machine's role is limited to the outdated-marking step during `create_revision`.

### Reflog

Records every ref movement. Append-only list in `ceremony.json`.

```python
@dataclass
class ReflogEntry:
    from_revision: str | None   # previous revision ID (null for first)
    to_revision: str            # new revision ID
    at: str                     # ISO 8601
    actor: str                  # who created the revision
    actor_email: str            # resolved by get_current_actor()
    reason: str                 # "initial commit", "addressed rejection: ...", "post-ratification: ..."
```

### Hooks

| Hook | Type | Fires when | Can abort? |
|------|------|-----------|------------|
| `post-create` | Notify | After `declareIntent` creates a new ceremony | No |
| `pre-revision` | Gate | Before `create_revision` writes a new revision | Yes |
| `post-revision` | Notify | After new revision is written and ref advances | No |
| `pre-validate` | Gate | Before validation gate runs | Yes |
| `post-validate` | Notify | After validation completes (pass or fail) | No |
| `pre-commit` | Gate | Before revision is sealed | Yes |
| `post-commit` | Notify | After revision is written | No |
| `pre-ratify` | Gate | Before approval verdict is recorded | Yes |
| `post-ratify` | Notify | After ratification threshold is met | No |
| `pre-reject` | Gate | Before rejection verdict is recorded | Yes |
| `post-reject` | Notify | After ceremony transitions to `REJECTED` | No |
| `post-abandon` | Notify | After ceremony transitions to `ABANDONED` | No |

### Downstream behavior

System-level behavior triggered by reaching specific states. These are guarantees, not optional hooks. Hooks fire after the system behavior completes.

| State reached | System behavior | Corresponding hook |
|---|---|---|
| `RATIFIED` | `speed plan` unblocked | `post-ratify` |
| `REJECTED` | Author notified with rejection reason | `post-reject` |
| `ABANDONED` | Ceremony ref marked inactive. Recoverable by creating a new revision within grace period (default 90 days) | `post-abandon` |

### Bootstrap

Precondition, not a state. The `/define/new` route checks `bootstrapStatus` and renders `BootstrapWizard` or `IntentInput`. The state machine starts at `DRAFTING` after bootstrap is satisfied.

## Shared Strawberry Types

All types live in `dashboard/backend/resolvers/ceremony_types.py`, built by the [parent RFC](speed-define-ceremony.md). Child specs import from here.

```python
# ── Ceremony lifecycle ────────────────────────────────────────

@strawberry.enum
class CeremonyStatus(enum.Enum):
    """Per-revision lifecycle state. Forward-only transitions."""
    DRAFTING = "drafting"
    COMMITTED = "committed"
    RATIFIED = "ratified"
    REJECTED = "rejected"
    ABANDONED = "abandoned"

@strawberry.type
class RevisionSummary:
    """One node in the revision chain. Maps to Revision dataclass in ceremony.json."""
    revision_id: str           # str — SHA-256 content hash (short-form: first 8 chars)
    parent_id: Optional[str]   # str | None — previous revision's hash (null for first)
    status: CeremonyStatus     # CeremonyStatus — current lifecycle state
    spec_content_hash: str     # str — SHA-256 of spec markdown
    context_package_hash: str  # str — SHA-256 of context-package.json
    validation_hash: str       # str — SHA-256 of validation results
    created_at: str            # ISO 8601
    reason: Optional[str]      # str | None — why this revision was created

@strawberry.type
class CeremonyInfo:
    """Top-level ceremony state. Maps to ceremony.json."""
    feature_name: str                    # str — feature slug
    current_revision: RevisionSummary    # RevisionSummary — dereferenced from revisions[current_revision]
    revision_count: int                  # int — total revisions created
    author: str                          # str — resolved by get_current_actor() at creation
    author_email: str                    # str — resolved by get_current_actor() at creation
    created_at: str                      # ISO 8601 — when declareIntent was called
    is_multiplayer: bool                 # bool — MP_ENABLED at creation time

# ── Intent ────────────────────────────────────────────────────

@strawberry.type
class Intent:
    """Maps to intent.json."""
    text: str              # str — intent text (min 5 chars)
    author: str            # str — resolved by get_current_actor()
    author_email: str      # str — resolved by get_current_actor()
    created_at: str        # ISO 8601
    feature_name: str      # str — slugified from text

# ── Context package ───────────────────────────────────────────

@strawberry.type
class CodebaseItem:
    """One node from the semantic graph, scoped by intent keywords."""
    path: str              # str — file path in the repo
    description: str       # str — what the file does
    node_ids: list[str]    # list[str] — CSG node identifiers

@strawberry.type
class LearningItem:
    """One learning from .speed/memory/observations/*.jsonl, filtered by scoped file paths."""
    text: str              # str — the learning or convention text
    source_feature: str    # str — feature slug whose run produced this observation (e.g. "add-timeout-handling")
    confidence: str        # str — "high" | "medium" | "low" | "locked"

@strawberry.type
class DefectItem:
    """One defect from .speed/defects/ or specs/defects/."""
    name: str              # str — defect identifier
    severity: str          # str — "critical" | "major" | "minor"
    status: str            # str — "open" | "resolved" | "wont_fix"
    related_files: list[str]  # list[str] — file paths affected

@strawberry.type
class KnowledgeItem:
    """One entry from .speed/memory/project-knowledge.json."""
    text: str              # str — the knowledge
    confidence: str        # str — "high" | "medium" | "low"
    source: str            # str — where it came from (e.g. "observation", "manual")

@strawberry.type
class RelatedFeature:
    """Another ceremony touching overlapping files."""
    name: str              # str — feature slug
    state: str             # str — CeremonyStatus value of the other ceremony's current revision
    overlap_files: list[str]  # list[str] — shared file paths

@strawberry.type
class AuditHistoryItem:
    """One finding from a past spec audit."""
    feature_name: str      # str — feature that was audited
    finding: str           # str — what was found
    severity: str          # str — "critical" | "major" | "minor" | "info"
    section: str           # str — spec section the finding applies to

@strawberry.type
class ContextPackage:
    """Maps to context-package.json. Assembled from 7 sources by the context RFC."""
    intent: str                             # str — intent text
    feature_name: str                       # str — feature slug
    scoped_area: list[str]                  # list[str] — CSG nodes matching intent keywords
    codebase: list[CodebaseItem]            # list[CodebaseItem] — semantic graph hits
    learnings: list[LearningItem]           # list[LearningItem] — from observations
    defects: list[DefectItem]               # list[DefectItem] — open and recent defects
    project_knowledge: list[KnowledgeItem]  # list[KnowledgeItem] — project memory
    vision_status: str                      # str — "available" | "missing" | "stale"
    vision_content: Optional[str]           # str | None — specs/product/overview.md content
    related_features: list[RelatedFeature]  # list[RelatedFeature] — ceremonies touching same files
    audit_history: list[AuditHistoryItem]   # list[AuditHistoryItem] — past audit findings
    assembled_at: str                       # ISO 8601
    sources_status: strawberry.scalars.JSON # dict — per-source assembly status ("ok" | "error" | "empty")

# ── Validation ────────────────────────────────────────────────

@strawberry.type
class ValidationIssue:
    """One issue found by a validation dimension."""
    id: str                          # str — unique issue identifier
    dimension: str                   # str — which dimension found it (matches ValidationDimension.name)
    severity: str                    # str — "error" | "warning" | "info"
    message: str                     # str — human-readable description
    section: Optional[str]           # str | None — spec section where the issue was found
    line: Optional[int]              # int | None — line number in spec markdown
    cross_ref_spec: Optional[str]    # str | None — other spec involved (for cross_spec dimension)
    cross_ref_section: Optional[str] # str | None — section in the other spec

@strawberry.type
class ValidationDimension:
    """One of the six validation dimensions. Maps to validation-at-commit.json entries."""
    name: str                    # str — "template" | "structure" | "cross_spec" | "codebase" | "sizing" | "vision"
    status: str                  # str — "pass" | "warn" | "fail" | "pending" | "stale"
    issues: list[ValidationIssue]  # list[ValidationIssue] — issues found in this dimension
    checked_at: Optional[str]    # ISO 8601 | None — when this dimension last ran
    tier: int                    # int — 1 (live, runs on edit) or 2 (on-demand, runs at commit gate)

@strawberry.type
class ValidationState:
    """Aggregate validation across all dimensions. Maps to validation-at-commit.json."""
    dimensions: list[ValidationDimension]  # list[ValidationDimension] — all six dimensions
    pass_count: int                        # int — dimensions with status "pass"
    warn_count: int                        # int — dimensions with status "warn"
    fail_count: int                        # int — dimensions with status "fail"

# ── Spec draft ────────────────────────────────────────────────

@strawberry.type
class SpecDraft:
    """In-progress spec. Maps to specs/{type}/{name}.md on disk."""
    feature_name: str              # str — feature slug
    spec_type: str                 # str — "prd" | "rfc" | "design"
    content: str                   # str — markdown content
    file_path: str                 # str — target path (e.g. "specs/tech/add-timeout.md")
    template_name: str             # str — SPEED template used for generation
    generated_at: Optional[str]    # ISO 8601 | None — when LLM generated the draft (null if manual)
    child_specs: list['SpecDraft'] # list[SpecDraft] — child specs in multi-spec topology

# ── Suggestions ───────────────────────────────────────────────

@strawberry.type
class SuggestionResolution:
    """How a suggestion was resolved by the ceremony author."""
    action: str                    # str — "accept" | "dismiss"
    resolved_by: str               # str — ceremony author name
    resolved_by_email: str         # str — ceremony author email
    resolved_at: str               # ISO 8601
    reason: Optional[str]          # str | None — required for dismiss (min 10 chars)

@strawberry.type
class SuggestionReply:
    """One message in the suggestion thread."""
    id: str                # str — unique reply ID
    author: str            # str — reply author name
    author_email: str      # str — reply author email
    text: str              # str — reply body
    created_at: str        # ISO 8601

@strawberry.type
class Suggestion:
    """Maps to one entry in suggestions.json. See 'Suggestions across revisions' in the state machine section."""
    id: str                            # str — unique suggestion ID
    author: str                        # str — who created the suggestion
    author_email: str                  # str — suggestion author's email
    revision_id: str                   # str — revision the suggestion was created against
    section_id: str                    # str — spec section targeted
    section_title: str                 # str — human-readable section name at creation time
    section_content_hash: str          # str — SHA-256 of section content at creation time
    text: str                          # str — suggestion body (10-2000 chars)
    status: str                        # str — "unresolved" | "accepted" | "dismissed"
    outdated: bool                     # bool — true if section_content_hash != current revision's section hash
    created_at: str                    # ISO 8601
    updated_at: Optional[str]          # ISO 8601 | None — last edit timestamp
    resolution: Optional[SuggestionResolution]  # SuggestionResolution | None
    thread: list[SuggestionReply]      # list[SuggestionReply] — conversation thread

@strawberry.type
class DismissedSummary:
    """Aggregate of dismissed suggestions, used in SuggestionHistory."""
    count: int             # int — number dismissed
    reasons: list[str]     # list[str] — dismiss reasons provided

@strawberry.type
class SuggestionHistory:
    """Snapshot of suggestion stats at commit time. Stored in commit.json."""
    received: int                  # int — total suggestions created
    accepted: int                  # int — suggestions accepted
    dismissed: DismissedSummary    # DismissedSummary — dismissed count + reasons

# ── Commit & ratification ─────────────────────────────────────

@strawberry.type
class CommitRecord:
    """Maps to commit.json. Written by commitSpec at DRAFTING → COMMITTED."""
    feature_name: str                      # str — feature slug
    revision_id: str                       # str — revision that was committed
    author: str                            # str — ceremony author name
    author_email: str                      # str — ceremony author email
    committed_at: str                      # ISO 8601
    validation_state_ref: str              # str — path to validation-at-commit.json
    context_package_ref: str               # str — path to context-package.json
    suggestion_history: SuggestionHistory   # SuggestionHistory — snapshot at commit time
    spec_paths: list[str]                  # list[str] — all committed spec file paths
    is_multiplayer: bool                   # bool — MP_ENABLED at commit time
    ratification_threshold: int            # int — required approvals (0 in SP, auto-ratifies)
    ratification_status: str               # str — "pending" | "ratified" | "rejected"

@strawberry.type
class VerdictEntry:
    """One approver's verdict. Stored as JSONL in .speed/shared/events/."""
    id: str                    # str — unique verdict ID
    revision_id: str           # str — revision this verdict was cast on
    actor: str                 # str — approver name
    actor_email: str           # str — approver email
    verdict: str               # str — "approve" | "reject"
    comment: Optional[str]     # str | None — optional comment
    timestamp: str             # ISO 8601

@strawberry.type
class RatificationState:
    """Live ratification status for a committed revision."""
    feature_name: str                  # str — feature slug
    revision_id: str                   # str — revision being ratified
    status: str                        # str — "pending" | "ratified" | "rejected"
    ratification_count: int            # int — approvals received so far
    threshold: int                     # int — approvals required
    verdicts: list[VerdictEntry]       # list[VerdictEntry] — all verdicts submitted
    is_author: bool                    # bool — whether the current actor is the ceremony author
    has_voted: bool                    # bool — whether the current actor has already voted
```

## Ceremony Path Helpers

Added to `dashboard/backend/paths.py` on `SpeedPaths` class by the [parent RFC](speed-define-ceremony.md).

```python
def ceremony_dir(self, name: str) -> Path
def ceremony_state(self, name: str) -> Path      # ceremony.json
def ceremony_intent(self, name: str) -> Path      # intent.json
def ceremony_context_package(self, name: str) -> Path
def ceremony_suggestions(self, name: str) -> Path
def ceremony_commit_record(self, name: str) -> Path
def ceremony_validation_snapshot(self, name: str) -> Path
```

## Event Types

All use the `spec.*` namespace. Emitted only when `MP_ENABLED == true`, stored as JSONL in `.speed/shared/events/`.

| Event | New/Existing | Emitted when | Emitted by | Data |
|-------|-------------|-------------|------------|------|
| `spec.intent_declared` | New | Author declares intent | [context](speed-define-ceremony-context.md) | `{ feature_name, intent_text }` |
| `spec.validation_completed` | New | Full validation run (Tier 2) | [editor](speed-define-ceremony-editor.md) | `{ feature_name, pass_count, warn_count, fail_count }` |
| `spec.suggestion_created` | New | Contributor creates suggestion | [contributor](speed-define-ceremony-contributor.md) | `{ feature_name, suggestion_id, section_id }` |
| `spec.proposed` | Existing | Author commits in MP | [commit](speed-define-ceremony-commit.md) | `{ spec_path, spec_hash }` |
| `spec.reviewed` | Existing | Approver submits verdict | [commit](speed-define-ceremony-commit.md) | `{ spec_path, verdict, comment }` |
| `spec.ratified` | Existing | Threshold met | [commit](speed-define-ceremony-commit.md) | `{ spec_path, approvals }` |

## API Surface

The dashboard backend serves these GraphQL operations to power the ceremony.

### Queries

| Query | Returns | Implemented in |
|-------|---------|----------------|
| `ceremonyInfo(featureName)` | `CeremonyInfo` | [parent](speed-define-ceremony.md) |
| `contextPackage(featureName)` | `ContextPackage` | [context](speed-define-ceremony-context.md) |
| `contextAssemblyStatus(featureName)` | `AssemblyStatus` | [context](speed-define-ceremony-context.md) |
| `specDraft(featureName)` | `SpecDraft` | [editor](speed-define-ceremony-editor.md) |
| `validationState(featureName)` | `ValidationState` | [editor](speed-define-ceremony-editor.md) |
| `suggestions(featureName)` | `[Suggestion]` | [contributor](speed-define-ceremony-contributor.md) |
| `suggestionHistory(featureName)` | `SuggestionHistory` | [contributor](speed-define-ceremony-contributor.md) |
| `commitRecord(featureName)` | `CommitRecord` | [commit](speed-define-ceremony-commit.md) |
| `ratificationState(featureName)` | `RatificationState` | [commit](speed-define-ceremony-commit.md) |
| `bootstrapStatus` | `BootstrapStatus` | [bootstrap](speed-define-ceremony-bootstrap.md) |
| `derivedConventions` | `[DerivedConvention]` | [bootstrap](speed-define-ceremony-bootstrap.md) |
| `visionDraft` | `VisionDraft` | [bootstrap](speed-define-ceremony-bootstrap.md) |

### Mutations

| Mutation | Action | Implemented in |
|----------|--------|----------------|
| `declareIntent(text)` | Creates ceremony, assembles context | [context](speed-define-ceremony-context.md) |
| `refineIntent(featureName, text)` | Re-scopes and re-assembles context | [context](speed-define-ceremony-context.md) |
| `generateDraft(featureName, specType)` | LLM generates spec from intent + context | [editor](speed-define-ceremony-editor.md) |
| `updateDraft(featureName, content)` | Saves author edits | [editor](speed-define-ceremony-editor.md) |
| `validateDraft(featureName)` | Runs all 6 validation dimensions | [editor](speed-define-ceremony-editor.md) |
| `generateChildRfcs(featureName, decomposition)` | Generates child specs for multi-spec topology | [editor](speed-define-ceremony-editor.md) |
| `createSuggestion(featureName, sectionId, text)` | Contributor adds suggestion | [contributor](speed-define-ceremony-contributor.md) |
| `editSuggestion(id, text)` | Contributor edits own suggestion | [contributor](speed-define-ceremony-contributor.md) |
| `deleteSuggestion(id)` | Contributor deletes own suggestion | [contributor](speed-define-ceremony-contributor.md) |
| `resolveSuggestion(id, action, reason)` | Author accepts/dismisses | [contributor](speed-define-ceremony-contributor.md) |
| `replySuggestion(id, text)` | Author or contributor replies | [contributor](speed-define-ceremony-contributor.md) |
| `commitSpec(featureName)` | Git commits spec files, writes artifacts, unblocks plan (SP) or triggers ratification (MP) | [commit](speed-define-ceremony-commit.md) |
| `submitRatification(featureName, verdict, comment)` | Approver submits verdict | [commit](speed-define-ceremony-commit.md) |
| `startGraphBuild` | Triggers semantic graph build | [bootstrap](speed-define-ceremony-bootstrap.md) |
| `generateVision` | LLM generates vision draft | [bootstrap](speed-define-ceremony-bootstrap.md) |
| `regenerateVision` | Re-generates vision draft | [bootstrap](speed-define-ceremony-bootstrap.md) |
| `commitVision(content)` | Writes vision to overview.md | [bootstrap](speed-define-ceremony-bootstrap.md) |
| `extractConventions` | Runs convention extractors | [bootstrap](speed-define-ceremony-bootstrap.md) |
| `resolveConvention(id, action)` | Accept/reject derived convention | [bootstrap](speed-define-ceremony-bootstrap.md) |
| `acceptAllConventions` | Bulk accept | [bootstrap](speed-define-ceremony-bootstrap.md) |
| `commitConventions(personaInputs)` | Writes persona conventions | [bootstrap](speed-define-ceremony-bootstrap.md) |
| `completeBootstrap` | Finalizes bootstrap | [bootstrap](speed-define-ceremony-bootstrap.md) |

## Validation Rules

Rules enforced across the ceremony. Individual child specs add their own rules on top.

| Rule | Enforced by | Error |
|------|------------|-------|
| State transitions must follow the state machine | [parent](speed-define-ceremony.md) `ceremony_types.py` | "Cannot transition from {current} to {target}" |
| Feature name unique across active ceremonies | [context](speed-define-ceremony-context.md) `declareIntent` | "Feature '{name}' has an active ceremony owned by {author}" |
| Feature name not occupied on disk | [context](speed-define-ceremony-context.md) `declareIntent` | "Feature '{name}' already has artifacts on disk at {path}. Use a different name or clean up the previous ceremony's artifacts." |
| Feature name: lowercase, hyphens, max 50 chars | [context](speed-define-ceremony-context.md) `declareIntent` | "Feature name must be lowercase alphanumeric with hyphens, max 50 chars" |
| Only ceremony author can: edit draft, resolve suggestions, commit | [parent](speed-define-ceremony.md) `assert_ceremony_author()` | "Only the ceremony author ({author}) can perform this action" |
| Only non-authors can: create suggestions, submit ratifications | [parent](speed-define-ceremony.md) `assert_not_ceremony_author()` | "Cannot perform this action on your own ceremony" |
| Spec target paths must be unoccupied or owned by this ceremony | [commit](speed-define-ceremony-commit.md) `commitSpec` | "Spec path {path} already exists and is not owned by ceremony '{name}'" |
| Template conformance required for commit | [commit](speed-define-ceremony-commit.md) `commitSpec` | "Spec does not conform to {template}: missing: {list}" |
| Each approver submits one verdict | [commit](speed-define-ceremony-commit.md) `submitRatification` | "You have already submitted a verdict" |
| Ceremony must be in correct state for action | Per-mutation state check | "Action requires {required_state}, currently in {current_state}" |
| Intent text minimum 5 characters | [context](speed-define-ceremony-context.md) `declareIntent` | "Intent must be at least 5 characters" |
| Dismiss reason minimum 10 characters | [contributor](speed-define-ceremony-contributor.md) `resolveSuggestion` | "Dismiss reason must be at least 10 characters" |
| Suggestion text 10-2000 characters | [contributor](speed-define-ceremony-contributor.md) `createSuggestion` | "Suggestion must be between 10 and 2000 characters" |
| Child spec paths must not collide with existing specs | [editor](speed-define-ceremony-editor.md) `generateChildRfcs` | "Child spec path {path} conflicts with existing spec from ceremony '{other_name}'" |

## Ownership Model

Identity resolved by `get_current_actor()`, which follows `lib/actor.sh`'s resolution chain and never fails:

- **Name**: `$SPEED_ACTOR` env → `git config user.name` → `whoami`
- **Email**: `$SPEED_ACTOR_EMAIL` env → `git config user.email` → `{name}@local`

The function always returns a `(name, email)` tuple. Environments without git (CI runners, containers, fresh installs) fall back to the OS username and a synthetic email. Ownership checks still work because the same fallback is used consistently within and across requests.

| Action | Who can do it | Enforced by |
|--------|--------------|-------------|
| Declare intent (creates ceremony) | Any actor | [context](speed-define-ceremony-context.md) |
| Refine intent | Author only | `assert_ceremony_author()` |
| Edit spec draft | Author only | `assert_ceremony_author()` |
| Create suggestion | Non-authors only | `assert_not_ceremony_author()` |
| Edit/delete suggestion | Suggestion author, before resolution | [contributor](speed-define-ceremony-contributor.md) |
| Resolve suggestion | Ceremony author only | `assert_ceremony_author()` |
| Commit spec | Author only | `assert_ceremony_author()` |
| Submit ratification | Non-authors, one per actor. **Exception:** author can self-ratify when they are the sole actor on the roster. | `assert_not_ceremony_author()` + duplicate check. Solo-actor exemption checked by [commit](speed-define-ceremony-commit.md) before calling the assert. |

## Route Structure

| Route | Page file | Purpose |
|-------|-----------|---------|
| `/define` | existing | Portfolio mode (three-column grid), unchanged |
| `/define/new` | `app/define/new/page.tsx` | Intent input (or bootstrap wizard on cold start) |
| `/define/:feature` | `app/define/[feature]/page.tsx` | Ceremony editor: context + editor + suggestions + commit bar |
| `/define/:feature/review` | `app/define/[feature]/review/page.tsx` | Ratification view (MP only) |

## RFC Family

| Spec | Stories | What it builds |
|------|---------|----------------|
| [identity](speed-define-ceremony-identity.md) | — | Email-based actor identity: `actor_email_resolve()` in actor.sh, `actor_email` in event payloads, email-based ownership matching in ownership.sh and server.py. Prerequisite for all other RFCs. |
| [parent](speed-define-ceremony.md) | — | Ceremony state machine, shared types, path helpers, ownership helpers, `ceremonyInfo` query, route scaffolds |
| [context](speed-define-ceremony-context.md) | S1, S2, S13 | Intent declaration, context package assembly, IntelPanel ceremony mode, historical context viewing |
| [editor](speed-define-ceremony-editor.md) | S3, S4, S6, S10 | CeremonyLayout, LLM draft generation, two-tier validation, cross-spec flags, multi-spec topology |
| [contributor](speed-define-ceremony-contributor.md) | S7, S8 | Suggestion CRUD, SuggestionComposer, ContributorBanner, DismissReasonDialog |
| [commit](speed-define-ceremony-commit.md) | S5, S9 | CommitBar, CommitDialog, git commit of spec files, ratification flow, RatificationView |
| [bootstrap](speed-define-ceremony-bootstrap.md) | S11, S12 | Cold start detection, BootstrapWizard, VisionDraftEditor, ConventionReview |

## Resolved Questions

| Question | Decision | Rationale |
|----------|----------|-----------|
| What happens when ratification threshold is 1 and the author is the only actor in MP mode? | **Solo actors can self-ratify.** When the roster (`.speed/shared/roster/`) has exactly one actor and that actor is the ceremony author, the [commit RFC](speed-define-ceremony-commit.md)'s `submitRatification` skips `assert_not_ceremony_author` and allows the author to ratify their own spec. The exemption is scoped to ratification only; `createSuggestion` still requires a non-author regardless of roster size. | A solo developer who runs `speed mp-init` shouldn't be deadlocked in COMMITTED. Option (a) (treat it as misconfiguration) punishes a valid workflow. Option (b) (threshold 0) weakens ratification for all MP teams. Option (c) (roster-based exemption) is narrowly scoped and preserves the non-self-ratification rule for teams of 2+. |
