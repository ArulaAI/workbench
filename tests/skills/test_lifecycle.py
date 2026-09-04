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
from dataclasses import replace
from pathlib import Path

import pytest
from skills import PATHS
from skills.bootstrap import (
    IGNORE_POLICIES,
    MANAGED_BEGIN,
    MANAGED_END,
    reconcile_ignore,
    render_ignore_block,
)
from skills.models import SkillState

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable

MANIFEST_REL = PATHS.manifest.as_posix()
EVENTS_REL = PATHS.events.as_posix()

PROJECT_SH = REPO / "lib" / "cmd" / "project.sh"
INSTALL_SH = REPO / "install.sh"
MP_INIT_SH = REPO / "lib" / "cmd" / "mp_init.sh"
OWN_SPEED_IGNORE = REPO / ".speed" / ".gitignore"

# Two ignore files, one mechanism: a managed block rendered from the canonical
# state layout. The tests read the policy rather than restating its rules, and
# they run the shell functions that apply it for real, because what matters is
# the file a project ends up with and not that some heredoc holds the right
# lines.
SCOPES = ("project", "state")
_RECONCILE = {
    "project": (PROJECT_SH, "_init_reconcile_gitignore"),
    "state": (MP_INIT_SH, "_mp_reconcile_state_ignore"),
}

_GIT_ENV = dict(
    os.environ,
    GIT_CONFIG_GLOBAL="/dev/null",
    GIT_CONFIG_SYSTEM="/dev/null",
    GIT_AUTHOR_NAME="speed-test",
    GIT_AUTHOR_EMAIL="speed@test.invalid",
    GIT_COMMITTER_NAME="speed-test",
    GIT_COMMITTER_EMAIL="speed@test.invalid",
)


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=_GIT_ENV
    )


def _ignored(repo, rel) -> bool:
    return _git(repo, "check-ignore", "-q", rel).returncode == 0


def _project(tmp_path, name) -> Path:
    """A git repo carrying the skill state files and no ignore policy yet."""
    repo = tmp_path / name
    (repo / PATHS.state_root).mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    (repo / MANIFEST_REL).write_text("{}\n")
    (repo / EVENTS_REL).write_text("")
    return repo


def _ignore_path(project, scope) -> Path:
    return project / IGNORE_POLICIES[scope].relpath


def _ignore_text(project, scope) -> str:
    return _ignore_path(project, scope).read_text()


def _managed_text(scope) -> str:
    return "\n".join(render_ignore_block(IGNORE_POLICIES[scope])) + "\n"


def _tracking_policy_holds(project) -> bool:
    """Git carries the manifest and not the event log: the point of the rules."""
    return not _ignored(project, MANIFEST_REL) and _ignored(project, EVENTS_REL)


# The same two state files, addressed from the project root and from `.speed/`.
_MANIFEST_RULE = {
    "project": MANIFEST_REL,
    "state": PATHS.manifest.relative_to(PATHS.state_root.parent).as_posix(),
}
_EVENTS_RULE = {
    "project": EVENTS_REL,
    "state": PATHS.events.relative_to(PATHS.state_root.parent).as_posix(),
}

# One rule per file whose deletion is observable through `git check-ignore`.
# Only the project region names the event log, because `.speed/` itself is not
# ignored there; inside `.speed/.gitignore` everything starts ignored and the
# manifest carve-out is what git tracking hangs on.
_LOAD_BEARING_RULE = {
    "project": _EVENTS_RULE["project"],
    "state": f"!{_MANIFEST_RULE['state']}",
}

# A rule no released version ever wrote, standing in for one a later version
# introduces and a version after that retires. The two files ignore by
# opposite defaults, so each needs its own probe and expected verdict.
_INVENTED = {
    "project": ("invented-later/", "invented-later/file", True),
    "state": ("!invented-later", ".speed/invented-later", False),
}

_USER_PREFIX = "# mine, above the block\nnode_modules/\n*.tmp\n"
_USER_SUFFIX = "# mine, below the block\n!keep.tmp\nbuild/\n"


