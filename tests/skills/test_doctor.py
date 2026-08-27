import json

from skills import ABSENT, CONFLICTED, ORPHANED, STALE, UNSUPPORTED
from skills import __main__ as cli
from skills.doctor import diagnose
from skills.sync import sync


def test_doctor_is_healthy_when_all_skills_are_current(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    sync(tmp_project, skills_dir, "0.3.0")

    assert diagnose(tmp_project, skills_dir, "0.3.0") == []


def test_doctor_gives_sync_path_for_absent_skill(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()

    diagnostics = diagnose(tmp_project, skills_dir, "0.3.0")

    assert diagnostics[0].state == ABSENT
    assert diagnostics[0].repair == "Run `workbench skills sync`."


def test_doctor_gives_sync_path_for_stale_skill(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    sync(tmp_project, skills_dir, "0.3.0")

    diagnostics = diagnose(tmp_project, skills_dir, "0.4.0")

    assert diagnostics[0].state == STALE
    assert diagnostics[0].repair == "Run `workbench skills sync`."


def test_doctor_gives_force_path_for_conflicted_skill(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    sync(tmp_project, skills_dir, "0.3.0")
    projected = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    projected.write_text("user-owned edit\n")

    diagnostics = diagnose(tmp_project, skills_dir, "0.3.0")

    assert diagnostics[0].state == CONFLICTED
    assert diagnostics[0].repair.endswith("`workbench skills sync --force`.")
    assert projected.read_text() == "user-owned edit\n"


def test_doctor_gives_removal_path_for_orphaned_skill(
    tmp_catalog, tmp_project, tmp_path
):
    skills_dir = tmp_catalog()
    sync(tmp_project, skills_dir, "0.3.0")
    empty_catalog = tmp_path / "empty-skills"
    empty_catalog.mkdir()

    diagnostics = diagnose(tmp_project, empty_catalog, "0.3.0")

    assert diagnostics[0].state == ORPHANED
    assert "remove the obsolete projection" in diagnostics[0].repair


def test_doctor_gives_surface_path_when_unsupported(tmp_catalog, tmp_path):
    skills_dir = tmp_catalog()
    project = tmp_path / "no-surface"
    project.mkdir()

    diagnostics = diagnose(project, skills_dir, "0.3.0")

    assert diagnostics[0].state == UNSUPPORTED
    assert "supported agent" in diagnostics[0].repair


def test_doctor_cli_prints_healthy_result(tmp_catalog, tmp_project, capsys):
    skills_dir = tmp_catalog()
    sync(tmp_project, skills_dir, "0.3.0")

    rc = cli.main(
        [
            "doctor",
            "--project-root",
            str(tmp_project),
            "--skills-dir",
            str(skills_dir),
            "--catalog-version",
            "0.3.0",
        ]
    )

    assert rc == 0
    output = capsys.readouterr().out
    assert "skills doctor: healthy · 0 issue(s)" in output
    assert "ready to use" in output


def test_doctor_cli_json_reports_issue_and_repair(
    tmp_catalog, tmp_project, capsys
):
    skills_dir = tmp_catalog()

    rc = cli.main(
        [
            "doctor",
            "--project-root",
            str(tmp_project),
            "--skills-dir",
            str(skills_dir),
            "--catalog-version",
            "0.3.0",
            "--json",
        ]
    )

    assert rc == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "issues"
    assert result["diagnostics"][0]["state"] == ABSENT
    assert result["diagnostics"][0]["repair"] == "Run `workbench skills sync`."
