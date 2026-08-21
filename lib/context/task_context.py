"""Task Context — Layer 2, Dimension 2.

Architect reasoning, upstream decisions, downstream expectations,
cross-task risk indicators. Answers: "What decisions affect this task?"

Usage:
    from lib.context.task_context import build_task_context
    ctx = build_task_context(task, all_tasks, csg, completed_tasks)

Tech spec: tech-spec-context-constructor.md → Layer 2 § Task Context
"""

from __future__ import annotations

import os
from typing import Any

from .utils import write_json, read_json


def build_task_context(
    task: dict,
    all_tasks: list[dict],
    csg: dict | None = None,
    completed_tasks: dict[str, dict] | None = None,
) -> dict:
    """Build task context for a task.

    Args:
        task: task dict (with rationale, assumptions, depends_on, etc.)
        all_tasks: all tasks in the DAG
        csg: semantic-graph.json (for cross-task risk)
        completed_tasks: {task_id: output_dict} for completed dependency tasks

    Returns:
        task-context.json dict.
    """
    task_id = task.get("id", "")
    completed = completed_tasks or {}

    # Sub-dimension A: Architect Reasoning
    reasoning = {
        "rationale": task.get("rationale", ""),
        "assumptions": task.get("assumptions", []),
    }

    # Sub-dimension B: Upstream Decisions
    upstream = []
    depends_on = task.get("depends_on", [])
    if isinstance(depends_on, str):
        depends_on = [depends_on]

    for dep_id in depends_on:
        dep_task = _find_task(dep_id, all_tasks)
        if not dep_task:
            continue

        dep_output = completed.get(dep_id, {})
        upstream.append({
            "task_id": dep_id,
            "title": dep_task.get("title", dep_task.get("description", "")),
            "decisions": dep_output.get("decisions", []),
            "concerns": dep_output.get("concerns", []),
            "files_modified": dep_output.get("files_modified", dep_task.get("files_touched", [])),
        })

    # Sub-dimension C: Downstream Awareness
    downstream = []
    for other_task in all_tasks:
        other_id = other_task.get("id", "")
        if other_id == task_id:
            continue
        other_deps = other_task.get("depends_on", [])
        if isinstance(other_deps, str):
            other_deps = [other_deps]
        if task_id in other_deps:
            downstream.append({
                "task_id": other_id,
                "title": other_task.get("title", other_task.get("description", "")),
                "depends_on_me_for": other_task.get("description", ""),
                "files_will_touch": other_task.get("files_touched", []),
            })

    # Sub-dimension D: Cross-Task Risk Indicators
    shared_scope_warnings = []
    if csg:
        shared_scope_warnings = _compute_cross_task_risk(task, all_tasks, csg)

    # Sub-dimension E: Sibling-Owned Files
    # Maps files owned by other tasks so the developer knows what NOT to touch.
    sibling_owned_files: dict[str, str] = {}
    my_files = set(task.get("files_touched", []))
    for other_task in all_tasks:
        other_id = other_task.get("id", "")
        if other_id == task_id:
            continue
        for f in other_task.get("files_touched", []):
            if f not in my_files:
                sibling_owned_files[f] = other_id

    return {
        "reasoning": reasoning,
        "upstream": upstream,
        "downstream": downstream,
        "shared_scope_warnings": shared_scope_warnings,
        "sibling_owned_files": sibling_owned_files,
    }


def _compute_cross_task_risk(
    task: dict,
    all_tasks: list[dict],
    csg: dict,
) -> list[dict]:
    """Find symbols modified by this task that are also modified by other tasks."""
    task_id = task.get("id", "")
    files_touched = set(task.get("files_touched", []))

    # Find symbols in this task's files
    my_symbols = {
        n["id"]: n for n in csg.get("nodes", [])
        if n["file"] in files_touched
    }

    warnings = []
    for other_task in all_tasks:
        other_id = other_task.get("id", "")
        if other_id == task_id:
            continue

        other_files = set(other_task.get("files_touched", []))
        shared_files = files_touched & other_files

        if not shared_files:
            continue

        # Find shared symbols
        for sid, node in my_symbols.items():
            if node["file"] in shared_files:
                impact = node.get("impact", {})
                warnings.append({
                    "symbol": sid,
                    "also_modified_by": [other_id],
                    "impact": {
                        "blast_radius": impact.get("blast_radius", 0),
                        "stability": impact.get("stability", "unknown"),
                    },
                    "warning": (
                        f"Task {other_id} also modifies {node['file']}. "
                        f"Changes to shared interfaces require coordination."
                    ),
                })

    return warnings


def _find_task(task_id: str, all_tasks: list[dict]) -> dict | None:
    """Find a task by ID in the task list."""
    for t in all_tasks:
        if t.get("id") == task_id:
            return t
    return None


# ── Persistence ──────────────────────────────────────────────


def save_task_context(task_context: dict, task_context_dir: str) -> str:
    path = os.path.join(task_context_dir, "task-context.json")
    write_json(path, task_context)
    return path


def load_task_context(task_context_dir: str) -> dict:
    path = os.path.join(task_context_dir, "task-context.json")
    return read_json(path)