def _reconcile(project, scope):
    """Run the real shell function that applies one managed ignore policy.

    Init and mp-init reach the renderer through `_context_python`, so the
    script sources that resolver instead of calling an interpreter the test
    picked: a rename on either side then fails here rather than diverging
    quietly.
    """
    source, function = _RECONCILE[scope]
    script = f"""
set -euo pipefail
{_LOG_STUBS}
SPEED_DIR={_q(REPO)}
PROJECT_ROOT={_q(project)}
SPEED_PYTHON={_q(PY)}
source {_q(CONTEXT_BRIDGE_SH)}
source {_q(source)}
status=0
{function} || status=$?
echo "STATUS=${{status}}"
"""
    return _bash(script)


def _status(result) -> int:
    """0 changed the file, 1 found it current, 3 could not apply the policy."""
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(r"^STATUS=(\d+)$", result.stdout, re.MULTILINE)
    assert match, result.stdout + result.stderr
    return int(match.group(1))


@pytest.mark.parametrize("scope", SCOPES)
def test_init_tracks_the_manifest_and_ignores_the_event_log(tmp_path, scope):
    project = _project(tmp_path, f"policy-{scope}")

    assert _status(_reconcile(project, scope)) == 0

    assert not _ignored(project, MANIFEST_REL)
    assert _ignored(project, EVENTS_REL)


def test_multiplayer_zone_split_survives(tmp_path):
    """The manifest carve-out must not leak the local/ zone into git."""
    project = _project(tmp_path, "zones")
    assert _status(_reconcile(project, "state")) == 0
    (project / ".speed" / "shared").mkdir(parents=True, exist_ok=True)
    (project / ".speed" / "shared" / "active_feature").write_text("demo\n")
    (project / ".speed" / "local").mkdir(parents=True, exist_ok=True)
    (project / ".speed" / "local" / "dashboard.db").write_text("")

    assert not _ignored(project, ".speed/shared/active_feature")
    assert _ignored(project, ".speed/local/dashboard.db")


def test_workbench_own_state_ignore_commits_manifest(tmp_path):
    """The ignore file checked into this repo follows the same rule."""
    project = _project(tmp_path, "own")
    _ignore_path(project, "state").write_text(OWN_SPEED_IGNORE.read_text())

    assert not _ignored(project, MANIFEST_REL)
    assert _ignored(project, EVENTS_REL)


@pytest.mark.parametrize("scope", SCOPES)
def test_reinit_restores_a_managed_rule_that_went_missing(tmp_path, scope):
    """The defect this block closes.

    The rules used to be appended behind a test for their own header comment,
    which made the header stand in for the rules under it. Deleting one rule
    reproduces the state of a project initialized before that rule existed:
    header present, rule missing, and no run of init able to notice.
    """
    project = _project(tmp_path, f"dropped-{scope}")
    assert _status(_reconcile(project, scope)) == 0
    rule = _LOAD_BEARING_RULE[scope]
    assert rule in IGNORE_POLICIES[scope].rules
    path = _ignore_path(project, scope)
    path.write_text(path.read_text().replace(f"{rule}\n", "", 1))
    assert not _tracking_policy_holds(project)

    assert _status(_reconcile(project, scope)) == 0

    assert rule in _ignore_text(project, scope)
    assert _tracking_policy_holds(project)


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize(
    ("above", "below"),
    [
        (_USER_PREFIX, _USER_SUFFIX),
        # Blank lines the user left on either side of the region, which a
        # rewrite is most likely to eat or multiply.
        (f"{_USER_PREFIX}\n\n", f"\n{_USER_SUFFIX}\n"),
        # A last line with no newline after it, the one case where the file
        # cannot come back byte-identical.
        (_USER_PREFIX, _USER_SUFFIX.rstrip("\n")),
    ],
    ids=("plain", "blank-lines-adjacent", "no-trailing-newline"),
)
def test_rules_outside_the_block_survive_a_rewrite(tmp_path, scope, above, below):
    """The property the whole mechanism rests on."""
    project = _project(tmp_path, f"user-{scope}")
    path = _ignore_path(project, scope)
    path.write_text(above)
    assert _status(_reconcile(project, scope)) == 0
    assert path.read_text().startswith(above)
    path.write_text(path.read_text() + below)
    intended = path.read_text()

    # A missing rule forces the next init to rewrite a region that now has
    # user rules on both sides of it.
    path.write_text(intended.replace(f"{_LOAD_BEARING_RULE[scope]}\n", "", 1))
    assert _status(_reconcile(project, scope)) == 0

    # Every byte returns, except that a file not ending in a newline gains one.
    expected = intended if intended.endswith("\n") else f"{intended}\n"
    assert path.read_text() == expected
    assert path.read_text().startswith(above)
    assert path.read_text().rstrip("\n").endswith(below.rstrip("\n"))
    assert _status(_reconcile(project, scope)) == 1


