---
status: draft
feature: speed-dashboard-task-board
---

# Design: Dashboard Task Board

> See [product spec](../product/speed-dashboard-task-board.md) for product context.
> Design system: `dashboard/frontend/app/globals.css`

<!--
  WHO READS THIS SPEC
  AI coding agents use this as their primary implementation reference.
  Every visual property references a token from globals.css. No raw hex
  values, no invented token names.

  SCOPE
  Plan mode only. Execute mode is a separate design spec. The task board
  replaces the editor view when active, accessed via "Open Plan →" from
  the decomposition slide-out panel.
-->

## Design Intent

**Direction:** The task board reads like a structured document, not a project management tool. The author is reviewing a plan before approving it, not tracking execution. The layout prioritizes scanning (compact task rows), context (always-visible detail panel), and spatial understanding (execution shape showing parallelism and depth). Feels like reading an architecture document with an interactive table of contents.

**Do not:** Use a kanban board layout with columns. Use drag-and-drop as a primary interaction. Add status badges or progress bars in plan mode (no execution state exists yet). Use cards with equal visual weight for tasks of different complexity. Add animations beyond 150ms transitions on selection and hover.

## Pages / Routes

No new routes. The task board renders inside the existing `/define/:feature` page, replacing the editor area when the user navigates from the decomposition panel. The URL does not change. Back navigation restores the editor.

```
/define/:feature  →  CeremonyLayout (editor)
                  →  TaskBoard (plan mode, full takeover)
```

## Layout Structure

### Top-level: horizontal split

```
┌─────────────────────────────────────┬─────────────────────────┐
│          Left Panel                 │     Right Panel         │
│      (plan document, scrolls)       │   (task detail, scrolls)│
│                                     │                         │
│  ┌───────────────────────────────┐  │  ┌───────────────────┐  │
│  │ Plan Header                   │  │  │ T1 · sonnet       │  │
│  │   Mode badge                  │  │  │                   │  │
│  │   Feature name                │  │  │ Define recall     │  │
│  │   Intent                      │  │  │ data types...     │  │
│  │   Stats                       │  │  │                   │  │
│  │   Gate warnings               │  │  │ WHAT              │  │
│  │   Execution shape             │  │  │ ...               │  │
│  ├───────────────────────────────┤  │  │                   │  │
│  │ Start · 4 tasks               │  │  │ WHY               │  │
│  │   T1  Define recall types...  │  │  │ ...               │  │
│  │   T2  Add knowledge_items...  │  │  │                   │  │
│  │   T7  Badge color tokens...   │  │  │ FILES             │  │
│  │   T8  QueryInput, Filter...   │  │  │ ...               │  │
│  │   + Add task                  │  │  │                   │  │
│  ├───────────────────────────────┤  │  │ DONE WHEN         │  │
│  │ Phase 1 · 3 tasks             │  │  │ ...               │  │
│  │   T3  Build ingestion pipe... │  │  │                   │  │
│  │   T9  RecallAnswerBlock...    │  │  │ CONNECTED TO      │  │
│  │   T11 PriorDecisionsCard...   │  │  │ ...               │  │
│  │   + Add task                  │  │  │                   │  │
│  ├───────────────────────────────┤  │  │ ASSUMPTIONS       │  │
│  │ ...                           │  │  │ ...               │  │
│  └───────────────────────────────┘  │  └───────────────────┘  │
├─────────────────────────────────────┴─────────────────────────┤
│  Bottom Bar: gate status · Verify · Approve Plan              │
└───────────────────────────────────────────────────────────────┘
```

**Left panel:** `flex: 1 1 0`, `min-width: 420px`, `max-width: 860px`, `overflow-y: auto`
**Right panel:** `flex: 1 1 480px`, `min-width: 360px`, `max-width: 640px`, `overflow-y: auto`, `border-left: 1px solid --border`
**Bottom bar:** `flex-shrink: 0`, normal flow child (not fixed/absolute)

The detail panel is always visible. T1 is selected on initial load. No layout shift when selecting tasks.

### Nav bar (above the board)

