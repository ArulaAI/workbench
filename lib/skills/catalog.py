"""Discover, validate, then read canonical skill packages.

The order is the contract. Validation is the boundary a package has to clear
before any of its bytes are loaded, rather than a check applied to content
already in memory:

    1. discover   candidate directories, without requiring anything of them
    2. root       the package directory is a real directory, not a link
    3. required   SKILL.md is present
    4. symlinks   every member is refused if it is a link of any kind
    5. metadata   SKILL.md alone is read, parsed, and schema-validated
    6. members    the remaining files are read
    7. uniqueness no two packages in the catalog claim one name

Each phase runs only if the ones before it found nothing wrong, so a package
with a linked root is never walked, a package holding a link is never read, and
a package whose front matter fails its schema never has its other files opened.
The rules themselves live in ``validate``, which knows nothing about the
filesystem; this module owns only their ordering.

``load_catalog`` is the strict entrance and raises on the first package that
breaks the contract. ``load_package`` runs the same phases without raising, so
a caller that wants to inspect a broken package can, with the reason recorded
on it rather than thrown.
"""
from __future__ import annotations

import os
from pathlib import Path

from skills import is_junk
from skills.frontmatter import parse
from skills.models import NO_SYMLINK_ROOT, NO_SYMLINKS, SkillPackage
from skills.validate import (
    loader_violation,
    missing_skill_md,
    validate_metadata,
    validate_name,
    validate_relpaths,
    validate_uniqueness,
)

__all__ = ["NO_SYMLINKS", "SkillPackage", "load_catalog", "load_package"]

SKILL_MD = "SKILL.md"


def _discover(skills_dir: Path) -> list:
    """Phase 1: every directory that claims to be a package, valid or not.

    Filtering on ``SKILL.md`` here would make the "every skill needs a
    SKILL.md" rule unreachable: a package missing it would vanish from the
    catalog instead of being reported. Hidden and generated directories are
    still skipped, since a legal skill name can never start with a dot.
    """
    return [
        child
        for child in sorted(skills_dir.iterdir())
        if child.is_dir()
        and not (child.name.startswith(".") or is_junk(child.name))
    ]


def _root_error(pkg_dir: Path):
    """Phase 2: refuse a linked package root before anything walks it."""
    if pkg_dir.is_symlink():
        return (None, NO_SYMLINK_ROOT)
    return None


def _required_error(pkg_dir: Path):
    """Phase 3: SKILL.md has to exist. A stat, never a read.

    ``lexists`` rather than ``is_file`` so that a symlink in its place counts
    as present here and is refused by the symlink phase instead, which is the
    accurate report.
    """
    if os.path.lexists(pkg_dir / SKILL_MD):
        return None
    return "missing"


def _member_scan(pkg_dir: Path) -> tuple:
    """Phase 4: the member paths to read, or the links standing in their way.

    ``os.walk`` with ``followlinks=False`` refuses to descend a linked
    directory, and each entry is checked with ``is_symlink`` before it is
    recorded, so a link pointing at ``~/.ssh`` is reported rather than opened.
    Nothing here reads a single byte.
    """
    relpaths: list = []
    errors: list = []
    for dirpath, dirnames, filenames in os.walk(pkg_dir, followlinks=False):
        here = Path(dirpath)
        kept: list = []
        for name in sorted(dirnames):
            rel = (here / name).relative_to(pkg_dir).as_posix()
            if (here / name).is_symlink():
                errors.append((rel, NO_SYMLINKS))
                continue
            if is_junk(rel):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            rel = (here / name).relative_to(pkg_dir).as_posix()
            if (here / name).is_symlink():
                errors.append((rel, NO_SYMLINKS))
                continue
            if is_junk(rel):
                continue
            relpaths.append(rel)
    return sorted(relpaths), errors


def _metadata(pkg_dir: Path) -> tuple:
    """Phase 5: read SKILL.md, and only SKILL.md, then parse it.

    The encoding is spelled out so the same package loads identically whatever
    the machine's locale says. A broken fence and a non-UTF-8 file are reported
    the same way: both leave the front matter unknowable, and both are the
    package author's to fix.
    """
    try:
        source = (pkg_dir / SKILL_MD).read_bytes()
        return parse(source.decode("utf-8")), source, None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return ({}, ""), b"", (SKILL_MD, str(exc))


def _members(pkg_dir: Path, relpaths) -> dict:
    """Phase 6: read what the earlier phases cleared."""
    out: dict = {}
    for rel in relpaths:
        out[rel] = (pkg_dir / rel).read_bytes()
    return out


def _package(pkg_dir: Path, *, meta=None, body="", files=None, errors=None):
    return SkillPackage(
        name=pkg_dir.name,
        root=pkg_dir,
        meta=meta or {},
        body=body,
        files=files or {},
        errors=errors or [],
    )


def _load(pkg_dir: Path) -> tuple:
    """Run the phases in order. Returns ``(package, violations)``.

    A phase that finds a problem stops the pipeline, which is the whole point:
    every later phase would have to touch content this one just refused.
    """
    pkg_dir = Path(pkg_dir)
    name = pkg_dir.name
    # The directory name is a rule of its own and does not gate any read, so
    # it is collected once here and carried through whichever phase stops.
    violations = validate_name(name)

    root = _root_error(pkg_dir)
    if root is not None:
        return (
            _package(pkg_dir, errors=[root]),
            violations + [loader_violation(name, root)],
        )

    if _required_error(pkg_dir) is not None:
        return _package(pkg_dir), violations + [missing_skill_md(name)]

    relpaths, link_errors = _member_scan(pkg_dir)
    if link_errors:
        return (
            _package(pkg_dir, errors=link_errors),
            violations + [loader_violation(name, item) for item in link_errors],
        )

    (meta, body), source, parse_error = _metadata(pkg_dir)
    if parse_error is not None:
        return (
            _package(pkg_dir, errors=[parse_error]),
            violations + [loader_violation(name, parse_error)],
        )

    violations += validate_metadata(name, meta)
    violations += validate_relpaths(name, relpaths)
    if violations:
        # Rejected already. Reading the members now would be exactly the
        # read-before-validate order this pipeline exists to avoid. SKILL.md
        # stays on the package because it was read to get here.
        return (
            _package(pkg_dir, meta=meta, body=body, files={SKILL_MD: source}),
            violations,
        )

    return (
        _package(pkg_dir, meta=meta, body=body, files=_members(pkg_dir, relpaths)),
        [],
    )


def load_package(pkg_dir: Path) -> SkillPackage:
    """Load one package without raising, recording why it is broken if it is.

    A package that cannot be read still has to reach ``validate``, which is
    where the user gets told which file broke and how.
    """
    return _load(Path(pkg_dir))[0]


def load_catalog(skills_dir: Path) -> list:
    """Every package in the catalog, or a ValueError naming what is wrong.

    A missing catalog directory is an installation failure, never an empty
    catalog: treating it as empty would plan the removal of every projection a
    project already has.
    """
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        raise ValueError(f"skill catalog directory not found: {skills_dir}")

    pkgs: list = []
    violations: list = []
    for child in _discover(skills_dir):
        pkg, found = _load(child)
        pkgs.append(pkg)
        violations.extend(found)
    violations.extend(validate_uniqueness([pkg.name for pkg in pkgs]))

    if violations:
        details = "; ".join(
            f"{item.package}:{item.path or '-'}: {item.reason}"
            for item in violations
        )
        raise ValueError(f"invalid skill catalog: {details}")
    return pkgs
