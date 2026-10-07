"""Append one JSON line per sync run to ``.speed/skills/sync-log.jsonl``.

The install-event log (``events.py``) records each *change* a sync made, and a
no-op sync appends nothing to it. This log records each *run*, including the
ones that failed or aborted, with the cause of every failure: it is what a
maintainer reads after a CI job went red and the terminal is gone.

Rotation keeps the file bounded. When the active file has reached
``max_bytes`` it becomes ``.1``, the old ``.1`` becomes ``.2``, and so on,
keeping ``keep`` files in total. Writing the log is never allowed to fail a
sync: ``append`` reports ``False`` and the caller warns.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_KEEP = 3


class SyncLogWriter:
    def __init__(self, path, max_bytes: int = DEFAULT_MAX_BYTES, keep: int = DEFAULT_KEEP):
        if keep < 1:
            raise ValueError("keep must be at least 1")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.keep = keep
        self.last_error: Exception | None = None

    def _rotated(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.name}.{index}")

    def _rotate_if_full(self) -> None:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return
        if size < self.max_bytes:
            return
        if self.keep == 1:
            self.path.unlink()
            return
        oldest = self._rotated(self.keep - 1)
        if oldest.exists():
            oldest.unlink()
        for index in range(self.keep - 2, 0, -1):
            src = self._rotated(index)
            if src.exists():
                os.replace(src, self._rotated(index + 1))
        os.replace(self.path, self._rotated(1))

    def append(self, report) -> bool:
        """Write one line for ``report``. Returns False instead of raising."""
        data = report.to_dict() if hasattr(report, "to_dict") else report
        line = json.dumps(data, sort_keys=True) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_full()
            # One write call per run, so concurrent appenders cannot interleave
            # inside a line on platforms where O_APPEND writes are atomic.
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError as exc:
            self.last_error = exc
            return False
        self.last_error = None
        return True
