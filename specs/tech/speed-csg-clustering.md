# Tech Spec: CSG Domain Clustering

> Product spec: [speed-csg-clustering.md](../product/speed-csg-clustering.md)
> Depends on: `lib/context/csg.py` (current `build_layer_c`), `lib/context/treesitter_extract.py`, git history access

## Overview

Replace `build_layer_c()` in `lib/context/csg.py` with a 6-layer file-level clustering pipeline. The current implementation runs Louvain on symbol-to-symbol edges from Layer B, producing 91% singletons because Layer B resolves 12.5% of imports. The replacement builds its own edge graph from 6 independent signal layers, clusters with Leiden+CPM, and outputs the same consumer interface.

```
Layer 0   git ls-files → file inventory + language classification
   ↓
Layer 2a  ast.parse (Python) + tsconfig regex (TypeScript) → import edges
   ↓      → co-import similarity edges (shared deps ≥ 2)
Layer 2b  Naming conventions → test/story ↔ component edges
   ↓
Layer 3   GraphQL bridge matching → cross-language edges
   ↓      REST route matching → cross-language edges
Layer 4   Package detection → metadata for labeling (no edges)
   ↓
Layer 6   git log co-change → IDF-weighted co-occurrence edges
   ↓      Degree capping: max 25 per node
Layer 5   TF-IDF orphan rescue → intra-package semantic edges
   ↓      Cluster labeling → top domain terms + path segments
   ↓
Leiden    CPM resolution sweep → clusters
   ↓      Recursive splitting → cap oversized clusters
Adopt     Singleton adoption → join neighbor's cluster (2/3 majority)
   ↓
Rescue    Directory rescue → join directory-majority cluster (2/3, min 2 siblings)
   ↓
Output    clusters, cluster_edges, symbol_to_cluster (unchanged interface)
```

## Input Contract

The new `build_layer_c` takes the same inputs as today plus the repo path (for git access and file reading):

```python
def build_layer_c(
    nodes: list[dict],
    edges: list[dict],
    repo_path: str = "",
) -> tuple[list[dict], list[dict], dict[str, str]]:
```

When `repo_path` is empty or the directory doesn't exist, falls back to the current Louvain implementation (graceful degradation).

## Output Contract

Unchanged. Returns `(clusters, cluster_edges, symbol_to_cluster)` matching the existing schema.

### Cluster

```python
{
    "id": "cluster_city_wiki_7",
    "label": "city/wiki",
    "symbols": ["travel-api/schema/mutations/admin.py::update_city", ...],
    "files": ["travel-api/schema/mutations/admin.py", "travel-web/components/city-wiki/city-wiki-attractions.tsx", ...],
    "internal_refs": 47,
    "external_refs": 3,
    "cohesion": 0.94,
}
```

### Inter-cluster edge

```python
{
    "from": "cluster_city_wiki_7",
    "to": "cluster_travel_api_3",
    "edge_count": 29,
    "symbols": [{"from": "admin.py::update_city", "to": "types.py::CityInput"}, ...]
}
```

### symbol_to_cluster

```python
{"travel-api/schema/mutations/admin.py::update_city": "cluster_city_wiki_7", ...}
```

The file-level clustering assigns all symbols in a file to the file's cluster. `symbol_to_cluster` is derived by mapping each Layer A symbol to its file's cluster.

## Pipeline Implementation

### Module: `lib/context/layer1_domain_clustering.py`

New module. `build_layer_c` in `csg.py` delegates to this module when `repo_path` is available.

### Layer 0: File inventory

```python
def _get_file_inventory(repo_path: str) -> list[str]:
    """Get code files via git ls-files, respecting .gitignore."""
```

Uses `git ls-files --cached --others --exclude-standard`. Filters to `CODE_EXTENSIONS` (`.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.rb`, `.rs`, `.go`, `.java`, `.c`, `.cpp`, `.cs`). Strips `SKIP_DIRS` (`node_modules`, `__pycache__`, `.venv`, `dist`, `build`) as safety net. Falls back to `os.walk` if not a git repo.

### Layer 2a: Compiler-native imports

