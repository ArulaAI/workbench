"""Tests for backend.resolvers.process_status — PID detection, state parsing, liveness."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.resolvers.process_status import get_process_status, _check_pid, _read_pid_file
import backend.paths as paths_mod


# ── Helpers ──────────────────────────────────────────────────────


def _write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_paths_cache():
    """Reset the SpeedPaths module-level cache before each test.

    get_paths() caches by project_root string. Since every test uses a
    different tmp_path, stale entries would cause tests to bleed into each
    other or hit paths that no longer exist.
    """
    paths_mod._cache.clear()
    yield
    paths_mod._cache.clear()


# ── Tests ────────────────────────────────────────────────────────


def test_empty_project(tmp_path: Path):
    """No .speed/ directory at all.  Should return an empty features list
    and active_feature=None without raising."""
    result = get_process_status(str(tmp_path))

    assert result["active_feature"] is None
    assert result["features"] == []


def test_no_features(tmp_path: Path):
    """.speed/features/ exists but contains no subdirectories."""
    (tmp_path / ".speed" / "features").mkdir(parents=True)

    result = get_process_status(str(tmp_path))

    assert result["features"] == []
    assert result["active_feature"] is None


def test_idle_feature(tmp_path: Path):
    """state.json with status 'idle' should produce orchestrator_running=False."""
    feat_dir = tmp_path / ".speed" / "features" / "login-flow"
    _write_json(feat_dir / "state.json", {"status": "idle"})

    result = get_process_status(str(tmp_path))

    assert len(result["features"]) == 1
    feat = result["features"][0]
    assert feat["name"] == "login-flow"
    assert feat["orchestrator_running"] is False
    assert feat["started_at"] is None


def test_running_feature(tmp_path: Path):
    """state.json with status 'running' and a started_at timestamp."""
    feat_dir = tmp_path / ".speed" / "features" / "auth-refactor"
    _write_json(feat_dir / "state.json", {
        "status": "running",
        "started_at": "2026-03-26T10:00:00Z",
    })

    result = get_process_status(str(tmp_path))

    feat = result["features"][0]
    assert feat["orchestrator_running"] is True
    assert feat["started_at"] == "2026-03-26T10:00:00Z"


def test_live_pid(tmp_path: Path):
    """A PID file referencing the current process (os.getpid()) should show
    alive=True and appear in agents, not stale_processes."""
    feat_dir = tmp_path / ".speed" / "features" / "live-check"
    feat_dir.mkdir(parents=True)
    _write_file(feat_dir / "running" / "1.pid", str(os.getpid()))

    result = get_process_status(str(tmp_path))

    feat = result["features"][0]
    assert len(feat["agents"]) == 1
    agent = feat["agents"][0]
    assert agent["task_id"] == "1"
    assert agent["pid"] == os.getpid()
    assert agent["alive"] is True
    assert agent["agent_type"] == "developer"
    assert feat["stale_processes"] == []


def test_dead_pid(tmp_path: Path):
    """A PID file with a bogus high PID (99999999) should resolve to
    alive=False and land in stale_processes."""
    feat_dir = tmp_path / ".speed" / "features" / "stale-check"
    feat_dir.mkdir(parents=True)
    _write_file(feat_dir / "running" / "42.pid", "99999999")

    result = get_process_status(str(tmp_path))

    feat = result["features"][0]
    assert feat["agents"] == []
    assert len(feat["stale_processes"]) == 1

    stale = feat["stale_processes"][0]
    assert stale["task_id"] == "42"
    assert stale["pid"] == 99999999
    assert stale["agent_type"] == "developer"
    assert "pid_file" in stale


def test_support_agent(tmp_path: Path):
    """A support agent with a .pid and companion .task file in support/."""
    feat_dir = tmp_path / ".speed" / "features" / "review-flow"
    feat_dir.mkdir(parents=True)
    _write_file(feat_dir / "support" / "Reviewer-1.pid", str(os.getpid()))
    _write_file(feat_dir / "support" / "Reviewer-1.task", "task-abc-123")

    result = get_process_status(str(tmp_path))

    feat = result["features"][0]
    assert len(feat["support_agents"]) == 1

    sa = feat["support_agents"][0]
    assert sa["agent_type"] == "Reviewer"
    assert sa["task_id"] == "task-abc-123"
    assert sa["pid"] == os.getpid()
    assert sa["alive"] is True


def test_active_feature(tmp_path: Path):
    """Writing .speed/active_feature should populate the active_feature field."""
    feat_dir = tmp_path / ".speed" / "features" / "onboarding"
    feat_dir.mkdir(parents=True)
    _write_file(tmp_path / ".speed" / "active_feature", "onboarding")

    result = get_process_status(str(tmp_path))

    assert result["active_feature"] == "onboarding"


def test_multiple_features(tmp_path: Path):
    """Two features with different states should both appear in the output."""
    base = tmp_path / ".speed" / "features"

    _write_json(base / "alpha" / "state.json", {"status": "running", "started_at": "2026-03-26T08:00:00Z"})
    _write_json(base / "beta" / "state.json", {"status": "idle"})

    result = get_process_status(str(tmp_path))

    names = {f["name"] for f in result["features"]}
    assert names == {"alpha", "beta"}

    by_name = {f["name"]: f for f in result["features"]}
    assert by_name["alpha"]["orchestrator_running"] is True
    assert by_name["beta"]["orchestrator_running"] is False


def test_malformed_pid_file(tmp_path: Path):
    """A PID file containing non-numeric text should be skipped without error."""
    feat_dir = tmp_path / ".speed" / "features" / "bad-pid"
    feat_dir.mkdir(parents=True)
    _write_file(feat_dir / "running" / "7.pid", "not-a-number")

    result = get_process_status(str(tmp_path))

    feat = result["features"][0]
    assert feat["agents"] == []
    assert feat["stale_processes"] == []


def test_missing_state_json(tmp_path: Path):
    """Feature directory exists but has no state.json.  Should default to
    orchestrator_running=False (idle)."""
    feat_dir = tmp_path / ".speed" / "features" / "no-state"
    feat_dir.mkdir(parents=True)

    result = get_process_status(str(tmp_path))

    feat = result["features"][0]
    assert feat["name"] == "no-state"
    assert feat["orchestrator_running"] is False
    assert feat["started_at"] is None


# ── Unit tests for helpers ───────────────────────────────────────


class TestCheckPid:
    """Direct tests for _check_pid without filesystem setup."""

    def test_current_process_is_alive(self):
        assert _check_pid(os.getpid()) is True

    def test_impossible_pid_is_dead(self):
        assert _check_pid(99999999) is False


class TestReadPidFile:
    """Direct tests for _read_pid_file."""

    def test_valid_pid(self, tmp_path: Path):
        p = tmp_path / "test.pid"
        p.write_text("12345\n", encoding="utf-8")
        assert _read_pid_file(p) == 12345

    def test_non_numeric_returns_none(self, tmp_path: Path):
        p = tmp_path / "bad.pid"
        p.write_text("oops", encoding="utf-8")
        assert _read_pid_file(p) is None

    def test_missing_file_returns_none(self, tmp_path: Path):
        assert _read_pid_file(tmp_path / "gone.pid") is None
