# RFC: Define Ceremony — Commit & Ratification

<!-- REWRITE ANNOTATIONS (from parent RFC review pass):
  1. JSON SCHEMAS MISSING: `commit.json` has a Python dataclass and field table but no JSON Schema and no JSON example. `validation-at-commit.json` defers to editor RFC ("Same schema as editor RFC's ValidationState") with no local definition at all. Both need all four: Python dataclass + JSON Schema + field table + example.
  2. COMMIT RECORD FIELD OMISSION: Interface Contract Produces `CommitRecord` omits `ratification_status` (present in foundation and in this RFC's own Data Model).
  3. RATIFICATION VERDICT: Defined in a Data Model field table but missing from the Interface Contract as a Python dataclass.
  4. TERMINOLOGY MISMATCH: This RFC uses "approving" (state machine diagram line 215) where the foundation and parent RFC use "ratifying" (CeremonyStatus enum value). Also uses "approved" (Data Model line 114) where foundation uses "ratified" for ratification_status values. Reconcile to match the enum.
  5. PATH HELPER NAMING CONFLICT: File Impact claims to add `feature_commitment()` and `feature_validation_snapshot()` to paths.py. Parent RFC owns these as `ceremony_commit_record()` and `ceremony_validation_snapshot()`. Remove the child claims; consume the parent's helpers.
  6. INTERFACE CONTRACT: Consumes does not list parent RFC exports (CeremonyStatus, transition_ceremony_state, assert_ceremony_author, assert_not_ceremony_author, get_current_actor, path helpers). Only references "parent" in the header.
  7. ACTOR IDENTITY: References to "git identity" and "mock git identity" (risk table) should reference `get_current_actor()` for consistency.
-->

> See [product spec](../product/speed-define-ceremony.md) for product context.
> See [foundation reference](speed-define-ceremony-foundation.md) for shared types, API index, validation rules.
> Parent RFC: [speed-define-ceremony](speed-define-ceremony.md)
> Depends on: [parent](speed-define-ceremony.md), [editor](speed-define-ceremony-editor.md), [contributor](speed-define-ceremony-contributor.md)

## PRD & Design Traceability

**User Stories**: S5 (explicit commitment with recorded decision, author-only, template conformance gate, SP unblocks plan, MP triggers ratification), S9 (approver ratification, validation + context + suggestion history visible, author excluded, one verdict per actor, configurable threshold)

**User Flows**: "Committing the spec" (steps 1-5), "Approver ratification (multiplayer)" (steps 1-4)

**Success Criteria**: Commit records author/timestamp/validation/context/suggestions; commit in SP unblocks `speed plan`; commit in MP triggers ratification; approver sees suggestion resolution summary alongside validation state

**Design Components**: CommitBar (`ceremony/CommitBar.tsx`), CommitDialog (`ceremony/CommitDialog.tsx`), RatificationView (`ceremony/RatificationView.tsx`), RatificationSummary (`ceremony/RatificationSummary.tsx`), RatificationControls (`ceremony/RatificationControls.tsx`)

**Design Regions**: commit-bar (fixed bottom, 52px height within editor-area)

**Design Routes**: `/define/:feature` (commit bar within ceremony editor), `/define/:feature/review` (ratification view)

**Design Interactions**: Click commit (confirmation dialog with validation summary + unresolved warnings), click approve/reject (ratification event emission, threshold check), commit dialog confirm/cancel

**Design States**: CommitButton (enabled/hover/focus/pressed/disabled when template non-conformant/loading), RatifyApprove (enabled/hover/focus/pressed/disabled when author or already voted), RatifyReject (same), CommitDialogConfirm (enabled/loading), CommitDialogCancel

**Identity & Ownership**: Commit is author-only (cannot be delegated). Ratification excludes author. Each approver votes once. Threshold from `speed.toml` (default 1). Claim released on commit.

## Basic Example

```graphql
# Single-player commit
mutation {
  commitSpec(featureName: "sort-auth-by-last-activity") {
    commitment {
      author
      committedAt
      validationState { dimensions { name, status } }
      suggestionHistory { received, accepted, dismissed }
    }
    planUnblocked  # true in single-player
  }
}

# Multiplayer: approver ratifies
mutation {
  submitRatification(
    featureName: "sort-auth-by-last-activity"
    verdict: APPROVE
  ) {
    ratificationCount
    threshold
    thresholdMet
    planUnblocked  # true when ratificationCount >= threshold
  }
}
```

The author commits the spec, which writes durable artifacts and either unblocks `speed plan` (single-player) or triggers the ratification flow (multiplayer). Approvers review the spec, context, and suggestion history, then submit their verdict.

## Interface Contract

### Consumes (from prerequisite RFCs)

From `speed-define-ceremony-editor.md`:
- `ValidationState` — frozen at commit time into `validation-at-commit.json`
- `SpecDraft` — the committed spec content written to `specs/{type}/{name}.md`
- `validate_spec()` — called at commitment to get the final validation state

From `speed-define-ceremony-contributor.md`:
- `load_suggestions()` — all suggestions for the ceremony
- `get_suggestion_history()` — aggregate stats for commit record and ratification display

From `speed-define-ceremony-context.md`:
- `load_context_package()` — reference to the persisted context package (snapshot ref, not a copy)

### Produces (consumed by downstream systems)

```python
@dataclass
class CommitRecord:
    feature_name: str
    author: str  # git identity
    author_email: str
    committed_at: str  # ISO 8601
    validation_state_ref: str  # path to validation-at-commit.json
    context_package_ref: str  # path to context-package.json
    suggestion_history: SuggestionHistory
    spec_paths: list[str]  # all committed spec file paths
    is_multiplayer: bool
    ratification_threshold: int  # from speed.toml, 0 in single-player

# Consumed by:
# - Landing page Judge panel (ceremony status)
# - Learning pipeline (post-feature analysis)
# - speed plan gate (checks for commitment before planning)
```

## Data Model

### CommitRecord (persisted to `.speed/features/{feature}/commit.json`)

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| feature_name | string | no | Feature being committed |
| author | string | no | Git user.name of the committing author |
| author_email | string | no | Git user.email |
| committed_at | ISO 8601 | no | Timestamp of commitment |
| validation_state_ref | string | no | Relative path to `validation-at-commit.json` |
| context_package_ref | string | no | Relative path to `context-package.json` |
| suggestion_history | SuggestionHistory | no | Snapshot of suggestion stats at commit time |
| spec_paths | string[] | no | All spec file paths committed (supports multi-RFC) |
| is_multiplayer | boolean | no | Whether MP mode is active |
| ratification_threshold | int | no | Required ratifications (0 in single-player) |
| ratification_status | enum | no | "not_required" (SP), "pending", "approved", "rejected" |

### ValidationAtCommit (persisted to `.speed/features/{feature}/validation-at-commit.json`)

Frozen copy of the `ValidationState` at the moment of commit. Same schema as the editor RFC's `ValidationState`, persisted as a snapshot.

### RatificationVerdict (stored in `.speed/shared/events/` as JSONL events)

| Field | Type | Description |
|-------|------|-------------|
| actor | string | Git identity of the approver |
| verdict | enum | "approve" or "reject" |
| comment | string or null | Optional comment (typically provided on reject) |
| timestamp | ISO 8601 | When the verdict was submitted |

Ratification verdicts are stored as events (consistent with the existing multiplayer event system) rather than in the commit record. The commit record tracks aggregate status; individual verdicts live in the event log.

## State Machine

```
                    ┌─────────────┐
                    │   drafting   │
                    └──────┬──────┘
                           │ commitSpec()
                           ▼
              ┌────────────────────────┐
              │ Precondition checks:   │
              │ • template conformant? │──── NO ──→ blocked (error returned)
              │ • author owns ceremony?│
              └────────────┬───────────┘
                           │ YES
                    ┌──────┴──────┐
            ┌───────│  committed  │───────┐
            │       └─────────────┘       │
        SP mode                       MP mode
            │                             │
            ▼                             ▼
    ┌───────────────┐           ┌─────────────────┐
    │ plan_unblocked│           │    approving     │
    │ (terminal)    │           └────────┬────────┘
    └───────────────┘                    │
                              submitRatification()
                                         │
                           ┌─────────────┼──────────────┐
                           ▼             ▼              ▼
                    threshold met   below threshold   rejected
                           │             │              │
                           ▼             │              ▼
                   ┌───────────────┐     │      ┌──────────────┐
                   │ plan_unblocked│     │      │   rework     │
                   │ (terminal)    │     │      │ (reopens     │
                   └───────────────┘     │      │  drafting)   │
                                         │      └──────────────┘
                                    stays in
                                    approving
```

Transitions not allowed:
- `committed → drafting`: once committed, cannot uncommit. Start a new ceremony instead.
- `plan_unblocked → approving`: single-player commitments cannot be retroactively approved.
- `rework → plan_unblocked`: must go through drafting → committed → approving again.

## API Surface

### Mutations

#### `commitSpec(featureName: String!): CommitResult!`

The commit action. Performs these steps in order:

1. **Ownership check**: caller must be the ceremony author
2. **Template conformance check**: validate spec against its SPEED template. Block if non-conformant (return error with specific missing sections).
3. **Freeze validation state**: run `validate_spec()` one final time, write result to `validation-at-commit.json`
4. **Snapshot suggestion history**: call `get_suggestion_history()`, include in commit record
5. **Write spec files**: copy draft content to target paths (`specs/product/{name}.md`, etc.). For multi-RFC topologies, write all specs atomically.
6. **Write commit record**: persist `commit.json`
7. **Determine mode**: check `MP_ENABLED` (presence of `.speed/shared/`)
8. **Single-player**: set `ratification_status = "not_required"`, return `planUnblocked = true`
9. **Multiplayer**: emit `spec.proposed` event, set `ratification_status = "pending"`, return `planUnblocked = false`

**Return type:**
```graphql
type CommitResult {
  commitment: CommitRecord!
  planUnblocked: Boolean!
  warnings: [String!]!  # unresolved suggestions, validation warnings
}
```

**Error cases:**
- Caller is not ceremony author: ownership error
- Template non-conformant: error listing missing/malformed sections
- Spec content empty: validation error
- Feature directory doesn't exist (no intent declared): error

#### `submitRatification(featureName: String!, verdict: RatificationVerdict!, comment: String): RatificationResult!`

Submits an approver's verdict on a committed spec.

1. **Ownership check**: caller must NOT be the ceremony author
2. **Duplicate check**: caller has not already voted
3. **Status check**: ceremony must be in `approving` state
4. **Emit event**: write `spec.reviewed` event to `.speed/shared/events/`
5. **Check threshold**: count ratifications, compare to `ratification_threshold`
6. **If threshold met**: emit `spec.ratified` event to `.speed/shared/events/` (this is the event `plan.sh` gates on at line 480), update `commit.json` ratification_status to "approved", return `planUnblocked = true`
7. **If rejected**: update status to "rejected" (any single rejection), return `planUnblocked = false`

```graphql
enum RatificationVerdict { APPROVE, REJECT }

type RatificationResult {
  ratificationCount: Int!
  threshold: Int!
  thresholdMet: Boolean!
  planUnblocked: Boolean!
  verdicts: [VerdictEntry!]!
}

type VerdictEntry {
  actor: String!
  verdict: RatificationVerdict!
  comment: String
  timestamp: String!
}
```

**Error cases:**
- Caller is the ceremony author: "Cannot ratify your own spec"
- Caller already voted: "You have already submitted a verdict"
- Ceremony not in approving state: error with current state

### Queries

#### `commitRecord(featureName: String!): CommitRecord`

Returns the commit record for a feature. Null if not yet committed.

#### `ratificationState(featureName: String!): RatificationState`

```graphql
type RatificationState {
  status: String!  # "not_required" | "pending" | "approved" | "rejected"
  ratificationCount: Int!
  threshold: Int!
  verdicts: [VerdictEntry!]!
  isAuthor: Boolean!  # whether the querying actor is the ceremony author
  hasVoted: Boolean!  # whether the querying actor has already voted
}
```

Used by `RatificationView`, `RatificationControls`, and the landing page Judge panel.

## Validation Rules

| Field | Constraints |
|-------|-------------|
| commitment | Blocked when spec fails template conformance. Allowed with unresolved suggestions (warning shown, not blocking). Allowed with validation warnings in other dimensions. |
| ratification verdict | One vote per actor. Author excluded. Only valid in "approving" state. |
| rejection comment | Optional but recommended. Max 500 chars. |
| threshold | Read from `speed.toml` key `multiplayer.ratification_threshold`. Default 1. Minimum 1. |
| multi-RFC atomic commit | All specs in the topology must individually pass template conformance. If any fails, the entire commit is blocked. |

## Testing

### Acceptance Criteria

- Given an author with a template-conformant spec and no unresolved suggestions, when they commit, then `commit.json` and `validation-at-commit.json` are written, and `speed plan` is unblocked in single-player mode
- Given an author with a non-conformant spec (missing User Stories section), when they commit, then the mutation returns an error identifying "User Stories" as missing
- Given an author with 2 unresolved suggestions, when they commit, then the commit succeeds with warnings listing the unresolved suggestions
- Given a multiplayer ceremony, when the author commits, then a `spec.proposed` event is emitted and ratification status is "pending"
- Given a multiplayer ceremony with threshold 2, when one approver approves, then `ratificationCount = 1`, `thresholdMet = false`, `planUnblocked = false`
- Given a multiplayer ceremony with threshold 1, when one approver approves, then `thresholdMet = true`, `planUnblocked = true`, ratification status updates to "approved"
- Given any actor who is the ceremony author, when they try to submit a ratification, then the mutation returns "Cannot ratify your own spec"
- Given an approver who already voted, when they try to vote again, then the mutation returns "You have already submitted a verdict"
- Given a multi-RFC topology with 3 child specs, when the author commits, then all 3 specs plus the parent PRD are written atomically

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| Spec files written partially (crash mid-commit) | High | Integration test: simulate write failure on 2nd of 3 specs, verify no partial state (all-or-nothing) |
| Ratification threshold race condition (two approvers approve simultaneously) | Medium | Unit test: simulate concurrent ratifications, verify count is correct and threshold check is atomic |
| Author circumvents ownership check | Medium | Unit test: mock git identity, verify ownership check against stored ceremony author |
| `speed plan` runs before commitment | Low | Integration test: verify plan checks for `commit.json` existence |

### Test Plan

**Unit tests**
- `test_commit_preconditions`: template check, ownership check, empty content check
- `test_commit_artifacts`: verify commit.json schema, validation-at-commit.json matches current state
- `test_commit_spec_files`: verify spec files written to correct paths, multi-RFC atomic write
- `test_commit_single_player`: plan_unblocked = true, ratification_status = "not_required"
- `test_commit_multiplayer`: plan_unblocked = false, spec.proposed event emitted
- `test_ratification_approve`: count increment, threshold check, plan unlock on threshold met
- `test_ratification_reject`: status transitions to "rejected"
- `test_ratification_guards`: author blocked, duplicate vote blocked, wrong state blocked

**Integration tests**
- `test_graphql_commit_flow`: full mutation through Strawberry schema, SP and MP modes
- `test_graphql_ratification_flow`: commit → approve → threshold met, through schema
- `test_commitment_persistence`: commit, reload from disk, verify all fields
- `test_event_emission`: verify `spec.proposed` and `spec.reviewed` events written to `.speed/shared/events/`

**Visual/UI tests**
- CommitBar shows validation summary badges, unresolved count, commit button states
- Commit confirmation dialog shows per-dimension validation and unresolved warnings
- Post-commit SP: shows "speed plan is now unblocked" messaging
- Post-commit MP: shows "Proposed for ratification. Waiting for N ratification(s)"
- RatificationView: read-only spec, context, validation, suggestion summary, approve/reject controls
- RatificationControls: disabled for author, disabled after voting, shows ratification count vs threshold

### Edge Cases

- Commit with zero suggestions (no contributor feedback): suggestion_history shows all zeros, no warning
- Commit with all suggestions resolved (3 accepted, 1 dismissed): clean commit, no warnings
- Multi-RFC commit where one child RFC fails template check: entire commit blocked, error identifies which child failed
- Ratification with threshold 0 (shouldn't happen but defensive): treat as threshold 1
- Rejection after ratification: if one actor approves and another rejects, the rejection takes priority (any rejection = rejected)
- Ceremony has no context package (edge case: commit without intent): error, require intent declaration first

### Out of Scope

- Re-opening a committed ceremony for amendments. PRD Q5 leaves this open. Currently requires starting a new ceremony. Amendment workflow deferred pending design of audit trail and version tracking.
- Partial ratification (approve some specs, reject others in a multi-RFC topology). All-or-nothing. Granular per-RFC approval requires state machine changes for multi-spec topologies.
- Ratification via CLI. Dashboard-only. The existing `speed spec review` CLI command handles event emission for multiplayer, but the ceremony's ratification view is the primary interface. CLI integration deferred pending workflow analysis.

## Security & Controls

**Authorization:**

| Action | Who | Enforcement |
|--------|-----|-------------|
| Commit | Ceremony author only | Git identity matched against ceremony ownership record |
| Approve/reject | Any actor except author | Git identity checked against ceremony author; duplicate vote check against event log |
| View ratification state | Any actor | Read-only query, no auth check |

**Audit trail**: Every commitment and ratification verdict is recorded with actor identity and timestamp. Commitment artifacts persist in `.speed/features/`. Ratification events persist in `.speed/shared/events/`.

**Integrity**: Spec files are written to `specs/` directory on commit. These are regular files in the git working tree. The author (or any team member) can modify them directly outside the ceremony. The commit record captures what was committed; it does not enforce immutability on the spec files.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Template conformance blocks commitment | Hard block | Warn but allow, Soft gate with override | Downstream agents (Architect, Reviewer, Guardian) depend on predictable spec structure. Allowing non-conformant specs through would cause planning failures. |
| Unresolved suggestions warn but don't block | Warning | Hard block, No warning | Contributors shouldn't be able to veto commitment by leaving unresolved suggestions. The author is accountable for their decisions. Approvers see the dismissal reasons during ratification. |
| Single rejection fails ratification | Any rejection = rejected | Majority vote, Author can override | Spec review is a quality gate, not a vote. If one reviewer has a concern serious enough to reject, it should be addressed. The threshold is for minimum ratification count, not majority. |
| Ratification verdicts in event log, not commit.json | Event log | Embed in commit.json, Separate verdicts file | Consistent with the multiplayer event system. Events are append-only JSONL with unique filenames, ensuring zero merge conflicts. The commit record tracks aggregate status, not individual votes. |
| Multi-RFC commit is atomic | All-or-nothing | Per-spec commit, Best-effort | Partial commitment creates an inconsistent spec topology. If the PRD is committed but a child RFC fails template check, `speed plan` would see an incomplete decomposition. |

## Drawbacks

- Hard-blocking on template conformance means the author cannot commit a "good enough" spec that's missing a section they consider irrelevant. The template is rigid by design, but some projects may find certain sections unnecessary.
- Single-rejection-fails is strict. In a team of 5, one dissenting voice blocks the entire ceremony. The author's recourse is to address the feedback and re-commit (which triggers a new ratification round).
- Ratification is dashboard-only. Engineers who prefer CLI workflows must switch to the browser to approve specs. The existing `speed spec review` CLI can be extended if workflow analysis indicates demand.

## File Impact

**New files:**
- `dashboard/backend/resolvers/ceremony_commitment.py` — commit and ratification resolvers
- `dashboard/backend/resolvers/ceremony_commitment_types.py` — Strawberry types
- `dashboard/backend/commitment_store.py` — read/write commit.json, ratification state aggregation
- `dashboard/frontend/components/define/ceremony/CommitBar.tsx` — commit controls
- `dashboard/frontend/components/define/ceremony/CommitDialog.tsx` — confirmation dialog
- `dashboard/frontend/components/define/ceremony/RatificationView.tsx` — page layout for approvers
- `dashboard/frontend/components/define/ceremony/RatificationSummary.tsx` — evidence panel
- `dashboard/frontend/components/define/ceremony/RatificationControls.tsx` — approve/reject buttons
- `dashboard/frontend/lib/graphql/queries/ceremony-commitment.ts` — queries and mutations
- `dashboard/frontend/app/define/[feature]/review/page.tsx` — ratification route

**Modified files:**
- `dashboard/backend/schema.py` — register commitment queries and mutations. **Integration order**: fourth (after context, editor, contributor RFCs).
- `dashboard/backend/paths.py` — add `feature_commitment()`, `feature_validation_snapshot()` path helpers
- `lib/cmd/plan.sh` — already gates on `spec.ratified` events (line 480). No modification needed for MP mode. For SP mode, the commitment mutation directly unblocks planning by writing a ratification-not-required marker. Verify that SP commitment is compatible with the existing plan gate.

## Dependencies

- Editor RFC: `ValidationState`, `validate_spec()`, `SpecDraft`
- Contributor RFC: `load_suggestions()`, `get_suggestion_history()`
- Context RFC: `load_context_package()` for snapshot reference
- Multiplayer event system: `lib/events.sh` patterns for `spec.proposed`, `spec.reviewed` events
- Ceremony ownership: from context RFC's `declareIntent` (author assignment)
- `speed.toml`: `multiplayer.ratification_threshold` setting
- `speed plan` gate: `lib/cmd/plan.sh` must check for commitment before proceeding

## Unresolved Questions

| Question | Blocks | Proposed Resolution |
|----------|--------|---------------------|
| How does `speed plan` check for commitment in single-player? | Plan gate implementation | In MP mode, `plan.sh` already gates on `spec.ratified` events (line 480). The ceremony emits `spec.ratified` when threshold is met. For SP mode, planning is not currently gated on ceremony completion. Options: (a) emit a `spec.ratified` event even in SP mode when the author commits, or (b) SP mode continues to bypass the gate as it does today. Recommend option (a) for consistency. |
| Can a rejected spec be re-committed without changes? | Rework flow | No. Rejection transitions the ceremony back to drafting. The author must make edits (the system tracks `updated_at` on the draft). Re-commitment creates a new `commit.json` with fresh timestamps, triggering a new ratification round. |
| Should the commit record include a hash of the spec content? | Integrity verification | Yes. Include a SHA-256 hash of each committed spec file. Downstream systems can verify the spec hasn't been modified outside the ceremony by comparing hashes. |
