# RFC: Dashboard Landing Page

> See [product spec](../product/speed-dashboard-landing.md) for product context.
> Prototype: `working-docs/landing-editorial.html` (static HTML mockup in repo root)

## Basic Example

```graphql
query LandingView {
  landingView {
    greeting                        # "Good morning, Sanjay"
    projectName                     # "speed"
    branch                          # "feature/continuous-learning"
    narrative                       # LLM project narrative (nullable)

    define {
      visionStatus                  # "missing" | "placeholder" | "defined"
      draftSpecs {
        name
        specTypes                   # ["product", "technical"] (what exists)
        status                      # "unplanned" | "writing"
      }
      defects {
        severity                    # "P0" | "P1" | "P2" | "P3"
        name
      }
      defectCount
    }

    judge {
      pendingReview {               # nullable (null if no review pending)
        feature
        completedAt
        coveragePct
        criteriaPassed
        criteriaTotal
        guardianVerdict
        decisionsNeeded
        summary                     # short narrative (nullable)
      }
      lastCompleted {               # nullable
        feature
        verdict
        coveragePct
      }
    }

    execute {
      runningFeatures {
        name
        progressPct
        tasksCompleted
        tasksTotal
        blockedCount
      }
      escalations {
        feature
        taskId
        taskTitle
        question
      }
    }

    learn {
      coverageTrend {
        feature
        coveragePct
      }
      insights {
        type                        # "good" | "warn"
        text
      }
      escalationTrend {
        feature
        count
      }
    }
  }
}

# Mutation: respond to an escalation inline
mutation RespondToEscalation($feature: String!, $taskId: String!, $response: String!) {
  respondToEscalation(feature: $feature, taskId: $taskId, response: $response) {
    success
    error
  }
}
```

## Data Model

### What the resolver reads

The landing page is a summary projection of four phase data sources. Each panel reads a subset of the same artifacts the phase pages read.

| Panel | Source | Path | Data extracted |
|-------|--------|------|----------------|
| Define | Product vision | `specs/product/overview.md` | Existence check |
| Define | Spec files | `specs/product/*.md`, `specs/tech/*.md` | Feature names without execution state → draft specs |
| Define | Defect state | `.speed/defects/*/state.json` | Severity, name, count |
| Judge | Feature state | `.speed/features/*/state.json` | Features with status "done" and no review.json → pending review |
| Judge | Review state | `.speed/features/*/review.json` | Verdict status → last completed review |
| Judge | Verification | `.speed/features/*/criteria-verify.json` | Coverage, criteria counts (for pending review) |
| Judge | Guardian | `.speed/features/*/logs/Guardian-*.jsonl` | Verdict (for pending review) |
| Execute | Feature state | `.speed/features/*/state.json` | Features with status "running" |
| Execute | Task files | `.speed/features/*/tasks/*.json` | Progress counts, blocked tasks |
| Execute | Escalation data | `.speed/features/*/tasks/*.json` | Tasks with `status: "blocked"` and `escalation_question` field |
| Learn | Observations | `.speed/memory/observations/{feature}.jsonl` | Coverage per feature (for trend) |
| Learn | Spec traceability | `.speed/features/*/spec-traceability.json` | Coverage % per completed feature |
| Learn | Learnings | `.speed/memory/*-learnings.json` | Top insights by weight |

### Draft spec detection

A spec is a "draft" when it exists on disk but the feature has no execution state:
1. Scan `specs/product/*.md` for feature names
2. Check whether `.speed/features/{name}/` exists with a `state.json`
3. If no feature state: the spec is a draft (written but not planned)
4. Also check: if `specs/product/foo.md` exists but `specs/tech/foo.md` doesn't, the feature has a PRD without an RFC

### Escalation response mutation

Writes the response to the task's JSON file:

