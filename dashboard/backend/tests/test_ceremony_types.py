"""Tests for dashboard/backend/resolvers/ceremony_types.py.

Covers the state machine, ownership helpers, get_current_actor(),
ceremony.json parsing, suggestion outdated marking, serialization,
and the ceremonyInfo resolver.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.resolvers.ceremony_types import (
    VALID_TRANSITIONS,
    CeremonyInfo,
    CeremonyState,
    CeremonyStatus,
    Revision,
    ReflogEntry,
    RevisionSummary,
    assert_ceremony_author,
    assert_not_ceremony_author,
    create_revision,
    get_ceremony_info,
    get_current_actor,
    transition_ceremony_state,
    _load_ceremony_state,
    _save_ceremony_state,
    _reset_actor_cache,
    _write_json,
)
from backend.paths import SpeedPaths

# ── Helpers ────────────────────────────────────────────────────────


def _ceremony_path(root: Path, feature: str = "test-feature", *, mp: bool = False) -> Path:
    if mp:
        return root / ".speed" / "shared" / "features" / feature / "ceremony.json"
    return root / ".speed" / "features" / feature / "ceremony.json"


def _make_ceremony(
    tmp_path: Path,
    feature: str = "test-feature",
    status: str = "drafting",
    *,
    mp: bool = False,
    author_email: str = "jane@example.com",
) -> Path:
    """Write a minimal valid ceremony.json and return the project root."""
    path = _ceremony_path(tmp_path, feature, mp=mp)
    path.parent.mkdir(parents=True, exist_ok=True)

    rev_id = "a1b2c3d4"
    data = {
        "feature_name": feature,
        "author": "Jane Doe",
        "author_email": author_email,
        "created_at": "2026-03-29T10:00:00Z",
        "is_multiplayer": mp,
        "current_revision": rev_id,
        "revision_count": 1,
        "revisions": {
            rev_id: {
                "revision_id": rev_id,
                "parent_id": None,
                "status": status,
                "spec_content_hash": "a" * 64,
                "context_package_hash": "b" * 64,
                "validation_hash": "c" * 64,
                "created_at": "2026-03-29T10:00:00Z",
                "reason": None,
            }
        },
        "reflog": [
            {
                "from_revision": None,
                "to_revision": rev_id,
                "at": "2026-03-29T10:00:00Z",
                "actor": "Jane Doe",
                "actor_email": author_email,
                "reason": "initial commit",
            }
        ],
    }
    path.write_text(json.dumps(data, indent=2))
    return tmp_path


def _read_back(root: Path, feature: str = "test-feature", *, mp: bool = False) -> CeremonyState:
    return _load_ceremony_state(_ceremony_path(root, feature, mp=mp))


# ── State machine: valid transitions ──────────────────────────────


class TestValidTransitions:
    """Every valid transition pair succeeds and persists to disk."""

    def test_drafting_to_committed(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path, status="drafting")
        result = transition_ceremony_state(
            "test-feature", CeremonyStatus.COMMITTED, project_root=root
        )
        assert result == CeremonyStatus.COMMITTED
        state = _read_back(root)
        assert state.revisions["a1b2c3d4"].status == CeremonyStatus.COMMITTED

    def test_drafting_to_abandoned(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path, status="drafting")
        result = transition_ceremony_state(
            "test-feature", CeremonyStatus.ABANDONED, project_root=root
        )
        assert result == CeremonyStatus.ABANDONED
        state = _read_back(root)
        assert state.revisions["a1b2c3d4"].status == CeremonyStatus.ABANDONED

    def test_committed_to_ratified(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path, status="committed")
        result = transition_ceremony_state(
            "test-feature", CeremonyStatus.RATIFIED, project_root=root
        )
        assert result == CeremonyStatus.RATIFIED
        state = _read_back(root)
        assert state.revisions["a1b2c3d4"].status == CeremonyStatus.RATIFIED

    def test_committed_to_rejected(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path, status="committed")
        result = transition_ceremony_state(
            "test-feature", CeremonyStatus.REJECTED, project_root=root
        )
        assert result == CeremonyStatus.REJECTED
        state = _read_back(root)
        assert state.revisions["a1b2c3d4"].status == CeremonyStatus.REJECTED


class TestInvalidTransitions:
    """Every invalid pair raises ValueError with the correct message."""

    _INVALID_PAIRS = [
        (s, t)
        for s in CeremonyStatus
        for t in CeremonyStatus
        if t not in VALID_TRANSITIONS.get(s, [])
    ]

    def test_invalid_pair_count(self) -> None:
        # 5 states x 5 targets = 25. 4 valid transitions -> 21 invalid.
        assert len(self._INVALID_PAIRS) == 21

    @pytest.mark.parametrize("current,target", _INVALID_PAIRS)
    def test_invalid_pair(
        self, tmp_path: Path, current: CeremonyStatus, target: CeremonyStatus
    ) -> None:
        root = _make_ceremony(tmp_path, status=current.value)
        with pytest.raises(
            ValueError,
            match=f"Cannot transition from {current.value} to {target.value}",
        ):
            transition_ceremony_state("test-feature", target, project_root=root)

    def test_missing_ceremony(self, tmp_path: Path) -> None:
        (tmp_path / ".speed" / "features" / "ghost").mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            transition_ceremony_state(
                "ghost", CeremonyStatus.COMMITTED, project_root=tmp_path
            )


class TestSPMPBehavior:
    """SP auto-ratifies; MP accumulates verdicts."""

    def test_sp_committed_auto_ratifies(self, tmp_path: Path) -> None:
        """In SP, COMMITTED -> RATIFIED is a valid direct transition."""
        root = _make_ceremony(tmp_path, status="committed", mp=False)
        result = transition_ceremony_state(
            "test-feature", CeremonyStatus.RATIFIED, project_root=root
        )
        assert result == CeremonyStatus.RATIFIED
        state = _read_back(root)
        assert state.revisions["a1b2c3d4"].status == CeremonyStatus.RATIFIED

    def test_mp_committed_to_ratified(self, tmp_path: Path) -> None:
        """In MP, COMMITTED -> RATIFIED when approval threshold met."""
        root = _make_ceremony(tmp_path, status="committed", mp=True)
        result = transition_ceremony_state(
            "test-feature", CeremonyStatus.RATIFIED, project_root=root
        )
        assert result == CeremonyStatus.RATIFIED
        state = _read_back(root, mp=True)
        assert state.revisions["a1b2c3d4"].status == CeremonyStatus.RATIFIED

    def test_mp_committed_to_rejected(self, tmp_path: Path) -> None:
        """In MP, COMMITTED -> REJECTED on rejection verdict."""
        root = _make_ceremony(tmp_path, status="committed", mp=True)
        result = transition_ceremony_state(
            "test-feature", CeremonyStatus.REJECTED, project_root=root
        )
        assert result == CeremonyStatus.REJECTED
        state = _read_back(root, mp=True)
        assert state.revisions["a1b2c3d4"].status == CeremonyStatus.REJECTED


# ── create_revision ───────────────────────────────────────────────


class TestCreateRevision:

    def setup_method(self) -> None:
        _reset_actor_cache()

    def teardown_method(self) -> None:
        _reset_actor_cache()

    def _patch_actor(self, email: str = "jane@example.com"):
        return patch(
            "backend.resolvers.ceremony_types.get_current_actor",
            return_value=("Jane Doe", email),
        )

    def test_from_ratified(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path, status="ratified")
        with self._patch_actor():
            new_rev = create_revision(
                "test-feature", "post-ratification fix", project_root=root
            )
        assert new_rev.status == CeremonyStatus.DRAFTING
        assert new_rev.parent_id == "a1b2c3d4"
        assert new_rev.reason == "post-ratification fix"

        state = _read_back(root)
        assert state.current_revision == new_rev.revision_id
        assert state.revision_count == 2
        assert len(state.reflog) == 2
        # Old revision frozen at terminal state
        assert state.revisions["a1b2c3d4"].status == CeremonyStatus.RATIFIED
        # New revision in revisions map
        assert new_rev.revision_id in state.revisions

    def test_from_rejected(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path, status="rejected")
        with self._patch_actor():
            new_rev = create_revision(
                "test-feature", "addressed rejection", project_root=root
            )
        assert new_rev.status == CeremonyStatus.DRAFTING
        assert new_rev.parent_id == "a1b2c3d4"
        assert new_rev.reason == "addressed rejection"

        state = _read_back(root)
        assert state.current_revision == new_rev.revision_id
        assert state.revision_count == 2
        assert len(state.reflog) == 2
        assert state.revisions["a1b2c3d4"].status == CeremonyStatus.REJECTED

    def test_from_abandoned(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path, status="abandoned")
        with self._patch_actor():
            new_rev = create_revision(
                "test-feature", "recovered", project_root=root
            )
        assert new_rev.status == CeremonyStatus.DRAFTING
        assert new_rev.parent_id == "a1b2c3d4"
        assert new_rev.reason == "recovered"

        state = _read_back(root)
        assert state.current_revision == new_rev.revision_id
        assert state.revision_count == 2
        assert len(state.reflog) == 2
        assert state.revisions["a1b2c3d4"].status == CeremonyStatus.ABANDONED

    def test_from_drafting_fails(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path, status="drafting")
        with self._patch_actor(), pytest.raises(
            ValueError, match="current revision is still in drafting"
        ):
            create_revision("test-feature", "nope", project_root=root)

    def test_from_committed_fails(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path, status="committed")
        with self._patch_actor(), pytest.raises(
            ValueError, match="current revision is still in committed"
        ):
            create_revision("test-feature", "nope", project_root=root)

    def test_non_author_fails(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path, status="ratified")
        with patch(
            "backend.resolvers.ceremony_types.get_current_actor",
            return_value=("Intruder", "intruder@evil.com"),
        ), pytest.raises(PermissionError, match="Only the ceremony author"):
            create_revision("test-feature", "hijack", project_root=root)

    def test_revision_id_content_addressed(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path, status="ratified")
        with self._patch_actor():
            rev = create_revision("test-feature", "first", project_root=root)
        assert len(rev.revision_id) == 8
        assert rev.revision_id != "a1b2c3d4"

    def test_marks_suggestions_outdated(self, tmp_path: Path) -> None:
        """When spec content hash changes, unresolved suggestions are outdated."""
        root = _make_ceremony(tmp_path, status="ratified")
        sug_path = _ceremony_path(root).parent / "suggestions.json"
        _write_json(sug_path, {
            "suggestions": [
                {"id": "s1", "status": "unresolved", "outdated": False},
                {"id": "s2", "status": "accepted", "outdated": False},
                {"id": "s3", "status": "unresolved", "outdated": False},
            ]
        })
        with self._patch_actor():
            create_revision("test-feature", "changed spec", project_root=root)

        updated = json.loads(sug_path.read_text())
        # Unresolved suggestions marked outdated (spec hash changed)
        assert updated["suggestions"][0]["outdated"] is True
        assert updated["suggestions"][2]["outdated"] is True
        # Already-resolved suggestions not touched
        assert updated["suggestions"][1]["outdated"] is False

    def test_preserves_suggestions_when_no_file(self, tmp_path: Path) -> None:
        """No crash when suggestions.json doesn't exist."""
        root = _make_ceremony(tmp_path, status="ratified")
        with self._patch_actor():
            rev = create_revision("test-feature", "no suggestions", project_root=root)
        assert rev.status == CeremonyStatus.DRAFTING

    def test_preserves_resolved_suggestions(self, tmp_path: Path) -> None:
        """Accepted/dismissed suggestions keep their outdated=False flag."""
        root = _make_ceremony(tmp_path, status="ratified")
        sug_path = _ceremony_path(root).parent / "suggestions.json"
        _write_json(sug_path, {
            "suggestions": [
                {"id": "s1", "status": "accepted", "outdated": False},
                {"id": "s2", "status": "dismissed", "outdated": False},
            ]
        })
        with self._patch_actor():
            create_revision("test-feature", "new rev", project_root=root)

        updated = json.loads(sug_path.read_text())
        assert updated["suggestions"][0]["outdated"] is False
        assert updated["suggestions"][1]["outdated"] is False

    def test_no_crash_on_malformed_suggestions(self, tmp_path: Path) -> None:
        """suggestions.json exists but has no 'suggestions' key."""
        root = _make_ceremony(tmp_path, status="ratified")
        sug_path = _ceremony_path(root).parent / "suggestions.json"
        _write_json(sug_path, {"other_key": "value"})
        with self._patch_actor():
            rev = create_revision("test-feature", "ok", project_root=root)
        assert rev.status == CeremonyStatus.DRAFTING


