from lib.eval_report import reclassify_blocked_upstream


def _r(id_, status):
    return {"id": id_, "kind": "scenario", "status": status}


def test_records_dependency_without_hiding_downstream_failure():
    results = [_r("AC-01", "fail"), _r("AC-04", "fail")]
    edges = {"AC-01": [], "AC-04": ["AC-01"]}
    out = reclassify_blocked_upstream(results, edges)
    by = {r["id"]: r for r in out}
    assert by["AC-01"]["status"] == "fail"                 # root cause stays fail
    assert by["AC-04"]["status"] == "fail"
    assert by["AC-04"]["failed_dependencies"] == ["AC-01"]


def test_does_not_block_when_upstream_passed():
    results = [_r("AC-01", "pass"), _r("AC-04", "fail")]
    edges = {"AC-01": [], "AC-04": ["AC-01"]}
    out = reclassify_blocked_upstream(results, edges)
    by = {r["id"]: r for r in out}
    assert by["AC-04"]["status"] == "fail"                 # genuine downstream failure
    assert "root_cause" not in by["AC-04"]


def test_passing_scenario_untouched():
    results = [_r("AC-01", "fail"), _r("AC-04", "pass")]
    edges = {"AC-04": ["AC-01"]}
    out = reclassify_blocked_upstream(results, edges)
    assert {r["id"]: r["status"] for r in out}["AC-04"] == "pass"


def test_transitive_chain_records_failed_dependencies():
    # C depends on B depends on A; A and B fail.
    results = [_r("A", "fail"), _r("B", "fail"), _r("C", "fail")]
    edges = {"A": [], "B": ["A"], "C": ["B"]}
    out = reclassify_blocked_upstream(results, edges)
    by = {r["id"]: r for r in out}
    assert by["B"]["status"] == "fail" and by["B"]["failed_dependencies"] == ["A"]
    assert by["C"]["status"] == "fail" and by["C"]["failed_dependencies"] == ["B", "A"]
    assert by["A"]["status"] == "fail"


import json
from pathlib import Path
from lib.eval_report import build_report


def test_build_report_preserves_failures_and_stays_unaccepted(tmp_path):
    feature_dir = tmp_path / "feat"
    tasks = feature_dir / "tasks"
    tasks.mkdir(parents=True)
    spec = feature_dir / "tests.md"
    spec.write_text(
        "## Scenario Catalog\n\n### Area\n\n"
        "| ID | Scenario | Level | Expected |\n"
        "|----|----------|-------|----------|\n"
        "| AC-01 | create | unit | pass |\n"
        "| AC-04 | complete | unit | pass |\n",
        encoding="utf-8",
    )
    # test-plan.json declares AC-04 depends on AC-01, owned by task 4.
    (feature_dir / "test-plan.json").write_text(json.dumps({
        "test_spec": str(spec),
        "test_cases": [
            {"scenario_id": "AC-01", "owner_task_id": "4", "depends_on_scenarios": []},
            {"scenario_id": "AC-04", "owner_task_id": "4", "depends_on_scenarios": ["AC-01"]},
        ],
    }), encoding="utf-8")
    # Owner task 4 reports both scenarios failing on the integrated tree.
    (tasks / "4.json").write_text(json.dumps({
        "id": "4", "task_type": "implementation", "required_test_cases": ["AC-01", "AC-04"],
        "scenario_results": [
            {"scenario_id": "AC-01", "status": "fail"},
            {"scenario_id": "AC-04", "status": "fail"},
        ],
    }), encoding="utf-8")

    report = build_report("feat", tmp_path, tasks, spec, None)
    by = {r["id"]: r for r in report["results"] if r["kind"] == "scenario"}
    assert by["AC-01"]["status"] == "fail"
    assert by["AC-04"]["status"] == "fail"
    assert by["AC-04"]["failed_dependencies"] == ["AC-01"]
    assert by["AC-04"]["task_id"] == "4"
    assert report["summary"]["blocked_upstream"] == 0
    assert report["summary"]["fail"] == 2
    assert report["accepted"] is False
