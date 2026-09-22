import json
import tempfile
import unittest
from pathlib import Path

from lib.defect_reports import build_report_view, discover_defects, parse_report


class DefectReportTests(unittest.TestCase):
    def test_parses_titled_section_report_without_losing_metadata(self):
        report = parse_report("""# Defect: Retry fails

Severity: P1-high
Related Features: [Payments](specs/product/payments.md), refunds, payments
Related Files: docs/readme.md, src/retry.py
Source: define

## Observed Behavior
Retry charges twice.

## Expected Behavior
Retry is idempotent.

## Reproduction Steps
Run `pytest retry`.
""")
        self.assertEqual(report["title"], "Retry fails")
        self.assertEqual(report["severity"], "P1")
        self.assertEqual(report["related_features"], ["payments", "refunds"])
        self.assertEqual(report["related_files"], ["docs/readme.md", "src/retry.py"])
        self.assertEqual(report["observed"], "Retry charges twice.")

    def test_parses_bold_metadata_and_explicit_empty_features(self):
        report = parse_report("""# Defect: Retry fails

**Severity:** P2-medium
**Related Features:**
**Source:** review

## Observed Behavior
Retry fails.
## Expected Behavior
Retry succeeds.
## Reproduction Steps
Run the retry test.
""")
        self.assertEqual(report["severity"], "P2")
        self.assertEqual(report["related_features"], [])
        self.assertTrue(report["related_features_explicit"])
        self.assertEqual(report["source"], "review")

    def test_union_inventory_filters_related_features_and_derives_lifecycle(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "specs/defects").mkdir(parents=True)
            defects = root / ".speed/defects"
            (defects / "retry").mkdir(parents=True)
            (root / "specs/defects/retry.md").write_text("""# Defect: Retry

Severity: P2
Related Features: payments, refunds
Source: define

## Observed Behavior
Fails.
## Expected Behavior
Works.
## Reproduction Steps
Run it.
""")
            (defects / "retry/state.json").write_text(json.dumps({"status": "resolved", "severity": "P1"}))
            (defects / "state-only").mkdir()
            (defects / "state-only/state.json").write_text(json.dumps({"status": "filed", "related_features": []}))
            rows = discover_defects(root, defects)
            self.assertEqual({row["slug"] for row in rows}, {"retry", "state-only"})
            self.assertEqual(build_report_view(rows)["groups"][-1]["feature"], "_unassigned")
            view = build_report_view(rows, {"features": ["refunds"], "lifecycle": ["closed"]})
            self.assertEqual([row["slug"] for row in view["rows"]], ["retry"])
            self.assertEqual(view["totals"]["closed"], 1)
            self.assertEqual(view["groups"], [])
            unassigned = build_report_view(rows, {"features": ["_unassigned"]})
            self.assertEqual([row["slug"] for row in unassigned["rows"]], ["state-only"])
            self.assertIn("_unassigned", unassigned["facets"]["features"])

    def test_inventory_does_not_follow_canonical_symlink_outside_project(self):
        with tempfile.TemporaryDirectory() as raw, tempfile.NamedTemporaryFile(mode="w", suffix=".md") as outside:
            root = Path(raw)
            (root / "specs/defects").mkdir(parents=True)
            outside.write("# Defect: External\n\nSeverity: P0\n")
            outside.flush()
            (root / "specs/defects/external.md").symlink_to(outside.name)
            rows = discover_defects(root, root / ".speed/defects")
            self.assertEqual(rows[0]["canonical_path"], None)
            self.assertFalse(rows[0]["filed"])
            self.assertIn("Canonical report path escapes the project root", rows[0]["warnings"])


if __name__ == "__main__":
    unittest.main()
