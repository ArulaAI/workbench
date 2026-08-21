# RFC: Define Ceremony — Context Package

<!-- REWRITE ANNOTATIONS: All resolved. See git history for original annotations. -->

> See [product spec](../product/speed-define-ceremony.md) for product context.
> See [foundation reference](speed-define-ceremony-foundation.md) for shared types, API index, validation rules.
> See [design spec](../design/speed-define-ceremony.md) for component specs and interaction patterns.
> Depends on: [parent RFC](speed-define-ceremony.md) (shared types, path helpers, state machine).

## PRD & Design Traceability

**User Stories**: S1 (intent declaration + scoping), S2 (context delivery from 7 sources), S13 (historical context viewing)

**User Flows**: "Declaring intent and receiving context" (steps 1-7)

**Success Criteria**: Intent accepts free-text input and scopes assembly; context package assembles from 7 sources; context package persisted at `.speed/features/{feature}/context-package.json`; context package API is surface-agnostic

**Design Components**: IntentInput (`ceremony/IntentInput.tsx`), ContextPanel (modified `editor/IntelPanel.tsx` with `mode` prop, adds Defects/Vision Status/Audit History sections), ContextSection (existing, no changes), ScopeRefineBar (`ceremony/ScopeRefineBar.tsx`)

**Design Regions**: intent-input, context-panel

**Design Routes**: `/define/new` (intent input), `/define/:feature` (context panel within ceremony editor)

## Basic Example

```graphql
mutation {
  declareIntent(
    text: "Users should be able to sort the auth list by last activity",
    featureName: "sort-auth-by-last-activity"
  ) {
    featureName
    contextPackage {
      codebase { path, description }
      learnings { text, sourceFeature }
      defects { name, severity }
      projectKnowledge { text, confidence }
      visionStatus
      relatedFeatures { name, state }
      auditHistory { featureName, finding, severity }
    }
  }
}
```

The frontend calls `declareIntent` with the author's free-text intent and their chosen feature name. The backend validates the feature name, scopes the semantic graph using the intent text, assembles context from seven sources, persists the package to disk, and returns the structured result. The frontend first renders the BLUF (synthesized summary), then the context panel with drill-down sections.

## Interface Contract

### Consumes (from parent and foundation)

From [parent RFC](speed-define-ceremony.md):
- `CeremonyStatus` enum (for ceremony state checks)
- `CeremonyState`, `Revision` dataclasses (for reading `ceremony.json`)
- `create_revision()` (creates the initial ceremony at DRAFTING on `declareIntent`)
- `assert_ceremony_author()` (ownership gate for `refineIntent`)
- `get_current_actor()` (identity resolution for author attribution)
- Path helpers: `ceremony_dir()`, `ceremony_state()`, `ceremony_intent()`, `ceremony_context_package()` (all on `SpeedPaths`)

From existing codebase:
- `SpeedPaths.memory_dir`, `SpeedPaths.feature_shared()`, `SpeedPaths.feature_local()` for SP/MP-aware path resolution
- `sklearn.feature_extraction.text.TfidfVectorizer` for learnings relevance scoring (same pattern as `lib/context/related_specs.py`)

### Produces (for downstream RFCs)

#### Types

```python
@dataclass
class ContextPackage:
    intent: str
    feature_name: str
    scoped_area: list[str]            # CSG node IDs matching the intent
    codebase: list[CodebaseItem]
    learnings: list[LearningItem]
    defects: list[DefectItem]
    project_knowledge: list[KnowledgeItem]
    vision_status: str                # "available" | "missing" | "stale"
    vision_content: str | None        # specs/product/overview.md content, null when missing
    related_features: list[RelatedFeature]
    audit_history: list[AuditHistoryItem]
    assembled_at: str                 # ISO timestamp
    sources_status: dict[str, str]    # per-source: "ok" | "error" | "empty"
    scoping_method: str               # "llm" | "keyword" | "full_graph"
    low_confidence: bool              # True when scope fell back or >40% matched

@dataclass
class ContextHistory:
    snapshot: ContextPackage | None    # Persisted package from commit time
    current: ContextPackage | None     # Fresh assembly for the same scoped_area
    current_assembly_status: str       # "ok" | "error"
    current_assembly_error: str | None # Error message if current assembly failed
    ceremony: CeremonyInfo             # Author, committed date, status (from parent RFC)

@dataclass
class DeclareIntentResult:
    feature_name: str
    context_package: ContextPackage
    ceremony: CeremonyInfo             # Created ceremony state
```

#### Validation

