---
status: draft
feature: speed-dashboard-task-board
---

# RFC: Dashboard Task Board

> See [product spec](../product/speed-dashboard-task-board.md) for product context.
> See [design spec](../design/speed-dashboard-task-board.md) for visual specification.
> Depends on: Architect decomposition (`ceremony_editor.py`), decomposition gate (`lib/decomposition_gate.py`), `speed plan` task file format.

## Basic Example

```tsx
// CeremonyLayout renders TaskBoard when showTaskBoard is true
if (showTaskBoard && decompositionResult) {
  return (
    <TaskBoard
      tasks={decompositionResult.tasks}
      featureName={featureName}
      intent={contextPackage.intent}
      gate={decompositionResult.gate}
      onVerify={() => runGateCheck()}
      onApprove={() => approvePlan()}
    />
  );
}

// User edits a task title in the detail panel
const handleTaskUpdate = (taskId: string, changes: Partial<ArchitectTask>) => {
  setTasks(prev => prev.map(t => t.id === taskId ? { ...t, ...changes } : t));
  persistDraft(featureName, updatedTasks); // save to disk
};

// User approves the plan — writes task files
const approvePlan = async () => {
  await executeApprovePlan({ featureName, tasks: editedTasks });
  // Backend writes .speed/shared/features/{feature}/tasks/*.json
  setApproved(true);
};
```

## Interface Contract

### Consumes

| Artifact | Location | Usage |
|----------|----------|-------|
| `DecompositionResult` | `ceremony_editor.py` → `decomposition.json` | Source data for the task board; tasks, gate, stats |
| `ArchitectTask` fields | `ceremony_decomposition_types.py` | id, title, description, acceptanceCriteria, dependsOn, agentModel, filesTouched, rationale, assumptions, specReferences |
| Decomposition gate | `lib/decomposition_gate.py` | `check_decomposition()` powers the Verify action |
| Context package | `ceremony_types.py` | `intent` field displayed in plan header |
| `speed plan` task format | `.speed/shared/features/{feature}/tasks/{id}.json` | Approval writes task files in this format |

### Produces

| Artifact | Consumed By | Notes |
|----------|-------------|-------|
| Edited task plan | Approve action → task files | Modified tasks persisted as `decomposition-draft.json` during editing, then as task files on approval |
| Plan approval state | Commit flow | Approval state stored alongside the decomposition; commit gate can check if plan was approved |
| Task files | `speed run` | Written on approval in the same format `speed plan` produces |

## Data Model

### Plan State

The decomposition result gains a mutable draft and an approval state:

```
.speed/shared/features/{feature}/
  decomposition.json          # Original Architect output (immutable)
  decomposition-draft.json    # Edited version (mutable, created on first edit)
  plan-approval.json          # Approval record (created on approve)
  tasks/                      # Task files (written on approve)
    1.json
    2.json
    ...
```

### decomposition-draft.json

Same schema as `decomposition.json` but reflects the author's edits. Created by copying `decomposition.json` on the first edit. All subsequent edits modify this file. The original `decomposition.json` is preserved for diffing.

### plan-approval.json

```python
@strawberry.type
class PlanApproval:
    feature_name: str
    approved_by: str           # actor name
    approved_by_email: str     # actor email
    approved_at: str           # ISO 8601 UTC
    task_count: int
    spec_content_hash: str     # SHA-256 of spec content at approval time
    decomposition_hash: str    # SHA-256 of approved task plan
    gate_result: Optional[GateResult]
```

### Task file format (matching speed plan)

Each task file in `tasks/{id}.json`:

```json
{
  "id": "1",
  "title": "Define recall data types and Strawberry GraphQL types",
  "description": "...",
  "acceptance_criteria": "...",
  "depends_on": [],
  "agent_model": "sonnet",
  "files_touched": ["dashboard/backend/resolvers/recall_types.py"],
  "status": "pending",
  "spec_references": [...],
  "rationale": "...",
  "assumptions": [...]
}
```

