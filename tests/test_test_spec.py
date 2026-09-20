import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.test_spec import (
    parse_execution_mapping,
    parse_scenarios,
    parse_traceability,
)

REPO = Path(__file__).resolve().parents[1]

SPEC = """# Test Spec: Books

> See [../tech/books.md](../tech/books.md) for the technical contract under evaluation.

## Scenario Catalog
<!-- AC-99 inside a comment must not be read as a scenario. -->

### Books

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| AC-01 | Given a book exists, when it is deleted, then it is gone | integration | 204; a subsequent read returns 404 |
| {PREFIX}-01 | placeholder row | unit | ignored |
| | Given..., when..., then... | | |

### Lists

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| LIST-02 | Given a list, when a book is added, then it appears | e2e | The list shows the book |

## Acceptance Traceability

| RFC acceptance criterion | Covering scenarios |
|---|---|
| ST1: a book can be deleted | AC-01 |

### Additional Coverage

| Source requirement / risk | Covering scenarios | Gap or deferral reference |
|---|---|---|
| TR4: lists stay ordered | LIST-02 covers the happy path | none |
| TR9: no PAN at rest | none | Deferred; no decision yet |

## Execution and Evidence

- **Execution mapping:** the table below.

| Scenario | Selector | Command |
|---|---|---|
| AC-01 | tests/test_books.py::test_delete tests/test_books.py::test_gone | |
| LIST-02 | | |
| {PREFIX}-01 | tests/ignored.py | |
"""


class ParseScenariosTest(unittest.TestCase):
    def test_reads_only_identifier_rows_from_the_catalog(self):
        scenarios = parse_scenarios(SPEC)
        self.assertEqual(["AC-01", "LIST-02"], [s["id"] for s in scenarios])
        self.assertEqual("integration", scenarios[0]["level"])
        self.assertEqual("204; a subsequent read returns 404", scenarios[0]["expected"])
        self.assertTrue(scenarios[1]["scenario"].startswith("Given a list"))

    def test_scenarios_carry_their_catalog_area(self):
        self.assertEqual(["Books", "Lists"], [s["area"] for s in parse_scenarios(SPEC)])

    def test_traceability_maps_requirement_labels_to_scenarios(self):
        self.assertEqual({"AC-01": ["ST1"], "LIST-02": ["TR4"]}, parse_traceability(SPEC))

    def test_execution_mapping_yields_one_entry_per_selector(self):
        cases = parse_execution_mapping(SPEC)
        self.assertEqual(
            [("AC-01", "tests/test_books.py::test_delete"), ("AC-01", "tests/test_books.py::test_gone")],
            [(c["scenario_id"], c["selector"]) for c in cases],
        )
        self.assertEqual("", cases[0]["command"])
        self.assertEqual([], cases[0]["depends_on_scenarios"])

    def test_mapping_cli_prints_test_plan_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory) / "spec.md"
            spec.write_text(SPEC, encoding="utf-8")
            output = subprocess.run(
                [sys.executable, str(REPO / "lib/test_spec.py"), "mapping", str(spec)],
                capture_output=True, text=True, check=True, cwd=REPO,
            ).stdout
            plan = json.loads(output)
            self.assertEqual(str(spec), plan["test_spec"])
            self.assertEqual(2, len(plan["test_cases"]))

    def test_duplicate_ids_are_preserved_for_the_report_to_flag(self):
        duplicated = SPEC.replace("| LIST-02 |", "| AC-01 |")
        self.assertEqual(["AC-01", "AC-01"], [s["id"] for s in parse_scenarios(duplicated)])

    def test_missing_catalog_yields_no_scenarios(self):
        self.assertEqual([], parse_scenarios("# Test Spec: Empty\n\n## Scope\n\nNothing.\n"))

    def test_example_bookshelf_spec_parses_cleanly(self):
        text = (REPO / "example/specs/tests/bookshelf.md").read_text(encoding="utf-8")
        scenarios = parse_scenarios(text)
        ids = [s["id"] for s in scenarios]
        self.assertEqual(43, len(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({"db", "e2e", "integration"}, {s["level"] for s in scenarios})
        self.assertTrue(all(s["area"] for s in scenarios), "every bookshelf scenario sits under an H3 area")

    def test_list_cli_prints_json(self):
        spec_path = REPO / "example/specs/tests/bookshelf.md"
        output = subprocess.run(
            [sys.executable, str(REPO / "lib/test_spec.py"), "list", str(spec_path)],
            capture_output=True, text=True, check=True, cwd=REPO,
        ).stdout
        self.assertEqual(43, len(json.loads(output)))


if __name__ == "__main__":
    unittest.main()
