"""Resolver tests: projecting the helper result onto the GraphQL surface."""

from __future__ import annotations

from pathlib import Path
import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

pytest.importorskip("strawberry")

from dashboard.backend.resolvers import authoring as resolver
from dashboard.backend.resolvers.authoring_types import AuthoringAction

DESCRIPTION = (
    "Team leads cannot see which tasks are overdue; due dates live in ticket "
    "titles today, so nothing can be sorted or alerted on."
)

DETAILED_DESCRIPTION = (
    "Users add tasks that may not be due until next week and can forget them as new "
    "tasks push them down the list. Let users select an optional due date while adding "
    "a task, highlight dates that are today, tomorrow, or approaching, and show tasks "
    "with earlier due dates before later or undated tasks."
)
ANSWERS = {
    "P-Q1": "Team leads cannot see due work until they open each task, which delays planning.",
    "P-Q2": "Team leads use the feature; contributors keep their existing access.",
    "P-Q3": "Overdue work becomes visible while completion behavior and accessibility do not regress.",
    "P-Q4": "A lead opens the board, sees and filters due work, and receives a clear error for an invalid date. Given overdue work, when the filter is applied, then matching tasks remain visible.",
    "P-Q5": "Given an invalid date, when it is saved, then an inline error appears and no task data changes.",
    "P-Q6": "Within 30 days, ninety percent of leads identify overdue work within 30 seconds; Product Analytics owns it.",
    "P-Q7": "Board display and editing are included; reminders and notifications are excluded from V1.",
    "P-Q8": "Editors may change dates; viewers cannot, and Product owns timezone and audit decisions.",
}


@pytest.mark.parametrize("status", ["drafted", "drafted_with_open_questions", "published"])
def test_replan_never_mutates_a_terminal_artifact(
    tmp_path: Path, monkeypatch, status: str
):
    payload = {"status": status, "revision": 7}
    monkeypatch.setattr(
        resolver.authoring_planner,
        "plan_authoring",
        lambda *_args, **_kwargs: pytest.fail("terminal artifacts must not be replanned"),
    )

    result = resolver._replan_payload(tmp_path, "task-due-dates", "prd", payload)

    assert result is payload


def _complete(tmp_path: Path):
    session = resolver.start(tmp_path, "task-due-dates", "prd", "Due dates for tasks", DESCRIPTION)
    for _ in range(10):
        if session.status in {"drafted", "drafted_with_open_questions"}:
            return session
        session = resolver.submit_answer(
            tmp_path, "task-due-dates", "prd",
            ANSWERS[session.current_question["id"]], session.revision,
        )
    raise AssertionError("PRD interview did not complete")


def test_intake_returns_one_description_field_without_a_character_limit(tmp_path: Path):
    intake = resolver.get_intake(tmp_path, "prd")

    assert intake.status == "needs_input"
    assert intake.next_input["id"] == "new_prd_basics"
    field_ids = [field["id"] for field in intake.next_input["fields"]]
    assert field_ids == ["feature_description"]
    assert "max_length" not in intake.next_input["fields"][0]


def test_session_of_unknown_feature_is_not_started_and_writes_nothing(tmp_path: Path):
    session = resolver.get_session(tmp_path, "task-due-dates", "prd")

    assert session.status == "not_started"
    assert session.revision is None
    assert session.artifact_content is None
    assert not (tmp_path / ".speed").exists()


def test_start_returns_a_question_without_generating_a_draft(tmp_path: Path):
    session = resolver.start(
        tmp_path, "task-due-dates", "prd", "Due dates for tasks", DESCRIPTION
    )

    assert session.status == "question"
    assert session.feature_title == "Due dates for tasks"
    assert session.draft_available is False
    assert session.artifact_path is None
    assert session.artifact_content is None
    assert session.current_question["response_control"]["id"]
    assert session.sections
    assert session.authoring_url is None
    assert session.intake["feature_title"] == "Due dates for tasks"
    assert session.intake["feature_description"] == DESCRIPTION
    assert session.interview == []