```json
// .speed/features/{feature}/tasks/{taskId}.json
{
  "id": "1",
  "title": "Config parsing",
  "status": "blocked",
  "escalation_question": "Spec says [security] is optional...",
  "escalation_response": "Fall back to defaults",    // ← written by mutation
  "escalation_responded_at": "2026-03-15T10:30:00Z"  // ← written by mutation
}
```

The pipeline polls for this response. When it finds `escalation_response` populated, it unblocks the task and continues execution.

### LLM project narrative

**Input** (~1K tokens): feature states, escalation count, pending review info, defect counts.

**Prompt**: "Write 2-3 sentences summarizing the project state for someone arriving at the dashboard. What needs attention? What's progressing well? Direct and specific."

**Degradation**: Without LLM, the Judge panel shows structured data (feature name, metrics, decision count) without the narrative paragraph.

## Search / Query Strategy

The `landingView` resolver reads from 13 disk locations across four data source categories. All reads are local filesystem I/O with no database or network calls (aside from the optional LLM narrative).

### Access pattern

Every panel read is a directory listing followed by JSON parse. No file exceeds a few KB. The resolver performs these reads sequentially within each panel, but panels are independent and can be parallelized.

```
Define panel:    1 existence check + 2 glob scans + N state.json reads
Judge panel:     N state.json reads + 1 review.json + 1 criteria-verify.json + 1 Guardian log scan
Execute panel:   N state.json reads + M task JSON reads (M = total tasks across running features)
Learn panel:     N observation JSONL reads + N traceability JSON reads + 1 learnings JSON read
LLM narrative:   1 provider_chat() call (async, 5s timeout)
```

### Expected volumes

A typical SPEED project has 5-15 features, each with 5-20 tasks. At the upper bound (15 features, 20 tasks each), the resolver reads ~15 state files, ~300 task files, and ~15 observation files. Each file is under 5KB. Total I/O: ~1.5MB of sequential reads.

### Performance target

< 200ms for the combined query without the LLM call. The LLM narrative runs with a 5-second timeout and returns `null` on failure, so it never blocks the structured data response beyond that bound.

### Caching considerations

No caching in V1. The resolver reads fresh from disk on every query. Rationale: the dashboard is single-user, queries are infrequent (page load, not polling), and the data changes between loads (tasks complete, escalations arrive). If profiling shows the 200ms target is missed, the first optimization is parallel panel reads using `asyncio.gather()`, not caching. File-level caching with mtime checks is a V2 option if parallel reads are insufficient.

### Read ordering

Panels have no cross-dependencies. The resolver can read them in any order. Within the Judge panel, `state.json` must be read before `criteria-verify.json` and Guardian logs because the feature identity comes from state. Within Execute, `state.json` identifies running features before task files are scanned.

## API Surface

### GraphQL types

```python
@strawberry.type
class LandingDraftSpec:
    name: str
    spec_types: list[str]
    status: str

@strawberry.type
class LandingDefect:
    severity: str
    name: str

@strawberry.type
class LandingDefinePanel:
    vision_status: str
    draft_specs: list[LandingDraftSpec]
    defects: list[LandingDefect]
    defect_count: int

@strawberry.type
class LandingPendingReview:
    feature: str
    completed_at: Optional[str]
    coverage_pct: float
    criteria_passed: int
    criteria_total: int
    guardian_verdict: str
    decisions_needed: int
    summary: Optional[str]

@strawberry.type
class LandingLastCompleted:
    feature: str
    verdict: str
    coverage_pct: float

@strawberry.type
class LandingJudgePanel:
    pending_review: Optional[LandingPendingReview]
    last_completed: Optional[LandingLastCompleted]

@strawberry.type
class LandingRunningFeature:
    name: str
    progress_pct: float
    tasks_completed: int
    tasks_total: int
    blocked_count: int

@strawberry.type
class LandingEscalation:
    feature: str
    task_id: str
    task_title: str
    question: str

@strawberry.type
class LandingExecutePanel:
    running_features: list[LandingRunningFeature]
    escalations: list[LandingEscalation]

@strawberry.type
class LandingCoverageTrend:
    feature: str
    coverage_pct: float

@strawberry.type
class LandingInsight:
    type: str
    text: str

@strawberry.type
class LandingEscalationTrend:
    feature: str
    count: int

@strawberry.type
class LandingLearnPanel:
    coverage_trend: list[LandingCoverageTrend]
    insights: list[LandingInsight]
    escalation_trend: list[LandingEscalationTrend]

@strawberry.type
class LandingView:
    greeting: str
    project_name: str
    branch: Optional[str]
    narrative: Optional[str]
    define: LandingDefinePanel
    judge: LandingJudgePanel
    execute: LandingExecutePanel
    learn: LandingLearnPanel

@strawberry.input
class EscalationResponseInput:
    feature: str
    task_id: str
    response: str

@strawberry.type
class EscalationResponseResult:
    success: bool
    error: Optional[str]
```

