# SPEED: Unified Intake & Defect Pipeline

**Version:** 0.3 (Draft)
**Date:** February 2026
**Status:** RFC

---

## Problem

SPEED has a strong delivery pipeline but no intake layer. Work enters only one way: a human writes a markdown spec from scratch, puts it in `specs/tech/`, and runs `speed plan`. This creates three gaps:

1. **Blank-page authoring.** Every spec starts from zero. No structure, no guidance. Authors spend time deciding what sections to include rather than filling in content. Agents parse unpredictable formats because there is no canonical structure.

2. **Only one pipeline.** SPEED handles features but not defects. There is no way to say "tribe invites silently fail when the invitee has no GitHub connected" and have SPEED take it through diagnosis and fix. Bugs are handled ad-hoc — stuffed into feature branches or fixed outside the system entirely.

3. **No external system connection.** Work lives in GitHub Issues, Linear, JIRA, Figma. SPEED can't pull from any of them. Status stays inside `.speed/` JSON files with no way to push progress back.

These three gaps are one problem: **SPEED has no intake layer.** Templates, integrations, and defect handling are all variations of "how does work enter the system?"

---

## Solution: Unified Intake

One entry point. Multiple input modes. All produce the same output: a structured spec in `specs/`.

The key insight: the human already works with an LLM to write specs. SPEED's job isn't to draft — it's to **scaffold, validate, and route.**

```
┌─────────────────────────────────────────────────────┐
│                   INTAKE LAYER                       │
│                                                      │
│   Input Modes:                                       │
│   ┌─────────────┐ ┌───────────────┐ ┌────────────┐  │
│   │ Manual      │ │ Templated     │ │ External   │  │
│   │ (write spec │ │ (speed new    │ │ (GitHub,   │  │
│   │  by hand)   │ │  → scaffold)  │ │  Linear →  │  │
│   │             │ │               │ │  scaffold)  │  │
│   └──────┬──────┘ └──────┬────────┘ └─────┬──────┘  │
│          │               │                │          │
│          └───────────┬───┘────────────────┘          │
│                      ↓                               │
│            specs/{type}/{name}.md                    │
│                      ↓                               │
│          ┌───────────────────────┐                   │
│          │   Audit Agent         │                   │
│          │   validate structure  │                   │
│          │   check completeness  │                   │
│          │   flag gaps + sizing  │                   │
│          └───────────┬───────────┘                   │
│                      ↓                               │
│             spec ready for pipeline                  │
│                                                      │
└──────────────────────┬──────────────────────────────┘
                       ↓
         ┌─────────────┴──────────────┐
         ↓                            ↓
   Feature Pipeline             Defect Pipeline
   (existing)                   (new — see below)
```

### Input Modes

#### 1. Manual (existing — no change)

Human writes a spec directly in `specs/`. This is what SPEED does today. No agent involved.

```bash
vim specs/tech/my-feature.md
./speed/speed plan specs/tech/my-feature.md
```

#### 2. Templated (new — blank scaffold)

Human gets a structured template to fill in. No agent — just the right sections in the right order.

```bash
./speed/speed new prd my-feature          # → specs/product/my-feature.md
./speed/speed new rfc my-feature          # → specs/tech/my-feature.md
./speed/speed new design my-feature       # → specs/design/my-feature.md
./speed/speed new defect invite-failure   # → specs/defects/invite-failure.md
```

The human fills in the template with their LLM of choice. SPEED provides structure; the human provides substance.

#### 3. External (new — fetch + scaffold)

Fetch work from an external system, scaffold a spec, pre-fill what's available.

```bash
./speed/speed intake github #42
./speed/speed intake linear LIN-423
```

The adapter fetches fields (title, body, labels), picks the right template based on labels/type, pre-fills mechanically (title → Feature Name, body → Problem section), and opens for human editing. No intelligent drafting — just plumbing.

If the pre-fill isn't good enough, the human rewrites it. That's faster than reviewing and fixing an AI-drafted spec you don't trust.

---

## The Audit Agent

**Agent definition:** `speed/agents/audit.md`
**Model:** `support_model` (sonnet by default)

Validates a spec after the human writes it. Catches structural gaps, missing cross-references, and sizing problems before the spec enters the pipeline.

### When it runs

```bash
# Audit a single spec
./speed/speed audit specs/product/my-feature.md

# Audit before planning (integrated into speed plan)
./speed/speed plan specs/tech/my-feature.md
# → runs audit on the RFC (and linked PRD) before the Architect decomposes
```

### Input

