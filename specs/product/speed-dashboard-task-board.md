---
status: draft
feature: speed-dashboard-task-board
---

# Dashboard: Task Board

> Depends on: Define Ceremony (shipped), Architect Decomposition (shipped), Mission Control (shipped)

## Problem

The Architect decomposes an RFC into a task DAG. Right now that DAG appears as a read-only slide-out panel at the bottom of the editor. The author sees the tasks, closes the panel, and then runs `speed plan` from the CLI to create actual task files. The dashboard has no role in what happens between decomposition and execution.

Three gaps:

**Plan review has no surface.** The author can't edit task titles, adjust acceptance criteria, remove a task that doesn't make sense, or add one the Architect missed. The decomposition is take-it-or-leave-it. If the Architect over-scopes a task (touching 7 files when 3 would suffice), the author's only option is to re-run decomposition with a different prompt or model.

**Plan approval is invisible.** There's no explicit moment where the author says "this plan is correct, proceed." The commit action on the spec editor commits the spec content. It doesn't commit the plan. The plan exists as a JSON file on disk with no approval state, no audit trail.

**Execution tracking lives on a different page.** Mission Control shows a ReactFlow DAG of running tasks. It has no connection to the plan the author reviewed. The author can't see "this is the plan I approved, and here's how it's progressing." Plan and execution are two unrelated views of the same data.

The task board unifies these: one surface where the author reviews the plan, edits it, approves it, and later watches it execute.

## Users

### RFC Author (Engineering)
Writes the technical RFC, triggers decomposition, reviews the task plan. Needs to verify the Architect's output makes sense: are the tasks correctly scoped? Do the dependencies make sense? Are acceptance criteria testable? Are file assignments accurate? After review, approves the plan, which becomes the input to `speed run`.

### PRD Author (Product)
Writes the product spec and decomposes it into child RFCs via the RFC Decomposition table. Does not interact with task-level decomposition directly. Sees the task board only when checking overall feature progress: how many tasks are done, what's blocked, what failed.

### Design Author
Writes the design spec. Like the PRD author, doesn't interact with task decomposition. May check the task board to see if design-related tasks (frontend components, CSS tokens) are progressing.

### Reviewer
Reviews committed specs before ratification. After the RFC author approves a plan, the reviewer can see the plan alongside the spec to verify the implementation strategy matches the spec intent.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| TB1 | As an RFC author, I want to see the decomposition as a plan document with phase grouping, task rows, and a detail panel | Given an RFC has been decomposed into 14 tasks, when I click "Tasks" on the RFC tab and then "Open Plan", then I see a split layout: task list on the left grouped by execution phase, task detail on the right with the first task selected | Must |
| TB2 | As an RFC author, I want to understand the execution shape at a glance | Given the plan has 6 phases with max 4 parallel tasks, when I view the plan header, then I see an execution shape visualization where row width represents parallelism and row count represents depth | Must |
| TB3 | As an RFC author, I want to see which tasks are upstream and downstream of any selected task | Given I select T4 in the plan, when I look at the execution shape, then T4's upstream tasks appear in violet and downstream tasks appear in emerald, with opacity fading by distance | Must |
| TB4 | As an RFC author, I want to read the full task detail including rationale and assumptions | Given I select a task, when I view the detail panel, then I see: description (What), rationale (Why), files, acceptance criteria (Done when), dependency links (Connected to), and assumptions flagged in amber | Must |
| TB5 | As an RFC author, I want to navigate between tasks by clicking dependency links | Given T4's detail panel shows "← T1, T2, T3" as upstream deps, when I click T1, then T1 becomes selected and its detail loads in the right panel | Must |
| TB6 | As an RFC author, I want to see the source spec requirement for each acceptance criterion | Given a task's acceptance criteria reference PRD story S1, when I view "Done when", then the source spec section appears as tertiary text next to the criteria group | Should |
| TB7 | As an RFC author, I want to edit task titles, descriptions, and acceptance criteria | Given the plan is not yet approved, when I click a task's title in the detail panel, then it becomes editable inline; same for description and criteria | Must |
| TB8 | As an RFC author, I want to delete a task from the plan | Given the plan has a task T7 that I think is unnecessary, when I delete it, then it's removed and downstream dependency references update | Must |
| TB9 | As an RFC author, I want to add a task to a specific phase | Given Phase 1 has 3 tasks, when I click "+ Add task" below Phase 1, then a new empty task appears in the list and the detail panel shows a blank form | Should |
| TB10 | As an RFC author, I want to verify the plan passes quality gates before approving | Given I'm reviewing the plan, when I click "Verify", then the decomposition gate runs and any warnings appear (file ownership conflicts, oversized tasks, cross-cluster coordination issues) | Must |
| TB11 | As an RFC author, I want to approve the plan, locking it for execution | Given the plan has no blocking gate failures and I'm satisfied with the tasks, when I click "Approve Plan", then the plan state transitions to approved, task files are written to .speed/, and the plan becomes read-only | Must |
| TB12 | As an RFC author, I want to see plan execution progress on the same surface | Given I approved the plan and `speed run` is executing, when I open the task board, then I see task status (pending/running/done/failed), elapsed time, agent model, cost, and errors | Should |
| TB13 | As a reviewer, I want to see the approved plan alongside the spec during ratification | Given the RFC is committed with an approved plan, when I open the review page, then I can view the task plan as evidence of implementation strategy | Should |
| TB14 | As any user, I want to return to the spec editor from the task board | Given I'm viewing the task board, when I click "← Editor", then I return to the RFC editor with my cursor position preserved | Must |

