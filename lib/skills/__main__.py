"""CLI entry: ``python -m skills sync|status|doctor|harnesses``.

Private plumbing. ``workbench skills`` is the only supported entrance for a
user; this module's ``--project-root``, ``--skills-dir`` and
``--catalog-version`` arguments are internal context that the wrapper resolves
and passes in, which is why they are required here and have no defaults. The
``harnesses`` subcommand exists so the Bash commands can query the one canonical
harness registry instead of restating it.

Exit codes:
  sync   -> 0 converged / 2 conflicts remain / 3 error
  status -> 0 all current / 1 drift or conflict present / 3 error
  doctor -> 0 no issues / 1 issues found / 3 error

Usage and configuration errors are errors: they exit 3, never 1 or 2. argparse
would spend its own 2 on a malformed command line, which `sync` has already
promised means "conflicts remain", so a parser failure is remapped here.
Set WORKBENCH_DEBUG=1 to get the traceback behind an error message.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from dataclasses import asdict

from skills.doctor import NOTE, diagnose
from skills.inspect import inspect
from skills.models import HARNESS_IDS, SkillState
from skills.sync import sync

ERROR = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skills")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("sync", "status", "doctor"):
        sp = sub.add_parser(name)
        sp.add_argument("--project-root", required=True)
        sp.add_argument("--skills-dir", required=True)
        sp.add_argument("--catalog-version", default="dev")
        sp.add_argument("--harness", default=None)
        sp.add_argument("--json", action="store_true")
        if name == "sync":
            sp.add_argument("--force", action="store_true")
    # No project context: this only reports what Workbench supports.
    listing = sub.add_parser("harnesses")
    listing.add_argument("--json", action="store_true")
    return parser


def _status_rows(inspection) -> list:
    return [
        {"harness": item.harness, "skill": item.skill, "state": item.state}
        for item in inspection.skills
    ]


def _print_status(catalog_version, rows) -> None:
    print(f"catalog {catalog_version} · {len(rows)} row(s)")
    for row in rows:
        print(f"  {row['harness']:<10} {row['skill']:<20} {row['state']}")


def _print_sync(catalog_version, outcomes) -> None:
    print(f"catalog {catalog_version} · {len(outcomes)} row(s)")
    for row in outcomes:
        line = f"  {row.harness:<10} {row.skill:<20} {row.final_state}"
        if row.action:
            line += f"  ({row.action} from {row.previous_state})"
        print(line)


def _actionable(diagnostics):
    """Diagnostics a user can repair here and now.

    A missing harness is advice, not drift: `status` already exits 0 on it, and
    `workbench init` sends users to `doctor` for exactly that advice.
    """
    return [item for item in diagnostics if item.severity != NOTE]


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
        head = f"  {item['harness']} / {item['skill']} [{item['state']}]"
        print(f"{head} {item['severity']}: {item['code']}")
        if item["path"]:
            print(f"    path: {item['path']}")
        if item["expected"] or item["actual"]:
            print(f"    expected: {item['expected'] or '-'}")
            print(f"    actual:   {item['actual'] or '-'}")
        print(f"    message: {item['message']}")
        repair = item["repair_command"]
        suffix = "  (destructive)" if item["destructive"] else ""
        print(f"    repair: `{repair}`{suffix}")


def _parse(argv):
    """Parse argv, translating argparse's own exit statuses into ours.

    Returns the namespace, or an int for a caller that should stop now: 0 when
    argparse already answered (`--help`), ERROR for a bad command line.
    """
    try:
        return _build_parser().parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code in (None, 0) else ERROR


def _report_error(exc, *, as_json) -> int:
    """One failure, reported once per requested format, with a way to get more.

    The stderr line is what `speed init` shows a human and what a shell caller
    reads. The stdout object is what `--json` consumers parse; they get invalid
    JSON, or nothing at all, if the only report is prose on stderr.
    """
    if os.environ.get("WORKBENCH_DEBUG"):
        traceback.print_exc(file=sys.stderr)
    kind = type(exc).__name__
    print(f"error: {kind}: {exc}", file=sys.stderr)
    if as_json:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": {"type": kind, "message": str(exc)},
                },
                indent=2,
            )
        )
    return ERROR


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parse(argv)
    if isinstance(args, int):
        return args

    if args.cmd == "harnesses":
        if args.json:
            print(json.dumps(list(HARNESS_IDS)))
        else:
            print("\n".join(HARNESS_IDS))
        return 0

    try:
        if args.cmd == "sync":
            outcomes = sync(
                args.project_root,
                args.skills_dir,
                args.catalog_version,
                force=args.force,
                only_harness=args.harness,
            )
        else:
            inspection = inspect(
                args.project_root,
                args.skills_dir,
                args.catalog_version,
                only_harness=args.harness,
            )
    except Exception as exc:  # config / catalog / manifest error
        return _report_error(exc, as_json=args.json)

    if args.cmd == "sync":
        if args.json:
            print(json.dumps([asdict(item) for item in outcomes], indent=2))
        else:
            _print_sync(args.catalog_version, outcomes)
        return 2 if any(
            item.final_state is SkillState.CONFLICTED for item in outcomes
        ) else 0

    if args.cmd == "doctor":
        diagnostics = diagnose(inspection)
        result = _doctor_result(args.catalog_version, diagnostics)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            _print_doctor(result)
        return 1 if _actionable(diagnostics) else 0

    rows = _status_rows(inspection)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print_status(args.catalog_version, rows)
    return 0 if all(
        row["state"] in (SkillState.CURRENT, SkillState.UNSUPPORTED) for row in rows
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