def test_replan_uses_the_model_derived_title_instead_of_the_client_guess(
    tmp_path: Path, monkeypatch
):
    coverage = {
        f"P-Q{index}": {
            "coverage": f"Coverage {index}",
            "confidence": 0.9,
            "confidence_label": "evidence_backed",
            "impact": "medium",
            "basis": ["The author description supports this assessment."],
            "rationale": "The author description supports this assessment.",
            "resolved_value": f"Resolved value for P-Q{index}.",
            "question_value": 0.1,
        }
        for index in range(1, 9)
    }
    planned = {
        "mode": "model",
        "planner_version": "model-prd-v5",
        "model": "test/planner",
        "feature_title": "Task due dates and urgency ordering",
        "generated_at": "2026-09-08T00:00:00+00:00",
        "analysis_summary": "Only the compatibility boundary still needs confirmation.",
        "prd_size": "Small",
        "coverage": coverage,
        "questions": [{
            "id": "P-Q2",
            "coverage": "Compatibility",
            "prompt": "How should existing tasks without due dates continue to behave?",
            "purpose": "Confirm compatibility.",
            "evidence": "The description says due dates are optional.",
            "response_control": {
                "id": "model-answer-p-q2",
                "input_type": "single_select",
                "prompt": "Choose the compatibility behavior.",
                "initial_value": "",
                "options": [
                    {"value": "Existing undated tasks remain valid.", "label": "Keep valid"},
                    {"value": "Every task requires a due date.", "label": "Require dates"},
                ],
                "submit_action": "answer",
                "allow_other": True,
            },
            "suggestion": {
                "id": "model-p-q2-0",
                "answer": None,
                "confidence": "missing",
                "accept_ready": False,
                "sources": [],
                "gaps": [],
                "created_at": "2026-09-08T00:00:00+00:00",
                "rejected": False,
            },
        }],
        "composition": {"requirements": [], "scope": None, "guardrails": [], "success": None},
        "fallback_reason": None,
    }
    monkeypatch.setattr(resolver.authoring_planner, "plan_authoring", lambda *_args: planned)

    started = resolver.start(
        tmp_path,
        "when-the-user-adds-the-task-they-will-have",
        "prd",
        "When the user adds the task, they will have",
        DESCRIPTION,
    )
    session = resolver.replan(
        tmp_path,
        "when-the-user-adds-the-task-they-will-have",
        "prd",
        started.revision,
    )

    assert session.feature_name == "when-the-user-adds-the-task-they-will-have"
    assert session.feature_title == "Task due dates and urgency ordering"
    assert session.intake["feature_title"] == "Task due dates and urgency ordering"


def test_duplicate_automatic_replans_share_the_completed_result(
    tmp_path: Path, monkeypatch
):
    """A same-tab remount must not turn its own planning write into a conflict."""
    state = {
        "status": "question",
        "feature_name": "task-due-dates",
        "feature_title": None,
        "artifact_type": "prd",
        "revision": 0,
        "planning": {"mode": "fallback", "planner_version": None},
    }
    state_guard = threading.Lock()
    planner_started = threading.Event()
    finish_planning = threading.Event()
    planning_calls = 0

    def fake_helper_run(_root, _artifact, _feature, *args):
        nonlocal state
        with state_guard:
            if "--peek" in args:
                return copy.deepcopy(state)
            state = {
                **state,
                "revision": 1,
                "planning": {
                    "mode": "model",
                    "planner_version": resolver.authoring_planner.PLANNER_VERSION,
                },
            }
            return copy.deepcopy(state)

    def fake_plan(*_args, **_kwargs):
        nonlocal planning_calls
        planning_calls += 1
        planner_started.set()
        assert finish_planning.wait(timeout=2)
        return {"mode": "model", "questions": []}

    monkeypatch.setattr(resolver.authoring_helper, "run", fake_helper_run)
    monkeypatch.setattr(resolver.authoring_planner, "plan_authoring", fake_plan)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(resolver.replan, tmp_path, "task-due-dates", "prd", 0)
        assert planner_started.wait(timeout=1)
        second = pool.submit(resolver.replan, tmp_path, "task-due-dates", "prd", 0)
        time.sleep(0.05)
        finish_planning.set()
        results = [first.result(timeout=2), second.result(timeout=2)]

    assert planning_calls == 1
    assert [result.revision for result in results] == [1, 1]
    assert all(result.status == "question" for result in results)


