import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable  # the interpreter running the tests (works in a worktree too)

_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "workbench-test",
    "GIT_AUTHOR_EMAIL": "workbench@test.invalid",
    "GIT_COMMITTER_NAME": "workbench-test",
    "GIT_COMMITTER_EMAIL": "workbench@test.invalid",
}


def _git(project, *args):
    return subprocess.run(
        ["git", *args],
        cwd=project,
        capture_output=True,
        text=True,
        env=dict(os.environ, **_GIT_ENV),
    )


def _skills(project, *args):
    env = dict(os.environ, PYTHONPATH=str(REPO / "lib"))
    return subprocess.run(
        [
            PY,
            "-m",
            "skills",
            *args,
            "--project-root",
            str(project),
            "--skills-dir",
            str(REPO / "skills"),
            "--catalog-version",
            "test",
        ],
        capture_output=True,
        text=True,
        env=env,
    )


# The entrypoint preflights its interpreter for the packages context extraction
# needs. None of them belong to the skill system, but the check runs before any
# skill code, so an interpreter without them turns every lifecycle test into a
# failure that names `sklearn`. Report that as a skip carrying the fix, rather
# than as a fault in the code under test.
_PREFLIGHT_MODULES = ("tree_sitter", "sklearn", "networkx")


def _missing_preflight_modules():
    missing = []
    for name in _PREFLIGHT_MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    return missing


