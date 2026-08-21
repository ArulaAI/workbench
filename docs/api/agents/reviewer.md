---
title: Reviewer
description: The Reviewer agent checks task diffs against the original product specification.
---

## Mission

The Reviewer is a senior engineer conducting code review of work completed by a [Developer](/docs/api/agents/developer/) agent. Its primary job is verifying alignment between the code and the product specification, not just the task description. The task's acceptance criteria may be incomplete or a misinterpretation of the spec. The spec is the source of truth.

## Invocation

| Property | Value |
|----------|-------|
| Command | `speed review` (or `speed review --task-id ID`) |
| Assembly function | `assemble_reviewer` |
| Model tier | `support_model` (Sonnet) |
| Trigger | Manual, or automatic after task completion |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Git diff | Worktree branch | The code changes under review |
| Task acceptance criteria | Task JSON | What the task says to do |
| Product specification | `specs/product/<feature>.md` | What the product actually needs (source of truth) |
| Blast radius data | CSG analysis | Downstream impact of changed symbols |
| Spec verification matrix | Plan output | Requirement-to-task traceability |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Review report | Stdout (JSON) | Verdict, spec verification, missing items, out-of-scope code, issues |

## Process

1. **Read the product spec first.** Before looking at the diff, form an independent understanding of what the code should accomplish. Write down expectations in the output.

2. **Check the diff against the spec.** For every identified requirement, check whether the diff satisfies it. Quote specific lines from the product spec for each verification. If code cannot be traced to a spec line, flag it as potentially out of scope.

3. **Check for what is missing.** Identify what the spec requires that the diff does not implement.

4. **Standard code review.** Only after spec verification, review for code quality, convention adherence (CLAUDE.md), security, testing coverage, and performance.

## How It Works

The review pipeline iterates over completed tasks, running one Reviewer agent per task with a post-review Guardian gate.

```
speed review [--task-id ID]
    │
    ├─ 1. Gather tasks to review
    │      └─ All "done" tasks (or specific --task-id)
    │      └─ Skip already-approved tasks
    ├─ 2. Per task:
    │      ├─ a. Get git diff from worktree branch
    │      ├─ b. Load relevant specs (smart loader)
    │      ├─ c. Build Layer 2 context (reviewer stage)
    │      ├─ d. Assemble reviewer prompt
    │      ├─ e. Send to Reviewer agent (Sonnet, read-only)
    │      ├─ f. Parse verdict
    │      │      ├─ approve → mark reviewed
    │      │      └─ request_changes → mark for retry
    │      └─ g. Post-review Guardian gate (on approve)
    │             ├─ aligned → keep approved
    │             ├─ flagged → warn but keep
    │             └─ rejected → override to request_changes
    └─ 3. Collect and print nits from approved tasks
```

### Step 2a: Git diff

`cmd_review` (`lib/cmd/review.sh:82-307`) gets the diff via `git_diff_branch`, comparing the task branch against the main branch. Diffs exceeding `DIFF_HEAD_LINES` are truncated with a note pointing to the full branch.

### Step 2b: Relevant specs

`_load_relevant_specs` does a smart load: the primary product spec is marked as "SOURCE OF TRUTH", related specs are included with their relative path. Not all specs are loaded, only those relevant to the diff.

### Step 2c-d: Context assembly

`context_build_layer2_task` builds Layer 2 for the reviewer stage. `assemble_reviewer` (`lib/context/assembly.py:855-1005`) builds a 60k-token-budget prompt:

| Section | Budget share | Content |
|---------|-------------|---------|
| Task identity + rationale | — | What this task should achieve |
| Acceptance criteria | — | Table format with verify_by methods |
| Criteria verification | — | Automated check results if available |
| Assumptions to verify | — | Planning inferences not in the spec |
| Git diff | ~40% | Truncated to fit budget |
| Impact assessment | — | Bridge symbols, blast radius table from CSG |
| Spec requirements | — | Relevant spec sections with alignment status |
| Cross-cutting constraints | — | Feature-level rules the diff must respect |

### Step 2e-f: Agent execution and verdict

The Reviewer runs with Sonnet and read-only tools. On `approve`, the task status updates to "reviewed." On `request_changes`, `task_request_changes` writes review feedback into the task JSON for the Developer's retry.

### Step 2g: Post-review Guardian gate

For approved tasks (unless `SKIP_GUARDIAN=true`), `_run_guardian "post-review"` (`lib/shared.sh:28-146`) sends the diff + criteria to the [Product Guardian](/docs/api/agents/product-guardian/). A `rejected` verdict overrides the Reviewer's approval, setting the task back to `request_changes` with the Guardian's summary as feedback. Nit-level and minor issues from approved reviews are collected and printed as a batch at the end.

