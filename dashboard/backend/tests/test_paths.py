"""Tests for dashboard/backend/paths.py.

Covers single-player layout, multiplayer layout, derived paths,
feature_names() listing, and the module-level get_paths() cache.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add the dashboard/ directory so 'backend' resolves as a top-level package.
_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.paths import SpeedPaths, get_paths, _cache


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture()
def sp_root(tmp_path: Path) -> Path:
    """Single-player project: .speed/features/ exists, .speed/shared/ does not."""
    speed = tmp_path / ".speed"
    (speed / "features" / "auth").mkdir(parents=True)
    (speed / "features" / "billing").mkdir(parents=True)
    (speed / "memory" / "observations").mkdir(parents=True)
    (speed / "defects").mkdir(parents=True)
    (speed / "context").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def mp_root(tmp_path: Path) -> Path:
    """Multiplayer project: .speed/shared/ directory exists."""
    speed = tmp_path / ".speed"
    (speed / "shared" / "features" / "auth").mkdir(parents=True)
    (speed / "shared" / "features" / "billing").mkdir(parents=True)
    (speed / "shared" / "knowledge" / "observations").mkdir(parents=True)
    (speed / "shared" / "defects").mkdir(parents=True)
    (speed / "shared" / "events").mkdir(parents=True)
    (speed / "shared" / "roster").mkdir(parents=True)
    (speed / "shared" / "proposals").mkdir(parents=True)
    (speed / "local" / "features" / "auth").mkdir(parents=True)
    (speed / "local" / "features" / "billing").mkdir(parents=True)
    (speed / "context").mkdir(parents=True)
    return tmp_path


# ── Single-player mode ────────────────────────────────────────────


class TestSinglePlayer:
    """All paths collapse into .speed/ with no shared/local split."""

    def test_mp_disabled(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.mp_enabled is False

    def test_features_dir(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.features_dir == sp_root / ".speed" / "features"

    def test_local_features_dir_same_as_features_dir(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.local_features_dir == sp_root / ".speed" / "features"
        assert p.local_features_dir == p.features_dir

    def test_feature_shared(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.feature_shared("auth") == sp_root / ".speed" / "features" / "auth"

    def test_feature_local(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.feature_local("auth") == sp_root / ".speed" / "features" / "auth"

    def test_feature_shared_and_local_identical(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.feature_shared("billing") == p.feature_local("billing")

    def test_memory_dir(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.memory_dir == sp_root / ".speed" / "memory"

    def test_observations_dir(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.observations_dir == sp_root / ".speed" / "memory" / "observations"

    def test_conventions_path(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.conventions_path == sp_root / ".speed" / "memory" / "conventions.json"

    def test_defects_dir(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.defects_dir == sp_root / ".speed" / "defects"

    def test_context_dir(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.context_dir == sp_root / ".speed" / "context"

    def test_active_feature_path(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.active_feature_path == sp_root / ".speed" / "active_feature"

    def test_db_path(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.db_path == sp_root / ".speed" / "dashboard.db"

    def test_events_dir_none(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.events_dir is None

    def test_roster_dir_none(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.roster_dir is None

    def test_proposals_dir_none(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.proposals_dir is None

    def test_feature_names(self, sp_root: Path) -> None:
        p = SpeedPaths(sp_root)
        assert p.feature_names() == ["auth", "billing"]

    def test_feature_names_empty_when_no_features_dir(self, tmp_path: Path) -> None:
        """No .speed/features/ directory at all returns an empty list."""
        (tmp_path / ".speed").mkdir()
        p = SpeedPaths(tmp_path)
        assert p.feature_names() == []

    def test_feature_names_ignores_files(self, sp_root: Path) -> None:
        """Files inside features/ should not appear in the name list."""
        (sp_root / ".speed" / "features" / "README.md").write_text("")
        p = SpeedPaths(sp_root)
        assert p.feature_names() == ["auth", "billing"]


# ── Multiplayer mode ──────────────────────────────────────────────


class TestMultiplayer:
    """Paths split into .speed/shared/ and .speed/local/."""

    def test_mp_enabled(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.mp_enabled is True

    def test_features_dir(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.features_dir == mp_root / ".speed" / "shared" / "features"

    def test_local_features_dir(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.local_features_dir == mp_root / ".speed" / "local" / "features"

    def test_features_dir_differs_from_local(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.features_dir != p.local_features_dir

    def test_feature_shared(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.feature_shared("auth") == mp_root / ".speed" / "shared" / "features" / "auth"

    def test_feature_local(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.feature_local("auth") == mp_root / ".speed" / "local" / "features" / "auth"

    def test_memory_dir(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.memory_dir == mp_root / ".speed" / "shared" / "knowledge"

    def test_observations_dir(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.observations_dir == mp_root / ".speed" / "shared" / "knowledge" / "observations"

    def test_conventions_path(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.conventions_path == mp_root / ".speed" / "shared" / "knowledge" / "conventions.json"

    def test_defects_dir(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.defects_dir == mp_root / ".speed" / "shared" / "defects"

    def test_context_dir_unchanged(self, mp_root: Path) -> None:
        """Context dir stays at .speed/context/ regardless of mode."""
        p = SpeedPaths(mp_root)
        assert p.context_dir == mp_root / ".speed" / "context"

    def test_active_feature_path(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.active_feature_path == mp_root / ".speed" / "shared" / "active_feature"

    def test_db_path(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.db_path == mp_root / ".speed" / "local" / "dashboard.db"

    def test_events_dir(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.events_dir == mp_root / ".speed" / "shared" / "events"

    def test_roster_dir(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.roster_dir == mp_root / ".speed" / "shared" / "roster"

    def test_proposals_dir(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.proposals_dir == mp_root / ".speed" / "shared" / "proposals"

    def test_feature_names(self, mp_root: Path) -> None:
        p = SpeedPaths(mp_root)
        assert p.feature_names() == ["auth", "billing"]

    def test_feature_names_reads_shared_not_local(self, mp_root: Path) -> None:
        """feature_names() should enumerate shared/features/, not local/features/."""
        # Add a feature only to local -- it should NOT appear.
        (mp_root / ".speed" / "local" / "features" / "secret").mkdir(parents=True)
        p = SpeedPaths(mp_root)
        assert "secret" not in p.feature_names()


# ── get_paths() cache behavior ────────────────────────────────────


class TestGetPathsCache:
    """The module-level cache should reuse instances by project root."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        """Ensure each test starts with a clean cache."""
        _cache.clear()
        yield
        _cache.clear()

    def test_same_root_returns_same_instance(self, sp_root: Path) -> None:
        a = get_paths(sp_root)
        b = get_paths(sp_root)
        assert a is b

    def test_string_root_returns_same_as_path(self, sp_root: Path) -> None:
        a = get_paths(sp_root)
        b = get_paths(str(sp_root))
        assert a is b

    def test_different_roots_return_different_instances(self, tmp_path: Path) -> None:
        root_a = tmp_path / "project_a"
        root_b = tmp_path / "project_b"
        (root_a / ".speed").mkdir(parents=True)
        (root_b / ".speed").mkdir(parents=True)
        a = get_paths(root_a)
        b = get_paths(root_b)
        assert a is not b

    def test_cached_instance_is_SpeedPaths(self, sp_root: Path) -> None:
        p = get_paths(sp_root)
        assert isinstance(p, SpeedPaths)
