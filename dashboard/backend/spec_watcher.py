"""File watcher for spec .md files.

Same pattern as ingest.py's _LogFileHandler: watchdog observer with debounce.
On create/modify: update registry + edges, publish SPEC_CHANGED event.
On delete: remove from registry.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileCreatedEvent,
    FileModifiedEvent,
    FileDeletedEvent,
)

from .subscriptions import SubscriptionManager, DashboardEvent, EventType
from . import spec_registry, spec_graph

log = logging.getLogger("speed.dashboard.spec_watcher")


class _SpecFileHandler(FileSystemEventHandler):
    """Watchdog handler that triggers spec re-indexing on .md file changes."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        project_root: Path,
        sub_manager: SubscriptionManager,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._conn = conn
        self._root = project_root
        self._sub = sub_manager
        self._loop = loop
        self._debounce: dict[str, float] = {}

    def _handle_change(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        path = Path(event.src_path)
        if path.suffix != ".md":
            return

        now = time.monotonic()
        key = str(path)
        last = self._debounce.get(key, 0)
        if now - last < 0.1:
            return
        self._debounce[key] = now

        try:
            rel_path = str(path.relative_to(self._root))
        except ValueError:
            return

        log.info("Spec changed: %s", rel_path)
        spec_registry.update_spec(self._conn, path, self._root)
        spec_graph.update_edges_for_spec(self._conn, path, self._root)

        event_obj = DashboardEvent(
            type=EventType.SPEC_CHANGED,
            payload={"path": rel_path, "action": "modified"},
        )
        asyncio.run_coroutine_threadsafe(
            self._sub.publish(event_obj), self._loop
        )

    def _handle_delete(self, event: FileDeletedEvent) -> None:
        path = Path(event.src_path)
        if path.suffix != ".md":
            return

        # Ignore spurious delete events (e.g. from atomic write patterns)
        if path.exists():
            return

        try:
            rel_path = str(path.relative_to(self._root))
        except ValueError:
            return

        log.info("Spec deleted: %s", rel_path)
        spec_registry.remove_spec(self._conn, path, self._root)

        event_obj = DashboardEvent(
            type=EventType.SPEC_CHANGED,
            payload={"path": rel_path, "action": "deleted"},
        )
        asyncio.run_coroutine_threadsafe(
            self._sub.publish(event_obj), self._loop
        )

    def on_created(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        self._handle_change(event)

    def on_modified(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        self._handle_change(event)

    def on_deleted(self, event: FileDeletedEvent) -> None:
        self._handle_delete(event)


def start_spec_watcher(
    conn: sqlite3.Connection,
    project_root: str,
    sub_manager: SubscriptionManager,
    loop: asyncio.AbstractEventLoop,
) -> Observer:
    """Start watchdog observer on specs/ directory for .md file changes."""
    root = Path(project_root).resolve()
    specs_dir = root / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)

    handler = _SpecFileHandler(conn, root, sub_manager, loop)
    observer = Observer()
    observer.schedule(handler, str(specs_dir), recursive=True)
    observer.start()
    log.info("Spec watcher started on %s", specs_dir)
    return observer
