"""Parse feature test specifications.

A test spec (specs/tests/<name>.md) is the durable bridge between an RFC's
acceptance criteria and executable tests. The following sections are machine-read:

- Scenario Catalog: every table row whose first cell is a PREFIX-NN identifier
  is a scenario, grouped under the H3 area it appears in.
- Acceptance Traceability, including its Additional Coverage table: which
  requirement rows cite each scenario ID.
- Execution and Evidence: the Scenario / Selector / Command table that maps
  each scenario to the test selector that executes it.
- Out of Scope: rows the spec deliberately does not examine, with their owner.
- Exit Criteria: the Gate table whose rows gate merge and release.

Header rows, placeholder rows and rows with too few cells are ignored.
Scenario IDs remain stable once written.

CLI:
    python3 lib/test_spec.py list specs/tests/<name>.md
    python3 lib/test_spec.py traceability specs/tests/<name>.md
    python3 lib/test_spec.py out-of-scope specs/tests/<name>.md
    python3 lib/test_spec.py mapping specs/tests/<name>.md
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
from collections.abc import Iterator
from pathlib import Path


SECTION_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TABLE_DIVIDER_RE = re.compile(r"^:?-{3,}:?$")
SCENARIO_ID_RE = re.compile(r"[A-Z][A-Z0-9_-]*-\d{2,}")
OUT_OF_SCOPE_ID_RE = re.compile(r"^([A-Z][A-Z0-9_]*-\d+)\b\s*(.*)$", re.DOTALL)
EMPTY_SELECTORS = {"", "-", "none", "n/a"}
# Exit Criteria gate table: the first column names the gate, and the status and
# evidence columns are found by these header names, in this order of preference.
GATE_NAME_HEADER = "gate"
GATE_STATUS_HEADERS = ("status", "required result", "required results", "result", "required outcome")
GATE_EVIDENCE_HEADERS = ("evidence", "enforcement", "enforced by", "evidence / enforcement")


def _clean_markdown(text: str) -> str:
    return COMMENT_RE.sub("", text)


def _section(text: str, title: str) -> str:
    """Body of the heading named `title`, up to the next heading of the same or
    a higher level. Sub-heading lines are dropped but their content is kept."""
    lines = _clean_markdown(text).splitlines()
    wanted = title.casefold()
    start = None
    level = None
    collected: list[str] = []

    for line in lines:
        match = SECTION_RE.match(line)
        if match:
            heading_level = len(match.group(1))
            heading = match.group(2).strip().casefold()
            if start is None and heading == wanted:
                start = True
                level = heading_level
                continue
            if start and heading_level <= int(level):
                break
        elif start:
            collected.append(line)
    return "\n".join(collected).strip()


def _split_row(line: str) -> list[str]:
    return [
        cell.replace(r"\|", "|").strip()
        for cell in re.split(r"(?<!\\)\|", line.strip("|"))
    ]


def _tables(section: str) -> list[list[list[str]]]:
    """The section's tables, each a list of rows, in document order.

    A table is a run of consecutive table lines; any other line closes it.
    Divider rows are dropped, so a table's first row is its header. Callers that
    only need the cells use _table_rows; callers that must tell one table from
    the next, such as the gate and catalog readers, use this."""
    tables: list[list[list[str]]] = []
    current: list[list[str]] | None = None
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            current = None
            continue
        cells = _split_row(stripped)
        if cells and all(TABLE_DIVIDER_RE.match(cell.replace(" ", "")) for cell in cells):
            continue
        if current is None:
            current = []
            tables.append(current)
        current.append(cells)
    return tables


def _table_rows(section: str) -> list[list[str]]:
    return [row for table in _tables(section) for row in table]


def _catalog_areas(test_spec: str) -> list[tuple[str, str]]:
    """Split the Scenario Catalog into (area, body) chunks by its sub-headings.
    Rows before the first sub-heading belong to the area named ""."""
    lines = _clean_markdown(test_spec).splitlines()
    level = None
    chunks: list[tuple[str, list[str]]] = []

    for line in lines:
        match = SECTION_RE.match(line)
        if match:
            heading_level = len(match.group(1))
            heading = match.group(2).strip()
            if level is None:
                if heading.casefold() == "scenario catalog":
                    level = heading_level
                    chunks.append(("", []))
                continue
            if heading_level <= level:
                break
            chunks.append((heading, []))
        elif level is not None:
            chunks[-1][1].append(line)
    return [(name, "\n".join(body)) for name, body in chunks]


def _is_scenario_row(row: list[str]) -> bool:
    """A catalog row parse_scenarios reads: four or more cells led by a PREFIX-NN
    identifier. coverage_gaps applies the same rule, so the two cannot disagree
    about which rows are scenarios."""
    return (
        len(row) >= 4
        and row[0].casefold() != "id"
        and SCENARIO_ID_RE.fullmatch(row[0].strip()) is not None
    )


def _scenario_prefix(scenario_id: str) -> str:
    return scenario_id.rsplit("-", 1)[0]


def parse_scenarios(test_spec: str) -> list[dict[str, str]]:
    scenarios = []
    for area, chunk in _catalog_areas(test_spec):
        for row in _table_rows(chunk):
            if not _is_scenario_row(row):
                continue
            scenario_id = row[0].strip()
            scenarios.append(
                {
                    "id": scenario_id,
                    "area": area,
                    "scenario": row[1],
                    "level": row[2],
                    "expected": row[3],
                }
            )
    return scenarios


def _trace_label(cell: str) -> str:
    """Short handle for a requirement row: the text before the first colon when
    it is compact ("TR4", "ST3", "Product risk, High"), else the first 60 chars."""
    head, separator, _ = cell.partition(":")
    head = head.strip()
    if separator and 0 < len(head) <= 40:
        return head
    return cell.strip()[:60]


def parse_traceability(test_spec: str) -> dict[str, list[str]]:
    """Map each scenario ID to the requirement labels that cite it, from the
    Acceptance Traceability section and its Additional Coverage table."""
    traces: dict[str, list[str]] = {}
    prefixes = {_scenario_prefix(s["id"]) for s in parse_scenarios(test_spec)}
    for row in _table_rows(_section(test_spec, "Acceptance Traceability")):
        if len(row) < 2:
            continue
        ids = scenario_references(row[1], prefixes or None)
        if not ids:
            continue
        label = _trace_label(row[0])
        for scenario_id in ids:
            labels = traces.setdefault(scenario_id, [])
            if label not in labels:
                labels.append(label)
    return traces


def scenario_references(text: str, prefixes: set[str] | None = None) -> list[str]:
    """Scenario IDs cited in a cell, in order, expanding PREFIX-NN to PREFIX-NN ranges.

    A traceability cell carries prose as well as IDs, and prose cites things
    that are not scenarios: an RFC, an open decision, an Out of Scope row.
    `prefixes` keeps only IDs whose prefix the Scenario Catalog actually uses,
    so "None. GAP-01: no reorder operation. See OOS-10" cites no scenario, while
    a typo such as AC-99 stays a reference and is still reported as missing.
    Pass None, or nothing, to accept every PREFIX-NN token.
    """
    ids = SCENARIO_ID_RE.findall(text)
    for match in re.finditer(r"([A-Z][A-Z0-9_-]*-)(\d{2,})\s+(?:to|through)\s+\1(\d{2,})", text):
        prefix, start, end = match.groups()
        if 0 <= int(end) - int(start) <= 1000:
            ids.extend(f"{prefix}{n:0{len(start)}d}" for n in range(int(start), int(end) + 1))
    ordered = list(dict.fromkeys(ids))
    if not prefixes:
        return ordered
    return [scenario_id for scenario_id in ordered if _scenario_prefix(scenario_id) in prefixes]


def _scenario_tables(test_spec: str) -> list[list[list[str]]]:
    """Catalog tables that hold scenario rows: the ones headed by an ID column,
    and any table already contributing a scenario to parse_scenarios. A notes,
    fixture or open-decision table in the same section holds no scenario row, so
    its rows are not malformed ones."""
    tables = []
    for _, chunk in _catalog_areas(test_spec):
        for table in _tables(chunk):
            header = table[0] if table else []
            if (header and header[0].casefold() == "id") or any(_is_scenario_row(row) for row in table):
                tables.append(table)
    return tables


def coverage_gaps(test_spec: str) -> list[str]:
    """Preserve explicitly missing coverage rather than dropping its source row."""
    scenarios = parse_scenarios(test_spec)
    known = {s["id"] for s in scenarios}
    prefixes = {_scenario_prefix(scenario_id) for scenario_id in known}
    gaps = []
    if not known:
        gaps.append("The Scenario Catalog is missing or empty")
    for table in _scenario_tables(test_spec):
        for row in table:
            if not row or not row[0] or row[0].casefold() == "id" or "{" in row[0]:
                continue
            if not _is_scenario_row(row) or not all(row[:4]):
                gaps.append(f"Malformed scenario row: {row[0]}")
    for row in _table_rows(_section(test_spec, "Acceptance Traceability")):
        if not row or not row[0] or row[0].lower() in ("rfc acceptance criterion", "source requirement / risk"):
            continue
        ids = scenario_references(row[1], prefixes or None) if len(row) > 1 else []
        missing = set(ids) - known
        if not ids:
            gaps.append(f"No scenario covers requirement: {row[0]}")
        elif missing:
            gaps.append(f"{row[0]} references missing scenarios: {', '.join(sorted(missing))}")
        elif re.search(r"\b(blocked|unverified|unresolved|partial|GAP-\d+)\b", " ".join(row[1:]), re.I):
            gaps.append(f"Coverage remains unresolved: {' | '.join(row)}")
    return gaps


def _header_name(cell: str) -> str:
    """A header cell reduced to its name: casing, emphasis, backticks and
    repeated spaces do not change which column it is."""
    return re.sub(r"\s+", " ", cell.replace("*", "").replace("`", "").strip()).casefold()


def _gate_columns(row: list[str]) -> dict[str, int] | None:
    """The gate, status and evidence column indexes of a gate-table header row,
    or None when the row does not head a gate table."""
    names = [_header_name(cell) for cell in row]
    if len(names) < 3 or names[0] != GATE_NAME_HEADER:
        return None
    columns = {"gate": 0}
    for key, synonyms in (("status", GATE_STATUS_HEADERS), ("evidence", GATE_EVIDENCE_HEADERS)):
        index = next((names.index(name, 1) for name in synonyms if name in names[1:]), None)
        if index is None:
            return None
        columns[key] = index
    return columns


def parse_evaluation_gates(test_spec: str) -> list[dict[str, str]]:
    """Rows of the Exit Criteria gate table, the spec's explicit acceptance gates.

    A gate table is recognised by its header row:

    - the first column is headed `Gate` and names the gate;
    - one later column is headed `Status`, `Required result`, `Required
      results`, `Result`, or `Required outcome`, and supplies the status;
    - one later column is headed `Evidence`, `Enforcement`, `Enforced by`, or
      `Evidence / enforcement`, and supplies the evidence.

    Column order after the first is free, further columns are ignored, and
    casing, bold markers and backticks in a header do not matter. Nothing else
    is treated as a gate table, so an ordinary table elsewhere in the spec is
    never read as acceptance gates.

    Every table under Exit Criteria must be a gate table; one that is not raises
    a ValueError naming its header. Returning no gates would read downstream as
    a feature with nothing standing between it and acceptance, so an
    unrecognised header is an error rather than silence. An Exit Criteria
    section written as prose, with no table at all, declares no machine-read
    gate and leaves those conditions to human review.

    Gate prose elsewhere in the spec is descriptive; it is never converted to a
    pass.
    """
    gates: list[dict[str, str]] = []
    unreadable: list[list[str]] = []
    for table in _tables(_section(test_spec, "Exit Criteria")):
        if not table:
            continue
        columns = _gate_columns(table[0])
        if columns is None:
            unreadable.append(table[0])
            continue
        for row in table[1:]:
            if not row or not row[0]:
                continue
            if len(row) <= max(columns.values()):
                raise ValueError("Incomplete Exit Criteria gate row: " + " | ".join(row))
            gates.append({key: row[index] for key, index in columns.items()})
    if unreadable:
        raise ValueError(
            "Unreadable table under Exit Criteria: "
            + "; ".join("| " + " | ".join(header) + " |" for header in unreadable)
            + ". A gate table is headed by a Gate column, a status column "
            + "(" + ", ".join(GATE_STATUS_HEADERS) + ") and an evidence column "
            + "(" + ", ".join(GATE_EVIDENCE_HEADERS) + "). Rename the columns, or "
            "move a table that is not a gate table to another section."
        )
    return gates


def manual_scenarios(test_spec: str) -> set[str]:
    manual = set()
    for row in _table_rows(_section(test_spec, "Scenario Classification")):
        if len(row) >= 4 and row[3].lower().startswith("manual"):
            manual.add(row[0])
    return manual


def parse_out_of_scope(test_spec: str) -> list[dict[str, str]]:
    """Rows of the Out of Scope table: what is deliberately not examined, whether
    it is deferred or not applicable, why, and who owns the decision."""
    rows: list[dict[str, str]] = []
    for row in _table_rows(_section(test_spec, "Out of Scope")):
        if len(row) < 2:
            continue
        first = row[0].strip()
        if not first or first.casefold().startswith("excluded"):
            continue
        match = OUT_OF_SCOPE_ID_RE.match(first)
        oos_id, excluded = (match.group(1), match.group(2).strip()) if match else ("", first)
        rows.append(
            {
                "id": oos_id,
                "excluded": excluded,
                "disposition": row[1].strip(),
                "reason": row[2].strip() if len(row) > 2 else "",
                "owner": row[3].strip() if len(row) > 3 else "",
            }
        )
    return rows


def _mapping_columns(row: list[str]) -> dict[str, int | None] | None:
    """Column indexes of the Execution and Evidence header row, or None when the
    row does not head that table. A header cell containing "scenario" and one
    containing "selector" are required; "command", "depend" and a task column
    are optional."""
    lowered = [cell.casefold() for cell in row]
    if not (any("scenario" in c for c in lowered) and any("selector" in c for c in lowered)):
        return None
    return {
        "scenario": next(i for i, c in enumerate(lowered) if "scenario" in c),
        "selector": next(i for i, c in enumerate(lowered) if "selector" in c),
        "command": next((i for i, c in enumerate(lowered) if "command" in c), None),
        "depends": next((i for i, c in enumerate(lowered) if "depend" in c), None),
        "task": next((i for i, c in enumerate(lowered) if c in ("task", "task id")), None),
    }


def _mapping_selectors(cell: str) -> list[str]:
    """The selectors one Selector cell maps. Backticks delimit complete
    selectors, including parameter IDs with spaces and commas; unquoted
    selectors remain whitespace-separated. An empty cell or an EMPTY_SELECTORS
    sentinel maps nothing."""
    cell = cell.strip()
    if cell.count("`") % 2:
        raise ValueError("Unclosed backticks in mapping selector")
    cell = re.sub(r"`([^`]+)`", lambda match: shlex.quote(match[1]), cell)
    return [token for token in shlex.split(cell) if token.casefold() not in EMPTY_SELECTORS]


def _mapping_rows(test_spec: str) -> Iterator[tuple[str, list[str], list[str], dict[str, int | None]]]:
    """Yield (scenario_id, selectors, row, columns) for each Execution and
    Evidence row whose Scenario cell holds a scenario ID. Both readers of that
    table use this, so what executes and what is silent cannot drift apart.

    Every table in the section carries its own header, the way the gate reader
    treats Exit Criteria and the catalog reader treats its sub-headings. Reading
    the section as one flat row list and keeping the first header made a second
    table's rows read through the first table's column order, pairing scenarios
    with another column's text. An unreadable header raises rather than dropping
    the table: its scenarios would then look unmapped rather than silent, and an
    unmapped scenario still takes its outcome from the task's own test batch.
    """
    tables: list[tuple[dict[str, int | None], list[list[str]]]] = []
    unreadable: list[list[str]] = []
    for table in _tables(_section(test_spec, "Execution and Evidence")):
        if not table:
            continue
        columns = _mapping_columns(table[0])
        if columns is None:
            unreadable.append(table[0])
        else:
            tables.append((columns, table[1:]))
    if unreadable:
        raise ValueError(
            "Unreadable table under Execution and Evidence: "
            + "; ".join("| " + " | ".join(header) + " |" for header in unreadable)
            + ". A mapping table is headed by a Scenario column and a Selector "
            "column. Rename the columns, or move a table that is not a mapping "
            "table to another section."
        )

    for columns, rows in tables:
        for row in rows:
            if len(row) <= max(columns["selector"], columns["scenario"]):
                continue
            scenario_id = row[columns["scenario"]].strip().strip("`")
            if not SCENARIO_ID_RE.fullmatch(scenario_id):
                continue
            yield scenario_id, _mapping_selectors(row[columns["selector"]]), row, columns


def parse_execution_mapping(test_spec: str) -> list[dict[str, object]]:
    """Scenario ID to selector entries from the Execution and Evidence table.

    The header row names the columns: one cell containing "scenario", one
    containing "selector", optionally one containing "command" and one
    containing "depend". Several selectors in one cell are separated by
    spaces. Backticks or shell quotes preserve a selector containing spaces.
    A row whose Selector cell is empty maps nothing, reported as silence; read
    those rows with silent_scenarios. One entry is produced per selector, in the
    shape speed eval's runner consumes.
    """
    cases: list[dict[str, object]] = []
    for scenario_id, selectors, row, columns in _mapping_rows(test_spec):
        command = ""
        if columns["command"] is not None and len(row) > columns["command"]:
            command = row[columns["command"]].strip().strip("`")
        depends: list[str] = []
        if columns["depends"] is not None and len(row) > columns["depends"]:
            depends = SCENARIO_ID_RE.findall(row[columns["depends"]])
        for selector in selectors:
            cases.append(
                {
                    "scenario_id": scenario_id,
                    "selector": selector,
                    "command": command,
                    "depends_on_scenarios": depends,
                    **({"task_id": row[columns["task"]].strip()} if columns["task"] is not None
                       and len(row) > columns["task"] and row[columns["task"]].strip() else {}),
                }
            )
    return cases


def silent_scenarios(test_spec: str) -> set[str]:
    """Scenario IDs listed in Execution and Evidence that map no selector.

    Declared silence differs from absence: the row exists, and its Selector cell
    is empty or holds one of the EMPTY_SELECTORS sentinels ("-", "none", "n/a").
    parse_execution_mapping drops such a row, which leaves nothing downstream to
    distinguish the two, so a task batch could report the scenario as a pass.
    A scenario with several rows is silent only when no row supplies a selector.
    A spec with no mapping table yields an empty set.
    """
    mapped: set[str] = set()
    silent: set[str] = set()
    for scenario_id, selectors, _row, _columns in _mapping_rows(test_spec):
        (mapped if selectors else silent).add(scenario_id)
    return silent - mapped


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a test spec's machine-read sections.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("list", "print the Scenario Catalog as JSON"),
        ("traceability", "print scenario ID to requirement labels as JSON"),
        ("out-of-scope", "print the Out of Scope rows as JSON"),
        ("mapping", "print the Execution and Evidence mapping as a test-plan JSON"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("test_spec")
    args = parser.parse_args()

    text = Path(args.test_spec).read_text(encoding="utf-8")
    if args.command == "traceability":
        result: object = parse_traceability(text)
    elif args.command == "out-of-scope":
        result = parse_out_of_scope(text)
    elif args.command == "mapping":
        result = {"test_spec": args.test_spec, "test_cases": parse_execution_mapping(text)}
    else:
        result = parse_scenarios(text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
