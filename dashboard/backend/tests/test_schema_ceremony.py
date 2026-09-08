"""Schema-level integration tests for the ceremonyInfo query.

Exercises Strawberry's execute_sync() to verify the query is wired
correctly and produces valid GraphQL responses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.schema import schema


def _make_context(tmp_path: Path) -> dict:
    return {"project_root": tmp_path, "conn": MagicMock()}


CEREMONY_INFO_QUERY = """
query CeremonyInfo($featureName: String!) {
  ceremonyInfo(featureName: $featureName) {
    featureName
    currentRevision {
      revisionId
      parentId
      status
      specContentHash
      contextPackageHash
      validationHash
      createdAt
      reason
    }
    revisionCount
    author
    authorEmail
    createdAt
    isMultiplayer
  }
}
"""


def _write_ceremony(tmp_path: Path, feature: str = "test-feature") -> None:
    feat_dir = tmp_path / ".speed" / "features" / feature
    feat_dir.mkdir(parents=True)
    data = {
        "feature_name": feature,
        "author": "Jane Doe",
        "author_email": "jane@example.com",
        "created_at": "2026-03-29T10:00:00Z",
        "is_multiplayer": False,
        "current_revision": "a1b2c3d4",
        "revision_count": 1,
        "revisions": {
            "a1b2c3d4": {
                "revision_id": "a1b2c3d4",
                "parent_id": None,
                "status": "drafting",
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
                "to_revision": "a1b2c3d4",
                "at": "2026-03-29T10:00:00Z",
                "actor": "Jane Doe",
                "actor_email": "jane@example.com",
                "reason": "initial commit",
            }
        ],
    }
    (feat_dir / "ceremony.json").write_text(json.dumps(data, indent=2))


class TestCeremonyInfoQuery:

    def test_valid_ceremony(self, tmp_path: Path) -> None:
        _write_ceremony(tmp_path)
        result = schema.execute_sync(
            CEREMONY_INFO_QUERY,
            variable_values={"featureName": "test-feature"},
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None
        info = result.data["ceremonyInfo"]
        assert info["featureName"] == "test-feature"
        assert info["revisionCount"] == 1
        assert info["author"] == "Jane Doe"
        assert info["isMultiplayer"] is False

        rev = info["currentRevision"]
        assert rev["revisionId"] == "a1b2c3d4"
        assert rev["parentId"] is None
        assert rev["status"] == "DRAFTING"
        assert rev["specContentHash"] == "a" * 64
        assert rev["contextPackageHash"] == "b" * 64
        assert rev["validationHash"] == "c" * 64
        assert rev["reason"] is None

    def test_null_for_missing_feature(self, tmp_path: Path) -> None:
        (tmp_path / ".speed" / "features").mkdir(parents=True)
        result = schema.execute_sync(
            CEREMONY_INFO_QUERY,
            variable_values={"featureName": "nonexistent"},
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None
        assert result.data["ceremonyInfo"] is None

    def test_error_for_malformed_json(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "broken"
        feat_dir.mkdir(parents=True)
        (feat_dir / "ceremony.json").write_text("{not valid json")
        result = schema.execute_sync(
            CEREMONY_INFO_QUERY,
            variable_values={"featureName": "broken"},
            context_value=_make_context(tmp_path),
        )
        assert result.errors is not None
        assert "malformed" in result.errors[0].message

    def test_error_for_empty_feature_name(self, tmp_path: Path) -> None:
        result = schema.execute_sync(
            CEREMONY_INFO_QUERY,
            variable_values={"featureName": ""},
            context_value=_make_context(tmp_path),
        )
        assert result.errors is not None
        assert "featureName must not be empty" in result.errors[0].message


class TestSchemaRegistration:

    def test_ceremony_info_in_sdl(self) -> None:
        """ceremonyInfo query is registered on the Strawberry schema."""
        sdl = schema.as_str()
        assert "ceremonyInfo(featureName: String!): CeremonyInfo" in sdl

    def test_ceremony_info_returns_type(self) -> None:
        """CeremonyInfo type includes currentRevision and revisionCount fields."""
        sdl = schema.as_str()
        assert "currentRevision: RevisionSummary!" in sdl
        assert "revisionCount: Int!" in sdl

    def test_batched_authoring_mutation_is_registered(self) -> None:
        sdl = schema.as_str()
        assert "submitAuthoringAnswers(" in sdl
        assert "answers: JSON!" in sdl


class TestBootstrapJsonShape:

    def test_bootstrap_status_is_queryable_and_uses_graphql_casing(
        self, tmp_path: Path
    ) -> None:
        result = schema.execute_sync(
            "query { bootstrapStatus }",
            context_value=_make_context(tmp_path),
        )

        assert result.errors is None
        assert result.data["bootstrapStatus"] == {
            "needsBootstrap": True,
            "graphBuilt": False,
            "visionCommitted": False,
            "conventionsCommitted": False,
            "currentStep": "graph",
        }
