---
title: Plan Verifier
description: The Plan Verifier performs an adversarial audit of the Architect's task plan.
---

## Mission

The Plan Verifier is an independent auditor that checks whether the [Architect](/docs/api/agents/architect/)'s task plan will actually deliver what the product specification requires. It receives the original spec and the task plan, but never the Architect's reasoning. The separation is intentional: the Plan Verifier must form its own understanding of the spec and check the plan against it without being influenced by how the Architect interpreted it.

A `pass` means zero critical failures. Any critical failure produces a `fail`.

## Invocation

| Property | Value |
|----------|-------|
| Command | `speed verify` |
| Assembly function | `assemble_verifier` |
| Model tier | `planning_model` (Opus) |
| Trigger | Manual (runs after `speed plan`) |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Product specification | `specs/product/<feature>.md` | The original spec, without the Architect's reasoning |
| Task plan | `.speed/features/<feature>/tasks/*.json` | The Architect's generated task DAG |
| Contract | `.speed/features/<feature>/contract.json` | The Architect's entity declarations |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Verification report | Stdout (JSON) | Requirement coverage, critical failures, semantic drift, contract issues |

## Process

1. **Core question test.** Identify the product spec's central purpose. Ask: if every task executes perfectly, can the system answer that core question? A plan that creates entities unable to answer the core question is a critical failure.

2. **Entity relationship verification.** Extract every entity and relationship from the spec. For each one, verify a task creates it. Relationships like "X belongs to Y", "X has many Y", and "users form X" each imply specific data structures. A relationship with no corresponding task is a critical failure.

3. **Missing task detection.** Trace each requirement to a task. Common gaps: a UI view with no supporting API task, a relationship with no migration task, a behavior with no business logic task, validation constraints with no enforcement task.

4. **Semantic drift detection.** Check whether tasks use the same terms as the spec. If the spec says "workspace" but tasks say "group", that is semantic drift and may indicate the Architect reinterpreted the spec's concepts.

5. **Contract verification.** For each entity type (`database`, `file`, `function`), verify a task creates it. Check that every core query in the contract can be satisfied by the planned entities. Verify the contract's core queries answer the product spec's core question. An empty entities list is a red flag.

6. **File coverage verification.** If the tech spec includes a Files Changed table, cross-reference it against every task's `files_touched`. A file in the RFC with no task touching it is a critical failure.

## How It Works

The verification pipeline runs in six phases, with an auto-fix loop that can iterate up to `MAX_VERIFY_FIX_ITERATIONS` times.

```
speed verify
    │
    ├─ 1. Load spec + task plan + contract
    ├─ 2. Assemble verifier context
    │      ├─ Product spec (ground truth)
    │      ├─ All tasks with criteria, deps, files, rationale
    │      ├─ Cross-cutting concerns
    │      ├─ Contract as JSON
    │      ├─ Spec-alignment reality check
    │      └─ Decomposition quality indicators
    ├─ 3. Spec traceability pre-check
    │      └─ Injects uncovered requirements into verifier context
    ├─ 4. Send to Plan Verifier agent (Opus, read-only)
    ├─ 5. Parse JSON + print report
    └─ 6. Auto-fix loop (if status == "fail")
           ├─ Fix Agent edits task JSON files
           ├─ Re-verify after each fix round
           ├─ Convergence check (same failures = escalate)
           └─ Human escalation for judgment calls
```

### Phase 1: Load inputs

`cmd_verify` (`lib/cmd/verify.sh:259-280`) requires an active feature with tasks. It reads the spec file path saved during `speed plan` and loads the cross-cutting concerns JSON if it exists.

### Phase 2: Assemble context

`context_assemble_verifier` (`lib/context/assembly.py:452-629`) builds a structured prompt with a 40k token budget containing:

| Section | Source | Purpose |
|---------|--------|---------|
| Product spec | Spec file | Ground truth for all requirements |
| Task plan | Task JSON files | Full task details with criteria, deps, rationale, assumptions, spec refs |
| Cross-cutting concerns | Feature-level JSON | Constraints spanning 3+ tasks |
| Data model contract | `contract.json` | Machine-verifiable entity declarations |
| Codebase reality check | Spec-alignment from Layer 1 | Which claims are confirmed/missing/divergent |
| Decomposition quality | CSG + task mapping | Task-to-cluster mapping, cross-task coordination points |

If the Python assembly fails, lines 298-301 fall back to `_build_verify_message`, which concatenates tasks and contract inline.

### Phase 3: Spec traceability

`context_spec_traceability` pre-checks requirement-to-task coverage and injects any uncovered requirements into the verifier's context (lines 303-318). The verifier sees these gaps before it begins its own analysis.

