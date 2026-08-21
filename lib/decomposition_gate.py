"""Decomposition Quality Gate — Verification System.

Runs in cmd_plan after Architect output is parsed, before task creation.
Catches decomposition problems before any developer agent starts.

Four checks:
  1. Task size heuristic — sum lines from project map, thresholds <3K/3-5K/>5K
  2. Cross-cluster coordination cost — files_touched to CSG clusters, >15 edges = fail
  3. Bridge symbol exposure — bridge symbol modifications need downstream dependencies
  4. File ownership violation — parallel tasks with overlapping files_touched

Graceful degradation: without CSG, only checks 1 and 4 run.

Usage:
    from lib.decomposition_gate import check_decomposition
    result = check_decomposition(tasks, project_map, csg=csg)

Tech spec: tech-spec-context-constructor.md → Verification System § 1.3
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any


# ── Thresholds ───────────────────────────────────────────────
# Override via SPEED_TASK_SIZE_WARN / SPEED_TASK_SIZE_FAIL for
# projects with large monolithic files (e.g., declarative YAML manifests).

TASK_SIZE_WARN = int(os.environ.get("SPEED_TASK_SIZE_WARN", 3000))   # lines
TASK_SIZE_FAIL = int(os.environ.get("SPEED_TASK_SIZE_FAIL", 6000))   # lines
CROSS_CLUSTER_FAIL = 15  # edges


# ── Main entry point ─────────────────────────────────────────


def check_decomposition(
    tasks: list[dict],
    project_map: dict,
    csg: dict | None = None,
) -> dict:
    """Run all decomposition quality checks on a list of tasks.

    Args:
        tasks: list of task dicts (from Architect output)
        project_map: project-map.json dict
        csg: semantic-graph.json dict (or None for degraded mode)

    Returns:
        Dict with per-task results, overall verdict, and warnings.
    """
    per_task: list[dict] = []
    overall_pass = True
    warnings: list[str] = []

    # Build dependency graph for ownership check
    dep_graph = _build_dep_graph(tasks)

    for task in tasks:
        task_id = task.get("id", "?")
        task_result = {
            "task_id": task_id,
            "checks": [],
        }

        # Check 1: Task size (always runs)
        size_result = _check_task_size(task, project_map)
        task_result["checks"].append(size_result)
        if size_result["verdict"] == "fail":
            overall_pass = False
        elif size_result["verdict"] == "warn":
            warnings.append(f"Task {task_id}: {size_result['message']}")

        # Check 2: Cross-cluster coordination (needs CSG)
        if csg:
            cluster_result = _check_cross_cluster(task, csg)
            task_result["checks"].append(cluster_result)
            if cluster_result["verdict"] == "fail":
                overall_pass = False
        else:
            task_result["checks"].append({
                "check": "cross_cluster",
                "verdict": "skipped",
                "message": "CSG not available — skipping cross-cluster check",
            })

        # Check 3: Bridge symbol exposure (needs CSG)
        if csg:
            bridge_result = _check_bridge_symbols(task, tasks, csg, dep_graph)
            task_result["checks"].append(bridge_result)
            if bridge_result["verdict"] == "fail":
                overall_pass = False
        else:
            task_result["checks"].append({
                "check": "bridge_symbols",
                "verdict": "skipped",
                "message": "CSG not available — skipping bridge symbol check",
            })

        per_task.append(task_result)

    # Check 4: File ownership across all tasks (always runs)
    ownership_result = _check_file_ownership(tasks, dep_graph)
    if ownership_result["violations"]:
        overall_pass = False

    return {
        "overall": "pass" if overall_pass else "fail",
        "per_task": per_task,
        "file_ownership": ownership_result,
        "warnings": warnings,
    }


# ── Check 1: Task Size ──────────────────────────────────────


def _check_task_size(task: dict, project_map: dict) -> dict:
    """Sum lines for files_touched, check against thresholds."""
    files_touched = task.get("files_touched", [])
    task_id = task.get("id", "?")

    # Build file line count index from project map
    file_lines: dict[str, int] = {}
    for f in project_map.get("files", []):
        if f.get("lines") is not None:
            file_lines[f["path"]] = f["lines"]

    total_lines = 0
    file_details = []
    for f in files_touched:
        lines = file_lines.get(f, 0)
        total_lines += lines
        file_details.append(f"{f} ({lines})")

    if total_lines >= TASK_SIZE_FAIL:
        return {
            "check": "task_size",
            "verdict": "fail",
            "total_lines": total_lines,
            "message": f"Task {task_id} touches {total_lines} lines (>={TASK_SIZE_FAIL}) — needs splitting",
            "details": file_details,
        }
    elif total_lines > TASK_SIZE_WARN:
        return {
            "check": "task_size",
            "verdict": "warn",
            "total_lines": total_lines,
            "message": f"Task {task_id} touches {total_lines} lines ({TASK_SIZE_WARN}-{TASK_SIZE_FAIL}) — large but may be acceptable",
            "details": file_details,
        }
    else:
        return {
            "check": "task_size",
            "verdict": "pass",
            "total_lines": total_lines,
            "message": f"Task {task_id} touches {total_lines} lines (<{TASK_SIZE_WARN})",
        }


# ── Check 2: Cross-Cluster Coordination ─────────────────────


def _check_cross_cluster(task: dict, csg: dict) -> dict:
    """Resolve files_touched to CSG clusters, count cross-cluster edges."""
    files_touched = task.get("files_touched", [])
    task_id = task.get("id", "?")

    # Map files to clusters
    file_to_cluster: dict[str, set[str]] = defaultdict(set)
    for cluster in csg.get("clusters", []):
        for f in cluster.get("files", []):
            file_to_cluster[f].add(cluster["id"])

    # Find clusters touched by this task
    touched_clusters: set[str] = set()
    for f in files_touched:
        touched_clusters.update(file_to_cluster.get(f, set()))

    if len(touched_clusters) <= 1:
        return {
            "check": "cross_cluster",
            "verdict": "pass",
            "clusters_touched": len(touched_clusters),
            "cross_cluster_edges": 0,
            "message": f"Task {task_id} stays within {len(touched_clusters)} cluster(s)",
        }

    # Count cross-cluster edges between the touched clusters
    cross_edges = 0
    for ce in csg.get("cluster_edges", []):
        if ce["from"] in touched_clusters and ce["to"] in touched_clusters:
            cross_edges += ce.get("edge_count", 0)

    if cross_edges > CROSS_CLUSTER_FAIL:
        return {
            "check": "cross_cluster",
            "verdict": "fail",
            "clusters_touched": len(touched_clusters),
            "cross_cluster_edges": cross_edges,
            "message": (
                f"Task {task_id} has {cross_edges} cross-cluster edges "
                f"across {len(touched_clusters)} clusters (>{CROSS_CLUSTER_FAIL}) — split along cluster boundaries"
            ),
        }

    return {
        "check": "cross_cluster",
        "verdict": "pass",
        "clusters_touched": len(touched_clusters),
        "cross_cluster_edges": cross_edges,
        "message": f"Task {task_id}: {cross_edges} cross-cluster edges across {len(touched_clusters)} clusters",
    }


# ── Check 3: Bridge Symbol Exposure ─────────────────────────


def _check_bridge_symbols(
    task: dict,
    all_tasks: list[dict],
    csg: dict,
    dep_graph: dict[str, set[str]],
) -> dict:
    """Check if task modifies bridge symbols and has proper dependencies."""
    files_touched = task.get("files_touched", [])
    task_id = task.get("id", "?")

    # Find bridge symbols in files_touched
    bridge_symbols = []
    for node in csg.get("nodes", []):
        if (
            node.get("impact", {}).get("stability") == "bridge"
            and node["file"] in files_touched
        ):
            bridge_symbols.append(node)

    if not bridge_symbols:
        return {
            "check": "bridge_symbols",
            "verdict": "pass",
            "bridge_count": 0,
            "message": f"Task {task_id} does not modify any bridge symbols",
        }

    # For each bridge symbol, find dependents and check if they're covered
    # by tasks that depend on this task
    missing_deps = []
    dependent_tasks = dep_graph.get(task_id, set())  # tasks that depend on this one

    for bridge in bridge_symbols:
        bridge_id = bridge["id"]
        # Find all edges where this bridge symbol is referenced
        dependents = [
            e["from"] for e in csg.get("edges", [])
            if e["to"] == bridge_id and e["type"] in ("calls", "instantiates", "references_type", "accesses")
        ]

        # Find which tasks touch files containing these dependents
        dependent_files = set()
        for dep_symbol in dependents:
            for node in csg.get("nodes", []):
                if node["id"] == dep_symbol:
                    dependent_files.add(node["file"])
                    break

        for other_task in all_tasks:
            other_id = other_task.get("id", "?")
            if other_id == task_id:
                continue

            other_files = set(other_task.get("files_touched", []))
            affected_files = dependent_files & other_files

            if affected_files and other_id not in dependent_tasks:
                missing_deps.append({
                    "bridge_symbol": bridge_id,
                    "affected_task": other_id,
                    "affected_files": list(affected_files),
                })

    if missing_deps:
        return {
            "check": "bridge_symbols",
            "verdict": "fail",
            "bridge_count": len(bridge_symbols),
            "missing_dependencies": missing_deps,
            "message": (
                f"Task {task_id} modifies {len(bridge_symbols)} bridge symbol(s) "
                f"but {len(missing_deps)} downstream task(s) lack dependency edges"
            ),
        }

    return {
        "check": "bridge_symbols",
        "verdict": "pass",
        "bridge_count": len(bridge_symbols),
        "message": f"Task {task_id} modifies {len(bridge_symbols)} bridge symbol(s) — all downstream dependencies present",
    }


# ── Check 4: File Ownership ─────────────────────────────────


def _check_file_ownership(
    tasks: list[dict],
    dep_graph: dict[str, set[str]],
) -> dict:
    """Detect parallel tasks with overlapping files_touched."""
    # Build file → tasks mapping
    file_to_tasks: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        task_id = task.get("id", "?")
        for f in task.get("files_touched", []):
            file_to_tasks[f].append(task_id)

    violations = []
    for file_path, task_ids in file_to_tasks.items():
        if len(task_ids) < 2:
            continue

        # Check all pairs for missing dependency (direct or transitive)
        for i, t1 in enumerate(task_ids):
            for t2 in task_ids[i + 1:]:
                if not (
                    _is_transitive_dependent(t1, t2, dep_graph)
                    or _is_transitive_dependent(t2, t1, dep_graph)
                ):
                    violations.append({
                        "file": file_path,
                        "tasks": [t1, t2],
                        "message": f"Tasks {t1} and {t2} both touch '{file_path}' with no dependency between them",
                    })

    return {
        "violations": violations,
        "message": (
            f"{len(violations)} file ownership violation(s)"
            if violations
            else "No file ownership violations"
        ),
    }


# ── Helpers ──────────────────────────────────────────────────


def _is_transitive_dependent(
    source: str,
    target: str,
    dep_graph: dict[str, set[str]],
) -> bool:
    """Check if target transitively depends on source.

    dep_graph maps task_id → set of tasks that directly depend on it.
    BFS from source's direct dependents to see if target is reachable.
    """
    visited: set[str] = set()
    queue = list(dep_graph.get(source, set()))

    while queue:
        current = queue.pop(0)
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        for dependent in dep_graph.get(current, set()):
            if dependent not in visited:
                queue.append(dependent)

    return False


def _build_dep_graph(tasks: list[dict]) -> dict[str, set[str]]:
    """Build dependency graph: task_id → set of tasks that depend on it.

    Also includes reverse: if task B depends_on A, then A is in the
    "depended upon by" set for B's reference.
    """
    # Forward: task_id → set of task_ids it depends on
    depends_on: dict[str, set[str]] = {}
    # Reverse: task_id → set of task_ids that depend on it
    depended_by: dict[str, set[str]] = defaultdict(set)

    for task in tasks:
        task_id = task.get("id", "?")
        deps = task.get("depends_on", [])
        if isinstance(deps, str):
            deps = [deps]
        depends_on[task_id] = set(deps)
        for dep in deps:
            depended_by[dep].add(task_id)

    # For bridge symbol check, we need "tasks that depend on this task"
    # which is the depended_by direction
    return dict(depended_by)
