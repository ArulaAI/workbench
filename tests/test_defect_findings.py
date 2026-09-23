import json
import tempfile
import unittest
import uuid
from pathlib import Path

from dashboard.backend.paths import SpeedPaths
from lib.defect_findings import (
    FindingError,
    group_findings,
    publish_attempt,
    read_findings,
    record_decision,
)
from lib.review_evidence import parse_clean_review_payload


class DefectFindingTests(unittest.TestCase):
    def _paths(self, multiplayer=False):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        if multiplayer:
            (root / ".speed/shared").mkdir(parents=True)
        (root / "specs/product").mkdir(parents=True)
        (root / "specs/product/payments.md").write_text("# Payments\n")
        return temp, SpeedPaths(root)

    def test_review_summary_is_context_not_observed_fact(self):
        temp, paths = self._paths()
        self.addCleanup(temp.cleanup)
        publish_attempt(paths, "payments", "structured_review", "4", {
            "verdict": "request_changes",
            "issues": [{"message": "Retry may charge twice", "severity": "major", "file": "src/retry.py"}],
        })
        view = read_findings(paths, "payments")
        self.assertEqual(len(view["findings"]), 1)
        evidence = view["findings"][0]["evidence"][0]
        self.assertIsNone(evidence["observed"])
        self.assertEqual(evidence["summary"], "Retry may charge twice")
        self.assertEqual(evidence["recommended_action"], "fix_in_feature")
        self.assertFalse(any("Eval" in warning for warning in view["warnings"]))

    def test_fenced_clean_review_json_becomes_independent_findings(self):
        temp, paths = self._paths()
        self.addCleanup(temp.cleanup)
        raw = """```json
{"schema_version": 1, "issues": [
  {"message": "PAN redaction removed", "file": "src/payments/service.ts", "line": 67, "severity": "major"},
  {"message": "Fee rounding changed", "file": "src/payments/service.ts", "line": 119, "severity": "major"}
]}
```"""
        payload = parse_clean_review_payload(raw)
        publish_attempt(paths, "payments", "clean_review", "1", payload)
        findings = read_findings(paths, "payments")["findings"]
        self.assertEqual(len(findings), 2)
        self.assertEqual(
            {finding["title"] for finding in findings},
            {"PAN redaction removed", "Fee rounding changed"},
        )
        self.assertEqual(
            {finding["evidence"][0]["files"][0] for finding in findings},
            {"src/payments/service.ts:67", "src/payments/service.ts:119"},
        )
        with self.assertRaises(ValueError):
            parse_clean_review_payload("plain-text review")

    def test_multiplayer_archives_shared_and_decision_queues_rework(self):
        temp, paths = self._paths(multiplayer=True)
        self.addCleanup(temp.cleanup)
        task_dir = paths.feature_shared("payments") / "tasks"
        task_dir.mkdir(parents=True)
        (task_dir / "4.json").write_text(json.dumps({"id": "4", "status": "done"}))
        archive = publish_attempt(paths, "payments", "diagnose", "4", {
            "task": "4", "classes": [{"id": "D1", "failureMode": "Retry risk", "signals": [{"observed": "retry branch", "where": ["src/retry.py"]}]}],
        })
        self.assertTrue(str(archive).startswith(str(paths.feature_shared("payments"))))
        view = read_findings(paths, "payments")
        finding = view["findings"][0]
        request_id = str(uuid.uuid4())
        decision = record_decision(paths, "payments", 0, finding["revision"], {
            "request_id": request_id, "finding_id": finding["id"], "action": "fix_in_feature",
            "rationale": "Repair before completion", "task_id": "4",
        }, ("Engineer", "engineer@example.test"))
        self.assertEqual(decision["id"], request_id)
        saved = json.loads((paths.feature_shared("payments") / "findings.json").read_text())
        self.assertEqual(saved["rework"][request_id]["status"], "queued")
        with self.assertRaises(FindingError) as raised:
            record_decision(paths, "payments", 0, finding["revision"], {
                "request_id": str(uuid.uuid4()), "finding_id": finding["id"], "action": "fix_in_feature",
                "rationale": "Bad task", "task_id": "missing",
            }, ("Engineer", "engineer@example.test"))
        self.assertEqual(raised.exception.code, "INVALID_INPUT")

    def test_new_approved_attempt_resolves_completed_rework(self):
        temp, paths = self._paths()
        self.addCleanup(temp.cleanup)
        task_dir = paths.feature_shared("payments") / "tasks"
        task_dir.mkdir(parents=True)
        task_path = task_dir / "4.json"
        task_path.write_text(json.dumps({"id": "4", "status": "done"}))
        publish_attempt(paths, "payments", "structured_review", "4", {
            "verdict": "request_changes",
            "issues": [{"message": "Retry may charge twice", "severity": "major"}],
        })
        initial = read_findings(paths, "payments")
        finding = initial["findings"][0]
        record_decision(paths, "payments", initial["decision_revision"], finding["revision"], {
            "request_id": str(uuid.uuid4()), "finding_id": finding["id"],
            "action": "fix_in_feature", "rationale": "Repair the retry path", "task_id": "4",
        }, ("Engineer", "engineer@example.test"))
        task_path.write_text(json.dumps({"id": "4", "status": "done", "review_verdict": "approve"}))
        publish_attempt(paths, "payments", "structured_review", "4", {
            "verdict": "approve", "issues": [],
        })
        refreshed = read_findings(paths, "payments")
        retired = next(item for item in refreshed["findings"] if item["id"] == finding["id"])
        self.assertEqual(retired["resolution"], "resolved_by_rework")
        self.assertFalse(retired["stale"])

    def test_grouping_requires_every_active_evidence_item(self):
        temp, paths = self._paths()
        self.addCleanup(temp.cleanup)
        publish_attempt(paths, "payments", "structured_review", "4", {
            "verdict": "request_changes",
            "issues": [
                {"message": "First issue", "severity": "major"},
                {"message": "Second issue", "severity": "major"},
            ],
        })
        view = read_findings(paths, "payments")
        identity = view["findings"][0]["evidence"][0]
        member = f"{identity['producer']}:{identity['task_id']}:{identity['item_key']}"
        with self.assertRaises(FindingError) as raised:
            group_findings(
                paths, "payments", view["decision_revision"], {"only-one": [member]},
                "Incorrectly omit evidence", ("Engineer", "engineer@example.test"), str(uuid.uuid4()),
            )
        self.assertEqual(raised.exception.code, "INVALID_INPUT")

    def test_published_archive_redacts_secret_fields(self):
        temp, paths = self._paths()
        self.addCleanup(temp.cleanup)
        token = "ghp_" + ("a" * 36)
        archive = publish_attempt(paths, "payments", "structured_review", "4", {
            "issues": [{"message": f"Leaked {token}", "observed": token, "severity": "major"}],
        })
        stored = json.loads(archive.read_text())
        self.assertNotIn(token, archive.read_text())
        self.assertIn("payload.issues[0].message", stored["redacted_fields"])
        self.assertIn("items[0].summary", stored["redacted_fields"])
        self.assertIn("items[0].observed", stored["redacted_fields"])
        finding = read_findings(paths, "payments")["findings"][0]
        from lib.defect_intake import preview_defect
        preview = preview_defect(paths, "payments", finding["id"])
        self.assertEqual(preview["draft"]["observed"], "")
        self.assertIn("observed", preview["missing_fields"])

    def test_decision_freezes_legacy_source_before_saving(self):
        temp, paths = self._paths()
        self.addCleanup(temp.cleanup)
        shared = paths.feature_shared("payments")
        shared.mkdir(parents=True)
        (shared / "risk-surface.yaml").write_text(
            "task: '4'\nclasses:\n"
            "  - id: D1\n"
            "    plausible: undecided\n"
            "    signals:\n"
            "      - observed: retry branch\n"
            "        where: [src/retry.py]\n"
        )
        before = read_findings(paths, "payments")
        finding = before["findings"][0]
        decision = record_decision(paths, "payments", before["decision_revision"], finding["revision"], {
            "request_id": str(uuid.uuid4()), "finding_id": finding["id"],
            "action": "needs_verification", "rationale": "Confirm the risk signal",
        }, ("Engineer", "engineer@example.test"))
        archives = list((shared / "evidence/diagnose/4").glob("*.json"))
        self.assertEqual(len(archives), 1)
        self.assertEqual(decision["evidence_ids"], [finding["evidence"][0]["id"]])
        archived = read_findings(paths, "payments")["findings"][0]
        self.assertEqual(archived["revision"], finding["revision"])
        self.assertIsNotNone(archived["evidence"][0]["attempt_id"])

    def test_source_symlink_outside_project_is_rejected(self):
        temp, paths = self._paths()
        self.addCleanup(temp.cleanup)
        outside = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        self.addCleanup(Path(outside.name).unlink, missing_ok=True)
        outside.write("task: '4'\nclasses: []\n")
        outside.close()
        shared = paths.feature_shared("payments")
        shared.mkdir(parents=True)
        (shared / "risk-surface.yaml").symlink_to(outside.name)
        view = read_findings(paths, "payments")
        self.assertEqual(view["findings"], [])
        self.assertTrue(any("escapes the project root" in warning for warning in view["warnings"]))


if __name__ == "__main__":
    unittest.main()
