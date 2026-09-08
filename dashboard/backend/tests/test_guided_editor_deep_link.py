from __future__ import annotations

import json
from pathlib import Path

from dashboard.backend import db
from dashboard.backend.resolvers.define import _build_specified, _match_specs_to_feature
from dashboard.backend.resolvers.spec_editor import get_spec, update_spec_content
from dashboard.backend.spec_registry import match_spec_to_feature


GUIDED_PRD = """\
# PRD: Due dates for tasks

<!-- Interview: prd-v4; revision: 3 -->

## Summary
Make time-sensitive work visible.

## Problem & Evidence
Tasks have no due date.

## Hypothesis
Due dates reduce missed work.

## User Stories
| ID | Story | Priority |
|---|---|---|
| US-1 | As a task user, I want due dates. | Must |

## Requirements & Acceptance
| ID | Story | Product behavior | Done when |
|---|---|---|---|
| REQ-1 | US-1 | Save a due date. | The date is displayed. |

## Scope
| Included | Not included |
|---|---|
| Date entry | Reminders |

## Guardrails / Must Not Regress
| ID | What must remain true | How it will be verified |
|---|---|---|
| GR-1 | Undated tasks work. | Regression check |

## Success
| ID | Outcome or signal | Target | Window | Owner |
|---|---|---|---|---|
| SM-1 | Fewer missed tasks | Provisional | Post-launch | Unassigned |
"""


def _guided_project(tmp_path: Path) -> tuple[Path, Path]:
    feature = "due-dates-for-tasks"
    (tmp_path / ".speed" / "features" / feature).mkdir(parents=True)
    prd = tmp_path / "specs" / feature / "prd.md"
    prd.parent.mkdir(parents=True)
    prd.write_text(GUIDED_PRD)
    return tmp_path, prd


def test_define_recognizes_guided_prd_layout(tmp_path: Path) -> None:
    project, prd = _guided_project(tmp_path)

    primary, additional = _match_specs_to_feature(project, "due-dates-for-tasks")
    specified = _build_specified(project, "due-dates-for-tasks")

    assert primary["product"] == prd
    assert additional == []
    assert specified.product_spec.exists is True
    assert specified.product_spec.audit_status == "clean"


def test_registry_groups_guided_prd_by_parent_feature(tmp_path: Path) -> None:
    project, prd = _guided_project(tmp_path)

    assert match_spec_to_feature(prd, project) == "due-dates-for-tasks"


def test_editor_indexes_generated_prd_on_deep_link(tmp_path: Path) -> None:
    project, _prd = _guided_project(tmp_path)
    conn = db.connect(str(project))
    db.migrate(conn)
    try:
        spec = get_spec(conn, project, "specs/due-dates-for-tasks/prd.md")
    finally:
        conn.close()

    assert spec is not None
    assert spec.path == "specs/due-dates-for-tasks/prd.md"
    assert spec.feature == "due-dates-for-tasks"
    assert "# PRD: Due dates for tasks" in spec.content


def test_generic_editor_refuses_to_overwrite_a_guided_artifact(tmp_path: Path) -> None:
    project, prd = _guided_project(tmp_path)
    record = project / ".speed/features/due-dates-for-tasks/draft-prd.json"
    record.write_text(json.dumps({"authoring": {"revision": 3}}), encoding="utf-8")
    conn = db.connect(str(project))
    db.migrate(conn)
    before = prd.read_text(encoding="utf-8")
    try:
        result = update_spec_content(
            conn,
            project,
            "specs/due-dates-for-tasks/prd.md",
            "# Overwritten outside guided authoring\n",
        )
    finally:
        conn.close()

    assert result.success is False
    assert "/define/due-dates-for-tasks/authoring/prd" in (result.error or "")
    assert prd.read_text(encoding="utf-8") == before
