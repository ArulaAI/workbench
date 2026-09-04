"""Codebase Semantic Graph (CSG) — Layer 1, Artifact 2.

Four-layer graph representing the codebase's structural and semantic
relationships:

  Layer A — Symbol Layer: every defined symbol (class, function, method, etc.)
  Layer B — Reference Layer: resolved call/import/type/access edges
  Layer C — Domain Layer: community clusters (6-layer Leiden pipeline, Louvain fallback)
  Layer D — Impact Layer: blast_radius, centrality, stability per symbol

Usage:
    from lib.context.csg import build_csg
    graph = build_csg(project_root, project_map, extractions)
    # graph is a dict matching semantic-graph.json schema

Tech spec: tech-spec-context-constructor.md → Artifact 2 (CSG section)
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

try:
    from networkx.algorithms.community import louvain_communities
    HAS_LOUVAIN = True
except ImportError:
    HAS_LOUVAIN = False

from .layer1_domain_clustering import _classify_language
from .treesitter_extract import ExtractionResult, SymbolDef, Reference
from .utils import git_head_hash, now_iso, write_json, read_json


# ── Symbol ID construction ───────────────────────────────────


def symbol_id(file_path: str, symbol_name: str, parent: str | None = None) -> str:
    """Build a unique symbol ID: {file_path}::{parent.symbol_name} or {file_path}::{symbol_name}."""
    if parent:
        return f"{file_path}::{parent}.{symbol_name}"
    return f"{file_path}::{symbol_name}"


# ── Layer A: Symbol Layer ────────────────────────────────────


def build_layer_a(
    extractions: dict[str, ExtractionResult],
) -> tuple[list[dict], list[dict]]:
    """Build Layer A: symbol nodes and structural edges.

    Args:
        extractions: dict of rel_path → ExtractionResult

    Returns:
        (nodes, structural_edges) where nodes are symbol dicts and
        structural_edges are contains/inherits/implements edges.
    """
    nodes: list[dict] = []
    edges: list[dict] = []

    # Index: symbol_name → list of symbol IDs (for base class resolution)
    name_to_ids: dict[str, list[str]] = defaultdict(list)

    for rel_path, result in extractions.items():
        for defn in result.definitions:
            sid = symbol_id(rel_path, defn.name, defn.parent)

            node = {
                "id": sid,
                "name": defn.name,
                "kind": defn.kind,
                "file": rel_path,
                "line": defn.line,
                "signature": defn.signature,
                "decorators": defn.decorators,
                "parent": symbol_id(rel_path, defn.parent) if defn.parent else None,
                "inherits": [],
                "implements": [],
            }

            # Schema annotation (ORM models)
            if rel_path in extractions:
                schema = extractions[rel_path].schema_annotations.get(defn.name)
                if schema:
                    node["schema"] = {
                        "table_name": schema.table_name,
                        "columns": schema.columns,
                        "foreign_keys": schema.foreign_keys,
                        "relationships": schema.relationships,
                    }

            nodes.append(node)
            name_to_ids[defn.name].append(sid)

            # Structural edge: contains (parent → child)
            if defn.parent:
                parent_id = symbol_id(rel_path, defn.parent)
                edges.append({
                    "from": parent_id,
                    "to": sid,
                    "type": "contains",
                })

            # Structural edges: inherits
            for base in defn.base_classes:
                # Try to resolve base class to a symbol ID
                base_name = base.split(".")[-1]  # Handle dotted names
                candidates = name_to_ids.get(base_name, [])
                if candidates:
                    # Prefer same-file, then first match
                    target = candidates[0]
                    for c in candidates:
                        if c.startswith(rel_path + "::"):
                            target = c
                            break
                    edges.append({
                        "from": sid,
                        "to": target,
                        "type": "inherits",
                    })
                    node["inherits"].append(target)
                else:
                    # Unresolved base class — record with raw name
                    unresolved_id = f"unresolved::{base_name}"
                    edges.append({
                        "from": sid,
                        "to": unresolved_id,
                        "type": "inherits",
                    })
                    node["inherits"].append(unresolved_id)

            # Structural edges: implements
            for iface in getattr(defn, "implements", []):
                iface_name = iface.split(".")[-1]
                candidates = name_to_ids.get(iface_name, [])
                if candidates:
                    target = candidates[0]
                    for c in candidates:
                        if c.startswith(rel_path + "::"):
                            target = c
                            break
                    edges.append({
                        "from": sid,
                        "to": target,
                        "type": "implements",
                    })
                    node["implements"].append(target)
                else:
                    unresolved_id = f"unresolved::{iface_name}"
                    edges.append({
                        "from": sid,
                        "to": unresolved_id,
                        "type": "implements",
                    })
                    node["implements"].append(unresolved_id)

    return nodes, edges


# ── Layer B: Reference Layer ─────────────────────────────────


def _build_symbol_index(nodes: list[dict]) -> dict:
    """Build lookup indices for symbol resolution.

    Returns dict with:
        by_id: {symbol_id: node}
        by_name: {name: [symbol_ids]}
        by_file: {file_path: [symbol_ids]}
        imports: {file_path: {imported_name: source_module}}
    """
    by_id: dict[str, dict] = {}
    by_name: dict[str, list[str]] = defaultdict(list)
    by_file: dict[str, list[str]] = defaultdict(list)

    for node in nodes:
        by_id[node["id"]] = node
        by_name[node["name"]].append(node["id"])
        by_file[node["file"]].append(node["id"])

    return {
        "by_id": by_id,
        "by_name": by_name,
        "by_file": by_file,
    }


def _resolve_reference(
    ref_name: str,
    ref_file: str,
    index: dict,
    import_map: dict[str, dict[str, str]],
) -> str | None:
    """Resolve a reference name to a symbol ID.

    Resolution strategy (first match wins):
    1. Same-file definitions
    2. Imported symbols (follow import edges)
    3. Global name match (single match only — ambiguous = unresolved)
    """
    # Strip common prefixes for calls (e.g., "self.method" → "method")
    clean_name = ref_name
    if "." in clean_name:
        # For attribute access like obj.method, try the last segment
        parts = clean_name.split(".")
        clean_name = parts[-1]
    if clean_name.startswith("new "):
        clean_name = clean_name[4:]

    # 1. Same-file definitions
    file_symbols = index["by_file"].get(ref_file, [])
    for sid in file_symbols:
        node = index["by_id"][sid]
        if node["name"] == clean_name:
            return sid

    # 2. Imported symbols
    file_imports = import_map.get(ref_file, {})
    if clean_name in file_imports:
        source_module = file_imports[clean_name]
        # Try to find the symbol in the source module's file
        candidates = index["by_name"].get(clean_name, [])
        for sid in candidates:
            node = index["by_id"][sid]
            if source_module in node["file"]:
                return sid

    # 3. Global name match (only if unambiguous within the same language).
    # A same-named symbol in an unrelated language can never actually be
    # this reference's target — there's no import or call mechanism that
    # crosses that boundary. Without this guard, an unresolved name that
    # happens to be globally unique (e.g. a React component's own
    # `isNew` property matching a Java entity's `isNew()` method, and
    # nothing else in the repo sharing that name) resolves as if it were
    # a real call, producing a spurious cross-language relationship.
    #
    # NOTE: this strategy is NOT a reliable proxy for "less certain"
    # evidence, even though it's the most permissive of the three — Java
    # (and similarly-scoped languages) never emits an import statement
    # for a same-package sibling class, so the overwhelming majority of
    # legitimate intra-package references resolve here, not via strategy
    # 2. An earlier attempt to tag this strategy's matches "weak" and
    # downgrade the resulting relationship to an INFERRED tier was
    # reverted after validating against real PetClinic/Workbench builds:
    # it mislabeled ~100% of relationships as INFERRED, because it
    # conflated "no explicit import" with "uncertain," when for
    # same-package access the former is simply how the language works,
    # not a weaker claim. See RELATIONSHIP_EVIDENCE_TYPE.
    ref_lang = _classify_language(ref_file)
    candidates = index["by_name"].get(clean_name, [])
    same_lang_candidates = [
        sid for sid in candidates
        if _same_language(ref_lang, ref_file, index["by_id"][sid]["file"])
    ]
    if len(same_lang_candidates) == 1:
        return same_lang_candidates[0]

    return None


# Header/impl-split "other"-bucket languages (C, C++, Objective-C/C++)
# where a declaration and its definition routinely live in files with
# different extensions — the single most common "other"-language
# same-language reference shape there is. .h is deliberately shared
# across all of them rather than assigned to just one: a header's own
# extension alone never says which of these it belongs to.
_C_FAMILY_EXTENSIONS = frozenset({".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".m", ".mm"})


def _same_language(ref_lang: str, ref_file: str, candidate_file: str) -> bool:
    """True if candidate_file is plausibly the same language as ref_file.

    _classify_language only distinguishes python/typescript/java/ruby/go;
    everything else (C, Rust, Kotlin, ...) collapses into "other". For
    that bucket, fall back to comparing raw extensions so two genuinely
    different "other" languages don't get treated as a match either —
    except within the C-family group above, where different extensions
    on both sides is the normal, expected pattern (a function declared
    in foo.h and defined in foo.c), not a cross-language collision. A
    prior version of this guard required exact extension equality even
    within "other," which made that ordinary case indistinguishable from
    a real cross-language false positive and silently dropped every
    header/impl-split C/C++ reference.
    """
    candidate_lang = _classify_language(candidate_file)
    if ref_lang != candidate_lang:
        return False
    if ref_lang != "other":
        return True
    ref_ext = os.path.splitext(ref_file)[1].lower()
    candidate_ext = os.path.splitext(candidate_file)[1].lower()
    if ref_ext in _C_FAMILY_EXTENSIONS and candidate_ext in _C_FAMILY_EXTENSIONS:
        return True
    return ref_ext == candidate_ext


def _build_import_map(
    extractions: dict[str, ExtractionResult],
) -> dict[str, dict[str, str]]:
    """Build a map of file → {imported_name: source_module} for reference resolution."""
    import_map: dict[str, dict[str, str]] = defaultdict(dict)

    for rel_path, result in extractions.items():
        for ref in result.references:
            if ref.kind != "import":
                continue
            module = ref.module or ""
            for sym_name in ref.symbols:
                import_map[rel_path][sym_name] = module

    return dict(import_map)


def build_layer_b(
    extractions: dict[str, ExtractionResult],
    nodes: list[dict],
    structural_edges: list[dict],
) -> list[dict]:
    """Build Layer B: resolve references to symbol IDs, create reference edges.

    Args:
        extractions: dict of rel_path → ExtractionResult
        nodes: Layer A symbol nodes
        structural_edges: Layer A structural edges

    Returns:
        List of all edges (structural + reference).
    """
    index = _build_symbol_index(nodes)
    import_map = _build_import_map(extractions)

    edges = list(structural_edges)  # Start with Layer A structural edges
    seen_edges: set[tuple[str, str, str]] = set()

    # Add structural edges to seen set
    for e in edges:
        seen_edges.add((e["from"], e["to"], e["type"]))

    for rel_path, result in extractions.items():
        for ref in result.references:
            if ref.kind == "import":
                # Import edges: file → file with imported symbols
                module = ref.module or ""
                # Find target file
                target_file = None
                for fname in index["by_file"]:
                    # Match module path to file path
                    # e.g., "models.user" matches "models/user.py"
                    module_as_path = module.replace(".", "/")
                    if module_as_path in fname or fname.endswith(module_as_path + ".py"):
                        target_file = fname
                        break

                if target_file and target_file != rel_path:
                    edge_key = (rel_path, target_file, "imports")
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges.append({
                            "from": rel_path,
                            "to": target_file,
                            "type": "imports",
                            "symbols": ref.symbols,
                        })

            elif ref.kind == "call":
                # Resolve call to a symbol
                target = _resolve_reference(ref.name, rel_path, index, import_map)
                if target:
                    # Determine edge type: instantiation or call
                    target_node = index["by_id"].get(target)
                    edge_type = "calls"
                    if target_node and target_node["kind"] == "class":
                        edge_type = "instantiates"

                    # Find the calling symbol (closest definition in same file before this line)
                    caller = _find_enclosing_symbol(rel_path, ref.line, index)
                    from_id = caller or rel_path

                    edge_key = (from_id, target, edge_type)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges.append({
                            "from": from_id,
                            "to": target,
                            "type": edge_type,
                        })

            elif ref.kind == "type_ref":
                target = _resolve_reference(ref.name, rel_path, index, import_map)
                if target:
                    caller = _find_enclosing_symbol(rel_path, ref.line, index)
                    from_id = caller or rel_path

                    edge_key = (from_id, target, "references_type")
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges.append({
                            "from": from_id,
                            "to": target,
                            "type": "references_type",
                        })

            elif ref.kind == "attribute_access":
                target = _resolve_reference(ref.name, rel_path, index, import_map)
                if target:
                    caller = _find_enclosing_symbol(rel_path, ref.line, index)
                    from_id = caller or rel_path

                    edge_key = (from_id, target, "accesses")
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges.append({
                            "from": from_id,
                            "to": target,
                            "type": "accesses",
                        })

    return edges


def _find_enclosing_symbol(
    file_path: str, line: int, index: dict,
) -> str | None:
    """Find the symbol that encloses the given line in the given file.

    Returns the symbol ID of the innermost enclosing function/method/class,
    or None if the reference is at module level.
    """
    file_symbols = index["by_file"].get(file_path, [])
    best: str | None = None
    best_line = 0

    for sid in file_symbols:
        node = index["by_id"][sid]
        # Symbol must be before the reference line and be a function/method/class
        if node["line"] <= line and node["kind"] in ("function", "method", "class"):
            if node["line"] > best_line:
                best = sid
                best_line = node["line"]

    return best


# ── Layer C: Domain Layer (Community Detection) ──────────────


def build_layer_c(
    nodes: list[dict],
    edges: list[dict],
    repo_path: str = "",
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Build Layer C: community detection.

    Uses 6-layer file-level clustering (Leiden+CPM) when repo_path is
    available. Falls back to symbol-level Louvain otherwise.

    Args:
        nodes: Layer A symbol nodes
        edges: Layer B edges (structural + reference)
        repo_path: Repository root for file-level clustering

    Returns:
        (clusters, cluster_edges, symbol_to_cluster) matching the CSG schema.
    """
    # Try 6-layer file clustering when repo_path is available
    if repo_path and os.path.isdir(repo_path):
        try:
            from lib.context.layer1_domain_clustering import build_layer_c_from_files
            result = build_layer_c_from_files(nodes, edges, repo_path)
            if result[0]:  # non-empty clusters
                return result
        except ImportError:
            pass  # Fall through to Louvain

    if not HAS_NETWORKX:
        return [], [], {}

    # Build a networkx graph from symbol-to-symbol edges
    G = nx.Graph()

    # Add all symbol nodes
    node_ids = {n["id"] for n in nodes}
    for nid in node_ids:
        G.add_node(nid)

    # Add edges (only symbol-to-symbol, skip file-level and unresolved)
    reference_types = {"calls", "instantiates", "references_type", "accesses", "contains", "inherits", "implements"}
    for edge in edges:
        if edge["type"] not in reference_types:
            continue
        from_id = edge["from"]
        to_id = edge["to"]
        if from_id in node_ids and to_id in node_ids:
            G.add_edge(from_id, to_id)

    if len(G.nodes) == 0:
        return [], [], {}

    # Run Louvain community detection
    if HAS_LOUVAIN and len(G.nodes) > 1:
        try:
            communities = louvain_communities(G, seed=42)
        except Exception:
            # Fallback: each file is its own cluster
            communities = _file_based_communities(nodes)
    else:
        communities = _file_based_communities(nodes)

    # Build cluster data
    clusters = []
    symbol_to_cluster: dict[str, str] = {}
    node_lookup = {n["id"]: n for n in nodes}

    for idx, community in enumerate(communities):
        community_list = list(community)
        if not community_list:
            continue

        # Determine cluster label from common file path prefix
        files_in_cluster = set()
        for sid in community_list:
            node = node_lookup.get(sid)
            if node:
                files_in_cluster.add(node["file"])

        label = _infer_cluster_label(files_in_cluster)
        cluster_id = f"cluster_{label}_{idx}" if label else f"cluster_{idx}"

        # Count internal vs external refs
        internal_refs = 0
        external_refs = 0
        community_set = set(community_list)

        for edge in edges:
            if edge["type"] not in reference_types:
                continue
            from_in = edge["from"] in community_set
            to_in = edge["to"] in community_set
            if from_in and to_in:
                internal_refs += 1
            elif from_in or to_in:
                external_refs += 1

        total = internal_refs + external_refs
        cohesion = round(internal_refs / total, 2) if total > 0 else 0.0

        cluster = {
            "id": cluster_id,
            "label": label or f"cluster_{idx}",
            "symbols": community_list,
            "files": sorted(files_in_cluster),
            "internal_refs": internal_refs,
            "external_refs": external_refs,
            "cohesion": cohesion,
        }
        clusters.append(cluster)

        for sid in community_list:
            symbol_to_cluster[sid] = cluster_id

    # Build inter-cluster edges
    cluster_edge_counts: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for edge in edges:
        if edge["type"] not in reference_types:
            continue
        from_cluster = symbol_to_cluster.get(edge["from"])
        to_cluster = symbol_to_cluster.get(edge["to"])
        if from_cluster and to_cluster and from_cluster != to_cluster:
            key = (from_cluster, to_cluster)
            cluster_edge_counts[key].append({
                "from": edge["from"],
                "to": edge["to"],
            })

    cluster_edges = []
    for (from_c, to_c), symbol_pairs in cluster_edge_counts.items():
        cluster_edges.append({
            "from": from_c,
            "to": to_c,
            "edge_count": len(symbol_pairs),
            "symbols": symbol_pairs[:20],  # Cap at 20 to limit JSON size
        })

    return clusters, cluster_edges, symbol_to_cluster


