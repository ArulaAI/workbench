import json
import re

import pytest

from skills import __main__ as cli
from skills.doctor import ERROR, NOTE, WARNING, diagnose
from skills.inspect import inspect
from skills.models import (
    HARNESS_UNSUPPORTED,
    MANIFEST_LOST,
    ORPHANED_PROJECTION,
    PROJECTED_FILE_MODIFIED,
    PROJECTION_MISSING,
    PROJECTION_OUTDATED,
    PROJECTION_SYMLINK,
    Finding,
    Inspection,
    SkillInspection,
    SkillState,
)


def _diagnose(project, skills_dir, version="0.3.0", **kw):
    """Diagnose from a read-only inspection, which is all doctor consumes."""
    return diagnose(inspect(project, skills_dir, version, **kw))


def _sync(project, skills_dir, version="0.3.0", **kw):
    from skills.sync import sync

    return sync(project, skills_dir, version, **kw)


def test_doctor_is_healthy_when_all_skills_are_current(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)

    assert _diagnose(tmp_project, skills_dir) == []


def test_doctor_gives_sync_path_for_absent_skill(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()

    diagnostics = _diagnose(tmp_project, skills_dir)

    assert diagnostics[0].state == SkillState.ABSENT
    assert diagnostics[0].code == PROJECTION_MISSING
    assert diagnostics[0].severity == WARNING
    assert diagnostics[0].destructive is False
    assert diagnostics[0].repair_command == "workbench skills sync"


def test_doctor_gives_sync_path_for_stale_skill(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    (skills_dir / "example-skill" / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: A test skill\n---\n\nNewer text.\n"
    )

    diagnostics = _diagnose(tmp_project, skills_dir, "0.4.0")

    assert diagnostics[0].state == SkillState.STALE
    assert diagnostics[0].code == PROJECTION_OUTDATED
    assert diagnostics[0].path == "SKILL.md"
    assert diagnostics[0].repair_command == "workbench skills sync"


def test_doctor_gives_force_path_for_conflicted_skill(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    projected = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    projected.write_text("user-owned edit\n")

    diagnostics = _diagnose(tmp_project, skills_dir)

    assert diagnostics[0].state == SkillState.CONFLICTED
    assert diagnostics[0].code == PROJECTED_FILE_MODIFIED
    assert diagnostics[0].severity == ERROR
    assert diagnostics[0].destructive is True
    assert diagnostics[0].repair_command.endswith("--force")
    assert projected.read_text() == "user-owned edit\n"


# ── The evidence behind a finding, not just its label ────────────


def test_a_modified_file_is_reported_with_both_hashes(tmp_catalog, tmp_project):
    """The comparison that produced the state has to reach the user.

    Reporting only `conflicted` made every cause look alike and left the user
    to work out which file changed and how.
    """
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    projected = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    projected.write_text("user-owned edit\n")

    diagnostic = _diagnose(tmp_project, skills_dir)[0]

    assert diagnostic.path == "SKILL.md"
    assert diagnostic.expected.startswith("sha256:")
    assert diagnostic.actual.startswith("sha256:")
    assert diagnostic.expected != diagnostic.actual


def test_one_conflicted_skill_can_report_several_causes(tmp_catalog, tmp_project):
    """`conflicted` covers six distinct problems; a single prose line hid that."""
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    projection = tmp_project / ".claude" / "skills" / "example-skill"
    (projection / "SKILL.md").write_text("user-owned edit\n")
    (projection / "references" / "notes.md").unlink()
    (projection / "extra.md").write_text("not ours\n")

    codes = {d.code for d in _diagnose(tmp_project, skills_dir)}

    assert codes == {
        PROJECTED_FILE_MODIFIED,
        "projected_file_missing",
        "projected_file_unexpected",
    }


def test_a_symlink_is_a_different_finding_than_an_edit(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    projected = tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md"
    projected.unlink()
    projected.symlink_to("/etc/hosts")

    diagnostic = _diagnose(tmp_project, skills_dir)[0]

    assert diagnostic.code == PROJECTION_SYMLINK
    assert diagnostic.state == SkillState.CONFLICTED
    assert diagnostic.destructive is True


def test_a_destructive_repair_is_flagged_as_destructive(tmp_catalog, tmp_project):
    """A caller has to be able to tell "run this" from "confirm this first"."""
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    (tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md").write_text("x\n")

    # A second package in the same catalog is absent, so one inspection holds
    # both a destructive and a non-destructive finding.
    diagnostics = _diagnose(tmp_project, tmp_catalog("second-skill"))
    conflicted = next(d for d in diagnostics if d.skill == "example-skill")
    absent = next(d for d in diagnostics if d.skill == "second-skill")

    assert conflicted.destructive is True
    assert "--force" in conflicted.repair_command
    assert absent.destructive is False
    assert "--force" not in absent.repair_command


def test_doctor_gives_removal_path_for_orphaned_skill(
    tmp_catalog, tmp_project, tmp_path
):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    empty_catalog = tmp_path / "empty-skills"
    empty_catalog.mkdir()

    diagnostics = _diagnose(tmp_project, empty_catalog)

    assert diagnostics[0].state == SkillState.ORPHANED
    assert diagnostics[0].code == ORPHANED_PROJECTION
    assert diagnostics[0].repair_command == "workbench skills sync"


def test_doctor_gives_harness_path_when_unsupported(tmp_catalog, tmp_path):
    skills_dir = tmp_catalog()
    project = tmp_path / "no-harness"
    project.mkdir()

    diagnostics = _diagnose(project, skills_dir)

    assert diagnostics[0].state == SkillState.UNSUPPORTED
    assert diagnostics[0].code == HARNESS_UNSUPPORTED
    assert diagnostics[0].severity == NOTE


def test_doctor_cli_prints_healthy_result(tmp_catalog, tmp_project, capsys):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)

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


def test_doctor_cli_json_carries_the_full_diagnostic(tmp_catalog, tmp_project, capsys):
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
    first = result["diagnostics"][0]
    assert first["state"] == "absent"
    assert first["code"] == PROJECTION_MISSING
    assert first["severity"] == WARNING
    assert first["harness"] == "claude"
    assert first["destructive"] is False
    assert first["repair_command"] == "workbench skills sync"


def test_doctor_cli_text_shows_the_hash_comparison(tmp_catalog, tmp_project, capsys):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    (tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md").write_text("x\n")

    cli.main(
        [
            "doctor",
            "--project-root", str(tmp_project),
            "--skills-dir", str(skills_dir),
            "--catalog-version", "0.3.0",
        ]
    )

    output = capsys.readouterr().out
    assert "projected_file_modified" in output
    assert "path: SKILL.md" in output
    assert "expected: sha256:" in output
    assert "actual:   sha256:" in output
    assert "(destructive)" in output


def test_doctor_states_a_missing_harness_once(tmp_catalog, tmp_path):
    """It is one project-level fact, not one per harness we know about."""
    skills_dir = tmp_catalog()
    project = tmp_path / "no-harness"
    project.mkdir()

    diagnostics = _diagnose(project, skills_dir)

    assert [d.state for d in diagnostics] == [SkillState.UNSUPPORTED]


def test_doctor_agrees_with_status_on_a_project_with_no_harness(
    tmp_catalog, tmp_path, capsys
):
    """init routes this case to doctor, so doctor must not report failure."""
    skills_dir = tmp_catalog()
    project = tmp_path / "no-harness"
    project.mkdir()
    argv = [
        "--project-root", str(project),
        "--skills-dir", str(skills_dir),
        "--catalog-version", "0.3.0",
        "--json",
    ]

    assert cli.main(["status", *argv]) == 0
    capsys.readouterr()
    assert cli.main(["doctor", *argv]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "unsupported"


# ── Repair guidance stays inside the finding it repairs ──────────


def test_doctor_scopes_the_force_repair_to_the_affected_harness(
    tmp_catalog, tmp_project
):
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    (tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md").write_text(
        "user-owned edit\n"
    )

    diagnostics = _diagnose(tmp_project, skills_dir)

    assert diagnostics[0].state == SkillState.CONFLICTED
    assert diagnostics[0].repair_command == (
        "workbench skills sync --harness claude --force"
    )


def test_doctor_force_repair_leaves_an_unrelated_conflict_alone(
    tmp_catalog, tmp_path
):
    """Unscoped `--force` overwrote every conflict on every harness. Running the
    recommended command must repair only the row it was recommended for."""
    skills_dir = tmp_catalog()
    project = tmp_path / "two-harnesses"
    (project / ".claude").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)
    _sync(project, skills_dir)

    edited = {}
    for skills_root in (".claude/skills", ".agents/skills"):
        path = project / skills_root / "example-skill" / "SKILL.md"
        path.write_text(f"edit in {skills_root}\n")
        edited[skills_root] = path

    diagnostics = _diagnose(project, skills_dir)
    claude = next(d for d in diagnostics if d.harness == "claude")
    command = re.match(r"workbench skills (sync.*)$", claude.repair_command).group(1)

    rc = cli.main(
        [
            *command.split(),
            "--project-root", str(project),
            "--skills-dir", str(skills_dir),
            "--catalog-version", "0.3.0",
        ]
    )

    assert rc == 0
    assert "edit in .claude/skills" not in edited[".claude/skills"].read_text()
    assert edited[".agents/skills"].read_text() == "edit in .agents/skills\n"


def test_doctor_points_a_missing_harness_at_workbench_init(tmp_catalog, tmp_path):
    """Workbench creates harness roots itself; the advice must say so."""
    skills_dir = tmp_catalog()
    project = tmp_path / "no-harness"
    project.mkdir()

    diagnostics = _diagnose(project, skills_dir)

    assert "workbench init --harness" in diagnostics[0].repair_command
    assert "Open the project in a supported agent" not in diagnostics[0].message


# ── CLI exit codes and error reporting ───────────────────────────


def test_cli_maps_a_missing_argument_to_the_error_code(capsys):
    """argparse exits 2, which `sync` already spends on 'conflicts remain'."""
    assert cli.main(["sync"]) == 3


def test_cli_maps_an_unknown_subcommand_to_the_error_code(capsys):
    assert cli.main(["resync"]) == 3


def test_cli_help_exits_zero(capsys):
    assert cli.main(["--help"]) == 0
    assert "sync" in capsys.readouterr().out


def test_cli_lists_the_canonical_harness_registry(capsys):
    """The Bash commands query this instead of restating the harness list."""
    assert cli.main(["harnesses", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"id": "claude", "skills_root": ".claude/skills", "marker": ".claude"},
        {"id": "codex", "skills_root": ".agents/skills", "marker": ".agents"},
        {
            "id": "copilot",
            "skills_root": ".github/skills",
            "marker": ".github/skills",
        },
    ]


def _broken_catalog_argv(tmp_project, tmp_path, *extra):
    return [
        "status",
        "--project-root", str(tmp_project),
        "--skills-dir", str(tmp_path / "no-such-catalog"),
        "--catalog-version", "0.3.0",
        *extra,
    ]


def test_cli_reports_an_error_as_json_when_json_was_requested(
    tmp_project, tmp_path, capsys
):
    rc = cli.main(_broken_catalog_argv(tmp_project, tmp_path, "--json"))

    assert rc == 3
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "error"
    assert payload["error"]["type"] == "ValueError"
    assert "no-such-catalog" in payload["error"]["message"]
    assert "no-such-catalog" in captured.err


def test_cli_text_error_names_the_exception_type(tmp_project, tmp_path, capsys):
    rc = cli.main(_broken_catalog_argv(tmp_project, tmp_path))

    assert rc == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ValueError" in captured.err
    assert "no-such-catalog" in captured.err


def test_cli_debug_env_var_prints_a_traceback(
    tmp_project, tmp_path, capsys, monkeypatch
):
    monkeypatch.setenv("WORKBENCH_DEBUG", "1")

    rc = cli.main(_broken_catalog_argv(tmp_project, tmp_path))

    assert rc == 3
    assert "Traceback (most recent call last)" in capsys.readouterr().err


def test_cli_without_debug_prints_no_traceback(tmp_project, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("WORKBENCH_DEBUG", raising=False)

    cli.main(_broken_catalog_argv(tmp_project, tmp_path))

    assert "Traceback" not in capsys.readouterr().err


def test_doctor_names_a_lost_manifest_instead_of_blaming_local_edits(
    tmp_catalog, tmp_project
):
    """A clone that carries the projections without the manifest has no edits.

    Every skill classifies as conflicted in that situation, so reporting them
    one by one tells the user to back up changes they never made.
    """
    skills_dir = tmp_catalog()
    _sync(tmp_project, skills_dir)
    (tmp_project / ".speed" / "skills" / "manifest.json").unlink()

    diagnostics = _diagnose(tmp_project, skills_dir)

    assert len(diagnostics) == 1
    assert diagnostics[0].skill == "*"
    assert diagnostics[0].code == MANIFEST_LOST
    assert "manifest.json' is missing" in diagnostics[0].message
    assert "Restore" in diagnostics[0].repair_command
    # The per-skill "back up local edits" advice must not appear at all.
    assert not any("back up" in item.repair_command for item in diagnostics)


def test_every_emitted_code_has_a_definition():
    """A gap here would reach a user as a bare code instead of an explanation.

    doctor enforces this at import; the test states the same rule so a dropped
    entry fails as a named assertion rather than a collection error.
    """
    from skills.doctor import _CATALOG, _EMITTED

    assert _EMITTED - set(_CATALOG) == set()


def _one_row_inspection(state, findings):
    return Inspection(
        project_root="/nowhere",
        catalog_version="0.3.0",
        manifest={},
        manifest_state="present",
        harnesses=[object()],
        skills=[
            SkillInspection(
                harness="claude",
                skill="example-skill",
                state=state,
                findings=findings,
            )
        ],
    )


def test_an_unknown_code_is_reported_as_an_internal_error():
    """A code with no definition is a Workbench bug, not advice for the user."""
    inspection = _one_row_inspection(SkillState.CONFLICTED, [Finding("banana")])

    diagnostics = diagnose(inspection)

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "banana"
    assert "Internal error" in diagnostics[0].message
    assert "Workbench bug" in diagnostics[0].message
    assert "Report this" in diagnostics[0].repair_command


def test_a_non_current_row_without_evidence_is_an_internal_error():
    """Inspection must always say why. Silence would degrade to generic prose."""
    diagnostics = diagnose(_one_row_inspection(SkillState.STALE, []))

    assert len(diagnostics) == 1
    assert "Internal error" in diagnostics[0].message
    assert "stale" in diagnostics[0].message
