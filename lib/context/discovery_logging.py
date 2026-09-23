"""Structured, content-safe logging for repository discovery refreshes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_OPAQUE = re.compile(r"\b[A-Za-z0-9_+=]{32,}\b")
_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*[^\s,;}]+")
_SENSITIVE_KEYS = re.compile(
    r"(?i)(api[_-]?key|prompt|response|source|secret|password|token|authorization)")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def describe(value: Any, *, schema: str | None = None,
             artifact: str | None = None) -> dict[str, Any]:
    """Describe a value without copying content into the log."""
    data = _canonical(value)
    if isinstance(value, dict):
        counts = {key: len(child) for key, child in value.items()
                  if isinstance(child, (dict, list))}
    elif isinstance(value, list):
        counts = {"items": len(value)}
    else:
        counts = {}
    if schema is None:
        schema = ({dict: "JsonObject", list: "JsonArray", str: "JsonString",
                   bool: "JsonBoolean", int: "JsonNumber", float: "JsonNumber"}
                  .get(type(value), "Null" if value is None else type(value).__name__))
    return {"schema": schema, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "counts": counts, "artifact": artifact}


class _Boundary(AbstractContextManager):
    def __init__(self, recorder: "DiscoveryRecorder", name: str, value: Any,
                 metadata: dict[str, Any] | None, schema: str | None,
                 artifact: str | None):
        self.recorder, self.name = recorder, name
        self.boundary_id = str(uuid.uuid4())
        self.started, self.closed = time.monotonic(), False
        recorder.emit(name, "input", descriptor=describe(
            value, schema=schema, artifact=artifact),
                      boundary_id=self.boundary_id, metadata=metadata)

    def success(self, value: Any = None, *, schema: str | None = None,
                artifact: str | None = None, metadata=None) -> None:
        if self.closed:
            return
        self.recorder.emit(self.name, "output",
            descriptor=describe(value, schema=schema, artifact=artifact),
            boundary_id=self.boundary_id, metadata=metadata,
            duration_ms=int((time.monotonic()-self.started)*1000))
        self.closed = True

    def __exit__(self, exc_type, exc, traceback):
        if exc is not None and not self.closed:
            self.recorder.emit(self.name, "error", boundary_id=self.boundary_id,
                error={"code": getattr(exc, "code", type(exc).__name__),
                       "message": self.recorder.sanitize(str(exc)),
                       "retryable": bool(getattr(exc, "retryable", False))},
                duration_ms=int((time.monotonic()-self.started)*1000))
            self.closed = True
        elif not self.closed:
            self.success()
        return False


class DiscoveryRecorder:
    """Thread-safe append-only journal with a safe progress callback."""
    def __init__(self, root: str | Path, run_id: str | None = None,
                 progress: Callable[[dict[str, Any]], None] | None = None):
        self.root, self.run_id = Path(root).resolve(), run_id or str(uuid.uuid4())
        self.progress_callback = progress
        self.started, self.started_at = time.monotonic(), datetime.now(timezone.utc).isoformat()
        self.sequence, self.lock = 0, threading.Lock()
        self._open_boundaries: dict[str, str] = {}
        self.directory = self.root/".speed/logs/discovery"/self.run_id
        if any(parent.is_symlink() for parent in self.directory.parents
               if parent != self.root.parent):
            raise OSError("Discovery log path contains a symbolic link")
        self.directory.mkdir(parents=True, exist_ok=False)
        self.events_path = self.directory/"events.jsonl"
        self.stream = os.fdopen(os.open(
            self.events_path, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600), "ab", buffering=0)
        self._write_manifest("running")

    @property
    def relative_path(self) -> str:
        return str(self.directory.relative_to(self.root))

    def sanitize(self, message: str) -> str:
        home = str(Path.home())
        if home != "/":
            message = message.replace(home, "~")
        if "Traceback (most recent call last)" in message:
            message = message.split("Traceback (most recent call last)", 1)[0]
        message = _SECRET.sub(lambda match: match.group(1)+"=[redacted]", message)
        return _OPAQUE.sub("[redacted]", message).strip()[:500]

    def _safe_error(self, value: Any, key: str = "") -> Any:
        if _SENSITIVE_KEYS.search(key):
            return "[redacted]"
        if isinstance(value, str):
            return self.sanitize(value)
        if isinstance(value, dict):
            return {str(child_key): self._safe_error(child, str(child_key))
                    for child_key, child in value.items()}
        if isinstance(value, list):
            return [self._safe_error(child, key) for child in value]
        return value

    def _safe_metadata(self, value: Any, key: str = "") -> Any:
        if _SENSITIVE_KEYS.search(key):
            return "[redacted]"
        if isinstance(value, str):
            return self.sanitize(value)
        if isinstance(value, dict):
            return {str(child_key):self._safe_metadata(child, str(child_key))
                    for child_key,child in value.items()}
        if isinstance(value, list):
            return [self._safe_metadata(child, key) for child in value]
        return value

    def boundary(self, name: str, value: Any = None, *, metadata=None,
                 schema: str | None = None,
                 artifact: str | None = None) -> _Boundary:
        return _Boundary(self, name, value, metadata, schema, artifact)

    def emit(self, stage: str, direction: str, *, descriptor=None,
             boundary_id=None, metadata=None, error=None, duration_ms=None) -> None:
        with self.lock:
            if boundary_id and direction == "input":
                self._open_boundaries[boundary_id] = stage
            elif boundary_id and direction in ("output", "error"):
                self._open_boundaries.pop(boundary_id, None)
            self.sequence += 1
            event = {"schema_version":1, "run_id":self.run_id,
                     "event_id":str(uuid.uuid4()), "sequence":self.sequence,
                     "timestamp":datetime.now(timezone.utc).isoformat(),
                     "elapsed_ms":int((time.monotonic()-self.started)*1000),
                     "stage":stage, "direction":direction,
                     "boundary_id":boundary_id, "duration_ms":duration_ms,
                     "descriptor":descriptor,
                     "metadata":self._safe_metadata(metadata or {}),
                     "error":self._safe_error(error)}
            self.stream.write(_canonical(event)+b"\n")

    def progress(self, stage: str, message: str, *, level: str = "step", details=None) -> None:
        public = {"stage":stage, "message":self.sanitize(message),
                  "level":level, "details":details or {}}
        self.emit(stage, "progress", metadata=public)
        if self.progress_callback:
            try:
                self.progress_callback(public)
            except Exception:
                # Presentation is advisory; it must not alter discovery.
                pass

    def finish(self, outcome: str, result: Any = None) -> None:
        for boundary_id, stage in list(self._open_boundaries.items()):
            self.emit(stage, "error", boundary_id=boundary_id,
                      error={"code":"UNCLOSED_BOUNDARY",
                             "message":"Boundary did not produce a terminal event",
                             "retryable":False})
        self.emit("refresh", "terminal", descriptor=describe(result),
                  metadata={"outcome":outcome})
        self.stream.flush(); os.fsync(self.stream.fileno()); self.stream.close()
        self._write_manifest(outcome)

    def _write_manifest(self, outcome: str) -> None:
        event_bytes = self.events_path.read_bytes()
        event_count = len(event_bytes.splitlines())
        manifest = {"schema_version":1, "run_id":self.run_id,
                    "started_at":self.started_at,
                    "completed_at":(datetime.now(timezone.utc).isoformat()
                                    if outcome != "running" else None),
                    "outcome":outcome, "event_count":event_count,
                    "segments":([{"path":"events.jsonl",
                    "sha256":hashlib.sha256(event_bytes).hexdigest()}]
                    if outcome != "running" else [])}
        fd, temporary = tempfile.mkstemp(prefix=".manifest-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(_canonical(manifest)); output.flush(); os.fsync(output.fileno())
            os.replace(temporary, self.directory/"manifest.json")
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def prune(self, retention_days: int, max_runs: int = 50) -> None:
        """Remove only completed journals outside bounded retention."""
        parent = self.directory.parent
        cutoff = time.time()-retention_days*86400
        completed = []
        for directory in parent.iterdir():
            if directory == self.directory or not directory.is_dir():
                continue
            manifest = directory/"manifest.json"
            try:
                data = json.loads(manifest.read_text())
                if data.get("outcome") == "running":
                    continue
                completed.append((manifest.stat().st_mtime,directory))
            except (OSError,ValueError):
                continue
        for index, (modified, directory) in enumerate(
                sorted(completed,reverse=True)):
            if modified < cutoff or index >= max_runs:
                for path in directory.iterdir():
                    if path.is_file() and not path.is_symlink():
                        path.unlink()
                directory.rmdir()