The `status` field is set to `"pending"` on creation. `speed run` transitions it through `running` → `done` / `failed`.

### Stale plan detection

When the spec content changes after plan approval:

```python
def is_plan_stale(project_root: Path, feature_name: str) -> bool:
    approval = load_plan_approval(project_root, feature_name)
    if not approval:
        return False
    current_hash = hash_spec_content(project_root, feature_name)
    return current_hash != approval.spec_content_hash
```

The frontend queries this and shows a warning banner if stale.

## API Surface

### New GraphQL Operations

| Type | Name | Signature | Description |
|------|------|-----------|-------------|
| Query | `planDraft` | `(featureName: String!) → DecompositionResult` | Load the edited plan draft (falls back to original decomposition if no draft) |
| Query | `planApproval` | `(featureName: String!) → PlanApproval` | Load approval state |
| Query | `isPlanStale` | `(featureName: String!) → Boolean!` | Check if spec changed after approval |
| Mutation | `updatePlanTask` | `(featureName: String!, taskId: String!, title: String, description: String, acceptanceCriteria: String) → ArchitectTask` | Edit a task in the draft |
| Mutation | `deletePlanTask` | `(featureName: String!, taskId: String!) → Boolean!` | Remove a task from the draft |
| Mutation | `addPlanTask` | `(featureName: String!, afterPhase: Int!, title: String!) → ArchitectTask` | Add a new task |
| Mutation | `verifyPlan` | `(featureName: String!) → GateResult` | Run decomposition gate on current draft |
| Mutation | `approvePlan` | `(featureName: String!) → PlanApproval` | Lock the plan, write task files |

### Modified Operations

| Operation | Change |
|-----------|--------|
| `commitSpec` | Check plan approval state. If RFC has a decomposition but no approval, warn. If approved, include approval reference in commit record. |
| `decomposeDraft` | If a draft exists, warn that re-decomposing will overwrite edits. |

### Resolver Module

New file: `dashboard/backend/resolvers/ceremony_plan.py`

```python
def get_plan_draft(project_root, feature_name) -> DecompositionResult | None
def get_plan_approval(project_root, feature_name) -> PlanApproval | None
def is_plan_stale(project_root, feature_name) -> bool

def update_plan_task(project_root, feature_name, task_id, **changes) -> ArchitectTask
def delete_plan_task(project_root, feature_name, task_id) -> bool
def add_plan_task(project_root, feature_name, after_phase, title) -> ArchitectTask
def verify_plan(project_root, feature_name) -> GateResult
def approve_plan(project_root, feature_name) -> PlanApproval
```

## State Machine

### Plan lifecycle

```
decomposition_complete
        │
        ▼
    [draft]  ←── edit/add/delete tasks
        │
        ├── verify → gate warnings shown
        │
        ▼
    [approved]  ── writes task files to .speed/
        │
        ├── spec changes → [stale] warning
        │                      │
        │                      └── re-decompose → back to [draft]
        │
        ▼
    [executing]  ── speed run picks up task files
```

States are implicit (derived from file existence):
- Draft: `decomposition-draft.json` exists (or `decomposition.json` if no edits)
- Approved: `plan-approval.json` exists
- Stale: `plan-approval.json` exists AND spec content hash doesn't match
- Executing: `tasks/*.json` exist with non-pending statuses

### Task edit rules

| Current state | Edit allowed | Add allowed | Delete allowed | Re-decompose allowed |
|---------------|-------------|-------------|----------------|---------------------|
| Draft | Yes | Yes | Yes | Yes (overwrites draft) |
| Approved | No | No | No | Yes (clears approval, creates new draft) |
| Stale | No | No | No | Yes (expected action) |
| Executing | No | No | No | No |

## Component Architecture

### Frontend components (all in `dashboard/frontend/components/ceremony/`)