```python
class FeatureNameError(Exception):
    """Raised when feature name is invalid or collides."""
    reason: str  # "invalid_chars" | "too_long" | "empty" | "collision"
    detail: str  # human-readable: "Feature name must be lowercase..." or "Feature 'x' is owned by Jane Doe"

def validate_feature_name(name: str) -> str:
    """Validate and normalize a feature name.

    Rules:
    - Must be non-empty
    - Lowercase only (reject if uppercase chars present, don't silently lowercase)
    - Alphanumeric and hyphens only (no underscores, dots, spaces)
    - Cannot start or end with a hyphen
    - Cannot contain consecutive hyphens
    - Max 50 characters
    - Returns the validated name (stripped of leading/trailing whitespace)
    - Raises FeatureNameError with reason and detail on failure
    """

def check_feature_name_collision(paths: SpeedPaths, feature_name: str) -> str | None:
    """Check if a feature directory already has an active ceremony.

    Returns the existing author name if collision exists, None if clear.
    A ceremony is 'active' if its current revision status is DRAFTING or COMMITTED.
    Ceremonies in RATIFIED, REJECTED, or ABANDONED states do not block new ceremonies
    with the same name.
    """
```

#### Scoping

```python
def scope_csg_nodes(
    intent: str,
    graph_path: Path,
    *,
    use_llm: bool = True,
    model: str | None = None,
    conn: Any = None,
    project_root: Any = None,
) -> tuple[list[str], bool]:
    """Scope the semantic graph to nodes relevant to the author's intent.

    Two-tier strategy:
    1. If use_llm is True and a model is available, ask the LLM to select
       seed files directly from the project's file list. The LLM receives
       the full intent and all file paths from the semantic graph, and
       returns the subset that are integration points, pattern references,
       data sources, or core infrastructure. Seed files are mapped back to
       CSG node IDs (all nodes in a seed file are included).
    2. Fall back to keyword tokenization with word-boundary matching (not
       substring). If >40% of nodes match, sets low_confidence=True.
    3. If no matches, return all node IDs (full graph fallback) with
       low_confidence=True.

    When no model parameter is provided, the function attempts to resolve
    one from the ceremony model config via get_ceremony_models().

    Returns:
        Tuple of (matching_node_ids, low_confidence). Empty list if the
        graph file doesn't exist.
    """
```

Two helper functions support the scoping pipeline:

```python
def _llm_select_seed_files(
    intent: str,
    nodes: list[dict],
    *,
    model: str | None = None,
    conn: Any = None,
    project_root: Any = None,
) -> list[str] | None:
    """Ask the LLM to select seed files from the project file list.

    Builds a deduplicated file list from graph nodes. Sends the intent and
    file list to the LLM via llm_complete with the SeedFiles response model.
    Validates returned paths against actual files (rejects hallucinated paths).
    Returns a list of file paths, or None if unavailable.
    """

def _keyword_tokens(intent: str) -> set[str]:
    """Tokenize intent into keyword set for fallback matching.

    Splits on non-word characters, lowercases, removes stop words and
    single-character tokens. Used only when LLM scoping is unavailable.
    """
```

#### Source Readers

Each reader is independent. A failure in one does not affect the others. Each returns its typed list (empty on error) and the caller records the per-source status.

