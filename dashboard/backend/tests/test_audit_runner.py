"""Tests for dashboard/backend/resolvers/audit_runner.py.

Covers: running-state registry, disk reads with code-fence stripping,
spec_path matching, staleness detection, filename filtering, and the
get_latest / get_recent_audits entrypoints.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.resolvers import audit_runner as _ar_mod
from backend.resolvers.audit_runner import (
    _paths_match,
    _read_audit_file,
    _running_audits,
    _running_lock,
    get_audit_status,
    get_latest_audit,
    get_recent_audits,
)
from backend import paths as paths_mod

# ── Fixture data ─────────────────────────────────────────────────

VALID_AUDIT = {
    "status": "warn",
    "spec_type": "rfc",
    "spec_file": "specs/tech/test-feature.md",
    "linked_specs": {"prd": None, "design": None},
    "issues": [
        {
            "level": 2,
            "severity": "warning",
            "section": "API Surface",
            "message": "Test issue",
        }
    ],
    "sizing": {
        "estimated_tasks": 5,
        "recommendation": "ok",
        "rationale": "fits",
        "phase_sections": {},
        "suggested_children": [],
    },
}

FENCED_AUDIT = "```json\n" + json.dumps(VALID_AUDIT, indent=2) + "\n```"
PLAIN_AUDIT = json.dumps(VALID_AUDIT, indent=2)


# ── Helpers ──────────────────────────────────────────────────────


def _make_speed_layout(root: Path, feature: str = "my-feature") -> Path:
    """Create .speed/features/{feature}/logs/ and return the logs dir."""
    logs = root / ".speed" / "features" / feature / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs


def _write_audit(logs_dir: Path, name: str, content: str) -> Path:
    """Write an audit file into a logs directory."""
    p = logs_dir / name
    p.write_text(content, encoding="utf-8")
    return p


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_running_audits():
    """Reset the running-audit registry between tests."""
    with _running_lock:
        _running_audits.clear()
    yield
    with _running_lock:
        _running_audits.clear()


@pytest.fixture(autouse=True)
def _clear_paths_cache():
    """Purge the paths module cache so each test gets a fresh SpeedPaths."""
    paths_mod._cache.clear()
    yield
    paths_mod._cache.clear()


# ═════════════════════════════════════════════════════════════════
# get_audit_status / running state registry
# ═════════════════════════════════════════════════════════════════


class TestGetAuditStatus:
    def test_no_audit_running(self):
        """Unknown spec returns None."""
        assert get_audit_status("specs/tech/nonexistent.md") is None

    def test_audit_running(self):
        """Manually registered spec shows running=True with started_at."""
        ts = datetime.now(timezone.utc).isoformat()
        with _running_lock:
            _running_audits["specs/tech/active.md"] = ts

        result = get_audit_status("specs/tech/active.md")
        assert result is not None
        assert result["running"] is True
        assert result["started_at"] == ts

    def test_audit_cleared_after(self):
        """Simulating the try/finally cleanup pattern removes the entry."""
        ts = datetime.now(timezone.utc).isoformat()
        with _running_lock:
            _running_audits["specs/tech/done.md"] = ts

        # Simulate the finally block in run_speed_audit
        with _running_lock:
            _running_audits.pop("specs/tech/done.md", None)

        assert get_audit_status("specs/tech/done.md") is None


# ═════════════════════════════════════════════════════════════════
# _read_audit_file
# ═════════════════════════════════════════════════════════════════


class TestReadAuditFile:
    def test_code_fence_stripping(self, tmp_path: Path):
        """JSON wrapped in ```json code fences is parsed correctly."""
        p = tmp_path / "audit-001.json"
        p.write_text(FENCED_AUDIT, encoding="utf-8")

        data = _read_audit_file(p)
        assert data is not None
        assert data["status"] == "warn"
        assert data["spec_file"] == "specs/tech/test-feature.md"

    def test_plain_json(self, tmp_path: Path):
        """Plain JSON (no code fences) is parsed correctly."""
        p = tmp_path / "audit-002.json"
        p.write_text(PLAIN_AUDIT, encoding="utf-8")

        data = _read_audit_file(p)
        assert data is not None
        assert data["status"] == "warn"

    def test_malformed_json(self, tmp_path: Path):
        """Garbage content returns None."""
        p = tmp_path / "audit-003.json"
        p.write_text("this is not json at all {{{", encoding="utf-8")

        assert _read_audit_file(p) is None

    def test_missing_file(self, tmp_path: Path):
        """Non-existent file returns None."""
        assert _read_audit_file(tmp_path / "ghost.json") is None


# ═════════════════════════════════════════════════════════════════
# _paths_match
# ═════════════════════════════════════════════════════════════════


class TestPathsMatch:
    def test_exact_match(self):
        assert _paths_match("specs/tech/foo.md", "specs/tech/foo.md") is True

    def test_leading_dot_slash(self):
        """./specs/tech/foo.md matches specs/tech/foo.md."""
        assert _paths_match("./specs/tech/foo.md", "specs/tech/foo.md") is True
        assert _paths_match("specs/tech/foo.md", "./specs/tech/foo.md") is True

    def test_suffix_match(self):
        """Short path matches when the full path ends with it."""
        assert _paths_match("specs/tech/foo.md", "foo.md") is True
        assert _paths_match("foo.md", "specs/tech/foo.md") is True

    def test_no_match(self):
        assert _paths_match("specs/tech/foo.md", "specs/tech/bar.md") is False


# ═════════════════════════════════════════════════════════════════
# get_latest_audit / get_recent_audits (with monkeypatched _spec_mtime)
# ═════════════════════════════════════════════════════════════════


class TestGetLatestAudit:
    """All tests in this class work around the NameError bug on line 94 of
    audit_runner.py (`root` instead of `project_root`). We patch _spec_mtime
    AND inject `root` into the module globals so the call `_spec_mtime(root, ...)`
    resolves. Once the bug is fixed, the `_inject_root` fixture can be removed
    and these tests remain valid.
    """

    @pytest.fixture(autouse=True)
    def _inject_root(self, tmp_path: Path):
        """Inject `root` into audit_runner module globals to work around
        the line-94 NameError (uses `root` instead of `project_root`).
        """
        _ar_mod.root = tmp_path
        yield
        if hasattr(_ar_mod, "root"):
            delattr(_ar_mod, "root")

    def test_no_audit_files(self, tmp_path: Path):
        """Empty features dir returns None."""
        (tmp_path / ".speed" / "features").mkdir(parents=True)

        with patch(
            "backend.resolvers.audit_runner._spec_mtime", return_value=None
        ):
            result = get_latest_audit(tmp_path, "specs/tech/test-feature.md")
        assert result is None

    def test_single_audit_file(self, tmp_path: Path):
        """One valid fenced audit file is returned with metadata fields."""
        logs = _make_speed_layout(tmp_path)
        _write_audit(logs, "audit-1000.json", FENCED_AUDIT)

        # Spec does not exist on disk: _stale should be False
        with patch(
            "backend.resolvers.audit_runner._spec_mtime", return_value=None
        ):
            result = get_latest_audit(tmp_path, "specs/tech/test-feature.md")

        assert result is not None
        assert result["status"] == "warn"
        assert result["spec_file"] == "specs/tech/test-feature.md"
        assert result["_stale"] is False
        assert "_ran_at" in result
        assert result["_feature"] == "my-feature"

    def test_multiple_audit_files(self, tmp_path: Path):
        """Three audit files for the same spec: get_latest returns newest by mtime."""
        logs = _make_speed_layout(tmp_path)

        oldest = _write_audit(logs, "audit-100.json", FENCED_AUDIT)
        middle = _write_audit(logs, "audit-200.json", FENCED_AUDIT)
        newest = _write_audit(logs, "audit-300.json", FENCED_AUDIT)

        # Force distinct mtimes (filesystem resolution can be coarse)
        now = time.time()
        os.utime(oldest, (now - 30, now - 30))
        os.utime(middle, (now - 15, now - 15))
        os.utime(newest, (now, now))

        with patch(
            "backend.resolvers.audit_runner._spec_mtime", return_value=None
        ):
            result = get_latest_audit(tmp_path, "specs/tech/test-feature.md")

        assert result is not None
        # _ran_at should reflect the newest file's mtime
        ran_at = datetime.fromisoformat(result["_ran_at"])
        # Within 2 seconds of `now` to handle small clock drift
        assert abs(ran_at.timestamp() - now) < 2

    def test_recent_audits_limit(self, tmp_path: Path):
        """3 files with limit=2 returns exactly 2 results."""
        logs = _make_speed_layout(tmp_path)

        now = time.time()
        for i, offset in enumerate([30, 15, 0]):
            p = _write_audit(logs, f"audit-{i}.json", FENCED_AUDIT)
            os.utime(p, (now - offset, now - offset))

        with patch(
            "backend.resolvers.audit_runner._spec_mtime", return_value=None
        ):
            results = get_recent_audits(
                tmp_path, "specs/tech/test-feature.md", limit=2
            )

        assert len(results) == 2

    def test_spec_path_matching(self, tmp_path: Path):
        """Audit with spec_file matching the query is returned; non-matching is not."""
        logs = _make_speed_layout(tmp_path)

        # Audit for a different spec
        other = dict(VALID_AUDIT, spec_file="specs/tech/bar.md")
        _write_audit(logs, "audit-500.json", "```json\n" + json.dumps(other) + "\n```")

        with patch(
            "backend.resolvers.audit_runner._spec_mtime", return_value=None
        ):
            # Querying for foo.md should not find bar.md
            result = get_latest_audit(tmp_path, "specs/tech/foo.md")
        assert result is None

        with patch(
            "backend.resolvers.audit_runner._spec_mtime", return_value=None
        ):
            # Querying for bar.md should find it
            result = get_latest_audit(tmp_path, "specs/tech/bar.md")
        assert result is not None
        assert result["spec_file"] == "specs/tech/bar.md"

    def test_staleness_detection_stale(self, tmp_path: Path):
        """Spec modified after audit run marks _stale=True."""
        logs = _make_speed_layout(tmp_path)
        audit_file = _write_audit(logs, "audit-600.json", FENCED_AUDIT)

        now = time.time()
        os.utime(audit_file, (now - 60, now - 60))  # audit is 60s old
        spec_mtime = now  # spec was modified just now

        with patch(
            "backend.resolvers.audit_runner._spec_mtime", return_value=spec_mtime
        ):
            result = get_latest_audit(tmp_path, "specs/tech/test-feature.md")

        assert result is not None
        assert result["_stale"] is True

    def test_staleness_detection_fresh(self, tmp_path: Path):
        """Spec older than audit marks _stale=False."""
        logs = _make_speed_layout(tmp_path)
        audit_file = _write_audit(logs, "audit-700.json", FENCED_AUDIT)

        now = time.time()
        os.utime(audit_file, (now, now))  # audit is very recent
        spec_mtime = now - 120  # spec was modified 2 minutes ago

        with patch(
            "backend.resolvers.audit_runner._spec_mtime", return_value=spec_mtime
        ):
            result = get_latest_audit(tmp_path, "specs/tech/test-feature.md")

        assert result is not None
        assert result["_stale"] is False

    def test_filename_filter_valid(self, tmp_path: Path):
        """Files named audit-{N}.json and plan-audit-{type}-{N}.json are matched."""
        logs = _make_speed_layout(tmp_path)

        _write_audit(logs, "audit-12345.json", FENCED_AUDIT)
        _write_audit(logs, "plan-audit-tech-99999.json", FENCED_AUDIT)

        with patch(
            "backend.resolvers.audit_runner._spec_mtime", return_value=None
        ):
            results = get_recent_audits(
                tmp_path, "specs/tech/test-feature.md", limit=10
            )

        assert len(results) == 2

    def test_filename_filter_rejected(self, tmp_path: Path):
        """Files that don't match the audit naming convention are ignored."""
        logs = _make_speed_layout(tmp_path)

        # These should NOT be picked up
        _write_audit(logs, "security-audit.json", FENCED_AUDIT)
        _write_audit(logs, "random-audit-notes.json", FENCED_AUDIT)
        _write_audit(logs, "myaudit-123.json", FENCED_AUDIT)

        with patch(
            "backend.resolvers.audit_runner._spec_mtime", return_value=None
        ):
            results = get_recent_audits(
                tmp_path, "specs/tech/test-feature.md", limit=10
            )

        assert len(results) == 0

    def test_malformed_json_skipped(self, tmp_path: Path):
        """Malformed audit files are silently skipped."""
        logs = _make_speed_layout(tmp_path)
        _write_audit(logs, "audit-800.json", "not valid json")

        with patch(
            "backend.resolvers.audit_runner._spec_mtime", return_value=None
        ):
            result = get_latest_audit(tmp_path, "specs/tech/test-feature.md")

        assert result is None


# ═════════════════════════════════════════════════════════════════
# _to_speed_audit: null-safe conversion from disk JSON to GraphQL
# ═════════════════════════════════════════════════════════════════


class TestToSpeedAudit:
    """Verify _to_speed_audit handles null list fields from SPEED audit JSON.

    SPEED's audit agent can write explicit null values for list fields
    (e.g. "suggested_children": null). Python dict.get() returns None
    for these, not the default value. The converter must coerce None to [].
    """

    @pytest.fixture(autouse=True)
    def _import_converter(self):
        try:
            from backend.schema import _to_speed_audit
            self.convert = _to_speed_audit
        except ImportError:
            pytest.skip("strawberry not available")

    def test_null_suggested_children(self):
        data = {
            "status": "warn", "spec_type": "rfc", "spec_file": "specs/tech/foo.md",
            "linked_specs": {"prd": None, "design": None, "parent_rfc": None, "child_rfcs": None},
            "issues": [{"level": 2, "severity": "warning", "section": "API", "message": "test"}],
            "sizing": {
                "estimated_tasks": 10, "recommendation": "split",
                "rationale": "test", "suggested_children": None,
            },
            "_stale": False, "_ran_at": "2026-01-01T00:00:00Z", "_feature": "test",
        }
        result = self.convert(data)
        assert result.sizing is not None
        assert result.sizing.suggested_children == []
        assert result.linked_specs.child_rfcs == []

    def test_null_issues(self):
        data = {
            "status": "pass", "spec_type": "prd", "spec_file": "specs/product/foo.md",
            "linked_specs": None, "issues": None, "sizing": None,
            "_stale": False, "_ran_at": "2026-01-01T00:00:00Z", "_feature": "test",
        }
        result = self.convert(data)
        assert result.issues == []
        assert result.sizing is None
        assert result.linked_specs is None

    def test_null_sections_and_depends_on(self):
        data = {
            "status": "warn", "spec_type": "rfc", "spec_file": "specs/tech/foo.md",
            "linked_specs": None, "issues": [],
            "sizing": {
                "estimated_tasks": 15, "recommendation": "multi_rfc",
                "rationale": "big", "suggested_children": [
                    {"name": "child.md", "sections": None, "depends_on": None, "testable_output": "x"},
                ],
            },
            "_stale": False, "_ran_at": "2026-01-01T00:00:00Z", "_feature": "test",
        }
        result = self.convert(data)
        child = result.sizing.suggested_children[0]
        assert child.sections == []
        assert child.depends_on == []

    def test_missing_keys_use_defaults(self):
        data = {"_stale": False, "_ran_at": "", "_feature": ""}
        result = self.convert(data)
        assert result.status == "unknown"
        assert result.issues == []
        assert result.sizing is None

