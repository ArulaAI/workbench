#!/usr/bin/env python3
"""Tests for the conventions pipeline: Phase B (observations), Phase C (templates),
and the orchestrator (discover_conventions, format_*, trigger logic).

Covers 40+ test cases across three sections with edge cases for malformed input,
empty directories, confidence assignment, evolution tracking, conflict handling,
scope filtering, and token budget truncation.
"""

import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.learn.conventions import (
    ConventionEntry,
    ConventionResult,
    RawPattern,
    _should_run_discovery,
    discover_conventions,
    format_conventions_for_agent,
    format_knowledge_for_agent,
)
from lib.learn.convention_observations import _integrate_observations
from lib.learn.convention_templates import (
    CONVENTION_TEMPLATES,
    _assign_confidence,
    _detect_evolution,
    _format_and_validate,
    _format_convention_text,
    _handle_conflicts,
    _pattern_to_entry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pat(
    ptype: str = "naming_snake",
    files: list[str] | None = None,
    scope: list[str] | None = None,
    adherence: float = 0.85,
    evidence: str = "10 of 12 identifiers use snake_case",
    obs: int = 0,
    trend: str = "stable",
) -> RawPattern:
    return RawPattern(
        type=ptype,
        files=files if files is not None else ["lib/foo.py", "lib/bar.py"],
        scope=scope if scope is not None else ["lib/"],
        adherence=adherence,
        evidence=evidence,
        observation_support=obs,
        recent_trend=trend,
    )


def _write_obs(obs_dir: Path, filename: str, observations: list[dict]) -> None:
    obs_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(o) for o in observations]
    (obs_dir / filename).write_text("\n".join(lines) + "\n")


def _violation(file: str) -> dict:
    return {"observation_type": "convention_violation", "detail": {"file": file}}


def _reviewer(file: str, category: str = "convention") -> dict:
    return {
        "observation_type": "reviewer_finding",
        "detail": {"category": category, "file": file},
    }


def _override(file: str, change_category: str = "convention") -> dict:
    return {
        "observation_type": "human_override",
        "detail": {"change_category": change_category, "file": file},
    }


# ═══════════════════════════════════════════════════════════════
# Phase B: Observation Integration
# ═══════════════════════════════════════════════════════════════


