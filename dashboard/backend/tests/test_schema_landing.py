"""Schema-level integration tests for landing query and mutation.

Exercises the Strawberry schema's execute_sync() to verify that
landing_view and respond_to_escalation are wired correctly and
produce valid GraphQL responses (not just resolver-level tests).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sys

_BACKEND_DIR = Path(__file__).parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from schema import schema
from test_helpers import _write_file, _write_json


def _make_context(tmp_path: Path) -> dict:
    """Build the GraphQL context dict the schema expects."""
    return {"project_root": tmp_path, "conn": MagicMock()}


# ── landingView query ────────────────────────────────────────────────────────

LANDING_VIEW_QUERY = """
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
                feature
                completedAt
                coveragePct
                criteriaPassed
                criteriaTotal
                guardianVerdict
                decisionsNeeded
                decisionItems { title description }
                reviewStatus
                summary
            }
            qualityGates { name status detail }
            totalFeatures
            awaitingReview
        }
        execute {
            runningFeatures {
                name progressPct tasksCompleted tasksTotal blockedCount
            }
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


class TestLandingViewQuery:
    """Verify landingView query executes through the compiled schema."""

    def test_empty_project_returns_valid_response(self, tmp_path: Path) -> None:
        result = schema.execute_sync(
            LANDING_VIEW_QUERY,
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        data = result.data["landingView"]
        assert isinstance(data["greeting"], str)
        assert isinstance(data["projectName"], str)
        assert data["define"]["visionStatus"] == "missing"
        assert data["define"]["draftSpecs"] == []
        assert data["define"]["defects"] == []
        assert data["judge"]["completedFeatures"] == []
        assert data["judge"]["totalFeatures"] == 0
        assert data["judge"]["awaitingReview"] == 0
        assert data["execute"]["runningFeatures"] == []
        assert data["execute"]["escalations"] == []
        assert data["learn"]["coverageTrend"] == []

    def test_populated_project_returns_all_panels(self, tmp_path: Path) -> None:
        # Vision
        _write_file(
            tmp_path / "specs" / "product" / "overview.md",
            "A full product vision document with enough content. " * 5,
        )
        # Draft spec
        _write_file(tmp_path / "specs" / "product" / "search.md", "Search spec")
        # Defect
        _write_json(
            tmp_path / ".speed" / "defects" / "bug-1" / "state.json",
            {"severity": "P1", "name": "bug-1"},
        )
        # Running feature
        feat_run = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_run / "state.json", {"status": "running"})
        _write_json(feat_run / "tasks" / "t1.json", {"id": "t1", "status": "done"})
        _write_json(feat_run / "tasks" / "t2.json", {"id": "t2", "status": "running"})
        # Done feature (pending review)
        feat_done = tmp_path / ".speed" / "features" / "onboarding"
        _write_json(
            feat_done / "state.json",
            {"status": "done", "completed_at": "2025-01-15T10:00:00Z"},
        )
        _write_json(feat_done / "spec-traceability.json", {"coverage_pct": 90.0})
        # Learnings
        _write_json(
            tmp_path / ".speed" / "memory" / "sprint-learnings.json",
            [{"type": "good", "text": "Fast iteration", "weight": 0.8}],
        )

        result = schema.execute_sync(
            LANDING_VIEW_QUERY,
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        data = result.data["landingView"]

        assert data["define"]["visionStatus"] == "defined"
        assert len(data["define"]["draftSpecs"]) == 1
        assert data["define"]["defectCount"] == 1
        assert len(data["judge"]["completedFeatures"]) == 1
        assert data["judge"]["completedFeatures"][0]["feature"] == "onboarding"
        assert data["judge"]["completedFeatures"][0]["decisionItems"] == []
        assert data["judge"]["awaitingReview"] == 1
        assert len(data["execute"]["runningFeatures"]) == 1
        assert data["execute"]["runningFeatures"][0]["name"] == "auth"
        assert len(data["learn"]["coverageTrend"]) == 1
        assert len(data["learn"]["insights"]) == 1


# ── respondToEscalation mutation ─────────────────────────────────────────────

RESPOND_MUTATION = """
mutation RespondToEscalation($feature: String!, $taskId: String!, $response: String!) {
    respondToEscalation(feature: $feature, taskId: $taskId, response: $response) {
        success
        error
    }
}
"""


class TestRespondToEscalationMutation:
    """Verify respondToEscalation mutation executes through the compiled schema."""

    def _setup_blocked_task(self, tmp_path: Path) -> Path:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        task_file = feat_dir / "tasks" / "t1.json"
        _write_json(task_file, {
            "id": "t1",
            "status": "blocked",
            "escalation_question": "Which provider?",
        })
        return task_file

    def test_successful_escalation_response(self, tmp_path: Path) -> None:
        task_file = self._setup_blocked_task(tmp_path)
        result = schema.execute_sync(
            RESPOND_MUTATION,
            variable_values={
                "feature": "auth",
                "taskId": "t1",
                "response": "Use Google OAuth",
            },
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        mutation_data = result.data["respondToEscalation"]
        assert mutation_data["success"] is True
        assert mutation_data["error"] is None

        written = json.loads(task_file.read_text(encoding="utf-8"))
        assert written["escalation_response"] == "Use Google OAuth"

    def test_non_blocked_task_returns_failure(self, tmp_path: Path) -> None:
        feat_dir = tmp_path / ".speed" / "features" / "auth"
        _write_json(feat_dir / "tasks" / "t1.json", {
            "id": "t1",
            "status": "running",
            "escalation_question": "Q?",
        })
        result = schema.execute_sync(
            RESPOND_MUTATION,
            variable_values={
                "feature": "auth",
                "taskId": "t1",
                "response": "answer",
            },
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        mutation_data = result.data["respondToEscalation"]
        assert mutation_data["success"] is False
        assert "blocked" in mutation_data["error"].lower()

    def test_missing_feature_returns_failure(self, tmp_path: Path) -> None:
        result = schema.execute_sync(
            RESPOND_MUTATION,
            variable_values={
                "feature": "nonexistent",
                "taskId": "t1",
                "response": "answer",
            },
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        mutation_data = result.data["respondToEscalation"]
        assert mutation_data["success"] is False
        assert "not found" in mutation_data["error"].lower()


# ── landingView.define panel ──────────────────────────────────────────────────

DEFINE_QUERY = """
query {
    landingView {
        define {
            visionStatus
            draftSpecs { name specTypes status }
            defects { severity name }
            defectCount
        }
    }
}
"""


class TestLandingViewDefine:
    """Verify the define panel in isolation via the compiled schema."""

    def test_empty_project(self, tmp_path: Path) -> None:
        result = schema.execute_sync(
            DEFINE_QUERY,
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        define = result.data["landingView"]["define"]
        assert define["visionStatus"] == "missing"
        assert define["draftSpecs"] == []
        assert define["defects"] == []
        assert define["defectCount"] == 0

    def test_two_specs_and_one_defect(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path / "specs" / "product" / "overview.md",
            "A full product vision document with enough content. " * 5,
        )
        _write_file(tmp_path / "specs" / "product" / "search.md", "Search feature spec")
        _write_file(tmp_path / "specs" / "product" / "auth.md", "Auth feature spec")
        _write_json(
            tmp_path / ".speed" / "defects" / "login-crash" / "state.json",
            {"severity": "P1", "name": "login-crash"},
        )

        result = schema.execute_sync(
            DEFINE_QUERY,
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        define = result.data["landingView"]["define"]

        assert define["visionStatus"] == "defined"
        assert define["defectCount"] == 1
        assert len(define["draftSpecs"]) == 2
        spec_names = {s["name"] for s in define["draftSpecs"]}
        assert spec_names == {"search", "auth"}
        for spec in define["draftSpecs"]:
            assert "product" in spec["specTypes"]
            assert spec["status"] == "unplanned"
        assert len(define["defects"]) == 1
        assert define["defects"][0]["severity"] == "P1"
        assert define["defects"][0]["name"] == "login-crash"


# ── specAlignment query ───────────────────────────────────────────────────────

SPEC_ALIGNMENT_QUERY = """
query {
    specAlignment {
        specs {
            specFile
            sections {
                section
                claimCount
                confirmed
                missing
                unverifiable
                coveragePct
                claims {
                    source { specFile section line }
                    claimType
                    claimText
                    entity
                    status
                    evidence
                    divergence
                }
            }
            totalClaims
            confirmed
            coveragePct
        }
        totalClaims
        totalConfirmed
        totalMissing
        totalUnverifiable
        overallCoveragePct
    }
}
"""

SPEC_ALIGNMENT_FILTERED_QUERY = """
query($specFile: String) {
    specAlignment(specFile: $specFile) {
        specs {
            specFile
            totalClaims
        }
        totalClaims
    }
}
"""


def _make_alignment_fixture() -> dict:
    """Build a spec-alignment.json payload with two spec files and three claims."""
    return {
        "claims": [
            {
                "source": {
                    "spec_file": "specs/product/search.md",
                    "section": "Overview",
                    "line": 5,
                },
                "claim_type": "functional",
                "claim_text": "Full-text search across all content",
                "entity": "search-service",
                "status": "confirmed",
                "evidence": "SearchService.search() implements this",
                "divergence": None,
            },
            {
                "source": {
                    "spec_file": "specs/product/search.md",
                    "section": "Overview",
                    "line": 10,
                },
                "claim_type": "performance",
                "claim_text": "Search results in under 200ms",
                "entity": "search-service",
                "status": "missing",
                "evidence": None,
                "divergence": "No latency SLA found in implementation",
            },
            {
                "source": {
                    "spec_file": "specs/product/auth.md",
                    "section": "Login",
                    "line": 3,
                },
                "claim_type": "security",
                "claim_text": "Passwords stored as bcrypt hashes",
                "entity": "auth-service",
                "status": "confirmed",
                "evidence": "UserModel.set_password() uses bcrypt",
                "divergence": None,
            },
        ]
    }


class TestSpecAlignmentQuery:
    """Verify specAlignment query executes through the compiled schema."""

    def test_missing_data_file_returns_null(self, tmp_path: Path) -> None:
        result = schema.execute_sync(
            SPEC_ALIGNMENT_QUERY,
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        assert result.data["specAlignment"] is None

    def test_full_nested_response_structure(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / ".speed" / "context" / "spec-alignment.json",
            _make_alignment_fixture(),
        )

        result = schema.execute_sync(
            SPEC_ALIGNMENT_QUERY,
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        data = result.data["specAlignment"]

        assert data["totalClaims"] == 3
        assert data["totalConfirmed"] == 2
        assert data["totalMissing"] == 1
        assert data["totalUnverifiable"] == 0
        assert data["overallCoveragePct"] == round(2 / 3 * 100, 1)

        assert len(data["specs"]) == 2
        spec_files = {s["specFile"] for s in data["specs"]}
        assert spec_files == {"specs/product/search.md", "specs/product/auth.md"}

        search_spec = next(s for s in data["specs"] if s["specFile"] == "specs/product/search.md")
        assert search_spec["totalClaims"] == 2
        assert search_spec["confirmed"] == 1
        assert search_spec["coveragePct"] == 50.0
        assert len(search_spec["sections"]) == 1

        overview = search_spec["sections"][0]
        assert overview["section"] == "Overview"
        assert overview["claimCount"] == 2
        assert overview["confirmed"] == 1
        assert overview["missing"] == 1
        assert overview["unverifiable"] == 0
        assert len(overview["claims"]) == 2

        confirmed_claim = next(c for c in overview["claims"] if c["status"] == "confirmed")
        assert confirmed_claim["claimType"] == "functional"
        assert confirmed_claim["entity"] == "search-service"
        assert confirmed_claim["evidence"] == "SearchService.search() implements this"
        assert confirmed_claim["divergence"] is None
        assert confirmed_claim["source"]["specFile"] == "specs/product/search.md"
        assert confirmed_claim["source"]["section"] == "Overview"
        assert confirmed_claim["source"]["line"] == 5

        missing_claim = next(c for c in overview["claims"] if c["status"] == "missing")
        assert missing_claim["divergence"] == "No latency SLA found in implementation"
        assert missing_claim["evidence"] is None

    def test_spec_file_filter_returns_filtered_results(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / ".speed" / "context" / "spec-alignment.json",
            _make_alignment_fixture(),
        )

        result = schema.execute_sync(
            SPEC_ALIGNMENT_FILTERED_QUERY,
            variable_values={"specFile": "search.md"},
            context_value=_make_context(tmp_path),
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        data = result.data["specAlignment"]

        assert data["totalClaims"] == 2
        assert len(data["specs"]) == 1
        assert data["specs"][0]["specFile"] == "specs/product/search.md"
        assert data["specs"][0]["totalClaims"] == 2
