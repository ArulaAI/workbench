"""Unit tests for lib/context/repository_digest_extras.py — the Phase 2
additions (coverage stats, entrypoints, annotated tree, reading path,
read-only team-knowledge projection). Pure functions, synthetic inputs,
no full build required.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from lib.context.repository_digest_extras import (
    derive_coverage_stats,
    derive_entrypoints,
    derive_annotated_tree,
    derive_reading_path,
    load_pending_knowledge,
    project_knowledge_to_digest_entries,
)


# ── derive_coverage_stats ──────────────────────────────────────


class TestDeriveCoverageStats:
    def test_computes_percentage_from_real_fields(self):
        build_summary = {"extraction_stats": {"files_parsed": 139, "source_files_total": 150, "total_definitions": 500, "total_references": 1200}}
        stats = derive_coverage_stats(build_summary)
        assert stats is not None
        assert stats["source_files_total"] == 150
        assert stats["source_files_parsed"] == 139
        assert stats["parse_coverage_pct"] == round(139 / 150 * 100, 1)
        assert stats["symbols_extracted"] == 500
        assert stats["references_extracted"] == 1200

    def test_missing_build_summary_returns_none_not_zero(self):
        assert derive_coverage_stats(None) is None

    def test_build_summary_without_extraction_stats_returns_none(self):
        assert derive_coverage_stats({"status": "built"}) is None

    def test_old_build_summary_missing_source_files_total_returns_none(self):
        """An old build-summary.json (predating this field) must not be
        misread as 0/0 or crash — it genuinely has no coverage claim.
        """
        old_shape = {"extraction_stats": {"files_parsed": 100, "total_definitions": 50, "total_references": 10}}
        assert derive_coverage_stats(old_shape) is None

    def test_zero_source_files_does_not_divide_by_zero(self):
        stats = derive_coverage_stats({"extraction_stats": {"files_parsed": 0, "source_files_total": 0}})
        assert stats is not None
        assert stats["parse_coverage_pct"] is None

    def test_malformed_input_types_return_none(self):
        assert derive_coverage_stats("not a dict") is None
        assert derive_coverage_stats({"extraction_stats": "not a dict"}) is None


# ── derive_entrypoints ──────────────────────────────────────────


class TestDeriveEntrypoints:
    def test_finds_file_named_in_a_run_command(self):
        commands = [{"purpose": "run", "command": "python app.py"}]
        project_map = {"files": [{"path": "app.py"}, {"path": "other.py"}]}
        entrypoints = derive_entrypoints(commands, project_map)
        assert entrypoints == [{"name": "app.py", "file": "app.py", "kind": "run"}]

    def test_resolves_by_unambiguous_basename_when_full_path_in_command_differs(self):
        commands = [{"purpose": "develop", "command": "node server.js"}]
        project_map = {"files": [{"path": "client/server.js"}]}
        entrypoints = derive_entrypoints(commands, project_map)
        assert entrypoints == [{"name": "server.js", "file": "client/server.js", "kind": "develop"}]

    def test_ambiguous_basename_is_not_resolved(self):
        commands = [{"purpose": "run", "command": "python main.py"}]
        project_map = {"files": [{"path": "a/main.py"}, {"path": "b/main.py"}]}
        assert derive_entrypoints(commands, project_map) == []

    def test_file_named_in_command_but_not_in_project_map_is_ignored(self):
        commands = [{"purpose": "run", "command": "python missing.py"}]
        project_map = {"files": [{"path": "app.py"}]}
        assert derive_entrypoints(commands, project_map) == []

    def test_non_run_develop_purposes_are_ignored(self):
        commands = [{"purpose": "test", "command": "pytest app.py"}]
        project_map = {"files": [{"path": "app.py"}]}
        assert derive_entrypoints(commands, project_map) == []

    def test_no_commands_returns_empty(self):
        assert derive_entrypoints([], {"files": []}) == []

    def test_missing_files_key_in_project_map_does_not_crash(self):
        assert derive_entrypoints([{"purpose": "run", "command": "python app.py"}], {}) == []


# ── derive_annotated_tree ────────────────────────────────────────


class TestDeriveAnnotatedTree:
    def test_top_level_directories_only(self):
        project_map = {"directories": [
            {"path": "lib", "file_count": 10, "total_lines": 500},
            {"path": "lib/context", "file_count": 5, "total_lines": 200},
            {"path": "tests", "file_count": 3, "total_lines": 100},
        ]}
        tree = derive_annotated_tree(project_map, None, [])
        paths = {d["path"] for d in tree}
        assert paths == {"lib", "tests"}

    def test_sorted_by_file_count_descending(self):
        project_map = {"directories": [
            {"path": "small", "file_count": 1, "total_lines": 10},
            {"path": "big", "file_count": 100, "total_lines": 5000},
        ]}
        tree = derive_annotated_tree(project_map, None, [])
        assert [d["path"] for d in tree] == ["big", "small"]

    def test_annotates_with_dominant_domain_label(self):
        project_map = {"directories": [{"path": "lib", "file_count": 2, "total_lines": 100}]}
        csg = {"clusters": [{"id": "c0", "files": ["lib/a.py", "lib/b.py"]}]}
        domains = [{"id": "c0", "label": "Core"}]
        tree = derive_annotated_tree(project_map, csg, domains)
        assert tree[0]["dominant_domain_label"] == "Core"

    def test_directory_with_no_matching_domain_is_unannotated_not_guessed(self):
        project_map = {"directories": [{"path": "scripts", "file_count": 1, "total_lines": 10}]}
        tree = derive_annotated_tree(project_map, {"clusters": []}, [])
        assert tree[0]["dominant_domain_label"] is None

    def test_no_directories_returns_empty(self):
        assert derive_annotated_tree({}, None, []) == []


# ── derive_reading_path ──────────────────────────────────────────


class TestDeriveReadingPath:
    def test_orders_documentation_manifest_entrypoint_domain(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        identity = {"evidence": [{"source": "documentation", "path": "README.md"}]}
        entrypoints = [{"file": "app.py", "kind": "run"}]
        domains = [{"id": "c0", "label": "Core", "rank": 1, "representative_files": ["lib/core.py"]}]
        path = derive_reading_path(tmp_path, identity, entrypoints, domains)
        files = [p["file"] for p in path]
        assert files == ["README.md", "package.json", "app.py", "lib/core.py"]

    def test_every_item_carries_a_reason(self, tmp_path):
        identity = {"evidence": [{"source": "documentation", "path": "README.md"}]}
        path = derive_reading_path(tmp_path, identity, [], [])
        assert all(item["reason"] for item in path)

    def test_deterministic_across_repeated_calls(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'")
        identity = {"evidence": [{"source": "documentation", "path": "README.md"}]}
        entrypoints = [{"file": "app.py", "kind": "run"}, {"file": "worker.py", "kind": "run"}]
        domains = [{"id": "c0", "label": "Core", "rank": 2, "representative_files": ["lib/b.py"]},
                   {"id": "c1", "label": "Util", "rank": 1, "representative_files": ["lib/a.py"]}]
        first = derive_reading_path(tmp_path, identity, entrypoints, domains)
        second = derive_reading_path(tmp_path, identity, entrypoints, domains)
        assert first == second
        # rank 1 ("Util") must win over rank 2 ("Core") — proves it sorts
        # by rank rather than trusting caller order.
        assert first[-1]["file"] == "lib/a.py"

    def test_no_evidence_at_all_returns_empty_not_a_guess(self, tmp_path):
        identity = {"evidence": []}
        assert derive_reading_path(tmp_path, identity, [], []) == []

    def test_missing_documentation_evidence_falls_through_to_manifest(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]\nname='x'")
        identity = {"evidence": [{"source": "manifest", "path": "Cargo.toml"}]}
        path = derive_reading_path(tmp_path, identity, [], [])
        assert path == [{"file": "Cargo.toml", "reason": path[0]["reason"], "kind": "manifest"}]


# ── Team knowledge (read-only projection) ─────────────────────────


class TestLoadPendingKnowledge:
    def test_extracts_from_flat_list(self):
        raw = [{"id": "d1", "knowledge": "K1", "why_it_matters": "W1", "applies_to": ["a.py"], "source": "seeded", "draft_reason": "r1"}]
        drafts = load_pending_knowledge(raw)
        assert drafts == [{"id": "d1", "knowledge": "K1", "why_it_matters": "W1", "applies_to": ["a.py"], "source": "seeded", "draft_reason": "r1"}]

    def test_missing_or_none_returns_empty(self):
        assert load_pending_knowledge(None) == []
        assert load_pending_knowledge([]) == []

    def test_malformed_entries_without_id_are_skipped_not_crashed(self):
        raw = [{"knowledge": "no id here"}, {"id": "d2", "knowledge": "K2"}]
        drafts = load_pending_knowledge(raw)
        assert len(drafts) == 1
        assert drafts[0]["id"] == "d2"

    def test_completely_wrong_shape_returns_empty(self):
        assert load_pending_knowledge("not a list or dict") == []
        assert load_pending_knowledge(42) == []


class TestProjectKnowledgeToDigestEntries:
    def test_projects_known_fields_only(self):
        entries = [{"id": "pk-1", "knowledge": "K", "why_it_matters": "W", "applies_to": ["x"], "last_verified": "2026-01-01", "staleness_flag": "", "internal_field": "should not leak"}]
        result = project_knowledge_to_digest_entries(entries)
        assert result == [{"id": "pk-1", "knowledge": "K", "why_it_matters": "W", "applies_to": ["x"], "last_verified": "2026-01-01", "staleness_flag": ""}]

    def test_empty_list_returns_empty(self):
        assert project_knowledge_to_digest_entries([]) == []
