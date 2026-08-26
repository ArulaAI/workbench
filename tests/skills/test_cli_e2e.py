import os
import subprocess
import sys
from pathlib import Path

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


def test_end_to_end_projects_real_workbench_draft(tmp_path):
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    r = _skills(project, "sync")
    assert r.returncode == 0, r.stderr
    projected = project / ".claude" / "skills" / "workbench-draft" / "SKILL.md"
    assert projected.exists()
    text = projected.read_text()
    assert "x-speed-managed: true" in text
    s = _skills(project, "status")
    assert s.returncode == 0, s.stderr
    assert "current" in s.stdout
