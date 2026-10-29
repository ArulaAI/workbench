#!/usr/bin/env python3
"""Regression tests for three acceptance-report defects in lib/eval_report.py.

Each test reproduces one scenario in which the report either crashed instead of
producing a verdict, or turned absent evidence into an acceptance.
"""

import json
import os
import shlex
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.eval_report import build_report, write_report, _semantic_results
from lib.criteria_verify import verify_criteria


TEST_SPEC = """# Test Spec: Books

## Scenario Catalog

| ID | Scenario | Level | Expected outcome |
|----|----------|-------|------------------|
| AC-01 | Delete a book | integration | The book is removed |

## Acceptance Traceability

| RFC acceptance criterion | Covering scenarios |
|---|---|
| ST1: a book can be deleted | AC-01 |
"""


class EvalReportRegressionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tasks = self.root / "tasks"
        self.tasks.mkdir()
        self.test_spec = self.root / "test-spec.md"
        self.test_spec.write_text(TEST_SPEC, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _write_task(self, task):
        (self.tasks / f"{task['id']}.json").write_text(json.dumps(task), encoding="utf-8")

    def _by_id(self, report):
        return {result["id"]: result for result in report["results"]}

    def test_legacy_test_criterion_preserves_existence_only_caveat(self):
        (self.root / "test_books.py").write_text("def test_book():\n    assert False\n")
        task = {"files_touched": ["test_books.py"], "acceptance_criteria": [
            {"criterion": "Books tested", "verify_by": "test"}]}
        result = verify_criteria(task, str(self.root))["criteria_results"][0]
        self.assertEqual("pass", result["status"])
        self.assertIn("file existence only", result["evidence"])
        # Once configured, a failing runner must override the existence check.
        result = verify_criteria(task, str(self.root), test_command="false")["criteria_results"][0]
        self.assertEqual("fail", result["status"])

    def test_legacy_test_criterion_without_test_files_fails(self):
        task = {"files_touched": ["books.py"], "acceptance_criteria": [
            {"criterion": "Books tested", "verify_by": "test"}]}
        result = verify_criteria(task, str(self.root))["criteria_results"][0]
        self.assertEqual("fail", result["status"])

    def _test_criterion(self, files, commands):
        task = {"id": "1", "files_touched": files, "acceptance_criteria": [
            {"criterion": "Books tested", "verify_by": "test"}]}
        return _semantic_results([task], self.root, {"test_commands": commands},
                                 self.root / "evidence")[0]

    @unittest.skipUnless(shutil.which("npm") and shutil.which("node"), "requires npm and Node")
    def test_python_and_npm_receive_only_their_own_test_files(self):
        (self.root / "test_books.py").write_text("def test_book():\n    assert 1 + 1 == 2\n")
        (self.root / "books.test.js").write_text("module.exports = () => require('assert').equal(1 + 1, 2);\n")
        (self.root / "package.json").write_text(json.dumps({"scripts": {"test": "node runner.cjs"}}))
        (self.root / "runner.cjs").write_text("""
const fs = require('fs');
const tests = process.argv.slice(2).map(file => {
    require('assert').equal(require('path').extname(file), '.js');
    require(file)();
    return {id: file, status: 'pass'};
});
fs.writeFileSync(process.env.SPEED_EVAL_RESULT_FILE, JSON.stringify({tests}));
""")
        commands = [shlex.quote(sys.executable) + " -m pytest -q", "npm test --"]
        result = self._test_criterion(["test_books.py", "books.test.js"], commands)
        self.assertEqual("pass", result["status"], result["evidence"])
        self.assertEqual(2, len(result["executions"]))
        self.assertTrue(all(len(run["tests"]) == 1 for run in result["executions"]))
        # A real failure in the Python test still blocks acceptance.
        (self.root / "test_books.py").write_text("def test_book():\n    assert False\n")
        result = self._test_criterion(["test_books.py", "books.test.js"], commands)
        self.assertEqual("fail", result["status"])

    def test_ambiguous_custom_runners_do_not_execute_speculatively(self):
        (self.root / "test_books.py").write_text("def test_book(): pass\n")
        result = self._test_criterion(["test_books.py"], ["touch first", "touch second"])
        self.assertEqual("unverifiable", result["status"])
        self.assertFalse((self.root / "first").exists())
        self.assertFalse((self.root / "second").exists())

    def test_missing_test_files_fail_with_or_without_a_runner(self):
        for commands in ([], ["pytest -q"]):
            result = self._test_criterion(["books.py"], commands)
            self.assertEqual("fail", result["status"])

    # ── Defect 1: build provenance ───────────────────────────

    def _context(self, **extra):
        context = {"run_id": "run-1", "test_spec": str(self.test_spec),
                   "test_spec_sha256": "abc", "integration_verified": True}
        context.update(extra)
        return context

    def test_context_without_build_before_reports_unverifiable_provenance(self):
        """A --context payload with no build_before must not raise KeyError."""
        self._write_task({"id": "1", "required_test_cases": ["AC-01"],
                          "scenario_results": [
                              {"scenario_id": "AC-01", "status": "pass", "evidence": "passed"}],
                          "acceptance_criteria": []})
        report = build_report("books", self.root, self.tasks, self.test_spec,
                              context=self._context())
        gate = self._by_id(report).get("BUILD-PROVENANCE")
        self.assertIsNotNone(gate, "expected an explicit build provenance gate")
        self.assertEqual("unverifiable", gate["status"])
        self.assertIn("build_before", gate["evidence"])
        self.assertFalse(report["accepted"])

    def test_null_build_before_reports_unverifiable_provenance(self):
        """build_before present but null must not raise AttributeError."""
        self._write_task({"id": "1", "required_test_cases": ["AC-01"],
                          "scenario_results": [
                              {"scenario_id": "AC-01", "status": "pass", "evidence": "passed"}],
                          "acceptance_criteria": []})
        report = build_report("books", self.root, self.tasks, self.test_spec,
                              context=self._context(build_before=None))
        gate = self._by_id(report).get("BUILD-PROVENANCE")
        self.assertIsNotNone(gate, "expected an explicit build provenance gate")
        self.assertEqual("unverifiable", gate["status"])
        self.assertIn("build_before", gate["evidence"])
        self.assertFalse(report["accepted"])

    def test_summary_markdown_survives_missing_build_snapshot(self):
        """The written summary must render a verdict without a before snapshot."""
        self._write_task({"id": "1", "required_test_cases": ["AC-01"],
                          "scenario_results": [
                              {"scenario_id": "AC-01", "status": "pass", "evidence": "passed"}],
                          "acceptance_criteria": []})
        report = build_report("books", self.root, self.tasks, self.test_spec,
                              context=self._context(build_before=None))
        output = self.root / "eval"
        output.mkdir()
        write_report(report, output)
        summary = (output / "summary.md").read_text(encoding="utf-8")
        self.assertIn("NOT ACCEPTED", summary)
        self.assertIn("BUILD-PROVENANCE", summary)

    # ── Defect 3: lint criteria on deleted paths ─────────────

    LINT_CONFIG = {"test_commands": [],
                   "gates": [{"gate": "lint", "subsystem": "", "command": "test -f {file}"}],
                   "subsystems": {}}

    def _lint_task(self, files_touched):
        self._write_task({
            "id": "1", "required_test_cases": [], "scenario_results": [],
            "files_touched": files_touched,
            "acceptance_criteria": [
                {"criterion": "Touched files lint clean", "verify_by": "lint",
                 "scenario_ids": []}],
        })

    def _lint_report(self):
        return build_report("books", self.root, self.tasks, self.test_spec,
                            runner_config=self.LINT_CONFIG,
                            evidence_dir=self.root / "commands")

    def test_deleted_file_is_not_linted(self):
        """A renamed or deleted path must not be handed to the linter."""
        source = self.root / "src"
        source.mkdir()
        (source / "kept.py").write_text("x = 1\n", encoding="utf-8")
        self._lint_task(["src/removed.py", "src/kept.py"])
        result = self._by_id(self._lint_report())["TASK-1-CRIT-01"]
        self.assertEqual("pass", result["status"],
                        f"deleted path reached the linter: {result['evidence']}")
        self.assertNotIn("removed.py", result["command"])

    def test_all_touched_files_deleted_is_unverifiable_not_pass(self):
        """Nothing left to lint is an unverified criterion, never a pass."""
        self._lint_task(["src/removed.py"])
        result = self._by_id(self._lint_report())["TASK-1-CRIT-01"]
        self.assertEqual("unverifiable", result["status"])
        self.assertFalse(self._lint_report()["accepted"])


if __name__ == "__main__":
    unittest.main()
