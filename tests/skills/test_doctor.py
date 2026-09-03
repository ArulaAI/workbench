import json
import re

from skills import ABSENT, CONFLICTED, CURRENT, ORPHANED, STALE, UNSUPPORTED
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
    (skills_dir / "example-skill" / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: A test skill\n---\n\nNewer text.\n"
    )

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
    assert diagnostics[0].repair.endswith("--force`.")
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


def test_doctor_states_a_missing_surface_once(tmp_catalog, tmp_path):
    """It is one project-level fact, not one per harness we know about."""
    skills_dir = tmp_catalog()
    project = tmp_path / "no-surface"
    project.mkdir()

    diagnostics = diagnose(project, skills_dir, "0.3.0")

    assert [d.state for d in diagnostics] == [UNSUPPORTED]


def test_doctor_agrees_with_status_on_a_project_with_no_surface(
    tmp_catalog, tmp_path, capsys
):
    """init routes this case to doctor, so doctor must not report failure."""
    skills_dir = tmp_catalog()
    project = tmp_path / "no-surface"
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


def test_doctor_scopes_the_force_repair_to_the_affected_surface(
    tmp_catalog, tmp_project
):
    skills_dir = tmp_catalog()
    sync(tmp_project, skills_dir, "0.3.0")
    (tmp_project / ".claude" / "skills" / "example-skill" / "SKILL.md").write_text(
        "user-owned edit\n"
    )

    diagnostics = diagnose(tmp_project, skills_dir, "0.3.0")

    assert diagnostics[0].state == CONFLICTED
    assert diagnostics[0].repair.endswith(
        "`workbench skills sync --surface claude_code --force`."
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
    sync(project, skills_dir, "0.3.0")

    edited = {}
    for surface_root in (".claude/skills", ".agents/skills"):
        path = project / surface_root / "example-skill" / "SKILL.md"
        path.write_text(f"edit in {surface_root}\n")
        edited[surface_root] = path

    diagnostics = diagnose(project, skills_dir, "0.3.0")
    claude = next(d for d in diagnostics if d.surface == "claude_code")
    command = re.search(r"`workbench skills (sync[^`]*)`", claude.repair).group(1)

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


def test_doctor_points_a_missing_surface_at_workbench_init(tmp_catalog, tmp_path):
    """Workbench creates harness surfaces itself; the advice must say so."""
    skills_dir = tmp_catalog()
    project = tmp_path / "no-surface"
    project.mkdir()

    diagnostics = diagnose(project, skills_dir, "0.3.0")

    assert "workbench init --harness" in diagnostics[0].repair
    assert "Open the project in a supported agent" not in diagnostics[0].repair


# ── CLI exit codes and error reporting ───────────────────────────


def test_cli_maps_a_missing_argument_to_the_error_code(capsys):
    """argparse exits 2, which `sync` already spends on 'conflicts remain'."""
    assert cli.main(["sync"]) == 3


def test_cli_maps_an_unknown_subcommand_to_the_error_code(capsys):
    assert cli.main(["resync"]) == 3


def test_cli_help_exits_zero(capsys):
    assert cli.main(["--help"]) == 0
    assert "sync" in capsys.readouterr().out


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
    sync(tmp_project, skills_dir, "0.3.0")
    (tmp_project / ".speed" / "skills" / "manifest.json").unlink()

    diagnostics = diagnose(tmp_project, skills_dir, "0.3.0")

    assert len(diagnostics) == 1
    assert diagnostics[0].skill == "*"
    assert "manifest.json` is missing" in diagnostics[0].diagnosis
    assert "Restore" in diagnostics[0].repair
    # The per-skill "back up local edits" advice must not appear at all.
    assert not any("back up" in item.repair for item in diagnostics)


def test_every_state_has_a_diagnostic_defined():
    """A gap here would reach a user as generic prose instead of a real finding.

    doctor also enforces this at import; the test states the same rule so a
    dropped entry fails as a named assertion rather than a collection error.
    """
    from skills import STATES
    from skills.doctor import _GUIDANCE

    assert (STATES - {CURRENT}) - set(_GUIDANCE) == set()


def test_an_impossible_state_is_reported_as_an_internal_error(monkeypatch):
    """Generic advice would hide the fact that the classifier invented a state."""
    from skills import doctor as doctor_module
    from skills.sync import SkillState

    monkeypatch.setattr(
        doctor_module,
        "status",
        lambda *a, **k: [SkillState("claude_code", "example-skill", "banana")],
    )
    monkeypatch.setattr(doctor_module, "manifest_state", lambda _: "present")

    diagnostics = diagnose("/nowhere", "/nowhere", "0.3.0")

    assert len(diagnostics) == 1
    assert "Internal error" in diagnostics[0].diagnosis
    assert "banana" in diagnostics[0].diagnosis
    assert "Workbench bug" in diagnostics[0].diagnosis
    assert "Report this" in diagnostics[0].repair