@pytest.mark.parametrize("scope", SCOPES)
def test_a_current_region_is_left_byte_identical(tmp_path, scope):
    project = _project(tmp_path, f"noop-{scope}")
    path = _ignore_path(project, scope)
    path.write_text(_USER_PREFIX)
    assert _status(_reconcile(project, scope)) == 0
    text = path.read_text()

    assert _status(_reconcile(project, scope)) == 1

    assert path.read_text() == text


@pytest.mark.parametrize("scope", SCOPES)
def test_repeated_init_does_not_dirty_a_committed_ignore_file(tmp_path, scope):
    project = _project(tmp_path, f"clean-{scope}")
    assert _status(_reconcile(project, scope)) == 0
    _git(project, "add", "-A")
    committed = _git(project, "commit", "-qm", "workbench git policy")
    assert committed.returncode == 0, committed.stderr

    assert _status(_reconcile(project, scope)) == 1

    assert _git(project, "status", "--porcelain").stdout == ""


_HISTORICAL_IGNORES = (
    (
        "project",
        "released-block-without-skill-rules",
        "# SPEED runtime state\n"
        ".speed/logs/\n.speed/features/*/logs/\n.speed/state.json\n",
    ),
    (
        "project",
        "early-block-ignoring-all-skills",
        "# SPEED runtime state\n.speed/logs/\n.speed/skills/\n",
    ),
    (
        "project",
        "two-loose-blocks",
        "# SPEED runtime state\n.speed/logs/\n.speed/state.json\n"
        "\n"
        "# Workbench skill state policy v2\n"
        "!.speed/skills/\n!.speed/skills/manifest.json\n.speed/skills/events.jsonl\n",
    ),
    (
        "state",
        "released-allowlist",
        "# Multi-player mode: only shared/ and the skill manifest are committed,"
        " everything else is local\n"
        "*\n!shared/\n!shared/**\n!.gitignore\n"
        "!skills/\n!skills/manifest.json\nskills/events.jsonl\n",
    ),
    (
        "state",
        "allowlist-before-the-manifest-carve-out",
        "# Multi-player mode: only shared/ is committed, everything else is local\n"
        "*\n!shared/\n!shared/**\n!.gitignore\n",
    ),
)


