"""Read-only command-line adapter for feature findings and defect reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dashboard.backend.paths import get_paths
from lib.defect_findings import FindingError, read_findings
from lib.defect_reports import (
    build_report_view,
    discover_defects,
    discover_feature_names,
    export_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="speed define")
    parser.add_argument("--project-root", default=".", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="subject", required=True)

    feature = subparsers.add_parser("feature", help="Show a feature findings inbox")
    feature.add_argument("name")
    feature.add_argument("--json", action="store_true")
    feature.add_argument("--no-open", action="store_true")

    defects = subparsers.add_parser("defects", help="Show the defect portfolio")
    defects.add_argument("--feature", action="append", default=[])
    defects.add_argument("--severity", action="append", default=[])
    defects.add_argument("--status", action="append", default=[])
    defects.add_argument("--source", action="append", default=[])
    defects.add_argument("--lifecycle", action="append", default=[])
    defects.add_argument("--search", default="")
    defects.add_argument("--format", choices=("terminal", "json", "markdown"), default="terminal")
    defects.add_argument("--json", action="store_true")
    defects.add_argument("--no-open", action="store_true")
    return parser


def _feature_text(view: dict[str, Any]) -> str:
    unresolved = [item for item in view["findings"] if item["resolution"] == "unresolved"]
    lines = [
        f"Feature findings: {view['feature']}",
        f"{len(unresolved)} unresolved / {len(view['findings'])} total",
    ]
    for finding in view["findings"]:
        sources = ", ".join(sorted({item["producer"] for item in finding["evidence"]}))
        task_ids = sorted({str(item["task_id"]) for item in finding["evidence"] if item.get("task_id")})
        task = f" task {','.join(task_ids)}" if task_ids else ""
        stale = " [stale]" if finding["stale"] else ""
        lines.append(f"- {finding['title']} — {finding['resolution']}{stale} ({sources}{task})")
    for warning in view.get("warnings") or []:
        lines.append(f"Warning: {warning}")
    lines.append(f"Dashboard: /define/{view['feature']}/findings")
    return "\n".join(lines)


def _report_text(view: dict[str, Any]) -> str:
    totals = view["totals"]
    lines = [
        "Defect report",
        f"{totals['total']} total / {totals['active']} active / {totals['closed']} closed / {totals['p0_p1']} P0-P1",
    ]
    for row in view["rows"]:
        features = ", ".join(row["related_features"]) or "Unassigned"
        warning = " [repair required]" if not row["filed"] else ""
        lines.append(f"- {row['severity']} {row['status']}: {row['title']} ({features}){warning}")
        if row.get("canonical_path"):
            lines.append(f"  {row['canonical_path']}")
    for warning in view["warnings"]:
        lines.append(f"Warning: {warning}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.project_root).resolve()
    paths = get_paths(root)
    try:
        if args.subject == "feature":
            known = discover_feature_names(root, paths.features_dir)
            if args.name not in known:
                raise FindingError("NOT_FOUND", f"Unknown feature: {args.name}", "featureName")
            view = read_findings(paths, args.name)
            print(json.dumps(view, indent=2, sort_keys=True) if args.json else _feature_text(view))
            return 0

        filters = {
            "features": args.feature, "severity": args.severity,
            "status": args.status, "source": args.source,
            "lifecycle": args.lifecycle, "search": args.search,
        }
        rows = discover_defects(root, paths.defects_dir)
        view = build_report_view(rows, filters)
        output_format = "json" if args.json else args.format
        if output_format in {"json", "markdown"}:
            sys.stdout.write(export_report(view, output_format))
        else:
            print(_report_text(view))
        return 0
    except FindingError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