### Query and mutation fields

```python
@strawberry.field
def landing_view(self, info: strawberry.types.Info) -> LandingView:
    project_root = info.context["project_root"]
    conn = info.context["conn"]
    return landing.get_landing_view(project_root, conn)

@strawberry.mutation
def respond_to_escalation(self, info: strawberry.types.Info, input: EscalationResponseInput) -> EscalationResponseResult:
    project_root = info.context["project_root"]
    return landing.respond_to_escalation(project_root, input)
```

The landing page also uses the existing `taskStatusChanged` subscription for live Execute panel updates.

## Component Architecture

```
app/landing/page.tsx  (or app/page.tsx replacing the redirect)
├── TopBar (greeting + project + branch)
├── EditorialGrid (CSS grid: 260px | 1fr | 320px, rows: 1fr 1fr)
│   ├── DefinePanel (grid-column:1, grid-row:1/3)
│   │   ├── PanelLabel ("Define" + "Specs and preparation")
│   │   ├── VisionWarning (conditional)
│   │   ├── DraftSpecItem[] (icon + name + meta + arrow)
│   │   └── DefectList (severity badges + names)
│   │
│   ├── JudgePanel (grid-column:2, grid-row:1)
│   │   ├── PanelLabel ("Judge" + feature name + date)
│   │   ├── ReviewSummary (narrative text)
│   │   ├── HeroMetrics (28px: coverage, criteria, guardian, critical)
│   │   ├── DecisionCount (amber if > 0)
│   │   └── PrimaryCTA ("Review & decide")
│   │
│   ├── ExecutePanel (grid-column:2, grid-row:2)
│   │   ├── PanelLabel ("Execute" + running count)
│   │   ├── RunningFeature[] (dot + name + progress bar + %)
│   │   └── EscalationCard (badge + question + inline input + send)
│   │
│   └── LearnPanel (grid-column:3, grid-row:1/3)
│       ├── PanelLabel ("Learn" + "Patterns and improvement")
│       ├── CoverageTrend (feature rows with mini bars)
│       ├── Insights (good/warn cards)
│       └── EscalationTrend (feature rows with counts)
│
└── StatusBar (connection + project + features + running indicators)
```

## File Impact

