# Convention Discovery & Project Knowledge

> System design context: `working-docs/speed-continuous-learning.md` (internal working doc, not a spec).
> Depends on: [Observation Infrastructure](speed-observations.md), existing CSG infrastructure (`lib/context/layer1.py`, `lib/context/layer2.py`)

## Problem

SPEED produces correct code that doesn't belong. Tests pass, types check, logic is sound — but the Developer used raw `httpx.get()` when the project wraps all HTTP calls through `lib/api/client.py`. Test fixtures are inline when the project puts them in `conftest.py`. Error handling uses return codes when the project moved to exceptions two features ago.

A senior engineer on the team knows these patterns instinctively. Months of reading and writing code in the project built that knowledge. SPEED starts fresh every run. The Developer agent has Layer 2's code context (what files exist, what they contain) but not the interpretive layer on top: *how this project does things*.

Three sources of project-specific knowledge are missing from SPEED's context:

1. **Declared conventions** already codified in config files. Naming rules in ESLint's `naming-convention` or Ruff's `N` rules. Import ordering in isort profiles. Formatting in Prettier or Black. Type strictness in `tsconfig.json` or mypy. The team already made these decisions and wrote them down in machine-readable configs. SPEED just doesn't read them.

2. **Behavioral conventions** extractable from code but not captured in any config. Testing strategy (parametrize vs. TestCase, fixtures in conftest vs. inline). Error handling approach per architectural layer (exceptions in API, exit codes in CLI). File co-modification patterns (toml.py always changes with speed-toml.toml). Structural anatomy (new features need files in cmd/, agents/, tests/). Dependency wrapper patterns (HTTP calls go through client.py, not raw httpx). No linter config encodes these.

3. **Explicit knowledge** that lives in humans' heads. External API contracts, dependency footguns, design decisions not visible in code structure, infrastructure constraints. Code analysis can never discover "the payment service returns 202 for async operations — poll, don't retry."

Source 1 is a cold-start freebie: zero risk, high confidence, available on the first run before any features go through the pipeline. Source 2 requires code analysis and carries the P6 risk (convention discovery is high-risk, high-reward). Source 3 requires human authorship.

Config Reading extracts the first. Convention Discovery extracts the second. Project Knowledge captures the third. All three feed into agent prompts so that the Developer, Reviewer, and Architect produce output that reflects how this specific project works.

**Principle grounding:** P6 (convention discovery is high-risk, high-reward) — behavioral convention extraction (source 2) is the least proven component. Mitigated by confidence levels, observation corroboration, quality bars, and the fact that the highest-confidence conventions (source 1) come from configs, not discovery. P4 (human corrections are ground truth) — project knowledge is human-maintained, carrying the highest authority. P5 (staleness is silent wrongness) — conventions track confidence levels and evolution; project knowledge entries have staleness detection.

## Users

### Engineering (Operator)
Writes code alongside SPEED. Wants SPEED's output to follow the same conventions they follow. When the operator reviews SPEED's PR, convention-following code requires no corrections. Convention-violating code requires manual fixes, eroding trust. Also maintains project-knowledge.json with knowledge that code analysis can't extract.

### Developer Agent (Primary Consumer)
Receives conventions as implementation guidance: "Use relative imports within lib/context/. HTTP calls go through lib/api/client.py." Follows them when writing code, producing output that matches project patterns. Without conventions, defaults to generic best practices that may conflict with project norms.

### Reviewer Agent (Consumer)
Receives conventions as a validation checklist: "Flag if: direct httpx calls outside lib/api/client.py. Do NOT flag: return-code error handling in lib/api/legacy.py (known old pattern)." Catches real violations, avoids false alarms on known exceptions. Without conventions, applies generic quality standards that may over- or under-flag.

