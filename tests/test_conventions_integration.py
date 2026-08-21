#!/usr/bin/env python3
"""Integration tests for the conventions pipeline: assembly injection,
empty/missing params, graceful degradation, token budgets, and backward
compatibility.

Covers the full chain from convention/knowledge strings through assembly
functions to final prompt output. All tests use minimal fixtures with no
real project directories required.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.context.assembly import (
    assemble_architect,
    assemble_developer,
    assemble_reviewer,
)
from lib.context.utils import estimate_tokens_from_text
from lib.learn.conventions import (
    format_conventions_for_agent,
    format_knowledge_for_agent,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONVENTIONS = (
    "- **[established]** Use snake_case for Python identifiers\n"
    "- **[established]** Enforce import ordering (isort via ruff)\n"
    "- **[emerging]** Prefer pathlib over os.path"
)

SAMPLE_KNOWLEDGE = (
    "- **Performance-critical path**: The hot loop in lib/engine.py "
    "must not allocate on every iteration\n"
    "- **API stability**: Public endpoints under /api/v1 are frozen"
)

MINIMAL_TASK = {
    "id": "42",
    "title": "Add widget validation",
    "description": "Validate widgets before persisting them.",
    "acceptance_criteria": ["Widgets must be validated", "Invalid widgets rejected"],
}

MINIMAL_CODE_CONTEXT = {"full_content": {}, "skeleton": {}}
MINIMAL_TASK_CONTEXT = {"upstream": [], "downstream": []}
MINIMAL_SPEC_CONTEXT = {"relevant_spec_sections": []}

MINIMAL_PROJECT_MAP = {
    "summary": {"total_files": 10, "total_lines": 1000, "by_language": {}},
    "directories": [],
}

MINIMAL_CSG = {"clusters": [], "nodes": [], "edges": [], "cluster_edges": []}


# ===========================================================================
# 1. Assembly injection: section headers appear in output
# ===========================================================================


class TestDeveloperAssemblyInjection:
    """assemble_developer includes convention and knowledge sections."""

    def test_conventions_section_present(self):
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions=SAMPLE_CONVENTIONS,
        )
        assert "### Project Conventions" in result
        assert "snake_case" in result

    def test_knowledge_section_present(self):
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            project_knowledge=SAMPLE_KNOWLEDGE,
        )
        assert "### Project Knowledge" in result
        assert "Performance-critical path" in result

    def test_both_sections_present(self):
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions=SAMPLE_CONVENTIONS,
            project_knowledge=SAMPLE_KNOWLEDGE,
        )
        assert "### Project Conventions" in result
        assert "### Project Knowledge" in result

    def test_section_ordering_conventions_before_knowledge(self):
        """Conventions appear before knowledge in output."""
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions=SAMPLE_CONVENTIONS,
            project_knowledge=SAMPLE_KNOWLEDGE,
            learnings="Some learnings here",
        )
        conv_pos = result.index("### Project Conventions")
        know_pos = result.index("### Project Knowledge")
        learn_pos = result.index("### Learned Patterns")
        assert conv_pos < know_pos < learn_pos

    def test_learnings_section_present(self):
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            learnings="Pattern: always add tests",
        )
        assert "### Learned Patterns" in result


class TestReviewerAssemblyInjection:
    """assemble_reviewer includes convention checklist and knowledge sections."""

    def test_convention_checklist_present(self):
        result = assemble_reviewer(
            task=MINIMAL_TASK,
            diff="diff --git a/foo.py b/foo.py\n+hello",
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions=SAMPLE_CONVENTIONS,
        )
        assert "### Convention Checklist" in result
        assert "snake_case" in result

    def test_knowledge_section_present(self):
        result = assemble_reviewer(
            task=MINIMAL_TASK,
            diff="diff --git a/foo.py b/foo.py\n+hello",
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            project_knowledge=SAMPLE_KNOWLEDGE,
        )
        assert "### Project Knowledge" in result

    def test_section_ordering_conventions_before_knowledge(self):
        result = assemble_reviewer(
            task=MINIMAL_TASK,
            diff="diff --git a/foo.py b/foo.py\n+hello",
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions=SAMPLE_CONVENTIONS,
            project_knowledge=SAMPLE_KNOWLEDGE,
            learnings="Calibration data here",
        )
        conv_pos = result.index("### Convention Checklist")
        know_pos = result.index("### Project Knowledge")
        learn_pos = result.index("### Review Calibration")
        assert conv_pos < know_pos < learn_pos


class TestArchitectAssemblyInjection:
    """assemble_architect includes structural conventions and knowledge sections."""

    def test_structural_conventions_present(self):
        result = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
            conventions=SAMPLE_CONVENTIONS,
        )
        assert "### Structural Conventions" in result
        assert "snake_case" in result

    def test_knowledge_section_present(self):
        result = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
            project_knowledge=SAMPLE_KNOWLEDGE,
        )
        assert "### Project Knowledge" in result

    def test_section_ordering(self):
        result = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
            conventions=SAMPLE_CONVENTIONS,
            project_knowledge=SAMPLE_KNOWLEDGE,
            learnings="History notes",
        )
        conv_pos = result.index("### Structural Conventions")
        know_pos = result.index("### Project Knowledge")
        learn_pos = result.index("### Project History")
        assert conv_pos < know_pos < learn_pos


# ===========================================================================
# 2. Empty params: sections omitted entirely
# ===========================================================================


class TestEmptyParams:
    """Empty string conventions/project_knowledge produce no extra sections."""

    def test_developer_empty_conventions_omits_section(self):
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions="",
        )
        assert "### Project Conventions" not in result

    def test_developer_empty_knowledge_omits_section(self):
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            project_knowledge="",
        )
        assert "### Project Knowledge" not in result

    def test_reviewer_empty_conventions_omits_section(self):
        result = assemble_reviewer(
            task=MINIMAL_TASK,
            diff="",
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions="",
        )
        assert "### Convention Checklist" not in result

    def test_reviewer_empty_knowledge_omits_section(self):
        result = assemble_reviewer(
            task=MINIMAL_TASK,
            diff="",
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            project_knowledge="",
        )
        assert "### Project Knowledge" not in result

    def test_architect_empty_conventions_omits_section(self):
        result = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
            conventions="",
        )
        assert "### Structural Conventions" not in result

    def test_architect_empty_knowledge_omits_section(self):
        result = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
            project_knowledge="",
        )
        assert "### Project Knowledge" not in result


# ===========================================================================
# 3. Graceful degradation: None, missing args, malformed input
# ===========================================================================


class TestGracefulDegradation:
    """Functions don't crash with None or unexpected input types."""

    def test_developer_none_conventions_no_crash(self):
        """None is falsy, so the section is skipped just like empty string."""
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions=None,
        )
        assert "### Project Conventions" not in result
        assert "## Task:" in result

    def test_developer_none_knowledge_no_crash(self):
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            project_knowledge=None,
        )
        assert "### Project Knowledge" not in result

    def test_reviewer_none_params_no_crash(self):
        result = assemble_reviewer(
            task=MINIMAL_TASK,
            diff="",
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions=None,
            project_knowledge=None,
        )
        assert "## Review:" in result

    def test_architect_none_params_no_crash(self):
        result = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
            conventions=None,
            project_knowledge=None,
        )
        assert "## Codebase Context" in result

    def test_format_conventions_missing_file(self, tmp_path):
        """Missing conventions.json returns empty string."""
        result = format_conventions_for_agent(
            tmp_path / "nonexistent.json", "developer", ["lib/foo.py"]
        )
        assert result == ""

    def test_format_conventions_malformed_json(self, tmp_path):
        """Malformed JSON returns empty string."""
        bad_file = tmp_path / "conventions.json"
        bad_file.write_text("{not valid json")
        result = format_conventions_for_agent(bad_file, "developer", ["lib/foo.py"])
        assert result == ""

    def test_format_knowledge_missing_file(self, tmp_path):
        result = format_knowledge_for_agent(
            tmp_path / "nonexistent.json", "developer", ["lib/foo.py"]
        )
        assert result == ""

    def test_format_knowledge_malformed_json(self, tmp_path):
        bad_file = tmp_path / "knowledge.json"
        bad_file.write_text("<<<broken>>>")
        result = format_knowledge_for_agent(bad_file, "developer", ["lib/foo.py"])
        assert result == ""

    def test_format_knowledge_agent_not_in_entries(self, tmp_path):
        """Agent not listed in any entry returns empty string."""
        knowledge_file = tmp_path / "project-knowledge.json"
        knowledge_file.write_text(json.dumps({
            "entries": [
                {
                    "knowledge": "Only for architects",
                    "agents": ["architect"],
                    "applies_to": [],
                    "why_it_matters": "Structural concern",
                }
            ]
        }))
        result = format_knowledge_for_agent(knowledge_file, "developer", ["lib/foo.py"])
        assert result == ""

    def test_developer_empty_task_dict(self):
        """Assembly handles a near-empty task dict without crashing."""
        result = assemble_developer(
            task={},
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        assert isinstance(result, str)
        assert len(result) > 0


# ===========================================================================
# 4. Token budget: conventions reduce available budget
# ===========================================================================


class TestTokenBudget:
    """Conventions/knowledge text reduces the token budget for remaining content."""

    def test_developer_budget_reduced_by_conventions(self):
        """With large conventions, remaining output is constrained."""
        # Generate a large conventions string (~20k tokens = ~80k chars)
        large_conventions = "\n".join(
            f"- **[established]** Convention rule number {i}: "
            f"{'x' * 200}" for i in range(300)
        )
        large_tokens = estimate_tokens_from_text(large_conventions)
        assert large_tokens > 15000, "Test setup: conventions should be large"

        result_with = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions=large_conventions,
        )
        result_without = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        # The conventions text is included in the output, so the result
        # with conventions is larger, but the budget is consumed.
        assert "### Project Conventions" in result_with
        tokens_with = estimate_tokens_from_text(result_with)
        # Output should stay within the default developer budget (80k tokens)
        assert tokens_with <= 85000

    def test_architect_budget_reduced_by_knowledge(self):
        large_knowledge = "\n".join(
            f"- **Fact {i}**: {'y' * 200}" for i in range(300)
        )
        result = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
            project_knowledge=large_knowledge,
        )
        tokens = estimate_tokens_from_text(result)
        # Architect default budget is 60k tokens
        assert tokens <= 65000

    def test_format_conventions_truncates_large_views(self, tmp_path):
        """format_conventions_for_agent enforces a 2000-token internal budget."""
        # Build a conventions.json with many view entries scoped to "."
        entries = []
        for i in range(500):
            entries.append({
                "id": f"conv-{i}",
                "text": f"- **[established]** Rule {i}: {'z' * 100}",
                "scope": ["."],
            })
        data = {
            "conventions": [],
            "conflicts": [],
            "views": {"developer": entries},
        }
        conv_file = tmp_path / "conventions.json"
        conv_file.write_text(json.dumps(data))

        result = format_conventions_for_agent(
            conv_file, "developer", ["lib/foo.py"]
        )
        tokens = estimate_tokens_from_text(result)
        assert tokens <= 2100  # slightly above 2000 for line boundary

    def test_format_knowledge_truncates_large_entries(self, tmp_path):
        """format_knowledge_for_agent enforces a 1500-token internal budget."""
        entries = []
        for i in range(500):
            entries.append({
                "knowledge": f"Important fact {i}: {'w' * 100}",
                "agents": [],
                "applies_to": [],
                "why_it_matters": f"Reason {i}",
            })
        data = {"entries": entries}
        know_file = tmp_path / "project-knowledge.json"
        know_file.write_text(json.dumps(data))

        result = format_knowledge_for_agent(
            know_file, "developer", ["lib/foo.py"]
        )
        tokens = estimate_tokens_from_text(result)
        assert tokens <= 1600


