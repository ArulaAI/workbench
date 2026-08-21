# CSG Domain Clustering

> See [method-6-layer-domain-clustering.md](../../working-docs/method-6-layer-domain-clustering.md) for validated prototype and design decisions.
> See [tech-spec-csg-clustering-fix.md](../../working-docs/tech-spec-csg-clustering-fix.md) for edge quality root cause analysis.
> Depends on: CSG Layer A+B (symbol extraction and reference resolution), existing Layer 2 infrastructure (`lib/context/layer2.py`)

## Problem

Layer C of the Codebase Semantic Graph discovers domain clusters: groups of files that belong together conceptually and change together in practice. The Architect uses these clusters to draw task boundaries. Layer 2 uses the underlying edge graph to determine which files each developer agent receives. Layer D uses cluster membership to classify symbols as bridges (spanning domains) or stable (contained within one).

Layer C currently produces garbage. On travel-prod (1,123 files), it outputs 2,600 clusters with 91% singletons. On find-your-tribe (306 files), 1,059 clusters with 91% singletons. Every file is its own cluster. The Architect gets no domain signal: no "these 15 files form the auth domain," no "this feature spans 3 domains and needs coordination," no "splitting here would create 47 cross-task reference points."

The root cause is upstream: Layer B resolves 12.5% of Python imports and 0% of TypeScript imports. The reference graph feeding Louvain is near-random. No clustering algorithm can produce meaningful results from near-random edges. Detailed root cause analysis in `tech-spec-csg-clustering-fix.md`.

The cost is paid by the Architect and the Developer. The Architect guesses at task boundaries without structural evidence. When it guesses wrong, the Developer receives a task that spans multiple domains, burns turns exploring for files that should have been pre-loaded, and either produces code that doesn't integrate or exhausts its turn budget. Task 5 of the pipeline audit is this failure mode: the Developer hit 50 turns with zero output. Nothing in the system distinguished between "the task is hard" (complexity failure) and "the Developer lacked context" (pipeline failure).

A second cost is invisible: cross-language domain relationships. A Python GraphQL resolver (`create_booking`) and its TypeScript consumer (`gql`mutation CreateBooking``) serve the same feature, but no signal connects them. When the Architect decomposes "add verified flag to city attractions," it creates separate backend and frontend tasks with no awareness that the resolver and the component are two sides of the same domain. The frontend developer implements the UI without seeing the backend mutation that feeds it.

**Principle grounding:** G3 (scaffolding carries the weight) — domain clusters are pre-computed context that prevents the Architect from guessing and the Developer from exploring. G4 (right context, right format, right stage) — the Architect sees domain boundaries and coordination costs; the Developer sees pre-loaded files scoped to one domain. G5 (scale through context, not exploration) — clustering quality must not degrade with codebase size because it's computed from structural signals (imports, co-change, bridges), not exploration.

## Users

### Architect Agent (Primary Consumer)
Sees domain clusters when decomposing a spec into tasks. Uses cluster boundaries as candidate task boundaries. Uses inter-cluster edge counts to estimate coordination cost. A cluster with 47 internal references and 3 external connections is a natural single-task unit. A feature spanning 5 clusters with heavy inter-cluster edges needs careful dependency ordering.

### Layer 2 / Context Assembly (Infrastructure Consumer)
Uses the CSG edge graph (not clusters directly) to determine file content tiers: `files_touched` at full content, 1-hop neighbors at full content, 2-hop at skeleton. The edge graph that clustering is built on is the same graph Layer 2 traverses. Better edges mean better content tier assignments.

### Developer Agent (Indirect Beneficiary)
Does not interact with clusters directly. Benefits when the Architect draws task boundaries along cluster lines and Layer 2 loads the right files. A well-scoped task means the Developer writes correct code without exploration turns.

### Coherence Checker (Cross-Task Consumer)
Uses cross-task domain overlap to identify integration risks. When two tasks modify files in the same cluster, the Coherence Checker flags coordination requirements. Pre-computed cluster membership replaces manual inference from reading all diffs.

