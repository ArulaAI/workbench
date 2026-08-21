---
title: Triage
description: The Triage agent investigates defect reports and classifies complexity for fix pipeline routing.
---

## Mission

The Triage agent is a diagnostic engineer. Given a defect report, it investigates the codebase to find the root cause, classifies the defect's complexity, and determines the correct fix pipeline. It does not fix bugs. It locates them and classifies them so the right pipeline gets applied.

## Invocation

| Property | Value |
|----------|-------|
| Command | `speed defect <spec-path>` |
| Model tier | `support_model` (Sonnet) |
| Tools | Read, Glob, Grep (read-only) |
| Trigger | Manual |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Defect report | `specs/defects/<name>.md` | Reproduction steps, expected vs actual behavior, severity |
| Related feature spec | Auto-resolved from `Related Feature` field | Product requirements for intended behavior |
| Related tech spec | Auto-derived from feature name | Implementation design for data flows and component boundaries |
| CLAUDE.md | Project root | Architecture, naming, testing conventions |
| Full codebase | Read-only access | For investigation via Read, Glob, Grep |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Triage result | Stdout (JSON) | Complexity classification, root cause hypothesis, affected files, fix pipeline routing |

## Process

The Triage agent works in two phases. Phase 1 must be complete before Phase 2 output is produced.

### Phase 1: Investigation

1. **Read the defect report.** Identify symptoms, reproduction steps, reported severity (P0-P3), and affected feature.

2. **Read the related feature spec.** Understand intended behavior. Note spec ambiguities that could explain the reported behavior.

3. **Read the related tech spec** (if it exists). Understand implementation design, data flow, key functions, and component boundaries.

4. **Read CLAUDE.md.** Ground in project conventions: naming patterns, file locations, architecture layers, testing conventions.

5. **Locate the affected code.** Grep for entry points described in reproduction steps: route handlers, components, API endpoints, event handlers. Find functions and modules directly named in the report.

6. **Trace call chains.** From each entry point, follow the execution path across files. Check data transformations and state transitions. Locate the specific point where behavior diverges from the spec.

7. **Assess test coverage.** Find test files co-located with affected source. Determine whether the failing case is tested or is a gap.

8. **Assess blast radius.** Count involved files. Find callers of affected functions. Check whether shared utilities, models, or schemas are implicated. Determine whether the fix would require database migrations.

### Phase 2: Classification

After completing investigation, produce the triage result. The investigation transcript informs the classification.

## Complexity Classification

| Complexity | Criteria | Pipeline Path |
|------------|----------|---------------|
| **trivial** | 1 file affected, obvious and isolated fix, low blast radius, high confidence | Fix, Gates, Integrate |
| **moderate** | 2-4 files affected, non-obvious fix or medium blast radius, hypothesis needs test confirmation | Reproduce, Fix, Gates, Review, Integrate |
| **complex** | 5+ files, or schema change required, or high blast radius, or cannot isolate root cause, or no test coverage | Escalate to feature pipeline |

Complexity escalation rules: a trivial defect becomes moderate if the fix cannot be confirmed in isolation. A moderate defect becomes complex if fixing it requires touching shared infrastructure, changing a database schema, or if affected code has no test coverage.

## Defect Type Classification

| Type | Description | Test Strategy |
|------|-------------|---------------|
| **logic** | Wrong computation, incorrect state transition, missing validation, broken control flow | pytest (backend) or vitest + testing-library (frontend) |
| **visual** | Wrong design tokens, broken layout, missing component states, incorrect rendering | vitest + testing-library for state assertions; Playwright for layout |
| **data** | Wrong query, missing join, stale cache, incorrect aggregation, missing seed data | pytest with test database fixtures |

Choose the type describing the root cause, not the symptom. A defect may have characteristics of multiple types.

## Not-a-Defect Detection

If the code behaves exactly as the feature spec describes, set `is_defect: false`. Explain that the spec says X, the code does X, and the reported behavior is a feature change request rather than a defect. The fix pipeline cannot fix a spec; that requires a product decision.

## How It Works

The triage pipeline runs in eleven steps, with the agent invoked twice: once for investigation (with read-only tools) and once for classification (no tools, just the investigation transcript).

```
speed defect <spec-path>
    │
    ├─  1. Validate defect report format
    ├─  2. Extract defect name from filename
    ├─  3. Initialize defect directory + state
    ├─  4. Transition state → "triaging"
    ├─  5. Resolve related specs
    │       ├─ Product spec (from Related Feature field)
    │       └─ Tech spec (derived from feature name)
    ├─  6. Investigation phase
    │       ├─ Build investigation prompt (report + specs)
    │       └─ Send to Triage agent (Sonnet, read-only tools)
    ├─  7. Classification phase
    │       ├─ Build classification prompt (investigation transcript)
    │       └─ Send to Triage agent (Sonnet, no tools)
    ├─  8. Parse + validate triage JSON
    ├─  9. Transition state by result
    │       ├─ is_defect=true, trivial/moderate → "triaged"
    │       ├─ is_defect=false → "rejected"
    │       └─ complexity=complex → "escalated"
    ├─ 10. Print triage summary
    └─ 11. Route by complexity
            ├─ trivial  → Fix → Gates → Integrate
            ├─ moderate → Reproduce → Fix → Gates → Review → Integrate
            └─ complex  → Escalate to feature pipeline
```

### Steps 1-4: Setup

`triage_defect` (`lib/defect_triage.sh:297-446`) validates the defect report format, extracts the defect name from the filename, creates the defect directory under `.speed/defects/<name>/`, and transitions the state machine to "triaging."