### Architect Agent (Consumer)
Receives conventions as structural constraints: "New pipeline stages require files in three locations (cmd, agents, assembly). The context layer uses relative imports." Decomposes tasks respecting the project's structure. Without conventions, may create task boundaries that cross architectural lines.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| C0 | As an operator, I want SPEED to read my existing linter/formatter configs so that it respects conventions my team already declared without rediscovering them | Given a project with any of the 16 supported config types (`.editorconfig`, `pyproject.toml`, `.eslintrc.*`, `.prettierrc`, `biome.json`, `tsconfig.json`, `.golangci.yml`, `clippy.toml`, `checkstyle.xml`, `.rubocop.yml`, `.clang-format`, `.clang-tidy`, `stylecop.json`, `.shellcheckrc`, etc.), when `speed learn --conventions` runs, then declared conventions (naming rules, import ordering, formatting, type strictness, banned dependencies) are extracted and written to conventions.json with confidence `established`. Works on first run with zero observation history (cold start). | Must |
| C1 | As an operator, I want SPEED to discover behavioral conventions from code that aren't captured in config files | Given a codebase with 20+ files, when `speed learn --conventions` runs, then conventions.json includes entries for testing strategy, error handling patterns, file co-modification, structural anatomy, and dependency wrapper usage, each with confidence level and canonical examples | Must |
| C2 | As an operator, I want conventions assigned confidence levels so that agents distinguish between universal rules and emerging trends | Given a convention entry, then it has a confidence field: `established` (90%+ adherence AND corroborated by a second data source, or config-derived), `emerging` (60-89% or 3+ observation log entries), `decaying` (pattern being replaced), or `conflict` (two patterns competing) | Must |
| C3 | As an operator, I want convention discovery to integrate with the observation log so that reviewer findings and human corrections strengthen or challenge discovered patterns | Given 3 `convention_violation` observations about missing isinstance checks, when convention discovery runs, then an `emerging` convention entry is created even if AST analysis alone doesn't find a consistent pattern | Must |
| C4 | As an operator, I want a human-maintained project-knowledge.json for knowledge that code analysis can't extract | Given external API contracts, dependency footguns, or design decisions, when the operator adds entries to project-knowledge.json, then those entries are included in agent prompts filtered by the `agents` and `applies_to` fields | Must |
| C5 | As an operator, I want project-knowledge.json seeded from existing artifacts so that I don't start from a blank file | Given a project with README, CLAUDE.md, CONTRIBUTING.md, ADR documents, `.env.example`, or inline comments containing "IMPORTANT:", "NOTE:", "HACK:", "ASSUMPTION:", "DO NOT", "NEVER", "ALWAYS", when `speed learn --seed-knowledge` runs, then draft entries are generated in project-knowledge-drafts.json for human review. (Linter/formatter configs are handled separately by `speed learn --conventions` Phase 0, not by seed-knowledge.) | Should |
| C6 | As an operator, I want conventions formatted differently for each consuming agent so that each gets conventions in a useful form | Given conventions.json with 15 entries, when the Developer prompt is assembled, then conventions appear as implementation guidance. When the Reviewer prompt is assembled, the same conventions appear as a flag/don't-flag checklist. When the Architect prompt is assembled, they appear as structural constraints | Must |
| C7 | As an operator, I want convention evolution tracked so that agents follow the current pattern, not the one with the most legacy examples | Given a codebase where error handling shifted from return-codes (features 1-3) to exceptions (features 4+), then conventions.json marks the old pattern as `decaying` with a note pointing to the replacement, and agents follow the exception-based pattern | Must |
| C8 | As an operator, I want convention conflicts documented rather than silently resolved so that I can make the call | Given two competing patterns in the same codebase area (e.g., 4 files use return codes, 3 use exceptions), then a `conflict` entry is created documenting both patterns, with auto-resolution attempted only when observation evidence is available | Must |
| C9 | As an operator, I want convention discovery to run incrementally after the first full scan so that it's fast on large codebases | Given a codebase with 200 files where 10 changed since last discovery, when convention discovery runs, then only the changed files are re-analyzed (unless cluster structure changed, which triggers a full rescan) | Should |
| C10 | As an operator, I want project-knowledge.json entries validated against the current codebase so that stale entries are flagged | Given a project-knowledge entry referencing a dependency version no longer in the lock file, when staleness detection runs, then the entry is flagged as potentially stale in project-knowledge-drafts.json for human review | Should |
| C11 | As an operator, I want conventions to meet a quality bar before inclusion so that agents aren't guided by vague or generic patterns | Given a discovered pattern "use meaningful names," then it is rejected (not actionable). Given "fixture functions follow make_<entity>() pattern," then it passes (actionable, specific, evidenced, scoped) | Must |
| C12 | As an operator, I want the system to prompt me when recurring failures suggest missing project knowledge | Given 3+ unexplained retries in tasks touching the payments module with no convention or code pattern explaining why, then the system generates a draft question in project-knowledge-drafts.json: "Is there an external API contract or dependency constraint the system should know about?" | Should |
| C13 | As an operator, I want convention discovery to run automatically when triggers are met, not on a fixed schedule | Given 50+ files changed since last discovery run, or 3+ features completed, or 5+ convention_violation observations accumulated, then convention discovery triggers automatically during the next `speed learn` run | Should |

## User Flows

### First convention discovery on a project

