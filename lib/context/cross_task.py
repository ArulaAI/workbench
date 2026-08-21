"""Cross-Task Analysis — Layer 2.

Per-feature analysis of domain overlap, interface boundaries, and
high-impact modifications across tasks. Built once per feature at the
start of `speed run`.

Usage:
    from lib.context.cross_task import build_cross_task_analysis
    analysis = build_cross_task_analysis(tasks, csg)

Tech spec: tech-spec-context-constructor.md → Layer 2 § Cross-Task Analysis
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

from .utils import write_json, read_json


def build_cross_task_analysis(
    tasks: list[dict],
    csg: dict | None = None,
) -> dict:
    """Build cross-task analysis for a feature.

    Args:
        tasks: all tasks in the feature's DAG
        csg: semantic-graph.json dict (or None for degraded mode)

    Returns:
        cross-task-analysis.json dict with domain_overlap, interface_boundaries,
        high_impact_modifications.
    """
    domain_overlap = []
    interface_boundaries = []
    high_impact = []

    if not csg:
        # Degraded mode: only file-based overlap
        domain_overlap = _file_based_overlap(tasks)
        return {
            "domain_overlap": domain_overlap,
            "interface_boundaries": interface_boundaries,
            "high_impact_modifications": high_impact,
            "degraded": True,
        }

    # Build task → symbols mapping
    task_symbols: dict[str, set[str]] = {}
    task_files: dict[str, set[str]] = {}
    for task in tasks:
        tid = task.get("id", "")
        files = set(task.get("files_touched", []))
        task_files[tid] = files
        symbols = set()
        for node in csg.get("nodes", []):
            if node["file"] in files:
                symbols.add(node["id"])
        task_symbols[tid] = symbols

    # 1. Domain overlap — tasks sharing CSG clusters
    domain_overlap = _compute_domain_overlap(tasks, task_symbols, csg)

    # 2. Interface boundaries — symbols defined by one task, consumed by another
    interface_boundaries = _compute_interface_boundaries(tasks, task_symbols, csg)

    # 3. High-impact modifications — bridge symbols with downstream consumers
    high_impact = _compute_high_impact(tasks, task_symbols, csg)

    return {
        "domain_overlap": domain_overlap,
        "interface_boundaries": interface_boundaries,
        "high_impact_modifications": high_impact,
    }


def _compute_domain_overlap(
    tasks: list[dict],
    task_symbols: dict[str, set[str]],
    csg: dict,
) -> list[dict]:
    """Find clusters touched by multiple tasks."""
    # Map symbols to clusters
    symbol_to_cluster: dict[str, str] = {}
    for node in csg.get("nodes", []):
        cluster = node.get("cluster")
        if cluster:
            symbol_to_cluster[node["id"]] = cluster

    # Map clusters to tasks
    cluster_to_tasks: dict[str, set[str]] = defaultdict(set)
    cluster_symbols: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for tid, symbols in task_symbols.items():
        for sid in symbols:
            cluster = symbol_to_cluster.get(sid)
            if cluster:
                cluster_to_tasks[cluster].add(tid)
                cluster_symbols[cluster][tid].add(sid)

    overlaps = []
    for cluster, tids in cluster_to_tasks.items():
        if len(tids) < 2:
            continue

        # Find shared symbols across tasks
        all_syms = set()
        for tid in tids:
            all_syms.update(cluster_symbols[cluster][tid])

        # Count coordination edges (edges between symbols in different tasks)
        coord_edges = 0
        for edge in csg.get("edges", []):
            from_tasks = {tid for tid, syms in task_symbols.items() if edge["from"] in syms}
            to_tasks = {tid for tid, syms in task_symbols.items() if edge["to"] in syms}
            if from_tasks and to_tasks and from_tasks != to_tasks:
                coord_edges += 1

        # Risk classification
        bridge_count = sum(
            1 for sid in all_syms
            if _get_stability(sid, csg) == "bridge"
        )
        risk = "high" if bridge_count > 0 else ("medium" if coord_edges > 5 else "low")

        # Get symbol names
        sym_names = []
        for node in csg.get("nodes", []):
            if node["id"] in all_syms:
                sym_names.append(node["name"])

        overlaps.append({
            "cluster": cluster,
            "tasks_touching": sorted(tids),
            "shared_symbols": sym_names[:20],
            "coordination_edges": coord_edges,
            "risk": risk,
        })

    return overlaps


def _compute_interface_boundaries(
    tasks: list[dict],
    task_symbols: dict[str, set[str]],
    csg: dict,
) -> list[dict]:
    """Find symbols defined by one task and consumed by another."""
    boundaries = []

    task_ids = list(task_symbols.keys())
    for i, t1 in enumerate(task_ids):
        for t2 in task_ids[i + 1:]:
            syms1 = task_symbols[t1]
            syms2 = task_symbols[t2]

            # Find edges from t1's symbols to t2's symbols (and vice versa)
            interfaces = []
            reference_types = {"calls", "instantiates", "references_type", "accesses"}

            for edge in csg.get("edges", []):
                if edge["type"] not in reference_types:
                    continue

                if edge["from"] in syms1 and edge["to"] in syms2:
                    interfaces.append({
                        "symbol": edge["to"],
                        f"task_{t1}_role": "consumes",
                        f"task_{t2}_role": "defines",
                    })
                elif edge["from"] in syms2 and edge["to"] in syms1:
                    interfaces.append({
                        "symbol": edge["to"],
                        f"task_{t1}_role": "defines",
                        f"task_{t2}_role": "consumes",
                    })

            if interfaces:
                boundaries.append({
                    "from_task": t1,
                    "to_task": t2,
                    "interface_symbols": interfaces[:20],
                })

    return boundaries


def _compute_high_impact(
    tasks: list[dict],
    task_symbols: dict[str, set[str]],
    csg: dict,
) -> list[dict]:
    """Find bridge/high-centrality symbols being modified."""
    high_impact = []

    for tid, symbols in task_symbols.items():
        for sid in symbols:
            node = _find_node(sid, csg)
            if not node:
                continue
            impact = node.get("impact", {})
            if impact.get("stability") != "bridge" and impact.get("blast_radius", 0) < 10:
                continue

            # Find downstream consumer tasks
            consumers = []
            for edge in csg.get("edges", []):
                if edge["to"] == sid:
                    for other_tid, other_syms in task_symbols.items():
                        if other_tid != tid and edge["from"] in other_syms:
                            consumers.append(other_tid)

            if consumers or impact.get("blast_radius", 0) >= 10:
                high_impact.append({
                    "symbol": sid,
                    "modified_by": tid,
                    "blast_radius": impact.get("blast_radius", 0),
                    "centrality": impact.get("centrality", 0),
                    "stability": impact.get("stability", "unknown"),
                    "downstream_consumers": sorted(set(consumers)),
                })

    return high_impact


def _file_based_overlap(tasks: list[dict]) -> list[dict]:
    """Degraded mode: compute overlap based on shared files only."""
    file_to_tasks: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        tid = task.get("id", "")
        for f in task.get("files_touched", []):
            file_to_tasks[f].append(tid)

    overlaps = []
    for f, tids in file_to_tasks.items():
        if len(tids) >= 2:
            overlaps.append({
                "file": f,
                "tasks_touching": tids,
                "risk": "medium",
            })

    return overlaps


def _get_stability(symbol_id: str, csg: dict) -> str:
    """Get stability classification for a symbol."""
    for node in csg.get("nodes", []):
        if node["id"] == symbol_id:
            return node.get("impact", {}).get("stability", "unknown")
    return "unknown"


def _find_node(symbol_id: str, csg: dict) -> dict | None:
    for node in csg.get("nodes", []):
        if node["id"] == symbol_id:
            return node
    return None


# ── Persistence ──────────────────────────────────────────────


def save_cross_task_analysis(analysis: dict, feature_context_dir: str) -> str:
    path = os.path.join(feature_context_dir, "cross-task-analysis.json")
    write_json(path, analysis)
    return path


def load_cross_task_analysis(feature_context_dir: str) -> dict:
    path = os.path.join(feature_context_dir, "cross-task-analysis.json")
    return read_json(path)
