"""Adapter tests: reaching the shared interview helper from the dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.backend import authoring_helper

DESCRIPTION = (
    "Team leads cannot see which tasks are overdue; due dates live in ticket "
    "titles today, so nothing can be sorted or alerted on."
)


def test_helper_path_points_at_the_packaged_implementation():
    helper = authoring_helper.helper_path()
    assert helper.is_file()
    assert helper.name == "draft.py"
    assert helper.parent.parent.name == "workbench-draft"


def test_peek_of_unknown_feature_creates_nothing(tmp_path: Path):
    payload = authoring_helper.run(tmp_path, "prd", "task-due-dates", "--peek")

    assert payload["status"] == "not_started"
    assert not (tmp_path / ".speed").exists()
    assert not (tmp_path / "specs").exists()


def test_start_then_peek_returns_the_same_revision(tmp_path: Path):
    started = authoring_helper.run(
        tmp_path,
        "prd",
        "task-due-dates",
        "--feature-title",
        "Due dates for tasks",
        "--feature-description",
        DESCRIPTION,
    )
    assert started["status"] == "question"

    peeked = authoring_helper.run(tmp_path, "prd", "task-due-dates", "--peek")

    assert peeked["revision"] == started["revision"]
    assert peeked["current_question"]["id"] == started["current_question"]["id"]
    assert peeked["feature_title"] == "Due dates for tasks"
    assert peeked["implementation"] == started["implementation"]


def test_revision_conflict_is_a_payload_not_an_exception(tmp_path: Path):
    authoring_helper.run(
        tmp_path, "prd", "task-due-dates", "--feature-description", DESCRIPTION
    )

    payload = authoring_helper.run(
        tmp_path,
        "prd",
        "task-due-dates",
        "--answer",
        "A stale client answer.",
        "--expected-revision",
        "-1",
    )

    assert payload["status"] == "revision_conflict"
    assert "revision" in payload["message"].lower()


def test_missing_helper_reports_the_resolved_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DRAFT_HELPER", str(tmp_path / "absent.py"))

    payload = authoring_helper.run(tmp_path, "prd", "task-due-dates", "--peek")

    assert payload["status"] == "helper_unavailable"
    assert "absent.py" in payload["helper_path"]
    assert payload["interpreter"]


def test_non_json_output_is_reported_not_guessed(tmp_path: Path, monkeypatch):
    fake = tmp_path / "fake_helper.py"
    fake.write_text("print('not json at all')\n", encoding="utf-8")
    monkeypatch.setenv("WORKBENCH_DRAFT_HELPER", str(fake))

    payload = authoring_helper.run(tmp_path, "prd", "task-due-dates", "--peek")

    assert payload["status"] == "helper_unavailable"
    assert "not valid JSON" in payload["message"]


def test_multiplayer_layout_is_detected(tmp_path: Path):
    assert authoring_helper.is_multiplayer(tmp_path) is False
    (tmp_path / ".speed" / "shared").mkdir(parents=True)
    assert authoring_helper.is_multiplayer(tmp_path) is True


def test_dashboard_url_is_passed_through_to_the_helper(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DASHBOARD_URL", "http://localhost:4310")

    payload = authoring_helper.run(
        tmp_path, "prd", "task-due-dates", "--feature-description", DESCRIPTION
    )

    assert payload["dashboard_url"] == "http://localhost:4310/define/task-due-dates"
    assert payload["authoring_url"].endswith("/define/task-due-dates/authoring/prd")


def test_sections_and_draft_record_carry_provenance(tmp_path: Path):
    payload = authoring_helper.run(
        tmp_path, "prd", "task-due-dates", "--feature-description", DESCRIPTION
    )

    titles = [section["title"] for section in payload["sections"]]
    assert "Problem & Evidence" in titles

    record = json.loads(
        (tmp_path / ".speed/features/task-due-dates/draft-prd.json").read_text()
    )
    assert record["authoring"]["sections"]
    assert record["authoring"]["revision"] == payload["revision"]


@pytest.mark.parametrize("flag", ["--accept-suggestion", "--defer"])
def test_action_flags_return_a_payload(tmp_path: Path, flag: str):
    started = authoring_helper.run(
        tmp_path, "prd", "task-due-dates", "--feature-description", DESCRIPTION
    )

    payload = authoring_helper.run(
        tmp_path,
        "prd",
        "task-due-dates",
        flag,
        "--expected-revision",
        str(started["revision"]),
    )

    assert payload["status"] in {
        "question", "blocked", "drafted", "drafted_with_open_questions", "error"
    }
