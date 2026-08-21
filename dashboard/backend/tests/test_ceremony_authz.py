"""Tests for dashboard/backend/resolvers/ceremony_authz.py.

One test per row of the Authorization Matrix in the RFC. The PDP is
constructed directly with synthetic facts so these tests exercise the
policy in isolation — no disk I/O, no GraphQL, no mutation code.

See: specs/tech/speed-define-ceremony-ownership.md § Authorization Model.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.resolvers.ceremony_authz import CeremonyAbility, _Actor
from backend.resolvers.ceremony_types import SpecClaim


# ── Test fixtures ─────────────────────────────────────────────────

ME = _Actor(name="Sanjay", email="sanjay@example.com")
OTHER = _Actor(name="Priya", email="priya@example.com")

NOW = datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc)
ONE_HOUR = 3600


def _claim(
    spec_type: str,
    *,
    claimant: _Actor = ME,
    age_seconds: int = 60,
    released: bool = False,
) -> SpecClaim:
    """Build a SpecClaim at an age of `age_seconds` before NOW."""
    last_activity = (NOW - timedelta(seconds=age_seconds)).isoformat()
    return SpecClaim(
        spec_type=spec_type,
        claimant=claimant.name,
        claimant_email=claimant.email,
        claimed_at=last_activity,
        last_activity_at=last_activity,
        released_at=last_activity if released else None,
    )


def _make_ability(
    *,
    actor: _Actor = ME,
    spec_type: str | None = "prd",
    claim: SpecClaim | None = None,
    commit_record: dict | None = None,
    roster_emails: list[str] | None = None,
) -> CeremonyAbility:
    """Construct a PDP directly without touching disk."""
    return CeremonyAbility(
        actor=actor,
        feature_name="test-feature",
        spec_type=spec_type,
        claim=claim,
        commit_record=commit_record,
        roster_emails=roster_emails or [actor.email],
        now=NOW,
        stale_window_seconds=ONE_HOUR,
    )


# ── Authorization Matrix ─────────────────────────────────────────
# Each test corresponds to one row in the matrix, plus positive and
# negative coverage for the "caller is/is not the claimant" axis.


class TestDeclareIntent:
    """Row: Declare intent (any roster member)."""

    def test_anyone_can_declare(self) -> None:
        a = _make_ability(spec_type=None)
        assert a.can("declare") is True


class TestClaim:
    """Row: Claim a spec (unclaimed or stale)."""

    def test_unclaimed_allows_claim(self) -> None:
        a = _make_ability(claim=None)
        assert a.can("claim", "prd") is True

    def test_released_claim_allows_reclaim(self) -> None:
        released = _claim("prd", released=True)
        a = _make_ability(claim=released)
        assert a.can("claim", "prd") is True

    def test_active_claim_by_other_denies(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=OTHER))
        assert a.can("claim", "prd") is False

    def test_stale_claim_allows_takeover(self) -> None:
        stale = _claim("prd", claimant=OTHER, age_seconds=ONE_HOUR + 60)
        a = _make_ability(claim=stale)
        assert a.can("claim", "prd") is True

    def test_own_active_claim_denies_reclaim(self) -> None:
        """Can't claim what you already actively hold."""
        a = _make_ability(claim=_claim("prd", claimant=ME))
        assert a.can("claim", "prd") is False


class TestRelease:
    """Row: Release own claim (claimant only)."""

    def test_active_claimant_can_release(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=ME))
        assert a.can("release", "prd") is True

    def test_non_claimant_cannot_release(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=OTHER))
        assert a.can("release", "prd") is False

    def test_cannot_release_unclaimed(self) -> None:
        a = _make_ability(claim=None)
        assert a.can("release", "prd") is False


class TestEdit:
    """Row: Edit a spec (claimant only)."""

    def test_active_claimant_can_edit(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=ME))
        assert a.can("edit", "prd") is True

    def test_non_claimant_cannot_edit(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=OTHER))
        assert a.can("edit", "prd") is False

    def test_unclaimed_spec_cannot_be_edited(self) -> None:
        a = _make_ability(claim=None)
        assert a.can("edit", "prd") is False

    def test_stale_own_claim_cannot_edit(self) -> None:
        stale = _claim("prd", claimant=ME, age_seconds=ONE_HOUR + 60)
        a = _make_ability(claim=stale)
        assert a.can("edit", "prd") is False


class TestSuggest:
    """Row: Create suggestion (not the claimant)."""

    def test_non_claimant_can_suggest(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=OTHER))
        assert a.can("suggest", "prd") is True

    def test_claimant_cannot_suggest_on_own_spec(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=ME))
        assert a.can("suggest", "prd") is False

    def test_unclaimed_allows_suggest(self) -> None:
        """Suggest is 'not claimant', and nobody is claimant for unclaimed."""
        a = _make_ability(claim=None)
        assert a.can("suggest", "prd") is True


class TestResolve:
    """Row: Resolve suggestion (claimant of the suggestion's spec)."""

    def test_active_claimant_can_resolve(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=ME))
        assert a.can("resolve", "prd") is True

    def test_non_claimant_cannot_resolve(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=OTHER))
        assert a.can("resolve", "prd") is False