- The spec file to audit
- The corresponding template (auto-detected from file location: `specs/product/` → PRD template, `specs/tech/` → RFC template, etc.)
- The product vision file (`specs/product/overview.md`)
- Existing specs in `specs/` (for cross-reference validation)
- For RFCs: the linked PRD (for coverage checking)

### Checks

1. **Structure** — All template sections present and non-empty. Flags headings with no content beneath them.
2. **Completeness** — No `<!-- TODO -->` markers or placeholder text left unfilled. Warns on sections that look thin (< 2 sentences for sections that need substance).
3. **Cross-references** — Linked specs exist and resolve. RFC references a PRD. Design spec references a PRD. Defect report's `Related Feature` link resolves.
4. **Consistency** — PRD user flows covered by RFC API surface. PRD success criteria map to testable outcomes. RFC data model supports the features described in the PRD.
5. **Sizing** — Flag specs that would likely produce 10+ tasks. Recommend splitting with suggested boundaries.

### Output

```json
{
  "status": "pass | warn | fail",
  "spec_type": "prd | rfc | design | defect",
  "issues": [
    {
      "severity": "error | warning",
      "section": "API Surface",
      "message": "PRD user flow 'invite friend' requires an API endpoint not defined in the RFC"
    }
  ],
  "sizing": {
    "estimated_tasks": 6,
    "recommendation": "ok | split",
    "split_suggestion": null
  }
}
```

### What the Audit Agent is NOT

- Not a drafter. It validates what the human wrote — it doesn't write for them.
- Not the Architect. The Architect decomposes specs into tasks. The Audit Agent checks specs are ready for decomposition.
- Not a style checker. It checks structural completeness and cross-spec consistency, not prose quality.

---

## Goals

- Establish a unified intake layer with multiple input modes (manual, templated, external)
- Define canonical spec templates (PRD, RFC, Design, Defect Report) as scaffolds for human authoring and structural contracts for agents
- Introduce the Audit Agent for validating specs before they enter the pipeline
- Design an integration adapter layer that fetches external work items and scaffolds specs from them
- Define a lightweight defect pipeline that is structurally different from the feature pipeline — less ceremony, more focused, regression-aware
- Introduce the Triage Agent for investigating and routing defect reports
- Push status back to external systems as work progresses through either pipeline
- Make `speed plan` the trust-building gate — the Architect reviews the RFC for feasibility and codebase fit before decomposing into tasks
- Keep specs as the canonical format — all paths produce markdown specs, agents always read specs

## Non-Goals

- Building a full project management system inside SPEED (Linear/JIRA already exist)
- Real-time sync with external systems (batch/on-demand is sufficient)
- Replacing the feature pipeline for complex work (defects that are actually missing features get escalated)
- Auto-discovering bugs from production monitoring or logs (future)
- Agent-drafted specs — the human writes specs (with their own LLM), SPEED validates and processes them

---

## Spec Templates

Four canonical templates that define the structure for each spec type. Templates serve three consumers: the Audit Agent (structural contract to validate against), the `speed new` command (blank scaffold), and human authors (structural reference).

### Template 1: PRD (Product Requirements Document)

**File:** `speed/templates/prd.md`
**Output:** `specs/product/{name}.md`
**Consumed by:** Architect (decomposition), Product Guardian (vision alignment), Plan Verifier (blind verification)

```markdown
# F{n}: {Feature Name}

## Problem
<!-- Why does this need to exist? What user pain does it solve? -->
<!-- Read by: Architect (decomposition), Product Guardian (vision alignment) -->

## Users
<!-- Which personas are affected? Reference overview.md personas. -->
<!-- Describe by their problems, not demographics. -->

## User Stories
<!-- As a {persona}, I want to {action}, so that {outcome}. -->
<!-- Read by: Architect (task decomposition), Plan Verifier (blind verification) -->
| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| | | Given... When... Then... | |

## User Flows
<!-- Step-by-step interaction sequences. One flow per key scenario. -->
<!-- Read by: Architect (task boundaries), Reviewer (behavior verification) -->

## Success Criteria
<!-- Measurable outcomes with concrete thresholds. Not vibes — numbers. -->
- [ ] Criterion 1
- [ ] Criterion 2

## Scope
### In Scope
- ...
### Out of Scope (and why)
- ...

## Dependencies
<!-- Which features must exist before this one? Explicit dependency graph. -->
<!-- e.g., "Requires F3 (Auth) user model and session API" -->

## Security & Controls
<!-- Authentication, authorization, data sensitivity, rate limiting, audit logging. -->
<!-- What data is stored? Who can access it? What needs encryption? -->

## Risks
<!-- What could go wrong? Severity + mitigations. -->
| Risk | Severity | Mitigation |
|------|----------|------------|
| | | |

## Open Questions
<!-- Unresolved decisions that block implementation. -->
```

