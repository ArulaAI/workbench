---
title: The Codebase Semantic Graph
description: A multi-layer graph that captures what a codebase means, how it clusters, and what breaks when you change it.
sidebar:
  order: 4
---

A senior engineer decomposing a feature doesn't think in files. They think in relationships: the `User` model is referenced by 15 downstream symbols, the auth module's 6 files form a tight cluster with 47 internal references and only 3 external connections, and `process_payment` is called from both `checkout_handler` and `webhook_receiver`.

An agent without this information sees files and text. It can grep for symbols, but it can't know which clusters of code should stay together, which modifications carry risk, or how changing one symbol ripples through the rest of the system. Building that understanding through exploration burns turns.

The Codebase Semantic Graph (CSG) computes this understanding from static analysis before any agent runs. tree-sitter parses every source file into an AST; graph algorithms (networkx) extract structure and relationships. No LLM. Deterministic. Four layers, each built from the one below.

## Four layers, one through-line

Follow the `User` model through all four layers to see what each one adds.

### Layer A: Symbol

Every defined symbol in the codebase becomes a node: classes, functions, methods, types, constants. ORM model classes carry schema annotations (table name, columns, foreign keys, relationships).

For `User`, Layer A captures:

| Property | Value |
|----------|-------|
| Class | `User` in `src/backend/models/user.py`, inheriting from `Base` |
| Columns | `id` (Integer, PK), `email` (String, not null), `team_id` (Integer, nullable) |
| Foreign key | `team_id` → `teams.id` |
| Relationship | `team` → `Team` (many-to-one) |

The old pipeline had a separate symbol index and a separate schema snapshot. The CSG unifies both as properties on graph nodes.

### Layer B: Reference

Layer B adds edges between Layer A nodes. These edges capture call sites, imports, type references, and attribute access across the codebase.

For `User`, Layer B reveals:

- `create_user` in `auth/service.py` **instantiates** `User`
- `register` in `api/users.py` **calls** `create_user`
- `charge` in `billing/service.py` **references type** `User`
- `user.py` **imports** `Base` from `models/base.py`

Layer A tells you `User` exists. Layer B tells you `User` is created by the auth service, exposed through the user API, and referenced by billing. The difference is between a file listing and structural understanding of the codebase.

### Layer C: Domain

Community detection (Louvain algorithm) on the Layer B reference graph discovers **domain clusters**: groups of symbols that are densely connected internally and sparsely connected externally.

`User` lands in the `auth` cluster:

| Metric | Value |
|--------|-------|
| Symbols | `User`, `create_user`, `authenticate`, `auth_middleware`, and 12 others |
| Files | `models/user.py`, `auth/service.py`, `auth/middleware.py`, and 3 more |
| Internal references | 47 (within cluster) |
| External references | 3 (crossing cluster boundary) |
| Cohesion | 0.94 |

A cohesion of 0.94 means splitting this cluster across tasks would create 47 cross-task coordination points. The Architect sees this number and keeps the cluster together.

The **coordination cost** of any proposed decomposition is computable: sum the cross-cluster edges that would span task boundaries. Minimum coordination cost points to the optimal decomposition.

### Layer D: Impact

Graph analysis on Layer B edges computes per-symbol risk metrics.

For `User`:

| Metric | Value | Meaning |
|--------|-------|---------|
| Blast radius | 23 | Changing `User` can transitively affect 23 other symbols |
| Centrality | 0.72 | High betweenness centrality; `User` bridges domain clusters |
| Dependents | 15 | Fifteen symbols directly reference `User` |
| Stability | `bridge` | High centrality, crosses domain boundaries, highest modification risk |

Compare to a helper function like `format_date`: blast radius 0, centrality 0.01, stability `volatile`. The Reviewer receives these numbers alongside the diff and adjusts scrutiny accordingly. A change to a bridge symbol with blast radius 23 gets a different level of review than a change to a leaf function with blast radius 0.

## What the CSG enables

The individual layers are established techniques. Applying them to AI agent orchestration is new. Four capabilities emerge from the combination:

| Capability | How it works | Who uses it |
|-----------|-------------|-------------|
| Coordination cost optimization | Cross-cluster edge counts quantify the coordination overhead of any task decomposition. The Architect minimizes this cost when drawing task boundaries. | Architect |
| Graph-distance context scoping | The [context pipeline](/docs/context-pipeline/) selects what each agent sees based on structural proximity in the reference graph: full content for files touched and 1-hop neighbors, skeletons for 2-hop, nothing beyond. | Layer 2 (all agents) |
| Risk-proportional review | Blast radius and centrality set review intensity per change. The Reviewer sees "blast radius 23, stability bridge, verify these 8 downstream consumers" alongside the diff. | Reviewer |
| Impact-aware decomposition | High-centrality symbols (bridges between domains) require downstream coordination when modified. The Architect sees this before creating task boundaries. | Architect |

## Research foundations

The CSG's layers draw from established research. The combination into a multi-layer semantic graph designed for AI agent orchestration is novel.

| Layer | Foundation | Key work |
|-------|-----------|----------|
| A (Symbol) | Compiler symbol tables | Standard since the 1960s; extended with ORM schema annotations |
| B (Reference) | Call graphs and use-def chains | Allen & Cocke (1976); Aider's repo map uses similar tree-sitter extraction |
| C (Domain) | Community detection | Blondel et al. (2008), the Louvain algorithm; Mancoridis et al. (1999), software clustering |
| D (Impact) | Change impact analysis | Weiser (1981), program slicing; Freeman (1977), betweenness centrality |
| Multi-layer | Code property graphs | Yamaguchi et al. (2014), combined AST + control flow + dependence graphs for vulnerability detection |

## Built with tree-sitter

The entire CSG is built from [tree-sitter](https://tree-sitter.github.io/tree-sitter/): one parser infrastructure, 100+ language grammars, proper AST access. Each source file is parsed once. Multiple queries against the same AST feed both the CSG and [file skeletons](/docs/context-pipeline/#building-the-index).

tree-sitter is maintained by Zed (previously GitHub) and powers Zed, Neovim, Helix, Aider, and Repomix.

For the full JSON structure, build pipeline, and performance characteristics, see the [Architecture: Context Pipeline](/docs/architecture/context-pipeline/).
