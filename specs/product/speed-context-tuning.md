# Context Tuning

> See [speed-continuous-learning.md](../../working-docs/speed-continuous-learning.md) for system design.
> Depends on: [Observation Infrastructure](speed-observations.md), [Agent-Specific Synthesis](speed-synthesis.md), existing Layer 2 infrastructure (`lib/context/layer2.py`)

## Problem

Layer 2 of SPEED's context constructor selects files for each agent's prompt based on the Codebase Source Graph: import relationships, cluster membership, hop distance from declared files. The selection is structural — it follows edges in a graph. It doesn't know whether those files actually helped.

Task 2 of speed-security needed `lib/context_bridge.sh`, but Layer 2 didn't include it because it was 2 hops away and the hop limit was 1. The Developer had to discover the file through trial and error, costing a retry. Task 5 included `lib/context/utils.py` as a 1-hop neighbor — 450 tokens of context that the Developer never referenced. Across 8 features, `utils.py` appeared in 6 context packages and 0 diffs.

Layer 2 makes the same file selection decisions on run 10 as it did on run 1. The observation infrastructure tracks which files were provided and which were actually used; synthesis produces `context-learnings.json` with patterns like "always include context_bridge.sh when tasks touch lib/context/" and "exclude utils.py from context packages." Context tuning feeds these patterns back into Layer 2 so that file selection improves with experience.

This isn't about changing the import graph or the CSG structure. It's about calibrating the parameters that Layer 2 uses to traverse that graph: hop distances, tier assignments, inclusion/exclusion rules, and co-modification bundles. The graph stays the same; the traversal learns.

**Principle grounding:** G4 (right context, right format, right stage) — context tuning makes Layer 2's file selection adaptive rather than static. G5 (scale through context, not exploration) — learned exclusions prevent context pollution from growing with codebase size. P1 (learning is scaffolding) — every context tuning rule is pre-computed context that prevents the Developer from discovering file relationships through trial and error.

## Users

### Developer Agent (Primary Beneficiary)
Receives a context package for each task. When the package is right (all needed files, no noise), the Developer writes correct code on the first attempt. When files are missing, the Developer retries. When files are irrelevant, the Developer wastes context budget reading code that doesn't matter. Context tuning improves the hit rate.

### Context Assembly (Direct Consumer)
`layer2.py` reads `context-learnings.json` during file selection. The learnings modify traversal behavior: override hop distances for specific areas, exclude known-waste files, force-include co-modification partners, adjust tier assignments based on historical effectiveness.

