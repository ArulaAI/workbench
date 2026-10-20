---
title: Architect
description: The Architect agent decomposes specifications into a task DAG for parallel execution.
---

## Mission

The Architect is a senior software architect that receives up to three specifications for a feature (product, tech, design) plus codebase context, validates coverage across them, and decomposes the work into a directed acyclic graph (DAG) of tasks for parallel execution by Developer agents.

Every task the Architect produces carries traceability back to spec requirements, a machine-verifiable contract, and explicit rationale for its boundaries. When something in the specs is ambiguous, the Architect decides and records the assumption rather than leaving it to downstream agents.

## Invocation

| Property | Value |
|----------|-------|
| Command | `speed plan <spec-file>` |
| Assembly function | `assemble_architect` |
| Model tier | `planning_model` (Opus) |
| Trigger | Manual |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Product spec | `specs/product/<feature>.md` | User stories, requirements, success criteria |
| Tech spec (RFC) | `specs/tech/<feature>.md` | Data model, API surface, implementation design |
| Design spec | `specs/design/<feature>.md` | Component hierarchy, routes, UI states (optional) |
| CSG domain clusters | Layer 1 context pipeline | Groups of tightly-coupled symbols from the codebase |
| Project map | Layer 1 context pipeline | File structure and module relationships |
| Spec-codebase alignment | Layer 1 context pipeline | Per-claim status: `confirmed`, `missing`, or `divergent` |
| Related specs | TF-IDF scoring via `related_specs.py` | Other feature specs scored by relevance, with signal annotations |
| Product vision | `specs/product/overview.md` | High-level product identity and constraints |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Task DAG | `.speed/features/<feature>/tasks/*.json` | One JSON file per task with all required fields |
| Contract | `.speed/features/<feature>/contract.json` | Machine-verifiable entity declarations (database, file, function) |
| Validation report | Embedded in plan output | Spec triangulation findings: critical, warning, note |
| Cross-cutting concerns | Embedded in plan output | Constraints that apply across 3+ tasks |

## Process

1. **Spec triangulation.** Read all provided specs and cross-reference: every product requirement must trace to a backend or frontend implementation. Flag tech spec items with no product requirement, and design spec pages with no corresponding API.

2. **Codebase grounding.** Incorporate spec-codebase alignment data. Entities marked `confirmed` are not recreated. Entities marked `divergent` are extended or reconciled, not rebuilt from scratch. Only `missing` entities get new creation tasks.

3. **Domain cluster alignment.** Prefer task boundaries that align with CSG domain clusters, since clusters represent high-cohesion code groups. Tasks that span clusters acknowledge the coordination cost in their rationale.

4. **Related spec integration.** Check related specs for foreign keys, join tables, and shared data models that cross feature boundaries. If a related spec references an entity in this feature, the DAG must include the task creating that relationship.

5. **Task decomposition.** Break work into 15-30 minute units. No two parallel tasks may modify the same file. Foundation tasks (data models, types) come first. Each task gets acceptance criteria with `verify_by` hints (test, schema_check, file_exists, lint, manual).

6. **Contract declaration.** Every entity must name the task that creates it via `created_by_task`. Entity types: `database` (verified by model file + class), `file` (verified by path existence), `function` (verified by symbol in CSG). An empty contract is rejected.

7. **Cross-task verification.** Re-read all tasks as a set. For each value a task produces, verify a downstream task consumes it with a matching signature. For each value a task needs, verify an upstream task provides it.

## How It Works

The planning pipeline runs in seven phases. Phases 1-4 gather context and run pre-flight gates; Phase 5 sends it to the Architect; Phases 6-7 validate and persist the output.

```
speed plan <spec-file>
    │
    ├─ 1. Pre-plan Guardian gate                     (cached)
    │      └─ Product Guardian checks spec against vision
    ├─ 2. Pre-plan Audit gate, one per spec          (cached when it passed)
    │      └─ Spec Auditor checks structural completeness
    ├─ 3. Build Layer 1 context
    │      ├─ Project map (files, directories, languages)
    │      ├─ CSG domain clusters + bridge symbols
    │      ├─ Spec-codebase alignment (confirmed/missing/divergent)
    │      └─ Related specs (TF-IDF scored + compressed)
    ├─ 4. Assemble architect prompt (stable context first)
    ├─ 5. Architect                                  (cached)
    │      ├─ Skeleton pass (Opus): boundaries, files, dependencies
    │      │     └─ Phased if audit estimates > threshold tasks
    │      ├─ Decomposition gate on the skeleton (auto-patches bridge deps)
    │      └─ Enrich pass (Sonnet): criteria, spec refs, rationale, contract
    ├─ 6. Coverage verifier + validation gate        (coverage cached)
    │      └─ Critical issues block task creation
    └─ 7. Persist tasks + contract + decomposition gate
           ├─ Task JSON files → .speed/features/<feature>/tasks/
           ├─ Contract → .speed/features/<feature>/contract.json
           └─ Decomposition gate again (covers coverage-repair tasks)
```

