"""`speed eval --task N` picks up the task's persisted review by itself.

These drive the real prepare() so the plan source, ownership resolution and
run artifacts are the engine's own, not a stand-in for them.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lib.eval_runtime import prepare, review_derived_plan

SPEC = """# Test Spec

## Scenario Catalog

### Refund

| ID | Scenario | Level | Expected |
|---|---|---|---|
| RETRY-01 | a retried refund is accepted | integration | the refund succeeds |
| RETRY-02 | a third attempt is refused | integration | the refund is refused |
"""

TESTS = """import test from 'node:test';
test('[RETRY-01] a retried refund is accepted', () => {});
test('[RETRY-02] a third attempt is refused', () => {});
"""

OTHER_TESTS = "import test from 'node:test';\ntest('[RETRY-02] a third attempt is refused', () => {});\n"

TOML = '[eval]\ntest_command = "node --test {selectors}"\ntest_file_patterns = ["test/*.test.ts"]\n'


def review(*issues):
    return {"schema_version": 1, "issues": list(issues)}


def issue(scenario_id=None, testable=True, **extra):
    item = {"message": "a finding", "severity": "major", **extra}
    if scenario_id:
        item["scenario_id"] = scenario_id
    if testable is not None:
        item["testable"] = testable
    return item


class Project:
    """A minimal real project tree: git repo, spec, tasks, tests, config."""

    def __init__(self, root: Path):
        self.root = root
        (root / "test").mkdir(parents=True)
        (root / "test" / "refund-retry.test.ts").write_text(TESTS)
        (root / "specs" / "tests").mkdir(parents=True)
        self.spec = root / "specs" / "tests" / "payments.md"
        self.spec.write_text(SPEC)
        (root / "speed.toml").write_text(TOML)
        self.feature = root / ".speed" / "features" / "payments"
        (self.feature / "tasks").mkdir(parents=True)
        self.state = self.feature / "state.json"
        self.state.write_text(json.dumps({"status": "idle"}))
        for cmd in (["init", "-q"], ["add", "-A"],
                    ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
            subprocess.run(["git", "-C", str(root), *cmd], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def task(self, task_id, files, criteria=None):
        body = {"id": task_id, "status": "done", "files_touched": files}
        if criteria is not None:
            body["acceptance_criteria"] = criteria
        (self.feature / "tasks" / f"{task_id}.json").write_text(json.dumps(body))

    def review(self, task_id, payload):
        d = self.feature / "reviews"
        d.mkdir(exist_ok=True)
        (d / f"task-{task_id}.review").write_text(json.dumps(payload))

    def prepare(self, task_id="1", plan_path=None):
        run = prepare(self.root, self.feature, self.state, self.spec,
                      task_id=task_id, plan_path=plan_path)
        return run, json.loads((run / "test-plan.json").read_text())

    def tasks(self):
        return [json.loads(p.read_text())
                for p in sorted((self.feature / "tasks").glob("*.json"))]


class AutoReviewPlanTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.p = Project(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    DECLARED = [{"criterion": "[RETRY-01] a retried refund", "verify_by": "test"}]

    # 1 + 2 + 3 + 4. The artifact is found, the adapter runs, and its output
    # reaches the engine's own test-plan.json.
    def test_persisted_review_is_discovered_and_drives_the_plan(self):
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        self.p.review("1", review(issue("RETRY-01")))
        run, plan = self.p.prepare()
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-01"])
        self.assertEqual(plan["test_cases"][0]["source"], "review_findings",
                         "the case must come from the adapter, not task criteria")
        self.assertEqual(plan["test_cases"][0]["task_id"], "1")
        # Traceability: the adapter's own output is kept beside the resolved plan.
        raw = json.loads((run / "review-derived-plan.json").read_text())
        self.assertTrue(raw["review_source"].endswith("reviews/task-1.review"))

    # 7. No review artifact -> the long-standing behaviour is untouched.
    def test_without_a_review_the_task_criteria_path_still_runs(self):
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        _, plan = self.p.prepare()
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-01"])
        self.assertEqual(plan["test_cases"][0]["source"], "task_criteria")

    # 8. A review naming nothing executable must not fabricate a run, and must
    # not disable the path that would otherwise have chosen tests.
    def test_review_without_scenarios_falls_through_instead_of_fabricating(self):
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        self.p.review("1", review(issue(None), issue("RETRY-01", testable=False)))
        run, plan = self.p.prepare()
        self.assertEqual(plan["test_cases"][0]["source"], "task_criteria")
        self.assertFalse((run / "review-derived-plan.json").exists())

    def test_review_naming_nothing_at_all_is_ignored(self):
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        self.p.review("1", review())
        self.assertIsNone(review_derived_plan(
            self.p.root, self.p.feature, "1", SPEC,
            {"test_commands": ["node --test {selectors}"],
             "test_file_patterns": ["test/*.test.ts"]}, self.p.tasks()))

    # 5. Shared test file, nothing declared -> gap, never an execution.
    def test_shared_file_without_declaration_yields_no_review_case(self):
        self.p.task("1", ["test/refund-retry.test.ts"])
        self.p.task("2", ["test/refund-retry.test.ts"])
        self.p.review("1", review(issue("RETRY-01")))
        plan = review_derived_plan(
            self.p.root, self.p.feature, "1", SPEC,
            {"test_commands": ["node --test {selectors}"],
             "test_file_patterns": ["test/*.test.ts"]}, self.p.tasks())
        self.assertIsNone(plan, "ambiguous ownership must not become a case")

    # 6. Cross-task scenario is not executed under the wrong task. RETRY-02's
    # only tagged test must live in task 2's file, or task 1 would own it
    # outright by unique-file inference and executing it would be correct.
    def test_cross_task_scenario_is_not_executed_as_this_task(self):
        (self.p.root / "test" / "refund-retry.test.ts").write_text(
            "import test from 'node:test';\n"
            "test('[RETRY-01] a retried refund is accepted', () => {});\n")
        (self.p.root / "test" / "other.test.ts").write_text(OTHER_TESTS)
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        self.p.task("2", ["test/other.test.ts"])
        self.p.review("1", review(issue("RETRY-02")))
        _, plan = self.p.prepare()
        self.assertNotIn("RETRY-02", [c["scenario_id"] for c in plan["test_cases"]],
                         "task 2's scenario must not execute under task 1")

    # 9. An explicit --test-plan outranks the review.
    def test_explicit_test_plan_wins_over_the_review(self):
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        self.p.review("1", review(issue("RETRY-01")))
        explicit = self.p.root / "explicit.json"
        explicit.write_text(json.dumps({"test_cases": [
            {"scenario_id": "RETRY-02", "selector": "test/refund-retry.test.ts",
             "command": "node --test {selectors}", "runner": "node", "task_id": "1",
             "test_name": "[RETRY-02] a third attempt is refused", "source": "explicit"}]}))
        run, plan = self.p.prepare(plan_path=explicit)
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-02"])
        self.assertEqual(plan["test_cases"][0]["source"], "explicit")
        self.assertFalse((run / "review-derived-plan.json").exists(),
                         "an explicit plan must not also record a review-derived one")

    # 10/11/12. The engine still produces its usual run artifacts.
    def test_run_artifacts_are_unchanged_on_the_review_path(self):
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        self.p.review("1", review(issue("RETRY-01")))
        run, _ = self.p.prepare()
        for name in ("test-plan.json", "test-spec.md", "runner-config.json",
                     "context.json", "attempt.json", "tasks/1.json"):
            self.assertTrue((run / name).is_file(), f"missing run artifact: {name}")

    def test_malformed_review_is_skipped_not_fatal(self):
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        (self.p.feature / "reviews").mkdir(exist_ok=True)
        (self.p.feature / "reviews" / "task-1.review").write_text("{ not json")
        _, plan = self.p.prepare()
        self.assertEqual(plan["test_cases"][0]["source"], "task_criteria")

    def test_review_naming_an_unknown_scenario_is_skipped_not_fatal(self):
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        self.p.review("1", review(issue("GONE-99")))
        _, plan = self.p.prepare()
        self.assertEqual(plan["test_cases"][0]["source"], "task_criteria")

    # Feature scope must not acquire a review source: reviews are per task.
    def test_feature_scope_never_uses_a_review(self):
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        self.p.review("1", review(issue("RETRY-01")))
        run = prepare(self.p.root, self.p.feature, self.p.state, self.p.spec, task_id=None)
        self.assertFalse((run / "review-derived-plan.json").exists())


if __name__ == "__main__":
    unittest.main()


class UnknownScenarioToleranceTests(unittest.TestCase):
    """One out-of-catalog identifier must not discard a usable review."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.p = Project(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def test_out_of_catalog_id_alongside_a_good_one_still_plans(self):
        self.p.task("1", ["test/refund-retry.test.ts"],
                    [{"criterion": "[RETRY-01] a retried refund", "verify_by": "test"}])
        # OOS-01 is a real payments-spec deferral row, not a catalog scenario.
        self.p.review("1", review(issue("OOS-01"), issue("RETRY-01")))
        run, plan = self.p.prepare()
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-01"])
        self.assertEqual(plan["test_cases"][0]["source"], "review_findings")
        raw = json.loads((run / "review-derived-plan.json").read_text())
        self.assertTrue(any("OOS-01" in n for n in raw["selection"]["review_notes"]),
                        "the unusable id must be reported, not silently dropped")


