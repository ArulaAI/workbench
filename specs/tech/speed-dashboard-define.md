# RFC: Dashboard Define Page

> See [product spec](../product/speed-dashboard-define.md) for product context.
> Prototype: see `working-docs/define-page-prototype.html` (local file, not tracked in specs)

## Existing Infrastructure

Before building the `/define` page, the following related code already exists in the codebase. The Define page resolver and components should reuse these rather than rebuilding from scratch.

### Backend readers (in `dashboard/backend/resolvers/landing.py`)

| Function | What it reads | Reusable for |
|----------|--------------|--------------|
| `_read_vision_status()` | `specs/product/overview.md` existence and content | `DefineView.visionStatus` |
| `_read_draft_specs()` | `specs/product/*.md`, matches tech/design specs, reads feature state | `DefineFeature.specified` (spec existence, feature state) |
| `_read_defects()` | `.speed/defects/*/state.json` + `specs/defects/*.md` | `DefineView.defects` (needs enrichment: add description, impact, filedAt) |
| `_read_criteria_verify()` | Task JSON files, spec traceability | `DefineFeature.built` (coverage_pct, criteria_passed, criteria_total) |
| `_read_guardian_verdict()` | Guardian logs (JSON, JSONL, cache) | `DefineFeature.built.guardianVerdict` |
| `_read_task_files()` | `.speed/features/*/tasks/*.json` | `DefineFeature.built` (tasksDone, tasksTotal, blockedCount, taskProgress) |

### Frontend components

| Component | Location | Reusable for |
|-----------|----------|--------------|
| `VisionWarning` | `components/landing/DefinePanel.tsx` | Vision warning banner (extract to shared component) |
| `DraftSpecItem` with spec type pills | `components/landing/DefinePanel.tsx` | Spec pills in SpecifiedCell (adapt three-state styling) |
| `DefectRow` with severity badges | `components/landing/DefinePanel.tsx` | Defect rows (add description, impact columns) |
| `coverageColor()` | `app/spec-alignment/page.tsx` | Hero coverage metric color thresholds |
| `ProgressBar` | `components/shared/progress-bar.tsx` | Built column progress bars |
| `CardSkeleton` | `components/shared/loading-skeleton.tsx` | Loading state |

### Existing pages

| Page | Route | Relationship to `/define` |
|------|-------|--------------------------|
| Landing DefinePanel | `/` (grid cell) | Summary card showing vision status, draft specs, defects. Links to `/define` via SurfaceLink (currently points to `/spec-alignment`, needs updating). |
| Spec Alignment | `/spec-alignment` | Claim-level coverage viewer. Becomes a drill-down from the Define page's Built column when a user clicks a feature's coverage metric. |

### Sidebar navigation

The sidebar (`components/layout/sidebar.tsx`) currently has a "Spec Alignment" entry at `/spec-alignment`. When `/define` is built, add a "Define" entry and keep "Spec Alignment" as a sub-item or move it under the Define entry.

## Basic Example

```graphql
query DefineView($feature: String) {
  defineView {
    visionStatus          # "missing" | "placeholder" | "defined"
    visionPath            # "specs/product/overview.md"
    features {
      name
      state               # "complete" | "executing" | "writing" | "unplanned"
      specified {
        productSpec       # { exists, path, auditStatus, warningCount, warnings }
        technicalSpec     # same shape
        designSpec        # same shape
        openQuestions
        sizingEstimate    # nullable int (task count estimate)
      }
      built {
        coveragePct       # nullable float
        criteriaPassed    # nullable int
        criteriaTotal     # nullable int
        guardianVerdict   # nullable string
        taskProgress      # nullable float (0-100)
        tasksDone         # nullable int
        tasksTotal        # nullable int
        blockedCount      # int
        completedAt       # nullable ISO string
      }
      gap {
        escalationCount
        escalations       # [{ description, linkedWarningId }]
        unverifiableCount
        reworkCount
      }
    }
    defects {
      name
      severity            # "P0" | "P1" | "P2" | "P3"
      status              # "unfixed" | "triaging" | "fixing" | "resolved"
      description
      impact              # nullable string
      filedAt             # ISO string
    }
    aggregates {
      designSpecCount     # how many features have design specs
      featureCount
      auditWarningCount
      openQuestionCount
      escalationCount
      completedCount
      executingCount
      unplannedCount
    }
  }
}
```