### Layer D / Impact Analysis (Downstream Consumer)
Uses cluster membership to classify symbols. A symbol whose edges span two clusters is a bridge (highest modification risk). A symbol contained within one cluster is stable. Bridge classification depends on cluster quality: garbage clusters produce garbage stability classifications.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| DC1 | As an Architect, I want to see which files form coherent domains so that I can align task boundaries with domain boundaries instead of guessing | Given a 1,123-file monorepo, when the CSG builds Layer C, then it produces clusters where 80%+ of 2-5 file focused commits have all changed files within one cluster (commit coherence) | Must |
| DC2 | As an Architect, I want cross-language domains visible so that I can decompose full-stack features into tasks that include both backend and frontend files | Given a Python GraphQL resolver and its TypeScript consumer, when Layer C clusters the codebase, then both files appear in the same cluster connected by GraphQL bridge edges | Must |
| DC3 | As an Architect, I want inter-cluster coordination costs quantified so that I can estimate the risk of splitting a feature across clusters | Given two clusters with 29 cross-boundary edges, when the Architect considers a decomposition, then the inter-cluster edge count and weight are available as coordination cost indicators | Must |
| DC4 | As a Developer, I want my task scoped to files that actually change together so that I don't spend turns discovering related files | Given a task aligned with a cluster boundary, when Layer 2 loads files, then files_touched + 1-hop covers 80%+ of the files I'll actually need to modify | Must |
| DC5 | As a Coherence Checker, I want pre-computed domain overlap between tasks so that I can identify integration risks without inferring them from diffs | Given two tasks that both modify files in the same cluster, when coherence checking runs, then the shared cluster membership and specific shared files are pre-computed in the cross-task analysis | Should |
| DC6 | As an operator, I want singleton clusters to represent genuinely unclusterable files, not resolution failures | Given a codebase with proper import resolution, when Layer C runs, then singletons are limited to config files, init markers, and cross-cutting utilities — not files that simply failed to resolve imports | Must |
| DC7 | As an operator, I want cluster labels to reflect domain concepts, not framework vocabulary | Given a cluster containing booking-related files, when the label is generated, then it reads "booking/payment" or "travel/booking" — not "div/flex" or "text/name" | Should |
| DC8 | As a Layer D consumer, I want bridge symbol classification based on real domain boundaries so that stability assessments are meaningful | Given a symbol whose references span two clusters, when Layer D classifies it, then it is marked as "bridge" only if the clusters represent genuine domain boundaries (not artifacts of resolution failure) | Must |

## User Flows

### Architect decomposes a full-stack feature

1. Operator runs `speed plan` on a spec: "Add verified flag to city attractions"
2. Layer 1 builds the CSG. Layer C produces clusters from 6 signal layers
3. The `[city/wiki]` cluster contains both Python resolvers (`mutations/admin.py`, `resolvers/activity.py`) and TypeScript components (`city-wiki-attractions.tsx`, `city-wiki-list.tsx`) — connected by GraphQL bridges and co-change
4. The Architect sees this cluster: 6 files, high cohesion, few external edges. Natural single-task unit
5. The Architect also sees 14 backend schema files in `[travel/api]` with 29 cross-cluster edges to `[city/wiki]`
6. Decomposition: Task 1 (travel/api: schema types + shared resolvers), Task 2 (city/wiki: resolver logic + frontend components). Task 2 depends on Task 1
7. Layer 2 builds context: Task 2's developer gets the Python resolver AND the TSX component as full content. No exploration needed for the cross-language connection
8. Developer implements the verified flag in both backend and frontend in one task. First attempt succeeds

### Architect decomposes without clustering (current state)