`--single-call` (or `SPEED_PLAN_SINGLE_CALL=true`) replaces the skeleton and enrich passes with one Opus call that writes complete tasks.

### Phase 1: Guardian gate

`cmd_plan` (`lib/cmd/plan.sh:233-258`) calls `_run_guardian "pre-plan"` (`lib/shared.sh:28-146`) with the spec content. The Guardian checks whether the feature belongs in the product at all. A `rejected` status halts planning unless `SKIP_GUARDIAN=true`. Results are cached by spec hash, so unchanged specs skip this call.

### Phase 2: Audit gate

`cmd_plan` calls `cmd_audit` once for each spec it plans. The [Spec Auditor](/docs/api/agents/spec-auditor/) checks structural completeness. A `fail` (Level 1 errors) blocks planning. The audit's sizing estimate determines whether the Architect runs single-phase or multi-phase.

A passing audit is cached. `_plan_audit_cache_key` hashes the spec, the audit prompt, the spec templates, the vision, the model and every file under `specs/` (the audit reads linked and parent specs and the spec list). A failing audit is never reused, so a fixed spec is always audited again.

### Phase 3: Layer 1 context

`context_build_layer1` (`context_bridge.sh`) builds four artifacts:

| Artifact | Content | Budget |
|----------|---------|--------|
| Project map | File tree, line counts, directory structure | Included in 60k token architect budget |
| CSG clusters | Domain groupings from code references, bridge symbols, cross-domain edges | Top 20 clusters, 15 bridge symbols |
| Spec alignment | Per-claim status: `confirmed`, `missing`, `divergent` against actual codebase | All claims |
| Related specs | TF-IDF scored against primary specs, compressed to budget | 15k tokens default |

`assemble_architect` (`lib/context/assembly.py:280-444`) builds structured markdown from these artifacts: project overview, directory structure, domain architecture, cross-domain dependencies, high-impact symbols, and spec vs. reality.

### Phase 4: Prompt assembly

`_plan_stable_context` puts the blocks that are identical in every Architect call first: shared platform architecture, codebase context from Phase 3, and related specs. The specs follow, then any phase scope. Phase 1 and Phase 2 therefore share a prompt prefix that the provider's prompt cache can reuse.

### Phase 5: Architect agent

The Architect runs in two passes by default, so the planning model only writes the decisions that need it.

| Pass | Prompt | Schema | Model | Writes |
|---|---|---|---|---|
| Skeleton | `agents/architect-skeleton.md` | `templates/architect-skeleton.json` | planning (Opus) | task boundaries, `files_touched`, `depends_on`, `agent_model`, validation, cross-cutting concerns |
| Enrich | `agents/architect-enrich.md` | `templates/architect-enrich-output.json` | support (Sonnet) | `acceptance_criteria`, `spec_references`, `rationale`, `assumptions`, contract |

Between the passes, `_plan_gate_skeleton` runs the decomposition gate on the skeleton, including the bridge-symbol auto-patch. A structural failure stops the plan before any enrichment is paid for, and the rejected skeleton is saved to `architect-skeleton-rejected.json`. A skeleton that passes is cached, so if enrichment fails, a re-run only repeats the enrich pass. Enrichment receives the specs and the skeleton, not the codebase scan; the skeleton's descriptions carry the function and file names. Tasks the enrich pass skips get one retry, and the plan stops if any task is still missing criteria.

`_run_architect_phase` runs each call with `$ARCHITECT_MAX_TURNS` turns and a timeout scaled to the message size. With `--single-call`, one Opus call uses `agents/architect.md` and `templates/architect-output.json` to write complete tasks.

For large specs (audit estimated > threshold tasks), the planning-model pass splits into two phases. Phase 1 plans foundation tasks (data models, core services). Phase 2 receives Phase 1's tasks in full and plans features and integration, with a starting ID offset to prevent collisions.

### Phase 6: Validation gate

The coverage verifier checks the plan against the full specs first. Its verdict is cached on the specs, the task list, its prompt and the model, so an unchanged plan does not pay for it again. Then the `validation` array from the Architect's output is reported. Severity levels: `critical` blocks task creation, `warning` logs but continues, `note` is informational only.

### Phase 7: Persist and verify

The task JSON files, contract and cross-cutting concerns are written to the feature directory. Acceptance criteria are stored as `{criterion, verify_by}` objects, so criteria verification can run each one the way the Architect intended. The decomposition quality gate (`_plan_decomposition_gate`) then checks task size, cluster alignment, bridge symbol exposure, and file ownership. If the only failures are missing bridge-symbol dependency edges, the pipeline auto-patches the task JSON files and re-runs the gate.

## Worked Example

A `library-app` feature with product spec, tech spec, and an existing codebase containing a `users` module.

### What the context pipeline produces

**Spec alignment:**
```
Confirmed (2):
- users table: exists at src/backend/models/user.py
- Flask app: exists at src/backend/app.py

Missing (3):
- books table: expected but not found
- borrowing_rules service: expected but not found
- book availability endpoint: expected but not found

Divergent (1):
- users table has 'username' but spec says 'display_name'
```

