---
title: Debugger
description: The Debugger agent performs root cause analysis on failed tasks.
---

## Mission

The Debugger diagnoses why a task failed. It produces a root cause analysis with a specific fix instruction so the [Developer](/docs/api/agents/developer/) does not retry blindly. The diagnosis includes the exact file, line, and code that caused the failure, along with a targeted fix description.

## Invocation

| Property | Value |
|----------|-------|
| Command | Automatic (invoked by orchestrator on task failure) |
| Assembly function | `assemble_debugger` |
| Model tier | `support_model` (Sonnet) |
| Trigger | Automatic when a task fails quality gates or produces an agent error |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Task description | Task JSON | What the task was supposed to do, acceptance criteria |
| Error output | Agent logs | Test failures, lint errors, gate failures, agent output |
| Source code | Worktree branch diff | The code that was written |
| Quality gate results | Gate runner | Which gates passed, which failed, with output |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Diagnosis | Stdout (JSON) | Failure classification, root cause, fix instructions, confidence level |

## Process

1. **Classify the failure.** Determine which of eight categories the failure falls into (see table below).

2. **Find the root cause.** Trace the error to the specific line of code or missing code that caused it. For test failures: compare expected vs actual output and locate the divergence. For import errors: check whether the referenced module exists and whether another task should create it. For schema mismatches: identify where model and migration disagree.

3. **Determine the fix.** Be specific: "line 42 of test_user.py expects `user.name` but the model uses `user.display_name`." If the fix requires changes outside the task's scope, say so explicitly and identify the upstream dependency.

## Failure Categories

| Category | Description |
|----------|-------------|
| `syntax_error` | Code does not parse |
| `import_error` | References a module, package, or file that does not exist |
| `type_error` | Wrong types passed to functions, missing fields, schema mismatch |
| `test_failure` | Code runs but tests fail (wrong logic, wrong test, or wrong expectation) |
| `lint_failure` | Code works but violates style rules |
| `schema_mismatch` | Model does not match migration, or API type does not match DB model |
| `missing_dependency` | Code uses a package not installed, or relies on output from another task |
| `task_spec_error` | The task description itself is wrong or impossible; criteria are contradictory |

## How It Works

The Debugger is invoked automatically by the orchestrator when a Developer agent fails. It runs as a background support agent via `_spawn_support_agent`.

```
Task failure detected
    │
    ├─ 1. Gather failure evidence
    │      ├─ Task JSON (description, criteria)
    │      ├─ Agent output log (head + tail, capped at AGENT_OUTPUT_TAIL)
    │      └─ Git diff from failed branch
    ├─ 2. Assemble debugger context
    │      ├─ Failure classification (if pre-computed)
    │      ├─ Context budget analysis (cuts that may explain the failure)
    │      ├─ Task description + criteria
    │      ├─ Agent output (~20% budget)
    │      ├─ Git diff (~20% budget)
    │      └─ Relevant code context (~25% budget, 1-hop from Layer 2)
    ├─ 3. Send to Debugger agent (Sonnet, read-only)
    └─ 4. Parse diagnosis → route to Supervisor
```

### Phase 1: Gather evidence

`_invoke_debugger` (`lib/cmd/run.sh:176-237`) loads the task JSON, reads the agent output log (head + tail sampling for large logs to stay within `AGENT_OUTPUT_TAIL` lines), and gets the git diff from the failed branch.

### Phase 2: Context assembly

`assemble_debugger` (`lib/context/assembly.py:1144-1272`) builds a 50k-token-budget prompt with budget-aware sections:

| Section | Budget | Purpose |
|---------|--------|---------|
| Failure classification | — | Pre-computed class/subclass/evidence if available |
| Context budget analysis | — | Whether Layer 2 cut files that may explain the failure |
| Task description + criteria | — | What was supposed to happen |
| Agent output | ~20% (10k) | Error messages, test output, gate results |
| Git diff | ~20% (10k) | The code that was written |
| Relevant code (1-hop) | ~25% (12.5k) | Dependencies that may contain the root cause |

