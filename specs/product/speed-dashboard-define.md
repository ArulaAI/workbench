# Dashboard: Define Page

> See `working-docs/pm-surface-design.md` for the Human Surface initiative context.
> Prototype: see `working-docs/define-page-prototype.html` (local file, not tracked in specs)

## Problem

The dashboard has five engineering pages (Mission Control, Analytics, Budget, Topology, Spec Alignment). All five serve Execute. The human phases (Define, Judge, Learn) have no product surface. A PM opening the dashboard sees task DAGs and token burn with no way to answer: "How precisely have we described what we're building, and how did those descriptions perform?"

Spec health, audit findings, and gap analysis exist as pipeline artifacts scattered across `specs/`, `.speed/features/`, and log files. No surface assembles them into a readable portfolio view.

## Users

### Product Manager
Writes PRDs and reviews traceability. Wants to see: which features have complete spec coverage, which have audit warnings, where specs fell short during execution. Reads the Specified and Gap columns.

### Engineer
Runs pipelines and writes RFCs. Wants to see: sizing estimates, audit recommendations (split before Architect decomposes), open questions that will become escalations. Reads the Specified column for prep status.

### Designer
Tracks design-to-implementation fidelity. Wants to see: which features lack design specs, what visual decisions agents defaulted on. Reads the Specified column for DSN gaps.

### Engineering Manager
Monitors portfolio health. Wants to see: aggregate coverage, escalation patterns, which features are progressing and which are stalled. Reads all three columns at the aggregate level.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As any team member, I want to see all features with their spec coverage, execution state, and gap analysis in one view | Given the Define page is open, when features exist in `.speed/features/`, then each feature appears as a row with three columns (Specified, Built, Gap) showing spec indicators, execution metrics, and gap counts | Must |
| S2 | As a PM, I want column-level aggregates so I can read the portfolio without scanning rows | Given the Define page is open, when column headers render, then each header shows Name (15px), Intent (12px framing sentence), and Aggregate (11px computed summary like "0 of 4 features have design specs") | Must |
| S3 | As an engineer, I want to see audit warnings and sizing estimates per feature | Given a feature has audit findings, when I view its Specified cell, then I see the warning count, the specific finding text, and any sizing recommendation | Must |
| S4 | As any team member, I want feature rows to look structurally different based on lifecycle state | Given features at different stages, when I view the grid, then complete features show hero metrics (24px coverage), executing features show progress bars, and unplanned features collapse to compact single-line cells | Must |
| S5 | As a PM, I want to see defects alongside features in the same three-column structure | Given defects exist in `specs/defects/`, when I view the Define page, then defects appear below features with severity badges, fix status, and impact descriptions | Must |
| S6 | As a PM, I want a prominent warning when product vision is undefined | Given `specs/product/overview.md` does not exist, when I view the Define page, then a full-width warning banner appears above the grid explaining the downstream impact (Guardian runs without anchor, Architect plans without context) | Must |
| S7 | As any team member, I want to navigate the spec tree without leaving the analytical view | Given I need to find a specific spec, when I press Cmd+E or click Explorer, then a panel slides in from the left showing the document tree grouped by feature, and clicking a spec opens the Spec Editor | Should |
| S8 | As a PM, I want to see when a spec warning and an execution gap are the same issue | Given a feature has an RFC audit warning and a corresponding escalation in the Gap column, when I view the row, then both carry the same numbered visual marker so I can see the connection without reading prose | Should |

## User Flows

### Reading the portfolio

1. User opens the Define page
2. Column headers show aggregates: "0 of 4 features have design specs", "1 complete, 2 executing, 1 unplanned", "1 escalation across 4 features"
3. User scans top-to-bottom within the Specified column: all four features lack design specs (dashed DSN pills)
4. User reads left-to-right across Security Auditor: RFC has a warning, execution is at 92% with 1 blocked task, Gap shows 1 escalation linked to the same RFC issue
5. User decides to address the RFC warning before the escalation compounds

### Launching the explorer

1. User presses Cmd+E
2. Explorer panel slides in from the left (260px)
3. Document tree shows features grouped with PRD/RFC/DSN indicators
4. User clicks the Security Auditor RFC
5. Spec Editor opens with the RFC loaded
6. User presses Escape to dismiss the explorer and return to the analytical view

## Success Criteria