## User Flows

### Plan review and approval

1. RFC author finishes editing the RFC spec
2. Clicks "Decompose" on the RFC tab (or "Tasks" if decomposition already exists)
3. Slide-out panel appears at the bottom showing decomposition progress stages
4. Decomposition completes; panel shows task summary with "Open Plan →" button
5. Author clicks "Open Plan →"; full task board replaces the editor
6. Author scans the execution shape to understand parallelism and depth
7. Author reads through task rows, clicking each to review the detail panel
8. Author edits a task title that's unclear, adjusts acceptance criteria
9. Author deletes a task that duplicates another
10. Author clicks "Verify" in the bottom bar; gate warnings appear if any
11. Author resolves warnings by editing tasks or accepting them
12. Author clicks "Approve Plan"; plan locks, task files written to `.speed/`
13. Author clicks "← Editor" to return to the spec

### Execution tracking (future, after speed run)

1. Author or reviewer opens the task board for a feature with an approved plan
2. Board shows the same task list but with status indicators: pending, running, done, failed
3. Running tasks show elapsed time and agent model
4. Done tasks show completion time and cost
5. Failed tasks show error message and a retry button
6. Task status updates live via WebSocket subscription

### Reviewer checking the plan

1. Reviewer opens the review page for a committed RFC
2. Sees the spec content alongside a "View Plan" link
3. Clicks to see the approved task plan (read-only)
4. Verifies the plan covers the spec requirements (via spec_references on each task)

## Scope

### In Scope

- Plan mode: view, edit, verify, approve
- Execution shape visualization with dependency coloring
- Task detail panel with What/Why/Files/Done when/Connected to/Assumptions
- Task editing: title, description, acceptance criteria (in plan mode only)
- Task add/delete (in plan mode only)
- Verify action (runs decomposition gate)
- Approve action (writes task files, locks plan)
- Navigation: editor ↔ task board
- Bottom bar with gate status and action buttons
- "Done when" ↔ spec_references traceability

### Out of Scope (and why)

- **Execute mode UI.** The plan mode is the priority. Execute mode reuses the same layout but with status lanes instead of phases. Designed for extensibility but built separately. Mission Control serves as the interim execution view.
- **Drag-and-drop reordering.** The phase grouping is derived from dependencies. Reordering tasks means rewiring the dependency graph, which is complex and error-prone. Editing dependencies via the detail panel is sufficient for v1.
- **Real-time collaborative editing.** One author owns the RFC and its plan. Contributors suggest changes via the suggestion sidebar, not by editing the plan directly.
- **Undo/redo.** Task edits are saved immediately. Undo requires a history stack that adds complexity without proportional value for v1.
- **Per-task model reassignment.** The Architect assigns models (opus/sonnet) based on task complexity. Overriding this is an advanced feature for later.

## Success Criteria

| Metric | Target |
|--------|--------|
| Time from decomposition to plan approval | Under 10 minutes for a 10-15 task plan |
| Plan approval rate | >80% of decompositions approved without re-running (edits are sufficient) |
| Task edit rate | >30% of plans have at least one task edited before approval |
| Gate warning resolution | 100% of blocking warnings resolved before approval |

## Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| Architect decomposition (`ceremony_editor.py`) | Prerequisite | Produces the task DAG that the board displays |
| Decomposition gate (`lib/decomposition_gate.py`) | Prerequisite | Powers the Verify action |
| `speed plan` task file format | Contract | Approved plan writes task files in the same format `speed plan` produces |
| Mission Control (`/mission-control`) | Parallel | Existing execution view; task board's execute mode replaces it for ceremony-originated features |
| Per-spec ownership RFC | Adjacent | When implemented, the plan is owned by the RFC spec owner, not the ceremony initiator |

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Editing tasks creates inconsistencies in the dependency graph | Medium | Verify action catches file ownership conflicts and missing dependencies. Deleting a task warns if downstream tasks depend on it. |
| Large plans (20+ tasks) overwhelm the vertical layout | Low | The execution shape stays compact (max 360px). Task rows are single-line. 20 tasks = ~20 rows, scrollable. The detail panel handles depth. |
| Approved plan diverges from spec after further spec edits | Medium | Approving the plan snapshots the spec content hash. If the spec changes after approval, a warning appears and the author can re-decompose. |

## Open Questions

1. **Should the plan approval require verification first?** Currently Verify and Approve are independent actions. Requiring Verify before Approve ensures gate checks run, but adds friction for plans that obviously pass.

2. **Should deleted tasks be soft-deleted (hidden but recoverable) or hard-deleted?** Soft delete is safer but adds UI complexity (an "N hidden tasks" indicator, a way to restore). Hard delete is simpler and matches the no-undo scope decision.

3. **Should the execute mode live on the same URL as the plan mode, or a separate route?** Same URL with a mode toggle is simpler for the user (one bookmark). Separate route is cleaner architecturally. The prototype uses the same component with a `mode` prop.
