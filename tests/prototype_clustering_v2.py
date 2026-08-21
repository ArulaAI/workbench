#!/usr/bin/env python3
"""
Prototype v2: Co-change-first domain clustering.

Directory structure is worthless for domain discovery — it tells the system
what `tree` already shows. The value of clustering is discovering cross-directory,
cross-language relationships that aren't obvious from the file tree.

Primary signal: co-change (files that change together in commits)
Secondary: import proximity (file-level fuzzy matching)
Tertiary: identifier similarity (TF-IDF, for cold-start files only)
Directory structure: NOT USED as a clustering signal.
"""

import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import igraph as ig
import leidenalg as la
import networkx as nx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ─── File discovery ────────────────────────────────────────────────────

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".rb", ".go", ".rs",
    ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".php", ".scala", ".ex", ".exs", ".clj", ".cljs",
    ".vue", ".svelte", ".astro",
}

SKIP_DIRS = {
    "node_modules", "vendor", "dist", "build", ".git", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    "coverage", ".next", ".nuxt", ".astro", "site-packages",
    "egg-info", ".speed", ".claude",
}

SKIP_DIR_PATTERNS = {"_env", "site-packages", "egg-info", ".egg"}

GENERIC_SEGMENTS = {
    "src", "lib", "app", "main", "core", "utils", "helpers", "common",
    "shared", "internal", "pkg", "packages", "modules", "vendor",
}


def get_code_files(repo_path: str) -> list[str]:
    """Get all code files relative to repo root."""
    files = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS
            and not any(pat in d.lower() for pat in SKIP_DIR_PATTERNS)
        ]
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in CODE_EXTENSIONS:
                rel = os.path.relpath(os.path.join(root, f), repo_path)
                if "site-packages" not in rel and "_env/" not in rel:
                    files.append(rel)
    return sorted(files)


# ─── Signal 1: Co-Change (PRIMARY) ────────────────────────────────────

def build_cochange_graph(
    repo_path: str,
    files: list[str],
    max_commits: int = 5000,
    max_commit_size: int = 50,
    min_shared: int = 2,
    min_confidence: float = 0.15,
) -> nx.Graph:
    """
    Build co-change graph from git history.

    The key insight: files that change together in commits have an implicit
    dependency, even when no import or call edge exists. This captures
    cross-language and cross-directory coupling that static analysis misses.
    """
    G = nx.Graph()
    file_set = set(files)
    G.add_nodes_from(files)

    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={max_commits}",
             "--pretty=format:--COMMIT--", "--name-only"],
            cwd=repo_path, capture_output=True, text=True, timeout=60
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

    # Build co-occurrence
    pair_counts = Counter()
    file_counts = Counter()
    for commit_files in commits:
        if len(commit_files) > max_commit_size:
            continue
        if len(commit_files) < 2:
            continue
        for f in commit_files:
            file_counts[f] += 1
        for i, f1 in enumerate(commit_files):
            for f2 in commit_files[i + 1:]:
                pair = tuple(sorted([f1, f2]))
                pair_counts[pair] += 1

    # Add weighted edges
    for (f1, f2), count in pair_counts.items():
        if count < min_shared:
            continue
        conf1 = count / max(file_counts[f1], 1)
        conf2 = count / max(file_counts[f2], 1)
        max_conf = max(conf1, conf2)
        if max_conf >= min_confidence:
            # Weight: co-change count * confidence
            # This gives high weight to pairs that ALWAYS change together
            weight = count * (conf1 + conf2) / 2
            G.add_edge(f1, f2, weight=weight)

    return G


# ─── Signal 2: Import Proximity ───────────────────────────────────────

IMPORT_PATTERNS = [
    re.compile(r'^\s*(?:from|import)\s+([a-zA-Z_][\w.]*)', re.MULTILINE),
    re.compile(r'''(?:from|require)\s*\(?\s*['"]([^'"]+)['"]''', re.MULTILINE),
    re.compile(r'''require(?:_relative)?\s+['"]([^'"]+)['"]''', re.MULTILINE),
]