def _file_based_communities(nodes: list[dict]) -> list[set[str]]:
    """Fallback community detection: group symbols by file."""
    file_groups: dict[str, set[str]] = defaultdict(set)
    for node in nodes:
        file_groups[node["file"]].add(node["id"])
    return list(file_groups.values())


def _infer_cluster_label(files: set[str]) -> str:
    """Infer a human-readable label from a set of file paths.

    Uses the most common directory segment.
    """
    if not files:
        return ""

    # Count directory segments
    segment_counts: dict[str, int] = defaultdict(int)
    for f in files:
        parts = f.split("/")
        for part in parts[:-1]:  # Exclude filename
            if part and part not in ("src", "lib", "app", "main", "core"):
                segment_counts[part] += 1

    if not segment_counts:
        # Fall back to first directory
        for f in files:
            parts = f.split("/")
            if len(parts) > 1:
                return parts[0]
        return ""

    return max(segment_counts, key=segment_counts.get)


# ── Layer D: Impact Layer ────────────────────────────────────


def build_layer_d(
    nodes: list[dict],
    edges: list[dict],
    symbol_to_cluster: dict[str, str],
) -> dict[str, dict]:
    """Build Layer D: impact analysis per symbol.

    Args:
        nodes: Layer A symbol nodes
        edges: Layer B edges
        symbol_to_cluster: symbol_id → cluster_id mapping

    Returns:
        Dict of symbol_id → impact dict {blast_radius, centrality, dependents, stability}
    """
    if not HAS_NETWORKX:
        return {}

    # Build directed graph for impact analysis
    G = nx.DiGraph()
    node_ids = {n["id"] for n in nodes}

    for nid in node_ids:
        G.add_node(nid)

    reference_types = {"calls", "instantiates", "references_type", "accesses"}
    for edge in edges:
        if edge["type"] not in reference_types:
            continue
        if edge["from"] in node_ids and edge["to"] in node_ids:
            G.add_edge(edge["from"], edge["to"])

    if len(G.nodes) == 0:
        return {}

    # Pre-compute cross-cluster connections for bridge detection
    cross_cluster: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge["type"] not in reference_types:
            continue
        fc = symbol_to_cluster.get(edge["from"])
        tc = symbol_to_cluster.get(edge["to"])
        if fc and tc and fc != tc:
            cross_cluster[edge["from"]].add(tc)
            cross_cluster[edge["to"]].add(fc)

    # Compute betweenness centrality
    # For <10K symbols: exact. For larger: sampled.
    n_nodes = len(G.nodes)
    if n_nodes < 10000:
        centrality = nx.betweenness_centrality(G)
    else:
        # Sample ~sqrt(n) nodes for approximation
        k = min(int(n_nodes ** 0.5), 500)
        centrality = nx.betweenness_centrality(G, k=k)

    # Compute blast radius (bounded BFS, depth 5) and dependents
    impact: dict[str, dict] = {}
    MAX_DEPTH = 5
    MAX_REACHABLE = 1000

    for nid in G.nodes:
        # Blast radius: forward BFS on outgoing edges
        blast = _bounded_bfs(G, nid, MAX_DEPTH, MAX_REACHABLE)

        # Dependents: direct incoming edges
        dependents = G.in_degree(nid)

        # Centrality
        cent = round(centrality.get(nid, 0.0), 4)

        # Stability classification: bridge if cross-cluster, hub if many dependents
        stability = _classify_stability(nid, dependents, cross_cluster)

        impact[nid] = {
            "blast_radius": blast,
            "centrality": cent,
            "dependents": dependents,
            "stability": stability,
        }

    return impact


