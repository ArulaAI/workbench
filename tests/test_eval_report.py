import json
import tempfile
import unittest
from pathlib import Path

from lib.eval_report import build_report, write_report


TEST_SPEC = """# Test Spec: Books

## Scenario Catalog

| ID | Scenario | Level | Expected outcome |
|----|----------|-------|------------------|
| AC-01 | Delete a book | integration | The book is removed |
| EDGE-01 | Delete a missing book | integration | A not-found result is returned |

## Acceptance Traceability

| RFC acceptance criterion | Covering scenarios |
|---|---|
| ST1: a book can be deleted | AC-01 |
"""


class EvalReportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tasks = self.root / "tasks"
        self.tasks.mkdir()
        self.test_spec = self.root / "test-spec.md"
        self.test_spec.write_text(TEST_SPEC, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _write_task(self, scenario_results):
        task = {
            "id": "1",
            "required_test_cases": ["AC-01", "EDGE-01"],
            "scenario_results": scenario_results,
            "acceptance_criteria": [
                {
                    "criterion": "Delete behavior is documented",
                    "verify_by": "manual",
                    "scenario_ids": [],
                }
            ],
        }
        (self.tasks / "1.json").write_text(json.dumps(task), encoding="utf-8")

    def test_executable_failure_blocks_acceptance(self):
        self._write_task(
            [
                {"scenario_id": "AC-01", "status": "fail", "evidence": "failed"},
                {"scenario_id": "EDGE-01", "status": "pass", "evidence": "passed"},
            ]
        )
        report = build_report("books", self.root, self.tasks, self.test_spec)
        statuses = {result["id"]: result["status"] for result in report["results"]}
        self.assertEqual("fail", statuses["AC-01"])
        self.assertFalse(report["accepted"])

    def test_unresolved_semantic_criterion_blocks_acceptance(self):
        """Every scenario passes, but a criterion needing human judgment does
        not, so the feature is not accepted. Nothing discharges it now that
        evaluation is fully deterministic."""
        self._write_task(
            [
                {"scenario_id": "AC-01", "status": "pass", "evidence": "passed"},
                {"scenario_id": "EDGE-01", "status": "pass", "evidence": "passed"},
            ]
        )
        report = build_report("books", self.root, self.tasks, self.test_spec)
        statuses = {result["id"]: result["status"] for result in report["results"]}
        self.assertEqual("pass", statuses["AC-01"])
        self.assertEqual("unverifiable", statuses["TASK-1-CRIT-01"])
        self.assertFalse(report["accepted"])
        output = self.root / "eval"
        write_report(report, output)
        self.assertTrue((output / "report.json").is_file())
        self.assertTrue((output / "summary.md").is_file())

    def test_missing_execution_is_unverifiable(self):
        self._write_task([])
        report = build_report("books", self.root, self.tasks, self.test_spec)
        self.assertEqual(2, report["summary"]["unverifiable"])
        self.assertEqual(1, report["criteria_summary"]["unverifiable"])
        self.assertFalse(report["accepted"])

    def _write_task_with_test_criterion(self):
        """A task whose criterion is verified by running tests."""
        task = {
            "id": "1",
            "required_test_cases": ["AC-01", "EDGE-01"],
            "scenario_results": [
                {"scenario_id": "AC-01", "status": "pass", "evidence": "passed"},
                {"scenario_id": "EDGE-01", "status": "pass", "evidence": "passed"},
            ],
            "files_touched": ["app/books.py"],
            "test_files": ["tests/test_books.py"],
            "acceptance_criteria": [
                {
                    "criterion": "Deleting a book removes it",
                    "verify_by": "test",
                    "scenario_ids": [],
                }
            ],
        }
        (self.tasks / "1.json").write_text(json.dumps(task), encoding="utf-8")
        (self.root / "app").mkdir(exist_ok=True)
        (self.root / "app" / "books.py").write_text("def deleteBook():\n    pass\n")
        tests_dir = self.root / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "test_books.py").write_text(
            "def test_delete():\n    assert True\n"
        )

    def test_configured_test_runner_is_discovered_from_agent_file(self):
        """A test-verified criterion must actually run the project's test command.

        eval_report called verify_criteria without test_command, so it defaulted
        to None and every test-verified criterion came back "unverifiable — Test
        runner not configured". On the speed-todo-demo run that produced 8 of 11
        unverifiable rows and a NOT ACCEPTED verdict while `pytest -q` was
        configured and all 44 tests passed.

        The command lives in the "## Quality Gates" section of the agent file,
        which is the same source lib/gates.sh reads.
        """
        (self.root / "CLAUDE.md").write_text(
            "# Project\n\n## Quality Gates\n\ntest: python3 -m pytest -q\n",
            encoding="utf-8",
        )
        self._write_task_with_test_criterion()

        report = build_report("books", self.root, self.tasks, self.test_spec)
        statuses = {r["id"]: r["status"] for r in report["results"]}
        evidence = {r["id"]: r["evidence"] for r in report["results"]}

        self.assertNotEqual(
            "unverifiable",
            statuses["TASK-1-CRIT-01"],
            f"criterion should have been executed, evidence: "
            f"{evidence.get('TASK-1-CRIT-01')}",
        )
        self.assertEqual("pass", statuses["TASK-1-CRIT-01"])
        self.assertTrue(report["accepted"])

    def test_failing_test_runner_marks_criterion_failed(self):
        """The discovered command must be trusted in both directions."""
        (self.root / "CLAUDE.md").write_text(
            "# Project\n\n## Quality Gates\n\ntest: python3 -c 'import sys; sys.exit(1)'\n",
            encoding="utf-8",
        )
        self._write_task_with_test_criterion()

        report = build_report("books", self.root, self.tasks, self.test_spec)
        statuses = {r["id"]: r["status"] for r in report["results"]}
        self.assertEqual("fail", statuses["TASK-1-CRIT-01"])
        self.assertFalse(report["accepted"])

    def test_missing_linter_remains_unverifiable(self):
        """A required lint criterion cannot pass without a configured linter."""
        (self.root / "CLAUDE.md").write_text(
            "# Project\n\n## Quality Gates\n\ntest: python3 -m pytest -q\n",
            encoding="utf-8",
        )
        task = {
            "id": "1",
            "required_test_cases": ["AC-01", "EDGE-01"],
            "scenario_results": [
                {"scenario_id": "AC-01", "status": "pass", "evidence": "passed"},
                {"scenario_id": "EDGE-01", "status": "pass", "evidence": "passed"},
            ],
            "files_touched": ["app/books.py"],
            "acceptance_criteria": [
                {"criterion": "Code is lint clean", "verify_by": "lint",
                 "scenario_ids": []}
            ],
        }
        (self.tasks / "1.json").write_text(json.dumps(task), encoding="utf-8")
        (self.root / "app").mkdir(exist_ok=True)
        (self.root / "app" / "books.py").write_text("x = 1\n")

        report = build_report("books", self.root, self.tasks, self.test_spec)
        statuses = {r["id"]: r["status"] for r in report["results"]}
        self.assertEqual("unverifiable", statuses["TASK-1-CRIT-01"])
        self.assertFalse(report["accepted"])

    def test_duplicate_scenario_ids_fail_acceptance(self):
        self._write_task(
            [
                {"scenario_id": "AC-01", "status": "pass", "evidence": "passed"},
                {"scenario_id": "EDGE-01", "status": "pass", "evidence": "passed"},
            ]
        )
        content = self.test_spec.read_text(encoding="utf-8")
        self.test_spec.write_text(
            content.replace("| EDGE-01 |", "| AC-01 |"),
            encoding="utf-8",
        )
        report = build_report("books", self.root, self.tasks, self.test_spec)
        self.assertEqual(2, report["summary"]["fail"])
        self.assertFalse(report["accepted"])

    def test_mapped_results_are_used_when_no_task_owns_the_scenario(self):
        """Tasks planned today carry no scenario fields; the test-plan.json run
        supplies the evidence and the optional task attribution."""
        task = {"id": "1", "acceptance_criteria": "Books can be deleted\n  verify_by: manual"}
        (self.tasks / "1.json").write_text(json.dumps(task), encoding="utf-8")
        mapped = [
            {"scenario_id": "AC-01", "status": "pass", "task_id": "1",
             "command": "pytest -q tests/test_books.py::test_delete", "evidence": "passed"},
            {"scenario_id": "EDGE-01", "status": "fail",
             "command": "pytest -q tests/test_books.py::test_missing", "evidence": "assertion failed"},
        ]
        report = build_report("books", self.root, self.tasks, self.test_spec, mapped)
        by_id = {result["id"]: result for result in report["results"]}
        self.assertEqual("pass", by_id["AC-01"]["status"])
        self.assertEqual("1", by_id["AC-01"]["task_id"])
        self.assertEqual("fail", by_id["EDGE-01"]["status"])
        self.assertIsNone(by_id["EDGE-01"]["task_id"])
        self.assertEqual("unverifiable", by_id["TASK-1-CRIT-01"]["status"])
        self.assertFalse(report["accepted"])

    def test_unmapped_scenario_is_unverifiable_not_failed(self):
        (self.tasks / "1.json").write_text(
            json.dumps({"id": "1", "acceptance_criteria": []}), encoding="utf-8"
        )
        report = build_report("books", self.root, self.tasks, self.test_spec)
        statuses = {result["id"]: result["status"] for result in report["results"]}
        self.assertEqual({"AC-01": "unverifiable", "EDGE-01": "unverifiable"}, statuses)
        self.assertEqual(0, report["summary"]["fail"])
        self.assertFalse(report["accepted"])
        by_id = {result["id"]: result for result in report["results"]}
        self.assertEqual("No test mapped to this scenario", by_id["AC-01"]["evidence"])

    def test_results_carry_evidence_types_and_traces(self):
        self._write_task(
            [
                {"scenario_id": "AC-01", "status": "pass", "evidence": "passed"},
                {"scenario_id": "EDGE-01", "status": "fail", "evidence": "failed"},
            ]
        )
        report = build_report("books", self.root, self.tasks, self.test_spec)
        by_id = {result["id"]: result for result in report["results"]}
        self.assertEqual("statistical", by_id["AC-01"]["evidence_type"])
        self.assertEqual("counterexample", by_id["EDGE-01"]["evidence_type"])
        self.assertEqual("silence", by_id["TASK-1-CRIT-01"]["evidence_type"])
        self.assertEqual(["ST1"], by_id["AC-01"]["traces"])
        self.assertEqual([], by_id["EDGE-01"]["traces"])

    def test_summary_counts_examined_and_not_examined_without_a_score(self):
        self._write_task([])
        report = build_report("books", self.root, self.tasks, self.test_spec)
        self.assertNotIn("score", report["summary"])
        self.assertEqual(0, report["summary"]["examined"])
        self.assertEqual(2, report["summary"]["not_examined"])
        self.assertEqual(3, report["checks_summary"]["not_examined"])
        by_id = {result["id"]: result for result in report["results"]}
        self.assertEqual("silence", by_id["AC-01"]["evidence_type"])
        write_report(report, self.root / "eval")
        summary = (self.root / "eval" / "summary.md").read_text(encoding="utf-8")
        self.assertIn("NOT ACCEPTED. 3 never examined.", summary)
        self.assertNotIn("\u2014", summary)

    def test_legacy_text_criteria_are_expanded_per_bullet(self):
        """speed plan stores criteria as one string with verify_by lines; eval
        must verify each bullet on its own instead of one manual blob."""
        task = {
            "id": "1",
            "required_test_cases": ["AC-01", "EDGE-01"],
            "scenario_results": [
                {"scenario_id": "AC-01", "status": "pass", "evidence": "passed"},
                {"scenario_id": "EDGE-01", "status": "pass", "evidence": "passed"},
            ],
            "files_touched": ["app/books.py"],
            "acceptance_criteria": (
                "- Delete endpoint removes the book\n"
                "  and its list memberships\n"
                "  verify_by: manual\n"
                "- app/books.py exists\n"
                "  verify_by: file_exists\n"
            ),
        }
        (self.tasks / "1.json").write_text(json.dumps(task), encoding="utf-8")
        (self.root / "app").mkdir(exist_ok=True)
        (self.root / "app" / "books.py").write_text("def delete_book():\n    pass\n")

        report = build_report("books", self.root, self.tasks, self.test_spec)
        criteria = [r for r in report["results"] if r["kind"] == "criterion"]
        self.assertEqual(["TASK-1-CRIT-01", "TASK-1-CRIT-02"], [c["id"] for c in criteria])
        self.assertEqual(["manual", "file_exists"], [c["level"] for c in criteria])
        self.assertEqual(
            "Delete endpoint removes the book and its list memberships", criteria[0]["title"]
        )
        self.assertEqual("unverifiable", criteria[0]["status"])

    def test_plain_text_criteria_stay_a_single_manual_criterion(self):
        task = {"id": "1", "acceptance_criteria": "Works end to end"}
        (self.tasks / "1.json").write_text(json.dumps(task), encoding="utf-8")
        report = build_report("books", self.root, self.tasks, self.test_spec)
        criteria = [r for r in report["results"] if r["kind"] == "criterion"]
        self.assertEqual(1, len(criteria))
        self.assertEqual("manual", criteria[0]["level"])

    def test_task_id_filter_limits_scenarios_and_criteria(self):
        for task_id, scenario_id in (("1", "AC-01"), ("2", "EDGE-01")):
            task = {
                "id": task_id,
                "required_test_cases": [scenario_id],
                "scenario_results": [
                    {"scenario_id": scenario_id, "status": "pass", "evidence": "passed"}
                ],
                "acceptance_criteria": [
                    {"criterion": f"Task {task_id} is documented", "verify_by": "manual",
                     "scenario_ids": []}
                ],
            }
            (self.tasks / f"{task_id}.json").write_text(json.dumps(task), encoding="utf-8")

        report = build_report("books", self.root, self.tasks, self.test_spec, task_id="1")
        self.assertEqual(["AC-01", "TASK-1-CRIT-01"], [r["id"] for r in report["results"]])
        self.assertEqual("1", report["task_id"])

    def test_test_criterion_without_configured_runner_is_unverifiable(self):
        """A test file existing is not execution evidence."""
        self._write_task_with_test_criterion()
        report = build_report("books", self.root, self.tasks, self.test_spec)
        statuses = {r["id"]: r["status"] for r in report["results"]}
        self.assertEqual("unverifiable", statuses["TASK-1-CRIT-01"])
        self.assertFalse(report["accepted"])


if __name__ == "__main__":
    unittest.main()