```python
def _resolve_python_imports(repo_path: str, py_files: list[str]) -> list[tuple[str, str]]:
    """Python import resolution via ast.parse."""

def _resolve_typescript_imports(
    repo_path: str, ts_files: list[str],
    path_aliases: list[tuple[str, str, str]],
) -> list[tuple[str, str]]:
    """TypeScript import resolution via regex + tsconfig path aliases."""

def _find_tsconfig_paths(repo_path: str, ts_files: list[str]) -> list[tuple[str, str, str]]:
    """Find tsconfig.json path aliases, scoped to their directory.

    Returns list of (scope_dir, alias_prefix, resolved_target).
    Longest prefix match when tsconfigs nest.
    """
```

**Python:** `ast.parse` extracts `ImportFrom` and `Import` nodes. Module path converted via dot-to-slash + extension probing (`.py`, `/__init__.py`). Relative imports resolved against importing file's package.

**TypeScript:** Regex matches `import ... from '...'` (including multiline). Scoped tsconfig resolution: each `tsconfig.json` `compilerOptions.paths` entry maps to `(scope_dir, prefix, target)`. When resolving, the importing file uses the tsconfig from its longest matching ancestor directory. Extension probing: `.ts`, `.tsx`, `.js`, `.jsx`, `/index.ts`, `/index.tsx`.

**Co-import conversion:** Direct import edges are converted to co-import similarity edges. Files sharing ≥2 import targets get an edge weighted by Jaccard similarity × 3.0. Direct import edges are also added at weight 1.0.

### Layer 2b: Naming conventions

```python
def _find_naming_convention_edges(files: list[str]) -> list[tuple[str, str]]:
    """Match test/story files to components by filename transformation."""
```

Five patterns: `.stories` removal, `.test` removal, `.spec` removal, `test_` prefix strip, `_test` suffix strip. Case normalization tries lowercase, PascalCase-to-kebab, PascalCase-to-snake.

Scoped matching (stops at first match):
1. Same directory
2. Sibling directories (`__tests__/` next to `components/`)
3. Same package (monorepo-aware)
4. Global (only if exactly 1 unambiguous match)

Weight: 3.0. Reinforces existing edges rather than doubling.

### Layer 3: Cross-language bridges

```python
def _find_graphql_bridges(
    repo_path: str, py_files: list[str], ts_files: list[str],
) -> list[tuple[str, str]]:
    """Match Python @strawberry resolvers to TypeScript gql`` operations."""

def _find_rest_bridges(
    repo_path: str, py_files: list[str], ts_files: list[str],
) -> list[tuple[str, str]]:
    """Match Python @app.route to TypeScript fetch/axios calls."""
```

**GraphQL:** Extract `@strawberry.mutation`/`@strawberry.field` decorated function names (snake_case) from Python. Extract `mutation X`/`query X` from TypeScript `gql` template literals. Match via snake_case ↔ PascalCase conversion. Weight: 3.0.

**REST:** Extract `@app.route('/path')` from Python. Extract `fetch('/path')` / `axios.get('/path')` from TypeScript. Match by normalized URL path. Weight: 3.0.

### Layer 4: Package detection

```python
def _detect_packages(repo_path: str, files: list[str]) -> dict[str, str]:
    """Detect monorepo packages. Returns file → package_name mapping."""
```

Scans for `package.json`, `requirements.txt`, `setup.py`, `pyproject.toml`. Each file maps to its nearest package. Used for labeling and scoping TF-IDF (Layer 5). No edges created.

### Layer 5: TF-IDF semantic rescue + labeling

```python
def _build_semantic_edges(
    repo_path: str, files: list[str], orphans: set[str],
    file_to_package: dict[str, str], threshold: float = 0.4,
) -> tuple[list[tuple[str, str, float]], dict[str, list[str]]]:
    """TF-IDF cosine similarity edges for orphan files.

    Returns (edges, file_terms) where file_terms is used for labeling.
    """

def _label_cluster(
    cluster_files: list[str],
    file_terms: dict[str, list[str]],
    used_labels: set[str],
) -> str:
    """Generate cluster label from TF-IDF terms + path segments."""
```

**Orphan rescue:** Files with zero edges from Layers 2-6 get cosine similarity edges to other files in the same package (threshold 0.4, weight 0.5). Cross-package similarity suppressed.

**Labeling:** Top TF-IDF terms + path segments (3x weight for path segments). ~220 stop words covering React/JSX/DOM, CSS, UI libraries, theming, testing, generic programming, Python builtins, English stop words.

### Layer 6: Co-change with IDF

```python
def _build_cochange_graph(repo_path: str, files: list[str]) -> nx.Graph:
    """Build co-change graph from git log with IDF weighting."""
```