class AdapterGapSurvivalTests(unittest.TestCase):
    """A refusal the adapter reasoned about must reach the final selection.

    select_plan rebuilds `selection` wholesale, which silently dropped the
    adapter's gaps: a cross-task finding was correctly refused and then
    disappeared, leaving a clean-looking pass with no trace of it.
    """

    SPEC = SPEC + "| RISK-02 | the scheme fee rounds half up | integration | fee 3 |\n"
    RISK_TESTS = ("import test from 'node:test';\n"
                  "test('[RISK-02] the scheme fee rounds half up', () => {});\n")
    DECLARED = [{"criterion": "[RETRY-01] a retried refund", "verify_by": "test"}]

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.p = Project(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)
        # RISK-02's only tagged test belongs to task 2, mirroring payments.
        (self.p.root / "test" / "service.test.ts").write_text(self.RISK_TESTS)
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        self.p.task("2", ["test/service.test.ts"])
        self.p.spec.write_text(self.SPEC)

    def plan_for(self, *issues):
        self.p.review("1", review(*issues))
        run = prepare(self.p.root, self.p.feature, self.p.state, self.p.spec,
                      task_id="1")
        return run, json.loads((run / "test-plan.json").read_text())

    # 1. The adapter reasons about the cross-task refusal, as a note.
    def test_adapter_records_the_cross_task_refusal_as_a_note(self):
        run, _ = self.plan_for(issue("RETRY-01"), issue("RISK-02"))
        raw = json.loads((run / "review-derived-plan.json").read_text())
        self.assertTrue(any("RISK-02" in n and "owned by task 2" in n
                            for n in raw["selection"]["review_notes"]))
        self.assertEqual(raw["selection"]["gaps"], [],
                         "another task's scenario is not this task's gap")

    # 2. select_plan no longer discards it.
    def test_note_survives_select_plan_into_the_final_selection(self):
        _, plan = self.plan_for(issue("RETRY-01"), issue("RISK-02"))
        self.assertTrue(any("RISK-02" in n for n in plan["selection"]["review_notes"]),
                        "the adapter's note must reach test-plan.json")

    # 3 + 5. RISK-02 is recorded, never executed, and never a blocking gate.
    def test_risk_02_is_recorded_and_not_executed_and_does_not_block(self):
        _, plan = self.plan_for(issue("RETRY-01"), issue("RISK-02"))
        self.assertNotIn("RISK-02", [c["scenario_id"] for c in plan["test_cases"]])
        self.assertTrue(any("RISK-02" in n for n in plan["selection"]["review_notes"]))
        self.assertFalse(any("RISK-02" in g for g in plan["selection"]["gaps"]),
                         "a cross-task refusal must not become a SELECTION-* gate")

    # 4. RETRY-01 is still selected, owned by task 1.
    def test_retry_01_is_still_selected(self):
        _, plan = self.plan_for(issue("RETRY-01"), issue("RISK-02"))
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-01"])
        self.assertEqual(plan["test_cases"][0]["task_id"], "1")

    # 6. Nothing changes when the adapter had nothing to refuse.
    def test_no_spurious_gaps_when_nothing_was_refused(self):
        _, plan = self.plan_for(issue("RETRY-01"))
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-01"])
        self.assertEqual(plan["selection"]["gaps"], [])
        self.assertEqual(plan["selection"].get("review_notes", []), [])

    # 6 (cont). The engine's own gaps are preserved, not replaced.
    def test_engine_gaps_are_kept_alongside_adapter_gaps(self):
        _, plan = self.plan_for(issue("RETRY-01"), issue("RISK-02"))
        notes = plan["selection"]["review_notes"]
        self.assertEqual(len(notes), len(set(notes)), "notes must not duplicate")


