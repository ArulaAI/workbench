"""Tests for semantic, model-backed guided-PRD interview planning."""

from __future__ import annotations

import hashlib
from pathlib import Path

from dashboard.backend import authoring_planner


def _coverage(status: str = "missing") -> dict:
    return {
        question_id: {
            "status": status,
            "confidence": 0.2 if status == "missing" else 0.95,
            "rationale": f"Assessment for {question_id} is based on the supplied description.",
            "resolved_value": (
                f"Resolved product requirement for {question_id}."
                if status == "covered"
                else None
            ),
        }
        for question_id in (
            "P-Q1", "P-Q2", "P-Q3", "P-Q4",
            "P-Q5", "P-Q6", "P-Q7", "P-Q8",
        )
    }


def test_design_planner_uses_published_upstream_and_shared_interview_contract(
    tmp_path: Path, monkeypatch
):
    spec_dir = tmp_path / "specs" / "task-due-dates"
    spec_dir.mkdir(parents=True)
    prd = spec_dir / "prd.md"
    published_content = "# PRD\n\nREQ-1: Users can set an optional due date."
    published_hash = hashlib.sha256(published_content.encode()).hexdigest()
    prd.write_text(
        "# PRD draft\n\nUnpublished reminders are being explored.",
        encoding="utf-8",
    )
    captured: dict = {}
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [{"id": "claude-code/sonnet"}],
    )
    monkeypatch.setattr(
        authoring_planner,
        "read_model_config",
        lambda _root: {"support_model": "sonnet"},
    )

    def fake_complete(**kwargs):
        captured.update(kwargs)
        return authoring_planner.CompactInterviewPlan.model_validate({
            "feature_title": "Task due dates",
            "analysis_summary": "Published product behavior resolves most design coverage; failure states need confirmation.",
            "prd_size": "Small",
            "resolved_coverage": [
                {
                    "coverage_id": f"D-Q{index}",
                    "resolved_value": f"Grounded design decision for D-Q{index} from the published PRD.",
                }
                for index in (1, 2, 3, 4, 6, 7, 8)
            ],
            "questions": [{
                "coverage_id": "D-Q5",
                "prompt": "How should loading, empty, invalid-date, offline, and retry states behave for due dates?",
                "response_type": "textarea",
                "suggested_answer": "Reuse the published PRD's invalid-date recovery behavior and confirm the remaining states.",
                "suggestion_confidence": "partial",
                "suggestion_gap": "Loading, offline, and overflow states still need confirmation.",
            }],
        })

    monkeypatch.setattr(authoring_planner, "llm_complete", fake_complete)
    plan = authoring_planner.plan_authoring(tmp_path, {
        "feature_name": "task-due-dates",
        "feature_title": "Task due dates",
        "artifact_type": "design",
        "intake": {"feature_title": "Task due dates"},
        "interview": [],
        "revision": 0,
        "upstream": {"prd": {
            "path": "specs/task-due-dates/prd.md",
            "sha256": published_hash,
            "content": published_content,
        }},
    })

    assert plan["planner_version"] == "model-downstream-v1"
    assert [item["id"] for item in plan["questions"]] == ["D-Q5"]
    assert set(plan["coverage"]) == {f"D-Q{index}" for index in range(1, 9)}
    assert "PUBLISHED PRD" in captured["messages"][1]["content"]
    assert "Users can set an optional due date" in captured["messages"][1]["content"]
    assert "Unpublished reminders" not in captured["messages"][1]["content"]
    assert captured["purpose"] == "guided_design_completeness_planning"
    assert plan["questions"][0]["suggestion"]["sources"] == [{
        "id": "published-upstream:prd",
        "path": "specs/task-due-dates/prd.md",
        "excerpt": f"Pinned published SHA-256: {published_hash}",
    }]


