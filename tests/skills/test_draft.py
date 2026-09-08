import hashlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "skills" / "workbench-draft" / "scripts" / "draft.py"
ANSWERS = [
    "Team leads cannot see due work until they open each task, which delays planning.",
    "Team leads manage tasks; contributors can view and update tasks they own.",
    "Overdue work becomes visible while task completion and accessibility do not regress.",
    "A lead opens the board, sees due dates, filters overdue tasks, and "
    "recovers from invalid dates.",
    "REQ-1 shows a due date. Given an invalid date, when saved, then an inline error appears.",
    "Ninety percent of leads identify overdue tasks within 30 seconds; Product Analytics owns it.",
    "Board display and editing are in scope; reminders are out of scope until notifications ship.",
    "Editors may change dates; viewers cannot. Audit changes and decide "
    "timezone handling before approval.",
]
DESIGN_ANSWERS = [
    "Keep the board dense, calm, and task-first; due status must be prominent without decorative cards or gradients.",
    "The journey starts at /tasks, continues through the task detail drawer, and returns to the filtered board after save or cancel.",
    "Use the existing board shell with a persistent toolbar, scrollable task region, and detail drawer that becomes full-screen on narrow viewports.",
    "Reuse TaskCard and DateField, modify TaskDrawer, and add DueStatusBadge with explicit value, state, permission, and event inputs.",
    "Cover populated, no due date, overdue, loading, invalid date, permission denied, save failure, offline, disabled, and long-title overflow states.",
    "Validate inline, preserve focus on errors, announce save results, support keyboard dismissal, respect reduced motion, and use direct recovery copy.",
    "Use only resolved board spacing, type, status, surface, border, elevation, and icon tokens; flag DueStatusBadge treatment as new if no semantic token exists.",
    "Support mobile through desktop, text expansion, localization, reduced motion, keyboard and screen-reader operation, and WCAG 2.2 AA verification.",
]
RFC_ANSWERS = [
    "POST /tasks accepts an optional ISO 8601 due_date and returns the stored task with due_status; invalid input returns HTTP 422 with a field error.",
    "Add nullable due_at and due_timezone fields, with states unset, scheduled, due-soon, overdue, completed, and invalid during client entry.",
    "The API preserves omitted values on update, validates parseability and timezone, and returns stable field-level error codes without discarding other edits.",
    "Add unit tests for validation and ordering, contract tests for create and update, integration tests for migration, and browser tests for errors and recovery.",
    "Editors can write due dates and viewers can only read them; audit mutations, escape rendered values, apply existing authorization, and redact no additional data.",
    "Store UTC plus the originating timezone and derive display status at read time; this avoids stale status writes at the cost of read-time computation.",
    "Use a nullable additive migration with a backfill-free deploy, then update task model, API schema, service, repository, UI adapter, and tests before enabling the flag.",
    "The task service and existing database are dependencies; timezone ownership remains an explicit open decision before rollout approval.",
]
ANSWER_BY_ID = {f"P-Q{index}": answer for index, answer in enumerate(ANSWERS, start=1)}


def test_model_title_canonicalizes_only_a_provisional_feature_package(tmp_path):
    helper = runpy.run_path(str(HELPER))
    provisional = "draft-a1b2c3d4"
    source_dir = tmp_path / ".speed" / "features" / provisional
    source_dir.mkdir(parents=True)
    (source_dir / "authoring-prd.json").write_text("{}", encoding="utf-8")
    state = {
        "feature_name": provisional,
        "artifact_type": "prd",
        "artifact": None,
        "artifact_versions": [],
        "intake": {
            "feature_title": "Optional Task Due Dates",
            "feature_description": "Let task owners set optional due dates.",
        },
        "planning": {
            "sources": [f".speed/features/{provisional}/authoring-prd.json"],
        },
    }

    feature, feature_dir, state_path = helper["_canonicalize_provisional_feature"](
        tmp_path, provisional, "prd", state
    )

    assert feature == "optional-task-due-dates"
    assert feature_dir == tmp_path / ".speed/features/optional-task-due-dates"
    assert state_path == feature_dir / "authoring-prd.json"
    assert feature_dir.is_dir()
    assert not source_dir.exists()
    assert state["feature_name"] == feature
    assert state["identity"]["provisional_feature_name"] == provisional
    assert state["planning"]["sources"] == [
        ".speed/features/optional-task-due-dates/authoring-prd.json"
    ]


def test_confirmed_human_answer_replaces_model_coverage_guess():
    helper = runpy.run_path(str(HELPER))
    state = {
        "planning": {
            "mode": "model",
            "coverage": {
                "P-Q7": {
                    "confidence_label": "inferred",
                    "resolved_value": "V1 is CSV-only; PDF export is excluded.",
                }
            },
        },
        "answers": {
            "P-Q7": {
                "state": "confirmed",
                "coverage_id": "P-Q7",
                "answer": "V1 includes PDF export and scheduled monthly delivery.",
            }
        },
    }

    confirmed = helper["_confirmed_answers"](state)

    assert confirmed["P-Q7"] == (
        "V1 includes PDF export and scheduled monthly delivery."
    )


def test_model_plan_removes_unanswered_placeholder_from_progress():
    helper = runpy.run_path(str(HELPER))
    bank = helper["_load_question_bank"]("prd")
    coverage = {
        question["id"]: {
            "coverage": question["coverage"],
            "confidence": 0.4,
            "confidence_label": "unresolved",
            "impact": "high",
            "basis": ["Model planning"],
            "rationale": "This decision still needs explicit author confirmation.",
            "resolved_value": None,
            "question_value": 0.6,
        }
        for question in bank["questions"]
    }
    state = {
        "artifact_type": "prd",
        "revision": 0,
        "intake": {},
        "answers": {},
        "suggestions": {"P-Q2": {"answer": "Temporary placeholder"}},
        "clarifications_asked": ["P-Q2"],
        "clarification_plan": ["P-Q2"],
    }
    planned_question = {
        "id": "P-Q4-1",
        "coverage_id": "P-Q4",
        "prompt": "Where should tasks without a due date appear in the sorted list?",
        "evidence": "Current task-list behavior",
        "purpose": "Define deterministic ordering behavior.",
        "completion_evidence": "The undated-task position is explicit.",
        "response_control": {
            "id": "answer",
            "input_type": "single_select",
            "prompt": "Choose the intended ordering.",
            "options": [
                {"value": "last", "label": "After dated tasks"},
                {"value": "first", "label": "Before dated tasks"},
            ],
        },
    }
    plan = {
        "mode": "model",
        "model": "sonnet",
        "feature_title": "Task Due Dates",
        "analysis_summary": "The brief needs one explicit product behavior decision.",
        "prd_size": "Small",
        "coverage": coverage,
        "questions": [planned_question],
    }

    helper["_apply_planning_plan"](state, bank, json.dumps(plan), 0)

    assert state["clarification_plan"] == ["P-Q4-1"]
    assert state["clarifications_asked"] == []
    assert state["suggestions"] == {}


def test_answer_rejects_a_stale_question_identity(tmp_path):
    started, payload = _run(
        tmp_path,
        "--feature-description",
        "Team leads cannot see task due dates on the board, so overdue work is "
        "missed; the feature should make due status visible during planning.",
    )
    assert started.returncode == 0, started.stderr
    before = (
        tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json"
    ).read_text()

    stale, stale_payload = _run(
        tmp_path,
        "--answer",
        "This answer belongs to a question shown by a stale tab.",
        "--question-id",
        "P-Q999",
        "--expected-revision",
        str(payload["revision"]),
    )

    assert stale.returncode == 2
    assert stale_payload["status"] == "revision_conflict"
    assert (
        tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json"
    ).read_text() == before


def test_regeneration_preserves_an_out_of_band_edit_as_a_recovery_version(tmp_path):
    payload = _complete_prd(tmp_path)
    artifact = tmp_path / payload["artifact_path"]
    recovery_marker = "\n\n<!-- direct edit that must remain recoverable -->\n"
    artifact.write_text(artifact.read_text() + recovery_marker)

    answered, payload = _run(
        tmp_path,
        "--update-coverage",
        "P-Q1",
        "--answer",
        ANSWER_BY_ID["P-Q1"] + " Recovery behavior remains unchanged.",
        "--expected-revision",
        str(payload["revision"]),
    )

    assert answered.returncode == 0, answered.stderr
    recovered = [
        item for item in payload["versions"]
        if item.get("source") == "external_edit_recovery"
    ]
    assert recovered
    assert recovery_marker.strip() in recovered[-1]["content"]


def _run(project: Path, *args: str):
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "add-due-date-to-task",
            "--project-root",
            str(project),
            "--json",
            *args,
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    return result, payload


def _run_design(project: Path, *args: str):
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "design",
            "add-due-date-to-task",
            "--project-root",
            str(project),
            "--json",
            *args,
        ],
        capture_output=True,
        text=True,
    )
    return result, json.loads(result.stdout)


def _run_rfc(project: Path, *args: str):
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "rfc",
            "add-due-date-to-task",
            "--project-root",
            str(project),
            "--json",
            *args,
        ],
        capture_output=True,
        text=True,
    )
    return result, json.loads(result.stdout)


DESCRIPTION = (
    "Team leads cannot see which tasks are overdue; due dates live in ticket "
    "titles today, so nothing can be sorted or alerted on."
)