## Data Model

### What the resolver reads

| Source | Path | Data extracted |
|--------|------|----------------|
| Spec files | `specs/product/*.md`, `specs/tech/*.md`, `specs/design/*.md` | File existence, feature name matching |
| Product vision | `specs/product/overview.md` | Existence check only |
| Feature state | `.speed/features/*/state.json` | Status, started_at, completed_at |
| Task files | `.speed/features/*/tasks/*.json` | Task count, status per task, blocked count |
| Spec traceability | `.speed/features/*/spec-traceability.json` | Coverage %, criteria pass/total |
| Criteria verification | `.speed/features/*/criteria-verify.json` | Per-criteria pass/fail/unverifiable |
| Guardian logs | `.speed/features/*/logs/Guardian-*.jsonl` | Verdict (last entry) |
| Escalation logs | `.speed/features/*/logs/escalations.json` | Escalation descriptions and linked spec issues |
| Defect state | `.speed/defects/*/state.json` | Severity, status, created_at |
| Defect specs | `specs/defects/*.md` | Name, description (first paragraph) |

### Spec-to-feature matching

Features are identified by directory names in `.speed/features/`. Specs are matched by filename convention:

```
Feature: speed-defects
  Product spec: specs/product/speed-defects.md
  Technical spec: specs/tech/speed-defects.md
  Design spec: specs/design/speed-defects.md
```

If the filename doesn't match, the resolver falls back to scanning spec frontmatter for a `feature:` field.

### Audit computation

V1 audit is computed at query time (no cached artifact):

1. **Structural checks**: Required sections present (Problem, Users, User Stories, Scope, Success Criteria for PRD; Basic Example, Data Model, API Surface for RFC)
2. **Warning generation**: Missing required sections produce warnings with human-readable descriptions ("User Stories table is empty. The Architect uses these for task boundaries.")
3. **Open questions**: Count of rows in the Open Questions table where Status is "Open"
4. **Sizing estimate**: Parsed from the audit output or estimated from user story count (rough heuristic: stories * 2 tasks)

## API Surface

### GraphQL types

```python
@strawberry.type
class SpecIndicator:
    exists: bool
    path: Optional[str]
    audit_status: str          # "clean" | "warning" | "error"
    warning_count: int
    warnings: list[str]

@strawberry.type
class SpecifiedData:
    product_spec: SpecIndicator
    technical_spec: SpecIndicator
    design_spec: SpecIndicator
    open_questions: int
    sizing_estimate: Optional[int]

@strawberry.type
class BuiltData:
    coverage_pct: Optional[float]
    criteria_passed: Optional[int]
    criteria_total: Optional[int]
    guardian_verdict: Optional[str]
    task_progress: Optional[float]
    tasks_done: Optional[int]
    tasks_total: Optional[int]
    blocked_count: int
    completed_at: Optional[str]

@strawberry.type
class GapEscalation:
    description: str
    linked_warning_id: Optional[str]

@strawberry.type
class GapData:
    escalation_count: int
    escalations: list[GapEscalation]
    unverifiable_count: int
    rework_count: int

@strawberry.type
class DefineFeature:
    name: str
    state: str
    specified: SpecifiedData
    built: BuiltData
    gap: GapData

@strawberry.type
class DefineDefect:
    name: str
    severity: str
    status: str
    description: str
    impact: Optional[str]
    filed_at: Optional[str]

@strawberry.type
class DefineAggregates:
    design_spec_count: int
    feature_count: int
    audit_warning_count: int
    open_question_count: int
    escalation_count: int
    completed_count: int
    executing_count: int
    unplanned_count: int

@strawberry.type
class DefineView:
    vision_status: str
    vision_path: Optional[str]
    features: list[DefineFeature]
    defects: list[DefineDefect]
    aggregates: DefineAggregates
```