def test_model_plan_uses_support_model_and_fixed_context_package(
    tmp_path: Path, monkeypatch
):
    (tmp_path / ".speed" / "context").mkdir(parents=True)
    (tmp_path / ".speed" / "context" / "authoring-project-context.md").write_text(
        "Existing tasks are stored without a due-date field.",
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "task-platform.md").write_text(
        "Unrelated historical document that must not enter authoring context.",
        encoding="utf-8",
    )
    coverage = _coverage("covered")
    coverage["P-Q2"] = {
        "status": "partial",
        "confidence": 0.6,
        "rationale": "The description does not decide how undated tasks remain compatible.",
        "resolved_value": "Due dates are optional for newly created tasks.",
    }
    captured: dict = {}

    monkeypatch.setattr(
        authoring_planner,
        "read_model_config",
        lambda _root: {"planning_model": "opus", "support_model": "sonnet"},
    )
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [
            {"id": "claude-code/sonnet"},
            {"id": "claude-code/opus"},
        ],
    )

    def fake_complete(**kwargs):
        captured.update(kwargs)
        return authoring_planner.ModelInterviewPlan.model_validate({
            "feature_title": "Task due dates",
            "analysis_summary": (
                "The description covers the feature and happy path; only compatibility needs confirmation."
            ),
            "prd_size": "Standard",
            "coverage": coverage,
            "composition": {
                "requirements": [{
                    "story_id": "US-1",
                    "product_behavior": "Users can assign an optional due date to a task.",
                    "done_when": "Saving a valid date persists it and returns it on reload.",
                }],
                "guardrails": [{
                    "must_remain_true": "Existing undated tasks remain valid.",
                    "verification": "Loading and saving an undated task still succeeds.",
                }],
            },
            "questions": [{
                "coverage_id": "P-Q2",
                "prompt": (
                    "What should happen to existing tasks and new tasks that have no due date?"
                ),
                "response_type": "single_select",
                "options": [
                    {
                        "label": "Keep undated tasks unchanged",
                        "value": (
                            "Existing and new undated tasks remain valid and continue to work unchanged."
                        ),
                        "recommended": True,
                    },
                    {
                        "label": "Require due dates",
                        "value": "Every existing and new task must receive a due date.",
                    },
                ],
                "suggested_answer": (
                    "Existing and new undated tasks remain valid and continue to work unchanged."
                ),
                "suggestion_confidence": "partial",
                "suggestion_gap": "The backward-compatible default requires confirmation.",
            }],
        })

    monkeypatch.setattr(authoring_planner, "llm_complete", fake_complete)
    plan = authoring_planner.plan_authoring(tmp_path, {
        "feature_name": "task-due-dates",
        "feature_title": "Due dates for tasks",
        "intake": {
            "feature_description": (
                "Let users add optional due dates and highlight tasks due today or tomorrow."
            )
        },
        "interview": [],
        "revision": 0,
    })

    assert plan["mode"] == "model"
    assert plan["model"] == "claude-code/sonnet"
    assert plan["feature_title"] == "Task due dates"
    assert plan["prd_size"] == "Standard"
    assert plan["composition"]["requirements"][0]["done_when"].startswith("Saving")
    assert [question["id"] for question in plan["questions"]] == ["P-Q2"]
    assert plan["questions"][0]["response_control"]["input_type"] == "single_select"
    assert plan["questions"][0]["suggestion"]["confidence"] == "partial"
    assert plan["coverage"]["P-Q1"]["confidence_label"] == "evidence_backed"
    assert captured["model"] == "claude-code/sonnet"
    assert "There is no fixed minimum or maximum question count" in captured["messages"][0]["content"]
    assert "EXPLICIT AUTHOR TITLE\n[none; derive from the description]" in captured["messages"][1]["content"]
    assert "ROUTING SLUG (identifier only; do not treat as a title)\ntask-due-dates" in captured["messages"][1]["content"]
    assert "Due dates for tasks" not in captured["messages"][1]["content"]
    assert "PRD TEMPLATE AND COMPOSITION CONTRACT" in captured["messages"][1]["content"]
    assert "## Required structure" in captured["messages"][1]["content"]
    assert "COVERAGE ROUTING CONTRACT" in captured["messages"][1]["content"]
    assert "SOURCE .speed/context/authoring-project-context.md" in captured["messages"][1]["content"]
    assert "Existing tasks are stored without a due-date field." in captured["messages"][1]["content"]
    assert "Unrelated historical document" not in captured["messages"][1]["content"]
    assert captured["response_model"] is authoring_planner.CompactInterviewPlan
    assert captured["purpose"] == "guided_prd_completeness_planning"
    assert captured["max_tokens"] == 4096