# ── Ownership helpers ─────────────────────────────────────────────


class TestOwnership:

    def _state(self, email: str = "jane@example.com") -> CeremonyState:
        return CeremonyState(
            feature_name="test",
            author="Jane",
            author_email=email,
            created_at="2026-01-01T00:00:00Z",
            is_multiplayer=False,
            current_revision="abc",
            revision_count=1,
        )

    def test_assert_author_pass(self) -> None:
        assert_ceremony_author(self._state(), "jane@example.com")

    def test_assert_author_fail(self) -> None:
        with pytest.raises(
            PermissionError,
            match=r"Only the ceremony author \(Jane\) can perform this action",
        ):
            assert_ceremony_author(self._state(), "other@example.com")

    def test_assert_not_author_pass(self) -> None:
        assert_not_ceremony_author(self._state(), "other@example.com")

    def test_assert_not_author_fail(self) -> None:
        with pytest.raises(
            PermissionError,
            match="Cannot perform this action on your own ceremony",
        ):
            assert_not_ceremony_author(self._state(), "jane@example.com")


# ── get_current_actor ─────────────────────────────────────────────


class TestGetCurrentActor:

    def setup_method(self) -> None:
        _reset_actor_cache()

    def teardown_method(self) -> None:
        _reset_actor_cache()

    def test_env_vars_take_precedence(self) -> None:
        env = {"SPEED_ACTOR": "EnvUser", "SPEED_ACTOR_EMAIL": "env@test.com"}
        with patch.dict("os.environ", env, clear=True):
            name, email = get_current_actor()
        assert name == "EnvUser"
        assert email == "env@test.com"

    def test_git_config_fallback(self) -> None:
        def _mock_git(cmd, **kw):
            if "user.name" in cmd:
                return "GitUser"
            if "user.email" in cmd:
                return "git@test.com"
            raise subprocess.CalledProcessError(1, cmd)

        with patch.dict("os.environ", {}, clear=True), patch(
            "backend.resolvers.ceremony_types.subprocess.check_output",
            side_effect=_mock_git,
        ):
            name, email = get_current_actor()
        assert name == "GitUser"
        assert email == "git@test.com"

    def test_fallback_to_local_email(self) -> None:
        with patch.dict(
            "os.environ", {"SPEED_ACTOR": "NoEmail"}, clear=True
        ), patch(
            "backend.resolvers.ceremony_types.subprocess.check_output",
            side_effect=FileNotFoundError,
        ):
            name, email = get_current_actor()
        assert name == "NoEmail"
        assert email == "NoEmail@local"

    def test_full_fallback_to_unknown(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch(
            "backend.resolvers.ceremony_types.subprocess.check_output",
            side_effect=FileNotFoundError,
        ):
            name, email = get_current_actor()
        assert name == "unknown"
        assert email == "unknown@local"


# ── ceremony.json parsing ─────────────────────────────────────────


class TestCeremonyJsonParsing:

    def test_roundtrip(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path)
        state = _read_back(root)
        assert state.feature_name == "test-feature"
        assert state.revision_count == 1
        assert "a1b2c3d4" in state.revisions
        assert state.revisions["a1b2c3d4"].status == CeremonyStatus.DRAFTING

        _save_ceremony_state(_ceremony_path(root), state)
        state2 = _read_back(root)
        assert state2.feature_name == state.feature_name
        assert state2.current_revision == state.current_revision
        assert state2.revision_count == state.revision_count
        assert len(state2.revisions) == len(state.revisions)
        assert len(state2.reflog) == len(state.reflog)

    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "ceremony.json"
        path.write_text("")
        with pytest.raises(ValueError, match="empty"):
            _load_ceremony_state(path)

    def test_malformed_json(self, tmp_path: Path) -> None:
        path = tmp_path / "ceremony.json"
        path.write_text("{not json")
        with pytest.raises(ValueError, match="malformed"):
            _load_ceremony_state(path)

    def test_missing_top_level_field(self, tmp_path: Path) -> None:
        path = tmp_path / "ceremony.json"
        path.write_text(json.dumps({"feature_name": "x"}))
        with pytest.raises(ValueError, match="missing required field"):
            _load_ceremony_state(path)

    def test_invalid_status_in_revision(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path)
        path = _ceremony_path(root)
        data = json.loads(path.read_text())
        data["revisions"]["a1b2c3d4"]["status"] = "invalid"
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="Invalid ceremony status 'invalid'"):
            _load_ceremony_state(path)

    def test_dangling_current_revision(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path)
        path = _ceremony_path(root)
        data = json.loads(path.read_text())
        data["current_revision"] = "nonexistent"
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="'nonexistent' not found in revisions map"):
            _load_ceremony_state(path)

    @pytest.mark.parametrize("bad_name", [
        "INVALID!",
        "has spaces",
        "a" * 51,
        "-leading-dash",
    ])
    def test_invalid_feature_name(self, tmp_path: Path, bad_name: str) -> None:
        root = _make_ceremony(tmp_path)
        path = _ceremony_path(root)
        data = json.loads(path.read_text())
        data["feature_name"] = bad_name
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="lowercase alphanumeric"):
            _load_ceremony_state(path)

    def test_invalid_author_email(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path)
        path = _ceremony_path(root)
        data = json.loads(path.read_text())
        data["author_email"] = "nope"
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="Invalid author email"):
            _load_ceremony_state(path)

    @pytest.mark.parametrize("field", [
        "revision_id", "spec_content_hash", "context_package_hash",
        "validation_hash", "created_at",
    ])
    def test_invalid_revision_entry_missing_field(self, tmp_path: Path, field: str) -> None:
        root = _make_ceremony(tmp_path)
        path = _ceremony_path(root)
        data = json.loads(path.read_text())
        del data["revisions"]["a1b2c3d4"][field]
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match=f"Malformed revision entry 'a1b2c3d4': missing {field}"):
            _load_ceremony_state(path)

    @pytest.mark.parametrize("field", [
        "to_revision", "at", "actor", "actor_email", "reason",
    ])
    def test_invalid_reflog_entry_missing_field(self, tmp_path: Path, field: str) -> None:
        root = _make_ceremony(tmp_path)
        path = _ceremony_path(root)
        data = json.loads(path.read_text())
        del data["reflog"][0][field]
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="Malformed reflog entry at index 0"):
            _load_ceremony_state(path)

    def test_empty_object(self, tmp_path: Path) -> None:
        """ceremony.json containing {} (valid JSON, missing all fields)."""
        path = tmp_path / "ceremony.json"
        path.write_text("{}")
        with pytest.raises(ValueError, match="missing required field"):
            _load_ceremony_state(path)