**Key sections for each agent:**
| Agent | Needs | Why |
|-------|-------|-----|
| Architect | User Stories, User Flows, Success Criteria, Dependencies | Decomposes into tasks, derives acceptance criteria, orders by dependency |
| Product Guardian | Problem, Scope, Out of Scope | Prevents drift, enforces vision |
| Plan Verifier | Success Criteria, User Stories | Blind-checks whether the plan delivers what the spec requires |
| Reviewer | Success Criteria, User Flows | Checks code against intended behavior, not just task description |
| Audit Agent | All sections | Validates structural completeness, cross-references, sizing |

### Template 2: RFC (Technical Spec)

**File:** `speed/templates/rfc.md`
**Output:** `specs/tech/{name}.md`
**Consumed by:** Architect (primary input for task decomposition), Developer (implementation reference), Coherence Checker (interface verification)

```markdown
# RFC: {Feature Name}

> See [{product-spec}]({product-spec}) for product context.
> Depends on: [{dep}]({dep}).

## Basic Example
<!-- A concrete code snippet or API call showing the feature in action. -->
<!-- Grounds the reader before the detailed design. Omit if not applicable. -->

## Data Model
<!-- Tables, columns, relationships, constraints. -->
<!-- This becomes the contract source of truth. -->
<!-- Read by: Architect (contract generation), Coherence Checker (interface verification) -->

## State Machine
<!-- If applicable: valid transitions, triggers, side effects. -->

## API Surface
<!-- Endpoints, GraphQL types, mutations, queries. -->
<!-- Input types, return types, error cases. -->
<!-- Read by: Architect (task decomposition), Developer (implementation), Coherence Checker -->

## Validation Rules
<!-- Business logic constraints. What inputs are rejected? -->
| Field | Constraints |
|-------|-------------|
| | |

## Security & Controls
<!-- Auth requirements (which endpoints need auth? what roles?). -->
<!-- Data sensitivity (PII? encryption at rest?). Rate limiting. Audit logging. -->
<!-- Input sanitization. OWASP top 10 considerations for this feature. -->

## Key Decisions
<!-- Architectural choices and their rationale. -->
<!-- Read by: Plan Verifier (checks for semantic drift from stated rationale) -->
| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| | | | |

## Drawbacks
<!-- Why should we NOT do this? Implementation cost, complexity, maintenance burden. -->
<!-- Honest assessment. "There are no drawbacks" is never true. -->

## Search / Query Strategy
<!-- If applicable: indexing approach, query patterns, performance. -->

## Migration Strategy
<!-- If changing existing data: how do we get from A to B safely? -->
<!-- Sequence: migrations, feature flags, phased rollout. -->

## File Impact
<!-- Which files, modules, or services does this change touch? -->
<!-- Helps the Architect scope tasks and the Developer navigate the codebase. -->

## Dependencies
<!-- What must exist before this can be built? -->

## Unresolved Questions
<!-- What parts of the design are still TBD? What needs investigation? -->
```

**Key sections for each agent:**
| Agent | Needs | Why |
|-------|-------|-----|
| Architect | Data Model, API Surface, File Impact | Generates contract, decomposes tasks, declares files |
| Developer | Everything | Primary implementation reference |
| Plan Verifier | Key Decisions, Drawbacks | Checks for semantic drift from stated rationale |
| Coherence Checker | API Surface, Data Model | Verifies interfaces match across independent branches |
| Audit Agent | All sections | Validates against PRD coverage (user flows → API endpoints, features → data model) |

### Template 3: Design Spec

**File:** `speed/templates/design.md`
**Output:** `specs/design/{name}.md`
**Consumed by:** Developer (component implementation), Reviewer (visual/UX verification)