class TestPhaseB_ViolationSupport:
    """convention_violation observations increment observation_support."""

    def test_3_violations_matching_scope_increment_support(self, tmp_path):
        obs_dir = tmp_path / "observations"
        _write_obs(obs_dir, "f.jsonl", [
            _violation("lib/a.py"),
            _violation("lib/b.py"),
            _violation("lib/c.py"),
        ])
        pattern = _pat(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 3

    def test_violations_about_isinstance_increment_matching_pattern(self, tmp_path):
        """3 convention_violation observations about isinstance usage in scope."""
        obs_dir = tmp_path / "observations"
        _write_obs(obs_dir, "f.jsonl", [
            {"observation_type": "convention_violation",
             "detail": {"file": "lib/check.py", "description": "isinstance check"}},
            {"observation_type": "convention_violation",
             "detail": {"file": "lib/validate.py", "description": "isinstance usage"}},
            {"observation_type": "convention_violation",
             "detail": {"file": "lib/guard.py", "description": "isinstance pattern"}},
        ])
        pattern = _pat(ptype="naming_snake", scope=["lib/"], obs=0)
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 3


class TestPhaseB_HumanOverride:
    """human_override entries create new RawPattern with observation-derived evidence."""

    def test_2_overrides_create_new_pattern(self, tmp_path):
        obs_dir = tmp_path / "observations"
        _write_obs(obs_dir, "f.jsonl", [
            _override("src/http_client.py", "convention"),
            _override("src/api_wrapper.py", "convention"),
        ])
        result = _integrate_observations([], obs_dir)
        assert len(result) == 1
        assert result[0].evidence == "N/A — observation-derived"
        assert result[0].observation_support == 2
        assert result[0].adherence == 0.0


class TestPhaseB_EdgeCases:
    """Edge cases: empty dir, malformed JSONL."""

    def test_empty_observations_dir_returns_unchanged(self, tmp_path):
        obs_dir = tmp_path / "observations"
        obs_dir.mkdir()
        patterns = [_pat()]
        result = _integrate_observations(patterns, obs_dir)
        assert result[0] is patterns[0]

    def test_malformed_jsonl_skipped_valid_processed(self, tmp_path, caplog):
        """Malformed lines produce warnings; valid lines still processed."""
        obs_dir = tmp_path / "observations"
        obs_dir.mkdir(parents=True)
        valid_line = json.dumps(_violation("lib/x.py"))
        (obs_dir / "test.jsonl").write_text(
            "not json\n"
            + "{broken\n"
            + valid_line + "\n"
            + valid_line + "\n"
            + valid_line + "\n"
        )
        with caplog.at_level(logging.WARNING, logger="lib.learn.convention_observations"):
            result = _integrate_observations([_pat(scope=["lib/"])], obs_dir)

        assert result[0].observation_support == 3
        assert any("malformed" in r.message.lower() or "Skipping" in r.message
                    for r in caplog.records)


class TestPhaseB_ReviewerFinding:
    """reviewer_finding with category='convention' increments support."""

    def test_reviewer_convention_increments(self, tmp_path):
        obs_dir = tmp_path / "observations"
        _write_obs(obs_dir, "f.jsonl", [_reviewer("lib/foo.py", "convention")])
        pattern = _pat(scope=["lib/"])
        result = _integrate_observations([pattern], obs_dir)
        assert result[0].observation_support == 1


# ═══════════════════════════════════════════════════════════════
# Phase C: Templates and Validation
# ═══════════════════════════════════════════════════════════════


class TestPhaseC_Templates:
    """Template formatting for known pattern types."""

    def test_comodification_template(self):
        pattern = _pat(
            ptype="comodification",
            files=["lib/api.py", "lib/api_test.py"],
            scope=["lib/"],
            adherence=0.9,
        )
        text = _format_convention_text(CONVENTION_TEMPLATES["comodification"], pattern)
        assert "`lib/api.py`" in text
        assert "`lib/api_test.py`" in text
        assert "90%" in text

    def test_naming_snake_template_has_adherence(self):
        pattern = _pat(ptype="naming_snake", adherence=0.85)
        text = _format_convention_text(CONVENTION_TEMPLATES["naming_snake"], pattern)
        assert "85%" in text
        assert "snake_case" in text

    def test_naming_camel_template(self):
        pattern = _pat(ptype="naming_camel", adherence=0.78)
        text = _format_convention_text(CONVENTION_TEMPLATES["naming_camel"], pattern)
        assert "camelCase" in text
        assert "78%" in text

    def test_test_framework_template(self):
        pattern = _pat(
            ptype="test_framework",
            files=["tests/a.py", "tests/b.py"],
            scope=["tests/"],
            evidence="pytest detected in 8 of 10 test files",
        )
        text = _format_convention_text(CONVENTION_TEMPLATES["test_framework"], pattern)
        assert "pytest" in text

    def test_wrapper_module_template(self):
        pattern = _pat(
            ptype="wrapper_module",
            files=["lib/http_client.py", "lib/api/auth.py"],
            evidence="for httpx calls via wrapper",
        )
        text = _format_convention_text(CONVENTION_TEMPLATES["wrapper_module"], pattern)
        assert "httpx" in text

    def test_unknown_type_goes_to_candidates(self):
        pattern = _pat(ptype="totally_unknown_type")
        entries, candidates = _format_and_validate([pattern], [])
        discovered = [e for e in entries if e.source == "discovered"]
        assert len(discovered) == 0
        assert len(candidates) == 1
        assert candidates[0].evidence.get("rejection_reason") == "no_matching_template"


class TestPhaseC_QualityBar:
    """Quality bar rejections."""

    def test_generic_pattern_rejected_as_not_project_specific(self):
        pattern = _pat(evidence="Use meaningful names")
        entry = _pattern_to_entry(pattern, "Use meaningful names", "emerging")
        from lib.learn.convention_templates import _apply_quality_bar
        rejection = _apply_quality_bar(entry, pattern, [])
        assert rejection == "not_project_specific"

    def test_pattern_with_no_evidence_rejected(self):
        """Pattern with 0 files is rejected as not_evidenced."""
        pattern = _pat(files=[])
        entries, candidates = _format_and_validate([pattern], [])
        discovered = [e for e in entries if e.source == "discovered"]
        assert len(discovered) == 0
        assert len(candidates) == 1
        assert candidates[0].evidence.get("rejection_reason") == "not_evidenced"


class TestPhaseC_Confidence:
    """Confidence assignment via _assign_confidence (established, emerging, decaying)
    and conflict-path confidence via _handle_conflicts."""

    def test_established_92pct_obs2(self):
        assert _assign_confidence(_pat(adherence=0.92, obs=2)) == "established"

    def test_emerging_95pct_obs0_single_source(self):
        """95% adherence with 0 observations is emerging, not established."""
        assert _assign_confidence(_pat(adherence=0.95, obs=0)) == "emerging"

    def test_emerging_65pct_obs0(self):
        assert _assign_confidence(_pat(adherence=0.65, obs=0)) == "emerging"

    def test_decaying_trend_away(self):
        assert _assign_confidence(_pat(adherence=0.3, obs=0, trend="away")) == "decaying"

    def test_emerging_via_observation_path(self):
        """Low adherence but 3+ observations → emerging."""
        assert _assign_confidence(_pat(adherence=0.2, obs=3)) == "emerging"


class TestPhaseC_Evolution:
    """Evolution: old pattern away + new pattern toward in same scope."""

    def test_evolution_field_set_on_matching_pair(self):
        old_entry = _pattern_to_entry(
            _pat(ptype="naming_snake", scope=["lib/"], adherence=0.4, trend="away"),
            "Old snake convention", "decaying",
        )
        old_entry.evidence["recent_trend"] = "away"

        new_entry = _pattern_to_entry(
            _pat(ptype="naming_camel", scope=["lib/"], adherence=0.7, trend="toward"),
            "New camel convention", "emerging",
        )
        new_entry.evidence["recent_trend"] = "toward"

        _detect_evolution([old_entry, new_entry])

        assert old_entry.evolution is not None
        assert new_entry.evolution is not None
        assert old_entry.evolution["old_pattern"] == "Old snake convention"
        assert old_entry.evolution["new_pattern"] == "New camel convention"


class TestPhaseC_Conflicts:
    """Conflict detection and auto-resolution."""

    def test_conflict_neither_dominant_no_obs(self):
        a = _pattern_to_entry(
            _pat(ptype="naming_snake", scope=["src/"], adherence=0.5, obs=0),
            "Use snake_case in `src/`.", "emerging",
        )
        b = _pattern_to_entry(
            _pat(ptype="naming_snake", scope=["src/"], adherence=0.5, obs=0),
            "Use camelCase in `src/`.", "emerging",
        )
        b.tags = ["naming_snake"]

        entries = [a, b]
        candidates: list[ConventionEntry] = []
        conflicts = _handle_conflicts(entries, candidates)

        assert len(conflicts) >= 1
        assert conflicts[0]["status"] == "unresolved"
        assert len(candidates) == 2
        assert len(entries) == 0

    def test_conflict_auto_resolved_with_obs_evidence(self):
        winner = _pattern_to_entry(
            _pat(ptype="naming_camel", scope=["src/"], adherence=0.7, obs=3),
            "Use camelCase in `src/`.", "emerging",
        )
        loser = _pattern_to_entry(
            _pat(ptype="naming_camel", scope=["src/"], adherence=0.5, obs=0),
            "Use snake_case in `src/`.", "emerging",
        )

        entries = [winner, loser]
        candidates: list[ConventionEntry] = []
        conflicts = _handle_conflicts(entries, candidates)

        assert len(conflicts) == 0
        assert len(entries) == 2
        assert loser.confidence == "decaying"
        assert winner.confidence in ("emerging", "established")


# ═══════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════


class TestOrchestrator_ShouldRunDiscovery:
    """_should_run_discovery trigger logic."""

    def test_missing_meta_triggers_first_run(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        should_run, reason = _should_run_discovery(memory_dir, tmp_path)
        assert should_run is True
        assert reason == "first_run"

    def test_malformed_meta_triggers_first_run(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "conventions-meta.json").write_text("not json")
        should_run, reason = _should_run_discovery(memory_dir, tmp_path)
        assert should_run is True
        assert reason == "first_run"

    def test_empty_last_run_triggers_first_run(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "conventions-meta.json").write_text(json.dumps({"last_run": ""}))
        should_run, reason = _should_run_discovery(memory_dir, tmp_path)
        assert should_run is True
        assert reason == "first_run"

    def test_50_files_changed_triggers_files_changed(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "conventions-meta.json").write_text(
            json.dumps({"last_run": "2025-01-01T00:00:00+00:00"})
        )
        with patch("lib.learn.conventions._count_git_changes", return_value=50):
            should_run, reason = _should_run_discovery(memory_dir, tmp_path)
        assert should_run is True
        assert reason == "files_changed"

    def test_3_features_completed_triggers(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "conventions-meta.json").write_text(
            json.dumps({"last_run": "2025-01-01T00:00:00+00:00"})
        )
        with (
            patch("lib.learn.conventions._count_git_changes", return_value=10),
            patch("lib.learn.conventions._count_completed_features", return_value=3),
        ):
            should_run, reason = _should_run_discovery(memory_dir, tmp_path)
        assert should_run is True
        assert reason == "features_completed"

    def test_csg_restructured_triggers(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "conventions-meta.json").write_text(
            json.dumps({
                "last_run": "2025-01-01T00:00:00+00:00",
                "cluster_checksums": {"cluster-1": "oldchecksum1234"},
            })
        )
        with (
            patch("lib.learn.conventions._count_git_changes", return_value=0),
            patch("lib.learn.conventions._count_completed_features", return_value=0),
            patch(
                "lib.learn.conventions._get_current_cluster_checksums",
                return_value={"cluster-1": "newchecksum5678"},
            ),
        ):
            should_run, reason = _should_run_discovery(memory_dir, tmp_path)
        assert should_run is True
        assert reason == "csg_restructured"

    def test_5_violations_triggers_violations_threshold(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "conventions-meta.json").write_text(
            json.dumps({"last_run": "2025-01-01T00:00:00+00:00"})
        )
        with (
            patch("lib.learn.conventions._count_git_changes", return_value=0),
            patch("lib.learn.conventions._count_completed_features", return_value=0),
            patch(
                "lib.learn.conventions._get_current_cluster_checksums",
                return_value={},
            ),
            patch("lib.learn.conventions._count_convention_violations", return_value=5),
        ):
            should_run, reason = _should_run_discovery(memory_dir, tmp_path)
        assert should_run is True
        assert reason == "violations_threshold"

    def test_no_trigger_returns_false(self, tmp_path):
        """All conditions below threshold returns (False, '')."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "conventions-meta.json").write_text(
            json.dumps({"last_run": "2025-01-01T00:00:00+00:00"})
        )
        with (
            patch("lib.learn.conventions._count_git_changes", return_value=0),
            patch("lib.learn.conventions._count_completed_features", return_value=0),
            patch(
                "lib.learn.conventions._get_current_cluster_checksums",
                return_value={},
            ),
            patch("lib.learn.conventions._count_convention_violations", return_value=0),
        ):
            should_run, reason = _should_run_discovery(memory_dir, tmp_path)
        assert should_run is False
        assert reason == ""


class TestOrchestrator_DiscoverConventions:
    """discover_conventions on a synthetic project produces valid output files."""

    def test_produces_valid_output_files(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Mock all Phase A extractors and Phase 0 config to return minimal data
        mock_patterns = [
            _pat(
                ptype="naming_snake",
                files=["lib/a.py", "lib/b.py"],
                scope=["lib/"],
                adherence=0.92,
                obs=2,
            ),
        ]

        with (
            patch(
                "lib.learn.convention_configs._extract_config_conventions",
                return_value=[],
            ),
            patch(
                "lib.learn.convention_extractors._extract_comodification",
                return_value=[],
            ),
            patch(
                "lib.learn.convention_extractors._extract_imports_and_naming",
                return_value=mock_patterns,
            ),
            patch(
                "lib.learn.convention_extractors._extract_import_graph",
                return_value=[],
            ),
            patch(
                "lib.learn.convention_extractors._extract_dependency_usage",
                return_value=[],
            ),
        ):
            result = discover_conventions(
                project_root, memory_dir, csg_path=None, incremental=False
            )

        assert isinstance(result, ConventionResult)
        assert len(result.conventions) >= 1

        # Check output files were written
        assert (memory_dir / "conventions.json").exists()
        assert (memory_dir / "conventions-meta.json").exists()
        assert (memory_dir / "conventions-candidates.json").exists()

        # Validate JSON structure
        conv_data = json.loads((memory_dir / "conventions.json").read_text())
        assert "conventions" in conv_data
        assert "views" in conv_data

        meta_data = json.loads((memory_dir / "conventions-meta.json").read_text())
        assert "last_run" in meta_data
        assert "convention_count" in meta_data
        assert "files_analyzed" in meta_data
        assert "trigger" in meta_data


class TestOrchestrator_FormatConventions:
    """format_conventions_for_agent filtering and budget."""

    def test_missing_file_returns_empty(self, tmp_path):
        result = format_conventions_for_agent(
            tmp_path / "nonexistent.json", "developer", ["lib/foo.py"]
        )
        assert result == ""

    def test_filters_by_task_files(self, tmp_path):
        conventions_data = {
            "conventions": [],
            "views": {
                "developer": [
                    {"id": "c1", "text": "- Use snake_case in lib/", "scope": ["lib/"]},
                    {"id": "c2", "text": "- Use camelCase in src/", "scope": ["src/"]},
                ],
            },
        }
        path = tmp_path / "conventions.json"
        path.write_text(json.dumps(conventions_data))

        result = format_conventions_for_agent(path, "developer", ["lib/foo.py"])
        assert "snake_case" in result
        assert "camelCase" not in result

    def test_respects_token_budget(self, tmp_path):
        # Each entry ~50 chars → ~12 tokens. Create enough to exceed 2000-token budget.
        entries = []
        for i in range(300):
            entries.append({
                "id": f"c{i}",
                "text": f"- Convention rule number {i} " + "x" * 40,
                "scope": ["lib/"],
            })
        conventions_data = {"conventions": [], "views": {"developer": entries}}
        path = tmp_path / "conventions.json"
        path.write_text(json.dumps(conventions_data))

        result = format_conventions_for_agent(path, "developer", ["lib/foo.py"])
        # Should be truncated well under 300 entries
        lines = result.strip().split("\n")
        assert len(lines) < 300

    def test_root_scope_matches_everything(self, tmp_path):
        conventions_data = {
            "conventions": [],
            "views": {
                "developer": [
                    {"id": "c1", "text": "- Global rule", "scope": ["."]},
                ],
            },
        }
        path = tmp_path / "conventions.json"
        path.write_text(json.dumps(conventions_data))

        result = format_conventions_for_agent(path, "developer", ["anywhere/file.py"])
        assert "Global rule" in result


class TestOrchestrator_FormatKnowledge:
    """format_knowledge_for_agent with agent and applies_to filtering."""

    def test_filters_by_agent(self, tmp_path):
        knowledge = {
            "entries": [
                {"why_it_matters": "Dev only", "knowledge": "For developers", "agents": ["developer"], "applies_to": []},
                {"why_it_matters": "Review only", "knowledge": "For reviewers", "agents": ["reviewer"], "applies_to": []},
            ],
        }
        path = tmp_path / "project-knowledge.json"
        path.write_text(json.dumps(knowledge))

        result = format_knowledge_for_agent(path, "developer", ["lib/foo.py"])
        assert "Dev only" in result
        assert "Review only" not in result

    def test_empty_agents_matches_all(self, tmp_path):
        knowledge = {
            "entries": [
                {"why_it_matters": "Global", "knowledge": "For everyone", "agents": [], "applies_to": []},
            ],
        }
        path = tmp_path / "project-knowledge.json"
        path.write_text(json.dumps(knowledge))

        result = format_knowledge_for_agent(path, "architect", ["lib/foo.py"])
        assert "Global" in result

    def test_applies_to_glob_support(self, tmp_path):
        knowledge = {
            "entries": [
                {"why_it_matters": "Python only", "knowledge": "For .py files", "agents": [], "applies_to": ["*.py"]},
                {"why_it_matters": "JS only", "knowledge": "For .js files", "agents": [], "applies_to": ["*.js"]},
            ],
        }
        path = tmp_path / "project-knowledge.json"
        path.write_text(json.dumps(knowledge))

        result = format_knowledge_for_agent(path, "developer", ["lib/foo.py"])
        assert "Python only" in result
        assert "JS only" not in result

    def test_respects_token_budget(self, tmp_path):
        """Knowledge output is truncated at the 1500-token budget."""
        entries = []
        for i in range(300):
            entries.append({
                "why_it_matters": f"Rule {i}",
                "knowledge": f"Knowledge entry {i} " + "y" * 60,
                "agents": [],
                "applies_to": [],
            })
        knowledge = {"entries": entries}
        path = tmp_path / "project-knowledge.json"
        path.write_text(json.dumps(knowledge))

        result = format_knowledge_for_agent(path, "developer", ["lib/foo.py"])
        lines = result.strip().split("\n")
        assert len(lines) < 300

    def test_missing_file_returns_empty(self, tmp_path):
        result = format_knowledge_for_agent(
            tmp_path / "nonexistent.json", "developer", ["lib/foo.py"]
        )
        assert result == ""
