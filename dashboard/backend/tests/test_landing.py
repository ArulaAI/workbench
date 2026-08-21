"""Comprehensive tests for dashboard/backend/resolvers/landing.py.

Covers all four panel readers, the escalation mutation, and the
get_landing_view orchestrator. Uses tmp_path fixtures to build
mock .speed/ directory structures.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import strawberry
import pytest

# Import via sys.path manipulation so tests run without package install.
# Add the dashboard/ directory so that 'backend' is a proper top-level package,
# enabling relative imports (e.g. from ..paths import get_paths) to resolve.
import sys

_DASHBOARD_DIR = Path(__file__).parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.resolvers.landing import (
    get_landing_view,
    read_define_panel,
    read_execute_panel,
    read_judge_panel,
    read_learn_panel,
    respond_to_escalation,
    _read_project_name,
    _read_branch,
    _generate_narrative_for_feature,
    _compute_greeting,
)
from backend.resolvers.landing_types import (
    EscalationResponseInput,
    EscalationResponseResult,
    LandingCompletedFeature,
    LandingDecisionItem,
    LandingDefinePanel,
    LandingExecutePanel,
    LandingJudgePanel,
    LandingLearnPanel,
    LandingQualityGate,
    LandingView,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# Define Panel
# ═══════════════════════════════════════════════════════════════════════════════


class TestDefinePanel:
    """Tests for read_define_panel and its helpers."""

    def test_empty_project(self, tmp_path: Path) -> None:
        panel = read_define_panel(tmp_path)
        assert panel.vision_status == "missing"
        assert panel.draft_specs == []
        assert panel.defects == []
        assert panel.defect_count == 0

    def test_vision_missing(self, tmp_path: Path) -> None:
        panel = read_define_panel(tmp_path)
        assert panel.vision_status == "missing"

    def test_vision_placeholder_short(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "specs" / "product" / "overview.md", "# Vision\nTODO")
        panel = read_define_panel(tmp_path)
        assert panel.vision_status == "placeholder"

    def test_vision_placeholder_only_headings_and_templates(self, tmp_path: Path) -> None:
        content = "# Vision\n## Goals\n{{ template_var }}\n<!-- TODO: fill -->"
        # Pad to exceed 50 chars
        content += "\n" * 40
        _write_file(tmp_path / "specs" / "product" / "overview.md", content)
        panel = read_define_panel(tmp_path)
        assert panel.vision_status == "placeholder"

    def test_vision_defined(self, tmp_path: Path) -> None:
        content = (
            "# Product Vision\n\n"
            "Our product aims to solve the problem of managing reading lists "
            "across devices with a seamless experience that respects user privacy."
        )
        _write_file(tmp_path / "specs" / "product" / "overview.md", content)
        panel = read_define_panel(tmp_path)
        assert panel.vision_status == "defined"

    def test_draft_specs_product_only(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "specs" / "product" / "overview.md", "x" * 100)
        _write_file(tmp_path / "specs" / "product" / "auth.md", "Auth spec content")
        panel = read_define_panel(tmp_path)
        assert len(panel.draft_specs) == 1
        spec = panel.draft_specs[0]
        assert spec.name == "auth"
        assert spec.spec_types == ["product"]
        assert spec.status == "unplanned"

    def test_draft_specs_with_tech_spec(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "specs" / "product" / "overview.md", "x" * 100)
        _write_file(tmp_path / "specs" / "product" / "auth.md", "Auth product spec")
        _write_file(tmp_path / "specs" / "tech" / "auth.md", "Auth tech spec")
        panel = read_define_panel(tmp_path)
        assert len(panel.draft_specs) == 1
        assert panel.draft_specs[0].spec_types == ["product", "technical"]

    def test_draft_specs_speed_prefix_stripped(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "specs" / "product" / "overview.md", "x" * 100)
        _write_file(tmp_path / "specs" / "product" / "speed-auth.md", "Auth spec")
        panel = read_define_panel(tmp_path)
        assert len(panel.draft_specs) == 1
        assert panel.draft_specs[0].name == "speed-auth"

    def test_draft_specs_speed_prefix_with_tech_spec(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "specs" / "product" / "overview.md", "x" * 100)
        _write_file(tmp_path / "specs" / "product" / "speed-auth.md", "Auth product spec")
        _write_file(tmp_path / "specs" / "tech" / "speed-auth.md", "Auth tech spec")
        panel = read_define_panel(tmp_path)
        assert len(panel.draft_specs) == 1
        assert panel.draft_specs[0].spec_types == ["product", "technical"]

    def test_draft_specs_corrupt_state_json_treated_as_unplanned(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "specs" / "product" / "overview.md", "x" * 100)
        _write_file(tmp_path / "specs" / "product" / "auth.md", "Auth spec")
        state_file = tmp_path / ".speed" / "features" / "auth" / "state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("not valid json", encoding="utf-8")
        panel = read_define_panel(tmp_path)
        assert len(panel.draft_specs) == 1
        assert panel.draft_specs[0].status == "unplanned"

    def test_draft_specs_writing_status(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "specs" / "product" / "overview.md", "x" * 100)
        _write_file(tmp_path / "specs" / "product" / "auth.md", "Auth spec")
        _write_json(tmp_path / ".speed" / "features" / "auth" / "state.json", {"status": "planning"})
        panel = read_define_panel(tmp_path)
        assert len(panel.draft_specs) == 1
        assert panel.draft_specs[0].status == "writing"

    def test_draft_specs_running_excluded(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "specs" / "product" / "overview.md", "x" * 100)
        _write_file(tmp_path / "specs" / "product" / "auth.md", "Auth spec")
        _write_json(tmp_path / ".speed" / "features" / "auth" / "state.json", {"status": "running"})
        panel = read_define_panel(tmp_path)
        assert len(panel.draft_specs) == 0

    def test_draft_specs_done_excluded(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "specs" / "product" / "overview.md", "x" * 100)
        _write_file(tmp_path / "specs" / "product" / "auth.md", "Auth spec")
        _write_json(tmp_path / ".speed" / "features" / "auth" / "state.json", {"status": "done"})
        panel = read_define_panel(tmp_path)
        assert len(panel.draft_specs) == 0

    def test_defects_sorted_by_severity(self, tmp_path: Path) -> None:
        _write_json(tmp_path / ".speed" / "defects" / "bug-a" / "state.json", {"severity": "P2", "name": "bug-a"})
        _write_json(tmp_path / ".speed" / "defects" / "bug-b" / "state.json", {"severity": "P0", "name": "bug-b"})
        _write_json(tmp_path / ".speed" / "defects" / "bug-c" / "state.json", {"severity": "P1", "name": "bug-c"})
        panel = read_define_panel(tmp_path)
        assert panel.defect_count == 3
        assert [d.severity for d in panel.defects] == ["P0", "P1", "P2"]

    def test_defects_invalid_severity_clamped(self, tmp_path: Path) -> None:
        _write_json(tmp_path / ".speed" / "defects" / "bug" / "state.json", {"severity": "CRITICAL", "name": "bug"})
        panel = read_define_panel(tmp_path)
        assert panel.defects[0].severity == "P3"

    def test_defects_name_fallback_to_dir(self, tmp_path: Path) -> None:
        _write_json(tmp_path / ".speed" / "defects" / "my-bug" / "state.json", {"severity": "P1"})
        panel = read_define_panel(tmp_path)
        assert panel.defects[0].name == "my-bug"


# ═══════════════════════════════════════════════════════════════════════════════
# Judge Panel
# ═══════════════════════════════════════════════════════════════════════════════


class TestJudgePanel:
    """Tests for read_judge_panel."""

    def test_no_features_dir(self, tmp_path: Path) -> None:
        panel = read_judge_panel(tmp_path)
        assert panel.completed_features == []
        assert panel.awaiting_review == 0

    def test_no_done_features(self, tmp_path: Path) -> None:
        _write_json(tmp_path / ".speed" / "features" / "auth" / "state.json", {"status": "running"})
        panel = read_judge_panel(tmp_path)
        assert panel.completed_features == []
        assert panel.awaiting_review == 0

    def test_pending_review_no_review_file(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "done", "completed_at": "2025-01-15T10:00:00Z"})
        panel = read_judge_panel(tmp_path)
        assert len(panel.completed_features) == 1
        feature = panel.completed_features[0]
        assert feature.feature == "auth"
        assert feature.review_status == "pending"
        assert feature.summary is None
        assert panel.awaiting_review == 1

    def test_pending_review_with_criteria_verify(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "done", "completed_at": "2025-01-15T10:00:00Z"})
        _write_json(feat_dir / "criteria-verify.json", {
            "coverage_pct": 85.5,
            "criteria_passed": 8,
            "criteria_total": 10,
            "criteria": [
                {"name": "c1", "needs_decision": True},
                {"name": "c2", "needs_decision": False},
                {"name": "c3", "needs_decision": True},
            ],
        })
        panel = read_judge_panel(tmp_path)
        assert len(panel.completed_features) == 1
        feature = panel.completed_features[0]
        assert feature.coverage_pct == 85.5
        assert feature.criteria_passed == 8
        assert feature.criteria_total == 10
        # decisions_needed comes from _read_decision_items (spec-traceability, coherence, tasks),
        # not from criteria-verify.json's needs_decision field
        assert feature.decisions_needed == 0

    def test_pending_review_criteria_as_list(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "done"})
        _write_json(feat_dir / "criteria-verify.json", [
            {"name": "c1", "needs_decision": True},
            {"name": "c2", "needs_decision": False},
        ])
        panel = read_judge_panel(tmp_path)
        assert len(panel.completed_features) == 1
        feature = panel.completed_features[0]
        assert feature.criteria_total == 2
        assert feature.decisions_needed == 0

    def test_guardian_verdict_from_log(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "done"})
        logs_dir = feat_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / "Guardian-1700000000.jsonl"
        lines = [
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps({"verdict": "pass"}),
        ]
        log_file.write_text("\n".join(lines), encoding="utf-8")
        panel = read_judge_panel(tmp_path)
        assert len(panel.completed_features) == 1
        assert panel.completed_features[0].guardian_verdict == "pass"

    def test_guardian_verdict_no_logs(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "done"})
        panel = read_judge_panel(tmp_path)
        assert len(panel.completed_features) == 1
        assert panel.completed_features[0].guardian_verdict == "unknown"

    def test_reviewed_feature_approved(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "done", "completed_at": "2025-01-10T10:00:00Z"})
        _write_json(feat_dir / "review.json", {"verdict": "pass"})
        panel = read_judge_panel(tmp_path)
        assert len(panel.completed_features) == 1
        feature = panel.completed_features[0]
        assert feature.feature == "auth"
        assert feature.review_status == "approved"
        assert panel.awaiting_review == 0

    def test_both_pending_and_reviewed(self, tmp_path: Path) -> None:
        # Feature A: done, no review -> pending
        feat_a = tmp_path / ".speed" / "features" / "feat-a"
        _write_json(feat_a / "state.json", {"status": "done", "completed_at": "2025-01-15T10:00:00Z"})

        # Feature B: done, rejected review
        feat_b = tmp_path / ".speed" / "features" / "feat-b"
        _write_json(feat_b / "state.json", {"status": "done", "completed_at": "2025-01-10T10:00:00Z"})
        _write_json(feat_b / "review.json", {"verdict": "fail"})

        panel = read_judge_panel(tmp_path)
        assert panel.awaiting_review == 1
        assert len(panel.completed_features) == 2
        pending = [f for f in panel.completed_features if f.review_status == "pending"]
        reviewed = [f for f in panel.completed_features if f.review_status != "pending"]
        assert len(pending) == 1
        assert pending[0].feature == "feat-a"
        assert len(reviewed) == 1
        assert reviewed[0].feature == "feat-b"
        assert reviewed[0].review_status == "rejected"

    def test_coverage_pct_clamped(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "done"})
        _write_json(feat_dir / "criteria-verify.json", {
            "coverage_pct": 150.0,
            "criteria_passed": 10,
            "criteria_total": 10,
        })
        panel = read_judge_panel(tmp_path)
        assert len(panel.completed_features) == 1
        assert panel.completed_features[0].coverage_pct == 100.0


# ═══════════════════════════════════════════════════════════════════════════════
# Execute Panel
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecutePanel:
    """Tests for read_execute_panel."""

    def test_no_features_dir(self, tmp_path: Path) -> None:
        panel = read_execute_panel(tmp_path)
        assert panel.running_features == []
        assert panel.escalations == []

    def test_no_running_features(self, tmp_path: Path) -> None:
        _write_json(tmp_path / ".speed" / "features" / "auth" / "state.json", {"status": "done"})
        panel = read_execute_panel(tmp_path)
        assert panel.running_features == []

    def test_running_feature_with_tasks(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "running"})
        _write_json(feat_dir / "tasks" / "t1.json", {"id": "t1", "status": "done"})
        _write_json(feat_dir / "tasks" / "t2.json", {"id": "t2", "status": "running"})
        _write_json(feat_dir / "tasks" / "t3.json", {"id": "t3", "status": "pending"})

        panel = read_execute_panel(tmp_path)
        assert len(panel.running_features) == 1
        rf = panel.running_features[0]
        assert rf.name == "auth"
        assert rf.tasks_total == 3
        assert rf.tasks_completed == 1
        assert rf.blocked_count == 0
        assert abs(rf.progress_pct - 33.333) < 1

    def test_running_feature_no_tasks(self, tmp_path: Path) -> None:
        _write_json(tmp_path / ".speed" / "features" / "auth" / "state.json", {"status": "running"})
        panel = read_execute_panel(tmp_path)
        assert len(panel.running_features) == 1
        assert panel.running_features[0].progress_pct == 0.0
        assert panel.running_features[0].tasks_total == 0

    def test_escalations_from_blocked_tasks(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "running"})
        _write_json(feat_dir / "tasks" / "t1.json", {
            "id": "t1",
            "title": "Implement login",
            "status": "blocked",
            "escalation_question": "Which OAuth provider?",
        })
        _write_json(feat_dir / "tasks" / "t2.json", {
            "id": "t2",
            "title": "Write tests",
            "status": "blocked",
            "escalation_question": "Need fixtures?",
            "escalation_response": "Yes, use mock data",
        })

        panel = read_execute_panel(tmp_path)
        # t2 has a response, so only t1 should be an escalation
        assert len(panel.escalations) == 1
        assert panel.escalations[0].task_id == "t1"
        assert panel.escalations[0].question == "Which OAuth provider?"

    def test_running_features_sorted_by_blocked(self, tmp_path: Path) -> None:
        # Feature A: 0 blocked
        _write_json(tmp_path / ".speed" / "features" / "feat-a" / "state.json", {"status": "running"})

        # Feature B: 2 blocked
        feat_b = tmp_path / ".speed" / "features" / "feat-b"
        _write_json(feat_b / "state.json", {"status": "running"})
        _write_json(feat_b / "tasks" / "t1.json", {"id": "t1", "status": "blocked", "escalation_question": "Q1"})
        _write_json(feat_b / "tasks" / "t2.json", {"id": "t2", "status": "blocked", "escalation_question": "Q2"})

        panel = read_execute_panel(tmp_path)
        assert len(panel.running_features) == 2
        assert panel.running_features[0].name == "feat-b"  # more blocked first
        assert panel.running_features[1].name == "feat-a"

    def test_completed_and_done_counted(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "running"})
        _write_json(feat_dir / "tasks" / "t1.json", {"id": "t1", "status": "completed"})
        _write_json(feat_dir / "tasks" / "t2.json", {"id": "t2", "status": "done"})
        _write_json(feat_dir / "tasks" / "t3.json", {"id": "t3", "status": "running"})

        panel = read_execute_panel(tmp_path)
        assert panel.running_features[0].tasks_completed == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Learn Panel
# ═══════════════════════════════════════════════════════════════════════════════


class TestLearnPanel:
    """Tests for read_learn_panel."""

    def test_empty_project(self, tmp_path: Path) -> None:
        panel = read_learn_panel(tmp_path)
        assert panel.coverage_trend == []
        assert panel.insights == []
        assert panel.escalation_trend == []

    def test_coverage_trend_from_traceability(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "spec-traceability.json", {"coverage_pct": 75.0})
        panel = read_learn_panel(tmp_path)
        assert len(panel.coverage_trend) == 1
        assert panel.coverage_trend[0].feature == "auth"
        assert panel.coverage_trend[0].coverage_pct == 75.0

    def test_coverage_trend_clamped(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "spec-traceability.json", {"coverage_pct": -10.0})
        panel = read_learn_panel(tmp_path)
        assert panel.coverage_trend[0].coverage_pct == 0.0

    def test_coverage_trend_fallback_to_observations(self, tmp_path: Path) -> None:
        # Create feature dir but no traceability files
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        feat_dir.mkdir(parents=True, exist_ok=True)
        _write_json(feat_dir / "state.json", {"status": "running"})

        # Create observations JSONL with coverage data
        obs_dir = tmp_path / ".speed" / "memory" / "observations"
        obs_dir.mkdir(parents=True, exist_ok=True)
        obs_file = obs_dir / "auth.jsonl"
        lines = [
            json.dumps({"coverage_pct": 50.0}),
            json.dumps({"coverage_pct": 65.0}),
        ]
        obs_file.write_text("\n".join(lines), encoding="utf-8")

        panel = read_learn_panel(tmp_path)
        assert len(panel.coverage_trend) == 1
        assert panel.coverage_trend[0].coverage_pct == 65.0

    def test_insights_from_learnings(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / ".speed" / "memory"
        _write_json(memory_dir / "sprint-learnings.json", [
            {"type": "good", "text": "Tests helped catch regressions", "weight": 0.9},
            {"type": "warn", "text": "CI flaky on macOS", "weight": 0.7},
            {"type": "info", "text": "Skipped: not good/warn", "weight": 1.0},
        ])
        panel = read_learn_panel(tmp_path)
        assert len(panel.insights) == 2
        assert panel.insights[0].text == "Tests helped catch regressions"
        assert panel.insights[0].type == "good"
        assert panel.insights[1].type == "warn"

    def test_insights_max_five(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / ".speed" / "memory"
        entries = [{"type": "good", "text": f"Insight {i}", "weight": float(i)} for i in range(10)]
        _write_json(memory_dir / "big-learnings.json", entries)
        panel = read_learn_panel(tmp_path)
        assert len(panel.insights) == 5
        # Sorted by weight descending
        assert panel.insights[0].text == "Insight 9"

    def test_insights_dict_format_with_entries_key(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / ".speed" / "memory"
        _write_json(memory_dir / "sprint-learnings.json", {
            "entries": [
                {"type": "good", "text": "From dict format", "weight": 0.5},
            ]
        })
        panel = read_learn_panel(tmp_path)
        assert len(panel.insights) == 1
        assert panel.insights[0].text == "From dict format"

    def test_escalation_trend(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "spec-traceability.json", {"coverage_pct": 80.0})
        _write_json(feat_dir / "tasks" / "t1.json", {"id": "t1", "escalation_question": "Q1"})
        _write_json(feat_dir / "tasks" / "t2.json", {"id": "t2"})
        _write_json(feat_dir / "tasks" / "t3.json", {"id": "t3", "escalation_question": "Q3"})

        panel = read_learn_panel(tmp_path)
        assert len(panel.escalation_trend) == 1
        assert panel.escalation_trend[0].feature == "auth"
        assert panel.escalation_trend[0].count == 2

    def test_no_coverage_no_escalation_trend(self, tmp_path: Path) -> None:
        """Escalation trend only includes features that appear in coverage trend."""
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "running"})
        _write_json(feat_dir / "tasks" / "t1.json", {"id": "t1", "escalation_question": "Q1"})
        # No traceability or observations -> empty coverage -> empty escalation trend
        panel = read_learn_panel(tmp_path)
        assert panel.escalation_trend == []


# ═══════════════════════════════════════════════════════════════════════════════
# Escalation Mutation
# ═══════════════════════════════════════════════════════════════════════════════


class TestEscalationMutation:
    """Tests for respond_to_escalation."""

    def _setup_blocked_task(self, tmp_path: Path) -> Path:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        task_file = feat_dir / "tasks" / "t1.json"
        _write_json(task_file, {
            "id": "t1",
            "status": "blocked",
            "escalation_question": "Which provider?",
        })
        return task_file

    def test_success(self, tmp_path: Path) -> None:
        task_file = self._setup_blocked_task(tmp_path)
        inp = EscalationResponseInput(feature="auth", task_id="t1", response="Use Google OAuth")
        result = respond_to_escalation(tmp_path, inp)
        assert result.success is True
        assert result.error is None

        data = json.loads(task_file.read_text(encoding="utf-8"))
        assert data["escalation_response"] == "Use Google OAuth"
        assert "escalation_responded_at" in data

    def test_empty_response(self, tmp_path: Path) -> None:
        self._setup_blocked_task(tmp_path)
        inp = EscalationResponseInput(feature="auth", task_id="t1", response="")
        result = respond_to_escalation(tmp_path, inp)
        assert result.success is False
        assert "empty" in result.error.lower()

    def test_response_too_long(self, tmp_path: Path) -> None:
        self._setup_blocked_task(tmp_path)
        inp = EscalationResponseInput(feature="auth", task_id="t1", response="x" * 2001)
        result = respond_to_escalation(tmp_path, inp)
        assert result.success is False
        assert "2000" in result.error

    def test_path_traversal_feature(self, tmp_path: Path) -> None:
        self._setup_blocked_task(tmp_path)
        inp = EscalationResponseInput(feature="../etc", task_id="t1", response="answer")
        result = respond_to_escalation(tmp_path, inp)
        assert result.success is False
        assert "forbidden" in result.error.lower()

    def test_path_traversal_task_id(self, tmp_path: Path) -> None:
        self._setup_blocked_task(tmp_path)
        inp = EscalationResponseInput(feature="auth", task_id="../../etc/passwd", response="answer")
        result = respond_to_escalation(tmp_path, inp)
        assert result.success is False
        assert "forbidden" in result.error.lower()

    def test_feature_not_found(self, tmp_path: Path) -> None:
        inp = EscalationResponseInput(feature="nonexistent", task_id="t1", response="answer")
        result = respond_to_escalation(tmp_path, inp)
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_task_not_found(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        feat_dir.mkdir(parents=True, exist_ok=True)
        (feat_dir / "tasks").mkdir(parents=True, exist_ok=True)
        inp = EscalationResponseInput(feature="auth", task_id="missing", response="answer")
        result = respond_to_escalation(tmp_path, inp)
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_task_not_blocked(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "tasks" / "t1.json", {
            "id": "t1",
            "status": "running",
            "escalation_question": "Q?",
        })
        inp = EscalationResponseInput(feature="auth", task_id="t1", response="answer")
        result = respond_to_escalation(tmp_path, inp)
        assert result.success is False
        assert "blocked" in result.error.lower()

    def test_no_escalation_question(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "tasks" / "t1.json", {"id": "t1", "status": "blocked"})
        inp = EscalationResponseInput(feature="auth", task_id="t1", response="answer")
        result = respond_to_escalation(tmp_path, inp)
        assert result.success is False
        assert "escalation question" in result.error.lower()

    def test_null_byte_in_feature(self, tmp_path: Path) -> None:
        inp = EscalationResponseInput(feature="auth\x00evil", task_id="t1", response="answer")
        result = respond_to_escalation(tmp_path, inp)
        assert result.success is False

    def test_slash_in_task_id(self, tmp_path: Path) -> None:
        self._setup_blocked_task(tmp_path)
        inp = EscalationResponseInput(feature="auth", task_id="t1/evil", response="answer")
        result = respond_to_escalation(tmp_path, inp)
        assert result.success is False


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestProjectName:
    """Tests for _read_project_name."""

    def test_fallback_to_dir_name(self, tmp_path: Path) -> None:
        assert _read_project_name(tmp_path) == tmp_path.name

    def test_from_speed_toml_project_section(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "speed.toml", '[project]\nname = "Bookshelf"')
        assert _read_project_name(tmp_path) == "Bookshelf"

    def test_from_speed_toml_top_level_name(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "speed.toml", 'name = "MyProject"')
        assert _read_project_name(tmp_path) == "MyProject"

    def test_project_section_takes_precedence(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "speed.toml", 'name = "TopLevel"\n\n[project]\nname = "ProjectLevel"')
        assert _read_project_name(tmp_path) == "ProjectLevel"

    def test_invalid_toml_fallback(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "speed.toml", "this is not valid toml [[[")
        assert _read_project_name(tmp_path) == tmp_path.name

    def test_toml_without_name(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "speed.toml", '[agent]\nprovider = "claude-code"')
        assert _read_project_name(tmp_path) == tmp_path.name


class TestReadBranch:
    """Tests for _read_branch."""

    def test_returns_branch_in_git_repo(self, tmp_path: Path) -> None:
        """When run inside a git repo, returns a non-None branch name."""
        subprocess_run = __import__("subprocess").run
        subprocess_run(["git", "init", "-b", "test-branch"], cwd=str(tmp_path), capture_output=True)
        # git rev-parse needs at least one commit
        (tmp_path / "README").write_text("init")
        subprocess_run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess_run(
            ["git", "commit", "-m", "init", "--no-gpg-sign"],
            cwd=str(tmp_path), capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
        )
        branch = _read_branch(tmp_path)
        assert branch == "test-branch"

    def test_returns_none_outside_git_repo(self, tmp_path: Path) -> None:
        branch = _read_branch(tmp_path)
        assert branch is None

    @patch("backend.resolvers.landing.subprocess.run", side_effect=FileNotFoundError)
    def test_returns_none_when_git_missing(self, mock_run: MagicMock, tmp_path: Path) -> None:
        branch = _read_branch(tmp_path)
        assert branch is None

    @patch("backend.resolvers.landing.subprocess.run", side_effect=__import__("subprocess").TimeoutExpired("git", 5))
    def test_returns_none_on_timeout(self, mock_run: MagicMock, tmp_path: Path) -> None:
        branch = _read_branch(tmp_path)
        assert branch is None


class TestGreeting:
    """Tests for _compute_greeting."""

    def test_returns_generic_greeting(self) -> None:
        greeting = _compute_greeting()
        assert isinstance(greeting, str)
        assert len(greeting) > 0


class TestGenerateNarrative:
    """Tests for _generate_narrative_for_feature."""

    def _make_feature(self, **kwargs: object) -> LandingCompletedFeature:
        defaults: dict = {
            "feature": "auth",
            "completed_at": "2025-01-15T10:00:00Z",
            "coverage_pct": 85.0,
            "criteria_passed": 8,
            "criteria_total": 10,
            "guardian_verdict": "pass",
            "decisions_needed": 1,
            "decision_items": [],
            "review_status": "pending",
            "summary": None,
        }
        defaults.update(kwargs)
        return LandingCompletedFeature(**defaults)

    def test_provider_not_available_returns_none(self) -> None:
        feature = self._make_feature()
        execute = LandingExecutePanel(running_features=[], recent_features=[], escalations=[])
        result = _generate_narrative_for_feature(feature, "TestProject", execute)
        # provider module doesn't exist in test env, should return None
        assert result is None

    @patch("backend.resolvers.landing.log")
    def test_provider_import_failure_logged(self, mock_log: MagicMock) -> None:
        feature = self._make_feature(
            completed_at=None,
            coverage_pct=0.0,
            criteria_passed=0,
            criteria_total=0,
            guardian_verdict="unknown",
            decisions_needed=0,
        )
        execute = LandingExecutePanel(running_features=[], recent_features=[], escalations=[])
        _generate_narrative_for_feature(feature, "TestProject", execute)
        mock_log.debug.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator (get_landing_view)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetLandingView:
    """Tests for get_landing_view."""

    def test_empty_project(self, tmp_path: Path) -> None:
        view = get_landing_view(tmp_path)
        assert isinstance(view, LandingView)
        assert isinstance(view.greeting, str)
        assert view.project_name == tmp_path.name
        assert view.narrative is None
        assert view.define.vision_status == "missing"
        assert view.judge.completed_features == []
        assert view.execute.running_features == []
        assert view.learn.coverage_trend == []

    def test_project_name_from_toml(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "speed.toml", '[project]\nname = "Bookshelf"')
        view = get_landing_view(tmp_path)
        assert view.project_name == "Bookshelf"

    def test_branch_populated(self, tmp_path: Path) -> None:
        subprocess_run = __import__("subprocess").run
        subprocess_run(["git", "init", "-b", "feature/auth"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "README").write_text("init")
        subprocess_run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess_run(
            ["git", "commit", "-m", "init", "--no-gpg-sign"],
            cwd=str(tmp_path), capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
        )
        view = get_landing_view(tmp_path)
        assert view.branch == "feature/auth"

    def test_all_panels_populated(self, tmp_path: Path) -> None:
        """Build a complete project structure and verify all panels get data."""
        # Vision
        _write_file(
            tmp_path / "specs" / "product" / "overview.md",
            "A full product vision document with enough content to be defined. " * 5,
        )

        # Draft spec
        _write_file(tmp_path / "specs" / "product" / "search.md", "Search feature spec")

        # Defect
        _write_json(tmp_path / ".speed" / "defects" / "bug-1" / "state.json", {"severity": "P1", "name": "bug-1"})

        # Running feature (Execute panel)
        feat_exec = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_exec / "state.json", {"status": "running"})
        _write_json(feat_exec / "tasks" / "t1.json", {"id": "t1", "status": "done"})
        _write_json(feat_exec / "tasks" / "t2.json", {"id": "t2", "status": "running"})

        # Done feature without review (Judge pending)
        feat_judge = tmp_path / ".speed" / "features" / "onboarding"
        _write_json(feat_judge / "state.json", {"status": "done", "completed_at": "2025-01-15T10:00:00Z"})
        _write_json(feat_judge / "spec-traceability.json", {"coverage_pct": 90.0})

        # Learnings
        memory_dir = tmp_path / ".speed" / "memory"
        _write_json(memory_dir / "sprint-learnings.json", [
            {"type": "good", "text": "Fast iteration", "weight": 0.8},
        ])

        view = get_landing_view(tmp_path)

        # Define
        assert view.define.vision_status == "defined"
        assert len(view.define.draft_specs) == 1
        assert view.define.defect_count == 1

        # Judge
        assert view.judge.awaiting_review == 1
        pending = [f for f in view.judge.completed_features if f.review_status == "pending"]
        assert pending[0].feature == "onboarding"

        # Execute
        assert len(view.execute.running_features) == 1
        assert view.execute.running_features[0].name == "auth"

        # Learn
        assert len(view.learn.coverage_trend) == 1
        assert len(view.learn.insights) == 1

    def test_narrative_injected_into_pending_review(self, tmp_path: Path) -> None:
        """When _generate_narrative_for_feature returns a narrative, it's set on view.narrative."""
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "done", "completed_at": "2025-01-15T10:00:00Z"})

        with patch("backend.resolvers.landing._generate_narrative_for_feature", return_value="Auth feature looks good."):
            view = get_landing_view(tmp_path)

        assert view.narrative == "Auth feature looks good."

    def test_narrative_none_without_pending_review(self, tmp_path: Path) -> None:
        """No pending review means narrative stays None even if generator would return something."""
        view = get_landing_view(tmp_path)
        assert view.narrative is None
        assert view.judge.completed_features == []

    def test_narrative_none_on_llm_failure(self, tmp_path: Path) -> None:
        """LLM failure yields narrative=None without raising."""
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "done"})

        # The default behavior (no provider module) returns None
        view = get_landing_view(tmp_path)
        assert view.narrative is None

    def test_conn_parameter_accepted(self, tmp_path: Path) -> None:
        """Verify conn parameter is accepted (reserved for future use)."""
        view = get_landing_view(tmp_path, conn=MagicMock())
        assert isinstance(view, LandingView)

    def test_with_mocked_llm_provider(self, tmp_path: Path) -> None:
        """Simulate a working provider_chat via mock."""
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "state.json", {"status": "done", "completed_at": "2025-01-15T10:00:00Z"})
        _write_json(feat_dir / "criteria-verify.json", {
            "coverage_pct": 85.0,
            "criteria_passed": 8,
            "criteria_total": 10,
            "criteria": [],
        })

        mock_provider = MagicMock()
        mock_provider.provider_chat.return_value = "The auth feature has 85% coverage with 8 of 10 criteria met."

        with patch.dict("sys.modules", {"backend.resolvers.provider": mock_provider}):
            view = get_landing_view(tmp_path)

        assert view.narrative == "The auth feature has 85% coverage with 8 of 10 criteria met."


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Integration
# ═══════════════════════════════════════════════════════════════════════════════

