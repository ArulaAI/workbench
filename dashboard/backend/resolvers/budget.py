"""Context budget resolver — reads per-task budget.json files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def get_context_budget(
    project_root: str,
    feature: str | None = None,
) -> dict[str, Any]:
    """Read per-task budget.json files and join with task titles.

    Budget files: .speed/context/tasks/{id}/context/budget.json
    Task files:   .speed/features/{feature}/tasks/{id}.json
    """
    from ..paths import get_paths
    paths = get_paths(project_root)
    tasks_context_dir = paths.context_dir / "tasks"

    task_budgets = []

    if not tasks_context_dir.is_dir():
        return {"tasks": [], "summary": _empty_summary()}

    # Build task title lookup from all features
    task_titles: dict[str, str] = {}
    for fname in paths.feature_names():
        if feature and fname != feature:
            continue
        tasks_dir = paths.feature_shared(fname) / "tasks"
        if tasks_dir.is_dir():
            for tf in tasks_dir.glob("*.json"):
                try:
                    td = json.loads(tf.read_text(encoding="utf-8"))
                    task_titles[tf.stem] = td.get("title", f"Task {tf.stem}")
                except (json.JSONDecodeError, OSError):
                    pass

    # Read each task's budget
    total_budget_all = 0
    total_used_all = 0
    total_cuts = 0

    for task_dir in sorted(tasks_context_dir.iterdir(), key=_dir_sort_key):
        if not task_dir.is_dir():
            continue
        budget_path = task_dir / "context" / "budget.json"
        if not budget_path.exists():
            continue

        try:
            budget = json.loads(budget_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        task_id = task_dir.name
        allocated = budget.get("allocated", {})
        cuts = budget.get("cuts_made", [])

        entry = {
            "task_id": task_id,
            "title": task_titles.get(task_id, f"Task {task_id}"),
            "stage": budget.get("stage", "unknown"),
            "total_budget": budget.get("total_budget", 0),
            "total_used": budget.get("total_used", 0),
            "under_budget": budget.get("under_budget", True),
            "allocated": {
                "code_context": allocated.get("code_context", {}),
                "task_context": allocated.get("task_context", {}),
                "spec_context": allocated.get("spec_context", {}),
                "reserve": allocated.get("reserve", 0),
            },
            "cuts_made": cuts,
            "cuts_count": len(cuts),
            "tokens_saved": sum(c.get("tokens_saved", 0) for c in cuts),
        }

        total_budget_all += entry["total_budget"]
        total_used_all += entry["total_used"]
        total_cuts += len(cuts)

        task_budgets.append(entry)

    summary = {
        "task_count": len(task_budgets),
        "total_budget": total_budget_all,
        "total_used": total_used_all,
        "utilization_pct": round(
            (total_used_all / total_budget_all * 100) if total_budget_all > 0 else 0, 1
        ),
        "total_cuts": total_cuts,
        "under_budget_count": sum(1 for t in task_budgets if t["under_budget"]),
        "over_budget_count": sum(1 for t in task_budgets if not t["under_budget"]),
    }

    return {"tasks": task_budgets, "summary": summary}


def _empty_summary() -> dict[str, Any]:
    return {
        "task_count": 0,
        "total_budget": 0,
        "total_used": 0,
        "utilization_pct": 0.0,
        "total_cuts": 0,
        "under_budget_count": 0,
        "over_budget_count": 0,
    }


def _dir_sort_key(path: Path) -> int:
    try:
        return int(path.name)
    except ValueError:
        return 999999
