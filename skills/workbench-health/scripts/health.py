#!/usr/bin/env python3
"""Read-only health check for Workbench skill projections."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SKILL = "workbench-health"
HEALTHY = "healthy"
UNHEALTHY = "unhealthy"
SKILLS_ROOTS = {
    "claude_code": ".claude/skills",
    "codex": ".agents/skills",
    "copilot": ".github/skills",
}
SURFACE_ALIASES = {"claude": "claude_code"}
# Generated/OS files that are never part of a projection.
_JUNK_DIRS = {"__pycache__", ".git"}
_JUNK_SUFFIXES = (".pyc", ".pyo")
_JUNK_NAMES = {".DS_Store"}


def _is_junk(relative_path):
    parts = relative_path.split("/")
    if any(part in _JUNK_DIRS for part in parts):
        return True
    if parts[-1] in _JUNK_NAMES:
        return True
    return relative_path.endswith(_JUNK_SUFFIXES)


def _surface_from_location(project_root):
    """Infer the surface from the harness root this helper was projected into."""
    try:
        root = Path(__file__).resolve().parents[2]
    except IndexError:
        return None
    for surface_id, relative in SKILLS_ROOTS.items():
        if root == project_root / relative:
            return surface_id
    return None


def _hash_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def build_result(project_root, surface=None):
    """Verify that every manifested skill file exists and is unchanged."""
    project_root = Path(project_root).resolve()
    if surface:
        surface = SURFACE_ALIASES.get(surface, surface)
    else:
        surface = _surface_from_location(project_root) or "claude_code"
    issues: list[str] = []
    manifest_loaded = False
    manifest_path = project_root / ".speed" / "skills" / "manifest.json"
    manifest: dict = {}

    if not manifest_path.is_file():
        issues.append("skill manifest is missing; run `workbench skills sync`")
    else:
        try:
            loaded = json.loads(manifest_path.read_text())
            if not isinstance(loaded, dict):
                issues.append("skill manifest root must be an object")
            else:
                manifest = loaded
                manifest_loaded = True
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"skill manifest is unreadable: {exc}")

    surfaces = manifest.get("surfaces", {})
    if manifest_loaded and not isinstance(surfaces, dict):
        issues.append("skill manifest surfaces must be an object")
        surfaces = {}
    surface_entry = surfaces.get(surface, {})
    if surface_entry and not isinstance(surface_entry, dict):
        issues.append(f"manifest entry for surface '{surface}' must be an object")
        surface_entry = {}
    skills = surface_entry.get("skills", {})
    if skills and not isinstance(skills, dict):
        issues.append(f"manifest skills for surface '{surface}' must be an object")
        skills = {}
    if manifest_loaded and not skills:
        issues.append(f"no Workbench skills are imported for surface '{surface}'")

    skills_root = project_root / SKILLS_ROOTS.get(
        surface, surface_entry.get("root", f".{surface}/skills")
    )
    for skill_name, entry in sorted(skills.items()):
        expected_files = entry.get("files", {})
        skill_root = skills_root / skill_name
        if not expected_files:
            issues.append(f"{skill_name}: manifest contains no files")
            continue
        for relative_path, expected_hash in sorted(expected_files.items()):
            relative = Path(relative_path)
            projected = skill_root / relative
            if relative.is_absolute() or ".." in relative.parts:
                issues.append(f"{skill_name}: unsafe manifest path {relative_path}")
                continue
            if not projected.is_file():
                issues.append(f"{skill_name}: missing {relative_path}")
            elif _hash_file(projected) != expected_hash:
                issues.append(f"{skill_name}: modified {relative_path}")
        actual_files = {
            relative
            for relative in (
                path.relative_to(skill_root).as_posix()
                for path in skill_root.rglob("*")
                if path.is_file()
            )
            if not _is_junk(relative)
        } if skill_root.is_dir() else set()
        for relative_path in sorted(actual_files - set(expected_files)):
            issues.append(f"{skill_name}: unexpected {relative_path}")

    healthy = not issues
    return {
        "skill": SKILL,
        "status": HEALTHY if healthy else UNHEALTHY,
        "message": (
            "Workbench skills were imported successfully and are ready to use."
            if healthy
            else "Workbench skills are not ready to use."
        ),
        "catalog_version": manifest.get("catalog_version", "unknown"),
        "surface": surface,
        "skills": sorted(skills),
        "issues": issues,
    }


def format_text(result):
    lines = [
        f"skill: {result['skill']}",
        f"status: {result['status']}",
        f"message: {result['message']}",
        f"catalog_version: {result['catalog_version']}",
        f"surface: {result['surface']}",
        f"skills: {', '.join(result['skills']) or 'none'}",
    ]
    lines.extend(f"issue: {issue}" for issue in result["issues"])
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="workbench-health")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--surface", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_result(args.project_root, args.surface)
    print(json.dumps(result, indent=2) if args.json else format_text(result))
    return 0 if result["status"] == HEALTHY else 1


if __name__ == "__main__":
    raise SystemExit(main())
