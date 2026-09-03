"""The bootstrap path outside the Python engine: install, init, commit, clone.

Every rule SPEED writes must commit the skill manifest. The manifest is the sole
record distinguishing SPEED-written bytes from a user edit, so committing the
projections without it makes a fresh clone classify every projected skill as
`conflicted` and offer `--force` as the repair. Runtime data (`events.jsonl`)
stays local: per-machine append-only history that no classification reads.

The shell-source tests below read the real scripts rather than a copy of their
logic, because `set -euo pipefail` once killed init before its own error branches
could run: a fix present in the source but unreachable. Asserting on a restated
condition would not have caught that.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from skills import PATHS
from skills.models import SkillState

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable

MANIFEST_REL = PATHS.manifest.as_posix()
EVENTS_REL = PATHS.events.as_posix()

PROJECT_SH = REPO / "lib" / "cmd" / "project.sh"
INSTALL_SH = REPO / "install.sh"
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


# ── Shell wrapper contract ───────────────────────────────────────
#
# `cmd_init` and `cmd_skills` are sourced and called directly. Restating their
# conditions in the test would prove nothing: the bugs below are all about what
# the real scripts do with an argument or a missing directory.

SKILLS_SH = REPO / "lib" / "cmd" / "skills.sh"
CONTEXT_BRIDGE_SH = REPO / "lib" / "context_bridge.sh"

_LOG_STUBS = """
log_error()   { echo "ERROR: $*" >&2; }
log_warn()    { echo "WARN: $*" >&2; }
log_info()    { echo "INFO: $*" >&2; }
log_success() { echo "OK: $*" >&2; }
log_step()    { :; }
log_header()  { :; }
"""


def _bash(script, env=None):
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=dict(os.environ, **(env or {})),
    )


def _q(value) -> str:
    return "'" + str(value).replace("'", "'\\''") + "'"


def _init_script(speed_dir, project_root, body="cmd_init") -> str:
    return f"""
set -euo pipefail
{_LOG_STUBS}
git_ensure_repo() {{ echo "SCAFFOLDED"; }}
SPEED_DIR={_q(speed_dir)}
PROJECT_ROOT={_q(project_root)}
source {_q(PROJECT_SH)}
{body}
"""


def test_init_reports_a_missing_catalog_as_an_installation_error(tmp_path):
    """A catalog directory ships with the install, so its absence is a broken
    install, not a project that opted out of skills."""
    broken_install = tmp_path / "speed-install"
    broken_install.mkdir()
    project = tmp_path / "proj"
    project.mkdir()

    result = _bash(_init_script(broken_install, project))

    assert result.returncode == 3, result.stdout + result.stderr
    assert "SCAFFOLDED" not in result.stdout
    assert str(broken_install / "skills") in result.stderr
    assert sorted(p.name for p in project.iterdir()) == []


def test_init_accepts_an_installation_that_carries_its_catalog(tmp_path):
    speed_dir = tmp_path / "speed-install"
    (speed_dir / "skills").mkdir(parents=True)
    project = tmp_path / "proj"
    project.mkdir()

    result = _bash(
        _init_script(speed_dir, project, body="_init_require_skill_catalog; echo READY")
    )

    assert result.returncode == 0, result.stderr
    assert "READY" in result.stdout


# ── cmd_skills argument handling ─────────────────────────────────


def _skills_harness(tmp_path, speed_dir=None, home=None) -> tuple:
    """A sourced `cmd_skills` whose interpreter records the argv it receives."""
    recorder = tmp_path / "record-python"
    argv_log = tmp_path / "argv.txt"
    # `-c` is the receipt parser and `harnesses` is the canonical harness
    # registry query: both are real work the wrapper does before it delegates,
    # so they run for real and are not recorded. The log therefore holds the
    # lifecycle invocation and nothing else.
    recorder.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${1:-}" == "-c" ]]; then exec ' + _q(PY) + ' "$@"; fi\n'
        'if [[ "${3:-}" == "harnesses" ]]; then exec ' + _q(PY) + ' "$@"; fi\n'
        'printf "%s\\n" "$@" > "$ARGV_LOG"\n'
    )
    recorder.chmod(0o755)
    speed_dir = speed_dir or REPO
    home = home or tmp_path / "speed-home"
    return recorder, argv_log, speed_dir, home


def _run_skills(tmp_path, *args, speed_dir=None, home=None, verbosity=None):
    recorder, argv_log, speed_dir, home = _skills_harness(tmp_path, speed_dir, home)
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    verbosity_line = f"VERBOSITY={verbosity}\n" if verbosity is not None else ""
    script = f"""