def test_compact_plan_expands_into_stable_guided_authoring_contract(
    tmp_path: Path, monkeypatch
):
    captured: dict = {}
    monkeypatch.setattr(
        authoring_planner,
        "read_model_config",
        lambda _root: {"planning_model": "opus"},
    )
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [{"id": "claude-code/opus"}],
    )

    def fake_complete(**kwargs):
        captured.update(kwargs)
        return authoring_planner.CompactInterviewPlan.model_validate({
            "feature_title": "Optional Task Due Dates",
            "analysis_summary": (
                "The brief resolves the user and behavior while leaving compatibility and scope open."
            ),
            "prd_size": "Small",
            "resolved_coverage": [
                {
                    "coverage_id": "P-Q1",
                    "resolved_value": "Individual task owners need deadline-aware ordering.",
                    "confidence": 0.92,
                },
                {
                    "coverage_id": "P-Q4",
                    "resolved_value": "Tasks accept an optional due date and sort earliest first.",
                    "confidence": 0.9,
                },
                {
                    "coverage_id": "P-Q7",
                    "resolved_value": "V1 includes setting dates and excludes reminders.",
                    "confidence": 0.7,
                },
            ],
            "questions": [
                {
                    "coverage_id": "P-Q2",
                    "prompt": "How should existing and new tasks without due dates behave?",
                    "response_type": "single_select",
                    "options": [
                        {
                            "label": "Keep them unchanged",
                            "value": "Existing and new undated tasks remain valid and unchanged.",
                            "recommended": True,
                        },
                        {
                            "label": "Require a due date",
                            "value": "Every task must receive a due date before it can be saved.",
                        },
                    ],
                    "suggested_answer": "Existing and new undated tasks remain valid and unchanged.",
                    "suggestion_confidence": "partial",
                    "suggestion_gap": "Backward compatibility needs confirmation.",
                },
                {
                    "coverage_id": "P-Q7",
                    "prompt": "Which capabilities should define the first due-date release?",
                    "response_type": "multi_select",
                    "options": [
                        {
                            "label": "Set and edit dates",
                            "value": "Include setting and editing a due date.",
                            "recommended": True,
                        },
                        {
                            "label": "No reminders",
                            "value": "Exclude reminders and notifications from V1.",
                            "recommended": True,
                        },
                    ],
                },
            ],
        })

    monkeypatch.setattr(authoring_planner, "llm_complete", fake_complete)
    plan = authoring_planner.plan_authoring(tmp_path, {
        "feature_name": "task-due-dates",
        "intake": {"feature_description": "Add optional due dates and sort tasks earliest first."},
        "interview": [],
    })

    assert plan["mode"] == "model"
    assert plan["planner_version"] == "model-prd-v5"
    assert plan["optimization"] == "complete-template-intake-v1"
    assert plan["feature_title"] == "Optional Task Due Dates"
    assert plan["composition"] == {
        "requirements": [],
        "scope": None,
        "guardrails": [],
        "success": None,
    }
    assert plan["coverage"]["P-Q1"]["confidence_label"] == "evidence_backed"
    assert plan["coverage"]["P-Q3"]["confidence_label"] == "not_material"
    assert plan["coverage"]["P-Q3"]["confidence"] < 1.0
    assert plan["coverage"]["P-Q7"]["confidence_label"] == "unresolved"
    assert [question["id"] for question in plan["questions"]] == ["P-Q2", "P-Q7"]
    assert plan["questions"][1]["response_control"]["options"][1]["label"] == (
        "Exclude — No reminders"
    )
    assert captured["response_model"] is authoring_planner.CompactInterviewPlan


