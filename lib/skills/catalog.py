"""Discover and load canonical skill packages from the Workbench catalog.

Reading is deliberately paranoid about what it touches. A package is walked with
``followlinks=False`` and every symlink is refused on sight, so no byte outside
the package directory is ever read, not even to decide whether it is valid.
Contract failures found during the read are carried on the package as ``errors``
and turned into violations by ``validate``, which keeps every rule in one table
instead of splitting it between the reader and the validator.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from skills import is_junk
from skills.frontmatter import parse

NO_SYMLINKS = "package files must not be symlinks"


@dataclass
class SkillPackage:
    name: str
    root: Path
    meta: dict
    body: str
    files: dict = field(default_factory=dict)
    # (relative path or None, reason) pairs found while reading the package.
    errors: list = field(default_factory=list)


def _read_files(root: Path):
    """Return ``(files, errors)`` for a package directory.

    ``os.walk`` with ``followlinks=False`` refuses to descend a linked
    directory, and each entry is checked with ``is_symlink`` before it is
    opened, so a link pointing at ``~/.ssh`` is reported rather than read.
    """
    files: dict = {}
    errors: list = []
    if root.is_symlink():
        return files, [(None, "package directory must not be a symlink")]
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        kept: list = []
        for name in sorted(dirnames):
            rel = (here / name).relative_to(root).as_posix()
            if (here / name).is_symlink():
                errors.append((rel, NO_SYMLINKS))
                continue
            if is_junk(rel):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = here / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                errors.append((rel, NO_SYMLINKS))
                continue
            if is_junk(rel):
                continue
            files[rel] = path.read_bytes()
    return dict(sorted(files.items())), errors


def load_package(pkg_dir: Path) -> SkillPackage:
    """Load one package. Never raises on a malformed one: it records the reason.

    A package that cannot be parsed still has to reach ``validate``, which is
    where the user gets told which file broke and how. Front matter is decoded
    from the bytes already read, with the encoding spelled out so the same
    package loads identically whatever the machine's locale says.
    """
    pkg_dir = Path(pkg_dir)
    files, errors = _read_files(pkg_dir)
    meta: dict = {}
    body = ""
    source = files.get("SKILL.md")
    if source is not None:
        try:
            meta, body = parse(source.decode("utf-8"))
        except ValueError as exc:
            # Covers a broken fence and a non-UTF-8 file alike: both leave the
            # front matter unknowable, and both are the package author's to fix.
            errors.append(("SKILL.md", str(exc)))
    return SkillPackage(
        name=pkg_dir.name,
        root=pkg_dir,
        meta=meta,
        body=body,
        files=files,
        errors=errors,
    )


def _is_candidate(child: Path) -> bool:
    """True for a directory that claims to be a package, valid or not.

    Filtering on ``SKILL.md`` here would make the "every skill needs a SKILL.md"
    rule unreachable: a package missing it would vanish from the catalog instead
    of being reported. Hidden and generated directories are still skipped, since
    a legal skill name can never start with a dot.
    """
    if not child.is_dir():
        return False
    return not (child.name.startswith(".") or is_junk(child.name))


def load_catalog(skills_dir: Path) -> list:
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        raise ValueError(f"skill catalog directory not found: {skills_dir}")
    pkgs = [
        load_package(child)
        for child in sorted(skills_dir.iterdir())
        if _is_candidate(child)
    ]
    # Import here to avoid a module cycle: validate needs SkillPackage.
    from skills.validate import validate_catalog

    violations = validate_catalog(pkgs)
    if violations:
        details = "; ".join(
            f"{item.package}:{item.path or '-'}: {item.reason}"
            for item in violations
        )
        raise ValueError(f"invalid skill catalog: {details}")
    return pkgs
