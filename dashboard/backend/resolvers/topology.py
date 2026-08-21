"""Codebase topology resolver — reads semantic-graph.json (CSG)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def get_codebase_topology(
    project_root: str,
) -> dict[str, Any] | None:
    """Read the full CSG and return nodes, edges, cluster summaries."""
    from ..paths import get_paths
    paths = get_paths(project_root)
    csg_path = paths.context_dir / "semantic-graph.json"

    if not csg_path.exists():
        return None

    try:
        data = json.loads(csg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    # Build cluster summaries
    clusters: dict[str, dict[str, Any]] = {}
    for node in nodes:
        cid = node.get("cluster", "unclustered")
        if cid not in clusters:
            clusters[cid] = {
                "id": cid,
                "symbol_count": 0,
                "files": set(),
                "kinds": set(),
                "avg_blast_radius": 0.0,
                "total_blast_radius": 0,
            }
        c = clusters[cid]
        c["symbol_count"] += 1
        c["files"].add(node.get("file", ""))
        c["kinds"].add(node.get("kind", ""))
        impact = node.get("impact", {})
        c["total_blast_radius"] += impact.get("blast_radius", 0)

    # Finalize cluster data (convert sets to lists, compute averages)
    cluster_list = []
    for cid, c in sorted(clusters.items()):
        if c["symbol_count"] > 0:
            c["avg_blast_radius"] = c["total_blast_radius"] / c["symbol_count"]
        c["files"] = sorted(c["files"])
        c["kinds"] = sorted(c["kinds"])
        del c["total_blast_radius"]
        cluster_list.append(c)

    # Build cluster-level edges (edges between different clusters)
    node_cluster: dict[str, str] = {n["id"]: n.get("cluster", "") for n in nodes}
    cluster_edges_set: set[tuple[str, str]] = set()
    for edge in edges:
        src_cluster = node_cluster.get(edge.get("from", ""), "")
        tgt_cluster = node_cluster.get(edge.get("to", ""), "")
        if src_cluster and tgt_cluster and src_cluster != tgt_cluster:
            cluster_edges_set.add((src_cluster, tgt_cluster))

    cluster_edges = [
        {"source": s, "target": t} for s, t in sorted(cluster_edges_set)
    ]

    return {
        "generated_at": data.get("generated_at"),
        "git_head": data.get("git_head"),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "cluster_count": len(cluster_list),
        "nodes": nodes,
        "edges": [
            {"source": e.get("from", ""), "target": e.get("to", ""), "type": e.get("type", "")}
            for e in edges
        ],
        "clusters": cluster_list,
        "cluster_edges": cluster_edges,
    }


def get_cluster_detail(
    project_root: str, cluster_id: str
) -> dict[str, Any] | None:
    """Get all nodes and internal edges for a specific cluster."""
    topo = get_codebase_topology(project_root)
    if not topo:
        return None

    cluster_nodes = [n for n in topo["nodes"] if n.get("cluster") == cluster_id]
    cluster_node_ids = {n["id"] for n in cluster_nodes}

    # Internal edges: both endpoints in this cluster
    internal_edges = [
        e for e in topo["edges"]
        if e["source"] in cluster_node_ids and e["target"] in cluster_node_ids
    ]

    # External edges: one endpoint in cluster, one outside
    external_edges = [
        e for e in topo["edges"]
        if (e["source"] in cluster_node_ids) != (e["target"] in cluster_node_ids)
    ]

    return {
        "cluster_id": cluster_id,
        "nodes": cluster_nodes,
        "internal_edges": internal_edges,
        "external_edges": external_edges,
    }