| File | Change |
|------|--------|
| `dashboard/backend/resolvers/landing.py` | New file. Reads from all four phase data sources. Computes draft spec detection. Calls LLM for narrative. |
| `dashboard/backend/schema.py` | Add LandingView types, query field, escalation response mutation. Import resolver. |
| `dashboard/frontend/lib/graphql/queries/landing.ts` | New file. LANDING_VIEW_QUERY, RESPOND_TO_ESCALATION_MUTATION. Reuse TASK_STATUS_SUBSCRIPTION. |
| `dashboard/frontend/app/page.tsx` | Replace redirect with landing page component (or create `app/landing/page.tsx`). |
| `dashboard/frontend/components/layout/sidebar.tsx` | Shared: add nav items for all 4 new pages. See Define RFC for details. |
| `dashboard/frontend/components/layout/header.tsx` | Shared: add view entries for all 4 new pages. See Define RFC for details. |

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Fixed panel positions | Define always left, Judge always top-center, Execute always bottom-center, Learn always right | Rearrangeable panels, urgency-sorted | Fixed positions build muscle memory. After a week, the team knows where to look without scanning. Variable weight handles urgency within fixed positions. |
| T-shape layout | Center splits horizontally (Judge top, Execute bottom). Sidebars span full height. | Equal quadrants, single-column scroll | The center stage is where action happens (review CTA, escalation input). Sidebars are reference (spec health, learning trends). The T-shape gives the center more space. |
| Inline escalation response | Text input + Send button in the Execute panel | Route to Execute page for response | Responding to "Fall back to defaults, or require it?" doesn't need a full page. Inline reduces friction. The response writes to task JSON and the pipeline picks it up. |
| Single summary resolver | One query aggregates all four panels | Four separate queries (one per panel) | Reduces round trips. The landing page needs all four panels simultaneously. Four queries add latency without benefit (no partial rendering). |
| LLM narrative in Judge panel | Enhances the "lead story" when a review is pending | Narrative across all panels | The Judge panel is the lead story. The narrative contextualizes the pending review. Other panels have structured content that doesn't need synthesis. |

## Validation Rules

| Field | Constraints |
|-------|-------------|
| `escalation_response` (mutation input) | Required non-empty string. Maximum 2,000 characters. No structured format required (free text). |
| `feature` (mutation input) | Required. Must resolve to an existing directory at `.speed/features/{feature}/`. |
| `task_id` (mutation input) | Required. Must resolve to an existing file at `.speed/features/{feature}/tasks/{task_id}.json`. |
| `task.status` (mutation precondition) | Task must have `status: "blocked"` and a non-empty `escalation_question`. Mutation rejects if task is not in blocked state. |
| `severity` (defect display) | One of: `P0`, `P1`, `P2`, `P3`. Defects with unrecognized severity render as `P3`. |
| `vision_status` | One of: `missing`, `placeholder`, `defined`. Derived from `specs/product/overview.md`. See Define RFC for detection logic. |
| `coverage_pct` | Float 0.0-100.0. Clamped to range on read. Displayed as integer percentage. |
| `spec_types` (draft spec) | Non-empty array. Values limited to `"product"` and `"technical"`. |
| `insight.type` | One of: `good`, `warn`. Unknown types filtered out at the resolver. |
| LLM narrative prompt | Input capped at 1,000 tokens. Output capped at 150 tokens. Timeout: 5 seconds. On failure or timeout, `narrative` returns `null`. |

## Testing

### Acceptance Criteria

Verifiable behaviors that gate ship. A reviewer can confirm each without reading implementation code.

1. `landingView` query returns all four panels populated when `.speed/features/`, `specs/`, `.speed/defects/`, and `.speed/memory/` contain data
2. `landingView` query returns empty lists (not errors) when no features, specs, defects, or memory data exist
3. `define.vision_status` returns `"missing"` when `specs/product/overview.md` does not exist, and `"defined"` when it does (placeholder detection deferred to Define RFC logic)
4. `define.draft_specs` includes specs that exist on disk but have no `.speed/features/{name}/state.json`
5. `judge.pending_review` is non-null only when a feature has `status: "done"` in state.json and no `review.json`
6. `execute.escalations` includes only tasks with `status: "blocked"` and a non-empty `escalation_question` field
7. `respondToEscalation` mutation writes `escalation_response` and `escalation_responded_at` to the correct task JSON file
8. `respondToEscalation` mutation returns `success: false` when the task is not in blocked state
9. `narrative` field returns `null` (not an error) when the LLM provider is unavailable or times out
10. Frontend renders T-shape grid: Define left (260px), Judge top center, Execute bottom center, Learn right (320px)
11. Escalation inline input sends mutation and updates Execute panel without page navigation
12. "Review & decide" CTA navigates to Outcome Review with the correct feature pre-selected

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| Resolver reads stale or corrupt `state.json` | High | Unit test: malformed JSON in state.json. Verify resolver skips the feature with a warning, does not crash |
| Task JSON written by mutation is invalid for the pipeline | High | Unit test: after mutation, read the task JSON back and validate it contains all required fields with correct types |
| Race condition: two concurrent escalation responses to the same task | Medium | Unit test: simulate concurrent writes. Verify last-write-wins and file is not corrupted (atomic write via temp + rename) |
| LLM narrative takes > 5s and blocks the entire query | Medium | Unit test: mock provider with 6s delay. Verify `narrative` returns `null` and remaining fields are still populated |
| `.speed/memory/` directory missing on fresh project | Medium | Unit test: resolver called with empty project root. Verify Learn panel returns empty lists, no file-not-found errors |
| Draft spec detection misidentifies active features as drafts | Medium | Unit test: feature with `state.json` exists alongside spec. Verify it does not appear in `draft_specs` |