```
┌─────────────────────────────────────────────────────────────────┐
│  [← Editor]   speed-dashboard-recall   RFC                      │
└─────────────────────────────────────────────────────────────────┘
```

- "← Editor" button: `--text-secondary`, `--bg-elevated`, `--border`, `border-radius: 4px`
- Feature name: `--font-mono`, 11px, `--text-tertiary`
- Spec type: `--font-mono`, 10px, `--accent`

## Component Inventory

| Component | Description | Parent |
|-----------|-------------|--------|
| `TaskBoard` | Top-level plan mode shell. Manages selected task state, renders left/right/bottom layout. | `CeremonyLayout` |
| `PlanHeader` | Mode badge + feature name + intent + stats + gate warnings | `TaskBoard` (left) |
| `ExecutionShape` | Centered proportional row visualization with dependency coloring | `TaskBoard` (left) |
| `PhaseGroup` | Phase header + task rows + add button | `TaskBoard` (left) |
| `TaskRow` | Compact single-line task entry: ID, title, file, model, deps | `PhaseGroup` |
| `TaskDetail` | Full task information panel with structured sections | `TaskBoard` (right) |
| `Section` | Reusable labeled section (WHAT, WHY, FILES, etc.) | `TaskDetail` |
| `StructuredBody` | Renders description text with bullets, numbered lists, inline code | `TaskDetail` |
| `DepRow` | Clickable dependency link (upstream/downstream) | `TaskDetail` |
| `PlanStat` | Hero stat display (number + label) | `PlanHeader` |
| `BottomBar` | Gate status + Verify + Approve Plan buttons | `TaskBoard` |

## States

### Plan Header

| Element | Default | Verified (pass) | Verified (warnings) | Approved |
|---------|---------|-----------------|---------------------|----------|
| Gate status dot | Hidden | `--emerald`, 6px | `--amber`, 6px | `--emerald`, 6px |
| Gate status text | Hidden | "No warnings" | "N warnings" | "Approved" |
| Verify button | Visible | Visible | Visible | Hidden |
| Approve button | Visible | Visible | Visible | Hidden |
| Lock icon | Hidden | Hidden | Hidden | Visible, `--emerald` |

### Task Row

| Element | Default | Hover | Selected | Opus variant |
|---------|---------|-------|----------|-------------|
| Background | transparent | `--bg-card` | `--bg-card` | Same |
| Left border | 2px transparent | 2px transparent | 2px `--accent` | Same |
| Task ID color | `--text-tertiary` | `--text-tertiary` | `--accent` | `--accent` always |
| Title color | `--text` | `--text` | `--text` | Same |
| Model badge | `--text-tertiary`, `rgba(85,85,106,0.08)` bg | Same | Same | `--accent`, `--accent-dim` bg |

### Execution Shape Cell

| Element | Default | Selected | Upstream (distance 1/2/3) | Downstream (distance 1/2/3) |
|---------|---------|----------|---------------------------|------------------------------|
| Background | `--bg-elevated` | `--accent-dim` | `rgba(139,92,246, 0.14/0.08/0.04)` | `rgba(68,204,119, 0.14/0.08/0.04)` |
| Text color | `--text-tertiary` | `--accent` | `--violet` (1-2) / 60% (3) | `--emerald` (1-2) / 60% (3) |
| Border | `--border` | `--accent` | `rgba(139,92,246, 0.2/0.12/0.08)` | `rgba(68,204,119, 0.2/0.12/0.08)` |

### Task Detail Sections

| Section | Label | Typography | Visual treatment |
|---------|-------|-----------|-----------------|
| What | "WHAT" | `.dp-text` 12px, 1.7 line-height, `--text-secondary` | Structured rendering: bullets, numbered lists, inline `code` |
| Why | "WHY" | Same | Inset card: `--bg-card` bg, `--border-light` border, `border-radius: 6px`, `padding: 10px 12px` |
| Files | "FILES" | `--font-mono` 11px, `--text-secondary` | Stacked pills: `--bg-card` bg, `--border-light` border, `padding: 4px 8px` |
| Done when | "DONE WHEN" | 12px, 1.6 line-height, `--text-secondary` | Checklist: ☐ prefix in `--text-tertiary`, spec reference as tertiary text after label |
| Connected to | "CONNECTED TO" | 11px, `--text-secondary` | Clickable rows: ← arrow + violet ID (upstream) or → arrow + emerald ID (downstream), hover bg `--bg-card-hover` |
| Assumptions | "ASSUMPTIONS" | 11px, 1.5 line-height, `--amber` | Flag icon ⚑ prefix |

