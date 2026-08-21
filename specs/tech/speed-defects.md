# RFC: Defect Pipeline

> See [product spec](../product/speed-defects.md) for product context.
> Depends on: [Phase 1: Spec Templates](speed-templates.md), [Phase 2: Audit Agent](speed-audit.md)
> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)

## Basic Example

A CLI session showing the defect pipeline end-to-end:

```bash
# 1. File a defect report
cat > specs/defects/invite-failure.md <<'EOF'
# Defect: Invite Failure
Severity: P1
Related Feature: f4-tribes
Observed: Invite sent to users without GitHub connected
Expected: Guard clause prevents invite to unconnected users
Repro: Call send_invite() for user with github_connected=false
EOF

# 2. Triage — agent investigates codebase, classifies defect
./speed/speed defect specs/defects/invite-failure.md
# ✓ Triage complete: moderate complexity, logic defect
# → Affected: src/backend/app/graphql/mutations/tribe.py
# → Hypothesis: resolve_invite missing github_connected guard
# → Human review required before proceeding

# 3. Execute fix (reproduce → fix → review)
./speed/speed run --defect invite-failure
# ✓ Failing test committed (reproduce)
# ✓ Fix applied — test passes
# ✓ Quality gates passed

# 4. Integrate
./speed/speed integrate --defect invite-failure
# ✓ Merged to main, branch cleaned up
```

## Data Model

### Directory structure

Each defect gets a state directory under `.speed/defects/`:

```
.speed/defects/<name>/
  report.md              # Copy of the defect spec (snapshot)
  triage.json            # Triage Agent output
  state.json             # Runtime state
  logs/
    triage.log           # Triage agent conversation
    reproduce.log        # Reproduce agent conversation (moderate)
    fix.log              # Fix agent conversation
    review.log           # Review agent output (moderate)
```

### `triage.json` schema

Produced by the Triage Agent's classification phase. Consumed by all downstream stages.

```json
{
  "is_defect": true,                       // boolean — false triggers rejection
  "reported_severity": "P0 | P1 | P2 | P3", // string enum — from defect report
  "defect_type": "logic | visual | data",  // string enum — informs test strategy
  "complexity": "trivial | moderate | complex", // string enum — determines routing
  "root_cause_hypothesis": "string",       // free-text — Triage Agent's best guess
  "affected_files": ["string"],            // string[] — non-empty for trivial/moderate
  "blast_radius": "low | medium | high",   // string enum
  "blast_radius_detail": "string",         // free-text explanation
  "test_coverage": "existing | none",      // string enum — existing tests in area?
  "test_coverage_detail": "string",        // free-text — which test files, fixtures
  "related_spec": "string",               // path to related product spec
  "suggested_approach": "string",          // free-text — proposed fix strategy
  "regression_risks": ["string"],          // string[] — areas to watch
  "escalation_reason": "string | null"     // non-null when complexity=complex
}
```

### `state.json` schema

Runtime state tracking for the defect pipeline.

```json
{
  "status": "filed | triaging | triaged | reproducing | reproduced | fixing | fixed | reviewing | reviewed | integrating | resolved | rejected | escalated",
  "reported_severity": "P0 | P1 | P2 | P3",  // string enum — copied from report
  "defect_type": "logic | visual | data | null", // string enum | null — null before triage
  "complexity": "trivial | moderate | complex | null", // string enum | null — null before triage
  "branch": "string | null",              // git branch name, null before fix stage
  "created_at": "ISO 8601 timestamp",     // set on filing
  "updated_at": "ISO 8601 timestamp",     // updated on every state transition
  "source_spec": "string"                 // path to original defect spec
}
```

## State Machine

### Valid transitions

```
filed → triaging → triaged → reproducing → reproduced → fixing → fixed → reviewing → reviewed → integrating → resolved
                            → fixing (trivial skips reproduce)
                                                                → integrating (trivial skips review)
                 → rejected
                 → escalated
```

Transitions are one-way. There is no path from `resolved` back to any earlier state — a regression is a new defect. `rejected` and `escalated` are terminal within the defect pipeline.

### Severity × Complexity interaction

Severity (P0–P3) is reported by the human. Complexity (trivial/moderate/complex) is determined by the Triage Agent. They are orthogonal:

- A **P0-critical** defect with **trivial** complexity: fix proceeds immediately with no human gate (urgency overrides ceremony)
- A **P0-critical** defect with **moderate** complexity: Triage still stops for human review, but the output is flagged as urgent
- A **P3-low** defect with **complex** complexity: still escalates to feature pipeline — low urgency doesn't justify a risky hack
- Severity does not change the pipeline path. Complexity alone determines routing. Severity is metadata for human prioritization of what to triage next.

