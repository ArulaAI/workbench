"""Read-only terminal rendering of completed evaluation reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import textwrap


def _text(value: object) -> str:
    # Repository-controlled test names must not inject terminal control codes.
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "?", str(value or "")).expandtabs(4)


def _grid(rows: list[tuple[str, str, str]], columns: int) -> list[str]:
    total = max(72, min(columns, 180))
    first = min(18, max(11, max(len(row[0]) for row in rows)))
    remaining = total - 10 - first
    widths = (first, remaining * 45 // 100, remaining - remaining * 45 // 100)
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    lines = [border]
    for row in rows:
        wrapped = []
        for value, width in zip(row, widths):
            wrapped.append([line for paragraph in _text(value).split("\n")
                            for line in (textwrap.wrap(paragraph, width, break_on_hyphens=False) or [""])])
        for index in range(max(map(len, wrapped))):
            lines.append("| " + " | ".join(
                (part[index] if index < len(part) else "").ljust(width)
                for part, width in zip(wrapped, widths)) + " |")
        lines.append(border)
    return lines


def scenario_table(report: dict, *, columns: int = 120, evidence_root: Path | None = None) -> str:
    """Render only scenario rows; criterion rows are not extra test runs."""
    scenarios = [r for r in report.get("results", []) if r.get("kind") == "scenario"]
    if not scenarios:
        return "No scenario results in this evaluation."
    rows = [("Scenario ID", "Test file / case / result", "Expected behavior / execution evidence")]
    logs: list[str] = []
    for result in scenarios:
        tests = ["Scenario: " + str(result["status"]).upper()]
        evidence = []
        for execution in result.get("executions", []):
            selector = execution.get("selector") or ""
            name = execution.get("test_name")
            records = execution.get("tests") or []
            if name:
                # Some runner reports also list unrelated deselected tests.
                records = [test for test in records if test.get("name", test.get("id")) == name]
            file = selector.split("::", 1)[0]
            if file:
                tests.append("File: " + file)
            for test in records:
                identity = test.get("name") or test.get("id") or name or selector
                tests.append("Test: " + identity)
                tests.append("Result: " + str(test.get("status", "unverifiable")).upper())
            if not records:
                if name or selector:
                    tests.append("Mapped: " + (name or selector))
                tests.append("No individual test result: " + str(execution.get("status", "unverifiable")).upper())
            detail = str(execution.get("evidence") or "No runner evidence recorded")
            if execution.get("artifact_dir"):
                path = str(Path(execution["artifact_dir"]) / "output.log")
                detail = detail.replace(f" (log: {path})", "")
                if path not in logs:
                    logs.append(path)
                detail += f" [log {logs.index(path) + 1}]"
            evidence.append(detail)
        if len(tests) == 1:
            tests.append("No individual test evidence")
        if not evidence:
            evidence.append(result.get("evidence") or "No execution evidence recorded")
        rows.append((result["id"], "\n".join(tests),
                     "Expected: " + (result.get("expected") or "Not specified")
                     + "\n\nEvidence: " + "\n".join(dict.fromkeys(evidence))))
    lines = ["", "Scenario results", "", *_grid(rows, columns),
             "PASS means the mapped test assertions passed. Expected behavior is from the test spec.",
             "Whether those assertions correctly implement the spec still requires review."]
    reused = sum(r.get("kind") == "criterion" and str(r.get("evidence", "")).startswith(
        "Reused declared criterion scenarios:") for r in report.get("results", []))
    if reused:
        lines.append(f"{reused} task criteria reuse scenario evidence; they are not additional test executions.")
    if logs:
        lines.extend(["", "Execution logs" + (f" (relative to {evidence_root})" if evidence_root else "") + ":"])
        for index, path in enumerate(logs, 1):
            display = path
            if evidence_root:
                try:
                    display = str(Path(path).relative_to(evidence_root))
                except ValueError:
                    pass
            lines.append(f"  [{index}] {_text(display)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    print(scenario_table(report, columns=shutil.get_terminal_size(fallback=(120, 24)).columns,
                         evidence_root=args.evidence_root))


if __name__ == "__main__":
    main()
