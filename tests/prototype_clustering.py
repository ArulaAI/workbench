#!/usr/bin/env python3
"""
Prototype: Multi-signal file-level clustering.

Tests the proposed replacement for CSG Layer C against real codebases.
Four signals: directory structure, co-change, import proximity, identifier similarity.
Clustering: Leiden with CPM per signal, then consensus aggregation.
"""

import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from math import log
from pathlib import Path

import igraph as ig
import leidenalg as la
import networkx as nx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ─── Helpers ───────────────────────────────────────────────────────────

GENERIC_SEGMENTS = {
    "src", "lib", "app", "main", "core", "utils", "helpers", "common",
    "shared", "internal", "pkg", "packages", "modules", "vendor",
    "node_modules", "dist", "build", "__pycache__", ".git",
}

SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
    ".ttf", ".eot", ".lock", ".map", ".min.js", ".min.css",
    ".pyc", ".pyo", ".so", ".dylib", ".o",
}

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".rb", ".go", ".rs",
    ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".php", ".scala", ".ex", ".exs", ".clj", ".cljs",
    ".vue", ".svelte", ".astro",
}

SKIP_DIRS = {
    "node_modules", "vendor", "dist", "build", ".git", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    "coverage", ".next", ".nuxt", ".astro",
    # Virtualenv / site-packages patterns
    "site-packages", "egg-info",
}

# Any directory with these substrings gets skipped (catches tourism_api_env, .venv, etc.)
SKIP_DIR_PATTERNS = {"_env", "site-packages", "egg-info", ".egg"}


def get_code_files(repo_path: str) -> list[str]:
    """Get all code files relative to repo root, skipping noise."""
    files = []
    for root, dirs, filenames in os.walk(repo_path):
        # Skip known dirs and any dir matching skip patterns
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS
            and not any(pat in d.lower() for pat in SKIP_DIR_PATTERNS)
        ]
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in CODE_EXTENSIONS:
                rel = os.path.relpath(os.path.join(root, f), repo_path)
                # Skip paths containing site-packages or virtualenv dirs
                if "site-packages" in rel or "_env/" in rel:
                    continue
                files.append(rel)
    return sorted(files)


def tokenize_path(filepath: str) -> list[str]:
    """Split a file path into meaningful tokens."""
    parts = Path(filepath).parts
    # Remove extension from last part
    stem = Path(parts[-1]).stem
    meaningful = []
    for p in parts[:-1]:
        if p.lower() not in GENERIC_SEGMENTS:
            meaningful.append(p.lower())
    # Split stem on common separators
    tokens = re.split(r'[-_.]', stem.lower())
    meaningful.extend(t for t in tokens if len(t) > 1)
    return meaningful


# ─── Signal 1: Directory Structure ─────────────────────────────────────

def build_directory_graph(files: list[str]) -> nx.Graph:
    """Create weighted edges between files based on shared directory depth."""
    G = nx.Graph()
    G.add_nodes_from(files)

    # Group files by directory
    dir_to_files = defaultdict(list)
    for f in files:
        parts = Path(f).parts
        # Add to every ancestor directory
        for depth in range(1, len(parts)):
            dirpath = os.path.join(*parts[:depth])
            dir_to_files[dirpath].append(f)

    # Create edges weighted by deepest shared directory
    file_pairs = defaultdict(float)
    for dirpath, dir_files in dir_to_files.items():
        depth = len(Path(dirpath).parts)
        # Filter generic segments
        segments = Path(dirpath).parts
        meaningful_depth = sum(1 for s in segments if s.lower() not in GENERIC_SEGMENTS)
        if meaningful_depth == 0:
            continue

        weight = meaningful_depth  # Deeper shared path = stronger connection
        if len(dir_files) <= 50:  # Skip very broad directories
            for i, f1 in enumerate(dir_files):
                for f2 in dir_files[i + 1:]:
                    pair = tuple(sorted([f1, f2]))
                    file_pairs[pair] = max(file_pairs[pair], weight)

    for (f1, f2), weight in file_pairs.items():
        G.add_edge(f1, f2, weight=weight)

    return G


# ─── Signal 2: Co-Change (Git History) ────────────────────────────────

