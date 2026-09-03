"""Canonical package contract validation.

Every rule lives here, expressed over data rather than over the filesystem, so
a package assembled in memory can be validated without touching a disk. Each
rule maps to a fixture in tests/skills/test_validate.py.

Two entry points, for two different callers:

``validate_package``  every rule that applies to one already-loaded package.
``validate_catalog``  the same, plus catalog-wide uniqueness.

The loader does not use either. It walks the phases below in order so that a
package is rejected before its bytes are read, and calls the individual rule
functions at the phase where each one belongs:

    validate_name           the directory name is a legal skill name
    missing_skill_md        the one required member is present
    validate_metadata       front matter carries the fields and types
    validate_reserved_keys  the author declared none of Workbench's own keys
    validate_relpaths       no member path escapes the package
    validate_uniqueness     no two packages claim one name

Keeping the rules separate from their ordering is what lets the loader enforce
them early without the contract being stated twice.
"""
from __future__ import annotations

from dataclasses import dataclass

from skills import is_valid_skill_name
from skills.models import NO_SYMLINK_ROOT, NO_SYMLINKS, SkillPackage
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
INVALID_METADATA_TYPE = "invalid_metadata_type"


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
    """Code for a violation the loader recorded while walking the package."""
    if reason in (NO_SYMLINKS, NO_SYMLINK_ROOT):
        return SYMLINK
    return UNREADABLE_PACKAGE


def loader_violation(package: str, error) -> Violation:
    """Turn one ``(path, reason)`` the loader recorded into a violation."""
    path, reason = error
    return Violation(package, path, reason, _loader_code(reason))


# ── Rules ──────────────────────────────────────────────────────────────────
# Each is callable on its own so the loader can run it at the phase where it
# belongs, before the next phase reads anything.


def validate_name(name: str) -> list:
    """The package directory name, which is also its projection directory."""
    if is_valid_skill_name(name):
        return []
    return [Violation(name, None, f"invalid skill name '{name}'", INVALID_SKILL_NAME)]


def missing_skill_md(name: str) -> Violation:
    """The one required member of every package."""
    return Violation(name, "SKILL.md", "missing SKILL.md", MISSING_SKILL_MD)


# The scalar metadata fields the engine reads, and the type each has to be.
# Front matter is real YAML, so `version: 1.0` arrives as a float and
# `name: true` as a boolean. Enforcing that here is what keeps every consumer
# downstream free to treat these as strings.
_STRING_FIELDS = ("name", "description", "version")


def _string_fields(name: str, meta: dict) -> tuple:
    """Return ``(violations, bad_keys)`` for metadata fields of the wrong type."""
    out: list = []
    bad: set = set()
    for field in _STRING_FIELDS:
        if field not in meta:
            continue
        value = meta[field]
        if isinstance(value, str):
            continue
        bad.add(field)
        out.append(
            Violation(
                name,
                "SKILL.md",
                f"front-matter '{field}' must be a string, got "
                f"{type(value).__name__}; quote the value",
                INVALID_METADATA_TYPE,
            )
        )
    return out, bad


def validate_metadata(name: str, meta: dict) -> list:
    """The front-matter schema: required fields, their types, reserved keys.

    Call this only once the front matter has actually been parsed. Running it
    against an empty mapping because SKILL.md was missing or unreadable would
    report a missing description to an author whose real problem is the file.
    """
    out, mistyped = _string_fields(name, meta)
    # A field of the wrong type is already reported. Comparing or stripping it
    # as well would either crash or add a second, misleading violation about a
    # name or description the author did spell out.
    if "name" not in mistyped:
        declared = meta.get("name", "")
        if declared != name:
            out.append(
                Violation(
                    name,
                    "SKILL.md",
                    f"front-matter name '{declared}' != directory '{name}'",
                    NAME_MISMATCH,
                )
            )
    if "description" not in mistyped:
        if not meta.get("description", "").strip():
            out.append(
                Violation(
                    name, "SKILL.md", "empty or missing description", MISSING_DESCRIPTION
                )
            )
    return out + validate_reserved_keys(name, meta)


def validate_reserved_keys(name: str, meta: dict) -> list:
    """Keys an author may not declare, because projection writes them.

    Separate from the rest of the schema because it stands on its own: a
    declared key is a fact about what the author wrote, so it holds whatever
    else is wrong with the file, and it needs no required field to be present.
    """
    return [
        # An author who declares one of these would see it rewritten in the
        # projected copy and silently disagree with the canonical package.
        Violation(
            name,
            "SKILL.md",
            f"reserved front-matter key '{key}' (the "
            f"'{MANAGED_PREFIX}' prefix belongs to Workbench)",
            RESERVED_KEY,
        )
        for key in meta
        if key.startswith(MANAGED_PREFIX)
    ]


def validate_relpaths(name: str, relpaths) -> list:
    """Member paths, which become projection paths and must stay inside it."""
    return [
        Violation(name, rel, "unsafe path escapes package", UNSAFE_PATH)
        for rel in relpaths
        if rel.startswith("/") or ".." in rel.split("/")
    ]


def validate_uniqueness(names) -> list:
    """One name per catalog: two packages cannot project to one directory."""
    seen: dict = {}
    for name in names:
        seen[name] = seen.get(name, 0) + 1
    return [
        Violation(name, None, f"duplicate skill name '{name}'", DUPLICATE_NAME)
        for name, count in seen.items()
        if count > 1
    ]


# ── Compositions ───────────────────────────────────────────────────────────


def validate_package(pkg: SkillPackage) -> list:
    """Every rule that applies to one loaded package, in no particular order.

    Unlike the loader this cannot stop early, because the package is already
    read. It still declines to judge metadata it never saw: front matter that
    is absent or unparseable makes the name and description unknowable, and the
    file itself is the only honest thing to report.
    """
    errors = getattr(pkg, "errors", [])
    out: list = [loader_violation(pkg.name, error) for error in errors]
    # A package-level failure means the walk never happened, so nothing can be
    # said about members. Reporting a missing SKILL.md on top of "the root is a
    # symlink" would send the author looking for the wrong file.
    unread = any(path is None for path, _ in errors)
    unreadable = any(path == "SKILL.md" for path, _ in errors)
    absent = "SKILL.md" not in pkg.files
    if absent and not unread:
        out.append(missing_skill_md(pkg.name))
    out.extend(validate_name(pkg.name))
    if not (unread or unreadable or absent):
        out.extend(validate_metadata(pkg.name, pkg.meta))
    else:
        # The required fields are unknowable, but a key the author declared is
        # still a key the author declared.
        out.extend(validate_reserved_keys(pkg.name, pkg.meta))
    out.extend(validate_relpaths(pkg.name, pkg.files))
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
    """``validate_package`` over every package, plus catalog-wide uniqueness."""
    out: list = []
    for pkg in pkgs:
        out.extend(validate_package(pkg))
    out.extend(validate_uniqueness([pkg.name for pkg in pkgs]))
    return out
