---
title: Coherence Checker
description: The Coherence Checker verifies that independently built branches compose correctly before integration.
---

## Mission

The Coherence Checker verifies that all completed tasks form a consistent, working whole before integration. Each task was developed on an isolated branch by an independent [Developer](/docs/api/agents/developer/) agent. Code that is correct in isolation may fail at its boundaries: mismatched function signatures, inconsistent field names, duplicate implementations. The Coherence Checker finds these seams.

## Invocation

| Property | Value |
|----------|-------|
| Command | `speed integrate` (pre-merge phase) |
| Assembly function | `assemble_coherence` |
| Model tier | `support_model` (Sonnet) |
| Trigger | Automatic before branch merging begins |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Cross-task diffs | All completed worktree branches | The code from every task branch |
| Product specification | `specs/product/<feature>.md` | Original requirements for reference |
| Contract | `.speed/features/<feature>/contract.json` | The [Architect](/docs/api/agents/architect/)'s data model contract |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Coherence report | Stdout (raw JSON, no markdown wrapping) | Per-category findings, contract gaps, critical issues list |

The output is raw JSON with no markdown or prose. The consuming script parses it with `jq`.

## Process

The Coherence Checker reads all diffs before judging any single one. It needs the full picture to spot mismatches. Six check categories:

1. **Interface compatibility.** When Task A defines a function/class/type and Task B uses it: do signatures match (argument names, types, counts)? Do class/model field names match? Do import paths match?

2. **Schema consistency.** When multiple tasks touch the data model: do model definitions agree on field names and types? Do migrations match models? Do GraphQL types match underlying models? Are enum values consistent?

3. **Naming consistency.** Are the same concepts called the same thing everywhere? Is `user_id` in one place and `owner_id` in another for the same concept? Are naming conventions (snake_case vs camelCase) consistent?

4. **Duplicate implementation.** Did two tasks implement the same thing independently? Same utility function, same model defined twice, same query/mutation implemented by different tasks.

5. **Missing connections.** A model was created but never registered in `__init__.py`. A GraphQL type was created but never added to the schema. A route was created but never registered with the app. A migration was created but its supporting model does not exist.

6. **Contract satisfaction.** Does the combined code satisfy the data model contract? Every table exists in a migration, every FK exists, every core query is achievable, the contract's core question is answerable.

## How It Works

The coherence pipeline runs in eight phases. The first four gather and pre-compute context; Phase 5 sends it to the agent; Phases 6 through 8 parse and act on the result.

```
speed coherence
    │
    ├─ 1. Gather completed tasks + git diffs
    ├─ 2. Load product spec + contract.json
    ├─ 3. Build cross-task analysis via CSG
    │      ├─ Domain overlap (shared clusters)
    │      ├─ Interface boundaries (cross-task edges)
    │      └─ High-impact modifications (bridge symbols)
    ├─ 4. Assemble structured prompt
    ├─ 5. Send to Coherence Checker agent (read-only)
    ├─ 6. Parse JSON from agent output
    ├─ 7. Delta vs. previous run
    └─ 8. Pass/fail gate
           ├─ fail → suggest speed retry
           └─ pass → suggest speed integrate
```

### Phase 1: Gather diffs

`cmd_coherence` (`lib/cmd/coherence.sh:85-116`) lists all tasks with status "done." For each, it reads the task JSON, extracts the branch name, and runs `git_diff_branch`. All diffs are concatenated with per-task headers.

### Phase 2: Load spec and contract

Lines 118-130 read the product spec via `_get_spec_path()` and the architect's `contract.json`. These define what the combined code should achieve.

### Phase 3: Cross-task risk analysis

`context_build_cross_task` (`context_bridge.sh:159`) bridges to `build_cross_task_analysis` (`lib/context/cross_task.py:23`), which pre-computes three risk signals from the Code Semantic Graph (CSG):

| Signal | What it detects | Risk classification |
|--------|----------------|---------------------|
| Domain overlap | CSG clusters touched by 2+ tasks | `high` if bridge symbols present, `medium` if >5 coordination edges, `low` otherwise |
| Interface boundaries | Symbols defined by one task and consumed by another (via `calls`, `instantiates`, `references_type`, `accesses` edges) | Listed per task pair |
| High-impact modifications | Bridge symbols or symbols with blast_radius >= 10 being modified | Includes downstream consumer list |

Without a CSG, the system degrades to file-based overlap detection only.

### Phase 4: Assemble the prompt

`assemble_coherence` (`lib/context/assembly.py:1012`) builds a structured markdown prompt from five sections:

1. Cross-task risk analysis from Phase 3
2. All task diffs (budget-capped at ~50% of 100k character total, split evenly across tasks)
3. Product specification
4. Data model contract as JSON
5. Focus instructions (interface mismatches, schema consistency, contract compliance, duplicates)

If the Python pipeline fails, `coherence.sh:156-169` falls back to raw concatenation of diffs + spec + contract.

