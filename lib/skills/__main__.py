"""CLI entry: ``python -m skills sync|status``.

Exit codes:
  sync   -> 0 converged / 2 conflicts remain / 3 error
  status -> 0 all current / 1 drift or conflict present / 3 error
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path

from skills import CURRENT, CONFLICTED, UNSUPPORTED
from skills.sync import sync, status


def _load_hello_helper(skills_dir):
    """Import the ONE canonical helper so the CLI reuses it (no duplicate logic)."""
    helper = Path(skills_dir) / "workbench-hello" / "scripts" / "hello.py"
    if not helper.exists():
        raise FileNotFoundError(f"canonical helper missing: {helper}")
    spec = importlib.util.spec_from_file_location("workbench_hello_helper", helper)
    mod = importlib.util.module_from_spec(spec)
    # Do not write __pycache__ into the canonical package; a stray .pyc would
    # otherwise be swept into the next projection.
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skills")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("sync", "status"):
        sp = sub.add_parser(name)
        sp.add_argument("--project-root", required=True)
        sp.add_argument("--skills-dir", required=True)
        sp.add_argument("--catalog-version", default="dev")
        sp.add_argument("--surface", default=None)
        sp.add_argument("--json", action="store_true")
        if name == "sync":
            sp.add_argument("--force", action="store_true")

    hp = sub.add_parser("hello")
    hp.add_argument("name", nargs="?", default="World")
    hp.add_argument("--skills-dir", required=True)
    hp.add_argument("--catalog-version", default="dev")
    hp.add_argument("--surface", default="workbench-cli")
    hp.add_argument("--json", action="store_true")
    return parser


def _print_table(catalog_version, rows) -> None:
    print(f"catalog {catalog_version} · {len(rows)} row(s)")
    for r in rows:
        line = f"  {r.surface:<12} {r.skill:<20} {r.state}"
        if r.action:
            line += f"  ({r.action})"
        print(line)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _build_parser().parse_args(argv)

    if args.cmd == "hello":
        try:
            helper = _load_hello_helper(args.skills_dir)
            result = helper.build_result(args.name, args.catalog_version, args.surface)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
        print(json.dumps(result, indent=2) if args.json else helper.format_text(result))
        return 0

    try:
        if args.cmd == "sync":
            rows = sync(
                args.project_root,
                args.skills_dir,
                args.catalog_version,
                force=args.force,
                only_surface=args.surface,
            )
        else:
            rows = status(
                args.project_root,
                args.skills_dir,
                args.catalog_version,
                only_surface=args.surface,
            )
    except Exception as exc:  # config / catalog error
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
    else:
        _print_table(args.catalog_version, rows)

    if args.cmd == "sync":
        return 2 if any(r.state == CONFLICTED for r in rows) else 0
    return 0 if all(r.state in (CURRENT, UNSUPPORTED) for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