class TestDecompose:
    """Row: Decompose (claimant AND rfc slot)."""

    def test_claimant_can_decompose_rfc(self) -> None:
        a = _make_ability(spec_type="rfc", claim=_claim("rfc", claimant=ME))
        assert a.can("decompose", "rfc") is True

    def test_claimant_can_decompose_child_rfc(self) -> None:
        a = _make_ability(
            spec_type="rfc-ingestion",
            claim=_claim("rfc-ingestion", claimant=ME),
        )
        assert a.can("decompose", "rfc-ingestion") is True

    def test_claimant_cannot_decompose_prd(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=ME))
        assert a.can("decompose", "prd") is False

    def test_claimant_cannot_decompose_design(self) -> None:
        a = _make_ability(
            spec_type="design", claim=_claim("design", claimant=ME)
        )
        assert a.can("decompose", "design") is False

    def test_non_claimant_cannot_decompose_rfc(self) -> None:
        a = _make_ability(spec_type="rfc", claim=_claim("rfc", claimant=OTHER))
        assert a.can("decompose", "rfc") is False


class TestCommit:
    """Row: Commit a spec (claimant)."""

    def test_active_claimant_can_commit(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=ME))
        assert a.can("commit", "prd") is True

    def test_non_claimant_cannot_commit(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=OTHER))
        assert a.can("commit", "prd") is False


class TestRatify:
    """Row: Ratify a spec (not the commit record's author)."""

    def test_non_author_can_ratify(self) -> None:
        record = {"claimant_email": OTHER.email}
        a = _make_ability(
            spec_type="prd", commit_record=record, actor=ME
        )
        assert a.can("ratify", "prd") is True

    def test_commit_author_cannot_ratify_own_spec(self) -> None:
        """Regression for Issue 1: retired claim must not let author ratify."""
        record = {"claimant_email": ME.email}
        a = _make_ability(
            spec_type="prd", commit_record=record, actor=ME
        )
        assert a.can("ratify", "prd") is False

    def test_ratify_without_commit_record_returns_true(self) -> None:
        """No commit record means nothing to ratify. The can() path returns
        True because `not _is_commit_author` is True; the resolver's
        precondition check rejects the call for missing commit file.
        """
        a = _make_ability(spec_type="prd", commit_record=None)
        assert a.can("ratify", "prd") is True


class TestAbandon:
    """Row: Abandon (PRD claimant)."""

    def test_prd_claimant_can_abandon(self) -> None:
        a = _make_ability(
            spec_type="prd", claim=_claim("prd", claimant=ME)
        )
        assert a.can("abandon", None) is True

    def test_non_prd_claimant_cannot_abandon(self) -> None:
        a = _make_ability(
            spec_type="prd", claim=_claim("prd", claimant=OTHER)
        )
        assert a.can("abandon", None) is False


# ── Static helpers ───────────────────────────────────────────────


class TestIsRfcSlot:
    """Table test for `_is_rfc_slot()`."""

    @pytest.mark.parametrize(
        "spec_type,expected",
        [
            ("rfc", True),
            ("rfc-ingestion", True),
            ("rfc-a", True),
            ("rfc-complex-slug-name", True),
            ("prd", False),
            ("design", False),
            ("rfcfoo", False),  # must have hyphen for slug form
            ("", False),
            (None, False),
        ],
    )
    def test_is_rfc_slot(self, spec_type: str | None, expected: bool) -> None:
        assert CeremonyAbility._is_rfc_slot(spec_type) is expected


# ── Staleness ────────────────────────────────────────────────────


class TestStaleness:
    """Table test for stale detection inside `_unclaimed_or_stale()`."""

    def test_fresh_claim_is_not_stale(self) -> None:
        a = _make_ability(
            claim=_claim("prd", claimant=OTHER, age_seconds=60)
        )
        assert a.can("claim", "prd") is False

    def test_boundary_not_stale(self) -> None:
        """At exactly stale_window seconds old, still active (> not >=)."""
        a = _make_ability(
            claim=_claim("prd", claimant=OTHER, age_seconds=ONE_HOUR)
        )
        assert a.can("claim", "prd") is False

    def test_one_second_over_is_stale(self) -> None:
        a = _make_ability(
            claim=_claim("prd", claimant=OTHER, age_seconds=ONE_HOUR + 1)
        )
        assert a.can("claim", "prd") is True


# ── Authorize() raises on deny ───────────────────────────────────


class TestAuthorize:
    """The thin wrapper around `can()` that PEP resolvers call."""

    def test_allow_does_not_raise(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=ME))
        a.authorize("edit", "prd")  # no exception

    def test_deny_raises_permission_error(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=OTHER))
        with pytest.raises(PermissionError):
            a.authorize("edit", "prd")

    def test_deny_message_mentions_claimant(self) -> None:
        a = _make_ability(claim=_claim("prd", claimant=OTHER))
        with pytest.raises(PermissionError, match="Priya"):
            a.authorize("edit", "prd")

    def test_ratify_deny_mentions_own_spec(self) -> None:
        record = {"claimant_email": ME.email}
        a = _make_ability(spec_type="prd", commit_record=record)
        with pytest.raises(PermissionError, match="cannot ratify own spec"):
            a.authorize("ratify", "prd")


# ── has_eligible_ratifier (used by commitSpec, not can()) ────────


class TestHasEligibleRatifier:

    def test_sole_member_returns_false(self) -> None:
        a = _make_ability(roster_emails=[ME.email])
        assert a.has_eligible_ratifier(ME.email) is False

    def test_multi_member_with_non_author_returns_true(self) -> None:
        a = _make_ability(roster_emails=[ME.email, OTHER.email])
        assert a.has_eligible_ratifier(ME.email) is True

    def test_multi_member_all_authors_returns_false(self) -> None:
        """Edge: every non-author has been removed from the roster."""
        a = _make_ability(roster_emails=[ME.email])
        assert a.has_eligible_ratifier(ME.email) is False