### Step 5: Spec resolution

Lines 327-346 parse the `Related Feature:` field from the defect report. `resolve_related_specs` maps the feature name to product and tech spec paths (e.g., `specs/product/library-app.md` and `specs/tech/library-app.md`).

### Step 6: Investigation phase

`build_investigation_prompt` assembles the defect report, product spec, and tech spec into a single prompt. Lines 366-371 send it to the Triage agent with Sonnet and read-only tools (`AGENT_TOOLS_READONLY`). The agent uses Read, Glob, and Grep to navigate the codebase, trace call chains, assess test coverage, and locate the point where behavior diverges from the spec. The full investigation transcript is saved to `${defect_dir}/logs/investigation.log`.

### Step 7: Classification phase

`build_classification_prompt` wraps the investigation transcript and asks the agent to produce the structured triage JSON. Lines 393-398 send it to the Triage agent with Sonnet and no tools (the investigation is done; classification is purely analytical).

### Step 8: Parse and validate

Lines 407-422 parse the classification output via `parse_agent_json`, then `write_triage_output` validates required fields and writes `triage.json` to the defect directory.

### Step 9: State transition

Lines 425-438 route by result:

| Condition | Target state | Meaning |
|-----------|-------------|---------|
| `is_defect=true`, trivial/moderate | `triaged` | Ready for fix pipeline |
| `is_defect=false` | `rejected` | Spec change request, not a defect |
| `complexity=complex` | `escalated` | Too large for defect pipeline, needs feature treatment |

### Steps 10-11: Summary and routing

`print_triage_summary` displays the classification. `route_by_complexity` directs the defect into the appropriate fix pipeline: trivial (direct fix), moderate (reproduce first), or complex (escalate).

## Worked Example

A defect report at `specs/defects/wrong-availability.md` for the `library-app` feature. The report says: "Book shows as 'available' after being borrowed. Expected: status changes to 'borrowed'."

### What the investigation phase does

The Triage agent receives the defect report, reads the product spec's "Borrowing Rules" section, then investigates:

1. **Grep for `borrow_book`:** Finds `src/backend/services/borrow.py:15`
2. **Read the function:** Finds `borrow_book()` creates a `Borrow` record but never updates `Book.status`
3. **Check test coverage:** Finds `tests/test_borrow.py` but no test case checks status after borrowing
4. **Assess blast radius:** `Book.status` is read by `BookQuery.books` and `availability_check`. Two files affected.

### What the classification returns

```json
{
  "is_defect": true,
  "reported_severity": "P1",
  "defect_type": "logic",
  "complexity": "trivial",
  "root_cause_hypothesis": "borrow_book() in src/backend/services/borrow.py creates a Borrow record but does not set book.status = 'borrowed'. The status field exists on the Book model (added by Task 1) but is never updated during the borrowing flow.",
  "affected_files": ["src/backend/services/borrow.py"],
  "blast_radius": "low",
  "blast_radius_detail": "Fix is isolated to borrow_book(). BookQuery and availability_check read status but don't set it.",
  "test_coverage": "existing",
  "test_coverage_detail": "tests/test_borrow.py exists with 3 tests for borrow_book() but none check Book.status after borrow. Pattern: pytest with SQLAlchemy test fixtures.",
  "related_spec": "specs/product/library-app.md",
  "suggested_approach": "Add book.status = 'borrowed' after creating the Borrow record in borrow_book(). Add a regression test asserting status change.",
  "regression_risks": ["availability_check depends on status being accurate"],
  "escalation_reason": null
}
```

### What the user sees

```
═══ Defect Triage: wrong-availability ═══
  Validating defect report...
  Related feature: library-app
  Starting triage investigation...
  Running triage classification...

  Triage Result:
    Defect: ✓ confirmed
    Severity: P1 (reported)
    Type: logic
    Complexity: trivial
    Root cause: borrow_book() does not update Book.status to 'borrowed'
    Files: src/backend/services/borrow.py
    Blast radius: low

  Pipeline: Fix → Gates → Integrate
  Next: speed defect fix wrong-availability
```

## Constraints

- Read-only access. No writes, no shell commands, no code execution.
- Ground every finding in code actually read. If the defect cannot be located, set complexity to `complex` with an explanation.
- Do not skip Phase 1. A classification without code evidence is a guess, not a triage.
- Err toward higher complexity. A missed escalation sending a complex bug into the trivial pipeline causes regressions. A false escalation costs a planning conversation.
- Severity (P0-P3) is reported by the human and reflects business impact. Complexity is the Triage agent's determination based on code investigation. They are orthogonal: a P0 defect can be trivial (one-line fix), a P3 defect can be complex (schema migration).

## Output Schema

```json
{
  "is_defect": true,
  "reported_severity": "P0 | P1 | P2 | P3",
  "defect_type": "logic | visual | data",
  "complexity": "trivial | moderate | complex",
  "root_cause_hypothesis": "Description grounded in specific code read during investigation",
  "affected_files": ["path/to/file.py"],
  "blast_radius": "low | medium | high",
  "blast_radius_detail": "What else could be affected",
  "test_coverage": "existing | none",
  "test_coverage_detail": "What tests exist near affected files, patterns used",
  "related_spec": "specs/product/feature.md",
  "suggested_approach": "Specific fix approach",
  "regression_risks": ["things that could break"],
  "escalation_reason": null
}
```

`escalation_reason` is `null` unless complexity is `complex`, in which case it provides a human-readable explanation.
