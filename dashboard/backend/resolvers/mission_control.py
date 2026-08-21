"""Mission Control resolver — reads task JSON + state from the filesystem."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def get_mission_control(
    project_root: str, feature: str
) -> dict[str, Any] | None:
    """Compose the full mission control view for a feature.

    In MP mode, tasks/contracts are in shared/, state.json is in local/.
    """
    from ..paths import get_paths
    paths = get_paths(project_root)
    shared = paths.feature_shared(feature)
    local = paths.feature_local(feature)

    if not shared.is_dir():
        return None

    # state.json lives in local zone
    state = _read_json(local / "state.json") or {
        "status": "unknown",
        "agents": [],
    }

    # Tasks live in shared zone
    tasks_dir = shared / "tasks"
    tasks: list[dict[str, Any]] = []
    if tasks_dir.is_dir():
        for tf in sorted(tasks_dir.glob("*.json"), key=lambda p: _task_sort_key(p)):
            task = _read_json(tf)
            if task:
                tasks.append(task)

    # cross-task-analysis may be in either zone
    cross_task = _read_json(shared / "cross-task-analysis.json") or _read_json(local / "cross-task-analysis.json")

    # Compute status summary
    status_counts: dict[str, int] = {}
    for t in tasks:
        s = t.get("status", "pending")
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "feature": feature,
        "state": state,
        "tasks": tasks,
        "task_count": len(tasks),
        "status_counts": status_counts,
        "cross_task_analysis": cross_task,
    }


def get_task_detail(
    project_root: str, feature: str, task_id: str
) -> dict[str, Any] | None:
    """Fetch a single task with its full details."""
    from ..paths import get_paths
    paths = get_paths(project_root)
    path = paths.feature_shared(feature) / "tasks" / f"{task_id}.json"
    return _read_json(path)


def list_features(project_root: str) -> list[dict[str, Any]]:
    """List all features with their state and task counts."""
    from ..paths import get_paths
    paths = get_paths(project_root)

    results = []
    for name in paths.feature_names():
        shared = paths.feature_shared(name)
        local = paths.feature_local(name)
        state = _read_json(local / "state.json") or {"status": "idle"}
        tasks_dir = shared / "tasks"
        task_count = len(list(tasks_dir.glob("*.json"))) if tasks_dir.is_dir() else 0

        results.append({
            "name": name,
            "status": state.get("status", "idle"),
            "started_at": state.get("started_at"),
            "task_count": task_count,
        })

    return results


def _read_json(path: Path) -> dict[str, Any] | None:
    """Safely read a JSON file, returning None on any error."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _task_sort_key(path: Path) -> int:
    """Sort task files numerically by their stem (1.json, 2.json, ...)."""
    try:
        return int(path.stem)
    except ValueError:
        return 999999