def build_cochange_graph(repo_path: str, files: list[str], max_commits: int = 2000) -> nx.Graph:
    """Build co-change graph from git history."""
    G = nx.Graph()
    file_set = set(files)
    G.add_nodes_from(files)

    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={max_commits}", "--pretty=format:--COMMIT--", "--name-only"],
            cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return G
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return G

    # Parse commits
    commits = []
    current_files = []
    for line in result.stdout.split('\n'):
        line = line.strip()
        if line == '--COMMIT--':
            if current_files:
                commits.append(current_files)
            current_files = []
        elif line and line in file_set:
            current_files.append(line)
    if current_files:
        commits.append(current_files)

    # Build co-occurrence matrix
    pair_counts = Counter()
    file_counts = Counter()
    for commit_files in commits:
        # Cap per-commit to avoid mega-commits creating noise
        if len(commit_files) > 30:
            continue
        for f in commit_files:
            file_counts[f] += 1
        for i, f1 in enumerate(commit_files):
            for f2 in commit_files[i + 1:]:
                pair = tuple(sorted([f1, f2]))
                pair_counts[pair] += 1

    # Add edges where co-change is significant
    min_shared = 3
    min_confidence = 0.2
    for (f1, f2), count in pair_counts.items():
        if count < min_shared:
            continue
        conf1 = count / max(file_counts[f1], 1)
        conf2 = count / max(file_counts[f2], 1)
        if max(conf1, conf2) >= min_confidence:
            weight = count * max(conf1, conf2)
            G.add_edge(f1, f2, weight=weight)

    return G


# ─── Signal 3: Import Proximity ───────────────────────────────────────

IMPORT_PATTERNS = [
    # Python: import foo.bar / from foo.bar import X
    re.compile(r'^\s*(?:from|import)\s+([a-zA-Z_][\w.]*)', re.MULTILINE),
    # JS/TS: import ... from 'path' / require('path')
    re.compile(r'''(?:from|require)\s*\(?\s*['"]([^'"]+)['"]''', re.MULTILINE),
    # Ruby: require 'path' / require_relative 'path'
    re.compile(r'''require(?:_relative)?\s+['"]([^'"]+)['"]''', re.MULTILINE),
]


def extract_imports(filepath: str) -> list[str]:
    """Extract import module paths from a source file."""
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read(50000)  # First 50KB
    except (OSError, UnicodeDecodeError):
        return []

    modules = []
    for pattern in IMPORT_PATTERNS:
        for match in pattern.finditer(content):
            mod = match.group(1).strip("'\"")
            # Skip stdlib / external packages (heuristic: no dots and no relative path)
            if mod.startswith('.') or '/' in mod or '.' in mod:
                modules.append(mod)
    return modules


def module_to_file_match(module: str, files: list[str], file_index: dict) -> list[str]:
    """Fuzzy-match a module path to actual files."""
    # Normalize: replace dots with /, strip leading dots/slashes
    normalized = module.replace('.', '/').lstrip('./')
    normalized = normalized.rstrip('/')

    # Try exact match first
    candidates = []
    for ext in ['', '.py', '.ts', '.tsx', '.js', '.jsx', '.rb']:
        path = normalized + ext
        if path in file_index:
            candidates.append(path)
        # Try with /index
        idx_path = normalized + '/index' + ext
        if idx_path in file_index:
            candidates.append(idx_path)

    if candidates:
        return candidates

    # Fuzzy: match basename
    basename = os.path.basename(normalized)
    if len(basename) > 2:  # Skip very short names
        matches = [f for f in files if os.path.splitext(os.path.basename(f))[0] == basename]
        if 1 <= len(matches) <= 3:  # Only if reasonably unique
            return matches

    return []


def build_import_graph(repo_path: str, files: list[str]) -> nx.Graph:
    """Build file-to-file edges from import statements (fuzzy matching)."""
    G = nx.Graph()
    G.add_nodes_from(files)
    file_index = set(files)

    for f in files:
        full_path = os.path.join(repo_path, f)
        imports = extract_imports(full_path)
        for mod in imports:
            matches = module_to_file_match(mod, files, file_index)
            for target in matches:
                if target != f:
                    if G.has_edge(f, target):
                        G[f][target]['weight'] += 1
                    else:
                        G.add_edge(f, target, weight=1.0)

    return G


# ─── Signal 4: Identifier Similarity ──────────────────────────────────