def test_failed_automatic_replan_does_not_generate_a_partial_draft(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        resolver.authoring_planner,
        "plan_authoring",
        lambda *_args, **_kwargs: resolver.authoring_planner.fallback_plan(
            "Planner temporarily unavailable.", "test/planner"
        ),
    )
    started = resolver.start(
        tmp_path, "task-due-dates", "prd", None, DESCRIPTION
    )

    replanned = resolver.replan(
        tmp_path, "task-due-dates", "prd", started.revision
    )

    assert replanned.revision == started.revision + 1
    assert replanned.artifact_content == started.artifact_content
    assert replanned.versions == started.versions
    assert replanned.planning["mode"] == "fallback"
    assert replanned.planning["planner_version"] == resolver.authoring_planner.PLANNER_VERSION


def test_detailed_intake_asks_every_missing_material_decision(tmp_path: Path):
    session = resolver.start(
        tmp_path,
        "task-due-dates",
        "prd",
        "Due dates for tasks",
        DETAILED_DESCRIPTION,
    )

    assert session.progress.total == 4
    assert session.current_question["id"] == "P-Q2"
    assert "existing behavior" in session.current_question["prompt"]
    assert "task due dates" in session.current_question["prompt"]
    assert "what should they be able to accomplish" in session.current_question["prompt"]
    assert session.coverage["P-Q3"]["confidence_label"] == "inferred"
    assert session.coverage["P-Q8"]["confidence_label"] == "not_material"
    assert session.current_question["suggestion"]["confidence"] == "partial"
    assert session.current_question["suggestion"]["accept_ready"] is False
    assert "Existing tasks without a due date remain valid" in (
        session.current_question["suggestion"]["answer"]
    )
    option_labels = [
        option["label"]
        for option in session.current_question["response_control"]["options"]
    ]
    assert "Edit suggestion" in option_labels

    after_compatibility = resolver.submit_answer(
        tmp_path,
        "task-due-dates",
        "prd",
        "Existing tasks and new tasks without a due date remain valid and keep their "
        "current behavior; undated tasks appear after tasks with due dates.",
        session.revision,
    )
    assert after_compatibility.current_question["id"] == "P-Q4"
    assert "happy path" in after_compatibility.current_question["prompt"]
    assert "failure or recovery path" in after_compatibility.current_question["prompt"]

    after_recovery = resolver.submit_answer(
        tmp_path,
        "task-due-dates",
        "prd",
        "If the date is invalid or saving fails, preserve the entered task values, "
        "show a clear error, and let the user correct the date and retry.",
        after_compatibility.revision,
    )
    assert after_recovery.current_question["id"] == "P-Q5"

    after_acceptance = resolver.submit_answer(
        tmp_path,
        "task-due-dates",
        "prd",
        "Given an invalid date, when save is attempted, then an inline error appears, "
        "the task is unchanged, and the entered values remain available for correction.",
        after_recovery.revision,
    )
    assert after_acceptance.current_question["id"] == "P-Q7"
    assert "explicitly included or excluded" in after_acceptance.current_question["prompt"]

    drafted = resolver.submit_answer(
        tmp_path,
        "task-due-dates",
        "prd",
        "Exclude reminders, notifications, recurring schedules, and due times from "
        "V1. There is no external delivery dependency.",
        after_acceptance.revision,
    )
    assert drafted.status == "drafted"
    assert "Let users select an optional due date" in drafted.artifact_content
    assert "highlight dates that are today, tomorrow, or approaching" in drafted.artifact_content
    assert "If the date is invalid or saving fails" in drafted.artifact_content
    assert "As a user, I want to select an optional due date" in drafted.artifact_content


