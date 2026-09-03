import hashlib
import json
import os
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
ANSWER_BY_ID = {f"P-Q{index}": answer for index, answer in enumerate(ANSWERS, start=1)}


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
    assert next_input["input_type"] == "form"
    assert [field["id"] for field in next_input["fields"]] == [
        "feature_title",
        "feature_slug",
        "feature_description",
    ]
    slug_field = next_input["fields"][1]
    assert slug_field["derived_from"] == "feature_title"
    assert all(field["required"] for field in next_input["fields"])
    assert next_input["allow_existing"] is False
    assert "archive-a-task" not in result.stdout
    assert "reopen-task" not in result.stdout


def test_prd_description_generates_immediate_draft_and_skips_problem_question(tmp_path):
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
    assert payload["current_question"]["id"] == "P-Q5"
    assert payload["draft_available"] is True
    assert payload["artifact_path"] == "specs/add-due-date-to-task/prd.md"
    assert payload["coverage"]["P-Q1"]["confidence_label"] == "evidence_backed"
    assert payload["coverage"]["P-Q1"]["confidence"] == 0.95
    assert description in (tmp_path / payload["artifact_path"]).read_text()

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
    assert payload["current_question"]["id"] == "P-Q5"
    assert payload["current_question"]["suggestion"]["answer"] is None
    assert description in (tmp_path / payload["artifact_path"]).read_text()
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
        "defer",
    ]
    assert payload["resume_step"] == {
        "question_id": "P-Q5",
        "control_id": "suggestion_action",
        "revision": 0,
    }

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
    assert edit_control["initial_value"] == ""
    assert payload["resume_step"]["control_id"] == "edited_suggestion"

    resumed, resumed_payload = _run(tmp_path)
    assert resumed.returncode == 0, resumed.stderr
    assert resumed_payload["revision"] == 1
    assert resumed_payload["current_question"]["response_control"] == edit_control

    edited_answer = ANSWERS[4]
    answered, payload = _run(
        tmp_path,
        "--answer",
        edited_answer,
        "--expected-revision",
        "1",
    )
    assert answered.returncode == 0, answered.stderr
    assert payload["status"] == "drafted"
    assert payload["current_question"] is None
    state = json.loads(
        (tmp_path / ".speed/features/add-due-date-to-task/authoring-prd.json").read_text()
    )
    assert state["edit_requests"]["P-Q5"]["status"] == "answered"
    assert state["edit_requests"]["P-Q5"]["answer"] == edited_answer
    assert state["answers"]["P-Q5"]["decision"] == "edited"


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
    assert payload["current_question"]["id"] == "P-Q5"
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


def test_second_failed_self_review_records_open_questions_and_stops(tmp_path):
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
    assert payload["status"] == "drafted_with_open_questions"
    assert payload["self_review"]["pass_count"] == 2
    assert payload["self_review"]["status"] == "open_questions"
    content = (tmp_path / payload["artifact_path"]).read_text()
    assert "## Self-Review Open Questions" in content
    assert "**P-Q1:**" in content

    resumed, same = _run(tmp_path)
    assert resumed.returncode == 0
    assert same["status"] == "drafted_with_open_questions"
    assert same["self_review"]["pass_count"] == 2


def test_design_intake_requests_prd_and_lists_only_valid_guided_prds(tmp_path):
    _complete_prd(tmp_path)
    (tmp_path / ".speed/features/unrelated-feature").mkdir(parents=True)
    (tmp_path / "specs/tech").mkdir(parents=True)
    (tmp_path / "specs/tech/unrelated-feature.md").write_text("# RFC\n")

    result, payload = _run_intake(tmp_path, "design")

    assert result.returncode == 0
    assert payload["status"] == "needs_input"
    next_input = payload["next_input"]
    assert next_input["id"] == "source_prd"
    assert next_input["prompt"] == "Which PRD should ground this Design draft?"
    assert [option["feature_name"] for option in next_input["options"]] == [
        "add-due-date-to-task"
    ]
    assert next_input["fallback"]["id"] == "feature_name"
    assert "unrelated-feature" not in result.stdout


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
    assert payload["question_bank_version"] == "prd-v2"
    assert payload["current_question"]["id"] == "P-Q5"
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
    assert resumed_payload["current_question"]["id"] == "P-Q5"
    assert resumed_payload["implementation"] == cli_payload["implementation"]

    completed_payload = resumed_payload
    for _ in range(5):
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
    prd_payload = _complete_prd(tmp_path)
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


