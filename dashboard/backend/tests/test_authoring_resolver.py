"""Resolver tests: projecting the helper result onto the GraphQL surface."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("strawberry")

from dashboard.backend.resolvers import authoring as resolver
from dashboard.backend.resolvers.authoring_types import AuthoringAction

DESCRIPTION = (
    "Team leads cannot see which tasks are overdue; due dates live in ticket "
    "titles today, so nothing can be sorted or alerted on."
)


def test_intake_returns_the_prd_form_with_a_title_field(tmp_path: Path):
    intake = resolver.get_intake(tmp_path, "prd")

    assert intake.status == "needs_input"
    assert intake.next_input["id"] == "new_prd_basics"
    field_ids = [field["id"] for field in intake.next_input["fields"]]
    assert field_ids == ["feature_title", "feature_slug", "feature_description"]


def test_session_of_unknown_feature_is_not_started_and_writes_nothing(tmp_path: Path):
    session = resolver.get_session(tmp_path, "task-due-dates", "prd")

    assert session.status == "not_started"
    assert session.revision is None
    assert session.artifact_content is None
    assert not (tmp_path / ".speed").exists()


def test_start_returns_a_question_and_a_readable_provisional_draft(tmp_path: Path):
    session = resolver.start(
        tmp_path, "task-due-dates", "prd", "Due dates for tasks", DESCRIPTION
    )

    assert session.status == "question"
    assert session.feature_title == "Due dates for tasks"
    assert session.draft_available is True
    assert session.artifact_path == "specs/task-due-dates/prd.md"
    assert session.artifact_content.startswith("# PRD: Due dates for tasks")
    assert session.current_question["response_control"]["id"]
    assert session.sections
    assert session.authoring_url.endswith("/define/task-due-dates/authoring/prd")


def test_answer_advances_the_revision_and_regenerates(tmp_path: Path):
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
    assert answered.artifact_content != started.artifact_content


def test_stale_revision_is_reported_without_changing_state(tmp_path: Path):
    started = resolver.start(tmp_path, "task-due-dates", "prd", None, DESCRIPTION)

    conflicted = resolver.submit_answer(
        tmp_path, "task-due-dates", "prd", "A stale answer.", started.revision - 1
    )

    assert conflicted.status == "revision_conflict"
    fresh = resolver.get_session(tmp_path, "task-due-dates", "prd")
    assert fresh.revision == started.revision


def test_defer_keeps_the_provisional_draft_available(tmp_path: Path):
    started = resolver.start(tmp_path, "task-due-dates", "prd", None, DESCRIPTION)

    deferred = resolver.select_action(
        tmp_path, "task-due-dates", "prd", AuthoringAction.DEFER, started.revision
    )

    assert deferred.status in {"question", "blocked"}
    assert deferred.draft_available is True


def test_multiplayer_layout_is_supported_end_to_end(tmp_path: Path):
    (tmp_path / ".speed" / "shared").mkdir(parents=True)

    started = resolver.start(
        tmp_path, "task-due-dates", "prd", "Due dates for tasks", DESCRIPTION
    )

    assert started.status == "question"
    assert started.artifact_content.startswith("# PRD: Due dates for tasks")
    assert (
        tmp_path / ".speed/shared/features/task-due-dates/draft-prd.json"
    ).is_file()

    resumed = resolver.get_session(tmp_path, "task-due-dates", "prd")
    assert resumed.revision == started.revision


def test_helper_failure_surfaces_the_resolved_paths(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DRAFT_HELPER", str(tmp_path / "absent.py"))

    session = resolver.get_session(tmp_path, "task-due-dates", "prd")

    assert session.status == "helper_unavailable"
    assert session.helper_path.endswith("absent.py")
    assert session.interpreter
