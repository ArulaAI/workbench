---
title: Integrator
description: The Integrator merges validated branches in dependency order with regression testing.
---

## Mission

The Integrator merges completed task branches into the main repository in the correct dependency order, resolving merge conflicts intelligently while preserving the intent of each branch's changes. Unlike every other SPEED agent, the Integrator is deterministic and does not use an LLM. It is orchestrated entirely by the `speed integrate` CLI command.

## Invocation

| Property | Value |
|----------|-------|
| Command | `speed integrate` |
| Model tier | Deterministic (no LLM) |
| Trigger | Manual (runs after all tasks pass review and coherence check) |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Validated branches | Completed worktree branches | All task branches that passed review and coherence checks |
| Dependency order | Task DAG | Merge sequence derived from task `depends_on` edges |
| Contract | `.speed/features/<feature>/contract.json` | Data model contract for post-merge verification |
| Regression test config | Project test configuration | Test suite to run after each merge |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Merged code | Feature branch | All task branches merged in dependency order |
| Integration report | Stdout (JSON) | Merged branches, conflicts resolved, failed merges, test results |

## Process

1. **Merge in dependency order.** Tasks that other tasks depend on get merged first, following the order derived from the task DAG.

2. **For each branch:** check out main, attempt merge with `--no-ff` to preserve branch history. If the merge succeeds cleanly, continue. If conflicts arise, resolve them by reading both versions, understanding the intent, and merging intelligently. Irreconcilable conflicts are reported for human review.

3. **Run tests after each merge.** If a test suite is configured, run it after every merge to catch regressions early rather than at the end.

4. **Contract verification.** After all merges, verify that the implemented code satisfies the [Architect](/docs/api/agents/architect/)'s data model contract.

5. **Guardian gate.** Post-integration, the [Product Guardian](/docs/api/agents/product-guardian/) performs a final vision check on the integrated result.

## Conflict Resolution Strategy

| Conflict Type | Resolution |
|---------------|------------|
| Non-overlapping changes | Accept both (standard merge) |
| Import/dependency conflicts | Combine both sets of imports |
| Structural conflicts (same function modified differently) | Analyze both changes, create a version incorporating both intents |
| Irreconcilable conflicts | Stop and report to human with full context |

## How It Works

Despite the doc description stating "deterministic (no LLM)," the implementation actually uses `claude_run` with full tool access for conflict resolution. The merge ordering is deterministic; the conflict resolution is LLM-assisted.

```
speed integrate [--skip-tests]
    │
    ├─ 1. Acquire exclusive lock
    ├─ 2. Compute merge order
    │      └─ Topological sort of task DAG
    │      └─ Filter to "done" tasks with unmerged branches
    ├─ 3. Send to Integrator agent (Sonnet, full tools)
    │      └─ Branch list in dependency order
    │      └─ Agent performs merges with --no-ff
    ├─ 4. Post-merge verification
    │      ├─ Regression tests (unless --skip-tests)
    │      ├─ CSG rebuild for accurate contract check
    │      ├─ Contract verification
    │      │      └─ Failure → invoke Supervisor
    │      └─ Guardian vision check
    │             └─ Rejection → warn, log report
    └─ 5. Release lock
```

### Phase 1: Lock acquisition

`cmd_integrate` (`lib/cmd/integrate.sh:42-243`) acquires an exclusive integration lock via `speed_acquire_lock "integrate"`. Only one integration can run at a time.

### Phase 2: Merge order

Lines 69-102 compute the merge sequence. `task_topo_sort` produces a topological ordering of all tasks. The pipeline filters to "done" tasks, skips branches already merged (checked via `git merge-base --is-ancestor`), and builds the branch list.

### Phase 3: Agent-assisted merge

Lines 120-158 send the branch list to the Integrator agent via `claude_run` with full tool access (`AGENT_TOOLS_FULL`). The agent works through each branch: checkout main, merge with `--no-ff`, resolve conflicts if any arise. The agent has access to Bash, Read, Write, Edit, Glob, and Grep for intelligent conflict resolution. Results are saved to `integration.log`.

### Phase 4: Post-merge verification

Four verification steps run after all branches are merged:

| Step | Implementation | On failure |
|------|---------------|------------|
| Regression tests | `regression_run` (line 167) | Log error, suggest rollback |
| CSG rebuild | `context_build_layer1 "true"` (line 182) | Warn, contract check uses stale index |
| Contract check | `contract_check` (line 186) | Invoke Supervisor for `contract` trigger |
| Guardian vision check | `_run_guardian "post-integration"` (lines 200-240) | Log rejection, show report path |

The contract check verifies that every entity in the Architect's contract exists in the merged codebase: tables have corresponding model files, functions exist as symbols in the CSG, files exist at declared paths.

### Defect mode

`speed integrate --defect <name>` bypasses the feature requirement and merges a single defect fix branch via `_cmd_integrate_defect` (line 57).

## Worked Example

Three tasks for `library-app` have passed review. Branches: `speed/task-1` (Book model), `speed/task-2` (Borrowing service), `speed/task-3` (GraphQL queries).

### What the integrator agent receives

```
## Integration Task

Merge the following branches into main, in the order listed (dependency order):

- speed/task-1
- speed/task-2
- speed/task-3

### Working Directory
/Users/dev/library-app

### Instructions
1. For each branch, checkout main, then merge the branch with --no-ff
2. If there are merge conflicts, resolve them intelligently
3. After each merge, verify the code still works
4. Report results as JSON
```

### What the agent does

The agent merges `speed/task-1` cleanly. Merging `speed/task-2` produces a conflict in `src/backend/models/__init__.py` (both branches added imports). The agent reads both versions, combines the import lists, and writes the resolution. `speed/task-3` merges cleanly.

### What the agent returns

```json
{
  "merged_branches": ["speed/task-1", "speed/task-2", "speed/task-3"],
  "conflicts_resolved": [
    {
      "branch": "speed/task-2",
      "files": ["src/backend/models/__init__.py"],
      "resolution": "Combined import lists from both branches: added Book from task-1 and Borrow from task-2"
    }
  ],
  "failed_merges": [],
  "test_results": "not_configured"
}
```

### What the user sees

```
═══ Integrating Completed Work ═══
  Merging 3 branches in dependency order...
  Sending to Integrator agent...

  ... (agent merges branches) ...

  ✓ Integration log saved to .speed/logs/integration.log

═══ Post-Integration Verification ═══
  Rebuilding code symbol graph...
  ✓ Contract check passed — schema matches plan

═══ Post-Integration Vision Check ═══
  Running Product Guardian (post-integration)...
  ✓ Guardian: ALIGNED — Integrated result serves core mission
```

## Constraints

- Never force-push or rewrite history.
- Always use `--no-ff` merges to preserve branch context.
- When in doubt about a conflict resolution, err on the side of not merging and reporting the issue.
- Keep the main branch always in a working state.

## Output Schema

```json
{
  "merged_branches": ["branch-1", "branch-2"],
  "conflicts_resolved": [
    {
      "branch": "branch-name",
      "files": ["file.py"],
      "resolution": "Description of how it was resolved"
    }
  ],
  "failed_merges": [
    { "branch": "branch-name", "reason": "Why it couldn't be merged" }
  ],
  "test_results": "pass | fail | not_configured"
}
```
