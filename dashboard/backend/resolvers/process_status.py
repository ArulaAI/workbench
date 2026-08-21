"""Process detection — reads PID files and checks liveness.

Scans .speed/features/*/running/ and support/ for PID files,
reads state.json for orchestrator status, and verifies each PID
is still alive via os.kill(pid, 0).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("speed.dashboard.process_status")


def get_process_status(project_root: str) -> dict[str, Any]:
    """Build the full process status view across all features."""
    from ..paths import get_paths
    paths = get_paths(project_root)

    active_feature = _read_active_feature(paths.active_feature_path)

    features: list[dict[str, Any]] = []
    for name in paths.feature_names():
        # Runtime state (state.json, PIDs) lives in local zone
        local_dir = paths.feature_local(name)
        feat = _read_feature_processes(local_dir, name)
        if feat:
            features.append(feat)

    return {
        "active_feature": active_feature,
        "features": features,
    }


def _read_feature_processes(feature_dir: Path, name: str) -> dict[str, Any]:
    """Read process state for a single feature from its local directory."""

    # Orchestrator state from state.json
    state = _read_json(feature_dir / "state.json") or {}
    orchestrator_running = state.get("status") == "running"
    started_at = state.get("started_at")

    # Developer agent PIDs from running/
    agents: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    running_dir = feature_dir / "running"
    if running_dir.is_dir():
        for pid_file in running_dir.glob("*.pid"):
            task_id = pid_file.stem
            pid = _read_pid_file(pid_file)
            if pid is None:
                continue
            alive = _check_pid(pid)
            entry = {"task_id": task_id, "pid": pid, "alive": alive, "agent_type": "developer"}
            if alive:
                agents.append(entry)
            else:
                stale.append({
                    "task_id": task_id,
                    "pid": pid,
                    "pid_file": str(pid_file.relative_to(feature_dir.parent.parent)),
                    "agent_type": "developer",
                })

    # Support agent PIDs from support/
    support_agents: list[dict[str, Any]] = []
    support_dir = feature_dir / "support"
    if support_dir.is_dir():
        for pid_file in support_dir.glob("*.pid"):
            pid = _read_pid_file(pid_file)
            if pid is None:
                continue

            # Parse agent type and task ID from filename: {agent_type}-{task_id}.pid
            stem = pid_file.stem
            agent_type = stem
            task_id = ""
            # Try to read companion .task file
            task_file = pid_file.with_suffix(".task")
            if task_file.exists():
                try:
                    task_id = task_file.read_text(encoding="utf-8").strip()
                except OSError:
                    pass
            # Parse agent type from stem (e.g., "Reviewer-1" → "Reviewer")
            parts = stem.rsplit("-", 1)
            if len(parts) == 2:
                agent_type = parts[0]
                if not task_id:
                    task_id = parts[1]

            alive = _check_pid(pid)
            entry = {"task_id": task_id, "pid": pid, "alive": alive, "agent_type": agent_type}
            if alive:
                support_agents.append(entry)
            else:
                stale.append({
                    "task_id": task_id,
                    "pid": pid,
                    "pid_file": str(pid_file.relative_to(feature_dir.parent.parent)),
                    "agent_type": agent_type,
                })

    return {
        "name": name,
        "orchestrator_running": orchestrator_running,
        "started_at": started_at,
        "agents": agents,
        "support_agents": support_agents,
        "stale_processes": stale,
    }


# ── Helpers ──────────────────────────────────────────────────────


def _check_pid(pid: int) -> bool:
    """Check if a process is alive via signal 0 (no-op signal)."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but owned by different user — still alive
        return True
    except OSError:
        return False


def _read_pid_file(path: Path) -> Optional[int]:
    """Read a PID file and return the integer PID, or None on error."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(text)
    except (OSError, ValueError):
        return None


def _read_active_feature(path: Path) -> Optional[str]:
    """Read active_feature file, or None if missing."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text if text else None
    except OSError:
        return None


def _read_json(path: Path) -> Optional[dict]:
    """Read a JSON file, returning None on any error."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return None
