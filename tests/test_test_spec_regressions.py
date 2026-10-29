#!/usr/bin/env python3
"""Regressions for lib/test_spec.py.

Two defects, plus the mapping silence helper:

1. parse_evaluation_gates read the Exit Criteria header with exact cell
   matches, so a real header such as "| Gate | Required result | Enforcement |"
   matched nothing and the function returned zero gates without a word.
2. scenario_references matched any PREFIX-NN token in free prose, so a note
   citing RFC-002 or OOS-10 became a missing-scenario coverage gap, and
   coverage_gaps flagged every row of an unrelated table under the Scenario
   Catalog as a malformed scenario row.
3. silent_scenarios exposes the scenarios whose Selector cell is empty, which
   parse_execution_mapping drops.

Runs as `python3 tests/test_test_spec_regressions.py` and under pytest.
"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.test_spec import (
    coverage_gaps,
    parse_evaluation_gates,
    parse_execution_mapping,
    parse_scenarios,
    scenario_references,
    silent_scenarios,
)

REPO = Path(PROJECT_ROOT)

SPEC = """# Test Spec: Regression fixture

## Scenario Catalog

### Books

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| AC-01 | Given a book exists, when it is deleted, then it is gone | integration | 204; a later read returns 404 |
| AC-02 | Given a list, when a book is added, then it appears | integration | 200; the list holds the book |

## Acceptance Traceability

| RFC acceptance criterion | Covering scenarios |
|---|---|
| ST1: a book can be deleted | AC-01 |

### Additional Coverage

| Source requirement / risk | Covering scenarios | Gap or deferral reference |
|---|---|---|
| VR-1: title required | Covered by RFC-002 and AC-02 | None |

## Execution and Evidence

| Scenario | Selector | Command |
|---|---|---|
| AC-01 | tests/test_books.py::test_delete | |
| AC-02 | | |

## Exit Criteria