def _workbench(project, *args):
    missing = _missing_preflight_modules()
    if missing:
        pytest.skip(
            f"{PY} cannot import {', '.join(missing)}, which the entrypoint "
            "preflight requires. Build a venv from requirements.txt and run "
            "PYTHONPATH=lib .venv/bin/python3 -m pytest tests/skills/"
        )
    env = dict(
        os.environ,
        SPEED_PROJECT_ROOT=str(project),
        SPEED_PYTHON=PY,
        **_GIT_ENV,
    )
    return subprocess.run(
        [str(REPO / "workbench"), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=project,
    )


def test_end_to_end_projects_and_verifies_workbench_health(tmp_path):
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    r = _skills(project, "sync")
    assert r.returncode == 0, r.stderr
    projected = project / ".claude" / "skills" / "workbench-health" / "SKILL.md"
    assert projected.exists()
    text = projected.read_text()
    assert "x-workbench-managed: true" in text
    s = _skills(project, "status")
    assert s.returncode == 0, s.stderr
    assert "current" in s.stdout

    health = subprocess.run(
        [
            PY,
            str(project / ".claude" / "skills" / "workbench-health" / "scripts" / "health.py"),
            "--project-root",
            str(project),
            "--harness",
            "claude",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )
    assert health.returncode == 0, health.stderr
    assert "status: healthy" in health.stdout
    assert "ready to use" in health.stdout

    doctor = _skills(project, "doctor")
    assert doctor.returncode == 0, doctor.stderr
    assert "skills doctor: healthy" in doctor.stdout

    projected.write_text(text + "\nlocal edit\n")
    doctor = _skills(project, "doctor")
    assert doctor.returncode == 1
    assert "[conflicted]" in doctor.stdout
    # Scoped to the conflicting harness: an unscoped --force would also
    # overwrite conflicts on harnesses this finding says nothing about.
    assert "workbench skills sync --harness claude --force" in doctor.stdout


def test_workbench_doctor_shell_route_forwards_json(tmp_path):
    project = tmp_path / "shell-project"
    (project / ".claude").mkdir(parents=True)
    synced = _workbench(project, "skills", "sync")
    assert synced.returncode == 0, synced.stderr

    doctor = _workbench(project, "skills", "doctor", "--json")

    assert doctor.returncode == 0, doctor.stderr
    result = json.loads(doctor.stdout)
    assert result["status"] == "healthy"
    assert result["diagnostics"] == []


def test_workbench_health_is_not_a_command(tmp_path):
    project = tmp_path / "no-health-command"
    project.mkdir()

    result = _workbench(project, "health")

    assert result.returncode == 1
    assert "Unknown command: health" in result.stderr


@pytest.mark.parametrize(
    ("harness", "skills_root"),
    [
        ("claude", ".claude/skills"),
        ("codex", ".agents/skills"),
        ("copilot", ".github/skills"),
    ],
)
def test_workbench_init_creates_only_selected_harness(
    tmp_path, harness, skills_root
):
    project = tmp_path / harness
    project.mkdir()

    initialized = _workbench(project, "init", "--harness", harness)

    assert initialized.returncode == 0, initialized.stderr
    selected = project / skills_root / "workbench-health" / "SKILL.md"
    assert selected.is_file()
    assert sorted(path.name for path in selected.parent.parent.iterdir()) == [
        "workbench-health"
    ]
    health = subprocess.run(
        [
            PY,
            str(selected.parent / "scripts" / "health.py"),
            "--project-root",
            str(project),
            "--harness",
            harness,
            "--json",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )
    assert health.returncode == 0, health.stderr
    health_result = json.loads(health.stdout)
    assert health_result["status"] == "healthy"
    assert health_result["skills"] == ["workbench-health"]
    assert f"Skills projected for {harness}" in initialized.stdout
    assert f'harnesses = ["{harness}"]' in (project / "speed.toml").read_text()
    assert _git(project, "log", "--oneline").returncode != 0
    assert "speed.toml" in _git(project, "status", "--short").stdout
    roots = {
        ".claude/skills": project / ".claude" / "skills",
        ".agents/skills": project / ".agents" / "skills",
        ".github/skills": project / ".github" / "skills",
    }
    assert all(
        not root.exists()
        for name, root in roots.items()
        if name != skills_root
    )


def test_workbench_init_rejects_unknown_harness_before_writing(tmp_path):
    project = tmp_path / "invalid"
    project.mkdir()

    initialized = _workbench(project, "init", "--harness", "cursor")

    assert initialized.returncode == 3
    assert "expected: claude, codex, copilot" in initialized.stderr
    assert not (project / ".git").exists()


def test_workbench_init_requires_a_resolvable_harness_before_writing(tmp_path):
    project = tmp_path / "no-policy"
    project.mkdir()

    initialized = _workbench(project, "init")

    assert initialized.returncode == 3
    assert "no skill harness policy" in initialized.stderr
    assert list(project.iterdir()) == []


def test_repeated_init_uses_persisted_policy_not_new_marker_detection(tmp_path):
    project = tmp_path / "repeat"
    project.mkdir()
    first = _workbench(project, "init", "--harness", "codex")
    assert first.returncode == 0, first.stderr
    (project / ".claude").mkdir()

    repeated = _workbench(project, "init")

    assert repeated.returncode == 0, repeated.stderr
    assert (project / ".agents/skills/workbench-health/SKILL.md").is_file()
    assert not (project / ".claude/skills").exists()


def test_provider_does_not_override_persisted_skill_harness(tmp_path):
    project = tmp_path / "independent"
    project.mkdir()
    initialized = _workbench(project, "init", "--harness", "codex")
    assert initialized.returncode == 0, initialized.stderr
    config = project / "speed.toml"
    config.write_text(config.read_text().replace(
        '# provider = "claude-code"', 'provider = "claude-code"'
    ))

    repeated = _workbench(project, "init")

    assert repeated.returncode == 0, repeated.stderr
    assert (project / ".agents/skills/workbench-health/SKILL.md").is_file()


def test_init_commit_excludes_unrelated_existing_work(tmp_path):
    project = tmp_path / "commit-scope"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    unrelated = project / "unrelated.txt"
    unrelated.write_text("do not stage me\n")

    initialized = _workbench(project, "init", "--harness", "claude", "--commit")

    assert initialized.returncode == 0, initialized.stderr
    assert "workbench init: project scaffold" in _git(
        project, "log", "-1", "--pretty=%s"
    ).stdout
    assert "unrelated.txt" in _git(project, "status", "--short").stdout
    assert "unrelated.txt" not in _git(project, "show", "--name-only", "--pretty=").stdout


def test_init_commit_migrates_an_ignore_all_skills_policy(tmp_path):
    project = tmp_path / "old-ignore"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    (project / ".gitignore").write_text(
        "# SPEED runtime state\n.speed/logs/\n.speed/skills/\n"
    )
    _git(project, "add", ".gitignore")
    _git(project, "commit", "-qm", "old project")

    initialized = _workbench(project, "init", "--harness", "claude", "--commit")

    assert initialized.returncode == 0, initialized.stderr
    tracked = _git(project, "ls-files").stdout.splitlines()
    assert ".speed/skills/manifest.json" in tracked
    assert ".speed/skills/events.jsonl" not in tracked
    ignored = _git(
        project, "check-ignore", "-q", ".speed/skills/events.jsonl"
    )
    assert ignored.returncode == 0


def test_malformed_speed_toml_is_reported_once(tmp_path):
    project = tmp_path / "bad-config"
    project.mkdir()
    (project / "speed.toml").write_text("[skills\nharnesses = [\"claude\"]\n")

    result = _workbench(project, "skills", "status")

    assert result.returncode == 3
    messages = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(messages) == 1, result.stderr
    assert messages[0].startswith("Error: could not parse ")
    assert "Warning: Warning:" not in result.stderr
    assert "ValueError:" not in result.stderr


def test_a_leading_global_flag_is_not_taken_as_the_command(tmp_path):
    """`workbench --json skills status` used to die with "Unknown command".

    main() read $1 as the command before the global-flag loop ran, so every
    global flag in the leading position became a command name. The trailing
    form worked, which is why it went unnoticed.
    """
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    _workbench(project, "skills", "sync")

    leading = _workbench(project, "--json", "skills", "status")

    assert "Unknown command" not in leading.stderr
    rows = json.loads(leading.stdout)
    assert [row["state"] for row in rows] == ["current"]

    trailing = _workbench(project, "skills", "status", "--json")
    assert json.loads(trailing.stdout) == rows