set -euo pipefail
{_LOG_STUBS}
{verbosity_line}SPEED_DIR={_q(speed_dir)}
PROJECT_ROOT={_q(project)}
SPEED_PYTHON={_q(recorder)}
SPEED_HOME={_q(home)}
# The real dispatcher sources context_bridge.sh before any command file, and
# skills.sh now takes its interpreter from that shared resolver rather than
# keeping a private copy. Sourcing it here keeps the harness honest: a rename
# on either side fails the test instead of silently diverging.
source {_q(CONTEXT_BRIDGE_SH)}
source {_q(SKILLS_SH)}
cmd_skills "$@"
"""
    result = subprocess.run(
        ["bash", "-c", script, "bash", *args],
        capture_output=True,
        text=True,
        env=dict(os.environ, ARGV_LOG=str(argv_log), WORKBENCH_NS="1"),
    )
    recorded = argv_log.read_text().splitlines() if argv_log.exists() else None
    return result, recorded


def test_bash_reads_the_same_harness_registry_as_the_engine(tmp_path):
    """Bash used to carry its own `claude|codex|copilot` list in two files.

    A harness added to the engine has to reach the CLI, so the shell asks the
    registry instead of restating it.
    """
    from skills.models import HARNESS_IDS

    script = f"""
set -euo pipefail
{_LOG_STUBS}
SPEED_DIR={_q(REPO)}
PROJECT_ROOT={_q(tmp_path)}
source {_q(CONTEXT_BRIDGE_SH)}
source {_q(SKILLS_SH)}
workbench_harness_ids
echo "---"
workbench_harness_choices
echo "---"
workbench_harness_list
"""
    result = _bash(script, env={"WORKBENCH_NS": "1"})

    assert result.returncode == 0, result.stderr
    ids, choices, prose = result.stdout.strip().split("---")
    assert ids.split() == list(HARNESS_IDS)
    assert choices.strip() == "|".join(HARNESS_IDS)
    assert prose.strip() == ", ".join(HARNESS_IDS)


def test_skills_rejects_an_unknown_subcommand_with_the_error_code(tmp_path):
    """Exit 1 is reserved for drift and doctor findings; usage errors are 3."""
    result, recorded = _run_skills(tmp_path, "resync")

    assert result.returncode == 3, result.stderr
    assert recorded is None
    assert "resync" in result.stderr


def test_skills_requires_a_subcommand_instead_of_guessing_status(tmp_path):
    result, recorded = _run_skills(tmp_path)

    assert result.returncode == 3, result.stderr
    assert recorded is None
    assert "sync" in result.stderr and "doctor" in result.stderr


def test_skills_help_is_a_real_command(tmp_path):
    result, recorded = _run_skills(tmp_path, "--help")

    assert result.returncode == 0, result.stderr
    assert recorded is None
    assert "workbench skills" in result.stdout
    assert "--force" in result.stdout


def test_skills_refuses_to_let_a_caller_redirect_the_project_root(tmp_path):
    """`--project-root` is resolved by Workbench, not supplied by the caller."""
    result, recorded = _run_skills(
        tmp_path, "status", "--project-root", "/tmp/elsewhere"
    )

    assert result.returncode == 3, result.stderr
    assert recorded is None
    assert "--project-root" in result.stderr


def test_skills_refuses_to_let_a_caller_redirect_the_catalog(tmp_path):
    result, recorded = _run_skills(
        tmp_path, "sync", "--skills-dir", "/tmp/other", "--catalog-version", "9.9.9"
    )

    assert result.returncode == 3, result.stderr
    assert recorded is None


def test_skills_forwards_the_documented_public_options(tmp_path):
    result, recorded = _run_skills(tmp_path, "sync", "--harness", "codex", "--force")

    assert result.returncode == 0, result.stderr
    assert recorded[:2] == ["-m", "skills"]
    assert "--force" in recorded
    assert recorded[recorded.index("--harness") + 1] == "codex"
    assert recorded[recorded.index("--project-root") + 1] == str(tmp_path / "proj")


def test_skills_rejects_force_outside_sync(tmp_path):
    result, recorded = _run_skills(tmp_path, "status", "--force")

    assert result.returncode == 3, result.stderr
    assert recorded is None


def test_skills_rejects_a_harness_flag_with_no_value(tmp_path):
    result, recorded = _run_skills(tmp_path, "doctor", "--harness")

    assert result.returncode == 3, result.stderr
    assert recorded is None


def test_skills_reads_the_catalog_version_from_a_managed_receipt(tmp_path):
    home = tmp_path / "speed-home"
    home.mkdir()
    (home / "receipt.json").write_text('{"version": "1.4.2"}\n')
    managed = tmp_path / "managed-install"
    (managed / "skills").mkdir(parents=True)

    result, recorded = _run_skills(
        tmp_path, "status", speed_dir=managed, home=home
    )

    assert result.returncode == 0, result.stderr
    assert recorded[recorded.index("--catalog-version") + 1] == "1.4.2"


def test_skills_calls_a_git_checkout_a_development_build(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / "skills").mkdir(parents=True)
    (checkout / ".git").mkdir()
    home = tmp_path / "speed-home"
    home.mkdir()
    (home / "receipt.json").write_text('{"version": "1.4.2"}\n')

    result, recorded = _run_skills(tmp_path, "status", speed_dir=checkout, home=home)

    assert result.returncode == 0, result.stderr
    assert recorded[recorded.index("--catalog-version") + 1] == "dev"


def test_skills_refuses_to_invent_a_version_for_a_broken_install(tmp_path):
    """A corrupt receipt used to project the same provenance as a dev checkout."""
    home = tmp_path / "speed-home"
    home.mkdir()
    (home / "receipt.json").write_text("{not json\n")
    managed = tmp_path / "managed-install"
    (managed / "skills").mkdir(parents=True)

    result, recorded = _run_skills(tmp_path, "status", speed_dir=managed, home=home)

    assert result.returncode == 3, result.stdout
    assert recorded is None
    assert "receipt" in result.stderr


def test_skills_reports_a_missing_receipt_for_a_managed_install(tmp_path):
    home = tmp_path / "speed-home"
    home.mkdir()
    managed = tmp_path / "managed-install"
    (managed / "skills").mkdir(parents=True)

    result, recorded = _run_skills(tmp_path, "status", speed_dir=managed, home=home)

    assert result.returncode == 3, result.stdout
    assert recorded is None


def test_skills_forwards_debug_intent_to_the_engine(tmp_path):
    """`--debug` raises VERBOSITY in the dispatcher; the engine reads an env var."""
    recorder = tmp_path / "show-env"
    recorder.write_text("#!/usr/bin/env bash\necho \"DEBUG=${WORKBENCH_DEBUG:-}\"\n")
    recorder.chmod(0o755)
    project = tmp_path / "proj"
    project.mkdir()
    script = f"""
set -euo pipefail
{_LOG_STUBS}
VERBOSITY=3
SPEED_DIR={_q(REPO)}
PROJECT_ROOT={_q(project)}
SPEED_PYTHON={_q(recorder)}
source {_q(CONTEXT_BRIDGE_SH)}
source {_q(SKILLS_SH)}
cmd_skills status
"""
    result = _bash(script, env={"WORKBENCH_NS": "1"})

    assert result.returncode == 0, result.stderr
    assert "DEBUG=1" in result.stdout