def _bounded_bfs(G: Any, start: str, max_depth: int, max_count: int) -> int:
    """Count reachable nodes via BFS, bounded by depth and count."""
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(start, 0)]

    while queue and len(visited) < max_count:
        node, depth = queue.pop(0)
        if depth > max_depth:
            continue
        if node in visited:
            continue
        visited.add(node)
        if depth < max_depth:
            for neighbor in G.successors(node):
                if neighbor not in visited:
                    queue.append((neighbor, depth + 1))

    return len(visited) - 1  # Exclude the start node itself


def _classify_stability(
    sid: str,
    dependents: int,
    cross_cluster: dict[str, set[str]],
) -> str:
    """Classify symbol stability: bridge, hub, or stable.

    - bridge: references cross cluster boundaries
    - hub: 3+ direct dependents within its own cluster
    - stable: everything else (safe to modify)
    """
    # Bridge: symbol has edges crossing into other clusters
    if cross_cluster.get(sid):
        return "bridge"

    # Hub: important within its cluster (many dependents)
    if dependents >= 3:
        return "hub"

    # Stable: few dependents, safe to modify
    return "stable"


# ── CSG Builder (top-level) ──────────────────────────────────


def build_csg(
    project_root: str,
    extractions: dict[str, ExtractionResult],
) -> dict:
    """Build the complete Codebase Semantic Graph.

    Args:
        project_root: absolute path to project root
        extractions: dict of rel_path → ExtractionResult (from tree-sitter)

    Returns:
        semantic-graph.json dict with nodes, edges, clusters, cluster_edges
    """
    # Layer A: Symbol nodes + structural edges
    nodes, structural_edges = build_layer_a(extractions)

    # Layer B: Reference resolution
    edges = build_layer_b(extractions, nodes, structural_edges)

    # Layer C: Community detection (6-layer file clustering when possible)
    layer_c_result = build_layer_c(nodes, edges, repo_path=project_root)
    if len(layer_c_result) == 3:
        clusters, cluster_edges, symbol_to_cluster = layer_c_result
    else:
        clusters, cluster_edges = layer_c_result
        symbol_to_cluster = {}

    # Layer D: Impact analysis
    impact = build_layer_d(nodes, edges, symbol_to_cluster)

    # Annotate nodes with impact and cluster info
    for node in nodes:
        nid = node["id"]
        if nid in impact:
            node["impact"] = impact[nid]
        if nid in symbol_to_cluster:
            node["cluster"] = symbol_to_cluster[nid]

    return {
        "generated_at": now_iso(),
        "git_head": git_head_hash(project_root),
        "nodes": nodes,
        "edges": edges,
        "clusters": clusters,
        "cluster_edges": cluster_edges,
    }