def test_adaptive_suggestion_prefills_the_edit_control(tmp_path: Path):
    session = resolver.start(
        tmp_path,
        "task-due-dates",
        "prd",
        "Due dates for tasks",
        DETAILED_DESCRIPTION,
    )
    suggestion = session.current_question["suggestion"]["answer"]

    editing = resolver.select_action(
        tmp_path,
        "task-due-dates",
        "prd",
        AuthoringAction.EDIT,
        session.revision,
    )

    assert editing.current_question["response_control"]["input_type"] == "textarea"
    assert editing.current_question["response_control"]["initial_value"] == suggestion


def test_short_targeted_answer_gets_a_focused_prefilled_follow_up(tmp_path: Path):
    session = resolver.start(
        tmp_path,
        "task-due-dates",
        "prd",
        "Due dates for tasks",
        DETAILED_DESCRIPTION,
    )

    follow_up = resolver.submit_answer(
        tmp_path,
        "task-due-dates",
        "prd",
        "Remain valid.",
        session.revision,
    )

    control = follow_up.current_question["response_control"]
    assert control["id"] == "follow_up_answer"
    assert "existing cases must remain valid and unchanged" in control["prompt"]
    assert "who needs the outcome" not in control["prompt"]
    assert control["initial_value"] == session.current_question["suggestion"]["answer"]


def test_vague_intake_still_asks_for_missing_user_and_outcome(tmp_path: Path):
    session = resolver.start(
        tmp_path,
        "task-due-dates",
        "prd",
        "Due dates for tasks",
        "Add due dates to tasks.",
    )

    assert session.current_question["id"] == "P-Q2"
    assert "who needs the outcome" in session.current_question["prompt"]


def test_answer_advances_the_conversation_without_exposing_a_partial_draft(tmp_path: Path):
    started = resolver.start(tmp_path, "task-due-dates", "prd", None, DESCRIPTION)

    answered = resolver.submit_answer(
        tmp_path,
        "task-due-dates",
        "prd",
        "Tasks accept an optional due date; the board filters to overdue tasks. "
        "Given a past due date, when the overdue filter is applied, then the task "
        "appears with an overdue badge.",
        started.revision,
    )

    assert answered.revision > started.revision
    assert answered.progress.confirmed >= 1
    assert answered.current_question["id"] != started.current_question["id"]
    assert answered.artifact_content is None
    assert answered.draft_available is False
    assert len(answered.interview) == 1
    assert answered.interview[0]["id"] == started.current_question["id"]
    assert answered.interview[0]["prompt"] == started.current_question["prompt"]
    assert "optional due date" in answered.interview[0]["answer"]
    assert answered.interview[0]["state"] == "confirmed"
    assert answered.interview[0]["decision"] == "edited"
    assert answered.interview[0]["confirmed_at"]


def test_answer_does_not_invoke_the_model_planner(
    tmp_path: Path, monkeypatch
):
    original = resolver.authoring_planner.plan_authoring
    calls: list[int] = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(resolver.authoring_planner, "plan_authoring", counted)
    started = resolver.start(tmp_path, "task-due-dates", "prd", None, DESCRIPTION)
    assert len(calls) == 0

    answered = resolver.submit_answer(
        tmp_path,
        "task-due-dates",
        "prd",
        ANSWERS[started.current_question["id"]],
        started.revision,
    )

    assert answered.current_question is not None
    assert len(calls) == 0


def test_batch_answers_are_saved_and_generated_without_a_second_model_wait(
    tmp_path: Path, monkeypatch
):
    original = resolver.authoring_planner.plan_authoring
    calls: list[int] = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(resolver.authoring_planner, "plan_authoring", counted)
    started = resolver.start(tmp_path, "task-due-dates", "prd", None, DESCRIPTION)
    state_path = tmp_path / ".speed/features/task-due-dates/authoring-prd.json"
    state = json.loads(state_path.read_text())
    question_ids = state["clarification_plan"]
    planning_calls_after_start = len(calls)

    drafted = resolver.submit_answers(
        tmp_path,
        "task-due-dates",
        "prd",
        [
            {"question_id": question_id, "answer": ANSWERS[question_id]}
            for question_id in question_ids
        ],
        started.revision,
    )

    assert drafted.status == "drafted"
    assert drafted.progress.confirmed == len(question_ids)
    assert len(question_ids) > 3
    assert len(calls) == planning_calls_after_start


