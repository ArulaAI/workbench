"""Tests for dashboard/backend/resolvers/ceremony_suggestions.py.

Covers the per-spec routing added in Phase 2:
- `create_suggestion` takes `spec_type`, routes through CeremonyAbility,
  persists `spec_type` on the record
- `resolve_suggestion` reads the suggestion's stored `spec_type` and
  authorizes via the claim-of-that-spec
- `get_suggestion_history` filters by `spec_type` when provided
- Legacy suggestions (no `spec_type` field on disk) default to "prd"
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
from backend.resolvers.ceremony_suggestions import (
    create_suggestion,
    get_suggestion_history,
    get_suggestions,
    resolve_suggestion,
)
from backend.resolvers.ceremony_types import (
    CeremonyState,
    CeremonyStatus,
    Revision,
    SpecClaim,
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


def _bootstrap(tmp_path: Path, feature: str = "sample") -> None:
    base = tmp_path / ".speed" / "shared" / "features" / feature
    base.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".speed" / "shared").mkdir(parents=True, exist_ok=True)
    roster_dir = tmp_path / ".speed" / "shared" / "roster"
    roster_dir.mkdir(parents=True, exist_ok=True)
    for name, email in (("Sanjay", "sanjay@example.com"), ("Priya", "priya@example.com")):
        (roster_dir / f"{name.lower()}.json").write_text(
            json.dumps({"name": name, "email": email}) + "\n"
        )

    now = datetime.now(timezone.utc).isoformat()
    state = CeremonyState(
        feature_name=feature,
        author="Sanjay",
        author_email="sanjay@example.com",
        created_at=now,
        is_multiplayer=True,
        current_revision="rev1",
        revision_count=1,
        revisions={
            "rev1": Revision(
                revision_id="rev1",
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


def _patch_actor(actor_name: str, actor_email: str):
    from contextlib import ExitStack
    stack = ExitStack()
    for mod in (
        "backend.resolvers.ceremony_suggestions.get_current_actor",
        "backend.resolvers.ceremony_types.get_current_actor",
        "backend.resolvers.ceremony_authz.get_current_actor",
    ):
        stack.enter_context(patch(mod, return_value=(actor_name, actor_email)))
    return stack


# ── create_suggestion ────────────────────────────────────────────


class TestCreateSuggestion:

    def test_non_claimant_can_create(self, tmp_path: Path) -> None:
        _bootstrap(tmp_path)
        _prewrite_claim(tmp_path, "sample", "prd", "Sanjay", "sanjay@example.com")

        with _patch_actor("Priya", "priya@example.com"):
            suggestion = create_suggestion(
                tmp_path, "sample", "prd",
                "scope", "Scope", "Narrow the scope to just ingestion",
            )

        assert suggestion.spec_type == "prd"
        assert suggestion.author_email == "priya@example.com"
        assert suggestion.status == "unresolved"

    def test_claimant_cannot_create_on_own_spec(self, tmp_path: Path) -> None:
        _bootstrap(tmp_path)
        _prewrite_claim(tmp_path, "sample", "prd", "Sanjay", "sanjay@example.com")

        with _patch_actor("Sanjay", "sanjay@example.com"):
            with pytest.raises(PermissionError):
                create_suggestion(
                    tmp_path, "sample", "prd",
                    "scope", "Scope", "cannot suggest on my own",
                )

    def test_unclaimed_spec_allows_suggestion(self, tmp_path: Path) -> None:
        """Suggesting on an unclaimed spec is allowed — the `suggest`
        rule is `not _is_active_claimant`, which is True when no claim
        exists. This matches the authz matrix test in Phase 1."""
        _bootstrap(tmp_path)

        with _patch_actor("Priya", "priya@example.com"):
            suggestion = create_suggestion(
                tmp_path, "sample", "prd",
                "intro", "Intro", "Add a one-liner here",
            )
            assert suggestion.spec_type == "prd"

    def test_spec_type_persisted_on_disk(self, tmp_path: Path) -> None:
        _bootstrap(tmp_path)
        _prewrite_claim(tmp_path, "sample", "design", "Sanjay", "sanjay@example.com")

        with _patch_actor("Priya", "priya@example.com"):
            create_suggestion(
                tmp_path, "sample", "design",
                "layout", "Layout", "Rethink the column grid",
            )

        paths = get_paths(tmp_path)
        raw = json.loads(paths.ceremony_suggestions("sample").read_text())
        entries = raw if isinstance(raw, list) else raw.get("suggestions", [])
        assert len(entries) == 1
        assert entries[0]["spec_type"] == "design"


# ── resolve_suggestion ────────────────────────────────────────────


class TestResolveSuggestion:

    def _seed(self, tmp_path: Path, spec_type: str = "prd") -> str:
        _bootstrap(tmp_path)
        _prewrite_claim(
            tmp_path, "sample", spec_type, "Sanjay", "sanjay@example.com",
        )
        with _patch_actor("Priya", "priya@example.com"):
            s = create_suggestion(
                tmp_path, "sample", spec_type,
                "scope", "Scope", "Narrow the scope",
            )
        return s.id

    def test_claimant_of_target_spec_can_resolve(
        self, tmp_path: Path
    ) -> None:
        sid = self._seed(tmp_path, spec_type="prd")

        with _patch_actor("Sanjay", "sanjay@example.com"):
            resolved = resolve_suggestion(tmp_path, "sample", sid, "accept")
            assert resolved.status == "accepted"
            assert resolved.resolution is not None
            assert resolved.resolution.resolved_by_email == "sanjay@example.com"

    def test_non_claimant_cannot_resolve(self, tmp_path: Path) -> None:
        sid = self._seed(tmp_path, spec_type="prd")

        # Priya (author of the suggestion, non-claimant) cannot resolve.
        with _patch_actor("Priya", "priya@example.com"):
            with pytest.raises(PermissionError):
                resolve_suggestion(tmp_path, "sample", sid, "accept")

    def test_resolve_routes_via_suggestion_spec_type(
        self, tmp_path: Path
    ) -> None:
        """A design suggestion must be resolvable by the design claimant
        even if they are not the PRD claimant. This is the fix for the
        cross-spec routing ambiguity the RFC calls out."""
        _bootstrap(tmp_path)
        _prewrite_claim(
            tmp_path, "sample", "prd", "Priya", "priya@example.com",
        )
        _prewrite_claim(
            tmp_path, "sample", "design", "Sanjay", "sanjay@example.com",
        )

        # Priya leaves a design suggestion (she's not the Design claimant).
        with _patch_actor("Priya", "priya@example.com"):
            s = create_suggestion(
                tmp_path, "sample", "design",
                "grid", "Grid", "Reflow the column gutter",
            )

        # Sanjay is PRD non-claimant but Design claimant — should resolve.
        with _patch_actor("Sanjay", "sanjay@example.com"):
            resolved = resolve_suggestion(tmp_path, "sample", s.id, "accept")
            assert resolved.status == "accepted"

    def test_dismiss_without_reason_rejected(self, tmp_path: Path) -> None:
        sid = self._seed(tmp_path, spec_type="prd")
        with _patch_actor("Sanjay", "sanjay@example.com"):
            with pytest.raises(ValueError, match="reason"):
                resolve_suggestion(tmp_path, "sample", sid, "dismiss")

    def test_invalid_action_rejected(self, tmp_path: Path) -> None:
        sid = self._seed(tmp_path, spec_type="prd")
        with _patch_actor("Sanjay", "sanjay@example.com"):
            with pytest.raises(ValueError, match="Invalid action"):
                resolve_suggestion(tmp_path, "sample", sid, "ignore")


# ── get_suggestions (legacy field back-compat) ───────────────────


class TestLegacySuggestionsBackCompat:
    """Suggestions written before Phase 1 have no `spec_type` field on
    disk; the read path defaults to `"prd"`."""

    def test_read_legacy_suggestion_defaults_to_prd(
        self, tmp_path: Path
    ) -> None:
        _bootstrap(tmp_path)
        paths = get_paths(tmp_path)
        legacy_entry = {
            "id": "legacy-1",
            "author": "Sanjay",
            "author_email": "sanjay@example.com",
            "revision_id": "",
            "section_id": "scope",
            "section_title": "Scope",
            "section_content_hash": "",
            "text": "legacy suggestion",
            "status": "unresolved",
            "outdated": False,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": None,
            "resolution": None,
            "thread": [],
            # no spec_type field
        }
        _write_json(
            paths.ceremony_suggestions("sample"),
            [legacy_entry],
        )

        results = get_suggestions(tmp_path, "sample")
        assert len(results) == 1
        assert results[0].spec_type == "prd"


# ── get_suggestion_history filter ─────────────────────────────────


class TestSuggestionHistoryFilter:

    def test_filter_by_spec_type(self, tmp_path: Path) -> None:
        _bootstrap(tmp_path)
        _prewrite_claim(
            tmp_path, "sample", "prd", "Sanjay", "sanjay@example.com",
        )
        _prewrite_claim(
            tmp_path, "sample", "design", "Alex", "alex@example.com",
        )

        with _patch_actor("Priya", "priya@example.com"):
            create_suggestion(tmp_path, "sample", "prd", "a", "A", "prd-1")
            create_suggestion(tmp_path, "sample", "prd", "b", "B", "prd-2")
            create_suggestion(tmp_path, "sample", "design", "c", "C", "design-1")

        prd_history = get_suggestion_history(
            tmp_path, "sample", spec_type="prd",
        )
        design_history = get_suggestion_history(
            tmp_path, "sample", spec_type="design",
        )
        all_history = get_suggestion_history(tmp_path, "sample")

        assert prd_history.received == 2
        assert design_history.received == 1
        assert all_history.received == 3