```python
def read_codebase_context(paths: SpeedPaths, scoped_nodes: list[str]) -> list[CodebaseItem]:
    """Read semantic graph nodes matching the scoped_area.

    For each scoped node ID, extract:
    - path: the file path from the node
    - description: built from the node's name and kind (e.g., "function detect_platform",
      "class AuditWatcher"), or the node's own description if it has one
    - node_ids: the CSG node IDs this item belongs to

    The frontend groups items by file path for display (ContextPanel) and
    shows file-level summaries with symbol counts (BLUF).
    """

def read_learnings(paths: SpeedPaths, scoped_files: list[str], intent: str = "") -> list[LearningItem]:
    """Read observations filtered by TF-IDF similarity to the intent.

    Glob .speed/shared/knowledge/observations/*.jsonl (MP) or
    .speed/memory/observations/*.jsonl (SP). For each observation, extract
    display text from the detail dict (trying keys: finding, concern,
    what_happened, review_verdict, title, message). Prefix with category
    when available.

    Relevance filtering uses sklearn TF-IDF cosine similarity between the
    intent text and each observation's searchable text (feature name +
    observation type + display text). Only observations scoring above a
    0.05 threshold are included, ranked by score.

    This approach follows the same pattern as lib/context/related_specs.py.
    Results sorted by confidence: high/locked first, then medium, then low.
    """

def read_defects(paths: SpeedPaths, scoped_files: list[str], feature_name: str = "") -> list[DefectItem]:
    """Read defects filtered by scoped file paths and feature relevance.

    Source 1: .speed/defects/*/state.json — filter by related_files overlap
    with scoped files. Defects with empty related_files are excluded (cannot
    verify relevance).

    Source 2: specs/defects/*.md — parse header metadata (Related Feature,
    Tags, Severity, Related Files). Filter by: (a) related_files overlap,
    (b) related feature terms overlapping with scope terms, or (c) tags
    overlapping with scope terms. Defects with no matching metadata are excluded.

    Results sorted by severity: critical first, then major, then minor.
    """

def read_project_knowledge(paths: SpeedPaths) -> list[KnowledgeItem]:
    """Read curated conventions from .speed/shared/knowledge/conventions.json.

    Returns all entries as KnowledgeItem with text, confidence, source.
    This is not scoped — project knowledge is global. All conventions are
    returned and the frontend displays them all.

    Results sorted by confidence: high first, then medium, then low.
    """

def read_vision(project_root: Path) -> tuple[str, str | None]:
    """Read product vision from specs/product/overview.md.

    Returns (vision_status, vision_content):
    - ("available", content) — file exists and has substantive content (> 50 chars, not just headings)
    - ("stale", content) — file exists but is a template (< 50 chars or only headings)
    - ("missing", None) — file does not exist
    """

def read_related_features(paths: SpeedPaths, scoped_files: list[str], current_feature: str) -> list[RelatedFeature]:
    """Find other features with shared file paths.

    Primary: read context-package.json from prior ceremonies and check
    codebase file path overlap with scoped_files.

    Fallback: when no context-package.json exists, aggregate files_touched
    from task JSON files (.speed/shared/features/{name}/tasks/*.json) and
    check overlap. This ensures features that predate the Define Ceremony
    are still discoverable.

    Returns matching features with name, state, and overlap_files.
    """

def read_audit_history(paths: SpeedPaths, scoped_area: list[str]) -> list[AuditHistoryItem]:
    """Read audit findings from plan-audit-*.json files.

    Glob .speed/local/features/*/logs/plan-audit-*.json. These are
    structured audit results produced by the spec audit pipeline. Files
    may be wrapped in markdown code fences (stripped before parsing).

    Each file contains an issues array with severity, section, and message.
    Severity values are mapped: error → critical, warning → major.

    Results sorted by severity: critical first, then major, then minor, then info.
    """
```

#### Assembly

```python
def assemble_context_package(
    project_root: Path,
    intent: str,
    feature_name: str,
    *,
    model: str | None = None,
    conn: Any = None,
    sub_manager: Any = None,
) -> ContextPackage:
    """Assemble a scoped context package from 7 sources.

    1. Call scope_csg_nodes() with LLM-assisted extraction when model is
       available, keyword fallback otherwise
    2. Derive scoped_files from the codebase items' paths
    3. Call each reader independently. If a reader raises, catch the exception,
       log it, and record "error" for that source in sources_status. Other
       readers continue.
    4. Emit per-source progress events via sub_manager when available
       (enables the contextAssemblyProgress subscription)
    5. Build the ContextPackage with all results
    6. Set assembled_at to current ISO timestamp
    7. Set sources_status per source: "ok" (data returned), "error" (reader
       failed), "empty" (reader returned empty list and no error)
    8. Persist via persist_context_package()
    9. Return the package

    Args:
        model: LLM model ID for intent scoping. None uses keyword fallback.
        conn: database connection passed through to LLM calls.
        sub_manager: SubscriptionManager for emitting progressive events.
    """

def persist_context_package(
    project_root: Path,
    feature_name: str,
    pkg: ContextPackage,
) -> Path:
    """Write ContextPackage to .speed/features/{feature}/context-package.json.

    Serializes the dataclass to JSON. Overwrites any existing file (refinement
    replaces the previous package). Returns the written path.
    """

def load_context_package(
    project_root: Path,
    feature_name: str,
) -> ContextPackage | None:
    """Load a previously persisted context package.

    Reads .speed/features/{feature}/context-package.json and deserializes
    to ContextPackage. Returns None if the file doesn't exist.

    Handles schema evolution: missing fields default to empty lists or None.
    Does not raise on malformed JSON — returns None and logs.
    """
```

#### Consumers

The [editor RFC](speed-define-ceremony-editor.md) consumes `ContextPackage` for the ContextPanel display. The [commit RFC](speed-define-ceremony-commit.md) consumes `persist_context_package` to snapshot context at commit time. The [bootstrap RFC](speed-define-ceremony-bootstrap.md) calls `assemble_context_package` after bootstrap completes to verify context delivery works. The history view (`/define/:feature/history`) consumes `load_context_package` for the snapshot and `assemble_context_package` for the current comparison via the `contextHistory` query.

## Data Model

