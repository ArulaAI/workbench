"""Tests for _AuditFileHandler from audit_watcher.py.

Constructs the handler directly with mocks and verifies event routing,
filtering, feature-name extraction, and debounce behavior.
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from backend.audit_watcher import _AuditFileHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def features_dir(tmp_path: Path) -> Path:
    """Create a features directory structure under tmp_path."""
    d = tmp_path / ".speed" / "local" / "features"
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def mock_sub_manager() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def mock_loop() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def handler(
    features_dir: Path, mock_sub_manager: MagicMock, mock_loop: MagicMock
) -> _AuditFileHandler:
    return _AuditFileHandler(features_dir, mock_sub_manager, mock_loop)


def _make_event(src_path: str | Path) -> MagicMock:
    """Create a mock watchdog event with a src_path attribute."""
    event = MagicMock()
    event.src_path = str(src_path)
    return event


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuditJsonTriggersEvent:
    """Event with audit JSON in the logs dir publishes AUDIT_COMPLETED."""

    def test_on_created(
        self, handler: _AuditFileHandler, features_dir: Path, mock_loop: MagicMock
    ) -> None:
        audit_path = features_dir / "my-feat" / "logs" / "audit-12345.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("backend.audit_watcher.asyncio.run_coroutine_threadsafe") as rctf:
            handler.on_created(_make_event(audit_path))

            rctf.assert_called_once()
            published_event = rctf.call_args[0][0]  # first positional: the coroutine arg
            # run_coroutine_threadsafe receives a coroutine; the handler passes
            # self._sub.publish(event_obj), so sub.publish was called with the event.
            # Easier to check via the sub_manager mock directly.

        # The handler calls self._sub.publish(event_obj) inside
        # asyncio.run_coroutine_threadsafe, so we patch that and inspect.
        # Alternatively, re-run and inspect sub mock.

    def test_publish_payload(
        self, features_dir: Path, mock_sub_manager: MagicMock, mock_loop: MagicMock
    ) -> None:
        h = _AuditFileHandler(features_dir, mock_sub_manager, mock_loop)
        audit_path = features_dir / "my-feat" / "logs" / "audit-12345.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("backend.audit_watcher.asyncio.run_coroutine_threadsafe") as rctf:
            h.on_created(_make_event(audit_path))

            rctf.assert_called_once()
            # First arg is the coroutine (sub.publish(event_obj))
            # Second arg is the loop
            assert rctf.call_args[0][1] is mock_loop

            # The coroutine was created by calling mock_sub_manager.publish(event_obj).
            # Since publish is a mock, we can inspect what it received.
            mock_sub_manager.publish.assert_called_once()
            event_obj = mock_sub_manager.publish.call_args[0][0]

            from backend.subscriptions import EventType

            assert event_obj.type == EventType.AUDIT_COMPLETED
            assert event_obj.feature == "my-feat"
            assert event_obj.payload == {
                "file": "audit-12345.json",
                "feature": "my-feat",
            }


class TestPlanAuditTriggers:
    """plan-audit files contain 'audit' in the name and should trigger."""

    def test_plan_audit_publishes(
        self, handler: _AuditFileHandler, features_dir: Path, mock_sub_manager: MagicMock
    ) -> None:
        audit_path = features_dir / "tech" / "logs" / "plan-audit-tech-12345.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("backend.audit_watcher.asyncio.run_coroutine_threadsafe"):
            handler.on_modified(_make_event(audit_path))

            mock_sub_manager.publish.assert_called_once()
            event_obj = mock_sub_manager.publish.call_args[0][0]

            from backend.subscriptions import EventType

            assert event_obj.type == EventType.AUDIT_COMPLETED
            assert event_obj.feature == "tech"


class TestNonJsonIgnored:
    """Files that aren't .json should be silently ignored."""

    def test_jsonl_ignored(
        self, handler: _AuditFileHandler, features_dir: Path, mock_sub_manager: MagicMock
    ) -> None:
        path = features_dir / "my-feat" / "logs" / "audit-12345.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)

        with patch("backend.audit_watcher.asyncio.run_coroutine_threadsafe") as rctf:
            handler.on_created(_make_event(path))
            rctf.assert_not_called()
            mock_sub_manager.publish.assert_not_called()


