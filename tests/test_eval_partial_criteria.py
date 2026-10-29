"""Feature scope under partial adoption of [SCENARIO-ID] acceptance criteria.

One task adopting tagged criteria switches the whole feature onto the
task-criteria path. A task that declares none contributes no scenarios --
it has none to contribute -- but it must still be named, so a half-adopted
catalog is visible in the report rather than silently narrowed.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lib.eval_criteria import has_tagged_criteria, task_scenarios
from lib.eval_selection import select_plan, select_task_plan
from lib.test_spec import parse_execution_mapping

SPEC = """# Test Spec

## Scenario Catalog

### Refund

| ID | Scenario | Level | Expected |
|---|---|---|---|
| RETRY-01 | a retried refund is accepted | integration | the refund succeeds |
| RISK-02 | the scheme fee rounds half up | integration | fee 3 |
"""

RETRY_TESTS = ("import test from 'node:test';\n"
               "test('[RETRY-01] a retried refund is accepted', () => {});\n")
RISK_TESTS = ("import test from 'node:test';\n"
              "test('[RISK-02] the scheme fee rounds half up', () => {});\n")

CONFIG = {"test_commands": ["node --test {selectors}"],
          "test_file_patterns": ["test/*.test.ts"]}

TAGGED = [{"criterion": "[RETRY-01] a retried refund", "verify_by": "test"}]
TAGGED_RISK = [{"criterion": "[RISK-02] the fee rounds half up", "verify_by": "test"}]


def task(task_id, files, criteria=None):
    body = {"id": task_id, "status": "done", "files_touched": files}
    if criteria is not None:
        body["acceptance_criteria"] = criteria
    return body


class PartialCriteriaAdoptionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "test").mkdir()
        (self.root / "test" / "refund-retry.test.ts").write_text(RETRY_TESTS)
        (self.root / "test" / "service.test.ts").write_text(RISK_TESTS)
        self.addCleanup(self._tmp.cleanup)

    def feature_plan(self, tasks):
        """Exactly the branch prepare() takes at feature scope."""
        if has_tagged_criteria(tasks):
            return select_task_plan(self.root, SPEC, tasks, CONFIG, None)
        return select_plan({"test_cases": parse_execution_mapping(SPEC)},
                           SPEC, tasks, CONFIG, None, task_scenarios, override=False)

    # 1. No task tagged: the mapping path runs and reports every unmapped file.
    def test_no_tagged_criteria_keeps_the_mapping_path_and_its_gaps(self):
        tasks = [task("1", ["test/refund-retry.test.ts"]),
                 task("2", ["test/service.test.ts"])]
        plan = self.feature_plan(tasks)
        self.assertFalse(has_tagged_criteria(tasks))
        # A spec with no execution mapping yields nothing to run. That is the
        # pre-existing behaviour and this fix does not change it.
        self.assertEqual(plan["test_cases"], [])
        gaps = " ".join(plan["selection"]["gaps"])
        self.assertIn("test/refund-retry.test.ts", gaps)
        self.assertIn("test/service.test.ts", gaps)

    # 2. Only task 1 tagged: task 1 runs, task 2 is named rather than dropped.
    def test_partial_adoption_names_the_untagged_task(self):
        tasks = [task("1", ["test/refund-retry.test.ts"], TAGGED),
                 task("2", ["test/service.test.ts"])]
        plan = self.feature_plan(tasks)
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-01"])
        gaps = " ".join(plan["selection"]["gaps"])
        self.assertIn("Task 2 declares no [SCENARIO-ID] test criteria", gaps)
        self.assertIn("test/service.test.ts", gaps)
        # The file is visible as a candidate, not silently erased.
        self.assertIn("test/service.test.ts", plan["selection"]["candidate_files"])

    def test_partial_adoption_still_selects_only_declared_scenarios(self):
        # The fix must report, never widen: RISK-02 stays unmapped because no
        # task declares it. Inventing a mapping would be ownership guessing.
        tasks = [task("1", ["test/refund-retry.test.ts"], TAGGED),
                 task("2", ["test/service.test.ts"])]
        plan = self.feature_plan(tasks)
        self.assertNotIn("RISK-02", [c["scenario_id"] for c in plan["test_cases"]])

    # 3. Both tagged: full coverage and no untagged-task gap.
    def test_full_adoption_covers_both_and_emits_no_untagged_gap(self):
        tasks = [task("1", ["test/refund-retry.test.ts"], TAGGED),
                 task("2", ["test/service.test.ts"], TAGGED_RISK)]
        plan = self.feature_plan(tasks)
        self.assertEqual(sorted(c["scenario_id"] for c in plan["test_cases"]),
                         ["RETRY-01", "RISK-02"])
        self.assertNotIn("declares no [SCENARIO-ID]",
                         " ".join(plan["selection"]["gaps"]))

    def test_full_adoption_is_how_risk_02_becomes_executable(self):
        # The concrete answer to "why is RISK-02 unverifiable": nothing
        # declared it. Declaring it on its owning task makes it run.
        tasks = [task("1", ["test/refund-retry.test.ts"], TAGGED),
                 task("2", ["test/service.test.ts"], TAGGED_RISK)]
        case = [c for c in self.feature_plan(tasks)["test_cases"]
                if c["scenario_id"] == "RISK-02"][0]
        self.assertEqual(case["task_id"], "2")
        self.assertEqual(case["selector"], "test/service.test.ts")

    # 4. Task scope is untouched by the new gap.
    def test_task_scope_for_a_tagged_task_is_unchanged(self):
        tasks = [task("1", ["test/refund-retry.test.ts"], TAGGED),
                 task("2", ["test/service.test.ts"])]
        plan = select_task_plan(self.root, SPEC, tasks, CONFIG, "1")
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-01"])
        self.assertNotIn("Task 2", " ".join(plan["selection"]["gaps"]),
                         "a task run must not report another task's adoption")

    def test_task_scope_for_an_untagged_task_keeps_its_own_message(self):
        tasks = [task("1", ["test/refund-retry.test.ts"], TAGGED),
                 task("2", ["test/service.test.ts"])]
        plan = select_task_plan(self.root, SPEC, tasks, CONFIG, "2")
        self.assertEqual(plan["test_cases"], [])
        self.assertIn("No scenarios are attributable to this task",
                      " ".join(plan["selection"]["gaps"]))


if __name__ == "__main__":
    unittest.main()