### Test Plan

**Unit tests** (`tests/test_landing_resolver.py`)

Define panel:
- Vision detection: file missing, file < 50 chars, file with content. Verify three `vision_status` values
- Draft spec detection: spec exists with no feature dir, spec exists with feature dir, spec exists with state.json. Verify only unplanned specs appear
- Defect aggregation: multiple defects across severities. Verify list contents and `defect_count`

Judge panel:
- Pending review detection: feature with `status: "done"` and no `review.json`. Verify `pending_review` populated
- No pending review: all features have `review.json`. Verify `pending_review` is null
- Last completed review: feature with `review.json` containing verdict. Verify `last_completed` fields

Execute panel:
- Running features: features with `status: "running"`. Verify progress calculation from task counts
- Escalation extraction: blocked tasks with `escalation_question`. Verify only those appear in `escalations`
- No running features: all features done or planned. Verify empty lists

Learn panel:
- Coverage trend: multiple completed features with `spec-traceability.json`. Verify per-feature coverage values
- Insights: learnings files with weighted entries. Verify top insights returned with correct types
- Empty memory directory: verify empty lists returned

Escalation mutation:
- Valid response: task in blocked state with escalation question. Verify JSON updated with response and timestamp
- Invalid task: non-existent feature or task ID. Verify `success: false` with error message
- Task not blocked: task in running state. Verify mutation rejected

LLM narrative:
- Provider available: verify narrative string returned in Judge panel
- Provider timeout: verify `null` returned, other fields unaffected
- Provider error: verify `null` returned, no exception propagated

**Frontend tests** (`__tests__/landing/`)

- Grid layout snapshot: verify CSS grid template columns match `260px 1fr 320px`
- Panel rendering: each panel renders with mock data (labels, metrics, lists present)
- Escalation input: type text, click Send, verify mutation called with correct variables
- CTA routing: click "Review & decide", verify router push to `/outcome-review?feature=<name>`
- Empty states: all panels with empty data. Verify no crash, empty state messages shown
- Subscription integration: mock `taskStatusChanged`, verify Execute panel re-renders

**Integration tests**

Deferred to Phase 2 (frontend implementation). Two cross-module integration points require verification beyond unit mocks:

- LLM narrative integration: start the backend with a real (or locally stubbed) LLM provider. Issue `landingView` query. Verify `narrative` is a non-null string when provider is healthy, and `null` when provider is stopped. Confirms timeout handling, prompt assembly, and response parsing work end-to-end through `provider_chat()`.
- WebSocket subscription: start backend, connect a WebSocket client, subscribe to `taskStatusChanged`. Modify a task JSON on disk (simulating pipeline progress). Verify the subscription delivers the update. Confirms the existing subscription infrastructure carries landing page events without modification.

**End-to-end tests**

