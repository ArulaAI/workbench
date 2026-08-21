# RFC: The Define Ceremony

> See [product spec](../product/speed-define-ceremony.md) for product context.
> See [foundation reference](speed-define-ceremony-foundation.md) for shared types, full API surface, artifact flow, validation rules, and event types.

This RFC builds the shared infrastructure that all child specs depend on: ceremony state machine, Strawberry type definitions, path helpers, ownership enforcement, route scaffolds, and the `ceremonyInfo` query.

## PRD & Design Traceability

**User Stories**: This RFC does not own any PRD user stories directly. It provides the foundation (shared types, state machine, ownership enforcement, path helpers, route scaffolds) that all five child RFCs depend on. Every user story (S1-S12) passes through infrastructure defined here.

**User Flows**: All ceremony flows depend on the state machine defined in this RFC (see [State Machine](#state-machine)).

**Success Criteria**: Ceremony state transitions are enforced and auditable; ownership is verified on every protected mutation; all 23 shared types are importable by child spec resolvers; route scaffolds render without error.

**Design Components**: CeremonyLayout (`ceremony/CeremonyLayout.tsx`) depends on the route scaffolds this RFC creates. No ceremony-specific components are built here; child RFCs fill in the page content.

**Design Regions**: This RFC creates the empty page shells for: intent-input (`/define/new`), editor-area (`/define/:feature`), and ratification view (`/define/:feature/review`).

**Design Routes**: `/define/new` (route scaffold), `/define/:feature` (route scaffold), `/define/:feature/review` (route scaffold). All three are minimal page components with layout shell, loading state, and error boundary. Child RFCs add content.

## Basic Example

This RFC is shared infrastructure, not a user-facing feature. It delivers types, a state machine, helpers, and one read query. A traditional "here's what it looks like to use the feature" example doesn't apply cleanly because the five child RFCs are the actual consumers.

What this RFC produces, at a glance:

```python
# ceremony_types.py — the module every child RFC imports from
CeremonyStatus          # enum: 5 states
RevisionSummary         # Strawberry type for one node in the revision chain
CeremonyInfo            # Strawberry type returned by the ceremonyInfo query
transition_ceremony_state(feature_name, target)            # within-revision state machine
create_revision(feature_name, reason)                      # cross-revision advancement
assert_ceremony_author(state, actor_email)                 # ownership gate
assert_not_ceremony_author(state, actor_email)             # inverse gate
get_current_actor()     # (name, email) — never raises, falls back to whoami/synthetic
_read_json(path)        # safe JSON reader (None on error)
get_ceremony_info(project_root, feature_name)              # ceremonyInfo resolver
```

Plus 7 path helpers on `SpeedPaths` (see [Interface Contract](#produces-for-downstream-rfcs)) and 3 route scaffolds (see [API Surface](#route-scaffolds)).

The `ceremonyInfo` query is the one GraphQL operation this RFC implements. It reads `ceremony.json` and returns it:

```graphql
query CeremonyInfo($featureName: String!) {
  ceremonyInfo(featureName: $featureName) {
    featureName
    currentRevision {
      revisionId
      parentId
      status
      specContentHash
      contextPackageHash
      validationHash
      createdAt
      reason
    }
    revisionCount
    author
    authorEmail
    createdAt
    isMultiplayer
  }
}
```

## Interface Contract

### Consumes (from prerequisite RFCs)

From [foundation reference](speed-define-ceremony-foundation.md):
- 23 shared Strawberry definitions (22 `@strawberry.type` + 1 `@strawberry.enum`) with field names, types, and nullability. This RFC implements all 23 in `ceremony_types.py`.
- The ceremony state machine specification (5 states, 4 within-revision transitions, 3 terminal states) that this RFC implements as `VALID_TRANSITIONS`, `transition_ceremony_state()`, and `create_revision()`
- 7 ceremony path helpers that this RFC adds to `SpeedPaths`. These define where ceremony artifacts live on disk; the artifacts themselves are produced and consumed by child RFCs per the foundation's [Artifact Flow table](speed-define-ceremony-foundation.md#artifact-flow).
- The `ceremonyInfo` query specification from the foundation's [API Surface table](speed-define-ceremony-foundation.md#api-surface) (1 of 12 queries; the other 11 belong to child RFCs). This RFC implements `ceremonyInfo`; it implements no mutations (all 22 mutations belong to child RFCs).
- The [route structure](speed-define-ceremony-foundation.md#route-structure): 3 new routes this RFC scaffolds as page files, plus 1 existing route (`/define`) left unchanged.
- [Validation rules](speed-define-ceremony-foundation.md#validation-rules) for state transitions and ownership enforcement (3 of 11 rules). The remaining 8 rules are enforced by child RFCs.
- The [ownership model](speed-define-ceremony-foundation.md#ownership-model): this RFC implements the two helper functions (`assert_ceremony_author()` and `assert_not_ceremony_author()`) that enforce 6 of 8 actions. The remaining 2 actions (edit/delete own suggestion, declare intent) have child-RFC-specific enforcement or no ownership gate.
- The [event type catalog](speed-define-ceremony-foundation.md#event-types): 6 events in the `spec.*` namespace. This RFC emits none of them; all 6 are emitted by child RFCs. Listed here because the foundation defines the shared contract, and implementers of this RFC should be aware of the event namespace even though the parent doesn't participate in it.

The foundation reference is not a plannable spec. It defines no tasks. It is the shared contract that all six ceremony RFCs (this parent + five children) implement from. Each RFC references the foundation directly for its own responsibilities. The parent RFC's role is to build the shared module (`ceremony_types.py`) and infrastructure (path helpers, route scaffolds) that the foundation specifies; child RFCs consume both the foundation (for their own API surface, events, and validation rules) and the parent's outputs (for shared types and helpers).

From [identity RFC](speed-define-ceremony-identity.md) (must be built first):
- `actor_email_get()` in `lib/actor.sh` for email resolution
- `actor_email` field in event payloads (emitted by `lib/events.sh`)
- Email-based ownership matching in `lib/ownership.sh` and `lib/serve/server.py`

External dependencies consumed:

- `SpeedPaths` class and `get_paths()` factory from `dashboard/backend/paths.py` (existing). This RFC adds 7 methods to `SpeedPaths`. The existing `feature_shared(name)` method returns the feature directory; ceremony paths are nested under it (e.g., `ceremony_state` returns `feature_shared(name) / "ceremony.json"`).
- Strawberry schema (`Query` class) from `dashboard/backend/schema.py` (existing). This RFC adds one `@strawberry.field` method: `ceremony_info`.
- Next.js 15 app router from `dashboard/frontend/app/` (existing, for route scaffold page files)

### Produces (for downstream RFCs)

**Which child RFCs consume what:**

| Export | Context | Editor | Contributor | Commit | Bootstrap |
|--------|---------|--------|-------------|--------|-----------|
| `CeremonyStatus` | yes | yes | yes | yes | yes |
| `RevisionSummary` | no | GQL | GQL | yes | no |
| `CeremonyInfo` | yes | GQL | GQL | yes | no |
| `transition_ceremony_state()` | no | no | no | yes | no |
| `create_revision()` | yes | no | no | yes | yes |
| `assert_ceremony_author()` | yes | yes | yes | yes | no |
| `assert_not_ceremony_author()` | no | no | yes | yes | no |
| `get_current_actor()` | yes | yes | yes | yes | no |
| `get_ceremony_info()` | no | no | no | no | no |
| Path helpers | yes | yes | yes | yes | yes |
| TypeScript types | yes | yes | yes | yes | yes |

"GQL" means the child RFC consumes `CeremonyInfo` via the `ceremonyInfo` GraphQL query from the frontend, not as a Python import in its resolver. `CeremonyState`, `Revision`, and `ReflogEntry` (the on-disk dataclasses from the Data Model) are also importable by child RFCs that call `transition_ceremony_state()` or `create_revision()`, since those functions return ceremony state objects. They are not listed as separate rows because they are always consumed through those functions, not independently. Editor and Contributor frontends query ceremony state to determine author/contributor mode; their backend resolvers read `ceremony.json` as a dict via the path helpers instead.

This matrix is derived from what each child RFC needs based on its behavior (ownership checks, state transitions, identity resolution), not from what each child RFC explicitly declares in its Consumes section. Most child RFCs list only sibling dependencies in their Consumes and reference the parent via the `Depends on:` header. The parent's exports are implicit infrastructure.

[Context RFC](speed-define-ceremony-context.md) uses `create_revision` to create the initial ceremony at DRAFTING. [Commit RFC](speed-define-ceremony-commit.md) uses `transition_ceremony_state` to transition DRAFTING -> COMMITTED and COMMITTED -> RATIFIED/REJECTED. Commit RFC uses `create_revision` to start a new revision after RATIFIED or REJECTED. [Bootstrap RFC](speed-define-ceremony-bootstrap.md) transitions its precondition state independently (bootstrap is not a ceremony state). [Editor](speed-define-ceremony-editor.md) and [Contributor](speed-define-ceremony-contributor.md) RFCs read ceremony state but don't transition it.

`get_ceremony_info()` is the resolver behind the `ceremonyInfo` GraphQL query. No child RFC calls it directly in Python; they either query it via GraphQL from the frontend or read `ceremony.json` via path helpers in their own resolvers.

**Python exports** from `dashboard/backend/resolvers/ceremony_types.py`:

```python
# -- Enum --
class CeremonyStatus(enum.Enum):
    DRAFTING = "drafting"
    COMMITTED = "committed"
    RATIFIED = "ratified"
    REJECTED = "rejected"
    ABANDONED = "abandoned"

# -- Strawberry types (GraphQL query return) --
class RevisionSummary:
    revision_id: str
    parent_id: str | None
    status: CeremonyStatus
    spec_content_hash: str
    context_package_hash: str
    validation_hash: str
    created_at: str
    reason: str | None

class CeremonyInfo:
    feature_name: str
    current_revision: RevisionSummary
    revision_count: int
    author: str
    author_email: str
    created_at: str
    is_multiplayer: bool

# -- State machine (within-revision) --
def transition_ceremony_state(
    feature_name: str,
    target: CeremonyStatus,
) -> CeremonyStatus:
    """Validate and execute a within-revision state transition.
    Resolves paths internally via get_paths().
    Side effect: writes updated ceremony.json to disk.
    Returns: the new CeremonyStatus.
    Raises: ValueError on invalid transition.
    Raises: FileNotFoundError if ceremony.json doesn't exist."""

# -- State machine (cross-revision) --
def create_revision(
    feature_name: str,
    reason: str,
) -> Revision:
    """Create a new revision at DRAFTING and advance the ceremony ref.
    Preconditions: caller is ceremony author; current revision is terminal or none.
    Steps:
    1. Snapshot current spec, context, and validation hashes
    2. Compute revision_id from hashes + parent ID
    3. Write revision entry to ceremony.json with status: DRAFTING
    4. Compare section hashes; mark suggestions on changed sections as outdated
    5. Append reflog entry recording the ref movement
    6. Set current_revision to the new revision_id
    7. Increment revision_count
    Returns: the new Revision.
    Raises: PermissionError if caller is not the ceremony author.
    Raises: ValueError if current revision is not in a terminal state."""

# -- Ownership enforcement --
def assert_ceremony_author(ceremony: CeremonyState, actor_email: str) -> None:
    """Raise PermissionError if actor_email != ceremony.author_email."""

def assert_not_ceremony_author(ceremony: CeremonyState, actor_email: str) -> None:
    """Raise PermissionError if actor_email == ceremony.author_email."""

def get_current_actor() -> tuple[str, str]:
    """Returns (name, email). Never raises.
    Calls actor_get() for name and actor_email_get() for email
    (both from lib/actor.sh, email resolution added by identity RFC).
    Cached per GraphQL request."""

# -- Query resolver --
def get_ceremony_info(project_root: Path, feature_name: str) -> CeremonyInfo | None:
    """Read ceremony.json, return as CeremonyInfo Strawberry type.
    Dereferences current_revision into revisions map to build RevisionSummary.
    Returns None if ceremony.json doesn't exist.
    Returns error (not None) if ceremony.json exists but is malformed.
    Called by schema.py's ceremony_info field, not by child RFCs directly."""
```

`_read_json` is not a shared export. Each resolver module defines its own private copy, following the existing codebase convention (`define.py`, `landing.py`, `mission_control.py`, `process_status.py` each have their own).

**Path helpers** added to `SpeedPaths` in `dashboard/backend/paths.py`:

```python
# All delegate to feature_shared(name), which returns:
#   MP: .speed/shared/features/{name}/
#   SP: .speed/features/{name}/
# In SP, feature_shared and feature_local resolve to the same directory.
# Ceremony artifacts are shared state (visible to all actors in MP),
# so feature_shared is the correct base in both modes.
def ceremony_dir(self, name: str) -> Path                 # the feature directory itself
def ceremony_state(self, name: str) -> Path               # ceremony.json
def ceremony_intent(self, name: str) -> Path              # intent.json
def ceremony_context_package(self, name: str) -> Path     # context-package.json
def ceremony_suggestions(self, name: str) -> Path         # suggestions.json
def ceremony_commit_record(self, name: str) -> Path       # commit.json
def ceremony_validation_snapshot(self, name: str) -> Path # validation-at-commit.json
```

**Frontend TypeScript types** exported from `dashboard/frontend/lib/graphql/queries/ceremony.ts`:

```typescript
import { gql } from "urql"

export type CeremonyStatus =
  | "DRAFTING" | "COMMITTED"
  | "RATIFIED" | "REJECTED" | "ABANDONED"

export type RevisionSummary = {
  revisionId: string
  parentId: string | null
  status: CeremonyStatus
  specContentHash: string
  contextPackageHash: string
  validationHash: string
  createdAt: string
  reason: string | null
}

export type CeremonyInfo = {
  featureName: string
  currentRevision: RevisionSummary
  revisionCount: number
  author: string
  authorEmail: string
  createdAt: string
  isMultiplayer: boolean
}

export const CEREMONY_INFO_QUERY = gql`
  query CeremonyInfo($featureName: String!) {
    ceremonyInfo(featureName: $featureName) {
      featureName
      currentRevision {
        revisionId
        parentId
        status
        specContentHash
        contextPackageHash
        validationHash
        createdAt
        reason
      }
      revisionCount
      author
      authorEmail
      createdAt
      isMultiplayer
    }
  }
`
```

**Route scaffolds** (page files, not components — child RFCs add content):

| Route | File | Child RFC that fills it |
|-------|------|----------------------|
| `/define/new` | `app/define/new/page.tsx` | Context (IntentInput), Bootstrap (BootstrapWizard) |
| `/define/:feature` | `app/define/[feature]/page.tsx` | Editor (CeremonyLayout) |
| `/define/:feature/review` | `app/define/[feature]/review/page.tsx` | Commit (RatificationView) |

## Data Model

### `ceremony.json` -- Ceremony State File

Persisted at `SpeedPaths.ceremony_state(feature_name)`, which resolves to `.speed/features/{feature}/ceremony.json` in SP and `.speed/shared/features/{feature}/ceremony.json` in MP. Created by [context RFC](speed-define-ceremony-context.md) on `declareIntent`, updated by `transition_ceremony_state` and `create_revision`. The `ceremonyInfo` query reads this file.

To read the current state: dereference `current_revision` into the `revisions` map. `revisions[current_revision].status` is the ceremony's active lifecycle state.

For the full ceremony.json specification, Revision dataclass, ReflogEntry dataclass, and content-addressed revision identity computation, see [foundation reference](speed-define-ceremony-foundation.md#ceremonyjson).

#### Python definition

**Serialization note:** `CeremonyStatus` stores lowercase enum values on disk (`"drafting"`, `"committed"`, etc.). Strawberry serializes enum names as uppercase in GraphQL (`"DRAFTING"`, `"COMMITTED"`). The TypeScript types use the uppercase GraphQL form. The JSON Schema uses the lowercase on-disk form.

```python
@dataclass
class Revision:
    """Immutable snapshot. Once a revision reaches a terminal state, its fields are frozen."""
    revision_id: str            # SHA-256 content hash (see [foundation](speed-define-ceremony-foundation.md#ceremony-state-machine) for computation)
    parent_id: str | None       # previous revision's hash (null for first)
    status: CeremonyStatus      # current lifecycle state
    spec_content_hash: str      # SHA-256 of spec markdown
    context_package_hash: str   # SHA-256 of context-package.json
    validation_hash: str        # SHA-256 of validation results
    created_at: str             # ISO 8601
    reason: str | None          # why this revision exists (null for first)

@dataclass
class ReflogEntry:
    """Records one ref movement. Append-only list in ceremony.json."""
    from_revision: str | None   # previous revision ID (null for first)
    to_revision: str            # new revision ID
    at: str                     # ISO 8601
    actor: str                  # who created the revision
    actor_email: str            # resolved by get_current_actor()
    reason: str                 # "initial commit", "addressed rejection: ...", etc.

@dataclass
class CeremonyState:
    """On-disk schema for ceremony.json. One file per feature."""
    feature_name: str         # Slugified from intent. Lowercase, hyphens, max 50 chars.
    author: str               # Resolved name from get_current_actor().
    author_email: str         # Resolved email from get_current_actor(). May be {name}@local.
    created_at: str           # ISO 8601 timestamp. Set once at creation, never updated.
    is_multiplayer: bool      # Whether .speed/shared/ existed at creation. Immutable.
    current_revision: str     # revision_id of the active revision.
    revision_count: int       # Total revisions created.
    revisions: dict[str, Revision]  # Keyed by revision_id. Every revision ever created, frozen.
    reflog: list[ReflogEntry] # Append-only log of ref movements.
```

#### JSON Schema

See [foundation reference](speed-define-ceremony-foundation.md#ceremonyjson) for the full JSON Schema. Key constraints:

- `feature_name`: `^[a-z0-9][a-z0-9-]*$`, max 50 chars
- `current_revision`: must match a key in `revisions`
- `revisions`: map of revision objects, each with `revision_id`, `parent_id`, `status`, content hashes, `created_at`, `reason`
- `reflog`: append-only array of ref movement entries
- `status` values in revisions: `"drafting"`, `"committed"`, `"ratified"`, `"rejected"`, `"abandoned"`

#### Example

```json
{
  "feature_name": "sort-auth-by-last-activity",
  "author": "Jane Doe",
  "author_email": "jane@example.com",
  "created_at": "2026-03-29T10:00:00Z",
  "is_multiplayer": false,
  "current_revision": "a3f8c012",
  "revision_count": 1,
  "revisions": {
    "a3f8c012": {
      "revision_id": "a3f8c012",
      "parent_id": null,
      "status": "drafting",
      "spec_content_hash": "e5b7a1...",
      "context_package_hash": "c9d2f3...",
      "validation_hash": "0000000...",
      "created_at": "2026-03-29T10:00:00Z",
      "reason": null
    }
  },
  "reflog": [
    {
      "from_revision": null,
      "to_revision": "a3f8c012",
      "at": "2026-03-29T10:00:00Z",
      "actor": "Jane Doe",
      "actor_email": "jane@example.com",
      "reason": "initial commit"
    }
  ]
}
```

### Shared Strawberry Types

All 23 types live in `dashboard/backend/resolvers/ceremony_types.py`. Full type definitions with every field, type annotation, and nullability constraint are in [foundation reference](speed-define-ceremony-foundation.md#shared-strawberry-types).

Types grouped by domain:

| Group | Types | Consumed by |
|-------|-------|-------------|
| Ceremony lifecycle | `CeremonyStatus` (enum), `RevisionSummary`, `CeremonyInfo` | All child RFCs |
| Intent | `Intent` | Context RFC |
| Context package | `CodebaseItem`, `LearningItem`, `DefectItem`, `KnowledgeItem`, `RelatedFeature`, `AuditHistoryItem`, `ContextPackage` | Context, Editor, Contributor, Commit RFCs |
| Validation | `ValidationIssue`, `ValidationDimension`, `ValidationState` | Editor, Commit RFCs |
| Spec draft | `SpecDraft` | Editor, Contributor, Commit RFCs |
| Suggestions | `SuggestionResolution`, `SuggestionReply`, `Suggestion`, `DismissedSummary`, `SuggestionHistory` | Contributor, Commit RFCs |
| Commit & ratification | `CommitRecord`, `VerdictEntry`, `RatificationState` | Commit RFC |

Each child RFC imports only the types it needs. No child RFC defines its own Strawberry types for these 23 shared concerns; all definitions are centralized here.

## State Machine

Five states. Two operations modify ceremony state: `transition_ceremony_state` (within a revision) and `create_revision` (across revisions). For the full state machine specification, workflow diagrams (SP and MP), multi-revision examples, gates, and downstream behavior, see [foundation reference](speed-define-ceremony-foundation.md#ceremony-state-machine).

Bootstrap is a precondition, not a state. The `/define/new` route checks `bootstrapStatus` and renders `BootstrapWizard` or `IntentInput`. The state machine starts at `DRAFTING` after bootstrap is satisfied.

### Within-revision transitions

```
drafting ─────────> committed     (author commits, validation gate passes)
drafting ─────────> abandoned     (author releases)
committed ────────> ratified      (SP: auto-ratifies; MP: approval threshold met)
committed ────────> rejected      (MP: any approver rejects)

Terminal states: ratified, rejected, abandoned
```

```python
VALID_TRANSITIONS: dict[CeremonyStatus, list[CeremonyStatus]] = {
    CeremonyStatus.DRAFTING:   [CeremonyStatus.COMMITTED, CeremonyStatus.ABANDONED],
    CeremonyStatus.COMMITTED:  [CeremonyStatus.RATIFIED, CeremonyStatus.REJECTED],
    CeremonyStatus.RATIFIED:   [],  # terminal
    CeremonyStatus.REJECTED:   [],  # terminal
    CeremonyStatus.ABANDONED:  [],  # terminal
}
```

### Cross-revision transitions

Returning to DRAFTING after a terminal state is a cross-revision operation, not a within-revision transition. `create_revision` freezes the current revision at its terminal state and creates a new revision at DRAFTING.

```
RATIFIED  [Rev N] ──> DRAFTING [Rev N+1]   (post-ratification changes needed)
REJECTED  [Rev N] ──> DRAFTING [Rev N+1]   (author addresses rejection)
ABANDONED [Rev N] ──> DRAFTING [Rev N+1]   (within grace period, default 90 days)
```

### SP and MP behavior

SP and MP follow the same state path. The difference is how COMMITTED resolves:

- **SP**: `commitSpec` auto-transitions to RATIFIED immediately after COMMITTED. The author's commit is sufficient ratification.
- **MP**: The ceremony sits in COMMITTED while approvers call `submitRatification`. Each verdict is appended to the event log. A single rejection transitions to REJECTED. When the approval threshold is met, `transition_ceremony_state` fires with target RATIFIED.

RATIFIED is the plan-unblocking state in both modes.

### Operations

```python
def transition_ceremony_state(
    feature_name: str,
    target: CeremonyStatus,
) -> CeremonyStatus:
    """Move the current revision to target. Returns the new status.

    1. Resolve paths via get_paths() internally
    2. Read ceremony.json
    3. Dereference current_revision to get active revision status
    4. Check target is in VALID_TRANSITIONS[current_status]
    5. Update revision status in revisions map
    6. Write updated ceremony.json to disk
    7. Return new CeremonyStatus

    Raises ValueError if transition is invalid.
    Raises FileNotFoundError if ceremony.json doesn't exist.
    """

def create_revision(
    feature_name: str,
    reason: str,
) -> Revision:
    """Create a new revision at DRAFTING and advance the ceremony ref.

    Preconditions:
    - Caller is ceremony author
    - No current revision, or current revision is in a terminal state

    Steps:
    1. Snapshot current spec, context, and validation hashes
    2. Compute revision_id from hashes + parent ID (see [foundation](speed-define-ceremony-foundation.md#ceremony-state-machine) for hash computation)
    3. Write revision entry to ceremony.json with status: DRAFTING
    4. Compare section hashes between old and new revision;
       mark suggestions on changed sections as outdated
    5. Append reflog entry recording the ref movement
    6. Set current_revision to the new revision_id
    7. Increment revision_count

    Raises PermissionError if caller is not the ceremony author.
    Raises ValueError if current revision is not in a terminal state.
    """
```

### Hooks

The ceremony state machine fires lifecycle hooks at key points. For the full hook catalog (11 hooks, gate vs. notify types, and firing conditions), see [foundation reference](speed-define-ceremony-foundation.md#hooks).

### Suggestions across revisions

Suggestions are per-ceremony, not per-revision. When `create_revision` runs, suggestions on sections whose content hash changed are marked `outdated`. For the full suggestion data model and outdated-marking rules, see [foundation reference](speed-define-ceremony-foundation.md#suggestions-across-revisions).

## API Surface

### Query: `ceremonyInfo(featureName: String!): CeremonyInfo`

Reads `.speed/features/{feature}/ceremony.json` and returns `CeremonyInfo`.

**Input:**

| Parameter | Type | Constraints |
|-----------|------|-------------|
| featureName | String! | Non-empty. Must match an existing feature directory. |

**Returns:** `CeremonyInfo` or null.

**Null cases:**
- Feature directory doesn't exist (no ceremony or SPEED feature with that name)
- Feature directory exists (from a prior `speed run`) but has no `ceremony.json` (feature was created outside the ceremony flow)

**Error cases:**

| Condition | Error | Message |
|-----------|-------|---------|
| `featureName` is empty string | Validation error | "featureName must not be empty" |
| `ceremony.json` exists but is malformed JSON | Parse error | "ceremony.json for '{feature}' is malformed: {parse error}" |
| `ceremony.json` exists but missing required fields | Schema error | "ceremony.json for '{feature}' is missing required field: {field}" |
| `ceremony.json` has invalid status value | Schema error | "Invalid ceremony status '{value}' for '{feature}'" |

### Ownership Helpers

Python functions exported from `ceremony_types.py`. Not GraphQL operations. Called by every child spec resolver before protected mutations.

#### `assert_ceremony_author(ceremony: CeremonyState, actor_email: str) -> None`

Compares `actor_email` against `ceremony.author_email`. Raises `PermissionError` on mismatch.

**Called by:** [Context RFC](speed-define-ceremony-context.md) (`refineIntent`), [Editor RFC](speed-define-ceremony-editor.md) (`updateDraft`, `generateDraft`), [Contributor RFC](speed-define-ceremony-contributor.md) (`resolveSuggestion`), [Commit RFC](speed-define-ceremony-commit.md) (`commitSpec`).

**Error:** `PermissionError("Only the ceremony author ({author}) can perform this action")`

#### `assert_not_ceremony_author(ceremony: CeremonyState, actor_email: str) -> None`

Inverse check. Raises `PermissionError` when the actor IS the ceremony author.

**Called by:** [Contributor RFC](speed-define-ceremony-contributor.md) (`createSuggestion`), [Commit RFC](speed-define-ceremony-commit.md) (`submitRatification`).

**Error:** `PermissionError("Cannot perform this action on your own ceremony")`

**Solo-actor exemption for ratification:** When the author is the only actor on the MP roster, `submitRatification` in the [Commit RFC](speed-define-ceremony-commit.md) skips the `assert_not_ceremony_author` check and allows self-ratification. The exemption applies only to ratification, not to suggestions (you cannot suggest on your own spec regardless of roster size). The Commit RFC reads `.speed/shared/roster/` to determine roster size.

#### `get_current_actor() -> tuple[str, str]`

Returns `(name, email)`. Never raises. Wraps `actor_get()` (name) and `actor_email_get()` (email) from `lib/actor.sh`. The email resolution chain is added by the [identity RFC](speed-define-ceremony-identity.md). See that RFC for the full resolution chain, fallback behavior, and edge cases.

**Caching:** Result is cached per GraphQL request (read once at the start of resolution).

### Route Scaffolds

Three new Next.js 15 app router page files. Each is a minimal page component that provides the layout shell, loading state, and error boundary. Child RFCs add content to these pages.

#### `/define/new` (`app/define/new/page.tsx`)

**Renders:** Centered content area (max 720px). On first load, checks `bootstrapStatus` query. If bootstrap is needed, renders the [Bootstrap RFC](speed-define-ceremony-bootstrap.md)'s `BootstrapWizard`. Otherwise, renders the [Context RFC](speed-define-ceremony-context.md)'s `IntentInput`.

**Loading state:** Skeleton placeholder (opacity fade, not pulse per design spec) while `bootstrapStatus` resolves.

**Error boundary:** Catches render errors from child components. Shows error message with retry button.

**Props received by child content:** `featureName` (null until intent is declared).

#### `/define/:feature` (`app/define/[feature]/page.tsx`)

**Renders:** Full ceremony editor layout. The `CeremonyLayout` component (from [Editor RFC](speed-define-ceremony-editor.md)) fills this page.

**Loading state:** Skeleton for the three-panel layout while `ceremonyInfo` and `contextPackage` queries resolve.

**Error boundary:** Feature not found shows "No ceremony found for '{feature}'" with link back to `/define`.

**Dynamic segment validation:** `[feature]` must be lowercase alphanumeric with hyphens, max 50 chars. Invalid segments render a 404-style message (not a server error).

**Props received by child content:** `featureName` from the URL segment.

#### `/define/:feature/review` (`app/define/[feature]/review/page.tsx`)

**Renders:** Ratification view (MP only). The [Commit RFC](speed-define-ceremony-commit.md)'s `RatificationView` component fills this page.

**Loading state:** Skeleton while `commitRecord` and `ratificationState` queries resolve.

**Error boundary:** If ceremony's current revision is not in COMMITTED state, shows "This spec is not ready for review" with current status.

**SP redirect:** In single-player mode, this route redirects to `/define/:feature` (ratification doesn't apply).

**Props received by child content:** `featureName` from the URL segment.

## Validation Rules

For the full validation rules catalog (11 rules across all ceremony RFCs), see [foundation reference](speed-define-ceremony-foundation.md#validation-rules). The rules enforced by this RFC:

| Field / Context | Constraints | Error Message |
|-----------------|-------------|---------------|
| Within-revision transition | `target` must be in `VALID_TRANSITIONS[current_status]` | "Cannot transition from {current} to {target}" |
| Cross-revision creation | Current revision must be in a terminal state (or no current revision) | "Cannot create new revision: current revision is still in {status}" |
| Cross-revision creation | Caller must be ceremony author | "Only the ceremony author ({author}) can perform this action" |
| SP mode: auto-ratify | `commitSpec` transitions COMMITTED -> RATIFIED immediately | (no separate validation, auto-applied) |
| MP mode: verdicts | Verdicts accumulate on COMMITTED revision; threshold triggers RATIFIED | "Ratification threshold not met: {count}/{threshold}" |
| Ceremony author check | `actor_email` must match `ceremony.author_email` | "Only the ceremony author ({author}) can perform this action" |
| Non-author check | `actor_email` must NOT match `ceremony.author_email`. Exemption: author can self-ratify when sole actor on roster. | "Cannot perform this action on your own ceremony" |
| ceremony.json `feature_name` (read validation) | Non-empty string, lowercase, hyphens, max 50 chars. Write-time enforcement is in [Context RFC](speed-define-ceremony-context.md) `declareIntent`. | "Feature name must be lowercase alphanumeric with hyphens, max 50 chars" |
| ceremony.json revision `status` | Must be a valid CeremonyStatus enum value | "Invalid ceremony status '{value}'" |
| ceremony.json `author_email` | Non-empty string, must contain `@` | "Invalid author email format" |
| ceremony.json `current_revision` | Must match a key in `revisions` | "current_revision '{id}' not found in revisions map" |
| ceremony.json `revisions` | Map, each entry has `revision_id`, `parent_id`, `status`, content hashes, `created_at` | "Malformed revision entry '{id}': missing {field}" |
| ceremony.json `reflog` | Array, each entry has `from_revision`, `to_revision`, `at`, `actor`, `actor_email`, `reason` | "Malformed reflog entry at index {i}" |
| Route segment `[feature]` | Lowercase alphanumeric with hyphens, max 50 chars | 404-style page: "Feature name is invalid" |

## Testing

### Acceptance Criteria

- Given `declareIntent` is called (by [Context RFC](speed-define-ceremony-context.md)), then `ceremony.json` is created with one revision at `DRAFTING`, the calling actor as author, `revision_count: 1`, and a single reflog entry
- Given a ceremony whose current revision is in `DRAFTING`, when `transition_ceremony_state(COMMITTED)` is called, then the revision's status updates to `COMMITTED`
- Given a ceremony in `COMMITTED` in SP mode, then `commitSpec` auto-transitions to `RATIFIED` and returns `planUnblocked = true`
- Given a ceremony in `COMMITTED` in MP mode, when verdicts accumulate and the approval threshold is met, then `transition_ceremony_state(RATIFIED)` fires
- Given a ceremony in `COMMITTED` in MP mode, when a rejection verdict is submitted, then `transition_ceremony_state(REJECTED)` fires
- Given an invalid transition (e.g., `DRAFTING -> RATIFIED`), then `transition_ceremony_state` raises `ValueError` with the message "Cannot transition from drafting to ratified"
- Given a ceremony whose current revision is in `RATIFIED`, when `create_revision("post-ratification: ...")` is called by the author, then a new revision at `DRAFTING` is created, the previous revision remains frozen at `RATIFIED`, `revision_count` increments, `current_revision` advances, and a reflog entry is appended
- Given a ceremony whose current revision is in `REJECTED`, when `create_revision("addressed rejection: ...")` is called by the author, then a new revision at `DRAFTING` is created with `parent_id` pointing to the rejected revision
- Given `create_revision` is called when the current revision is still in `DRAFTING`, then `ValueError` is raised with "Cannot create new revision: current revision is still in drafting"
- Given `create_revision` is called by a non-author, then `PermissionError` is raised
- Given `assert_ceremony_author` with a non-matching email, then `PermissionError` is raised with the author's name in the message
- Given `assert_not_ceremony_author` with the author's own email, then `PermissionError` is raised
- Given `ceremonyInfo` query with a feature that has no `ceremony.json`, then null is returned
- Given `ceremonyInfo` query with a feature that has a malformed `ceremony.json`, then a parse error is returned (not null)
- Given `ceremonyInfo` query for a valid ceremony, then the response includes `currentRevision` with the dereferenced `RevisionSummary` and `revisionCount`
- Given all 7 path helpers called in SP mode, then they return paths under `.speed/features/{feature}/`
- Given all 7 path helpers called in MP mode, then they return paths under the appropriate zone (`.speed/shared/features/{feature}/` for shared artifacts)
- Given route `/define/new`, then the page renders without error and delegates to bootstrap or intent input based on `bootstrapStatus`
- Given route `/define/sort-auth-by-last-activity`, then the page renders with the feature name extracted from the URL segment
- Given route `/define/INVALID!NAME`, then the page shows a 404-style message, not a server error

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| State transition allows invalid path | High | Unit test: exhaustively test every state pair (5x5 = 25 combinations), verify only 4 valid transitions succeed and 21 are rejected |
| Cross-revision creation from non-terminal state | High | Unit test: attempt `create_revision` from every non-terminal state (DRAFTING, COMMITTED), verify ValueError |
| Revision content hash collision | Low | Unit test: verify two revisions with different content produce different `revision_id` values |
| Ownership helper bypassed by child spec | Medium | Integration test: verify all child spec mutations that require ownership call the appropriate assert function. Grep test: assert that every resolver file importing `ceremony_types` also calls an assert function. |
| ceremony.json corrupted or missing fields | Medium | Unit test: load ceremony.json with each field individually missing, with empty values, with wrong types. Verify graceful error, not crash. |
| `current_revision` points to nonexistent key in `revisions` | Medium | Unit test: verify clear error message, not crash |
| get_current_actor returns unexpected identity | Medium | Unit test: mock each level of the fallback chain ($SPEED_ACTOR, git config, whoami), verify correct precedence and that the function never raises |
| Two actors with same name but different emails | High | Covered by [identity RFC](speed-define-ceremony-identity.md) tests. This RFC's `assert_ceremony_author` compares on `author_email`, so the identity RFC's guarantees propagate. |
| Route scaffold renders blank or crashes | Low | Visual test: each route renders loading skeleton, then content or error boundary |
| Concurrent ceremony.json writes (two resolvers write simultaneously) | Low | Known limitation. File-based storage has no locking. Document in Drawbacks. Not tested. Accepted risk for local dashboard with 1-5 users. |

### Test Plan

**Unit tests**

- `test_valid_transitions`: every valid within-revision transition pair succeeds, revision status updates correctly
- `test_invalid_transitions`: every invalid pair (21 of 25) raises `ValueError` with the correct "Cannot transition from X to Y" message
- `test_sp_committed_auto_ratifies`: COMMITTED in SP mode auto-transitions to RATIFIED
- `test_mp_committed_to_ratified`: COMMITTED in MP mode transitions to RATIFIED when threshold met
- `test_mp_committed_to_rejected`: COMMITTED in MP mode transitions to REJECTED on rejection verdict
- `test_create_revision_from_ratified`: creates new revision at DRAFTING with parent pointing to ratified revision, increments revision_count, advances current_revision, appends reflog
- `test_create_revision_from_rejected`: creates new revision at DRAFTING with parent pointing to rejected revision
- `test_create_revision_from_abandoned`: creates new revision at DRAFTING within grace period
- `test_create_revision_from_drafting_fails`: attempting create_revision while current revision is DRAFTING raises ValueError
- `test_create_revision_from_committed_fails`: attempting create_revision while current revision is COMMITTED raises ValueError
- `test_create_revision_non_author_fails`: non-author calling create_revision raises PermissionError
- `test_create_revision_marks_suggestions_outdated`: when sections change between revisions, suggestions on those sections are marked outdated
- `test_create_revision_preserves_unchanged_suggestions`: suggestions on unchanged sections carry forward as-is
- `test_revision_id_content_addressed`: revision_id is SHA-256 of spec_content_hash + context_package_hash + validation_hash + parent_id
- `test_revision_immutability`: once a revision reaches a terminal state (RATIFIED, REJECTED, ABANDONED), its fields cannot be modified
- `test_assert_ceremony_author_pass`: matching email does not raise
- `test_assert_ceremony_author_fail`: non-matching email raises PermissionError with author name
- `test_assert_not_ceremony_author_pass`: non-matching email does not raise
- `test_assert_not_ceremony_author_fail`: matching email raises PermissionError
- `test_get_current_actor_git_config`: when git config has name and email, returns them
- `test_get_current_actor_speed_actor_env`: `$SPEED_ACTOR` / `$SPEED_ACTOR_EMAIL` env vars take precedence over git config
- `test_get_current_actor_no_git`: when git is not installed, falls back to `whoami` for name and `{whoami}@local` for email
- `test_get_current_actor_no_git_email`: when git has name but no email, falls back to `{name}@local` for email
- `test_get_current_actor_never_raises`: all fallback scenarios return a valid tuple, never raise
- `test_ceremony_types_serialization`: all 23 Strawberry types serialize to JSON and deserialize back without data loss
- `test_path_helpers_sp`: all 7 ceremony paths resolve under `.speed/features/{feature}/` in SP mode
- `test_path_helpers_mp`: all 7 ceremony paths resolve under the correct zone in MP mode
- `test_ceremony_json_roundtrip`: write ceremony.json with all fields (revisions map, reflog), read back, verify equality
- `test_ceremony_json_missing_fields`: load with each required field removed, verify clear error
- `test_ceremony_json_invalid_status`: revision status value not in CeremonyStatus enum, verify error
- `test_ceremony_json_empty_file`: empty file returns parse error, not null
- `test_ceremony_json_invalid_feature_name`: feature_name with uppercase, spaces, or >50 chars, verify error
- `test_ceremony_json_invalid_author_email`: author_email missing `@`, verify error
- `test_ceremony_json_invalid_current_revision`: current_revision not in revisions map, verify error
- `test_ceremony_json_invalid_revision_entry`: revision missing required field, verify error with revision_id
- `test_ceremony_json_invalid_reflog_entry`: reflog entry missing required field, verify error with index
- `test_ceremony_info_empty_feature_name`: `ceremonyInfo` query with empty string featureName, verify validation error (not null)
- `test_ceremony_info_dereferences_revision`: `ceremonyInfo` response includes `currentRevision` with all `RevisionSummary` fields populated from `revisions[current_revision]`

**Integration tests**

- `test_graphql_ceremony_info`: query `ceremonyInfo` through the Strawberry schema with a real ceremony.json on disk, verify response includes `currentRevision` with `RevisionSummary` fields and `revisionCount`
- `test_graphql_ceremony_info_null`: query for a non-existent feature, verify null return (not error)
- `test_graphql_ceremony_info_malformed`: query for a feature with corrupted ceremony.json, verify error return (not null)
- `test_types_importable_by_children`: import all 23 types from `ceremony_types` in a test module that mimics each child spec's import pattern, verify no import errors
- `test_schema_registration`: verify `ceremonyInfo` query is registered on the Strawberry schema and callable

**End-to-end tests**

Deferred to child RFC implementation. The parent RFC's deliverables (types, helpers, scaffolds) are infrastructure consumed by child RFCs. E2E flows (declare intent -> author spec -> commit -> ratify) span multiple child RFCs and will be tested as integration scenarios in the [Commit RFC](speed-define-ceremony-commit.md)'s test plan.

**Visual/UI tests**

- `/define/new` route scaffold renders loading skeleton (opacity fade, not pulse), then delegates to content
- `/define/:feature` route scaffold renders three-panel skeleton layout
- `/define/:feature/review` route scaffold renders two-panel skeleton layout
- All three routes render error boundary when child content throws
- `/define/:feature/review` redirects to `/define/:feature` in SP mode (ratification not applicable)
- Invalid `[feature]` segment renders 404-style message, not blank page

### Edge Cases

- `ceremony.json` exists but is empty (0 bytes): return parse error with message, not null and not crash
- `ceremony.json` exists but contains `{}` (valid JSON, missing all fields): return schema error listing all missing fields
- Feature directory exists from a prior `speed run` but has no `ceremony.json`: return null (feature exists but no ceremony was started)
- `current_revision` points to a key not present in `revisions` map: return schema error with the dangling reference, not crash
- Ceremony with 10+ revisions from repeated reject/rework cycles: all revisions preserved in the `revisions` map, full reflog preserved. Performance acceptable since each revision is ~200 bytes and each reflog entry is ~150 bytes.
- SP ceremony in COMMITTED state: auto-transitions to RATIFIED immediately. No separate ratification step.
- SP project runs `speed mp-init` mid-ceremony: `is_multiplayer` retains its original value from ceremony creation time. The ceremony continues as SP.
- `create_revision` called on an ABANDONED ceremony outside the grace period (90 days): the behavior is determined by the caller ([Commit RFC](speed-define-ceremony-commit.md) or [Context RFC](speed-define-ceremony-context.md)). The parent RFC's `create_revision` only checks that the current revision is terminal; the grace period check is a policy layered on top.
- Two actors call `transition_ceremony_state` simultaneously: last write wins. No file locking. (See [Drawbacks](#drawbacks).)
- `get_current_actor()` returns different results across requests if user changes git config or env vars between requests: per-request cache means each request gets a consistent identity.
- Machine has no git installed: `get_current_actor()` falls back to `whoami` for name, `{whoami}@local` for email. Ownership checks still work because the same fallback is used consistently within and across requests on that machine.
- Route `/define/new` visited by two users simultaneously in MP: each sees independent bootstrap/intent state (no shared browser state).

### Out of Scope

- Performance testing of ceremony.json read/write latency. The file stays under 20KB even after 50+ revisions and is read once per query. No performance concerns at current scale.
- Load testing of concurrent GraphQL requests. The dashboard runs locally with 1-5 concurrent users. Concurrent file access race conditions are documented in Drawbacks but not tested.
- Browser compatibility testing for route scaffolds. Next.js 15 handles cross-browser rendering. Ceremony-specific browser testing is owned by child RFCs that add interactive content.

## Security & Controls

**Identity**: `get_current_actor()` resolves identity server-side via `lib/actor.sh`. Cannot be spoofed through GraphQL input parameters. See [identity RFC](speed-define-ceremony-identity.md) for the full resolution chain and spoofing analysis.

**Unique identifier**: Ownership checks match on `author_email`, not `author` name. Email is reliably unique across a team; display names are not. The `author` name field is stored for display (error messages, UI) but is not the matching key. The [identity RFC](speed-define-ceremony-identity.md) upgrades the broader SPEED ownership system to use email, so the ceremony system and existing `speed claim` both use the same matching key.

**Ownership enforcement**: `assert_ceremony_author()` and `assert_not_ceremony_author()` are the only ownership check mechanisms in the ceremony system. They are plain functions, not middleware or decorators. Each child spec resolver must call them explicitly before protected mutations. The parent RFC does not wrap child spec resolvers with automatic ownership checks. This is intentional: explicit calls are auditable and testable (the integration test verifies every child resolver calls them).

**Audit trail**: Every state transition is recorded in the revision's status field and every ref movement is recorded in the `reflog` with actor, actor_email, timestamp, from/to revision IDs, and reason. Revisions are immutable once they leave DRAFTING. The reflog is append-only and never truncated. No deletion mechanism exists.

**Data sensitivity**: `ceremony.json` contains the author's git name and email. This is the same identity information already present in git commits and `.speed/shared/roster/`. No additional PII is introduced.

**Input sanitization**: `featureName` parameters are validated (lowercase alphanumeric with hyphens, max 50 chars) before being used to construct file paths, preventing path traversal attacks.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| All 23 shared types in one module | Single `ceremony_types.py` file | Per-child-spec type files; shared Python package with submodules | One file, one import path. Follows existing `resolvers/*_types.py` convention in the codebase (e.g., `define_types.py`, `landing_types.py`). A shared package adds import complexity without benefit at this scale. |
| State persists to `ceremony.json` file | Flat JSON file on disk | Derive state from artifacts (check for intent.json, commit.json, events); SQLite database; in-memory only | Deriving from artifacts is fragile: checking "does intent.json exist? does commit.json exist?" to infer state creates implicit coupling between the state machine and artifact existence. A single file is fast to read (~1ms), unambiguous, and debuggable with `cat`. SQLite adds a dependency for a single-record store. |
| Revision chain with reflog as audit trail | `revisions` map + `reflog` array inside `ceremony.json` | Flat `status` + `status_history` array; separate log file per ceremony; events-only (rely on `.speed/shared/events/`) | The revision model provides content-addressed immutable snapshots, enabling cross-revision suggestion tracking and post-mortem forensics. Co-locating revisions and reflog with current state means one file read gives the full picture. Events-only works for MP but not SP (SP has no event system). |
| Ownership helpers as plain functions | Exported functions in `ceremony_types.py` | Python decorator on resolver methods; Strawberry middleware; GraphQL directive | Functions are explicit: the child spec resolver's code visibly calls `assert_ceremony_author(state, email)`. A decorator hides the check. Middleware applies to all resolvers (too broad). Directives aren't supported by Strawberry's current API. |
| Route scaffolds as separate page files | One `page.tsx` per route | Single page with URL-based mode switching; no scaffolds (child RFCs create their own pages) | Separate routes = separate page components = child RFCs can develop independently without merge conflicts. A single page with mode switching creates a God component. No scaffolds forces child RFCs to handle layout boilerplate redundantly. |
| `get_current_actor()` cached per request | Read git config once per GraphQL operation | Read on every resolver call; cache for the entire server lifetime | Per-call is wasteful (subprocess spawn per resolver). Lifetime cache is stale if the user changes git config between requests. Per-request is the right granularity: consistent within a single operation, fresh across operations. |
| Ownership matches on `author_email`, not `author` name | Email as unique key | Display name (existing SPEED pattern); actor slug; composite `name:email` | See [identity RFC](speed-define-ceremony-identity.md) for full rationale. The ceremony system matches on `author_email`; UI and error messages display the human-readable `author` name. |
| Solo author can self-ratify in MP | Exempt author from `assert_not_ceremony_author` for ratification when they are the only actor on the roster | (a) SP mode is the only path for solo developers (MP with one actor is a misconfiguration); (b) threshold 0 skips ratification in MP | A solo developer who runs `speed mp-init` shouldn't be deadlocked. The exemption is narrowly scoped: only ratification, not suggestions. Roster size is already available via `.speed/shared/roster/`. |

## Drawbacks

- **All 23 types in one file creates a large module.** At ~280 lines of type definitions plus ~150 lines of helpers (including `create_revision`), `ceremony_types.py` will be one of the larger files in `resolvers/`. If the type count grows beyond the ceremony feature, the file should be split. For now, 23 types is manageable and the single-import benefit outweighs the file size.

- **No file locking on `ceremony.json`.** Two concurrent GraphQL mutations could read-modify-write simultaneously, causing a lost update. In practice, the dashboard serves 1-5 local users, ceremony state transitions are infrequent (a handful per session), and the risk window is milliseconds. If MP mode scales to larger teams, file locking or an atomic write strategy (write to temp, rename) should be added.

- **The state machine is rigid.** Adding a new state or transition requires modifying the `VALID_TRANSITIONS` dict and the `CeremonyStatus` enum. There's no plugin mechanism for custom states. This is acceptable because the ceremony lifecycle is a core contract that downstream agents depend on; flexibility here would create unpredictable behavior for `speed plan`, the Guardian, and the learning pipeline.

- **Ownership enforcement is opt-in by child RFCs.** The parent RFC exports `assert_ceremony_author()` but cannot force child spec resolvers to call it. A child RFC that forgets the check has an unprotected mutation. The integration test mitigates this (grep for assert calls), but it's a convention, not a compile-time guarantee.

- **Route scaffolds are shells with no standalone value.** Until child RFCs add content, the three pages show only loading skeletons and error boundaries. A reviewer looking at the parent RFC's deliverables in isolation sees minimal UI. The scaffolds exist so child RFCs have a place to render without creating route conflicts.

## Search / Query Strategy

| Operation | Access Pattern | Expected Volume | Performance |
|-----------|---------------|-----------------|-------------|
| `ceremonyInfo` query | Single file read: `.speed/features/{feature}/ceremony.json`, dereference `current_revision` into `revisions` map | 1 file, < 10KB | < 5ms (stat + read + JSON parse + dereference) |
| `transition_ceremony_state` | Read + write `ceremony.json` (update one revision's status in `revisions` map) | 1 file, < 10KB | < 10ms (read + parse + update + write) |
| `create_revision` | Read + write `ceremony.json` (add revision to map, append reflog, advance ref) + read `suggestions.json` for outdated marking | 2 files, < 15KB total | < 20ms (two reads + hash computation + two writes) |
| `get_current_actor` | Env var check, then subprocess (`git config`), then `whoami` fallback | 0-3 calls depending on fallback depth | < 50ms first call, cached after |
| Path helpers | String concatenation on `SpeedPaths.root` | No I/O | < 1ms |

No database queries. No indexing. No pagination. The ceremony state model is one file per feature, read in full on every access. `ceremony.json` grows with each revision (~200 bytes per revision entry + ~150 bytes per reflog entry), but even after 50 revisions the file stays under 20KB. For a project with 50 features, the landing page would need to read 50 `ceremony.json` files to show ceremony status alongside the portfolio grid. Not implemented in this RFC (future concern), but the access pattern scales linearly with feature count.

## Migration Strategy

No data migration. This RFC creates new files and adds methods to existing classes. No existing data formats are changed. The identity system migration (adding `actor_email` to events, changing ownership matching) is handled by the [identity RFC](speed-define-ceremony-identity.md), which is a prerequisite.

## File Impact

**New files:**

| File | Size Estimate | What It Contains | Owned By |
|------|--------------|------------------|----------|
| `dashboard/backend/resolvers/ceremony_types.py` | ~430 lines | `CeremonyStatus` enum, 23 shared Strawberry types (including `RevisionSummary`), `VALID_TRANSITIONS` dict, `transition_ceremony_state()`, `create_revision()`, `assert_ceremony_author()`, `assert_not_ceremony_author()`, `get_current_actor()`, `ceremonyInfo` query resolver, `ceremony.json` read/write helpers | This RFC (parent) |
| `dashboard/frontend/lib/graphql/queries/ceremony.ts` | ~130 lines | TypeScript type definitions matching all 23 shared Strawberry types (including `RevisionSummary`), `CEREMONY_INFO_QUERY` document | This RFC (parent) |
| `dashboard/frontend/app/define/new/page.tsx` | ~60 lines | Route scaffold: layout shell, `bootstrapStatus` check, delegates to BootstrapWizard or IntentInput | This RFC creates the file. Content filled by [Context RFC](speed-define-ceremony-context.md) (IntentInput) and [Bootstrap RFC](speed-define-ceremony-bootstrap.md) (BootstrapWizard). |
| `dashboard/frontend/app/define/[feature]/page.tsx` | ~50 lines | Route scaffold: layout shell, `ceremonyInfo` + `contextPackage` queries, delegates to CeremonyLayout | This RFC creates the file. Content filled by [Editor RFC](speed-define-ceremony-editor.md) (CeremonyLayout). |
| `dashboard/frontend/app/define/[feature]/review/page.tsx` | ~50 lines | Route scaffold: layout shell, `commitRecord` + `ratificationState` queries, SP redirect, delegates to RatificationView | This RFC creates the file. Content filled by [Commit RFC](speed-define-ceremony-commit.md) (RatificationView). |

**Modified files:**

| File | Change | Owned By |
|------|--------|----------|
| `dashboard/backend/paths.py` | Add 7 ceremony path helpers to `SpeedPaths` class. No existing methods modified. | This RFC adds helpers. [Context RFC](speed-define-ceremony-context.md) and [Commit RFC](speed-define-ceremony-commit.md) also add helpers to this file (different methods, no overlap). |
| `dashboard/backend/schema.py` | Import `CeremonyInfo` type, register `ceremonyInfo` query on the Strawberry schema. | This RFC modifies schema.py first in the integration order (identity -> parent -> context -> editor -> contributor -> commit -> bootstrap). |

## Dependencies

| Dependency | What It Provides | Where It Lives |
|------------|-----------------|----------------|
| [Identity RFC](speed-define-ceremony-identity.md) | `actor_email_get()` in `lib/actor.sh`, `actor_email` field in events, email-based ownership matching in `lib/ownership.sh` and `lib/serve/server.py`. Must be built first. | `specs/tech/speed-define-ceremony-identity.md` |
| `SpeedPaths` class | Path resolution with SP/MP zone awareness | `dashboard/backend/paths.py` (existing, 22 helpers) |
| Strawberry GraphQL schema | Schema registration for queries/mutations | `dashboard/backend/schema.py` (existing) |
| `lib/actor.sh` | Name resolution (`actor_resolve`, `actor_get`, `actor_slug`). Email resolution (`actor_email_resolve`) added by [Identity RFC](speed-define-ceremony-identity.md). | `lib/actor.sh` (existing, modified by [Identity RFC](speed-define-ceremony-identity.md)) |
| Next.js 15 app router | File-based routing for page scaffolds | `dashboard/frontend/app/` (existing) |
| `.speed/shared/` directory | MP mode detection (`is_multiplayer` flag) | Created by `speed mp-init`, checked via `Path.exists()` |

## Unresolved Questions

See also [foundation resolved questions](speed-define-ceremony-foundation.md#resolved-questions) for cross-cutting decisions.

| Question | Blocks | Proposed Resolution |
|----------|--------|---------------------|
| Should ceremony.json use atomic writes (write to temp, rename) to prevent corruption? | Data integrity | Deferred. The risk of corruption from concurrent writes is low for a local dashboard with 1-5 users and infrequent transitions. If MP scales to larger teams, atomic writes should be added. Documented in Drawbacks. |
| What happens when ratification threshold is 1 and the author is the only actor in MP mode? | Ratification flow for small MP teams | **Decided:** Solo actors can self-ratify. When the roster has exactly one actor (the author), `submitRatification` skips the non-self-ratification check. The exemption is scoped to ratification only; suggestions still require a non-author. |
