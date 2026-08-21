# RFC: Per-Spec Ownership in the Define Ceremony

> See [product spec](../product/speed-define-ceremony-ownership.md) for product context.
> See [design spec](../design/speed-define-ceremony-ownership.md) for the UI contract (tab bar, Progress Overview, commit bar modes, read-only editor treatment).
> Parent RFC: [speed-define-ceremony.md](speed-define-ceremony.md) — single-author baseline this RFC generalizes.
> Depends on: [speed-define-ceremony-foundation.md](speed-define-ceremony-foundation.md) — shared types, state machine, artifact flow, roster and actor resolution.
> Depends on: [speed-define-ceremony-commit.md](speed-define-ceremony-commit.md) — commit and ratification flow this RFC extends to per-spec granularity.

## Problem

The define ceremony today assigns one author to the whole feature. See the [product spec](../product/speed-define-ceremony-ownership.md) for the full framing, user stories, and success criteria. This RFC covers the technical model that lets a PM, a designer, and an engineer own different specs within the same ceremony without blocking on each other, including stale-claim takeover, per-spec commit and ratification, and the authorization policy enforcing it.

## Basic Example

Three concrete interactions, showing how the claim model is used from a caller's perspective.

**1. PM claims the PRD and commits it while an engineer drafts the RFC.**

```graphql
# PM opens the ceremony. PRD is unclaimed.
mutation { claimSpec(featureName: "user-ingestion", specType: "prd") { specType claimant } }
# → { specType: "prd", claimant: "sanjay" }

# PM edits and commits without touching the RFC.
mutation { commitSpec(featureName: "user-ingestion", specType: "prd") {
  revisionId committedAt ceremonyStatus
} }
# → { ..., ceremonyStatus: "DRAFTING" }   # RFC still drafting, ceremony stays DRAFTING

# Engineer commits the RFC last.
mutation { commitSpec(featureName: "user-ingestion", specType: "rfc") {
  revisionId committedAt ceremonyStatus
} }
# → { ..., ceremonyStatus: "COMMITTED" }  # last drafted spec committed, ceremony advances
```

**2. Stale claim takeover.**

```graphql
# RFC claimed by priya two hours ago. stale_window = 60min.
query { ceremonyClaims(featureName: "user-ingestion") { specType claimant releasedAt staleFor } }
# → [{ specType: "rfc", claimant: "priya", releasedAt: null, staleFor: "2h" }, ...]

# Another engineer claims it. Server resolves as stale takeover in one transaction.
mutation { claimSpec(featureName: "user-ingestion", specType: "rfc") { claimant } }
# → { claimant: "alex" }
# The old claim file on disk is updated: released_at = now, reason = "stale"
# The new claim file is written with alex as the claimant. priya's draft content is preserved.
```

**3. Non-claimant leaves a suggestion, the claimant resolves it.**

```graphql
# priya (non-claimant of PRD) leaves a suggestion on sanjay's PRD.
mutation { createSuggestion(
  featureName: "user-ingestion",
  specType: "prd",
  sectionId: "user-stories",
  text: "Add acceptance criterion for null accessedAt rows"
) { id } }
# → { id: "s-0a31" }

# sanjay (PRD claimant) accepts it.
mutation { resolveSuggestion(id: "s-0a31", action: "accept", reason: null) { status } }
# → { status: "accepted" }
# Server checks: claims["prd"].claimant == actor → sanjay → allowed.
# If priya tried the same resolve call, authorization denies with "not claimant of prd".
```

## Interface Contract

This is a child RFC. It consumes types and artifacts from the foundation and commit RFCs; it produces the per-spec claim, commit, and ratification model that the editor and commit RFCs consume.

### Consumes (from foundation and commit RFCs)

From [speed-define-ceremony-foundation.md](speed-define-ceremony-foundation.md):

- `CeremonyState` dataclass (ceremony-wide status, revision pointer, author_email) — this RFC does not add fields to it
- `CeremonyStatus` enum (DRAFTING / COMMITTED / RATIFIED / REJECTED / ABANDONED)
- `Revision` dataclass — this RFC adds no new fields (sets are derived)
- `transition_ceremony_state()` function — called from `commitSpec` / `submitRatification` when gates are met
- `create_revision()` function — called on amendments; this RFC extends the artifact reset to cover per-spec files
- `VALID_TRANSITIONS` dict — unchanged in shape
- `get_current_actor() -> (name, email)` from `ceremony_types.py`
- `lib/ownership.sh` UTC-safe staleness comparison helpers — reused verbatim, not reimplemented
- `speed.toml [multiplayer] stale_window` configuration value
- Roster loading helpers at `.speed/shared/roster/*.json`

From [speed-define-ceremony-commit.md](speed-define-ceremony-commit.md):

- Single-file `commit.json` model — replaced here with per-spec `commit-{spec_type}.json`
- Single-file ratification model — replaced with per-spec `ratification-{spec_type}.json`
- `submitRatification` mutation — extended with `specType` parameter

### Produces (for downstream RFCs and callers)

- `SpecClaim` dataclass (spec_type, claimant, claimant_email, claimed_at, last_activity_at, released_at)
- Per-spec claim files: `claim-{spec_type}.json` in the ceremony directory, one per claimed spec
- Per-spec commit files: `commit-{spec_type}.json` — existence is ground truth for `committed_specs` derivation
- Per-spec ratification files: `ratification-{spec_type}.json` — the `ratified` field is ground truth for `ratified_specs` derivation
- `derive_transition_sets(feature_name) -> tuple[set[str], set[str], set[str]]` helper, returning `(drafted, committed, ratified)` computed from filesystem listings
- New mutations: `claimSpec(featureName, specType)`, `releaseSpec(featureName, specType)`
- Modified mutations: `updateDraft`, `generateDraft`, `createSuggestion`, `resolveSuggestion`, `decomposeDraft`, `commitSpec`, `submitRatification` — all gain a `specType` parameter (or look it up via the Suggestion record for `resolveSuggestion`)
- New query: `ceremonyClaims(featureName) -> list[SpecClaim]` enumerated by directory listing
- New GraphQL field: `Suggestion.spec_type`
- `CeremonyAbility` policy class at `dashboard/backend/resolvers/ceremony_authz.py` — the single source of truth for authorization
- New path helpers on `SpeedPaths`: `ceremony_claim(name, spec_type)`, `ceremony_commit_record(name, spec_type)`, `ceremony_decomposition(name, spec_type)`

## Scope

### In scope

- Per-spec claims via new `claimSpec` / `releaseSpec` mutations and stale claim detection
- Per-spec claim records at `claim-{spec_type}.json`, one file per claimed spec
- Claim display on each tab in the editor
- Action authorization keyed off the per-spec claim files: write, resolve suggestion, decompose, commit, ratify
- `spec_type` field added to `Suggestion` so suggestions route to the correct claimant
- Per-RFC decomposition storage at `decomposition-{spec_type}.json` (only instantiated when `spec_type` is an RFC slot)
- Per-spec commit records at `commit-{spec_type}.json`
- Per-spec ratification: verdicts and thresholds key on `(revision_id, spec_type)`
- `spec_type` values expand from `"prd" | "design" | "rfc"` to also include `"rfc-{slug}"` entries so each child RFC in a decomposed ceremony has its own slot
- Ceremony state machine transitions gated on aggregate per-spec state
- Progress overview showing each spec's claimant and status

### Out of scope

- **Persistent role tags on the roster.** Roles are ephemeral and claim-derived. Persistent tags would duplicate the claim concept.
- **Assigning a spec to someone.** Claims are pulled, not pushed. This matches the existing `speed claim` pattern and avoids introducing a coordinator role.
- **Multiple claimants on one spec.** One claimant per spec. Collaboration runs through suggestions, same as today.
- **A separate "review" action.** Review is suggestions plus resolution. Claimants resolve open suggestions before decomposition, which serves the same function as a formal review step without adding a new action.
- **Rewriting the claimant on a committed spec.** Once `commit-{spec_type}.json` is written for a revision, the claimant snapshot recorded inside it is immutable. Changing who committed requires creating a new revision and committing it fresh under a different claimant. There is no "transfer ownership of an already-committed spec" action.
- **Cross-spec dependency enforcement at commit time.** If the RFC depends on the PRD being ratified, the system does not block RFC commit. Dependencies are informational and shown in the progress overview.
- **Role-based claim gating.** Any roster member can claim any spec. There is no rule that says "only designers can claim the Design spec." Teams self-police by leaving suggestions if the wrong person claims something.

## Data Model Changes

### Per-spec claim files