@pytest.mark.parametrize(
    ("scope", "historical"),
    [(scope, body) for scope, _, body in _HISTORICAL_IGNORES],
    ids=[f"{scope}-{name}" for scope, name, _ in _HISTORICAL_IGNORES],
)
def test_loose_historical_rules_migrate_to_one_managed_block(
    tmp_path, scope, historical
):
    project = _project(tmp_path, "historical")
    _ignore_path(project, scope).write_text(f"{_USER_PREFIX}\n{historical}")

    assert _status(_reconcile(project, scope)) == 0

    text = _ignore_text(project, scope)
    assert text.count(MANAGED_BEGIN) == 1
    assert text.count(MANAGED_END) == 1
    assert text.startswith(_USER_PREFIX)
    rules = [
        line
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert len(rules) == len(set(rules)), text
    assert not _ignored(project, MANIFEST_REL)
    assert _ignored(project, EVENTS_REL)
    assert _status(_reconcile(project, scope)) == 1


def _repolicy(monkeypatch, scope, **changes):
    """Stand in a policy a later Workbench version could ship."""
    monkeypatch.setitem(
        IGNORE_POLICIES, scope, replace(IGNORE_POLICIES[scope], **changes)
    )


@pytest.mark.parametrize("scope", SCOPES)
def test_a_policy_change_both_delivers_and_retires_a_rule(tmp_path, scope, monkeypatch):
    """The property the whole change exists for, driven by two rule sets.

    Reconciliation runs in-process here so the policy can differ between the
    two calls, which is the real upgrade: one Workbench version writes a rule
    into an initialized project and a later one takes it away again. The shell
    route to the same function is covered by the tests above.
    """
    project = _project(tmp_path, f"policy-change-{scope}")
    _ignore_path(project, scope).write_text(_USER_PREFIX)
    released = IGNORE_POLICIES[scope]
    rule, probe, ignored_with_rule = _INVENTED[scope]
    assert reconcile_ignore(project, scope) is True
    assert _ignored(project, probe) is not ignored_with_rule

    _repolicy(monkeypatch, scope, rules=(*released.rules, rule))
    assert reconcile_ignore(project, scope) is True
    assert rule in _ignore_text(project, scope)
    assert _ignored(project, probe) is ignored_with_rule

    monkeypatch.setitem(IGNORE_POLICIES, scope, released)
    assert reconcile_ignore(project, scope) is True

    assert rule not in _ignore_text(project, scope)
    assert _ignored(project, probe) is not ignored_with_rule
    assert _ignore_text(project, scope).count(MANAGED_BEGIN) == 1
    assert _ignore_text(project, scope).startswith(_USER_PREFIX)
    assert _tracking_policy_holds(project)
    assert reconcile_ignore(project, scope) is False


@pytest.mark.parametrize("scope", SCOPES)
def test_the_managed_set_could_carry_a_state_directory_rename(
    tmp_path, scope, monkeypatch
):
    """The concrete future case: `.speed/skills` moving somewhere else.

    Nothing is renamed here. What is proved is that repointing the rules at a
    new directory rewrites an initialized project onto the new paths and takes
    the old ones with it, instead of leaving both generations in the file.
    """
    project = _project(tmp_path, f"rename-{scope}")
    path = _ignore_path(project, scope)
    path.write_text(_USER_PREFIX)
    assert reconcile_ignore(project, scope) is True
    assert _EVENTS_RULE[scope] in path.read_text()

    old, new = PATHS.state_root.name, "packs"
    _repolicy(
        monkeypatch,
        scope,
        rules=tuple(rule.replace(old, new) for rule in IGNORE_POLICIES[scope].rules),
    )

    assert reconcile_ignore(project, scope) is True

    text = path.read_text()
    assert _EVENTS_RULE[scope] not in text
    assert _EVENTS_RULE[scope].replace(old, new) in text
    assert _MANIFEST_RULE[scope] not in text
    assert text.count(MANAGED_BEGIN) == 1
    assert text.startswith(_USER_PREFIX)
    assert reconcile_ignore(project, scope) is False


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize(
    "begin",
    [MANAGED_BEGIN, "# >>> workbench managed (v0) >>>"],
    ids=("same-version-marker", "older-version-marker"),
)
def test_a_retired_rule_is_dropped_from_the_block_where_it_sits(
    tmp_path, scope, begin
):
    """A later Workbench has to be able to retire a rule, not only add one.

    Detection compares the rendered block to the file, so a rule leaving the
    policy converges whether or not the version was bumped with it. The marker
    matters for a different reason: without matching an earlier version, a
    bumped block would be appended next to the one it replaces.
    """
    project = _project(tmp_path, f"retired-{scope}")
    path = _ignore_path(project, scope)
    path.write_text(_USER_PREFIX)
    assert _status(_reconcile(project, scope)) == 0
    intended = path.read_text() + _USER_SUFFIX
    path.write_text(intended)
    assert _status(_reconcile(project, scope)) == 1

    path.write_text(
        intended.replace(MANAGED_BEGIN, begin).replace(
            MANAGED_END, f"retired/\n{MANAGED_END}"
        )
    )

    assert _status(_reconcile(project, scope)) == 0

    assert path.read_text() == intended


@pytest.mark.parametrize("scope", SCOPES)
def test_a_second_block_is_collapsed_into_the_first(tmp_path, scope):
    """One generation of rules survives a version change, not two."""
    project = _project(tmp_path, f"duplicate-{scope}")
    path = _ignore_path(project, scope)
    path.write_text(_USER_PREFIX)
    assert _status(_reconcile(project, scope)) == 0
    intended = path.read_text()
    path.write_text(
        f"{intended}# >>> workbench managed (v0) >>>\nretired/\n{MANAGED_END}\n"
    )

    assert _status(_reconcile(project, scope)) == 0

    assert path.read_text() == intended


@pytest.mark.parametrize("scope", SCOPES)
def test_a_block_without_its_end_marker_fails_instead_of_guessing(tmp_path, scope):
    """Where the block ends is unknowable once the marker is gone, and the
    lines below it may well be the user's. Report it and change nothing."""
    project = _project(tmp_path, f"broken-{scope}")
    path = _ignore_path(project, scope)
    broken = f"{MANAGED_BEGIN}\n{_LOAD_BEARING_RULE[scope]}\n{_USER_SUFFIX}"
    path.write_text(broken)

    result = _reconcile(project, scope)

    assert _status(result) == 3
    assert _ignore_text(project, scope) == broken
    assert "marker" in result.stderr


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

    (origin / ".gitignore").write_text(_managed_text("project"))
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
    (origin / ".gitignore").write_text(_managed_text("project"))
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
        'if [[ "${2:-}" == "skills.bootstrap" ]]; then exec ' + _q(PY) + ' "$@"; fi\n'
        'printf "%s\\n" "$@" > "$ARGV_LOG"\n'
    )
    recorder.chmod(0o755)
    speed_dir = speed_dir or REPO
    home = home or tmp_path / "speed-home"
    return recorder, argv_log, speed_dir, home