```markdown
# Design: {Feature Name}

> See [{product-spec}]({product-spec}) for product context.

## Pages / Routes
<!-- Which URLs? What does the user see at each step? -->

## Component Inventory
<!-- New and modified components. -->
<!-- Read by: Developer (file structure), Reviewer (completeness check) -->
| Component | Type | Parent | Props | Notes |
|-----------|------|--------|-------|-------|
| | new / modified | where it nests | | |

## Component Composition
<!-- How components nest. Tree structure showing containment. -->
<!-- e.g., ProfileCard → Avatar + NameBlock + StatRow -->

## States
<!-- Every component must account for all states. -->
<!-- Read by: Developer (implementation), Audit Agent (completeness) -->
### Empty State
<!-- What the user sees with no data. Must look intentional, not broken. -->
<!-- Include fallback values: no avatar → initials → generic icon. -->

### Loading State
<!-- Skeleton, spinner, or progressive reveal. Which parts load first? -->

### Populated State
<!-- Primary view with typical data. -->

### Error State
<!-- What happens when things fail. Error messages, retry affordances. -->

## Data Binding
<!-- What dynamic data populates each element? -->
<!-- e.g., "Name field displays user.displayName. Bio truncates at 280 chars." -->
<!-- This bridges design and implementation — don't leave it to the developer to guess. -->

## Interactions
<!-- User actions → system responses. Include transition durations and easing. -->

## Responsive Behavior
<!-- Specific layout changes at each breakpoint, not just "it stacks on mobile." -->

## Accessibility
<!-- Keyboard navigation order, ARIA roles, screen reader behavior, contrast ratios. -->

## Design Tokens
<!-- Reference globals.css token names, not raw values. -->
<!-- e.g., "Card background: surface-elevated" not "background: #ffffff" -->

## Figma Reference
<!-- Link to Figma file/frame, or FigmaMCP reference. -->
```

**Key sections for each agent:**
| Agent | Needs | Why |
|-------|-------|-----|
| Developer | Component Inventory, Composition, States, Data Binding, Design Tokens | Knows exactly what to build, how it nests, and with which tokens |
| Reviewer | States, Interactions, Accessibility | Verifies all states handled, interactions work, accessibility met |
| Audit Agent | All sections | Validates components cover PRD user flows, all states present, tokens valid |

### Template 4: Defect Report

**File:** `speed/templates/defect.md`
**Output:** `specs/defects/{name}.md`
**Consumed by:** Triage Agent (investigation and routing)

```markdown
# Defect: {Short Description}

**Severity:** P0-critical | P1-high | P2-moderate | P3-low
**Related Feature:** {link to spec, e.g., specs/product/f4-tribes.md}
**Reproducibility:** always | intermittent (N/10) | once
**Last Known Working:** {version, date, or commit where this worked — or "never worked"}

## Observed Behavior
<!-- What actually happens? Be specific. Include error messages verbatim. -->

## Expected Behavior
<!-- What should happen instead? Reference the spec if possible. -->

## Reproduction Steps
<!-- Numbered, sequential, from a known starting state. -->
1. Step 1
2. Step 2
3. Bug manifests

## Environment
<!-- Browser, OS, user state, data conditions. Anything relevant. -->

## Error Output
<!-- Console logs, network responses, stack traces. Copy-paste, don't paraphrase. -->

## Additional Context
<!-- Screenshots, screen recordings, related issues. -->
```

Intentionally lightweight. A defect report should take 2 minutes to fill out. The Triage Agent does the investigation — the reporter just describes symptoms. The key additions (reproducibility, last known working, error output) help the Triage Agent narrow its search without burdening the reporter.

---

## Defect Pipeline

A structured workflow for fixing bugs. Lighter than the feature pipeline because defects have lower ambiguity — the behavior exists, it's just wrong. Less decomposition, more diagnosis.

### Pipeline Shape

Triage is a router. Not all defects deserve the same process.

```
specs/defects/{name}.md
        │
   [TRIAGE] ─────────────────────────────────────┐
        │                                         │
        ├── trivial ──→ Fix → Gates ──────────────┤
        │                                         │
        ├── moderate ──→ Reproduce → Fix →        │
        │                 Gates → Review ─────────┤
        │                                         │
        └── complex ──→ Escalate                  │
                        (→ intake as feature)      │
                                                  ↓
                                            [INTEGRATE]
```

Three tiers, gated by complexity.

### Entering the Defect Pipeline

Defects reach the pipeline through intake:

```bash
# Scaffold a defect report from template
./speed/speed new defect invite-failure
# → blank template at specs/defects/invite-failure.md
# → human fills in the report (with their LLM)

# Scaffold from a GitHub issue labeled 'bug'
./speed/speed intake github #42
# → fetches issue, scaffolds specs/defects/issue-42-invite-failure.md
# → human reviews/edits the pre-filled report

# Run triage on an existing defect report
./speed/speed defect specs/defects/invite-failure.md

# Check status
./speed/speed status --defects
```

### Stage 1: Triage (New Agent)

**Agent definition:** `speed/agents/triage.md`
**Model:** `support_model` (sonnet by default)

**Input:** Defect report markdown + codebase read access (full read, no write) + related specs (auto-resolved from `Related Feature` field)

