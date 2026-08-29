"""Every ignore rule SPEED writes must commit the skill manifest.

The manifest is the sole record distinguishing SPEED-written bytes from a user
edit. Committing the projections without it makes a fresh clone classify every
projected skill as `conflicted` and offer `--force` as the repair. Runtime data
(`events.jsonl`) stays local: it is per-machine append-only history that no
classification reads.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable

MANIFEST_REL = ".speed/skills/manifest.json"
EVENTS_REL = ".speed/skills/events.jsonl"

PROJECT_SH = REPO / "lib" / "cmd" / "project.sh"
MP_INIT_SH = REPO / "lib" / "cmd" / "mp_init.sh"
OWN_SPEED_IGNORE = REPO / ".speed" / ".gitignore"

_SINGLE_PLAYER_SENTINEL = "# SPEED runtime state"
_MULTIPLAYER_SENTINEL = (
    "# Multi-player mode: only shared/ and the skill manifest are committed, everything else is local"
)
_HEREDOC_TERMINATORS = {"EOF", "INNER_GITIGNORE"}

_GIT_ENV = dict(
    os.environ,
    GIT_CONFIG_GLOBAL="/dev/null",
    GIT_CONFIG_SYSTEM="/dev/null",
    GIT_AUTHOR_NAME="speed-test",
    GIT_AUTHOR_EMAIL="speed@test.invalid",
    GIT_COMMITTER_NAME="speed-test",
    GIT_COMMITTER_EMAIL="speed@test.invalid",
)


def _ignore_blocks(source: Path, sentinel: str) -> list:
    """Return every shell heredoc ignore block introduced by `sentinel`."""
    lines = source.read_text().splitlines()
    blocks = []
    for index, line in enumerate(lines):
        if line.strip() != sentinel:
            continue
        body = []
        for candidate in lines[index:]:
            if candidate.strip() in _HEREDOC_TERMINATORS:
                blocks.append("\n".join(body) + "\n")
                break
            body.append(candidate)
        else:
            raise AssertionError(f"unterminated ignore block at {source}:{index + 1}")
    assert blocks, f"no ignore block for {sentinel!r} in {source}"
    return blocks


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=_GIT_ENV
    )


def _repo_with_ignore(tmp_path, name, ignore_rel, body):
    repo = tmp_path / name
    (repo / ".speed" / "skills").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    target = repo / ignore_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    (repo / MANIFEST_REL).write_text("{}\n")
    (repo / EVENTS_REL).write_text("")
    return repo


def _ignored(repo, rel) -> bool:
    return _git(repo, "check-ignore", "-q", rel).returncode == 0


def _block_ids(blocks) -> list:
    return [f"block{index}" for index in range(len(blocks))]


SINGLE_PLAYER_BLOCKS = _ignore_blocks(PROJECT_SH, _SINGLE_PLAYER_SENTINEL)
MULTIPLAYER_BLOCKS = _ignore_blocks(MP_INIT_SH, _MULTIPLAYER_SENTINEL)


@pytest.mark.parametrize("body", SINGLE_PLAYER_BLOCKS, ids=_block_ids(SINGLE_PLAYER_BLOCKS))
def test_single_player_init_commits_manifest_and_ignores_events(tmp_path, body):
    repo = _repo_with_ignore(tmp_path, "single", ".gitignore", body)
    assert not _ignored(repo, MANIFEST_REL)
    assert _ignored(repo, EVENTS_REL)


@pytest.mark.parametrize("body", MULTIPLAYER_BLOCKS, ids=_block_ids(MULTIPLAYER_BLOCKS))
def test_multiplayer_init_commits_manifest_and_ignores_events(tmp_path, body):
    repo = _repo_with_ignore(tmp_path, "mp", ".speed/.gitignore", body)
    assert not _ignored(repo, MANIFEST_REL)
    assert _ignored(repo, EVENTS_REL)


@pytest.mark.parametrize("body", MULTIPLAYER_BLOCKS, ids=_block_ids(MULTIPLAYER_BLOCKS))
def test_multiplayer_zone_split_survives(tmp_path, body):
    """The manifest carve-out must not leak the local/ zone into git."""
    repo = _repo_with_ignore(tmp_path, "zones", ".speed/.gitignore", body)
    (repo / ".speed" / "shared").mkdir(parents=True, exist_ok=True)
    (repo / ".speed" / "shared" / "active_feature").write_text("demo\n")
    (repo / ".speed" / "local").mkdir(parents=True, exist_ok=True)
    (repo / ".speed" / "local" / "dashboard.db").write_text("")
    assert not _ignored(repo, ".speed/shared/active_feature")
    assert _ignored(repo, ".speed/local/dashboard.db")


def test_workbench_own_state_ignore_commits_manifest(tmp_path):
    """The ignore file checked into this repo follows the same rule."""
    repo = _repo_with_ignore(
        tmp_path, "own", ".speed/.gitignore", OWN_SPEED_IGNORE.read_text()
    )
    assert not _ignored(repo, MANIFEST_REL)
    assert _ignored(repo, EVENTS_REL)


def test_fresh_clone_of_committed_project_is_current(tmp_path):
    """The reviewer's scenario: clone a project whose projections were committed."""
    origin = tmp_path / "origin"
    (origin / ".claude").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(origin))

    synced = subprocess.run(
        [
            PY, "-m", "skills", "sync",
            "--project-root", str(origin),
            "--skills-dir", str(REPO / "skills"),
            "--catalog-version", "test",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=str(REPO / "lib")),
    )
    assert synced.returncode == 0, synced.stderr

    (origin / ".gitignore").write_text(SINGLE_PLAYER_BLOCKS[0])
    _git(origin, "add", "-A")
    committed = _git(origin, "commit", "-qm", "add workbench skills")
    assert committed.returncode == 0, committed.stderr

    tracked = _git(origin, "ls-files").stdout.split()
    assert MANIFEST_REL in tracked
    assert ".claude/skills/workbench-health/SKILL.md" in tracked
    assert EVENTS_REL not in tracked

    clone = tmp_path / "clone"
    cloned = _git(tmp_path, "clone", "-q", str(origin), str(clone))
    assert cloned.returncode == 0, cloned.stderr

    result = subprocess.run(
        [
            PY, "-m", "skills", "status",
            "--project-root", str(clone),
            "--skills-dir", str(REPO / "skills"),
            "--catalog-version", "test",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=str(REPO / "lib")),
    )
    assert "conflicted" not in result.stdout, result.stdout
    assert "current" in result.stdout, result.stdout
    assert result.returncode == 0, result.stdout


def test_fresh_clone_reports_healthy(tmp_path):
    """The projected health skill must pass in a clone that never ran sync."""
    origin = tmp_path / "origin"
    (origin / ".claude").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(origin))
    subprocess.run(
        [
            PY, "-m", "skills", "sync",
            "--project-root", str(origin),
            "--skills-dir", str(REPO / "skills"),
            "--catalog-version", "test",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=str(REPO / "lib")),
        check=True,
    )
    (origin / ".gitignore").write_text(SINGLE_PLAYER_BLOCKS[0])
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "add workbench skills")

    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))

    health = subprocess.run(
        [
            PY,
            str(clone / ".claude/skills/workbench-health/scripts/health.py"),
            "--project-root",
            str(clone),
        ],
        capture_output=True,
        text=True,
    )
    assert health.returncode == 0, health.stdout
    assert "status: healthy" in health.stdout
