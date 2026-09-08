"""A guided draft cannot be edited as a document."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("strawberry")

from dashboard.backend import authoring_helper
from dashboard.backend.resolvers import ceremony_editor

DESCRIPTION = (
    "Team leads cannot see which tasks are overdue; due dates live in ticket "
    "titles today, so nothing can be sorted or alerted on."
)

ANSWERS = {
    "P-Q1": "Team leads cannot see due work until they open each task, which delays planning.",
    "P-Q2": "Team leads use the feature; existing undated tasks and clients remain unchanged.",
    "P-Q3": "Due work becomes visible without regressing task completion behavior.",
    "P-Q4": "Users set an optional date and see overdue, today, and tomorrow states in the list.",
    "P-Q5": "API responses and the rendered task list prove persistence, ordering, and badges.",
    "P-Q6": "Product reviews due-date adoption during the first month after launch.",
    "P-Q7": "Include dates and list states; exclude reminders and recurrence from V1.",
    "P-Q8": "The field is additive, existing dates default to null, and no migration is required.",
}


def _complete(tmp_path: Path) -> None:
    payload = authoring_helper.run(
        tmp_path, "prd", "task-due-dates", "--feature-description", DESCRIPTION
    )
    for _ in range(12):
        if payload["status"] in {"drafted", "drafted_with_open_questions"}:
            return
        payload = authoring_helper.run(
            tmp_path,
            "prd",
            "task-due-dates",
            "--answer",
            ANSWERS[payload["current_question"]["id"]],
            "--expected-revision",
            str(payload["revision"]),
        )
    raise AssertionError("PRD interview did not complete")


def test_update_draft_refuses_a_guided_prd(tmp_path: Path):
    _complete(tmp_path)
    artifact = tmp_path / "specs/task-due-dates/prd.md"
    before = artifact.read_text(encoding="utf-8")

    with pytest.raises(PermissionError) as excinfo:
        ceremony_editor.update_draft(
            tmp_path, "task-due-dates", "prd", "# Hand-edited PRD\n"
        )

    assert "authoring/prd" in str(excinfo.value)
    assert artifact.read_text(encoding="utf-8") == before


def test_update_draft_still_accepts_a_non_guided_draft(tmp_path: Path):
    feature_dir = tmp_path / ".speed/features/legacy-feature"
    feature_dir.mkdir(parents=True)
    (feature_dir / "draft-prd.json").write_text(
        json.dumps(
            {
                "feature_name": "legacy-feature",
                "spec_type": "prd",
                "content": "# PRD: Legacy\n",
                "file_path": "specs/legacy-feature/prd.md",
                "template_name": "prd.md",
                "generated_at": "2026-01-01T00:00:00+00:00",
                "child_specs": [],
            }
        ),
        encoding="utf-8",
    )

    guided = ceremony_editor._guided_authoring_record(
        tmp_path, "legacy-feature", "prd"
    )

    assert guided is None
