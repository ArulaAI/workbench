"""Ingestion pipeline: scan .speed/ JSONL files, parse events, populate SQLite.

Four operations:
  1. register_project() — upsert the project row
  2. backfill()         — scan all existing JSONL files, skip already-ingested
  3. ingest_file()      — process a single new/modified JSONL file
  4. start_watcher()    — watchdog observer for live file changes
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

from .db import transaction
from .subscriptions import SubscriptionManager, DashboardEvent, EventType

if TYPE_CHECKING:
    pass

log = logging.getLogger("speed.dashboard.ingest")

# Filename pattern: {AgentType}-{epoch}.jsonl
# Agent type may contain spaces and parens, e.g. "Architect (Phase 1)-1772032468.jsonl"
FILENAME_RE = re.compile(r"^(.+)-(\d+)\.jsonl$")


def register_project(conn: sqlite3.Connection, project_root: str) -> None:
    """Insert or update the project row from the target project's metadata."""
    root = Path(project_root).resolve()
    name = root.name

    git_remote = None
    git_head = None
    try:
        git_remote = subprocess.check_output(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    try:
        git_head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    with transaction(conn):
        existing = conn.execute(
            "SELECT id FROM project WHERE id = 'default'"
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE project
                   SET git_head = ?, updated_at = strftime('%Y-%m-%dT%%H:%%M:%%SZ','now')
                   WHERE id = 'default'""",
                (git_head,),
            )
        else:
            conn.execute(
                """INSERT INTO project (id, name, root_path, git_remote, git_head)
                   VALUES ('default', ?, ?, ?, ?)""",
                (name, str(root), git_remote, git_head),
            )


def _parse_filename(filename: str) -> tuple[str, datetime] | None:
    """Extract agent_type and timestamp from JSONL filename."""
    m = FILENAME_RE.match(filename)
    if not m:
        return None
    agent_type = m.group(1)
    epoch = int(m.group(2))
    ts = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return agent_type, ts


def _extract_feature_from_path(path: Path, features_base: Path) -> str | None:
    """Extract feature name from {features_base}/{feature}/logs/{file}."""
    try:
        rel = path.relative_to(features_base)
        parts = rel.parts
        if len(parts) >= 3 and parts[1] == "logs":
            return parts[0]
    except ValueError:
        pass
    # Also try matching {features_base}/{feature}/* for non-logs files
    try:
        rel = path.relative_to(features_base)
        if rel.parts:
            return rel.parts[0]
    except ValueError:
        pass
    return None


def ingest_file(
    conn: sqlite3.Connection,
    filepath: Path,
    feature: str,
    project_root: Path,
) -> dict | None:
    """Parse a single JSONL file and insert agent_runs + model_usage + agent_turns.

    Returns the result event dict if found, else None.
    """
    parsed = _parse_filename(filepath.name)
    if not parsed:
        log.warning("Skipping file with unparseable name: %s", filepath.name)
        return None

    agent_type, file_ts = parsed
    rel_path = str(filepath.relative_to(project_root))

    # Ensure feature row exists
    conn.execute(
        "INSERT OR IGNORE INTO features (name) VALUES (?)", (feature,)
    )

    session_id = ""
    result_event = None
    turn_index = 0

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")

            if etype == "system" and event.get("subtype") == "init":
                session_id = event.get("session_id", "")

            elif etype == "assistant":
                msg = event.get("message", {})
                usage = msg.get("usage", {})
                model = msg.get("model", "")
                content = msg.get("content", [])
                has_tool = any(
                    c.get("type") == "tool_use" for c in content if isinstance(c, dict)
                )
                has_thinking = any(
                    c.get("type") == "thinking" for c in content if isinstance(c, dict)
                )

                cache_creation = usage.get("cache_creation", {})
                cache_creation_tokens = (
                    usage.get("cache_creation_input_tokens", 0)
                    or cache_creation.get("ephemeral_1h_input_tokens", 0)
                    + cache_creation.get("ephemeral_5m_input_tokens", 0)
                )

                conn.execute(
                    """INSERT INTO agent_turns
                       (agent_run_id, feature, session_id, source_file, turn_index,
                        model, input_tokens, output_tokens, cache_read_tokens,
                        cache_creation_tokens, has_tool_use, has_thinking, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        None,  # linked after result event
                        feature,
                        session_id or event.get("session_id", ""),
                        rel_path,
                        turn_index,
                        model,
                        usage.get("input_tokens", 0),
                        usage.get("output_tokens", 0),
                        usage.get("cache_read_input_tokens", 0),
                        cache_creation_tokens,
                        int(has_tool),
                        int(has_thinking),
                        file_ts.isoformat(),
                    ),
                )
                turn_index += 1

            elif etype == "result":
                result_event = event

    if result_event:
        run_id = result_event.get("uuid", "")
        usage = result_event.get("usage", {})
        model_usage_map = result_event.get("modelUsage", {})

        # Aggregate token totals from modelUsage
        total_input = sum(m.get("inputTokens", 0) for m in model_usage_map.values())
        total_output = sum(m.get("outputTokens", 0) for m in model_usage_map.values())
        total_cache_creation = sum(
            m.get("cacheCreationInputTokens", 0) for m in model_usage_map.values()
        )
        total_cache_read = sum(
            m.get("cacheReadInputTokens", 0) for m in model_usage_map.values()
        )

        with transaction(conn):
            conn.execute(
                """INSERT OR REPLACE INTO agent_runs
                   (id, feature, session_id, agent_type, task_id, subtype, is_error,
                    duration_ms, duration_api_ms, num_turns, total_cost_usd,
                    input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
                    source_file, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    feature,
                    result_event.get("session_id", session_id),
                    agent_type,
                    None,  # task_id extracted from context if available
                    result_event.get("subtype"),
                    int(result_event.get("is_error", False)),
                    result_event.get("duration_ms"),
                    result_event.get("duration_api_ms"),
                    result_event.get("num_turns"),
                    result_event.get("total_cost_usd"),
                    total_input,
                    total_output,
                    total_cache_creation,
                    total_cache_read,
                    rel_path,
                    file_ts.isoformat(),
                ),
            )

            # Insert per-model usage breakdown
            for model_name, mdata in model_usage_map.items():
                conn.execute(
                    """INSERT INTO model_usage
                       (agent_run_id, model, input_tokens, output_tokens,
                        cache_read_tokens, cache_creation_tokens, cost_usd,
                        context_window, max_output_tokens)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        model_name,
                        mdata.get("inputTokens", 0),
                        mdata.get("outputTokens", 0),
                        mdata.get("cacheReadInputTokens", 0),
                        mdata.get("cacheCreationInputTokens", 0),
                        mdata.get("costUSD", 0.0),
                        mdata.get("contextWindow"),
                        mdata.get("maxOutputTokens"),
                    ),
                )

            # Link turns to this run
            conn.execute(
                """UPDATE agent_turns SET agent_run_id = ?
                   WHERE source_file = ? AND agent_run_id IS NULL""",
                (run_id, rel_path),
            )

    # Record file as ingested
    stat = filepath.stat()
    conn.execute(
        """INSERT OR REPLACE INTO ingested_files (path, mtime, size)
           VALUES (?, ?, ?)""",
        (rel_path, stat.st_mtime, stat.st_size),
    )
    conn.commit()

    return result_event