`git log --name-only` → file co-occurrence per commit. Edge weight: `co_count × avg_confidence × idf(f1) × idf(f2)`. IDF dampens hub files that appear in many commits. Degree cap: max 25 edges per node (keep highest weight).

### Clustering

```python
def _leiden_cluster(graph: nx.Graph, resolution: float) -> dict[str, int]:
    """Run Leiden with CPM resolution on the combined graph."""
```

**Resolution sweep:** Try `[0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5]`. Pick the resolution closest to √N clusters with the best MQ score.

**Recursive splitting:** Clusters exceeding max(40, 8% of files) are re-clustered at higher resolution. Up to 5 rounds.

**Post-clustering adoption:** Singletons with edges join their neighbor's cluster when 2/3+ of neighbor edges point to one multi-file cluster.

**Directory rescue:** Remaining singletons join the majority cluster of their directory siblings (2/3 threshold, minimum 2 siblings).

**Global degree cap:** Max 50 edges per node in the combined graph before clustering.

### Interface mapping

The pipeline operates on files. The consumer interface expects symbols. The mapping:

```python
def _map_files_to_symbols(
    file_clusters: dict[str, int],  # file → cluster_id
    nodes: list[dict],              # Layer A symbol nodes
) -> dict[str, str]:                # symbol_id → cluster_id_string
    """Map file-level clusters back to symbol-level for consumer compatibility."""
    symbol_to_cluster = {}
    for node in nodes:
        file_path = node["file"]
        cluster_id = file_clusters.get(file_path)
        if cluster_id is not None:
            symbol_to_cluster[node["id"]] = f"cluster_{cluster_id}"
    return symbol_to_cluster
```

All symbols in a file inherit the file's cluster assignment.

## Consumer Compatibility

| Consumer | Code location | Fields used | Changes needed |
|----------|--------------|-------------|----------------|
| `assembly.py` (Architect) | lines 331-387 | `clusters[].id`, `.label`, `.files`, `.cohesion`, `.internal_refs`, `.external_refs` | None |
| `decomposition_gate.py` | lines 164-213 | `clusters[].files`, `.id`, `cluster_edges[].from`, `.to`, `.edge_count` | None |
| `cross_task.py` | lines 80-143 | `nodes[].cluster` via `symbol_to_cluster` | None |
| Dashboard topology | `dashboard/backend/resolvers/topology.py` | `nodes[].cluster`, `edges` | None |
| Layer D stability | `csg.py:196-241` | `symbol_to_cluster` mapping | None |

## Quality Metric: Commit Coherence

```python
def measure_commit_coherence(
    repo_path: str,
    file_to_cluster: dict[str, int],
    max_commits: int = 200,
) -> dict:
    """Measure how well clusters predict real change sets.

    For each multi-file, non-merge commit:
      coherence = files_in_dominant_cluster / total_changed_files

    Returns summary statistics.
    """
```

Validated results:

| Codebase | Focused commits | Mean coherence | Median | ≥50% | <50% |
|----------|----------------|----------------|--------|------|------|
| travel-prod | 94 | 72.4% | 71.4% | 83% | 17% |
| find-your-tribe | 79 | 79.6% | 100% | 92% | 8% |

Coherence by commit size (travel-prod, focused):

| Size | Mean | Perfect (100%) |
|------|------|----------------|
| 2 files | 81.2% | 62.5% |
| 3-5 files | 80.4% | 50.0% |
| 6-10 files | 63.5% | 22.7% |
| 11-20 files | 64.1% | 20.0% |
| 21-30 files | 62.5% | 0% |

Low-coherence focused commits are consistently cross-cutting features (navigation overhauls, session timeout, database cleanup) — exactly the cases where the Architect should decompose into multiple tasks.

### Why not Domain Reach

Domain Reach (% of files in clusters spanning 2+ top-level directories) was considered and rejected. It measures cross-directory novelty, not task boundary quality. Loosening the directory depth to inflate the number is gaming the metric. Commit coherence directly answers the question clustering must serve: do the clusters predict real change patterns?

## File Impact

