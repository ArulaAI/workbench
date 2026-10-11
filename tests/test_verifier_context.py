"""The plan verifier must see the whole spec, every task and the contract.

verify used to cut its context at a fixed token budget, with tasks in text order
(1, 10, 11 ... 2, 20 ... 9). On a 28-task feature the cut fell inside task 5, so the
verifier reported work owned by tasks 6 to 9 as missing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.context.assembly import assemble_verifier


def _tasks(n: int) -> list[dict]:
    # Shuffled the way os.listdir + sorted() returns them: text order.
    ids = sorted(str(i) for i in range(1, n + 1))
    return [{"id": i, "title": f"Title {i}", "description": "x " * 400,
             "files_touched": [f"src/f{i}.ts"]} for i in ids]


def _small_budget() -> dict:
    return {"context": {"budgets": {"verifier": 2000}}}


def test_tasks_are_listed_in_numeric_order():
    out = assemble_verifier("spec", _tasks(12))
    headers = [line for line in out.splitlines() if line.startswith("### Task ")]
    assert [h.split()[2].rstrip(":") for h in headers] == [str(i) for i in range(1, 13)]


def test_over_budget_keeps_every_task_and_the_contract():
    contract = {"entities": [{"name": "Payment"}]}
    out = assemble_verifier("spec " * 2000, _tasks(28), contract=contract,
                            cross_cutting_concerns=["c " * 5000], config=_small_budget())
    for i in range(1, 29):
        assert f"### Task {i}: Title {i}" in out
    assert '"Payment"' in out
    assert "spec " * 2000 in out


def test_optional_sections_are_trimmed_not_the_plan():
    tasks = _tasks(3)
    out = assemble_verifier("spec", tasks, cross_cutting_concerns=["concern " * 20000],
                            config={"context": {"budgets": {"verifier": 3000}}})
    assert "### Task 3: Title 3" in out
    assert out.count("concern ") < 20000


def test_under_budget_output_has_everything():
    out = assemble_verifier("spec", _tasks(2), cross_cutting_concerns=["keep me"],
                            contract={"entities": []})
    assert "keep me" in out and "## Data Model Contract" in out
