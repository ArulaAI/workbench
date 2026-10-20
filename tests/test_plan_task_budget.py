"""speed plan --max-tasks N caps the number of tasks the Architect produces.

The Architect is told the budget; a plan over it gets one merge call; a plan
still over it stops instead of running with more tasks than asked for; and
coverage repair only adds tasks the budget has room for.
"""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "lib"
PLAN = LIB / "cmd" / "plan.sh"


def _funcs(*names: str) -> str:
    return "; ".join(f"eval \"$(sed -n '/^{n}()/,/^}}/p' '{PLAN.as_posix()}' | tr -d '\\r')\"" for n in names)


def _bash(script: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ["PATH"], "NO_COLOR": "1", **(env_extra or {})}
    prelude = f'source "{LIB.as_posix()}/colors.sh"; source "{LIB.as_posix()}/log.sh"; EXIT_GATE_FAILURE=2; '
    return subprocess.run(["bash", "-c", prelude + script], check=False, capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=60)


def _plan(n: int) -> dict:
    return {"tasks": [{"id": str(i), "title": f"T{i}", "description": "d", "files_touched": [f"f{i}.py"],
                       "depends_on": [], "agent_model": "sonnet"} for i in range(1, n + 1)],
            "validation": [{"severity": "note", "issue": "i", "product_requirement": "p", "recommendation": "r"}],
            "cross_cutting_concerns": ["UUIDs"]}


def _enforce(tmp_path: Path, planned: int, merged: int | None, budget: str = "3") -> subprocess.CompletedProcess:
    if merged is not None:
        (tmp_path / "merged.json").write_text(json.dumps({"tasks": _plan(merged)["tasks"]}))
    script = (
        _funcs("_plan_task_budget_text", "_plan_enforce_task_budget") + "; "
        f'max_tasks="{budget}"; LOGS_DIR="{tmp_path.as_posix()}"; arch_agent=a; arch_schema=s; '
        'plan_spec_paths=(x); plan_spec_contents=("spec"); plan_spec_labels=("Tech Spec"); '
        f'_run_architect_phase() {{ printf "%s" "$2" > "{tmp_path.as_posix()}/msg"; echo "$1" >> "{tmp_path.as_posix()}/calls"; '
        f'cat "{tmp_path.as_posix()}/merged.json"; }}; '
        f"parsed_architect='{json.dumps(_plan(planned))}'; "
        '_plan_enforce_task_budget; echo "RESULT=$(echo "$parsed_architect" | jq -c .)"'
    )
    return _bash(script)


def _result(r: subprocess.CompletedProcess) -> dict:
    return json.loads(next(ln for ln in r.stdout.splitlines() if ln.startswith("RESULT="))[7:])


def test_plan_within_budget_makes_no_extra_call(tmp_path):
    r = _enforce(tmp_path, planned=3, merged=None)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (tmp_path / "calls").exists()
    assert len(_result(r)["tasks"]) == 3


def test_plan_over_budget_is_merged_and_keeps_validation(tmp_path):
    r = _enforce(tmp_path, planned=6, merged=3)
    assert r.returncode == 0, r.stdout + r.stderr
    plan = _result(r)
    assert len(plan["tasks"]) == 3
    # The merge reply had no validation or concerns: the first call's are kept
    assert plan["validation"][0]["issue"] == "i" and plan["cross_cutting_concerns"] == ["UUIDs"]
    msg = (tmp_path / "msg").read_text()
    assert "at most 3 task(s)" in msg and "Current Plan (6 tasks" in msg and "spec" in msg
    assert (tmp_path / "calls").read_text().count("merge to budget") == 1


def test_plan_still_over_budget_stops(tmp_path):
    r = _enforce(tmp_path, planned=6, merged=5)
    assert r.returncode == 2
    assert "could not fit the plan into 3" in r.stdout + r.stderr
    assert (tmp_path / "architect-over-budget.json").exists()


def test_no_budget_means_no_instruction():
    r = _bash(_funcs("_plan_task_budget_text") + '; max_tasks=""; printf "[%s]" "$(_plan_task_budget_text)"')
    assert r.stdout == "[]"
    r = _bash(_funcs("_plan_task_budget_text") + '; max_tasks=4; _plan_task_budget_text')
    assert "## Task Budget" in r.stdout and "at most 4 task(s)" in r.stdout


def _repair(tmp_path: Path, planned: int, added: int, budget: str) -> subprocess.CompletedProcess:
    (tmp_path / "add.json").write_text(json.dumps({"tasks": _plan(added)["tasks"]}))
    script = (
        _funcs("_plan_task_details", "_repair_coverage_gaps") + "; "
        f'max_tasks="{budget}"; _cov_critical=1; '
        '_cov_gaps=\'[{"severity":"critical","spec":"tech","section":"S","requirement":"r","explanation":"e"}]\'; '
        'tech_spec_content=spec; product_spec_content=""; design_spec_content=""; '
        f'_run_architect_phase() {{ printf "%s" "$2" > "{tmp_path.as_posix()}/msg"; cat "{tmp_path.as_posix()}/add.json"; }}; '
        f"parsed_architect='{json.dumps(_plan(planned))}'; "
        '_repair_coverage_gaps; echo "RESULT=$(echo "$parsed_architect" | jq -c .)"'
    )
    return _bash(script)


def test_repair_with_a_full_budget_adds_nothing(tmp_path):
    r = _repair(tmp_path, planned=3, added=1, budget="3")
    assert len(_result(r)["tasks"]) == 3
    assert "budget of 3 is used up" in r.stdout + r.stderr
    assert not (tmp_path / "msg").exists()


def test_repair_is_told_the_room_and_rejects_more(tmp_path):
    r = _repair(tmp_path, planned=3, added=1, budget="4")
    assert len(_result(r)["tasks"]) == 4
    assert "Add at most 1 task(s)" in (tmp_path / "msg").read_text()

    r = _repair(tmp_path, planned=3, added=2, budget="4")
    assert len(_result(r)["tasks"]) == 3
    assert "None added" in r.stdout + r.stderr


def test_budget_is_part_of_the_architect_cache_key():
    source = PLAN.read_text(encoding="utf-8")
    key = source[source.index("architect_cache_hash=$({"):][:600]
    assert "${max_tasks:-}" in key


def test_toml_plan_max_tasks_is_emitted(tmp_path):
    toml = tmp_path / "speed.toml"
    toml.write_text("[plan]\nmax_tasks = 5\n")
    out = subprocess.run(["python3", str(LIB / "toml.py"), str(toml)], check=False, capture_output=True,
                         text=True, encoding="utf-8").stdout
    assert "TOML_PLAN_MAX_TASKS='5'" in out