### Engineering (Operator)
Sees fewer retries caused by missing context and better token budget utilization. Can review context-learnings.json to understand what the system has learned about file relationships.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| CT1 | As an operator, I want files that are consistently included but never used excluded from context packages so that token budget is spent on relevant files | Given `lib/context/utils.py` included in 6 context packages and referenced in 0 diffs, when context tuning processes this pattern, then `context-learnings.json` contains a learned exclusion for this file, and Layer 2 skips it in future packages | Must |
| CT2 | As an operator, I want files that are consistently needed but missing force-included so that fewer tasks retry due to missing context | Given `lib/context_bridge.sh` modified in 3 tasks but absent from all 3 context packages, when context tuning processes this pattern, then `context-learnings.json` contains a force-inclusion rule for this file when tasks touch `lib/context/`, and Layer 2 includes it in future packages | Must |
| CT3 | As an operator, I want co-modified files bundled together so that the Developer always sees both sides of a change | Given `lib/toml.py` and `templates/speed-toml.toml` co-modified in 100% of commits, when context tuning processes this pattern, then `context-learnings.json` contains a co-modification bundle, and Layer 2 includes both whenever either is in the task scope | Must |
| CT4 | As an operator, I want tier assignments calibrated by historical effectiveness so that files are shown at the right detail level | Given test files provided as skeleton led to fixture rewrites in 2 features, but full content eliminated the problem, when context tuning processes this pattern, then `context-learnings.json` contains a tier override: "test files at full content when task involves writing tests" | Should |
| CT5 | As an operator, I want hop distance calibrated per codebase area so that the traversal depth matches actual need | Given tasks in `lib/context/` where 2-hop files were referenced 60% of the time, and tasks in `lib/toml.py` where 1-hop was sufficient 100% of the time, then context-learnings.json contains per-area hop overrides | Should |
| CT6 | As an operator, I want hub files discounted in hop calculations so that they don't inflate traversal without adding signal | Given `__init__.py` files that inflate hop counts to 15+ files per hop but are never referenced in diffs, when context tuning identifies hub inflation, then hop calculations discount `__init__.py` as a hub node | Should |
| CT7 | As an operator, I want conditional inclusion rules based on task type so that different tasks get different file selections | Given "test files should be excluded when the task has no test requirements" and "migration files should include only the most recent 2 for data layer tasks," when context tuning applies these rules, then Layer 2 filters files conditionally based on task metadata | Should |
| CT8 | As an operator, I want token budget utilization tracked per agent so that I know when truncation is causing lost context | Given Developer prompts hitting the 80K budget and truncating Related Code in 3 of 8 features, then context-learnings.json flags this pattern and suggests rebalancing (prioritize Files You'll Modify over Related Code when budget is tight) | Should |
| CT9 | As an operator, I want context tuning rules to have staleness detection so that learned rules don't persist when the codebase changes | Given a learned exclusion for `utils.py` and a subsequent significant rewrite of `utils.py`, when staleness detection runs, then the exclusion is flagged as `possibly_stale` and reverted to default behavior until reconfirmed | Must |
| CT10 | As an operator, I want related spec context prioritized based on feature type so that the budget is allocated to what matters most | Given "related spec context improved first-attempt rate for 'extend existing' features but not 'build new' features," when a new 'extend existing' feature runs, then related spec context gets higher priority in the budget allocation | Could |

## User Flows

### Context tuning improving file selection

1. Features 1-4 ran. Observation infrastructure recorded context_miss and context_waste observations for each task
2. Synthesis processed observations into `context-learnings.json`
3. Feature 5 starts. Task 3 touches `lib/toml.py`
4. Layer 2 begins file selection: follows import graph from `lib/toml.py`
5. Layer 2 reads context-learnings.json:
   - Co-modification bundle: include `templates/speed-toml.toml` (always co-modified)
   - Learned exclusion: skip `lib/context/utils.py` (6 inclusions, 0 references)
   - Hop override: `lib/toml.py` area uses 1-hop (sufficient 100% of time)
6. Context package: `lib/toml.py` (full), `templates/speed-toml.toml` (full), relevant test files (full), 1-hop imports minus excluded files
7. Developer receives the package. Template is there (no retry for discovering it). Utils.py is absent (450 tokens saved for useful code)
8. Task passes on first attempt
9. Observation recorded: context_miss=0, context_waste=0 — the tuning worked

### Context tuning with stale rule

1. `context-learnings.json` contains a learned exclusion for `lib/context/utils.py`
2. A feature rewrites `utils.py` from a generic helper into a critical context utility (>50% lines changed)
3. Next synthesis cycle: staleness detection compares content hash, finds >50% change
4. Exclusion rule flagged as `possibly_stale` and reverted to default (include if within hop range)
5. Next task in `lib/context/`: `utils.py` is included again
6. If the Developer uses it: the exclusion was wrong, it stays reverted. If not: a new context_waste observation re-establishes the exclusion

### Budget utilization tracking

1. After 8 features, context-learnings.json tracks: "Developer prompts average 71K of 80K budget. Truncation in Related Code section for 3 features."
2. Operator reviews context-learnings.json: "Budget pressure comes from large test files in Related Code. Files You'll Modify never truncated."
3. Synthesis suggests: "When budget is tight, deprioritize Related Code test files in favor of Files You'll Modify completeness"
4. Layer 2 adjusts: for budget-constrained tasks, test files in Related Code are shown as skeleton instead of full content
5. Next feature: Developer prompt is 68K. No truncation. Related Code test files shown as skeleton (Developer can read them via existing file access if needed)

## Success Criteria

- [ ] `context-learnings.json` produced by synthesis contains learned exclusions, force-inclusions, co-modification bundles, tier overrides, and hop distance calibration
- [ ] Layer 2 reads `context-learnings.json` during file selection and applies the rules
- [ ] Learned exclusions: files included N times but referenced 0 times are excluded from future packages
- [ ] Force-inclusions: files absent from packages but present in diffs are force-included for relevant task scopes
- [ ] Co-modification bundles: files co-modified in 80%+ of commits are always included together
- [ ] Tier overrides: tier assignments (full/skeleton/signature) adjusted based on historical effectiveness data
- [ ] Hop distance: per-area hop overrides based on actual 2-hop file usage rates
- [ ] Hub discounting: `__init__.py` and similar hub files discounted in hop traversal calculations
- [ ] Conditional rules: file inclusion/exclusion conditioned on task metadata (test requirements, task type, affected area)
- [ ] Staleness detection: rules referencing significantly changed files are reverted to defaults
- [ ] Budget utilization: tracked per agent per feature, truncation patterns surfaced in context-learnings.json
- [ ] Context-learnings.json is consumed by Layer 2 only — never injected into agent prompts directly
- [ ] Layer 2 degrades gracefully: if context-learnings.json is missing or malformed, default behavior (import-graph traversal without learned rules) continues

## Scope

### In Scope
- `context-learnings.json` schema (learned exclusions, force-inclusions, co-modification bundles, tier overrides, hop calibration, conditional rules, budget utilization)
- Layer 2 integration: reading and applying context-learnings.json during file selection
- Staleness detection for context tuning rules
- Budget utilization tracking per agent per feature
- Hub file identification and discounting in hop calculations
- Conditional inclusion rules based on task metadata

### Out of Scope (and why)
- **CSG structure changes** — Context tuning calibrates traversal parameters, not the graph itself. The CSG (Layer 1) is rebuilt independently. Adding or removing edges in the import graph is a structural change, not a tuning change.
- **Agent prompt modifications** — Context tuning changes which files appear in the prompt, not how the prompt is structured. Injection of learnings into prompt sections is synthesis/injection's scope.
- **File content preprocessing** — Context tuning decides which files to include and at what tier. It does not modify file content (e.g., summarization, truncation of individual files). Content preprocessing is an existing Layer 2 responsibility.
- **Cross-project context patterns** — Context tuning is per-project. File selection patterns in one codebase don't transfer to another.

## Dependencies

- **Observation Infrastructure** ([speed-observations.md](speed-observations.md)) — Context_miss and context_waste observations are the raw data. Without observations, there's nothing to tune.
- **Agent-Specific Synthesis** ([speed-synthesis.md](speed-synthesis.md)) — Synthesis produces `context-learnings.json` from context-relevant observations. Context tuning consumes the file; synthesis produces it.
- **Layer 2** (`lib/context/layer2.py`) — The integration point. Layer 2 must read context-learnings.json and apply rules during file selection. Layer 2 must degrade gracefully when the file is absent.
- **CSG** (`lib/context/layer1.py`) — Context tuning consumes CSG cluster structure for per-area rules. The CSG must be built before context tuning rules can be scoped.

## Security & Controls

**Read-only for context-learnings.json.** Layer 2 reads the file; it never writes to it. Synthesis writes; Layer 2 reads. Separation of concerns prevents Layer 2 from self-modifying its tuning.

**No source code in tuning rules.** Rules reference file paths, tiers, and hop distances. No code content is stored in context-learnings.json.

**Graceful degradation is the primary safety control.** If context-learnings.json contains a wrong rule (e.g., excludes a needed file), the worst outcome is a retry — the same outcome as run 1 before tuning existed. The system never crashes, and bad rules are self-correcting: the resulting context_miss observation will override the exclusion in the next synthesis cycle.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Learned exclusion removes a file that's actually needed for a new type of task | Medium | Exclusions are scoped by codebase area. A file excluded for `lib/toml.py` tasks may still be included for `lib/context/` tasks. Self-correcting: the resulting context_miss observation overrides the exclusion. |
| Co-modification bundles inflate context packages when one file of the pair is large | Low | Bundles respect token budget. If adding the co-modified file would exceed budget, it's included as skeleton instead of full content. Budget enforcement overrides bundle rules. |
| Hub discounting is too aggressive (some `__init__.py` files contain real logic) | Medium | Discounting reduces weight in hop calculation, not complete exclusion. `__init__.py` files with significant logic (>50 lines) are not classified as hubs. |
| Tier overrides conflict with task-specific needs | Low | Task metadata takes precedence over general overrides. If a task explicitly requires full-content tests, the override is respected over the general "skeleton for tests" rule. |
| Context tuning adds latency to file selection | Low | Reading context-learnings.json is a single file read. Applying rules is a filter pass over the already-selected file list. Negligible compared to the AST parsing and CSG traversal that Layer 2 already performs. |

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should context-learnings.json be a file that Layer 2 reads at startup, or should it be passed as a parameter to Layer 2's file selection function? File read is simpler; parameter passing is more testable. | Determines the integration pattern between synthesis and Layer 2. | Open |
| Q2 | What's the threshold for "never referenced" to trigger a learned exclusion — 3 inclusions with 0 references, or more? Lower threshold learns faster but risks false exclusions. | Affects exclusion aggressiveness and self-correction frequency. | Open |
| Q3 | Should conditional inclusion rules be expressed declaratively (JSON rules) or procedurally (Python functions)? Declarative is safer and auditable; procedural is more flexible. | Determines how complex conditional rules can be. | Open |