def test_compact_plan_missing_required_coverage_falls_back(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(authoring_planner, "read_model_config", lambda _root: {})
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [{"id": "claude-code/sonnet"}],
    )
    monkeypatch.setattr(
        authoring_planner,
        "llm_complete",
        lambda **_kwargs: authoring_planner.CompactInterviewPlan.model_validate({
            "feature_title": "Optional Task Due Dates",
            "analysis_summary": "The result intentionally omits required coverage for validation.",
            "resolved_coverage": [{
                "coverage_id": "P-Q1",
                "resolved_value": "Task owners need deadline-aware ordering.",
            }],
            "questions": [],
        }),
    )

    plan = authoring_planner.plan_authoring(tmp_path, {
        "feature_name": "task-due-dates",
        "intake": {"feature_description": "Add optional due dates to tasks."},
        "interview": [],
    })

    assert plan["mode"] == "fallback"
    assert "omitted required coverage" in plan["fallback_reason"]


def test_compact_plan_accepts_semantic_coverage_labels_as_stable_id_aliases(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(authoring_planner, "read_model_config", lambda _root: {})
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [{"id": "claude-code/sonnet"}],
    )
    monkeypatch.setattr(
        authoring_planner,
        "llm_complete",
        lambda **_kwargs: authoring_planner.CompactInterviewPlan.model_validate({
            "feature_title": "Optional Task Due Dates",
            "analysis_summary": "Every required area is resolved using semantic coverage labels.",
            "resolved_coverage": [
                {
                    "coverage_id": coverage_id,
                    "resolved_value": f"Resolved product evidence for {coverage_id}.",
                }
                for coverage_id in (
                    "problem_evidence",
                    "user_boundary",
                    "product_behavior",
                    "scope_dependencies",
                )
            ],
            "questions": [],
        }),
    )

    plan = authoring_planner.plan_authoring(tmp_path, {
        "feature_name": "task-due-dates",
        "intake": {"feature_description": "Add optional due dates to tasks."},
        "interview": [],
    })

    assert plan["mode"] == "model"
    assert plan["coverage"]["P-Q1"]["resolved_value"].endswith("problem_evidence.")
    assert plan["coverage"]["P-Q7"]["resolved_value"].endswith("scope_dependencies.")


def test_scope_multiselect_options_name_inclusions_and_exclusions(
    tmp_path: Path, monkeypatch
):
    coverage = _coverage("covered")
    coverage["P-Q7"] = {
        "status": "partial",
        "confidence": 0.5,
        "rationale": "The initial request does not settle the complete V1 boundary.",
        "resolved_value": "Due-date display is included, but adjacent features are undecided.",
    }
    monkeypatch.setattr(
        authoring_planner,
        "read_model_config",
        lambda _root: {"planning_model": "opus"},
    )
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [{"id": "claude-code/opus"}],
    )
    monkeypatch.setattr(
        authoring_planner,
        "llm_complete",
        lambda **_kwargs: authoring_planner.ModelInterviewPlan.model_validate({
            "feature_title": "Task due dates",
            "analysis_summary": "Only the exact product boundary needs confirmation.",
            "coverage": coverage,
            "questions": [{
                "coverage_id": "P-Q7",
                "prompt": "Which capabilities define the V1 due-date boundary?",
                "response_type": "multi_select",
                "options": [
                    {
                        "label": "Set, edit, and clear dates",
                        "value": "Include setting, editing, and clearing due dates.",
                        "recommended": True,
                    },
                    {
                        "label": "No reminders or notifications",
                        "value": "Exclude reminders and notifications from V1.",
                        "recommended": True,
                    },
                ],
            }],
        }),
    )

    plan = authoring_planner.plan_authoring(tmp_path, {
        "feature_name": "task-due-dates",
        "intake": {"feature_description": "Add optional due dates to tasks."},
        "interview": [],
    })

    control = plan["questions"][0]["response_control"]
    assert control["prompt"] == (
        "Select every inclusion and exclusion that should define V1."
    )
    assert [option["label"] for option in control["options"]] == [
        "Include — Set, edit, and clear dates",
        "Exclude — No reminders or notifications",
    ]