class TestNonAuditJsonIgnored:
    """JSON files without 'audit' in the name should be ignored."""

    def test_state_json_ignored(
        self, handler: _AuditFileHandler, features_dir: Path, mock_sub_manager: MagicMock
    ) -> None:
        path = features_dir / "my-feat" / "logs" / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        with patch("backend.audit_watcher.asyncio.run_coroutine_threadsafe") as rctf:
            handler.on_created(_make_event(path))
            rctf.assert_not_called()
            mock_sub_manager.publish.assert_not_called()


class TestFileOutsideLogsIgnored:
    """Files outside the expected features/*/logs/ structure should be ignored."""

    def test_file_in_feature_root(
        self, handler: _AuditFileHandler, features_dir: Path, mock_sub_manager: MagicMock
    ) -> None:
        # File directly in feature dir, not in logs/
        path = features_dir / "my-feat" / "audit-12345.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        with patch("backend.audit_watcher.asyncio.run_coroutine_threadsafe") as rctf:
            handler.on_created(_make_event(path))
            rctf.assert_not_called()

    def test_file_in_wrong_subdir(
        self, handler: _AuditFileHandler, features_dir: Path, mock_sub_manager: MagicMock
    ) -> None:
        # File in tasks/ instead of logs/
        path = features_dir / "my-feat" / "tasks" / "audit-12345.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        with patch("backend.audit_watcher.asyncio.run_coroutine_threadsafe") as rctf:
            handler.on_created(_make_event(path))
            rctf.assert_not_called()

    def test_file_completely_outside(
        self, handler: _AuditFileHandler, features_dir: Path, mock_sub_manager: MagicMock, tmp_path: Path
    ) -> None:
        # File outside the features directory entirely
        path = tmp_path / "some" / "other" / "audit-12345.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        with patch("backend.audit_watcher.asyncio.run_coroutine_threadsafe") as rctf:
            handler.on_created(_make_event(path))
            rctf.assert_not_called()


class TestDebounce:
    """Two events for the same file within 200ms produce one publish; 300ms apart produce two."""

    def test_duplicate_within_window(
        self, features_dir: Path, mock_sub_manager: MagicMock, mock_loop: MagicMock
    ) -> None:
        h = _AuditFileHandler(features_dir, mock_sub_manager, mock_loop)
        audit_path = features_dir / "my-feat" / "logs" / "audit-99.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        ev = _make_event(audit_path)

        with patch("backend.audit_watcher.asyncio.run_coroutine_threadsafe"):
            h.on_created(ev)
            h.on_modified(ev)  # immediately after, well within 200ms

            assert mock_sub_manager.publish.call_count == 1

    def test_events_after_debounce_window(
        self, features_dir: Path, mock_sub_manager: MagicMock, mock_loop: MagicMock
    ) -> None:
        h = _AuditFileHandler(features_dir, mock_sub_manager, mock_loop)
        audit_path = features_dir / "my-feat" / "logs" / "audit-99.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        ev = _make_event(audit_path)

        with patch("backend.audit_watcher.asyncio.run_coroutine_threadsafe"):
            h.on_created(ev)
            assert mock_sub_manager.publish.call_count == 1

            time.sleep(0.3)  # exceed the 200ms debounce window

            h.on_modified(ev)
            assert mock_sub_manager.publish.call_count == 2


class TestFeatureNameExtracted:
    """The feature name is the first path component relative to features_dir."""

    @pytest.mark.parametrize(
        "feature_name",
        ["my-feat", "auth-service", "landing-page-v2", "x"],
    )
    def test_various_feature_names(
        self,
        features_dir: Path,
        mock_sub_manager: MagicMock,
        mock_loop: MagicMock,
        feature_name: str,
    ) -> None:
        h = _AuditFileHandler(features_dir, mock_sub_manager, mock_loop)
        audit_path = features_dir / feature_name / "logs" / "audit-1.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("backend.audit_watcher.asyncio.run_coroutine_threadsafe"):
            h.on_created(_make_event(audit_path))

            mock_sub_manager.publish.assert_called_once()
            event_obj = mock_sub_manager.publish.call_args[0][0]
            assert event_obj.feature == feature_name
            assert event_obj.payload["feature"] == feature_name
