---
title: Supervisor
description: The Supervisor agent decides recovery strategy after failures and detects cross-task patterns.
---

## Mission

The Supervisor is SPEED's decision-maker for failure recovery. It analyzes the current state of the system, diagnoses failures, and determines the recovery strategy. Its most critical function is pattern detection: recognizing when multiple tasks fail for the same underlying reason and prescribing a single root-cause fix instead of retrying each task individually.

## Invocation

| Property | Value |
|----------|-------|
| Command | Automatic (invoked by orchestrator) |
| Model tier | `planning_model` (Opus) |
| Trigger | Task failure, blocked status, repeated failure patterns, coherence/contract check failure |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Current SPEED state | Orchestrator | Task statuses, timings, costs |
| Failed/blocked task details | Agent output | Error logs, [Debugger](/docs/api/agents/debugger/) analysis |
| Overall progress metrics | Orchestrator | Completion rates, failure counts |
| Failure history | `.speed/` state | Previous failures and their resolutions |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Recovery decision | Stdout (JSON) | Diagnosis, pattern analysis, recovery actions, halt recommendation |

## Process

The Supervisor applies different decision frameworks depending on the failure type:

### Failed Tasks

| Failure Type | Decision | Action |
|--------------|----------|--------|
| Transient (network error, timeout, rate limit) | Retry with same configuration | `retry` |
| Capability (task too complex for model) | Escalate model tier | `retry_escalated` (sonnet to opus) |
| Specification (task description unclear or impossible) | Re-plan the task | `replan` |
| Dependency (upstream task output was wrong) | Fix upstream first | `retry_dependency` |
| Systemic (multiple tasks failing similarly) | Escalate to human | `escalate` |

### Blocked Tasks

Blocked status means the Developer was honest instead of fabricating. High-priority input, not an error.

| Block Type | Action |
|------------|--------|
| Ambiguous spec | `escalate` to human with the specific question (highest priority) |
| Missing dependency | `reorder` task priority, or `replan` if the dependency is absent from the plan |
| Contradictory requirements | `replan` with contradiction highlighted, or `escalate` if the product spec itself is contradictory |
| Impossible as specified | Review the claim; if valid, `replan`; if uncertain, `escalate` |

### Pattern Failures

When the same failure repeats across multiple tasks:

- 2+ tasks fail with import errors for the same module: missing foundational task
- 2+ tasks fail with schema mismatches: migration is wrong or missing
- 2+ tasks fail with "file not found": scaffolding task was skipped or failed

Pattern failures get diagnosed as a single root cause with a single fix (`fix_root_cause`), not retried individually.

### Coherence Failures

Interface mismatch: retry the task that needs to change. Schema inconsistency: identify the authoritative definition, retry deviating tasks. Missing connections: retry the task that should have made the connection. Plan-level coherence failure: `replan` affected tasks.

### Contract Failures

Post-integration contract check failures (missing table, missing FK, core query not traversable) are traced to the responsible task for retry, or trigger `replan` if no task covers the gap.

## How It Works

The Supervisor is invoked by the orchestrator through `_invoke_supervisor` (`lib/shared.sh:153+`). It runs in two modes: async (background, for non-blocking diagnosis during `speed run`) and sync (inline, for decisions that must complete before the pipeline continues).

```
_invoke_supervisor(task_id, trigger_type, mode)
    │
    ├─ 1. Gather SPEED state
    │      ├─ Task counts by status (total, done, running, pending, failed, blocked)
    │      ├─ Triggering task details (status, error, title)
    │      └─ Debugger analysis (if available)
    ├─ 2. Load failure history
    │      └─ .speed/features/<feature>/failure_history.jsonl
    ├─ 3. Build supervisor message
    │      ├─ Trigger type (blocked, pattern, coherence, contract)
    │      ├─ SPEED state summary
    │      ├─ Task details + debugger log
    │      └─ Full failure history
    ├─ 4. Send to Supervisor agent
    │      ├─ async → _spawn_support_agent (background)
    │      └─ sync  → claude_run (inline, returns output)
    └─ 5. Orchestrator applies recovery actions
```

### Phase 1: State gathering

Lines 161-168 query task counts by status using `task_count_by_status`. Lines 178-187 load the triggering task's details and, if present, the Debugger's JSON analysis from `${LOGS_DIR}/debugger-${task_id}.json`.

### Phase 2: Failure history

Lines 172-175 load the cumulative failure history from `failure_history.jsonl`. Each line is a JSON record of a previous failure with its resolution. Pattern detection depends on this history: the Supervisor compares current failures against past ones to identify systemic issues.

### Phase 3: Prompt assembly

Lines 189-200 build a prompt with four sections: trigger type label, SPEED state summary, triggering task details (with debugger analysis if available), and the full failure history.

