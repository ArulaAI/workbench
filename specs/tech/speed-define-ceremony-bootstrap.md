# RFC: Define Ceremony — Bootstrap

<!-- REWRITE ANNOTATIONS (from parent RFC review pass):
  1. NO JSON ARTIFACTS: Bootstrap RFC doesn't own any ceremony JSON files directly. It writes to `specs/product/overview.md` (vision) and `.speed/memory/project-knowledge.json` (conventions). Verify whether project-knowledge.json needs a schema definition here or if it's already defined by `lib/learn/project_knowledge.py`.
  2. INTERFACE CONTRACT: Consumes does not list parent RFC exports (CeremonyStatus, transition_ceremony_state, path helpers). Bootstrap needs `transition_ceremony_state` to go BOOTSTRAPPING -> DRAFTING on `completeBootstrap`, but its Consumes only lists the context RFC.
  3. IMPORT PATH: Consumes code block says `from ceremony_context import assemble_context_package` — should use relative import matching codebase convention.
  4. BOOTSTRAP-SPECIFIC TYPES: `BootstrapStatus`, `DerivedConvention`, `VisionDraft` are referenced in the foundation's API Surface but absent from the foundation's 22 shared types. These are child-RFC-specific types. Confirm they are defined in this RFC's resolver module, not in ceremony_types.py.
  5. DEPENDENCY: Lists `lib/learn/project_knowledge.py: seed_knowledge()` but notes that `upsert_entries()` does not exist. Verify the public API is still `seed_knowledge()` and hasn't changed.
  6. SCHEMA REGISTRATION ORDER: File Impact says "fifth and last" for schema.py integration. Verify this matches the parent RFC's stated order (context -> editor -> contributor -> commit -> bootstrap).
-->

> See [product spec](../product/speed-define-ceremony.md) for product context.
> See [foundation reference](speed-define-ceremony-foundation.md) for shared types, API index, validation rules.
> Parent RFC: [speed-define-ceremony](speed-define-ceremony.md)
> Depends on: [parent](speed-define-ceremony.md), [context](speed-define-ceremony-context.md)

## PRD & Design Traceability

**User Stories**: S11 (guided bootstrap, cold start detection, semantic graph build, vision + conventions establishment), S12 (LLM-generated vision draft from codebase, author reviews/edits/commits, write-from-scratch option)

**User Flows**: "First-time setup (Bootstrap)" (steps 1-5, including vision generation choice, convention extraction, persona prompts)

**Success Criteria**: Bootstrap flow guides first-time users through vision and conventions; context package API is surface-agnostic (bootstrap ensures context sources exist for future ceremonies)

**Design Components**: BootstrapWizard (`ceremony/BootstrapWizard.tsx`), VisionDraftEditor (`ceremony/VisionDraftEditor.tsx`), ConventionReview (`ceremony/ConventionReview.tsx`)

**Design Regions**: bootstrap-flow (content area, max 640px centered, replaces intent-input on cold start)

**Design Routes**: `/define/new` (intercepted when cold start detected)

**Design Interactions**: Select vision generation vs. write-from-scratch, accept/reject convention (individual), accept-all conventions, regenerate vision, commit vision, bootstrap step complete/skip, persona convention input

**Design States**: Bootstrap state (page-level: wizard replaces intent input), VisionDraftEditor regenerate (enabled/loading), ConventionReview accept/reject (enabled/hover/focus), ConventionReview acceptAll (enabled/hover/focus/pressed), bootstrap progress indicator (complete=accent, current=text, pending=text-tertiary)

**Design Typography**: Bootstrap step title (type-section-title, 15px 600), step description (type-body, 13px 400), progress label (type-caption, 11px 400), vision draft content (type-body, 13px 400), convention review item (type-body, 13px 400), convention source (type-caption, 11px 400)

## Basic Example

```graphql
# Check if bootstrap is needed
query {
  bootstrapStatus {
    needed
    reasons  # ["no_semantic_graph", "no_vision", "no_project_knowledge"]
    graphBuildStatus  # "not_started" | "building" | "complete" | "error"
  }
}

# Generate vision from codebase
mutation {
  generateVision {
    draft
    sources  # ["README.md", "AGENTS.md", "package.json"]
    generating  # false when complete
  }
}

# Commit the vision
mutation {
  commitVision(content: "Appwrite is a self-hosted BaaS...") {
    path  # "specs/product/overview.md"
    written
  }
}
```