def _scan_features(conn: sqlite3.Connection, project_root: Path) -> None:
    """Populate the features table from feature state files."""
    from .paths import get_paths
    paths = get_paths(project_root)

    for name in paths.feature_names():
        state_file = paths.feature_local(name) / "state.json"
        status = "idle"
        started_at = None
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                status = data.get("status", "idle")
                started_at = data.get("started_at")
            except (json.JSONDecodeError, OSError):
                pass

        conn.execute(
            """INSERT INTO features (name, status, started_at) VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET status = excluded.status,
               started_at = excluded.started_at""",
            (name, status, started_at),
        )
    conn.commit()


def backfill(conn: sqlite3.Connection, project_root: str) -> int:
    """Scan all feature logs and ingest new/changed JSONL files.

    Returns the number of files processed.
    """
    from .paths import get_paths
    root = Path(project_root).resolve()
    paths = get_paths(project_root)
    _scan_features(conn, root)

    count = 0
    for feature in paths.feature_names():
        logs_dir = paths.feature_local(feature) / "logs"
        if not logs_dir.is_dir():
            continue

        for jsonl in sorted(logs_dir.glob("*.jsonl")):
            rel = str(jsonl.relative_to(root))
            stat = jsonl.stat()

            # Check if already ingested with same mtime+size
            row = conn.execute(
                "SELECT mtime, size FROM ingested_files WHERE path = ?", (rel,)
            ).fetchone()
            if row and row["mtime"] == stat.st_mtime and row["size"] == stat.st_size:
                continue

            log.info("Ingesting %s", rel)
            ingest_file(conn, jsonl, feature, root)
            count += 1

    return count