**Job:**
1. Find the relevant code — which files, which functions
2. Read the related spec to understand *intended* behavior
3. Determine: is this actually a bug, or is the reporter wrong about expected behavior?
4. Classify complexity: trivial, moderate, or complex
5. Identify blast radius — what else could break if this code changes?
6. For trivial/moderate: propose a fix approach
7. For complex: explain why this needs a spec and recommend escalation

**Output:**
```json
{
  "is_defect": true,
  "reported_severity": "P0 | P1 | P2 | P3",
  "defect_type": "logic | visual | data",
  "complexity": "trivial | moderate | complex",
  "root_cause_hypothesis": "Invite resolver doesn't check github_connected...",
  "affected_files": ["src/backend/app/graphql/mutations/tribe.py"],
  "blast_radius": "low | medium | high",
  "blast_radius_detail": "Isolated to invite flow, no other callers",
  "test_coverage": "existing | none",
  "related_spec": "specs/product/f4-tribes.md",
  "suggested_approach": "Add guard clause in resolve_invite checking...",
  "regression_risks": ["invite happy path", "tribe membership count"],
  "escalation_reason": null
}
```

**Not a defect → rejection:**
If `is_defect` is false, Triage explains why (e.g., "Working as designed per spec. The spec says X, the code does X. If the spec is wrong, this is a feature change."). Pipeline stops. User can override.

**Complex → escalation:**
If complexity is `complex`, Triage explains why and pre-populates a PRD template from the defect report (Problem → observed behavior, User Stories → reproduction steps, Success Criteria → expected behavior). The user completes the PRD and enters it through the feature pipeline.

**Key difference from Debugger:** Triage is *investigative* — works from human-described symptoms with no stack trace. The Debugger is *forensic* — explains why a known build failure happened.

**Key difference from Architect:** The Architect decomposes ambiguity into multiple tasks. Triage *reduces* ambiguity to a single root cause. If it can't, that's the signal to escalate.

**Key difference from Audit Agent:** The Audit Agent validates spec *structure and completeness*. Triage *investigates code* against a spec. Audit checks the report is well-formed; Triage investigates whether the reported behavior is actually a bug.

### Stage 2: Reproduce (Developer Agent, Focused Prompt)

**Runs for:** Moderate defects only
**Agent:** Developer (reused, with defect-specific system prompt)
**Model:** `support_model`

**Job:** Write a failing test that captures the bug. TDD red phase.

The test *is* the acceptance criterion. The Developer is explicitly instructed: "Write a test that fails demonstrating this behavior. Do not fix the bug."

**Output:** A branch with the failing test committed. Quality gates run lint + typecheck only (test gate skipped — the new test is expected to fail).

**Skip for trivial:** Fix is obvious and scoped. Adding a test during the Fix stage is sufficient.

### Stage 3: Fix (Developer Agent, Reused)

**Runs for:** All defects (trivial and moderate)
**Agent:** Developer (reused, with defect-specific system prompt)
**Model:** `support_model` (escalatable to `planning_model` on retry)

**Input:**
- Triage output (root cause, affected files, suggested approach)
- For moderate: the reproduce branch with the failing test
- Explicit instruction: "Minimal change. Fix the defect. Do not refactor, do not improve surrounding code, do not add features."