| Component | File | Props | State |
|-----------|------|-------|-------|
| `TaskBoard` | `TaskBoard.tsx` | `tasks, featureName, intent, gate, onVerify, onApprove, approved, verifying` | `selectedId` |
| `PlanHeader` | Inline in TaskBoard | Stats, gate warnings | None (derived) |
| `ExecutionShape` | Inline in TaskBoard | `phases, tasks, selectedId, onSelect` | None |
| `TaskRow` | Inline in TaskBoard | `task, tasks, selected, onSelect` | None |
| `TaskDetail` | Inline in TaskBoard | `task, tasks, onSelect, onUpdate, onDelete` | Edit state per field |
| `BottomBar` | Inline in TaskBoard | `gate, approved, onVerify, onApprove, verifying` | None |

### GraphQL queries (in `dashboard/frontend/lib/graphql/queries/ceremony-plan.ts`)

```typescript
export const PLAN_DRAFT_QUERY = gql`...`;
export const PLAN_APPROVAL_QUERY = gql`...`;
export const IS_PLAN_STALE_QUERY = gql`...`;
export const UPDATE_PLAN_TASK_MUTATION = gql`...`;
export const DELETE_PLAN_TASK_MUTATION = gql`...`;
export const ADD_PLAN_TASK_MUTATION = gql`...`;
export const VERIFY_PLAN_MUTATION = gql`...`;
export const APPROVE_PLAN_MUTATION = gql`...`;
```

## Integration with speed plan / speed run

### Task file compatibility

The `approvePlan` resolver writes task files in the exact format `speed plan` produces:

```python
def _write_task_files(project_root: Path, feature_name: str, tasks: list[dict]):
    paths = get_paths(project_root)
    task_dir = paths.feature_shared(feature_name) / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    for task in tasks:
        task_data = {
            **task,
            "status": "pending",
            "created_at": _now_iso(),
        }
        _write_json(task_dir / f"{task['id']}.json", task_data)
```

### speed plan skip detection

`speed plan` should detect existing task files and skip the Architect:

```bash
# In lib/cmd/plan.sh, before calling the Architect:
task_dir="$SHARED_DIR/features/$FEATURE/tasks"
if [[ -d "$task_dir" ]] && [[ $(ls "$task_dir"/*.json 2>/dev/null | wc -l) -gt 0 ]]; then
    log_info "Task files already exist (written by dashboard). Skipping Architect."
    # Proceed directly to validation/execution
    return 0
fi
```

### Dependency graph validation

On approval, the resolver validates the task DAG before writing:
- No circular dependencies
- All `depends_on` references point to existing task IDs
- No orphaned tasks (every task reachable from a root or reaching a leaf)
- File ownership: no two parallel tasks modify the same file without a dependency edge

These are the same checks `lib/decomposition_gate.py` performs, run one final time before writing.

## Testing

### Unit tests (`dashboard/backend/tests/test_ceremony_plan.py`)

| Test | Coverage |
|------|----------|
| `test_get_plan_draft_returns_original_when_no_edits` | Falls back to decomposition.json |
| `test_get_plan_draft_returns_edited_version` | Returns decomposition-draft.json when it exists |
| `test_update_task_creates_draft_on_first_edit` | Copies decomposition.json to decomposition-draft.json |
| `test_update_task_modifies_title` | Title change persisted |
| `test_update_task_modifies_criteria` | Acceptance criteria change persisted |
| `test_delete_task_removes_from_draft` | Task removed; downstream deps updated |
| `test_delete_task_warns_on_downstream_deps` | Returns warning if other tasks depend on deleted task |
| `test_add_task_inserts_at_phase` | New task with correct depends_on for that phase depth |
| `test_verify_runs_gate` | Gate result returned with warnings |
| `test_approve_writes_task_files` | Task files exist in tasks/ directory |
| `test_approve_creates_approval_record` | plan-approval.json written with correct fields |
| `test_approve_rejects_when_gate_fails` | Blocking gate failures prevent approval |
| `test_is_plan_stale_detects_spec_change` | Returns true after spec content changes |
| `test_redecompose_clears_approval` | Re-decomposing removes plan-approval.json |
| `test_task_file_format_matches_speed_plan` | Written files are parseable by speed run |

