"""The bootstrap path outside the Python engine: install, init, commit, clone.

Every rule SPEED writes must commit the skill manifest. The manifest is the sole
record distinguishing SPEED-written bytes from a user edit, so committing the
projections without it makes a fresh clone classify every projected skill as
`conflicted` and offer `--force` as the repair. Runtime data (`events.jsonl`)
stays local: per-machine append-only history that no classification reads.

The shell-source tests below exist because three defects here shared one shape:
the fix was present in the source but unreachable. A migration branch sat behind
a condition already true for every existing project; `set -euo pipefail` killed
init before its own error branches could run; only `install.sh` ever created the
`bin/` links, so an upgrade never gained a newly added command. Reading the real
source keeps them honest — asserting on a copy of a condition proves nothing.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable

MANIFEST_REL = ".speed/skills/manifest.json"
EVENTS_REL = ".speed/skills/events.jsonl"

PROJECT_SH = REPO / "lib" / "cmd" / "project.sh"
INSTALL_SH = REPO / "install.sh"
SELF_SH = REPO / "lib" / "cmd" / "self.sh"
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


def _shell_condition(source: Path, needle: str) -> str:
    """Extract the `if`/`elif` condition containing `needle` from a shell file.

    Reading the real source keeps these tests honest: a rule that only ever
    appears inside an unreachable branch is the exact defect they exist to
    catch, so asserting on a copy of the condition would prove nothing.
    """
    lines = source.read_text().splitlines()
    start = next(index for index, line in enumerate(lines) if needle in line)
    while not lines[start].strip().startswith(("if ", "elif ")):
        start -= 1
    chunk = []
    for line in lines[start:]:
        chunk.append(line)
        if line.rstrip().endswith("; then"):
            break
    else:
        raise AssertionError(f"unterminated condition for {needle!r} in {source}")
    chunk[0] = chunk[0].strip()
    text = "\n".join(chunk)
    keyword = "elif " if text.startswith("elif ") else "if "
    return text[len(keyword): text.rindex("; then")]


def _fires(condition: str, **shell_vars) -> bool:
    script = f"if {condition}\nthen exit 0\nelse exit 1\nfi\n"
    return subprocess.run(
        ["bash", "-c", script],
        env=dict(os.environ, **shell_vars),
        capture_output=True,
    ).returncode == 0


_OLD_MP_ALLOWLIST = """\
*
!shared/
!shared/**
!.gitignore
"""


def test_multiplayer_repair_fires_for_an_already_migrated_project(tmp_path):
    """The bare `*` alone is not evidence the manifest carve-out is present."""
    condition = _shell_condition(MP_INIT_SH, "!skills/manifest\\.json$")
    state = tmp_path / ".speed"
    state.mkdir(parents=True)
    (state / ".gitignore").write_text(_OLD_MP_ALLOWLIST)

    assert _fires(condition, STATE_DIR=str(state))


def test_multiplayer_repair_is_idempotent_once_the_carve_out_is_present(tmp_path):
    condition = _shell_condition(MP_INIT_SH, "!skills/manifest\\.json$")
    state = tmp_path / ".speed"
    state.mkdir(parents=True)
    (state / ".gitignore").write_text(MULTIPLAYER_BLOCKS[0])

    assert not _fires(condition, STATE_DIR=str(state))


def test_events_rule_is_added_to_a_project_initialized_before_the_skill_engine(
    tmp_path,
):
    condition = _shell_condition(PROJECT_SH, "-qF '.speed/skills/events.jsonl'")
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("# SPEED runtime state\n.speed/logs/\n.speed/features/*/logs/\n")

    assert _fires(condition, project_gitignore=str(gitignore))


def test_events_rule_is_not_added_twice(tmp_path):
    condition = _shell_condition(PROJECT_SH, "-qF '.speed/skills/events.jsonl'")
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(SINGLE_PLAYER_BLOCKS[0])

    assert not _fires(condition, project_gitignore=str(gitignore))


_LINK_RE = re.compile(r'\$\{SPEED_HOME\}/bin/(\w[\w.-]*)"')


def _published(source: Path) -> set:
    """Entrypoint names this script symlinks into `~/.speed/bin`."""
    return {
        match.group(1)
        for line in source.read_text().splitlines()
        if line.strip().startswith("ln ")
        for match in [_LINK_RE.search(line)]
        if match
    }


def test_install_publishes_both_entrypoints():
    assert _published(INSTALL_SH) == {"speed", "workbench"}


def test_self_update_publishes_what_install_does():
    """`doctor`, the README, and every projected skill tell users to run
    `workbench`; an upgrade that omits the link sends them nowhere."""
    assert _published(SELF_SH) == _published(INSTALL_SH)


def _sync_assignment() -> str:
    """The real line init uses to run sync and record its exit status."""
    for line in PROJECT_SH.read_text().splitlines():
        if "cmd_skills " in line and "--json" in line:
            return line.strip()
    raise AssertionError(f"no cmd_skills --json invocation in {PROJECT_SH}")


@pytest.mark.parametrize("rc", [0, 2, 3])
def test_init_records_the_sync_status_instead_of_dying_on_it(rc):
    """Sync exits 2 on a conflict and 3 on a catalog error. Either one used to
    kill init before its own branches and before the initial commit."""
    script = f"""
set -euo pipefail
cmd_skills() {{ echo '[]'; return {rc}; }}
sync_args=(sync)
sync_status=0
sync_err=$(mktemp)
{_sync_assignment()}
echo "STATUS=$sync_status"
echo "CONTINUED"
rm -f "$sync_err"
"""
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert f"STATUS={rc}" in result.stdout
    assert "CONTINUED" in result.stdout
