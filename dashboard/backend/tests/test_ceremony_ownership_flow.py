"""Integration tests for the per-spec ownership user stories.

Maps one-to-one to the RFC's acceptance criteria (stories O1-O10) in
specs/product/speed-define-ceremony-ownership.md.

These tests run at the resolver layer — direct Python calls into
ceremony_claims, ceremony_commitment, ceremony_suggestions — so they
exercise the real authz/derive/state-machine path without going through
GraphQL or HTTP. The ceremony_generator and ceremony_validator modules
(which depend on mistune) are stubbed the same way Phase 2's commitment
tests do, so the tests run against the ownership logic in isolation.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
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
    _ceremony_state_to_dict,
    _reset_actor_cache,
    _write_json,
    load_spec_claim,
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


SANJAY = ("Sanjay", "sanjay@example.com")
PRIYA = ("Priya", "priya@example.com")
ALEX = ("Alex", "alex@example.com")

ALL_ACTOR_MODULES = [
    "backend.resolvers.ceremony_claims.get_current_actor",
    "backend.resolvers.ceremony_types.get_current_actor",
    "backend.resolvers.ceremony_authz.get_current_actor",
    "backend.resolvers.ceremony_commitment.get_current_actor",
    "backend.resolvers.ceremony_suggestions.get_current_actor",
]


def as_actor(actor: tuple[str, str]):
    """Return a multi-module patch of get_current_actor across resolvers."""
    from contextlib import ExitStack

    class _Ctx:
        def __enter__(self):
            self.stack = ExitStack()
            for mod in ALL_ACTOR_MODULES:
                try:
                    self.stack.enter_context(patch(mod, return_value=actor))
                except AttributeError:
                    # Some resolvers don't import get_current_actor; skip.
                    pass
            return self

        def __exit__(self, *exc):
            self.stack.close()

    return _Ctx()


def _bootstrap_mp_ceremony(
    tmp_path: Path, feature: str, author_name: str, author_email: str,
    *, roster_emails: list[tuple[str, str]] | None = None,
) -> None:
    """Write a multiplayer ceremony + roster to disk."""
    base = tmp_path / ".speed" / "shared" / "features" / feature
    base.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".speed" / "shared").mkdir(parents=True, exist_ok=True)
    roster_dir = tmp_path / ".speed" / "shared" / "roster"
    roster_dir.mkdir(parents=True, exist_ok=True)

    for name, email in roster_emails or [(author_name, author_email)]:
        (roster_dir / f"{name.lower()}.json").write_text(
            json.dumps({"name": name, "email": email}) + "\n"
        )

    rev_id = "rev0001"
    now = datetime.now(timezone.utc).isoformat()
    state = CeremonyState(
        feature_name=feature,
        author=author_name,
        author_email=author_email,
        created_at=now,
        is_multiplayer=True,
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


def _write_draft(
    tmp_path: Path, feature: str, spec_type: str, content: str = "stub draft"
) -> None:
    base = tmp_path / ".speed" / "shared" / "features" / feature
    base.mkdir(parents=True, exist_ok=True)
    _write_json(
        base / f"draft-{spec_type}.json",
        {
            "content": content,
            "file_path": f"specs/product/{feature}.md",
            "feature_name": feature,
            "spec_type": spec_type,
        },
    )


@pytest.fixture
def stub_ceremony_modules():
    """Stub ceremony_generator + ceremony_validator (mistune-dependent)."""
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


# ── O1: PM claims PRD and commits independently ─────────────────


class TestO1_PMClaimsPRD:
    """PM claims PRD tab, edits, resolves suggestions, commits — all
    without affecting sibling specs."""

    def test_claim_then_commit_succeeds(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA],
        )
        _write_draft(tmp_path, "user-ingestion", "prd")

        with as_actor(SANJAY):
            from backend.resolvers.ceremony_claims import claim_spec
            from backend.resolvers.ceremony_commitment import commit_spec

            claim = claim_spec(tmp_path, "user-ingestion", "prd")
            assert claim.claimant_email == SANJAY[1]

            record = commit_spec(tmp_path, "user-ingestion", "prd")
            assert record.claimant_email == SANJAY[1]
            assert record.spec_type == "prd"

    def test_non_claimant_cannot_edit(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA],
        )
        _write_draft(tmp_path, "user-ingestion", "prd")

        with as_actor(SANJAY):
            from backend.resolvers.ceremony_claims import claim_spec
            claim_spec(tmp_path, "user-ingestion", "prd")

        # Priya cannot commit Sanjay's PRD.
        with as_actor(PRIYA):
            from backend.resolvers.ceremony_commitment import commit_spec
            with pytest.raises(PermissionError):
                commit_spec(tmp_path, "user-ingestion", "prd")


# ── O2, O3: Parallel claims on sibling specs ────────────────────


class TestO2_ParallelDesignClaim:
    """Given PRD claimed by PM, Designer can claim Design independently."""

    def test_claims_coexist_with_independent_clocks(
        self, tmp_path: Path
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA, ALEX],
        )

        from backend.resolvers.ceremony_claims import claim_spec, ceremony_claims

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")

        with as_actor(PRIYA):
            claim_spec(tmp_path, "user-ingestion", "design")

        claims = ceremony_claims(tmp_path, "user-ingestion")
        by_type = {c.spec_type: c for c in claims}
        assert by_type["prd"].claimant_email == SANJAY[1]
        assert by_type["design"].claimant_email == PRIYA[1]
        assert by_type["prd"].released_at is None
        assert by_type["design"].released_at is None
        # Independent clocks: each claim has its own last_activity_at.
        assert by_type["prd"].claimed_at != by_type["design"].claimed_at or \
               by_type["prd"].last_activity_at != by_type["design"].last_activity_at


class TestO3_ParallelRFCClaim:
    """Engineer claims RFC while PM is still drafting the PRD."""

    def test_rfc_claimable_with_prd_drafting(
        self, tmp_path: Path
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA, ALEX],
        )
        _write_draft(tmp_path, "user-ingestion", "prd")

        from backend.resolvers.ceremony_claims import claim_spec

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")

        # Alex claims RFC in parallel. PRD is still drafting.
        with as_actor(ALEX):
            rfc_claim = claim_spec(tmp_path, "user-ingestion", "rfc")
            assert rfc_claim.claimant_email == ALEX[1]

        # PRD claim is unaffected.
        from backend.resolvers.ceremony_claims import ceremony_claims
        claims = ceremony_claims(tmp_path, "user-ingestion")
        by_type = {c.spec_type: c for c in claims}
        assert by_type["prd"].claimant_email == SANJAY[1]


# ── O4: Non-claimant leaves a suggestion ────────────────────────


class TestO4_NonClaimantSuggestions:
    """Any roster member who is NOT the active claimant can leave a
    suggestion on that spec; the claimant cannot suggest on their own
    work."""

    def test_non_claimant_can_create_suggestion(
        self, tmp_path: Path
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA],
        )

        from backend.resolvers.ceremony_claims import claim_spec
        from backend.resolvers.ceremony_suggestions import create_suggestion

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")

        with as_actor(PRIYA):
            suggestion = create_suggestion(
                tmp_path,
                "user-ingestion",
                "prd",
                "user-stories",
                "User Stories",
                "Add acceptance criterion for null accessedAt rows",
            )
            assert suggestion.spec_type == "prd"
            assert suggestion.author_email == PRIYA[1]
            assert suggestion.status == "unresolved"

    def test_claimant_cannot_suggest_on_own_spec(
        self, tmp_path: Path
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA],
        )

        from backend.resolvers.ceremony_claims import claim_spec
        from backend.resolvers.ceremony_suggestions import create_suggestion

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")
            with pytest.raises(PermissionError):
                create_suggestion(
                    tmp_path, "user-ingestion", "prd",
                    "user-stories", "User Stories", "cannot suggest on my own",
                )


# ── O5: Claimant resolves suggestion ────────────────────────────


class TestO5_ClaimantResolvesSuggestion:
    """Claimant resolves a suggestion routed by its spec_type; a
    non-claimant attempt is denied."""

    def test_claimant_can_resolve_own_spec_suggestion(
        self, tmp_path: Path
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA],
        )

        from backend.resolvers.ceremony_claims import claim_spec
        from backend.resolvers.ceremony_suggestions import (
            create_suggestion,
            resolve_suggestion,
        )

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")

        with as_actor(PRIYA):
            suggestion = create_suggestion(
                tmp_path, "user-ingestion", "prd",
                "user-stories", "User Stories", "add acceptance",
            )

        with as_actor(SANJAY):
            resolved = resolve_suggestion(
                tmp_path, "user-ingestion", suggestion.id, "accept",
            )
            assert resolved.status == "accepted"
            assert resolved.resolution is not None
            assert resolved.resolution.resolved_by_email == SANJAY[1]

    def test_non_claimant_cannot_resolve(
        self, tmp_path: Path
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA, ALEX],
        )

        from backend.resolvers.ceremony_claims import claim_spec
        from backend.resolvers.ceremony_suggestions import (
            create_suggestion,
            resolve_suggestion,
        )

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")

        with as_actor(PRIYA):
            suggestion = create_suggestion(
                tmp_path, "user-ingestion", "prd",
                "scope", "Scope", "out of scope",
            )

        # Alex (non-claimant of PRD) cannot resolve.
        with as_actor(ALEX):
            with pytest.raises(PermissionError):
                resolve_suggestion(
                    tmp_path, "user-ingestion", suggestion.id, "accept",
                )


# ── O6: Independent decompose + commit ──────────────────────────


class TestO6_IndependentCommit:
    """Committing one spec does not advance sibling specs; the ceremony
    stays DRAFTING until every drafted spec has a commit record."""

    def test_committing_prd_leaves_rfc_drafting(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA],
        )
        _write_draft(tmp_path, "user-ingestion", "prd")
        _write_draft(tmp_path, "user-ingestion", "rfc")

        from backend.resolvers.ceremony_claims import claim_spec
        from backend.resolvers.ceremony_commitment import commit_spec

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")
            claim_spec(tmp_path, "user-ingestion", "rfc")
            commit_spec(tmp_path, "user-ingestion", "prd")

        # Ceremony state should still be DRAFTING because RFC is not
        # yet committed.
        paths = get_paths(tmp_path)
        state_data = json.loads(
            paths.ceremony_state("user-ingestion").read_text()
        )
        rev = list(state_data["revisions"].values())[0]
        assert rev["status"] == "drafting"

        # After committing RFC too, ceremony advances to COMMITTED.
        with as_actor(SANJAY):
            commit_spec(tmp_path, "user-ingestion", "rfc")
        state_data = json.loads(
            paths.ceremony_state("user-ingestion").read_text()
        )
        rev = list(state_data["revisions"].values())[0]
        # Multi-actor roster so ratification is pending, but commit
        # transition happens regardless — we check either committed or
        # ratified, depending on whether another ratifier was reachable.
        assert rev["status"] in ("committed", "ratified")

    def test_decompose_rejected_on_prd(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY],
        )
        _write_draft(tmp_path, "user-ingestion", "prd")

        with as_actor(SANJAY):
            from backend.resolvers.ceremony_claims import claim_spec
            claim_spec(tmp_path, "user-ingestion", "prd")

            # Decomposing PRD is a role violation even when you are the
            # claimant — only RFC slots decompose.
            from backend.resolvers.ceremony_authz import CeremonyAbility
            ability = CeremonyAbility.for_request(
                "user-ingestion", "prd", project_root=tmp_path,
            )
            assert ability.can("decompose", "prd") is False


# ── O7: Progress overview ───────────────────────────────────────


class TestO7_ProgressOverview:
    """ceremonyClaims returns every claim file on disk (including
    released ones); derive_transition_sets returns derived sets
    consistent with the per-spec files."""

    def test_all_claims_visible_including_released(
        self, tmp_path: Path
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA],
        )

        from backend.resolvers.ceremony_claims import (
            ceremony_claims,
            claim_spec,
            release_spec,
        )

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")
            claim_spec(tmp_path, "user-ingestion", "design")
            release_spec(tmp_path, "user-ingestion", "design")

        claims = ceremony_claims(tmp_path, "user-ingestion")
        assert len(claims) == 2
        by_type = {c.spec_type: c for c in claims}
        assert by_type["prd"].released_at is None
        assert by_type["design"].released_at is not None

    def test_derive_sets_match_filesystem(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY],
        )
        _write_draft(tmp_path, "user-ingestion", "prd")
        _write_draft(tmp_path, "user-ingestion", "design")
        _write_draft(tmp_path, "user-ingestion", "rfc")

        with as_actor(SANJAY):
            from backend.resolvers.ceremony_claims import claim_spec
            from backend.resolvers.ceremony_commitment import commit_spec

            claim_spec(tmp_path, "user-ingestion", "prd")
            claim_spec(tmp_path, "user-ingestion", "design")
            claim_spec(tmp_path, "user-ingestion", "rfc")

            commit_spec(tmp_path, "user-ingestion", "prd")
            commit_spec(tmp_path, "user-ingestion", "design")

        from backend.resolvers.ceremony_derive import derive_transition_sets
        drafted, committed, ratified = derive_transition_sets(
            "user-ingestion", project_root=tmp_path,
        )
        assert drafted == {"prd", "design", "rfc"}
        assert committed == {"prd", "design"}
        # Sole actor: committed specs auto-ratify.
        assert ratified == {"prd", "design"}


# ── O8: Independent ratification ────────────────────────────────


class TestO8_IndependentRatification:
    """PRD can ratify while RFC is still drafting. Committer cannot
    ratify their own spec."""

    def test_multi_spec_ceremony_ratifies_prd_independently(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA],
        )
        _write_draft(tmp_path, "user-ingestion", "prd")
        _write_draft(tmp_path, "user-ingestion", "rfc")

        from backend.resolvers.ceremony_claims import claim_spec
        from backend.resolvers.ceremony_commitment import (
            commit_spec,
            submit_ratification,
        )

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")
            commit_spec(tmp_path, "user-ingestion", "prd")

        # Priya (non-author) ratifies the PRD.
        with as_actor(PRIYA):
            state = submit_ratification(
                tmp_path, "user-ingestion", "prd", "approve",
            )
            assert state.status == "ratified"

        # Ceremony hasn't advanced to RATIFIED because RFC isn't drafted-
        # committed-ratified yet.
        paths = get_paths(tmp_path)
        state_data = json.loads(
            paths.ceremony_state("user-ingestion").read_text()
        )
        rev = list(state_data["revisions"].values())[0]
        assert rev["status"] == "drafting"

    def test_committer_cannot_ratify_own_spec(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA],
        )
        _write_draft(tmp_path, "user-ingestion", "prd")

        from backend.resolvers.ceremony_claims import claim_spec
        from backend.resolvers.ceremony_commitment import (
            commit_spec,
            submit_ratification,
        )

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")
            commit_spec(tmp_path, "user-ingestion", "prd")

            with pytest.raises(PermissionError, match="cannot ratify own spec"):
                submit_ratification(
                    tmp_path, "user-ingestion", "prd", "approve",
                )


# ── O9: Stale takeover ──────────────────────────────────────────


class TestO9_StaleTakeover:
    """A claim older than `stale_window` can be taken over by any roster
    member in a single claimSpec call."""

    def test_stale_claim_taken_over(
        self, tmp_path: Path
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA],
        )

        # Seed a stale claim (2 hours old, window is 1 hour).
        paths = get_paths(tmp_path)
        stale_iso = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()
        save_spec_claim(
            paths.ceremony_claim("user-ingestion", "prd"),
            SpecClaim(
                spec_type="prd",
                claimant=SANJAY[0],
                claimant_email=SANJAY[1],
                claimed_at=stale_iso,
                last_activity_at=stale_iso,
                released_at=None,
            ),
        )

        from backend.resolvers.ceremony_claims import claim_spec

        with as_actor(PRIYA):
            new_claim = claim_spec(tmp_path, "user-ingestion", "prd")
            assert new_claim.claimant_email == PRIYA[1]
            assert new_claim.released_at is None

        # Verify the file on disk is now Priya's active claim.
        loaded = load_spec_claim(
            paths.ceremony_claim("user-ingestion", "prd")
        )
        assert loaded is not None
        assert loaded.claimant_email == PRIYA[1]


# ── O10: Sole actor uses the same flow ──────────────────────────


class TestO10_SoleActor:
    """Single-member roster uses the same tab bar + progress overview +
    commit bar as a multi-actor ceremony. Commits auto-ratify inline
    via the no-eligible-ratifier branch."""

    def test_sole_actor_full_flow(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY],
        )
        _write_draft(tmp_path, "user-ingestion", "prd")
        _write_draft(tmp_path, "user-ingestion", "design")
        _write_draft(tmp_path, "user-ingestion", "rfc")

        from backend.resolvers.ceremony_claims import claim_spec
        from backend.resolvers.ceremony_commitment import commit_spec

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")
            claim_spec(tmp_path, "user-ingestion", "design")
            claim_spec(tmp_path, "user-ingestion", "rfc")

            commit_spec(tmp_path, "user-ingestion", "prd")
            commit_spec(tmp_path, "user-ingestion", "design")
            commit_spec(tmp_path, "user-ingestion", "rfc")

        # Every spec has a ratification file with the inline source.
        paths = get_paths(tmp_path)
        for spec_type in ("prd", "design", "rfc"):
            ratification_path = paths.ceremony_ratification(
                "user-ingestion", spec_type,
            )
            assert ratification_path.exists()
            data = json.loads(ratification_path.read_text())
            assert data["ratified"] is True
            assert data["source"] == "no-eligible-ratifier"
            assert data["verdicts"] == []

        # Ceremony advanced all the way to RATIFIED.
        state_data = json.loads(
            paths.ceremony_state("user-ingestion").read_text()
        )
        rev = list(state_data["revisions"].values())[0]
        assert rev["status"] == "ratified"

    def test_non_author_departs_mid_ceremony(
        self, tmp_path: Path, stub_ceremony_modules
    ) -> None:
        """Edge case from the RFC: multi-member roster loses every
        non-author between commit and ratify — inline auto-ratify
        should still fire because no eligible ratifier exists."""
        _bootstrap_mp_ceremony(
            tmp_path, "user-ingestion", *SANJAY,
            roster_emails=[SANJAY, PRIYA],
        )
        _write_draft(tmp_path, "user-ingestion", "prd")

        from backend.resolvers.ceremony_claims import claim_spec
        from backend.resolvers.ceremony_commitment import commit_spec

        with as_actor(SANJAY):
            claim_spec(tmp_path, "user-ingestion", "prd")

        # Priya leaves the roster before commit.
        roster_dir = tmp_path / ".speed" / "shared" / "roster"
        (roster_dir / "priya.json").unlink()

        with as_actor(SANJAY):
            commit_spec(tmp_path, "user-ingestion", "prd")

        paths = get_paths(tmp_path)
        ratification_path = paths.ceremony_ratification(
            "user-ingestion", "prd",
        )
        data = json.loads(ratification_path.read_text())
        assert data["ratified"] is True
        assert data["source"] == "no-eligible-ratifier"