### Query field

```python
@strawberry.field
def define_view(self, info: strawberry.types.Info, feature: Optional[str] = None) -> Optional[DefineView]:
    project_root = info.context["project_root"]
    return define.get_define_view(project_root, feature)
```

When `feature` is provided, the resolver filters `DefineView.features` to only those whose name ends with the given string (same `str.endswith()` semantics as `spec_alignment`). Aggregates are recomputed from the filtered list. Defects are not filtered (they are project-wide, not per-feature).

No mutations. Define is read-only. Writing happens in the Spec Editor.

## Validation Rules

| Field | Constraints |
|-------|-------------|
| `DefineView.visionStatus` | One of `"missing"`, `"placeholder"`, `"defined"`. Resolver defaults to `"missing"` if `overview.md` is absent. |
| `DefineView.visionPath` | Absolute path string or null. Null when `overview.md` does not exist. |
| `DefineFeature.state` | One of `"complete"`, `"executing"`, `"writing"`, `"unplanned"`. Derived from `state.json`. Features without a `state.json` default to `"unplanned"`. |
| `DefineFeature.name` | Non-empty string. Derived from the `.speed/features/` directory name. |
| `SpecIndicator.auditStatus` | One of `"clean"`, `"warning"`, `"error"`. `"clean"` when all required sections are present. `"warning"` when optional sections are missing. `"error"` when required sections are missing. |
| `SpecIndicator.warningCount` | Non-negative integer. Zero when `auditStatus` is `"clean"`. |
| `BuiltData.coveragePct` | Float 0.0-100.0 or null. Null for features that have not been executed. Clamped to [0, 100]. |
| `BuiltData.taskProgress` | Float 0.0-100.0 or null. Computed as `(tasksDone / tasksTotal) * 100`. Null when `tasksTotal` is 0 or feature is unplanned. |
| `BuiltData.blockedCount` | Non-negative integer. Count of tasks with `status == "blocked"`. |
| `GapData.escalationCount` | Non-negative integer. Zero for features without escalation logs. |
| `GapData.reworkCount` | Non-negative integer. Count of tasks with `retry_count > 0`. |
| `DefineDefect.severity` | One of `"P0"`, `"P1"`, `"P2"`, `"P3"`. Unknown severities clamped to `"P3"`. |
| `DefineDefect.status` | One of `"unfixed"`, `"triaging"`, `"fixing"`, `"resolved"`. Defaults to `"unfixed"` if `state.json` has no status. |
| `DefineDefect.filedAt` | ISO 8601 string or null. Null if `state.json` has no `created_at`. |
| `DefineAggregates` | All fields are non-negative integers. Computed from the `features` array, not independently queried. |

## Component Architecture

```
app/define/page.tsx
├── Left: (no left panel — full-width grid)
├── VisionWarning (conditional, full width above grid)
├── ColumnHeaders (3-column grid: Specified | Built | Gap)
│   └── Each: Name (15px) → Intent (12px) → Aggregate (11px)
├── FeatureRows (3-column grid per feature)
│   ├── SpecifiedCell: name + state badge, spec pills, audit, questions
│   ├── BuiltCell: hero metric or progress bar (varies by state)
│   └── GapCell: escalation/unverifiable/rework counts with descriptions
├── SectionDivider ("Defects · 9")
├── DefectRows (3-column grid per defect)
└── ExplorerPanel (slide-in, launched via Cmd+E)
```

### State-based row structure

