"""Integration tests for dashboard/backend/resolvers/ceremony_commitment.py.

These tests exercise commit_spec + submit_ratification end-to-end at the
resolver layer (direct Python calls, no GraphQL). They cover:

- O1: PM claims PRD, edits, commits; ceremony advances
- O8: committer cannot ratify own spec; another actor can
- O10: sole actor flow — commit writes ratification inline with
  source: "no-eligible-ratifier"

The tests stub out the ceremony_generator / ceremony_validator layers
that depend on the mistune markdown parser (unavailable in this env),
so the resolver logic is tested in isolation.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.paths import get_paths
from backend.resolvers.ceremony_types import (
    CeremonyState,
    CeremonyStatus,
    Revision,
    SpecClaim,
    ValidationState,
    _ceremony_state_to_dict,
    _reset_actor_cache,
    _write_json,
    save_spec_claim,
)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path, monkeypatch):
    from backend import paths as paths_module
    paths_module._cache.clear()
    _reset_actor_cache()
    monkeypatch.setenv("SPEED_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("TOML_MULTIPLAYER_STALE_WINDOW", raising=False)
    yield
    paths_module._cache.clear()
    _reset_actor_cache()


def _bootstrap_ceremony(
    tmp_path: Path,
    feature: str,
    author: str,
    author_email: str,
    mp: bool = False,
) -> None:
    """Write ceremony.json in DRAFTING state and create the feature dir."""
    base = (
        tmp_path / ".speed" / "shared" / "features" / feature
        if mp
        else tmp_path / ".speed" / "features" / feature
    )
    base.mkdir(parents=True, exist_ok=True)
    if mp:
        (tmp_path / ".speed" / "shared").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".speed" / "shared" / "roster").mkdir(parents=True, exist_ok=True)

    rev_id = "rev0001"
    now = datetime.now(timezone.utc).isoformat()
    state = CeremonyState(
        feature_name=feature,
        author=author,
        author_email=author_email,
        created_at=now,
        is_multiplayer=mp,
        current_revision=rev_id,
        revision_count=1,
        revisions={
            rev_id: Revision(
                revision_id=rev_id,
                parent_id=None,
                status=CeremonyStatus.DRAFTING,
                spec_content_hash="a" * 64,
                context_package_hash="b" * 64,
                validation_hash="c" * 64,
                created_at=now,
                reason="initial",
            )
        },
        reflog=[],
    )
    _write_json(base / "ceremony.json", _ceremony_state_to_dict(state))


def _write_draft_file(
    tmp_path: Path, feature: str, spec_type: str, content: str = "draft body"
) -> Path:
    """Create a draft-{spec_type}.json on disk. Returns path."""
    feature_dir = tmp_path / ".speed" / "features" / feature
    feature_dir.mkdir(parents=True, exist_ok=True)
    path = feature_dir / f"draft-{spec_type}.json"
    _write_json(path, {"content": content, "file_path": f"specs/product/{feature}.md"})
    return path


def _prewrite_claim(
    tmp_path: Path, feature: str, spec_type: str,
    claimant: str, claimant_email: str,
) -> None:
    paths = get_paths(tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    save_spec_claim(
        paths.ceremony_claim(feature, spec_type),
        SpecClaim(
            spec_type=spec_type,
            claimant=claimant,
            claimant_email=claimant_email,
            claimed_at=now,
            last_activity_at=now,
            released_at=None,
        ),
    )


def _add_roster_member(tmp_path: Path, name: str, email: str) -> None:
    roster_dir = tmp_path / ".speed" / "shared" / "roster"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / f"{name}.json").write_text(
        json.dumps({"name": name, "email": email}) + "\n"
    )


@pytest.fixture
def stub_ceremony_modules():
    """Stub out ceremony_generator and ceremony_validator imports.

    These modules transitively import mistune, which isn't installed in
    this env. We stub them so the commit flow can be tested in isolation.
    """

    mock_draft = MagicMock()
    mock_draft.content = "stubbed draft content"
    mock_draft.file_path = "specs/product/test-feature.md"

    with patch(
        "backend.ceremony_generator.load_spec_draft",
        return_value=mock_draft,
    ), patch(
        "backend.ceremony_validator.load_validation_state",
        return_value=None,
    ):
        yield


# ── O1: Claimant commits, ceremony advances ──────────────────────


class TestCommitSpecSingleActor:
    """Sole-actor (roster size 1) flow — covers O10."""

    def test_commit_writes_per_spec_files(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        _bootstrap_ceremony(
            tmp_path, "test-feature", "Sanjay", "sanjay@example.com", mp=False,
        )
        _prewrite_claim(
            tmp_path, "test-feature", "prd", "Sanjay", "sanjay@example.com",
        )
        _write_draft_file(tmp_path, "test-feature", "prd")

        with patch(
            "backend.resolvers.ceremony_commitment.get_current_actor",
            return_value=("Sanjay", "sanjay@example.com"),
        ), patch(
            "backend.resolvers.ceremony_types.get_current_actor",
            return_value=("Sanjay", "sanjay@example.com"),
        ), patch(
            "backend.resolvers.ceremony_authz.get_current_actor",
            return_value=("Sanjay", "sanjay@example.com"),
        ):
            from backend.resolvers.ceremony_commitment import commit_spec

            record = commit_spec(tmp_path, "test-feature", "prd")

        paths = get_paths(tmp_path)
        # commit-prd.json exists with the new shape.
        commit_data = json.loads(
            paths.ceremony_commit_record("test-feature", "prd").read_text()
        )
        assert commit_data["spec_type"] == "prd"
        assert commit_data["claimant_email"] == "sanjay@example.com"
        assert "spec_path" in commit_data
        assert "author" not in commit_data  # no legacy field leaked through

        # Claim was retired, not deleted.
        claim_data = json.loads(
            paths.ceremony_claim("test-feature", "prd").read_text()
        )
        assert claim_data["released_at"] is not None

        # Inline auto-ratification wrote ratification-prd.json.
        ratification_data = json.loads(
            paths.ceremony_ratification("test-feature", "prd").read_text()
        )
        assert ratification_data["ratified"] is True
        assert ratification_data["source"] == "no-eligible-ratifier"
        assert ratification_data["verdicts"] == []

        # Return value has the new shape.
        assert record.claimant_email == "sanjay@example.com"
        assert record.spec_type == "prd"
        assert record.ratification_status == "ratified"

    def test_non_claimant_commit_is_rejected(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        _bootstrap_ceremony(
            tmp_path, "test-feature", "Sanjay", "sanjay@example.com", mp=False,
        )
        _prewrite_claim(
            tmp_path, "test-feature", "prd", "Sanjay", "sanjay@example.com",
        )
        _write_draft_file(tmp_path, "test-feature", "prd")

        # Priya tries to commit Sanjay's PRD.
        with patch(
            "backend.resolvers.ceremony_commitment.get_current_actor",
            return_value=("Priya", "priya@example.com"),
        ), patch(
            "backend.resolvers.ceremony_types.get_current_actor",
            return_value=("Priya", "priya@example.com"),
        ), patch(
            "backend.resolvers.ceremony_authz.get_current_actor",
            return_value=("Priya", "priya@example.com"),
        ):
            from backend.resolvers.ceremony_commitment import commit_spec

            with pytest.raises(PermissionError):
                commit_spec(tmp_path, "test-feature", "prd")


# ── O8: Committer cannot ratify own spec ─────────────────────────


class TestSubmitRatification:
    """Multi-actor flow with explicit submitRatification calls."""

    def test_committer_cannot_ratify_own_spec(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        """Regression for the original Issue 1 loophole."""
        _bootstrap_ceremony(
            tmp_path, "test-feature", "Sanjay", "sanjay@example.com", mp=True,
        )
        _add_roster_member(tmp_path, "sanjay", "sanjay@example.com")
        _add_roster_member(tmp_path, "priya", "priya@example.com")

        # Seed a committed PRD by Sanjay directly (skipping commit_spec
        # because we just need the commit-prd.json file on disk).
        paths = get_paths(tmp_path)
        commit_data = {
            "feature_name": "test-feature",
            "spec_type": "prd",
            "revision_id": "rev0001",
            "claimant": "Sanjay",
            "claimant_email": "sanjay@example.com",
            "committed_at": "2026-04-11T10:00:00+00:00",
            "validation_state_ref": "abc123",
            "context_package_ref": "",
            "suggestion_history": {"received": 0, "accepted": 0, "dismissed": {"count": 0, "reasons": []}},
            "spec_path": "specs/product/test-feature.md",
            "decomposition_ref": None,
            "is_multiplayer": True,
            "ratification_threshold": 1,
            "ratification_status": "pending",
        }
        _write_json(
            paths.ceremony_commit_record("test-feature", "prd"),
            commit_data,
        )

        # Sanjay tries to ratify his own commit. Should be rejected.
        with patch(
            "backend.resolvers.ceremony_commitment.get_current_actor",
            return_value=("Sanjay", "sanjay@example.com"),
        ), patch(
            "backend.resolvers.ceremony_types.get_current_actor",
            return_value=("Sanjay", "sanjay@example.com"),
        ), patch(
            "backend.resolvers.ceremony_authz.get_current_actor",
            return_value=("Sanjay", "sanjay@example.com"),
        ):
            from backend.resolvers.ceremony_commitment import submit_ratification

            with pytest.raises(PermissionError, match="cannot ratify own spec"):
                submit_ratification(
                    tmp_path, "test-feature", "prd", "approve"
                )

    def test_non_author_can_ratify(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        _bootstrap_ceremony(
            tmp_path, "test-feature", "Sanjay", "sanjay@example.com", mp=True,
        )
        _add_roster_member(tmp_path, "sanjay", "sanjay@example.com")
        _add_roster_member(tmp_path, "priya", "priya@example.com")
        _write_draft_file(tmp_path, "test-feature", "prd")

        # Mark the draft as committed under MP layout.
        paths = get_paths(tmp_path)
        mp_feature_dir = tmp_path / ".speed" / "shared" / "features" / "test-feature"
        (mp_feature_dir / "draft-prd.json").write_text(
            json.dumps({"content": "stubbed", "file_path": "specs/product/test-feature.md"})
        )
        commit_data = {
            "feature_name": "test-feature",
            "spec_type": "prd",
            "revision_id": "rev0001",
            "claimant": "Sanjay",
            "claimant_email": "sanjay@example.com",
            "committed_at": "2026-04-11T10:00:00+00:00",
            "validation_state_ref": "abc123",
            "context_package_ref": "",
            "suggestion_history": {"received": 0, "accepted": 0, "dismissed": {"count": 0, "reasons": []}},
            "spec_path": "specs/product/test-feature.md",
            "decomposition_ref": None,
            "is_multiplayer": True,
            "ratification_threshold": 1,
            "ratification_status": "pending",
        }
        _write_json(
            paths.ceremony_commit_record("test-feature", "prd"),
            commit_data,
        )
        # Also mark COMMITTED in ceremony state so RATIFIED transition is valid.
        state_path = paths.ceremony_state("test-feature")
        state_data = json.loads(state_path.read_text())
        state_data["revisions"]["rev0001"]["status"] = "committed"
        state_path.write_text(json.dumps(state_data, indent=2))

        # Priya ratifies. Should succeed and flip ratification to ratified.
        with patch(
            "backend.resolvers.ceremony_commitment.get_current_actor",
            return_value=("Priya", "priya@example.com"),
        ), patch(
            "backend.resolvers.ceremony_types.get_current_actor",
            return_value=("Priya", "priya@example.com"),
        ), patch(
            "backend.resolvers.ceremony_authz.get_current_actor",
            return_value=("Priya", "priya@example.com"),
        ):
            from backend.resolvers.ceremony_commitment import submit_ratification

            state = submit_ratification(
                tmp_path, "test-feature", "prd", "approve"
            )

        assert state.status == "ratified"
        # ratification-prd.json on disk has the verdict.
        ratification_data = json.loads(
            paths.ceremony_ratification("test-feature", "prd").read_text()
        )
        assert ratification_data["ratified"] is True
        assert ratification_data["source"] == "threshold-met"
        assert len(ratification_data["verdicts"]) == 1
        assert ratification_data["verdicts"][0]["actor_email"] == "priya@example.com"
