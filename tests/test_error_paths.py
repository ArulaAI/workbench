"""Wrong input and broken state fail fast with a clear message and exit 3.

Found by an unhappy-path sweep: planning a product spec ran the whole AI plan,
missing input exited 1 in validate and guardian (1 also means REJECTED there),
a corrupt task file printed raw jq errors with exit 5, status showed a cyclic
plan as normal, and an agent CLI failure was reported only as "invalid JSON".
"""

import json
import subprocess
from pathlib import Path

SPEED_DIR = Path(__file__).resolve().parent.parent
SPEED = SPEED_DIR / "speed"
LIB = SPEED_DIR / "lib"
ENV = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "NO_COLOR": "1", "HOME": "/tmp",
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _project(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    (repo / "specs/product").mkdir(parents=True)
    (repo / "specs/tech").mkdir(parents=True)
    (repo / "specs/product/x.md").write_text("# X\n")
    (repo / "specs/tech/x.md").write_text("# X RFC\n")
    (repo / "specs/product/overview.md").write_text("# Vision\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=ENV)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=ENV)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, env=ENV)
    return repo


def _speed(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(SPEED), *args], cwd=repo, capture_output=True, text=True, env=ENV, timeout=120)


def test_plan_refuses_a_product_spec_without_calling_an_agent(tmp_path):
    r = _speed(_project(tmp_path), "plan", "specs/product/x.md")
    out = r.stdout + r.stderr
    assert r.returncode == 3, out
    assert "Not a tech spec" in out and "speed plan specs/tech/x.md" in out
    assert "Guardian" not in out  # stopped before any agent ran


def test_missing_input_is_exit_3_in_validate_and_guardian(tmp_path):
    repo = _project(tmp_path)
    assert _speed(repo, "validate", "specs/nope").returncode == 3
    assert _speed(repo, "guardian", "specs/nope.md").returncode == 3


def _feature(repo: Path, tasks: dict) -> None:
    d = repo / ".speed/features/f/tasks"
    d.mkdir(parents=True)
    for tid, body in tasks.items():
        (d / f"{tid}.json").write_text(body if isinstance(body, str) else json.dumps(body))
    (repo / ".speed/active_feature").write_text("f\n")


def _task(tid: str, deps: list[str]) -> dict:
    return {"id": tid, "title": f"T{tid}", "description": "d", "acceptance_criteria": "",
            "status": "pending", "depends_on": deps, "files_touched": []}


def test_corrupt_task_file_is_named_and_exit_3(tmp_path):
    repo = _project(tmp_path)
    _feature(repo, {"1": _task("1", []), "2": "{ not json"})
    for cmd in (("status",), ("run",), ("verify",)):
        r = _speed(repo, *cmd)
        out = r.stdout + r.stderr
        assert r.returncode == 3, (cmd, out)
        assert "not valid JSON" in out and "2.json" in out, (cmd, out)
        assert "jq: parse error" not in out, (cmd, out)


def test_status_warns_about_a_cycle_and_run_refuses_it(tmp_path):
    repo = _project(tmp_path)
    _feature(repo, {"1": _task("1", ["2"]), "2": _task("2", ["1"])})
    s = _speed(repo, "status")
    assert s.returncode == 0 and "dependency cycle" in (s.stdout + s.stderr)
    r = _speed(repo, "run")
    assert r.returncode == 3 and "circular dependencies" in (r.stdout + r.stderr)


def test_agent_cli_failure_text_is_shown():
    script = (f"eval \"$(sed -n '/^agent_output_first_line()/,/^}}/p' '{LIB}/provider.sh')\"; "
              'agent_output_first_line "$(printf "\\n\\nThere is an issue with the selected model (x).\\nmore")"')
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV).stdout
    assert out.strip() == "There is an issue with the selected model (x)."
    assert "The agent said:" in (LIB / "provider.sh").read_text()
