"""CLI entry: ``python -m skills sync|status|doctor``.

Exit codes:
  sync   -> 0 converged / 2 conflicts remain / 3 error
  status -> 0 all current / 1 drift or conflict present / 3 error
  doctor -> 0 no issues / 1 issues found / 3 error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from skills import CURRENT, CONFLICTED, UNSUPPORTED
from skills.doctor import diagnose
from skills.sync import sync, status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skills")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("sync", "status", "doctor"):
        sp = sub.add_parser(name)
        sp.add_argument("--project-root", required=True)
        sp.add_argument("--skills-dir", required=True)
        sp.add_argument("--catalog-version", default="dev")
        sp.add_argument("--surface", default=None)
        sp.add_argument("--json", action="store_true")
        if name == "sync":
            sp.add_argument("--force", action="store_true")

    return parser


def _print_table(catalog_version, rows) -> None:
    print(f"catalog {catalog_version} · {len(rows)} row(s)")
    for r in rows:
        line = f"  {r.surface:<12} {r.skill:<20} {r.state}"
        if r.action:
            line += f"  ({r.action})"
        print(line)


def _actionable(diagnostics):
    """Diagnostics a user can repair here and now.

    A missing harness is advice, not drift: `status` already exits 0 on it, and
    `workbench init` sends users to `doctor` for exactly that advice.
    """
    return [item for item in diagnostics if item.state != UNSUPPORTED]


def _doctor_status(diagnostics) -> str:
    if not diagnostics:
        return "healthy"
    return "issues" if _actionable(diagnostics) else "unsupported"


def _doctor_result(catalog_version, diagnostics):
    return {
        "status": _doctor_status(diagnostics),
        "catalog_version": catalog_version,
        "diagnostics": [asdict(item) for item in diagnostics],
    }


def _print_doctor(result) -> None:
    diagnostics = result["diagnostics"]
    noun = "note" if result["status"] == "unsupported" else "issue"
    print(f"skills doctor: {result['status']} · {len(diagnostics)} {noun}(s)")
    if not diagnostics:
        print("All imported Workbench skills are current and ready to use.")
        return
    for item in diagnostics:
        print(f"  {item['surface']} / {item['skill']} [{item['state']}]")
        print(f"    diagnosis: {item['diagnosis']}")
        print(f"    repair: {item['repair']}")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _build_parser().parse_args(argv)

    try:
        if args.cmd == "sync":
            rows = sync(
                args.project_root,
                args.skills_dir,
                args.catalog_version,
                force=args.force,
                only_surface=args.surface,
            )
        elif args.cmd == "status":
            rows = status(
                args.project_root,
                args.skills_dir,
                args.catalog_version,
                only_surface=args.surface,
            )
        else:
            diagnostics = diagnose(
                args.project_root,
                args.skills_dir,
                args.catalog_version,
                only_surface=args.surface,
            )
    except Exception as exc:  # config / catalog error
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.cmd == "doctor":
        result = _doctor_result(args.catalog_version, diagnostics)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            _print_doctor(result)
        return 1 if _actionable(diagnostics) else 0

    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
    else:
        _print_table(args.catalog_version, rows)

    if args.cmd == "sync":
        return 2 if any(r.state == CONFLICTED for r in rows) else 0
    return 0 if all(r.state in (CURRENT, UNSUPPORTED) for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
