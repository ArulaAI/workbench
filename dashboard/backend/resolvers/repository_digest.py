"""Repository Digest resolver — loads the stored artifact, computes
freshness, and coordinates refresh builds.

Read path (repositoryDigest / repositoryDigestStatus queries) only reads
files and computes a git-HEAD comparison — it never rebuilds, walks the
repository, or invokes an agent provider. Only the refreshRepositoryDigest
mutation triggers a real build, in a background thread.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - POSIX-only; no cross-process lock elsewhere either
    fcntl = None  # type: ignore

log = logging.getLogger("speed.dashboard.repository_digest")

# In-memory registry of running builds: {project_root: started_at_iso}.
# Same pattern as audit_runner.py's _running_audits — thread-safe because
# the build runs in a thread pool executor while status queries run on the
# main async event loop. This alone only protects one dashboard process;
# _acquire_repo_lock() below adds the cross-process guarantee the RFC's
# "repository-scoped digest build lock" actually implies.
_running_builds: dict[str, str] = {}
_running_lock = threading.Lock()


def _project_key(project_root: str) -> str:
    return str(Path(project_root).resolve())


# ── Reads (no rebuild) ────────────────────────────────────────────


def get_repository_digest(project_root: str) -> Optional[dict[str, Any]]:
    """Load the stored digest and attach freshness. Returns None only when
    no valid stored artifact exists.
    """
    from lib.context.repository_digest import attach_effective_state, load_repository_digest

    digest = load_repository_digest(project_root)
    if digest is None:
        return None

    config = _load_config(project_root)
    return attach_effective_state(project_root, digest, config=config)


def get_repository_digest_status(project_root: str) -> dict[str, Any]:
    """Lightweight status for polling during a refresh.

    Distinguishes "no artifact ever written" (MISSING) from "an artifact
    exists but is malformed or an unsupported schema_version" (ERROR, with
    lastError explaining why) even when no build has ever run or failed —
    per Validation Rules > schema_version: "unsupported versions return no
    digest plus an invalid status reason," and Dashboard Design's distinct
    Missing vs. Malformed artifact page states.
    """
    from lib.context.repository_digest import load_repository_digest_with_status
    from lib.context.repository_digest_freshness import compute_digest_freshness

    key = _project_key(project_root)
    with _running_lock:
        started_at = _running_builds.get(key)

    persisted = _read_status_file(project_root)
    load_status, digest, malformed_reason = load_repository_digest_with_status(project_root)
    has_readable = load_status == "ok"

    freshness = None
    if has_readable:
        config = _load_config(project_root)
        freshness = compute_digest_freshness(project_root, digest, config=config)

    if started_at is not None:
        state = "GENERATING"
    elif load_status == "malformed":
        state = "ERROR"
    elif not has_readable:
        state = "MISSING"
    elif freshness["state"] == "STALE":
        state = "STALE"
    else:
        state = "CURRENT"

    last_error = (persisted or {}).get("last_error")
    if load_status == "malformed" and not last_error:
        last_error = _sanitize_error(malformed_reason or "stored repository-digest.json is malformed")

    return {
        "state": state,
        "started_at": started_at or (persisted or {}).get("started_at"),
        "completed_at": (persisted or {}).get("completed_at"),
        "last_error": last_error,
        "has_readable_digest": has_readable,
        "indexed_git_head": freshness["indexed_git_head"] if freshness else None,
        "current_git_head": freshness["current_git_head"] if freshness else None,
        "stale_reasons": freshness["stale_reasons"] if freshness else [],
    }


# ── Refresh (the only path that builds anything) ──────────────────


def refresh_repository_digest(
    project_root: str,
    *,
    rebuild_discovery: bool = False,
    narrative: bool = False,
    sub_manager: Any = None,
) -> dict[str, Any]:
    """Start a build in a background thread if one isn't already running
    for this project. Returns immediately — callers should poll
    repositoryDigestStatus or subscribe to repositoryDigestUpdated.
    """
    key = _project_key(project_root)

    with _running_lock:
        if key in _running_builds:
            return {
                "accepted": False,
                "state": "GENERATING",
                "message": "A digest build is already running for this project.",
                "has_readable_digest": get_repository_digest(project_root) is not None,
            }
        # Cross-process guard (Edge Cases: "Two dashboard processes request
        # refresh against the same repository") — the in-memory dict above
        # only protects this process. Held for the build's whole duration,
        # released in _run_build's finally.
        lock_handle = _acquire_repo_lock(project_root)
        if lock_handle is None:
            return {
                "accepted": False,
                "state": "GENERATING",
                "message": "A digest build is already running for this project (held by another process).",
                "has_readable_digest": get_repository_digest(project_root) is not None,
            }
        started_at = datetime.now(timezone.utc).isoformat()
        _running_builds[key] = started_at

    _write_status_file(project_root, {"state": "GENERATING", "started_at": started_at,
                                       "completed_at": None, "last_error": None})
    _publish(project_root, sub_manager)

    thread = threading.Thread(
        target=_run_build,
        args=(project_root, rebuild_discovery, narrative, started_at, sub_manager, lock_handle),
        daemon=True,
    )
    thread.start()

    return {
        "accepted": True,
        "state": "GENERATING",
        "message": "Digest build started.",
        "has_readable_digest": get_repository_digest(project_root) is not None,
    }


def _run_build(
    project_root: str, rebuild_discovery: bool, narrative: bool, started_at: str,
    sub_manager: Any, lock_handle: Any = None,
) -> None:
    from lib.context.repository_digest import DigestInputError, build_repository_digest

    key = _project_key(project_root)
    try:
        if rebuild_discovery:
            _rebuild_layer1(project_root)

        config = _load_config(project_root)
        build_repository_digest(project_root, config=config, narrative=narrative)

        _write_status_file(project_root, {
            "state": "COMPLETE", "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(), "last_error": None,
        })
    except DigestInputError as e:
        _write_status_file(project_root, {
            "state": "ERROR", "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "last_error": _sanitize_error(str(e)),
        })
        log.warning("Repository digest build failed for %s: %s", project_root, e)
    except Exception as e:  # noqa: BLE001 — must never crash the background thread
        _write_status_file(project_root, {
            "state": "ERROR", "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "last_error": _sanitize_error(str(e)),
        })
        log.exception("Unexpected error building repository digest for %s", project_root)
    finally:
        with _running_lock:
            _running_builds.pop(key, None)
        _release_repo_lock(lock_handle)
        _publish(project_root, sub_manager)


def _rebuild_layer1(project_root: str) -> None:
    """Invoke the existing Layer 1 builder before digest generation.
    Deliberately not implemented as a separate scanner — this calls the
    same build_layer1() the CLI uses via context_bridge.sh, imported
    directly to avoid a subprocess round-trip.
    """
    try:
        from lib.context.layer1 import build_layer1
    except ImportError:
        log.warning("build_layer1 not importable; skipping rebuildDiscovery for %s", project_root)
        return
    build_layer1(project_root, fresh=False)


def _acquire_repo_lock(project_root: str) -> Any:
    """Best-effort cross-process lock on top of the in-memory _running_builds
    check, using flock on a dedicated lock file. Returns an open file
    handle to hold for the build's duration, or None if another process
    already holds it (or fcntl isn't available, e.g. non-POSIX — in that
    case the in-memory check remains the only guard, same as before this
    was added).
    """
    if fcntl is None:
        return "no-op"
    from ..paths import get_paths
    lock_path = get_paths(project_root).context_dir / ".repository-digest.lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        try:
            fh.close()
        except Exception:
            pass
        return None


def _release_repo_lock(lock_handle: Any) -> None:
    if lock_handle is None or lock_handle == "no-op" or fcntl is None:
        return
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        try:
            lock_handle.close()
        except Exception:
            pass


_STACK_TRACE_LINE_RE = re.compile(r'^\s*File "[^"]*", line \d+.*$', re.MULTILINE)
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-/+=]{32,}\b")


def _sanitize_error(message: str) -> str:
    """Strip absolute home paths, stack-trace frames, and long opaque
    tokens (which could be a secret/credential value), then cap length.
    Refresh errors must never contain provider prompts, secret values, or
    stack traces (Security & Controls > Auditability; API Surface >
    repositoryDigestStatus).
    """
    home = os.path.expanduser("~")
    if home and home != "/":
        message = message.replace(home, "~")
    if "Traceback (most recent call last)" in message:
        message = message.split("Traceback (most recent call last)")[0].strip()
    message = _STACK_TRACE_LINE_RE.sub("", message)
    message = _LONG_TOKEN_RE.sub("[redacted]", message)
    return message.strip()[:500]


def _publish(project_root: str, sub_manager: Any) -> None:
    if sub_manager is None:
        return
    try:
        from ..subscriptions import DashboardEvent, EventType
        status = get_repository_digest_status(project_root)
        sub_manager.publish_sync(DashboardEvent(
            type=EventType.REPOSITORY_DIGEST_STATUS_CHANGED,
            payload=status,
        ))
    except Exception:  # noqa: BLE001 — publishing must never break a build
        log.debug("Could not publish repository digest status event", exc_info=True)


# ── Status file (persisted outside repository-digest.json) ────────


def _status_path(project_root: str) -> Path:
    from ..paths import get_paths
    return get_paths(project_root).repository_digest_status_path


def _read_status_file(project_root: str) -> Optional[dict[str, Any]]:
    path = _status_path(project_root)
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _write_status_file(project_root: str, data: dict[str, Any]) -> None:
    path = _status_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        log.warning("Could not write repository digest status file for %s", project_root)


def _load_config(project_root: str) -> dict[str, Any]:
    from lib.context.utils import load_speed_toml
    return load_speed_toml(project_root)