When an author opens `/define/new` on a project with no vision, no semantic graph, and no project knowledge, the bootstrap wizard intercepts before the intent input. Two wizard steps: establish vision (generate or write), seed conventions (extract from code, supplement with persona prompts). The graph builds in the background as a parallel activity, not a named wizard step. The `BootstrapWizard` component tracks graph build status via `graphBuildStatus` prop separately from the step progression.

## Interface Contract

### Consumes (from context RFC)

```python
from ceremony_context import assemble_context_package

# Called after bootstrap completes to verify the system can now deliver context.
# If assembly returns a non-empty package, bootstrap succeeded.
```

### Produces (for all downstream RFCs)

```python
# Vision document written to specs/product/overview.md
# Conventions written to .speed/memory/project-knowledge.json
# Semantic graph built at .speed/context/semantic-graph.json

# After bootstrap, the context RFC's assemble_context_package() will find:
# - A semantic graph to scope
# - A vision document to check status
# - Project knowledge entries to deliver
# These are prerequisites for meaningful context delivery.
```

## Data Model

### BootstrapState (in-memory, tracks wizard progress)

| Field | Type | Description |
|-------|------|-------------|
| needed | boolean | Whether bootstrap conditions are met |
| reasons | string[] | Which conditions triggered bootstrap |
| current_step | enum | "vision", "conventions" (graph build is tracked separately via `graph_build_status`, not as a wizard step) |
| graph_build_status | enum | "not_started", "building", "complete", "error" |
| vision_status | enum | "pending", "generating", "reviewing", "committed", "skipped" |
| conventions_status | enum | "pending", "extracting", "reviewing", "committed", "skipped" |

### Cold Start Detection Conditions

Bootstrap is triggered when ALL three conditions are true:

| Condition | Check | File/Path |
|-----------|-------|-----------|
| No semantic graph | `.speed/context/semantic-graph.json` does not exist | `.speed/context/` |
| No vision document | `specs/product/overview.md` does not exist OR file is < 50 chars | `specs/product/` |
| No project knowledge | `.speed/memory/project-knowledge.json` does not exist OR file is empty `{}` | `.speed/memory/` |

