#!/usr/bin/env python3
"""
Retrospective Commit Coherence Validation.

For each multi-file commit in the travel-prod repo, measure what fraction
of changed code files fall within the dominant cluster from the 6-layer
pipeline. This validates that the clustering captures real developer intent:
focused commits should have high coherence (files in one cluster), while
WIP/bulk commits should scatter across clusters.

Pipeline: full 6-layer from prototype_clustering_v3.py
"""

import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Add the tests dir to path so we can import from prototype
sys.path.insert(0, os.path.dirname(__file__))

from prototype_clustering_v3 import (
    get_code_files,
    classify_language,
    resolve_python_imports,
    resolve_typescript_imports,
    find_tsconfig_paths,
    find_naming_convention_edges,
    find_graphql_bridges,
    find_rest_bridges,
    detect_packages,
    build_package_edges,
    build_cochange_graph_idf,
    build_semantic_edges,
    leiden_cluster,
    compute_mq,
    label_cluster,
)

import networkx as nx

REPO_PATH = "/Users/sanjay.kotagiri/Documents/code/project-travel-prod-bug-fixes"

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".rb", ".go", ".rs",
    ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".php", ".scala", ".ex", ".exs", ".clj", ".cljs",
    ".vue", ".svelte", ".astro",
}

WIP_PATTERNS = re.compile(
    r"\b(wip|initial|scaffolding|scaffold|refactor)\b", re.IGNORECASE
)


