import json
import tempfile
import unittest
from difflib import SequenceMatcher
from pathlib import Path

from lib.eval_review_adapter import (
    prove_ownership,
    ReviewAdapterError,
    build_test_plan,
    review_scenarios,
    scenario_findings,
)
from lib.eval_criteria import task_scenarios
from lib.eval_runtime import validate_plan
from lib.eval_selection import select_plan
from lib.review_evidence import parse_clean_review_payload, parse_report_findings_events

SPEC = """
## Scenario Catalog

### Refund

| ID | Scenario | Level | Expected |
|---|---|---|---|
| RETRY-01 | a retried refund is accepted | integration | the refund succeeds |
| RETRY-02 | a third attempt is refused | integration | the refund is refused |
"""

TESTS = """
import { test } from 'node:test';

test('[RETRY-01] a retried refund is accepted', () => {});
test('[RETRY-02] a third attempt is refused', () => {});
test('untagged housekeeping', () => {});
"""

TASK = {
    "id": "1",
    "status": "done",
    "files_touched": ["src/payments/retry.ts", "test/refund-retry.test.ts"],
}

CONFIG = {
    "test_commands": ["node --test {selectors}"],
    "test_file_patterns": ["test/*.test.ts"],
}


def _transcript(findings):
    """A provider event log whose ReportFindings call was confirmed."""
    return "\n".join(json.dumps(event) for event in (
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "ReportFindings", "id": "t1",
             "input": {"findings": findings}}]}},
        {"type": "user",
         "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}], "role": "user"},
         "tool_use_result": {"count": len(findings), "findings": findings}},
    ))


def issue(**overrides):
    base = {"message": "Retry helper is untested", "severity": "major"}
    base.update(overrides)
    return base


def review(*issues):
    return {"schema_version": 1, "issues": list(issues)}


class ReviewAdapterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "test").mkdir()
        (self.root / "test" / "refund-retry.test.ts").write_text(TESTS, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def plan(self, payload):
        return build_test_plan(payload, SPEC, self.root, CONFIG, TASK)

    # A. Valid review issue with scenario_id -> valid eval test-plan entry.
    def test_scenario_linked_finding_becomes_an_executable_case(self):
        plan = self.plan(review(issue(scenario_id="RETRY-01", testable=True)))
        self.assertEqual(len(plan["test_cases"]), 1)
        case = plan["test_cases"][0]
        self.assertEqual(case["scenario_id"], "RETRY-01")
        self.assertEqual(case["selector"], "test/refund-retry.test.ts")
        self.assertEqual(case["test_name"], "[RETRY-01] a retried refund is accepted")
        self.assertEqual(case["runner"], "node")
        self.assertEqual(case["task_id"], "1")
        self.assertEqual(case["source"], "review_findings")
        # The engine's own validator must accept what the adapter produced.
        validate_plan(plan, {"RETRY-01", "RETRY-02"}, [TASK])

    # B. Unknown scenario_id -> deterministic validation error.
    def test_unknown_scenario_is_rejected_by_name(self):
        with self.assertRaises(ReviewAdapterError) as caught:
            self.plan(review(issue(scenario_id="NOPE-99", testable=True)))
        self.assertIn("NOPE-99", str(caught.exception))

    # C. Missing scenario_id -> dropped, never guessed.
    def test_finding_without_scenario_is_dropped_not_inferred(self):
        plan = self.plan(review(
            issue(file="src/payments/retry.ts", line=9, testable=True),
            issue(scenario_id="RETRY-01"),
        ))
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-01"])

    # C (cont). testable absent must not exclude a scenario-linked finding.
    def test_absent_testable_still_selects(self):
        self.assertEqual(len(scenario_findings(review(issue(scenario_id="RETRY-01")))), 1)

    # D. testable: false -> never becomes an executable case.
    def test_untestable_finding_produces_no_case(self):
        payload = review(issue(scenario_id="RETRY-01", testable=False))
        self.assertEqual(scenario_findings(payload), [])
        plan = self.plan(payload)
        self.assertEqual(plan["test_cases"], [])
        self.assertEqual(plan["selection"]["scenario_ids"], [])

    # D (cont). An untestable finding must not smuggle its scenario in via a
    # second, testable finding being absent.
    def test_untestable_is_excluded_even_alongside_a_testable_peer(self):
        plan = self.plan(review(
            issue(scenario_id="RETRY-01", testable=False),
            issue(scenario_id="RETRY-02", testable=True),
        ))
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-02"])

    # E. Multiple issues mapping to multiple scenarios.
    def test_multiple_findings_map_to_multiple_scenarios(self):
        plan = self.plan(review(
            issue(scenario_id="RETRY-01", testable=True),
            issue(message="Third attempt is wrong", severity="critical",
                  scenario_id="RETRY-02", testable=True),
        ))
        self.assertEqual(
            sorted(c["scenario_id"] for c in plan["test_cases"]),
            ["RETRY-01", "RETRY-02"],
        )
        validate_plan(plan, {"RETRY-01", "RETRY-02"}, [TASK])

    # E (cont). Two findings on one scenario collapse to a single case.
    def test_duplicate_scenario_references_collapse(self):
        plan = self.plan(review(
            issue(scenario_id="RETRY-01", testable=True),
            issue(message="Same scenario, other angle", severity="minor",
                  scenario_id="RETRY-01", testable=True),
        ))
        self.assertEqual([c["scenario_id"] for c in plan["test_cases"]], ["RETRY-01"])

    def test_declared_scenario_without_a_tagged_test_is_reported_as_a_gap(self):
        (self.root / "test" / "refund-retry.test.ts").write_text(
            "test('[RETRY-01] a retried refund is accepted', () => {});", encoding="utf-8")
        plan = self.plan(review(issue(scenario_id="RETRY-02", testable=True)))
        self.assertEqual(plan["test_cases"], [])
        self.assertTrue(any("RETRY-02" in n for n in plan["selection"]["review_notes"]))

    # Fix 1 invariant: every emitted case is owned by the requested task.
    def test_every_emitted_case_claims_only_this_task(self):
        plan = self.plan(review(
            issue(scenario_id="RETRY-01", testable=True),
            issue(scenario_id="RETRY-02", testable=True),
        ))
        self.assertTrue(plan["test_cases"])
        for case in plan["test_cases"]:
            self.assertEqual(case["task_id"], "1")
            # The claim is only sound because the selector's file is one of
            # this task's own candidates.
            self.assertIn(case["selector"].split("::", 1)[0], TASK["files_touched"])

    # Fix 2: a scenario owned by another task names that task and does not run.
    def test_cross_task_scenario_names_its_owner_and_produces_no_case(self):
        other_tests = "test('[RISK-02] the scheme fee rounds half up', () => {});\n"
        (self.root / "test" / "service.test.ts").write_text(other_tests, encoding="utf-8")
        spec = SPEC + "| RISK-02 | fee rounds half up | integration | fee 3 |\n"
        other = {"id": "2", "status": "done",
                 "files_touched": ["src/payments/service.ts", "test/service.test.ts"]}
        plan = build_test_plan(review(issue(scenario_id="RISK-02", testable=True)),
                               spec, self.root, CONFIG, TASK, [TASK, other])
        self.assertEqual(plan["test_cases"], [], "cross-task test must not execute")
        self.assertEqual(plan["selection"]["scenario_ids"], ["RISK-02"])
        gap = plan["selection"]["review_notes"][0]
        self.assertIn("RISK-02", gap)
        self.assertIn("owned by task 2", gap)
        self.assertIn("feature-scoped", gap)

    def test_unknown_owner_gap_does_not_guess(self):
        # No sibling tasks supplied: state only that it is out of scope.
        spec = SPEC + "| RISK-02 | fee rounds half up | integration | fee 3 |\n"
        plan = build_test_plan(review(issue(scenario_id="RISK-02", testable=True)),
                               spec, self.root, CONFIG, TASK)
        gap = plan["selection"]["review_notes"][0]
        self.assertIn("outside task 1's candidate scope", gap)
        self.assertNotIn("owned by task", gap)

    def test_review_scenarios_preserves_first_seen_order(self):
        payload = review(
            issue(scenario_id="RETRY-02", testable=True),
            issue(scenario_id="RETRY-01", testable=True),
        )
        self.assertEqual(review_scenarios(payload, {"RETRY-01", "RETRY-02"}),
                         (["RETRY-02", "RETRY-01"], []))

    def test_unknown_scenario_raises_under_strict_but_is_a_gap_otherwise(self):
        # The explicit CLI keeps its deterministic error. Eval's automatic path
        # must not lose a whole review to one out-of-catalog identifier, such
        # as an Out of Scope deferral row the reviewer quoted from the diff.
        payload = review(issue(scenario_id="RETRY-01", testable=True),
                         issue(scenario_id="OOS-01", testable=True))
        with self.assertRaises(ReviewAdapterError):
            review_scenarios(payload, {"RETRY-01"})
        self.assertEqual(review_scenarios(payload, {"RETRY-01"}, strict=False),
                         (["RETRY-01"], ["OOS-01"]))


class SchemaCompatibilityTests(unittest.TestCase):
    # F. Existing review JSON without the new optional fields stays valid.
    def test_review_without_new_fields_is_unchanged(self):
        payload = json.dumps({"schema_version": 1, "issues": [
            {"message": "Capture fee floors instead of rounding",
             "severity": "critical", "file": "src/payments/service.ts", "line": 119},
        ]})
        parsed = parse_clean_review_payload(payload)
        self.assertEqual(parsed["schema_version"], 1)
        self.assertNotIn("scenario_id", parsed["issues"][0])
        self.assertNotIn("testable", parsed["issues"][0])

    def test_new_fields_round_trip_through_the_validator(self):
        payload = json.dumps({"schema_version": 1, "issues": [
            {"message": "Retry helper is untested", "severity": "major",
             "scenario_id": "RETRY-01", "testable": True},
        ]})
        parsed = parse_clean_review_payload(payload)
        self.assertEqual(parsed["issues"][0]["scenario_id"], "RETRY-01")
        self.assertIs(parsed["issues"][0]["testable"], True)

    def test_malformed_scenario_id_is_rejected(self):
        for bad in ("retry-01", "RETRY-1", "RETRY", "", 7):
            with self.subTest(bad=bad):
                payload = json.dumps({"schema_version": 1, "issues": [
                    {"message": "m", "severity": "nit", "scenario_id": bad}]})
                with self.assertRaises(ValueError):
                    parse_clean_review_payload(payload)

    def test_non_boolean_testable_is_rejected(self):
        for bad in (1, 0, "true", None if False else "yes"):
            with self.subTest(bad=bad):
                payload = json.dumps({"schema_version": 1, "issues": [
                    {"message": "m", "severity": "nit", "testable": bad}]})
                with self.assertRaises(ValueError):
                    parse_clean_review_payload(payload)

    def test_tool_transcript_recovers_scenario_fields_from_final_json(self):
        # ReportFindings carries no scenario_id/testable of its own. Without
        # recovery the persisted review silently loses every declared
        # scenario, which is exactly how the first end-to-end run failed.
        findings = [{"summary": "Capture fee floors instead of rounding",
                     "severity": "critical", "file": "src/payments/service.ts", "line": 119}]
        events = "\n".join(json.dumps(event) for event in (
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "ReportFindings", "id": "t1",
                 "input": {"findings": findings}}]}},
            {"type": "user",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}], "role": "user"},
             "tool_use_result": {"count": 1, "findings": findings}},
        ))
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": "Capture fee floors instead of rounding", "severity": "critical",
             "file": "src/payments/service.ts", "line": 119,
             "scenario_id": "RISK-02", "testable": True}]})
        parsed = parse_report_findings_events(events, final_text=final)
        self.assertEqual(parsed["issues"][0]["scenario_id"], "RISK-02")
        self.assertIs(parsed["issues"][0]["testable"], True)

    def test_scenario_survives_when_wording_shares_almost_nothing(self):
        # Gap #2. The real failing run had file 5/5 and line 5/5 matching while
        # message similarity ran 0.053-0.506, because ReportFindings.summary is
        # a compressed label and the final message is a full sentence. Every
        # declared scenario was dropped. Recovery must key off location alone.
        findings = [{"summary": "retry helper needs coverage", "severity": "major",
                     "file": "src/payments/retry.ts", "line": 9}]
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": "The refund retry implementation does not have sufficient "
                        "coverage for the retry path.",
             "severity": "major", "file": "src/payments/retry.ts", "line": 9,
             "scenario_id": "RETRY-01", "testable": True}]})
        ratio = SequenceMatcher(
            None, "retry helper needs coverage",
            "the refund retry implementation does not have sufficient coverage for the retry path",
        ).ratio()
        self.assertLess(ratio, 0.8, "fixture must stay below the old prose threshold")
        parsed = parse_report_findings_events(_transcript(findings), final_text=final)
        self.assertEqual(parsed["issues"][0]["scenario_id"], "RETRY-01")
        self.assertIs(parsed["issues"][0]["testable"], True)

    def test_testable_false_survives_ingestion(self):
        findings = [{"summary": "naming nit", "severity": "nit",
                     "file": "test/fixtures/cards.ts", "line": 19}]
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": "RETRY_TEST_CARD is added to the fixtures but never referenced.",
             "severity": "nit", "file": "test/fixtures/cards.ts", "line": 19,
             "testable": False}]})
        parsed = parse_report_findings_events(_transcript(findings), final_text=final)
        self.assertIs(parsed["issues"][0]["testable"], False)
        self.assertNotIn("scenario_id", parsed["issues"][0])

    def test_finding_without_scenario_id_still_persists(self):
        findings = [{"summary": "scope creep", "severity": "minor", "file": ".gitignore"}]
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": "The diff modifies many files outside the declared list.",
             "severity": "minor", "file": ".gitignore"}]})
        parsed = parse_report_findings_events(_transcript(findings), final_text=final)
        self.assertEqual(len(parsed["issues"]), 1)
        self.assertEqual(parsed["issues"][0]["severity"], "minor")
        self.assertNotIn("scenario_id", parsed["issues"][0])
        self.assertNotIn("testable", parsed["issues"][0])

    def test_location_mismatch_abandons_recovery_rather_than_misattributing(self):
        # Wrong-but-plausible attachment is worse than no attachment: a
        # scenario bound to the wrong finding would be indistinguishable from
        # evidence downstream.
        findings = [{"summary": "a", "severity": "major",
                     "file": "src/payments/retry.ts", "line": 9}]
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": "Some other finding entirely", "severity": "major",
             "file": "src/payments/service.ts", "line": 119,
             "scenario_id": "RISK-02", "testable": True}]})
        parsed = parse_report_findings_events(_transcript(findings), final_text=final)
        self.assertNotIn("scenario_id", parsed["issues"][0])

    def test_recovery_survives_five_findings_with_wholly_different_wording(self):
        # The exact shape of the failing production run: five findings, every
        # summary reworded, two carrying scenarios.
        spots = [("src/payments/service.ts", 119), ("test/refund-retry.test.ts", 1),
                 ("src/payments/retry.ts", 24), ("test/fixtures/cards.ts", 19),
                 (".gitignore", None)]
        scenarios = ["RISK-02", "RETRY-01", None, None, None]
        findings, final_issues = [], []
        for index, ((path, line), sid) in enumerate(zip(spots, scenarios)):
            tool = {"summary": f"short label {index}", "severity": "major", "file": path}
            final_issue = {"message": f"A completely different sentence describing finding "
                                      f"number {index} at length.",
                           "severity": "major", "file": path}
            if line is not None:
                tool["line"] = line
                final_issue["line"] = line
            if sid:
                final_issue["scenario_id"] = sid
            final_issue["testable"] = sid is not None
            findings.append(tool)
            final_issues.append(final_issue)
        parsed = parse_report_findings_events(
            _transcript(findings),
            final_text=json.dumps({"schema_version": 1, "issues": final_issues}),
        )
        self.assertEqual(
            [i.get("scenario_id") for i in parsed["issues"]],
            ["RISK-02", "RETRY-01", None, None, None],
        )
        self.assertEqual([i["testable"] for i in parsed["issues"]],
                         [True, True, False, False, False])

    def test_one_location_mismatch_does_not_erase_the_other_scenarios(self):
        # The exact real-run shape: six findings, five locations agree, the
        # sixth disagrees because the tool carried a `file` the final JSON
        # omitted. All-or-nothing recovery lost RISK-02 and RETRY-01 with it.
        spots = [("src/payments/service.ts", 67), ("src/payments/service.ts", 119),
                 ("src/payments/retry.ts", 12), ("src/payments/service.ts", 17),
                 ("test/fixtures/cards.ts", 19), ("test/service.test.ts", None)]
        scenarios = [None, "RISK-02", "RETRY-01", None, None, None]
        findings, final_issues = [], []
        for index, ((path, line), sid) in enumerate(zip(spots, scenarios)):
            tool = {"summary": f"label {index}", "severity": "major", "file": path}
            final_issue = {"message": f"A differently worded sentence {index}.",
                           "severity": "major"}
            # The last finding is the disagreement: tool has a file, the final
            # JSON has none.
            if index < 5:
                final_issue["file"] = path
            if line is not None:
                tool["line"] = line
                final_issue["line"] = line
            if sid:
                final_issue["scenario_id"] = sid
            final_issue["testable"] = sid is not None
            findings.append(tool)
            final_issues.append(final_issue)
        parsed = parse_report_findings_events(
            _transcript(findings),
            final_text=json.dumps({"schema_version": 1, "issues": final_issues}),
        )
        self.assertEqual([i.get("scenario_id") for i in parsed["issues"]],
                         [None, "RISK-02", "RETRY-01", None, None, None])
        # The five aligned findings recovered `testable`; the sixth did not.
        self.assertEqual([i.get("testable") for i in parsed["issues"]],
                         [False, True, True, False, False, None])
        self.assertNotIn("testable", parsed["issues"][5])

    def test_mismatched_finding_recovers_nothing_of_its_own(self):
        # Per-finding skipping must not become per-finding guessing: the
        # disagreeing position takes no fields from the issue opposite it.
        findings = [
            {"summary": "a", "severity": "major", "file": "src/a.ts", "line": 1},
            {"summary": "b", "severity": "major", "file": "src/b.ts", "line": 2},
        ]
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": "first", "severity": "major", "file": "src/a.ts", "line": 1,
             "scenario_id": "AC-01", "testable": True},
            {"message": "second", "severity": "major", "file": "src/OTHER.ts", "line": 99,
             "scenario_id": "AC-02", "testable": True},
        ]})
        parsed = parse_report_findings_events(_transcript(findings), final_text=final)
        self.assertEqual(parsed["issues"][0]["scenario_id"], "AC-01")
        self.assertNotIn("scenario_id", parsed["issues"][1],
                         "AC-02 must not attach to a finding at a different location")

    def test_recovery_uses_no_message_similarity_at_all(self):
        # Identical locations, deliberately opposite wording. If any similarity
        # gate survived anywhere, this would recover nothing.
        findings = [{"summary": "zzz", "severity": "major",
                     "file": "src/payments/service.ts", "line": 119}]
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": "qqq totally unrelated prose sharing no vocabulary whatsoever",
             "severity": "major", "file": "src/payments/service.ts", "line": 119,
             "scenario_id": "RISK-02", "testable": True}]})
        ratio = SequenceMatcher(None, "zzz",
                                "qqq totally unrelated prose sharing no vocabulary whatsoever").ratio()
        self.assertLess(ratio, 0.3)
        parsed = parse_report_findings_events(_transcript(findings), final_text=final)
        self.assertEqual(parsed["issues"][0]["scenario_id"], "RISK-02")

    def test_unequal_counts_still_recover_nothing(self):
        # Position identifies a finding only while both channels describe the
        # same set. Unequal counts must remain all-or-nothing.
        findings = [{"summary": "a", "severity": "major", "file": "src/a.ts", "line": 1}]
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": "first", "severity": "major", "file": "src/a.ts", "line": 1,
             "scenario_id": "AC-01"},
            {"message": "extra", "severity": "nit"},
        ]})
        parsed = parse_report_findings_events(_transcript(findings), final_text=final)
        self.assertNotIn("scenario_id", parsed["issues"][0])

    def test_legacy_findings_without_new_fields_still_persist(self):
        findings = [{"summary": "a", "severity": "major", "file": "src/a.ts", "line": 1}]
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": "first", "severity": "major", "file": "src/a.ts", "line": 1}]})
        parsed = parse_report_findings_events(_transcript(findings), final_text=final)
        self.assertEqual(len(parsed["issues"]), 1)
        self.assertEqual(parsed["issues"][0]["severity"], "major")
        self.assertNotIn("scenario_id", parsed["issues"][0])
        self.assertNotIn("testable", parsed["issues"][0])

    def test_severity_recovers_per_finding_without_similarity(self):
        # Three findings, all severities omitted by the tool, all wordings
        # different. Locations agree, so every severity recovers.
        spots = [("src/a.ts", 1), ("src/b.ts", 2), ("src/c.ts", 3)]
        sev = ["critical", "major", "nit"]
        findings = [{"summary": f"short {i}", "file": p, "line": l}
                    for i, (p, l) in enumerate(spots)]
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": f"an entirely different sentence about item {i}",
             "severity": s, "file": p, "line": l}
            for i, ((p, l), s) in enumerate(zip(spots, sev))]})
        parsed = parse_report_findings_events(_transcript(findings), final_text=final)
        self.assertEqual([i["severity"] for i in parsed["issues"]], sev)

    def test_one_unrecoverable_severity_declines_rather_than_raises(self):
        # Severity is required by the schema, so a finding whose severity
        # cannot be recovered cannot be published from the transcript. The
        # transcript is declined (None) so the caller falls back to the final
        # JSON. It must not raise, which previously exited the review 3.
        findings = [{"summary": "a", "file": "src/a.ts", "line": 1},
                    {"summary": "b", "file": "src/b.ts", "line": 2}]
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": "first", "severity": "major", "file": "src/a.ts", "line": 1},
            {"message": "second", "severity": "minor", "file": "src/ELSEWHERE.ts", "line": 9},
        ]})
        self.assertIsNone(parse_report_findings_events(_transcript(findings), final_text=final))

    def test_partial_severity_omission_still_recovers_the_rest(self):
        # One severity supplied by the tool, one omitted and recovered.
        findings = [{"summary": "a", "severity": "critical", "file": "src/a.ts", "line": 1},
                    {"summary": "b", "file": "src/b.ts", "line": 2}]
        final = json.dumps({"schema_version": 1, "issues": [
            {"message": "first", "severity": "nit", "file": "src/a.ts", "line": 1},
            {"message": "second", "severity": "minor", "file": "src/b.ts", "line": 2},
        ]})
        parsed = parse_report_findings_events(_transcript(findings), final_text=final)
        # The tool's own severity wins where it supplied one.
        self.assertEqual([i["severity"] for i in parsed["issues"]], ["critical", "minor"])

    def test_severity_is_never_invented_without_a_final_json(self):
        findings = [{"summary": "a", "file": "src/a.ts", "line": 1}]
        self.assertIsNone(parse_report_findings_events(_transcript(findings)))

    def test_mismatched_final_json_does_not_fail_a_complete_transcript(self):
        # Recovery is best-effort: a drifted final JSON must not turn a review
        # whose severities were all supplied into an error.
        findings = [{"summary": "Retry helper is untested", "severity": "major",
                     "file": "src/payments/retry.ts", "line": 9}]
        events = "\n".join(json.dumps(event) for event in (
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "ReportFindings", "id": "t1",
                 "input": {"findings": findings}}]}},
            {"type": "user",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}], "role": "user"},
             "tool_use_result": {"count": 1, "findings": findings}},
        ))
        unrelated = json.dumps({"schema_version": 1, "issues": [
            {"message": "Something else entirely", "severity": "nit"}]})
        parsed = parse_report_findings_events(events, final_text=unrelated)
        self.assertEqual(len(parsed["issues"]), 1)
        self.assertNotIn("scenario_id", parsed["issues"][0])

    def test_unknown_fields_are_still_rejected(self):
        payload = json.dumps({"schema_version": 1, "issues": [
            {"message": "m", "severity": "nit", "scenario_ids": ["RETRY-01"]}]})
        with self.assertRaises(ValueError):
            parse_clean_review_payload(payload)