Deferred to after both phases ship. The two product spec user flows (morning check-in, escalation response) span resolver reads, mutation writes, pipeline read-back, and client-side routing. Automating these requires a running backend, a seeded `.speed/` directory, and a browser driver. Planned as a post-ship validation suite rather than a gate, because the individual unit and integration layers cover each step independently.

Milestone: add e2e suite within one sprint of Phase 2 completion.

**Visual/UI tests**

- Layout regression: snapshot the EditorialGrid at 1280px and 1920px viewport widths. Verify CSS grid columns (260px | 1fr | 320px) and row spans are stable across changes.
- Panel states: snapshot each panel in four states (loading skeleton, empty, populated, error fallback). Eight snapshots total (4 panels x populated + empty; loading and error are shared grid-level states).
- Escalation card: snapshot with question text of varying lengths (short, 200+ chars with line wrapping). Verify the inline input and Send button remain visible.
- Theme consistency: verify no component uses `#fff` or hardcoded colors outside the design token palette defined in `globals.css`.

### Edge Cases

- Project with zero specs, zero features, zero defects, zero memory: all panels return empty lists, no errors
- Feature directory exists but `state.json` is missing or empty: feature skipped in all panels
- Task JSON missing `escalation_question` field entirely (not just empty): task excluded from escalations
- Spec file with unconventional name (spaces, special characters): draft spec detection still works via filename normalization
- Two features both awaiting review: `pending_review` returns the one with the most recent `completed_at`; second is not surfaced (documented limitation)
- Guardian log directory exists but contains no `Guardian-*.jsonl` files: `guardian_verdict` defaults to `"unknown"`
- `escalation_responded_at` already present on task when mutation fires (duplicate response): overwrite with new response and timestamp
- Observation JSONL file with corrupted lines: valid lines parsed, corrupted lines skipped with warning
- LLM returns narrative exceeding 150 token cap: response truncated at sentence boundary

### Out of Scope

- Load testing the summary resolver across projects with 50+ features. Optimization deferred until real usage data exists.
- Offline/cached rendering when the backend is unreachable. The landing page requires a live GraphQL connection.
- Keyboard navigation between panels. Accessibility improvements planned as a separate initiative.
- Responsive layout below 1280px viewport width. V1 targets desktop only.
- Panel-level error boundaries showing "resolver failed" vs "no data." V1 uses empty states for both cases.
- Real-time narrative updates (re-running LLM on every state change). Narrative refreshes only on full page load or manual refresh.

## Security & Controls

The dashboard runs locally on the developer's machine with no authentication layer. No network-accessible endpoints are exposed by default. Binding to `0.0.0.0` makes the operator responsible for network-level access control.

The `respondToEscalation` mutation is the only write path. It targets `.speed/features/{feature}/tasks/{taskId}.json`, validating both `feature` and `taskId` against existing directory and file paths before any write. Path components containing `/`, `..`, or null bytes are rejected. All writes use atomic temp-file-then-rename to prevent partial writes on crash or concurrent access.

The resolver reads JSON and markdown files from disk. No user input is interpolated into shell commands or subprocess calls. The LLM narrative prompt receives only project metadata (feature names, task counts, escalation counts, defect counts). No source code, credentials, or file contents reach the LLM provider, and the prompt is hardcoded rather than user-configurable.

Escalation questions surfaced in the Execute panel originate from agent escalations and may quote code snippets or spec text. The frontend renders these as text using React's default escaping; no `dangerouslySetInnerHTML`.

## Dependencies