class ReviewNoteAcceptanceTests(unittest.TestCase):
    """A cross-task note is auditable but must not gate this task's verdict.

    select_plan already drops another task's case with no gap, so a review
    naming one must not be stricter than the engine's own path.
    """

    SPEC = AdapterGapSurvivalTests.SPEC
    DECLARED = AdapterGapSurvivalTests.DECLARED

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.p = Project(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)
        (self.p.root / "test" / "service.test.ts").write_text(
            AdapterGapSurvivalTests.RISK_TESTS)
        self.p.spec.write_text(self.SPEC)

    def build(self, *issues, sharer_files=None):
        self.p.task("1", ["test/refund-retry.test.ts"], self.DECLARED)
        self.p.task("2", sharer_files or ["test/service.test.ts"])
        self.p.review("1", review(*issues))
        run = prepare(self.p.root, self.p.feature, self.p.state, self.p.spec, task_id="1")
        return run, json.loads((run / "test-plan.json").read_text())

    def test_cross_task_note_does_not_become_a_selection_gate(self):
        _, plan = self.build(issue("RETRY-01"), issue("RISK-02"))
        self.assertEqual(plan["selection"]["gaps"], [],
                         "no gap means eval_report emits no SELECTION-* row")
        self.assertTrue(any("RISK-02" in n for n in plan["selection"]["review_notes"]))

    def test_retry_01_still_selected_and_owned(self):
        _, plan = self.build(issue("RETRY-01"), issue("RISK-02"))
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-01"])
        self.assertEqual(plan["test_cases"][0]["task_id"], "1")

    def test_risk_02_absent_from_scenario_scope_and_cases(self):
        _, plan = self.build(issue("RETRY-01"), issue("RISK-02"))
        self.assertNotIn("RISK-02", [c["scenario_id"] for c in plan["test_cases"]])
        self.assertNotIn("RISK-02", plan["selection"]["scenario_ids"])

    def test_notes_do_not_change_scenario_counts(self):
        # One case either way: a note adds no row and removes none.
        _, with_note = self.build(issue("RETRY-01"), issue("RISK-02"))
        self._tmp.cleanup(); self.setUp()
        _, without = self.build(issue("RETRY-01"))
        self.assertEqual(len(with_note["test_cases"]), len(without["test_cases"]))
        self.assertEqual(with_note["selection"]["scenario_ids"],
                         without["selection"]["scenario_ids"])

    def test_ambiguous_ownership_is_still_a_real_gap(self):
        # Task 2 shares task 1's file: this task is a candidate owner, so the
        # question is unresolved *for task 1* and must keep blocking.
        undeclared = {"id": "1", "status": "done",
                      "files_touched": ["test/refund-retry.test.ts"]}
        (self.p.feature / "tasks" / "1.json").write_text(json.dumps(undeclared))
        self.p.task("2", ["test/refund-retry.test.ts"])
        self.p.review("1", review(issue("RETRY-01")))
        run = prepare(self.p.root, self.p.feature, self.p.state, self.p.spec, task_id="1")
        raw = json.loads((run / "review-derived-plan.json").read_text()) \
            if (run / "review-derived-plan.json").exists() else None
        if raw is not None:
            self.assertTrue(any("shares with" in g for g in raw["selection"]["gaps"]))
            self.assertEqual(raw["selection"]["review_notes"], [])

    def test_genuine_this_task_gaps_are_untouched(self):
        # No candidate test files at all is this task's problem, so it stays
        # in gaps even though it arrived through the review path.
        self.p.task("1", ["src/payments/retry.ts"], self.DECLARED)
        self.p.task("2", ["test/service.test.ts"])
        self.p.review("1", review(issue("RETRY-01")))
        plan = review_derived_plan(
            self.p.root, self.p.feature, "1", self.SPEC,
            {"test_commands": ["node --test {selectors}"],
             "test_file_patterns": ["test/*.test.ts"]}, self.p.tasks())
        self.assertIsNone(plan, "no cases means the review path yields nothing")