### Phase 4: Agent execution

Lines 320-349 send the assembled prompt to the Plan Verifier with the planning-tier model (Opus) and read-only tools. The agent forms its own understanding of the spec before reading the plan, then checks six dimensions: core question test, entity relationships, missing tasks, semantic drift, contract verification, and file coverage.

### Phase 5: Report and gate

`_print_verify_report` (`verify.sh:4-100`) formats core question status, requirement coverage, semantic drift, critical failures, and recommendations.

### Phase 6: Auto-fix loop

On `fail` status, lines 369-611 enter the fix loop:

1. A Fix Agent (Sonnet, write tools) receives the verification issues + task files
2. It edits task JSON files for mechanical fixes (adjusting thresholds, adding missing fields)
3. Issues requiring human judgment go to `needs_human` instead
4. After fixes, the Plan Verifier re-runs against the updated tasks
5. A convergence check compares failure keys across iterations. If the same failures persist, the loop escalates to human review

## Worked Example

A `library-app` plan with 5 tasks. The Architect planned a `books` table but missed the `borrowing_limit` constraint from the product spec.

### What the verifier context includes

**Spec traceability pre-check** found one uncovered requirement: "Users can borrow up to 5 books simultaneously" maps to no task.

**Decomposition quality indicators** show Task 3 touches the `user-domain` cluster (because it modifies `user.py`), flagging a cross-task coordination point.

### What the agent returns

```json
{
  "status": "fail",
  "core_question": "Can the system manage a library's book lending operations?",
  "core_question_answerable": false,
  "core_question_reasoning": "The plan creates books and borrows tables but has no enforcement of borrowing limits. The core lending operation is unbounded.",
  "spec_requirements": [
    {
      "requirement": "Users can borrow up to 5 books simultaneously",
      "spec_location": "Borrowing Rules",
      "mapped_to_task": null,
      "status": "missing",
      "notes": "No task enforces the limit. Task 2 creates borrow_book() but has no limit check in its criteria."
    },
    {
      "requirement": "Books have title, author, ISBN, and availability status",
      "spec_location": "Library Catalog",
      "mapped_to_task": "1",
      "status": "covered"
    }
  ],
  "semantic_drift": [],
  "contract_issues": [],
  "critical_failures": [
    {
      "description": "No task enforces borrowing limit of 5",
      "spec_reference": "Borrowing Rules: 'Users can borrow up to 5 books simultaneously'",
      "plan_gap": "Task 2 creates borrow_book() but acceptance criteria have no limit check"
    }
  ],
  "recommendations": [
    "Add acceptance criterion to Task 2: borrow_book() returns error when user has 5 active borrows"
  ]
}
```

### The auto-fix loop

The Fix Agent reads the critical failure, opens `tasks/2.json`, and adds the missing acceptance criterion:

```
  Auto-fixed: Task 2 — acceptance_criteria: added "borrow_book() returns error when user has 5 active borrows (verify: test)"
```

Re-verification passes:

```
  ✓ Core question: answerable
  Spec requirements: 8 of 8 covered

  Summary: 0 critical, 0 warnings, 0 recommendations

✓ Plan verification PASSED (1 issue auto-fixed)
  Next: speed run to execute tasks
```

## Constraints

- Read-only access. Cannot modify files.
- Adversarial posture: assume the Architect may have misinterpreted the spec.
- Read the spec first, form an independent understanding, then read the plan.
- Quote the spec for every flagged issue. If a specific text cannot be cited, the requirement may be fabricated.
- Do not fabricate requirements. Only flag gaps for what the spec actually says.

## Output Schema

```json
{
  "status": "pass | fail",
  "core_question": "The product's core question as the verifier understands it",
  "core_question_answerable": true,
  "core_question_reasoning": "How the planned data model does or does not answer it",
  "spec_requirements": [
    {
      "requirement": "Exact quote or close paraphrase from spec",
      "spec_location": "Section name",
      "mapped_to_task": "task ID or null",
      "status": "covered | missing | partial | drifted",
      "notes": "Explanation if not fully covered"
    }
  ],
  "semantic_drift": [
    { "spec_term": "What the spec calls it", "plan_term": "What the plan calls it", "risk": "Why concerning" }
  ],
  "contract_issues": [
    { "type": "missing_table | missing_fk | unresolvable_query | no_task_creates_it", "description": "What's wrong" }
  ],
  "critical_failures": [
    { "description": "What is critically wrong", "spec_reference": "What the spec says", "plan_gap": "What the plan is missing" }
  ],
  "recommendations": ["Actionable fixes"]
}
```
