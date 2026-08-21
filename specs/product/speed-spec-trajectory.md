# Spec Trajectory

> See [speed-continuous-learning.md](../../working-docs/speed-continuous-learning.md) for system design.
> Depends on: [Observation Infrastructure](speed-observations.md), [Agent-Specific Synthesis](speed-synthesis.md), existing feature storage (`.speed/features/`)

## Problem

After 7 features on the same codebase, the Architect decomposes feature 8 from scratch. It doesn't know that `lib/context/assembly.py` was modified in 6 of the last 7 features and is accumulating technical debt. It doesn't know that spec scope definitions for the context layer are consistently too broad, leading to oversized tasks. It doesn't know that "add pipeline stage" features always decompose into 5 tasks following the same cmd → agent → assembly → wiring → tests pattern.

Every completed feature leaves behind a full execution record: `contract.json` (the Architect's plan), task JSON files (what happened), `spec-alignment.json` (what the spec got right and wrong), observations (retries, findings, corrections). Reading these records in sequence reveals how the project evolves: which areas are volatile, which modules are accumulating risk, what feature shapes recur, and where specs are unreliable.

Spec Trajectory reads the sequence of completed features and produces `spec-trajectory-learnings.json` with structured knowledge about project evolution. The Architect uses this to decompose better (reuse proven shapes, avoid known failure modes, size tasks for volatile areas). The Developer and Reviewer use subsets of it (active areas, risk accumulation, regression zones) to calibrate effort and scrutiny.

**Principle grounding:** P1 (learning is scaffolding) — trajectory data is pre-computed context about how the project evolves, replacing the need for agents to infer patterns from raw code. P5 (staleness is silent wrongness) — risk accumulation and regression zones flag areas where accumulated changes may have degraded code quality. P3 (failure memory first) — spec quality signals and decomposition precedents encode where prior specs and plans fell short.

## Users

### Architect Agent (Primary Consumer)
Plans task decomposition for new features. When the Architect knows that "pipeline stage" features follow a 5-task pattern, that the context layer causes retries when tasks exceed 3 files, and that specs for the CLI layer get overridden 60% of the time, decomposition starts from precedent rather than first principles.

### Developer Agent (Consumer)
Receives active areas and risk accumulation data. When the Developer knows that `assembly.py` has been extended by 6 features with no refactor and that coherence issues appeared in the last 2 features touching it, it approaches modifications to that file with more caution and writes more targeted tests.

### Reviewer Agent (Consumer)
Receives regression zones. When the Reviewer knows that `lib/shared.sh` was modified by features 3, 5, and 7 with feature 7 partially reverting feature 5's additions, it checks for unintended reversions in the current feature's changes to that file.

### Engineering (Operator)
Sees the project's evolution trajectory: which areas are hot, where risk is accumulating, and which spec patterns are unreliable. Helps the operator decide whether to write tighter specs for the context layer, schedule a refactoring feature for assembly.py, or split the next CLI feature into smaller pieces.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| ST1 | As an operator, I want active and mature codebase areas identified across features so that the Architect can size tasks appropriately for volatile vs. stable code | Given 5+ completed features, when spec trajectory runs, then `spec-trajectory-learnings.json` contains active areas (modified in 50%+ of recent features) and mature areas (modified in 1-2 features only, patterns stable). The Architect decomposes tasks smaller in active areas | Must |
| ST2 | As an operator, I want feature shape taxonomy extracted from prior features so that the Architect can reuse proven decomposition patterns | Given 3+ features where "pipeline stage" features followed the same 5-task pattern, when a new spec matches the shape, then `spec-trajectory-learnings.json` contains the pattern: task count, task boundaries, clusters touched, retry outcomes. The Architect reuses the pattern rather than decomposing from scratch | Must |
| ST3 | As an operator, I want spec quality signal tracked per codebase area so that the Architect knows which parts of the spec to trust | Given tech specs where scope definitions for the context layer were consistently too broad (overridden by the Architect or Developer in 3+ features), then `spec-trajectory-learnings.json` records: "Context layer specs: scope definitions consistently too broad. Plan defensively." The Architect adjusts | Must |
| ST4 | As an operator, I want risk accumulation flagged so that areas collecting technical debt are visible before they become crises | Given `lib/context/assembly.py` extended by 6 features with no refactor, function count growing, coherence issues in the last 2 features, then `spec-trajectory-learnings.json` flags it as high-risk-accumulation with evidence. Agents touching it scope tasks smaller and write more tests | Must |
| ST5 | As an operator, I want dependency evolution tracked across features so that the Architect knows which modules have increasing blast radius | Given `assembly.py` went from 2 consumers in feature 1 to 7 consumers by feature 7, then `spec-trajectory-learnings.json` records the trend: "Becoming critical path. Modifications have increasing blast radius." The Architect decomposes tasks touching it as smaller, isolated changes | Should |
| ST6 | As an operator, I want cross-feature regression zones identified so that the Reviewer checks for unintended reversions | Given `lib/shared.sh` modified by features 3, 5, and 7, where feature 7 partially reverted feature 5's additions, then `spec-trajectory-learnings.json` records the regression zone. The Reviewer explicitly checks for reversions in the next feature touching it | Should |
| ST7 | As an operator, I want spec gap patterns surfaced so that the Architect proactively fills recurring blind spots | Given context layer specs never mention token budget implications (discovered during implementation in 3 features), then `spec-trajectory-learnings.json` records: "Context layer specs: never specify token budget implications." The Architect adds budget considerations proactively | Should |
| ST8 | As an operator, I want decomposition precedents linked to related spec context so that the Architect sees how similar features were decomposed | Given related spec compression identifies 2 past specs similar to the current one, when the Architect receives trajectory data, then it sees how those features decomposed: task count, boundaries, retry outcomes, and failure modes. "Both 'add pipeline stage' features decomposed into 5 tasks. Task 3 (assembly) caused retries both times due to missed imports." | Should |

## User Flows

### Architect receiving trajectory context

1. Operator writes a product spec for a new pipeline stage feature
2. `speed plan` triggers synthesis, which runs spec trajectory analysis
3. The Architect receives `spec-trajectory-learnings.json` content in its "Project History" section
4. The trajectory data shows: "Pipeline stage features: 5-task pattern (cmd → agent → assembly → wiring → tests). Assembly task caused retries in 2 of 3 prior pipeline features due to missed imports. Context layer is active (modified 6 of last 7 features). Scope definitions for context layer specs are consistently too broad."
5. The Architect decomposes into 5 tasks following the proven pattern, sizes the assembly task smaller (3 files max), and adds an explicit import-update step

### Developer receiving volatility data

1. Developer is assigned a task modifying `lib/context/assembly.py`
2. Assembly function includes trajectory subset in "Learned Patterns" section: "assembly.py: modified by 6 features, function count grew from 4 to 12, coherence issues in last 2 features. HIGH RISK. Write targeted tests for integration points."
3. Developer writes more careful code with explicit tests for the integration surface

### Reviewer receiving regression zones

1. Reviewer checks task modifying `lib/shared.sh`
2. Assembly function includes trajectory subset in "Review Calibration" section: "shared.sh: regression zone. Feature 7 partially reverted feature 5's additions. Check for unintended reversions."
3. Reviewer explicitly diffs the current change against features 5 and 7's changes to shared.sh

### Risk accumulation prompting operator action

1. Operator runs `speed learn --summary`
2. Summary includes trajectory data: "Risk accumulation: assembly.py (high — 6 features, no refactor, coherence issues increasing)"
3. Operator creates a refactoring spec for assembly.py before the next feature that touches it

## Success Criteria

- [ ] `spec-trajectory-learnings.json` produced after 3+ features contain active areas, mature areas, and feature shape taxonomy
- [ ] Active areas defined as: modified in 50%+ of last 5 features. Mature areas: modified in 1-2 features only
- [ ] Feature shape taxonomy groups features by structural similarity (task count, cluster coverage, file patterns)
- [ ] Decomposition precedents include: task count, task boundaries, clusters touched, retry outcomes for each prior feature matching the current shape
- [ ] Spec quality signal tracked per codebase area: which spec sections are consistently accurate vs. consistently overridden
- [ ] Risk accumulation scored per module: features touched, function growth, coherence issue trend, refactor history
- [ ] Dependency evolution tracked: consumer count trend per module across features
- [ ] Regression zones identified: modules touched by 3+ features where later features partially reverted earlier changes
- [ ] Spec gap patterns surfaced: spec sections consistently absent for specific codebase areas
- [ ] Trajectory data injected into Architect (full), Developer (active areas + risk), Reviewer (regression zones)
- [ ] Per-agent token budget: Architect 2,000 tokens, Developer 500 tokens (subset), Reviewer 500 tokens (subset)
- [ ] Graceful degradation: fewer than 3 features → no trajectory data, no crash, pipeline continues

## Scope

### In Scope
- Spec trajectory analysis pipeline reading `.speed/features/*/` metadata
- `spec-trajectory-learnings.json` with active areas, mature areas, feature shapes, decomposition precedents, spec quality, risk accumulation, dependency evolution, regression zones, spec gap patterns
- Injection into Architect, Developer (subset), and Reviewer (subset) assembly functions
- `speed learn --trajectory` for manual invocation
- Automatic trigger during `speed learn` when 3+ features exist

### Out of Scope (and why)
- **Modifying specs based on trajectory data** — Trajectory informs agents that consume specs, it doesn't rewrite specs. Spec authoring is a human responsibility, with trajectory data helping the human write better specs.
- **Cross-project trajectory** — Feature shapes in a Python CLI project have no bearing on a React frontend project. Trajectory is per-project.
- **Predicting feature complexity** — Trajectory provides historical data ("similar features took 5 tasks"). Predicting future complexity from that data is speculative and outside scope.
- **Automated refactoring triggers** — Risk accumulation flags areas for human attention. Automatically creating refactoring tasks is a product decision beyond the learning system's scope.

## Dependencies

- **Feature storage** (`.speed/features/`) — Contract.json, task JSON files, spec_path, state.json. These are the primary data source. They already persist after integration.
- **Observation Infrastructure** ([speed-observations.md](speed-observations.md)) — Retry counts, coherence issues, and verify findings per feature provide the quality signals that trajectory aggregates across features.
- **Spec alignment** (`.speed/context/spec-alignment.json`) — Spec claim validation status (confirmed, missing, divergence) provides the spec quality signal.
- **CSG** (`lib/context/csg.py`) — Cluster structure for grouping file-level signals into area-level patterns. Symbol count and edge count for dependency evolution tracking.
- **Assembly functions** (`lib/context/assembly.py`) — Injection point. Architect's "Project History" section, Developer's "Learned Patterns" section, Reviewer's "Review Calibration" section already accept learnings strings.

## Security & Controls

**Read-only feature access.** Trajectory reads `.speed/features/*/` metadata files. It does not modify feature artifacts, task JSON, or any pipeline state.

**No external data.** All trajectory data is derived from local feature execution records and the local CSG. No network calls, no external APIs.

**Risk accumulation is advisory.** Risk scores inform agents and operators. They do not block pipeline execution or reject features. A high-risk module still gets built; agents just approach it more carefully.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Feature shape taxonomy overfits to a small sample (3-5 features) | Medium | Shapes require 2+ matching features to be surfaced. Single-occurrence patterns are stored but not injected into prompts until a second match confirms the shape. |
| Risk accumulation score misleads on intentionally-extended modules | Medium | Risk score components are transparent (features touched, function growth, coherence trend). The Architect sees the evidence, not just the score. If a module is intentionally growing, the operator can annotate it in project-knowledge.json. |
| Spec quality signal is wrong when specs intentionally changed during implementation | Low | Spec quality measures override rate, not correctness. If a spec was intentionally revised, the override still happened. The signal is "plan defensively for this area" — valid regardless of whether the override was a spec error or a deliberate pivot. |
| Trajectory data becomes stale after a major refactoring | Medium | Trajectory uses the last 5 features by default, not all-time history. A major refactor naturally ages out old patterns within 2-3 features. Risk accumulation resets when a refactor feature is completed (detected via high line-count delta with reduced function count). |

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should feature shape matching use structural similarity (task count + cluster overlap) or semantic similarity (spec text embedding)? Structural is deterministic but may miss matches where different task counts implement similar features. Semantic catches more matches but requires an LLM call. | Determines whether trajectory is LLM-free or requires a model call for shape matching. | Open |
| Q2 | How many recent features should the "active area" window consider? 5 features is a reasonable default, but a project with 50 features might want a wider window while a project with 6 features might want narrower. | Affects sensitivity of active/mature classification. | Open |
| Q3 | Should regression zone detection use git-level diff analysis (actual revert detection) or observation-level signals (coherence issues between features)? Git analysis is precise but expensive. Observation signals are cheaper but approximate. | Determines accuracy and cost of regression detection. | Open |
