"""Tests for dashboard/backend/resolvers/budget.py.

Covers empty state, single and multiple task budgets, title resolution
from feature task JSON, feature filtering, missing budget files, cuts
aggregation, and multiplayer directory layout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add the dashboard/ directory so 'backend' resolves as a top-level package.
_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.paths import _cache
from backend.resolvers.budget import get_context_budget


# ── Fixtures ──────────────────────────────────────────────────────


BUDGET_FIXTURE = {
    "total_budget": 50000,
    "total_used": 30000,
    "under_budget": True,
    "allocated": {
        "code_context": {"budget": 20000, "used": 15000, "files": 5},
        "task_context": {"budget": 15000, "used": 10000, "files": 3},
        "spec_context": {"budget": 10000, "used": 5000, "files": 2},
        "reserve": 5000,
    },
    "cuts_made": [],
    "cuts_count": 0,
    "tokens_saved": 0,
}

TASK_FIXTURE = {"id": "1", "title": "Implement resolver", "status": "done"}


@pytest.fixture(autouse=True)
def _clear_paths_cache():
    """Prevent stale SpeedPaths instances from leaking between tests."""
    _cache.clear()
    yield
    _cache.clear()


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ── Tests ─────────────────────────────────────────────────────────


def test_no_context_dir(tmp_path: Path) -> None:
    """No .speed/context/tasks/ directory returns empty tasks and empty summary."""
    (tmp_path / ".speed").mkdir()

    result = get_context_budget(str(tmp_path))

    assert result["tasks"] == []
    summary = result["summary"]
    assert summary["task_count"] == 0
    assert summary["total_budget"] == 0
    assert summary["total_used"] == 0
    assert summary["utilization_pct"] == 0.0
    assert summary["total_cuts"] == 0
    assert summary["under_budget_count"] == 0
    assert summary["over_budget_count"] == 0


def test_no_budget_files(tmp_path: Path) -> None:
    """Context tasks dir exists but is empty returns empty tasks."""
    (tmp_path / ".speed" / "context" / "tasks").mkdir(parents=True)

    result = get_context_budget(str(tmp_path))

    assert result["tasks"] == []
    assert result["summary"]["task_count"] == 0


def test_single_task_budget(tmp_path: Path) -> None:
    """A valid budget.json paired with a task JSON produces correct fields."""
    _write_json(
        tmp_path / ".speed" / "context" / "tasks" / "1" / "context" / "budget.json",
        BUDGET_FIXTURE,
    )
    _write_json(
        tmp_path / ".speed" / "features" / "my-feat" / "tasks" / "1.json",
        TASK_FIXTURE,
    )

    result = get_context_budget(str(tmp_path))

    assert len(result["tasks"]) == 1
    task = result["tasks"][0]
    assert task["task_id"] == "1"
    assert task["title"] == "Implement resolver"
    assert task["total_budget"] == 50000
    assert task["total_used"] == 30000
    assert task["under_budget"] is True
    assert task["allocated"]["code_context"] == {"budget": 20000, "used": 15000, "files": 5}
    assert task["allocated"]["task_context"] == {"budget": 15000, "used": 10000, "files": 3}
    assert task["allocated"]["spec_context"] == {"budget": 10000, "used": 5000, "files": 2}
    assert task["allocated"]["reserve"] == 5000
    assert task["cuts_made"] == []
    assert task["cuts_count"] == 0
    assert task["tokens_saved"] == 0

    summary = result["summary"]
    assert summary["task_count"] == 1
    assert summary["total_budget"] == 50000
    assert summary["total_used"] == 30000
    assert summary["utilization_pct"] == 60.0
    assert summary["under_budget_count"] == 1
    assert summary["over_budget_count"] == 0


def test_feature_filter(tmp_path: Path) -> None:
    """Filtering by feature name returns only that feature's tasks."""
    _write_json(
        tmp_path / ".speed" / "context" / "tasks" / "1" / "context" / "budget.json",
        BUDGET_FIXTURE,
    )
    _write_json(
        tmp_path / ".speed" / "features" / "feature-a" / "tasks" / "1.json",
        {"id": "1", "title": "Task in A", "status": "done"},
    )
    _write_json(
        tmp_path / ".speed" / "features" / "feature-b" / "tasks" / "1.json",
        {"id": "1", "title": "Task in B", "status": "done"},
    )

    # Filter to feature-a: only its title lookup should run
    result = get_context_budget(str(tmp_path), feature="feature-a")

    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["title"] == "Task in A"


def test_task_title_from_feature(tmp_path: Path) -> None:
    """Budget references a task ID; matching feature task JSON supplies the title."""
    _write_json(
        tmp_path / ".speed" / "features" / "auth" / "tasks" / "42.json",
        {"title": "Implement OAuth flow"},
    )
    _write_json(
        tmp_path / ".speed" / "context" / "tasks" / "42" / "context" / "budget.json",
        BUDGET_FIXTURE,
    )

    result = get_context_budget(str(tmp_path))

    assert result["tasks"][0]["title"] == "Implement OAuth flow"