Each claimed spec has its own `claim-{spec_type}.json` file under the ceremony directory, containing a single `SpecClaim` record. Claims are not stored as a map inside `ceremony.json`; every other per-spec artifact (draft, validation state, decomposition, commit record) already lives in its own file, and claims should match that pattern for three reasons: write isolation (two actors claiming different specs never touch the same file), consistency with the event-sourcing model used elsewhere in multiplayer, and locality (a spec's claim lives next to its other artifacts, not buried in a shared map).

```python
@dataclass
class SpecClaim:
    spec_type: str              # "prd" | "design" | "rfc" | "rfc-{slug}"
    claimant: str               # resolved by get_current_actor()
    claimant_email: str
    claimed_at: str             # ISO 8601
    last_activity_at: str       # refreshed on any claimant mutation
    released_at: str | None     # set on voluntary release, stale expiry, or commit; None when active
```

`CeremonyState` gains no claims field. A spec is unclaimed if `claim-{spec_type}.json` does not exist on disk, or if the file exists but `released_at` is populated. The ceremony's existing `author_email` field stays as the intent declarer and is populated as the PRD claimant by `declareIntent` (see API changes below).

`spec_type` is the same discriminator already used by `ceremony_draft` and `ceremony_validation_state` today; this RFC expands the set of valid values to also include `rfc-{slug}` entries for child RFCs but does not rename the field or any helper parameter.

When code needs the coarse category ("is this any kind of RFC?") it derives it on the fly with a one-line helper: `"rfc" if spec_type.startswith("rfc") else spec_type`. No stored "broad category" field; deriving it costs nothing and eliminates the risk of the two fields drifting.

**Child RFCs are first-class claimable specs.** A simple ceremony with one RFC has one claim at `spec_type = "rfc"`. A ceremony decomposed into child RFCs replaces that single entry with one claim per child, keyed as `rfc-<slug>`, where `<slug>` is the lowercase hyphenated name of the child spec and matches the slug used in the child's published file path (`specs/tech/<feature>-<slug>.md`). Concrete values for a four-way ingestion feature decomposition: `rfc-ingestion`, `rfc-query`, `rfc-editor`, `rfc-feedback`. Each child is claimed, drafted, suggested on, resolved, decomposed, committed, and ratified independently of its siblings. The same `spec_type` value keys both the in-ceremony working files (`draft-rfc-ingestion.md`, `commit-rfc-ingestion.json`, and so on under the ceremony directory) and the published file the child lands in after ratification; these are different files on disk, reached through different path helpers, but they share the identifier.

### Claim lifecycle

Claims and ceremonies have two different state machines. The [foundation RFC](speed-define-ceremony-foundation.md#state-machine) owns the ceremony lifecycle (DRAFTING → COMMITTED → RATIFIED / REJECTED / ABANDONED, with revision chaining on terminal states); this section owns the per-spec claim lifecycle (UNCLAIMED → ACTIVE → RELEASED). They run on different axes and should not be confused:

- The ceremony lifecycle is scoped to the whole ceremony. It advances once, based on aggregate per-spec state (DRAFTING → COMMITTED fires only when every drafted spec has a commit record).
- The claim lifecycle is scoped to a single spec slot. It runs N times in parallel, once per `spec_type`, driven by direct actor action on that one spec.

The two machines touch at exactly one point: `commitSpec` advances the inner (claim) machine to RELEASED-via-commit and may, in the same transaction, advance the outer (ceremony) machine from DRAFTING to COMMITTED if it happens to be the last drafted spec. Every other transition in either machine is independent of the other.

Every claim has its own age clock. A claim is considered stale when `now - last_activity_at > stale_window`. The window value is the existing `[multiplayer] stale_window` setting in `speed.toml`, which defaults to 3600 seconds (one hour). This is the same setting `speed claim` uses for feature ownership, and the ownership RFC deliberately reuses it rather than introducing a ceremony-specific knob. One value in config, one staleness math path, one place to fix the open UTC bug tracked in `specs/defects/ownership-stale-check-utc-mismatch.md`.

Each spec claim ages on its own timer. If the PM claims the PRD at 9:00 and does nothing else, the PRD claim is stale at 10:00. If the Engineer claims the RFC at 9:55, the RFC claim is stale at 10:55. The two expirations are independent; the claims share the window value, not the expiration moment.

**Resets the clock** (any mutation by the claimant on their spec refreshes `last_activity_at`):

- `generateDraft`
- `updateDraft`
- `resolveSuggestion`
- `decomposeDraft`
- `commitSpec`

**Does not reset the clock**:

- Opening or reading the tab
- Another actor leaving a suggestion on the spec
- Another actor viewing the progress overview
- Mutations on other specs in the same ceremony

**Detection is lazy.** There is no background sweeper. Staleness is computed on demand inside `claimSpec` (to decide whether an existing claim can be superseded) and inside the `ceremonyClaims` query (to decide what to display). When a stale claim is detected during a `claimSpec` call, the new claim replaces the old one in a single transaction and `released_at` is set on the old record. The staleness comparison must use the same UTC-safe path as `lib/ownership.sh`, not a new implementation.

**What `commitSpec` does to the claim file.** At commit time the claimant snapshot is copied into `commit-{spec_type}.json`, which becomes the durable record of who committed the spec for that revision. The live `claim-{spec_type}.json` file is updated in the same transaction: `last_activity_at` is refreshed and `released_at` is set to `committed_at`. The claim is retired, not deleted. Reading `claim-{spec_type}.json` after commit shows the same claimant with a non-null `released_at`, so the tab bar can continue to display "committed by sanjay" without having to read the commit record for simple UI queries. Deleting the file would lose information the UI already expects to have at that path.

If the ceremony advances to a new revision (via `create_revision()`), the `claim-{spec_type}.json` file is left in its released state on disk but the next `claimSpec` call on that spec treats it the same as any other released claim: eligible for re-claim by any roster member. The committing claimant retains no implicit priority on the new revision.

**Claim state diagram.** This is the inner, per-spec machine only. For the outer ceremony state machine (DRAFTING / COMMITTED / RATIFIED / REJECTED / ABANDONED and cross-revision chaining), see the [foundation RFC](speed-define-ceremony-foundation.md#state-machine).

```
              ┌─────────────┐
              │  UNCLAIMED  │  ← no file, or released_at is set and revision advanced
              └─────────────┘
                     │
            claimSpec│
                     ▼
              ┌─────────────┐
    ┌─────────│   ACTIVE    │─────────┐
    │         └─────────────┘         │
    │                │                │
    │        commitSpec               │
    │                │                │releaseSpec
    │                ▼                │
    │         ┌─────────────┐         │
    │         │  COMMITTED  │         │
    │         │  (released_ │         │
    │         │   at = now) │         │
    │         └─────────────┘         │
    │                                 │
    │ stale_window elapsed            │
    │ since last_activity_at          │
    ▼                                 ▼
   ┌────────────────────────────────────┐
   │   RELEASED (file retains history)  │
   │   re-claimable by any roster member│
   └────────────────────────────────────┘
```

Three ways to leave ACTIVE: the claimant commits, the claimant releases voluntarily, or the clock runs out. All three produce an on-disk file with `released_at` populated; the only difference is what else the call touches (commit writes a commit record; stale-takeover writes a new ACTIVE claim in the same transaction; voluntary release just updates the file).

### Derived per-spec sets (no new Revision fields)

The state machine needs three sets to evaluate transition gates: `drafted_specs`, `committed_specs`, and `ratified_specs`. None of them are stored on `Revision` or anywhere else in `ceremony.json`. They are derived on demand from the ceremony directory, because the ground truth for each already lives in a per-spec file on disk:

| Set | Derivation |
|-----|------------|
| `drafted_specs` | Directory listing of `draft-*.md` in the ceremony directory; the suffix is the `spec_type`. |
| `committed_specs` | Directory listing of `commit-*.json`; presence means the spec was committed for the current revision. |
| `ratified_specs` | Directory listing of `ratification-*.json` whose contents report `ratified: true`. |

Storing these as sets on the `Revision` dataclass would duplicate state that already lives on disk, serialize every per-spec mutation on a `ceremony.json` rewrite, and recreate the exact write-contention and drift problems that per-spec files were introduced to solve. Deriving them is cheap — the ceremony directory holds a handful of files — and the derivation runs only at transition-gate checkpoints (`commitSpec`, `submitRatification`), not on every query.

`Revision` is unchanged in shape by this RFC. `revision_id` continues to be content-addressed over the existing hash inputs; the per-spec files are the revision's artifacts but not part of its identity.

```python
def derive_transition_sets(feature_name: str) -> tuple[set[str], set[str], set[str]]:
    """Returns (drafted, committed, ratified) for the current revision."""
    ceremony_dir = paths.ceremony_dir(feature_name)
    drafted   = {f.stem.removeprefix("draft-") for f in ceremony_dir.glob("draft-*.md")}
    committed = {f.stem.removeprefix("commit-") for f in ceremony_dir.glob("commit-*.json")}
    ratified  = {f.stem.removeprefix("ratification-")
                 for f in ceremony_dir.glob("ratification-*.json")
                 if json.loads(f.read_text()).get("ratified") is True}
    return drafted, committed, ratified
```

`create_revision()` resets the filesystem exactly the same way the foundation describes for single-author ceremonies — whatever archival the reflog does for `commit.json` today applies file-by-file to the new per-spec commit and ratification files. No new dataclass fields to reset.

### Suggestion: spec_type field

`Suggestion` today has `section_id` and `section_title` but no way to identify which spec the suggestion belongs to. Section titles are not unique across specs (PRD, Design, and RFC all have a "Scope" section), and child RFCs share identical section names, so routing suggestions by title is ambiguous. Add a `spec_type` field:

```python
@strawberry.type
class Suggestion:
    # existing fields unchanged
    spec_type: str  # "prd" | "design" | "rfc" | "rfc-{slug}"
```

`resolveSuggestion` uses this to look up the correct claimant: read `claim-{suggestion.spec_type}.json` and check `claimant_email == actor_email`.

### Decomposition: per-spec storage

The current code reads a single `decomposition.json` at `feature_shared(name)` (`ceremony_editor.py:266` and `:540`). Move it to `decomposition-{spec_type}.json`. Add a new path helper `ceremony_decomposition(name, spec_type)` on `SpeedPaths`. Update the two reader/writer sites in `ceremony_editor.py` to pass the spec_type.

### CommitRecord: per-spec

Replace the single `commit.json` with `commit-{spec_type}.json`, one per committed spec. The `CommitRecord` type becomes:

```python
@strawberry.type
class CommitRecord:
    feature_name: str
    spec_type: str                          # NEW: "prd" | "design" | "rfc" | "rfc-{slug}"
    revision_id: str                        # ceremony revision at commit time
    claimant: str                           # NEW: was "author"
    claimant_email: str                     # NEW: was "author_email"
    committed_at: str
    validation_state_ref: str               # validation-state-{spec_type}.json
    context_package_ref: str                # unchanged: context is feature-level
    suggestion_history: SuggestionHistory   # filtered to this spec_type
    spec_path: str                          # was spec_paths: list[str]
    decomposition_ref: str | None           # decomposition-{spec_type}.json or None
    is_multiplayer: bool
    ratification_threshold: int
    ratification_status: str
```

`suggestion_history` is computed at commit time by filtering `suggestions.json` to entries where `suggestion.spec_type` matches this commit's spec_type.

### Ratification: per-spec record shape

Each committed spec has its own `ratification-{spec_type}.json` file. The minimal shape is fixed by this RFC so the Design spec's `RatifyControl` bindings (approval count, `hasVoted`, threshold display) have a contract to read against.

```python
@dataclass
class Verdict:
    actor: str               # display name from get_current_actor()
    actor_email: str         # canonical identity, used for dedupe and hasVoted
    verdict: str             # "approve" | "reject"
    comment: str | None      # required when verdict == "reject", optional for approve
    submitted_at: str        # ISO 8601 UTC

@dataclass
class Ratification:
    spec_type: str           # matches the filename suffix
    revision_id: str         # ceremony revision at the time the commit was written
    ratified: bool           # ground truth for derive_transition_sets' ratified set
    verdicts: list[Verdict]  # one per actor; duplicate submissions by the same actor_email overwrite in place
    source: str              # "threshold-met" | "no-eligible-ratifier"
```

Field rules:

- `ratified` is the single field `derive_transition_sets()` checks. A file whose `ratified` is `false` still counts as "ratification open"; the file exists the moment the first verdict lands, so the gate only flips when the threshold is cleared.
- `verdicts` is keyed by `actor_email` for dedupe. A second `submitRatification` call by the same actor updates the existing entry (new verdict, new comment, new `submitted_at`) instead of appending a duplicate. This is what makes the design spec's "You voted: {verdict}" state reachable on a refresh.
- `source` distinguishes the two paths a `ratified: true` flip can take. `threshold-met` is the normal path where approvals reach `speed.toml [multiplayer] ratification_threshold` via `submitRatification` calls. `no-eligible-ratifier` is the inline write `commitSpec` performs when the current roster contains no member other than the commit author; in that case `verdicts` is an empty list and `ratified` is `true` at creation time. A single-member roster always takes this path; a multi-member roster takes it only in the edge case where every non-author has left the roster between commit and ratification.
- The file is written once per `submitRatification` call and once on the inline `no-eligible-ratifier` path inside `commitSpec`. There is no background process that mutates it.

Approval count and threshold readbacks from the Design spec map directly:

```python
approval_count = sum(1 for v in ratification.verdicts if v.verdict == "approve")
has_voted      = any(v.actor_email == current_actor.email for v in ratification.verdicts)
threshold      = speed_toml["multiplayer"]["ratification_threshold"]  # 1 in default multiplayer config
```

### New path helpers

```python
def ceremony_claim(self, name: str, spec_type: str) -> Path            # claim-{spec_type}.json
def ceremony_commit_record(self, name: str, spec_type: str) -> Path    # commit-{spec_type}.json
def ceremony_decomposition(self, name: str, spec_type: str) -> Path    # decomposition-{spec_type}.json
```

`ceremony_decomposition` is only invoked for spec_types that are RFC slots; the decompose action is rejected for `prd` and `design` at the authorization layer (see Authorization Model). No `decomposition-prd.json` or `decomposition-design.json` files will ever exist on disk.

The existing single-arg `ceremony_commit_record(name)` is replaced with the two-arg form above; all callers pass the spec_type explicitly. The existing `ceremony_validation_state(name, spec_type)` and `ceremony_draft(name, spec_type)` helpers keep their signatures unchanged. The only change is that the set of valid `spec_type` values now includes `rfc-{slug}` entries, so each child RFC produces its own `validation-state-rfc-{slug}.json` and `draft-rfc-{slug}.md` without any helper rewrite. In ceremonies with a single RFC, every resulting filename is identical to today.

## API Surface

### New mutations

| Mutation | AuthZ | Description |
|----------|-------|-------------|
| `claimSpec(featureName, specType)` | Any roster member; spec must be unclaimed or stale | Writes `claim-{spec_type}.json` with the caller as claimant. Refreshes `last_activity_at`. |
| `releaseSpec(featureName, specType)` | Current claimant only | Sets `released_at` on the claim file. Subsequent `claimSpec` by any roster member is allowed. |

### Modified mutations

| Mutation | Change |
|----------|--------|
| `declareIntent(text)` | Auto-claims the PRD for the caller by writing `claim-prd.json` alongside `author_email`. |
| `updateDraft(featureName, specType, content)` | Adds `specType` parameter. Permission check becomes "caller claims `specType`." Writes `draft-{spec_type}.md`; membership in `drafted_specs` is derived from the file's existence, not from a separate bookkeeping call. |
| `generateDraft(featureName, specType)` | Adds `specType` parameter. Permission check becomes "caller claims `specType`." Writes `draft-{spec_type}.md`; membership in `drafted_specs` is derived from the file's existence. |
| `createSuggestion(featureName, specType, sectionId, text)` | Adds `specType` parameter. Persisted on the `Suggestion` record. |
| `resolveSuggestion(id, action, reason)` | Looks up the suggestion's `spec_type` and checks the caller claims it. |
| `decomposeDraft(featureName, specType)` | Adds `specType` parameter. Checks the caller claims the spec AND `specType` is an RFC slot (`"rfc"` or starts with `"rfc-"`); rejects PRD and Design slots at the resolver. Writes `decomposition-{spec_type}.json`. |
| `commitSpec(featureName, specType)` | Adds `specType` parameter. Checks the caller claims the spec. Writes `commit-{spec_type}.json`; the file's existence is the ground truth for `committed_specs` membership. After the write, re-derives the transition sets and advances the ceremony state if the gate is now met. See **Commit and auto-ratification** below for the full transition chain. |
| `submitRatification(featureName, specType, verdict, comment)` | Adds `specType` parameter. Checks the caller does NOT claim the spec. Writes or updates `ratification-{spec_type}.json`; when the verdict tally clears the threshold, the file's `ratified` field flips to `true`, which is the ground truth for `ratified_specs` membership. After the write, re-derives the transition sets and advances the ceremony state if `ratified_specs == drafted_specs`. |

### New query

| Query | Returns |
|-------|---------|
| `ceremonyClaims(featureName)` | `list[SpecClaim]` including released entries. Enumerated by listing `claim-*.json` files in the ceremony directory and deserializing each one. Powers the tab bar claim display and the progress overview. |

### Modified queries

| Query | Change |
|-------|--------|
| `commitRecord(featureName)` | Becomes `commitRecord(featureName, specType)`. Returns the per-spec commit record or null. |
| `ratificationState(featureName)` | Becomes `ratificationState(featureName, specType)`. Returns the per-spec ratification state. |

## Authorization Model

Roles are ceremony-scoped and derived from the per-spec claim files. "Claimant of spec X" is the only role concept; everything else reduces to "is the caller the claimant, or is the caller a non-claimant."

| Action | Allowed when |
|--------|--------------|
| Declare intent (creates ceremony, auto-claims PRD) | Any roster member |
| Claim a spec | Any roster member AND the spec is unclaimed or stale |
| Release own claim | Caller is the current claimant of that spec |
| Edit a spec | Caller is the current claimant of that spec |
| Create suggestion on a spec | Any roster member who is NOT the current claimant of that spec |
| Edit or delete own suggestion | Suggestion author, before resolution |
| Resolve suggestion | Caller is the current claimant of the suggestion's spec |
| Decompose a spec | Caller is the current claimant of that spec AND `spec_type` is an RFC slot (`"rfc"` or starts with `"rfc-"`). PRD and Design slots do not decompose because only RFCs produce tasks. |
| Commit a spec | Caller is the current claimant of that spec AND validation passes |
| Ratify a spec | Caller is NOT the author recorded in the spec's commit record (`commit-{spec_type}.json.claimant_email`). When the roster contains no one other than the commit author, `commitSpec` writes the ratification inline and `submitRatification` is never called. |
| Abandon the ceremony | Caller is the PRD claimant (the intent declarer) |

A sole actor is `n = 1` in this model. They claim each spec they want to edit (same button, same mutation as a team member), they pass every authorization check as the active claimant, and they commit under the normal rules. The one place a single-member roster diverges is at commit time: `commitSpec` detects that the roster has no eligible ratifier and writes `ratification-{spec_type}.json` inline. Everything else — the tab bar, the progress overview, the claim chrome — is identical to the multi-actor experience.

### Implementation: PEP, PDP, PIP

The authorization matrix above is the product contract. The implementation uses a CanCan-style single policy class with a clean separation between the three classical roles of an authorization pipeline, so the matrix maps one-to-one to code and the same rules are enforced identically from every call site. This separation is where the whole ownership model actually lives. Claims are just facts; the policy is what makes them meaningful.

**Policy Enforcement Point (PEP).** The mutation resolvers in `dashboard/backend/resolvers/ceremony_editor.py` and its siblings. Each resolver is thin: load the ability for the current request, call `authorize(action, spec_type)`, proceed on success, raise on denial. No policy logic lives in the resolver. Every protected mutation looks structurally identical:

```python
def commit_spec(feature_name: str, spec_type: str) -> CommitResult:
    ability = CeremonyAbility.for_request(feature_name)
    ability.authorize("commit", spec_type)   # raises PermissionError on deny
    # ... proceed with commit
```

Uniform PEPs make it easy to audit ("does every mutation call `authorize`?") and easy to hang observability on a single place (log every allow and deny in one hook).

**Policy Decision Point (PDP).** A single class, `CeremonyAbility`, in a new file `dashboard/backend/resolvers/ceremony_authz.py`. It holds every rule in the authorization matrix as match cases on a single `can(action, spec_type)` method. When the matrix changes, exactly one file changes.

```python
class CeremonyAbility:
    def can(self, action: str, spec_type: str | None = None) -> bool:
        match action:
            case "declare":   return True
            case "claim":     return self._unclaimed_or_stale(spec_type)
            case "release":   return self._is_active_claimant(spec_type)
            case "edit" | "resolve" | "commit":
                              return self._is_active_claimant(spec_type)
            case "decompose": return self._is_active_claimant(spec_type) and self._is_rfc_slot(spec_type)
            case "suggest":   return not self._is_active_claimant(spec_type)
            case "ratify":    return not self._is_commit_author(spec_type)
            case "abandon":   return self._is_active_claimant("prd")
            case _:           return False

    def authorize(self, action: str, spec_type: str | None = None) -> None:
        if not self.can(action, spec_type):
            raise PermissionError(f"{self.actor.email} cannot {action} on {spec_type}")

    @staticmethod
    def _is_rfc_slot(spec_type: str | None) -> bool:
        return spec_type == "rfc" or (spec_type or "").startswith("rfc-")
```

The helper methods `_is_active_claimant` and `_unclaimed_or_stale` encapsulate the claim lookup and staleness comparison. Staleness is not a special case bolted onto the policy; it is part of the definition of "active claimant." A claim whose `last_activity_at` is older than `stale_window` is treated as if the claim does not exist for AuthZ purposes, and the next `claimSpec` call writes a new claim in a single transaction.

`_is_commit_author(spec_type)` reads `commit-{spec_type}.json.claimant_email` and returns True if it matches the current actor. The ratify rule uses the commit record, not the live claim file, because `commitSpec` sets `released_at` on the claim; by ratify time the original author is no longer an "active claimant" and would otherwise pass a naive "not current claimant" check and ratify their own work. The commit record carries the immutable authorship snapshot for the revision and is the right source of truth for the ratify exclusion. If the commit record does not exist, `_is_commit_author` returns False (nothing has been committed, so nothing can be ratified anyway).

**There is no solo-mode branch in the authorization policy.** A sole actor is `n = 1` in the same multi-actor model: they claim each spec they want to edit, they pass `_is_active_claimant` because they're the only roster member who could have written the claim file, and they commit under the normal rules. The single exception to this uniformity is auto-ratification at commit time, and it is not phrased as a "solo mode" — it is a roster-side check inside `commitSpec` that asks "does the current roster contain any member who is not the commit author?" If the answer is no, `commitSpec` writes `ratification-{spec_type}.json` inline with `ratified: true` because there is no one left who could ever legitimately submit a verdict. In a single-member roster this always fires; in a multi-member roster it would also fire if, say, the only other member left the team between commit and ratify. The check is written as `_has_eligible_ratifier()` on `CeremonyState` and is called from `commitSpec`, not from `CeremonyAbility.can()` — the `ratify` authorization rule itself stays as the flat "not the commit author" check because the inline auto-write bypasses `submitRatification` entirely and never reaches the policy.

**Policy Information Point (PIP).** The loaders that supply facts to the PDP at construction time. The PDP never reads disk. `CeremonyAbility.for_request(feature_name, spec_type)` delegates to the PIP to:

1. Resolve the current actor via `get_current_actor()` (already exists in `ceremony_types.py`)
2. Load `CeremonyState` from `ceremony.json` (for the ceremony status and revision pointer only; `drafted_specs` / `committed_specs` / `ratified_specs` are derived from the filesystem, not loaded from this file)
3. Read `claim-{spec_type}.json` from disk if it exists; return `None` if it does not. Only the claim for the spec being acted on is loaded — other specs' claims are irrelevant to this request
4. Read `commit-{spec_type}.json` from disk if it exists; return `None` if it does not. This is the source for `_is_commit_author` and is only loaded when the action is `ratify` (every other action reads the live claim, not the commit record)
5. Read the ceremony roster (`.speed/shared/roster/*.json` listing) once per request. Used by `commitSpec` to evaluate `_has_eligible_ratifier()` at commit time; not consulted by the authorization policy itself. The roster is small and already cached by the foundation's roster loader, so the read is free
6. Capture a single `now` timestamp that every staleness check in this request uses (so two checks in the same request cannot disagree about whether a claim is stale)
7. Read `stale_window` from `[multiplayer]` in `speed.toml` once per request

Loading only the relevant claim is deliberate: a `claimSpec("rfc-ingestion")` call has no reason to read `claim-rfc-query.json`, and in a deeply decomposed ceremony reading every claim file on every mutation would scale poorly. The `ceremonyClaims` query is the one place that loads all of them, and it does so by listing the ceremony directory for `claim-*.json` files rather than walking a map.

If claims ever move from JSON files to a database, only the PIP changes. The PDP and the PEPs are unaffected. This is the long-term escape hatch if the file-based model stops scaling.

**Testing.** Unit tests construct `CeremonyAbility` directly with a synthetic actor, a synthetic `SpecClaim` (or `None`), and a fixed `now`, then call `can()` for each cell in the Authorization Matrix. One test file exercises the entire policy without starting GraphQL, touching disk, or running any mutation code. This is the primary regression safety net for AuthZ; the RFC's acceptance criteria for each user story should include a matching PDP unit test.

## State Machine

The ceremony state machine keeps the same five states and the same within-revision transitions. What changes is the gate condition on the two advancing transitions.

| Transition | Gated on |
|------------|----------|
| DRAFTING to COMMITTED | Every file in `draft-*.md` has a matching `commit-*.json` (derived; see Derived per-spec sets above) |
| COMMITTED to RATIFIED | Every file in `draft-*.md` has a `ratification-*.json` whose `ratified` field is `true` |
| COMMITTED to REJECTED | Any single spec has a `ratification-*.json` with a rejection verdict (conservative; can relax later) |
| DRAFTING to ABANDONED | PRD claimant initiates abandon |

All three gate checks call `derive_transition_sets()` from Derived per-spec sets above. The in-prose shorthand `committed_specs == drafted_specs` and `ratified_specs == drafted_specs` used elsewhere in this RFC refers to the comparison between those derived sets; there is no persisted state to update.

A spec is considered drafted the first time its `draft-{spec_type}.md` file is persisted through `generateDraft` or `updateDraft`. Specs that were claimed but never drafted do not block ceremony commit because they never appear in `drafted_specs`.

`VALID_TRANSITIONS`, `transition_ceremony_state()`, `create_revision()`, and the reflog are unchanged in shape. `create_revision()` handles the per-spec files on disk the same way the foundation's reflog archives `commit.json` today — file by file — and leaves the `claim-{spec_type}.json` files in place. Claims persist across revisions by default; if a revision is created after a spec commits, the committing claimant retains their active claim on the new revision unless they explicitly release or go stale. This matches the single-author amendment flow in the parent ceremony, where the same author drives consecutive revisions without re-claiming.

Ceremony-wide revision identity remains content-addressed over the aggregate spec content hash, context package hash, validation hash, and parent ID. Per-spec commits and ratifications are runtime overlays on the current revision; they do not participate in the revision hash.

**Transitions are atomic with the per-spec action that caused them.** When `commitSpec` writes the last remaining per-spec commit record, the same server-side transaction also transitions the ceremony from DRAFTING to COMMITTED. The ceremony advances to RATIFIED only when `ratified_specs == drafted_specs`; that transition happens either inside `submitRatification` (when a non-author verdict clears the threshold) or inside `commitSpec` itself (when no eligible ratifier exists and the ratification file is written inline). See the next subsection for the inline path.

### Commit and auto-ratification when no eligible ratifier exists

The authorization rule for `submitRatification` is "caller is not the commit author." In a roster with exactly one member that member is always the commit author of anything they commit, so no one on the roster can ever satisfy the ratify rule and the ceremony would be stuck. The same situation can arise — rare but possible — in a multi-member roster when every member other than the commit author has been removed from the roster between commit and ratify. The RFC treats both cases identically: if the current roster contains no member who is not the commit author, `commitSpec` writes the ratification inline, in the same transaction, and `submitRatification` is never called.

Server-side sequence for `commitSpec(featureName, specType)`:

1. `authorize("commit", specType)` — succeeds because the caller is the claimant.
2. Write `commit-{spec_type}.json` and update `claim-{spec_type}.json` (`released_at = committed_at`) in one transaction. The commit file's existence is the ground truth for `committed_specs`.
3. Re-derive `(drafted_specs, committed_specs, ratified_specs)` from the filesystem. If `committed_specs == drafted_specs`, transition DRAFTING to COMMITTED via `transition_ceremony_state()`.
4. Evaluate `_has_eligible_ratifier()`: load the roster, count members whose email is not `commit-{spec_type}.json.claimant_email`. If the count is zero, write `ratification-{spec_type}.json` with `ratified: true`, `verdicts: []`, and `source: "no-eligible-ratifier"` directly, without calling `submitRatification` and without constructing a verdict record. The file is the ground truth for `ratified_specs`.
5. Re-derive the sets again. If `ratified_specs == drafted_specs`, transition COMMITTED to RATIFIED in the same transaction.

In a single-member roster, step 4 always fires and the caller sees DRAFTING to RATIFIED in a single `commitSpec` round trip. In a multi-member roster with at least one non-author, step 4 is a no-op and ratification proceeds through the normal `submitRatification` path. The check is the same code in both cases; the ceremony doesn't know or care whether it is "single-player."

The check is inlined into `commitSpec` rather than made a separate mutation for the same reason it was inlined before: wiring ratification through a recursive `submitRatification` call would require the server to synthesize a verdict record that bypasses the "not author" rule, which is exactly what the inline write avoids. Inlining keeps the contract "one mutation, one round-trip, final state returned."

## UI Contract

See the [design spec](../design/speed-define-ceremony-ownership.md) for the full UI contract: tab bar affordances (claim badge, Claim/Release/Takeover buttons, stale indicators), Progress Overview panel, commit bar modes, read-only editor treatment, SuggestionPopover, state matrices, keyboard navigation, and accessibility rules. The prototype at [working-docs/prototype-speed-define-ceremony-ownership.html](../../working-docs/prototype-speed-define-ceremony-ownership.html) is the visual reference for every state.

This RFC covers only the backend contract the UI consumes:

- Every UI affordance either maps to a mutation listed in the API Surface section above (`claimSpec`, `releaseSpec`, `updateDraft`, `resolveSuggestion`, `decomposeDraft`, `commitSpec`, `submitRatification`) or a read from a file listed in the Data Model section (`claim-{spec_type}.json`, `commit-{spec_type}.json`, `ratification-{spec_type}.json`, `validation-state-{spec_type}.json`, `draft-{spec_type}.md`)
- The Progress Overview is populated by the `ceremonyClaims` query plus filesystem listings of per-spec artifacts. No new query is needed for the overview itself — it composes over existing reads
- The UI is identical regardless of roster size. There is no "solo mode" client flag. A sole actor sees the same tab bar, claim chrome, progress overview, and commit bar as a multi-actor ceremony — they are simply the only roster member, so claimed-by-other and stale states never appear for them naturally
- Mutations are optimistic per the design spec. The server enforces authorization via `CeremonyAbility` and returns a structured `PermissionError` the UI maps to the design spec's disabled-with-reason captions

## Validation Rules

Input constraints enforced at the resolver layer before any file is written. Every row here should map to at least one test.

| Field | Constraints |
|-------|-------------|
| `specType` (input to all mutations) | Non-empty string matching `^(prd|design|rfc|rfc-[a-z0-9-]+)$`. Reject other values with `ValueError("invalid spec_type: {value}")`. |
| `specType` (decompose only) | Must pass `CeremonyAbility._is_rfc_slot(spec_type)` — equals `"rfc"` or starts with `"rfc-"`. PRD and Design slots are rejected with `PermissionError("decompose not allowed on {spec_type}")`. |
| `featureName` | Must match an existing ceremony directory. Reject with `NotFoundError`. |
| `SpecClaim.claimant_email` | Must match a recognized actor per `get_current_actor()`. No guest actors. |
| `SpecClaim.claimed_at`, `last_activity_at`, `released_at` | ISO 8601 UTC timestamps. `last_activity_at >= claimed_at`. `released_at == null` or `released_at >= last_activity_at`. |
| `SpecClaim` staleness | `now - last_activity_at > stale_window` computed through `lib/ownership.sh`, not a new implementation. |
| `Suggestion.spec_type` | Must match an existing drafted spec or a spec whose tab exists in the ceremony. Dangling suggestions (spec_type has no draft) are rejected at creation. |
| `claimSpec` preconditions | Target spec must be unclaimed OR existing claim must be stale. Otherwise reject with `PermissionError("spec already claimed by {current.claimant}")`. |
| `releaseSpec` preconditions | Caller must be the current claimant. Otherwise reject. Releasing an already-released claim is a no-op, not an error. |
| `commitSpec` preconditions | Caller must be the current claimant AND validation state must be passing for this `spec_type`. Validation is read from `validation-state-{spec_type}.json`; if the file is missing or reports failures, commit is rejected with the existing commit-validation error. |
| `decomposeDraft` preconditions | All three of: caller is claimant, `spec_type` is an RFC slot, draft exists at `draft-{spec_type}.md`. |
| `submitRatification` preconditions | Caller's email must NOT match `commit-{spec_type}.json.claimant_email`. The spec must already be committed (`commit-{spec_type}.json` exists). Verdict must be `"approve"` or `"reject"`. Reject verdict requires a non-empty comment (enforced at resolver, not client). In rosters where no member other than the commit author exists, `submitRatification` is never called because `commitSpec` writes the ratification inline; this precondition therefore only runs in multi-actor rosters. |
| Concurrent `claimSpec` calls | Server uses a file-lock on `claim-{spec_type}.json` to serialize. Two simultaneous claims on the same unclaimed spec: one wins, one receives `PermissionError` with the winner's name. No optimistic lock versioning needed because claims are not content-hashed. |
| Authorization before write | Every protected mutation MUST call `CeremonyAbility.authorize(action, spec_type)` before any file write. Audit tests enforce this via a grep-based check over the resolver files. |

## Testing

### Acceptance Criteria

Each PRD user story maps to verifiable behavior. The PRD owns the Given/When/Then text; this RFC maps them to concrete assertions the test layer can check. Story IDs match `specs/product/speed-define-ceremony-ownership.md`.

| Story ID | Verification |
|----------|--------------|
| O1 (PM claims PRD) | `claimSpec(featureName, "prd")` writes `claim-prd.json` with the caller as claimant, the tab bar `ceremonyClaims` query includes the new claim, and the PM can fire `updateDraft`, `resolveSuggestion`, and `commitSpec` on `"prd"` without `PermissionError`. A second actor firing the same mutations on `"prd"` is denied. |
| O2 (parallel Design claim) | After O1, `claimSpec(featureName, "design")` by a different actor succeeds. `claim-prd.json` is unchanged. Both claims have independent `last_activity_at` timestamps. |
| O3 (parallel RFC claim) | A third actor can `claimSpec(featureName, "rfc")` while `draft-prd.md` exists and is being edited. The RFC claim file is written; the PRD claim is unaffected. |
| O4 (non-claimant suggestions) | `createSuggestion(featureName, "rfc", ...)` by a non-claimant of the RFC succeeds. The Suggestion record carries `spec_type: "rfc"`. `commitSpec` on the RFC returns a response that includes the unresolved-suggestion count but does not block. |
| O5 (claimant resolves suggestion) | `resolveSuggestion(id, "accept")` by the RFC claimant succeeds. The same call by a non-claimant of the RFC is denied with `PermissionError`. Suggestion state transitions visible to every reader via `ceremonyClaims` and the Suggestion query. |
| O6 (independent decompose + commit) | `decomposeDraft(featureName, "rfc")` by the RFC claimant writes `decomposition-rfc.json`. `commitSpec(featureName, "rfc")` writes `commit-rfc.json` and retires the claim. Sibling specs (`prd`, `design`) remain in DRAFTING. Decomposing `"prd"` or `"design"` is rejected. |
| O7 (progress overview) | `ceremonyClaims` returns one entry per claim file on disk, including released ones. Filesystem listing produces `drafted_specs`, `committed_specs`, `ratified_specs` consistent with the per-spec files. |
| O8 (independent ratification) | After `commitSpec("prd")` by actor A, `submitRatification(featureName, "prd", "approve")` by actor B (whose email does not match `commit-prd.json.claimant_email`) succeeds and advances `"prd"` to ratified while `"rfc"` remains in DRAFTING. Actor A calling the same mutation on their own committed spec is rejected with `PermissionError` matching "cannot ratify own spec." In a single-member roster `submitRatification` is never called — `commitSpec` writes `ratification-{spec_type}.json` inline with `source: "no-eligible-ratifier"`. Ceremony state stays COMMITTED until every drafted spec is ratified. |
| O9 (stale takeover) | A claim older than `stale_window` can be replaced by any roster member via `claimSpec`. The old file's `released_at` is set to `now`, the new file is written, both within one transaction. The old claimant's draft content is preserved. |
| O10 (sole actor uses the same flow) | A sole roster member declares intent (auto-claims PRD), clicks Claim on Design, drafts it, clicks Claim on RFC, drafts it, then commits each in turn. The tab bar, progress overview, and commit bar render identically to a multi-actor ceremony. Backend verifies: `commitSpec` on each spec writes `ratification-{spec_type}.json` with `source: "no-eligible-ratifier"` inline because the roster has no member other than the commit author, and the ceremony advances DRAFTING → COMMITTED → RATIFIED in a single call on the last commit. |

### Risks and Coverage

See the Risks section below for the full table. Test approach derives from each risk:

| Risk | Test approach |
|------|---------------|
| Claimant goes dark mid-ceremony | Unit test: construct a `SpecClaim` with `last_activity_at = now - 61min`, `stale_window = 60min`, assert `CeremonyAbility._unclaimed_or_stale()` returns True. Integration test: stale takeover writes new claim and preserves draft content. |
| Wrong role claims a spec | No automated test — this is a social risk mitigated by Release + suggestions, not enforced by code. Documented in the Drawbacks section. |
| Per-spec commit creates temporary inconsistency | Integration test: commit PRD, assert ceremony state is still DRAFTING. Commit RFC, assert ceremony state advances to COMMITTED only when all drafted specs are committed. |
| Implicit reviewer quality bar | No automated test — it's a process risk. Acceptance tests ensure suggestions do not block commit; documentation warns about the trade-off. |
| Claim goes stale during a commit transaction | Unit test: mock `now()` to return stale-window-plus between the authorization check and the file write inside `commitSpec`. Assert the commit still succeeds because validity is checked once at the start, not again during the write. |
| Drafted-specs derivation drifts from reality | Unit test: create draft files in a temp directory, assert `derive_transition_sets()` returns the expected drafted set. Integration test: `commitSpec` then `derive_transition_sets()` reflects the new commit file. |
| Authorization bypass via a missed `authorize` call | Grep-based lint: every resolver function whose name maps to a protected action must contain a call to `CeremonyAbility.authorize(...)`. Enforced by a test that introspects the resolver module. |
| `CeremonyAbility` policy drift from the documented matrix | Unit test per authorization matrix row. Construct synthetic claim state, call `.can(action, spec_type)` for each cell, assert expected allow/deny. One test per matrix row, no coverage gaps. |

### Test Plan

**Unit tests**

- `CeremonyAbility.can()` matrix — one test per row of the authorization matrix, constructed with synthetic actors and claim files, no disk or GraphQL. This is the primary regression safety net for authorization.
- `CeremonyAbility._is_rfc_slot()` — table test for `"prd" → False`, `"design" → False`, `"rfc" → True`, `"rfc-foo" → True`, `"rfcfoo" → False`, `"" → False`, `None → False`.
- `derive_transition_sets()` — table test creating a ceremony directory with various combinations of draft/commit/ratification files and asserting the returned sets.
- Staleness comparison — delegate to `lib/ownership.sh`'s existing tests; add a new test that `CeremonyAbility._unclaimed_or_stale()` uses the same path.
- Per-spec path helpers — `ceremony_claim`, `ceremony_commit_record`, `ceremony_decomposition` produce expected paths for simple and child-RFC slot inputs.
- Validation rules per the Validation Rules table — one test per row.

**Integration tests**

- Full claim lifecycle: `claimSpec` → `updateDraft` → `resolveSuggestion` → `commitSpec`, across all three single-ceremony spec types, with multiple actors.
- Stale takeover: advance clock past `stale_window`, assert `claimSpec` by a new actor succeeds and releases the old claim in one transaction.
- Multi-RFC decomposition: create a feature with four child RFCs (`rfc-a`, `rfc-b`, `rfc-c`, `rfc-d`), claim each with a different actor, assert all claims coexist, commit each independently, assert ceremony advances only when all are committed.
- Sole-actor auto-ratification: with roster size 1, commit a spec and assert `ratification-{spec_type}.json` is written inline within the same `commitSpec` call with `source: "no-eligible-ratifier"` and the ceremony state advances past COMMITTED to RATIFIED.
- Sole-actor claim flow: with roster size 1, `declareIntent` auto-claims PRD; the actor must then call `claimSpec("design")` and `claimSpec("rfc")` explicitly before firing `updateDraft("design", ...)` or `updateDraft("rfc", ...)`. Attempting `updateDraft("design", ...)` before `claimSpec("design")` must raise `PermissionError` — solo actors follow the same claim path as any other roster member. There is no implicit-claim-on-edit fallback.
- Non-author departs mid-ceremony: roster starts with two actors A and B. A commits the PRD. B is removed from the roster. Assert the next `commitSpec` call on another spec still by A triggers `_has_eligible_ratifier() == False`, writes the ratification inline with `source: "no-eligible-ratifier"`, and the ceremony advances to RATIFIED. The same code path that single-actor rosters exercise also catches this edge case.
- Authorization denial: non-claimant attempts `updateDraft`, `resolveSuggestion`, `decomposeDraft`, `commitSpec` — each returns `PermissionError` with the expected message.
- Committer cannot ratify own spec: actor A commits the PRD; actor A then calls `submitRatification(featureName, "prd", "approve")` and must receive `PermissionError` because `commit-prd.json.claimant_email` matches. A different actor (B) making the same call succeeds.
- Concurrent claim collision: two simultaneous `claimSpec` calls on the same unclaimed spec — one succeeds, one fails with a clear error.

**End-to-end tests**

- Multiplayer ceremony: two browsers, one claims PRD, the other claims RFC, each commits independently, ratification runs with each actor ratifying the other's spec.
- Non-claimant read-only: open a tab claimed by someone else, verify editor is read-only, suggestion popover appears on selection, commit button is disabled with reason.
- Stale takeover UX: fast-forward clock (or use a short stale window in test config), verify the tab transitions to stale state, the Takeover button appears, and clicking it transfers the claim.
- Sole-actor ceremony: open a ceremony as the sole roster member, verify the tab bar, progress overview, and commit bar render identically to a multi-actor ceremony (full Claim/Release chrome is present). Click Claim on Design and RFC, draft and commit each, and verify the final `commitSpec` advances ceremony state through COMMITTED to RATIFIED in one round trip.

**Visual/UI tests**

- Tab bar state snapshots: one per claim state (mine, claimed-by-other, stale, unclaimed, committed). Five snapshots covering the 1280px viewport.
- Progress Overview snapshot: the single 5-column layout regardless of roster size.
- Read-only editor banner: standard and stale variants.

### Edge Cases

- Claim expires at the exact second of `stale_window` boundary. Test with `now - last_activity_at == stale_window` (not strictly greater) and assert the claim is still considered active (`>` not `>=` in `_unclaimed_or_stale`).
- Concurrent claim race between two actors at `ms` precision. File lock must serialize; loser gets `PermissionError` with winner's name.
- Claiming a spec that has never been drafted (no `draft-{spec_type}.md` on disk yet). The claim file is written successfully; the spec is claimable before it is drafted.
- Drafting a spec before claiming it. `updateDraft` and `generateDraft` require a prior claim — a draft cannot appear without a claimant. If the claim exists but is stale, these mutations are denied.
- Creating a revision (`create_revision()`) while a claim is stale. The stale claim file is left in place on disk; the new revision does not inherit the stale state, and the next `claimSpec` takes over cleanly.
- Resolving a suggestion whose `spec_type` no longer exists on disk (e.g., the claim was released and no new claimant took over, deleting intermediate state). The Suggestion record carries its own `spec_type` and remains routable as long as a claim file can be read or reconstructed.
- Commit happens and simultaneously another actor takes over the claim as stale. Commit transaction checks authorization at its start and proceeds atomically; stale takeover happens either fully before (blocks the commit with a denial) or fully after (runs against the new claimant's state). No partial state.
- Sole actor in a single-member roster calls `submitRatification` directly on their own committed spec. Rejected with `PermissionError` — the inline write inside `commitSpec` is the only path that can ratify when no eligible non-author exists, and the authorization rule on `submitRatification` itself makes no exception. In practice the UI never surfaces a ratify affordance for the committer, so the caller would have to hit the mutation manually to reach this error.
- Per-spec commit while the ceremony is in REJECTED state from a prior revision. `transition_ceremony_state()` validates the target transition, so `commitSpec` is rejected until a new revision is created. The error message must explain the ceremony is not in DRAFTING.
- Ratification verdict submitted on a spec whose `claim-{spec_type}.json` was never written (edge case: a spec was committed via migration from the pre-ownership model). Ratify authorization always reads from `commit-{spec_type}.json.claimant_email`, so a missing live claim file has no effect on the check; this edge case resolves naturally through the general rule.

### Out of Scope (for testing)

- **Load testing for ceremonies with hundreds of specs.** A ceremony with 50+ drafted specs is outside realistic use; decomposition sizing flags features that large long before they become ceremonies.
- **Distributed clock skew between actors.** Single repo, single filesystem — clocks are consistent enough from `git config` and `get_current_actor()`. If the clock issue becomes real, the UTC-safe comparison path in `lib/ownership.sh` is the single patch point per the existing open defect.
- **Cross-machine file locking.** The file lock on `claim-{spec_type}.json` uses `fcntl` semantics and is only correct on a local filesystem. NFS / cloud-backed filesystems are out of scope; they already break every multiplayer assumption in SPEED.
- **Real-time collaborative editing of a single spec by two actors.** Excluded by design. One claimant per spec; there is no code path to test.
- **Byzantine actors forging event log entries to fake a stale takeover.** The event log is append-only and authenticated via git identity; tampering is out of scope for this RFC.

## Security & Controls

See the [PRD's Security & Controls section](../product/speed-define-ceremony-ownership.md#security--controls) for the full product contract. This RFC implements it:

- **Authentication** — reuses the existing actor resolution chain (`$SPEED_ACTOR` → `git config user.name` → `whoami`). No new auth layer.
- **Authorization** — every protected mutation routes through `CeremonyAbility.authorize(action, spec_type)` before any file write. The policy class is the single source of truth for the Authorization Model table above. Audit enforcement: a grep-based test asserts every resolver in `dashboard/backend/resolvers/ceremony_editor.py` whose name maps to a protected action contains an `authorize(...)` call. Bypass is a test failure, not a runtime possibility.
- **Audit logging** — every claim lifecycle event (`claim_started`, `claim_refreshed`, `claim_released`, `claim_committed`, `claim_stale_takeover`) is written to the multiplayer event stream at `.speed/shared/events/` with the same schema the existing feature-claim events use. No new log pipeline.
- **Data sensitivity** — claim files contain only actor name, email, and timestamps. No new PII beyond what `get_current_actor()` already exposes. Nothing is transmitted externally.
- **Surprise-action mitigation** — stale takeover is always a deliberate user action (explicit click), never a background sweeper. The stale clock is lazy per the Claim Lifecycle section.

## Key Decisions

| Decision | Choice | Alternatives considered | Rationale |
|----------|--------|------------------------|-----------|
| Where do claims live on disk? | Per-spec `claim-{spec_type}.json` files | (a) Claims map inside `ceremony.json`. (b) Single `claims.json` aggregate file. | Per-spec files match every other ceremony artifact (draft, commit, ratification, validation state). They isolate write contention (two actors claiming different specs don't touch the same file), match the event-sourcing pattern used elsewhere in multiplayer, and keep the claim physically next to its spec's other artifacts. The map-in-ceremony.json approach serializes every claim mutation on a ceremony.json rewrite, which is exactly the contention we're trying to avoid. |
| How are `drafted_specs` / `committed_specs` / `ratified_specs` represented? | Derived on demand from filesystem listings | Stored as sets on the `Revision` dataclass inside `ceremony.json`. | Same argument as claim storage: stored sets duplicate filesystem state and invite drift. Derivation is cheap (a handful of files per ceremony) and structurally impossible to drift because the filesystem is the single source of truth. This also means `create_revision()` does not need to reset the sets — archiving per-spec files is the reset. |
| Unified name for the slot discriminator? | Keep `spec_type`, expand its value set | Rename to `spec_id` and introduce a new "broad category" `spec_type` field. | The existing codebase already uses `spec_type` as the file-naming discriminator. Renaming it to `spec_id` and repurposing `spec_type` for a coarser category caused multiple name-drift bugs during RFC review. Letting `spec_type` hold `"rfc-{slug}"` as additional valid values keeps every existing helper signature and filename unchanged. The "broad category" is a one-line derivation (`"rfc" if spec_type.startswith("rfc") else spec_type`), not a stored field. |
| Where does authorization live? | Single `CeremonyAbility` PDP class with `can()` and `authorize()` | Scatter authorization checks across each resolver. | A single policy class maps the authorization matrix to code one-to-one. When the matrix changes, exactly one file changes. Scattered checks are where authorization drift lives, and every new mutation is a chance to forget a check. |
| How is `CeremonyAbility` constructed? | PEP/PDP/PIP separation with `CeremonyAbility.for_request(feature, spec_type)` | Inline policy reads from disk inside each resolver. | The PDP never reads disk; the PIP supplies facts. If claims move from JSON files to a database, only the PIP changes. Same pattern used in production authorization frameworks. |
| Where does auto-ratification happen when no eligible ratifier exists? | Inlined into `commitSpec` as a direct write to `ratification-{spec_type}.json` | Call `submitRatification` recursively from `commitSpec`. | Recursive mutation calls require the server to synthesize a verdict record bypassing the "not commit author" rule, which is exactly the check the inline write sidesteps. Inlining keeps the contract "one mutation, one round-trip, final state returned" and avoids a second code path that depends on mutation composition. The same inline path covers both single-member rosters and multi-member rosters that have lost every non-author between commit and ratify. |
| Does decompose apply to every spec slot or only RFCs? | RFC slots only | Allow decomposing any claim, leave PRD / Design decompositions as empty task lists. | Only RFCs produce tasks in SPEED. Allowing `decomposeDraft("prd")` creates a file that has no meaning and confuses downstream consumers. Narrowing it to RFC slots in the authorization matrix makes the contract explicit. |
| Does the sole-actor UI differ from multiplayer? | No — same tab bar, same claim buttons, same progress overview | Hide Claim/Release and the progress overview columns when the roster has one member. | Solo users are `n = 1` of the same model, not a separate mode. Clicking Claim on Design and RFC is two clicks per ceremony they wouldn't have had before, but it (a) prepares them for the moment a teammate joins without introducing new UI, (b) deletes an entire parallel rendering path (`SoloCollapseBoundary`, `soloMode` props, 3-column progress variant, "never rendered in solo" carve-outs) from the codebase, and (c) matches the Figma-style premise that the individual experience is the same canvas as the team experience, just with fewer cursors on it. The one functional difference — auto-ratification at commit — is framed as "no eligible ratifier" rather than "solo mode" and applies to any roster where everyone except the commit author has left. |
| `/define/:feature/review` route? | Retire it; ratification is inline on the ceremony page | Keep a separate review route per the original design. | Per-spec ratification makes a single route unable to represent "PRD ratified, RFC still drafting." The editor is already the single surface for claimant and non-claimant modes; adding ratification as a third mode on the same surface is simpler than routing people to a separate URL that only shows a subset of the ceremony. |

## Drawbacks

Every design choice trades something. The honest list:

- **Stale claim takeover can surprise the original claimant.** Someone stepping away for an hour and returning finds their work locked. The draft content is preserved so it's not lost, but the social dynamic of "this was mine" is broken. Mitigation is the event log (the takeover is visible) and the `ClaimHistoryPanel` UI, but neither eliminates the surprise.
- **Sole actors pay two extra clicks per ceremony.** With the unified model, a single-member roster has to click Claim on Design and Claim on RFC before editing each one (the PRD is still auto-claimed by `declareIntent`). This is two more clicks than today's single-author ceremony. The trade is consistency across roster sizes and the code simplification that comes with it; teams that grow from a single user into a pair of collaborators do not cross a new UI boundary.
- **Five per-spec file types (draft, claim, commit, ratification, validation-state) live alongside each other in one ceremony directory.** For a decomposed ceremony with six specs, that's 30 files in one directory. The directory becomes harder to scan for humans doing forensics; grep-ability of the filesystem degrades.
- **Authorization is file-based and not transactional across specs.** A resolver that needs to enforce cross-spec invariants (e.g., "cannot commit the RFC unless the PRD is at least in draft state") has to compose multiple file reads and cannot rely on a transactional view. The scope deliberately leaves cross-spec dependency enforcement out, but if it's needed later, the current design makes it awkward to add.
- **The PDP/PEP/PIP pattern is heavier than strictly necessary for the current scale.** Every mutation has the same three-step dance (load ability, authorize, proceed). A smaller codebase could inline the checks. The pattern pays off if authorization complexity grows or if claims move off disk, but it is a cost now for a benefit later.
- **Non-claimant reviewers have no formal sign-off mechanism.** Review is "leave a suggestion and hope the claimant resolves it." Teams that want enforced review need to use ratification, which introduces a separate gate with its own UX overhead. The middle ground (suggestions that block commit) was deliberately excluded.
- **The stale window (`stale_window` in `speed.toml`) is a single value shared with feature-level claims.** A team that wants a longer stale window for ceremonies (e.g., "PRDs take a week, don't expire them in an hour") has to change the value globally, affecting `speed claim` behavior for the whole feature. Per-ceremony stale windows would require a new config knob.
- **Progress Overview updates are not real-time.** The UI refetches `ceremonyClaims` on tab activation or claim mutation, not on a websocket push. If two actors are working in parallel, each sees the other's state at refresh time, not instantaneously. Polling or push is out of scope for this RFC.

## Migration

Existing ceremonies have no `claim-{spec_type}.json` files and no per-spec commit records. The migration runs on first load and is idempotent: every step guards on the presence of its output file so re-running the migration on an already-migrated ceremony is a no-op.

1. For each drafted spec in the ceremony, write a `claim-{spec_type}.json` file containing a `SpecClaim` with `claimant_email = ceremony.author_email`, `claimant = ceremony.author`, `claimed_at = ceremony.created_at`, `last_activity_at = ceremony.updated_at`, `released_at = null` (or `ceremony.committed_at` if a `commit.json` exists), and `spec_type` set to the slot the draft occupies. **Idempotency guard:** skip the write if `claim-{spec_type}.json` already exists, regardless of its content. This prevents the migration from clobbering `last_activity_at` refreshes or mid-flight edits on a re-run.
2. For each suggestion in `suggestions.json` without a `spec_type` field, default to `"prd"`. Pre-migration ceremonies have PRDs in practice; the default is correct in every case we have on disk. **Idempotency guard:** skip any suggestion that already has a populated `spec_type`.
3. If `commit.json` exists, **transform** it into per-spec `commit-{spec_type}.json` files. This is not a straight copy — the new `CommitRecord` renamed fields and split `spec_paths: list[str]` into one `commit-{spec_type}.json` per entry:
    - `author` → `claimant`
    - `author_email` → `claimant_email`
    - `spec_paths: list[str]` → one output file per path, each with `spec_path: str` set to that single path
    - `spec_type`: derived from the path (e.g., `specs/product/{name}.md` → `"prd"`, `specs/design/{name}.md` → `"design"`, `specs/tech/{name}.md` → `"rfc"`, `specs/tech/{name}-{slug}.md` → `"rfc-{slug}"`)
    - `revision_id`, `committed_at`, `validation_state_ref`, `context_package_ref`, `suggestion_history`, `is_multiplayer`, `ratification_threshold`, `ratification_status` — copied verbatim
    - `decomposition_ref`: set to `"decomposition-{spec_type}.json"` for RFC slots if `decomposition.json` exists at the feature root; otherwise `null`
    - `suggestion_history`: filtered to entries where `suggestion.spec_type` matches this commit's spec_type after step 2's default is applied

    Also transform the legacy ratification state into per-spec `ratification-{spec_type}.json` files. If the legacy `commit.json.ratification_status == "not_required"` (sole-author ceremonies), write one `Ratification` per transformed commit with `ratified: true`, `verdicts: []`, `source: "no-eligible-ratifier"`. If `ratification_status == "approved"`, replay the verdict events from `.speed/shared/events/` filtered by feature name into each per-spec `Ratification.verdicts` array with `ratified: true` and `source: "threshold-met"`. If `ratification_status == "pending"`, write the same but with `ratified: false`. If `"rejected"`, write with `ratified: false` and the rejection verdict in the array.

    Leave the old `commit.json` in place for one release cycle to give rollback a landing pad, then remove it. **Idempotency guard:** skip the transform if every target `commit-{spec_type}.json` already exists for the paths listed in the legacy record.
4. Migration does not create, modify, or remove `ceremony.json`. The ceremony-level state machine is unchanged in shape by this RFC, so existing ceremonies resume in their current state and the per-spec derived sets are populated from the files written in steps 1-3.

No changes to the ceremony state machine are required for migration. Existing ceremonies resume in their current state; the per-spec sets are populated from the migrated commit records.

## Dependencies

| Dependency | Notes |
|------------|-------|
| Roster (`.speed/shared/roster/`) | Already exists. Used to validate claimants are recognized actors. |
| Per-spec validation state | Already on disk at `validation-state-{spec_type}.json` via `ceremony_validation_state(name, spec_type)`. |
| `get_current_actor()` | Already returns `(name, email)` with the documented fallback chain. Email-based ownership already works in the foundation. |

The Identity RFC is not listed. It is already merged into the foundation; its functions and fields are available.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| A claimant goes dark mid-ceremony and blocks progress | Medium | Claim goes stale after 60 minutes of inactivity (the shared `[multiplayer] stale_window`). Any roster member can re-claim after that. See the Claim Lifecycle subsection for the full reset rules. |
| Wrong role claims a spec (e.g., an engineer claims the Design spec) | Low | Claims are reversible via Release, and the wrong claimant usually self-corrects after non-claimants leave suggestions asking "are you sure you want to write this?" |
| Per-spec commit creates temporary inconsistency where the PRD is committed but the RFC is drafting | Medium | Ceremony state stays DRAFTING until all drafted specs are committed. `speed plan` gates on ceremony state, not per-spec state. |
| Implicit reviewer quality bar | Medium | Non-claimants leave suggestions, claimants resolve. Teams that want a formal sign-off use ratification, which already excludes claimants. |
| Claim goes stale between the start and end of a commit transaction | Low | Commit is atomic on the server. The claim validity is checked once at the start of `commitSpec`; if it was valid then, the commit proceeds regardless of staleness during the write. |
| Drafted-specs set drifts from the filesystem, causing the COMMITTED gate to trigger unexpectedly | Low | `drafted_specs` is derived from `draft-*.md` directory listing at check time, not stored separately. Drift is structurally impossible: the only way a spec is "drafted" is if its file exists. `generateDraft` and `updateDraft` are the only mutations that create those files. |

The test approach per risk is in [Testing > Risks and Coverage](#risks-and-coverage).

## File Impact

### New files

| Path | Purpose |
|------|---------|
| `dashboard/backend/resolvers/ceremony_authz.py` | `CeremonyAbility` policy class (PDP + `.for_request()` PIP). Single source of authorization truth. |
| `dashboard/backend/resolvers/ceremony_claims.py` | New resolver module for `claimSpec`, `releaseSpec`, `ceremonyClaims`. Kept separate from `ceremony_editor.py` to avoid bloating the existing editor resolver file. |
| `dashboard/backend/resolvers/ceremony_derive.py` | `derive_transition_sets(feature_name)` helper. Called from `commitSpec`, `submitRatification`, and the state-machine gate checks. |
| `lib/paths.py` — new methods on `SpeedPaths` | `ceremony_claim(name, spec_type)`, `ceremony_commit_record(name, spec_type)`, `ceremony_decomposition(name, spec_type)`. The existing single-arg `ceremony_commit_record(name)` is replaced. |
| `dashboard/frontend/components/define/ceremony/ownership/` — directory | New directory for all ownership components listed in the design spec's Component Inventory. Individual files: `TabClaimBadge.tsx`, `ClaimButton.tsx`, `ReleaseButton.tsx`, `TakeoverButton.tsx`, `StaleBadge.tsx`, `ProgressOverview.tsx`, `ProgressRow.tsx`, `ProgressSummary.tsx`, `ReadOnlyBanner.tsx`, `SuggestionPopover.tsx`, `CommitBarScope.tsx`, `RatifyControl.tsx`, `ClaimHistoryPanel.tsx`. |
| `tests/unit/test_ceremony_authz.py` | One test per cell in the authorization matrix, plus `_is_rfc_slot()` and `_unclaimed_or_stale()` tables. |
| `tests/unit/test_ceremony_derive.py` | Table tests for `derive_transition_sets()` across filesystem states. |
| `tests/unit/test_ceremony_claims.py` | Claim lifecycle: claim / release / stale / takeover in unit form. |
| `tests/integration/test_ceremony_ownership_flow.py` | End-to-end resolver flow exercising the PRD's user stories O1-O10. |
| `tests/e2e/ceremony-ownership.spec.ts` | Playwright specs for multi-actor claim UI, read-only review, stale takeover, and sole-actor unified flow (same chrome, inline auto-ratification). |
| `.speed/shared/features/*/ceremony/claim-{spec_type}.json` | New runtime artifacts. One per claimed spec per ceremony. Not checked in as fixtures. |
| `.speed/shared/features/*/ceremony/ratification-{spec_type}.json` | New runtime artifacts replacing the single ratification record. |

### Modified files

| Path | Change |
|------|--------|
| `dashboard/backend/resolvers/ceremony_editor.py` (existing) | `updateDraft`, `generateDraft`, `decomposeDraft`, `commitSpec` gain `spec_type` parameter and call `CeremonyAbility.authorize(...)` before any write. The two decomposition read/write sites at `ceremony_editor.py:266` and `:540` pass `spec_type` to the new `ceremony_decomposition()` path helper. |
| `dashboard/backend/resolvers/commit.py` (existing) | `commitSpec` extended with the inline auto-ratification sequence described in State Machine > Commit and auto-ratification. Writes `ratification-{spec_type}.json` inline when `_has_eligible_ratifier()` returns False, regardless of whether the cause is a single-member roster or a multi-member roster that lost its non-authors. |
| `dashboard/backend/resolvers/ratification.py` (existing) | `submitRatification` gains `spec_type` parameter; non-claimant check uses `CeremonyAbility`. |
| `dashboard/backend/resolvers/suggestions.py` (existing) | `createSuggestion` gains `spec_type` parameter; `resolveSuggestion` looks up the suggestion's `spec_type` and routes the authorization check through `CeremonyAbility`. |
| `dashboard/backend/types.py` (existing) | `Suggestion` type gains `spec_type: str` field. `CommitRecord` type reshaped per the Data Model section. `CeremonyState` loses nothing but is documented as not containing claims. |
| `dashboard/frontend/components/editor/EditorTabs.tsx` (existing) | Ceremony mode renders `TabClaimBadge` per tab. Tab label rendering unchanged for non-ceremony modes. Per-tab suggestion notification dot added. |
| `dashboard/frontend/components/editor/IntelPanel.tsx` (existing) | Ceremony mode mounts `ProgressOverview` as the first section above the existing context package sections. |
| `dashboard/frontend/components/define/ceremony/CommitBar.tsx` (existing) | Extended with mode-aware scoping, disabled-with-reason treatment, and the Commit ↔ Ratify cross-fade. |
| `dashboard/frontend/components/define/ceremony/CeremonyLayout.tsx` (existing) | Mounts the ownership tab chrome and progress overview unconditionally. No roster-size branching — the layout is identical for every ceremony. |
| `dashboard/frontend/lib/graphql/mutations/ceremony.ts` (existing) | New mutation exports for `claimSpec`, `releaseSpec`. Existing mutations (`updateDraft`, `commitSpec`, etc.) gain `specType` parameter. |
| `specs/product/speed-define-ceremony.md` (parent PRD) | Add a note in the "Ownership Model" section pointing at `specs/product/speed-define-ceremony-ownership.md` as the per-spec extension. Do not rewrite the section; the single-author baseline is still a valid operating mode (roster size 1), just served through the same unified claim model as multi-actor ceremonies. |
| `specs/tech/speed-define-ceremony-foundation.md` (parent RFC / foundation) | Add a cross-reference in the artifact flow section noting that `commit.json` is the single-author shape and ownership RFC replaces it with per-spec files. No behavioral change to foundation. |
| `specs/tech/speed-define-ceremony-commit.md` (sibling commit RFC) | Add a cross-reference noting that `submitRatification` signature is extended by the ownership RFC. |
| `specs/design/speed-define-ceremony.md` (parent Design) | Mark `/define/:feature/review` route as superseded by inline ratification on the main ceremony surface per the ownership design spec. Update `EditorTabBar` component row to reference the ownership design spec for claim chrome details. |

### Files that move

No files move. The single-file `commit.json` and ratification record are replaced by per-spec files in the same directory, not relocated. Migration (see below) handles the on-disk transition.

## Unresolved Questions

| ID | Question | Impact | Proposed path |
|----|----------|--------|---------------|
| UQ1 | Should the `stale_window` be configurable per ceremony, or only globally via `speed.toml`? | Affects teams with slow-moving ceremonies that want a longer window. Currently shared with `speed claim` feature ownership, so changing it globally affects other SPEED behaviors. | Defer. Revisit if a team hits the shared-window friction in practice. Add a `stale_window` field to `ceremony.json` as a later enhancement, defaulting to the global value. |
| UQ2 | How does Progress Overview reflect state changes from other actors in real time? | Current design uses refetch-on-mutation. Two actors working in parallel see each other's state only on their next mutation or tab switch. Real-time push would be nicer but requires websockets or SSE. | Defer. Ship with refetch-on-mutation. Measure how often stale overview causes confusion before introducing push. |
| UQ3 | Does `ratification-{spec_type}.json` carry anything beyond the `Ratification` shape defined in Data Model Changes? | Affects audit trail granularity. The defined shape already covers per-verdict actor, comment, and timestamp; additional fields (comment edit history, verdict supersession chain) would aid deep forensics at a storage cost. | Ship the defined shape. Additional fields only if the multiplayer event stream proves insufficient during real forensic work; the event stream remains the primary audit trail and the file is a gate flag plus verdict roll-up. |
| UQ4 | Should `claim-{spec_type}.json` be deleted or kept after `create_revision()` archives per-spec files? | Affects long-term directory size and the ability to reconstruct who claimed what for a superseded revision. | Keep them in the archived location (same pattern as commit records). The reflog is the authoritative history; the archive is a convenience. |