1. Operator runs `speed learn --conventions` on a project with 40 Python files
2. Phase 0 (config reading): reads linter/formatter configs found in the project (e.g., `pyproject.toml`, `.prettierrc`, `.editorconfig`, `eslint.config.js`). Extracts declared naming rules, import ordering, formatting preferences, type strictness, and banned dependencies. All marked `established`. No analysis needed — the team already codified these decisions
3. Phase A (mechanical): tree-sitter import analysis across test files detects test framework (e.g., 34/34 files import vitest), test style (describe/it vs test()), DOM testing library (@testing-library/react in 17/34), mocking approach (vi in 19/34), and file organization (separate `__tests__/` tree vs co-located). Git log shows file co-modification pairs (e.g., `lib/toml.py` and `templates/speed-toml.toml` co-modified in 12/12 commits)
4. Phase B (observation integration): reads observation log from 4 prior features. Finds 3 `convention_violation` entries about isinstance checks, 2 `human_override` entries replacing raw httpx with the project wrapper
5. Phase C (formatting and validation): each discovered pattern formatted into a convention entry via templates ("Use {pattern} in {scope}. {count}/{total} files follow this. Canonical example: {file}:{line}"), checked against quality bar (actionable? specific? evidenced? scoped?). Config-read conventions skip the quality bar (team already vetted them). Patterns that fail go to conventions-candidates.json
6. Output: conventions.json with 15 entries, each with confidence level, scope, and canonical example
7. Summary printed: "15 conventions (6 from config, 5 discovered established, 3 emerging, 1 conflict). 4 candidates rejected (too generic or insufficient evidence)"

### Convention discovery integrated with observations

1. After feature 5, the observation log contains 5 `convention_violation` entries about missing isinstance checks
2. Trigger condition met: 5+ convention_violation observations since last run
3. Convention discovery runs automatically during `speed learn`
4. Phase B finds the isinstance pattern: strong observation evidence, but AST shows only 60% of existing code follows it
5. Convention created with confidence `emerging`: "Validate dict types with isinstance before .get() calls"
6. On subsequent `speed run`, the Developer's prompt includes: "Validate dict types with isinstance before .get() calls (emerging convention, 3 reviewer findings + 2 human corrections)"

### Project knowledge from blank to populated

1. Operator runs `speed learn --seed-knowledge`
2. System scans README.md, CLAUDE.md, ADR docs, inline comments
3. Finds: "IMPORTANT: payment service returns 202 for async operations" in a code comment
4. Generates draft entry in project-knowledge-drafts.json with `source: seeded`
5. Operator reviews: accepts the payment entry, edits the description, discards 2 irrelevant entries
6. Accepted entries move to project-knowledge.json with `source: human`
7. On next `speed run`, the Developer's prompt includes the payment service constraint when working on tasks that touch `lib/api/payments.py`

### Stale project knowledge detected

1. Project-knowledge.json contains an entry referencing `stripe-api-v2`
2. Staleness detection runs during convention discovery
3. Lock file shows `stripe-api-v3` — the entry references a deprecated version
4. Draft flagged in project-knowledge-drafts.json: "Entry pk-stripe-v2 references stripe-api-v2 but the codebase now imports from stripe-api-v3. Is this entry still accurate?"
5. Operator reviews: updates the entry to reference v3 behavior

### Convention conflict detected

1. AST analysis finds 4 files in `lib/api/` use return-code error handling, 3 use exceptions
2. Git history shows return-code files were last modified in features 1-3, exception files in features 4-6
3. Convention discovery creates a `conflict` entry: "Error handling in lib/api/: return-code (decaying) vs. exception-based (emerging)"
4. Observation log shows the Reviewer flagged return-code style twice — auto-resolves: current = exception-based, decaying = return-code
5. Developer prompt includes: "Error handling in lib/api/: use exception-based. Return-code style in legacy.py and auth.py is an old pattern — do not follow it"

## Success Criteria

