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
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.eval_execution import configured_commands, load_config, render_command, run_command

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


def gate_commands(root, gate):
    return configured_commands(load_config(root), gate)


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


def test_rendering_without_appending_accepts_compound_commands():
    # lib/criteria_verify.py renders with append=False; that path stays usable.
    rendered = render_command("cd src && ruff check .", ["app/x.py"], append=False)
    assert rendered == "cd src && ruff check ."


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