def extract_imports(filepath: str) -> list[str]:
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read(50000)
    except (OSError, UnicodeDecodeError):
        return []
    modules = []
    for pattern in IMPORT_PATTERNS:
        for match in pattern.finditer(content):
            mod = match.group(1).strip("'\"")
            if mod.startswith('.') or '/' in mod or '.' in mod:
                modules.append(mod)
    return modules


def module_to_file_match(module: str, files: list[str], file_index: set) -> list[str]:
    normalized = module.replace('.', '/').lstrip('./')
    normalized = normalized.rstrip('/')
    candidates = []
    for ext in ['', '.py', '.ts', '.tsx', '.js', '.jsx', '.rb']:
        path = normalized + ext
        if path in file_index:
            candidates.append(path)
        idx_path = normalized + '/index' + ext
        if idx_path in file_index:
            candidates.append(idx_path)
    if candidates:
        return candidates
    basename = os.path.basename(normalized)
    if len(basename) > 2:
        matches = [f for f in files if os.path.splitext(os.path.basename(f))[0] == basename]
        if 1 <= len(matches) <= 3:
            return matches
    return []


def build_import_graph(repo_path: str, files: list[str]) -> nx.Graph:
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


# ─── Signal 3: Identifier Similarity (cold-start only) ────────────────

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
    "test", "describe", "expect", "should", "assert",
}


def extract_identifiers(filepath: str) -> str:
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read(50000)
    except (OSError, UnicodeDecodeError):
        return ""
    idents = IDENT_PATTERN.findall(content)
    expanded = []
    for ident in idents:
        lower = ident.lower()
        if lower in STOP_IDENTS:
            continue
        parts = re.sub(r'([a-z])([A-Z])', r'\1 \2', ident)
        parts = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', parts)
        for p in parts.split():
            if len(p) > 2 and p.lower() not in STOP_IDENTS:
                expanded.append(p.lower())
    return ' '.join(expanded)


def build_identifier_graph(
    repo_path: str, files: list[str],
    orphan_files: set[str],  # Only connect files that have no other edges
    threshold: float = 0.35,
) -> nx.Graph:
    """Build identifier similarity edges, but ONLY for orphan files
    that have no co-change or import edges."""
    G = nx.Graph()
    G.add_nodes_from(files)

    if not orphan_files:
        return G

    # Still compute TF-IDF across all files for proper IDF weighting
    docs = []
    valid_files = []
    for f in files:
        idents = extract_identifiers(os.path.join(repo_path, f))
        if idents.strip():
            docs.append(idents)
            valid_files.append(f)

    if len(docs) < 2:
        return G

    vectorizer = TfidfVectorizer(max_features=5000, min_df=2, max_df=0.8)
    try:
        tfidf_matrix = vectorizer.fit_transform(docs)
    except ValueError:
        return G

    # Only create edges FROM orphan files
    orphan_indices = [i for i, f in enumerate(valid_files) if f in orphan_files]
    if not orphan_indices:
        return G

    for idx in orphan_indices:
        sims = cosine_similarity(tfidf_matrix[idx:idx+1], tfidf_matrix)[0]
        for j in range(len(valid_files)):
            if j != idx and sims[j] >= threshold:
                G.add_edge(valid_files[idx], valid_files[j], weight=sims[j])

    return G


# ─── Clustering ────────────────────────────────────────────────────────

def leiden_cluster(G: nx.Graph, resolution: float = 0.05) -> dict[str, int]:
    if G.number_of_edges() == 0:
        return {n: i for i, n in enumerate(G.nodes())}

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
        ig_graph, la.CPMVertexPartition,
        resolution_parameter=resolution,
        weights=weights, seed=42,
    )

    result = {}
    for cluster_id, members in enumerate(partition):
        for idx in members:
            result[nodes[idx]] = cluster_id
    return result


# ─── Labeling ──────────────────────────────────────────────────────────