# ── get_ceremony_info resolver ────────────────────────────────────


class TestGetCeremonyInfo:

    def test_valid_dereferences_revision(self, tmp_path: Path) -> None:
        root = _make_ceremony(tmp_path)
        info = get_ceremony_info(root, "test-feature")
        assert info is not None
        assert isinstance(info, CeremonyInfo)
        assert info.feature_name == "test-feature"
        assert info.revision_count == 1
        assert info.author == "Jane Doe"
        assert info.author_email == "jane@example.com"
        assert info.is_multiplayer is False

        rev = info.current_revision
        assert isinstance(rev, RevisionSummary)
        assert rev.revision_id == "a1b2c3d4"
        assert rev.parent_id is None
        assert rev.status == CeremonyStatus.DRAFTING
        assert rev.spec_content_hash == "a" * 64
        assert rev.context_package_hash == "b" * 64
        assert rev.validation_hash == "c" * 64
        assert rev.reason is None

    def test_null_no_file(self, tmp_path: Path) -> None:
        (tmp_path / ".speed" / "features" / "ghost").mkdir(parents=True)
        assert get_ceremony_info(tmp_path, "ghost") is None

    def test_null_no_feature(self, tmp_path: Path) -> None:
        (tmp_path / ".speed" / "features").mkdir(parents=True)
        assert get_ceremony_info(tmp_path, "nonexistent") is None

    def test_empty_feature_name(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="featureName must not be empty"):
            get_ceremony_info(tmp_path, "")

    def test_malformed_ceremony(self, tmp_path: Path) -> None:
        feat = tmp_path / ".speed" / "features" / "broken"
        feat.mkdir(parents=True)
        (feat / "ceremony.json").write_text("{bad json")
        with pytest.raises(ValueError, match="malformed"):
            get_ceremony_info(tmp_path, "broken")