**Quality gates:** Run gates for the affected subsystem (from Triage's `affected_files`). Also run the related feature's test suite if identifiable from the `related_spec` field.

**Output:** Branch with the fix. All quality gates must pass, including the reproduction test (now green).

### Stage 4: Review (Reviewer Agent, Adapted Prompt)

**Runs for:** Moderate defects only
**Agent:** Reviewer (reused, with defect-specific prompt)

The defect Reviewer asks:
1. "Does this fix address the reported defect?"
2. "Does it introduce any new behavior beyond the fix?"
3. "Is the change minimal and scoped — no drive-by refactoring?"
4. "Are there obvious regressions introduced?"

**Skip for trivial:** A one-line fix that passes gates doesn't need review. Triage validated the approach. Gates passed.

### Stage 5: Integrate (Integrator, Reused)

Same as the feature pipeline. Merge the branch, run regression tests.

**Product Guardian for defects:** Optional. Runs only if the diff exceeds a size threshold (>100 lines changed or >3 files touched). A small, focused fix doesn't need vision alignment. A large diff that started as a "bug fix" does.

### What Runs When

| Tier | Triage | Reproduce | Fix | Gates | Review | Guardian | Integrate |
|------|--------|-----------|-----|-------|--------|----------|-----------|
| **Trivial** | Yes | No | Yes | Yes | No | No | Yes |
| **Moderate** | Yes | Yes | Yes | Yes | Yes | If large diff | Yes |
| **Complex** | Yes | — | — | — | — | — | — |

**Not used for defects:** Architect, Plan Verifier, Coherence Checker (single branch, nothing to cross-check).

### Defect State

```
.speed/defects/{name}/
  report.md              # Copy of the defect spec
  triage.json            # Triage Agent output
  state.json             # Runtime state
  logs/                  # Agent output logs
```

State transitions:
```
filed → triaging → triaged → reproducing → fixing → reviewing → integrating → resolved
                 ↘ rejected (not a defect)
                 ↘ escalated (pre-populates PRD, enters feature pipeline)
```

---

## External Adapters

External adapters are dumb plumbing. They fetch data from an external system, pick the right template, pre-fill what they can, and scaffold a spec for human editing. They also push status updates back as work progresses.

### Architecture

```
speed/integrations/
  github.sh         # GitHub Issues + PRs
  linear.sh         # Linear tickets
  jira.sh           # JIRA tickets
  figma.sh          # FigmaMCP design extraction
```

Each adapter implements two functions:

```bash
adapter_fetch()     # Pull raw data from external system → scaffold spec from template
adapter_sync()      # Push SPEED status → external system
```

The adapter fetches fields (title, body, labels, comments), classifies based on labels/type, scaffolds from the right template, and pre-fills mechanically. No intelligent drafting — the human reviews and edits.

### Adapter 1: GitHub Issues

**Priority:** First (project already lives on GitHub, lowest friction)
**Dependencies:** `gh` CLI

**Fetch:**
```bash
./speed/speed intake github #42
./speed/speed intake github #42 --as defect    # force type
./speed/speed intake github #42 --as feature   # force type
```

1. Reads issue via `gh issue view 42 --json title,body,labels,assignees,comments`
2. Classifies based on labels:
   - `bug`, `defect`, `fix` labels → defect template
   - `feature`, `enhancement` labels → PRD template
3. Scaffolds spec from template, pre-fills title and body into appropriate sections
4. Stores source reference: `<!-- source: github#42 -->`
5. Opens for human editing

**Sync (opt-in):**
At each pipeline stage transition, adapter comments on the source issue:

| Pipeline | Event | GitHub Action |
|----------|-------|--------------|
| Feature | Plan complete | Comment: task count, scope |
| Feature | Integrated | Close issue, summary comment |
| Feature | Guardian rejected | Comment: concern, label `needs-revision` |
| Defect | Triage complete | Comment: classification, root cause |
| Defect | Integrated | Close issue, summary comment |
| Defect | Escalated | Comment: explanation, label `needs-spec` |
| Defect | Rejected | Comment: explanation (do NOT close — human decides) |

### Adapter 2: Linear

**Priority:** Second
**Dependencies:** Linear API key

```bash
./speed/speed intake linear LIN-423
```

Field mapping: Title → spec title, Description → body, Priority → severity (defects), Labels → type hints, Comments → additional context.

**Sync:** Status transitions via API (In Progress, Done, Backlog) + comments at stage transitions.

```toml
[integrations.linear]
api_key_env = "LINEAR_API_KEY"
sync = true
team_id = "TEAM_ID"
```

### Adapter 3: JIRA

**Priority:** Third (only when an enterprise team needs it)
**Dependencies:** JIRA API key

```bash
./speed/speed intake jira PROJ-891
```

Field mapping: Summary → title, Description → body, Priority → severity, Issue Type → type hint, Epic Link → related feature, Components → subsystem hints.

**Sync:** JIRA transitions via REST API. Transition IDs are configurable (every JIRA instance has different workflow IDs).

```toml
[integrations.jira]
base_url = "https://company.atlassian.net"
api_key_env = "JIRA_API_KEY"
user_email_env = "JIRA_USER_EMAIL"
sync = true
transitions = { in_progress = "31", done = "41", backlog = "11" }
```

### Adapter 4: FigmaMCP

**Priority:** Fourth (highest value for design accuracy, most complex)
**Dependencies:** FigmaMCP server, Figma API access

```bash
./speed/speed intake figma "https://figma.com/file/abc123" --frame "Profile Page"
```

1. Connects to FigmaMCP to extract structured design data
2. Extracts: component tree, design tokens, component states, breakpoint hints
3. Scaffolds a design spec from template, pre-fills Component Inventory and Design Tokens sections
4. Flags token mismatches against `globals.css`
5. Opens for human editing

**Verification (separate command):**
```bash
./speed/speed figma-verify "https://figma.com/file/abc123" --frame "Profile Page"
```
Compares implementation against Figma source of truth during review. Separate from the intake flow.

**Sync:** One-directional. SPEED does not push back to Figma.

```toml
[integrations.figma]
mcp_endpoint = "http://localhost:3845"
token_env = "FIGMA_ACCESS_TOKEN"
```

---

## New Agents Summary

| Agent | Role | Input | Output | When |
|-------|------|-------|--------|------|
| **Audit** | Validate spec structure, completeness, cross-references | Spec file + template + project context | Audit report JSON | `speed audit`, `speed plan` |
| **Triage** | Investigate defect, classify complexity, route | Defect report + codebase read access | Triage analysis JSON | `speed defect` |

Both are new. Existing agents (Architect, Developer, Reviewer, etc.) are reused without changes — they already read specs, which is what these new agents validate/consume.

**Modified agent:** The Architect gains an RFC review responsibility during `speed plan` (see Human Gates).

---

## Spec Sizing

Large specs produce large task DAGs, and large task DAGs fail in predictable ways: more dependency edges, more coordination failures between branches, harder coherence checking, degraded Architect decomposition quality.

### Recommended limits

- **3-5 features per spec** (targeting 4-8 tasks from the Architect)
- **If a spec would produce 10+ tasks, it should be split**

### Enforcement: two layers

**1. Audit Agent flags during `speed audit`.** The Audit Agent estimates task count from the spec's scope (user stories, API endpoints, data model complexity). If the estimate exceeds 8 tasks, the audit warns and suggests split boundaries. The human can split the spec or proceed anyway.

**2. Architect flags during RFC review.** If the Architect's decomposition would produce more than 8 tasks, it stops and proposes a split before proceeding. This is a hard gate — the Architect reports the recommended split and `speed plan` exits. The human can override with `--allow-large` if they understand the risk.

The Architect's split recommendation includes:
- Proposed sub-features with names
- Which acceptance criteria go to which sub-feature
- Suggested dependency ordering between sub-features

### Why both layers

The Audit Agent catches sizing early — before the human invests in a detailed RFC. The Architect catches subtle cases that only emerge during decomposition (one feature that looks simple but expands into 12 tasks because the data model is complex). Early warning + hard gate.

---

## State & File Structure

### New directories

```
speed/
  templates/
    prd.md              # PRD template (new)
    rfc.md              # RFC template (new)
    design.md           # Design spec template (new)
    defect.md           # Defect report template (new)
    spec.md             # Existing generic template (kept)
  agents/
    audit.md            # Audit Agent definition (new)
    triage.md           # Triage Agent definition (new)
  integrations/         # External adapters (new)
    github.sh
    linear.sh
    jira.sh
    figma.sh

specs/
  defects/              # Defect reports (new)

.speed/
  defects/              # Defect runtime state (new)
```

### Configuration additions

```toml
# speed.toml

[integrations.github]
sync = true
close_on_resolve = true

[integrations.linear]
api_key_env = "LINEAR_API_KEY"
sync = true
team_id = "TEAM_ID"

[integrations.jira]
base_url = "https://company.atlassian.net"
api_key_env = "JIRA_API_KEY"
user_email_env = "JIRA_USER_EMAIL"
sync = true
transitions = { in_progress = "31", done = "41", backlog = "11" }

[integrations.figma]
mcp_endpoint = "http://localhost:3845"
token_env = "FIGMA_ACCESS_TOKEN"
```

---

## Decisions (Closed)

| Question | Decision | Rationale |
|----------|----------|-----------|
| Auto-number features in `speed new`? | No. Author sets the number. | Feature numbers are semantic (F4 = 4th in the vision), not sequential by creation order. |
| Severity vs. classification overlap? | Rename classification to `complexity`. | Different axes: severity = business impact (reporter sets), complexity = technical scope (Triage sets). A critical-severity bug can be trivial-complexity. |
| Integration sync frequency? | Per-stage transition only. | Heartbeats add complexity for marginal value. A 3-minute silence isn't a problem; a 10-minute one is a timeout issue. |
| FigmaMCP as review tool? | Separate command: `speed figma-verify`. | Keeps the review path clean. Optional dependency stays optional. |
| Defect-to-feature escalation? | Pre-populate a PRD from the defect report. | Problem, reproduction steps, and expected behavior map directly to PRD sections. Don't make the user re-type. |
| Template versioning? | Don't. | Agents parse markdown flexibly. Templates evolve. Old specs still work. Solve when it's a problem. |
| Agent-drafted specs? | No. Audit, don't draft. | The human already works with an LLM to write specs. A drafting agent produces generic output the human rewrites. An audit agent catches real gaps. SPEED scaffolds and validates; the human provides substance. |

---

## Human Gates

Every CLI command is a gate. The file system is the handoff. No new mechanism — this is the existing SPEED pattern applied to intake and defects.

### Feature flow

```
speed new prd my-feature            → scaffolds PRD from template, opens $EDITOR
  human writes PRD (with their LLM)
speed audit specs/product/X.md      → validates structure, completeness, sizing — stops
  human addresses any issues
speed new rfc my-feature            → scaffolds RFC from template, opens $EDITOR
  human writes RFC (with their LLM)
speed audit specs/tech/X.md         → validates RFC against PRD, checks coverage — stops
  human addresses any issues
speed plan specs/tech/X.md          → Architect reviews RFC, then decomposes into task DAG
  ├── RFC review passed             → prints task graph, stops
  └── RFC review flagged issues     → prints issues, stops (human fixes RFC, re-runs plan)
  human reviews task graph
speed verify                        → blind-checks plan, stops
speed run                           → executes tasks, stops
speed review                        → reviews diffs, stops
speed coherence                     → checks cross-branch consistency, stops
speed integrate                     → merges, stops
```

**The `speed plan` gate is the most critical.** The Architect reviews the RFC before decomposing it. This is where technical problems get caught before they cascade into a bad task DAG. The Architect checks:

1. **Feasibility** — Can this data model actually support the features in the PRD?
2. **Codebase fit** — Does the proposed schema conflict with or duplicate existing tables?
3. **Completeness** — Are there API endpoints in the PRD's user flows that the RFC doesn't define?
4. **Consistency** — Do the RFC's relationships match the PRD's feature descriptions?

If the Architect flags issues, `speed plan` stops and reports them. The human fixes the RFC and re-runs. If the RFC passes review, the Architect proceeds to task decomposition in the same invocation.

This is the trust-building moment. The human sees the Architect validate their technical decisions before committing to execution. Over time, the Architect's RFC reviews build confidence that the pipeline catches real problems early.

### Defect flow

```
speed new defect my-bug             → scaffolds defect report from template, opens $EDITOR
  human writes defect report (with their LLM)
speed audit specs/defects/X.md      → validates report structure, checks Related Feature link — stops
  human addresses any issues
speed defect specs/defects/X.md     → runs triage, prints analysis, stops
  human reviews triage (classification, root cause, approach)
  — trivial: triage auto-proceeds to fix
  — moderate: human confirms, fix proceeds
  — complex: triage pre-populates PRD, stops (enters feature flow)
speed run --defect X                → fix + gates + review, stops
speed integrate --defect X          → merges, stops
```

### Design principles

- **Every gate is a command boundary.** No implicit auto-chaining. The human decides when to proceed.
- **The file system is the handoff.** Intake writes specs to `specs/`. Triage writes analysis to `.speed/defects/`. The human reads files, edits if needed, runs the next command.
- **No approval prompts.** SPEED doesn't ask "proceed? [y/n]". Running the next command *is* the approval.
- **Override at the gate, not mid-pipeline.** If the Guardian rejects during `speed review`, the command finishes and reports the rejection. The human decides whether to revise the spec or re-run with `SKIP_GUARDIAN=true`.

---

## Implementation Priority

| Phase | What | Why First |
|-------|------|-----------|
| **1** | Spec templates + `speed new` command | Zero external deps, immediately useful, defines output formats for everything else |
| **2** | Audit Agent + `speed audit` command | Validates specs before pipeline, catches gaps early, no external deps |
| **3** | Triage Agent + defect pipeline | Completes the defect workflow, validates the template system with a real consumer |
| **4** | GitHub adapter | Project lives on GitHub, lowest friction, tests the adapter architecture |
| **5** | Linear adapter | Second adapter validates the plugin model |
| **6** | FigmaMCP adapter + `speed figma-verify` | Highest design value, most complex |
| **7** | JIRA adapter | Only when an enterprise team needs it |

---

## Out of Scope

- Auto-discovery of bugs from production logs, monitoring, or error tracking (Sentry, Datadog)
- Bi-directional Figma sync
- Integration with Notion, Shortcut, Asana, or other PM tools (pluggable architecture supports future additions)
- Defect prioritization queue or backlog management
- SLA tracking or defect resolution time metrics
- Integration authentication management (keys live in env vars)
- Agent-drafted specs — SPEED scaffolds and validates, the human writes (with their own LLM)
- `speed validate` for defect specs (defects reference a feature spec but don't have product/tech/design siblings — audit checks that the `Related Feature` link resolves, nothing more)
