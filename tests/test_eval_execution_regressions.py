#!/usr/bin/env python3
"""Regression tests for lib/eval_execution.py gate discovery and selector scoping.

Two defects are covered here.

1. Quality-gate discovery read past the end of the ``## Quality Gates`` section.
   Only a following H2 terminated it, so an H1 appendix (or a fenced shell
   example) kept contributing "configured" gate commands that run_command hands
   to ``bash -c``. Documentation became executable configuration.

2. When a configured command carried no ``{selectors}`` placeholder the
   selectors were concatenated onto the raw command string. For a compound
   command the selectors landed on the wrong simple command, the real runner
   executed the entire suite unscoped, and the pytest discovery guard then found
   the selected test in that full report and reported a pass it never earned.

Sentinels here are deliberately harmless: an ``echo PWNED`` gate that must never
be returned, and a marker file written by a test that must never be reached by a
scoped run.

Runs both as ``python3 tests/test_eval_execution_regressions.py`` and under
``python3 -m pytest``.
"""

import contextlib
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.eval_execution import (commands_for_file, configured_commands, load_config,
                                render_command, run_command, subsystem_for)

PYTEST = shlex.quote(sys.executable) + " -m pytest -q"
# Written by a test that only a full, unscoped suite run would reach.
UNSCOPED_MARKER = "unscoped-suite-ran.marker"
SCOPED_SELECTOR = "tests/test_a.py::test_x"


@contextlib.contextmanager
def agent_project(agent_text):
    """A project whose only gate configuration is the given agent file."""
    saved = {name: os.environ.pop(name, None)
             for name in ("SPEED_AGENT_FILE", "SPEED_EVAL_TEST_COMMAND")}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text(agent_text, encoding="utf-8")
            yield root
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


@contextlib.contextmanager
def pytest_project():
    """Two test files: one holds the selected test, one records a full-suite run."""
    with agent_project("## Quality Gates\n") as root:
        (root / "tests").mkdir()
        (root / "tests" / "test_a.py").write_text("def test_x():\n    assert True\n")
        (root / "tests" / "test_b.py").write_text(
            "from pathlib import Path\n"
            "def test_marker():\n"
            f"    Path({UNSCOPED_MARKER!r}).write_text('ran')\n")
        yield root


def gate_commands(root, gate, task=None):
    config = load_config(root)
    commands = configured_commands(config, gate, task)
    subsystem = subsystem_for(task, config) if task else "both"
    shell = subprocess.run(
        ["bash", "-c", 'source "$1/gates.sh"; '
         '_context_python() { printf "%s\\n" "$TEST_PYTHON"; }; gates_get_config "$2" "$3"',
         "gates-test", str(Path(PROJECT_ROOT) / "lib"), gate, subsystem],
        env={**os.environ, "LIB_DIR": str(Path(PROJECT_ROOT) / "lib"),
             "AGENT_FILE_PATH": str(root / "AGENTS.md"), "TEST_PYTHON": sys.executable},
        text=True, capture_output=True, check=True)
    assert shell.stdout.splitlines() == commands, (shell.stdout, commands)
    return commands


# ── Defect 1: the Quality Gates section must end at the next section ──────────

def test_h1_appendix_ends_the_quality_gates_section():
    agent = ("## Quality Gates\n"
             "- test: real-test-command\n"
             "\n"
             "# Appendix\n"
             "\n"
             "Never configure a gate like this:\n"
             "- lint: echo PWNED\n")
    with agent_project(agent) as root:
        assert gate_commands(root, "test") == ["real-test-command"]
        assert gate_commands(root, "lint") == [], "an H1 must end the gate section"


def test_fenced_example_is_documentation_not_configuration():
    agent = ("## Quality Gates\n"
             "- test: real-test-command\n"
             "\n"
             "### Backend\n"
             "Example of what a lint gate looks like:\n"
             "```sh\n"
             "- lint: echo PWNED\n"
             "```\n")
    with agent_project(agent) as root:
        assert gate_commands(root, "test") == ["real-test-command"]
        assert gate_commands(root, "lint") == [], "a fenced example is not a gate"


def test_fenced_section_header_cannot_open_gate_configuration():
    agent = ("# Project\n"
             "\n"
             "~~~markdown\n"
             "## Quality Gates\n"
             "- lint: echo PWNED\n"
             "~~~\n")
    with agent_project(agent) as root:
        assert gate_commands(root, "lint") == []
        assert gate_commands(root, "test") == []