def test_unavailable_model_returns_visible_deterministic_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(authoring_planner, "read_model_config", lambda _root: {})
    monkeypatch.setattr(authoring_planner, "get_available_models", lambda _root: [])

    plan = authoring_planner.plan_authoring(tmp_path, {
        "feature_name": "task-due-dates",
        "intake": {"feature_description": "Add optional due dates to tasks."},
        "interview": [],
    })

    assert plan["mode"] == "fallback"
    assert "No configured LLM is available" in plan["fallback_reason"]
    assert "deterministic fallback" in plan["analysis_summary"]


def test_multiple_missing_decisions_in_one_coverage_are_preserved(
    tmp_path: Path, monkeypatch
):
    coverage = _coverage("covered")
    coverage["P-Q2"] = {
        "status": "missing",
        "confidence": 0.2,
        "rationale": "The description does not define compatibility for existing tasks.",
        "resolved_value": None,
    }
    monkeypatch.setattr(
        authoring_planner,
        "read_model_config",
        lambda _root: {"planning_model": "opus"},
    )
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [{"id": "claude-code/opus"}],
    )
    monkeypatch.setattr(
        authoring_planner,
        "llm_complete",
        lambda **_kwargs: authoring_planner.ModelInterviewPlan.model_validate({
            "feature_title": "Task labels",
            "analysis_summary": (
                "The description is usable, but compatibility needs one product decision."
            ),
            "coverage": coverage,
            "questions": [
                {
                    "coverage_id": "P-Q2",
                    "prompt": "Should existing tasks without labels remain valid after launch?",
                    "response_type": "textarea",
                    "options": [],
                },
                {
                    "coverage_id": "P-Q2",
                    "prompt": "How should existing unlabeled tasks behave after launch?",
                    "response_type": "textarea",
                    "options": [],
                },
                {
                    "coverage_id": "P-Q2",
                    "prompt": "How should API clients that omit labels behave after launch?",
                    "response_type": "textarea",
                    "options": [],
                },
                {
                    "coverage_id": "P-Q2",
                    "prompt": "Which user roles may assign or remove task labels?",
                    "response_type": "textarea",
                    "options": [],
                },
            ],
        }),
    )

    plan = authoring_planner.plan_authoring(tmp_path, {
        "feature_name": "task-labels",
        "intake": {"feature_description": "Add color-coded labels to tasks."},
        "interview": [],
    })

    assert plan["mode"] == "model"
    assert [question["id"] for question in plan["questions"]] == [
        "P-Q2-1",
        "P-Q2-2",
        "P-Q2-3",
        "P-Q2-4",
    ]
    assert [question["coverage_id"] for question in plan["questions"]] == [
        "P-Q2",
        "P-Q2",
        "P-Q2",
        "P-Q2",
    ]
    assert plan["questions"][0]["prompt"] == (
        "Should existing tasks without labels remain valid after launch?"
    )


