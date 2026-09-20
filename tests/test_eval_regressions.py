"""Regression cases for evaluation evidence, state, boundaries and CLI behavior.

All projects and command artifacts live under pytest's temporary directory.
CLI cases bypass only the unrelated global dependency preflight (LLM/grammar
packages); argument dispatch, locking and evaluation use the real entrypoint.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import pytest

from lib.eval_execution import run_command
from lib.eval_report import build_report, write_report
from lib.eval_runtime import atomic_json, execute, finish, prepare


REPO = Path(__file__).resolve().parents[1]
PYTEST = shlex.quote(sys.executable) + " -m pytest -q"
SPEC = """# Test Spec: Books
## Scenario Catalog
| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| AC-01 | Read a book | unit | Correct book |

## Acceptance Traceability
| RFC acceptance criterion | Covering scenarios |
|---|---|
| Read a book | AC-01 |
"""
TESTS = """import os, time
from pathlib import Path
import pytest

def test_pass():
    assert 1 + 1 == 2

def test_fail():
    assert False

@pytest.mark.skip(reason='unavailable')
def test_skipped():
    assert False

@pytest.mark.parametrize('value', [1, 2], ids=['1', 'two words, three'])
def test_parameter(value):
    assert value > 0

class TestGroup:
    def test_member(self):
        assert True

def test_wait():
    marker = Path('.speed/started')
    marker.write_text('started')
    while not Path('.speed/release').exists():
        time.sleep(0.02)
    assert False
