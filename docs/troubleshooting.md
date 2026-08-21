---
title: How to Troubleshoot Failed Tasks
description: Systematic recipes for identifying and resolving agent failures using SPEED's failure classification system.
sidebar:
  order: 6
---

When a task fails, SPEED classifies it into one of six subclasses across two categories: **pipeline failures** (SPEED's responsibility to fix) and **complexity failures** (the spec or task needs refinement). The classification system uses `budget.json`, grounding gate results, and agent output patterns. Rules are evaluated in priority order; the first match wins.

## Step 1: Check Status

```bash
speed status --verbose
```

The status output includes a **Failure Classification** section showing the pipeline-vs-complexity breakdown with per-subclass counts. If the majority are pipeline failures, the context or decomposition needs adjustment.

## Step 2: Identify the Subclass

### Pipeline Failures

| Subclass | Trigger | Recovery |
|----------|---------|----------|
| `context_cut` | `budget.json` has cuts AND the agent references files that were cut | Increase the token budget in `speed.toml`, or split the task to reduce context demand. |
| `exploration_death` | Agent spent 80%+ turns on exploration with <10% code output | Improve spec detail or add file hints to the task. The agent couldn't orient itself despite receiving context. |
| `decomposition_error` | Undeclared files outnumber declared files (3+ undeclared) | The Architect's `files_touched` list was incomplete. Rerun `speed plan` with a more detailed spec. |
| `spec_gap` | Agent reports `ambiguous_spec` or `missing_dependency` patterns in its output | Fill the gap in the spec (missing signature, unclear requirement), then retry. |

### Complexity Failures

| Subclass | Trigger | Recovery |
|----------|---------|----------|
| `exceeded_capacity` | Task timed out (with or without model escalation) | Split the task into smaller pieces, or escalate with `speed retry --escalate`. |
| `implementation_error` | Quality gate failures (syntax, lint, test, typecheck) | Use `speed retry --task-id ID --context "guidance"` to provide specific fix instructions. |

## Step 3: Inspect the Budget

If the classification is `context_cut`, inspect the budget to see exactly what was removed:

```bash
cat .speed/features/<feature>/context/task-<id>/budget.json
```

The `cuts_made` array shows each cut with the file path, original tier (`full` or `skeleton`), the tier it was downgraded to, tokens saved, and the reason.

## Step 4: Retry or Decompose

**For pipeline failures**: Fix the root cause (better spec, larger budget, more precise `files_touched`) and rerun.

**For complexity failures**: Provide human guidance or escalate the model:

```bash
# Retry with specific instructions
speed retry --task-id 4 --context "Use the StructuredLogger from lib/logging.py, not print statements."

# Retry with a more capable model
speed retry --task-id 4 --escalate
```

## Scope Enforcement

SPEED tracks whether developer agents stay within their declared `files_touched` boundary:

| Undeclared Files | Behavior |
|-----------------|----------|
| 1-2 | Warning logged. Agent continues. |
| 3+ | Classified as `decomposition_error`. Task fails. |

Override with the `SCOPE_STRICT` environment variable to enforce strict mode (any undeclared file = failure) or disable enforcement entirely.

## Recovery Recipes

### "Contract Mismatch" during integration
The implementation diverged from the `contract` section in the tech spec. Update the spec to match reality OR use `speed retry` to instruct the agent to follow the contract.

### "Merge Conflict during Integration"
Parallel tasks modified the same lines in a shared file. Check the CSG's blast radius data in `speed review` output to understand the overlap, resolve the conflict, then run `speed integrate` to resume.

### Supervisor halts the run
The failure rate exceeded 30% across all tasks. Run `speed status` to see the Supervisor's diagnosis, detected patterns, root cause, and recommendations before deciding whether to retry individual tasks or re-plan.
