# RFC: Define Ceremony — Editor & Validation

<!-- REWRITE ANNOTATIONS (from parent RFC review pass):
  1. JSON SCHEMA MISSING: `validation-at-commit.json` (frozen ValidationState) has a Python dataclass and partial field table but no JSON Schema and no JSON example. Needs all four.
  2. TYPE DIVERGENCE FROM FOUNDATION: ValidationState uses `summary: ValidationSummary` (nested) + `timestamp: str` (extra field); foundation uses flat `pass_count`/`warn_count`/`fail_count` with no timestamp. ValidationDimension omits `checked_at`, `tier`, and "stale" status value that the foundation defines. ValidationIssue uses nested `location: IssueLocation` and `cross_ref: CrossSpecRef` where foundation uses flat fields (`section`, `line`, `cross_ref_spec`, `cross_ref_section`). These structural mismatches mean the foundation types and this RFC's types cannot both be the implementation. Reconcile with foundation.
  3. SPEC DRAFT FIELD OMISSIONS: Interface Contract Produces `SpecDraft` omits `template_name` and `generated_at` (both present in foundation and in this RFC's own Data Model).
  4. CROSSSPECISSUE: Defined in the Data Model field table but missing from the Interface Contract Python dataclass block.
  5. INTERFACE CONTRACT: Consumes does not list parent RFC exports (CeremonyStatus, assert_ceremony_author, get_current_actor, path helpers). Only references "parent" in the header.
  6. IMPORT PATH: Consumes code block says `from ceremony_context import ...` — should be `from .ceremony_context import ...` or similar relative import matching codebase convention.
-->

> See [product spec](../product/speed-define-ceremony.md) for product context.
> See [foundation reference](speed-define-ceremony-foundation.md) for shared types, API index, validation rules.
> Parent RFC: [speed-define-ceremony](speed-define-ceremony.md)
> Depends on: [parent](speed-define-ceremony.md), [context](speed-define-ceremony-context.md)

## PRD & Design Traceability

**User Stories**: S3 (LLM draft generation from intent + context), S4 (continuous validation, 6 dimensions, template conformance), S6 (cross-spec contradiction and coverage gap detection), S10 (multi-RFC decomposition guidance)

**User Flows**: "Authoring with context" (steps 1-7), "Authoring a complex feature (multi-RFC)" (steps 1-6), "Cross-spec contradiction resolution" (steps 1-5), "Cross-spec coverage gap" (steps 1-4)

**Success Criteria**: System generates complete first draft; generated draft presented in interactive editor; all specs conform to SPEED template; validation runs continuously (6 dimensions); sizing analysis guides decomposition; cross-spec validation flags contradictions and coverage gaps

**Design Components**: CeremonyLayout (`ceremony/CeremonyLayout.tsx`), SpecEditor (existing, no changes), EditorTabBar (modified `editor/EditorTabs.tsx`, adds child RFC tabs), ValidationGutter (`ceremony/ValidationGutter.tsx`), ValidationBadge (`ceremony/ValidationBadge.tsx`), ScopeRefineBar (created by Context RFC, consumed here)

**Design Regions**: editor-area, validation-gutter

**Design Routes**: `/define/:feature` (ceremony editor)

**Design Interactions**: Save spec (Tier 1 validation runs live), click Validate / Cmd+Shift+R (all 6 dimensions), click validation badge (expand gutter), click inline validation marker (scroll gutter), click cross-spec flag (navigate to other tab), validation marker appear (150ms ease-out)

## Basic Example

```tsx
// /define/:feature page
<CeremonyLayout feature={featureName}>
  <ContextPanel mode="ceremony" contextPackage={pkg} />
  <EditorArea>
    <EditorTabBar childRfcTabs={childTabs} suggestionCount={3} />
    <SpecEditor content={draft} readOnly={false} />
    <ValidationGutter dimensions={validationState} />
  </EditorArea>
  <SuggestionSidebar suggestions={suggestions} isAuthor={true} />
  <CommitBar validation={summary} unresolvedCount={2} onCommit={handleCommit} />
</CeremonyLayout>
```

The CeremonyLayout composes existing components (SpecEditor, IntelPanel) with new ceremony surfaces (ValidationGutter, CommitBar). The editor itself has no ceremony awareness.

## Interface Contract

### Consumes (from context RFC)

```python
from ceremony_context import ContextPackage, assemble_context_package, load_context_package

# Used to populate ContextPanel in ceremony mode
# Used to ground LLM draft generation
```

### Produces (for commit and contributor RFCs)

```python
@dataclass
class ValidationState:
    dimensions: list[ValidationDimension]
    summary: ValidationSummary  # pass/warn/fail counts
    timestamp: str  # when validation last ran

@dataclass
class ValidationDimension:
    name: str  # "template" | "structure" | "cross_spec" | "codebase" | "sizing" | "vision"
    status: str  # "pass" | "warn" | "fail" | "pending"
    issues: list[ValidationIssue]

@dataclass
class ValidationIssue:
    id: str
    dimension: str
    severity: str  # "error" | "warning" | "info"
    message: str
    location: IssueLocation | None  # section, line reference in spec
    cross_ref: CrossSpecRef | None  # for cross-spec issues: target spec + section

@dataclass
class SpecDraft:
    feature_name: str
    spec_type: str  # "prd" | "rfc" | "design"
    content: str  # markdown
    file_path: str  # where it will be written (e.g., specs/product/sort-auth.md)
    child_specs: list[SpecDraft]  # for multi-RFC topologies

def generate_spec_draft(intent: str, context: ContextPackage, spec_type: str) -> SpecDraft:
    """LLM generates a complete spec draft from intent + context. Validates against template and audit before returning."""

def load_spec_draft(project_root: Path, feature_name: str) -> SpecDraft | None:
    """Load the current draft for a feature. Returns None if no draft exists."""

def validate_spec(draft: SpecDraft, project_root: Path) -> ValidationState:
    """Run all 6 validation dimensions against the current draft."""
```

## Data Model

### SpecDraft (in-memory, persisted via GraphQL)

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| feature_name | string | no | Feature this draft belongs to |
| spec_type | enum | no | "prd", "rfc", "design" |
| content | string | no | Full markdown content |
| file_path | string | no | Target path relative to project root |
| template_name | string | no | Template used: "prd.md", "rfc.md", "design.md" |
| generated_at | ISO 8601 | yes | When the LLM generated the initial draft. Null if manually created. |
| child_specs | SpecDraft[] | no | Empty for single-spec, populated for multi-RFC |

### ValidationDimension

| Field | Type | Description |
|-------|------|-------------|
| name | string | One of 6 dimension names |
| status | enum | "pass", "warn", "fail", "pending" |
| issues | ValidationIssue[] | Issues found in this dimension |
| checked_at | ISO 8601 | When this dimension was last validated |

### ValidationIssue

| Field | Type | Description |
|-------|------|-------------|
| id | string | Unique issue ID (dimension + hash) |
| dimension | string | Which dimension found this |
| severity | enum | "error", "warning", "info" |
| message | string | Human-readable description |
| location | object or null | `{ section: string, line: number }` in the spec |
| cross_ref | object or null | `{ target_spec: string, target_section: string }` for cross-spec issues |

### CrossSpecIssue (for cross-spec validation)

| Field | Type | Description |
|-------|------|-------------|
| type | enum | "contradiction" or "coverage_gap" |
| message | string | Description of the conflict |
| source_spec | string | File path of the spec where the issue was found |
| source_section | string | Section heading in source spec |
| target_spec | string | File path of the conflicting spec |
| target_section | string | Section heading in target spec |

## API Surface

### Mutations

#### `generateDraft(featureName: String!, specType: String!): GenerateDraftResult!`

Calls the LLM to generate a complete spec draft from the persisted intent and context package.

1. Loads context package from `.speed/features/{feature}/context-package.json`
2. Reads the appropriate SPEED template (`templates/{specType}.md`)
3. Sends intent + context + template to the configured LLM provider
4. Validates the generated draft against template conformance and audit structural checks
5. If validation fails, retries generation with feedback (up to 2 retries)
6. Returns the draft content and its spec_type

**Error cases:**
- Context package not found: return error suggesting `declareIntent` first
- LLM provider not configured: return error with `speed.toml` guidance
- Draft fails validation after 3 attempts: return the best attempt with validation issues attached

#### `updateDraft(featureName: String!, content: String!): UpdateDraftResult!`

Saves the author's edits to the spec draft. Triggers async validation.

**Error cases:**
- Feature not found: return error
- Caller is not the ceremony author: return ownership error

#### `validateDraft(featureName: String!): ValidationState!`

Runs all 6 validation dimensions against the current draft. Returns the full state.

Validation dimensions are split into two tiers based on cost:

**Tier 1 — Live (run on every save, < 100ms):**

| Dimension | Source | What it checks |
|-----------|--------|----------------|
| template | Template file + draft | Required sections present, correct headings, table formats match template |
| structure | Draft content | Acceptance criteria in Given/When/Then, user stories have IDs, scope has in/out sections |

**Tier 2 — On-demand (run when explicitly triggered or at commit time):**

| Dimension | Source | What it checks |
|-----------|--------|----------------|
| cross_spec | All specs in topology | Contradictions between companion specs, PRD user stories mapped to child RFCs |
| codebase | Semantic graph + draft | References to files/functions that exist or don't exist, API endpoints mentioned |
| sizing | Draft + audit heuristics | Task count estimate, whether decomposition is recommended (>10 tasks) |
| vision | Vision doc + draft | Alignment with product vision (Guardian-style check) |

**Validation triggers:**

| Trigger | What runs | UI feedback |
|---------|-----------|-------------|
| Spec file saved (auto, on every edit) | Tier 1 only (template + structure) | Badges update immediately, no loading state |
| Author clicks "Validate" button or presses Cmd+Shift+R | All 6 dimensions | Loading spinner on Tier 2 badges, results replace previous state |
| Draft generation completes | All 6 dimensions | Automatic, no author action needed |
| Author clicks "Commit" | All 6 dimensions | Runs as precondition before commit dialog opens. If Tier 1 fails, commit is blocked. Tier 2 results are shown in the commit dialog. |

Tier 2 badges display staleness: if the draft has been edited since the last Tier 2 run, badges show a subtle stale indicator (dimmed, with "last checked: 2m ago" tooltip). Stale badges do not block commit — the commit action re-runs all dimensions.

#### `generateChildRfcs(featureName: String!, decomposition: DecompositionInput!): [SpecDraft!]!`

When the author accepts a decomposition recommendation:
1. Takes the decomposition plan (user story groupings, child RFC names)
2. Generates each child RFC from the parent PRD context + subsystem-scoped context
3. Each child RFC passes template + audit validation before returning
4. Updates the parent PRD's RFC Decomposition table

**Input:**
```graphql
input DecompositionInput {
  children: [ChildRfcInput!]!
}
input ChildRfcInput {
  name: String!
  userStoryIds: [String!]!
  dependsOn: [String!]
}
```

### Queries

#### `specDraft(featureName: String!): SpecDraft`

Returns the current draft for a feature. Includes child specs for multi-RFC topologies.

#### `validationState(featureName: String!): ValidationState`

Returns the latest validation state. Called after Tier 1 runs (on save) or after a full validation run (on-demand or at commit time).

## Validation Rules

| Field | Constraints |
|-------|-------------|
| spec content | Cannot be empty at commit time. No maximum length. |
| template conformance | All required sections from the SPEED template must be present. Missing sections produce "error" severity. Extra sections are allowed (produce no issue). |
| cross-spec references | PRD user story IDs referenced in RFC must match actual story IDs in the PRD. Mismatches produce "error" severity. |
| codebase references | File paths and function names in backticks are checked against the semantic graph. Missing references produce "warning" severity (the author may be describing something new). |
| sizing threshold | >10 estimated tasks produces a "warning" recommending decomposition. >15 produces an "error" recommending decomposition. Author can override by proceeding with a single RFC. |
| vision alignment | Runs only when vision_status is "defined". "placeholder" and "missing" produce a standing "warning" that vision alignment cannot be verified. |

## Testing

### Acceptance Criteria

- Given an intent and context package, when `generateDraft` is called, then the LLM produces a complete spec using the correct SPEED template, and the draft passes template conformance and audit validation before being returned
- Given a spec draft with a missing required section, when validation runs, then the template dimension reports "fail" with an issue identifying the missing section
- Given a PRD and an RFC that contradict each other (different data types for the same field), when cross-spec validation runs, then a cross-spec issue is reported with references to both specs and sections
- Given a PRD with 5 user stories and an RFC Decomposition mapping only 4 of them, when cross-spec validation runs, then a coverage gap issue is reported for the unmapped story
- Given a spec that references `src/models/User.php` and the file exists in the semantic graph, when codebase validation runs, then no issue is reported for that reference
- Given a spec estimated at 12 tasks, when sizing validation runs, then a warning recommends decomposition
- Given author saves the spec, then Tier 1 validation (template + structure) runs immediately and badges update within 100ms
- Given author clicks Validate (or presses Cmd+Shift+R), then all 6 dimensions run and Tier 2 badges update with results
- Given author has edited the spec since the last full validation, then Tier 2 badges show a stale indicator (dimmed with "last checked" tooltip)
- Given author clicks Commit, then all 6 dimensions run as a precondition before the commit dialog opens

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| LLM generates spec that fails template validation | High | Integration test: generate drafts for 3 different spec types, verify all pass template check. Test the retry loop with intentionally bad first attempts. |
| Cross-spec validation false positives (flagging non-contradictions) | Medium | Unit test: construct pairs of specs with subtle similarities that aren't contradictions, verify no false flags |
| Validation latency exceeds 2s budget on large specs | Medium | Performance test: validate a 500-line spec with 20 references, verify total time < 2s |
| Sizing heuristic miscounts tasks | Low | Unit test: specs of known complexity (3, 10, 15 tasks), verify estimates within +/- 2 |

### Test Plan

**Unit tests**
- `test_template_conformance`: missing sections, extra sections, malformed tables
- `test_cross_spec_contradiction`: matching field names with different types, matching story IDs with different criteria
- `test_cross_spec_coverage_gap`: unmapped stories, partially mapped stories
- `test_codebase_references`: existing files, missing files, new files (no issue)
- `test_sizing_estimate`: small spec (3 tasks), medium (10), large (15+)
- `test_vision_alignment`: defined vision, placeholder (warning), missing (warning)

**Integration tests**
- `test_generate_draft_prd`: full generation with real context package
- `test_generate_draft_rfc`: full generation with parent PRD context
- `test_validation_pipeline`: all 6 dimensions on a realistic spec
- `test_graphql_mutations`: `generateDraft`, `updateDraft`, `validateDraft` through Strawberry schema

**Visual/UI tests**
- CeremonyLayout renders three-panel layout at 1280px
- ValidationGutter toggles between collapsed (40px) and expanded (200px)
- Inline validation markers appear as 2px left-border (red/amber/blue)
- Cross-spec flag click navigates to target tab and highlights section
- EditorTabBar renders child RFC tabs with correct labels

### Edge Cases

- Empty context package (no graph, no learnings): LLM generates from intent and template alone
- Spec with zero references to codebase: codebase dimension returns "pass" with no issues
- Multi-RFC with circular dependencies between child RFCs: validation flags as error
- Author saves rapidly: Tier 1 runs on each save (< 100ms, no throttling needed). Tier 2 only runs on explicit trigger, so rapid editing has no impact on expensive checks.
- Very long spec (1000+ lines): validation runs in background, does not block editor interaction
- Cross-spec validation with one spec open and one not yet created: skip cross-spec for missing companion, report as "pending"

### Out of Scope

- Real-time collaborative editing (multiple authors editing simultaneously). Single-author only. Real-time co-editing requires distributed locking and conflict resolution.
- Diff view showing changes between LLM draft and author edits. Useful but not critical for initial release.
- Undo/redo for accepted suggestions. Standard editor undo handles this at the text level.

## Security & Controls

**Authentication**: Local dashboard, no additional auth.

**Authorization**: `generateDraft`, `updateDraft` require author ownership. `validateDraft` and `specDraft` are read-only queries accessible to any actor.

**LLM data**: Draft generation sends intent + context + template to the configured LLM provider. Context contains codebase structure, not source code. The LLM provider is configured by the user in `speed.toml`.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| CeremonyLayout composes SpecEditor, not extends it | Composition | Add `mode` prop to SpecEditor | SpecEditor stays unchanged. Ceremony features are layout concerns, not editor concerns. Reduces blast radius of ceremony changes. |
| ContextPanel extends IntelPanel with `mode` prop | Extension | New component, Composition wrapper | IntelPanel already has 5 of 7 needed sections. Adding 2 sections and a data source switch is less work and more consistent than building from scratch. |
| Validation runs on backend, results delivered via GraphQL | Backend validation | Frontend-only validation, Hybrid | Template and codebase checks require filesystem access. Cross-spec needs multiple files. Backend is the only place with full context. |
| Two-tier validation model | Tier 1 live on save, Tier 2 on-demand | All dimensions live (debounced), All dimensions on-demand only | Running all 6 dimensions on every edit is expensive (codebase reads the semantic graph, vision calls the Guardian). Tier 1 (template + structure) is cheap (< 100ms, markdown parsing only) and gives immediate feedback. Tier 2 runs when the author is ready to check or commit. |
| Draft generation retries up to 2 times on validation failure | Retry with feedback | Single attempt, Unlimited retries | First attempts often miss a section. Feedback-driven retry usually fixes it. 3 attempts total caps the cost. |

## Drawbacks

- LLM draft generation adds a dependency on an external service (the configured LLM provider). If the provider is down or slow, the ceremony stalls at the authoring step. The author can fall back to manual writing.
- Tier 2 validation only runs on explicit trigger, so backend load scales with how often authors click Validate, not how fast they type. For a team of 5, worst case is 5 concurrent full validation runs (one per ceremony), not 5 per edit.
- Cross-spec validation requires loading all companion specs on every run. For a PRD with 5 child RFCs, each validation run reads 6 files.

## File Impact

**New files:**
- `dashboard/backend/resolvers/ceremony_editor.py` — resolver for draft generation, update, validation
- `dashboard/backend/resolvers/ceremony_editor_types.py` — Strawberry types for SpecDraft, ValidationState
- `dashboard/backend/ceremony_validator.py` — validation pipeline: 6 dimension runners
- `dashboard/backend/ceremony_generator.py` — LLM draft generation with template + audit gate
- `dashboard/frontend/components/define/ceremony/CeremonyLayout.tsx` — page composition
- `dashboard/frontend/components/define/ceremony/ValidationGutter.tsx` — collapsed/expanded validation display
- `dashboard/frontend/components/define/ceremony/ValidationBadge.tsx` — individual dimension badge
- `dashboard/frontend/components/define/ceremony/CommitBar.tsx` — owned by Commit RFC. Editor RFC imports `ValidationSummary` type for display but does not create this file.
- `dashboard/frontend/components/define/ceremony/ScopeRefineBar.tsx` — intent refinement at top of context panel
- `dashboard/frontend/lib/graphql/queries/ceremony-editor.ts` — GraphQL queries and mutations
- `dashboard/frontend/app/define/[feature]/page.tsx` — ceremony editor route

**Modified files:**
- `dashboard/backend/schema.py` — register editor mutations and queries. **Integration order**: second (after context RFC).
- `dashboard/frontend/components/editor/IntelPanel.tsx` — consumed as already modified by Context RFC (ceremony mode with `mode` prop, Defects/Vision Status/Audit History sections). Editor RFC does not modify this file.
- `dashboard/frontend/components/editor/EditorTabs.tsx` — add child RFC tabs for multi-RFC topologies. Suggestion sidebar toggle is owned by the Contributor RFC.

## Dependencies

- Context RFC: `ContextPackage`, `load_context_package()` for grounding draft generation and populating ContextPanel
- LLM provider configured in `speed.toml` for draft generation
- SPEED templates at `templates/prd.md`, `templates/rfc.md`, `templates/design.md`
- Audit agent logic for structural/completeness checks (reused in template and structure dimensions)
- Guardian agent for vision alignment dimension
- Semantic graph for codebase reference validation

## Unresolved Questions

| Question | Blocks | Proposed Resolution |
|----------|--------|---------------------|
| Should the LLM draft be cached or regenerated each time? | Performance, cost | Cache the initial draft. Author edits overwrite. Regeneration only on explicit "Regenerate" action (not in scope for the ceremony editor; regeneration is available in the bootstrap VisionDraftEditor). |
| How does codebase validation handle references to things the author intends to create (new files, new functions)? | False positive rate | Treat backtick references not found in the graph as "info" severity, not "warning". The author is likely describing something new. Only flag "warning" when a reference looks like an existing path pattern but doesn't match. |
| Should validation results persist across sessions? | Resume experience | Yes. Write `validation-state.json` alongside the draft. On page reload, show the last validation state immediately while re-running in the background. |