def label_cluster(files: list[str], all_labels: list[str] | None = None) -> str:
    """Label a cluster by its dominant domain terms, not directory structure."""
    used = set(all_labels or [])

    if len(files) == 1:
        return Path(files[0]).stem

    # Extract domain terms from file paths and names
    # Split paths into tokens, weight deeper segments higher
    term_scores = Counter()
    for f in files:
        parts = Path(f).parts
        for i, p in enumerate(parts):
            # Skip generic segments and extensions
            name = p.lower().replace('.py', '').replace('.ts', '').replace('.tsx', '').replace('.js', '').replace('.jsx', '')
            if name in GENERIC_SEGMENTS | {'__init__', 'index', '__tests__', 'test', 'tests', 'stories', 'specs'}:
                continue
            if len(name) <= 2:
                continue
            # Split on separators
            tokens = re.split(r'[-_.]', name)
            for t in tokens:
                if len(t) > 2 and t not in GENERIC_SEGMENTS:
                    # Weight by depth (deeper = more specific) and frequency
                    depth_weight = 1 + (i / max(len(parts), 1))
                    term_scores[t] += depth_weight

    if not term_scores:
        return f"cluster_{len(used)}"

    # Pick top terms that aren't already used
    for term, _ in term_scores.most_common(20):
        if term not in used:
            # Try combining with second-most-common for specificity
            remaining = [(t, s) for t, s in term_scores.most_common(20) if t != term and t not in used]
            if remaining:
                second = remaining[0][0]
                combo = f"{term}/{second}"
                if combo not in used:
                    return combo
            return term

    # Fallback
    return f"cluster_{len(used)}"


# ─── Cross-directory analysis ──────────────────────────────────────────

def cross_dir_stats(clusters: dict[int, list[str]]) -> dict:
    """Measure how many clusters span multiple top-level directories."""
    cross_dir_clusters = 0
    cross_lang_clusters = 0
    total_multi = 0

    for cid, cfiles in clusters.items():
        if len(cfiles) < 2:
            continue
        total_multi += 1

        # Top-level directories
        top_dirs = set()
        extensions = set()
        for f in cfiles:
            parts = Path(f).parts
            if parts:
                top_dirs.add(parts[0])
            ext = os.path.splitext(f)[1]
            extensions.add(ext)

        if len(top_dirs) > 1:
            cross_dir_clusters += 1

        # Cross-language: Python + TypeScript/JavaScript
        py = any(e in extensions for e in {'.py'})
        ts_js = any(e in extensions for e in {'.ts', '.tsx', '.js', '.jsx'})
        if py and ts_js:
            cross_lang_clusters += 1

    return {
        'multi_file_clusters': total_multi,
        'cross_dir': cross_dir_clusters,
        'cross_lang': cross_lang_clusters,
        'cross_dir_pct': cross_dir_clusters * 100 // max(total_multi, 1),
        'cross_lang_pct': cross_lang_clusters * 100 // max(total_multi, 1),
    }


# ─── Main ──────────────────────────────────────────────────────────────

