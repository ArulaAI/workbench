"""Tests for dashboard/backend/resolvers/ceremony_derive.py.

Covers `derive_transition_sets()` against fixture ceremony directories
and the `has_eligible_ratifier()` roster-side predicate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.resolvers.ceremony_derive import (
    derive_transition_sets,
    has_eligible_ratifier,
)


def _write(path: Path, content: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _feature_dir(tmp_path: Path, name: str = "sample") -> Path:
    # Single-player layout: .speed/features/{name}/
    return tmp_path / ".speed" / "features" / name


class TestDeriveTransitionSets:
    """Table tests over filesystem states the derivation must handle."""

    def test_empty_dir_returns_three_empty_sets(self, tmp_path: Path) -> None:
        _feature_dir(tmp_path).mkdir(parents=True)
        drafted, committed, ratified = derive_transition_sets(
            "sample", project_root=tmp_path
        )
        assert drafted == set()
        assert committed == set()
        assert ratified == set()

    def test_missing_dir_returns_three_empty_sets(self, tmp_path: Path) -> None:
        drafted, committed, ratified = derive_transition_sets(
            "ghost", project_root=tmp_path
        )
        assert drafted == set()
        assert committed == set()
        assert ratified == set()

    def test_drafted_from_draft_json_files(self, tmp_path: Path) -> None:
        d = _feature_dir(tmp_path)
        _write(d / "draft-prd.json", '{"content": "..."}')
        _write(d / "draft-design.json", '{"content": "..."}')
        _write(d / "draft-rfc.json", '{"content": "..."}')
        drafted, _, _ = derive_transition_sets("sample", project_root=tmp_path)
        assert drafted == {"prd", "design", "rfc"}

    def test_committed_from_commit_json_files(self, tmp_path: Path) -> None:
        d = _feature_dir(tmp_path)
        _write(d / "commit-prd.json", '{"claimant_email": "a@b.c"}')
        _write(d / "commit-rfc.json", '{"claimant_email": "a@b.c"}')
        _, committed, _ = derive_transition_sets("sample", project_root=tmp_path)
        assert committed == {"prd", "rfc"}

    def test_ratified_only_when_ratified_is_true(self, tmp_path: Path) -> None:
        d = _feature_dir(tmp_path)
        _write(d / "ratification-prd.json", json.dumps({"ratified": True}))
        _write(d / "ratification-design.json", json.dumps({"ratified": False}))
        _write(d / "ratification-rfc.json", json.dumps({"ratified": True}))
        _, _, ratified = derive_transition_sets("sample", project_root=tmp_path)
        assert ratified == {"prd", "rfc"}

    def test_malformed_ratification_json_does_not_count(self, tmp_path: Path) -> None:
        d = _feature_dir(tmp_path)
        _write(d / "ratification-prd.json", "{not valid json")
        _, _, ratified = derive_transition_sets("sample", project_root=tmp_path)
        assert ratified == set()

    def test_child_rfc_slots_are_first_class(self, tmp_path: Path) -> None:
        d = _feature_dir(tmp_path)
        _write(d / "draft-rfc-ingestion.json", '{}')
        _write(d / "draft-rfc-query.json", '{}')
        _write(d / "commit-rfc-ingestion.json", '{}')
        drafted, committed, _ = derive_transition_sets(
            "sample", project_root=tmp_path
        )
        assert drafted == {"rfc-ingestion", "rfc-query"}
        assert committed == {"rfc-ingestion"}

    def test_draft_without_commit_doesnt_mark_committed(self, tmp_path: Path) -> None:
        d = _feature_dir(tmp_path)
        _write(d / "draft-prd.json", '{}')
        drafted, committed, _ = derive_transition_sets(
            "sample", project_root=tmp_path
        )
        assert drafted == {"prd"}
        assert committed == set()

    def test_commit_without_ratification_doesnt_mark_ratified(
        self, tmp_path: Path
    ) -> None:
        d = _feature_dir(tmp_path)
        _write(d / "draft-prd.json", '{}')
        _write(d / "commit-prd.json", '{}')
        _, committed, ratified = derive_transition_sets(
            "sample", project_root=tmp_path
        )
        assert committed == {"prd"}
        assert ratified == set()

    def test_mixed_state_full_ceremony(self, tmp_path: Path) -> None:
        """PRD ratified, Design committed-pending-ratification, RFC drafting."""
        d = _feature_dir(tmp_path)
        _write(d / "draft-prd.json", '{}')
        _write(d / "draft-design.json", '{}')
        _write(d / "draft-rfc.json", '{}')
        _write(d / "commit-prd.json", '{}')
        _write(d / "commit-design.json", '{}')
        _write(d / "ratification-prd.json", json.dumps({"ratified": True}))
        _write(d / "ratification-design.json", json.dumps({"ratified": False}))

        drafted, committed, ratified = derive_transition_sets(
            "sample", project_root=tmp_path
        )
        assert drafted == {"prd", "design", "rfc"}
        assert committed == {"prd", "design"}
        assert ratified == {"prd"}


class TestHasEligibleRatifier:
    """Unit tests for the roster-side predicate used by commitSpec."""

    def test_empty_roster_returns_false(self) -> None:
        assert has_eligible_ratifier("a@x.com", []) is False

    def test_sole_member_is_commit_author_returns_false(self) -> None:
        assert has_eligible_ratifier("a@x.com", ["a@x.com"]) is False

    def test_sole_member_is_not_commit_author_returns_true(self) -> None:
        # Edge case: commit author has been removed from the roster.
        assert has_eligible_ratifier("a@x.com", ["b@x.com"]) is True

    def test_two_members_author_plus_one_returns_true(self) -> None:
        assert (
            has_eligible_ratifier("a@x.com", ["a@x.com", "b@x.com"]) is True
        )

    def test_many_members_all_non_author_returns_true(self) -> None:
        assert (
            has_eligible_ratifier(
                "a@x.com", ["b@x.com", "c@x.com", "d@x.com"]
            )
            is True
        )