| Feature state | SpecifiedCell | BuiltCell | GapCell | Row CSS |
|---------------|---------------|-----------|---------|---------|
| complete | Full height, all indicators | 24px hero coverage, criteria, guardian | Full gap analysis | `min-height: 100px`, `bg: --color-bg` |
| executing | Full height | Progress bar, task counts, blocked | Partial or empty | `min-height: 100px`, `bg: --color-bg` |
| writing | Same as executing | "Specs in progress" italic, no task data | Empty | `min-height: 100px`, `bg: --color-bg` |
| unplanned | Compact, inline layout | "Not yet planned" italic | "Requires execution data" italic | `min-height: auto`, `padding: 10px`, `bg: --color-bg-elevated` |

## File Impact

| File | Change | Status |
|------|--------|--------|
| `dashboard/backend/resolvers/define.py` | New file. Reads specs, features, defects. Computes audit. Returns DefineView. Calls existing readers from `landing.py` where possible. | New |
| `dashboard/backend/schema.py` | Add DefineView types and `define_view` query field. Import define resolver. Note: `spec_alignment` and `landing_view` query fields already exist. | Modify (exists) |
| `dashboard/frontend/lib/graphql/queries/define.ts` | New file. DEFINE_VIEW_QUERY. | New |
| `dashboard/frontend/app/define/page.tsx` | New file. Three-column grid with feature rows, defect rows, explorer. | New |
| `dashboard/frontend/components/layout/sidebar.tsx` | Add "Define" nav item. Update "Spec Alignment" to be a sub-item or keep as separate entry. | Modify (exists) |
| `dashboard/frontend/components/layout/header.tsx` | Add view entry for Define page. | Modify (exists) |
| `dashboard/frontend/components/landing/DefinePanel.tsx` | Update SurfaceLink href from `/spec-alignment` to `/define`. Extract VisionWarning to shared component if reused on Define page. | Modify (exists) |

## Search / Query Strategy

The `defineView` query reads from 8+ file sources on every request. No database, no indexing; all reads are filesystem-based.

### Access pattern

```
defineView query
├── specs/product/overview.md              → single file read (vision)
├── specs/product/*.md                     → glob + per-file stat (spec existence)
├── specs/tech/*.md                        → glob + per-file stat
├── specs/design/*.md                      → glob + per-file stat
├── specs/defects/*.md                     → glob + first-paragraph parse
├── .speed/features/*/state.json           → glob + per-file JSON parse
├── .speed/features/*/tasks/*.json         → glob + per-file JSON parse (heaviest)
├── .speed/features/*/spec-traceability.json → per-feature JSON parse
├── .speed/features/*/criteria-verify.json → per-feature JSON parse
├── .speed/features/*/logs/Guardian-*.jsonl → per-feature, last-entry read
├── .speed/features/*/logs/escalations.json → per-feature JSON parse
└── .speed/defects/*/state.json            → glob + per-file JSON parse
```

### Expected volumes

| Source | Typical count | Upper bound | Per-file size |
|--------|--------------|-------------|---------------|
| Spec files (product/tech/design) | 15-30 | 100 | 5-50KB (only stat, not read for content except audit) |
| Feature directories | 5-15 | 50 | N/A (directory listing) |
| Task files per feature | 5-15 | 30 | 1-5KB JSON |
| Defect state files | 2-10 | 50 | <1KB JSON |
| Guardian JSONL logs | 1 per feature | 1 | 50-500KB (only last line read) |

### Performance budget

Target: full query completes in under 500ms for a project with 10 features and 20 defects (per PRD success criterion).

Breakdown:
- Vision status: <5ms (single file stat)
- Spec existence + audit: ~50ms (30 file reads + section parsing)
- Feature state + tasks: ~100ms (15 directories, ~150 task files)
- Traceability + criteria: ~30ms (15 JSON files)
- Guardian verdicts: ~20ms (15 last-line reads)
- Escalations: ~10ms (15 JSON files)
- Defects: ~20ms (10 file reads + first-paragraph parse)
- Aggregation: <5ms (in-memory computation)
- Total: ~240ms typical, ~400ms worst case