def test_design_blocks_on_changed_prd_without_mutating_checkpoint(tmp_path):
    _complete_prd(tmp_path)
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
    assert payload["current_question"]["id"] == "P-Q5"
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
    assert payload["current_question"]["id"] == "P-Q5"


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
    assert payload["current_question"]["id"] == "P-Q5"
    migrated = json.loads(state_path.read_text())
    assert migrated["schema_version"] == 2
    assert migrated["question_bank_version"] == "prd-v2"
    assert migrated["answers"]["P-Q1"]["answer"] == ANSWERS[0]
    assert migrated["answers"]["P-Q1"]["decision"] == "edited"
    assert "P-Q5" in migrated["suggestions"]


def test_authentication_asks_method_then_existing_user_rollout_then_controls(tmp_path):
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
    assert payload["draft_available"] is True
    assert payload["progress"]["total"] == 3
    assert set(payload["coverage"]) == {f"P-Q{index}" for index in range(1, 9)}
    initial_content = (tmp_path / payload["artifact_path"]).read_text()
    assert "**Unresolved:**" in initial_content

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
    assert payload["current_question"]["id"] == "P-Q7"
    assert "rolling out authentication to existing users" in payload["current_question"]["prompt"]
    assert "set up authentication" in payload["current_question"]["prompt"]
    assert "existing account and data" in payload["current_question"]["prompt"]
    assert payload["current_question"]["suggestion"]["answer"] is None
    assert "backward compatibility" in payload["current_question"]["purpose"]

    rollout_answer = (
        "Existing users are prompted to claim their account with Google sign-in "
        "on their next visit; their existing tasks remain attached to that account."
    )
    rolled_out = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "auth-system",
            "--project-root",
            str(tmp_path),
            "--answer",
            rollout_answer,
            "--expected-revision",
            str(payload["revision"]),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(rolled_out.stdout)
    assert rolled_out.returncode == 0, rolled_out.stderr
    assert payload["current_question"]["id"] == "P-Q8"

    controls_answer = (
        "Authentication failures must not expose another user's tasks. Product owns "
        "the privacy review and rollout; existing tasks require an ownership decision."
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "auth-system",
            "--project-root",
            str(tmp_path),
            "--answer",
            controls_answer,
            "--expected-revision",
            str(payload["revision"]),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    assert payload["status"] == "drafted"
    final_content = (tmp_path / payload["artifact_path"]).read_text()
    assert method_answer in final_content
    assert rollout_answer in final_content
    assert controls_answer in final_content


def test_local_feature_omits_immaterial_scope_and_risk_questions(tmp_path):
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
    assert payload["progress"]["total"] == 1
    assert payload["current_question"]["id"] == "P-Q5"
    assert payload["draft_available"] is True
    assert payload["coverage"]["P-Q7"]["confidence_label"] == "not_material"
    assert payload["coverage"]["P-Q8"]["confidence_label"] == "not_material"


def test_draft_review_updates_stable_coverage_and_regenerates(tmp_path):
    description = (
        "Let a task user rename an existing task inline so they can correct its title."
    )
    started = subprocess.run(
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
    payload = json.loads(started.stdout)
    acceptance = (
        "Given an existing task, when its owner saves a valid changed title, then "
        "the list shows the new title without changing other task fields."
    )
    answered = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "prd",
            "rename-task-inline",
            "--project-root",
            str(tmp_path),
            "--answer",
            acceptance,
            "--expected-revision",
            str(payload["revision"]),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(answered.stdout)
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
    assert payload["progress"]["total"] <= 3

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

    for _ in range(5):
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
    assert (tmp_path / "specs/add-due-date-to-task/prd.md").exists()


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
    artifact_before = (tmp_path / "specs/task-due-dates/prd.md").read_text()

    payload = _peek(tmp_path, "task-due-dates")

    assert payload["status"] == "question"
    assert payload["current_question"]["response_control"]["id"]
    assert state_path.read_text() == before
    assert (tmp_path / "specs/task-due-dates/prd.md").read_text() == artifact_before


def test_feature_title_becomes_document_heading(tmp_path):
    payload = _start_prd(
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
    payload = _start_prd(tmp_path, "task-due-dates", description=DESCRIPTION)

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


def test_multiplayer_layout_writes_where_the_dashboard_reads(tmp_path):
    (tmp_path / ".speed" / "shared").mkdir(parents=True)

    _start_prd(tmp_path, "task-due-dates", description=DESCRIPTION)

    assert (
        tmp_path / ".speed/shared/features/task-due-dates/authoring-prd.json"
    ).is_file()
    assert (
        tmp_path / ".speed/shared/features/task-due-dates/draft-prd.json"
    ).is_file()
    assert not (tmp_path / ".speed/features").exists()