### Phase 5: Agent execution

`claude_run` sends the assembled prompt to the Coherence Checker with read-only tool access and the planning-tier model. The agent reads all diffs before judging any single one, then returns a single JSON object.

### Phase 6: Parse the result

`parse_agent_json` (`lib/provider.sh:49`) extracts JSON using three strategies in order: direct `jq` parse, code-fence extraction, then Python brace-scanning for JSON embedded in prose. The parsed report is saved to `coherence.log`.

### Phase 7: Delta comparison

If a previous report exists, `_print_coherence_delta` (`coherence.sh:4-73`) classifies each `critical_issues` entry as fixed, remaining, or new by exact string comparison against the prior run.

### Phase 8: Pass/fail gate

`status: "fail"` logs the critical issue count and suggests `speed retry --task-id ID --context "..."`. `status: "pass"` clears the previous report and prompts `speed integrate`.

## Worked Example

Three tasks for a `user-profiles` feature, all completed on isolated branches:

| Task | Branch | What it does |
|------|--------|-------------|
| 1 | `feat/user-model` | Creates `User` model: fields `id`, `name`, `email` |
| 2 | `feat/user-graphql` | Creates GraphQL `UserType`: fields `id`, `display_name`, `email` |
| 3 | `feat/user-api` | Creates REST endpoint importing `User` from `models/user.py` |

Task 2 uses `display_name` where Task 1 defined `name`. Each task passes its own review in isolation.

### What the cross-task analysis produces

**Domain overlap:** Tasks 1 and 2 both touch the "user-domain" CSG cluster.

```json
{
  "cluster": "user-domain",
  "tasks_touching": ["1", "2"],
  "shared_symbols": ["User", "UserType"],
  "coordination_edges": 3,
  "risk": "medium"
}
```

**Interface boundary:** Task 3 imports `User` from Task 1's module.

```json
{
  "from_task": "1",
  "to_task": "3",
  "interface_symbols": [{"symbol": "User"}]
}
```

### What the agent returns

```json
{
  "status": "fail",
  "summary": "Field name mismatch between User model and GraphQL UserType will cause runtime errors in the resolver layer.",
  "interface_mismatches": [
    {
      "task_a": "1",
      "task_b": "2",
      "location_a": "models/user.py:5",
      "location_b": "schema/types.py:8",
      "description": "Task 1 defines User.name, Task 2 expects User.display_name in GraphQL resolver",
      "severity": "critical"
    }
  ],
  "schema_inconsistencies": [],
  "duplicates": [],
  "missing_connections": [],
  "contract_gaps": [
    {
      "contract_item": "users table with name column",
      "status": "partial",
      "notes": "Model uses 'name', GraphQL uses 'display_name'. One must change."
    }
  ],
  "critical_issues": [
    "Field name mismatch: User.name (Task 1) vs User.display_name (Task 2)"
  ],
  "recommendations": [
    "Align on a single field name. If display_name is desired, update Task 1's model and migration."
  ]
}
```

### What the user sees

```
✗ Coherence check FAILED — tasks have compatibility issues
  1 critical issue(s) found

  Fix issues before integrating. Options:
    1. speed retry --task-id 2 --context "Rename display_name to name to match User model"
    2. Review the coherence report and fix manually
```

On a subsequent run after fixing Task 2:

```
  Delta (vs. previous run):
  Critical issues: 1 → 0
    ✓ Fixed: Field name mismatch: User.name vs User.display_name

  1 issue(s) fixed, 0 remaining, 0 new
  All previous issues resolved!

✓ Coherence check PASSED — tasks are compatible
  Next: speed integrate
```

## Constraints

- Read-only access. Cannot modify files.
- A `pass` means zero critical issues. Any critical issue produces a `fail`.
- Be specific about locations: file paths, line numbers, function/class names.
- If uncertain whether an issue is real, note the confidence level. Do not assert problems without confidence.

## Output Schema

The entire response is a single JSON object. No markdown, no prose, no code fences.

```json
{
  "status": "pass | fail",
  "summary": "One-paragraph assessment",
  "interface_mismatches": [
    {
      "task_a": "ID", "task_b": "ID",
      "location_a": "file:line", "location_b": "file:line",
      "description": "What doesn't match",
      "severity": "critical | major | minor"
    }
  ],
  "schema_inconsistencies": [
    { "description": "What's inconsistent", "locations": ["file:line"], "severity": "critical | major | minor" }
  ],
  "duplicates": [
    { "description": "What's duplicated", "locations": ["file:line"] }
  ],
  "missing_connections": [
    { "description": "What's not connected", "expected_in": "file or module", "severity": "critical | major" }
  ],
  "contract_gaps": [
    { "contract_item": "What the contract specifies", "status": "satisfied | missing | partial", "notes": "Details" }
  ],
  "critical_issues": ["Issues that MUST be fixed before integration"],
  "recommendations": ["Suggested fixes"]
}
```
