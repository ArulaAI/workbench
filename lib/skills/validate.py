"""Canonical package contract validation.

Run at catalog-build time and defensively at load time. Every rule maps to a
fixture in tests/skills/test_validate.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from skills.catalog import SkillPackage

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass
class Violation:
    package: str
    path: str  # None allowed
    reason: str


def validate_package(pkg: SkillPackage) -> list:
    out: list = []
    if "SKILL.md" not in pkg.files:
        out.append(Violation(pkg.name, "SKILL.md", "missing SKILL.md"))
    if not _NAME_RE.match(pkg.name or ""):
        out.append(Violation(pkg.name, None, f"invalid skill name '{pkg.name}'"))
    declared = pkg.meta.get("name", "")
    if declared != pkg.name:
        out.append(
            Violation(
                pkg.name,
                "SKILL.md",
                f"front-matter name '{declared}' != directory '{pkg.name}'",
            )
        )
    if not pkg.meta.get("description", "").strip():
        out.append(Violation(pkg.name, "SKILL.md", "empty or missing description"))
    for rel in pkg.files:
        if rel.startswith("/") or ".." in rel.split("/"):
            out.append(Violation(pkg.name, rel, "unsafe path escapes package"))
    root = pkg.root.resolve()
    if pkg.root.is_dir():
        for path in pkg.root.rglob("*"):
            if not path.is_symlink():
                continue
            try:
                path.resolve().relative_to(root)
            except (OSError, ValueError):
                out.append(
                    Violation(
                        pkg.name,
                        path.relative_to(pkg.root).as_posix(),
                        "symlink escapes package",
                    )
                )
    return out


def validate_catalog(pkgs: list) -> list:
    out: list = []
    seen: dict = {}
    for pkg in pkgs:
        out.extend(validate_package(pkg))
        seen[pkg.name] = seen.get(pkg.name, 0) + 1
    for name, count in seen.items():
        if count > 1:
            out.append(Violation(name, None, f"duplicate skill name '{name}'"))
    return out
