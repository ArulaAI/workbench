import json
import tempfile
import unittest
from pathlib import Path

from lib.evidence_cli import main as evidence_main
from lib.review_evidence import parse_clean_review_payload, parse_report_findings_events


class CleanReviewEvidenceTests(unittest.TestCase):
    def test_confirmed_tool_missing_severity_uses_matching_final_json(self):
        findings = [
            {"summary": "Capture fee floors instead of rounding", "file": "src/payments/service.ts", "line": 119},
            {"summary": "Retry helper is untested", "file": "test/refund-retry.test.ts", "line": 9},
        ]
        events = "\n".join(json.dumps(event) for event in (
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "ReportFindings", "id": "done", "input": {"findings": findings}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "done"}], "role": "user"}, "tool_use_result": {"count": 2, "findings": findings}},
        ))
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": findings[0]["summary"], "file": findings[0]["file"], "line": 119, "severity": "major"},
            {"message": findings[1]["summary"], "file": findings[1]["file"], "line": 9, "severity": "minor"},
        ]})
        parsed = parse_report_findings_events(events, final_text=final)
        self.assertEqual([issue["severity"] for issue in parsed["issues"]], ["major", "minor"])
        with self.assertRaisesRegex(ValueError, "does not match"):
            parse_report_findings_events(events, final_text=final.replace("test/refund-retry.test.ts", "test/other.test.ts"))
        with self.assertRaisesRegex(ValueError, "does not match"):
            parse_report_findings_events(events, final_text=final.replace("Retry helper is untested", "Payment data leaks to logs"))
        self.assertEqual(parsed["issues"][0]["message"], findings[0]["summary"])

    def test_confirmed_report_findings_becomes_separate_issues(self):
        rejected = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "ReportFindings", "id": "bad", "input": {"findings": [{"summary": "Unaccepted"}]}}]}}
        accepted = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "ReportFindings", "id": "good", "input": {"findings": [
            {"summary": "Duplicate refund", "file": "src/retry.ts", "line": 12, "severity": "critical", "failure_scenario": "Repeat a successful refund"},
            {"summary": "Retry is untested", "file": "test/retry.ts", "line": 9, "severity": "major"},
        ]}}]}}
        confirmed = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "good", "content": "2 findings reported."}], "role": "user"}, "tool_use_result": {"count": 2, "findings": [
            {"summary": "Duplicate refund", "file": "src/retry.ts", "line": 12},
            {"summary": "Retry is untested", "file": "test/retry.ts", "line": 9},
        ]}}
        events = "\n".join(json.dumps(event) for event in (rejected, accepted, confirmed))
        payload = parse_report_findings_events(events)
        self.assertEqual([issue["message"] for issue in payload["issues"]], ["Duplicate refund", "Retry is untested"])
        self.assertEqual(payload["issues"][0]["severity"], "critical")
        self.assertEqual(payload["issues"][0]["reproduction"], "Repeat a successful refund")
        self.assertIsNone(parse_report_findings_events(json.dumps(rejected)))
        mismatched = dict(confirmed)
        mismatched["tool_use_result"] = {"count": 2, "findings": [{"summary": "Different issue", "file": "src/retry.ts", "line": 12}, confirmed["tool_use_result"]["findings"][1]]}
        self.assertIsNone(parse_report_findings_events("\n".join(json.dumps(event) for event in (accepted, mismatched))))
        empty = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "ReportFindings", "id": "empty", "input": {"findings": []}}]}}
        empty_result = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "empty"}]}, "tool_use_result": {"count": 0, "findings": []}}
        self.assertIsNone(parse_report_findings_events("\n".join(json.dumps(event) for event in (empty, empty_result))))

    def test_cli_publishes_confirmed_tool_results_for_define(self):
        from dashboard.backend.paths import SpeedPaths
        from lib.defect_findings import read_findings
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "review.tmp"
            review.write_text("1. Duplicate refund\n2. Retry untested", encoding="utf-8")
            events = root / "events.jsonl"
            issues = [
                {"summary": "Duplicate refund", "file": "src/retry.ts", "line": 12, "severity": "critical"},
                {"summary": "Retry untested", "file": "test/retry.ts", "line": 9, "severity": "major"},
            ]
            events.write_text("\n".join(json.dumps(event) for event in (
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "ReportFindings", "id": "done", "input": {"findings": issues}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "done"}], "role": "user"}, "tool_use_result": {"count": 2, "findings": issues}},
            )), encoding="utf-8")
            normalized = root / "normalized.json"
            compatibility = root / ".speed/features/payments/reviews/task-1.review"
            compatibility.parent.mkdir(parents=True)
            compatibility.write_text("Previous prose review", encoding="utf-8")
            self.assertEqual(evidence_main(["--project-root", str(root), "--feature", "payments", "--producer", "clean_review", "--task", "1", "--payload", str(review), "--provider-events", str(events), "--normalized-output", str(normalized), "--compatibility", str(compatibility)]), 0)
            self.assertEqual(len(json.loads(normalized.read_text())["issues"]), 2)
            findings = read_findings(SpeedPaths(root), "payments")["findings"]
            self.assertEqual({finding["title"] for finding in findings}, {"Duplicate refund", "Retry untested"})
            archives = list((root / ".speed/features/payments/evidence/clean_review/1").glob("*.json"))
            self.assertEqual(len(archives), 2)
            latest = max((json.loads(path.read_text()) for path in archives), key=lambda value: value["sequence"])
            self.assertEqual(latest["source_event_log"], "events.jsonl")

    def test_cli_publishes_matching_final_when_confirmed_tool_omits_severity(self):
        from dashboard.backend.paths import SpeedPaths
        from lib.defect_findings import read_findings
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "review.tmp"
            review.write_text(json.dumps({"schema_version": 1, "issues": [{
                "message": "Capture fee floors instead of rounding", "file": "src/payments/service.ts",
                "line": 119, "severity": "major", "observed": "Fee is 2, not 3.",
            }]}), encoding="utf-8")
            finding = {"summary": "Capture fee floors instead of rounding", "file": "src/payments/service.ts", "line": 119}
            events = root / "events.jsonl"
            events.write_text("\n".join(json.dumps(event) for event in (
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "ReportFindings", "id": "done", "input": {"findings": [finding]}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "done"}], "role": "user"}, "tool_use_result": {"count": 1, "findings": [finding]}},
            )), encoding="utf-8")
            normalized = root / "normalized.json"
            self.assertEqual(evidence_main([
                "--project-root", str(root), "--feature", "payments", "--producer", "clean_review",
                "--task", "1", "--payload", str(review), "--provider-events", str(events),
                "--normalized-output", str(normalized),
            ]), 0)
            self.assertEqual(json.loads(normalized.read_text())["issues"][0]["severity"], "major")
            self.assertEqual(len(read_findings(SpeedPaths(root), "payments")["findings"]), 1)

    def test_cli_accepts_json_when_provider_has_no_tool_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "review.tmp"
            review.write_text('{"schema_version":1,"issues":[{"message":"Fee mismatch","severity":"major"}]}', encoding="utf-8")
            events = root / "events.jsonl"
            events.touch()
            self.assertEqual(evidence_main(["--project-root", str(root), "--feature", "payments", "--producer", "clean_review", "--task", "1", "--payload", str(review), "--provider-events", str(events)]), 0)

    def test_accepts_versioned_json_and_provider_fence(self):
        source = json.dumps({
            "schema_version": 1,
            "issues": [{
                "message": "  PAN redaction was removed  ",
                "file": "src/payments/service.ts",
                "line": 67,
                "severity": "critical",
                "observed": "  The raw request reaches the logger.  ",
            }],
        })
        payload = parse_clean_review_payload(f"```json\n{source}\n```")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["issues"][0]["message"], "PAN redaction was removed")
        self.assertEqual(payload["issues"][0]["observed"], "The raw request reaches the logger.")

    def test_accepts_empty_issues(self):
        self.assertEqual(
            parse_clean_review_payload('{"schema_version":1,"issues":[]}'),
            {"schema_version": 1, "issues": []},
        )

    def test_rejects_unversioned_or_malformed_current_output(self):
        invalid = (
            "plain review",
            '{"issues":[]}',
            '{"schema_version":2,"issues":[]}',
            '{"schema_version":1,"issues":"none"}',
            '{"schema_version":1,"issues":["problem"]}',
            '{"schema_version":1,"issues":[{"message":"problem","severity":"high"}]}',
            '{"schema_version":1,"issues":[],"verdict":"approve"}',
        )
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_clean_review_payload(source)

    def test_rejects_invalid_locations_and_optional_fields(self):
        invalid_issues = (
            {"message": "problem", "severity": "major", "file": "/etc/passwd"},
            {"message": "problem", "severity": "major", "file": "src/../secret"},
            {"message": "problem", "severity": "major", "line": 1},
            {"message": "problem", "severity": "major", "file": "src/a.py", "line": True},
            {"message": "problem", "severity": "major", "expected": ""},
            {"message": "problem", "severity": "major", "expected": None},
        )
        for issue in invalid_issues:
            source = json.dumps({"schema_version": 1, "issues": [issue]})
            with self.subTest(issue=issue), self.assertRaises(ValueError):
                parse_clean_review_payload(source)

    def test_legacy_mode_keeps_old_json_and_plain_text_readable(self):
        old_json = parse_clean_review_payload(
            '{"issues":[{"message":"old finding","severity":"high"}]}',
            legacy=True,
        )
        self.assertEqual(old_json["issues"][0]["severity"], "high")
        plain = parse_clean_review_payload("old prose review", legacy=True)
        self.assertEqual(plain["issues"][0]["message"], "old prose review")
        self.assertEqual(plain["issues"][0]["severity"], "unknown")

    def test_cli_rejects_invalid_current_output_without_publishing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "review.tmp"
            payload.write_text("unstructured current review", encoding="utf-8")
            compatibility = root / ".speed/features/payments/reviews/task-1.review"
            compatibility.parent.mkdir(parents=True)
            compatibility.write_text("existing review", encoding="utf-8")

            result = evidence_main([
                "--project-root", str(root),
                "--feature", "payments",
                "--producer", "clean_review",
                "--task", "1",
                "--payload", str(payload),
                "--compatibility", str(compatibility),
            ])

            self.assertEqual(result, 1)
            self.assertEqual(compatibility.read_text(encoding="utf-8"), "existing review")
            archives = list((root / ".speed/features/payments/evidence/clean_review/1").glob("*.json"))
            self.assertEqual(len(archives), 1)
            archived = json.loads(archives[0].read_text(encoding="utf-8"))
            self.assertEqual(archived["payload"]["issues"][0]["message"], "existing review")


if __name__ == "__main__":
    unittest.main()
