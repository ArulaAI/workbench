#!/usr/bin/env python3
"""workbench-hello: the one canonical greeting implementation.

Both the `workbench hello` CLI adapter and the projected agent skill execute
this exact file. It has no domain logic, no external access, and writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sys

SKILL = "workbench-hello"


def build_result(name, catalog_version, surface):
    name = (name or "").strip() or "World"
    return {
        "skill": SKILL,
        "message": f"Hello, {name}! Workbench skills are available.",
        "catalog_version": catalog_version,
        "surface": surface,
    }


def format_text(result):
    return "\n".join(f"{k}: {v}" for k, v in result.items())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    p = argparse.ArgumentParser(prog="workbench-hello")
    p.add_argument("name", nargs="?", default="World")
    p.add_argument("--catalog-version", default="dev")
    p.add_argument("--surface", default="unknown")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    result = build_result(args.name, args.catalog_version, args.surface)
    print(json.dumps(result, indent=2) if args.json else format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