### Complexity classification criteria

| Complexity | Criteria | Pipeline path |
|------------|----------|---------------|
| **Trivial** | 1 file affected, obvious fix, low blast radius, Triage has high confidence in approach | Fix → Gates → Integrate |
| **Moderate** | 2–4 files, non-obvious fix or medium blast radius, Triage has a hypothesis but wants test confirmation, existing tests in affected area | Reproduce → Fix → Gates → Review → Integrate |
| **Complex** | 5+ files, requires schema change or migration, high blast radius, Triage can't isolate root cause, OR no existing test coverage in affected area (reproduce stage can't follow patterns) | Escalate to feature pipeline |

## API Surface

### CLI commands

```bash
# Run triage
./speed/speed defect specs/defects/<name>.md

# Execute fix (after human reviews triage)
./speed/speed run --defect <name>

# Integrate fixed branch
./speed/speed integrate --defect <name>

# Retry with context or model escalation
./speed/speed retry --defect <name> [--context "hint"] [--escalate]

# Check defect status
./speed/speed status --defects
```

### Triage Agent

**File:** `speed/agents/triage.md`
**Model:** `support_model` (sonnet by default)
**Access:** Full codebase read, no write. Investigative — finds code, doesn't change it.

The Triage Agent receives:
- The defect report markdown
- Related feature spec (auto-resolved from `Related Feature` field in the defect report)
- Related tech spec (auto-derived: `specs/tech/<feature-name>.md`)
- Full codebase read access
- Project conventions from `CLAUDE.md`

### Defect type classification

The Triage Agent classifies the defect type to inform the reproduce stage's test strategy:

| Type | Description | Test strategy |
|------|-------------|---------------|
| **logic** | Backend or frontend logic error — wrong return value, missing guard, bad state transition | Backend: pytest with existing fixtures. Frontend: vitest + testing-library (render component, assert behavior). |
| **visual** | Wrong design tokens, broken layout, missing component states, responsive breakpoint issues | vitest + testing-library for component state assertions. Playwright for layout/visual regression (screenshot comparison, element positioning). |
| **data** | Wrong query, missing join, stale cache, incorrect aggregation, migration issue | pytest against test database with seed data that triggers the defect. |

### Stage 1: Triage (`speed defect`)

Implementation in `cmd_defect()`:

1. Parse defect report from the provided path
2. Extract `Related Feature` field → resolve to spec paths
3. Build Triage Agent system prompt with report, specs, codebase access
4. Run agent in two phases:
   - **Investigation:** `provider_run()` with Read/Glob/Grep tools — agent explores the codebase, traces call chains, checks test coverage in affected area
   - **Classification:** `provider_run_json()` with the investigation transcript — agent produces the structured triage JSON
5. Parse triage output
6. Write triage result to `.speed/defects/<name>/triage.json`
7. Update state: `filed → triaging → triaged`
8. Print triage summary to stdout
9. Route based on classification:
   - `trivial`: update state, proceed to fix automatically (no human gate)
   - `moderate`: update state, stop (human reviews before `speed run --defect`)
   - `complex`: pre-populate PRD, update state to `escalated`, stop
10. If `is_defect` is false: update state to `rejected`, print explanation, stop

**Error cases:**
- Defect spec path does not exist → exit with "Defect spec not found: <path>"
- `Related Feature` field missing or unresolvable → warn, proceed without spec context
- Triage Agent returns malformed JSON → exit with "Triage output parse error", log raw output

### Stage 2: Reproduce (`speed run --defect`, moderate only)

Implementation: reuse `cmd_run()` with defect-specific developer prompt.

1. Create isolated branch: `speed/defect-<name>`
2. Build Developer Agent prompt:
   - "Write a failing test that demonstrates this defect"
   - "Do NOT fix the bug"
   - "Look at existing tests near the affected files for patterns, fixtures, and conventions to follow"
   - Test strategy based on `defect_type`:
     - `logic`: "Use pytest (backend) or vitest + testing-library (frontend) to assert the correct behavior"
     - `visual`: "Use vitest + testing-library for component state assertions, or Playwright for layout/visual regression if the bug is about positioning, spacing, or responsive behavior"
     - `data`: "Use pytest with test database fixtures that reproduce the data conditions described in the defect report"
   - Include: triage output (with `test_coverage_detail`, `defect_type`), defect report, related specs
3. Run Developer Agent
4. Run quality gates: lint + typecheck only (test gate skipped — the new test is expected to fail)
5. Commit the failing test
6. Update state: `triaged → reproducing → reproduced`