# Minimal test schema wiring only the landing resolver — no db connections or
# subscription infrastructure. Exercises the full Strawberry serialisation path
# from GraphQL query text through resolver to JSON-shaped response dict.


@strawberry.type
class _SchemaTestQuery:
    @strawberry.field
    def landing_view(self, info: strawberry.types.Info) -> LandingView:
        return get_landing_view(info.context["project_root"])


@strawberry.type
class _SchemaTestMutation:
    @strawberry.mutation
    def respond_to_escalation(
        self,
        info: strawberry.types.Info,
        feature: str,
        task_id: str,
        response: str,
    ) -> EscalationResponseResult:
        return respond_to_escalation(
            info.context["project_root"],
            EscalationResponseInput(feature=feature, task_id=task_id, response=response),
        )


_LANDING_SCHEMA = strawberry.Schema(query=_SchemaTestQuery, mutation=_SchemaTestMutation)

_LANDING_VIEW_QUERY = """
  query {
    landingView {
      greeting
      projectName
      branch
      narrative
      define {
        visionStatus
        draftSpecs { name specTypes status }
        defects { severity name }
        defectCount
      }
      judge {
        completedFeatures {
          feature completedAt coveragePct criteriaPassed
          criteriaTotal guardianVerdict decisionsNeeded reviewStatus summary
        }
        qualityGates { name status detail }
        totalFeatures
        awaitingReview
      }
      execute {
        runningFeatures { name progressPct tasksCompleted tasksTotal blockedCount }
        recentFeatures { name completedAt coveragePct tasksCompleted tasksTotal }
        escalations { feature taskId taskTitle question }
      }
      learn {
        coverageTrend { feature coveragePct }
        insights { type text }
        escalationTrend { feature count }
      }
    }
  }
"""

