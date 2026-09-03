"""Append-only project install-event log at .speed/skills/events.jsonl.

Records the changes and the detected conflicts on each surface, one entry per
skill per sync transaction. A preserved conflict is logged even though no file
moved, because the fact that sync declined to write is itself history. Contains
only names, versions, metadata excluding file hashes, and actions: no prompts,
generated content, or credentials. A skill that was already current is not
logged, so a no-op sync appends nothing.

Durability, stated precisely, because the log is read by humans debugging a bad
projection and by ``workbench-health``:

* One sync's records are written as a single buffered append while an exclusive
  ``flock`` is held, so two Workbench processes syncing the same repo serialize
  instead of interleaving records. On a platform without ``fcntl`` the lock is
  skipped and only the O_APPEND write ordering remains.
* A crash between the write and the flush can still leave one truncated line,
  always the last. ``read_events`` drops exactly that and nothing else: a bad
  line anywhere above it, or a bad line that ends in a newline, is real damage
  and gets reported with its line number rather than silently skipped.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:  # POSIX only; Workbench ships for macOS and Linux.
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

_EVENTS_REL = ".speed/skills/events.jsonl"


def new_transaction() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_events(project_root, events) -> None:
    if not events:
        return
    path = Path(project_root) / _EVENTS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
    with path.open("a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_events(project_root) -> list:
    """Stream the log into a list, tolerating only an interrupted final append."""
    path = Path(project_root) / _EVENTS_REL
    if not path.exists():
        return []
    events: list = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                events.append(json.loads(text))
            except json.JSONDecodeError as exc:
                if not line.endswith("\n"):
                    # No newline means this is the end of the file and the write
                    # that produced it never finished. Everything above it is
                    # intact, so recover the log instead of refusing to read it.
                    break
                raise ValueError(
                    f"corrupt event log ({path}): line {lineno} is not valid "
                    f"JSON: {exc}"
                ) from exc
    return events