### Playwright tests (`dashboard/frontend/e2e/task-board.spec.ts`)

| Test | Coverage |
|------|----------|
| `test_plan_loads_with_default_selection` | T1 selected, detail panel visible |
| `test_click_task_updates_detail_and_shape` | Selection changes, dep coloring updates |
| `test_click_dep_row_navigates` | Clicking upstream/downstream link selects that task |
| `test_back_button_returns_to_editor` | ← Editor returns to CeremonyLayout editor view |
| `test_editor_scroll_not_broken` | SpecEditor .cm-scroller has scrollHeight > clientHeight |

## File Impact

### New files

| File | Purpose |
|------|---------|
| `dashboard/backend/resolvers/ceremony_plan.py` | Plan CRUD + verify + approve resolvers |
| `dashboard/backend/tests/test_ceremony_plan.py` | Unit tests |
| `dashboard/frontend/lib/graphql/queries/ceremony-plan.ts` | GraphQL queries/mutations/types |
| `dashboard/frontend/e2e/task-board.spec.ts` | Playwright integration tests |

### Modified files

| File | Change |
|------|--------|
| `dashboard/backend/schema.py` | Register plan queries + mutations |
| `dashboard/backend/resolvers/ceremony_editor.py` | Warn on re-decompose if draft exists |
| `dashboard/backend/resolvers/ceremony_commitment.py` | Check plan approval state in commit flow |
| `dashboard/frontend/components/ceremony/TaskBoard.tsx` | Wire mutations for edit/delete/add/verify/approve |
| `dashboard/frontend/components/ceremony/CeremonyLayout.tsx` | Already wired; may need plan draft query |
| `lib/cmd/plan.sh` | Skip Architect when task files exist |

## Key Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Edit creates a draft copy, original preserved | Copy-on-write: `decomposition-draft.json` | Edit in place | Preserves the original Architect output for diffing and re-decomposition comparison |
| Approval writes task files immediately | Synchronous write on approve | Write on commit, or write on `speed run` | Task files are the contract between the dashboard and the CLI. Writing on approve makes them visible to `speed plan --status` and other CLI tools immediately. |
| No undo/redo | Edits are immediate and persistent | History stack with undo | Adds significant complexity for a plan review flow that typically takes one pass. Re-decompose is the escape hatch. |
| Gate check is advisory, not blocking | Verify shows warnings; Approve is always available | Block Approve on gate failures | Some warnings are acceptable (e.g., "consider splitting" is advice, not a blocker). The author decides. |
| speed plan skips Architect when task files exist | Directory check in plan.sh | Flag file, API check | Simple, filesystem-based. No new IPC between dashboard and CLI. |

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Draft diverges from decomposition.json after many edits, making re-decompose destructive | Medium | Show diff between original and draft before re-decompose. Confirm dialog. |
| Task file format changes in speed plan break dashboard-written files | Low | Both read the same `templates/architect-output.json` schema. Schema is the contract. |
| Author approves plan, edits spec, forgets to re-decompose | Medium | Stale plan detection. Warning banner on task board and commit bar. |
| Concurrent edits (two browser tabs) corrupt the draft | Low | Single-actor ownership per RFC. No concurrent editing in scope. |

## Open Questions

1. **Should `speed run` refuse to execute if task files were written by the dashboard but the plan approval is missing?** Currently `speed run` only checks that task files exist. Adding an approval check creates a hard dependency between the dashboard and the CLI.

2. **Should the draft auto-save or save on explicit action?** Auto-save (debounced, like the spec editor) is simpler UX. Explicit save gives the author a clear "I'm done editing" moment. The spec editor uses auto-save; consistency suggests the same for the plan.

3. **Should re-decompose offer to keep manual edits?** If the author edited 3 tasks and re-decomposes, those edits are lost. A merge strategy (keep edits for tasks whose IDs still exist in the new decomposition) is possible but complex. For v1, re-decompose replaces everything with a confirmation dialog.