def _run_skills(
    tmp_path,
    *args,
    speed_dir=None,
    home=None,
    verbosity=None,
    configured_harnesses=None,
    environment_harnesses=None,
):
    recorder, argv_log, speed_dir, home = _skills_harness(tmp_path, speed_dir, home)
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    if configured_harnesses is not None:
        values = ", ".join(
            f'"{item}"' for item in configured_harnesses.split()
        )
        (project / "speed.toml").write_text(
            f"[skills]\nharnesses = [{values}]\n"
        )
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
        env=dict(
            os.environ,
            ARGV_LOG=str(argv_log),
            WORKBENCH_NS="1",
            **(
                {"WORKBENCH_HARNESSES": environment_harnesses}
                if environment_harnesses is not None
                else {}
            ),
        ),
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


def test_skills_uses_project_harness_policy_when_flag_is_absent(tmp_path):
    result, recorded = _run_skills(
        tmp_path, "status", configured_harnesses="claude codex"
    )

    assert result.returncode == 0, result.stderr
    positions = [i for i, value in enumerate(recorded) if value == "--harness"]
    assert [recorded[i + 1] for i in positions] == ["claude", "codex"]


def test_skills_harness_precedence_is_flag_then_environment_then_config(tmp_path):
    from_env, env_argv = _run_skills(
        tmp_path,
        "status",
        configured_harnesses="claude",
        environment_harnesses="codex",
    )
    from_flag, flag_argv = _run_skills(
        tmp_path,
        "status",
        "--harness",
        "copilot",
        configured_harnesses="claude",
        environment_harnesses="codex",
    )

    assert from_env.returncode == 0, from_env.stderr
    assert env_argv[env_argv.index("--harness") + 1] == "codex"
    assert from_flag.returncode == 0, from_flag.stderr
    assert flag_argv[flag_argv.index("--harness") + 1] == "copilot"


def test_skills_fails_closed_on_invalid_project_harness_policy(tmp_path):
    result, recorded = _run_skills(
        tmp_path, "status", configured_harnesses="cursor"
    )

    assert result.returncode == 3
    assert recorded is None
    assert "speed.toml" in result.stderr


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