No caching in V1. If latency exceeds budget, the first optimization is caching spec audit results (structural checks don't change unless spec files change; use file mtime as cache key).

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Full-width grid (no left panel) | The grid IS the primary content | Two-panel like OR | Define is analytical, not ceremonial. The three columns show everything at once. No work area vs context split needed. |
| Audit computed at query time | No cached artifact | Pre-computed audit file | Avoids staleness. Spec files change during Spec Sessions. The structural checks are lightweight (file existence, section parsing). Full semantic audit is a follow-up. |
| Spec pills say "Product/Technical/Design" not "PRD/RFC/DSN" | Self-describing labels | Abbreviated labels | IA principle #6: content is self-describing without column context. |
| Explorer is slide-in, not persistent | Launched via Cmd+E | Permanent sidebar | IA principle #8: secondary surfaces are launched, not persistent. The grid owns full width by default. |

## Drawbacks

- **Audit at query time adds latency.** Parsing markdown files for section presence on every load. For 10 features with 3 specs each, that's 30 file reads + section scans. Should stay under 100ms but could be slow on network-mounted filesystems.
- **No real-time updates.** Spec files change infrequently so no WebSocket subscription. But if the user is in a Spec Session and has Define open in another tab, the Define page won't reflect changes until refresh.
- **Defect impact descriptions are manual.** The "Blocks topology accuracy for all features" text in the prototype is hand-written. The resolver would need to infer impact from the defect's blast radius or leave it as the first paragraph of the defect spec.

## Testing

### Acceptance Criteria

- Define page renders at `/define` with three-column grid (Specified, Built, Gap) and column headers showing aggregates
- Each feature from `.speed/features/` appears as a row with correct lifecycle state (complete/executing/unplanned)
- Complete features show 24px hero coverage metric with emerald/amber/red color thresholds
- Executing features show progress bars with task done/total counts and blocked count
- Unplanned features render as compact single-line cells with italic placeholder text
- Spec pills show three states: present (emerald), warning (amber), missing (dashed)
- Vision warning banner renders when `specs/product/overview.md` is missing and hides otherwise
- Defect rows render below features with severity badges, status, description, and impact
- Explorer panel slides in on Cmd+E, shows document tree grouped by feature, dismisses on Escape
- Cross-column ref-markers link audit warnings in Specified to corresponding escalations in Gap
- `defineView` query returns null fields gracefully when source files are missing (no crashes)
- Page loads within 500ms for 10 features and 20 defects (measured from query start to render complete)

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| Resolver crashes on malformed `state.json` or missing fields | High | Unit tests with corrupt/partial JSON fixtures |
| Spec audit produces false positives on valid but unconventional spec files | Medium | Unit tests with edge-case markdown structures (no headings, only frontmatter, empty files) |
| Feature-spec matching fails for features with non-standard naming | Medium | Unit tests with mismatched directory/filename pairs, frontmatter fallback |
| Task file glob returns thousands of files in large projects | Low | Performance test with 50 features x 30 tasks fixture |
| Three-column grid breaks on narrow viewports | Medium | Visual test at 1024px and 1440px breakpoints |
| Guardian JSONL with corrupted last line | Medium | Unit test with truncated JSONL |

### Test Plan

**Unit tests** (`dashboard/backend/tests/test_define.py`)
- `get_define_view()` with empty project (no features, no specs, no defects)
- `get_define_view()` with fully populated project (all feature states, all spec types, defects)
- Vision status: missing, placeholder, defined
- Spec-to-feature matching: filename convention, frontmatter fallback
- Audit computation: clean specs, specs missing required sections, empty specs
- Per-feature Built data assembly from task files + traceability + guardian
- Gap data assembly from escalation logs
- Defect enrichment: severity clamping, description parsing, filedAt extraction
- Aggregates computed correctly from features array

**Integration tests** (`dashboard/backend/tests/test_schema_define.py`)
- `defineView` query returns valid GraphQL response with all nested types
- `defineView` returns null gracefully for missing project
- Feature filtering works when `$feature` argument is provided

**Visual/UI tests** (`dashboard/frontend/app/define/page.test.tsx`)
- Loading skeleton renders during query
- Three-column grid renders with correct column headers and aggregates
- Feature rows render with correct state-based structure (complete/executing/unplanned)
- Spec pills render with correct three-state styling
- Vision warning banner shows/hides based on data
- Defect rows render with severity badges
- Explorer panel toggles on Cmd+E

### Edge Cases

- Feature directory exists but `state.json` is missing (treat as unplanned)
- `spec-traceability.json` exists but has zero claims (coverage 0%, not null)
- Feature has tasks but all are status `"pending"` (progress 0%, blockedCount 0)
- Defect `state.json` has unknown severity value like `"P5"` (clamp to P3)
- Spec file exists but is empty (0 bytes; audit status "error", no warnings to list)
- Multiple features match the same spec file via frontmatter (first match wins)
- Guardian JSONL log is empty (verdict null)
- Escalation log references a `linkedWarningId` that doesn't match any audit warning (render without link)

### Out of Scope

- Performance benchmarking beyond the 500ms acceptance criterion. Load testing with 100+ features deferred until a real project reaches that scale.
- Real-time WebSocket updates for spec file changes. Specs change infrequently; manual refresh is acceptable for V1.
- Visual regression testing for the Explorer panel's document tree. The tree is a standard list; layout regressions are unlikely.

## Security & Controls

**Authentication**: The dashboard runs locally on `localhost:4440` (backend) and `localhost:3000` (frontend). No authentication beyond filesystem access. Same model as all existing dashboard pages.

**Authorization**: Read-only page. No mutations. The `defineView` query reads files that already exist on the user's filesystem. No privilege escalation.

**Data handling**: Spec content may contain user-facing text but no credentials or PII. The resolver reads file contents for audit section parsing but does not store or transmit them beyond the GraphQL response. No encryption needed (local-only).

**Input sanitization**: The optional `$feature` argument is used in `str.endswith()` matching against directory names. No shell injection risk (no subprocess calls). No SQL (no database). GraphQL input validation handled by Strawberry's type system.

**Rate limiting**: Not applicable. Local server, single user.

**Audit logging**: No action logging needed. Read-only query with no side effects.

## Dependencies

- Spec files on disk at `specs/product/`, `specs/tech/`, `specs/design/`
- Feature state at `.speed/features/*/state.json`
- Task files at `.speed/features/*/tasks/*.json`
- Spec traceability output from `spec_traceability.py` at `.speed/features/*/spec-traceability.json`
- Criteria verification output from `criteria_verify.py` at `.speed/features/*/criteria-verify.json`
- Guardian verdict logs at `.speed/features/*/logs/Guardian-*.jsonl`
- Escalation logs at `.speed/features/*/logs/escalations.json`
- Defect state at `.speed/defects/*/state.json` and defect specs at `specs/defects/*.md`
- Existing backend readers in `dashboard/backend/resolvers/landing.py` (see Existing Infrastructure section)
- Existing frontend components: `VisionWarning`, spec type pills, `DefectRow`, `ProgressBar`, `coverageColor()`, `CardSkeleton`
- Dashboard infrastructure: Next.js 14 app router, Strawberry GraphQL backend, urql client, sidebar navigation

## Unresolved Questions

- **Spec-to-feature matching**: What happens when spec filenames don't match feature directory names? Frontmatter fallback works but isn't implemented in any existing resolver.
- **Audit depth**: Should V1 audit check section content (non-empty User Stories table) or just section existence?
- **Gap data before Outcome Review**: For executing features, gap data (escalations, unverifiable criteria) accumulates during execution. Where does this data live before the Outcome Review is completed? Escalation logs exist, but unverifiable criteria counts come from `criteria_verify.py` which runs at feature completion.