def analyze_codebase(repo_path: str, name: str):
    print(f"\n{'='*70}")
    print(f"  ANALYZING: {name}")
    print(f"{'='*70}\n")

    files = get_code_files(repo_path)
    print(f"Code files: {len(files)}")

    # ── Signal 1: Co-change (PRIMARY) ──
    print("\n--- Signal 1: Co-Change (git history) ---")
    cc_graph = build_cochange_graph(repo_path, files)
    cc_connected = sum(1 for n in files if cc_graph.degree(n) > 0)
    print(f"  Edges: {cc_graph.number_of_edges()}")
    print(f"  Connected files: {cc_connected} / {len(files)} ({cc_connected*100//len(files)}%)")

    # Show cross-directory edges specifically
    cross_dir_edges = 0
    cross_lang_edges = 0
    for u, v in cc_graph.edges():
        u_dir = u.split('/')[0] if '/' in u else ''
        v_dir = v.split('/')[0] if '/' in v else ''
        if u_dir != v_dir:
            cross_dir_edges += 1
        u_ext = os.path.splitext(u)[1]
        v_ext = os.path.splitext(v)[1]
        py_exts = {'.py'}
        js_exts = {'.ts', '.tsx', '.js', '.jsx'}
        if (u_ext in py_exts and v_ext in js_exts) or (v_ext in py_exts and u_ext in js_exts):
            cross_lang_edges += 1
    print(f"  Cross-directory edges: {cross_dir_edges}")
    print(f"  Cross-language edges: {cross_lang_edges}")

    # ── Signal 2: Import proximity ──
    print("\n--- Signal 2: Import Proximity ---")
    imp_graph = build_import_graph(repo_path, files)
    imp_connected = sum(1 for n in files if imp_graph.degree(n) > 0)
    print(f"  Edges: {imp_graph.number_of_edges()}")
    print(f"  Connected files: {imp_connected} / {len(files)} ({imp_connected*100//len(files)}%)")

    # ── Merge primary signals ──
    print("\n--- Merging co-change + imports ---")
    merged = nx.Graph()
    merged.add_nodes_from(files)

    # Co-change edges get 3x weight (the primary signal)
    for u, v, data in cc_graph.edges(data=True):
        merged.add_edge(u, v, weight=data['weight'] * 3.0)

    # Import edges get 1x weight
    for u, v, data in imp_graph.edges(data=True):
        if merged.has_edge(u, v):
            merged[u][v]['weight'] += data['weight']
        else:
            merged.add_edge(u, v, weight=data['weight'])

    merged_connected = sum(1 for n in files if merged.degree(n) > 0)
    print(f"  Merged edges: {merged.number_of_edges()}")
    print(f"  Connected files: {merged_connected} / {len(files)} ({merged_connected*100//len(files)}%)")

    # Find orphan files (no co-change or import edges)
    orphans = {n for n in files if merged.degree(n) == 0}
    print(f"  Orphan files: {len(orphans)} ({len(orphans)*100//len(files)}%)")

    # ── Signal 3: Identifier similarity (orphans only) ──
    if orphans:
        print(f"\n--- Signal 3: Identifier Similarity (for {len(orphans)} orphans) ---")
        ident_graph = build_identifier_graph(repo_path, files, orphans, threshold=0.35)
        ident_edges = ident_graph.number_of_edges()
        print(f"  Edges added: {ident_edges}")

        # Add to merged graph
        for u, v, data in ident_graph.edges(data=True):
            if merged.has_edge(u, v):
                merged[u][v]['weight'] += data['weight'] * 0.5  # Lower weight
            else:
                merged.add_edge(u, v, weight=data['weight'] * 0.5)

        final_connected = sum(1 for n in files if merged.degree(n) > 0)
        remaining_orphans = sum(1 for n in files if merged.degree(n) == 0)
        print(f"  Connected after TF-IDF: {final_connected} / {len(files)}")
        print(f"  Remaining orphans: {remaining_orphans}")

    # ── Cluster ──
    print("\n--- Clustering (Leiden + CPM) ---")
    # Try multiple resolutions, pick the one closest to sqrt(N) clusters
    target = max(5, int(len(files) ** 0.5))
    best_clusters = None
    best_diff = float('inf')
    best_res = None

    for res in [0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3]:
        clusters = leiden_cluster(merged, resolution=res)
        n_clusters = len(set(clusters.values()))
        diff = abs(n_clusters - target)
        if diff < best_diff:
            best_diff = diff
            best_clusters = clusters
            best_res = res
        # Also track: prefer more clusters over fewer (within reason)
        if n_clusters >= target and diff <= best_diff + 5:
            best_clusters = clusters
            best_res = res

    print(f"  Target: ~{target} clusters")
    print(f"  Best resolution: {best_res}")

    # Build cluster objects
    cluster_to_files = defaultdict(list)
    for f, cid in best_clusters.items():
        cluster_to_files[cid].append(f)

    sorted_clusters = sorted(cluster_to_files.items(), key=lambda x: len(x[1]), reverse=True)
    sizes = [len(fs) for _, fs in sorted_clusters]
    n_final = len(sorted_clusters)
    singletons = sum(1 for s in sizes if s == 1)
    multi_file = n_final - singletons

    print(f"  Final clusters: {n_final}")
    print(f"  Singletons: {singletons} ({singletons*100//max(n_final,1)}%)")
    print(f"  Multi-file clusters: {multi_file}")
    print(f"  Largest: {max(sizes)} files")

    # Cross-directory analysis
    stats = cross_dir_stats(dict(sorted_clusters))
    print(f"\n  *** CROSS-DIRECTORY CLUSTERS: {stats['cross_dir']} / {stats['multi_file_clusters']} ({stats['cross_dir_pct']}%) ***")
    print(f"  *** CROSS-LANGUAGE CLUSTERS: {stats['cross_lang']} / {stats['multi_file_clusters']} ({stats['cross_lang_pct']}%) ***")

    # Show clusters
    print(f"\n--- Clusters (multi-file only) ---")
    labels = []
    for cid, cfiles in sorted_clusters:
        if len(cfiles) < 2:
            break
        label = label_cluster(cfiles, labels)
        labels.append(label)

        # Analyze cross-dir nature
        top_dirs = Counter(Path(f).parts[0] for f in cfiles if Path(f).parts)
        extensions = Counter(os.path.splitext(f)[1] for f in cfiles)
        is_cross_dir = len(top_dirs) > 1
        marker = " [CROSS-DIR]" if is_cross_dir else ""

        # Show directory breakdown for cross-dir clusters
        print(f"\n  [{label}] ({len(cfiles)} files){marker}")
        if is_cross_dir:
            dir_summary = ", ".join(f"{d}:{c}" for d, c in top_dirs.most_common(5))
            print(f"    dirs: {dir_summary}")

        # Show sample files, highlighting cross-dir pairs
        for s in cfiles[:6]:
            print(f"    {s}")
        if len(cfiles) > 6:
            print(f"    ... and {len(cfiles) - 6} more")

    # Compare
    csg_path = os.path.join(repo_path, '.speed', 'context', 'semantic-graph.json')
    if os.path.exists(csg_path):
        with open(csg_path) as f:
            csg = json.load(f)
        old = csg.get('clusters', [])
        old_singletons = sum(1 for c in old if len(c.get('symbols', [])) <= 1)
        old_zero = sum(1 for c in old if c.get('cohesion', 0) == 0)
        print(f"\n--- vs Current Layer C ---")
        print(f"  Current: {len(old)} clusters, {old_singletons} singletons ({old_singletons*100//max(len(old),1)}%), {old_zero} zero-cohesion")
        print(f"  New:     {n_final} clusters, {singletons} singletons ({singletons*100//max(n_final,1)}%)")
        print(f"  Cross-dir clusters: {stats['cross_dir']} (current: ~0)")
        print(f"  Cross-lang clusters: {stats['cross_lang']} (current: 0)")

    return {
        'name': name, 'files': len(files),
        'clusters': n_final, 'singletons': singletons,
        'multi_file': multi_file, 'largest': max(sizes),
        'cross_dir': stats['cross_dir'], 'cross_lang': stats['cross_lang'],
    }


if __name__ == '__main__':
    repos = [
        ("/Users/sanjay.kotagiri/Documents/code/project-travel-prod-bug-fixes", "travel-prod"),
        ("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe", "find-your-tribe"),
        ("/Users/sanjay.kotagiri/Documents/code/tmp/speed", "SPEED"),
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

    print(f"\n\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"{'Codebase':<20} {'Files':>6} {'Clusters':>9} {'Singles':>8} {'Multi':>6} {'X-Dir':>6} {'X-Lang':>7}")
    for r in results:
        print(f"{r['name']:<20} {r['files']:>6} {r['clusters']:>9} {r['singletons']:>8} {r['multi_file']:>6} {r['cross_dir']:>6} {r['cross_lang']:>7}")