class _LogFileHandler(FileSystemEventHandler):
    """Watchdog handler that triggers incremental ingestion on JSONL changes."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        project_root: Path,
        features_base: Path,
        sub_manager: SubscriptionManager,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._conn = conn
        self._root = project_root
        self._features_base = features_base
        self._sub = sub_manager
        self._loop = loop
        self._debounce: dict[str, float] = {}

    def _handle(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        path = Path(event.src_path)

        # Process status signals: state.json or PID files
        if path.name == "state.json" or path.suffix == ".pid":
            feature = _extract_feature_from_path(path, self._features_base)
            if not feature:
                try:
                    rel = path.relative_to(self._features_base)
                    feature = rel.parts[0] if rel.parts else None
                except ValueError:
                    pass
            if feature:
                event_obj = DashboardEvent(
                    type=EventType.PROCESS_STATUS_CHANGED,
                    feature=feature,
                    payload={"trigger": path.name},
                )
                asyncio.run_coroutine_threadsafe(
                    self._sub.publish(event_obj), self._loop
                )
            return

        # Audit file signals: audit-*.json or plan-audit-*.json in logs/
        if path.suffix == ".json" and "audit" in path.name:
            feature = _extract_feature_from_path(path, self._features_base)
            if feature:
                import time as _time
                now = _time.monotonic()
                key = str(path)
                if now - self._debounce.get(key, 0) >= 0.2:
                    self._debounce[key] = now
                    event_obj = DashboardEvent(
                        type=EventType.AUDIT_COMPLETED,
                        feature=feature,
                        payload={"file": path.name, "feature": feature},
                    )
                    asyncio.run_coroutine_threadsafe(
                        self._sub.publish(event_obj), self._loop
                    )
            return

        if not path.suffix == ".jsonl":
            return

        # Debounce: skip if processed within last 100ms
        import time

        now = time.monotonic()
        key = str(path)
        last = self._debounce.get(key, 0)
        if now - last < 0.1:
            return
        self._debounce[key] = now

        feature = _extract_feature_from_path(path, self._features_base)
        if not feature:
            return

        log.info("File watcher triggered: %s", path.name)
        result = ingest_file(self._conn, path, feature, self._root)

        if result:
            event_obj = DashboardEvent(
                type=EventType.AGENT_RUN_COMPLETED,
                feature=feature,
                payload={
                    "run_id": result.get("uuid", ""),
                    "cost": result.get("total_cost_usd", 0),
                },
            )
            asyncio.run_coroutine_threadsafe(
                self._sub.publish(event_obj), self._loop
            )

    def on_created(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        self._handle(event)

    def on_modified(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        self._handle(event)


def start_watcher(
    conn: sqlite3.Connection,
    project_root: str,
    sub_manager: SubscriptionManager,
    loop: asyncio.AbstractEventLoop,
) -> Observer:
    """Start watchdog observer on feature logs directories."""
    from .paths import get_paths
    root = Path(project_root).resolve()
    paths = get_paths(project_root)
    # Logs live in the local zone
    features_dir = paths.local_features_dir
    features_dir.mkdir(parents=True, exist_ok=True)

    handler = _LogFileHandler(conn, root, features_dir, sub_manager, loop)
    observer = Observer()
    observer.schedule(handler, str(features_dir), recursive=True)
    observer.start()
    log.info("File watcher started on %s", features_dir)
    return observer


class _ActiveFeatureHandler(FileSystemEventHandler):
    """Detect changes to .speed/active_feature."""

    def __init__(
        self,
        sub_manager: SubscriptionManager,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._sub = sub_manager
        self._loop = loop

    def _handle(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        if Path(event.src_path).name != "active_feature":
            return
        event_obj = DashboardEvent(
            type=EventType.PROCESS_STATUS_CHANGED,
            feature=None,
            payload={"trigger": "active_feature"},
        )
        asyncio.run_coroutine_threadsafe(
            self._sub.publish(event_obj), self._loop
        )

    def on_created(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        self._handle(event)

    def on_modified(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        self._handle(event)


def start_active_feature_watcher(
    project_root: str,
    sub_manager: SubscriptionManager,
    loop: asyncio.AbstractEventLoop,
) -> Observer:
    """Start watchdog observer for active_feature changes."""
    from .paths import get_paths
    paths = get_paths(project_root)
    # Watch the directory containing active_feature
    speed_dir = paths.active_feature_path.parent
    speed_dir.mkdir(parents=True, exist_ok=True)

    handler = _ActiveFeatureHandler(sub_manager, loop)
    observer = Observer()
    observer.schedule(handler, str(speed_dir), recursive=False)
    observer.start()
    log.info("Active feature watcher started on %s", speed_dir)
    return observer


class _AuthoringCheckpointHandler(FileSystemEventHandler):
    """Detect writes to authoring-<type>.json from any surface."""

    def __init__(
        self,
        sub_manager: SubscriptionManager,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._sub = sub_manager
        self._loop = loop

    def _handle(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        path = Path(event.src_path)
        name = path.name
        if not name.startswith("authoring-") or not name.endswith(".json"):
            return
        artifact_type = name[len("authoring-"):-len(".json")]
        revision = None
        status = ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            revision = data.get("revision")
            status = str(data.get("status") or "")
        except (OSError, ValueError):
            # A torn or partial read is not worth dropping the notification:
            # the client refetches through the resolver anyway.
            pass
        event_obj = DashboardEvent(
            type=EventType.AUTHORING_SESSION_CHANGED,
            feature=path.parent.name,
            payload={
                "artifact_type": artifact_type,
                "revision": revision,
                "status": status,
            },
        )
        asyncio.run_coroutine_threadsafe(self._sub.publish(event_obj), self._loop)

    def on_created(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        self._handle(event)

    def on_modified(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        self._handle(event)


def start_authoring_watcher(
    project_root: str,
    sub_manager: SubscriptionManager,
    loop: asyncio.AbstractEventLoop,
) -> Observer:
    """Watch every feature's interview checkpoint for cross-surface resume."""
    from .paths import get_paths
    paths = get_paths(project_root)
    features_dir = paths.features_dir
    features_dir.mkdir(parents=True, exist_ok=True)

    handler = _AuthoringCheckpointHandler(sub_manager, loop)
    observer = Observer()
    observer.schedule(handler, str(features_dir), recursive=True)
    observer.start()
    log.info("Authoring checkpoint watcher started on %s", features_dir)
    return observer