**Error cases:**
- Branch already exists → exit with "Branch speed/defect-<name> already exists. Clean up or use a different name."
- Quality gates fail (lint/typecheck) → exit with gate output, state stays at `reproducing`

### Stage 3: Fix (`speed run --defect`)

Implementation: reuse `cmd_run()` with defect-specific developer prompt.

1. Branch:
   - Trivial: create new branch `speed/defect-<name>`
   - Moderate: continue on defect branch (failing test already there)
2. Build Developer Agent prompt:
   - "Minimal change. Fix the defect described in the triage output."
   - "Do not refactor, do not improve surrounding code, do not add features."
   - Include: triage output (root cause, affected files, approach), defect report
   - For moderate: "The failing test on this branch defines 'done' — make it pass."
3. Run Developer Agent
4. Run quality gates:
   - Gates for the affected subsystem (determined from `affected_files` glob matching against `[subsystems]` config)
   - Related feature's test suite if identifiable from `related_spec`
5. Grounding gates: non-empty diff, files touched within declared scope
6. Update state: `fixing → fixed`

**Error cases:**
- Quality gates fail → exit with gate output, state stays at `fixing`
- Grounding gate: empty diff → exit with "No changes produced"
- Grounding gate: files outside declared scope → exit with "Files modified outside affected scope: <list>"

### Stage 4: Review (moderate only)

Implementation: reuse the Reviewer agent with defect-specific prompt.

1. Build Reviewer prompt with defect-specific questions:
   - "Does this fix address the reported defect?"
   - "Does it introduce any new behavior beyond the fix?"
   - "Is the change minimal and scoped — no drive-by refactoring?"
   - "Are there obvious regressions introduced?"
2. Input: the diff, the defect report, the triage output
3. If review passes → update state: `fixed → reviewed`
4. If review flags issues → log issues, state remains `fixed` (human decides)

**Error cases:**
- Reviewer agent fails to produce structured output → log raw output, state remains `fixed`, human reviews manually

**Product Guardian (conditional):** If diff > 100 lines changed or > 3 files touched, run the Product Guardian. Same prompt as feature pipeline Guardian but scoped to "is this fix staying in scope?"

### Stage 5: Integrate (`speed integrate --defect`)

Implementation: reuse `cmd_integrate()`.

1. Merge defect branch into main
2. Run regression tests
3. Update state: `reviewed → integrating → resolved`
4. Clean up branch

**Error cases:**
- Merge conflict → exit with conflict details, state stays at `integrating`
- Regression tests fail → exit with test output, state stays at `integrating`

### Escalation: Complex → Feature Pipeline

When Triage classifies as `complex`:

1. Load the defect report
2. Map fields to PRD template:
   - Defect `Observed Behavior` → PRD `Problem`
   - Defect `Expected Behavior` → PRD `Success Criteria`
   - Defect `Reproduction Steps` → PRD `User Flows`
   - Defect `Related Feature` → PRD `Dependencies`
3. Write draft PRD to `specs/product/<name>.md`
4. Print: "Escalated to feature pipeline. Draft PRD: specs/product/<name>.md"
5. Update defect state to `escalated`

### `speed status --defects`

Add defect summary to `cmd_status()` output:

```
Defects:
  invite-failure     P1   moderate   fixing     speed/defect-invite-failure
  login-redirect     P2   trivial    resolved   (merged)
  tribe-count        P0   complex    escalated  → specs/product/tribe-count.md
```

## Validation Rules