| Dependency | Required artifact | Consequence if absent |
|------------|------------------|----------------------|
| **Feature state files** | `.speed/features/*/state.json` with `status` field (produced by `cmd_plan()` and `cmd_run()`) | Execute and Judge panels return empty. Define draft detection still works (absence of state = draft). |
| **Spec files** | `specs/product/*.md` and `specs/tech/*.md` (authored by user or `cmd_plan()`) | Define panel shows no draft specs. Other panels unaffected. |
| **Defect state** | `.speed/defects/*/state.json` with `severity` and `name` fields (produced by `cmd_defect()`) | Define panel defect list empty. `defect_count` = 0. |
| **Verification results** | `.speed/features/*/criteria-verify.json` with `coverage_pct`, `criteria_passed`, `criteria_total` (produced by `cmd_verify()`) | Judge panel `pending_review` shows zeroed metrics. Review still surfaced but without coverage data. |
| **Guardian logs** | `.speed/features/*/logs/Guardian-*.jsonl` (produced by `cmd_guardian()`) | `guardian_verdict` defaults to `"unknown"` in pending review. |
| **Task files** | `.speed/features/*/tasks/*.json` with `status`, `escalation_question` fields (produced by `cmd_plan()`, written during `cmd_run()`) | Execute panel shows running features with 0/0 progress. No escalations surfaced. |
| **Observation data** | `.speed/memory/observations/{feature}.jsonl` (produced by `speed learn`) | Learn panel coverage trend empty. |
| **Learnings data** | `.speed/memory/*-learnings.json` with weighted entries (produced by `speed learn`) | Learn panel insights list empty. |
| **Spec traceability** | `.speed/features/*/spec-traceability.json` (produced by `cmd_review()`) | Learn panel coverage trend falls back to observation data only. |
| **LLM provider** | `provider_chat()` function from dashboard backend (existing infrastructure) | `narrative` field returns `null`. Judge panel shows structured data without summary paragraph. |
| **WebSocket subscription** | `taskStatusChanged` subscription (exists for Mission Control, defined in `schema.py`) | Execute panel does not update live. User must refresh for progress changes. |
| **Phase pages** | Define page, Outcome Review page, Learning page (sibling RFCs: `speed-dashboard-define.md`, `speed-dashboard-outcome-review.md`, `speed-dashboard-learning.md`) | CTAs render but route to 404 until those pages ship. Landing page itself is functional without them. |

## Migration Strategy

The `respondToEscalation` mutation adds two fields to existing task JSON files: `escalation_response` (string) and `escalation_responded_at` (ISO timestamp). The change is additive. Existing task files that predate these fields require no backfill. The pipeline treats a missing `escalation_response` field identically to an unresponded escalation (the task remains blocked). The resolver's read path already handles absent fields via optional access: a task without `escalation_response` simply does not appear in the "responded" filter. No migration script, no feature flag, no phased rollout. Code ships first; the fields appear only when a user responds to an escalation through the dashboard.

## Drawbacks

- **Summary resolver is broad.** It reads from `.speed/features/`, `specs/`, `.speed/defects/`, `.speed/memory/`, and log files. Any change to these file structures breaks the resolver. It's the most fragile resolver in the system.
- **Escalation response bypasses the CLI.** Writing directly to task JSON from the dashboard skips any CLI validation. If the pipeline expects responses in a specific format, the dashboard mutation must enforce the same rules.
- **No offline indicator per panel.** If the Learn panel has no data (no completed features), it shows an empty state. But the user doesn't know if that's "no data yet" or "resolver failed." Panel-level error states would help but add complexity.
- **Greeting requires timezone.** "Good morning" vs "Good afternoon" needs the client's local time. The resolver can't determine this server-side. The greeting must be computed on the client.

## Unresolved Questions

- **Root route replacement**: Should `app/page.tsx` become the landing page (replacing the Mission Control redirect)? Or should the landing page be at `/landing` with the root still redirecting to Mission Control for backward compatibility?
- **Multiple pending reviews**: If two features are awaiting review simultaneously, the Judge panel shows the most recent one. Should there be a "2 more" indicator? Or should the panel stack them?
- **Escalation response format**: The mutation writes a plain text `escalation_response` to task JSON. Does the pipeline expect structured input (e.g., JSON with a `type` field)? Or is free-text sufficient?
- **Panel loading states**: Should each panel show an independent loading skeleton, or should the entire grid show a single skeleton until the combined query resolves?