"""


class Project:
    def __init__(self, root):
        self.root = root
        self.feature = root / ".speed/features/books"
        self.tasks = self.feature / "tasks"
        self.tasks.mkdir(parents=True)
        self.state = self.feature / "state.json"
        atomic_json(self.state, {"status": "completed"})
        self.spec = root / "specs/tests/books.md"
        self.spec.parent.mkdir(parents=True)
        self.spec.write_text(SPEC)
        (self.feature / "test_spec_path").write_text(str(self.spec))
        (root / "tests").mkdir()
        (root / "tests/test_books.py").write_text(TESTS)
        (root / ".gitignore").write_text(".speed/\n__pycache__/\n.pytest_cache/\n")
        (root / "AGENTS.md").write_text("## Quality Gates\ntest: " + PYTEST + "\n")
        self.task = {"id": "1", "status": "done", "required_test_cases": ["AC-01"],
                     "test_selectors": ["tests/test_books.py::test_pass"],
                     "files_touched": ["tests/test_books.py"], "acceptance_criteria": []}
        self.save_task()
        self.git("init", "-q")
        self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.PIPE, text=True).strip()

    def commit(self):
        self.git("add", "-A")
        self.git("-c", "user.name=Tests", "-c", "user.email=tests@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "fixture", "--allow-empty")

    def save_task(self):
        atomic_json(self.tasks / "1.json", self.task)

    def mapping(self, selector="tests/test_books.py::test_pass", criterion=""):
        self.spec.write_text(self.spec.read_text() + "\n## Execution and Evidence\n"
                             "| Scenario | Selector | Command | Criterion |\n|---|---|---|---|\n"
                             f"| AC-01 | `{selector}` | | {criterion} |\n")

    def evaluate(self, **kwargs):
        run = prepare(self.root, self.feature, self.state, self.spec, **kwargs)
        execute(run)
        report = build_report("books", self.root, run / "tasks", run / "test-spec.md",
                              scenario_results=json.loads((run / "scenario-results.json").read_text())["results"],
                              task_id=kwargs.get("task_id"), test_plan_path=run / "test-plan.json",
                              runner_config=json.loads((run / "runner-config.json").read_text()),
                              evidence_dir=run / "criteria-commands",
                              context=json.loads((run / "context.json").read_text()))
        write_report(report, run)
        finish(run)
        return run, report


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in ("SPEED_AGENT_FILE", "SPEED_EVAL_TEST_COMMAND", "SPEED_EVAL_STRICT", "SPEED_EVAL_FILE_DEFECTS"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "project with spaces"
    root.mkdir()
    return Project(root)


@pytest.fixture
def cli(tmp_path):
    entry = tmp_path / "speed-test"
    source = (REPO / "speed").read_text()
    source = source.replace('SCRIPT_DIR="$(cd "$(dirname "$_speed_source")" && pwd)"',
                            "SCRIPT_DIR=" + shlex.quote(str(REPO)))
    source = source.replace('source "${SCRIPT_DIR}/lib/deps.sh"', "# preflight omitted in isolated CLI tests")
    entry.write_text(source)
    return entry


def command(project, cli, *args):
    env = os.environ.copy()
    env.update(SPEED_PROJECT_ROOT=str(project.root), SPEED_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
    return ["bash", str(cli), "eval", "--feature", "books", "--skip-judge", *args], env


def invoke(project, cli, *args):
    argv, env = command(project, cli, *args)
    return subprocess.run(argv, env=env, cwd=project.root, text=True, capture_output=True, timeout=30)


def result(report, id_="AC-01"):
    return next(row for row in report["results"] if row["id"] == id_)


@pytest.mark.parametrize("selector,base", [
    ("tests/test_books.py::test_skipped", PYTEST),
    ("tests/test_books.py::test_pass", "true"),
    ("tests/test_books.py::test_pass", PYTEST + " --help"),
    ("--help", PYTEST),
])
def test_noop_or_skip_never_passes(project, selector, base):
    outcome = run_command(base, [selector], project.root, project.feature / "evidence")
    assert outcome["status"] != "pass"


def test_conflicting_mapping_preserves_failure(project):
    project.mapping()
    # Both tests are explicitly required for this scenario. Legacy task batches
    # no longer contribute unrelated failures to a fully mapped scenario.
    with project.spec.open("a") as stream:
        stream.write("| AC-01 | `tests/test_books.py::test_fail` | | |\n")
    project.task["test_selectors"] = ["tests/test_books.py::test_fail"]
    project.save_task()
    project.commit()
    _, report = project.evaluate()
    assert not report["accepted"]
    assert result(report)["status"] == "fail"
    assert {r["status"] for r in result(report)["executions"]} == {"pass", "fail"}


@pytest.mark.parametrize("gap", ["unknown", "empty", "unmapped", "partial", "range"])
def test_required_coverage_gaps_block_acceptance(project, gap):
    if gap == "unknown":
        project.task["acceptance_criteria"] = [{"criterion": "missing", "scenario_ids": ["AC-99"]}]
        project.save_task()
    elif gap == "empty":
        project.spec.write_text("")
    elif gap == "unmapped":
        project.spec.write_text(SPEC + "| Additional requirement | None |\n")
    elif gap == "partial":
        project.spec.write_text(SPEC.replace("| Read a book | AC-01 |", "| Read a book | AC-01 (partial, GAP-01) |"))
    else:
        project.spec.write_text(SPEC.replace("| Read a book | AC-01 |", "| Read a book | AC-01 to AC-03 |"))
    project.commit()
    _, report = project.evaluate()
    assert not report["accepted"]
    assert any(r["id"].startswith(("COVERAGE-", "MISSING-")) for r in report["results"])


def test_criterion_filename_cannot_execute_shell(project):
    name = "test_one;touch injected-marker;.py"
    (project.root / "tests" / name).write_text("def test_safe():\n    assert True\n")
    project.task["files_touched"] = ["tests/" + name]
    project.task["acceptance_criteria"] = [{"criterion": "safe", "verify_by": "test"}]
    project.save_task()
    project.mapping(selector="tests/" + name + "::test_safe", criterion="1")
    project.commit()
    _, report = project.evaluate()
    assert result(report)["criteria"][0]["status"] == "pass"
    assert not (project.root / "injected-marker").exists()


@pytest.mark.parametrize("placeholder", ["{file}", '"{file}"', "'{file}'", '"{selectors}"'])
def test_quoted_placeholders_cannot_expand_filename_commands(project, placeholder):
    name = "tests/test_one$(touch injected-marker).py"
    (project.root / name).write_text("def test_safe():\n    assert True\n")
    outcome = run_command(PYTEST + " " + placeholder, [name], project.root, project.feature / "evidence")
    assert outcome["status"] == "pass", outcome
    assert not (project.root / "injected-marker").exists()


@pytest.mark.parametrize("selector", ["tests/test_books.py::test_parameter[1]",
                                     "tests/test_books.py::test_parameter[two words, three]"])
def test_parameter_selectors_are_data(project, selector):
    project.mapping(selector)
    project.task["test_selectors"] = []
    project.save_task()
    project.commit()
    _, report = project.evaluate(task_id="1")
    assert report["accepted"], report
    assert len(result(report)["executions"][0]["tests"]) == 1
    assert "parameter" in result(report)["executions"][0]["tests"][0]["id"]


def test_class_selector_is_discovered(project):
    outcome = run_command(PYTEST, ["tests/test_books.py::TestGroup"], project.root, project.feature / "evidence")
    assert outcome["status"] == "pass", outcome


def test_green_unrelated_pytest_command_does_not_verify_selected_file(project):
    base = PYTEST + " tests/test_books.py::test_pass && true"
    outcome = run_command(base, ["tests/test_unexecuted.py"], project.root, project.feature / "evidence")
    assert outcome["status"] == "unverifiable", outcome


def test_mixed_quoted_and_unquoted_mappings_preserve_every_selector(project):
    project.spec.write_text(SPEC + "\n## Execution and Evidence\n"
                             "| Scenario | Selector | Command |\n|---|---|---|\n"
                             "| AC-01 | `tests/test_books.py::test_pass` tests/test_books.py::test_fail | |\n")
    project.task["test_selectors"] = []
    project.save_task()
    project.commit()
    _, report = project.evaluate()
    assert not report["accepted"] and result(report)["status"] == "fail"
    assert len(result(report)["executions"]) == 2


def test_task_scope_uses_owned_spec_mapping(project):
    project.mapping()
    project.task["test_selectors"] = []
    project.save_task()
    # A task run excludes unrelated feature-wide gates and coverage gaps.
    project.spec.write_text(project.spec.read_text().replace("## Execution", "| Unowned requirement | None |\n\n## Execution"))
    project.commit()
    before = project.state.read_bytes()
    _, report = project.evaluate(task_id="1")
    assert report["accepted"]
    assert project.state.read_bytes() == before


@pytest.mark.parametrize("text", ["{broken", "[]", '{"test_cases":{}}', '{"test_cases":[{}]}'])
def test_malformed_explicit_plan_fails_before_execution(project, cli, text):
    plan = project.feature / "override.json"
    plan.write_text(text)
    run = invoke(project, cli, "--strict", "--no-defects", "--test-plan", str(plan))
    assert run.returncode == 3, run.stderr
    assert not (project.feature / "eval/report.json").exists()
    assert json.loads(project.state.read_text())["status"] == "completed"


@pytest.mark.parametrize("target", ["state", "task"])
def test_corrupted_runtime_state_does_not_accept(project, cli, target):
    path = project.state if target == "state" else project.tasks / "1.json"
    path.write_text("{broken")
    run = invoke(project, cli, "--strict", "--no-defects")
    assert run.returncode == 3
    assert not (project.feature / "eval/report.json").exists()


def test_retries_and_legacy_upgrade_retain_evidence(project):
    output = project.feature / "eval"
    output.mkdir()
    atomic_json(output / "report.json", {"legacy": True})
    project.task["test_selectors"] = ["tests/test_books.py::test_fail"]
    project.save_task()
    first, report = project.evaluate()
    assert not report["accepted"]
    original = (first / "report.json").read_bytes()
    project.task["test_selectors"] = ["tests/test_books.py::test_pass"]
    project.save_task()
    second, report = project.evaluate()
    assert report["accepted"]
    assert second != first and (first / "report.json").read_bytes() == original
    legacy = list((output / "runs").glob("legacy-*/report.json"))
    assert len(legacy) == 1 and json.loads(legacy[0].read_text()) == {"legacy": True}
    assert json.loads((output / "report.json").read_text())["run_id"] == second.name


def test_dirty_build_and_idle_state_never_become_integrated_on_retry(project):
    atomic_json(project.state, {"status": "idle", "integration_failure": {"stage": "regression"}})
    (project.root / "tests/test_books.py").write_text(TESTS + "\n# uncommitted change\n")
    for _ in range(2):
        _, report = project.evaluate()
        assert not report["accepted"] and report["commit"] is None
        assert result(report, "BUILD-COMMITTED")["status"] == "unverifiable"
        assert result(report, "BUILD-INTEGRATED")["status"] == "unverifiable"
        state = json.loads(project.state.read_text())
        assert state["status"] == "idle" and state["integration_failure"] == {"stage": "regression"}


def test_unmerged_branch_blocks_full_acceptance(project):
    branch = project.git("symbolic-ref", "--short", "HEAD")
    project.git("checkout", "-qb", "task-work")
    (project.root / "branch-only.txt").write_text("unmerged")
    project.commit()
    project.git("checkout", "-q", branch)
    project.task["branch"] = "task-work"
    project.save_task()
    _, report = project.evaluate()
    assert not report["accepted"]
    assert result(report, "BUILD-INTEGRATED")["status"] == "unverifiable"


def test_aborted_attempt_invalidates_state_and_retry_works(project):
    first = prepare(project.root, project.feature, project.state, project.spec)
    finish(first, failed=True)
    state = json.loads(project.state.read_text())
    assert state["evaluation"]["accepted"] is False
    assert state["evaluation"]["status"] == "failed"
    assert json.loads((first / "attempt.json").read_text())["status"] == "failed"
    second, report = project.evaluate()
    assert report["accepted"] and second != first


@pytest.mark.parametrize("mode", ["toml", "env", "agent"])
def test_criteria_share_effective_runner(project, monkeypatch, mode):
    project.task["acceptance_criteria"] = [{"criterion": "test", "verify_by": "test"}]
    project.save_task()
    project.mapping(criterion="1")
    (project.root / "tests/test_books.py").write_text("def test_pass():\n    assert True\n")
    (project.root / "CLAUDE.md").write_text("## Quality Gates\ntest: false\n")
    if mode in ("toml", "env"):
        (project.root / "AGENTS.md").write_text("## Quality Gates\ntest: false\n")
    if mode == "toml":
        (project.root / "speed.toml").write_text("[eval]\ntest_command = " + json.dumps(PYTEST) + "\n")
    elif mode == "env":
        monkeypatch.setenv("SPEED_EVAL_TEST_COMMAND", PYTEST)
    project.commit()
    _, report = project.evaluate()
    assert report["accepted"], report
    assert result(report)["criteria"][0]["status"] == "pass"


def test_json_cli_and_strict_exit_codes(project, cli):
    success = invoke(project, cli, "--json", "--strict", "--no-defects")
    assert success.returncode == 0, success.stderr
    assert json.loads(success.stdout)["accepted"] is True
    assert json.loads(success.stdout)["results"] == [{"id": "AC-01", "status": "pass"}]
    assert json.loads(success.stdout) == json.loads((project.feature / "eval/report.json").read_text())
    project.task["test_selectors"] = ["tests/test_books.py::test_fail"]
    project.save_task()
    failure = invoke(project, cli, "--json", "--strict", "--no-defects")
    assert failure.returncode == 2, failure.stderr
    assert json.loads(failure.stdout)["accepted"] is False
    assert json.loads(failure.stdout)["results"] == [{"id": "AC-01", "status": "fail"}]
    diagnostic = invoke(project, cli, "--json", "--no-defects")
    assert diagnostic.returncode == 0 and not json.loads(diagnostic.stdout)["accepted"]


@pytest.mark.parametrize("args", [("--task-id",), ("--test-plan",), ("--unknown",),
                                 ("--task-id", "../../../../victim/eval"), ("--force",), ("--feature",)])
def test_invalid_cli_arguments_do_not_write(project, cli, args):
    run = invoke(project, cli, *args)
    assert run.returncode == 3, run.stderr
    assert not (project.feature / "eval").exists()


def test_concurrent_eval_cannot_read_another_verdict(project, cli):
    project.task["test_selectors"] = ["tests/test_books.py::test_wait"]
    project.save_task()
    argv, env = command(project, cli, "--strict", "--json", "--no-defects")
    first = subprocess.Popen(argv, cwd=project.root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 15
        while not (project.root / ".speed/started").exists():
            assert first.poll() is None, first.communicate()
            assert time.monotonic() < deadline
            time.sleep(0.05)
        second = invoke(project, cli, "--strict", "--json", "--no-defects")
        # --json owes stdout exactly one object on every exit, error paths
        # included, so a caller piping into jq never sees a truncated stream.
        assert second.returncode == 3
        assert json.loads(second.stdout)["accepted"] is False
        (project.root / ".speed/release").touch()
        stdout, stderr = first.communicate(timeout=15)
        assert first.returncode == 2, stderr
        assert json.loads(stdout)["accepted"] is False
        assert len(list((project.feature / "eval/runs").iterdir())) == 1
    finally:
        (project.root / ".speed/release").touch()
        if first.poll() is None:
            first.kill()
        first.communicate(timeout=15)


def test_symlink_state_and_selector_boundaries(project, cli, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_text("keep")
    (project.feature / "eval").symlink_to(outside, target_is_directory=True)
    rejected = invoke(project, cli, "--strict", "--no-defects")
    assert rejected.returncode == 3
    assert list(outside.iterdir()) == [outside / "sentinel"]
    (project.root / "external").symlink_to(outside, target_is_directory=True)
    for selector in ("../outside/test.py", "external/test.py", str(outside / "test.py")):
        outcome = run_command(PYTEST, [selector], project.root, project.feature / "commands")
        assert outcome["status"] == "fail" and "boundary" in outcome["evidence"]


def test_dangling_state_symlink_is_rejected_before_initialization(project, cli, tmp_path):
    target = tmp_path / "outside-state.json"
    project.state.unlink()
    project.state.symlink_to(target)
    run = invoke(project, cli, "--strict", "--no-defects")
    assert run.returncode == 3
    assert not target.exists()


def test_empty_lock_is_not_stolen(project, cli):
    lock = project.feature / "speed.lock"
    lock.mkdir()
    run = invoke(project, cli, "--strict", "--no-defects")
    assert run.returncode == 3 and lock.is_dir()
    assert not (project.feature / "eval").exists()


def test_report_failure_aborts_attempt_and_keeps_old_evidence(project, cli):
    initial = invoke(project, cli, "--strict", "--json", "--no-defects")
    assert initial.returncode == 0
    old = json.loads(initial.stdout)
    # Simulate a partial filesystem failure after execution, before reporting.
    test = project.root / "tests/test_books.py"
    test.write_text("import os\nfrom pathlib import Path\n"
                    "def test_pass():\n"
                    "    run = Path(os.environ['SPEED_EVAL_RESULT_FILE']).parents[2]\n"
                    "    (run / 'test-plan.json').write_text('{broken')\n")
    project.commit()
    failed = invoke(project, cli, "--strict", "--json", "--no-defects")
    assert failed.returncode == 3
    assert json.loads(failed.stdout)["accepted"] is False
    state = json.loads(project.state.read_text())
    assert state["evaluation"]["status"] == "failed" and not state["evaluation"]["accepted"]
    attempt = project.feature / "eval/runs" / state["evaluation"]["run_id"]
    assert json.loads((attempt / "attempt.json").read_text())["status"] == "failed"
    old_report = project.feature / "eval/runs" / old["run_id"] / "report.json"
    assert json.loads(old_report.read_text())["accepted"] is True
    assert not (project.feature / "speed.lock").exists()
    test.write_text(TESTS)
    project.commit()
    retry = invoke(project, cli, "--strict", "--json", "--no-defects")
    assert retry.returncode == 0 and json.loads(retry.stdout)["accepted"]


def test_new_spec_has_resolvable_rfc_link_and_preserves_existing_file(project, cli):
    import re
    rfc = project.root / "specs/tech/fresh.md"
    rfc.parent.mkdir()
    rfc.write_text("# RFC: Fresh\n")
    env = os.environ.copy()
    env.update(SPEED_PROJECT_ROOT=str(project.root), SPEED_PYTHON=sys.executable, EDITOR="")
    argv = ["bash", str(cli), "new", "test-spec", "fresh"]
    created = subprocess.run(argv, env=env, text=True, capture_output=True, timeout=15)
    assert created.returncode == 0, created.stderr
    spec = project.root / "specs/tests/fresh.md"
    original = spec.read_bytes()
    links = re.findall(r"\]\(([^)]+)\)", spec.read_text())
    assert links and all((spec.parent / link).resolve() == rfc for link in links)
    repeated = subprocess.run(argv, env=env, text=True, capture_output=True, timeout=15)
    assert repeated.returncode == 3 and spec.read_bytes() == original


def test_existing_authored_defect_is_preserved(project, cli):
    document = project.root / "specs/defects/eval-books-ac-01.md"
    document.parent.mkdir()
    document.write_text("Human investigation with valuable evidence\n")
    project.commit()
    project.task["test_selectors"] = ["tests/test_books.py::test_fail"]
    project.save_task()
    run = invoke(project, cli, "--strict")
    assert run.returncode == 2, run.stderr
    assert document.read_text() == "Human investigation with valuable evidence\n"


def test_dependency_cycle_keeps_both_failures_and_defects(project, cli):
    project.spec.write_text(SPEC.replace("## Acceptance", "| AC-02 | Other failure | unit | Correct result |\n\n## Acceptance"))
    project.task["required_test_cases"] = ["AC-01", "AC-02"]
    project.task["test_selectors"] = []
    project.save_task()
    plan = project.feature / "mapping.json"
    atomic_json(plan, {"test_cases": [
        {"scenario_id": sid, "selector": "tests/test_books.py::test_fail", "depends_on_scenarios": [dep]}
        for sid, dep in (("AC-01", "AC-02"), ("AC-02", "AC-01"))]})
    project.commit()
    run = invoke(project, cli, "--json", "--strict", "--test-plan", str(plan))
    assert run.returncode == 2, run.stderr
    report = json.loads(run.stdout)
    for sid in ("AC-01", "AC-02"):
        assert result(report, sid)["status"] == "fail"
        assert (project.root / f"specs/defects/eval-books-{sid.lower()}.md").is_file()


def test_declared_exit_gate_and_missing_linter_block_acceptance(project):
    project.spec.write_text(SPEC + "\n## Exit Criteria\n| Gate | Status | Evidence |\n|---|---|---|\n"
                             "| Release review | pending | Awaiting owner |\n")
    project.task["acceptance_criteria"] = [{"criterion": "lint required", "verify_by": "lint"}]
    project.save_task()
    project.commit()
    _, report = project.evaluate()
    assert not report["accepted"]
    assert result(report, "GATE-01")["status"] == "unverifiable"
    assert result(report, "TASK-1-CRIT-01")["status"] == "unverifiable"


def test_shell_harness_catches_early_assertion_failure(tmp_path):
    source = (REPO / "tests/test_eval.sh").read_text()
    source = source.replace('SPEED_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"', "SPEED_DIR=" + shlex.quote(str(REPO)))
    source = source.replace('assert_equals "python3 runner.py tests/test_books.py::test_delete"',
                            'assert_equals "INTENTIONALLY-WRONG-COMMAND"', 1)
    # Run just the mutated test using the actual harness.
    source = source[:source.index("\nrun_test test_accepts")] + "\nrun_test test_accepts_when_task_declared_scenarios_pass\n[[ $FAIL -eq 0 ]]\n"
    script = tmp_path / "harness-probe.sh"
    script.write_text(source)
    run = subprocess.run(["bash", str(script)], text=True, capture_output=True, timeout=30)
    assert run.returncode == 1
    assert "FAIL test_accepts" in run.stdout and "INTENTIONALLY-WRONG-COMMAND" in run.stderr