Section labels: `--font-mono`, 9px, 500 weight, `--text-tertiary`, uppercase, `letter-spacing: 0.04em`, `margin-bottom: 8px`

## Interaction State Table

| Component | Rest | Hover | Focus | Active | Disabled |
|-----------|------|-------|-------|--------|----------|
| Task row | transparent bg | `--bg-card` bg | Not focusable | Selected state | N/A |
| Shape cell | `--bg-elevated`, `--border` | `rgba(255,255,255,0.12)` border | Not focusable | Selected state | N/A |
| Dep row | transparent bg | `--bg-card-hover` bg | Not focusable | Navigates to task | N/A |
| Verify button | `--text-secondary`, `--bg-elevated`, `--border` | `--accent-glow` border, `--text` | Ring | N/A | `--text-tertiary` (verifying) |
| Approve button | `--bg` text, `--accent` bg | 0.9 opacity | Ring | N/A | N/A |
| ← Editor button | `--text-secondary`, `--bg-elevated` | Same | Ring | Navigates back | N/A |
| + Add task | `--text-tertiary` | `--text-secondary` | N/A | Creates task | Hidden when approved |

## Data Binding

| Element | Source | Format | Constraints |
|---------|--------|--------|-------------|
| Feature name | `featureName` prop | Mono text | Verbatim |
| Intent | `contextPackage.intent` | Sans prose | Max 2 lines before truncation |
| Stats: tasks | `tasks.length` | Integer | Always shown |
| Stats: files | `Set(tasks.flatMap(t.filesTouched)).size` | Integer | Deduplicated |
| Stats: depth | `phases.length` | Integer | Computed from DAG |
| Stats: parallel | `phases[0].tasks.length` | Integer | Root phase count |
| Shape rows | `computePhases(tasks)` | Phase groups | Width proportional to `phase.tasks.length / maxTasks` |
| Shape cell color | `computeDepDistances(selectedId)` | BFS distance | upstream: violet, downstream: emerald, fading by distance |
| Task row: title | `task.title` | Sans text | `text-overflow: ellipsis` |
| Task row: file | `task.filesTouched[0]` filename only | Mono pill | `+N` overflow if >1 file |
| Task row: model | `task.agentModel` | Mono uppercase badge | "opus" gets accent treatment |
| Task row: deps | `task.dependsOn` + downstream computed | Mono text | ← upstream, → downstream |
| Detail: description | `task.description` | Structured text | Bullets, numbered lists, inline code |
| Detail: rationale | `task.rationale` | Sans prose in inset card | Null = section hidden |
| Detail: files | `task.filesTouched` | Mono pills, full paths | Stacked vertically |
| Detail: criteria | `task.acceptanceCriteria` | Checklist lines | ☐ prefix, split on `\n` |
| Detail: connected | upstream + downstream tasks | Clickable rows | Click navigates |
| Detail: assumptions | `task.assumptions` | Amber flagged text | ⚑ prefix, array |

## Interactions & Motion

### Interactions

| Trigger | Target | Response |
|---------|--------|----------|
| Click task row | TaskBoard | Selected task changes; detail panel updates; execution shape recolors |
| Click shape cell | TaskBoard | Same as clicking the corresponding task row |
| Click dep row in detail | TaskBoard | Navigates to that task (selects it) |
| Click "Verify" | Backend | Runs decomposition gate; warnings appear in header + bottom bar |
| Click "Approve Plan" | Backend | Writes task files; plan becomes read-only; bottom bar shows "Approved" |
| Click "← Editor" | CeremonyLayout | Returns to editor view; task board unmounts |
| Click "+ Add task" | TaskBoard | New empty task added to that phase; selected and editable in detail panel |

