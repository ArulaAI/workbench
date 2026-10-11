"""Task dependency graphs: valid ones sort, invalid ones are named precisely.

task_topo_sort reported a dependency on a missing task as a "cycle", and listed
every blocked task as "in cycle" instead of the loop itself. speed plan left a
cyclic plan installed after rejecting it.
"""

import json
import subprocess
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"
PLAN = LIB / "cmd" / "plan.sh"
ENV = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "NO_COLOR": "1"}


def _sort(tmp_path: Path, graph: dict) -> subprocess.CompletedProcess:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    for tid, deps in graph.items():
        (tasks / f"{tid}.json").write_text(json.dumps({"id": tid, "depends_on": deps}))
    script = (f'source "{LIB}/colors.sh"; source "{LIB}/log.sh"; source "{LIB}/tasks.sh"; '
              'task_topo_sort')
    return subprocess.run(["bash", "-c", script], check=False, capture_output=True, text=True,
                          env=dict(ENV, TASKS_DIR=str(tasks)))


def _order(r: subprocess.CompletedProcess) -> list[str]:
    return [l for l in r.stdout.splitlines() if l.strip()]


def test_chain_and_diamond_sort_with_dependencies_first(tmp_path):
    r = _sort(tmp_path, {"1": [], "2": ["1"], "3": ["1"], "4": ["2", "3"]})
    assert r.returncode == 0, r.stderr
    order = _order(r)
    assert sorted(order) == ["1", "2", "3", "4"]
    for task, dep in (("2", "1"), ("3", "1"), ("4", "2"), ("4", "3")):
        assert order.index(dep) < order.index(task)


def test_numeric_ids_in_depends_on_are_accepted(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "1.json").write_text('{"id": "1", "depends_on": []}')
    (tasks / "2.json").write_text('{"id": "2", "depends_on": [1]}')
    script = f'source "{LIB}/colors.sh"; source "{LIB}/log.sh"; source "{LIB}/tasks.sh"; task_topo_sort'
    r = subprocess.run(["bash", "-c", script], check=False, capture_output=True, text=True, env=dict(ENV, TASKS_DIR=str(tasks)))
    assert r.returncode == 0 and _order(r) == ["1", "2"], r.stderr


def test_single_task_with_no_dependencies(tmp_path):
    r = _sort(tmp_path, {"1": []})
    assert r.returncode == 0 and _order(r) == ["1"]


def test_direct_cycle_is_named(tmp_path):
    r = _sort(tmp_path, {"1": ["2"], "2": ["1"]})
    assert r.returncode == 1
    assert "Dependency cycle" in r.stderr
    assert "1 → 2 → 1" in r.stderr or "2 → 1 → 2" in r.stderr


def test_indirect_cycle_is_named_and_blocked_tasks_listed_separately(tmp_path):
    r = _sort(tmp_path, {"1": ["3"], "2": ["1"], "3": ["2"], "4": ["3"], "5": []})
    assert r.returncode == 1
    cycle_line = next(l for l in r.stderr.splitlines() if "Dependency cycle" in l)
    loop = cycle_line.split(": ", 1)[1].split(" → ")
    assert loop[0] == loop[-1] and set(loop) == {"1", "2", "3"}  # task 4 is blocked, not in the loop
    assert "Tasks that cannot start: " in r.stderr and "4" in r.stderr.split("cannot start: ")[1]


def test_self_dependency_is_a_cycle(tmp_path):
    r = _sort(tmp_path, {"1": ["1"], "2": []})
    assert r.returncode == 1 and "1 → 1" in r.stderr


def test_missing_dependency_is_named_not_called_a_cycle(tmp_path):
    r = _sort(tmp_path, {"1": [], "2": ["9"]})
    assert r.returncode == 1
    assert "Task 2 depends on task 9, which does not exist" in r.stderr
    assert "cycle" not in r.stderr.lower()


def test_plan_rejects_an_unresolvable_graph_without_installing_it():
    source = PLAN.read_text()
    block = source[source.index("# The unusable plan is moved aside"):][:900]
    assert "task_topo_sort" in block
    assert 'mv "${TASKS_DIR}"/*.json "$_rejected"/' in block
    assert "No plan was installed" in block and 'exit "$EXIT_GATE_FAILURE"' in block


def test_bridge_auto_patch_never_adds_an_edge_that_closes_a_loop():
    # The auto-patch checks reachability before adding source -> affected.
    source = PLAN.read_text()
    patch = source[source.index("# Never add an edge that closes a loop"):][:600]
    assert '_plan_task_depends_on "$source_task" "$affected_task"' in patch
