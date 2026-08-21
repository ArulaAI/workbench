# RFC: Define Ceremony — Contributor Suggestions

<!-- REWRITE ANNOTATIONS (from parent RFC review pass):
  1. JSON SCHEMA MISSING: `suggestions.json` has a Python dataclass and field table but no JSON Schema and no JSON example. Needs all four.
  2. SUGGESTION FIELD OMISSIONS: Interface Contract Produces `Suggestion` dataclass omits `author_email` and `updated_at` (both present in foundation and in this RFC's own Data Model table).
  3. INTERFACE CONTRACT: Consumes does not list parent RFC exports (CeremonyStatus, assert_ceremony_author, assert_not_ceremony_author, get_current_actor, path helpers). Only references "parent" in the header.
  4. IMPORT PATH: Consumes code blocks say `from ceremony_context import ...` — should use relative imports matching codebase convention.
  5. ACTOR IDENTITY: Some field descriptions still say "git identity" or reference `git config user.name` directly. Should reference `get_current_actor()` for consistency with parent RFC.
-->

> See [product spec](../product/speed-define-ceremony.md) for product context.
> See [foundation reference](speed-define-ceremony-foundation.md) for shared types, API index, validation rules.
> Parent RFC: [speed-define-ceremony](speed-define-ceremony.md)
> Depends on: [parent](speed-define-ceremony.md), [editor](speed-define-ceremony-editor.md), [context](speed-define-ceremony-context.md)

## PRD & Design Traceability

**User Stories**: S7 (contributor inline suggestions, read-only spec, edit/delete own before resolution), S8 (author resolves suggestions with accept/dismiss/reply, decision trail, unresolved warning at commit)

**User Flows**: "Contributor leaving suggestions" (steps 1-6), "Resolving suggestions before commitment" (steps 1-5)

**Success Criteria**: Contributors leave inline suggestions on specific sections; author can accept/dismiss (with reason)/reply; suggestion resolution recorded (who, when, decision, original preserved); unresolved suggestions surface as warning at commit

**Design Components**: SuggestionSidebar (`ceremony/SuggestionSidebar.tsx`), SuggestionCard (`ceremony/SuggestionCard.tsx`), SuggestionComposer (`ceremony/SuggestionComposer.tsx`), ContributorBanner (`ceremony/ContributorBanner.tsx`), DismissReasonDialog (`ceremony/DismissReasonDialog.tsx`), EditorTabBar (modified `editor/EditorTabs.tsx`, adds suggestion sidebar toggle with unresolved count badge)

**Design Regions**: suggestion-sidebar (280px, toggleable, Cmd+Shift+S)

**Design Routes**: `/define/:feature` (contributor view, read-only with suggestion affordances)

**Design Interactions**: Select section (contributor, gutter affordance), submit/cancel suggestion, accept/dismiss/reply (author), edit/delete own suggestion (contributor, before resolution), toggle suggestion sidebar, dismiss reason dialog (modal, min 10 chars, focus trap)

**Design States**: SuggestionComposer (enabled/hover/focus/disabled), SuggestionCard accept/dismiss (enabled/hover/focus), ContributorBanner (non-interactive), DismissReasonDialog submit (enabled/disabled below 10 chars)

## Basic Example

```graphql
# Contributor creates a suggestion
mutation {
  createSuggestion(
    featureName: "sort-auth-by-last-activity"
    sectionId: "scope-in-scope"
    text: "Add a criterion for the 24-hour throttle on accessedAt updates."
  ) {
    id
    author
    sectionId
    text
    status
    createdAt
  }
}

# Author resolves a suggestion
mutation {
  resolveSuggestion(
    id: "sug-001"
    action: ACCEPT
  ) {
    id
    status
    resolution { resolvedBy, resolvedAt, action }
  }
}
```

A contributor opens `/define/sort-auth-by-last-activity`, sees the spec in read-only mode with the same context panel the author sees, clicks a section heading to anchor a suggestion, writes their feedback, and submits. The author sees the suggestion inline and accepts, dismisses (with reason), or replies.

## Interface Contract

### Consumes (from prerequisite RFCs)

From `speed-define-ceremony-context.md`:
- `ContextPackage` — displayed in ContextPanel for contributor view (same data as author sees)
- `load_context_package(project_root, feature_name)` — loads context for display

From `speed-define-ceremony-editor.md`:
- `SpecDraft` — rendered read-only in contributor mode via SpecEditor's `readOnly` prop
- `load_spec_draft(project_root, feature_name)` — loads current draft for display

### Produces (for commit RFC)

```python
@dataclass
class Suggestion:
    id: str
    author: str  # git identity
    section_id: str  # heading slug from spec
    section_title: str  # human-readable heading
    text: str
    status: str  # "unresolved" | "accepted" | "dismissed"
    created_at: str  # ISO 8601
    resolution: SuggestionResolution | None
    thread: list[SuggestionReply]

@dataclass
class SuggestionResolution:
    action: str  # "accept" | "dismiss"
    resolved_by: str  # git identity
    resolved_at: str  # ISO 8601
    reason: str | None  # required for dismiss, null for accept

@dataclass
class SuggestionReply:
    author: str
    text: str
    created_at: str

@dataclass
class DismissedSummary:
    count: int
    reasons: list[str]

@dataclass
class SuggestionHistory:
    received: int
    accepted: int
    dismissed: DismissedSummary  # nested to carry reasons alongside count

def load_suggestions(project_root: Path, feature_name: str) -> list[Suggestion]:
    """Load all suggestions for a ceremony."""

def get_suggestion_history(suggestions: list[Suggestion]) -> SuggestionHistory:
    """Aggregate suggestion resolution stats for commit/ratification display."""
```

## Data Model

### Suggestion (persisted to `.speed/features/{feature}/suggestions.json`)

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| id | string | no | Unique ID: `sug-{timestamp}-{hash}` |
| author | string | no | Contributor's resolved name (from `get_current_actor()`: `$SPEED_ACTOR` / git config / whoami) |
| author_email | string | no | Git email for deduplication |
| section_id | string | no | Slugified heading from the spec (e.g., "scope-in-scope") |
| section_title | string | no | Original heading text (e.g., "Scope > In Scope") |
| text | string | no | Suggestion content |
| status | enum | no | "unresolved", "accepted", "dismissed" |
| created_at | ISO 8601 | no | When submitted |
| updated_at | ISO 8601 | yes | Last edit by contributor (before resolution) |
| resolution | Resolution | yes | Null while unresolved |
| thread | Reply[] | no | Flat list of replies, empty initially |

### Resolution

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| action | enum | no | "accept" or "dismiss" |
| resolved_by | string | no | Git identity of the author |
| resolved_at | ISO 8601 | no | When resolved |
| reason | string | yes | Required for dismiss (min 10 chars), null for accept |

### Reply

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| author | string | no | Git identity of replier (author or contributor) |
| text | string | no | Reply content |
| created_at | ISO 8601 | no | When submitted |

### Section Identification

Spec sections are identified by slugifying markdown headings. The slug is computed client-side when the contributor selects a section:

```
## User Stories → "user-stories"
### Scope > In Scope → "scope-in-scope"
```

If a heading changes after a suggestion is created, the `section_title` field preserves the original text. The `section_id` may no longer match a heading in the current draft, in which case the suggestion is displayed in a "detached" state at the bottom of the sidebar with a note that the referenced section was modified.

## API Surface

### Mutations

#### `createSuggestion(featureName: String!, sectionId: String!, sectionTitle: String!, text: String!): Suggestion!`

Creates a new suggestion anchored to a spec section.

**Authorization**: Any actor except the ceremony author. The author cannot suggest on their own spec (they edit directly).

**Error cases:**
- Feature not found: return error
- Caller is the ceremony author: return "Authors edit directly; suggestions are for contributors"
- Text < 10 characters: return validation error
- Text > 2000 characters: return validation error

#### `editSuggestion(id: String!, text: String!): Suggestion!`

Edits an existing suggestion. Only the suggestion's author can edit, and only while the suggestion is unresolved.

**Error cases:**
- Suggestion not found: return error
- Caller is not the suggestion author: return ownership error
- Suggestion already resolved: return "Cannot edit a resolved suggestion"
- Text < 10 or > 2000 characters: return validation error

#### `deleteSuggestion(id: String!): Boolean!`

Deletes a suggestion. Only the suggestion's author can delete, and only while unresolved.

**Error cases:**
- Same ownership and status checks as `editSuggestion`

#### `resolveSuggestion(id: String!, action: ResolveAction!, reason: String): Suggestion!`

Resolves a suggestion. Only the ceremony author can resolve.

```graphql
enum ResolveAction { ACCEPT, DISMISS }
```

When action is `ACCEPT`:
1. The suggestion's text is not auto-applied to the spec (the author applies it manually through the editor). The suggestion is marked as accepted for record-keeping.
2. Status transitions to "accepted".

When action is `DISMISS`:
1. `reason` is required (min 10 chars). Returns validation error if missing or too short.
2. Status transitions to "dismissed".

**Error cases:**
- Caller is not the ceremony author: return ownership error
- Suggestion already resolved: return "Suggestion already resolved"
- DISMISS without reason or reason < 10 chars: return validation error

#### `replySuggestion(id: String!, text: String!): Suggestion!`

Adds a reply to a suggestion thread. Both the ceremony author and the suggestion's contributor can reply. Replies are allowed on resolved suggestions (for post-resolution discussion).

**Error cases:**
- Text < 1 or > 1000 characters: return validation error

### Queries

#### `suggestions(featureName: String!): [Suggestion!]!`

Returns all suggestions for a ceremony, ordered by section position in the spec then by creation time.

#### `suggestionHistory(featureName: String!): SuggestionHistory!`

Returns aggregate resolution stats. Used by CommitBar (unresolved count) and RatificationSummary (received/accepted/dismissed breakdown).

## Validation Rules

| Field | Constraints |
|-------|-------------|
| suggestion text | Min 10 chars, max 2000 chars. Whitespace-trimmed. |
| dismiss reason | Min 10 chars, max 500 chars. Required for DISMISS action. |
| reply text | Min 1 char, max 1000 chars. |
| section_id | Must be a valid slug (lowercase, hyphens). Not validated against current spec headings (sections may change). |
| author identity | Resolved server-side by `get_current_actor()` (`$SPEED_ACTOR` / git config / whoami). Cannot be spoofed through GraphQL input parameters. |

## Testing

### Acceptance Criteria

- Given a contributor opens a ceremony's Define surface, then they see the spec in read-only mode with the same context panel the author sees
- Given a contributor clicks a section heading, then a SuggestionComposer appears anchored to that section with submit/cancel actions
- Given a contributor submits a suggestion with >= 10 characters, then it persists and appears in the SuggestionSidebar for both contributor and author
- Given the ceremony author opens the SuggestionSidebar, then each suggestion shows accept/dismiss/reply actions
- Given the author accepts a suggestion, then it transitions to "accepted" status with a recorded resolution (who, when)
- Given the author dismisses a suggestion, then a reason dialog appears requiring >= 10 characters, and on submit the suggestion transitions to "dismissed" with the reason recorded
- Given a contributor tries to edit a resolved suggestion, then the mutation returns an error
- Given the ceremony author tries to create a suggestion on their own spec, then the mutation returns an error
- Given a contributor edits their own unresolved suggestion, then the text updates and `updated_at` is set
- Given the author has 3 unresolved suggestions, then the CommitBar shows "3 unresolved" in amber

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| Section heading changes after suggestion created | Medium | Unit test: create suggestion, change heading slug, verify suggestion displays as "detached" |
| Concurrent suggestion edits (contributor edits while author resolves) | Medium | Unit test: simulate race condition, verify last-write-wins with appropriate error |
| Suggestion count mismatch between sidebar and commit bar | Low | Integration test: create, resolve, delete suggestions, verify counts stay consistent |

### Test Plan

**Unit tests**
- `test_create_suggestion`: valid input, too short, too long, author self-suggest blocked
- `test_edit_suggestion`: own suggestion, others' suggestion, resolved suggestion
- `test_delete_suggestion`: own unresolved, own resolved (blocked), others' (blocked)
- `test_resolve_accept`: author accepts, non-author blocked, already resolved blocked
- `test_resolve_dismiss`: with reason, without reason (blocked), reason too short (blocked)
- `test_reply`: author replies, contributor replies, on resolved suggestion (allowed)
- `test_section_detachment`: suggestion with stale section_id
- `test_suggestion_history`: aggregate counts after mixed resolutions

**Integration tests**
- `test_graphql_suggestion_lifecycle`: create → edit → resolve → reply through Strawberry schema
- `test_persistence_roundtrip`: create suggestions, reload from disk, verify data integrity

**Visual/UI tests**
- ContributorBanner renders with author name, status, suggestion count
- SuggestionComposer anchors to clicked heading with accent border
- SuggestionCard shows accept/dismiss/reply for author, edit/delete for contributor (own, unresolved)
- DismissReasonDialog traps focus, validates 10-char minimum, shows inline error
- SuggestionSidebar toggle shows badge with unresolved count

### Edge Cases

- Zero suggestions: sidebar hidden by default, toggle shows empty state "No suggestions yet"
- Suggestion on a heading that no longer exists: displayed as "detached" at bottom of sidebar with original section_title preserved
- Very long suggestion text (2000 chars): wraps in SuggestionCard, no truncation
- Contributor submits then immediately deletes: delete succeeds, suggestion disappears from sidebar
- Multiple contributors suggest on same section: suggestions stack in sidebar grouped by section
- Reply thread with 20+ replies: thread scrolls independently within SuggestionCard

### Out of Scope

- Real-time notification when a suggestion is created or resolved. Polling is used (sidebar refreshes on tab focus). Real-time notifications deferred until multiplayer collaboration patterns scale.
- Suggestion diff view (showing what would change if accepted). The author reads the suggestion and applies changes manually.
- Suggestion assignment to specific team members. Any contributor can suggest.

## Security & Controls

**Authorization model:**

| Action | Who can do it | How identity is verified |
|--------|--------------|------------------------|
| Create suggestion | Any actor except ceremony author | Git identity from server-side `git config` |
| Edit suggestion | Suggestion author only, while unresolved | Match `author_email` against current git config |
| Delete suggestion | Suggestion author only, while unresolved | Same |
| Accept/dismiss | Ceremony author only | Match against ceremony ownership record |
| Reply | Ceremony author or suggestion author | Git identity |

**Data sensitivity**: Suggestions may contain technical discussion about the spec. Stored as JSON on the local filesystem, same security posture as task JSON files.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Accept does not auto-apply suggestion text | Manual application by author | Auto-insert at section, Auto-replace section | Suggestions are feedback, not patches. The author decides how to incorporate the intent. Auto-insertion would require diff merging logic that's complex and error-prone. |
| Suggestions persist to a single JSON file | `.speed/features/{feature}/suggestions.json` | Per-suggestion files, SQLite, event log | Single file is simple, matches the task JSON pattern, and avoids file proliferation. Suggestion count per ceremony is low (typically < 20). |
| Section identification by heading slug | Client-side slug computation | Line numbers, content hashes, UUID markers | Heading slugs are stable across edits within a section. Line numbers shift on every edit. Content hashes change when any character changes. Slugs are the best balance of stability and simplicity. |
| Replies are flat, not threaded | Flat chronological list | Nested threading, GitHub-style resolve/unresolve | Ceremony suggestions are short discussions (2-5 exchanges), not long debates. Flat display is simpler and sufficient. |
| Resolved suggestions can receive replies | Allow | Block replies after resolution | Post-resolution discussion is useful ("I dismissed this because X" / "Makes sense, thanks"). No reason to prevent it. |

## Drawbacks

- Manual suggestion application means the author must read the suggestion, understand the intent, and edit the spec accordingly. There's no guarantee the applied change matches what the contributor intended.
- Single JSON file for suggestions could theoretically have write conflicts if two contributors submit simultaneously in multiplayer mode. In practice, the file is written via GraphQL mutation (serialized), so conflicts are unlikely.
- Section slug stability breaks down when the author renames or removes a heading entirely. Detached suggestions lose their spatial context.

## File Impact

**New files:**
- `dashboard/backend/resolvers/ceremony_suggestions.py` — GraphQL resolvers for suggestion CRUD
- `dashboard/backend/resolvers/ceremony_suggestion_types.py` — Strawberry types
- `dashboard/backend/suggestion_store.py` — read/write suggestions.json, suggestion history aggregation
- `dashboard/frontend/components/define/ceremony/SuggestionSidebar.tsx` — suggestion list and toggle
- `dashboard/frontend/components/define/ceremony/SuggestionCard.tsx` — individual suggestion display and actions
- `dashboard/frontend/components/define/ceremony/SuggestionComposer.tsx` — anchored suggestion input
- `dashboard/frontend/components/define/ceremony/ContributorBanner.tsx` — read-only mode indicator
- `dashboard/frontend/components/define/ceremony/DismissReasonDialog.tsx` — modal for dismiss reason
- `dashboard/frontend/lib/graphql/queries/ceremony-suggestions.ts` — GraphQL queries and mutations

**Modified files:**
- `dashboard/backend/schema.py` — register suggestion queries and mutations. **Integration order**: third (after context and editor RFCs).
- `dashboard/frontend/components/editor/EditorTabs.tsx` — add suggestion sidebar toggle with badge
- `dashboard/frontend/app/define/[feature]/page.tsx` — integrate contributor mode detection and SuggestionSidebar

## Dependencies

- Context RFC: `load_context_package()` for contributor's context panel
- Editor RFC: `SpecDraft`, `load_spec_draft()` for read-only spec display, `CeremonyLayout` for page composition
- Actor identity: `get_current_actor()` from parent RFC (`$SPEED_ACTOR` / git config / whoami chain) for author/contributor identification
- Ceremony ownership record: determines who is the author (from intent declaration in context RFC)

## Unresolved Questions

| Question | Blocks | Proposed Resolution |
|----------|--------|---------------------|
| Should suggestions be visible to all contributors or only to the author and the suggesting contributor? | Multiplayer UX | Visible to all. Transparency reduces redundant suggestions and lets contributors build on each other's feedback. |
| How should the UI handle many suggestions on a single section (5+)? | Visual design | Group by section in the sidebar with a count badge. Individual cards stack vertically within the group. Collapse groups with > 3 suggestions, showing only the count and most recent. |
| Should there be a notification when a suggestion is resolved? | Contributor experience | No real-time notification. Contributor sees resolution status on next visit. Email or dashboard notification can be added based on user feedback. |