# ===========================================================================
# 5. Backward compatibility: no params = same as empty strings
# ===========================================================================


class TestBackwardCompatibility:
    """Calling assembly without conventions/project_knowledge params produces
    the same output as calling with empty strings."""

    def test_developer_default_equals_empty(self):
        result_default = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        result_empty = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions="",
            project_knowledge="",
            learnings="",
        )
        assert result_default == result_empty

    def test_reviewer_default_equals_empty(self):
        result_default = assemble_reviewer(
            task=MINIMAL_TASK,
            diff="some diff content",
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        result_empty = assemble_reviewer(
            task=MINIMAL_TASK,
            diff="some diff content",
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            conventions="",
            project_knowledge="",
            learnings="",
        )
        assert result_default == result_empty

    def test_architect_default_equals_empty(self):
        result_default = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
        )
        result_empty = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
            conventions="",
            project_knowledge="",
            learnings="",
        )
        assert result_default == result_empty


# ===========================================================================
# 6. Scope filtering: conventions and knowledge scope matching
# ===========================================================================


class TestScopeFiltering:
    """Scope and applies_to filtering works correctly."""

    def test_convention_scoped_to_lib_matches_lib_file(self, tmp_path):
        """Convention with scope=['lib/'] appears when task_files include lib/."""
        data = {
            "conventions": [],
            "conflicts": [],
            "views": {
                "developer": [
                    {
                        "id": "conv-scoped",
                        "text": "- **[established]** Use snake_case in lib/",
                        "scope": ["lib/"],
                    }
                ]
            },
        }
        conv_file = tmp_path / "conventions.json"
        conv_file.write_text(json.dumps(data))

        result = format_conventions_for_agent(
            conv_file, "developer", ["lib/models.py"]
        )
        assert "snake_case" in result

    def test_convention_scoped_to_lib_absent_for_tests_file(self, tmp_path):
        """Convention with scope=['lib/'] does NOT appear for tests/ files."""
        data = {
            "conventions": [],
            "conflicts": [],
            "views": {
                "developer": [
                    {
                        "id": "conv-scoped",
                        "text": "- **[established]** Lib-only rule",
                        "scope": ["lib/"],
                    }
                ]
            },
        }
        conv_file = tmp_path / "conventions.json"
        conv_file.write_text(json.dumps(data))

        result = format_conventions_for_agent(
            conv_file, "developer", ["tests/test_foo.py"]
        )
        assert result == ""

    def test_knowledge_applies_to_specific_file(self, tmp_path):
        data = {
            "entries": [
                {
                    "knowledge": "Payments API has rate limits",
                    "agents": [],
                    "applies_to": ["lib/api/payments.py"],
                    "why_it_matters": "Rate limiting",
                }
            ]
        }
        know_file = tmp_path / "project-knowledge.json"
        know_file.write_text(json.dumps(data))

        matched = format_knowledge_for_agent(
            know_file, "developer", ["lib/api/payments.py"]
        )
        assert "rate limits" in matched.lower()

        unmatched = format_knowledge_for_agent(
            know_file, "developer", ["lib/api/users.py"]
        )
        assert unmatched == ""

    def test_knowledge_agent_filter(self, tmp_path):
        """Entry with agents=['developer'] does not appear for reviewer."""
        data = {
            "entries": [
                {
                    "knowledge": "Developer-only guidance",
                    "agents": ["developer"],
                    "applies_to": [],
                    "why_it_matters": "Dev hint",
                }
            ]
        }
        know_file = tmp_path / "project-knowledge.json"
        know_file.write_text(json.dumps(data))

        dev_result = format_knowledge_for_agent(
            know_file, "developer", ["lib/foo.py"]
        )
        assert "Developer-only" in dev_result

        rev_result = format_knowledge_for_agent(
            know_file, "reviewer", ["lib/foo.py"]
        )
        assert rev_result == ""

    def test_knowledge_glob_expansion(self, tmp_path):
        """fnmatch glob in applies_to matches task files."""
        data = {
            "entries": [
                {
                    "knowledge": "All API files need auth headers",
                    "agents": [],
                    "applies_to": ["lib/api/*.py"],
                    "why_it_matters": "Auth requirement",
                }
            ]
        }
        know_file = tmp_path / "project-knowledge.json"
        know_file.write_text(json.dumps(data))

        matched = format_knowledge_for_agent(
            know_file, "developer", ["lib/api/client.py"]
        )
        assert "auth headers" in matched.lower()

        unmatched = format_knowledge_for_agent(
            know_file, "developer", ["lib/models/user.py"]
        )
        assert unmatched == ""

    def test_knowledge_empty_agents_matches_all(self, tmp_path):
        """Entry with empty agents list applies to every agent."""
        data = {
            "entries": [
                {
                    "knowledge": "Global fact",
                    "agents": [],
                    "applies_to": [],
                    "why_it_matters": "Universal",
                }
            ]
        }
        know_file = tmp_path / "project-knowledge.json"
        know_file.write_text(json.dumps(data))

        for agent in ("developer", "reviewer", "architect"):
            result = format_knowledge_for_agent(
                know_file, agent, ["lib/foo.py"]
            )
            assert "Global fact" in result

    def test_root_scope_convention_matches_everything(self, tmp_path):
        """Convention with scope=['.'] matches any task file."""
        data = {
            "conventions": [],
            "conflicts": [],
            "views": {
                "developer": [
                    {
                        "id": "conv-global",
                        "text": "- **[established]** Global rule",
                        "scope": ["."],
                    }
                ]
            },
        }
        conv_file = tmp_path / "conventions.json"
        conv_file.write_text(json.dumps(data))

        for task_file in ("lib/foo.py", "tests/bar.py", "scripts/deploy.sh"):
            result = format_conventions_for_agent(
                conv_file, "developer", [task_file]
            )
            assert "Global rule" in result