IDENT_PATTERN = re.compile(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b')
STOP_IDENTS = {
    "self", "this", "true", "false", "none", "null", "undefined",
    "return", "import", "from", "class", "def", "function", "const",
    "let", "var", "async", "await", "yield", "export", "default",
    "interface", "type", "enum", "struct", "impl", "pub", "private",
    "protected", "public", "static", "final", "override", "abstract",
    "extends", "implements", "throws", "try", "catch", "finally",
    "raise", "except", "pass", "break", "continue", "for", "while",
    "with", "elif", "else", "end", "begin", "module", "require",
    "include", "use", "print", "println", "console", "log",
    "string", "int", "float", "bool", "boolean", "void", "any",
    "object", "array", "list", "dict", "map", "set", "tuple",
}


def extract_identifiers(filepath: str) -> str:
    """Extract identifiers from a source file as a space-separated string."""
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read(50000)
    except (OSError, UnicodeDecodeError):
        return ""

    idents = IDENT_PATTERN.findall(content)
    # Split camelCase and PascalCase
    expanded = []
    for ident in idents:
        lower = ident.lower()
        if lower in STOP_IDENTS:
            continue
        # Split camelCase
        parts = re.sub(r'([a-z])([A-Z])', r'\1 \2', ident)
        parts = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', parts)
        for p in parts.split():
            if len(p) > 2 and p.lower() not in STOP_IDENTS:
                expanded.append(p.lower())

    return ' '.join(expanded)


def build_identifier_graph(repo_path: str, files: list[str], threshold: float = 0.15) -> nx.Graph:
    """Build file-to-file edges from identifier TF-IDF cosine similarity."""
    G = nx.Graph()
    G.add_nodes_from(files)

    # Extract identifiers per file
    docs = []
    valid_files = []
    for f in files:
        idents = extract_identifiers(os.path.join(repo_path, f))
        if idents.strip():
            docs.append(idents)
            valid_files.append(f)

    if len(docs) < 2:
        return G

    # TF-IDF + cosine similarity
    vectorizer = TfidfVectorizer(max_features=5000, min_df=2, max_df=0.8)
    try:
        tfidf_matrix = vectorizer.fit_transform(docs)
    except ValueError:
        return G

    # Compute similarities in batches to avoid memory explosion
    batch_size = 200
    for start in range(0, len(valid_files), batch_size):
        end = min(start + batch_size, len(valid_files))
        batch_sim = cosine_similarity(tfidf_matrix[start:end], tfidf_matrix)

        for i_offset in range(end - start):
            i = start + i_offset
            for j in range(i + 1, len(valid_files)):
                sim = batch_sim[i_offset, j]
                if sim >= threshold:
                    G.add_edge(valid_files[i], valid_files[j], weight=sim)

    return G


# ─── Clustering ────────────────────────────────────────────────────────

def leiden_cluster(G: nx.Graph, resolution: float = 0.05) -> dict[str, int]:
    """Run Leiden with CPM on a networkx graph. Returns node -> cluster_id."""
    if G.number_of_edges() == 0:
        # Every node is its own cluster
        return {n: i for i, n in enumerate(G.nodes())}

    # Convert to igraph
    nodes = list(G.nodes())
    node_to_idx = {n: i for i, n in enumerate(nodes)}
    ig_graph = ig.Graph(n=len(nodes), directed=False)

    edges = []
    weights = []
    for u, v, data in G.edges(data=True):
        edges.append((node_to_idx[u], node_to_idx[v]))
        weights.append(data.get('weight', 1.0))
    ig_graph.add_edges(edges)

    partition = la.find_partition(
        ig_graph,
        la.CPMVertexPartition,
        resolution_parameter=resolution,
        weights=weights,
        seed=42,
    )

    result = {}
    for cluster_id, members in enumerate(partition):
        for idx in members:
            result[nodes[idx]] = cluster_id
    return result


def consensus_clusters(
    clusterings: list[dict[str, int]],
    files: list[str],
    min_agreement: float = 0.5,
    resolution: float = 0.02,
) -> dict[str, int]:
    """
    Consensus clustering: two files belong together if a majority of
    signals agree they're in the same cluster.

    Build a co-membership graph, then cluster it with Leiden.
    """
    G = nx.Graph()
    G.add_nodes_from(files)

    n_signals = len(clusterings)
    if n_signals == 0:
        return {f: i for i, f in enumerate(files)}

    # For each pair, count how many signals put them in the same cluster
    # (Optimize: only check pairs that are co-clustered in at least one signal)
    cluster_to_files = []
    for clustering in clusterings:
        c2f = defaultdict(list)
        for f, cid in clustering.items():
            c2f[cid].append(f)
        cluster_to_files.append(c2f)

    pair_agreement = Counter()
    for clustering_idx, c2f in enumerate(cluster_to_files):
        for cid, members in c2f.items():
            if len(members) > 100:  # Skip mega-clusters
                continue
            for i, f1 in enumerate(members):
                for f2 in members[i + 1:]:
                    pair = tuple(sorted([f1, f2]))
                    pair_agreement[pair] += 1

    # Add edges where agreement meets threshold
    threshold = max(1, int(n_signals * min_agreement))
    for (f1, f2), count in pair_agreement.items():
        if count >= threshold:
            G.add_edge(f1, f2, weight=count / n_signals)

    # Final clustering
    return leiden_cluster(G, resolution=resolution)


# ─── Labeling ──────────────────────────────────────────────────────────

def label_cluster(files: list[str], all_labels_so_far: list[str] | None = None) -> str:
    """Generate a human-readable label for a cluster of files.
    Uses all_labels_so_far to avoid duplicate labels."""
    if not files:
        return "unknown"

    used = set(all_labels_so_far or [])

    # Strategy 1: Find the most specific common path segments
    parts_list = [Path(f).parts for f in files]

    if len(parts_list) == 1:
        p = Path(files[0])
        meaningful = [s for s in p.parts[:-1] if s.lower() not in GENERIC_SEGMENTS]
        if meaningful:
            return '/'.join(meaningful[-2:])
        return p.stem

    # Collect all directory segments with depth info
    all_segments = []
    for parts in parts_list:
        meaningful = [s for s in parts[:-1] if s.lower() not in GENERIC_SEGMENTS]
        all_segments.extend(meaningful)

    seg_counts = Counter(all_segments)

    if seg_counts:
        # Try to find a specific sub-domain: deepest common segment
        # that appears in a majority of files
        majority = len(files) * 0.4

        # Build candidate labels from common segments, preferring deeper/more specific ones
        candidates = []
        common = [s for s, c in seg_counts.most_common() if c >= majority]

        if common:
            # Try 2-segment label first for specificity
            if len(common) >= 2:
                label_2 = '/'.join(common[:2])
                if label_2 not in used:
                    candidates.append(label_2)
            # Then 3-segment
            if len(common) >= 3:
                label_3 = '/'.join(common[:3])
                if label_3 not in used:
                    candidates.insert(0, label_3)  # prefer more specific
            # Single segment
            for s in common:
                if s not in used:
                    candidates.append(s)

        # If all directory labels are taken, differentiate by file content
        if not candidates or all(c in used for c in candidates):
            # Use most common filename tokens to differentiate
            stems = [Path(f).stem.lower() for f in files]
            stem_tokens = []
            for s in stems:
                stem_tokens.extend(re.split(r'[-_.]', s))
            token_counts = Counter(
                t for t in stem_tokens
                if len(t) > 2 and t.lower() not in GENERIC_SEGMENTS
                and t.lower() not in {'test', 'index', 'page', 'spec', 'stories', 'init'}
            )
            if token_counts:
                top_token = token_counts.most_common(1)[0][0]
                # Combine with directory context
                dir_prefix = common[0] if common else ""
                combined = f"{dir_prefix}/{top_token}" if dir_prefix else top_token
                if combined not in used:
                    candidates.insert(0, combined)
                elif top_token not in used:
                    candidates.insert(0, top_token)

        # Return first unused candidate
        for c in candidates:
            if c not in used:
                return c

        if candidates:
            return candidates[0]

    # Strategy 2: Common filename patterns
    stems = [Path(f).stem.lower() for f in files]
    stem_tokens = []
    for s in stems:
        stem_tokens.extend(re.split(r'[-_.]', s))
    token_counts = Counter(t for t in stem_tokens if len(t) > 2 and t not in GENERIC_SEGMENTS)
    if token_counts:
        return token_counts.most_common(1)[0][0]

    return "misc"


# ─── Quality Metrics ──────────────────────────────────────────────────

def compute_mq(clusters: dict[str, int], reference_graph: nx.Graph) -> float:
    """Compute Modularization Quality (Bunch MQ metric)."""
    cluster_to_files = defaultdict(set)
    for f, cid in clusters.items():
        cluster_to_files[cid].add(f)

    if len(cluster_to_files) <= 1:
        return 0.0

    intra_scores = []
    inter_scores = []

    cluster_ids = list(cluster_to_files.keys())
    for cid in cluster_ids:
        members = cluster_to_files[cid]
        if len(members) < 2:
            continue

        # Intra-cluster edges
        intra = 0
        possible_intra = len(members) * (len(members) - 1) / 2
        for f1 in members:
            for f2 in members:
                if f1 < f2 and reference_graph.has_edge(f1, f2):
                    intra += 1
        if possible_intra > 0:
            intra_scores.append(intra / possible_intra)

    # Inter-cluster edges
    for i, cid1 in enumerate(cluster_ids):
        for cid2 in cluster_ids[i + 1:]:
            m1 = cluster_to_files[cid1]
            m2 = cluster_to_files[cid2]
            inter = 0
            for f1 in m1:
                for f2 in m2:
                    if reference_graph.has_edge(f1, f2):
                        inter += 1
            possible = len(m1) * len(m2)
            if possible > 0:
                inter_scores.append(inter / possible)

    avg_intra = sum(intra_scores) / len(intra_scores) if intra_scores else 0
    avg_inter = sum(inter_scores) / len(inter_scores) if inter_scores else 0
    return avg_intra - avg_inter


# ─── Main ──────────────────────────────────────────────────────────────

def analyze_codebase(repo_path: str, name: str):
    """Run the full multi-signal clustering on a codebase."""
    print(f"\n{'='*70}")
    print(f"  ANALYZING: {name}")
    print(f"  Path: {repo_path}")
    print(f"{'='*70}\n")

    # Get files
    files = get_code_files(repo_path)
    print(f"Code files found: {len(files)}")
    if len(files) > 3000:
        print(f"  (Capping at 3000 for prototype)")
        files = files[:3000]

    # Adaptive resolution: target ~sqrt(N) clusters as starting point
    # CPM resolution controls minimum internal edge density
    target_clusters = max(5, int(len(files) ** 0.5))
    print(f"  Target cluster count (approx): {target_clusters}")

    # Signal 1: Directory structure
    print("\n--- Signal 1: Directory Structure ---")
    dir_graph = build_directory_graph(files)
    print(f"  Edges: {dir_graph.number_of_edges()}")
    dir_clusters = leiden_cluster(dir_graph, resolution=0.5)
    n_dir = len(set(dir_clusters.values()))
    print(f"  Clusters: {n_dir}")

    # Signal 2: Co-change
    print("\n--- Signal 2: Co-Change (git history) ---")
    cochange_graph = build_cochange_graph(repo_path, files)
    print(f"  Edges: {cochange_graph.number_of_edges()}")
    cochange_clusters = leiden_cluster(cochange_graph, resolution=0.05)
    n_cc = len(set(cochange_clusters.values()))
    print(f"  Clusters: {n_cc}")

    # Signal 3: Import proximity
    print("\n--- Signal 3: Import Proximity ---")
    import_graph = build_import_graph(repo_path, files)
    print(f"  Edges: {import_graph.number_of_edges()}")
    import_clusters = leiden_cluster(import_graph, resolution=0.05)
    n_imp = len(set(import_clusters.values()))
    print(f"  Clusters: {n_imp}")

    # Signal 4: Identifier similarity
    print("\n--- Signal 4: Identifier Similarity (TF-IDF) ---")
    # Higher threshold to avoid over-connecting files that share common vocab
    ident_graph = build_identifier_graph(repo_path, files, threshold=0.30)
    print(f"  Edges: {ident_graph.number_of_edges()}")
    ident_clusters = leiden_cluster(ident_graph, resolution=0.08)
    n_ident = len(set(ident_clusters.values()))
    print(f"  Clusters: {n_ident}")

    # Consensus
    print("\n--- Consensus Aggregation ---")
    all_clusterings = [dir_clusters, cochange_clusters, import_clusters, ident_clusters]
    # Filter out signals that produced only singletons
    effective = [c for c in all_clusterings if len(set(c.values())) < len(files) * 0.9]
    print(f"  Effective signals: {len(effective)} of 4")
    if not effective:
        effective = [dir_clusters]  # Fallback to directory
        print(f"  Falling back to directory-only clustering")

    final_clusters = consensus_clusters(effective, files, min_agreement=0.35, resolution=0.05)
    n_final = len(set(final_clusters.values()))

    # Build cluster objects
    cluster_to_files = defaultdict(list)
    for f, cid in final_clusters.items():
        cluster_to_files[cid].append(f)

    # Sort by size descending
    sorted_clusters = sorted(cluster_to_files.items(), key=lambda x: len(x[1]), reverse=True)

    # Stats
    sizes = [len(fs) for _, fs in sorted_clusters]
    singletons = sum(1 for s in sizes if s == 1)

    print(f"\n  Final clusters: {n_final}")
    print(f"  Singletons: {singletons} ({singletons * 100 // n_final}%)")
    print(f"  Multi-file clusters: {n_final - singletons}")
    print(f"  Largest cluster: {max(sizes)} files")
    print(f"  Median cluster size: {sorted(sizes)[len(sizes)//2]} files")

    # Quality metric (using combined graph as reference)
    combined = nx.Graph()
    combined.add_nodes_from(files)
    for G in [dir_graph, cochange_graph, import_graph, ident_graph]:
        for u, v, data in G.edges(data=True):
            if combined.has_edge(u, v):
                combined[u][v]['weight'] += data.get('weight', 1)
            else:
                combined.add_edge(u, v, weight=data.get('weight', 1))

    # Sample MQ (full computation too expensive for large graphs)
    if n_final < 500:
        mq = compute_mq(final_clusters, combined)
        print(f"  MQ score: {mq:.4f}")

    # Show top clusters
    print(f"\n--- Top {min(25, n_final - singletons)} Clusters (by size) ---")
    shown = 0
    assigned_labels = []
    for cid, cfiles in sorted_clusters:
        if len(cfiles) < 2:
            break
        label = label_cluster(cfiles, assigned_labels)
        assigned_labels.append(label)
        # Show sample files
        samples = cfiles[:5]
        print(f"\n  [{label}] ({len(cfiles)} files)")
        for s in samples:
            print(f"    {s}")
        if len(cfiles) > 5:
            print(f"    ... and {len(cfiles) - 5} more")
        shown += 1
        if shown >= 25:
            break

    # Compare to existing CSG clusters if available
    csg_path = os.path.join(repo_path, '.speed', 'context', 'semantic-graph.json')
    if os.path.exists(csg_path):
        with open(csg_path) as f:
            csg = json.load(f)
        old_clusters = csg.get('clusters', [])
        old_singletons = sum(1 for c in old_clusters if len(c.get('symbols', [])) <= 1)
        old_zero_cohesion = sum(1 for c in old_clusters if c.get('cohesion', 0) == 0)
        print(f"\n--- Comparison with Current Layer C ---")
        print(f"  Current: {len(old_clusters)} clusters, {old_singletons} singletons ({old_singletons*100//max(len(old_clusters),1)}%), {old_zero_cohesion} zero-cohesion ({old_zero_cohesion*100//max(len(old_clusters),1)}%)")
        print(f"  New:     {n_final} clusters, {singletons} singletons ({singletons*100//max(n_final,1)}%)")

    return {
        'name': name,
        'files': len(files),
        'clusters': n_final,
        'singletons': singletons,
        'multi_file': n_final - singletons,
        'largest': max(sizes),
    }


if __name__ == '__main__':
    repos = [
        ("/Users/sanjay.kotagiri/Documents/code/tmp/speed", "SPEED"),
        ("/Users/sanjay.kotagiri/Documents/code/project-travel-prod-bug-fixes", "travel-prod"),
        ("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe", "find-your-tribe"),
    ]

    results = []
    for path, name in repos:
        if os.path.exists(path):
            try:
                r = analyze_codebase(path, name)
                results.append(r)
            except Exception as e:
                print(f"\nERROR on {name}: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"\nSkipping {name}: path not found")

    print(f"\n\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"{'Codebase':<20} {'Files':>6} {'Clusters':>9} {'Singletons':>11} {'Multi-file':>11} {'Largest':>8}")
    for r in results:
        print(f"{r['name']:<20} {r['files']:>6} {r['clusters']:>9} {r['singletons']:>11} {r['multi_file']:>11} {r['largest']:>8}")
