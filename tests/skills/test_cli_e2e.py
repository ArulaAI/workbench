import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable  # the interpreter running the tests (works in a worktree too)


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


def _workbench(project, *args):
    env = dict(
        os.environ,
        SPEED_PROJECT_ROOT=str(project),
        SPEED_PYTHON=PY,
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
            "--surface",
            "claude_code",
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
    assert "workbench skills sync --force" in doctor.stdout


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
            "--surface",
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