**CSG cluster relevant to planning:**
```
user-domain — 4 files, cohesion: 0.82
  Key symbols: User, get_user, UserType
  Files: src/backend/models/user.py, src/backend/schema/user.py
  Internal references: 8, External references: 3
```

**Related specs:** `specs/product/notifications.md` scored 0.12 (above 0.05 threshold), included because it references "user preferences" which touch the same `users` table.

### What the Architect produces

```json
{
  "tasks": [
    {
      "id": "1",
      "title": "Create Book model and migration",
      "files_touched": ["src/backend/models/book.py", "src/backend/migrations/0002_books.py"],
      "depends_on": [],
      "agent_model": "sonnet",
      "spec_references": [
        {"spec": "product", "section": "Library Catalog", "requirement": "Books have title, author, ISBN, status"}
      ]
    },
    {
      "id": "2",
      "title": "Create Borrowing model and rules service",
      "files_touched": ["src/backend/models/borrow.py", "src/backend/services/borrow.py"],
      "depends_on": ["1"],
      "agent_model": "sonnet"
    },
    {
      "id": "3",
      "title": "Add book availability GraphQL query",
      "files_touched": ["src/backend/schema/book.py", "src/backend/schema/__init__.py"],
      "depends_on": ["1", "2"],
      "agent_model": "sonnet"
    }
  ],
  "contract": {
    "entities": [
      {"name": "books", "type": "database", "created_by_task": "1"},
      {"name": "borrows", "type": "database", "created_by_task": "2"},
      {"name": "borrow_book", "type": "function", "created_by_task": "2"}
    ]
  },
  "validation": [
    {
      "severity": "warning",
      "issue": "Spec says 'display_name' but existing User model has 'username'",
      "product_requirement": "User profile shows display name",
      "recommendation": "Add a migration to rename username → display_name, or alias it"
    }
  ]
}
```

### What the user sees

```
═══ Planning Task DAG ═══
  Tech spec:    specs/tech/library-app.md
  Product spec: specs/product/library-app.md

  Guardian: ALIGNED — Feature aligns with product vision
  Audit: PASS

  Building Layer 1 context index...
  ✓ Layer 1: built
  Scoring related specs from: specs/
  Related specs scored and compressed (budget: 15000 tokens)

  Sending to Architect agent...

═══ Validation Report ═══
  ⚠ WARNING: Spec says 'display_name' but existing User model has 'username'
    Requirement: User profile shows display name
    Suggestion: Add a migration to rename username → display_name

  ✓ Decomposition quality gate passed

═══ Task Graph ═══
  Task 1: Create Book model and migration
  Task 2: Create Borrowing model and rules service  [depends: 1]
  Task 3: Add book availability GraphQL query        [depends: 1, 2]

  3 tasks, 1 warning, 0 critical

  Next: speed verify to validate the plan against the spec
```

## Constraints

- Every product requirement must be covered by at least one task. Nothing unassigned.
- No two parallel tasks may modify the same file. Overlapping files require a dependency edge.
- Task size: 15-30 minutes of focused implementation. Larger tasks must be split.
- Foundation first: data models, then service logic, then API/resolvers, then frontend components, then pages.
- Use `sonnet` as default `agent_model`. Reserve `opus` for architecturally complex tasks.
- Use spec terminology exactly. Semantic drift from the spec's vocabulary is a verification failure.
- When no product spec is provided, decompose from tech/design spec alone and apply stricter scrutiny to completeness.

## Phased Planning

When the spec is too large for a single planning cycle (flagged by the [Spec Auditor](/docs/api/agents/spec-auditor/)'s sizing check), the Architect receives a Phase Scope section:

- Plan only the spec sections assigned to the current phase.
- Set `depends_on` edges to prior-phase tasks where needed, without recreating their work.
- Use the starting task ID specified. IDs must be unique across phases.
- The contract covers only entities created by the current phase's tasks.

## Output Schema

Per-task JSON fields: `id`, `title`, `description`, `acceptance_criteria`, `depends_on`, `agent_model`, `files_touched`, `spec_references`, `rationale`, `assumptions`.

```json
{
  "id": "3",
  "title": "Add borrowing rules and availability check",
  "description": "Implement borrowing rules in src/backend/services/borrow.py...",
  "files_touched": ["src/backend/services/borrow.py", "src/backend/models/book.py"],
  "depends_on": ["1", "2"],
  "agent_model": "sonnet",
  "acceptance_criteria": [
    { "criterion": "borrow_book() returns error when user has 5 active borrows", "verify_by": "test" },
    { "criterion": "Migration 0004 adds status column with default 'available'", "verify_by": "file_exists" }
  ],
  "spec_references": [
    { "spec": "product", "section": "Borrowing Rules", "requirement": "Users can borrow up to 5 books simultaneously" }
  ],
  "rationale": "Separated from Book model (task 1) because rules depend on both models existing first.",
  "assumptions": ["Spec says 'borrowing limit' but doesn't specify number — assumed 5"]
}
```

Validation report severity levels: `critical` (blocks task creation), `warning` (partial coverage or minor inconsistency), `note` (observation only).
