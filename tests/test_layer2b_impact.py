#!/usr/bin/env python3
"""
Measure the clustering impact of adding Layer 2b (naming conventions).

Runs the full 6-layer pipeline twice:
  1. Baseline (current prototype)
  2. With Layer 2b edges added after Layer 2a

Compares: singletons, cluster count, MQ, cross-dir, cross-lang.
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from prototype_clustering_v3 import (
    get_code_files,
    classify_language,
    resolve_python_imports,
    resolve_typescript_imports,
    find_tsconfig_paths,
    find_graphql_bridges,
    find_rest_bridges,
    detect_packages,
    build_semantic_edges,
    build_cochange_graph_idf,
    leiden_cluster,
    compute_mq,
    label_cluster,
)
from test_naming_conventions import find_naming_convention_edges

import networkx as nx
from pathlib import Path


def run_pipeline(repo_path, name, with_layer_2b=False):
    """Run the full 6-layer pipeline. Returns metrics dict."""
    files = get_code_files(repo_path)
    py_files = [f for f in files if classify_language(f) == "python"]
    ts_files = [f for f in files if classify_language(f) == "typescript"]

    combined = nx.Graph()
    combined.add_nodes_from(files)

    # Layer 2a: Import resolution + co-import conversion
    py_edges = resolve_python_imports(repo_path, py_files)
    tsconfig_paths = find_tsconfig_paths(repo_path, ts_files)
    ts_edges = resolve_typescript_imports(repo_path, ts_files, tsconfig_paths)

    py_unique = set(tuple(sorted(e)) for e in py_edges)
    ts_unique = set(tuple(sorted(e)) for e in ts_edges)

    import_targets = defaultdict(set)
    for source, target in py_unique | ts_unique:
        import_targets[source].add(target)

    files_with_imports = [f for f in files if f in import_targets]
    for i, f1 in enumerate(files_with_imports):
        t1 = import_targets[f1]
        for f2 in files_with_imports[i + 1:]:
            t2 = import_targets[f2]
            shared = len(t1 & t2)
            if shared >= 2:
                union = len(t1 | t2)
                weight = shared / union * 3.0
                combined.add_edge(f1, f2, weight=weight)

    for u, v in py_unique | ts_unique:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += 1.0
        else:
            combined.add_edge(u, v, weight=1.0)

    # Layer 2b: Naming conventions (optional)
    l2b_edges = 0
    if with_layer_2b:
        nc_edges = find_naming_convention_edges(repo_path, files)
        # Deduplicate
        nc_pairs = set()
        for src, tgt, _ in nc_edges:
            nc_pairs.add(tuple(sorted([src, tgt])))
        for u, v in nc_pairs:
            if combined.has_edge(u, v):
                combined[u][v]["weight"] += 3.0  # reinforce
            else:
                combined.add_edge(u, v, weight=3.0)
                l2b_edges += 1

    # Layer 3: Cross-language bridges
    gql_edges = find_graphql_bridges(repo_path, py_files, ts_files)
    gql_unique = set(tuple(sorted(e)) for e in gql_edges)
    rest_edges = find_rest_bridges(repo_path, py_files, ts_files)
    rest_unique = set(tuple(sorted(e)) for e in rest_edges)

    for u, v in gql_unique | rest_unique:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += 3.0
        else:
            combined.add_edge(u, v, weight=3.0)

    # Layer 4: Package detection
    file_to_package = detect_packages(repo_path, files)

    # Layer 6: Co-change (before Layer 5, to know orphans)
    cc_graph = build_cochange_graph_idf(repo_path, files)
    MAX_DEGREE = 25
    cc_capped = nx.Graph()
    cc_capped.add_nodes_from(cc_graph.nodes())
    for node in cc_graph.nodes():
        neighbors = list(cc_graph[node].items())
        if len(neighbors) <= MAX_DEGREE:
            for nbr, data in neighbors:
                if not cc_capped.has_edge(node, nbr):
                    cc_capped.add_edge(node, nbr, weight=data["weight"])
        else:
            top_k = sorted(neighbors, key=lambda x: x[1]["weight"], reverse=True)[:MAX_DEGREE]
            for nbr, data in top_k:
                if not cc_capped.has_edge(node, nbr):
                    cc_capped.add_edge(node, nbr, weight=data["weight"])

    for u, v, data in cc_capped.edges(data=True):
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += data["weight"]
        else:
            combined.add_edge(u, v, weight=data["weight"])

    # Layer 5: Semantic orphan rescue
    orphans = {n for n in files if combined.degree(n) == 0}
    sem_edges, file_terms = build_semantic_edges(repo_path, files, orphans, file_to_package, threshold=0.4)
    for u, v, w in sem_edges:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += w * 0.5
        else:
            combined.add_edge(u, v, weight=w * 0.5)

    # Global degree cap
    GLOBAL_MAX_DEGREE = 50
    for node in list(combined.nodes()):
        neighbors = list(combined[node].items())
        if len(neighbors) > GLOBAL_MAX_DEGREE:
            sorted_nbrs = sorted(neighbors, key=lambda x: x[1]["weight"], reverse=True)
            for nbr, _ in sorted_nbrs[GLOBAL_MAX_DEGREE:]:
                combined.remove_edge(node, nbr)

    # Clustering
    target = max(5, int(len(files) ** 0.5))
    best_clusters = None
    best_diff = float("inf")
    best_res = None
    best_mq = -999

    for res in [0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5]:
        clusters = leiden_cluster(combined, resolution=res)
        n_clusters = len(set(clusters.values()))
        mq = compute_mq(combined, clusters)
        diff = abs(n_clusters - target)
        if diff < best_diff or (diff <= best_diff + 3 and mq > best_mq):
            best_diff = diff
            best_clusters = clusters
            best_res = res
            best_mq = mq

    cluster_to_files = defaultdict(list)
    for f, cid in best_clusters.items():
        cluster_to_files[cid].append(f)

    # Recursive splitting
    max_cluster_size = max(40, int(len(files) * 0.08))
    next_id = max(cluster_to_files.keys()) + 1
    for iteration in range(5):
        oversized = [cid for cid, cfiles in cluster_to_files.items() if len(cfiles) > max_cluster_size]
        if not oversized:
            break
        for cid in oversized:
            cfiles = cluster_to_files[cid]
            subgraph = combined.subgraph(cfiles).copy()
            if subgraph.number_of_edges() == 0:
                continue
            sub_target = max(3, int(len(cfiles) ** 0.5))
            sub_best = None
            sub_best_diff = float("inf")
            for sub_res in [0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]:
                sub_clusters = leiden_cluster(subgraph, resolution=sub_res)
                n = len(set(sub_clusters.values()))
                if n > 1:
                    diff = abs(n - sub_target)
                    if sub_best is None or diff < sub_best_diff:
                        sub_best = sub_clusters
                        sub_best_diff = diff
                        if n >= sub_target:
                            break
            if sub_best and len(set(sub_best.values())) > 1:
                del cluster_to_files[cid]
                sub_groups = defaultdict(list)
                for f, sub_cid in sub_best.items():
                    sub_groups[sub_cid].append(f)
                for sub_cid, sub_files in sub_groups.items():
                    cluster_to_files[next_id] = sub_files
                    next_id += 1

    sorted_clusters = sorted(cluster_to_files.items(), key=lambda x: -len(x[1]))
    sizes = [len(fs) for _, fs in sorted_clusters]
    n_final = len(sorted_clusters)
    singletons = sum(1 for s in sizes if s == 1)
    multi_file = n_final - singletons

    cross_dir = 0
    cross_lang = 0
    for cid, cfiles in sorted_clusters:
        if len(cfiles) < 2:
            continue
        top_dirs = set(Path(f).parts[0] for f in cfiles if Path(f).parts)
        if len(top_dirs) > 1:
            cross_dir += 1
        exts = set(os.path.splitext(f)[1] for f in cfiles)
        has_py = ".py" in exts
        has_ts = bool(exts & {".ts", ".tsx", ".js", ".jsx"})
        if has_py and has_ts:
            cross_lang += 1

    connected = sum(1 for n in files if combined.degree(n) > 0)
    final_orphans = len(files) - connected

    return {
        "files": len(files),
        "edges": combined.number_of_edges(),
        "connected": connected,
        "orphans": final_orphans,
        "clusters": n_final,
        "singletons": singletons,
        "singleton_pct": singletons * 100 // max(n_final, 1),
        "multi_file": multi_file,
        "largest": max(sizes),
        "cross_dir": cross_dir,
        "cross_lang": cross_lang,
        "mq": best_mq,
        "resolution": best_res,
        "l2b_novel_edges": l2b_edges,
    }


def main():
    repos = [
        ("/Users/sanjay.kotagiri/Documents/code/project-travel-prod-bug-fixes", "travel-prod"),
        ("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe", "find-your-tribe"),
        ("/Users/sanjay.kotagiri/Documents/code/tmp/speed", "SPEED"),
    ]

    print(f"\n{'='*80}")
    print("  LAYER 2B IMPACT: NAMING CONVENTION MATCHING")
    print(f"{'='*80}")

    all_results = []

    for repo_path, name in repos:
        if not os.path.exists(repo_path):
            continue

        print(f"\n{'─'*60}")
        print(f"  {name}")
        print(f"{'─'*60}")

        baseline = run_pipeline(repo_path, name, with_layer_2b=False)
        with_2b = run_pipeline(repo_path, name, with_layer_2b=True)

        metrics = [
            ("Edges", "edges", ""),
            ("Connected files", "connected", f"/{baseline['files']}"),
            ("Orphans", "orphans", ""),
            ("Clusters", "clusters", ""),
            ("Singletons", "singletons", ""),
            ("Singleton %", "singleton_pct", "%"),
            ("Multi-file", "multi_file", ""),
            ("Largest", "largest", ""),
            ("Cross-dir", "cross_dir", ""),
            ("Cross-lang", "cross_lang", ""),
            ("MQ", "mq", ""),
        ]

        print(f"\n  {'Metric':<20} {'Baseline':>12} {'With 2b':>12} {'Delta':>12}")
        print(f"  {'─'*56}")
        for label, key, suffix in metrics:
            b = baseline[key]
            w = with_2b[key]
            if isinstance(b, float):
                delta = f"{w - b:+.4f}"
                print(f"  {label:<20} {b:>12.4f} {w:>12.4f} {delta:>12}")
            else:
                delta = f"{w - b:+d}" if w != b else "—"
                print(f"  {label:<20} {b:>12}{suffix} {w:>12}{suffix} {delta:>12}")

        print(f"\n  Layer 2b novel edges: {with_2b['l2b_novel_edges']}")
        all_results.append((name, baseline, with_2b))

    # Summary table
    print(f"\n\n{'='*80}")
    print("  SUMMARY: SINGLETON REDUCTION")
    print(f"{'='*80}")
    print(f"  {'Codebase':<16} {'Before':>10} {'After':>10} {'Delta':>10} {'Novel 2b':>10}")
    print(f"  {'─'*56}")
    for name, baseline, with_2b in all_results:
        before = f"{baseline['singleton_pct']}%"
        after = f"{with_2b['singleton_pct']}%"
        delta = f"{with_2b['singleton_pct'] - baseline['singleton_pct']:+d}pp"
        novel = str(with_2b['l2b_novel_edges'])
        print(f"  {name:<16} {before:>10} {after:>10} {delta:>10} {novel:>10}")


if __name__ == "__main__":
    main()