# ── Persistence ──────────────────────────────────────────────


def save_csg(csg: dict, context_dir: str) -> str:
    """Save CSG to .speed/context/semantic-graph.json. Returns path."""
    path = os.path.join(context_dir, "semantic-graph.json")
    write_json(path, csg)
    return path


def load_csg(context_dir: str) -> dict:
    """Load CSG from .speed/context/semantic-graph.json."""
    path = os.path.join(context_dir, "semantic-graph.json")
    return read_json(path)


# ── Queries ──────────────────────────────────────────────────


def get_symbol(csg: dict, symbol_id: str) -> dict | None:
    """Look up a symbol node by ID."""
    for node in csg.get("nodes", []):
        if node["id"] == symbol_id:
            return node
    return None


def get_symbols_in_file(csg: dict, file_path: str) -> list[dict]:
    """Get all symbols defined in a file."""
    return [n for n in csg.get("nodes", []) if n["file"] == file_path]


def get_edges_for_symbol(csg: dict, symbol_id: str) -> list[dict]:
    """Get all edges involving a symbol (incoming and outgoing)."""
    return [
        e for e in csg.get("edges", [])
        if e["from"] == symbol_id or e["to"] == symbol_id
    ]


def get_dependents(csg: dict, symbol_id: str) -> list[str]:
    """Get symbol IDs that reference (depend on) the given symbol."""
    return [
        e["from"] for e in csg.get("edges", [])
        if e["to"] == symbol_id and e["type"] in ("calls", "instantiates", "references_type", "accesses")
    ]


def get_dependencies(csg: dict, symbol_id: str) -> list[str]:
    """Get symbol IDs that the given symbol depends on."""
    return [
        e["to"] for e in csg.get("edges", [])
        if e["from"] == symbol_id and e["type"] in ("calls", "instantiates", "references_type", "accesses")
    ]


def get_cluster_for_file(csg: dict, file_path: str) -> dict | None:
    """Find the cluster containing symbols from the given file."""
    for cluster in csg.get("clusters", []):
        if file_path in cluster.get("files", []):
            return cluster
    return None


def get_bridge_symbols(csg: dict) -> list[dict]:
    """Get all symbols classified as 'bridge' stability."""
    return [
        n for n in csg.get("nodes", [])
        if n.get("impact", {}).get("stability") == "bridge"
    ]


def get_high_impact_symbols(csg: dict, min_blast_radius: int = 10) -> list[dict]:
    """Get symbols with blast radius above threshold."""
    return [
        n for n in csg.get("nodes", [])
        if n.get("impact", {}).get("blast_radius", 0) >= min_blast_radius
    ]
