"""Discover and load canonical skill packages from the SPEED catalog."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from skills.frontmatter import parse


@dataclass
class SkillPackage:
    name: str
    root: Path
    meta: dict
    body: str
    files: dict = field(default_factory=dict)


# Generated/OS junk that must never become part of a package or its projection.
_EXCLUDE_DIRS = {"__pycache__", ".git"}
_EXCLUDE_SUFFIXES = (".pyc", ".pyo")
_EXCLUDE_NAMES = {".DS_Store"}


def _is_junk(rel: str) -> bool:
    parts = rel.split("/")
    if any(part in _EXCLUDE_DIRS for part in parts):
        return True
    if parts[-1] in _EXCLUDE_NAMES:
        return True
    return rel.endswith(_EXCLUDE_SUFFIXES)


def _read_files(root: Path) -> dict:
    files: dict = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if _is_junk(rel):
            continue
        files[rel] = p.read_bytes()
    return files


def load_package(pkg_dir: Path) -> SkillPackage:
    pkg_dir = Path(pkg_dir)
    skill_md = pkg_dir / "SKILL.md"
    meta, body = parse(skill_md.read_text()) if skill_md.exists() else ({}, "")
    return SkillPackage(
        name=pkg_dir.name,
        root=pkg_dir,
        meta=meta,
        body=body,
        files=_read_files(pkg_dir),
    )


def load_catalog(skills_dir: Path) -> list:
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        return []
    pkgs = []
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            pkgs.append(load_package(child))
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
