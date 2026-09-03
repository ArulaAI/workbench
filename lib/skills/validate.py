"""Canonical package contract validation.

Run at catalog load time. Nothing in this release invokes it as a separate
catalog-build step; it is written to be reusable by one when that exists. Every
rule maps to a fixture in tests/skills/test_validate.py.

This module depends only on ``models``, never on the loader, so validation of
a package built in memory needs no filesystem at all.

Two of the rules are enforced twice on purpose. The loader refuses symlinks and
records an unreadable SKILL.md while it walks the package, because catching
those later would mean reading a linked file first; repeating them here keeps
the contract stated in one place and testable against a package built in memory.
Duplicates are collapsed before the list is returned.
"""
from __future__ import annotations

from dataclasses import dataclass

from skills import is_valid_skill_name
from skills.models import NO_SYMLINKS, SkillPackage
from skills.frontmatter import MANAGED_PREFIX


# Stable identifiers for each rule. Callers and tests match on these rather
# than on `reason`, whose wording is free to improve.
MISSING_SKILL_MD = "missing_skill_md"
UNREADABLE_PACKAGE = "unreadable_package"
INVALID_SKILL_NAME = "invalid_skill_name"
NAME_MISMATCH = "name_mismatch"
MISSING_DESCRIPTION = "missing_description"
RESERVED_KEY = "reserved_front_matter_key"
UNSAFE_PATH = "unsafe_path"
SYMLINK = "package_symlink"
DUPLICATE_NAME = "duplicate_skill_name"


@dataclass(frozen=True)
class Violation:
    """One broken rule. Immutable, because a reported violation is a fact.

    ``path`` is None for a violation about the package as a whole, such as an
    illegal directory name, rather than about one file inside it.
    """

    package: str
    path: str | None
    reason: str
    code: str = ""


def _dedupe(violations: list) -> list:
    out: list = []
    seen: set = set()
    for item in violations:
        key = (item.package, item.path, item.reason, item.code)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _loader_code(reason: str) -> str:
    """Code for a violation the loader recorded while walking the package.

    The symlink rule is enforced in both places, and the codes have to agree or
    `_dedupe` stops recognising the two reports as the same fact.
    """
    return SYMLINK if reason == NO_SYMLINKS else UNREADABLE_PACKAGE


def validate_package(pkg: SkillPackage) -> list:
    out: list = [
        Violation(pkg.name, path, reason, _loader_code(reason))
        for path, reason in getattr(pkg, "errors", [])
    ]
    # Front matter that could not be read tells us nothing about name or
    # description, so the syntax error above is the only honest thing to report.
    unreadable = any(path == "SKILL.md" for path, _ in getattr(pkg, "errors", []))
    if "SKILL.md" not in pkg.files:
        out.append(Violation(pkg.name, "SKILL.md", "missing SKILL.md", MISSING_SKILL_MD))
    if not is_valid_skill_name(pkg.name):
        out.append(Violation(
                pkg.name, None, f"invalid skill name '{pkg.name}'", INVALID_SKILL_NAME
            ))
    if not unreadable:
        declared = pkg.meta.get("name", "")
        if declared != pkg.name:
            out.append(
                Violation(
                    pkg.name,
                    "SKILL.md",
                    f"front-matter name '{declared}' != directory '{pkg.name}'",
                    NAME_MISMATCH,
                )
            )
        if not pkg.meta.get("description", "").strip():
            out.append(Violation(
                    pkg.name,
                    "SKILL.md",
                    "empty or missing description",
                    MISSING_DESCRIPTION,
                ))
    for key in pkg.meta:
        if key.startswith(MANAGED_PREFIX):
            # Projection sets these. An author who declares one would see it
            # rewritten in the projected copy and silently disagree with the
            # canonical package.
            out.append(
                Violation(
                    pkg.name,
                    "SKILL.md",
                    f"reserved front-matter key '{key}' (the "
                    f"'{MANAGED_PREFIX}' prefix belongs to Workbench)",
                    RESERVED_KEY,
                )
            )
    for rel in pkg.files:
        if rel.startswith("/") or ".." in rel.split("/"):
            out.append(Violation(pkg.name, rel, "unsafe path escapes package", UNSAFE_PATH))
    if pkg.root.is_dir():
        for path in pkg.root.rglob("*"):
            if path.is_symlink():
                out.append(
                    Violation(
                        pkg.name,
                        path.relative_to(pkg.root).as_posix(),
                        NO_SYMLINKS,
                        SYMLINK,
                    )
                )
    return _dedupe(out)


def validate_catalog(pkgs: list) -> list:
    out: list = []
    seen: dict = {}
    for pkg in pkgs:
        out.extend(validate_package(pkg))
        seen[pkg.name] = seen.get(pkg.name, 0) + 1
    for name, count in seen.items():
        if count > 1:
            out.append(Violation(
                    name, None, f"duplicate skill name '{name}'", DUPLICATE_NAME
                ))
    return out