def test_question_for_covered_area_is_reconciled_instead_of_discarding_plan(
    tmp_path: Path, monkeypatch
):
    coverage = _coverage("covered")
    monkeypatch.setattr(
        authoring_planner,
        "read_model_config",
        lambda _root: {"planning_model": "opus"},
    )
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [{"id": "claude-code/opus"}],
    )
    monkeypatch.setattr(
        authoring_planner,
        "llm_complete",
        lambda **_kwargs: authoring_planner.ModelInterviewPlan.model_validate({
            "feature_title": "Task due dates",
            "analysis_summary": "Compatibility is mostly described but still needs confirmation.",
            "coverage": coverage,
            "questions": [{
                "coverage_id": "P-Q2",
                "prompt": "How should existing tasks without due dates continue to behave?",
                "response_type": "textarea",
                "options": [],
            }],
        }),
    )

    plan = authoring_planner.plan_authoring(tmp_path, {
        "feature_name": "task-due-dates",
        "intake": {"feature_description": "Add optional due dates to tasks."},
        "interview": [],
    })

    assert plan["mode"] == "model"
    assert plan["feature_title"] == "Task due dates"
    assert plan["coverage"]["P-Q2"]["confidence_label"] == "unresolved"
    assert plan["coverage"]["P-Q2"]["resolved_value"] is None
    assert [question["id"] for question in plan["questions"]] == ["P-Q2"]


def test_confirmed_answer_is_never_reasked(tmp_path: Path, monkeypatch):
    coverage = _coverage("covered")
    coverage["P-Q2"] = {
        "status": "partial",
        "confidence": 0.5,
        "rationale": "The model incorrectly proposes asking the confirmed compatibility decision.",
        "resolved_value": "Undated tasks remain valid.",
    }
    monkeypatch.setattr(
        authoring_planner,
        "read_model_config",
        lambda _root: {"planning_model": "opus"},
    )
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [{"id": "claude-code/opus"}],
    )
    monkeypatch.setattr(
        authoring_planner,
        "llm_complete",
        lambda **_kwargs: authoring_planner.ModelInterviewPlan.model_validate({
            "feature_title": "Task due dates",
            "analysis_summary": "The planner proposes a duplicate question and must be rejected safely.",
            "coverage": coverage,
            "questions": [{
                "coverage_id": "P-Q2",
                "prompt": "Should existing tasks without due dates remain valid after launch?",
                "response_type": "textarea",
                "options": [],
            }],
        }),
    )

    plan = authoring_planner.plan_authoring(tmp_path, {
        "feature_name": "task-due-dates",
        "intake": {"feature_description": "Add optional due dates to tasks."},
        "interview": [{
            "id": "P-Q2",
            "prompt": "What happens to undated tasks?",
            "answer": "Existing and new undated tasks remain valid.",
            "state": "confirmed",
        }],
    })

    assert plan["mode"] == "fallback"
    assert "Already confirmed coverage P-Q2 was asked again" in plan["fallback_reason"]


def test_new_material_gap_is_asked_after_an_existing_answer(
    tmp_path: Path, monkeypatch
):
    coverage = _coverage("covered")
    coverage["P-Q6"] = {
        "status": "missing",
        "confidence": 0.1,
        "rationale": "No post-launch metric appears in the supplied product request.",
        "resolved_value": None,
    }
    monkeypatch.setattr(
        authoring_planner,
        "read_model_config",
        lambda _root: {"planning_model": "opus"},
    )
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [{"id": "claude-code/opus"}],
    )
    monkeypatch.setattr(
        authoring_planner,
        "llm_complete",
        lambda **_kwargs: authoring_planner.ModelInterviewPlan.model_validate({
            "feature_title": "Task due dates",
            "analysis_summary": "Required product decisions are usable; measurement is still absent.",
            "coverage": coverage,
            "questions": [{
                "coverage_id": "P-Q6",
                "prompt": "Which post-launch signal should be used to measure due-date success?",
                "response_type": "textarea",
                "options": [],
            }],
        }),
    )
    interview = [{
        "id": "P-Q2",
        "prompt": "Who needs due dates?",
        "answer": "Task owners need due dates and existing tasks remain valid.",
        "state": "confirmed",
    }]

    plan = authoring_planner.plan_authoring(tmp_path, {
        "feature_name": "task-due-dates",
        "intake": {"feature_description": "Add optional due dates to tasks."},
        "interview": interview,
    })

    assert plan["mode"] == "model"
    assert [question["id"] for question in plan["questions"]] == ["P-Q6"]
    assert plan["planner_version"] == "model-prd-v5"