def test_missing_task_title(tmp_path: Path) -> None:
    """When no task JSON exists, the title defaults to 'Task {id}'."""
    _write_json(
        tmp_path / ".speed" / "context" / "tasks" / "42" / "context" / "budget.json",
        BUDGET_FIXTURE,
    )
    # No features dir at all, so no task JSON can be found
    (tmp_path / ".speed").mkdir(exist_ok=True)

    result = get_context_budget(str(tmp_path))

    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["task_id"] == "42"
    assert result["tasks"][0]["title"] == "Task 42"


def test_missing_budget_file(tmp_path: Path) -> None:
    """Task context directory exists but contains no budget.json; skipped gracefully."""
    (tmp_path / ".speed" / "features").mkdir(parents=True)
    # Create the task context dir with a subdirectory but no budget.json
    (tmp_path / ".speed" / "context" / "tasks" / "7" / "context").mkdir(parents=True)
    (tmp_path / ".speed" / "context" / "tasks" / "7" / "context" / "other.json").write_text("{}")

    result = get_context_budget(str(tmp_path))

    assert result["tasks"] == []
    assert result["summary"]["task_count"] == 0


def test_multiple_tasks(tmp_path: Path) -> None:
    """Multiple task budgets aggregate into the summary correctly."""
    (tmp_path / ".speed" / "features").mkdir(parents=True)

    _write_json(
        tmp_path / ".speed" / "context" / "tasks" / "1" / "context" / "budget.json",
        {**BUDGET_FIXTURE, "total_budget": 100000, "total_used": 80000, "under_budget": True},
    )
    _write_json(
        tmp_path / ".speed" / "context" / "tasks" / "2" / "context" / "budget.json",
        {**BUDGET_FIXTURE, "total_budget": 50000, "total_used": 55000, "under_budget": False},
    )
    _write_json(
        tmp_path / ".speed" / "context" / "tasks" / "3" / "context" / "budget.json",
        {**BUDGET_FIXTURE, "total_budget": 75000, "total_used": 30000, "under_budget": True},
    )

    result = get_context_budget(str(tmp_path))

    assert len(result["tasks"]) == 3
    summary = result["summary"]
    assert summary["task_count"] == 3
    assert summary["total_budget"] == 225000
    assert summary["total_used"] == 165000
    assert summary["utilization_pct"] == round(165000 / 225000 * 100, 1)
    assert summary["under_budget_count"] == 2
    assert summary["over_budget_count"] == 1
    assert summary["total_cuts"] == 0


def test_cuts_made(tmp_path: Path) -> None:
    """Budget with cuts populates cuts_made, cuts_count, and tokens_saved."""
    (tmp_path / ".speed" / "features").mkdir(parents=True)

    cuts = [
        {"source": "code_context", "tokens_saved": 5000, "reason": "low relevance"},
        {"source": "spec_context", "tokens_saved": 3000, "reason": "duplicate"},
    ]
    budget_with_cuts = {
        **BUDGET_FIXTURE,
        "cuts_made": cuts,
        "cuts_count": 2,
        "tokens_saved": 8000,
    }
    _write_json(
        tmp_path / ".speed" / "context" / "tasks" / "1" / "context" / "budget.json",
        budget_with_cuts,
    )

    result = get_context_budget(str(tmp_path))

    task = result["tasks"][0]
    assert task["cuts_count"] == 2
    assert task["tokens_saved"] == 8000
    assert len(task["cuts_made"]) == 2
    assert task["cuts_made"][0]["source"] == "code_context"
    assert result["summary"]["total_cuts"] == 2


def test_mp_mode_paths(tmp_path: Path) -> None:
    """In multiplayer mode, task titles resolve via .speed/shared/features/."""
    # Create .speed/shared/ to trigger MP mode detection
    (tmp_path / ".speed" / "shared").mkdir(parents=True)

    # Task JSON under the shared path (where feature_shared() points in MP mode)
    _write_json(
        tmp_path / ".speed" / "shared" / "features" / "my-feat" / "tasks" / "1.json",
        TASK_FIXTURE,
    )
    # Budget file (context path is the same in both modes)
    _write_json(
        tmp_path / ".speed" / "context" / "tasks" / "1" / "context" / "budget.json",
        BUDGET_FIXTURE,
    )

    result = get_context_budget(str(tmp_path))

    assert len(result["tasks"]) == 1
    task = result["tasks"][0]
    assert task["task_id"] == "1"
    assert task["title"] == "Implement resolver"
    assert task["total_budget"] == 50000
