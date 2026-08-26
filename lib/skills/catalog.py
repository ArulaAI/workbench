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


def _read_files(root: Path) -> dict:
    files: dict = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            files[p.relative_to(root).as_posix()] = p.read_bytes()
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
    return pkgs