## Worked Example

Task 3 of `library-app`: "Add book availability GraphQL query." The Developer completed it on branch `speed/task-3`.

### What the reviewer prompt includes

**Acceptance criteria table:**

| # | Criterion | Verify By |
|---|-----------|-----------|
| 1 | BookQuery.books returns all books with status field | test |
| 2 | BookQuery.book(id) returns single book with borrowing history | test |
| 3 | availability_check resolver returns true/false based on Book.status | test |

**Impact assessment:**

| Symbol | Blast Radius | Stability | Dependents |
|--------|-------------|-----------|------------|
| `BookType` | 6 | core | 6 |
| `BookQuery` | 4 | stable | 4 |

**Spec requirement:**
> From product § Library Catalog: "Users can search for books and see real-time availability status."

### What the agent returns

```json
{
  "verdict": "approve",
  "spec_verification": [
    {
      "spec_quote": "Users can search for books and see real-time availability status",
      "spec_section": "Library Catalog",
      "satisfied": true,
      "evidence": "schema/book.py:15 — BookQuery.books includes status field via BookType",
      "notes": "Search is basic name matching, not full-text. Acceptable for MVP."
    }
  ],
  "missing_from_spec": [],
  "out_of_scope": [],
  "issues": [
    {
      "severity": "nit",
      "file": "src/backend/schema/book.py",
      "line": 28,
      "message": "availability_check could be a computed field on BookType instead of a separate resolver",
      "suggestion": "Use @hybrid_property on the model for cleaner API"
    }
  ],
  "strengths": ["Good test coverage", "Consistent with existing schema patterns"]
}
```

### What the user sees

```
═══ Code Review ═══
  Reviewing task 3: Add book availability GraphQL query

  ... (agent output) ...

  ✓ Task 3: approved by Reviewer

  Running Product Guardian (post-review)...
  ✓ Guardian: ALIGNED — Implementation serves core mission

  Nits (non-blocking, from approved reviews):
    Task 3: [nit] schema/book.py:28 — availability_check could be a computed field
```

## Constraints

- Read-only access. Cannot modify files.
- The spec is the source of truth. If the task says "implement X" but the spec says "implement Y", the code should implement Y.
- Quote the spec for every verification. If a citation cannot be provided, the requirement may be fabricated or the code may be out of scope.
- Flag over-engineering: unnecessary abstractions, premature generalizations, frameworks nobody asked for.
- Do not approve things you are not sure about. Mark uncertain items and explain the uncertainty.

## Special Modes

### Defect Fix Review

Injected at runtime when reviewing a defect fix. In addition to standard review, the Reviewer checks:

**Defect addressed.** Does the fix resolve the specific issue in the defect report and triage hypothesis? For moderate defects, verify the failing test passes for the right reason, not by changing the test or masking the defect.

**Scope containment.** All changed files must be within the `affected_files` list from the triage output. Renamed variables, reformatted code, updated comments, and reorganized code outside the fix are flagged.

**No new behavior.** The fix should not introduce behavior beyond correcting the defect: no new endpoints, UI states, return type changes, or dependencies.

**Regression risk.** Based on `regression_risks` from triage, assess whether changed code paths are covered by the test suite and whether the happy path behavior is preserved.

**Large diff flag.** If the diff exceeds 100 lines changed or touches more than 3 files, the Reviewer flags it. The orchestrator uses the flag to decide whether to invoke the [Product Guardian](/docs/api/agents/product-guardian/).

## Output Schema

```json
{
  "verdict": "approve | request_changes",
  "spec_verification": [
    {
      "spec_quote": "Exact text from the product spec",
      "spec_section": "Section name",
      "satisfied": true,
      "evidence": "file:line reference or description of what's missing",
      "notes": "Any concerns"
    }
  ],
  "missing_from_spec": [
    { "spec_quote": "What the spec says", "description": "What's missing from the implementation" }
  ],
  "out_of_scope": [
    { "file": "path/to/file", "line": 42, "description": "Code that doesn't map to any spec requirement" }
  ],
  "issues": [
    { "severity": "critical | major | minor | nit", "file": "path/to/file", "line": 42, "message": "Description", "suggestion": "How to fix" }
  ],
  "strengths": ["Things done well"]
}
```

Defect fix review adds: `defect_scope_check` (`scope_ok`, `large_diff`) and `scope_violations` array.