| Gate | Status | Evidence |
|---|---|---|
| Release review | pending | Awaiting the release owner |
"""


class ExitCriteriaGates(unittest.TestCase):
    """Defect 1: the Exit Criteria gate table must be read, or the spec rejected."""

    def test_example_bookshelf_spec_declares_its_gates(self):
        text = (REPO / "example/specs/tests/bookshelf.md").read_text(encoding="utf-8")
        gates = parse_evaluation_gates(text)
        self.assertTrue(gates, "the repo's own example spec must yield acceptance gates")
        by_name = {gate["gate"]: gate for gate in gates}
        self.assertIn("Test design ready", by_name)
        design = by_name["Test design ready"]
        self.assertNotEqual("pass", design["status"].strip().lower())
        self.assertIn("Not met on 2026-09-17", design["evidence"])
        for name in ("Merge", "Release", "Exception", "Flaky outcome"):
            self.assertIn(name, by_name)

    def test_template_ships_a_usable_gate_table(self):
        text = (REPO / "templates/test-spec.md").read_text(encoding="utf-8")
        gates = parse_evaluation_gates(text)
        self.assertTrue(gates, "a scaffolded spec must start with explicit gates, not zero")
        names = " ".join(gate["gate"] for gate in gates)
        self.assertIn("Merge", names)
        self.assertIn("Release", names)
        for gate in gates:
            self.assertNotEqual("pass", gate["status"].strip().lower())

    def test_canonical_gate_status_evidence_header_still_parses(self):
        self.assertEqual(
            [{"gate": "Release review", "status": "pending", "evidence": "Awaiting the release owner"}],
            parse_evaluation_gates(SPEC),
        )

    def test_unreadable_gate_table_raises_and_names_the_header(self):
        spec = SPEC.replace("| Gate | Status | Evidence |", "| Criterion | Owner | Comment |")
        with self.assertRaises(ValueError) as caught:
            parse_evaluation_gates(spec)
        message = str(caught.exception)
        self.assertIn("Criterion", message)
        self.assertIn("Exit Criteria", message)

    def test_prose_only_exit_criteria_declares_no_gates(self):
        spec = SPEC[: SPEC.index("## Exit Criteria")] + "## Exit Criteria\n\n- Merge gate: required scenarios pass.\n"
        self.assertEqual([], parse_evaluation_gates(spec))

    def test_short_gate_row_is_rejected(self):
        spec = SPEC.replace("| Release review | pending | Awaiting the release owner |", "| Release review |")
        with self.assertRaises(ValueError):
            parse_evaluation_gates(spec)


class CoverageGapAccuracy(unittest.TestCase):
    """Defect 2: only real scenario references and real scenario rows count."""

    def test_prose_identifiers_are_not_missing_scenarios(self):
        self.assertNotIn("RFC-002", " ".join(coverage_gaps(SPEC)))
        self.assertEqual([], coverage_gaps(SPEC))

    def test_scenario_references_filters_by_catalog_prefix(self):
        self.assertEqual(["AC-02"], scenario_references("Covered by RFC-002 and AC-02", {"AC"}))
        self.assertEqual(["RFC-002", "AC-02"], scenario_references("Covered by RFC-002 and AC-02"))

    def test_genuinely_missing_scenario_reference_is_still_a_gap(self):
        spec = SPEC.replace("Covered by RFC-002 and AC-02", "AC-02, AC-99")
        self.assertIn("VR-1: title required references missing scenarios: AC-99", coverage_gaps(spec))

    def test_requirement_with_no_scenario_is_still_a_gap(self):
        spec = SPEC.replace("Covered by RFC-002 and AC-02", "None. See OOS-04")
        self.assertIn("No scenario covers requirement: VR-1: title required", coverage_gaps(spec))

    def test_unrelated_table_in_the_catalog_is_not_a_scenario_table(self):
        spec = SPEC.replace(
            "## Acceptance Traceability",
            "### Catalog notes\n\n| Note | Detail |\n|---|---|\n"
            "| Fixtures | Reset between cases |\n\n## Acceptance Traceability",
        )
        self.assertEqual([], [gap for gap in coverage_gaps(spec) if gap.startswith("Malformed")])
        self.assertEqual({"AC-01", "AC-02"}, {s["id"] for s in parse_scenarios(spec)})

    def test_malformed_scenario_row_is_still_reported(self):
        spec = SPEC.replace(
            "| AC-02 | Given a list, when a book is added, then it appears | integration | 200; the list holds the book |",
            "| AC-02 | Given a list, when a book is added, then it appears |  | 200; the list holds the book |",
        )
        self.assertIn("Malformed scenario row: AC-02", coverage_gaps(spec))

    def test_example_bookshelf_spec_has_no_phantom_coverage_gaps(self):
        text = (REPO / "example/specs/tests/bookshelf.md").read_text(encoding="utf-8")
        gaps = coverage_gaps(text)
        for gap in gaps:
            self.assertNotIn("missing scenarios: GAP-", gap)
            self.assertNotIn("missing scenarios: OOS-", gap)
        self.assertTrue(
            any(gap.startswith("No scenario covers requirement: F2-5") for gap in gaps),
            f"F2-5 really has no covering scenario: {gaps}",
        )


class SilentScenarios(unittest.TestCase):
    """Rows that map no selector are declared silence, not absence."""

    def test_empty_selector_cell_is_silent(self):
        self.assertEqual({"AC-02"}, silent_scenarios(SPEC))

    def test_each_empty_selector_sentinel_is_silent(self):
        for sentinel in ("-", "none", "N/A", "None"):
            spec = SPEC.replace("| AC-02 | | |", f"| AC-02 | {sentinel} | |")
            self.assertEqual({"AC-02"}, silent_scenarios(spec), sentinel)

    def test_a_scenario_with_one_real_selector_row_is_not_silent(self):
        spec = SPEC.replace("| AC-02 | | |", "| AC-02 | | |\n| AC-02 | tests/test_lists.py::test_add | |")
        self.assertEqual(set(), silent_scenarios(spec))
        self.assertEqual(2, len(parse_execution_mapping(spec)))

    def test_a_scenario_absent_from_the_table_is_not_silent(self):
        spec = SPEC.replace("| AC-02 | | |\n", "")
        self.assertEqual(set(), silent_scenarios(spec))

    def test_missing_mapping_table_returns_an_empty_set(self):
        self.assertEqual(set(), silent_scenarios("# Test Spec: Empty\n\n## Scope\n\nNothing.\n"))

    def test_row_without_a_scenario_id_is_skipped(self):
        spec = SPEC.replace("| AC-02 | | |", "| {PREFIX}-01 | | |")
        self.assertEqual(set(), silent_scenarios(spec))


SPLIT_MAPPING = """# Test Spec: Split mapping

## Scenario Catalog
| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| AC-01 | Read a book | unit | The book |
| AC-02 | Write a book | integration | It is stored |

## Execution and Evidence

Unit scenarios:

| Scenario | Selector | Command |
|---|---|---|
| AC-01 | `tests/test_read.py::test_read` | |

Integration scenarios, whose table names its columns in another order:

| Scenario | Command | Selector |
|---|---|---|
| AC-02 | make integration | `tests/test_write.py::test_write` |
"""


class SplitMappingTable(unittest.TestCase):
    """Each table under Execution and Evidence carries its own header.

    The section used to be flattened into one row list with the first header
    kept for all of it, so a second table's rows were read through the first
    table's column order. Here that put the Command cell where the selector
    belonged and AC-02 was mapped to the words of "make integration".
    """

    def test_a_second_table_is_read_through_its_own_header(self):
        mapping = {case["scenario_id"]: case["selector"]
                   for case in parse_execution_mapping(SPLIT_MAPPING)}
        self.assertEqual(
            {"AC-01": "tests/test_read.py::test_read",
             "AC-02": "tests/test_write.py::test_write"},
            mapping,
        )

    def test_a_split_mapping_declares_no_silence(self):
        self.assertEqual(set(), silent_scenarios(SPLIT_MAPPING))

    def test_an_unreadable_mapping_table_is_an_error_not_a_dropped_table(self):
        """Dropping it would leave its scenarios looking unmapped rather than
        silent, and an unmapped scenario takes the task batch's outcome."""
        spec = SPLIT_MAPPING.replace("| Scenario | Command | Selector |",
                                     "| Scenario | Command | Notes |")
        with self.assertRaisesRegex(ValueError, "Unreadable table"):
            parse_execution_mapping(spec)


if __name__ == "__main__":
    unittest.main()
