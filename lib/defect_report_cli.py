"""Shell-compatible adapter around the shared defect report model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib.defect_reports import intake_readiness, parse_report, validate_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    parse = sub.add_parser("parse")
    parse.add_argument("path")
    parse.add_argument("--json", action="store_true")
    validate = sub.add_parser("validate")
    validate.add_argument("path")
    validate.add_argument("--strict", action="store_true")
    related = sub.add_parser("related-specs")
    related.add_argument("path")
    related.add_argument("project_root")
    ready = sub.add_parser("readiness")
    ready.add_argument("project_root")
    ready.add_argument("defects_dir")
    ready.add_argument("slug")
    ready.add_argument("spec_path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in {"parse", "validate", "related-specs"}:
        path = Path(args.path)
        if not path.is_file():
            print(f"Defect spec not found: {path}", file=sys.stderr)
            return 1
        try:
            report = parse_report(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            print(f"Could not read defect report: {exc}", file=sys.stderr)
            return 1
    if args.command == "parse":
        errors = validate_report(report)
        if errors:
            for error in errors:
                print(f"{error['field']}: {error['message']}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            print(f"severity={report['severity'] or ''}")
            print(f"related_feature={(report['related_features'] or [''])[0]}")
            print(f"observed_behavior={report['observed']}")
            print(f"expected_behavior={report['expected']}")
            print(f"reproduction_steps={report['reproduction']}")
        return 0
    if args.command == "validate":
        errors = validate_report(report, strict=args.strict)
        for error in errors:
            print(f"{error['field']}: {error['message']}", file=sys.stderr)
        return int(bool(errors))
    if args.command == "related-specs":
        root = Path(args.project_root)
        for feature in report["related_features"]:
            for kind in ("product", "tech"):
                candidate = root / "specs" / kind / f"{feature}.md"
                if candidate.is_file():
                    print(candidate)
        return 0

    root = Path(args.project_root).resolve()
    defects_dir = Path(args.defects_dir).resolve()
    state_path = defects_dir / args.slug / "state.json"
    try:
        state_path.resolve().relative_to(defects_dir)
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Defect state is unreadable: {exc}", file=sys.stderr)
        return 1
    ready, warnings = intake_readiness(defects_dir, args.slug, state)
    if not ready:
        print("; ".join(warnings), file=sys.stderr)
        return 1
    intake = state.get("intake")
    if isinstance(intake, dict):
        source = Path(str(state.get("source_spec") or ""))
        expected = Path(args.spec_path)
        if not source.is_absolute():
            source = root / source
        if not expected.is_absolute():
            expected = root / expected
        try:
            if source.resolve() != expected.resolve():
                print("Defect source_spec does not match the supplied report", file=sys.stderr)
                return 1
        except OSError as exc:
            print(f"Defect source path is invalid: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