def test_direct_section_revision_is_returned_and_persisted(tmp_path: Path):
    started = _complete(tmp_path)

    revised = resolver.revise_section(
        tmp_path,
        "task-due-dates",
        "prd",
        "Summary",
        "A concise manually reviewed summary for task due dates.",
        started.revision,
    )

    assert revised.revision > started.revision
    assert "A concise manually reviewed summary" in revised.artifact_content
    summary = next(section for section in revised.sections if section["title"] == "Summary")
    assert summary["state"] == "manual"


def test_complete_document_revision_preserves_version_history(tmp_path: Path):
    drafted = _complete(tmp_path)
    editable = drafted.artifact_content[drafted.artifact_content.index("## "):]
    edited = editable.replace(
        "## Summary\n",
        "## Summary\n\nThis draft was refined in the embedded editor.\n\n",
        1,
    )

    revised = resolver.revise_document(
        tmp_path,
        "task-due-dates",
        "prd",
        edited,
        drafted.revision,
    )

    assert revised.revision == drafted.revision + 1
    assert "This draft was refined in the embedded editor." in revised.artifact_content
    versions = {item["revision"]: item["content"] for item in revised.versions}
    assert drafted.revision in versions
    assert revised.revision in versions
    assert versions[drafted.revision] == drafted.artifact_content


def test_coverage_revision_keeps_the_original_question_in_interview_history(
    tmp_path: Path,
):
    drafted = _complete(tmp_path)
    original = next(item for item in drafted.interview if item["id"] == "P-Q2")

    revised = resolver.revise_coverage(
        tmp_path,
        "task-due-dates",
        "prd",
        "P-Q2",
        "All task owners need due dates while existing undated tasks remain valid.",
        drafted.revision,
    )

    updated = next(item for item in revised.interview if item["id"] == "P-Q2")
    assert updated["prompt"] == original["prompt"]
    assert not updated["prompt"].startswith("Draft review update")
    assert updated["answer"].startswith("All task owners")


def test_review_comments_reconsider_multiple_sections_in_one_model_revision(
    tmp_path: Path, monkeypatch
):
    drafted = _complete(tmp_path)
    captured: dict = {}

    def fake_review(_root, payload, comments, current_content):
        captured["payload"] = payload
        captured["comments"] = comments
        captured["current_content"] = current_content
        return {
            "model": "test/reviewer",
            "analysis_summary": "Both commented sections were reconsidered in context.",
            "sections": [
                {
                    "section_title": "Scope",
                    "revised_body": (
                        "| Included | Not included |\n"
                        "|---|---|\n"
                        "| Due-date display and editing | Reminders and calendar export |"
                    ),
                },
                {
                    "section_title": "Requirements & Acceptance",
                    "revised_body": (
                        "| ID | Story | Product behavior | Done when |\n"
                        "|---|---|---|---|\n"
                        "| REQ-1 | US-1 | Invalid due dates do not discard other task edits. "
                        "| Given an invalid date and other edits, saving shows the date error "
                        "and preserves the other entered values. |"
                    ),
                },
            ],
        }

    monkeypatch.setattr(
        resolver.authoring_planner,
        "revise_prd_from_comments",
        fake_review,
    )

    revised = resolver.submit_review_comments(
        tmp_path,
        "task-due-dates",
        "prd",
        [
            {
                "section_title": "Scope",
                "comment": "Mention that calendar export is out of scope for V1.",
            },
            {
                "section_title": "Requirements & Acceptance",
                "comment": "Mention that invalid dates preserve the other task changes.",
            },
        ],
        drafted.revision,
    )

    assert revised.status == "drafted"
    assert revised.revision == drafted.revision + 1
    assert "Reminders and calendar export" in revised.artifact_content
    assert "preserves the other entered values" in revised.artifact_content
    assert "Mention that" not in revised.artifact_content
    assert drafted.artifact_content in captured["current_content"]
    assert captured["comments"][0]["section_title"] == "Scope"
    reviewed = {
        section["title"]: section["state"]
        for section in revised.sections
        if section["title"] in {"Scope", "Requirements & Acceptance"}
    }
    assert reviewed == {
        "Requirements & Acceptance": "reviewed",
        "Scope": "reviewed",
    }