If any one condition is false (e.g., vision exists but graph doesn't), bootstrap is not triggered. The author can still run individual steps manually from the bootstrap settings.

### DerivedConvention (extracted from codebase)

| Field | Type | Description |
|-------|------|-------------|
| id | string | Unique ID: `conv-{hash}` |
| text | string | Convention description |
| source | string | Where it was derived from (e.g., "CI config: .github/workflows/", "package.json dependencies") |
| category | enum | "engineering", "product", "design" |
| status | enum | "pending", "accepted", "rejected" |

## API Surface

### Queries

#### `bootstrapStatus: BootstrapStatus!`

Returns whether bootstrap is needed and the current build status.

```graphql
type BootstrapStatus {
  needed: Boolean!
  reasons: [String!]!
  graphBuildStatus: String!
  steps: [BootstrapStep!]!
}
type BootstrapStep {
  id: String!  # "graph" | "vision" | "conventions"
  title: String!
  status: String!  # "pending" | "current" | "complete" | "skipped"
}
```

#### `derivedConventions: [DerivedConvention!]!`

Returns conventions extracted from the codebase by the Learn pipeline's convention extractors. Called after the extraction step completes.

#### `visionDraft: VisionDraft`

Returns the LLM-generated vision draft. Null if generation hasn't been triggered or author chose "write from scratch."

```graphql
type VisionDraft {
  content: String!
  sources: [String!]!  # files the LLM used as input
  generatedAt: String!
}
```

### Mutations

#### `startGraphBuild: GraphBuildResult!`

Triggers the semantic graph builder independently of `speed plan`. Runs in the background.

1. Invokes `build_layer1()` from `lib/context/layer1.py`
2. Writes output to `.speed/context/semantic-graph.json` and `.speed/context/project-map.json`
3. Returns immediately with `status: "building"`
4. Frontend polls `bootstrapStatus` to check `graphBuildStatus`

**Error cases:**
- Build already in progress: return current status, don't restart
- No supported languages found in project: return error with message

#### `generateVision: VisionDraft!`

Generates a product vision draft from codebase artifacts.

**Input sources** (read in order, used as context for the LLM):
1. `README.md` (or `README`, `readme.md`)
2. `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md` (project documentation)
3. `package.json` / `composer.json` / `Cargo.toml` / `pyproject.toml` (project metadata)
4. `docs/` directory (first 5 markdown files by modification date)
5. `.github/` or `.gitlab-ci.yml` (CI configuration, infers deployment model)

The LLM receives these sources plus the SPEED overview template (`templates/overview.md`) and generates a draft vision document.

**Error cases:**
- LLM provider not configured: return error with `speed.toml` guidance
- No readable project files found: return error suggesting manual vision authoring
- Generation timeout (> 60s): return partial draft if available, error otherwise

#### `regenerateVision: VisionDraft!`

Re-generates the vision draft. Discards the previous draft. The author's edits in the right pane are not affected (they live in frontend state, not on disk).

#### `commitVision(content: String!): CommitVisionResult!`

Writes the vision document to `specs/product/overview.md`.

1. Creates `specs/product/` directory if it doesn't exist
2. Writes the content to `overview.md`
3. Returns the written path and success status

**Error cases:**
- Content is empty or whitespace-only: validation error
- File system write failure: return error with path

#### `extractConventions: [DerivedConvention!]!`

Runs the Learn pipeline's convention extractors against the codebase.

Uses `lib/learn/convention_extractors.py` extractors:
- A1: Co-modification analysis (git history patterns)
- A2: Tree-sitter AST analysis (naming patterns, code structure)
- A3: CSG import graph analysis (dependency patterns)
- A4: Lock file analysis (dependency management conventions)

Additionally scans:
- CI/CD config files for deployment and testing conventions
- Linter/formatter configs (`.eslintrc`, `.prettierrc`, `pint.json`, `phpstan.neon`) for code style
- `tsconfig.json`, `composer.json` for project structure conventions

Returns extracted conventions for author review.

**Error cases:**
- Semantic graph not built: warn but continue with extractors that don't need it (A1, A4)
- Git history unavailable: skip A1, continue with others

#### `resolveConvention(id: String!, action: ConventionAction!): DerivedConvention!`

```graphql
enum ConventionAction { ACCEPT, REJECT }
```

Accepts or rejects an individual derived convention. Accepted conventions are written to `.speed/memory/project-knowledge.json`. Rejected conventions are discarded (not persisted).

#### `acceptAllConventions: [DerivedConvention!]!`

Accepts all pending conventions in bulk. Returns the updated list.

#### `commitConventions(personaInputs: PersonaConventionInput): CommitConventionsResult!`

Writes persona-specific conventions (from the manual prompts) to project knowledge.

```graphql
input PersonaConventionInput {
  engineering: [String!]
  product: [String!]
  design: [String!]
}
```

Each non-empty entry is added to `.speed/memory/project-knowledge.json` with `confidence: "locked"` (human-provided conventions don't decay).

#### `completeBootstrap: BootstrapResult!`

Finalizes bootstrap. Validates that minimum requirements are met (vision exists, even if conventions were skipped). Transitions to normal intent input flow.

**Error cases:**
- Vision not committed: return error requiring at least a vision document
- Graph still building: warn but allow (graph can finish in background)

## Validation Rules

| Field | Constraints |
|-------|-------------|
| vision content | Min 50 chars. Must contain substantive content, not just template headings. Validated by checking for at least 3 non-heading lines. |
| convention text | Max 200 chars. Whitespace-trimmed. |
| persona inputs | All optional. Empty arrays are valid (author can skip persona prompts). |
| bootstrap completion | Vision document must be committed. Conventions and persona inputs are optional. Graph build can still be in progress. |

## Testing

### Acceptance Criteria

- Given a project with no semantic graph, no vision, and no project knowledge, when the author opens `/define/new`, then the bootstrap wizard renders instead of the intent input
- Given bootstrap is active, when the semantic graph build starts, then the frontend shows progressive status (building → complete) without blocking other steps
- Given the author chooses vision generation, when the LLM produces a draft, then a split view shows the generated draft (read-only left) and an editable copy (right)
- Given the author edits the right pane and clicks "Commit Vision," then `specs/product/overview.md` is written with the edited content
- Given convention extraction completes, when results are shown, then each convention has accept/reject controls and a source citation
- Given the author accepts 3 conventions and rejects 2, then only the 3 accepted entries appear in `.speed/memory/project-knowledge.json`
- Given the author enters Engineering conventions ("We deploy via Docker, staging required before prod"), then these are written to project-knowledge.json with `confidence: "locked"`
- Given bootstrap completes, when the author is redirected to intent input, then subsequent context delivery includes the vision status and seeded conventions

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| Vision generation produces hallucinated project description | High | Integration test: generate vision for a real project, manually verify accuracy against README/docs. Include negative test with minimal project (no README). |
| Convention extraction produces noise (trivial or incorrect patterns) | Medium | Unit test: run extractors against a known project, verify extracted conventions match actual patterns |
| Graph build blocks the UI | Medium | Integration test: verify graph builds in background, wizard steps are navigable during build |
| Bootstrap triggers on a mature project (false positive) | Low | Unit test: project with vision + graph + knowledge, verify `bootstrapStatus.needed = false` |

### Test Plan

**Unit tests**
- `test_cold_start_detection`: all three conditions true, each individually false, edge cases (empty files)
- `test_vision_generation_sources`: verify which files are read as input (README variants, package files, docs)
- `test_vision_content_validation`: too short, template-only, substantive content
- `test_convention_extraction`: mock codebase with known patterns, verify extracted conventions
- `test_convention_resolution`: accept, reject, accept-all, verify project-knowledge.json writes
- `test_persona_inputs`: engineering/product/design entries, empty arrays, mixed

**Integration tests**
- `test_graph_build_independent`: trigger build without `speed plan`, verify CSG output
- `test_full_bootstrap_flow`: cold start → graph build → vision generation → convention extraction → commit → verify context delivery works
- `test_graphql_bootstrap_mutations`: all mutations through Strawberry schema

**Visual/UI tests**
- BootstrapWizard renders stepped progress (Graph → Vision → Conventions)
- VisionDraftEditor split view: generated left (bg-elevated), editable right (bg-card)
- ConventionReview shows per-item accept/reject with source citations
- Bootstrap progress indicator colors: accent (complete), text (current), text-tertiary (pending)

### Edge Cases

- Project with only a README and no source code: graph build returns empty, convention extraction finds nothing, vision generation works from README alone
- Project with vision document but no graph or knowledge: bootstrap not triggered (only one of three conditions met)
- Author clicks "Write from scratch" for vision: VisionDraftEditor shows empty right pane, no left pane (generation skipped)
- Author skips conventions entirely: valid, bootstrap completes with vision only
- Graph build fails (unsupported language): warn, allow bootstrap to continue without graph
- Multiple browser tabs open bootstrap simultaneously: first graph build wins, second detects "building" status and skips
- Vision file already exists at `specs/product/overview.md` from a prior partial bootstrap: overwrite with new content (the author explicitly committed)

### Out of Scope

- Guided project onboarding (cloning, dependency installation, environment setup). Bootstrap operates on an existing project directory.
- Importing conventions from another SPEED project. Each project bootstraps independently.
- Multi-language support for persona prompts. English only. Multi-language support deferred until i18n infrastructure is established.

## Security & Controls

**LLM data**: Vision generation sends README, project documentation, and metadata files to the configured LLM provider. No source code is sent. The author reviews the draft before committing.

**File writes**: Bootstrap writes to `specs/product/overview.md` and `.speed/memory/project-knowledge.json`. Both are regular files in the working tree, subject to normal git tracking.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Bootstrap triggers only when ALL three conditions are true | All three required | Any one triggers, Configurable | Reduces false positives. A project with a vision but no graph shouldn't force a full bootstrap; the user can just run `speed plan` to build the graph. |
| Graph build runs independently of `speed plan` | Independent trigger | Require `speed plan`, Manual CLI trigger only | Bootstrap needs the graph before the first `speed plan`. Decoupling allows the wizard to start the build in background. |
| Vision generation is optional (author can write from scratch) | Optional | Required generation, No generation option | Some authors prefer writing their own vision. Others want a starting point. Offering both respects different workflows. |
| Persona conventions get `confidence: "locked"` | Locked | "high", "medium" | Human-provided conventions are intentional declarations, not inferred patterns. They shouldn't be overridden by automated extraction in future Learn cycles. |
| Bootstrap requires vision, conventions are optional | Vision required | All required, All optional | Vision is the anchor for Guardian checks and the context package. Conventions grow naturally through the Learn ceremony. Vision doesn't have an automatic growth mechanism. |

## Drawbacks

- The three-condition trigger is rigid. A project that has a vision and project knowledge but has never built a graph won't get bootstrap guidance for the graph step. The workaround is `speed plan` (which builds the graph) or manual graph trigger.
- Vision generation quality depends on the project having readable documentation. A project with no README, no docs, and no metadata files will get a poor or empty draft. The author must write from scratch in that case.
- Convention extraction at bootstrap time runs the same extractors that the Learn pipeline uses post-feature. On a large codebase, extraction can take 30-60 seconds. The wizard should indicate this is running without blocking navigation.

## Search / Query Strategy

| Operation | Access Pattern | Expected Volume |
|-----------|---------------|-----------------|
| Cold start detection | Stat 3 files (semantic-graph.json, overview.md, project-knowledge.json) | 3 stat calls |
| Vision generation sources | Glob for README*, AGENTS.md, package.json, docs/*.md | 5-15 files |
| Convention extraction | Full codebase scan via tree-sitter + git log + lock files | Depends on codebase size |
| Graph build | Full codebase via `build_layer1()` | Depends on codebase size |

## File Impact

**New files:**
- `dashboard/backend/resolvers/ceremony_bootstrap.py` — bootstrap queries and mutations
- `dashboard/backend/resolvers/ceremony_bootstrap_types.py` — Strawberry types
- `dashboard/backend/bootstrap_engine.py` — cold start detection, vision generation, convention extraction orchestration
- `dashboard/frontend/components/define/ceremony/BootstrapWizard.tsx` — stepped wizard flow
- `dashboard/frontend/components/define/ceremony/VisionDraftEditor.tsx` — split view editor
- `dashboard/frontend/components/define/ceremony/ConventionReview.tsx` — accept/reject list
- `dashboard/frontend/lib/graphql/queries/ceremony-bootstrap.ts` — queries and mutations
- `dashboard/frontend/app/define/new/page.tsx` — modified to detect bootstrap vs. intent input

**Modified files:**
- `dashboard/backend/schema.py` — register bootstrap queries and mutations. **Integration order**: fifth and last (after context, editor, contributor, commit RFCs).
- `lib/context/layer1.py` — `build_layer1()` already exists as a Python function. The bash wrapper `context_build_layer1()` in `lib/context_bridge.sh` calls it. Bootstrap can invoke `build_layer1()` directly from Python or call the bash wrapper via subprocess.

## Dependencies

- Context RFC: `assemble_context_package()` for post-bootstrap verification
- `lib/context/layer1.py`: semantic graph builder (needs to be callable independently)
- `lib/learn/convention_extractors.py`: A1-A4 extractors for convention derivation
- `lib/learn/project_knowledge.py`: `seed_knowledge()` for writing accepted conventions (note: `upsert_entries()` does not exist; the public API is `seed_knowledge()`, `detect_knowledge_gaps()`, and `check_staleness()`)
- LLM provider in `speed.toml` for vision generation
- SPEED overview template at `templates/overview.md`

## Unresolved Questions

| Question | Blocks | Proposed Resolution |
|----------|--------|---------------------|
| Should the graph builder be a separate Python process or run in-thread on the backend? | Graph build architecture | Separate process (subprocess). The graph builder is CPU-intensive and long-running. Running it in-thread would block the GraphQL server. Subprocess communicates completion via file existence check. |
| Should bootstrap re-trigger if vision or knowledge are deleted after initial bootstrap? | Edge case handling | No. Bootstrap only triggers on first visit when all three conditions are true. If an author deletes their vision doc, the context panel will show "vision: missing" as a warning, but bootstrap won't re-trigger. The author can re-run individual bootstrap steps from settings. |
| Should extracted conventions show the actual code patterns they were derived from? | Convention review UX | Yes. Each convention should include a source citation (file path, line range, or git log entry). The author needs evidence to judge whether the extracted convention is real or noise. |