class SharedFileOwnershipTests(unittest.TestCase):
    """Ownership must be proven, never inferred from a shared touched file."""

    SPEC = SPEC

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "test").mkdir()
        (self.root / "test" / "refund-retry.test.ts").write_text(TESTS, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)
        # Task 2 also touches the same test file: the payments fixture's real shape.
        self.sharer = {"id": "2", "status": "done",
                       "files_touched": ["src/payments/service.ts",
                                         "test/refund-retry.test.ts"]}

    def plan(self, task, tasks):
        return build_test_plan(review(issue(scenario_id="RETRY-01", testable=True)),
                               self.SPEC, self.root, CONFIG, task, tasks)

    # 1. Uniquely owned scenario: the only task touching the file.
    def test_unique_file_owner_is_proven(self):
        plan = self.plan(TASK, [TASK])
        self.assertEqual(len(plan["test_cases"]), 1)
        self.assertEqual(plan["test_cases"][0]["task_id"], "1")

    # 2. Shared test file, nothing declared: ambiguous, so no case.
    def test_shared_file_produces_no_case_and_an_explicit_gap(self):
        plan = self.plan(TASK, [TASK, self.sharer])
        self.assertEqual(plan["test_cases"], [],
                         "a shared touched file must not establish ownership")
        gap = " ".join(plan["selection"]["gaps"])
        self.assertIn("shares with task 2", gap)
        self.assertIn("does not", gap)
        self.assertIn("acceptance criteria", gap)

    # 3. Explicitly owned via the task's own declared scenarios.
    def test_declared_criterion_proves_ownership_despite_sharing(self):
        declaring = {**TASK, "acceptance_criteria": [
            {"criterion": "[RETRY-01] a retried refund is accepted", "verify_by": "test"}]}
        plan = self.plan(declaring, [declaring, self.sharer])
        self.assertEqual(len(plan["test_cases"]), 1)
        self.assertEqual(plan["test_cases"][0]["task_id"], "1")

    def test_required_test_cases_also_proves_ownership(self):
        declaring = {**TASK, "required_test_cases": ["RETRY-01"]}
        plan = self.plan(declaring, [declaring, self.sharer])
        self.assertEqual(len(plan["test_cases"]), 1)

    # 4. Cross-task: the spec assigns the scenario to another task.
    def test_spec_assignment_to_another_task_is_refused(self):
        spec = SPEC + (
            "\n## Execution and Evidence\n\n"
            "| Scenario ID | Task | Selector |\n|---|---|---|\n"
            "| RETRY-01 | 2 | test/refund-retry.test.ts |\n"
        )
        plan = build_test_plan(review(issue(scenario_id="RETRY-01", testable=True)),
                               spec, self.root, CONFIG, TASK, [TASK, self.sharer])
        self.assertEqual(plan["test_cases"], [])
        self.assertIn("assigned to task 2", " ".join(plan["selection"]["review_notes"]))

    def test_spec_assignment_to_this_task_is_honoured(self):
        spec = SPEC + (
            "\n## Execution and Evidence\n\n"
            "| Scenario ID | Task | Selector |\n|---|---|---|\n"
            "| RETRY-01 | 1 | test/refund-retry.test.ts |\n"
        )
        plan = build_test_plan(review(issue(scenario_id="RETRY-01", testable=True)),
                               spec, self.root, CONFIG, TASK, [TASK, self.sharer])
        self.assertEqual(len(plan["test_cases"]), 1)
        self.assertEqual(plan["test_cases"][0]["task_id"], "1")

    # 5. Unknown ownership: no task list supplied, file is this task's only.
    def test_absent_task_list_falls_back_to_this_task_alone(self):
        plan = build_test_plan(review(issue(scenario_id="RETRY-01", testable=True)),
                               self.SPEC, self.root, CONFIG, TASK)
        self.assertEqual(len(plan["test_cases"]), 1)

    # 6. The adapter never emits a task_id it cannot prove.
    def test_no_case_ever_carries_an_unproven_task_id(self):
        for tasks in ([TASK], [TASK, self.sharer]):
            with self.subTest(tasks=len(tasks)):
                plan = self.plan(TASK, tasks)
                for case in plan["test_cases"]:
                    proven, _, _ = prove_ownership(
                        case["scenario_id"], case["selector"], TASK, CONFIG,
                        {}, tasks)
                    self.assertTrue(proven, "emitted a case whose ownership is unproven")

    # 7. The real engine agrees with whatever the adapter decided.
    def test_real_select_plan_agrees_with_the_adapter(self):
        tasks = [TASK, self.sharer]
        plan = self.plan(TASK, tasks)
        out = select_plan(plan, self.SPEC, tasks, CONFIG, "1", task_scenarios, override=True)
        self.assertEqual(plan["test_cases"], [])
        self.assertEqual(out["test_cases"], [],
                         "engine and adapter must reach the same refusal")

    def test_engine_would_have_refused_the_same_shared_case(self):
        # Without a claim the engine calls it Ambiguous; the adapter now
        # declines to make that claim, so the two agree instead of conflicting.
        tasks = [TASK, self.sharer]
        out = select_plan({"test_cases": [{
            "scenario_id": "RETRY-01", "selector": "test/refund-retry.test.ts",
            "command": "node --test {selectors}", "runner": "node",
            "test_name": "[RETRY-01] a retried refund is accepted"}]},
            self.SPEC, tasks, CONFIG, "1", task_scenarios, override=True)
        self.assertEqual(out["test_cases"], [])
        self.assertIn("Ambiguous", " ".join(out["selection"]["gaps"]))


