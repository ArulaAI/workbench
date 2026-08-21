#!/usr/bin/env python3
"""Integration tests for learnings injection into assembly functions.

Verifies that each assembly function accepts the learnings parameter,
renders the correct section header, and subtracts learnings tokens
from the context budget.
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "lib"))

from lib.context.assembly import (
    assemble_architect,
    assemble_coherence,
    assemble_debugger,
    assemble_developer,
    assemble_reviewer,
)


# ── Minimal fixtures ─────────────────────────────────────────────────

LEARNINGS_TEXT = (
    "- **retry** on `lib/cmd/plan.sh`: reason=\"timeout\"\n"
    "- **drift** on `lib/shared.sh`: description=\"scope creep\""
)

MINIMAL_PROJECT_MAP = {
    "summary": {"total_files": 10, "total_lines": 500, "by_language": {}},
    "directories": [],
    "files": [],
}

MINIMAL_CSG = {"clusters": [], "bridge_symbols": []}

MINIMAL_TASK = {
    "id": "T1",
    "title": "Add login endpoint",
    "description": "Implement POST /login",
    "files_to_modify": ["lib/auth.py"],
    "acceptance_criteria": [],
}

MINIMAL_CODE_CONTEXT = {
    "full_content": {"files_touched": []},
    "skeleton_content": {"high_relevance": []},
}

MINIMAL_TASK_CONTEXT = {"upstream": [], "downstream": []}

MINIMAL_SPEC_CONTEXT = {"relevant_sections": []}

MINIMAL_BUDGET = {
    "total_budget": 50000,
    "allocated": {},
}

MINIMAL_CROSS_TASK = {
    "domain_overlap": [],
    "interface_boundaries": [],
    "high_impact_modifications": [],
}


# ── Architect ─────────────────────────────────────────────────────────


class TestArchitectInjection:
    def test_learnings_rendered(self):
        result = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
            learnings=LEARNINGS_TEXT,
        )
        assert "### Project History" in result
        assert "**retry**" in result
        assert "reason=\"timeout\"" in result

    def test_no_learnings_no_section(self):
        result = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
        )
        assert "### Project History" not in result

    def test_empty_learnings_no_section(self):
        result = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg=MINIMAL_CSG,
            learnings="",
        )
        assert "### Project History" not in result

    def test_section_appears_before_domain_architecture(self):
        result = assemble_architect(
            project_map=MINIMAL_PROJECT_MAP,
            csg={"clusters": [{"name": "auth", "symbols": ["a", "b"]}]},
            learnings=LEARNINGS_TEXT,
        )
        history_pos = result.find("### Project History")
        domain_pos = result.find("### Domain Architecture")
        assert history_pos < domain_pos


# ── Developer ─────────────────────────────────────────────────────────


class TestDeveloperInjection:
    def test_learnings_rendered(self):
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            learnings=LEARNINGS_TEXT,
        )
        assert "### Learned Patterns" in result
        assert "**drift**" in result

    def test_no_learnings_no_section(self):
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=MINIMAL_CODE_CONTEXT,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        assert "### Learned Patterns" not in result

    def test_section_appears_before_files_youll_modify(self):
        code_ctx = {
            "full_content": {
                "files_touched": [{"path": "lib/auth.py", "content": "pass"}],
            },
            "skeleton_content": {"high_relevance": []},
        }
        result = assemble_developer(
            task=MINIMAL_TASK,
            code_context=code_ctx,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            learnings=LEARNINGS_TEXT,
        )
        learned_pos = result.find("### Learned Patterns")
        files_pos = result.find("### Files You'll Modify")
        assert learned_pos < files_pos


# ── Reviewer ──────────────────────────────────────────────────────────


class TestReviewerInjection:
    def test_learnings_rendered(self):
        result = assemble_reviewer(
            task=MINIMAL_TASK,
            diff="diff --git a/lib/auth.py\n+pass\n",
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            learnings=LEARNINGS_TEXT,
        )
        assert "### Review Calibration" in result
        assert "**retry**" in result

    def test_no_learnings_no_section(self):
        result = assemble_reviewer(
            task=MINIMAL_TASK,
            diff="",
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        assert "### Review Calibration" not in result

    def test_section_appears_before_git_diff(self):
        result = assemble_reviewer(
            task=MINIMAL_TASK,
            diff="diff --git a/lib/auth.py\n+pass\n",
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            learnings=LEARNINGS_TEXT,
        )
        calibration_pos = result.find("### Review Calibration")
        diff_pos = result.find("### Git Diff")
        assert calibration_pos < diff_pos


# ── Coherence ─────────────────────────────────────────────────────────


class TestCoherenceInjection:
    def test_learnings_rendered(self):
        result = assemble_coherence(
            cross_task_analysis=MINIMAL_CROSS_TASK,
            completed_tasks=[MINIMAL_TASK],
            task_diffs={"T1": "diff"},
            learnings=LEARNINGS_TEXT,
        )
        assert "### Integration History" in result
        assert "scope creep" in result

    def test_no_learnings_no_section(self):
        result = assemble_coherence(
            cross_task_analysis=MINIMAL_CROSS_TASK,
            completed_tasks=[MINIMAL_TASK],
            task_diffs={"T1": "diff"},
        )
        assert "### Integration History" not in result

    def test_section_appears_before_task_diffs(self):
        result = assemble_coherence(
            cross_task_analysis=MINIMAL_CROSS_TASK,
            completed_tasks=[MINIMAL_TASK],
            task_diffs={"T1": "diff --git a/lib/auth.py\n+pass\n"},
            learnings=LEARNINGS_TEXT,
        )
        history_pos = result.find("### Integration History")
        diffs_pos = result.find("### All Task Diffs")
        assert history_pos < diffs_pos


# ── Debugger ──────────────────────────────────────────────────────────


class TestDebuggerInjection:
    def test_learnings_rendered(self):
        result = assemble_debugger(
            task=MINIMAL_TASK,
            budget=MINIMAL_BUDGET,
            learnings=LEARNINGS_TEXT,
        )
        assert "### Known Failure Patterns" in result
        assert "**retry**" in result

    def test_no_learnings_no_section(self):
        result = assemble_debugger(
            task=MINIMAL_TASK,
            budget=MINIMAL_BUDGET,
        )
        assert "### Known Failure Patterns" not in result

    def test_section_appears_before_context_budget(self):
        result = assemble_debugger(
            task=MINIMAL_TASK,
            budget=MINIMAL_BUDGET,
            learnings=LEARNINGS_TEXT,
        )
        patterns_pos = result.find("### Known Failure Patterns")
        budget_pos = result.find("### Context Budget Analysis")
        assert patterns_pos < budget_pos


# ── Budget subtraction ────────────────────────────────────────────────


class TestBudgetSubtraction:
    """Verify learnings reduce available budget for code context.

    Uses a tight budget via config so code truncation kicks in. With
    learnings consuming part of the budget, less code fits, producing
    shorter code sections.
    """

    def _make_code_context(self, n_files: int = 20) -> dict:
        files = []
        for i in range(n_files):
            files.append({
                "path": f"lib/module_{i}.py",
                "content": f"# Module {i}\n" + ("x = 1\n" * 200),
            })
        return {
            "full_content": {"files_touched": files},
            "skeleton_content": {"high_relevance": []},
        }

    def test_developer_less_code_with_learnings(self):
        """With learnings eating budget, fewer code tokens fit."""
        learnings = "\n".join(
            f"- **pattern_{i}** on `lib/module_{i}.py`: finding=\"x\"" for i in range(30)
        )
        code_ctx = self._make_code_context()
        tight_config = {"context": {"budgets": {"developer": 5000}}}

        without = assemble_developer(
            task=MINIMAL_TASK,
            code_context=code_ctx,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            config=tight_config,
        )
        with_learnings = assemble_developer(
            task=MINIMAL_TASK,
            code_context=code_ctx,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
            learnings=learnings,
            config=tight_config,
        )
        assert "### Learned Patterns" in with_learnings
        # Strip the learnings section to compare just code content
        code_without = without.split("### Files You'll Modify")[-1] if "### Files You'll Modify" in without else without
        code_with = with_learnings.split("### Files You'll Modify")[-1] if "### Files You'll Modify" in with_learnings else with_learnings
        assert len(code_with) < len(code_without), (
            f"Code section with learnings ({len(code_with)}) should be "
            f"shorter than without ({len(code_without)})"
        )