# ── Serialization ─────────────────────────────────────────────────


class TestSerialization:

    def test_all_strawberry_types_importable(self) -> None:
        """All 23 shared types can be imported from ceremony_types."""
        from backend.resolvers.ceremony_types import (
            CeremonyStatus, RevisionSummary, CeremonyInfo,
            Intent,
            CodebaseItem, LearningItem, DefectItem, KnowledgeItem,
            RelatedFeature, AuditHistoryItem, ContextPackage,
            ValidationIssue, ValidationDimension, ValidationState,
            SpecDraft,
            SuggestionResolution, SuggestionReply, Suggestion,
            DismissedSummary, SuggestionHistory,
            CommitRecord, VerdictEntry, RatificationState,
        )
        types = [
            CeremonyStatus, RevisionSummary, CeremonyInfo,
            Intent,
            CodebaseItem, LearningItem, DefectItem, KnowledgeItem,
            RelatedFeature, AuditHistoryItem, ContextPackage,
            ValidationIssue, ValidationDimension, ValidationState,
            SpecDraft,
            SuggestionResolution, SuggestionReply, Suggestion,
            DismissedSummary, SuggestionHistory,
            CommitRecord, VerdictEntry, RatificationState,
        ]
        assert len(types) == 23

    def test_ceremony_status_has_5_values(self) -> None:
        assert len(CeremonyStatus) == 5
        assert set(s.value for s in CeremonyStatus) == {
            "drafting", "committed", "ratified", "rejected", "abandoned"
        }


