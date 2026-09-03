import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from skills import PATHS

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


def _speed(project, *args):
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
        [str(REPO / "speed"), *args],
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
        "workbench-draft",
        "workbench-health",
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
    assert health_result["skills"] == ["workbench-draft", "workbench-health"]
    assert f"Skills projected for {harness}" in initialized.stdout
    assert f'harnesses = ["{harness}"]' in (project / "speed.toml").read_text()
    # Without --commit, init commits none of the project's own files, but it
    # does leave a usable repository: an unborn HEAD cannot host a worktree and
    # `run` creates one per task, so the root commit is established and empty.
    log = _git(project, "log", "--pretty=%s")
    assert log.returncode == 0, log.stderr
    assert log.stdout.strip().splitlines() == ["Initial commit"]
    assert "speed.toml" in _git(project, "status", "--short").stdout
    worktree = _git(project, "worktree", "add", str(tmp_path / "wt"), "-b", "probe")
    assert worktree.returncode == 0, worktree.stderr
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


def test_malformed_speed_toml_warns_once_and_unrelated_command_continues(tmp_path):
    project = tmp_path / "bad-config"
    project.mkdir()
    (project / "speed.toml").write_text("[skills\nharnesses = [\"claude\"]\n")

    result = _workbench(project, "help")

    assert result.returncode == 0
    messages = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(messages) == 1, result.stderr
    assert messages[0].startswith("Warning: could not parse ")
    assert "using defaults" in messages[0]
    assert "Warning: Warning:" not in result.stderr
    assert "ValueError:" not in result.stderr


def test_speed_init_labels_the_init_alias_not_its_internal_sync(tmp_path):
    project = tmp_path / "speed-init-alias"
    project.mkdir()

    result = _speed(project, "init", "--harness", "claude")

    assert result.returncode == 0, result.stderr
    assert "'speed init' is a temporary alias" in result.stderr
    assert "'speed skills' is a temporary alias" not in result.stderr


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
    assert rows and all(row["state"] == "current" for row in rows)

    trailing = _workbench(project, "skills", "status", "--json")
    assert json.loads(trailing.stdout) == rows


def test_init_commit_survives_a_gitignored_harness_root(tmp_path):
    """`git add` refuses the whole invocation on an ignored pathspec.

    Ignoring `.claude/` is ordinary, and it used to stage every acceptable
    path, refuse the projection, and return 3 with a fully staged index and no
    commit, after projection and verification had both succeeded.
    """
    project = tmp_path / "ignored-root"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    (project / ".gitignore").write_text(".claude/\n")
    _git(project, "add", ".gitignore")
    _git(project, "commit", "-qm", "base")

    initialized = _workbench(project, "init", "--harness", "claude", "--commit")

    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    # log_warn writes to stderr.
    assert "ignored path" in initialized.stderr
    committed = _git(project, "show", "--name-only", "--pretty=", "HEAD").stdout
    assert ".speed/skills/manifest.json" in committed
    assert "speed.toml" in committed
    # Nothing may be left staged behind the error path that used to run here.
    assert _git(project, "status", "--short").stdout.strip() == ""


def test_init_commit_survives_a_manifest_entry_whose_projection_is_gone(tmp_path):
    """A removed skill leaves a path that never entered the index.

    Sync reports the removal, so the path reached `git add`, which failed with
    `did not match any files` and took the whole commit with it.
    """
    project = tmp_path / "converge"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    (project / ".claude").mkdir()
    assert _workbench(project, "init", "--harness", "claude", "--commit").returncode == 0

    manifest_path = project / PATHS.manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["harnesses"]["claude"]["skills"]["gone-skill"] = {
        "files": {"SKILL.md": "sha256:dead"},
        "projected_at_version": "old",
        "version": "1.0.0",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    again = _workbench(project, "init", "--harness", "claude", "--commit")

    assert again.returncode == 0, again.stdout + again.stderr
    converged = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "gone-skill" not in converged["harnesses"]["claude"]["skills"]


def test_init_warns_when_an_outside_rule_excludes_the_manifest(tmp_path):
    """A blanket `.speed/` outside the managed block wins.

    Git cannot re-include a path whose parent directory is excluded, so the
    block's own `!.speed/skills/manifest.json` is inert. The rule belongs to
    the user, so init reports it instead of rewriting it; staying silent ships
    a repo whose teammates classify every projected skill as conflicted.
    """
    project = tmp_path / "shadowed"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    (project / ".gitignore").write_text(".speed/\n")
    (project / ".claude").mkdir()

    initialized = _workbench(project, "init", "--harness", "claude")

    assert initialized.returncode == 0, initialized.stderr
    # log_warn writes to stderr.
    assert ".speed/skills/manifest.json is excluded by" in initialized.stderr
    assert ".gitignore:1:.speed/" in initialized.stderr
    ignored = _git(project, "check-ignore", "-q", "--", ".speed/skills/manifest.json")
    assert ignored.returncode == 0, "repro no longer reproduces the shadowing"
