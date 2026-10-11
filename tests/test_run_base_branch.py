"""speed run compares and merges task branches against the branch the run started on.

Task branches are created from the current branch, but gates diffed them against the
repository default (main). On any other working branch, every file that branch had
changed counted as the task's own change: scope checks failed and the secrets scan
flagged files the task never touched. Merges also went to main.
"""

import subprocess
from pathlib import Path

SPEED_DIR = Path(__file__).resolve().parent.parent
LIB = SPEED_DIR / "lib"
ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "NO_COLOR": "1",
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "HOME": "/tmp"}


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "commit", "-q", "--allow-empty", "-m", "base"],
                ["git", "checkout", "-q", "-b", "feat/work"]):
        subprocess.run(cmd, cwd=repo, check=True, env=ENV)
    return repo


def _sh(repo: Path, script: str, main_branch: str = "") -> str:
    env = dict(ENV, PROJECT_ROOT=str(repo), FEATURE_DIR=str(repo / ".speed/features/f"))
    if main_branch:
        env["MAIN_BRANCH"] = main_branch
    r = subprocess.run(
        ["bash", "-c", f'source "{LIB}/colors.sh"; source "{LIB}/log.sh"; source "{LIB}/git.sh"; {script}'],
        check=False, capture_output=True, text=True, env=env)
    return (r.stdout + r.stderr).strip()


def test_without_a_record_the_default_branch_is_used(tmp_path):
    assert _sh(_repo(tmp_path), "git_main_branch") == "main"


def test_run_records_the_starting_branch_as_base(tmp_path):
    repo = _repo(tmp_path)
    assert _sh(repo, "git_record_feature_base_branch; git_main_branch") == "feat/work"
    assert (repo / ".speed/features/f/base_branch").read_text().strip() == "feat/work"


def test_resumed_run_keeps_the_recorded_base(tmp_path):
    repo = _repo(tmp_path)
    _sh(repo, "git_record_feature_base_branch")
    subprocess.run(["git", "checkout", "-q", "-b", "other"], cwd=repo, check=True, env=ENV)
    out = _sh(repo, "git_record_feature_base_branch; git_main_branch")
    assert "feat/work" in out.splitlines()
    assert "recorded base branch 'feat/work'" in out


def test_main_branch_env_wins_and_records_nothing(tmp_path):
    repo = _repo(tmp_path)
    assert _sh(repo, "git_record_feature_base_branch; git_main_branch", main_branch="main") == "main"
    assert not (repo / ".speed/features/f/base_branch").exists()


def test_record_for_a_deleted_branch_is_ignored(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".speed/features/f").mkdir(parents=True)
    (repo / ".speed/features/f/base_branch").write_text("gone\n")
    assert _sh(repo, "git_main_branch") == "main"


def test_run_records_the_base_before_any_task_starts():
    source = (LIB / "cmd" / "run.sh").read_text()
    assert source.index("git_record_feature_base_branch") < source.index("total=$(task_count_total)")


def _db_url_pattern() -> str:
    # The default list ends with "Database URL", so its regex is the last default regex.
    source = (LIB / "grounding.sh").read_text()
    start = source.index('"Database URL"\n        )\n        pattern_regexes=(')
    block = source[start:source.index("\n        )", start + 20)]
    last = block.strip().splitlines()[-1].strip()
    return subprocess.run(["bash", "-c", f"printf '%s' {last}"], check=False, capture_output=True, text=True).stdout


def _matches(text: str) -> bool:
    r = subprocess.run(["grep", "-qE", "-e", _db_url_pattern()], check=False, input=text, text=True)
    return r.returncode == 0


def test_database_url_pattern_catches_credentials():
    assert _matches('DATABASE_URL="postgres://admin:s3cret@db.internal:5432/app"')
    assert _matches("mongodb+srv://u:p@cluster0.example.net/x")


def test_database_url_pattern_ignores_paths_and_query_strings():
    fonts = ('<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,300'
             '&display=swap" rel="stylesheet">')
    assert not _matches(fonts)
    assert not _matches("see https://example.com/a?b=c:d@e")


def test_a_new_plan_forgets_the_previous_base_branch():
    source = (LIB / "cmd" / "plan.sh").read_text()
    reset = source.index('rm -f "${TASKS_DIR}"/*.json')
    assert 'rm -f "${FEATURE_DIR}/base_branch"' in source[reset:reset + 200]


def test_syntax_check_diffs_against_the_run_base_not_main(tmp_path):
    # No `main` branch exists: the gate used to diff `main...task` and silently check nothing.
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["git", "init", "-q", "-b", "trunk"], ["git", "commit", "-q", "--allow-empty", "-m", "base"],
                ["git", "checkout", "-q", "-b", "speed/f/task-1"]):
        subprocess.run(cmd, cwd=repo, check=True, env=ENV)
    (repo / "bad.json").write_text("{not json")
    subprocess.run(["git", "add", "bad.json"], cwd=repo, check=True, env=ENV)
    subprocess.run(["git", "commit", "-q", "-m", "task"], cwd=repo, check=True, env=ENV)
    feature = repo / ".speed/features/f"
    (feature / "tasks").mkdir(parents=True)
    (feature / "tasks/1.json").write_text('{"id": "1", "branch": "speed/f/task-1"}')
    (feature / "base_branch").write_text("trunk\n")
    env = dict(ENV, PROJECT_ROOT=str(repo), FEATURE_DIR=str(feature), TASKS_DIR=str(feature / "tasks"))
    r = subprocess.run(
        ["bash", "-c", (f'source "{LIB}/colors.sh"; source "{LIB}/log.sh"; source "{LIB}/git.sh"; '
                       f"eval \"$(sed -n '/^gate_syntax_check()/,/^}}/p' '{LIB}/gates.sh')\"; "
                       f'gate_syntax_check 1 "{repo}"; echo "rc=$?"')],
        check=False, capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr
    assert "JSON syntax error in: bad.json" in out, out
    assert "unknown revision" not in out