def test_review_comments_rewrite_exact_affected_sections_with_current_prd_context(
    tmp_path: Path, monkeypatch
):
    captured: dict = {}
    monkeypatch.setattr(
        authoring_planner,
        "read_model_config",
        lambda _root: {"planning_model": "opus"},
    )
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [{"id": "claude-code/opus"}],
    )

    def fake_complete(**kwargs):
        captured.update(kwargs)
        return authoring_planner.PrdReviewRevision.model_validate({
            "analysis_summary": (
                "The API color contract becomes a testable requirement in the existing table."
            ),
            "sections": [{
                "section_title": "Requirements & Acceptance",
                "revised_body": (
                    "| ID | Story | Product behavior | Done when |\n"
                    "|---|---|---|---|\n"
                    "| REQ-4 | US-1 | The API returns the due-status color as a hex value. "
                    "| A task response includes a valid six-digit hex color used by the list. |"
                ),
            }],
        })

    monkeypatch.setattr(authoring_planner, "llm_complete", fake_complete)
    current_prd = (
        "# PRD: Due dates\n\n## Requirements & Acceptance\n\n"
        "| ID | Story | Product behavior | Done when |\n|---|---|---|---|\n"
        "| REQ-1 | US-1 | Tasks accept due dates. | A saved date is returned. |\n"
    )
    comments = [{
        "section_title": "Requirements & Acceptance",
        "comment": "Add the API color-code contract in hex format.",
    }]

    revision = authoring_planner.revise_prd_from_comments(
        tmp_path,
        {
            "feature_name": "task-due-dates",
            "feature_title": "Due dates",
            "intake": {"feature_description": "Add optional task due dates."},
            "interview": [],
        },
        comments,
        current_prd,
    )

    assert revision["model"] == "claude-code/opus"
    assert revision["sections"][0]["section_title"] == "Requirements & Acceptance"
    assert "six-digit hex color" in revision["sections"][0]["revised_body"]
    prompt = captured["messages"][1]["content"]
    assert current_prd in prompt
    assert "Add the API color-code contract" in prompt
    assert captured["purpose"] == "guided_prd_review_regeneration"


def test_review_regeneration_rejects_an_unrequested_model_section(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        authoring_planner,
        "read_model_config",
        lambda _root: {"planning_model": "opus"},
    )
    monkeypatch.setattr(
        authoring_planner,
        "get_available_models",
        lambda _root: [{"id": "claude-code/opus"}],
    )
    monkeypatch.setattr(
        authoring_planner,
        "llm_complete",
        lambda **_kwargs: authoring_planner.PrdReviewRevision.model_validate({
            "analysis_summary": "The model incorrectly changes an extra PRD section.",
            "sections": [
                {
                    "section_title": "Scope",
                    "revised_body": "| Included | Not included |\n|---|---|\n| Due dates | Reminders |",
                },
                {
                    "section_title": "Summary",
                    "revised_body": "This unrequested summary must be rejected by validation.",
                },
            ],
        }),
    )

    try:
        authoring_planner.revise_prd_from_comments(
            tmp_path,
            {"feature_name": "task-due-dates", "intake": {}, "interview": []},
            [{"section_title": "Scope", "comment": "Exclude reminders."}],
            "# PRD\n\n## Scope\n\nExisting scope.",
        )
    except ValueError as exc:
        assert "unexpected Summary" in str(exc)
    else:
        raise AssertionError("An unrequested model section should be rejected")
