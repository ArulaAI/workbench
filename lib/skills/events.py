"""Append-only project install-event log at .speed/skills/events.jsonl.

Records what actually changed on each surface per sync transaction. Contains
only names, versions, hashes-free metadata, and actions: no prompts, generated
content, or credentials. Unchanged skills are not logged, so a no-op sync
appends nothing.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
    with path.open("a") as fh:
        for event in events:
            fh.write(json.dumps(event, sort_keys=True) + "\n")


def read_events(project_root) -> list:
    path = Path(project_root) / _EVENTS_REL
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