| Field | Constraints |
|-------|-------------|
| `severity` (defect report) | Required. One of: `P0`, `P1`, `P2`, `P3`. |
| `Related Feature` (defect report) | Required. Must resolve to an existing spec in `specs/product/`. |
| `Observed Behavior` (defect report) | Required. Non-empty string. |
| `Expected Behavior` (defect report) | Required. Non-empty string. |
| `Reproduction Steps` (defect report) | Required. Non-empty string. |
| `affected_files` (triage output) | Must be non-empty array for `trivial` and `moderate` complexity. May be empty for `complex` (Triage couldn't isolate). |
| `complexity` (triage output) | One of: `trivial`, `moderate`, `complex`. |
| `defect_type` (triage output) | One of: `logic`, `visual`, `data`. |
| State transitions | Only valid transitions allowed (see State Machine). Invalid transition → error. |
| Grounding: diff scope | Files touched by fix must be within `affected_files` scope. Violations block integration. |

## Security & Controls

- **Triage Agent access:** Read-only codebase access. No file writes, no shell commands, no network calls. Investigation only.
- **Input sanitization:** Spec file paths passed to shell commands are validated against `specs/` directory prefix. No path traversal outside project root.
- **Human gate for moderate/complex:** No auto-merge. Moderate requires human review of triage before `speed run`. Complex escalates to feature pipeline entirely.
- **Product Guardian trigger:** Activated when diff exceeds 100 lines changed or touches more than 3 files. Ensures fix stays in scope and doesn't become a stealth feature.
- **Branch isolation:** All defect work happens on `speed/defect-<name>` branches. No direct commits to main.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Two-phase triage | Investigate first (multi-turn with tools), then classify (structured JSON) | Single-pass classification from report text alone | Investigation phase gives the agent codebase context — root cause hypothesis and affected files are grounded in actual code, not guesses from the report. |
| Complexity-based routing | Complexity determines pipeline path (trivial/moderate/complex) | Severity-based routing (P0 gets fast path, P3 gets slow path) | Severity is subjective (human-reported). Complexity is objective (how much code changes). A P0 in 1 file is still trivial to fix; a P3 touching 10 files is still risky. |
| No human gate for trivial | Trivial fixes proceed automatically: fix → gates → integrate | Always require human review regardless of complexity | Trivial = 1 file, obvious fix, low blast radius, high confidence. Quality gates catch regressions. Human review for every typo fix adds friction without proportional safety. |
| Reuse existing agents | Developer and Reviewer agents with defect-specific prompts | Dedicated defect-fix and defect-review agents | Avoids agent sprawl. The agents are the same capability (write code, review code) — only the prompts differ. Defect-specific prompts are injected at runtime. |
| File-based state in `.speed/defects/` | Separate directory tree from features | Extend `.speed/features/` with a `type: defect` flag | Defects have different state machines, different artifacts (triage.json vs plan), and different lifecycles. Mixing them in one directory makes status queries and cleanup harder. |

## Drawbacks

- **Trivial auto-fix has no human review.** A bad Triage classification (marking something trivial that isn't) could merge a broken fix. Mitigated by quality gates, but gates don't catch semantic correctness.
- **Two-phase triage doubles agent cost.** Every defect pays for two LLM calls (investigation + classification). For high-volume defect filing, this adds up. Could be optimized to single-pass for obviously-trivial reports.
- **Complex escalation loses triage context.** When a defect escalates to the feature pipeline, the triage investigation transcript is not carried forward into the PRD. The feature pipeline re-discovers context that triage already found.
- **80% triage accuracy target has no measurement mechanism.** The product spec sets a success criterion of "80% correct triage on first pass" but there's no instrumentation to track whether triage classifications were correct after the fact.
- **Reproduce stage test may not be meaningful.** For some defects, the "failing test" may pass trivially or test the wrong thing. The Developer Agent writing a test for a bug it hasn't debugged may produce a test that doesn't actually exercise the defect path.

## File Impact

| File | Change |
|------|--------|
| `speed/speed` | Add `cmd_defect()`, modify `cmd_run()` for `--defect`, modify `cmd_integrate()` for `--defect`, modify `cmd_status()` for `--defects`, modify `cmd_retry()` for `--defect` |
| `speed/agents/triage.md` | New file — Triage Agent definition |
| `speed/agents/developer.md` | Add defect-specific prompt variants (reproduce, fix) |
| `speed/agents/reviewer.md` | Add defect-specific prompt variant |
| `speed/lib/tasks.sh` | Add defect state CRUD functions (or new `speed/lib/defects.sh`) |

## Dependencies

- Phase 1: defect report template must exist
- Existing infrastructure: Developer Agent, Reviewer Agent, Integrator, quality gates, grounding gates
- `provider_run()` for Triage Agent investigation phase (multi-turn with tools)
- `provider_run_json()` for Triage Agent classification phase (structured output)

## Unresolved Questions

- **Subsystem detection:** How is subsystem detection from `affected_files` configured? Glob patterns in `speed.toml`? Currently the fix stage says "determined from `affected_files` glob matching against `[subsystems]` config" but `[subsystems]` doesn't exist yet.
- **Retry context passing:** How is `--context "hint"` text passed to the Triage Agent during `speed retry`? Appended to the original report? Injected as a separate system prompt section?
- **Product Guardian thresholds:** Is the 100-line / 3-file Product Guardian threshold hardcoded or configurable? Should it be in `speed.toml`?
- **Triage accuracy measurement:** How do we measure the "80% correct triage" success criterion from the product spec? Post-hoc labeling? Comparing triage classification against actual fix complexity?
