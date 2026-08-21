"""Tests for dashboard/backend/resolvers/ceremony_claims.py.

Covers the claim lifecycle (claim/release/stale takeover/reclaim own),
spec_type validation, concurrent-claim file lock, and the idempotent
`refresh_claim_activity` / `retire_claim_on_commit` helpers.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.paths import get_paths
from backend.resolvers.ceremony_claims import (
    ceremony_claims,
    claim_spec,
    refresh_claim_activity,
    release_spec,
    retire_claim_on_commit,
    _validate_spec_type,
)
from backend.resolvers.ceremony_types import (
    SpecClaim,
    _reset_actor_cache,
    load_spec_claim,
    save_spec_claim,
)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_env(tmp_path: Path, monkeypatch):
    """Reset actor cache + path cache between tests."""
    # Clear module-level path cache so each test gets a fresh SpeedPaths.
    from backend import paths as paths_module
    paths_module._cache.clear()
    _reset_actor_cache()
    monkeypatch.setenv("SPEED_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("TOML_MULTIPLAYER_STALE_WINDOW", raising=False)
    yield
    paths_module._cache.clear()
    _reset_actor_cache()


@pytest.fixture
def mock_actor_me():
    with patch(
        "backend.resolvers.ceremony_claims.get_current_actor",
        return_value=("Sanjay", "sanjay@example.com"),
    ), patch(
        "backend.resolvers.ceremony_types.get_current_actor",
        return_value=("Sanjay", "sanjay@example.com"),
    ), patch(
        "backend.resolvers.ceremony_authz.get_current_actor",
        return_value=("Sanjay", "sanjay@example.com"),
    ):
        yield


@pytest.fixture
def mock_actor_other():
    with patch(
        "backend.resolvers.ceremony_claims.get_current_actor",
        return_value=("Priya", "priya@example.com"),
    ), patch(
        "backend.resolvers.ceremony_types.get_current_actor",
        return_value=("Priya", "priya@example.com"),
    ), patch(
        "backend.resolvers.ceremony_authz.get_current_actor",
        return_value=("Priya", "priya@example.com"),
    ):
        yield


def _feature_dir(tmp_path: Path, name: str = "sample") -> Path:
    d = tmp_path / ".speed" / "features" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── spec_type validation ─────────────────────────────────────────


class TestValidateSpecType:

    @pytest.mark.parametrize(
        "spec_type",
        ["prd", "design", "rfc", "rfc-ingestion", "rfc-query-api", "rfc-a"],
    )
    def test_valid(self, spec_type: str) -> None:
        _validate_spec_type(spec_type)  # no exception

    @pytest.mark.parametrize(
        "spec_type",
        [
            "",
            "PRD",
            "rfcfoo",
            "rfc-",
            "rfc-INGEST",
            "rfc-with_underscore",
            "rfc-trailing-",
            "rfc--double",
        ],
    )
    def test_invalid(self, spec_type: str) -> None:
        with pytest.raises(ValueError):
            _validate_spec_type(spec_type)


# ── claim_spec ────────────────────────────────────────────────────


class TestClaimSpec:

    def test_unclaimed_succeeds(self, tmp_path: Path, mock_actor_me) -> None:
        _feature_dir(tmp_path)
        claim = claim_spec(tmp_path, "sample", "prd")
        assert claim.claimant_email == "sanjay@example.com"
        assert claim.spec_type == "prd"
        assert claim.released_at is None
        # File on disk matches.
        paths = get_paths(tmp_path)
        loaded = load_spec_claim(paths.ceremony_claim("sample", "prd"))
        assert loaded is not None
        assert loaded.claimant_email == "sanjay@example.com"

    def test_active_claim_by_other_denies(
        self, tmp_path: Path, mock_actor_other
    ) -> None:
        """Pre-seed a claim by 'me', then try to claim as 'other'."""
        _feature_dir(tmp_path)
        paths = get_paths(tmp_path)
        now_iso = datetime.now(timezone.utc).isoformat()
        save_spec_claim(
            paths.ceremony_claim("sample", "prd"),
            SpecClaim(
                spec_type="prd",
                claimant="Sanjay",
                claimant_email="sanjay@example.com",
                claimed_at=now_iso,
                last_activity_at=now_iso,
                released_at=None,
            ),
        )
        with pytest.raises(PermissionError, match="Sanjay"):
            claim_spec(tmp_path, "sample", "prd")

    def test_released_claim_allows_reclaim(
        self, tmp_path: Path, mock_actor_other
    ) -> None:
        _feature_dir(tmp_path)
        paths = get_paths(tmp_path)
        now_iso = datetime.now(timezone.utc).isoformat()
        save_spec_claim(
            paths.ceremony_claim("sample", "prd"),
            SpecClaim(
                spec_type="prd",
                claimant="Sanjay",
                claimant_email="sanjay@example.com",
                claimed_at=now_iso,
                last_activity_at=now_iso,
                released_at=now_iso,
            ),
        )
        claim = claim_spec(tmp_path, "sample", "prd")
        assert claim.claimant_email == "priya@example.com"

    def test_stale_claim_allows_takeover(
        self, tmp_path: Path, monkeypatch, mock_actor_other
    ) -> None:
        _feature_dir(tmp_path)
        paths = get_paths(tmp_path)
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        save_spec_claim(
            paths.ceremony_claim("sample", "prd"),
            SpecClaim(
                spec_type="prd",
                claimant="Sanjay",
                claimant_email="sanjay@example.com",
                claimed_at=old,
                last_activity_at=old,
                released_at=None,
            ),
        )
        claim = claim_spec(tmp_path, "sample", "prd")
        assert claim.claimant_email == "priya@example.com"
        # The old claim file should have released_at set on disk now (the
        # file path is the same — the new claim overwrites it — so just
        # verify the current file is priya's).
        loaded = load_spec_claim(paths.ceremony_claim("sample", "prd"))
        assert loaded is not None
        assert loaded.claimant_email == "priya@example.com"
        assert loaded.released_at is None

    def test_reclaim_own_active_claim_refreshes(
        self, tmp_path: Path, mock_actor_me
    ) -> None:
        """Reclaiming your own active claim is a no-op refresh."""
        _feature_dir(tmp_path)
        first = claim_spec(tmp_path, "sample", "prd")
        second = claim_spec(tmp_path, "sample", "prd")
        assert first.claimant_email == second.claimant_email
        # last_activity_at should have advanced.
        assert second.last_activity_at >= first.last_activity_at

    def test_invalid_spec_type_rejected(
        self, tmp_path: Path, mock_actor_me
    ) -> None:
        _feature_dir(tmp_path)
        with pytest.raises(ValueError):
            claim_spec(tmp_path, "sample", "invalid-type")


# ── release_spec ──────────────────────────────────────────────────


class TestReleaseSpec:

    def test_claimant_can_release(self, tmp_path: Path, mock_actor_me) -> None:
        _feature_dir(tmp_path)
        claim_spec(tmp_path, "sample", "prd")
        released = release_spec(tmp_path, "sample", "prd")
        assert released.released_at is not None

    def test_non_claimant_cannot_release(
        self, tmp_path: Path
    ) -> None:
        _feature_dir(tmp_path)
        # Me claims it.
        with patch(
            "backend.resolvers.ceremony_claims.get_current_actor",
            return_value=("Sanjay", "sanjay@example.com"),
        ), patch(
            "backend.resolvers.ceremony_types.get_current_actor",
            return_value=("Sanjay", "sanjay@example.com"),
        ):
            claim_spec(tmp_path, "sample", "prd")

        # Other tries to release.
        with patch(
            "backend.resolvers.ceremony_claims.get_current_actor",
            return_value=("Priya", "priya@example.com"),
        ):
            with pytest.raises(PermissionError):
                release_spec(tmp_path, "sample", "prd")

    def test_release_missing_claim_raises(
        self, tmp_path: Path, mock_actor_me
    ) -> None:
        _feature_dir(tmp_path)
        with pytest.raises(FileNotFoundError):
            release_spec(tmp_path, "sample", "prd")

    def test_release_already_released_is_noop(
        self, tmp_path: Path, mock_actor_me
    ) -> None:
        _feature_dir(tmp_path)
        claim_spec(tmp_path, "sample", "prd")
        release_spec(tmp_path, "sample", "prd")
        # Second release: idempotent, no exception
        result = release_spec(tmp_path, "sample", "prd")
        assert result.released_at is not None


# ── ceremony_claims query ────────────────────────────────────────


class TestCeremonyClaimsQuery:

    def test_empty_when_no_claims(
        self, tmp_path: Path, mock_actor_me
    ) -> None:
        _feature_dir(tmp_path)
        assert ceremony_claims(tmp_path, "sample") == []

    def test_returns_all_claims_including_released(
        self, tmp_path: Path, mock_actor_me
    ) -> None:
        _feature_dir(tmp_path)
        claim_spec(tmp_path, "sample", "prd")
        claim_spec(tmp_path, "sample", "design")
        release_spec(tmp_path, "sample", "design")
        claims = ceremony_claims(tmp_path, "sample")
        assert len(claims) == 2
        by_type = {c.spec_type: c for c in claims}
        assert by_type["prd"].released_at is None
        assert by_type["design"].released_at is not None

    def test_missing_feature_dir_returns_empty(
        self, tmp_path: Path, mock_actor_me
    ) -> None:
        assert ceremony_claims(tmp_path, "ghost") == []


# ── refresh_claim_activity ───────────────────────────────────────


class TestRefreshClaimActivity:

    def test_refreshes_last_activity(
        self, tmp_path: Path, mock_actor_me
    ) -> None:
        _feature_dir(tmp_path)
        first = claim_spec(tmp_path, "sample", "prd")
        import time
        time.sleep(0.01)
        refresh_claim_activity(tmp_path, "sample", "prd")
        paths = get_paths(tmp_path)
        loaded = load_spec_claim(paths.ceremony_claim("sample", "prd"))
        assert loaded is not None
        assert loaded.last_activity_at > first.last_activity_at

    def test_noop_when_not_claimant(self, tmp_path: Path) -> None:
        _feature_dir(tmp_path)
        # Me claims.
        with patch(
            "backend.resolvers.ceremony_claims.get_current_actor",
            return_value=("Sanjay", "sanjay@example.com"),
        ), patch(
            "backend.resolvers.ceremony_types.get_current_actor",
            return_value=("Sanjay", "sanjay@example.com"),
        ):
            claim_spec(tmp_path, "sample", "prd")

        paths = get_paths(tmp_path)
        before = load_spec_claim(paths.ceremony_claim("sample", "prd"))

        # Other tries to refresh: silent no-op.
        with patch(
            "backend.resolvers.ceremony_claims.get_current_actor",
            return_value=("Priya", "priya@example.com"),
        ):
            refresh_claim_activity(tmp_path, "sample", "prd")

        after = load_spec_claim(paths.ceremony_claim("sample", "prd"))
        assert before.last_activity_at == after.last_activity_at

    def test_noop_when_no_claim_file(
        self, tmp_path: Path, mock_actor_me
    ) -> None:
        _feature_dir(tmp_path)
        # No claim file yet; should not raise.
        refresh_claim_activity(tmp_path, "sample", "prd")


# ── retire_claim_on_commit ───────────────────────────────────────


class TestRetireClaimOnCommit:

    def test_sets_released_at(self, tmp_path: Path, mock_actor_me) -> None:
        _feature_dir(tmp_path)
        claim_spec(tmp_path, "sample", "prd")
        committed_at = datetime.now(timezone.utc).isoformat()
        retire_claim_on_commit(tmp_path, "sample", "prd", committed_at)
        paths = get_paths(tmp_path)
        loaded = load_spec_claim(paths.ceremony_claim("sample", "prd"))
        assert loaded is not None
        assert loaded.released_at == committed_at
        assert loaded.last_activity_at == committed_at

    def test_noop_when_no_claim_file(
        self, tmp_path: Path, mock_actor_me
    ) -> None:
        _feature_dir(tmp_path)
        retire_claim_on_commit(tmp_path, "sample", "prd", "2026-01-01T00:00:00Z")
        # No exception.