# ── Path helpers ──────────────────────────────────────────────────


class TestPathHelpers:

    def test_sp_all_seven(self, tmp_path: Path) -> None:
        (tmp_path / ".speed" / "features").mkdir(parents=True)
        p = SpeedPaths(tmp_path)
        base = tmp_path / ".speed" / "features" / "auth"
        assert p.ceremony_dir("auth") == base
        assert p.ceremony_state("auth") == base / "ceremony.json"
        assert p.ceremony_intent("auth") == base / "intent.json"
        assert p.ceremony_context_package("auth") == base / "context-package.json"
        assert p.ceremony_suggestions("auth") == base / "suggestions.json"
        assert p.ceremony_commit_record("auth") == base / "commit.json"
        assert p.ceremony_validation_snapshot("auth") == base / "validation-at-commit.json"

    def test_mp_all_seven(self, tmp_path: Path) -> None:
        (tmp_path / ".speed" / "shared" / "features").mkdir(parents=True)
        p = SpeedPaths(tmp_path)
        base = tmp_path / ".speed" / "shared" / "features" / "auth"
        assert p.ceremony_dir("auth") == base
        assert p.ceremony_state("auth") == base / "ceremony.json"
        assert p.ceremony_intent("auth") == base / "intent.json"
        assert p.ceremony_context_package("auth") == base / "context-package.json"
        assert p.ceremony_suggestions("auth") == base / "suggestions.json"
        assert p.ceremony_commit_record("auth") == base / "commit.json"
        assert p.ceremony_validation_snapshot("auth") == base / "validation-at-commit.json"