### Phase 4: Agent execution

Two execution modes (lines 202-211):

| Mode | Function | Use case |
|------|----------|----------|
| `async` | `_spawn_support_agent` | Non-blocking during parallel task execution |
| `sync` | `claude_run` | Contract failures, coherence failures (pipeline must wait for decision) |

Both use Sonnet and read-only tools. The Supervisor never modifies files directly.

### Phase 5: Action application

The orchestrator (`_handle_support_completion`) parses the Supervisor's JSON output and applies each action:

| Action | What the orchestrator does |
|--------|---------------------------|
| `retry` | Reset task to pending, re-enqueue with same config |
| `retry_escalated` | Reset task, upgrade model (sonnet → opus) |
| `replan` | Mark affected tasks for re-planning by the Architect |
| `retry_dependency` | Reorder dependency, retry the blocked task after upstream completes |
| `fix_root_cause` | Apply a single fix, then retry all affected tasks |
| `escalate` | Log the `human_question`, halt the task, notify the user |
| `skip` | Mark task as skipped, unblock dependents if safe |

### Trigger types

| Trigger | When | Typical pattern |
|---------|------|-----------------|
| `blocked` | Developer reports `status: "blocked"` | Ambiguous spec, missing dependency |
| `pattern` | 2+ tasks fail with similar errors | Missing foundational task, wrong migration |
| `coherence` | Coherence check finds interface mismatches | Signature mismatch across branches |
| `contract` | Post-integration contract check fails | Missing table, missing FK |

## Worked Example

During `speed run`, Tasks 3 and 5 both fail with `import_error` for `src/backend/models/reservation.py`. The Debugger analyzed both and identified `upstream_dependency: "4"` in each case.

### What the supervisor receives

**SPEED State:**
```
Total tasks: 8
Done: 2
Running: 0
Pending: 1
Failed: 2
Blocked: 0
```

**Failure History:**
```jsonl
{"task_id": "3", "classification": "import_error", "root_cause": "reservation.py not found", "upstream": "4"}
{"task_id": "5", "classification": "import_error", "root_cause": "reservation.py not found", "upstream": "4"}
```

### What the agent returns

```json
{
  "diagnosis": "Tasks 3 and 5 both fail importing from reservation.py, which is created by Task 4. Task 4 is still pending because its dependency (Task 2) was running. This is a scheduling issue, not a code issue.",
  "pattern_detected": {
    "description": "Multiple tasks import a module created by a not-yet-completed task",
    "affected_tasks": ["3", "5"],
    "root_cause": "Task 4 (Create Reservation model) has not run yet. Tasks 3 and 5 should depend on Task 4 but don't."
  },
  "actions": [
    {
      "task_id": "4",
      "action": "reorder",
      "reason": "Task 4 must complete before Tasks 3 and 5 can succeed"
    },
    {
      "task_id": "3",
      "action": "retry_dependency",
      "reason": "Will succeed once Task 4 provides reservation.py",
      "additional_context": "No code changes needed — just needs the import to resolve"
    },
    {
      "task_id": "5",
      "action": "retry_dependency",
      "reason": "Same root cause as Task 3"
    }
  ],
  "recommendations": [
    "Consider adding depends_on edges from Tasks 3 and 5 to Task 4 to prevent this pattern in future runs"
  ],
  "should_halt": false,
  "halt_reason": null
}
```

### What happens next

The orchestrator reorders Task 4 to run immediately. Once Task 4 completes, Tasks 3 and 5 are retried. Both succeed because `reservation.py` now exists.

## Constraints

- Patterns over individuals. If the same failure appears twice, stop fixing individual tasks and find the root cause.
- Blocked is not failed. Treat it as high-priority input.
- Escalate early. Retrying a wrong approach three times costs more than asking once.
- Be conservative with replans. Replanning discards existing work. Only replan when the plan itself is wrong.
- If more than 30% of tasks fail, recommend halting and escalating to human.
- Consider cost implications of retries and model escalations.

## Output Schema

```json
{
  "diagnosis": "Summary of the current situation",
  "pattern_detected": {
    "description": "What pattern is observed",
    "affected_tasks": ["task IDs"],
    "root_cause": "The single underlying issue"
  },
  "actions": [
    {
      "task_id": "3",
      "action": "retry | retry_escalated | replan | reorder | fix_root_cause | skip | escalate",
      "reason": "Why this action",
      "new_model": "opus",
      "additional_context": "Extra info for the retried agent",
      "human_question": "If escalating, what specific question to ask"
    }
  ],
  "recommendations": ["Human-readable suggestions"],
  "should_halt": false,
  "halt_reason": null
}
```