def test_deep_heading_ends_the_quality_gates_section():
    agent = ("## Quality Gates\n"
             "- test: real-test-command\n"
             "###### Example\n"
             "- lint: echo PWNED\n")
    with agent_project(agent) as root:
        assert gate_commands(root, "test") == ["real-test-command"]
        assert gate_commands(root, "lint") == []


def test_hash_prefixed_text_is_not_a_heading():
    agent = ("## Quality Gates\n"
             "#hashtag is prose, not a section boundary\n"
             "- test: real-test-command\n")
    with agent_project(agent) as root:
        assert gate_commands(root, "test") == ["real-test-command"]


def test_subsystem_headings_and_h2_boundary_still_parse():
    agent = ("## Quality Gates\n"
             "### Backend\n"
             "- test: backend-test-command\n"
             "### Frontend\n"
             "- test: frontend-test-command\n"
             "## Patterns\n"
             "- lint: echo PWNED\n")
    with agent_project(agent) as root:
        assert gate_commands(root, "test") == ["backend-test-command", "frontend-test-command"]
        assert gate_commands(root, "lint") == []


def test_shell_and_eval_share_global_gates_and_exact_subsystem_names():
    agent = ("## Quality Gates\n"
             "- typecheck: global-check\n"
             "### Front\n"
             "- typecheck: front-check\n"
             "### Frontend\n"
             "- typecheck: frontend-check\n")
    with agent_project(agent) as root:
        (root / "speed.toml").write_text('[subsystems]\nfront = ["src/front/*"]\n')
        assert gate_commands(root, "typecheck", {"files_touched": ["src/front/a.ts"]}) == [
            "global-check", "front-check"]
        assert gate_commands(root, "typecheck", {"files_touched": ["README.md"]}) == ["global-check"]


# ── Subsystem routing must be an exact match ─────────────────────────────────

def test_subsystem_prefix_does_not_borrow_another_subsystems_gate():
    agent = ("## Quality Gates\n"
             "### Front\n"
             "- test: front-test-command\n"
             "### Frontend\n"
             "- test: frontend-test-command\n")
    with agent_project(agent) as root:
        config = load_config(root)
        config["subsystems"] = {"front": ["src/front/*"], "frontend": ["src/frontend/*"]}
        task = {"files_touched": ["src/front/app.js"]}
        assert configured_commands(config, "test", task) == ["front-test-command"]


# ── Defect 2: appended selectors must not silently unscope the run ────────────

def test_compound_command_cannot_silently_unscope_the_run():
    for base in (PYTEST + " ; echo done",
                 PYTEST + " | tee runner-out.log",
                 PYTEST + " # run everything"):
        with pytest_project() as root:
            outcome = run_command(base, [SCOPED_SELECTOR], root, root / "evidence")
            assert outcome["status"] != "pass", (base, outcome)
            assert not (root / UNSCOPED_MARKER).exists(), \
                f"{base!r} ran the whole suite while claiming to run {SCOPED_SELECTOR}"
            assert "{selectors}" in outcome["evidence"], (base, outcome["evidence"])


def test_simple_command_still_receives_appended_selectors():
    with pytest_project() as root:
        outcome = run_command(PYTEST, [SCOPED_SELECTOR], root, root / "evidence")
        assert outcome["status"] == "pass", outcome
        assert not (root / UNSCOPED_MARKER).exists(), "the run was not scoped"
        assert len(outcome["tests"]) == 1, outcome["tests"]


def test_explicit_placeholder_scopes_a_compound_command():
    with pytest_project() as root:
        base = PYTEST + " {selectors} ; echo done"
        outcome = run_command(base, [SCOPED_SELECTOR], root, root / "evidence")
        assert outcome["status"] == "pass", outcome
        assert not (root / UNSCOPED_MARKER).exists(), "the placeholder did not scope the run"
        assert len(outcome["tests"]) == 1, outcome["tests"]


def test_quoted_metacharacters_stay_data_and_still_take_selectors():
    rendered = render_command("python3 -c 'import sys; sys.exit(0)'", ["tests/test_a.py"])
    assert "tests/test_a.py" in rendered
    assert rendered.startswith("python3 -c 'import sys; sys.exit(0)'")


