"""Tests for the Define Ceremony context package resolver.

Covers validation, intent declaration/refinement, source readers,
assembly, persistence, and schema integration.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.resolvers.context import (
    _extract_observation_text,
    assemble_context_package,
    check_feature_name_collision,
    declare_intent,
    get_context_assembly_status,
    get_context_history,
    load_context_package,
    persist_context_package,
    read_codebase_context,
    read_defects,
    read_learnings,
    read_project_knowledge,
    read_related_features,
    read_vision,
    read_audit_history,
    refine_intent,
    scope_csg_nodes,
    validate_feature_name,
)
from backend.resolvers.context_types import FeatureNameError
from backend.schema import schema


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_llm():
    """Prevent all tests from triggering real LLM calls (CLI subprocesses or API)."""
    with patch("backend.resolvers.context._llm_select_seed_files", return_value=None):
        yield


# ── Helpers ────────────────────────────────────────────────────


def _make_context(tmp_path: Path) -> dict:
    from backend.subscriptions import SubscriptionManager
    return {"project_root": tmp_path, "conn": MagicMock(), "sub_manager": SubscriptionManager()}


def _execute_gql(query: str, variable_values: dict | None = None, context_value: dict | None = None):
    """Execute a GraphQL operation. Uses async execute to support async mutation resolvers."""
    return asyncio.run(schema.execute(query, variable_values=variable_values, context_value=context_value))


def _setup_speed_dir(tmp_path: Path) -> None:
    """Create a minimal .speed/ directory structure for testing."""
    (tmp_path / ".speed" / "features").mkdir(parents=True)
    (tmp_path / ".speed" / "context").mkdir(parents=True)
    (tmp_path / ".speed" / "defects").mkdir(parents=True)


def _write_semantic_graph(tmp_path: Path, nodes: list[dict]) -> None:
    graph_path = tmp_path / ".speed" / "context" / "semantic-graph.json"
    graph_path.write_text(json.dumps({"nodes": nodes, "edges": []}))


def _write_observations(tmp_path: Path, feature: str, observations: list[dict]) -> None:
    obs_dir = tmp_path / ".speed" / "shared" / "knowledge" / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(o) for o in observations]
    (obs_dir / f"{feature}.jsonl").write_text("\n".join(lines))


def _write_defect(tmp_path: Path, name: str, severity: str, related_files: list[str] | None = None) -> None:
    defect_dir = tmp_path / ".speed" / "defects" / name
    defect_dir.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "severity": severity, "status": "open"}
    if related_files:
        data["related_files"] = related_files
    (defect_dir / "state.json").write_text(json.dumps(data))


def _write_conventions(tmp_path: Path, conventions: list[dict]) -> None:
    knowledge_path = tmp_path / ".speed" / "shared" / "knowledge" / "conventions.json"
    knowledge_path.parent.mkdir(parents=True, exist_ok=True)
    knowledge_path.write_text(json.dumps({"conventions": conventions}))


def _write_vision(tmp_path: Path, content: str) -> None:
    vision_path = tmp_path / "specs" / "product" / "overview.md"
    vision_path.parent.mkdir(parents=True, exist_ok=True)
    vision_path.write_text(content)


def _write_defect_spec(tmp_path: Path, name: str, content: str) -> None:
    specs_dir = tmp_path / "specs" / "defects"
    specs_dir.mkdir(parents=True, exist_ok=True)
    (specs_dir / f"{name}.md").write_text(content)


def _write_audit_log(tmp_path: Path, feature: str, issues: list[dict], spec_type: str = "rfc") -> None:
    """Write plan-audit JSON file wrapped in markdown fences (matches real format)."""
    logs_dir = tmp_path / ".speed" / "features" / feature / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    data = {"status": "warn", "spec_type": spec_type, "issues": issues}
    content = f"```json\n{json.dumps(data, indent=2)}\n```"
    (logs_dir / f"plan-audit-{spec_type}-1234567890.json").write_text(content)


def _write_audit_log_plain(tmp_path: Path, feature: str, issues: list[dict], spec_type: str = "rfc") -> None:
    """Write plan-audit JSON without markdown fences."""
    logs_dir = tmp_path / ".speed" / "features" / feature / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    data = {"status": "warn", "spec_type": spec_type, "issues": issues}
    (logs_dir / f"plan-audit-{spec_type}-9999999999.json").write_text(json.dumps(data, indent=2))


def _write_mp_conventions(tmp_path: Path, conventions: list[dict]) -> None:
    knowledge_path = tmp_path / ".speed" / "shared" / "knowledge" / "conventions.json"
    knowledge_path.parent.mkdir(parents=True, exist_ok=True)
    knowledge_path.write_text(json.dumps({"conventions": conventions}))


def _create_declared_feature(tmp_path: Path, feature: str, author: str = "Jane", email: str = "jane@example.com"):
    """Declare a feature and return the result. Use inside a get_current_actor patch."""
    return declare_intent(tmp_path, f"Build the {feature} feature for users", feature)


# ── Validation tests ──────────────────────────────────────────


class TestValidateFeatureName:
    def test_valid_simple(self):
        assert validate_feature_name("my-feature") == "my-feature"

    def test_valid_single_char(self):
        assert validate_feature_name("x") == "x"

    def test_valid_numbers(self):
        assert validate_feature_name("feature-123") == "feature-123"

    def test_strips_whitespace(self):
        assert validate_feature_name("  my-feature  ") == "my-feature"

    def test_empty_raises(self):
        with pytest.raises(FeatureNameError) as exc_info:
            validate_feature_name("")
        assert exc_info.value.reason == "empty"

    def test_too_long_raises(self):
        with pytest.raises(FeatureNameError) as exc_info:
            validate_feature_name("a" * 51)
        assert exc_info.value.reason == "too_long"

    def test_uppercase_raises(self):
        with pytest.raises(FeatureNameError) as exc_info:
            validate_feature_name("My-Feature")
        assert exc_info.value.reason == "invalid_chars"

    def test_special_chars_raises(self):
        with pytest.raises(FeatureNameError) as exc_info:
            validate_feature_name("my_feature")
        assert exc_info.value.reason == "invalid_chars"

    def test_leading_hyphen_raises(self):
        with pytest.raises(FeatureNameError) as exc_info:
            validate_feature_name("-my-feature")
        assert exc_info.value.reason == "leading_trailing_hyphen"

    def test_trailing_hyphen_raises(self):
        with pytest.raises(FeatureNameError) as exc_info:
            validate_feature_name("my-feature-")
        assert exc_info.value.reason == "leading_trailing_hyphen"

    def test_consecutive_hyphens_raises(self):
        with pytest.raises(FeatureNameError) as exc_info:
            validate_feature_name("my--feature")
        assert exc_info.value.reason == "consecutive_hyphens"

    def test_max_length_ok(self):
        name = "a" * 50
        assert validate_feature_name(name) == name


class TestCheckFeatureNameCollision:
    def test_no_collision(self, tmp_path):
        _setup_speed_dir(tmp_path)
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert check_feature_name_collision(paths, "new-feature") is None

    def test_collision_with_active_ceremony(self, tmp_path):
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "existing"
        feat_dir.mkdir(parents=True)
        (feat_dir / "ceremony.json").write_text(json.dumps({
            "author": "Jane Doe",
            "current_revision": "abc123",
            "revisions": {"abc123": {"status": "drafting"}},
        }))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert check_feature_name_collision(paths, "existing") == "Jane Doe"

    def test_no_collision_with_ratified_ceremony(self, tmp_path):
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "old-feature"
        feat_dir.mkdir(parents=True)
        (feat_dir / "ceremony.json").write_text(json.dumps({
            "author": "Jane Doe",
            "current_revision": "abc123",
            "revisions": {"abc123": {"status": "ratified"}},
        }))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert check_feature_name_collision(paths, "old-feature") is None


# ── CSG Scoping tests ─────────────────────────────────────────


class TestScopeCsgNodes:
    def test_matches_by_name(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "Users", "file": "src/Users.php", "kind": "class"},
            {"id": "n2", "name": "Teams", "file": "src/Teams.php", "kind": "class"},
            {"id": "n3", "name": "Config", "file": "src/Config.php", "kind": "class"},
            {"id": "n4", "name": "Router", "file": "src/Router.php", "kind": "class"},
            {"id": "n5", "name": "Logger", "file": "src/Logger.php", "kind": "class"},
        ])
        graph_path = tmp_path / ".speed" / "context" / "semantic-graph.json"
        ids, low_conf = scope_csg_nodes("sort users by activity", graph_path)
        assert "n1" in ids
        assert "n2" not in ids
        assert not low_conf

    def test_full_graph_fallback(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "Users", "file": "src/Users.php", "kind": "class"},
            {"id": "n2", "name": "Teams", "file": "src/Teams.php", "kind": "class"},
        ])
        graph_path = tmp_path / ".speed" / "context" / "semantic-graph.json"
        ids, low_conf = scope_csg_nodes("improve performance", graph_path)
        assert len(ids) == 2  # All nodes returned
        assert low_conf

    def test_missing_graph(self, tmp_path):
        graph_path = tmp_path / "nonexistent.json"
        ids, low_conf = scope_csg_nodes("anything", graph_path)
        assert ids == []
        assert not low_conf


# ── Source Reader tests ────────────────────────────────────────


class TestReadCodebaseContext:
    def test_returns_scoped_nodes(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "Users", "file": "src/Users.php", "kind": "class", "description": "User model"},
            {"id": "n2", "name": "Teams", "file": "src/Teams.php", "kind": "class", "description": "Team model"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_codebase_context(paths, ["n1"])
        assert len(items) == 1
        assert items[0].path == "src/Users.php"

    def test_empty_on_missing_graph(self, tmp_path):
        _setup_speed_dir(tmp_path)
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert read_codebase_context(paths, ["n1"]) == []


class TestReadLearnings:
    def test_reads_observations(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_observations(tmp_path, "add-search", [
            {"text": "Need index migration for search", "confidence": "high", "file_paths": ["src/Users.php"]},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_learnings(paths, ["src/Users.php"], "add search index migration")
        assert len(items) == 1
        assert "index migration" in items[0].text
        assert items[0].confidence == "high"

    def test_tfidf_filters_irrelevant(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_observations(tmp_path, "feature", [
            {"text": "Dashboard schema needs migration for new queries", "confidence": "high"},
            {"text": "Security scanner found XSS in templates", "confidence": "high"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_learnings(paths, [], "add dashboard query migration")
        # Dashboard/migration observation should match; security/XSS should not
        assert len(items) >= 1
        assert any("migration" in i.text.lower() or "dashboard" in i.text.lower() for i in items)

    def test_empty_intent_returns_empty(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_observations(tmp_path, "feature", [
            {"text": "Some observation", "confidence": "high"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_learnings(paths, [], "")
        assert len(items) == 0

    def test_empty_on_no_observations(self, tmp_path):
        _setup_speed_dir(tmp_path)
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert read_learnings(paths, ["src/Users.php"], "test intent about dashboard") == []


class TestReadDefects:
    def test_reads_defects(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_defect(tmp_path, "bad-validator", "major", ["src/Users.php"])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_defects(paths, ["src/Users.php"], "test-feature")
        assert len(items) == 1
        assert items[0].severity == "major"

    def test_normalizes_p_severity(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_defect(tmp_path, "critical-bug", "P0")
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_defects(paths, [], "test-feature")
        assert items[0].severity == "critical"

    def test_empty_on_no_defects(self, tmp_path):
        _setup_speed_dir(tmp_path)
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert read_defects(paths, [], "test-feature") == []


class TestReadProjectKnowledge:
    def test_reads_conventions(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_conventions(tmp_path, [
            {"text": "Use migration specs", "confidence": "high", "source": "observation"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_project_knowledge(paths)
        assert len(items) == 1
        assert items[0].text == "Use migration specs"

    def test_empty_on_missing_file(self, tmp_path):
        _setup_speed_dir(tmp_path)
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert read_project_knowledge(paths) == []


class TestReadVision:
    def test_available(self, tmp_path):
        _write_vision(tmp_path, "# Vision\n\nSPEED is a structured execution pipeline that transforms product specifications into verified code. " * 2)
        status, content = read_vision(tmp_path)
        assert status == "available"
        assert content is not None

    def test_stale(self, tmp_path):
        _write_vision(tmp_path, "# Vision\n\nTODO: fill in")
        status, content = read_vision(tmp_path)
        assert status == "stale"

    def test_missing(self, tmp_path):
        status, content = read_vision(tmp_path)
        assert status == "missing"
        assert content is None


class TestReadRelatedFeatures:
    def test_finds_overlapping_feature(self, tmp_path):
        _setup_speed_dir(tmp_path)
        # Create another feature with a context package
        other_dir = tmp_path / ".speed" / "features" / "other-feature"
        other_dir.mkdir(parents=True)
        (other_dir / "context-package.json").write_text(json.dumps({
            "codebase": [{"path": "src/Users.php", "description": "User model", "node_ids": ["n1"]}],
        }))
        (other_dir / "ceremony.json").write_text(json.dumps({
            "current_revision": "abc",
            "revisions": {"abc": {"status": "ratified"}},
        }))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_related_features(paths, ["src/Users.php"], "my-feature")
        assert len(items) == 1
        assert items[0].name == "other-feature"
        assert items[0].state == "ratified"

    def test_excludes_current_feature(self, tmp_path):
        _setup_speed_dir(tmp_path)
        my_dir = tmp_path / ".speed" / "features" / "my-feature"
        my_dir.mkdir(parents=True)
        (my_dir / "context-package.json").write_text(json.dumps({
            "codebase": [{"path": "src/Users.php"}],
        }))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_related_features(paths, ["src/Users.php"], "my-feature")
        assert len(items) == 0


# ── Assembly tests ─────────────────────────────────────────────


class TestAssemblyAndPersistence:
    def test_assemble_and_persist(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "Users", "file": "src/Users.php", "kind": "class"},
        ])
        # Create the feature directory so persist works
        (tmp_path / ".speed" / "features" / "test-feature").mkdir(parents=True)

        with patch("backend.resolvers.context.get_current_actor", return_value=("Test", "test@local")):
            pkg = assemble_context_package(tmp_path, "sort users by activity", "test-feature")

        assert pkg.feature_name == "test-feature"
        assert pkg.intent == "sort users by activity"
        assert "codebase" in pkg.sources_status

    def test_persist_and_load_roundtrip(self, tmp_path):
        _setup_speed_dir(tmp_path)
        (tmp_path / ".speed" / "features" / "test-feature").mkdir(parents=True)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "Users", "file": "src/Users.php", "kind": "class"},
        ])

        with patch("backend.resolvers.context.get_current_actor", return_value=("Test", "test@local")):
            original = assemble_context_package(tmp_path, "sort users", "test-feature")

        loaded = load_context_package(tmp_path, "test-feature")
        assert loaded is not None
        assert loaded.intent == original.intent
        assert loaded.feature_name == original.feature_name
        assert len(loaded.codebase) == len(original.codebase)

    def test_load_missing_returns_none(self, tmp_path):
        _setup_speed_dir(tmp_path)
        assert load_context_package(tmp_path, "nonexistent") is None

    def test_partial_failure_continues(self, tmp_path):
        _setup_speed_dir(tmp_path)
        (tmp_path / ".speed" / "features" / "test-feature").mkdir(parents=True)
        # No semantic graph = codebase reader returns empty, but others should still work
        _write_conventions(tmp_path, [
            {"text": "Test convention", "confidence": "high", "source": "manual"},
        ])

        with patch("backend.resolvers.context.get_current_actor", return_value=("Test", "test@local")):
            pkg = assemble_context_package(tmp_path, "anything", "test-feature")

        assert pkg.sources_status.get("codebase") == "empty"
        assert pkg.sources_status.get("project_knowledge") == "ok"
        assert len(pkg.project_knowledge) == 1


# ── Intent declaration tests ──────────────────────────────────


class TestDeclareIntent:
    def test_creates_ceremony_artifacts(self, tmp_path):
        _setup_speed_dir(tmp_path)
        with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
            result = declare_intent(tmp_path, "Sort users by activity", "sort-users")

        assert result.feature_name == "sort-users"
        assert (tmp_path / ".speed" / "features" / "sort-users" / "intent.json").exists()
        assert (tmp_path / ".speed" / "features" / "sort-users" / "ceremony.json").exists()
        assert (tmp_path / ".speed" / "features" / "sort-users" / "context-package.json").exists()

    def test_rejects_invalid_name(self, tmp_path):
        _setup_speed_dir(tmp_path)
        with pytest.raises(FeatureNameError):
            declare_intent(tmp_path, "Some intent", "Bad-Name")

    def test_rejects_short_intent(self, tmp_path):
        _setup_speed_dir(tmp_path)
        with pytest.raises(ValueError, match="at least 5"):
            declare_intent(tmp_path, "hi", "my-feature")

    def test_rejects_collision(self, tmp_path):
        _setup_speed_dir(tmp_path)
        with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
            declare_intent(tmp_path, "First intent", "my-feature")
            with pytest.raises(FeatureNameError) as exc_info:
                declare_intent(tmp_path, "Second intent", "my-feature")
            assert exc_info.value.reason == "collision"


class TestRefineIntent:
    def test_updates_intent_text(self, tmp_path):
        _setup_speed_dir(tmp_path)
        with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
            declare_intent(tmp_path, "Sort users by activity", "sort-users")
            result = refine_intent(tmp_path, "sort-users", "Sort users by last access time specifically")

        assert result.context_package.intent == "Sort users by last access time specifically"
        # Original author preserved
        intent_data = json.loads((tmp_path / ".speed" / "features" / "sort-users" / "intent.json").read_text())
        assert intent_data["author"] == "Jane"

    def test_rejects_non_author(self, tmp_path):
        _setup_speed_dir(tmp_path)
        with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
            declare_intent(tmp_path, "Sort users by activity", "sort-users")

        with patch("backend.resolvers.context.get_current_actor", return_value=("Bob", "bob@example.com")):
            with pytest.raises(PermissionError):
                refine_intent(tmp_path, "sort-users", "Different intent")

    def test_rejects_missing_feature(self, tmp_path):
        _setup_speed_dir(tmp_path)
        with pytest.raises(FileNotFoundError):
            refine_intent(tmp_path, "nonexistent", "Some text here")


# ── Schema integration tests ──────────────────────────────────


DECLARE_INTENT_MUTATION = """
mutation DeclareIntent($text: String!, $featureName: String!) {
  declareIntent(text: $text, featureName: $featureName) {
    featureName
    contextPackage {
      intent
      featureName
      scopedArea
      visionStatus
      sourcesStatus
    }
    ceremony {
      featureName
      author
      revisionCount
    }
  }
}
"""

CONTEXT_PACKAGE_QUERY = """
query ContextPackage($featureName: String!) {
  contextPackage(featureName: $featureName) {
    intent
    featureName
    codebase { path description }
    learnings { text sourceFeature confidence }
    defects { name severity }
    projectKnowledge { text confidence source }
    visionStatus
    relatedFeatures { name state }
    auditHistory { featureName finding severity section }
    assembledAt
    sourcesStatus
  }
}
"""


class TestSchemaIntegration:
    def test_declare_intent_mutation(self, tmp_path):
        _setup_speed_dir(tmp_path)
        with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
            with patch("backend.resolvers.ceremony_types.get_current_actor", return_value=("Jane", "jane@example.com")):
                result = _execute_gql(
                    DECLARE_INTENT_MUTATION,
                    variable_values={"text": "Sort users by activity", "featureName": "sort-users"},
                    context_value=_make_context(tmp_path),
                )

        assert result.errors is None, f"GraphQL errors: {result.errors}"
        data = result.data["declareIntent"]
        assert data["featureName"] == "sort-users"
        # contextPackage is None — assembly runs in background
        assert data["contextPackage"] is None
        assert data["ceremony"]["author"] == "Jane"

    def test_context_package_query(self, tmp_path):
        _setup_speed_dir(tmp_path)
        # First declare to create the package
        with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
            with patch("backend.resolvers.ceremony_types.get_current_actor", return_value=("Jane", "jane@example.com")):
                _execute_gql(
                    DECLARE_INTENT_MUTATION,
                    variable_values={"text": "Sort users by activity", "featureName": "sort-users"},
                    context_value=_make_context(tmp_path),
                )

        # Then query the package
        result = _execute_gql(
            CONTEXT_PACKAGE_QUERY,
            variable_values={"featureName": "sort-users"},
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        pkg = result.data["contextPackage"]
        assert pkg["featureName"] == "sort-users"
        assert pkg["visionStatus"] == "missing"

    def test_context_package_query_missing(self, tmp_path):
        _setup_speed_dir(tmp_path)
        result = _execute_gql(
            CONTEXT_PACKAGE_QUERY,
            variable_values={"featureName": "nonexistent"},
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None
        assert result.data["contextPackage"] is None

    def test_declare_intent_with_model_param(self, tmp_path):
        """The model param should be accepted by the schema even if unused (LLM mocked)."""
        _setup_speed_dir(tmp_path)
        mutation = """
        mutation DeclareIntent($text: String!, $featureName: String!, $model: String) {
          declareIntent(text: $text, featureName: $featureName, model: $model) {
            featureName
            contextPackage { intent }
          }
        }
        """
        with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
            with patch("backend.resolvers.ceremony_types.get_current_actor", return_value=("Jane", "jane@example.com")):
                result = _execute_gql(
                    mutation,
                    variable_values={"text": "Sort users by activity", "featureName": "model-test", "model": "test/mock-model"},
                    context_value=_make_context(tmp_path),
                )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        assert result.data["declareIntent"]["featureName"] == "model-test"

    def test_assembly_emits_progress_events(self, tmp_path):
        """Context assembly must emit progress events for each source via sub_manager."""
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "App", "file": "src/app.py", "kind": "module"},
        ])

        from backend.subscriptions import SubscriptionManager, EventType
        sub_manager = SubscriptionManager()

        # Subscribe before assembly starts
        sub_id, queue = sub_manager.subscribe()

        with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
            with patch("backend.resolvers.ceremony_types.get_current_actor", return_value=("Jane", "jane@example.com")):
                # Run assembly directly (not through GraphQL, to avoid async complexity)
                declare_intent(
                    project_root=tmp_path,
                    text="Build a recall surface",
                    feature_name="progress-test",
                    sub_manager=sub_manager,
                )

        # Drain the queue — collect all events
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        progress_events = [
            e for e in events
            if e.type == EventType.CONTEXT_ASSEMBLY_PROGRESS
        ]

        # Must have events for each source + "complete"
        sources_seen = {e.payload["source"] for e in progress_events}
        expected_sources = {"codebase", "learnings", "defects", "project_knowledge", "vision", "related_features", "audit_history", "synthesis", "complete"}
        assert expected_sources == sources_seen, f"Missing progress events for: {expected_sources - sources_seen}"

        # "complete" must be last
        assert progress_events[-1].payload["source"] == "complete"

    def test_assembly_progress_events_reach_async_listener(self, tmp_path):
        """Events emitted from run_in_executor thread must reach async subscription listeners.

        This reproduces the actual runtime path: the mutation runs declare_intent
        in an executor thread (via run_in_executor), and a subscription listener
        awaits events via async for. asyncio.Queue.put_nowait from a non-event-loop
        thread does not wake async waiters — this test verifies the fix works.
        """
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "App", "file": "src/app.py", "kind": "module"},
        ])

        from backend.subscriptions import SubscriptionManager, EventType

        async def run():
            sub_manager = SubscriptionManager()
            received: list[str] = []

            async def collect_events():
                """Listener that collects source names until 'complete'."""
                async for event in sub_manager.listen(EventType.CONTEXT_ASSEMBLY_PROGRESS, "async-progress-test"):
                    received.append(event.payload["source"])
                    if event.payload["source"] == "complete":
                        break

            # Start listener task before assembly
            listener = asyncio.create_task(collect_events())

            # Give the listener a tick to register its subscription
            await asyncio.sleep(0)

            # Run assembly in executor thread (same as schema.py declare_intent)
            loop = asyncio.get_event_loop()
            with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
                with patch("backend.resolvers.ceremony_types.get_current_actor", return_value=("Jane", "jane@example.com")):
                    await loop.run_in_executor(
                        None,
                        declare_intent,
                        tmp_path, "Build async progress", "async-progress-test",
                        sub_manager, None, None,
                    )

            # Wait for listener to finish (with timeout)
            await asyncio.wait_for(listener, timeout=5.0)
            return received

        received = asyncio.run(run())
        expected = {"codebase", "learnings", "defects", "project_knowledge", "vision", "related_features", "audit_history", "synthesis", "complete"}
        assert expected == set(received), f"Missing: {expected - set(received)}, got: {received}"
        assert received[-1] == "complete"

    def test_emit_works_from_thread_without_event_loop(self, tmp_path):
        """_emit must work from a thread that has no event loop (executor thread).

        In production, run_in_executor spawns a plain thread. That thread has no
        asyncio event loop. _emit must still deliver events to the subscription queue.
        """
        _setup_speed_dir(tmp_path)

        from backend.subscriptions import SubscriptionManager, EventType
        from backend.resolvers.context import _emit

        sub_manager = SubscriptionManager()
        sub_id, queue = sub_manager.subscribe()

        import concurrent.futures

        def emit_from_plain_thread():
            # This thread has no event loop — simulates run_in_executor
            _emit(sub_manager, "thread-test", "codebase", "ok")
            _emit(sub_manager, "thread-test", "complete", "ok")

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(emit_from_plain_thread)
            future.result(timeout=5)

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        sources = [e.payload["source"] for e in events if e.type == EventType.CONTEXT_ASSEMBLY_PROGRESS]
        assert "codebase" in sources, f"Events from thread not delivered: {sources}"
        assert "complete" in sources

    def test_async_listener_wakes_on_cross_thread_put(self, tmp_path):
        """async for queue.get() must wake up when put_nowait is called from another thread.

        This is the exact production scenario: subscription listener awaits on the
        event loop, executor thread calls publish_sync (put_nowait) from a plain thread.
        """
        from backend.subscriptions import SubscriptionManager, EventType, DashboardEvent
        import concurrent.futures

        async def run():
            sub_manager = SubscriptionManager()
            received: list[str] = []

            async def listener():
                async for event in sub_manager.listen(EventType.CONTEXT_ASSEMBLY_PROGRESS, "wake-test"):
                    received.append(event.payload["source"])
                    if event.payload["source"] == "complete":
                        break

            task = asyncio.create_task(listener())
            await asyncio.sleep(0)  # let listener register

            def emit_from_thread():
                import time
                for src in ["codebase", "learnings", "defects", "complete"]:
                    sub_manager.publish_sync(DashboardEvent(
                        type=EventType.CONTEXT_ASSEMBLY_PROGRESS,
                        feature="wake-test",
                        payload={"source": src, "status": "ok"},
                    ))
                    time.sleep(0.01)  # small delay between events

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, emit_from_thread)
            await asyncio.wait_for(task, timeout=5.0)
            return received

        received = asyncio.run(run())
        assert received == ["codebase", "learnings", "defects", "complete"]

    def test_subscription_delivers_progress_before_mutation_returns(self, tmp_path):
        """Integration test: subscription events must arrive at the client BEFORE
        the mutation response, so the frontend can show per-source progress.

        This reproduces the exact production flow:
        1. Client starts a subscription via schema.subscribe
        2. Client fires declareIntent mutation via schema.execute
        3. Events should arrive on the subscription WHILE the mutation is running

        CURRENT BUG: The mutation blocks until assembly completes. All subscription
        events are emitted during the mutation, but the client can't process them
        until the mutation response arrives. By then all sources are already done
        and the progress animation is never visible.
        """
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "App", "file": "src/app.py", "kind": "module"},
        ])

        from backend.subscriptions import SubscriptionManager

        SUBSCRIPTION_QUERY = """
        subscription ContextAssemblyProgress($feature: String!) {
          contextAssemblyProgress(feature: $feature) {
            feature
            source
            status
          }
        }
        """

        MUTATION_QUERY = """
        mutation DeclareIntent($text: String!, $featureName: String!, $model: String) {
          declareIntent(text: $text, featureName: $featureName, model: $model) {
            featureName
            contextPackage { intent }
          }
        }
        """

        async def run():
            sub_manager = SubscriptionManager()
            ctx = {"project_root": tmp_path, "conn": MagicMock(), "sub_manager": sub_manager}

            events_before_mutation: list[str] = []
            events_after_mutation: list[str] = []
            mutation_done = False

            # 1. Start subscription
            sub_result = await schema.subscribe(
                SUBSCRIPTION_QUERY,
                variable_values={"feature": "progress-integ"},
                context_value=ctx,
            )

            # Collect subscription events in background
            async def collect():
                nonlocal mutation_done
                async for result in sub_result:
                    if result.errors:
                        break
                    event = result.data["contextAssemblyProgress"]
                    if mutation_done:
                        events_after_mutation.append(event["source"])
                    else:
                        events_before_mutation.append(event["source"])
                    if event["source"] == "complete":
                        break

            collector = asyncio.create_task(collect())
            await asyncio.sleep(0)  # let collector register

            # 2. Fire mutation (runs assembly synchronously in executor)
            with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
                with patch("backend.resolvers.ceremony_types.get_current_actor", return_value=("Jane", "jane@example.com")):
                    mutation_result = await schema.execute(
                        MUTATION_QUERY,
                        variable_values={"text": "Build progress tracking", "featureName": "progress-integ"},
                        context_value=ctx,
                    )

            assert mutation_result.errors is None, f"Mutation errors: {mutation_result.errors}"

            # The mutation returned. context_package should be None (assembly in background).
            declare_data = mutation_result.data["declareIntent"]

            # Now wait for assembly to complete via subscription
            await asyncio.wait_for(collector, timeout=5.0)

            return declare_data

        result = asyncio.run(run())

        expected_sources = {"codebase", "learnings", "defects", "project_knowledge", "vision", "related_features", "audit_history", "synthesis", "complete"}

        # The mutation should return WITHOUT a context package (assembly is background)
        assert result.get("contextPackage") is None, (
            "Mutation should not return contextPackage — assembly runs in background"
        )

        # All subscription events should have been delivered
        # (collector breaks on "complete", so if we got here it received all events)


# ── CSG Scoping — additional tests ───────────────────────────


class TestScopeCsgNodesEdgeCases:
    def test_matches_by_description(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "Ctrl", "file": "src/ctrl.py", "kind": "class", "description": "Authentication controller"},
            {"id": "n2", "name": "Db", "file": "src/db.py", "kind": "module"},
        ])
        graph_path = tmp_path / ".speed" / "context" / "semantic-graph.json"
        ids, low_conf = scope_csg_nodes("authentication", graph_path)
        assert "n1" in ids
        assert "n2" not in ids

    def test_matches_by_file_path(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "Model", "file": "src/auth/login.py", "kind": "module"},
            {"id": "n2", "name": "Model", "file": "src/billing/plan.py", "kind": "module"},
        ])
        graph_path = tmp_path / ".speed" / "context" / "semantic-graph.json"
        ids, low_conf = scope_csg_nodes("login flow", graph_path)
        assert "n1" in ids
        assert "n2" not in ids

    def test_malformed_graph_json(self, tmp_path):
        _setup_speed_dir(tmp_path)
        graph_path = tmp_path / ".speed" / "context" / "semantic-graph.json"
        graph_path.write_text("{invalid json")
        ids, low_conf = scope_csg_nodes("anything", graph_path)
        assert ids == []

    def test_empty_nodes_list(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [])
        graph_path = tmp_path / ".speed" / "context" / "semantic-graph.json"
        ids, low_conf = scope_csg_nodes("anything", graph_path)
        assert ids == []

    def test_nodes_without_ids_skipped(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"name": "NoId", "file": "src/test.py", "kind": "class"},
            {"id": "n1", "name": "Test", "file": "src/test.py", "kind": "class"},
        ])
        graph_path = tmp_path / ".speed" / "context" / "semantic-graph.json"
        ids, low_conf = scope_csg_nodes("test", graph_path)
        assert ids == ["n1"]


# ── Source Reader — learnings edge cases ─────────────────────


class TestReadLearningsEdgeCases:
    def test_malformed_jsonl_lines_skipped(self, tmp_path):
        _setup_speed_dir(tmp_path)
        obs_dir = tmp_path / ".speed" / "shared" / "knowledge" / "observations"
        obs_dir.mkdir(parents=True, exist_ok=True)
        content = '{"detail": {"finding": "good dashboard observation"}, "observation_type": "reviewer_finding"}\n{bad json\n{"detail": {"finding": "another dashboard observation"}, "observation_type": "reviewer_finding"}'
        (obs_dir / "feature.jsonl").write_text(content)
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_learnings(paths, [], "dashboard observation finding")
        assert len(items) == 2

    def test_empty_intent_returns_empty(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_observations(tmp_path, "feature", [
            {"detail": {"finding": "something"}, "observation_type": "reviewer_finding"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_learnings(paths, [], "")
        assert len(items) == 0

    def test_detail_dict_extraction(self, tmp_path):
        """Detail dicts are extracted via _extract_observation_text, not dumped as JSON."""
        _setup_speed_dir(tmp_path)
        _write_observations(tmp_path, "dashboard-feature", [
            {"detail": {"finding": "Dashboard schema needs update", "category": "spec_alignment"}, "observation_type": "reviewer_finding"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_learnings(paths, [], "dashboard schema update alignment")
        assert len(items) >= 1
        assert not items[0].text.startswith("{")  # should NOT be raw JSON


# ── Source Reader — defects edge cases ───────────────────────


class TestReadDefectsEdgeCases:
    def test_defect_spec_md_read(self, tmp_path):
        """Defects from specs/defects/*.md should be found."""
        _setup_speed_dir(tmp_path)
        _write_defect_spec(tmp_path, "ui-glitch", "Severity: major\n\nThe dropdown breaks on hover.")
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_defects(paths, [], "test-feature")
        assert len(items) == 1
        assert items[0].name == "ui-glitch"
        assert items[0].severity == "major"

    def test_defect_spec_p_severity_normalized(self, tmp_path):
        """P0/P1/P2/P3 in spec md files should be normalized. This was the severity_map scoping bug."""
        _setup_speed_dir(tmp_path)
        _write_defect_spec(tmp_path, "crash-bug", "Severity: P0\n\nApp crashes on startup.")
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_defects(paths, [], "test-feature")
        assert items[0].severity == "critical"

    def test_deduplication_between_state_and_spec(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_defect(tmp_path, "same-bug", "major")
        _write_defect_spec(tmp_path, "same-bug", "Severity: minor\n\nDuplicate.")
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_defects(paths, [], "test-feature")
        assert len(items) == 1
        assert items[0].severity == "major"  # state.json wins

    def test_sorted_by_severity(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_defect(tmp_path, "minor-bug", "minor")
        _write_defect(tmp_path, "critical-bug", "critical")
        _write_defect(tmp_path, "major-bug", "major")
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_defects(paths, [], "test-feature")
        assert [d.severity for d in items] == ["critical", "major", "minor"]

    def test_string_related_files_coerced(self, tmp_path):
        _setup_speed_dir(tmp_path)
        defect_dir = tmp_path / ".speed" / "defects" / "bug"
        defect_dir.mkdir(parents=True)
        (defect_dir / "state.json").write_text(json.dumps({
            "name": "bug", "severity": "minor", "status": "open",
            "related_files": "src/single.py",
        }))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_defects(paths, ["src/single.py"], "test-feature")
        assert len(items) == 1

    def test_scoped_filtering(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_defect(tmp_path, "relevant", "major", ["src/target.py"])
        _write_defect(tmp_path, "irrelevant", "major", ["src/other.py"])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_defects(paths, ["src/target.py"], "test-feature")
        assert len(items) == 1
        assert items[0].name == "relevant"


# ── Source Reader — project knowledge edge cases ─────────────


class TestReadProjectKnowledgeEdgeCases:
    def test_multiplayer_path(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_mp_conventions(tmp_path, [
            {"text": "MP convention", "confidence": "high", "source": "manual"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_project_knowledge(paths)
        assert len(items) == 1
        assert items[0].text == "MP convention"

    def test_list_format(self, tmp_path):
        """project-knowledge.json can be a bare list instead of {"conventions": [...]}."""
        _setup_speed_dir(tmp_path)
        knowledge_path = tmp_path / ".speed" / "memory" / "project-knowledge.json"
        knowledge_path.parent.mkdir(parents=True, exist_ok=True)
        knowledge_path.write_text(json.dumps([
            {"text": "Bare list item", "confidence": "medium", "source": "observation"},
        ]))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_project_knowledge(paths)
        assert len(items) == 1
        assert items[0].text == "Bare list item"

    def test_pattern_key_fallback(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_conventions(tmp_path, [
            {"pattern": "Via pattern key", "confidence": "high", "source": "manual"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_project_knowledge(paths)
        assert items[0].text == "Via pattern key"

    def test_convention_key_fallback(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_conventions(tmp_path, [
            {"convention": "Via convention key", "confidence": "low", "source": "manual"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_project_knowledge(paths)
        assert items[0].text == "Via convention key"

    def test_sorted_by_confidence(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_conventions(tmp_path, [
            {"text": "low", "confidence": "low", "source": "o"},
            {"text": "high", "confidence": "high", "source": "o"},
            {"text": "medium", "confidence": "medium", "source": "o"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_project_knowledge(paths)
        assert [i.confidence for i in items] == ["high", "medium", "low"]


# ── Source Reader — vision edge cases ────────────────────────


class TestReadVisionEdgeCases:
    def test_headings_only_is_stale(self, tmp_path):
        _write_vision(tmp_path, "# Product Vision\n\n## Goals\n\n## Non-Goals\n\n## Success Criteria\n")
        status, content = read_vision(tmp_path)
        assert status == "stale"

    def test_template_markers_stale(self, tmp_path):
        _write_vision(tmp_path, "# Vision\n\n{{ fill this in }}\n\n<!-- TODO: complete this section -->\n" * 5)
        status, content = read_vision(tmp_path)
        assert status == "stale"

    def test_short_content_is_stale(self, tmp_path):
        _write_vision(tmp_path, "# Vision\n\nTBD")
        status, content = read_vision(tmp_path)
        assert status == "stale"
        assert content is not None  # Content returned even when stale

    def test_oserror_returns_missing(self, tmp_path):
        """If read fails, treat as missing."""
        status, content = read_vision(tmp_path / "nonexistent-root")
        assert status == "missing"


# ── Source Reader — related features edge cases ──────────────


class TestReadRelatedFeaturesEdgeCases:
    def test_empty_scoped_files_returns_empty(self, tmp_path):
        _setup_speed_dir(tmp_path)
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert read_related_features(paths, [], "my-feature") == []

    def test_feature_without_context_package_skipped(self, tmp_path):
        _setup_speed_dir(tmp_path)
        other_dir = tmp_path / ".speed" / "features" / "no-pkg"
        other_dir.mkdir(parents=True)
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert read_related_features(paths, ["src/a.py"], "my-feature") == []

    def test_no_overlap_returns_empty(self, tmp_path):
        _setup_speed_dir(tmp_path)
        other_dir = tmp_path / ".speed" / "features" / "other"
        other_dir.mkdir(parents=True)
        (other_dir / "context-package.json").write_text(json.dumps({
            "codebase": [{"path": "src/unrelated.py"}],
        }))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert read_related_features(paths, ["src/target.py"], "my-feature") == []

    def test_overlap_files_populated(self, tmp_path):
        _setup_speed_dir(tmp_path)
        other_dir = tmp_path / ".speed" / "features" / "other"
        other_dir.mkdir(parents=True)
        (other_dir / "context-package.json").write_text(json.dumps({
            "codebase": [{"path": "src/shared.py"}, {"path": "src/other.py"}],
        }))
        (other_dir / "ceremony.json").write_text(json.dumps({
            "current_revision": "a", "revisions": {"a": {"status": "committed"}},
        }))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_related_features(paths, ["src/shared.py"], "my-feature")
        assert items[0].overlap_files == ["src/shared.py"]
        assert items[0].state == "committed"


# ── Source Reader — audit history ────────────────────────────


class TestReadAuditHistory:
    def test_reads_plan_audit(self, tmp_path):
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "past-feature"
        feat_dir.mkdir(parents=True)
        _write_audit_log(tmp_path, "past-feature", [
            {"message": "Missing AC for edge case", "severity": "error", "section": "Stories"},
            {"message": "Typo in title", "severity": "info", "section": "Overview"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_audit_history(paths, [])
        assert len(items) == 2
        # error -> critical mapping
        assert items[0].severity == "critical"

    def test_sorted_by_severity(self, tmp_path):
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "feat"
        feat_dir.mkdir(parents=True)
        _write_audit_log(tmp_path, "feat", [
            {"message": "info issue", "severity": "info", "section": "A"},
            {"message": "error issue", "severity": "error", "section": "B"},
            {"message": "warning issue", "severity": "warning", "section": "C"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_audit_history(paths, [])
        assert [i.severity for i in items] == ["critical", "major", "info"]

    def test_empty_on_no_logs(self, tmp_path):
        _setup_speed_dir(tmp_path)
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert read_audit_history(paths, []) == []

    def test_plain_json_without_fences(self, tmp_path):
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "feat"
        feat_dir.mkdir(parents=True)
        _write_audit_log_plain(tmp_path, "feat", [
            {"message": "Plain JSON finding", "severity": "warning", "section": "Scope"},
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_audit_history(paths, [])
        assert len(items) == 1
        assert items[0].finding == "Plain JSON finding"
        assert items[0].severity == "major"  # warning -> major


# ── Persistence edge cases ───────────────────────────────────


class TestPersistenceEdgeCases:
    def test_load_malformed_json_returns_none(self, tmp_path):
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "bad"
        feat_dir.mkdir(parents=True)
        (feat_dir / "context-package.json").write_text("{totally broken json")
        assert load_context_package(tmp_path, "bad") is None

    def test_load_missing_fields_defaults(self, tmp_path):
        """Schema evolution: old packages missing new fields should still load."""
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "old"
        feat_dir.mkdir(parents=True)
        (feat_dir / "context-package.json").write_text(json.dumps({
            "intent": "test",
            "feature_name": "old",
            # Missing most fields
        }))
        pkg = load_context_package(tmp_path, "old")
        assert pkg is not None
        assert pkg.intent == "test"
        assert pkg.codebase == []
        assert pkg.learnings == []
        assert pkg.vision_status == "missing"
        assert pkg.sources_status == {}

    def test_full_roundtrip_all_fields(self, tmp_path):
        """Persist and load with all field types populated."""
        _setup_speed_dir(tmp_path)
        (tmp_path / ".speed" / "features" / "full").mkdir(parents=True)
        from backend.resolvers.ceremony_types import (
            CodebaseItem, LearningItem, DefectItem, KnowledgeItem,
            RelatedFeature, AuditHistoryItem, ContextPackage,
        )
        pkg = ContextPackage(
            intent="build a thing",
            feature_name="full",
            scoped_area=["n1", "n2"],
            codebase=[CodebaseItem(path="a.py", description="Module A", node_ids=["n1"])],
            learnings=[LearningItem(text="lesson", source_feature="old", confidence="high")],
            defects=[DefectItem(name="bug", severity="critical", status="open", related_files=["a.py"])],
            project_knowledge=[KnowledgeItem(text="convention", confidence="high", source="manual")],
            vision_status="available",
            vision_content="# Vision\n\nThe product does things.",
            related_features=[RelatedFeature(name="other", state="ratified", overlap_files=["a.py"])],
            audit_history=[AuditHistoryItem(feature_name="old", finding="issue", severity="major", section="AC")],
            assembled_at="2026-01-01T00:00:00Z",
            sources_status={"codebase": "ok", "learnings": "ok"},
        )
        persist_context_package(tmp_path, "full", pkg)
        loaded = load_context_package(tmp_path, "full")
        assert loaded is not None
        assert loaded.intent == "build a thing"
        assert len(loaded.codebase) == 1
        assert loaded.codebase[0].node_ids == ["n1"]
        assert len(loaded.learnings) == 1
        assert len(loaded.defects) == 1
        assert loaded.defects[0].related_files == ["a.py"]
        assert len(loaded.related_features) == 1
        assert loaded.related_features[0].overlap_files == ["a.py"]
        assert len(loaded.audit_history) == 1
        assert loaded.vision_content is not None
        assert loaded.sources_status == {"codebase": "ok", "learnings": "ok"}


# ── Query resolver — assembly status ─────────────────────────


class TestGetContextAssemblyStatus:
    def test_idle_when_no_package(self, tmp_path):
        _setup_speed_dir(tmp_path)
        result = get_context_assembly_status(tmp_path, "nonexistent")
        assert result.status == "idle"
        assert result.sources == []

    def test_complete_with_sources(self, tmp_path):
        _setup_speed_dir(tmp_path)
        (tmp_path / ".speed" / "features" / "feat").mkdir(parents=True)
        with patch("backend.resolvers.context.get_current_actor", return_value=("Test", "test@local")):
            declare_intent(tmp_path, "Build some feature", "feat")
        result = get_context_assembly_status(tmp_path, "feat")
        assert result.status == "complete"
        assert len(result.sources) > 0
        source_names = {s.name for s in result.sources}
        assert "codebase" in source_names
        assert "vision" in source_names

    def test_error_sources_have_messages(self, tmp_path):
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "err"
        feat_dir.mkdir(parents=True)
        from backend.resolvers.ceremony_types import ContextPackage
        pkg = ContextPackage(
            intent="test", feature_name="err", scoped_area=[], codebase=[],
            learnings=[], defects=[], project_knowledge=[],
            vision_status="missing", vision_content=None,
            related_features=[], audit_history=[],
            assembled_at="2026-01-01T00:00:00Z",
            sources_status={"codebase": "error", "learnings": "ok"},
        )
        persist_context_package(tmp_path, "err", pkg)
        result = get_context_assembly_status(tmp_path, "err")
        cb = next(s for s in result.sources if s.name == "codebase")
        assert cb.status == "error"
        assert cb.error is not None
        lr = next(s for s in result.sources if s.name == "learnings")
        assert lr.error is None


# ── Query resolver — context history ─────────────────────────


class TestGetContextHistory:
    def test_returns_none_when_no_snapshot(self, tmp_path):
        _setup_speed_dir(tmp_path)
        result = get_context_history(tmp_path, "nonexistent")
        assert result is None

    def test_returns_snapshot_and_current(self, tmp_path):
        _setup_speed_dir(tmp_path)
        with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
            declare_intent(tmp_path, "Build navigation feature", "nav-feature")
        result = get_context_history(tmp_path, "nav-feature")
        assert result is not None
        assert result.snapshot is not None
        assert result.current is not None
        assert result.current_assembly_status == "ok"
        assert result.snapshot.intent == "Build navigation feature"

    def test_returns_error_when_intent_missing(self, tmp_path):
        """If intent.json is deleted but context-package.json exists."""
        _setup_speed_dir(tmp_path)
        with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
            declare_intent(tmp_path, "Build a feature here", "orphan")
        # Delete intent.json
        (tmp_path / ".speed" / "features" / "orphan" / "intent.json").unlink()
        result = get_context_history(tmp_path, "orphan")
        assert result is not None
        assert result.snapshot is not None
        assert result.current is None
        assert result.current_assembly_status == "error"
        assert "intent" in result.current_assembly_error.lower()

    def test_current_assembly_failure(self, tmp_path):
        """If current assembly throws, snapshot is still returned."""
        _setup_speed_dir(tmp_path)
        with patch("backend.resolvers.context.get_current_actor", return_value=("Jane", "jane@example.com")):
            declare_intent(tmp_path, "Build a feature here", "broken")
        with patch("backend.resolvers.context.assemble_context_package", side_effect=RuntimeError("boom")):
            result = get_context_history(tmp_path, "broken")
        assert result is not None
        assert result.snapshot is not None
        assert result.current is None
        assert result.current_assembly_status == "error"
        assert "boom" in result.current_assembly_error


# ── Collision edge cases ─────────────────────────────────────


class TestCheckFeatureNameCollisionEdgeCases:
    def test_malformed_ceremony_returns_none(self, tmp_path):
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "broken"
        feat_dir.mkdir(parents=True)
        (feat_dir / "ceremony.json").write_text("{invalid json")
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert check_feature_name_collision(paths, "broken") is None

    def test_committed_is_active(self, tmp_path):
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "committed-feat"
        feat_dir.mkdir(parents=True)
        (feat_dir / "ceremony.json").write_text(json.dumps({
            "author": "Bob",
            "current_revision": "rev1",
            "revisions": {"rev1": {"status": "committed"}},
        }))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert check_feature_name_collision(paths, "committed-feat") == "Bob"

    def test_abandoned_is_not_active(self, tmp_path):
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "dead-feat"
        feat_dir.mkdir(parents=True)
        (feat_dir / "ceremony.json").write_text(json.dumps({
            "author": "Bob",
            "current_revision": "rev1",
            "revisions": {"rev1": {"status": "abandoned"}},
        }))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        assert check_feature_name_collision(paths, "dead-feat") is None


# ── New tests for context assembly fixes ──────────────────────


class TestExtractObservationText:
    def test_finding_with_category(self):
        result = _extract_observation_text(
            {"finding": "test finding", "category": "testing"}, "reviewer_finding"
        )
        assert result == "[testing] test finding"

    def test_concern_key(self):
        result = _extract_observation_text({"concern": "my concern"}, "agent_concern")
        assert result == "my concern"

    def test_description_with_issue_type(self):
        result = _extract_observation_text(
            {"description": "mismatch found", "issue_type": "interface_mismatch"}, "coherence_issue"
        )
        assert result == "[interface_mismatch] mismatch found"

    def test_requirement_and_analysis(self):
        result = _extract_observation_text(
            {"requirement": "must have X", "analysis": "missing"}, "verify_finding"
        )
        assert result == "must have X: missing"

    def test_context_miss(self):
        result = _extract_observation_text(
            {"file": "lib/auth.py", "reason": "not in context"}, "context_miss"
        )
        assert result == "lib/auth.py: not in context"

    def test_forced_approval(self):
        result = _extract_observation_text(
            {"change_type": "forced_approval", "reviewer_verdict": "request_changes"}, "human_override"
        )
        assert "Forced approval" in result

    def test_empty_detail_returns_empty(self):
        assert _extract_observation_text({}, "unknown") == ""

    def test_success_returns_empty(self):
        assert _extract_observation_text(
            {"files_planned": 1, "files_actual": 1, "agent_model": "sonnet"}, "success"
        ) == ""


class TestScopeCsgNodesWordBoundary:
    def test_word_boundary_not_substring(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "auth", "kind": "module", "file": "lib/auth.py"},
            {"id": "n2", "name": "authentication_handler", "kind": "function", "file": "lib/authentication.py"},
            {"id": "n3", "name": "oauth_client", "kind": "class", "file": "lib/oauth.py"},
        ])
        graph_path = tmp_path / ".speed" / "context" / "semantic-graph.json"
        nodes, low = scope_csg_nodes("fix auth module", graph_path, use_llm=False)
        assert "n1" in nodes
        assert "n2" not in nodes  # "authentication" != "auth"
        assert "n3" not in nodes  # "oauth" != "auth"

    def test_low_confidence_when_broad(self, tmp_path):
        _setup_speed_dir(tmp_path)
        # Create nodes where >40% match "test"
        nodes = [{"id": f"n{i}", "name": "test", "kind": "function", "file": f"test_{i}.py"} for i in range(10)]
        _write_semantic_graph(tmp_path, nodes)
        graph_path = tmp_path / ".speed" / "context" / "semantic-graph.json"
        matched, low = scope_csg_nodes("run test", graph_path, use_llm=False)
        assert len(matched) == 10
        assert low is True


class TestReadDefectsFiltering:
    def test_defect_spec_filtered_by_related_feature(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_defect_spec(tmp_path, "dashboard-bug", "# Defect\nSeverity: major\nRelated Feature: dashboard-landing\n\nSome bug")
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_defects(paths, ["dashboard/backend/schema.py"], "test-feature")
        assert len(items) == 1
        assert items[0].name == "dashboard-bug"

    def test_defect_spec_excluded_when_no_match(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_defect_spec(tmp_path, "security-bug", "# Defect\nSeverity: major\nRelated Feature: security\n\nSome bug")
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_defects(paths, ["dashboard/backend/schema.py"], "test-feature")
        assert len(items) == 0

    def test_empty_related_files_excluded(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_defect(tmp_path, "vague-bug", "major")  # no related_files
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_defects(paths, ["lib/auth.py"], "test-feature")
        assert len(items) == 0


class TestReadRelatedFeaturesFallback:
    def test_task_fallback_finds_overlap(self, tmp_path):
        _setup_speed_dir(tmp_path)
        # Create a feature with task files but no context package
        feat_dir = tmp_path / ".speed" / "features" / "other-feature"
        tasks_dir = feat_dir / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "1.json").write_text(json.dumps({"files_touched": ["lib/auth.py", "lib/db.py"]}))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_related_features(paths, ["lib/auth.py", "lib/config.py"], "my-feature")
        assert len(items) == 1
        assert items[0].name == "other-feature"
        assert "lib/auth.py" in items[0].overlap_files

    def test_no_overlap_returns_empty(self, tmp_path):
        _setup_speed_dir(tmp_path)
        feat_dir = tmp_path / ".speed" / "features" / "other-feature"
        tasks_dir = feat_dir / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "1.json").write_text(json.dumps({"files_touched": ["lib/unrelated.py"]}))
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_related_features(paths, ["lib/auth.py"], "my-feature")
        assert len(items) == 0


class TestReadAuditHistoryNew:
    def test_reads_plan_audit_with_fences(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_audit_log(tmp_path, "feat-a", [
            {"severity": "error", "section": "Testing", "message": "Missing test coverage"}
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_audit_history(paths, [])
        assert len(items) == 1
        assert items[0].finding == "Missing test coverage"
        assert items[0].severity == "critical"  # error -> critical

    def test_plain_json_also_works(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_audit_log_plain(tmp_path, "feat-b", [
            {"severity": "warning", "section": "Scope", "message": "Scope too broad"}
        ])
        from backend.paths import get_paths
        paths = get_paths(tmp_path)
        items = read_audit_history(paths, [])
        assert len(items) == 1
        assert items[0].finding == "Scope too broad"
        assert items[0].severity == "major"  # warning -> major


class TestBlufSummaryPersistence:
    def test_persist_and_load_bluf(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "test", "kind": "function", "file": "test.py"}
        ])
        pkg = assemble_context_package(tmp_path, "test intent", "test-feature")
        assert pkg.bluf_summary is None  # no LLM available
        pkg.bluf_summary = "This is a synthesized brief."
        persist_context_package(tmp_path, "test-feature", pkg)
        loaded = load_context_package(tmp_path, "test-feature")
        assert loaded is not None
        assert loaded.bluf_summary == "This is a synthesized brief."


class TestScopingMetadataPersistence:
    def test_scoping_fields_persisted(self, tmp_path):
        _setup_speed_dir(tmp_path)
        _write_semantic_graph(tmp_path, [
            {"id": "n1", "name": "test", "kind": "function", "file": "test.py"}
        ])
        pkg = assemble_context_package(tmp_path, "test intent", "test-feature")
        assert pkg.scoping_method in ("llm", "keyword", "full_graph")
        persist_context_package(tmp_path, "test-feature", pkg)
        loaded = load_context_package(tmp_path, "test-feature")
        assert loaded is not None
        assert loaded.scoping_method == pkg.scoping_method
        assert loaded.low_confidence == pkg.low_confidence
