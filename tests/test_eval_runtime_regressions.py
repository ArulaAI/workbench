#!/usr/bin/env python3
"""Regressions for task-batch attribution, read-path validation, criterion
verification without a runner, and array values in the fallback TOML parser.

Each case here reproduces a defect where missing or unattributable evidence
was reported as a pass, or where a configuration error was reported as a
failing test run.
"""
import json
import os
import shlex
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.criteria_verify import verify_criteria
from lib.eval_runtime import prepare
from lib.eval_report import _semantic_results
from lib.toml import _hand_parse

from test_eval_regressions import Project, project  # noqa: F401  (pytest fixture)


def scenario(report, scenario_id):
    return next(r for r in report["results"] if r["id"] == scenario_id)


def records(run, source=None):
    results = json.loads((run / "scenario-results.json").read_text())["results"]
    return [r for r in results if source is None or r["source"] == source]


# ── task batch attribution ───────────────────────────────────


def test_passing_task_batch_does_not_overwrite_a_failing_mapping_result(project):
    """A task batch cannot attribute its outcome to an individual scenario.

    The mapping ran AC-01 directly and it failed. The task's own selectors
    point at a passing test, and every owned scenario used to receive that
    passing outcome, so green task evidence landed on top of a red result.
    """
    project.mapping(selector="tests/test_books.py::test_fail")
    project.task["test_selectors"] = ["tests/test_books.py::test_pass"]
    project.save_task()
    project.commit()

    run, report = project.evaluate()

    assert records(run, source="task") == []
    assert scenario(report, "AC-01")["status"] == "fail"
    assert not report["accepted"]


def test_failing_task_batch_still_reaches_a_mapped_scenario(project):
    """The opposite direction: a failure must not be hidden either.

    Mapped evidence passed, the task's own selectors failed. Skipping the
    batch entirely for mapped scenarios would lose that failure.
    """
    project.mapping(selector="tests/test_books.py::test_pass")
    project.task["test_selectors"] = ["tests/test_books.py::test_fail"]
    project.save_task()
    project.commit()

    run, report = project.evaluate()

    assert [r["scenario_id"] for r in records(run, source="task")] == ["AC-01"]
    assert records(run, source="task")[0]["status"] == "fail"
    assert scenario(report, "AC-01")["status"] == "fail"
    assert not report["accepted"]


TWO_SCENARIOS = """# Test Spec: Books
## Scenario Catalog
| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| AC-01 | Read a book | unit | Correct book |
| AC-02 | Delete a book | unit | Book removed |

## Acceptance Traceability
| RFC acceptance criterion | Covering scenarios |
|---|---|
| Read a book | AC-01 |
| Delete a book | AC-02 |

## Execution and Evidence
| Scenario | Selector | Command |
|---|---|---|
| AC-01 | `tests/test_books.py::test_pass` | |
| AC-02 | | |
"""


def test_scenario_with_an_empty_selector_cell_is_never_passed_by_a_task_batch(project):
    """The case the template promises: a Selector cell left deliberately empty
    declares that nothing examines the scenario. One green run of an unrelated
    selector used to report it as a pass."""
    project.spec.write_text(TWO_SCENARIOS)
    project.task["required_test_cases"] = ["AC-01", "AC-02"]
    project.task["test_selectors"] = ["tests/test_books.py::test_pass"]
    project.save_task()
    project.commit()

    run, report = project.evaluate()

    assert records(run, source="task") == []
    assert scenario(report, "AC-02")["status"] == "unverifiable"
    assert not report["accepted"]


def test_unmapped_owned_scenario_still_uses_the_task_batch(project):
    """Guard against over-correcting: with no mapping row, the task's own
    selectors remain the declared evidence for the scenario it owns."""
    project.task["test_selectors"] = ["tests/test_books.py::test_pass"]
    project.save_task()
    project.commit()

    run, report = project.evaluate()

    assert [r["scenario_id"] for r in records(run, source="task")] == ["AC-01"]
    assert scenario(report, "AC-01")["status"] == "pass"


# ── read paths leaving the project ───────────────────────────


@pytest.mark.parametrize("keyword", ["test_spec", "manual_path"])
def test_symlinked_read_path_is_rejected(project, tmp_path, keyword):
    """A symlinked spec was read and pasted into the evaluator prompt verbatim,
    so anything the link pointed at was shipped to the model provider."""
    secret = tmp_path / "outside-the-project.txt"
    secret.write_text("PRIVATE KEY MATERIAL")
    link = project.root / f"specs/tests/linked-{keyword}.md"
    link.symlink_to(secret)

    kwargs = {"test_spec": project.spec, "manual_path": None}
    kwargs[keyword] = link

    with pytest.raises(ValueError, match="symlink|leaves the project"):
        prepare(project.root, project.feature, project.state, kwargs["test_spec"],
                manual_path=kwargs["manual_path"])


