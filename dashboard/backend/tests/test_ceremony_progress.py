"""Tests for get_ceremony_progress — the batched per-spec progress query.

Covers the query's composition from claim files + commit records +
ratification files across a ceremony directory in various states.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.paths import get_paths
from backend.resolvers.ceremony_commitment import get_ceremony_progress
from backend.resolvers.ceremony_types import (
    Ratification,
    SpecClaim,
    Verdict,
    _reset_actor_cache,
    _write_json,
    save_ratification,
    save_spec_claim,
)


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path, monkeypatch):
    from backend import paths as paths_module
    paths_module._cache.clear()
    _reset_actor_cache()
    monkeypatch.setenv("SPEED_PROJECT_ROOT", str(tmp_path))
    yield
    paths_module._cache.clear()
    _reset_actor_cache()


def _feature_dir(tmp_path: Path, feature: str = "sample") -> Path:
    d = tmp_path / ".speed" / "features" / feature
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_draft(tmp_path: Path, feature: str, spec_type: str) -> None:
    _write_json(
        _feature_dir(tmp_path, feature) / f"draft-{spec_type}.json",
        {"content": "stub", "file_path": f"specs/product/{feature}.md"},
    )


def _write_commit(
    tmp_path: Path, feature: str, spec_type: str,
    claimant: str, claimant_email: str,
) -> None:
    paths = get_paths(tmp_path)
    _write_json(
        paths.ceremony_commit_record(feature, spec_type),
        {
            "feature_name": feature,
            "spec_type": spec_type,
            "revision_id": "rev1",
            "claimant": claimant,
            "claimant_email": claimant_email,
            "committed_at": "2026-04-11T10:00:00+00:00",
            "validation_state_ref": "abc",
            "context_package_ref": "",
            "suggestion_history": {"received": 0, "accepted": 0, "dismissed": {"count": 0, "reasons": []}},
            "spec_path": f"specs/product/{feature}.md",
            "decomposition_ref": None,
            "is_multiplayer": False,
            "ratification_threshold": 1,
            "ratification_status": "pending",
        },
    )


@pytest.fixture
def patch_actor():
    def _wrap(name: str, email: str):
        from contextlib import ExitStack
        stack = ExitStack()
        for mod in (
            "backend.resolvers.ceremony_commitment.get_current_actor",
            "backend.resolvers.ceremony_types.get_current_actor",
        ):
            stack.enter_context(patch(mod, return_value=(name, email)))
        return stack
    return _wrap


class TestGetCeremonyProgress:

    def test_empty_dir_returns_empty_list(self, tmp_path: Path, patch_actor) -> None:
        _feature_dir(tmp_path)
        with patch_actor("Sanjay", "sanjay@example.com"):
            assert get_ceremony_progress(tmp_path, "sample") == []

    def test_missing_dir_returns_empty_list(self, tmp_path: Path, patch_actor) -> None:
        with patch_actor("Sanjay", "sanjay@example.com"):
            assert get_ceremony_progress(tmp_path, "ghost") == []

    def test_row_per_drafted_spec(self, tmp_path: Path, patch_actor) -> None:
        _write_draft(tmp_path, "sample", "prd")
        _write_draft(tmp_path, "sample", "design")
        _write_draft(tmp_path, "sample", "rfc")

        with patch_actor("Sanjay", "sanjay@example.com"):
            rows = get_ceremony_progress(tmp_path, "sample")

        assert [r.spec_type for r in rows] == ["design", "prd", "rfc"]  # alphabetical
        for row in rows:
            assert row.claim is None
            assert row.has_commit is False
            assert row.has_ratification is False
            assert row.ratified is False
            assert row.has_voted is False

    def test_drafted_and_claimed(self, tmp_path: Path, patch_actor) -> None:
        _write_draft(tmp_path, "sample", "prd")
        paths = get_paths(tmp_path)
        now = datetime.now(timezone.utc).isoformat()
        save_spec_claim(
            paths.ceremony_claim("sample", "prd"),
            SpecClaim(
                spec_type="prd",
                claimant="Sanjay",
                claimant_email="sanjay@example.com",
                claimed_at=now,
                last_activity_at=now,
                released_at=None,
            ),
        )

        with patch_actor("Sanjay", "sanjay@example.com"):
            rows = get_ceremony_progress(tmp_path, "sample")

        assert len(rows) == 1
        assert rows[0].claim is not None
        assert rows[0].claim.claimant_email == "sanjay@example.com"
        assert rows[0].claim.released_at is None
        assert rows[0].has_commit is False

    def test_committed_spec_exposes_committer(self, tmp_path: Path, patch_actor) -> None:
        _write_draft(tmp_path, "sample", "prd")
        _write_commit(
            tmp_path, "sample", "prd", "Sanjay", "sanjay@example.com",
        )

        with patch_actor("Priya", "priya@example.com"):
            rows = get_ceremony_progress(tmp_path, "sample")

        assert rows[0].has_commit is True
        assert rows[0].committer == "Sanjay"
        assert rows[0].committer_email == "sanjay@example.com"

    def test_ratified_spec_reports_verdict_stats(self, tmp_path: Path, patch_actor) -> None:
        _write_draft(tmp_path, "sample", "prd")
        _write_commit(
            tmp_path, "sample", "prd", "Sanjay", "sanjay@example.com",
        )

        paths = get_paths(tmp_path)
        save_ratification(
            paths.ceremony_ratification("sample", "prd"),
            Ratification(
                spec_type="prd",
                revision_id="rev1",
                ratified=True,
                verdicts=[
                    Verdict(
                        actor="Priya",
                        actor_email="priya@example.com",
                        verdict="approve",
                        comment=None,
                        submitted_at="2026-04-11T10:01:00+00:00",
                    )
                ],
                source="threshold-met",
            ),
        )

        with patch_actor("Priya", "priya@example.com"):
            rows = get_ceremony_progress(tmp_path, "sample")

        assert rows[0].has_ratification is True
        assert rows[0].ratified is True
        assert rows[0].approval_count == 1
        assert rows[0].has_voted is True
        assert rows[0].has_rejection is False

    def test_rejection_verdict_counted(self, tmp_path: Path, patch_actor) -> None:
        _write_draft(tmp_path, "sample", "prd")
        _write_commit(
            tmp_path, "sample", "prd", "Sanjay", "sanjay@example.com",
        )
        paths = get_paths(tmp_path)
        save_ratification(
            paths.ceremony_ratification("sample", "prd"),
            Ratification(
                spec_type="prd",
                revision_id="rev1",
                ratified=False,
                verdicts=[
                    Verdict(
                        actor="Priya",
                        actor_email="priya@example.com",
                        verdict="reject",
                        comment="scope too broad",
                        submitted_at="2026-04-11T10:01:00+00:00",
                    )
                ],
                source="threshold-met",
            ),
        )

        with patch_actor("Alex", "alex@example.com"):
            rows = get_ceremony_progress(tmp_path, "sample")

        assert rows[0].has_rejection is True
        assert rows[0].ratified is False
        assert rows[0].has_voted is False  # Alex hasn't voted

    def test_has_voted_is_per_actor(self, tmp_path: Path, patch_actor) -> None:
        _write_draft(tmp_path, "sample", "prd")
        _write_commit(
            tmp_path, "sample", "prd", "Sanjay", "sanjay@example.com",
        )
        paths = get_paths(tmp_path)
        save_ratification(
            paths.ceremony_ratification("sample", "prd"),
            Ratification(
                spec_type="prd",
                revision_id="rev1",
                ratified=False,
                verdicts=[
                    Verdict(
                        actor="Alex",
                        actor_email="alex@example.com",
                        verdict="approve",
                        comment=None,
                        submitted_at="2026-04-11T10:01:00+00:00",
                    )
                ],
                source="threshold-met",
            ),
        )

        with patch_actor("Alex", "alex@example.com"):
            rows = get_ceremony_progress(tmp_path, "sample")
        assert rows[0].has_voted is True

        with patch_actor("Priya", "priya@example.com"):
            rows = get_ceremony_progress(tmp_path, "sample")
        assert rows[0].has_voted is False