def _start_prd(
    project: Path,
    feature: str,
    *,
    description: str,
    title: str | None = None,
):
    args = [
        sys.executable,
        str(HELPER),
        "prd",
        feature,
        "--project-root",
        str(project),
        "--feature-description",
        description,
        "--json",
    ]
    if title:
        args.extend(["--feature-title", title])
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def _complete_named_prd(project: Path, feature: str, *, description: str, title: str | None = None):
    payload = _start_prd(project, feature, description=description, title=title)
    for _ in range(10):
        if payload["status"] in {"drafted", "drafted_with_open_questions"}:
            return payload
        question_id = payload["current_question"]["id"]
        result = subprocess.run(
            [
                sys.executable, str(HELPER), "prd", feature,
                "--project-root", str(project),
                "--answer", ANSWER_BY_ID[question_id],
                "--expected-revision", str(payload["revision"]), "--json",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout)
    raise AssertionError("Named PRD interview did not complete")


def _peek(project: Path, feature: str, artifact_type: str = "prd"):
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            artifact_type,
            feature,
            "--project-root",
            str(project),
            "--peek",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def _list(project: Path, *args: str):
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            *args,
            "--list",
            "--project-root",
            str(project),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def _run_intake(project: Path, *args: str):
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            *args,
            "--project-root",
            str(project),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    return result, json.loads(result.stdout)


def _complete_prd(project: Path):
    result, payload = _run(project)
    assert result.returncode == 0, result.stderr
    for _ in range(10):
        if payload["status"] in {"drafted", "drafted_with_open_questions"}:
            return payload
        question_id = payload["current_question"]["id"]
        result, payload = _run(
            project,
            "--answer",
            ANSWER_BY_ID[question_id],
            "--expected-revision",
            str(payload["revision"]),
        )
        assert result.returncode == 0, result.stderr
    raise AssertionError("PRD clarification workflow did not complete")


def _publish_prd(project: Path):
    payload = _complete_prd(project)
    result, payload = _run(
        project,
        "--publish",
        "--expected-revision",
        str(payload["revision"]),
    )
    assert result.returncode == 0, result.stderr
    return payload


def _complete_design(project: Path, *, publish: bool = False):
    result, payload = _run_design(project)
    assert result.returncode == 0, result.stderr
    for answer in DESIGN_ANSWERS:
        if payload["status"] in {"drafted", "drafted_with_open_questions"}:
            break
        result, payload = _run_design(
            project,
            "--answer",
            answer,
            "--expected-revision",
            str(payload["revision"]),
        )
        assert result.returncode == 0, result.stderr
    assert payload["status"] == "drafted"
    if publish:
        result, payload = _run_design(
            project,
            "--publish",
            "--expected-revision",
            str(payload["revision"]),
        )
        assert result.returncode == 0, result.stderr
    return payload


def _reach_self_review_repair(project: Path):
    first, payload = _run(
        project,
        "--answer",
        "Leads struggle.",
        "--expected-revision",
        "0",
    )
    assert first.returncode == 0, first.stderr
    assert payload["current_question"]["follow_up"]
    second, payload = _run(
        project,
        "--answer",
        "Board unclear.",
        "--expected-revision",
        "1",
    )
    assert second.returncode == 0, second.stderr
    for _ in range(10):
        if payload["self_review"]["pass_count"] == 1:
            return payload
        question_id = payload["current_question"]["id"]
        result, payload = _run(
            project,
            "--answer",
            ANSWER_BY_ID[question_id],
            "--expected-revision",
            str(payload["revision"]),
        )
        assert result.returncode == 0, result.stderr
    raise AssertionError("PRD did not reach self-review repair")


def test_missing_arguments_use_branch_aware_intake(tmp_path):
    missing, payload = _run_intake(tmp_path)
    assert missing.returncode == 0
    assert payload["status"] == "needs_input"
    assert payload["next_input"]["id"] == "artifact_type"
    assert [option["value"] for option in payload["next_input"]["options"]] == [
        "prd",
        "design",
        "rfc",
    ]

    cli = subprocess.run(
        [str(REPO / "workbench"), "draft", "prd", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert cli.returncode == 0, cli.stderr
    cli_payload = json.loads(cli.stdout)
    assert cli_payload["next_input"]["id"] == "new_prd_basics"


def test_prd_intake_asks_for_new_feature_without_existing_options(tmp_path):
    (tmp_path / ".speed/features/archive-a-task").mkdir(parents=True)
    (tmp_path / "specs/product").mkdir(parents=True)
    (tmp_path / "specs/product/reopen-task.md").write_text("# Existing PRD\n")

    result, payload = _run_intake(tmp_path, "prd")

    assert result.returncode == 0
    assert payload["status"] == "needs_input"
    next_input = payload["next_input"]
    assert next_input["id"] == "new_prd_basics"
    assert next_input["input_type"] == "conversation"
    assert [field["id"] for field in next_input["fields"]] == [
        "feature_description",
    ]
    assert "max_length" not in next_input["fields"][0]
    assert all(field["required"] for field in next_input["fields"])
    assert next_input["allow_existing"] is False
    assert "archive-a-task" not in result.stdout
    assert "reopen-task" not in result.stdout


def test_compact_net_worth_plan_derives_identity_and_returns_only_authoring_url(tmp_path):
    description = "I want a dashboard that shows an individual's net worth."
    plan = {
        "feature_title": "Net Worth Dashboard",
        "analysis_summary": (
            "The description resolves the purpose; the data entry journey needs confirmation."
        ),
        "prd_size": "Small",
        "resolved_coverage": [
            {
                "coverage_id": "P-Q1",
                "resolved_value": (
                    "Individuals currently lack one place to see assets, liabilities, "
                    "and their current net worth."
                ),
                "confidence": 0.95,
            },
            {
                "coverage_id": "P-Q2",
                "resolved_value": (
                    "An individual manages only their own financial data; existing "
                    "stored records remain unchanged."
                ),
                "confidence": 0.9,
            },
            {
                "coverage_id": "P-Q3",
                "resolved_value": (
                    "Showing assets minus liabilities helps an individual understand "
                    "their current financial position."
                ),
                "confidence": 0.9,
            },
            {
                "coverage_id": "P-Q5",
                "resolved_value": (
                    "Given recorded assets and liabilities, the dashboard displays each "
                    "category and the correct net total after reload."
                ),
                "confidence": 0.9,
            },
            {
                "coverage_id": "P-Q6",
                "resolved_value": (
                    "Success is that individuals can identify their net worth and its "
                    "breakdown; Product owns a provisional post-launch baseline."
                ),
                "confidence": 0.8,
            },
            {
                "coverage_id": "P-Q7",
                "resolved_value": (
                    "V1 includes manual asset and liability entries, category totals, "
                    "and net worth. Bank connections, sharing, and advice are excluded."
                ),
                "confidence": 0.9,
            },
            {
                "coverage_id": "P-Q8",
                "resolved_value": (
                    "Financial values remain private to the individual. Product owns "
                    "release readiness and validation of calculation accuracy."
                ),
                "confidence": 0.85,
            },
        ],
        "questions": [
            {
                "coverage_id": "P-Q4",
                "prompt": "How should an individual add or update assets and liabilities?",
                "response_type": "textarea",
                "options": [],
                "suggested_answer": None,
                "suggestion_confidence": "missing",
                "suggestion_gap": "The input and update journey is not specified.",
            }
        ],
    }
    plan_path = tmp_path / "net-worth-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    started = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "--project-root",
            str(tmp_path),
            "--feature-description",
            description,
            "--compact-plan-file",
            str(plan_path),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert started.returncode == 0, started.stderr or started.stdout
    payload = json.loads(started.stdout)
    assert payload["feature_name"] == "net-worth-dashboard"
    assert payload["feature_title"] == "Net Worth Dashboard"
    assert payload["current_question"]["id"] == "P-Q4"
    assert payload["artifact_path"] is None
    assert payload["implementation"]["planner_contract_hash"].startswith("sha256:")
    assert payload["implementation"]["planner_prompt_hash"].startswith("sha256:")

    completed = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "net-worth-dashboard",
            "--project-root",
            str(tmp_path),
            "--answer",
            (
                "The individual manually adds, edits, or removes named assets and "
                "liabilities; saved changes immediately recalculate totals and persist "
                "after reload."
            ),
            "--question-id",
            "P-Q4",
            "--expected-revision",
            str(payload["revision"]),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stdout.strip() == (
        "http://localhost:3000/define/net-worth-dashboard/authoring/prd"
    )
    assert (tmp_path / "specs/net-worth-dashboard/prd.md").is_file()


def test_prd_description_starts_interview_without_a_partial_draft(tmp_path):
    description = (
        "Team leads cannot see task due dates on the board, so overdue work is "
        "missed; the feature should make due status visible during planning."
    )

    started, payload = _run(
        tmp_path,
        "--feature-description",
        description,
    )

    assert started.returncode == 0, started.stderr
    assert payload["current_question"]["id"] == "P-Q2"
    assert payload["draft_available"] is False
    assert payload["artifact_path"] is None
    assert payload["coverage"]["P-Q1"]["confidence_label"] == "evidence_backed"
    assert payload["coverage"]["P-Q1"]["confidence"] == 0.95
    assert not (tmp_path / "specs/add-due-date-to-task/prd.md").exists()

    state_path = tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json"
    state = json.loads(state_path.read_text())
    assert state["intake"]["feature_description"] == description
    assert state["answers"] == {}

    repeated, repeated_payload = _run(
        tmp_path,
        "--feature-description",
        description,
    )
    assert repeated.returncode == 0, repeated.stderr
    assert repeated_payload["revision"] == 0

    before = state_path.read_bytes()
    duplicate, error = _run(
        tmp_path,
        "--feature-description",
        "A different description must not replace existing workflow state.",
    )
    assert duplicate.returncode == 1
    assert "cannot replace existing interview evidence" in error["message"]
    assert state_path.read_bytes() == before


def test_prd_description_accepts_more_than_500_characters(tmp_path):
    description = (
        "Team leads need due dates so time-sensitive work stays visible. "
        + "Include detailed validation, recovery, permissions, and accessibility behavior. " * 8
    )

    started, payload = _run(tmp_path, "--feature-description", description)

    assert len(description) > 500
    assert started.returncode == 0, started.stderr
    assert payload["status"] == "question"
    state = json.loads(
        (tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json").read_text()
    )
    assert state["intake"]["feature_description"] == description.strip()

def test_description_is_attached_to_an_existing_empty_checkpoint(tmp_path):
    started, payload = _run(tmp_path)
    assert started.returncode == 0, started.stderr
    assert payload["revision"] == 0
    assert payload["current_question"]["suggestion"]["confidence"] == "missing"

    description = (
        "Operations leads miss task deadlines because due status is absent from "
        "the board; make due work visible during daily planning."
    )
    attached, payload = _run(
        tmp_path,
        "--feature-description",
        description,
    )

    assert attached.returncode == 0, attached.stderr
    assert payload["revision"] == 1
    assert payload["current_question"]["id"] == "P-Q2"
    assert payload["current_question"]["suggestion"]["answer"] is None
    assert payload["draft_available"] is False
    state = json.loads(
        (tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json").read_text()
    )
    assert state["intake"]["feature_description"] == description
    assert state["decision_history"][-1]["action"] == "intake_description_added"


def test_question_returns_select_actions_and_resumes_a_persisted_edit(tmp_path):
    description = (
        "Team leads miss deadlines because task due dates are not visible during "
        "board planning; show due status where planning happens."
    )
    started, payload = _run(tmp_path, "--feature-description", description)
    assert started.returncode == 0, started.stderr
    control = payload["current_question"]["response_control"]
    assert control["input_type"] == "single_select"
    assert [option["value"] for option in control["options"]] == [
        "edit",
        "reject",
        "defer",
    ]
    assert payload["resume_step"] == {
        "question_id": "P-Q2",
        "control_id": "suggestion_action",
        "revision": 0,
    }
    suggested_answer = payload["current_question"]["suggestion"]["answer"]

    selected, payload = _run(
        tmp_path,
        "--edit-suggestion",
        "--expected-revision",
        "0",
    )
    assert selected.returncode == 0, selected.stderr
    assert payload["revision"] == 1
    edit_control = payload["current_question"]["response_control"]
    assert edit_control["input_type"] == "textarea"
    assert edit_control["initial_value"] == suggested_answer
    assert payload["resume_step"]["control_id"] == "edited_suggestion"

    resumed, resumed_payload = _run(tmp_path)
    assert resumed.returncode == 0, resumed.stderr
    assert resumed_payload["revision"] == 1
    assert resumed_payload["current_question"]["response_control"] == edit_control

    edited_answer = ANSWERS[1]
    answered, payload = _run(
        tmp_path,
        "--answer",
        edited_answer,
        "--expected-revision",
        "1",
    )
    assert answered.returncode == 0, answered.stderr
    assert payload["status"] == "question"
    assert payload["draft_available"] is False
    assert payload["current_question"]["id"] == "P-Q4"
    state = json.loads(
        (tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json").read_text()
    )
    assert state["edit_requests"]["P-Q2"]["status"] == "answered"
    assert state["edit_requests"]["P-Q2"]["answer"] == edited_answer
    assert state["answers"]["P-Q2"]["decision"] == "edited"


def test_unavailable_accept_action_is_omitted_from_response_options(tmp_path):
    started, payload = _run(tmp_path)

    assert started.returncode == 0, started.stderr
    suggestion = payload["current_question"]["suggestion"]
    assert suggestion["accept_ready"] is False
    control = payload["current_question"]["response_control"]
    assert control["input_type"] == "single_select"
    assert [option["value"] for option in control["options"]] == [
        "edit",
        "defer",
    ]
    assert control["options"][0]["label"] == "Answer question"


def test_incomplete_answer_gets_one_persisted_targeted_follow_up(tmp_path):
    first, payload = _run(
        tmp_path,
        "--answer",
        "Team leads struggle.",
        "--expected-revision",
        "0",
    )

    assert first.returncode == 0, first.stderr
    assert payload["revision"] == 1
    assert payload["current_question"]["id"] == "P-Q1"
    follow_up = payload["current_question"]["follow_up"]
    assert "affected user" in follow_up["prompt"]
    assert payload["progress"]["confirmed"] == 0

    continued, payload = _run(
        tmp_path,
        "--answer",
        "They cannot see due work during planning, so deadlines are missed.",
        "--expected-revision",
        "1",
    )
    assert continued.returncode == 0, continued.stderr
    assert payload["revision"] == 2
    assert payload["current_question"]["id"] == "P-Q2"
    state = json.loads(
        (tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json").read_text()
    )
    assert state["follow_ups"]["P-Q1"]["status"] == "answered"
    assert state["answers"]["P-Q1"]["quality_gaps"] == []
    assert sum(
        entry["action"] == "follow_up_requested"
        for entry in state["decision_history"]
    ) == 1


def test_self_review_reopens_source_question_and_passes_after_repair(tmp_path):
    payload = _reach_self_review_repair(tmp_path)

    assert payload["status"] == "question"
    assert payload["current_question"]["id"] == "P-Q1"
    assert payload["current_question"]["existing_answer"]
    assert payload["current_question"]["review_findings"][0]["kind"] == "answer_quality"
    assert payload["self_review"]["pass_count"] == 1
    assert payload["self_review"]["status"] == "needs_repair"

    repaired, payload = _run(
        tmp_path,
        "--answer",
        ANSWERS[0],
        "--expected-revision",
        str(payload["revision"]),
    )
    assert repaired.returncode == 0, repaired.stderr
    assert payload["status"] == "drafted"
    assert payload["self_review"]["pass_count"] == 2
    assert payload["self_review"]["status"] == "passed"
    assert payload["self_review"]["findings"] == []


def test_second_failed_self_review_keeps_the_misleading_draft_hidden(tmp_path):
    payload = _reach_self_review_repair(tmp_path)
    revision = payload["revision"]

    repaired, payload = _run(
        tmp_path,
        "--answer",
        "Still inadequate.",
        "--expected-revision",
        str(revision),
    )

    assert repaired.returncode == 0, repaired.stderr
    assert payload["status"] == "question"
    assert payload["draft_available"] is False
    assert payload["self_review"]["pass_count"] == 2
    assert payload["self_review"]["status"] == "needs_repair"
    assert payload["current_question"]["id"] == "P-Q1"
    assert payload["artifact_path"] is None

    resumed, same = _run(tmp_path)
    assert resumed.returncode == 0
    assert same["status"] == "question"
    assert same["draft_available"] is False
    assert same["self_review"]["pass_count"] == 2


def test_structural_review_repair_exposes_only_the_embedded_repair_surface(tmp_path):
    payload = _complete_prd(tmp_path)
    state_path = tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["status"] = "review_repair"
    state["self_review"] = {
        "pass_count": 1,
        "max_passes": 2,
        "status": "needs_repair",
        "artifact_sha256": state["artifact"]["sha256"],
        "findings": [{
            "id": "markdown-table-20",
            "kind": "invalid_table",
            "question_id": None,
            "message": "Markdown table near line 20 has inconsistent columns.",
            "blocking": True,
        }],
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    repaired = _peek(tmp_path, "add-due-date-to-task")

    assert repaired["status"] == "review_repair"
    assert repaired["draft_available"] is True
    assert repaired["artifact_path"] == payload["artifact_path"]
    assert repaired["current_question"] is None
    assert repaired["message"] == (
        "The generated draft needs a structural repair before V1 is ready."
    )


def test_design_intake_requests_prd_and_lists_only_valid_guided_prds(tmp_path):
    _publish_prd(tmp_path)
    (tmp_path / ".speed/features/unrelated-feature").mkdir(parents=True)
    (tmp_path / "specs/tech").mkdir(parents=True)
    (tmp_path / "specs/tech/unrelated-feature.md").write_text("# RFC\n")

    result, payload = _run_intake(tmp_path, "design")

    assert result.returncode == 0
    assert payload["status"] == "needs_input"
    next_input = payload["next_input"]
    assert next_input["id"] == "source_prd"
    assert next_input["prompt"] == "Which published PRD should ground this Design draft?"
    assert [option["feature_name"] for option in next_input["options"]] == [
        "add-due-date-to-task"
    ]
    assert next_input["fallback"]["id"] == "feature_name"
    assert "unrelated-feature" not in result.stdout


def test_design_uses_last_published_prd_while_a_newer_draft_is_open(tmp_path):
    published = _publish_prd(tmp_path)
    published_path = tmp_path / published["artifact_path"]
    published_content = published_path.read_text(encoding="utf-8")
    published_hash = hashlib.sha256(published_content.encode()).hexdigest()
    editable = published_content[published_content.index("## "):]
    editable = editable.replace(
        "## Problem & Evidence\n\n",
        "## Problem & Evidence\n\nUnpublished editorial marker. ",
        1,
    )

    result, draft = _run(
        tmp_path,
        "--update-document",
        "--answer",
        editable,
        "--expected-revision",
        str(published["revision"]),
    )
    assert result.returncode == 0, result.stderr
    assert draft["status"] == "drafted"
    assert hashlib.sha256(published_path.read_bytes()).hexdigest() != published_hash

    result, intake = _run_intake(tmp_path, "design")
    assert result.returncode == 0, result.stderr
    [source] = intake["next_input"]["options"]
    assert source["sha256"] == published_hash
    assert source["published_revision"] == published["published_revision"]

    result, design = _run_design(tmp_path)
    assert result.returncode == 0, result.stderr
    assert design["upstream"]["prd"]["sha256"] == published_hash
    assert "Unpublished editorial marker" not in design["upstream"]["prd"]["content"]


def test_workbench_command_routes_to_interview_without_speed_preflight(tmp_path):
    result = subprocess.run(
        [
            str(REPO / "workbench"),
            "draft",
            "prd",
            "add-due-date-to-task",
            "--json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "question"
    assert payload["current_question"]["id"] == "P-Q1"


def test_explicit_no_authentication_does_not_create_an_authentication_story(tmp_path):
    description = (
        "Internal operators need a basic API dashboard to inspect backend jobs. "
        "There is no authentication, account, session, or role boundary in the first release."
    )

    payload = _complete_named_prd(
        tmp_path,
        "backend-dashboard",
        description=description,
        title="Backend dashboard",
    )

    content = (tmp_path / payload["artifact_path"]).read_text()
    assert "authenticate securely" not in content
    assert "existing or new user" not in content


def test_direct_section_edit_survives_later_answer_regeneration(tmp_path):
    payload = _complete_prd(tmp_path)
    manual_summary = "A focused V1 for making overdue task status visible during planning."

    edited, payload = _run(
        tmp_path,
        "--update-section",
        "Summary",
        "--answer",
        manual_summary,
        "--expected-revision",
        str(payload["revision"]),
    )

    assert edited.returncode == 0, edited.stderr
    summary = next(section for section in payload["sections"] if section["title"] == "Summary")
    assert summary["state"] == "manual"
    assert manual_summary in (tmp_path / payload["artifact_path"]).read_text()

    answered, payload = _run(
        tmp_path,
        "--review-comments-json",
        '[{"section_title":"Scope","comment":"Calendar export is out of scope."}]',
        "--review-plan-json",
        json.dumps({
            "model": "test/reviewer",
            "analysis_summary": "The scope was reconsidered using the review comment.",
            "sections": [{
                "section_title": "Scope",
                "revised_body": (
                    "| Included | Not included |\n"
                    "|---|---|\n"
                    "| Due-date display and editing | Calendar export |"
                ),
            }],
        }),
        "--expected-revision",
        str(payload["revision"]),
    )

    assert answered.returncode == 0, answered.stderr
    assert manual_summary in (tmp_path / payload["artifact_path"]).read_text()
    state = json.loads(
        (tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json").read_text()
    )
    assert state["manual_sections"]["Summary"]["body"] == manual_summary


def test_review_comments_without_a_model_revision_do_not_change_the_prd(tmp_path):
    payload = _complete_prd(tmp_path)
    artifact_path = tmp_path / payload["artifact_path"]
    before = artifact_path.read_text()

    attempted, error = _run(
        tmp_path,
        "--review-comments-json",
        '[{"section_title":"Scope","comment":"Exclude calendar export."}]',
        "--expected-revision",
        str(payload["revision"]),
    )

    assert attempted.returncode != 0
    assert "host-model revision plan" in error["message"]
    assert artifact_path.read_text() == before


def test_review_comment_is_durable_before_regeneration(tmp_path):
    payload = _complete_prd(tmp_path)
    comment = {
        "section_title": "Requirements & Acceptance",
        "comment": "Cover invalid API date values explicitly.",
        "selected_text": "Given an invalid date",
        "selection_start": 10,
        "selection_end": 31,
        "anchor_revision": payload["revision"],
    }

    saved, payload = _run(
        tmp_path,
        "--add-review-comment-json",
        json.dumps(comment),
        "--expected-revision",
        str(payload["revision"]),
    )

    assert saved.returncode == 0, saved.stderr
    assert payload["review_comments"][0]["status"] == "open"
    assert payload["review_comments"][0]["comment"] == comment["comment"]
    assert payload["review_comments"][0]["author_email"]
    resumed, resumed_payload = _run(tmp_path, "--peek")
    assert resumed.returncode == 0, resumed.stderr
    assert resumed_payload["review_comments"] == payload["review_comments"]


def test_review_revision_preserves_a_table_section_shape(tmp_path):
    payload = _complete_prd(tmp_path)
    artifact_path = tmp_path / payload["artifact_path"]
    before = artifact_path.read_text()

    attempted, error = _run(
        tmp_path,
        "--review-comments-json",
        '[{"section_title":"Requirements & Acceptance","comment":"Add an API color contract."}]',
        "--review-plan-json",
        json.dumps({
            "model": "test/reviewer",
            "analysis_summary": "The invalid plan appends prose outside the required table.",
            "sections": [{
                "section_title": "Requirements & Acceptance",
                "revised_body": (
                    "| ID | Story | Product behavior | Done when |\n"
                    "|---|---|---|---|\n"
                    "| REQ-1 | US-1 | Return a hex color. | The API returns #RRGGBB. |\n\n"
                    "Also append this comment as prose."
                ),
            }],
        }),
        "--expected-revision",
        str(payload["revision"]),
    )

    assert attempted.returncode != 0
    assert "template-shaped Markdown table" in error["message"]
    assert artifact_path.read_text() == before


def test_cli_and_projected_skill_share_implementation_and_checkpoint(tmp_path):
    project = tmp_path / "projected"
    (project / ".agents").mkdir(parents=True)
    synced = subprocess.run(
        [
            sys.executable,
            "-m",
            "skills",
            "sync",
            "--project-root",
            str(project),
            "--skills-dir",
            str(REPO / "skills"),
            "--catalog-version",
            "test",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=str(REPO / "lib")),
    )
    assert synced.returncode == 0, synced.stderr

    projected = project / ".agents/skills/workbench-draft/scripts/draft.py"
    projected_bank = (
        project / ".agents/skills/workbench-draft/references/prd-questions.json"
    )
    canonical_bank = REPO / "skills/workbench-draft/references/prd-questions.json"
    assert projected.read_bytes() == HELPER.read_bytes()
    assert projected_bank.read_bytes() == canonical_bank.read_bytes()

    command = subprocess.run(
        [
            str(REPO / "workbench"),
            "draft",
            "prd",
            "sample-feature",
            "--json",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        env=dict(os.environ, SPEED_PROJECT_ROOT=str(project)),
    )
    assert command.returncode == 0, command.stderr
    cli_payload = json.loads(command.stdout)
    assert cli_payload["current_question"]["id"] == "P-Q1"

    result = subprocess.run(
        [
            sys.executable,
            str(projected),
            "prd",
            "sample-feature",
            "--project-root",
            str(project),
            "--answer",
            ANSWERS[0],
            "--expected-revision",
            "0",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["question_bank_version"] == "prd-v4"
    assert payload["current_question"]["id"] == "P-Q2"
    assert payload["revision"] == 1
    assert payload["implementation"] == cli_payload["implementation"]

    resumed = subprocess.run(
        [
            str(REPO / "workbench"),
            "draft",
            "prd",
            "sample-feature",
            "--json",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        env=dict(os.environ, SPEED_PROJECT_ROOT=str(project)),
    )
    assert resumed.returncode == 0, resumed.stderr
    resumed_payload = json.loads(resumed.stdout)
    assert resumed_payload["revision"] == 1
    assert resumed_payload["current_question"]["id"] == "P-Q2"
    assert resumed_payload["implementation"] == cli_payload["implementation"]

    completed_payload = resumed_payload
    for _ in range(10):
        if completed_payload["status"] in {"drafted", "drafted_with_open_questions"}:
            break
        question_id = completed_payload["current_question"]["id"]
        completed = subprocess.run(
            [
                sys.executable,
                str(projected),
                "prd",
                "sample-feature",
                "--project-root",
                str(project),
                "--answer",
                ANSWER_BY_ID[question_id],
                "--expected-revision",
                str(completed_payload["revision"]),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        completed_payload = json.loads(completed.stdout)
    assert completed_payload["status"] == "drafted"

    published = subprocess.run(
        [
            sys.executable,
            str(projected),
            "prd",
            "sample-feature",
            "--project-root",
            str(project),
            "--publish",
            "--expected-revision",
            str(completed_payload["revision"]),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert published.returncode == 0, published.stderr

    design_cli = subprocess.run(
        [str(REPO / "workbench"), "draft", "design", "sample-feature", "--json"],
        cwd=project,
        capture_output=True,
        text=True,
        env=dict(os.environ, SPEED_PROJECT_ROOT=str(project)),
    )
    assert design_cli.returncode == 0, design_cli.stderr
    design_cli_payload = json.loads(design_cli.stdout)
    assert design_cli_payload["current_question"]["id"] == "D-Q1"

    design_projected = subprocess.run(
        [
            sys.executable,
            str(projected),
            "design",
            "sample-feature",
            "--project-root",
            str(project),
            "--answer",
            DESIGN_ANSWERS[0],
            "--expected-revision",
            "0",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert design_projected.returncode == 0, design_projected.stderr
    design_projected_payload = json.loads(design_projected.stdout)
    assert design_projected_payload["current_question"]["id"] == "D-Q2"
    assert design_projected_payload["implementation"] == design_cli_payload["implementation"]

    design_resumed = subprocess.run(
        [str(REPO / "workbench"), "draft", "design", "sample-feature", "--json"],
        cwd=project,
        capture_output=True,
        text=True,
        env=dict(os.environ, SPEED_PROJECT_ROOT=str(project)),
    )
    assert design_resumed.returncode == 0, design_resumed.stderr
    design_resumed_payload = json.loads(design_resumed.stdout)
    assert design_resumed_payload["revision"] == 1
    assert design_resumed_payload["current_question"]["id"] == "D-Q2"
    assert design_resumed_payload["implementation"] == design_cli_payload["implementation"]


def test_design_requires_generated_prd_without_creating_design_checkpoint(tmp_path):
    result, payload = _run_design(tmp_path)

    assert result.returncode == 1
    assert payload["status"] == "error"
    assert "workbench draft prd add-due-date-to-task" in payload["message"]
    assert not (
        tmp_path / ".speed/features/add-due-date-to-task/authoring-design.json"
    ).exists()


def test_design_is_pinned_to_prd_and_generates_linked_artifact(tmp_path):
    prd_payload = _publish_prd(tmp_path)
    prd_hash = prd_payload["artifact_path"] and hashlib.sha256(
        (tmp_path / prd_payload["artifact_path"]).read_bytes()
    ).hexdigest()

    first, payload = _run_design(tmp_path)
    assert first.returncode == 0, first.stderr
    assert payload["current_question"]["id"] == "D-Q1"
    assert payload["upstream"]["prd"]["path"] == "specs/add-due-date-to-task/prd.md"
    assert payload["upstream"]["prd"]["sha256"] == prd_hash
    suggestion = payload["current_question"]["suggestion"]
    assert suggestion["sources"][0]["id"].startswith("prd:")
    assert suggestion["sources"][0]["path"] == payload["upstream"]["prd"]["path"]

    for revision, answer in enumerate(DESIGN_ANSWERS):
        result, payload = _run_design(
            tmp_path, "--answer", answer, "--expected-revision", str(revision)
        )
        assert result.returncode == 0, result.stderr

    assert payload["status"] == "drafted"
    assert payload["artifact_path"] == "specs/add-due-date-to-task/design.md"
    design = (tmp_path / payload["artifact_path"]).read_text()
    assert "**Product source:** [PRD](prd.md)" in design
    assert f"**Product source hash:** `{prd_hash}`" in design
    assert "### D-Q1" in design
    assert DESIGN_ANSWERS[0] in design
    assert [item["id"] for item in payload["interview"]] == [
        f"D-Q{index}" for index in range(1, 9)
    ]

    feature_dir = tmp_path / ".speed/features/add-due-date-to-task"
    checkpoint = json.loads((feature_dir / "authoring-design.json").read_text())
    dashboard_draft = json.loads((feature_dir / "draft-design.json").read_text())
    assert checkpoint["upstream"]["prd"]["sha256"] == prd_hash
    assert checkpoint["artifact"]["upstream"] == checkpoint["upstream"]
    assert dashboard_draft["upstream"] == checkpoint["upstream"]
    assert dashboard_draft["authoring"]["self_review"]["status"] == "passed"
    package_index = (tmp_path / "specs/add-due-date-to-task/index.md").read_text()
    assert "[PRD](prd.md)" in package_index
    assert "[Design](design.md)" in package_index


def test_rfc_reuses_the_guided_shell_and_publishes_a_version(tmp_path):
    _publish_prd(tmp_path)
    _complete_design(tmp_path, publish=True)
    result, payload = _run_rfc(tmp_path)
    assert result.returncode == 0, result.stderr
    assert payload["current_question"]["id"] == "R-Q1"

    for revision, answer in enumerate(RFC_ANSWERS):
        result, payload = _run_rfc(
            tmp_path, "--answer", answer, "--expected-revision", str(revision)
        )
        assert result.returncode == 0, result.stderr

    assert payload["status"] == "drafted"
    assert payload["artifact_path"] == "specs/add-due-date-to-task/rfc.md"
    assert [item["id"] for item in payload["interview"]] == [
        f"R-Q{index}" for index in range(1, 9)
    ]
    published_revision = payload["revision"] + 1
    result, published = _run_rfc(
        tmp_path,
        "--publish",
        "--expected-revision",
        str(payload["revision"]),
    )
    assert result.returncode == 0, result.stderr
    assert published["status"] == "published"
    assert published["published_revision"] == published_revision
    assert published["message"] == "Technical RFC v2 published."
    assert any(
        item["revision"] == published_revision and item["status"] == "published"
        for item in published["versions"]
    )
    draft_record = json.loads(
        (tmp_path / ".speed/features/add-due-date-to-task/draft-rfc.json").read_text()
    )
    assert draft_record["status"] == "published"
    assert draft_record["authoring"]["published_revision"] == published_revision
    assert draft_record["authoring"]["publish_history"][-1]["revision"] == published_revision
    package_index = (tmp_path / "specs/add-due-date-to-task/index.md").read_text()
    assert "| [Technical RFC](rfc.md) | Published |" in package_index


def test_design_blocks_on_changed_prd_without_mutating_checkpoint(tmp_path):
    _publish_prd(tmp_path)
    answered, payload = _run_design(
        tmp_path,
        "--answer",
        DESIGN_ANSWERS[0],
        "--expected-revision",
        "0",
    )
    assert answered.returncode == 0, answered.stderr
    state_path = tmp_path / ".speed/features/add-due-date-to-task/authoring-design.json"
    before = state_path.read_bytes()
    prd_path = tmp_path / "specs/add-due-date-to-task/prd.md"
    prd_path.write_text(prd_path.read_text() + "\nChanged product obligation.\n")

    blocked, error = _run_design(tmp_path)

    assert blocked.returncode == 1
    assert error["status"] == "upstream_changed"
    assert state_path.read_bytes() == before


def test_question_exposes_suggestion_sources_confidence_and_gaps(tmp_path):
    result, payload = _run(tmp_path)

    assert result.returncode == 0
    suggestion = payload["current_question"]["suggestion"]
    assert suggestion["confidence"] == "missing"
    assert suggestion["accept_ready"] is False
    assert suggestion["answer"] is None
    assert suggestion["sources"] == []
    assert "No usable evidence" in suggestion["gaps"][0]

    refused, error = _run(
        tmp_path,
        "--accept-suggestion",
        "--expected-revision",
        "0",
    )
    assert refused.returncode == 1
    assert error["status"] == "error"
    state = json.loads(
        (tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json").read_text()
    )
    assert state["revision"] == 0
    assert state["answers"] == {}


def test_grounded_suggestion_can_be_accepted_and_preserves_decision(tmp_path):
    feature_dir = tmp_path / ".speed/features/add-due-date-to-task"
    feature_dir.mkdir(parents=True)
    (feature_dir / "intent.json").write_text(json.dumps({
        "text": "Team leads cannot identify overdue work on the task board."
    }))
    (feature_dir / "context-package.json").write_text(json.dumps({
        "bluf_summary": "Overdue tasks are hidden until each task is opened.",
        "defects": [{"name": "Due dates are not visible on task cards."}],
        "sources_status": {"research": "ok"},
        "suggested_responses": {
            "P-Q1": {
                "answer": (
                    "Team leads cannot identify overdue work from the task board, "
                    "which delays daily planning and intervention."
                )
            }
        },
    }))

    initial, payload = _run(tmp_path)
    assert initial.returncode == 0
    suggestion = payload["current_question"]["suggestion"]
    assert suggestion["confidence"] == "grounded"
    assert suggestion["accept_ready"] is True
    assert len(suggestion["sources"]) >= 2

    accepted, payload = _run(
        tmp_path,
        "--accept-suggestion",
        "--expected-revision",
        "0",
    )
    assert accepted.returncode == 0
    assert payload["revision"] == 1
    assert payload["current_question"]["id"] == "P-Q2"
    state = json.loads((feature_dir / "authoring-prd.json").read_text())
    answer = state["answers"]["P-Q1"]
    assert answer["decision"] == "accepted"
    assert answer["suggestion_id"] == suggestion["id"]
    assert answer["answer"] == suggestion["answer"]
    assert state["decision_history"][-1]["action"] == "accepted"


def test_rejected_suggestion_stays_open_and_is_recorded(tmp_path):
    feature_dir = tmp_path / ".speed/features/add-due-date-to-task"
    feature_dir.mkdir(parents=True)
    suggested = (
        "Team leads miss deadlines because due dates are not visible during board "
        "planning; show due status where planning happens."
    )
    (feature_dir / "context-package.json").write_text(json.dumps({
        "bluf_summary": suggested,
        "suggested_responses": {"P-Q1": {"answer": suggested}},
    }))
    initial, payload = _run(tmp_path)
    suggestion_id = payload["current_question"]["suggestion"]["id"]

    rejected, payload = _run(
        tmp_path,
        "--reject-suggestion",
        "--expected-revision",
        "0",
    )
    assert rejected.returncode == 0
    assert payload["revision"] == 1
    assert payload["current_question"]["id"] == "P-Q1"
    assert payload["current_question"]["suggestion"]["rejected"] is True

    state_path = tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json"
    state = json.loads(state_path.read_text())
    assert "P-Q1" not in state["answers"]
    decision = state["decision_history"][-1]
    assert decision["question_id"] == "P-Q1"
    assert decision["suggestion_id"] == suggestion_id
    assert decision["action"] == "rejected"
    assert decision["answer"] is None
    assert decision["revision"] == 1

    answered, payload = _run(
        tmp_path,
        "--answer",
        ANSWERS[0],
        "--expected-revision",
        "1",
    )
    assert answered.returncode == 0
    assert payload["current_question"]["id"] == "P-Q2"


def test_v1_checkpoint_migrates_without_losing_answers(tmp_path):
    state_path = tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "schema_version": 1,
        "feature_name": "add-due-date-to-task",
        "artifact_type": "prd",
        "question_bank_version": "prd-v1",
        "status": "interviewing",
        "revision": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "answers": {
            "P-Q1": {
                "state": "confirmed",
                "answer": ANSWERS[0],
                "confirmed_at": "2026-01-01T00:00:00+00:00",
            }
        },
        "artifact": None,
    }))

    result, payload = _run(tmp_path)

    assert result.returncode == 0
    assert payload["current_question"]["id"] == "P-Q2"
    migrated = json.loads(state_path.read_text())
    assert migrated["schema_version"] == 2
    assert migrated["question_bank_version"] == "prd-v4"
    assert migrated["answers"]["P-Q1"]["answer"] == ANSWERS[0]
    assert migrated["answers"]["P-Q1"]["decision"] == "edited"
    assert "P-Q2" in migrated["suggestions"]


def test_authentication_fallback_surfaces_every_material_question(tmp_path):
    description = (
        "Add authentication to the existing single-user task application so each "
        "person's tasks are private instead of visible to everyone."
    )
    started = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "auth-system",
            "--project-root",
            str(tmp_path),
            "--feature-description",
            description,
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(started.stdout)
    assert started.returncode == 0, started.stderr
    question = payload["current_question"]
    assert question["id"] == "P-Q2"
    assert "authentication method" in question["prompt"]
    assert "username and password" in question["prompt"]
    assert "Google sign-in" in question["prompt"]
    assert "shared" not in question["prompt"].lower()
    assert "what jobs" not in question["prompt"]
    assert "roles are affected" not in question["prompt"]
    assert question["suggestion"]["answer"] is None
    assert "does not resolve this decision" in question["suggestion"]["gaps"][-1]
    assert payload["draft_available"] is False
    assert payload["progress"]["total"] > 3
    assert set(payload["coverage"]) == {f"P-Q{index}" for index in range(1, 9)}
    assert payload["artifact_path"] is None

    method_answer = (
        "The first release supports Google sign-in only; username and password "
        "authentication is not included."
    )
    answered = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "auth-system",
            "--project-root",
            str(tmp_path),
            "--answer",
            method_answer,
            "--expected-revision",
            "0",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(answered.stdout)
    assert answered.returncode == 0, answered.stderr
    auth_answers = {
        "P-Q3": "Successful sign-in gives private access while existing task behavior and accessibility do not regress.",
        "P-Q4": "A user signs in with Google, reaches their tasks, sees clear failures, can retry, and can sign out. Given valid credentials, when sign-in succeeds, then only that user's tasks are visible.",
        "P-Q5": "Given valid Google identity, when sign-in completes, then a private session opens; invalid identity returns a recoverable error.",
        "P-Q6": "Within 30 days, ninety percent of active users sign in successfully; Product Analytics owns the measure.",
        "P-Q7": "Google sign-in, private task access, and sign-out are included; password authentication and account recovery are excluded from V1.",
        "P-Q8": "The existing identity provider is a dependency; Security owns session and account-migration risks before release.",
    }
    seen = []
    for _ in range(8):
        if payload["status"] == "drafted":
            break
        question = payload["current_question"]
        seen.append(question["id"])
        if question["id"] == "P-Q7":
            assert "existing account and data" in question["prompt"]
        completed = subprocess.run(
            [sys.executable, str(HELPER), "prd", "auth-system", "--project-root", str(tmp_path),
             "--answer", auth_answers[question["id"]], "--expected-revision", str(payload["revision"]), "--json"],
            capture_output=True, text=True,
        )
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout)
    assert payload["status"] == "drafted"
    assert seen == ["P-Q3", "P-Q4", "P-Q5", "P-Q7", "P-Q8"]
    final_content = (tmp_path / payload["artifact_path"]).read_text()
    assert method_answer in final_content
    assert auth_answers["P-Q3"] in final_content
    assert "A user signs in with Google, reaches their tasks" in final_content
    assert "when sign-in succeeds, then only that user's tasks are visible" in final_content


def test_local_feature_requires_scope_but_omits_immaterial_risk_question(tmp_path):
    description = (
        "Let a task user rename an existing task inline so they can correct its title."
    )
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "rename-task-inline",
            "--project-root",
            str(tmp_path),
            "--feature-description",
            description,
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert payload["progress"]["total"] == 5
    assert payload["current_question"]["id"] == "P-Q2"
    assert payload["draft_available"] is False
    assert payload["coverage"]["P-Q7"]["confidence_label"] == "unresolved"
    assert payload["coverage"]["P-Q8"]["confidence_label"] == "not_material"


def test_simple_feature_reaches_a_traceable_v1_after_complete_interview(tmp_path):
    description = (
        "People create tasks for future work, but tasks have no due date and the "
        "list cannot highlight work that is due today or tomorrow."
    )
    payload = _start_prd(
        tmp_path,
        "task-due-dates",
        description=description,
        title="Due dates for tasks",
    )
    assert payload["current_question"]["id"] == "P-Q2"

    answers = {
        "P-Q2": (
            "Every task user needs to assign and see due dates so time-sensitive "
            "work is not missed; task creation, completion, editing, and deletion "
            "must remain unchanged."
        ),
        "P-Q3": (
            "Due dates make time-sensitive work visible while existing task creation, "
            "completion, editing, deletion, and accessibility behavior remain unchanged."
        ),
        "P-Q4": (
            "A user adds or edits an optional due date and saves the task; the list "
            "shows overdue, today, and tomorrow states. If saving fails, the date and "
            "other edits remain available so the user can retry."
        ),
        "P-Q5": (
            "Given an invalid due date, when save is attempted, then a clear inline "
            "error appears, the task is not changed, and the entered values remain available."
        ),
        "P-Q7": (
            "Date entry, persistence, display, editing, and clearing are in scope; "
            "reminders and recurring schedules are out. Delivery depends on a nullable "
            "API field. Engineering owns the date-boundary release risk."
        ),
    }
    asked = []
    while payload["status"] != "drafted":
        question_id = payload["current_question"]["id"]
        asked.append(question_id)
        completed = subprocess.run(
            [
                sys.executable,
                str(HELPER),
                "prd",
                "task-due-dates",
                "--project-root",
                str(tmp_path),
                "--answer",
                answers[question_id],
                "--expected-revision",
                str(payload["revision"]),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout)

    assert asked == ["P-Q2", "P-Q3", "P-Q4", "P-Q5", "P-Q7"]
    assert payload["progress"] == {"confirmed": 5, "total": 5, "deferred": []}
    sections = {section["title"]: section for section in payload["sections"]}
    assert sections["Summary"]["question_ids"] == ["P-Q1", "P-Q2", "P-Q3"]
    assert sections["Requirements & Acceptance"]["question_ids"] == ["P-Q4", "P-Q5"]
    assert sections["Delivery, Risks & Open Questions"]["question_ids"] == ["P-Q7"]
    assert sections["User Stories"]["source_answer"] == answers["P-Q2"]
    assert sections["Summary"]["source_answers"] == {
        "P-Q1": description,
        "P-Q2": answers["P-Q2"],
        "P-Q3": answers["P-Q3"],
    }
    assert sections["Success"]["question_ids"] == ["P-Q3"]
    content = (tmp_path / payload["artifact_path"]).read_text()
    assert "No feature-specific" not in content
    assert "Unresolved" not in content
    assert "| ID | Story | Priority |" in content
    assert "| US-1 | As a task user" in content
    assert "| ID | Story | Product behavior | Done when |" in content
    assert "| REQ-1 | US-1 |" in content
    assert "| Included | Not included |" in content
    assert "| ID | What must remain true | How it will be verified |" in content
    assert "| GR-1 |" in content
    assert "| ID | Outcome or signal | Target | Window | Owner |" in content
    assert "| SM-1 |" in content
    scope_body = content.split("## Scope\n\n", 1)[1].split("\n\n## ", 1)[0]
    delivery_body = content.split("## Delivery, Risks & Open Questions\n\n", 1)[1].split("\n\n## ", 1)[0]
    assert "Date entry, persistence, display, editing, and clearing are in scope" in scope_body
    assert "Delivery depends on a nullable API field" in delivery_body
    assert "Engineering owns the date-boundary release risk" in delivery_body


def test_compact_plan_preserves_brief_behaviors_when_one_flow_is_clarified(tmp_path):
    description = (
        "Older tasks can be buried and missed. "
        "What I want is an optional due date when creating a task. "
        "Tasks due today or tomorrow can be highlighted. "
        "Tasks with earlier due dates can be shown first."
    )
    coverage = {
        question_id: {
            "coverage": f"coverage-{question_id}",
            "confidence": 0.9,
            "confidence_label": "evidence_backed",
            "impact": "high",
            "basis": ["Resolved from the author description."],
            "rationale": "Resolved from the author description.",
            "resolved_value": f"Resolved value for {question_id}.",
            "question_value": 0.1,
        }
        for question_id in (f"P-Q{index}" for index in range(1, 9))
    }
    coverage["P-Q4"].update({
        "confidence": 0.2,
        "confidence_label": "unresolved",
        "resolved_value": None,
        "question_value": 0.8,
    })
    coverage["P-Q5"].update({
        "confidence": 1.0,
        "confidence_label": "not_material",
        "resolved_value": None,
        "question_value": 0.0,
    })
    coverage["P-Q7"]["resolved_value"] = (
        "V1 includes optional due dates, due-soon highlighting, and ordering; "
        "reminders and recurring tasks are out of scope."
    )
    plan = {
        "mode": "model",
        "planner_version": "model-prd-v5",
        "model": "claude-code/opus",
        "generated_at": "2026-09-08T08:00:00+00:00",
        "feature_title": "Optional Task Due Dates",
        "analysis_summary": "The brief covers the core behavior; overdue handling needs confirmation.",
        "prd_size": "Small",
        "coverage": coverage,
        "questions": [{
            "id": "P-Q4",
            "prompt": "How should overdue pending tasks behave in the list?",
            "purpose": "Confirm overdue behavior.",
            "evidence": "The brief defines due-soon behavior but not overdue behavior.",
            "completion_evidence": "Ordering and emphasis are explicit.",
            "response_control": {
                "id": "model-answer-p-q4",
                "input_type": "single_select",
                "prompt": "Choose the closest answer or write your own.",
                "initial_value": "",
                "options": [
                    {"value": "Overdue tasks sort above all other tasks and use a stronger highlight.", "label": "Sort and highlight overdue"},
                    {"value": "Overdue tasks keep the current order.", "label": "Keep current order"},
                ],
                "submit_action": "answer",
                "allow_other": True,
            },
        }],
        "composition": {
            "requirements": [],
            "scope": None,
            "guardrails": [],
            "success": None,
        },
        "fallback_reason": None,
        "optimization": "complete-template-intake-v1",
    }
    started = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "optional-task-due-dates",
            "--project-root",
            str(tmp_path),
            "--feature-description",
            description,
            "--model-plan-json",
            json.dumps(plan),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert started.returncode == 0, started.stderr or started.stdout
    payload = json.loads(started.stdout)

    completed = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "optional-task-due-dates",
            "--project-root",
            str(tmp_path),
            "--answers-json",
            json.dumps([{
                "question_id": "P-Q4",
                "answer": "Overdue tasks sort above all other tasks and use a stronger highlight.",
            }]),
            "--expected-revision",
            str(payload["revision"]),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["status"] in {"drafted", "drafted_with_open_questions"}

    content = (tmp_path / payload["artifact_path"]).read_text()
    requirements = content.split(
        "## Requirements & Acceptance\n\n", 1
    )[1].split("\n\n## ", 1)[0]
    assert requirements.count("| REQ-") == 4
    assert "optional due date when creating a task" in requirements
    assert "due today or tomorrow can be highlighted" in requirements
    assert "earlier due dates can be shown first" in requirements
    assert "Overdue tasks sort above all other tasks" in requirements


def test_model_plan_accepts_more_than_three_questions_for_one_coverage_area(tmp_path):
    coverage = {
        question_id: {
            "coverage": f"coverage-{question_id}",
            "confidence": 0.9,
            "confidence_label": "evidence_backed",
            "impact": "high",
            "basis": ["Resolved from the author description."],
            "rationale": "Resolved from the author description.",
            "resolved_value": f"Resolved value for {question_id}.",
            "question_value": 0.1,
        }
        for question_id in (f"P-Q{index}" for index in range(1, 9))
    }
    coverage["P-Q4"].update({
        "confidence": 0.1,
        "confidence_label": "unresolved",
        "resolved_value": None,
        "question_value": 0.9,
    })
    coverage["P-Q7"]["resolved_value"] = (
        "V1 includes create, edit, clear, and retry behavior for optional due dates; "
        "reminders and recurring tasks are out of scope."
    )
    prompts = [
        "How should users create a task with a due date?",
        "How should users change an existing due date?",
        "How should users clear a due date from a task?",
        "What should happen when saving a due date fails?",
    ]
    questions = []
    for index, prompt in enumerate(prompts, 1):
        question_id = f"P-Q4-{index}"
        questions.append({
            "id": question_id,
            "coverage_id": "P-Q4",
            "prompt": prompt,
            "purpose": "Resolve one observable task due-date behavior.",
            "evidence": "The description identifies due dates but not this behavior.",
            "completion_evidence": "The behavior and result are explicit.",
            "response_control": {
                "id": f"model-answer-{question_id.lower()}",
                "input_type": "textarea",
                "prompt": "Describe the expected product behavior.",
                "initial_value": "",
                "options": [],
                "submit_action": "answer",
                "allow_other": False,
            },
            "suggestion": {
                "id": f"model-{question_id.lower()}-0",
                "answer": None,
                "confidence": "missing",
                "accept_ready": False,
                "sources": [],
                "gaps": ["This decision is absent from the evidence."],
                "created_at": "2026-09-08T08:00:00+00:00",
                "rejected": False,
            },
        })
    plan = {
        "mode": "model",
        "planner_version": "model-prd-v5",
        "model": "test/planner",
        "generated_at": "2026-09-08T08:00:00+00:00",
        "feature_title": "Optional Task Due Dates",
        "analysis_summary": "Four independent product behaviors still need confirmation.",
        "prd_size": "Small",
        "coverage": coverage,
        "questions": questions,
        "composition": {
            "requirements": [],
            "scope": None,
            "guardrails": [],
            "success": None,
        },
        "fallback_reason": None,
    }
    started = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "optional-task-due-dates",
            "--project-root",
            str(tmp_path),
            "--feature-description",
            "Let task owners assign optional due dates to avoid missing time-sensitive work.",
            "--model-plan-json",
            json.dumps(plan),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert started.returncode == 0, started.stderr or started.stdout
    payload = json.loads(started.stdout)
    assert payload["progress"]["total"] == 4

    answers = [
        "A user can create a task with a valid optional due date.",
        "A user can replace an existing due date and the new value persists.",
        "A user can clear a due date and the task remains valid.",
        "A failed save preserves the entered due date and offers a retry.",
    ]
    completed = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "optional-task-due-dates",
            "--project-root",
            str(tmp_path),
            "--answers-json",
            json.dumps([
                {"question_id": question["id"], "answer": answer}
                for question, answer in zip(questions, answers)
            ]),
            "--expected-revision",
            str(payload["revision"]),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["status"] == "drafted"
    assert [item["coverage_id"] for item in payload["interview"]] == ["P-Q4"] * 4
    content = (tmp_path / payload["artifact_path"]).read_text()
    for answer in answers:
        assert answer in content


def test_model_resolved_values_drive_requirements_and_scope_without_open_gaps(tmp_path):
    description = (
        "Tasks can have labels. What I want is a label picker and a filter, "
        "with several conversational examples that are not PRD-ready requirements."
    )
    coverage = {
        question_id: {
            "coverage": f"coverage-{question_id}",
            "confidence": 0.9,
            "confidence_label": "evidence_backed",
            "impact": "high",
            "basis": ["Resolved by the supplied product context."],
            "rationale": "Resolved by the supplied product context.",
            "resolved_value": f"Resolved value for {question_id}.",
            "question_value": 0.1,
        }
        for question_id in (f"P-Q{index}" for index in range(1, 9))
    }
    coverage["P-Q1"]["resolved_value"] = (
        "Task owners cannot group related work (e.g. launch tasks) for quick discovery. "
        "They currently scan the full list."
    )
    coverage["P-Q2"]["resolved_value"] = (
        "Task owners can use labels; existing unlabeled tasks and API clients remain unchanged."
    )
    coverage["P-Q3"]["resolved_value"] = (
        "Labels improve task discovery while existing task behavior does not regress."
    )
    coverage["P-Q4"]["resolved_value"] = (
        "A task owner assigns one label and filters the task list by that label."
    )
    coverage["P-Q4"]["confidence_label"] = "confirmed"
    coverage["P-Q5"].update({
        "confidence_label": "inferred",
        "resolved_value": (
            "Filtering is observable in the list. Behavior for deleted labels is unstated."
        ),
    })
    coverage["P-Q6"].update({
        "confidence_label": "not_material",
        "resolved_value": None,
    })
    coverage["P-Q7"]["resolved_value"] = (
        "In: assigning and filtering one label. Out: sharing and bulk editing. "
        "Dependency: the existing task-list API."
    )
    coverage["P-Q8"].update({
        "confidence_label": "not_material",
        "resolved_value": None,
    })
    plan = {
        "mode": "model",
        "planner_version": "model-prd-v5",
        "model": "claude-code/opus",
        "generated_at": "2026-09-07T13:15:35+00:00",
        "analysis_summary": "The feature is sufficiently resolved to draft without more questions.",
        "prd_size": "Standard",
        "coverage": coverage,
        "questions": [],
        "composition": {
            "requirements": [
                {
                    "story_id": "US-1",
                    "product_behavior": "A task owner assigns one label to a task.",
                    "done_when": "After save and reload, the selected label remains on the task.",
                },
                {
                    "story_id": "US-1",
                    "product_behavior": "A task owner filters the list by a label.",
                    "done_when": "The list shows only tasks assigned to the selected label.",
                },
            ],
            "scope": {
                "included": "Assigning and filtering one label.",
                "not_included": "Label sharing and bulk editing.",
            },
            "guardrails": [{
                "must_remain_true": "Existing unlabeled tasks and API clients remain valid.",
                "verification": "Existing task create, read, update, and delete checks pass without labels.",
            }],
            "success": {
                "outcome_or_signal": "Task owners find labeled work without scanning the full list.",
                "target": "Provisional baseline comparison",
                "window": "First 30 days",
                "owner": "Product",
            },
        },
        "fallback_reason": None,
    }
    initial_coverage = json.loads(json.dumps(coverage))
    initial_coverage["P-Q4"].update({
        "confidence": 0.2,
        "confidence_label": "unresolved",
        "resolved_value": None,
        "question_value": 0.8,
    })
    initial_plan = {
        **plan,
        "coverage": initial_coverage,
        "questions": [{
            "id": "P-Q4",
            "prompt": "How should assigning and filtering task labels behave?",
            "purpose": "Resolve the observable product behavior.",
            "evidence": "Use the feature description and repository context.",
            "completion_evidence": "The happy path and boundaries are explicit.",
            "response_control": {
                "id": "model-answer-p-q4",
                "input_type": "textarea",
                "prompt": "Submit the product behavior.",
                "initial_value": "",
                "options": [],
                "submit_action": "answer",
                "allow_other": False,
            },
        }],
    }
    started = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "task-labels",
            "--project-root",
            str(tmp_path),
            "--feature-description",
            description,
            "--model-plan-json",
            json.dumps(initial_plan),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert started.returncode == 0, started.stderr or started.stdout
    payload = json.loads(started.stdout)
    assert payload["current_question"]["id"] == "P-Q4"

    answered = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "task-labels",
            "--project-root",
            str(tmp_path),
            "--answers-json",
            json.dumps([{
                "question_id": "P-Q4",
                "answer": (
                    "Raw interview wording about labels that the final model will normalize."
                ),
            }]),
            "--expected-revision",
            str(payload["revision"]),
            "--hold-generation",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(answered.stdout)
    assert answered.returncode == 0, answered.stderr or answered.stdout

    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "task-labels",
            "--project-root",
            str(tmp_path),
            "--model-plan-json",
            json.dumps(plan),
            "--expected-revision",
            str(payload["revision"]),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr or result.stdout
    assert payload["status"] == "drafted"
    content = (tmp_path / payload["artifact_path"]).read_text()
    summary = content.split("## Summary\n\n", 1)[1].split("\n\n## ", 1)[0]
    requirements = content.split(
        "## Requirements & Acceptance\n\n", 1
    )[1].split("\n\n## ", 1)[0]
    scope = content.split("## Scope\n\n", 1)[1].split("\n\n## ", 1)[0]
    assert "A task owner assigns one label" in requirements
    assert "After save and reload, the selected label remains" in requirements
    assert "Pass when this observable behavior is true" not in requirements
    assert "Raw interview wording about labels" not in requirements
    assert "Behavior for deleted labels is unstated" not in requirements
    assert "conversational examples" not in requirements
    assert "assigning and filtering one label" in scope.lower()
    assert "sharing and bulk editing" in scope.lower()
    assert "No explicit exclusion" not in scope
    assert "conversational examples" not in scope
    assert "(e.g. launch tasks) for quick discovery." in summary
    assert "| Draft | mohit-inrhythm |" in content
    assert "| Standard |" not in content
    guardrails = content.split(
        "## Guardrails / Must Not Regress\n\n", 1
    )[1].split("\n\n## ", 1)[0]
    assert "Existing unlabeled tasks and API clients remain valid" in guardrails
    assert "Existing task create, read, update, and delete checks pass" in guardrails
    success = content.split("## Success\n\n", 1)[1].split("\n\n## ", 1)[0]
    assert "First 30 days" in success
    assert "Product" in success


def test_broader_dashboard_asks_complete_flow_without_false_authentication(tmp_path):
    description = (
        "The application exposes task APIs but has no user-facing interface. Users "
        "need a responsive dashboard for the existing task operations."
    )
    payload = _start_prd(
        tmp_path,
        "task-dashboard-ui",
        description=description,
        title="Dashboard UI for the task API",
    )
    answers = {
        "P-Q2": (
            "Every task user needs the dashboard for all core operations. An empty "
            "account shows an empty state. Existing API behavior must remain unchanged, "
            "and Product should measure successful task operations after launch."
        ),
        "P-Q3": (
            "The dashboard makes core task work usable without direct API calls while "
            "existing API behavior, task data, and accessibility do not regress."
        ),
        "P-Q4": (
            "The dashboard loads the task list and each saved operation updates it. "
            "If an API request fails, preserve the user's input and allow a retry."
        ),
        "P-Q5": (
            "Given an API failure, when a task operation is attempted, then the dashboard "
            "shows a recoverable error, preserves input, and permits a retry."
        ),
        "P-Q6": (
            "Use task-operation success rate from client analytics against a baseline "
            "captured before launch; Product Analytics owns the measure."
        ),
        "P-Q7": (
            "The responsive list and existing CRUD operations are included; new API "
            "capabilities are excluded. Delivery depends on the existing API contract, "
            "and Engineering owns compatibility risk."
        ),
    }
    asked = []
    while payload["status"] != "drafted":
        question = payload["current_question"]
        asked.append(question["id"])
        assert "authentication" not in question["prompt"].lower()
        completed = subprocess.run(
            [
                sys.executable,
                str(HELPER),
                "prd",
                "task-dashboard-ui",
                "--project-root",
                str(tmp_path),
                "--answer",
                answers[question["id"]],
                "--expected-revision",
                str(payload["revision"]),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout)

    assert asked == ["P-Q2", "P-Q3", "P-Q4", "P-Q5", "P-Q7"]
    assert payload["progress"]["confirmed"] == 5
    success = next(section for section in payload["sections"] if section["title"] == "Success")
    assert success["question_ids"] == ["P-Q3"]


def test_draft_review_updates_stable_coverage_and_regenerates(tmp_path):
    description = (
        "Let a task user rename an existing task inline so they can correct its title."
    )
    payload = _complete_named_prd(
        tmp_path, "rename-task-inline", description=description
    )
    revised_hypothesis = (
        "If task owners can rename inline, correction time will fall while task "
        "completion state and list readability do not regress."
    )
    revised = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "rename-task-inline",
            "--project-root",
            str(tmp_path),
            "--update-coverage",
            "hypothesis",
            "--answer",
            revised_hypothesis,
            "--expected-revision",
            str(payload["revision"]),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(revised.stdout)
    assert revised.returncode == 0, revised.stderr
    assert payload["status"] == "drafted"
    content = (tmp_path / payload["artifact_path"]).read_text()
    assert revised_hypothesis in content
    state = json.loads(
        (tmp_path / ".speed/features/rename-task-inline/authoring-prd.json").read_text()
    )
    assert state["answers"]["P-Q3"]["decision"] == "review_edited"


def test_interview_resumes_and_generates_dashboard_compatible_prd(tmp_path):
    first, payload = _run(tmp_path)
    assert first.returncode == 0
    assert payload["status"] == "question"
    assert payload["current_question"]["id"] == "P-Q1"

    payload = _complete_prd(tmp_path)

    assert payload["status"] == "drafted"
    assert payload["artifact_path"] == "specs/add-due-date-to-task/prd.md"
    assert payload["dashboard_url"] == (
        "http://localhost:3000/define/add-due-date-to-task"
    )
    assert payload["progress"]["confirmed"] == payload["progress"]["total"]
    assert 3 <= payload["progress"]["total"] <= 8

    prd = tmp_path / payload["artifact_path"]
    content = prd.read_text()
    assert "| Draft |" in content
    assert "Scale" not in content
    assert "draft_scale" not in payload
    for heading in (
        "Summary",
        "Problem & Evidence",
        "Hypothesis",
        "User Stories",
        "Requirements & Acceptance",
        "Scope",
        "Guardrails / Must Not Regress",
        "Delivery, Risks & Open Questions",
        "Success",
        "References",
    ):
        assert f"## {heading}" in content
    assert "### P-Q1" not in content
    assert ANSWERS[0] in content

    feature_dir = tmp_path / ".speed" / "features" / "add-due-date-to-task"
    assert (feature_dir / "authoring-prd.json").is_file()
    assert (feature_dir / "ceremony.json").is_file()
    assert (feature_dir / "context-package.json").is_file()
    draft = json.loads((feature_dir / "draft-prd.json").read_text())
    assert draft["content"] == content
    assert draft["file_path"] == payload["artifact_path"]
    assert draft["authoring"]["self_review"]["status"] == "passed"
    interview = json.loads((feature_dir / "authoring-prd.json").read_text())
    assert interview["answers"]["P-Q1"]["actor_email"]
    assert interview["answers"]["P-Q1"]["evidence_prompt"].startswith("Reviewed")


def test_revision_conflict_does_not_change_answer_state(tmp_path):
    _run(tmp_path)
    accepted, payload = _run(
        tmp_path,
        "--answer",
        ANSWERS[0],
        "--expected-revision",
        "0",
    )
    assert accepted.returncode == 0
    assert payload["revision"] == 1

    stale, payload = _run(
        tmp_path,
        "--answer",
        "This stale answer must not win.",
        "--expected-revision",
        "0",
    )
    assert stale.returncode == 2
    assert payload["status"] == "revision_conflict"
    state = json.loads(
        (tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json").read_text()
    )
    assert state["answers"]["P-Q1"]["answer"] == ANSWERS[0]
    assert "P-Q2" not in state["answers"]


def test_deferred_required_answer_blocks_generation_after_other_questions(tmp_path):
    deferred, payload = _run(tmp_path, "--defer", "--expected-revision", "0")
    assert deferred.returncode == 0
    assert payload["current_question"]["id"] == "P-Q2"

    for _ in range(10):
        if payload["status"] == "blocked":
            break
        question_id = payload["current_question"]["id"]
        result, payload = _run(
            tmp_path,
            "--answer",
            ANSWER_BY_ID[question_id],
            "--expected-revision",
            str(payload["revision"]),
        )
        assert result.returncode == 0

    assert payload["status"] == "blocked"
    assert payload["current_question"]["id"] == "P-Q1"
    assert not (tmp_path / "specs/add-due-date-to-task/prd.md").exists()


def test_existing_context_package_is_preserved(tmp_path):
    context = tmp_path / ".speed/features/add-due-date-to-task/context-package.json"
    context.parent.mkdir(parents=True)
    context.write_text('{"existing": true}\n')

    payload = _complete_prd(tmp_path)
    assert payload["status"] == "drafted"
    assert json.loads(context.read_text()) == {"existing": True}


def test_peek_reports_not_started_without_creating_state(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "task-due-dates",
            "--project-root",
            str(tmp_path),
            "--peek",
            "--json",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "not_started"
    assert payload["revision"] is None
    assert payload["sections"] == []
    assert not (tmp_path / ".speed").exists()
    assert not (tmp_path / "specs").exists()


def test_peek_resumes_without_advancing_or_writing(tmp_path):
    _start_prd(tmp_path, "task-due-dates", description=DESCRIPTION)
    state_path = (
        tmp_path / ".speed/features/task-due-dates/authoring-prd.json"
    )
    before = state_path.read_text()

    payload = _peek(tmp_path, "task-due-dates")

    assert payload["status"] == "question"
    assert payload["current_question"]["response_control"]["id"]
    assert state_path.read_text() == before
    assert not (tmp_path / "specs/task-due-dates/prd.md").exists()


def test_feature_title_becomes_document_heading(tmp_path):
    payload = _complete_named_prd(
        tmp_path,
        "task-due-dates",
        description=DESCRIPTION,
        title="Due dates for tasks",
    )

    assert payload["feature_title"] == "Due dates for tasks"
    content = (tmp_path / "specs/task-due-dates/prd.md").read_text()
    assert content.startswith("# PRD: Due dates for tasks")


def test_feature_title_cannot_rename_an_existing_interview(tmp_path):
    _start_prd(
        tmp_path, "task-due-dates", description=DESCRIPTION, title="Due dates for tasks"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "task-due-dates",
            "--project-root",
            str(tmp_path),
            "--feature-title",
            "Something else",
            "--json",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "error"


def test_sections_expose_source_questions_for_every_prd_section(tmp_path):
    payload = _complete_named_prd(tmp_path, "task-due-dates", description=DESCRIPTION)

    titles = [section["title"] for section in payload["sections"]]
    assert titles[0] == "Summary"
    assert "Requirements & Acceptance" in titles
    by_title = {section["title"]: section for section in payload["sections"]}
    assert by_title["Problem & Evidence"]["question_ids"] == ["P-Q1"]
    assert by_title["Requirements & Acceptance"]["question_ids"] == ["P-Q4", "P-Q5"]
    assert by_title["References"]["state"] == "generated"
    content = (tmp_path / "specs/task-due-dates/prd.md").read_text()
    for title in titles:
        assert f"## {title}" in content
    assert "| ID | Story | Priority |" in content
    assert "| ID | Story | Product behavior | Done when |" in content


def test_multiplayer_layout_writes_where_the_dashboard_reads(tmp_path):
    (tmp_path / ".speed" / "shared").mkdir(parents=True)

    _complete_named_prd(tmp_path, "task-due-dates", description=DESCRIPTION)

    assert (
        tmp_path / ".speed/shared/features/task-due-dates/authoring-prd.json"
    ).is_file()
    assert (
        tmp_path / ".speed/shared/features/task-due-dates/draft-prd.json"
    ).is_file()
    assert not (tmp_path / ".speed/features").exists()


def test_list_is_empty_and_writes_nothing_for_a_fresh_project(tmp_path):
    payload = _list(tmp_path, "prd")

    assert payload["status"] == "listed"
    assert payload["sessions"] == []
    assert not (tmp_path / ".speed").exists()
    assert not (tmp_path / "specs").exists()


def test_list_reports_every_interview_most_recent_first(tmp_path):
    _start_prd(tmp_path, "task-due-dates", description=DESCRIPTION, title="Due dates")
    _start_prd(tmp_path, "reopen-task", description=DESCRIPTION, title="Reopen a task")

    payload = _list(tmp_path, "prd")
    names = [entry["feature_name"] for entry in payload["sessions"]]

    assert names == ["reopen-task", "task-due-dates"]
    first = payload["sessions"][0]
    assert first["feature_title"] == "Reopen a task"
    assert first["artifact_type"] == "prd"
    assert first["status"] == "question"
    assert first["revision"] == 0
    assert first["progress"]["total"] > 0
    assert first["artifact_path"] is None
    assert first["draft_available"] is False
    assert first["updated_at"]


def test_list_matches_what_peek_reports_for_the_same_feature(tmp_path):
    """Both surfaces resolve the current suggestion, which sets
    clarifications_asked and so decides how many questions stay active."""
    _start_prd(tmp_path, "task-due-dates", description=DESCRIPTION)
    _start_prd(tmp_path, "reopen-task", description=DESCRIPTION)

    sessions = {
        entry["feature_name"]: entry for entry in _list(tmp_path, "prd")["sessions"]
    }
    entry = sessions["task-due-dates"]
    peeked = _peek(tmp_path, "task-due-dates")

    assert entry["status"] == peeked["status"]
    assert entry["revision"] == peeked["revision"]
    assert entry["progress"] == peeked["progress"]
    assert entry["feature_title"] == peeked["feature_title"]


def test_list_does_not_advance_or_write(tmp_path):
    _start_prd(tmp_path, "task-due-dates", description=DESCRIPTION)
    state_path = tmp_path / ".speed/features/task-due-dates/authoring-prd.json"
    before = state_path.read_text()

    _list(tmp_path, "prd")

    assert state_path.read_text() == before
    assert not (tmp_path / "specs/task-due-dates/prd.md").exists()


def test_list_filters_by_artifact_type(tmp_path):
    _publish_prd(tmp_path)
    _run_design(tmp_path, "--answer", DESIGN_ANSWERS[0])

    prd_only = _list(tmp_path, "prd")["sessions"]
    everything = _list(tmp_path)["sessions"]

    assert {entry["artifact_type"] for entry in prd_only} == {"prd"}
    assert {entry["artifact_type"] for entry in everything} == {"prd", "design"}


def test_list_reports_a_damaged_checkpoint_instead_of_hiding_it(tmp_path):
    _start_prd(tmp_path, "task-due-dates", description=DESCRIPTION)
    state_path = tmp_path / ".speed/features/task-due-dates/authoring-prd.json"
    state_path.write_text("{ not json")

    entry = _list(tmp_path, "prd")["sessions"][0]

    assert entry["feature_name"] == "task-due-dates"
    assert entry["status"] == "error"
    assert entry["revision"] is None
    assert "unreadable" in entry["message"]
    assert state_path.read_text() == "{ not json"


def test_list_reads_the_multiplayer_layout(tmp_path):
    (tmp_path / ".speed" / "shared").mkdir(parents=True)
    _start_prd(tmp_path, "task-due-dates", description=DESCRIPTION)

    payload = _list(tmp_path, "prd")

    assert [entry["feature_name"] for entry in payload["sessions"]] == ["task-due-dates"]
    assert ".speed/shared/features" in payload["message"]