class RealOwnershipTests(unittest.TestCase):
    """Exercise the engine's real select_plan, not a stand-in for it."""

    SPEC = SPEC + "| RISK-02 | fee rounds half up | integration | fee 3 |\n"
    TASKS = [
        TASK,
        {"id": "2", "status": "done",
         "files_touched": ["src/payments/service.ts", "test/service.test.ts"]},
    ]

    def select(self, case):
        return select_plan({"test_cases": [case]}, self.SPEC, self.TASKS, CONFIG,
                           "1", task_scenarios, override=True)

    def test_adapter_owned_case_is_kept_by_select_plan(self):
        kept = self.select({
            "scenario_id": "RETRY-01", "task_id": "1",
            "selector": "test/refund-retry.test.ts", "command": "node --test {selectors}",
            "runner": "node", "test_name": "[RETRY-01] a retried refund is accepted",
        })
        self.assertEqual(len(kept["test_cases"]), 1)
        self.assertEqual(kept["test_cases"][0]["task_id"], "1")

    def test_cross_task_case_without_task_id_is_dropped_by_select_plan(self):
        # This is why the adapter must not stamp task_id onto a test it does
        # not own: without the claim the engine correctly refuses it.
        kept = self.select({
            "scenario_id": "RISK-02",
            "selector": "test/service.test.ts", "command": "node --test {selectors}",
            "runner": "node", "test_name": "[RISK-02] fee rounds half up",
        })
        self.assertEqual(kept["test_cases"], [])

    def test_a_false_task_id_would_defeat_the_engine_guard(self):
        # Documents the hazard the adapter is responsible for not creating:
        # select_plan trusts an explicit owner, so the guard cannot save us.
        kept = self.select({
            "scenario_id": "RISK-02", "task_id": "1",
            "selector": "test/service.test.ts", "command": "node --test {selectors}",
            "runner": "node", "test_name": "[RISK-02] fee rounds half up",
        })
        self.assertEqual(len(kept["test_cases"]), 1,
                         "engine trusts an explicit owner; only the adapter can prevent this")

    def test_adapter_never_emits_such_a_case(self):
        # The end-to-end guarantee: run the adapter over a tree where RISK-02's
        # test exists but belongs to task 2, then feed whatever it produced to
        # the real select_plan. Nothing may execute under task 1.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "test").mkdir()
        (root / "test" / "refund-retry.test.ts").write_text(TESTS, encoding="utf-8")
        (root / "test" / "service.test.ts").write_text(
            "test('[RISK-02] fee rounds half up', () => {});\n", encoding="utf-8")
        plan = build_test_plan(review(issue(scenario_id="RISK-02", testable=True)),
                               self.SPEC, root, CONFIG, TASK, self.TASKS)
        self.assertEqual(plan["test_cases"], [])
        kept = select_plan(plan, self.SPEC, self.TASKS, CONFIG, "1",
                           task_scenarios, override=True)
        self.assertEqual(kept["test_cases"], [])