- [ ] `speed learn --conventions` runs convention discovery and produces conventions.json
- [ ] Convention entries include: id, convention text, scope, confidence level, canonical_example, evidence, exceptions, evolution tracking, tags, source (`config` or `discovered`)
- [ ] Confidence levels assigned correctly: `established` (config-derived, or 90%+ adherence AND corroborated by a second data source), `emerging` (60-89% or observation-backed), `decaying` (pattern being replaced), `conflict` (competing patterns)
- [ ] Config reading (Phase 0) extracts declared conventions from linter/formatter configs: naming rules, import ordering, formatting, type strictness, banned dependencies. All marked `established` with source `config`. Works on cold start with zero observation history.
- [ ] Supported config files (16 types covering all SPEED-supported languages): `.editorconfig`, `pyproject.toml` (Ruff/Black/Pylint sections), `.flake8`/`setup.cfg [flake8]`, `.eslintrc.*`/`eslint.config.*`, `.prettierrc`/`prettier.config.*`, `biome.json`, `tsconfig.json`, `.golangci.yml`, `clippy.toml`/`.clippy.conf`, `checkstyle.xml`, `pmd.xml`/`.pmd`, `.rubocop.yml`, `.clang-format`, `.clang-tidy`, `stylecop.json`/`.editorconfig` (C# sections), `.shellcheckrc`
- [ ] Discovery extracts 5 behavioral pattern categories not available in configs: file co-modification, testing strategy, error handling per layer, structural anatomy, dependency wrapper usage
- [ ] Mechanical extraction (Phase A) runs without LLM calls: tree-sitter import analysis, git log co-modification, CSG hub detection
- [ ] Observation integration (Phase B) incorporates convention_violation, reviewer_finding, and human_override observations from the observation log
- [ ] Template-based formatting (Phase C) converts raw patterns into convention entries without LLM calls. Templates: "Use {pattern} in {scope}. {count}/{total} files follow this."
- [ ] Entire pipeline is LLM-free. Zero cost per run, deterministic output (same codebase = same conventions)
- [ ] Quality bar applied to discovered conventions (Phases A-C). Config-read conventions (Phase 0) skip the quality bar — the team already vetted them
- [ ] Rejected patterns stored in conventions-candidates.json for potential future promotion
- [ ] Conventions formatted differently per consumer: Developer gets implementation guidance, Reviewer gets flag/don't-flag checklist, Architect gets structural constraints
- [ ] Convention evolution tracking marks old patterns as `decaying` with replacement references
- [ ] Convention conflicts documented with both patterns, auto-resolved when observation evidence is available
- [ ] Incremental discovery: re-analyzes only changed files after the first full scan (full rescan on cluster restructuring)
- [ ] project-knowledge.json schema defined with entry structure (id, knowledge, why_it_matters, applies_to, agents, tags, source, last_verified)
- [ ] `speed learn --seed-knowledge` generates draft entries from README, CLAUDE.md, ADRs, inline comments
- [ ] Seeded entries go to project-knowledge-drafts.json for human review, not directly to project-knowledge.json
- [ ] Staleness detection cross-references project-knowledge entries against current codebase (dependency versions, file paths, API references)
- [ ] System prompts human with draft questions when recurring failures have no code/convention explanation
- [ ] Convention discovery triggers automatically on: first run, 50+ file changes, 3+ features, CSG restructuring, or 5+ convention_violation observations
- [ ] Per-agent token budgets respected: Developer 2,000 tokens, Reviewer 2,000 tokens, Architect 2,000 tokens for conventions; 1,500 tokens per agent for project knowledge

## Scope

### In Scope
- Config reading (Phase 0) for declared conventions from linter/formatter configs
- Convention discovery pipeline (Phase A mechanical + Phase B observation + Phase C template formatting and validation) for behavioral conventions not in configs. Entire pipeline is LLM-free.
- conventions.json with confidence levels, scope, canonical examples, evolution tracking, and source (`config` or `discovered`)
- Per-agent convention formatting (Developer view, Reviewer view, Architect view)
- Convention conflict detection and auto-resolution when evidence supports it
- Incremental discovery with trigger conditions
- project-knowledge.json schema and entry structure
- project-knowledge-drafts.json for seeded entries, system-prompted entries, and staleness flags
- `speed learn --seed-knowledge` for bootstrapping from existing artifacts
- Staleness detection for project-knowledge entries
- System-prompted knowledge gaps from unexplained failures
- conventions-meta.json for incremental state (last run timestamp, files analyzed, cluster checksums)
- conventions-candidates.json for rejected patterns awaiting future promotion
- Injection into Developer, Reviewer, and Architect assembly functions

### Out of Scope (and why)
- **Formatting convention discovery** — Formatting is fully solved by existing tools (Black, Prettier, gofmt, rustfmt). SPEED reads the formatter config in Phase 0; it does not rediscover formatting rules from code. If a project has no formatter config, SPEED does not attempt to infer formatting preferences.
- **Agent-specific synthesized learnings (architect-learnings.json, developer-learnings.json, etc.)** — Separate feature (speed-synthesis). Conventions and project knowledge are knowledge sources; synthesis produces agent-specific views from observations. Different extraction paths, different consumers, different implementation phases.
- **Context tuning (adjusting Layer 2 file selection)** — Separate feature (speed-context-tuning). Conventions inform what code patterns to follow; context tuning decides what files to include. conventions.json may note file co-modification patterns, but Layer 2 integration is context-tuning's scope.
- **Enforcing conventions via linting** — Convention discovery describes patterns, it doesn't enforce them. Enforcement happens through agent prompt injection (agents follow conventions) and reviewer calibration (reviewer flags violations). Building custom lint rules from conventions is a separate tooling concern.
- **Cross-project convention sharing** — Conventions are per-project. A convention in project A ("use React hooks, not class components") has no bearing on project B ("Rust CLI with no frontend"). Cross-project patterns belong to model training, not project-level learning.

## Dependencies

- **Observation Infrastructure** ([speed-observations.md](speed-observations.md)) — Convention discovery's Phase B reads the observation log. Without observations, discovery relies solely on code analysis (Phase A), which works but produces weaker confidence signals. Observation integration strengthens emerging conventions with evidence from actual pipeline runs.
- **CSG infrastructure** (`lib/context/layer1.py`) — Cluster boundaries define convention scopes. Hub detection identifies dependency wrappers. CSG restructuring triggers a full rescan. Convention Discovery is a consumer of the CSG, not a modifier.
- **Assembly functions** (`lib/context/assembly.py`) — Convention and project knowledge injection points. `assemble_developer()`, `assemble_reviewer()`, and `assemble_architect()` need new optional parameters for conventions and project knowledge content.
- **Tree-sitter infrastructure** (`lib/context/treesitter_extract.py`) — Import analysis and AST extraction for test strategy detection, error handling patterns, and structural conventions. Already installed with 14 language grammars.

## Security & Controls

**Read-only codebase access.** Convention discovery reads source files (AST parsing), git history, and lock files. It does not modify any source files. Output is written only to `.speed/memory/`.

**Project-knowledge.json is operator-maintained.** The system never overwrites project-knowledge.json entries. It writes drafts to a separate file (project-knowledge-drafts.json) for human review. The human controls what enters the canonical knowledge file.

**No LLM calls.** The entire convention discovery pipeline is deterministic: config reading, tree-sitter AST, git log, observation log, template-based formatting. No external API calls. Conventions that require human interpretation belong in project-knowledge.json, not automated discovery.

**Local-only.** All convention and project knowledge files are stored locally. No external transmission.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Behavioral convention discovery produces wrong conventions that mislead agents | Medium | The highest-confidence conventions (naming, imports, formatting) come from config files, not discovery. Discovery risk is limited to behavioral patterns. Confidence levels prevent premature trust. Quality bar rejects vague or generic patterns. Observation integration corroborates or challenges. |
| Config files missing or misconfigured | None | Phase 0 produces empty results. Phases A-C still run. No degradation. Projects without configs simply get fewer `established` conventions. |
| AST analysis fails on unconventional code structures | Medium | AST parsing uses tree-sitter via ast-grep (`lib/context/treesitter_extract.py`). Unparseable files are skipped with a warning. Discovery degrades to fewer conventions, not crashes. |
| Project-knowledge.json becomes stale as the project evolves | Medium | Staleness detection cross-references entries against the current codebase. Stale entries are flagged for human review. `last_verified` field prompts periodic human review. |
| Convention discovery slow on large codebases | Low | Incremental discovery limits re-analysis to changed files. Trigger conditions prevent unnecessary runs. Entire pipeline is deterministic (no LLM calls, no API costs). |
| Human doesn't maintain project-knowledge.json | Low | The system works without project knowledge — conventions.json provides automated coverage. Project knowledge adds value but isn't required. System-prompted drafts reduce the burden by asking specific questions rather than expecting blanket documentation. |
| Too many conventions overwhelm the token budget | Low | Per-agent budget caps (2,000 tokens). Conventions ranked by evidence strength; lowest-evidence entries are cut when budget is exceeded. |

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should behavioral convention discovery (Phase A AST analysis) support languages beyond Python on day one? Config reading (Phase 0) is already multi-language (each config format is parsed independently). Git co-modification and import graph analysis are language-agnostic. Only AST pattern extraction is language-specific. | Determines implementation scope of Phase A2. Phase 0 and A1/A4 work for all languages on day one. | Open |
| Q2 | Should project-knowledge-drafts.json be auto-promoted to project-knowledge.json after N days without human review, or should drafts always require explicit human acceptance? | Affects the maintenance burden vs. knowledge freshness tradeoff. | Open |
| Q3 | How should conventions.json handle monorepos where different subdirectories follow different conventions? Scope field handles per-directory rules, but discovery needs to know subdirectory boundaries. | Affects convention accuracy in monorepo setups. | Open |
