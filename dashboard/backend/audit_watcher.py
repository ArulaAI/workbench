"""File watcher for audit JSON files.

Same pattern as spec_watcher.py: watchdog observer with debounce.
Watches .speed/features/*/logs/ for new or modified *audit*.json files.
Publishes AUDIT_COMPLETED events so the frontend can refetch.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileCreatedEvent,
    FileModifiedEvent,
)

from .subscriptions import SubscriptionManager, DashboardEvent, EventType

log = logging.getLogger("speed.dashboard.audit_watcher")


class _AuditFileHandler(FileSystemEventHandler):
    """Watchdog handler that publishes AUDIT_COMPLETED on audit JSON changes."""

    def __init__(
        self,
        features_dir: Path,
        sub_manager: SubscriptionManager,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._features_dir = features_dir
        self._sub = sub_manager
        self._loop = loop
        self._debounce: dict[str, float] = {}

    def _handle(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        path = Path(event.src_path)

        # Only audit JSON files
        if path.suffix != ".json":
            return
        if "audit" not in path.name:
            return

        # Must be in a feature logs directory
        try:
            rel = path.relative_to(self._features_dir)
        except ValueError:
            return

        parts = rel.parts
        if len(parts) < 3 or parts[1] != "logs":
            return

        # Debounce: 200ms
        now = time.monotonic()
        key = str(path)
        if now - self._debounce.get(key, 0) < 0.2:
            return
        self._debounce[key] = now

        feature = parts[0]
        log.info("Audit file changed: %s (feature: %s)", path.name, feature)

        event_obj = DashboardEvent(
            type=EventType.AUDIT_COMPLETED,
            feature=feature,
            payload={"file": path.name, "feature": feature},
        )
        asyncio.run_coroutine_threadsafe(
            self._sub.publish(event_obj), self._loop
        )

    def on_created(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        self._handle(event)

    def on_modified(self, event: FileCreatedEvent | FileModifiedEvent) -> None:
        self._handle(event)


def start_audit_watcher(
    project_root: str,
    sub_manager: SubscriptionManager,
    loop: asyncio.AbstractEventLoop,
) -> Observer:
    """Start watchdog observer for audit JSON changes in the local features zone."""
    from .paths import get_paths
    paths = get_paths(project_root)
    # Audit logs live in the local zone (or .speed/features/ in single-player)
    features_dir = paths.local_features_dir
    features_dir.mkdir(parents=True, exist_ok=True)

    handler = _AuditFileHandler(features_dir, sub_manager, loop)
    observer = Observer()
    observer.schedule(handler, str(features_dir), recursive=True)
    observer.start()
    log.info("Audit watcher started on %s", features_dir)
    return observer