| File | Change |
|------|--------|
| `lib/context/layer1_domain_clustering.py` | **New.** 6-layer clustering pipeline (~750 lines) |
| `lib/context/csg.py` | Modify `build_layer_c()` to delegate to `layer1_domain_clustering.py` when `repo_path` available. Add `repo_path` parameter. ~10 lines changed |
| `tests/test_clustering.py` | **New.** 76 unit + integration tests covering all layers, consumer interface, fallback, and commit coherence validation |
| `requirements.txt` | Add `networkx`, `python-igraph`, `leidenalg` (`scikit-learn` already declared) |

## Testing Plan

### Unit tests (`tests/test_clustering.py`)

**Layer 0:**
- Git repo → files via `git ls-files`, respects `.gitignore`
- Non-git directory → falls back to `os.walk`
- `SKIP_DIRS` filtered in both paths

**Layer 2a:**
- Python imports resolve via ast.parse (dot-to-path, relative imports, `__init__.py`)
- TypeScript imports resolve via regex (multiline, scoped tsconfig aliases)
- Scoped tsconfig: `travel-mobile/@/components` resolves to `travel-mobile/components`, not `travel-web/components`
- Co-import: files sharing 2+ import targets get weighted edge
- External imports (`react`, `typing`) produce no edges

**Layer 2b:**
- `.stories.tsx` → component `.tsx` matched
- `test_booking.py` → `booking.py` matched
- `PascalCase.stories.tsx` → `pascal-case.tsx` via kebab conversion
- Ambiguous global match (7 `agency.py` files) → skipped
- Same-dir match preferred over global

**Layer 3:**
- GraphQL: `create_booking` (Python) ↔ `CreateBooking` (TypeScript) matched
- REST: `@app.route('/api/users')` ↔ `fetch('/api/users')` matched
- No false matches across unrelated operations

**Layer 4:**
- `package.json` detected as package root
- Files assigned to nearest package
- No edges created

**Layer 5:**
- Orphan files (0 edges) get TF-IDF edges to same-package files
- Cross-package TF-IDF edges suppressed
- Stop words filtered from label generation
- Labels contain domain terms, not framework tokens

**Layer 6:**
- Co-change edges weighted by IDF
- Hub files (many commits) get low IDF weight
- Degree cap enforced (max 25)
- Repos with <10 commits → empty co-change graph (no crash)

**Clustering:**
- Resolution sweep picks closest to √N clusters
- Recursive splitting caps oversized clusters
- Adoption moves singletons with unambiguous neighbor signal
- Directory rescue uses 2/3 majority + min 2 siblings
- Global degree cap applied before clustering

**Interface:**
- Output matches `(clusters, cluster_edges, symbol_to_cluster)` schema
- All symbols mapped via file-to-cluster
- Cluster fields: `id`, `label`, `symbols`, `files`, `internal_refs`, `external_refs`, `cohesion`
- Inter-cluster edges: `from`, `to`, `edge_count`, `symbols`

### Integration tests

- `build_layer_c(nodes, edges, repo_path="")` → falls back to Louvain (current behavior)
- `build_layer_c(nodes, edges, repo_path="/valid/repo")` → 6-layer pipeline
- Consumer code (`assembly.py`, `decomposition_gate.py`, `cross_task.py`) runs without modification on new output
- Dashboard topology renders new clusters

### Real data validation

| Check | travel-prod | find-your-tribe | SPEED |
|-------|-------------|-----------------|-------|
| Singleton % | <35% | <25% | <55% |
| Cross-language clusters | ≥5 | ≥2 | ≥1 |
| MQ | >0.7 | >0.7 | >0.5 |
| Largest cluster | <100 files | <40 files | <50 files |
| Commit coherence (mean, focused) | >70% | >75% | n/a (too few commits) |
| Labels domain-meaningful | spot check top 10 | spot check top 10 | spot check |

## Decisions

| ID | Question (from product spec) | Decision | Rationale |
|----|------------------------------|----------|-----------|
| Q1 | Replace Layer B or coexist? | Coexist. New pipeline builds its own edges; Layer B unchanged for other consumers. | Layer B's symbol-level resolution serves Layer D (blast radius, centrality). Replacing it requires re-validating all Layer D consumers. The 6-layer pipeline operates at file level for clustering; Layer B operates at symbol level for impact analysis. |
| Q2 | Integrate into `build_layer_c` or new module? | New module (`lib/context/layer1_domain_clustering.py`). `build_layer_c` delegates. | Keeps `csg.py` as the orchestrator. New module is independently testable. Named `layer1_` to avoid collision with CSG internal layer naming (Layer C) vs Context Constructor layer naming (Layer 1). |