- [ ] Three-column grid renders with Specified, Built, and Gap columns
- [ ] Column headers show the three-layer pattern (Name, Intent, Aggregate)
- [ ] Feature rows render with spec indicators (Product/Technical/Design pills)
- [ ] Complete features show 24px hero coverage metric
- [ ] Executing features show progress bars with task counts
- [ ] Unplanned features collapse to compact single-line cells
- [ ] Product vision warning appears when `overview.md` is missing
- [ ] Defects appear below features with severity, status, and impact
- [ ] Explorer panel slides in on Cmd+E and dismisses on Escape
- [ ] Cross-column ref-markers connect related spec warnings and execution gaps
- [ ] Page loads within 500ms for a project with 10 features and 20 defects

## Scope

### In Scope
- Three-column analytical grid (Specified, Built, Gap)
- Column header three-layer pattern (Name → Intent → Aggregate)
- Feature rows with lifecycle-state-based structure
- Spec indicator pills (Product, Technical, Design) with present/warning/missing states
- Audit findings display per feature
- Product vision warning banner
- Defect section with severity badges
- Explorer slide-in panel with document tree
- Cross-column relationship markers
- GraphQL resolver reading from `specs/` and `.speed/`

### Out of Scope (and why)
- Spec editing (handled by the Spec Editor page)
- Real-time updates via WebSocket (specs change infrequently)
- Defect filing or triage (handled by the CLI)
- Feature planning or execution (handled by Execute page)

## Prior Art

The following surfaces already exist and partially cover Define page user stories. The `/define` page builds on these rather than replacing them.

| Surface | What it covers | User stories partially addressed |
|---------|---------------|----------------------------------|
| Landing DefinePanel (`/`, grid cell) | Vision status warning, draft spec list with type pills (Product/Technical/Design), defect list with severity badges. Max 5 items per list with "View all" overflow link. | S1 (spec coverage at a glance), S5 (defects with severity), S6 (vision warning) |
| Spec Alignment page (`/spec-alignment`) | Per-claim verification status (confirmed/missing/unverifiable/divergent) with expandable sections per spec file. Summary bar with coverage %, total claims, confirmed, missing counts. | None directly, but provides the drill-down data for S1's "spec coverage" when a user wants claim-level detail |

The landing panel provides portfolio awareness without navigation. The Define page provides the full analytical grid with per-feature rows, lifecycle-state-based structure, audit findings, and gap analysis that the landing panel cannot fit.

The Spec Alignment page answers "which claims are confirmed?" The Define page answers "which features are well-specified, well-built, and where are the gaps?" They operate at different levels of abstraction. `/spec-alignment` becomes a drill-down from the Define page's Built column.

## Dependencies

- Spec files on disk at `specs/product/`, `specs/tech/`, `specs/design/`
- Feature state at `.speed/features/*/state.json`
- Spec traceability output from `spec_traceability.py`
- Criteria verification output from `criteria_verify.py`
- Escalation logs from feature execution
- Audit results (structural checks on spec files)
- Existing dashboard infrastructure: Next.js 14 app router, Strawberry GraphQL backend, urql client, sidebar navigation, feature selector
- Existing backend readers in `landing.py`: `_read_vision_status()`, `_read_draft_specs()`, `_read_defects()`, `_read_criteria_verify()`, `_read_guardian_verdict()`, `_read_task_files()`
- Existing frontend components: `VisionWarning`, spec type pills, `DefectRow`, `ProgressBar`, `coverageColor()` utility

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Spec files don't follow expected directory structure | Medium | Resolver handles missing files gracefully. Empty cells show "no spec found" rather than errors. |
| Large project (50+ features) makes the grid unwieldy | Low | Defects dim at P3+. Completed features could collapse. Pagination not needed for typical project sizes (5-15 features). |
| Audit results don't exist yet as structured data | Medium | Resolver computes basic structural checks (file exists, required sections present) at query time. Full audit integration is a follow-up. |

## Security & Controls

**Authentication**: Dashboard runs locally. No additional auth beyond filesystem access.

**Authorization**: Read-only page. No mutations. Any team member with repo access can view.

**PII**: Spec content may contain user-facing text. No new PII surfaces beyond what's already in the spec files.

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should the audit results be computed at query time or read from a cached artifact? | Affects resolver complexity and page load time. Cached is faster but stale. | Open |
| Q2 | Should the explorer panel show audit status per spec file? | The prototype shows it. The resolver would need to run structural checks per file. | Open |
| Q3 | How should the page handle features that exist in `.speed/features/` but have no corresponding specs? | These are features started without spec coverage. Could show as a warning row. | Open |