def build_full_pipeline(repo_path: str):
    """Build the full 6-layer clustering pipeline and return file_to_cluster mapping."""
    print("=" * 70)
    print("  BUILDING 6-LAYER CLUSTERING PIPELINE")
    print("=" * 70)
    print()

    files = get_code_files(repo_path)
    py_files = [f for f in files if classify_language(f) == "python"]
    ts_files = [f for f in files if classify_language(f) == "typescript"]

    print(f"Files: {len(files)} total ({len(py_files)} Python, {len(ts_files)} TS/JS)")

    combined = nx.Graph()
    combined.add_nodes_from(files)

    # ── Layer 2a: Compiler-native imports ──
    print("\nL2a: Compiler-native imports...")
    py_edges = resolve_python_imports(repo_path, py_files)
    tsconfig_paths = find_tsconfig_paths(repo_path, ts_files)
    ts_edges = resolve_typescript_imports(repo_path, ts_files, tsconfig_paths)

    py_unique = set(tuple(sorted(e)) for e in py_edges)
    ts_unique = set(tuple(sorted(e)) for e in ts_edges)

    # Co-import similarity
    import_targets = defaultdict(set)
    for source, target in py_unique | ts_unique:
        import_targets[source].add(target)

    co_import_edges = 0
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
                co_import_edges += 1

    for u, v in py_unique | ts_unique:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += 1.0
        else:
            combined.add_edge(u, v, weight=1.0)

    print(f"  Direct edges: {len(py_unique) + len(ts_unique)}, co-import: {co_import_edges}")

    # ── Layer 2b: Naming conventions ──
    print("L2b: Naming conventions...")
    nc_edges = find_naming_convention_edges(files)
    nc_pairs = set(tuple(sorted(e)) for e in nc_edges)
    novel_nc = 0
    for u, v in nc_pairs:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += 3.0
        else:
            combined.add_edge(u, v, weight=3.0)
            novel_nc += 1
    print(f"  Pairs: {len(nc_pairs)}, novel: {novel_nc}")

    # ── Layer 3: Cross-language bridges ──
    print("L3: Cross-language bridges...")
    gql_edges = find_graphql_bridges(repo_path, py_files, ts_files)
    gql_unique = set(tuple(sorted(e)) for e in gql_edges)
    rest_edges = find_rest_bridges(repo_path, py_files, ts_files)
    rest_unique = set(tuple(sorted(e)) for e in rest_edges)

    for u, v in gql_unique | rest_unique:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += 3.0
        else:
            combined.add_edge(u, v, weight=3.0)
    print(f"  GraphQL: {len(gql_unique)}, REST: {len(rest_unique)}")

    # ── Layer 4: Package detection ──
    print("L4: Package detection...")
    file_to_package = detect_packages(repo_path, files)
    packages = defaultdict(list)
    for f, pkg in file_to_package.items():
        packages[pkg].append(f)
    print(f"  Packages: {len(packages)}")

    # ── Layer 6: Co-change with IDF ──
    print("L6: Co-change with IDF...")
    cc_graph = build_cochange_graph_idf(repo_path, files)
    cc_edges = cc_graph.number_of_edges()

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
    print(f"  Edges: {cc_edges}, after cap: {cc_capped.number_of_edges()}")

    # ── Layer 5: Semantic orphan rescue ──
    print("L5: Semantic orphan rescue...")
    orphans = {n for n in files if combined.degree(n) == 0}
    sem_edges, file_terms = build_semantic_edges(repo_path, files, orphans, file_to_package, threshold=0.4)

    for u, v, w in sem_edges:
        if combined.has_edge(u, v):
            combined[u][v]["weight"] += w * 0.5
        else:
            combined.add_edge(u, v, weight=w * 0.5)
    print(f"  Orphans: {len(orphans)}, semantic edges: {len(sem_edges)}")

    # ── Global degree cap ──
    GLOBAL_MAX_DEGREE = 50
    for node in list(combined.nodes()):
        neighbors = list(combined[node].items())
        if len(neighbors) > GLOBAL_MAX_DEGREE:
            sorted_nbrs = sorted(neighbors, key=lambda x: x[1]["weight"], reverse=True)
            for nbr, _ in sorted_nbrs[GLOBAL_MAX_DEGREE:]:
                combined.remove_edge(node, nbr)

    connected = sum(1 for n in files if combined.degree(n) > 0)
    print(f"\nCombined graph: {combined.number_of_edges()} edges, {connected}/{len(files)} connected")

    # ── Clustering ──
    print("\nClustering (Leiden + CPM)...")
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

    # Build cluster objects
    cluster_to_files = defaultdict(list)
    for f, cid in best_clusters.items():
        cluster_to_files[cid].append(f)

    # Recursive splitting
    max_cluster_size = max(40, int(len(files) * 0.08))
    next_id = max(cluster_to_files.keys()) + 1
    total_splits = 0

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
                total_splits += 1

    # Post-clustering adoption
    file_to_cluster = {}
    for cid, cfiles in cluster_to_files.items():
        for f in cfiles:
            file_to_cluster[f] = cid

    adopted = 0
    for cid in list(cluster_to_files.keys()):
        cfiles = cluster_to_files[cid]
        if len(cfiles) != 1:
            continue
        f = cfiles[0]
        if combined.degree(f) == 0:
            continue

        nbr_clusters = Counter()
        for nbr in combined[f]:
            nbr_cid = file_to_cluster.get(nbr)
            if nbr_cid is not None and len(cluster_to_files.get(nbr_cid, [])) > 1:
                nbr_clusters[nbr_cid] += 1

        if not nbr_clusters:
            continue

        best_cid, best_count = nbr_clusters.most_common(1)[0]
        total_nbr_edges = sum(nbr_clusters.values())
        if len(nbr_clusters) == 1 or best_count >= total_nbr_edges * 2 / 3:
            del cluster_to_files[cid]
            cluster_to_files[best_cid].append(f)
            file_to_cluster[f] = best_cid
            adopted += 1

    # Directory-based rescue
    dir_rescued = 0
    for cid in list(cluster_to_files.keys()):
        cfiles = cluster_to_files[cid]
        if len(cfiles) != 1:
            continue
        f = cfiles[0]
        parent = os.path.dirname(f)
        if not parent:
            continue

        dir_clusters = Counter()
        for other_f in files:
            if other_f == f or os.path.dirname(other_f) != parent:
                continue
            other_cid = file_to_cluster.get(other_f)
            if other_cid is not None and len(cluster_to_files.get(other_cid, [])) > 1:
                dir_clusters[other_cid] += 1

        if not dir_clusters:
            continue

        best_cid, best_count = dir_clusters.most_common(1)[0]
        total_dir_files = sum(dir_clusters.values())
        if total_dir_files >= 2 and best_count >= total_dir_files * 2 / 3:
            del cluster_to_files[cid]
            cluster_to_files[best_cid].append(f)
            file_to_cluster[f] = best_cid
            dir_rescued += 1

    n_final = len(cluster_to_files)
    singletons = sum(1 for cid, cf in cluster_to_files.items() if len(cf) == 1)
    print(f"Clusters: {n_final} ({singletons} singletons), MQ: {best_mq:.4f}, res: {best_res}")
    if total_splits > 0:
        print(f"Recursive splits: {total_splits}")
    if adopted > 0:
        print(f"Adopted: {adopted} singletons")
    if dir_rescued > 0:
        print(f"Directory rescued: {dir_rescued} singletons")

    # Label clusters for display
    used_labels = set()
    cluster_labels = {}
    for cid, cfiles in sorted(cluster_to_files.items(), key=lambda x: -len(x[1])):
        lbl = label_cluster(cfiles, file_terms, used_labels)
        used_labels.add(lbl)
        cluster_labels[cid] = lbl

    return file_to_cluster, cluster_labels, cluster_to_files