def test_read_path_outside_the_project_is_rejected(project, tmp_path):
    outside = tmp_path / "elsewhere.md"
    outside.write_text("# Not this project\n")

    with pytest.raises(ValueError, match="leaves the project"):
        prepare(project.root, project.feature, project.state, outside)


# ── criterion verification without a runner ──────────────────


def test_legacy_test_criterion_without_a_runner_records_existence_only(tmp_path):
    """Grounding and traceability retain their existence-only check. Eval
    requires execution evidence through its separate criterion path."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_thing.py").write_text("def test_ok():\n    assert True\n")
    task = {"id": "1", "files_touched": ["tests/test_thing.py"],
            "acceptance_criteria": [{"criterion": "it works", "verify_by": "test"}]}

    result = verify_criteria(task, str(tmp_path))["criteria_results"][0]

    assert result["status"] == "pass"
    assert "file existence only" in result["evidence"]
    evaluated = _semantic_results([task], tmp_path, {"test_commands": [], "gates": []},
                                  tmp_path / "evidence")[0]
    assert evaluated["status"] == "unverifiable"


def test_test_criterion_with_a_runner_still_passes(tmp_path):
    """Guard against over-correcting: a configured runner that passes is a pass."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_thing.py").write_text("def test_ok():\n    assert True\n")
    task = {"id": "1", "files_touched": ["tests/test_thing.py"],
            "acceptance_criteria": [{"criterion": "it works", "verify_by": "test"}]}

    result = verify_criteria(task, str(tmp_path),
                             test_command="true")["criteria_results"][0]

    assert result["status"] == "pass"


# ── arrays in the fallback TOML parser ───────────────────────


def write_toml(tmp_path, text):
    path = tmp_path / "speed.toml"
    path.write_text(text)
    return str(path)


def test_hand_parsed_array_is_a_list_not_its_source_text(tmp_path):
    """Without array support the emitted command was the literal text
    '["pytest -q", "npm test"]', which bash then failed to parse, marking
    every scenario failed instead of reporting a configuration error."""
    path = write_toml(tmp_path, '[eval]\ntest_commands = ["pytest -q", "npm test"]\n')

    data = _hand_parse(path)

    assert data["eval"]["test_commands"] == ["pytest -q", "npm test"]


def test_hand_parsed_array_may_span_lines_and_carry_comments(tmp_path):
    path = write_toml(tmp_path, '[agent]\ncli_models = [\n  "opus",\n  "sonnet",  # note\n]\n')

    assert _hand_parse(path)["agent"]["cli_models"] == ["opus", "sonnet"]


def test_unterminated_array_is_an_error_not_a_silent_string(tmp_path):
    path = write_toml(tmp_path, '[eval]\ntest_commands = ["pytest -q",\n')

    with pytest.raises(ValueError, match="Unterminated array"):
        _hand_parse(path)


NEEDS_ARG = (shlex.quote(sys.executable)
             + " -c 'import sys; sys.exit(0 if len(sys.argv) > 1 else 1)'")


def _test_task():
    return {"id": "1", "files_touched": ["tests/test_thing.py"],
            "acceptance_criteria": [{"criterion": "it works", "verify_by": "test"}]}


def _with_a_test_file(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_thing.py").write_text("def test_ok():\n    assert True\n")


def test_a_change_with_no_test_file_is_a_failure_not_a_silence(tmp_path):
    """Whether a change ships a test is knowable without a runner.

    Checking the runner first sent this decisive finding to "unverifiable",
    which the report counts as not examined. A missing test is a gap that was
    examined, and it must stay in the failing column.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src/thing.py").write_text("x = 1\n")
    task = {"id": "1", "files_touched": ["src/thing.py"],
            "acceptance_criteria": [{"criterion": "it works", "verify_by": "test"}]}

    result = verify_criteria(task, str(tmp_path))["criteria_results"][0]

    assert result["status"] == "fail", result


def test_a_placeholderless_test_command_is_given_the_file_it_reports_on(tmp_path):
    """The command declares no {file}, so the file is appended. It used to be
    dropped: the configured suite ran unscoped, once per file, and each run was
    recorded as "Tests pass: <that file>"."""
    _with_a_test_file(tmp_path)

    result = verify_criteria(_test_task(), str(tmp_path),
                             test_command=NEEDS_ARG)["criteria_results"][0]

    assert result["status"] == "pass", result


def test_a_test_command_that_cannot_be_scoped_is_unverifiable(tmp_path):
    """Nothing can be said about one file from a command whose selectors would
    land on whichever simple command comes last."""
    _with_a_test_file(tmp_path)

    result = verify_criteria(_test_task(), str(tmp_path),
                             test_command="pytest -q ; echo done")["criteria_results"][0]

    assert result["status"] == "unverifiable", result
    assert "{selectors}" in result["evidence"], result["evidence"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