def test_a_placeholderless_command_never_drops_its_target():
    """The renderer has no opt-out from placing the selectors.

    lib/criteria_verify.py used to render with append=False, which returned the
    command untouched whenever it declared no placeholder. The target file was
    dropped, the configured suite ran unscoped, and the result was filed as
    evidence for that one file - once per file, each a pass it never earned.
    """
    assert render_command("cd src && ruff check .", ["app/x.py"]) == \
        "cd src && ruff check . app/x.py"
    assert render_command("ruff check", ["app/x.py"]) == "ruff check app/x.py"

    try:
        render_command("ruff check . ; echo done", ["app/x.py"])
    except ValueError as exc:
        assert "{selectors}" in str(exc), exc
    else:
        raise AssertionError("a compound command took the target silently")


def test_a_task_outside_every_subsystem_does_not_inherit_all_of_them():
    """No configured glob matched the task's files.

    That is not the same as a task spanning every subsystem, and folding the two
    together ran the frontend, backend and plugin suites over a README change,
    reporting their unrelated failures against it.
    """
    agent = ("## Quality Gates\n"
             "### Frontend\n"
             "- test: frontend-test-command\n"
             "### Backend\n"
             "- test: backend-test-command\n")
    with agent_project(agent) as root:
        config = load_config(root)
        config["subsystems"] = {"frontend": ["src/frontend/*"], "backend": ["src/backend/*"]}

        assert configured_commands(config, "test", {"files_touched": ["README.md"]}) == []
        assert configured_commands(config, "test", {"files_touched": ["src/frontend/a.js"]}) == \
            ["frontend-test-command"]
        assert configured_commands(
            config, "test",
            {"files_touched": ["src/frontend/a.js", "src/backend/b.py"]}) == \
            ["frontend-test-command", "backend-test-command"]


def test_a_gate_declared_outside_any_subsystem_still_covers_an_unmatched_task():
    """Guard against over-correcting: a repo-wide gate is not scoped to a
    subsystem and applies whatever the task touched."""
    agent = ("## Quality Gates\n"
             "- lint: repo-lint\n"
             "### Frontend\n"
             "- lint: frontend-lint\n")
    with agent_project(agent) as root:
        config = load_config(root)
        config["subsystems"] = {"frontend": ["src/frontend/*"]}
        assert configured_commands(config, "lint", {"files_touched": ["README.md"]}) == ["repo-lint"]


def test_criterion_files_route_to_their_own_subsystem_in_a_mixed_task():
    config = {"subsystems": {"api": ["api/*"], "web": ["web/*"]}, "gates": [
        {"gate": "test", "subsystem": "api", "command": "api-custom-tests"},
        {"gate": "test", "subsystem": "web", "command": "web-custom-tests"}]}
    task = {"files_touched": ["api/test_books.py", "web/books.test.ts"]}
    assert commands_for_file(config, "test", task, "api/test_books.py") == ["api-custom-tests"]
    assert commands_for_file(config, "test", task, "web/books.test.ts") == ["web-custom-tests"]


def test_test_peer_outside_the_source_glob_retains_the_tasks_subsystem():
    config = {"subsystems": {"api": ["api/*"], "web": ["web/*"]}, "gates": [
        {"gate": "test", "subsystem": "api", "command": "api-custom-tests"},
        {"gate": "test", "subsystem": "web", "command": "web-custom-tests"}]}
    task = {"files_touched": ["api/books.py"]}
    assert commands_for_file(config, "test", task, "tests/test_books.py") == ["api-custom-tests"]


def test_global_gate_does_not_hide_the_test_peers_subsystem_gate():
    config = {"subsystems": {"api": ["api/*"]}, "gates": [
        {"gate": "test", "subsystem": "", "command": "pytest -q -m smoke"},
        {"gate": "test", "subsystem": "api", "command": "pytest -q"}]}
    task = {"files_touched": ["api/books.py"]}
    assert commands_for_file(config, "test", task, "tests/test_books.py") == [
        "pytest -q -m smoke", "pytest -q"]


# ── Standalone runner ────────────────────────────────────────────────────────

def _cases():
    return [(name, value) for name, value in sorted(globals().items())
            if name.startswith("test_") and callable(value)]


if __name__ == "__main__":
    failed = 0
    cases = _cases()
    for name, case in cases:
        try:
            case()
        except Exception as exc:  # noqa: BLE001 - a standalone harness reports everything
            failed += 1
            print(f"  FAIL: {name} — {type(exc).__name__}: {exc}")
        else:
            print(f"  PASS: {name}")
    print(f"\nResults: {len(cases) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
