"""Read audit results from disk and launch `speed audit` as a subprocess.

SPEED writes audit output to .speed/features/{feature}/logs/.
The dashboard reads those files — it never parses stdout or normalizes
the schema. SPEED is the authority on audit format.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("speed.dashboard.audit_runner")

# Markdown code fence pattern that SPEED's agent output wraps JSON in
_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL
)

# In-memory registry of currently running audits: {spec_path: started_at_iso}
# Thread-safe because run_speed_audit executes in a thread pool executor
# while get_audit_status is called from the main async event loop.
_running_audits: dict[str, str] = {}
_running_lock = threading.Lock()


def get_audit_status(spec_path: str) -> Optional[dict]:
    """Return running state for a spec, or None if no audit is running."""
    with _running_lock:
        started = _running_audits.get(spec_path)
    if started is None:
        return None
    return {"running": True, "started_at": started}


# ── Read from disk ───────────────────────────────────────────────


def get_latest_audit(
    project_root: Path, spec_path: str,
) -> Optional[dict]:
    """Find the most recent audit result for a spec, from any feature.

    Scans .speed/features/*/logs/ for audit-*.json and plan-audit-*.json,
    matches by spec_file field, returns the newest with staleness info.

    Returns SPEED's native schema plus `_stale` and `_ran_at` metadata,
    or None if no audit exists for this spec.
    """
    audits = get_recent_audits(project_root, spec_path, limit=1)
    return audits[0] if audits else None


def get_recent_audits(
    project_root: Path, spec_path: str, limit: int = 3,
) -> list[dict]:
    """Return the last N audit results for a spec, newest first.

    Each result is SPEED's native JSON with added metadata:
      _stale: bool  — spec was modified after this audit ran
      _ran_at: str  — ISO timestamp of when the audit file was written
      _feature: str — which feature directory contained the audit
    """
    from ..paths import get_paths
    paths = get_paths(project_root)

    # Collect audit JSON files matching SPEED's naming convention:
    #   audit-{epoch}.json          (from speed audit)
    #   plan-audit-{type}-{epoch}.json  (from speed plan)
    _AUDIT_FILE_RE = re.compile(r"^(?:plan-)?audit-.*-?\d+\.json$")

    candidates: list[tuple[float, Path, str]] = []  # (mtime, path, feature)
    for feature_name in paths.feature_names():
        # Logs live in local zone (or same dir in single-player)
        logs_dir = paths.feature_local(feature_name) / "logs"
        if not logs_dir.is_dir():
            continue
        for f in logs_dir.iterdir():
            if not _AUDIT_FILE_RE.match(f.name):
                continue
            candidates.append((f.stat().st_mtime, f, feature_name))

    # Sort newest first
    candidates.sort(key=lambda x: x[0], reverse=True)

    # Read and filter by spec_path match
    spec_mtime = _spec_mtime(Path(project_root), spec_path)
    results: list[dict] = []

    for mtime, audit_path, feature_name in candidates:
        data = _read_audit_file(audit_path)
        if data is None:
            continue

        # Match: the audit's spec_file should match the requested spec path
        audit_spec = data.get("spec_file", "")
        if not _paths_match(audit_spec, spec_path):
            continue

        # Add dashboard metadata
        data["_stale"] = spec_mtime is not None and spec_mtime > mtime
        data["_ran_at"] = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        data["_feature"] = feature_name

        results.append(data)
        if len(results) >= limit:
            break

    return results


def _read_audit_file(path: Path) -> Optional[dict]:
    """Read an audit JSON file, stripping markdown code fences if present."""
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    # Strip markdown code fences (SPEED's agent output wraps JSON in ```json ... ```)
    match = _CODE_FENCE_RE.search(raw)
    if match:
        raw = match.group(1).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Failed to parse audit JSON: %s", path)
        return None


def _paths_match(audit_spec: str, requested: str) -> bool:
    """Check if an audit's spec_file matches the requested spec path.

    Handles both relative and absolute paths, with or without leading ./ etc.
    """
    a = audit_spec.strip().lstrip("./")
    b = requested.strip().lstrip("./")
    return a == b or a.endswith(b) or b.endswith(a)


def _spec_mtime(project_root: Path, spec_path: str) -> Optional[float]:
    """Get the modification time of a spec file, or None if missing."""
    full = project_root / spec_path
    try:
        return full.stat().st_mtime if full.exists() else None
    except OSError:
        return None


# ── Launch audit subprocess ──────────────────────────────────────


def run_speed_audit(
    project_root: Path, spec_path: str, timeout: int | None = None,
) -> dict:
    """Launch `speed audit <spec_path>` and return success/error status.

    Does NOT parse the audit output — SPEED writes it to disk and the
    file watcher picks it up. This just reports whether the subprocess
    succeeded.

    Registers the spec in _running_audits before launch so the frontend
    can detect a running audit even after page refresh.
    """
    full_path = project_root / spec_path
    if not full_path.exists():
        return {"success": False, "error": f"File not found: {spec_path}"}

    speed_bin = _find_speed_bin(project_root)
    if not speed_bin:
        return {
            "success": False,
            "error": "speed CLI not found. Set SPEED_BIN env var or place speed script in project root.",
        }

    if timeout is None:
        timeout = int(os.environ.get("SPEED_TIMEOUT", "600"))

    # Register running state before launching
    started_at = datetime.now(timezone.utc).isoformat()
    with _running_lock:
        _running_audits[spec_path] = started_at

    try:
        result = subprocess.run(
            [str(speed_bin), "audit", str(full_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(project_root),
            env=_audit_env(project_root),
        )
    except FileNotFoundError:
        return {"success": False, "error": f"speed CLI not executable: {speed_bin}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Audit timed out after {timeout}s"}
    finally:
        with _running_lock:
            _running_audits.pop(spec_path, None)

    if result.returncode == 0:
        return {"success": True, "error": None}

    return {
        "success": False,
        "error": result.stderr[:500] if result.stderr else f"Audit failed with exit code {result.returncode}",
    }


# ── Git ──────────────────────────────────────────────────────────


def get_git_branch(project_root: Path) -> Optional[str]:
    """Return the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(project_root),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


# ── Internal helpers ─────────────────────────────────────────────


def _find_speed_bin(project_root: Path) -> Optional[str]:
    """Find the speed CLI."""
    speed_dir = os.environ.get("SPEED_DIR") or os.environ.get("PYTHONPATH", "").split(":")[0]
    if speed_dir:
        candidate = Path(speed_dir) / "speed"
        if candidate.exists() and os.access(str(candidate), os.X_OK):
            return str(candidate)

    candidate = project_root / "speed"
    if candidate.exists() and os.access(str(candidate), os.X_OK):
        return str(candidate)

    env_bin = os.environ.get("SPEED_BIN")
    if env_bin and Path(env_bin).exists():
        return env_bin

    return None


def _audit_env(project_root: Path) -> dict:
    """Build environment for the audit subprocess."""
    env = os.environ.copy()
    env["PROJECT_ROOT"] = str(project_root)
    return env