def test_failed_review_model_leaves_existing_prd_unchanged(tmp_path: Path, monkeypatch):
    drafted = _complete(tmp_path)
    state_path = tmp_path / ".speed/features/task-due-dates/authoring-prd.json"
    before_state = state_path.read_text()

    monkeypatch.setattr(
        resolver.authoring_planner,
        "revise_prd_from_comments",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("Model quota unavailable.")),
    )
    result = resolver.submit_review_comments(
        tmp_path,
        "task-due-dates",
        "prd",
        [{"section_title": "Scope", "comment": "Exclude calendar export."}],
        drafted.revision,
    )

    assert result.status == "error"
    assert result.message == "Model quota unavailable."
    assert result.artifact_content == drafted.artifact_content
    assert state_path.read_text() == before_state


def test_stale_revision_is_reported_without_changing_state(tmp_path: Path):
    started = resolver.start(tmp_path, "task-due-dates", "prd", None, DESCRIPTION)

    conflicted = resolver.submit_answer(
        tmp_path, "task-due-dates", "prd", "A stale answer.", started.revision - 1
    )

    assert conflicted.status == "revision_conflict"
    fresh = resolver.get_session(tmp_path, "task-due-dates", "prd")
    assert fresh.revision == started.revision


def test_defer_keeps_the_interview_resumable_without_a_partial_draft(tmp_path: Path):
    started = resolver.start(tmp_path, "task-due-dates", "prd", None, DESCRIPTION)

    deferred = resolver.select_action(
        tmp_path, "task-due-dates", "prd", AuthoringAction.DEFER, started.revision
    )

    assert deferred.status in {"question", "blocked"}
    assert deferred.draft_available is False


def test_multiplayer_layout_is_supported_end_to_end(tmp_path: Path):
    (tmp_path / ".speed" / "shared").mkdir(parents=True)

    started = resolver.start(
        tmp_path, "task-due-dates", "prd", "Due dates for tasks", DESCRIPTION
    )

    assert started.status == "question"
    assert started.artifact_content is None
    assert (
        tmp_path / ".speed/shared/features/task-due-dates/authoring-prd.json"
    ).is_file()

    resumed = resolver.get_session(tmp_path, "task-due-dates", "prd")
    assert resumed.revision == started.revision