The context budget analysis is unique to the Debugger. If Layer 2 downgraded files from full content to skeleton (or dropped them entirely), the Debugger sees this and can attribute failures to insufficient context rather than task complexity. The prompt explicitly notes: "If the failure involves symbols from these files, the root cause may be insufficient context."

If the Python assembly fails, lines 216-233 fall back to a basic inline prompt with task description, raw agent output, and diff.

### Phase 3: Agent execution

`_spawn_support_agent` launches the Debugger as a background process with Sonnet and read-only tools. The agent classifies the failure into one of eight categories and produces a specific fix with file:line references.

### Phase 4: Route to Supervisor

When the Debugger completes, `_handle_support_completion` parses the diagnosis JSON. The [Supervisor](/docs/api/agents/supervisor/) receives the classification and decides the recovery strategy (retry, escalate, replan).

## Worked Example

Task 2 ("Create Borrowing model and rules service") failed because it imported `ReservationStatus` from `src/backend/models/reservation.py`, which does not exist (Task 4 creates it, but Task 2 does not depend on Task 4).

### What the debugger context includes

**Context budget analysis:**
```
Total budget: 80000 tokens
Code context: 45000/52000 (8 full, 3 skeleton, 1 dropped)

Context was cut — potential pipeline failure:
- src/backend/models/reservation.py: tier_1 → dropped (file does not exist yet)

If the failure involves symbols from these files, the root cause
may be insufficient context, not a task complexity problem.
```

**Agent output (tail):**
```
ModuleNotFoundError: No module named 'src.backend.models.reservation'

  File "src/backend/services/borrow.py", line 4, in <module>
    from src.backend.models.reservation import ReservationStatus
```

### What the agent returns

```json
{
  "failure_classification": "import_error",
  "root_cause": "Task 2 imports ReservationStatus from reservation.py, but that module is created by Task 4. Task 2 does not declare a dependency on Task 4.",
  "root_cause_location": {
    "file": "src/backend/services/borrow.py",
    "line": 4,
    "context": "from src.backend.models.reservation import ReservationStatus"
  },
  "fix": {
    "description": "Add Task 4 to Task 2's depends_on, or inline the ReservationStatus enum in Task 2's scope.",
    "changes": [
      {
        "file": "tasks/2.json",
        "line": null,
        "current": "\"depends_on\": [\"1\"]",
        "should_be": "\"depends_on\": [\"1\", \"4\"]"
      }
    ]
  },
  "out_of_scope": true,
  "out_of_scope_reason": "Fix requires editing the task DAG, not the task code",
  "upstream_dependency": "4",
  "confidence": "high",
  "confidence_reason": "Import error with clear traceback pointing to a module created by another task"
}
```

### What happens next

The Supervisor receives this diagnosis, detects `upstream_dependency: "4"`, and issues a `retry_dependency` action: reorder Task 4 ahead of Task 2, then retry Task 2.

## Constraints

- Read-only access. Cannot modify files.
- Be specific: file names, line numbers, exact text. The Developer needs to know exactly where to look.
- Do not guess when uncertain. Set `confidence: "low"` and explain what further investigation would be needed.
- Check the obvious first. Most failures are import errors, typos, or missing files.
- If the task spec is wrong, classify as `task_spec_error`. The [Supervisor](/docs/api/agents/supervisor/) will trigger a replan.
- If the failure depends on another task, set `upstream_dependency` to that task's ID.

## Output Schema

```json
{
  "failure_classification": "syntax_error | import_error | type_error | test_failure | lint_failure | schema_mismatch | missing_dependency | task_spec_error",
  "root_cause": "Specific explanation of why it failed",
  "root_cause_location": {
    "file": "path/to/file.py",
    "line": 42,
    "context": "The specific code that's wrong"
  },
  "fix": {
    "description": "What needs to change",
    "changes": [
      {
        "file": "path/to/file.py",
        "line": 42,
        "current": "What the code currently says",
        "should_be": "What it should say"
      }
    ]
  },
  "out_of_scope": false,
  "out_of_scope_reason": null,
  "upstream_dependency": null,
  "confidence": "high | medium | low",
  "confidence_reason": "Why you are or aren't sure about this diagnosis"
}
```