All nested types (`CodebaseItem`, `LearningItem`, etc.) are defined in the [foundation reference](speed-define-ceremony-foundation.md#shared-strawberry-types) and implemented in `ceremony_types.py` by the [parent RFC](speed-define-ceremony.md). This RFC consumes them; it does not redefine them. The field tables below are summaries for quick reference. The foundation is authoritative.

### `intent.json` (persisted to `SpeedPaths.ceremony_intent(feature)`)

Created by `declareIntent`, updated by `refineIntent`.

```python
@dataclass
class IntentRecord:
    text: str           # Free-text intent (min 5 chars)
    author: str         # Resolved by get_current_actor()
    author_email: str   # Resolved by get_current_actor()
    created_at: str     # ISO 8601, set once at creation
    feature_name: str   # Author-provided, validated on input
```

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| text | string | no | Free-text intent from the author (min 5 chars, whitespace-trimmed) |
| author | string | no | Display name from `get_current_actor()` |
| author_email | string | no | Email from `get_current_actor()` |
| created_at | string (ISO 8601) | no | When `declareIntent` was called. Immutable on `refineIntent`. |
| feature_name | string | no | Author-provided feature name. Lowercase, hyphens, max 50 chars. Validated on input, not derived from intent text. |

**Example:**

```json
{
  "text": "Users should be able to sort the auth list by last activity, specifically the accessedAt attribute",
  "author": "Jane Doe",
  "author_email": "jane@example.com",
  "created_at": "2026-03-29T10:00:00Z",
  "feature_name": "sort-auth-by-last-activity"
}
```

### `context-package.json` (persisted to `SpeedPaths.ceremony_context_package(feature)`)

Created by `declareIntent`, re-created by `refineIntent`.

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| intent | string | no | Original intent text from the author |
| feature_name | string | no | Author-provided feature name |
| scoped_area | string[] | no | CSG node IDs that matched the intent scope |
| codebase | [CodebaseItem](speed-define-ceremony-foundation.md#shared-strawberry-types)[] | no | Relevant files, functions, and descriptions from the scoped area |
| learnings | [LearningItem](speed-define-ceremony-foundation.md#shared-strawberry-types)[] | no | Observations and conventions from past features in this area |
| defects | [DefectItem](speed-define-ceremony-foundation.md#shared-strawberry-types)[] | no | Open defects related to the scoped area |
| project_knowledge | [KnowledgeItem](speed-define-ceremony-foundation.md#shared-strawberry-types)[] | no | Curated conventions from project-knowledge.json |
| vision_status | string | no | `"available"` / `"missing"` / `"stale"` |
| vision_content | string | yes | Content of `specs/product/overview.md`. Null when vision_status is `"missing"`. |
| related_features | [RelatedFeature](speed-define-ceremony-foundation.md#shared-strawberry-types)[] | no | Other ceremonies touching overlapping files |
| audit_history | [AuditHistoryItem](speed-define-ceremony-foundation.md#shared-strawberry-types)[] | no | Audit findings from past specs in this area |
| assembled_at | string (ISO 8601) | no | When the package was assembled |
| sources_status | dict | no | Per-source assembly status (`"complete"` / `"error"`) |
| scoping_method | string | no | `"llm"` / `"keyword"` / `"full_graph"` — which scoping strategy was used |
| low_confidence | boolean | no | True when scope fell back to full graph or >40% of nodes matched |

**Example:**

```json
{
  "intent": "sort auth list by last activity",
  "feature_name": "sort-auth-by-last-activity",
  "scoped_area": ["csg:users-module", "csg:auth-endpoints"],
  "codebase": [
    { "path": "src/Users.php", "description": "User model with accessedAt attribute", "node_ids": ["csg:users-module"] }
  ],
  "learnings": [
    { "text": "Queryable attributes require index migration", "source_feature": "add-search-filter", "confidence": "high" }
  ],
  "defects": [],
  "project_knowledge": [
    { "text": "All new queryable fields need a migration spec", "confidence": "high", "source": "observation" }
  ],
  "vision_status": "available",
  "vision_content": "# Product Vision\n\nSPEED is a structured execution pipeline...",
  "related_features": [],
  "audit_history": [],
  "assembled_at": "2026-03-29T10:00:05Z",
  "sources_status": {
    "codebase": "complete",
    "learnings": "complete",
    "defects": "complete",
    "project_knowledge": "complete",
    "vision": "complete",
    "related_features": "complete",
    "audit_history": "complete"
  }
}
```

## API Surface

### Mutations

#### `declareIntent(text: String!, featureName: String!, model: String): DeclareIntentResult!`

Receives free-text intent and an author-provided feature name. The intent is a free-form description of what the author wants to build (can be a sentence or a paragraph). The feature name is a short identifier chosen by the author, used as the directory name and display label.

Performs:
1. Validates the feature name (lowercase, hyphens, alphanumeric only, max 50 chars)
2. Creates `.speed/features/{feature_name}/` directory if it doesn't exist
3. Writes `intent.json` with the intent text, feature name, and author identity (resolved by `get_current_actor()`)
4. Creates `ceremony.json` via `create_revision()` from the [parent RFC](speed-define-ceremony.md), establishing the ceremony at DRAFTING with the declaring actor as author
5. Emits `spec.intent_declared` event to `.speed/shared/events/` (MP) per the [foundation event catalog](speed-define-ceremony-foundation.md#event-types)
6. Scopes the semantic graph using LLM-assisted keyword extraction (falls back to simple tokenization when no model is available)
7. Assembles context from 7 sources (partial assembly on source failure)
8. Persists the package to `context-package.json` via `SpeedPaths.ceremony_context_package()`
9. Returns the assembled package

**Error cases:**
- Feature name collision (directory already exists with an active ceremony): returns error with existing author name
- Feature name invalid (uppercase, special chars, over 50 chars): returns validation error with specific reason
- Semantic graph not built: returns partial package with `sources_status.codebase = "error"` and a message suggesting bootstrap or `speed plan`
- Intent too short (< 5 chars): returns validation error

#### `refineIntent(featureName: String!, text: String!, model: String): DeclareIntentResult!`

Same assembly pipeline as `declareIntent` but for an existing ceremony. Calls `assert_ceremony_author()` to verify the caller owns the ceremony. Updates the `text` field in `intent.json` (preserves original author and created_at). Re-assembles the context package with the new scope. Does not affect the spec draft (which lives in the editor, not in the context package). Does not emit a new event (refinement is not a new claim).

**Error cases:**
- Feature not found: returns error
- Caller is not the ceremony author (checked by `assert_ceremony_author()`): returns ownership error

### Queries

#### `contextPackage(featureName: String!): ContextPackage`

Returns the persisted context package for a feature. Used by the [editor RFC](speed-define-ceremony-editor.md) for initial load, by the [contributor RFC](speed-define-ceremony-contributor.md) for shared context, and by the [commit RFC](speed-define-ceremony-commit.md) for snapshot reference.

Returns null if no context package exists for the feature.

#### `contextAssemblyStatus(featureName: String!): AssemblyStatus!`

Returns per-source status during assembly. Used by the frontend to show progressive loading.

```graphql
type AssemblyStatus {
  status: String!  # "idle" | "assembling" | "complete"
  sources: [SourceStatus!]!
}
type SourceStatus {
  name: String!
  status: String!  # "pending" | "complete" | "error"
  error: String
}
```

#### `contextHistory(featureName: String!): ContextHistory`

Returns the persisted context snapshot alongside a freshly assembled current context for the same scoped area. Used by the `/define/:feature/history` view (S13) to show what the system knew when the spec was authored vs. what's true now.

```graphql
type ContextHistory {
  snapshot: ContextPackage          # Persisted package from commit time
  current: ContextPackage           # Fresh assembly for the same scoped_area
  currentAssemblyStatus: String!    # "ok" | "error"
  currentAssemblyError: String      # Error message if current assembly failed
  ceremony: CeremonyInfo            # Author, committed date, status
}
```

1. Loads the persisted `context-package.json` via `load_context_package()` for the snapshot
2. Reads the snapshot's `scoped_area` and `intent` fields
3. Calls `assemble_context_package()` with the same intent to produce the current context
4. Returns both packages alongside ceremony metadata from `ceremony.json`

**Error cases:**
- No persisted context package: returns null (feature was created before context persistence, or assembly failed at commit time)
- Current assembly fails (semantic graph deleted, project restructured): `snapshot` is returned normally, `current` is null, `currentAssemblyStatus = "error"` with message. The snapshot is still useful for reference.
- Feature not found: returns null

## Validation Rules

| Field | Constraints |
|-------|-------------|
| intent text | Minimum 5 characters. No maximum. Whitespace-trimmed. |
| feature_name | Author-provided. Must be lowercase, alphanumeric and hyphens only, max 50 chars. Must not collide with existing active ceremony. Validated on input, not derived from intent. |
| scoped_area | If no CSG nodes match, falls back to full graph. Author is shown a warning that scoping confidence is low. |
| context package | Assembly continues on individual source failure. Failed sources get `"error"` status. Package is still persisted and returned with available data. |

## Testing

### Acceptance Criteria

- Given an intent string, when `declareIntent` is called, then a context package is assembled from all 7 sources and persisted to `.speed/features/{feature}/context-package.json`
- Given a large codebase with a semantic graph, when intent mentions a specific module, then the scoped_area contains CSG nodes relevant to that module (not the full graph)
- Given a project with no semantic graph, when `declareIntent` is called, then the package is returned with `sources_status.codebase = "error"` and other sources still populate
- Given an existing ceremony, when `refineIntent` is called with new text, then the context package is re-assembled with the new scope and the persisted file is updated
- Given a non-author actor, when they call `refineIntent`, then the mutation returns an ownership error
- Given a feature name collision, when `declareIntent` is called, then the mutation returns an error identifying the existing author
- Given a committed feature with a persisted context package, when `contextHistory` is queried, then the snapshot is returned alongside a fresh current context assembled for the same scoped area
- Given a committed feature with a persisted context package, when the current assembly fails (e.g., semantic graph deleted), then the snapshot is returned with `currentAssemblyStatus = "error"` and `current` is null
- Given a feature with no persisted context package, when `contextHistory` is queried, then null is returned

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| Intent scoping returns irrelevant CSG nodes | Medium | Integration test with a real CSG: verify that "sort auth by last activity" matches Users-related nodes, not unrelated modules. LLM-assisted extraction reduces this risk when a model is available; keyword fallback still carries the original risk. |
| One source failure blocks entire assembly | Medium | Unit test: mock each source to raise, verify package still assembles with error status on failed source |
| Feature name collision not detected | Medium | Unit test: create two ceremonies with similar intents, verify collision is caught |
| Context package too large for frontend rendering | Low | Integration test: assemble package for a 50+ feature project, verify JSON size is under 1MB |

### Test Plan

**Unit tests**
- `test_validate_feature_name`: valid names, invalid chars, too long, empty, collision
- `test_scope_csg_nodes`: LLM seed selection with mock LLM, keyword fallback with word boundaries, full graph fallback, low_confidence detection
- `test_read_learnings_tfidf`: TF-IDF filtering produces relevant subset, threshold behavior, empty intent returns nothing
- `test_read_defects_filtering`: state.json with/without related_files, markdown metadata parsing (Related Feature, Tags), scope filtering
- `test_read_related_features_fallback`: context-package.json primary path, task files_touched fallback, overlap detection
- `test_read_audit_history_format`: plan-audit-*.json parsing, markdown fence stripping, severity mapping
- `test_assemble_sources`: each source individually (mock filesystem), partial failure
- `test_ownership_check`: refine by author succeeds, refine by non-author fails

**Integration tests**
- `test_full_assembly`: real project directory with specs, features, observations, defects, vision doc
- `test_persistence_roundtrip`: assemble, persist, load, compare
- `test_graphql_declare_intent`: full mutation through Strawberry schema
- `test_context_history`: commit a ceremony, query `contextHistory`, verify snapshot matches persisted package and current is a fresh assembly
- `test_context_history_no_snapshot`: query `contextHistory` for a feature with no `context-package.json`, verify null returned
- `test_context_history_current_fails`: query `contextHistory` after deleting the semantic graph, verify snapshot loads and `currentAssemblyStatus` is `"error"`

**Visual/UI tests**
- N/A for this RFC. ContextPanel rendering is covered by the [editor RFC](speed-define-ceremony-editor.md).

### Edge Cases

- Empty project (no specs, no features, no graph): all sources return empty arrays, vision_status is `"missing"`, scoping_method is `"full_graph"`, low_confidence is true
- Vision doc is a blank template (< 50 chars or only headings): vision_status is `"stale"`
- Feature name collides with existing active ceremony: return error with existing author, do not auto-suffix
- LLM seed selection returns hallucinated paths: validated against actual file list, invalid paths are silently dropped
- LLM seed selection fails (model unavailable, timeout): falls back to keyword matching with warning log
- Keyword fallback matches >40% of graph nodes: low_confidence is set to true, BLUF shows a warning
- Defect specs with no Related Feature/Tags/Related Files metadata: excluded from results (cannot verify relevance)
- Defect state.json with empty related_files: excluded from results
- Observations JSONL has malformed lines: skip and log, don't fail the source
- All observations have zero TF-IDF similarity to intent: learnings returns empty list
- sklearn not available: all observations returned unfiltered (graceful degradation)
- No features have context-package.json: related features reader falls back to task JSON files_touched
- Audit log files wrapped in markdown code fences: fences stripped before JSON parsing
- Context history where the snapshot was assembled with an older version of the context package schema: `load_context_package` handles missing fields gracefully (scoping_method defaults to "keyword", low_confidence defaults to false)

### Scope Boundary

This RFC covers five things:

- **Intent declaration and refinement** — `declareIntent` and `refineIntent` mutations, intent persistence
- **Context assembly** — scoping the semantic graph, reading 7 sources, assembling the `ContextPackage`
- **Context persistence** — writing and reading `context-package.json`
- **Context queries** — `contextPackage` and `contextAssemblyStatus` GraphQL queries
- **Historical context** — `contextHistory` query that returns the persisted snapshot alongside a fresh current assembly for comparison (S13)

The editor, validation, spec draft generation, suggestions, commitment, ratification, and bootstrap are covered by sibling RFCs: [editor](speed-define-ceremony-editor.md), [contributor](speed-define-ceremony-contributor.md), [commit](speed-define-ceremony-commit.md), [bootstrap](speed-define-ceremony-bootstrap.md). The `CeremonyLayout` that composes the context panel with the editor is defined in the editor RFC.

### Out of Scope

- Embedding similarity for scoping. LLM seed selection + word-boundary keyword fallback is sufficient. Embeddings can be added without schema changes.
- Call graph expansion from seed files (à la `lib/context/code_context.py`). The LLM seed selection alone produces good results. Graph expansion could improve recall for missed dependency files but adds complexity. Can be layered on without schema changes.
- Real-time context updates (WebSocket push when sources change). Context is assembled once per intent declaration or refinement.

## Security & Controls

**Authentication**: Dashboard runs locally. No auth beyond filesystem access.

**Authorization**: `declareIntent` creates a ceremony and assigns ownership to the calling actor (resolved by `get_current_actor()`). `refineIntent` checks ownership via `assert_ceremony_author()`. `contextPackage` query is read-only, accessible to any actor.

**Data sensitivity**: Context package contains codebase structure and file paths. All data already exists on disk. The API does not transmit data externally. External LLM host delivery (separate feature, not part of this RFC) requires explicit author action.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Scoping mechanism | LLM seed file selection with word-boundary keyword fallback | Token extraction + substring matching, embedding similarity | The LLM receives the full file list and selects seed files directly, avoiding the noise from substring matching generic terms against file paths. Testing showed 0% noise and 56% precision vs. 41% noise and 34% precision for the token extraction approach. Keyword fallback uses word-boundary matching (not substring) for when no model is available. |
| Partial assembly on failure | Continue with available sources, mark failed sources | Block until all sources succeed, retry failed sources | Users shouldn't wait for a slow source when 6 others are ready. Progressive loading is a core UX requirement from the design spec. |
| Feature name | Author-provided, validated on input | Auto-slugify from intent, UUID-based | Slugifying free-text paragraphs produces garbage names. The intent and the feature name serve different purposes: intent is what the author wants to build (can be long), feature name is a short identifier for the directory and display. Collision is an immediate validation error, not a silent suffix. |
| Persistence format | Single JSON file per feature | SQLite, event log, no persistence | JSON is readable, debuggable, and consistent with existing `.speed/` conventions (task JSONs, contracts). |

## Drawbacks

- LLM seed scoping requires a model call (2-15 seconds depending on the model and project size). The keyword fallback is instant but produces lower-quality results. Progressive loading mitigates perceived delay.
- Learnings filtering uses TF-IDF, which requires sklearn. If sklearn is unavailable, all observations are returned unfiltered.
- Related features fallback reads task JSON files from all features, which can be slow for projects with many features and tasks. No caching is built in.
- The context package JSON file can grow large for projects with extensive observation history. TF-IDF filtering significantly reduces this (424 → 27 in testing) but no hard size cap is enforced.

## Search / Query Strategy

Seven filesystem reads, no database queries. All paths resolved via `SpeedPaths` for SP/MP awareness:

| Source | Access Pattern | Filtering | Expected Volume |
|--------|---------------|-----------|-----------------|
| Semantic graph | Read `semantic-graph.json`, LLM selects seed files from the deduplicated file list | LLM seed selection; keyword word-boundary fallback | 1 file, 100KB-5MB |
| Learnings | Glob `observations/*.jsonl` | TF-IDF cosine similarity against intent (threshold 0.05) | 0-50 files → typically 5-30 items after filtering |
| Defects | `defects/*/state.json` + `specs/defects/*.md` | File overlap (state.json), metadata parsing: Related Feature, Tags (markdown) | 0-20 files → typically 2-5 relevant |
| Project knowledge | Read `conventions.json` | None (global, intentionally unscoped) | 1 file, 1-50KB |
| Vision | Read `specs/product/overview.md` | None | 1 file |
| Related features | Glob features, check `context-package.json` or task `files_touched` | File path overlap with scoped files | 0-20 features |
| Audit history | Glob `plan-audit-*.json` (strips markdown fences) | None (all findings returned) | 0-10 files |

Performance budget: < 5 seconds for a project with 10 features, 20 defects, and a 200-file codebase. The semantic graph read is the bottleneck.

## File Impact

**New files:**
- `dashboard/backend/resolvers/context.py` — resolver for intent declaration, context assembly, scoping, source readers, refinement
- `dashboard/backend/resolvers/context_types.py` — Strawberry type definitions for DeclareIntentResult, AssemblyStatus, and related context-specific types
- `dashboard/frontend/lib/graphql/queries/ceremony-context.ts` — GraphQL queries, mutations, and subscriptions (including `contextHistory` and `contextAssemblyProgress`)

**Modified files:**
- `dashboard/backend/schema.py` — register new query and mutation fields. **Integration order**: this RFC modifies schema.py after the parent RFC (parent → context → editor → contributor → commit → bootstrap).
- `dashboard/frontend/components/editor/IntelPanel.tsx` — add `mode` prop and ceremony-specific sections (Defects, Vision Status, Audit History)

**Path helpers consumed from parent RFC** (already built): `ceremony_intent()`, `ceremony_context_package()`, `ceremony_dir()`, `ceremony_state()` on `SpeedPaths`. This RFC does not add any path helpers.

## Dependencies

- Codebase semantic graph at `.speed/context/semantic-graph.json` (built by `speed plan` or independently via [bootstrap RFC](speed-define-ceremony-bootstrap.md))
- Project knowledge at `.speed/memory/project-knowledge.json` (managed by `lib/learn/project_knowledge.py`)
- Observation JSONL files at `.speed/memory/observations/*.jsonl`
- Product vision at `specs/product/overview.md`
- Feature state files at `.speed/features/*/state.json`
- Defect state at `.speed/defects/*/state.json` and `specs/defects/*.md`
- Existing `SpeedPaths` class in `dashboard/backend/paths.py`
- `dashboard/backend/llm` module: `llm_complete`, `get_ceremony_models`, `SeedFiles` response model (for LLM seed scoping). Ollama models use direct `/api/chat` calls (bypasses litellm's broken tool routing for models with dedicated RENDERER/PARSER)
- `sklearn.feature_extraction.text.TfidfVectorizer` and `sklearn.metrics.pairwise.cosine_similarity` (for learnings relevance scoring)

## Resolved Questions

| Question | Decision |
|----------|----------|
| Should the context package include vision document content or just status? | **Include content.** `vision_content` is populated when `vision_status` is `"available"` or `"stale"`. Null when `"missing"`. Per [foundation type definition](speed-define-ceremony-foundation.md#shared-strawberry-types). |
| How should feature names handle non-ASCII input? | **Author provides the name.** Feature name is a separate input from intent, validated to be lowercase, alphanumeric, and hyphens only (max 50 chars). The name is not derived from intent text. |
| Synchronous or async assembly? | **Synchronous mutation, progressive polling.** The mutation returns when all sources have completed or errored. Frontend polls `contextAssemblyStatus` during assembly for progressive UX per the [design spec](../design/speed-define-ceremony.md). |
| Should context package paths account for multiplayer mode? | **Yes.** All readers use `SpeedPaths` methods (`memory_dir`, `defects_dir`, `features_dir`), which resolve SP vs. MP paths internally. |
| Should scoping use LLM-assisted extraction? | **Yes, via seed file selection.** Originally implemented as LLM token extraction + substring matching, which still produced 41% noise (generic tokens like "dashboard" matched too broadly). Replaced with LLM seed file selection: the LLM receives the full project file list and intent, selects relevant files directly. Testing showed 0% noise vs 41%, 56% precision vs 34%. Keyword fallback uses word-boundary matching (not substring). |
| How should learnings be filtered? | **TF-IDF cosine similarity against the intent.** Observations lack file-path metadata (`file_paths`/`files` fields are empty). Feature-name matching produced false positives (e.g., "dashboard" matching both observation files). TF-IDF similarity between the intent and observation text follows the same pattern as `lib/context/related_specs.py`. Reduced 424 → 27 in testing. |
| How should defects from markdown specs be filtered? | **Parse header metadata.** `specs/defects/*.md` files contain `Related Feature:`, `Tags:`, and `Severity:` in their headers. The reader parses these and filters by overlap with scope terms. Defects with no matching metadata are excluded. Previously all 14 project defects were included regardless of scope. |
| How should related features work before ceremonies exist? | **Fall back to task files_touched.** The primary path checks `context-package.json` from prior ceremonies. When no package exists (most features predate the Define Ceremony), the reader aggregates `files_touched` from task JSON files and checks overlap. |
| How should audit history be read? | **Read plan-audit-*.json, not Audit-*.jsonl.** The JSONL files are Claude Code session logs (conversation turns). The structured audit results are in `plan-audit-*.json` files, which contain `issues[]` arrays with severity, section, and message. Files may be wrapped in markdown code fences. |

## Unresolved Questions

| Question | Blocks | Status |
|----------|--------|--------|
| Should stale ceremony claims be detected and expired automatically? | Ownership enforcement | Deferred. The PRD requires stale claim expiration (3600s default, matching `speed claim`). The `declareIntent` collision check catches the common case. Full stale detection can be added without schema changes. |