def test_helper_failure_surfaces_the_resolved_paths(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DRAFT_HELPER", str(tmp_path / "absent.py"))

    session = resolver.get_session(tmp_path, "task-due-dates", "prd")

    assert session.status == "helper_unavailable"
    assert session.helper_path.endswith("absent.py")
    assert session.interpreter


def test_sessions_are_empty_for_a_project_with_no_interview(tmp_path: Path):
    listing = resolver.list_sessions(tmp_path, "prd")

    assert listing.status == "listed"
    assert listing.sessions == []
    assert not (tmp_path / ".speed").exists()


def test_sessions_project_every_interview_for_resuming(tmp_path: Path):
    resolver.start(tmp_path, "task-due-dates", "prd", "Due dates", DESCRIPTION)
    resolver.start(tmp_path, "reopen-task", "prd", "Reopen a task", DESCRIPTION)

    listing = resolver.list_sessions(tmp_path, "prd")
    by_name = {entry.feature_name: entry for entry in listing.sessions}

    assert [entry.feature_name for entry in listing.sessions] == [
        "reopen-task",
        "task-due-dates",
    ]
    entry = by_name["task-due-dates"]
    assert entry.feature_title == "Due dates"
    assert entry.artifact_type == "prd"
    assert entry.status == "question"
    assert entry.revision == 0
    assert entry.progress.total > 0
    assert entry.draft_available is False
    assert entry.artifact_path is None
    assert entry.updated_at


def test_sessions_agree_with_the_session_query(tmp_path: Path):
    resolver.start(tmp_path, "task-due-dates", "prd", None, DESCRIPTION)

    entry = resolver.list_sessions(tmp_path, "prd").sessions[0]
    session = resolver.get_session(tmp_path, "task-due-dates", "prd")

    assert entry.status == session.status
    assert entry.revision == session.revision
    assert entry.progress.confirmed == session.progress.confirmed
    assert entry.progress.total == session.progress.total


@pytest.mark.parametrize("status", ["drafted", "published"])
def test_prepare_commit_creates_missing_ceremony_state(
    tmp_path: Path, monkeypatch, status: str
):
    from dashboard.backend.resolvers import context as context_resolver
    from dashboard.backend.paths import get_paths

    session = SimpleNamespace(
        status=status,
        feature_title="Due dates for tasks",
        self_review={"status": "passed"},
        review_comments=[],
    )
    monkeypatch.setattr(resolver, "get_session", lambda *_args: session)
    paths = get_paths(tmp_path)
    paths.ceremony_intent("task-due-dates").parent.mkdir(parents=True, exist_ok=True)
    paths.ceremony_intent("task-due-dates").write_text(
        '{"text":"Managers need visible due dates."}', encoding="utf-8"
    )

    prepared = resolver.prepare_commit(tmp_path, "task-due-dates", "prd")

    assert prepared is session
    assert paths.ceremony_state("task-due-dates").is_file()
    assert context_resolver.get_ceremony_info(tmp_path, "task-due-dates") is not None


def test_prepare_commit_rejects_an_unfinished_interview(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        resolver,
        "get_session",
        lambda *_args: SimpleNamespace(status="question", feature_title="Due dates"),
    )

    with pytest.raises(ValueError, match="Resolve every blocking self-review finding"):
        resolver.prepare_commit(tmp_path, "task-due-dates", "prd")


def test_publish_preserves_an_immutable_version_then_allows_a_new_draft(tmp_path: Path):
    drafted = _complete(tmp_path)
    published = resolver.publish(
        tmp_path, "task-due-dates", "prd", drafted.revision
    )

    assert published.status == "published"
    assert published.published_revision == published.revision
    published_version = next(
        item for item in published.versions if item["revision"] == published.revision
    )
    assert published_version["status"] == "published"
    assert published_version["content"] == published.artifact_content
    draft_record = json.loads(
        (tmp_path / ".speed/features/task-due-dates/draft-prd.json").read_text()
    )
    assert draft_record["status"] == "published"
    assert draft_record["authoring"]["published_revision"] == published.revision
    package_index = (tmp_path / "specs/task-due-dates/index.md").read_text()
    assert "| [PRD](prd.md) | Published |" in package_index

    republished = resolver.publish(
        tmp_path, "task-due-dates", "prd", published.revision
    )
    assert republished.revision == published.revision
    assert republished.versions == published.versions

    state_path = tmp_path / ".speed/features/task-due-dates/authoring-prd.json"
    state_before_open = state_path.read_text()
    artifact_before_open = (
        tmp_path / "specs/task-due-dates/prd.md"
    ).read_text()
    opened = resolver.replan(
        tmp_path, "task-due-dates", "prd", published.revision
    )
    assert opened.status == "published"
    assert opened.revision == published.revision
    assert state_path.read_text() == state_before_open
    assert (tmp_path / "specs/task-due-dates/prd.md").read_text() == artifact_before_open

    changed = published.artifact_content[published.artifact_content.index("## "):].replace(
        "Team leads", "Delivery leads", 1
    )
    revised = resolver.revise_document(
        tmp_path, "task-due-dates", "prd", changed, published.revision
    )

    assert revised.status in {"drafted", "drafted_with_open_questions"}
    assert revised.revision > published.revision
    assert revised.published_revision == published.revision
    retained = next(
        item for item in revised.versions if item["revision"] == published.revision
    )
    assert retained["status"] == "published"
    assert retained["content"] == published.artifact_content