def get_commits(repo_path: str, max_count: int = 500):
    """Get all non-merge commits with their changed files."""
    result = subprocess.run(
        ["git", "log", f"--max-count={max_count}", "--no-merges",
         "--pretty=format:--COMMIT--%H|%s", "--name-only"],
        cwd=repo_path, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git log failed: {result.stderr}")

    commits = []
    current_hash = None
    current_msg = None
    current_files = []

    for line in result.stdout.split("\n"):
        line = line.strip()
        if line.startswith("--COMMIT--"):
            if current_hash:
                commits.append((current_hash, current_msg, current_files))
            rest = line[len("--COMMIT--"):]
            parts = rest.split("|", 1)
            current_hash = parts[0]
            current_msg = parts[1] if len(parts) > 1 else ""
            current_files = []
        elif line:
            current_files.append(line)

    if current_hash:
        commits.append((current_hash, current_msg, current_files))

    return commits


def is_code_file(f: str) -> bool:
    ext = os.path.splitext(f)[1].lower()
    return ext in CODE_EXTENSIONS


def is_wip_or_bulk(msg: str, n_files: int) -> bool:
    if n_files > 30:
        return True
    if WIP_PATTERNS.search(msg):
        return True
    return False


def compute_coherence(changed_files: list[str], file_to_cluster: dict[str, int]):
    """
    Coherence = best_cluster_count / total_changed_files.
    Only count files that are in the clustering (i.e., exist in the repo's file set).
    """
    cluster_counts = Counter()
    mapped = 0
    for f in changed_files:
        cid = file_to_cluster.get(f)
        if cid is not None:
            cluster_counts[cid] += 1
            mapped += 1

    if mapped == 0:
        return None, 0, 0, {}

    best_cluster, best_count = cluster_counts.most_common(1)[0]
    coherence = best_count / mapped
    return coherence, best_count, mapped, cluster_counts


def size_bucket(n: int) -> str:
    if n == 2:
        return "2 files"
    elif 3 <= n <= 5:
        return "3-5 files"
    elif 6 <= n <= 10:
        return "6-10 files"
    elif 11 <= n <= 20:
        return "11-20 files"
    elif 21 <= n <= 30:
        return "21-30 files"
    else:
        return ">30 files"


def main():
    print()
    print("=" * 70)
    print("  RETROSPECTIVE COMMIT COHERENCE VALIDATION")
    print("  travel-prod: ALL commits, 6-layer pipeline")
    print("=" * 70)
    print()

    # Step 1: Build the clustering
    file_to_cluster, cluster_labels, cluster_to_files = build_full_pipeline(REPO_PATH)

    # Step 2: Get all commits
    print()
    print("=" * 70)
    print("  ANALYZING COMMITS")
    print("=" * 70)
    print()

    commits = get_commits(REPO_PATH, max_count=500)
    print(f"Total non-merge commits: {len(commits)}")

    # Step 3: Filter to multi-file code commits and compute coherence
    focused_results = []
    wip_results = []
    skipped_single = 0
    skipped_no_code = 0

    for commit_hash, msg, all_files in commits:
        code_files = [f for f in all_files if is_code_file(f)]
        if len(code_files) < 2:
            if len(code_files) == 0:
                skipped_no_code += 1
            else:
                skipped_single += 1
            continue

        coherence, best_count, mapped, cluster_dist = compute_coherence(code_files, file_to_cluster)
        if coherence is None:
            continue

        entry = {
            "hash": commit_hash[:8],
            "msg": msg[:80],
            "total_code_files": len(code_files),
            "mapped": mapped,
            "coherence": coherence,
            "best_count": best_count,
            "cluster_dist": cluster_dist,
        }

        if is_wip_or_bulk(msg, len(code_files)):
            wip_results.append(entry)
        else:
            focused_results.append(entry)

    print(f"Skipped: {skipped_single} single-file, {skipped_no_code} no-code-files")
    print(f"Multi-file code commits: {len(focused_results) + len(wip_results)}")
    print(f"  Focused: {len(focused_results)}")
    print(f"  WIP/bulk: {len(wip_results)}")

    # Step 4: Compute statistics
    print()
    print("=" * 70)
    print("  COHERENCE RESULTS")
    print("=" * 70)

    def print_stats(label: str, results: list[dict]):
        if not results:
            print(f"\n{label}: no commits")
            return

        coherences = [r["coherence"] for r in results]
        coherences.sort()
        n = len(coherences)
        mean = sum(coherences) / n
        median = coherences[n // 2]
        p25 = coherences[n // 4]
        p75 = coherences[3 * n // 4]
        pct_above_80 = sum(1 for c in coherences if c >= 0.8) * 100 / n
        pct_above_50 = sum(1 for c in coherences if c >= 0.5) * 100 / n
        perfect = sum(1 for c in coherences if c == 1.0) * 100 / n

        print(f"\n  {label} (n={n})")
        print(f"  {'─' * 50}")
        print(f"    Mean coherence:     {mean:.3f}")
        print(f"    Median coherence:   {median:.3f}")
        print(f"    P25:                {p25:.3f}")
        print(f"    P75:                {p75:.3f}")
        print(f"    Min:                {min(coherences):.3f}")
        print(f"    Max:                {max(coherences):.3f}")
        print(f"    Perfect (1.0):      {perfect:.1f}%")
        print(f"    >= 0.80:            {pct_above_80:.1f}%")
        print(f"    >= 0.50:            {pct_above_50:.1f}%")

    print_stats("FOCUSED commits (non-WIP, non-refactor, ≤30 files)", focused_results)
    print_stats("WIP/BULK commits (WIP, refactor, scaffold, >30 files)", wip_results)

    # Step 5: Size bucket breakdown for focused commits
    print()
    print("=" * 70)
    print("  FOCUSED COMMITS BY SIZE BUCKET")
    print("=" * 70)

    bucket_order = ["2 files", "3-5 files", "6-10 files", "11-20 files", "21-30 files"]
    buckets = defaultdict(list)
    for r in focused_results:
        b = size_bucket(r["mapped"])
        buckets[b].append(r["coherence"])

    print()
    print(f"  {'Bucket':<14} {'N':>5} {'Mean':>7} {'Median':>8} {'P25':>7} {'P75':>7} {'>=0.8':>7} {'=1.0':>7}")
    print(f"  {'─' * 68}")

    for b in bucket_order:
        vals = buckets.get(b, [])
        if not vals:
            print(f"  {b:<14} {'0':>5} {'--':>7} {'--':>8} {'--':>7} {'--':>7} {'--':>7} {'--':>7}")
            continue
        vals.sort()
        n = len(vals)
        mean = sum(vals) / n
        median = vals[n // 2]
        p25 = vals[n // 4] if n >= 4 else vals[0]
        p75 = vals[3 * n // 4] if n >= 4 else vals[-1]
        pct80 = sum(1 for v in vals if v >= 0.8) * 100 / n
        pct100 = sum(1 for v in vals if v == 1.0) * 100 / n
        print(f"  {b:<14} {n:>5} {mean:>7.3f} {median:>8.3f} {p25:>7.3f} {p75:>7.3f} {pct80:>6.1f}% {pct100:>6.1f}%")

    # Step 6: Show lowest-coherence focused commits (interesting cases)
    print()
    print("=" * 70)
    print("  LOWEST COHERENCE FOCUSED COMMITS (bottom 15)")
    print("=" * 70)
    print()

    focused_sorted = sorted(focused_results, key=lambda r: r["coherence"])
    for r in focused_sorted[:15]:
        dist_str = ", ".join(
            f"{cluster_labels.get(cid, f'c{cid}')}:{cnt}"
            for cid, cnt in r["cluster_dist"].most_common(4)
        )
        print(f"  {r['hash']}  coh={r['coherence']:.2f}  files={r['mapped']:>2}  {r['msg']}")
        print(f"           clusters: {dist_str}")

    # Step 7: Show highest-coherence focused commits
    print()
    print("=" * 70)
    print("  HIGHEST COHERENCE FOCUSED COMMITS (top 15)")
    print("=" * 70)
    print()

    focused_sorted_desc = sorted(focused_results, key=lambda r: (-r["coherence"], -r["mapped"]))
    shown = 0
    for r in focused_sorted_desc:
        if shown >= 15:
            break
        # Only show commits with 3+ files for interest
        if r["mapped"] >= 3:
            dist_str = ", ".join(
                f"{cluster_labels.get(cid, f'c{cid}')}:{cnt}"
                for cid, cnt in r["cluster_dist"].most_common(4)
            )
            print(f"  {r['hash']}  coh={r['coherence']:.2f}  files={r['mapped']:>2}  {r['msg']}")
            print(f"           clusters: {dist_str}")
            shown += 1

    # Step 8: WIP/bulk detail
    if wip_results:
        print()
        print("=" * 70)
        print("  WIP/BULK COMMITS (all)")
        print("=" * 70)
        print()

        for r in sorted(wip_results, key=lambda r: r["coherence"]):
            dist_str = ", ".join(
                f"{cluster_labels.get(cid, f'c{cid}')}:{cnt}"
                for cid, cnt in r["cluster_dist"].most_common(4)
            )
            print(f"  {r['hash']}  coh={r['coherence']:.2f}  files={r['mapped']:>2}  {r['msg']}")
            print(f"           clusters: {dist_str}")

    # Step 9: Overall summary
    all_results = focused_results + wip_results
    all_coherences = [r["coherence"] for r in all_results]
    focused_coherences = [r["coherence"] for r in focused_results]
    wip_coherences = [r["coherence"] for r in wip_results]

    print()
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print()
    print(f"  Total multi-file code commits analyzed: {len(all_results)}")
    print()

    def safe_mean(vals):
        return sum(vals) / len(vals) if vals else 0

    def safe_median(vals):
        if not vals:
            return 0
        s = sorted(vals)
        return s[len(s) // 2]

    print(f"  {'Category':<35} {'N':>5} {'Mean':>7} {'Median':>8} {'>=0.8':>7}")
    print(f"  {'─' * 65}")
    for label, vals in [
        ("All multi-file commits", all_coherences),
        ("Focused (non-WIP, ≤30 files)", focused_coherences),
        ("WIP/bulk", wip_coherences),
    ]:
        if vals:
            mean = safe_mean(vals)
            med = safe_median(vals)
            pct80 = sum(1 for v in vals if v >= 0.8) * 100 / len(vals)
            print(f"  {label:<35} {len(vals):>5} {mean:>7.3f} {med:>8.3f} {pct80:>6.1f}%")
        else:
            print(f"  {label:<35} {'0':>5} {'--':>7} {'--':>8} {'--':>7}")

    print()
    print("  Interpretation:")
    f_mean = safe_mean(focused_coherences)
    w_mean = safe_mean(wip_coherences) if wip_coherences else 0
    if f_mean > 0.7:
        print("    Focused commit coherence > 0.70: clustering captures developer intent well.")
    elif f_mean > 0.5:
        print("    Focused commit coherence 0.50-0.70: clustering partially captures intent.")
    else:
        print("    Focused commit coherence < 0.50: clustering does not align with commit patterns.")

    if wip_coherences and f_mean > w_mean + 0.05:
        print(f"    Focused vs WIP gap: {f_mean - w_mean:.3f} (focused commits are more coherent, as expected)")
    elif wip_coherences:
        print(f"    Focused vs WIP gap: {f_mean - w_mean:.3f} (small gap, WIP commits may also be focused)")

    print()


if __name__ == "__main__":
    main()
