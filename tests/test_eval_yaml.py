#!/usr/bin/env python3
"""evaluation.yaml: the machine-readable hand-off `speed eval` writes beside
report.json for the next workflow step.

The renderer has no YAML library. These tests hold it to two promises: the
file parses as YAML with the same facts as report.json, and free text from
the spec or a runner can never change the document's structure.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.eval_report import _evaluation_yaml, _yaml_scalar, write_report

try:
    import yaml
except ImportError:  # the renderer must not need it; the tests degrade to text checks
    yaml = None


def _report(**overrides):
    report = {
        "feature": "payments",
        "task_id": None,
        "commit": None,
        "build": {
            "before": {"head_commit": "652a8648384792c6ca862911a7d5fa9602d9a85b",
                       "fingerprint": "b2d6d501e4c66f24", "dirty": True, "available": True},
            "after": {"head_commit": "652a8648384792c6ca862911a7d5fa9602d9a85b",
                      "fingerprint": "b2d6d501e4c66f24", "dirty": True, "available": True},
        },
        "run_id": "b010982d3fd34f2c98278e8cc926f4ee",
        "test_spec_sha256": "a56fad84",
        "generated_at": "2026-09-18T09:16:48Z",
        "test_spec": "/repo/specs/tests/payments.md",
        "accepted": False,
        "summary": {"total": 2, "pass": 1, "partial": 0, "fail": 0, "unverifiable": 1,
                    "not_applicable": 0, "blocked_upstream": 0, "applicable": 2,
                    "examined": 1, "not_examined": 1},
        "results": [
            {"id": "AC-01", "kind": "scenario", "area": "Authorise",
             "title": "Given a valid card, when 2500 is authorised, then the amount is reserved",
             "expected": "authorised is 2500; status authorised", "level": "integration",
             "task_id": None, "tier": "executable", "status": "pass",
             "evidence": "All 11 discovered tests executed and passed (log: /repo/out.log)",
             "command": "node --test {selectors}", "required": True,
             "executions": [{"status": "pass", "artifact_dir": "/repo/.speed/eval/commands/729c",
                             "tests": [{"id": "test::authorise", "status": "pass"}]}],
             "traces": ["ST1", "TR5"], "evidence_type": "statistical"},
            {"id": "RISK-01", "kind": "scenario", "area": "Authorise",
             "title": "Given an authorise request that fails, then no field holds a full card number",
             "expected": "the logged record shows the pan field as redacted", "level": "integration",
             "task_id": None, "tier": "executable", "status": "unverifiable",
             "evidence": "No test mapped to this scenario", "command": "", "required": True,
             "traces": ["TR11", "Product risk, Critical"], "evidence_type": "silence"},
        ],
        "out_of_scope": [
            {"id": "OOS-01", "excluded": "Refund idempotency: one refund or two",
             "disposition": "Deferred", "reason": "ST6 covers authorise and capture only",
             "owner": "payments-product to decide; release claim bounded until then"},
        ],
        "criteria_results": None,
    }
    report.update(overrides)
    return report


class YamlScalarTest(unittest.TestCase):
    def test_identifiers_stay_bare(self):
        for value in ("AC-01", "pass", "silence", "integration", "payments"):
            self.assertEqual(value, _yaml_scalar(value))

    def test_text_a_yaml_reader_could_misread_is_quoted(self):
        for value in ("yes", "No", "null", "true", "OFF", "2024", "1e3", "a: b", "x # y",
                      "Product risk, Critical", "[list]", "{map}", "", " lead", "tail "):
            self.assertTrue(_yaml_scalar(value).startswith('"'), value)

    def test_digests_are_quoted_whatever_they_start_with(self):
        for value in ("b010982d3fd34f2c98278e8cc926f4ee", "652a8648384792c6ca862911a7d5fa9602d9a85b",
                      "a56fad841eb40b5cc083519179c248f005c6cfed97629fad79311cc13993702b"):
            self.assertEqual(f'"{value}"', _yaml_scalar(value))

    def test_none_bool_int(self):
        self.assertEqual("null", _yaml_scalar(None))
        self.assertEqual("true", _yaml_scalar(True))
        self.assertEqual("false", _yaml_scalar(False))
        self.assertEqual("17", _yaml_scalar(17))


class EvaluationYamlTest(unittest.TestCase):
    def test_write_report_writes_evaluation_yaml_beside_report_json(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            write_report(_report(), out)
            self.assertTrue((out / "report.json").is_file())
            self.assertTrue((out / "summary.md").is_file())
            text = (out / "evaluation.yaml").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Written by `speed eval`."))
        self.assertIn("\nfeature: payments\n", text)
        self.assertIn("\naccepted: false\n", text)
        self.assertIn("\n  - id: AC-01\n", text)
        self.assertIn("\n  - id: RISK-01\n", text)
        self.assertIn("\n  - id: OOS-01\n", text)

    @unittest.skipUnless(yaml, "PyYAML not installed; structure check needs a parser")
    def test_parses_to_the_facts_in_report_json(self):
        report = _report()
        data = yaml.safe_load(_evaluation_yaml(report))
        self.assertEqual("payments", data["feature"])
        self.assertIsNone(data["task"])
        self.assertIsNone(data["commit"])
        self.assertEqual(report["run_id"], data["run_id"])
        self.assertEqual(report["build"]["before"]["head_commit"], data["build"]["head_commit"])
        self.assertIs(True, data["build"]["dirty"])
        self.assertIs(False, data["accepted"])
        self.assertEqual({"total": 2, "examined": 1, "not_examined": 1, "pass": 1, "fail": 0,
                          "partial": 0, "blocked_upstream": 0, "unverifiable": 1,
                          "not_applicable": 0}, data["summary"])
        passed, silent = data["results"]
        self.assertEqual({"id": "AC-01", "kind": "scenario", "area": "Authorise",
                          "title": report["results"][0]["title"],
                          "expected": "authorised is 2500; status authorised",
                          "level": "integration", "status": "pass", "evidence_type": "statistical",
                          "evidence": report["results"][0]["evidence"], "traces": ["ST1", "TR5"],
                          "task": None, "command": "node --test {selectors}",
                          "log": "/repo/.speed/eval/commands/729c/output.log"}, passed)
        self.assertEqual("unverifiable", silent["status"])
        self.assertEqual("silence", silent["evidence_type"])
        self.assertEqual(["TR11", "Product risk, Critical"], silent["traces"])
        self.assertIsNone(silent["command"])
        self.assertIsNone(silent["log"])
        self.assertEqual([{"id": "OOS-01", "excluded": "Refund idempotency: one refund or two",
                           "disposition": "Deferred",
                           "reason": "ST6 covers authorise and capture only",
                           "owner": "payments-product to decide; release claim bounded until then"}],
                         data["out_of_scope"])

    @unittest.skipUnless(yaml, "PyYAML not installed; structure check needs a parser")
    def test_hostile_free_text_cannot_change_the_document(self):
        evidence = 'a: b # not a comment\nsecond line "quoted" \\ backslash — dash\n- id: FAKE-99'
        report = _report()
        report["results"][1]["evidence"] = evidence
        report["results"][1]["title"] = "yes"
        report["results"][1]["traces"] = ["null", "2024", "on"]
        report["out_of_scope"][0]["reason"] = "reason: with colon"
        data = yaml.safe_load(_evaluation_yaml(report))
        self.assertEqual(2, len(data["results"]))
        self.assertEqual(evidence, data["results"][1]["evidence"])
        self.assertEqual("yes", data["results"][1]["title"])
        self.assertEqual(["null", "2024", "on"], data["results"][1]["traces"])
        self.assertEqual("reason: with colon", data["out_of_scope"][0]["reason"])

    @unittest.skipUnless(yaml, "PyYAML not installed; structure check needs a parser")
    def test_empty_results_and_out_of_scope_are_empty_lists(self):
        report = _report(results=[], out_of_scope=[],
                         summary={"total": 0, "pass": 0, "partial": 0, "fail": 0, "unverifiable": 0,
                                  "not_applicable": 0, "blocked_upstream": 0, "applicable": 0,
                                  "examined": 0, "not_examined": 0})
        data = yaml.safe_load(_evaluation_yaml(report))
        self.assertEqual([], data["results"])
        self.assertEqual([], data["out_of_scope"])

    @unittest.skipUnless(yaml, "PyYAML not installed; structure check needs a parser")
    def test_missing_build_snapshot_is_null_not_clean(self):
        report = _report(build={"before": None, "after": None})
        data = yaml.safe_load(_evaluation_yaml(report))
        self.assertEqual({"head_commit": None, "fingerprint": None, "dirty": None}, data["build"])

    def test_task_scoped_report_names_its_task(self):
        report = _report(task_id="3")
        report["results"][0]["task_id"] = "3"
        text = _evaluation_yaml(report)
        self.assertIn('\ntask: "3"\n', text)
        self.assertIn('\n    task: "3"\n', text)


if __name__ == "__main__":
    unittest.main()