class TestPlanContractTests(unittest.TestCase):
    # G. Existing --test-plan behaviour is unchanged by the adapter.
    def test_hand_written_plan_still_validates(self):
        plan = {"test_cases": [
            {"scenario_id": "RETRY-01", "selector": "test/refund-retry.test.ts"}]}
        validate_plan(plan, {"RETRY-01"}, [TASK])

    def test_plan_with_unknown_scenario_is_still_rejected_by_the_engine(self):
        plan = {"test_cases": [{"scenario_id": "GONE-01", "selector": "test/x.test.ts"}]}
        with self.assertRaises(ValueError):
            validate_plan(plan, {"RETRY-01"}, [TASK])


if __name__ == "__main__":
    unittest.main()


class GapClarityTests(unittest.TestCase):
    """An ownership refusal must not also claim the test was never found."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "test").mkdir()
        (self.root / "test" / "refund-retry.test.ts").write_text(TESTS, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def test_shared_file_refusal_emits_exactly_one_reason(self):
        sharer = {"id": "2", "status": "done",
                  "files_touched": ["test/refund-retry.test.ts"]}
        plan = build_test_plan(review(issue(scenario_id="RETRY-01", testable=True)),
                               SPEC, self.root, CONFIG, TASK, [TASK, sharer])
        # Ambiguity is this task's problem to resolve, so it stays a real gap
        # and keeps its power to block. Only "another task owns it" is a note.
        gaps = [g for g in plan["selection"]["gaps"] if "RETRY-01" in g]
        self.assertEqual(len(gaps), 1, f"expected one reason, got: {gaps}")
        self.assertIn("shares with task 2", gaps[0])
        self.assertNotIn("no tagged test", gaps[0])
        self.assertEqual(plan["selection"]["review_notes"], [],
                         "an ambiguous refusal is not a non-blocking note")


class NullCriteriaRobustnessTests(unittest.TestCase):
    """The adapter reads task JSON directly, without validate_task's guard."""

    def test_null_acceptance_criteria_does_not_raise(self):
        # eval_criteria.task_scenarios raises TypeError on an explicit null.
        # validate_task rejects that value first for the engine, but the
        # adapter has no such gate, so it must degrade to "nothing declared".
        task = {"id": "1", "files_touched": ["test/a.test.ts"],
                "acceptance_criteria": None}
        proven, reason, _ = prove_ownership(
            "RETRY-01", "test/a.test.ts", task, CONFIG, {}, [task])
        self.assertTrue(proven, "unique file owner still proves ownership")
        self.assertIsNone(reason)

    def test_null_criteria_cannot_manufacture_ownership_of_a_shared_file(self):
        task = {"id": "1", "files_touched": ["test/a.test.ts"],
                "acceptance_criteria": None}
        other = {"id": "2", "files_touched": ["test/a.test.ts"]}
        proven, reason, _ = prove_ownership(
            "RETRY-01", "test/a.test.ts", task, CONFIG, {}, [task, other])
        self.assertFalse(proven)
        self.assertIn("shares with task 2", reason)