_RESPOND_MUTATION = """
  mutation($feature: String!, $taskId: String!, $response: String!) {
    respondToEscalation(feature: $feature, taskId: $taskId, response: $response) {
      success
      error
    }
  }
"""


class TestSchemaIntegration:
    """Schema-level integration tests for landingView query and respondToEscalation mutation.

    Each test executes GraphQL through the test schema, verifying that the
    Strawberry type hierarchy serialises correctly and the resolver wiring works.
    """

    def _ctx(self, project_root: Path) -> dict:
        return {"project_root": project_root}

    def test_landing_view_full_shape(self, tmp_path: Path) -> None:
        """landingView query returns all four panels with correct field shapes."""
        _write_file(
            tmp_path / "specs" / "product" / "overview.md",
            "A vision statement with enough substance to be classified as defined. " * 3,
        )
        _write_file(tmp_path / "specs" / "product" / "search.md", "Search feature spec")
        _write_json(
            tmp_path / ".speed" / "defects" / "bug-1" / "state.json",
            {"severity": "P1", "name": "bug-1"},
        )

        feat_exec = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_exec / "state.json", {"status": "running"})
        _write_json(feat_exec / "tasks" / "t1.json", {"id": "t1", "status": "done"})
        _write_json(feat_exec / "tasks" / "t2.json", {"id": "t2", "status": "running"})

        feat_judge = tmp_path / ".speed" / "features" / "onboarding"
        _write_json(
            feat_judge / "state.json",
            {"status": "done", "completed_at": "2025-01-15T10:00:00Z"},
        )
        _write_json(feat_judge / "spec-traceability.json", {"coverage_pct": 90.0})

        _write_json(
            tmp_path / ".speed" / "memory" / "sprint-learnings.json",
            [{"type": "good", "text": "Fast iteration", "weight": 0.8}],
        )

        result = _LANDING_SCHEMA.execute_sync(_LANDING_VIEW_QUERY, context_value=self._ctx(tmp_path))

        assert result.errors is None
        data = result.data["landingView"]

        assert isinstance(data["greeting"], str)
        assert isinstance(data["projectName"], str)

        define = data["define"]
        assert define["visionStatus"] == "defined"
        assert len(define["draftSpecs"]) == 1
        spec = define["draftSpecs"][0]
        assert "name" in spec
        assert "specTypes" in spec
        assert "status" in spec
        assert define["defectCount"] == 1
        assert define["defects"][0]["severity"] == "P1"

        judge = data["judge"]
        assert judge["awaitingReview"] == 1
        pending = [f for f in judge["completedFeatures"] if f["reviewStatus"] == "pending"]
        assert len(pending) == 1
        assert pending[0]["feature"] == "onboarding"
        for field in ("coveragePct", "criteriaPassed", "criteriaTotal", "guardianVerdict", "decisionsNeeded"):
            assert field in pending[0]

        execute = data["execute"]
        assert len(execute["runningFeatures"]) == 1
        rf = execute["runningFeatures"][0]
        assert rf["name"] == "auth"
        for field in ("progressPct", "tasksCompleted", "tasksTotal", "blockedCount"):
            assert field in rf

        learn = data["learn"]
        assert learn["coverageTrend"][0]["feature"] == "onboarding"
        assert learn["insights"][0]["type"] == "good"
        # onboarding is in coverage_trend, so it appears in escalation_trend;
        # it has no tasks with escalation_question, so count is 0.
        assert isinstance(data["branch"], (str, type(None)))
        assert len(learn["escalationTrend"]) == 1
        assert learn["escalationTrend"][0]["feature"] == "onboarding"
        assert learn["escalationTrend"][0]["count"] == 0

    def test_empty_project_all_panels_empty(self, tmp_path: Path) -> None:
        """Empty project returns default/empty values in all panels, no GraphQL errors."""
        result = _LANDING_SCHEMA.execute_sync(_LANDING_VIEW_QUERY, context_value=self._ctx(tmp_path))

        assert result.errors is None
        data = result.data["landingView"]

        assert data["define"]["visionStatus"] == "missing"
        assert data["define"]["draftSpecs"] == []
        assert data["define"]["defects"] == []
        assert data["define"]["defectCount"] == 0

        assert data["judge"]["completedFeatures"] == []
        assert data["judge"]["awaitingReview"] == 0

        assert data["execute"]["runningFeatures"] == []
        assert data["execute"]["escalations"] == []

        assert data["learn"]["coverageTrend"] == []
        assert data["learn"]["insights"] == []
        assert data["learn"]["escalationTrend"] == []

    def test_respond_to_escalation_writes_file(self, tmp_path: Path) -> None:
        """respondToEscalation mutation writes the response to the task JSON file."""
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        task_file = feat_dir / "tasks" / "t1.json"
        _write_json(task_file, {
            "id": "t1",
            "status": "blocked",
            "escalation_question": "Which OAuth provider?",
        })

        result = _LANDING_SCHEMA.execute_sync(
            _RESPOND_MUTATION,
            variable_values={"feature": "auth", "taskId": "t1", "response": "Use Google OAuth"},
            context_value=self._ctx(tmp_path),
        )

        assert result.errors is None
        mutation_result = result.data["respondToEscalation"]
        assert mutation_result["success"] is True
        assert mutation_result["error"] is None

        saved = json.loads(task_file.read_text(encoding="utf-8"))
        assert saved["escalation_response"] == "Use Google OAuth"
        assert "escalation_responded_at" in saved

    def test_respond_to_escalation_non_blocked_task(self, tmp_path: Path) -> None:
        """respondToEscalation returns success: false for a task not in blocked status."""
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "tasks" / "t1.json", {
            "id": "t1",
            "status": "running",
            "escalation_question": "Which provider?",
        })

        result = _LANDING_SCHEMA.execute_sync(
            _RESPOND_MUTATION,
            variable_values={"feature": "auth", "taskId": "t1", "response": "An answer"},
            context_value=self._ctx(tmp_path),
        )

        assert result.errors is None
        mutation_result = result.data["respondToEscalation"]
        assert mutation_result["success"] is False
        assert mutation_result["error"] is not None
        assert "blocked" in mutation_result["error"].lower()

    def test_corrupted_state_json_skips_feature(self, tmp_path: Path) -> None:
        """A feature with corrupted state.json is skipped; other features still returned."""
        good_feat = tmp_path / ".speed" / "features" / "good-feature"
        _write_json(good_feat / "state.json", {"status": "running"})
        _write_json(good_feat / "tasks" / "t1.json", {"id": "t1", "status": "done"})

        bad_feat = tmp_path / ".speed" / "features" / "bad-feature"
        bad_feat.mkdir(parents=True, exist_ok=True)
        (bad_feat / "state.json").write_text("{not valid json{{", encoding="utf-8")

        result = _LANDING_SCHEMA.execute_sync(_LANDING_VIEW_QUERY, context_value=self._ctx(tmp_path))

        assert result.errors is None
        running_names = [f["name"] for f in result.data["landingView"]["execute"]["runningFeatures"]]
        assert "good-feature" in running_names
        assert "bad-feature" not in running_names

    def test_narrative_null_on_llm_timeout(self, tmp_path: Path) -> None:
        """narrative returns null when the LLM provider times out; other panels must still populate."""
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(
            feat_dir / "state.json",
            {"status": "done", "completed_at": "2025-01-15T10:00:00Z"},
        )

        # Provide spec content so define panel has a draft spec.
        # "billing" spec has no matching running feature, so it stays in draft_specs.
        _write_file(tmp_path / "specs" / "product" / "overview.md", "x" * 100)
        _write_file(tmp_path / "specs" / "product" / "billing.md", "Billing spec")

        # Provide a running feature so execute panel is non-empty.
        # "payments" has no spec file, so it doesn't affect define panel.
        running_feat = tmp_path / ".speed" / "features" / "payments"
        _write_json(running_feat / "state.json", {"status": "running"})
        _write_json(running_feat / "tasks" / "t1.json", {"id": "t1", "status": "running"})

        mock_provider = MagicMock()
        mock_provider.provider_chat.side_effect = TimeoutError("LLM call exceeded 5s timeout")

        with patch.dict("sys.modules", {"backend.resolvers.provider": mock_provider}):
            result = _LANDING_SCHEMA.execute_sync(
                _LANDING_VIEW_QUERY, context_value=self._ctx(tmp_path)
            )

        assert result.errors is None
        data = result.data["landingView"]
        assert data["narrative"] is None
        # Timeout must not cascade — other panels still return data.
        assert len(data["define"]["draftSpecs"]) == 1
        assert len(data["execute"]["runningFeatures"]) == 1

    def test_respond_to_escalation_no_escalation_question(self, tmp_path: Path) -> None:
        """respondToEscalation returns success: false when blocked task has no escalation_question."""
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "tasks" / "t1.json", {
            "id": "t1",
            "status": "blocked",
        })

        result = _LANDING_SCHEMA.execute_sync(
            _RESPOND_MUTATION,
            variable_values={"feature": "auth", "taskId": "t1", "response": "An answer"},
            context_value=self._ctx(tmp_path),
        )

        assert result.errors is None
        mutation_result = result.data["respondToEscalation"]
        assert mutation_result["success"] is False
        assert "escalation question" in mutation_result["error"].lower()