### Motion

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| row-select | 120ms | ease | background-color, border-color | Task row selection |
| shape-recolor | 150ms | ease | background, color, border-color | Execution shape dependency coloring |
| detail-transition | 0ms | instant | content swap | Detail panel content change (no animation, instant swap) |
| hover-bg | 120ms | ease | background-color | Task row and dep row hover |

**Reduced motion:** All transitions become instant. No functional impact since all transitions are cosmetic (color/background changes).

## Responsive Behavior

| Breakpoint | Layout | Notes |
|------------|--------|-------|
| ≥1280px | Full split: left (420-860px) + right (360-640px) | Both panels visible |
| 1024-1279px | Left narrows, right stays min 360px | Task titles may truncate more |
| 768-1023px | Detail panel becomes a bottom drawer | Task list takes full width; clicking a task opens drawer from bottom |
| <768px | Single column, detail replaces list | Click task → detail view; back button returns to list |

## Accessibility

### Keyboard Navigation

| Component | Keys | Behavior |
|-----------|------|----------|
| Task rows | `Tab` to first row, `↑`/`↓` between rows | Arrow keys navigate within a phase; `Tab` moves to next phase |
| Task row | `Enter` / `Space` | Selects the task |
| Shape cells | `Tab` focus, `Enter` to select | Focus order follows phase order |
| Dep rows | `Tab` within detail panel, `Enter` | Navigates to linked task |
| Verify button | `Enter` / `Space` | Triggers verification |
| Approve button | `Enter` / `Space` | Triggers approval (consider confirmation dialog) |
| ← Editor | `Enter` / `Space` or `Escape` | Returns to editor |

### ARIA

| Component | Role | ARIA |
|-----------|------|------|
| Task list | `list` | `aria-label="Task plan"` |
| Task row | `listitem` | `aria-selected`, `aria-label="Task {id}: {title}"` |
| Phase group | `group` | `aria-label="{phase label}, {count} tasks"` |
| Detail panel | `complementary` | `aria-label="Task detail"`, `aria-live="polite"` |
| Shape cell | `button` | `aria-label="Task {id}", aria-pressed` |
| Bottom bar | `toolbar` | `aria-label="Plan actions"` |
| Gate warnings | `status` | `aria-live="polite"` |

### Contrast

- All text meets WCAG AA (4.5:1 body, 3:1 large/bold)
- Dependency coloring (violet/emerald on dark bg) must be verified at each opacity level
- Shape cells at distance-3 opacity (0.04 bg) rely on border contrast, not fill contrast
- Interactive elements have visible focus indicators via 2px accent ring

## Content Constraints

| Element | Max | Overflow |
|---------|-----|----------|
| Feature name | 50 chars (enforced by feature name regex) | N/A |
| Intent | 2 lines at 600px max-width | Truncate with ellipsis |
| Task title (row) | Available width | `text-overflow: ellipsis` |
| Task title (detail) | Unconstrained | Wraps |
| Description | Unconstrained | Panel scrolls |
| Rationale | Unconstrained | Wraps within inset card |
| File path | Unconstrained | Wraps within pill |
| Acceptance criteria line | Unconstrained | Wraps |
| Assumption | Unconstrained | Wraps |

## Verification Criteria

**TB1:** Given a decomposition with 14 tasks, the plan view shows all 14 in phase groups. No horizontal scrolling. T1 selected by default with detail visible.

**TB2:** Execution shape width is proportional. A phase with 4 tasks is visibly wider than a phase with 1 task. Shape canvas is max 360px wide, centered.

**TB3:** Selecting T4 colors T1/T2/T3 in violet and T5/T6/T13/T14 in emerald. T7/T8/T9/T10/T11 remain neutral gray.

**TB4:** Detail panel shows all 6 sections with correct labels and typography. Rationale appears in inset card. Assumptions appear in amber.

**TB7:** Editing a task title in the detail panel persists the change. The task row title updates to match.

**TB10:** Verify action runs the gate. Warnings appear below the stats and in the bottom bar.

**TB11:** Approve locks the plan. Task rows lose hover states. Add task buttons disappear. Bottom bar shows "Approved" with lock icon.
