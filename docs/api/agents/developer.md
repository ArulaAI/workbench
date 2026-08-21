---
title: Developer
description: The Developer agent implements a single task on an isolated git worktree branch.
---

## Mission

The Developer is a skilled software engineer responsible for implementing a single, well-defined task within a larger project. It works on a dedicated git branch in an isolated worktree, follows the project's conventions from `CLAUDE.md`, and runs quality gates iteratively as it builds.

When uncertain about a requirement, the Developer reports a blocked status rather than fabricating a solution. The system has a recovery path for blocked tasks through the [Supervisor](/docs/api/agents/supervisor/).

## Invocation

| Property | Value |
|----------|-------|
| Command | `speed run` |
| Assembly function | `assemble_developer` |
| Model tier | `support_model` (Sonnet), escalatable to `planning_model` via `--escalate` |
| Trigger | Automatic for each pending task during `speed run` |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Task JSON | `.speed/features/<feature>/tasks/<id>.json` | Task description, acceptance criteria, files_touched, dependencies |
| Layer 2 context | Context pipeline | Full source for touched files, 1-hop callers/callees, 2-hop skeletons |
| Upstream decisions | Prior completed tasks | Outputs from dependency tasks |
| Spec references | Injected per `spec_references` field | Exact spec sections relevant to this task |
| Cross-cutting concerns | Plan output | Constraints applying across 3+ tasks |
| CLAUDE.md | Project root | Project conventions, patterns, architecture |
| Quality gate commands | Developer context | Pre-built gate commands with correct paths and IDs |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Code changes | Worktree branch | Committed changes implementing the task |
| Completion summary | Agent stdout (JSON) | Files created/modified, decisions made, tests added, concerns |
| Blocked report | Agent stdout (JSON) | If uncertain: what is unclear, what was attempted, options considered |

## Process

1. **Read CLAUDE.md.** Project conventions are binding. Every pattern, naming convention, and architectural decision applies.

2. **Explore the codebase.** Before writing code, understand project structure, existing patterns, dependencies, and how similar features are implemented.

3. **Implement incrementally.** Start with core data structures/interfaces, build main logic, add error handling, write tests. Commit after each logical step.

4. **Run gates iteratively.** Run `speed gates --fast` (syntax + lint + typecheck) after each group of files. Run `speed gates --full` before declaring done. Fix any failures before continuing.

5. **Write tests.** Every new function or module gets corresponding tests matching the project's established testing patterns.

6. **Handle errors.** Implement beyond the happy path: edge cases, invalid inputs, failure scenarios.

7. **Report completion or blocked status.** Output a structured JSON summary either way.

## How It Works

Each Developer agent runs on an isolated git worktree branch. The orchestrator (`cmd_run`) spawns multiple Developer agents in parallel, bounded by `max_parallel`. The per-task pipeline has five phases.

```
speed run (per task)
    │
    ├─ 1. Check readiness
    │      └─ Dependencies done? Branch exists? Not already running?
    ├─ 2. Build Layer 2 context
    │      ├─ Tier 0: Full source for files_touched
    │      ├─ Tier 1: Full source for 1-hop callers/callees
    │      ├─ Tier 2: Skeletons for 2-hop neighbors
    │      ├─ Task context: upstream decisions, downstream expectations
    │      └─ Spec context: relevant spec sections + alignment status
    ├─ 3. Assemble developer prompt
    ├─ 4. Spawn agent in worktree (background)
    └─ 5. Monitor + harvest
           ├─ Poll for completion
           ├─ Parse output JSON
           └─ Route: done → review, blocked → supervisor, fail → debugger
```

### Phase 1: Readiness check

`cmd_run` (`lib/cmd/run.sh:239+`) iterates pending tasks in dependency order. A task is ready when all `depends_on` tasks are "done" and no other agent is running for it. The orchestrator creates or reuses a worktree branch (`speed/task-<id>`).

### Phase 2: Layer 2 context

`context_build_layer2_task` builds a per-task context package using the CSG:

| Tier | Content | Budget share |
|------|---------|-------------|
| Tier 0 (files_touched) | Full file contents for every declared file | ~40% |
| Tier 1 (1-hop) | Full source for direct callers, callees, importers, type references | ~30% |
| Tier 2 (2-hop skeleton) | Function/class signatures only for second-degree neighbors | ~15% |
| Task context | Upstream task decisions/concerns, downstream expectations, shared-scope warnings | ~10% |
| Spec context | Relevant spec sections matched by `spec_references`, codebase alignment status | ~5% |

### Phase 3: Prompt assembly

`assemble_developer` (`lib/context/assembly.py:637-848`) builds an 80k-token-budget prompt:

- Task identity with rationale
- Acceptance criteria as a checklist
- Assumptions to verify (inferred during planning)
- Cross-cutting constraints
- Pre-loaded code (Tiers 0, 1, 2)
- Context from completed dependency tasks
- Downstream awareness (what depends on this task's output)
- Shared-scope warnings (bridge symbols modified by other tasks)
- Spec requirements with alignment status
- Git branch name, quality gate commands, working directory

If Layer 2 assembly fails, lines 776-807 fall back to a basic inline prompt with just the task description, criteria, and gate commands.

### Phase 4: Spawn

`claude_spawn_bg` (`lib/cmd/run.sh:814-821`) launches the agent as a background process in the worktree directory with the developer agent definition, full tool access, and the task-specific model (default: Sonnet, `opus` if the Architect flagged the task).

### Phase 5: Monitor and harvest

The polling loop checks running agents for completion. On finish, the output is parsed as JSON. Routing:

| Output status | Next step |
|---------------|-----------|
| `done` | Mark task "done", proceed to review |
| `blocked` | Mark task "blocked", invoke [Supervisor](/docs/api/agents/supervisor/) |
| Agent error / gate failure | Mark task "failed", invoke [Debugger](/docs/api/agents/debugger/) |

## Worked Example

Task 2 of the `library-app` feature: "Create Borrowing model and rules service." Depends on Task 1 (Book model), which has already completed.

### What the Layer 2 context provides

**Tier 0 (files_touched):** Full contents of `src/backend/models/borrow.py` (empty, to be created) and `src/backend/services/borrow.py` (empty, to be created).

**Tier 1 (1-hop):** Full contents of `src/backend/models/book.py` (created by Task 1) and `src/backend/models/user.py` (existing).

**Tier 2 (2-hop skeleton):**
```python
# src/backend/schema/book.py — skeleton
class BookType(SQLAlchemyObjectType):
    class Meta: ...
class BookQuery(graphene.ObjectType):
    books: ...
    book: ...
```

**Upstream decisions from Task 1:**
```
Files modified: src/backend/models/book.py, src/backend/migrations/0002_books.py
Decisions: Used SQLAlchemy declarative base, added status enum (available, borrowed, reserved)
```

**Downstream awareness:**
```
Task 3 (Add book availability GraphQL query): expects borrow_book() function and Borrow model
```

**Shared-scope warning:**
```
Book.status is also modified by Task 3. Impact: blast_radius=4, stability=core.
Coordinate on enum values — do not change the status field contract.
```

### What the agent produces

```json
{
  "status": "done",
  "task_id": "2",
  "files_created": ["src/backend/models/borrow.py", "src/backend/services/borrow.py"],
  "files_modified": ["src/backend/models/__init__.py"],
  "decisions": [
    "Borrowing limit set to 5 based on spec 'Users can borrow up to 5 books simultaneously'",
    "Used 14-day default borrowing period (spec says 'standard lending period')"
  ],
  "tests_added": ["tests/test_borrow.py"],
  "concerns": ["Spec says 'reservation expiry' but doesn't specify duration — used 24 hours"]
}
```

### What the orchestrator shows

```
  Spawned agent for task 2: Create Borrowing model and rules service
    PID: 48721 | model: sonnet | branch: speed/task-2

  ... (agent works for several minutes) ...

  ✓ Task 2: done
    Files: borrow.py, borrow_service.py, test_borrow.py
    Gates: ✓ syntax ✓ lint ✓ typecheck ✓ tests
```

## Constraints

- Stay in scope. Only implement what the task describes.
- Only touch declared files from `files_touched`. Exception: cascading import/export fixes from creating or deleting a declared file are permitted, but must be documented.
- Do not break existing code. Ensure backward compatibility when building on existing work.
- Follow existing patterns. No new libraries, frameworks, or architectural patterns unless the task specifically requires them.
- No over-engineering. Three lines of repeated code is better than a premature abstraction.
- Do not skip quality gate checks. The output log is audited for gate invocations.

## Special Modes

### Defect Reproduce Mode

Injected at runtime for moderate-complexity defects during the reproduce stage. The Developer's only job is to write a failing test that demonstrates the defect, without fixing the bug.

The test must fail with the current code. If it passes, the defect has not been reproduced. The Developer reads `test_coverage_detail` from the triage output to find existing test patterns and follows them exactly.

Test strategy by defect type:
- **logic**: pytest (backend) or vitest + testing-library (frontend)
- **visual**: vitest + testing-library for state assertions, Playwright for layout verification
- **data**: pytest with test database fixtures reproducing the triggering data conditions

### Defect Fix Mode

Injected at runtime during the fix stage. The Developer makes the smallest modification that resolves the defect.

For moderate defects, the existing failing test defines "done." For trivial defects, a regression test is written alongside the fix if no test exists for the affected code path.

Explicit prohibitions during defect fixes: no variable renaming, no formatting changes, no comment additions to unrelated code, no dependency upgrades, no "while I'm here" changes.

## Output Schema

Completion:
```json
{
  "status": "done",
  "task_id": "3",
  "files_created": ["src/services/borrow.py"],
  "files_modified": ["src/models/book.py"],
  "decisions": ["Assumed borrowing limit of 5 based on typical library systems"],
  "tests_added": ["tests/test_borrow.py"],
  "concerns": ["Not 100% sure reservation expiry is handled correctly"]
}
```

Blocked:
```json
{
  "status": "blocked",
  "task_id": "3",
  "uncertain_about": "Description of what cannot be resolved",
  "options": ["Option A", "Option B"],
  "attempted": "What was tried before getting stuck",
  "files_completed": ["files successfully created before the block"],
  "blocked_reason": "ambiguous_spec | missing_dependency | contradictory_requirements | impossible_as_specified"
}
```