1. Same spec: "Add verified flag to city attractions"
2. Layer C produces 2,600 singleton clusters. No domain signal
3. The Architect guesses: separates backend and frontend into two tasks based on directory structure
4. Task 1: Python resolvers. Task 2: TSX components. No dependency declared (the Architect can't see the cross-language connection)
5. Task 2's developer gets only the TSX files. The Python resolver that controls the verified flag is not in context
6. Developer implements the frontend badge but doesn't know the resolver's field name or return shape. Explores the codebase for 8 turns, finds the resolver, modifies code to match
7. Task passes but cost 8 exploration turns + risk of mismatched field names

## Success Criteria

- [ ] Singleton ratio below 35% on travel-prod (1,123 files), below 25% on find-your-tribe (306 files)
- [ ] Cross-language clusters exist: clusters containing both Python and TypeScript files connected by GraphQL or REST bridges
- [ ] Commit coherence: 80%+ of focused 2-5 file commits have all changed files within one cluster
- [ ] Commit coherence: mean coherence above 70% across all focused commits (2+ files, non-WIP, ≤30 files)
- [ ] Cluster labels reflect domain concepts (booking, auth, city, messaging) not framework tokens (div, flex, props, component)
- [ ] MQ (Modularization Quality) above 0.7 on codebases with 300+ files
- [ ] No cluster exceeds 8% of total files (or 40 files, whichever is larger) after recursive splitting
- [ ] Consumer interface unchanged: `(clusters, cluster_edges, symbol_to_cluster)` with existing field schemas
- [ ] Layer D bridge classification uses cluster boundaries from the new Layer C without code changes
- [ ] Clustering completes in under 30 seconds for codebases up to 2,000 files

## Scope

### In Scope
- Replacement of `build_layer_c()` in `lib/context/csg.py` with 6-layer clustering
- Six signal layers: compiler-native imports (Python ast.parse, TypeScript tsconfig), naming conventions, cross-language bridges (GraphQL, REST), package detection, TF-IDF semantic rescue, co-change with IDF weighting
- Leiden+CPM clustering with recursive splitting for oversized clusters
- Post-clustering singleton rescue (adoption + directory-based)
- Cluster labeling from TF-IDF domain terms + path segments
- Commit coherence as the validated quality metric
- Consumer interface compatibility with existing assembly, decomposition gate, cross-task analysis, and dashboard

### Out of Scope (and why)
- **Layer A/B edge quality fixes** (quote stripping, module resolution, parent field) — prerequisite work documented in `tech-spec-csg-clustering-fix.md`. Must be completed before clustering integration, but is a separate change with its own verification criteria.
- **Layer 2 traversal changes** — Clustering changes the domain map, not how Layer 2 traverses it. Hop distance calibration and content tier logic remain unchanged. Context tuning (separate spec) addresses traversal optimization.
- **Layer D algorithm changes** — Layer D's stability classifier reads `symbol_to_cluster` unchanged. Better clusters produce better classifications automatically. No code changes needed in Layer D.
- **Decomposition gate threshold tuning** — The gate's cross-cluster edge threshold (>15 = fail) may need recalibration with real clusters instead of singletons. Follow-up, not part of the clustering implementation.
- **Symbol-level clustering** — The prototype operates at file level, not symbol level. File-level clustering matches the Architect's task boundary granularity (tasks are scoped to files, not individual functions). Symbol-level resolution is a possible future enhancement.

## Dependencies

- **Layer A+B edge quality** (`tech-spec-csg-clustering-fix.md`) — The 6-layer pipeline includes its own import resolution (Python ast.parse, TypeScript regex + tsconfig). The existing Layer B resolution (substring matching, 12.5% rate) is replaced, not consumed. However, the Phase 0 fixes (quote stripping, module path matching) should be applied to Layer B first for other consumers of the reference graph.
- **Git history** — Co-change layer (Layer 6) reads `git log` for file co-occurrence. Repos with fewer than 50 commits produce sparse co-change signals. Clustering degrades gracefully (other 5 layers still contribute).
- **NetworkX + igraph + leidenalg** — Python dependencies for graph construction and Leiden clustering. Must be added to SPEED's Python environment.
- **tree-sitter** (existing) — Layer A/B already depends on tree-sitter for extraction. No new dependency.

## Security & Controls

**No new data surfaces.** Clustering operates on file paths, import edges, and git history. No source code content is stored in cluster definitions. Cluster labels are derived from file path segments and identifier names, not code content.

**Deterministic output.** Given the same codebase at the same git commit, clustering produces identical results. The Leiden algorithm uses a fixed seed. No LLM calls in the clustering pipeline.

**Graceful degradation.** If git history is unavailable (Layer 6), clustering runs on the remaining 5 layers. If tsconfig.json is missing (Layer 2a), TypeScript files cluster based on co-change and semantic signals. Each layer is additive; no single layer failure blocks clustering.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Bad cluster boundary splits tightly-coupled files into separate tasks | Medium | The Architect's DAG declares task dependencies. Even if files land in different clusters, Layer 2's 1-hop content loading includes cross-cluster neighbors. Retrospective validation shows all cross-cluster commit file pairs are reachable via 1-hop. |
| Over-decomposition: Architect creates more tasks than necessary because clusters are too fine-grained | Low | Recursive splitting has a floor (40 files or 8% of codebase). The Architect can merge adjacent clusters when their inter-cluster edges are dense. Task count issue, not a correctness issue. |
| Co-change layer dominates on repos with messy git history (large commits, WIP dumps) | Medium | IDF weighting dampens hub files. Degree capping (max 25 per node) limits co-change connectivity. On travel-prod, co-change contributes 42% of edges — significant but not dominant. |
| Leiden+CPM dependency adds Python packages that may conflict with existing environment | Low | `leidenalg` and `igraph` are mature packages with stable APIs. Already validated in `.venv`. Pin versions in requirements. |
| Clustering quality varies across codebase types (monorepo vs single-package, Python-only vs polyglot) | Medium | Validated on 3 codebases: Python/TS monorepo (travel-prod), Python/TS dual-package (find-your-tribe), and shell/Python tool (SPEED). Commit coherence ranged 72-80%. Additional validation on open-source repos recommended before production. |

## Open Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should the 6-layer import resolution replace Layer B entirely, or coexist alongside it? The prototype's resolver is Python-specific (ast.parse) and TypeScript-specific (regex + tsconfig). Layer B handles 11 languages via tree-sitter. | Determines whether Layer B's cross-file edges improve or are replaced. Layer B's non-Python, non-TypeScript resolution is untested. | Open |
| Q2 | The prototype runs as a standalone Python script. Should it integrate into the existing `build_layer_c()` entry point, or should Layer C be extracted into its own module (`lib/context/clustering.py`)? | Affects code organization and testability. Separate module is cleaner but requires refactoring call sites. | Open |
| Q3 | Commit coherence validation requires access to git history at build time. Should it run as a CI check, a post-build verification, or only during development? | Running it on every build adds ~10 seconds. Running it as a CI check catches regressions. Running it only during development saves time but misses drift. | Open |
| Q4 | The decomposition gate's cross-cluster threshold (>15 = fail) was set when clusters were singletons. With real clusters, cross-cluster edge counts will be higher. What's the right threshold? | Affects decomposition gate false-positive rate. Too low = every multi-domain task fails. Too high = no protection. | Open |
