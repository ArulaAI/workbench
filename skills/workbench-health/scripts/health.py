#!/usr/bin/env python3
"""Read-only health check for Workbench skill projections.

The file is projected into each harness skill directory and executed from
there, so it stays stdlib-only and imports nothing from the Workbench library:
the copy that runs is the copy the harness received, with no package around it.

Everything the manifest supplies is untrusted input. That file is committed, so
a bad merge, a hand edit, or a hostile branch reaches this helper as data, and
none of it may steer a read outside the project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SKILL = "workbench-health"
HEALTHY = "healthy"
UNHEALTHY = "unhealthy"
# The only projection roots that exist. A `root` recorded in the manifest is
# deliberately never resolved: honoring it would let the manifest pick the
# directory this helper reads.
SKILLS_ROOTS = {
    "claude_code": ".claude/skills",
    "codex": ".agents/skills",
    "copilot": ".github/skills",
}
SURFACE_ALIASES = {"claude": "claude_code"}
# Same rule as `is_valid_skill_name` in lib/skills/__init__.py, restated here
# because a projected helper has no library to import it from. A skill name is
# also the only legal path segment for its projection directory.
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Repairs, worded to match `workbench skills doctor` so the CLI and the skill
# never send a user two different ways.
FIX_SYNC = "Run `workbench skills sync`."
FIX_FORCE = (
    "Review or back up local edits, then run "
    "`workbench skills sync --surface {surface} --force`."
)
FIX_MANIFEST = (
    "Restore `.speed/skills/manifest.json` from version control, then run "
    "`workbench skills sync`."
)
FIX_HARNESS = (
    "Run `workbench init --harness <claude|codex|copilot>`, then run "
    "`workbench skills sync`."
)

# Generated/OS files that are never part of a projection.
_JUNK_DIRS = {"__pycache__", ".git"}
_JUNK_SUFFIXES = (".pyc", ".pyo")
_JUNK_NAMES = {".DS_Store"}
_MISSING = object()


class _Findings:
    """Issues, each paired with the repair that actually fixes it.

    Repairs are deduplicated in first-seen order. Four missing files are one
    `sync` away, and repeating the command per issue would bury the case that
    matters: a result needing two different repairs.
    """

    def __init__(self, surface: str):
        self.surface = surface
        self.issues: list[str] = []
        self.repairs: list[str] = []

    def add(self, issue: str, repair: str) -> None:
        self.issues.append(issue)
        # A plain substitution rather than str.format, matching doctor.py, so a
        # repair string stays free to contain a brace of its own.
        scoped = repair.replace("{surface}", self.surface)
        if scoped not in self.repairs:
            self.repairs.append(scoped)


def _is_junk(relative_path):
    parts = relative_path.split("/")
    if any(part in _JUNK_DIRS for part in parts):
        return True
    if parts[-1] in _JUNK_NAMES:
        return True
    return relative_path.endswith(_JUNK_SUFFIXES)


def _is_valid_skill_name(name) -> bool:
    return bool(isinstance(name, str) and SKILL_NAME_RE.match(name))


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


def _normalize_surface(surface, project_root):
    if not surface:
        return _surface_from_location(project_root) or "claude_code"
    normalized = str(surface).strip().lower()
    return SURFACE_ALIASES.get(normalized, normalized)


def _hash_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _as_mapping(container, key):
    """Return ``(mapping, state)`` with a missing key kept apart from a bad type.

    Truthiness cannot stand in for the type check. ``[]``, ``""`` and ``0`` are
    all falsey, none of them has ``.get()``, and a guard that skips the check
    for falsey values hands the next line an object it cannot use.
    """
    value = container.get(key, _MISSING)
    if value is _MISSING or value is None:
        return {}, "missing"
    if not isinstance(value, dict):
        return {}, "invalid"
    return value, "ok"


def _safe_relative(relative_path):
    """Return the manifest's path as a relative ``Path``, or None if it is not one."""
    if not isinstance(relative_path, str) or not relative_path:
        return None
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        return None
    return relative


def _path_fault(path: Path, project_root: Path):
    """Name why ``path`` may not be read, or return None when it is safe to touch.

    ``is_file()`` and ``read_bytes()`` both follow links, so a projection whose
    bytes live elsewhere would otherwise hash clean and be reported intact. The
    two faults are reported separately because they need different words: a
    symlink pointing back into the same repository is still a link this helper
    refuses, while an escape is a path that leaves the project entirely.
    """
    try:
        relative = path.relative_to(project_root)
    except ValueError:
        return "escape"
    walked = project_root
    for part in relative.parts:
        walked = walked / part
        if walked.is_symlink():
            return "symlink"
    try:
        resolved = path.resolve()
    except OSError:
        return "escape"
    if resolved != project_root and project_root not in resolved.parents:
        return "escape"
    return None


def _projected_paths(skill_root: Path) -> set:
    """Every non-junk entry on disk, symlinks included so none can hide."""
    found: set = set()
    if not skill_root.is_dir():
        return found
    try:
        for path in skill_root.rglob("*"):
            relative = path.relative_to(skill_root).as_posix()
            if _is_junk(relative):
                continue
            if path.is_symlink() or path.is_file():
                found.add(relative)
    except OSError:
        pass
    return found


def _load_manifest(project_root: Path, findings: _Findings):
    path = project_root / ".speed" / "skills" / "manifest.json"
    if not path.is_file():
        findings.add("skill manifest is missing", FIX_SYNC)
        return {}, False
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        findings.add(f"skill manifest is unreadable: {exc}", FIX_MANIFEST)
        return {}, False
    if not isinstance(loaded, dict):
        findings.add("skill manifest root must be an object", FIX_MANIFEST)
        return {}, False
    return loaded, True


def _check_skill(skill_root, project_root, skill_name, expected_files, findings):
    """Compare one projected skill against the files the manifest recorded."""
    fault = _path_fault(skill_root, project_root)
    if fault is not None:
        detail = (
            "is a symlink" if fault == "symlink" else "escapes the project"
        )
        findings.add(f"{skill_name}: projection directory {detail}", FIX_FORCE)
        return
    for relative_path in sorted(expected_files, key=str):
        expected_hash = expected_files[relative_path]
        relative = _safe_relative(relative_path)
        if relative is None:
            findings.add(
                f"{skill_name}: unsafe manifest path {relative_path}", FIX_MANIFEST
            )
            continue
        if not isinstance(expected_hash, str):
            findings.add(
                f"{skill_name}: manifest records no hash for {relative_path}",
                FIX_MANIFEST,
            )
            continue
        projected = skill_root / relative
        fault = _path_fault(projected, project_root)
        if fault == "symlink":
            findings.add(f"{skill_name}: symlink at {relative_path}", FIX_FORCE)
            continue
        if fault is not None:
            findings.add(
                f"{skill_name}: {relative_path} escapes the project", FIX_FORCE
            )
            continue
        if not projected.is_file():
            findings.add(f"{skill_name}: missing {relative_path}", FIX_SYNC)
            continue
        try:
            digest = _hash_file(projected)
        except OSError as exc:
            findings.add(f"{skill_name}: unreadable {relative_path}: {exc}", FIX_SYNC)
            continue
        if digest != expected_hash:
            findings.add(f"{skill_name}: modified {relative_path}", FIX_FORCE)
    for relative_path in sorted(_projected_paths(skill_root) - set(expected_files)):
        findings.add(f"{skill_name}: unexpected {relative_path}", FIX_FORCE)


def build_result(project_root, surface=None):
    """Verify that every manifested skill file exists, is managed, and is unchanged."""
    project_root = Path(project_root).resolve()
    surface = _normalize_surface(surface, project_root)
    findings = _Findings(surface)

    if surface not in SKILLS_ROOTS:
        # Without a canonical root there is nothing safe to resolve, so the
        # check stops before it touches the filesystem.
        findings.add(
            f"'{surface}' is not a supported agent harness (expected one of: "
            f"{', '.join(sorted(SKILLS_ROOTS))})",
            FIX_HARNESS,
        )
        return _result(surface, {}, "unknown", findings)

    manifest, manifest_loaded = _load_manifest(project_root, findings)

    surfaces, state = _as_mapping(manifest, "surfaces")
    schema_ok = state != "invalid"
    if state == "invalid":
        findings.add("skill manifest surfaces must be an object", FIX_MANIFEST)

    surface_entry, state = _as_mapping(surfaces, surface)
    if state == "invalid":
        schema_ok = False
        findings.add(
            f"manifest entry for surface '{surface}' must be an object", FIX_MANIFEST
        )

    skills, state = _as_mapping(surface_entry, "skills")
    if state == "invalid":
        schema_ok = False
        findings.add(
            f"manifest skills for surface '{surface}' must be an object", FIX_MANIFEST
        )

    if manifest_loaded and schema_ok and not skills:
        findings.add(
            f"no Workbench skills are imported for surface '{surface}'", FIX_SYNC
        )

    skills_root = project_root / SKILLS_ROOTS[surface]
    for skill_name in sorted(skills, key=str):
        entry = skills[skill_name]
        if not _is_valid_skill_name(skill_name):
            # Nothing sync wrote can carry this key, and it is also the path
            # segment the projection directory would be built from.
            findings.add(
                f"manifest records an unsafe skill name: {skill_name}", FIX_MANIFEST
            )
            continue
        if not isinstance(entry, dict):
            findings.add(
                f"{skill_name}: manifest entry must be an object", FIX_MANIFEST
            )
            continue
        expected_files, state = _as_mapping(entry, "files")
        if state == "invalid":
            findings.add(
                f"{skill_name}: manifest files must be an object", FIX_MANIFEST
            )
            continue
        if not expected_files:
            findings.add(f"{skill_name}: manifest contains no files", FIX_SYNC)
            continue
        _check_skill(
            skills_root / skill_name,
            project_root,
            skill_name,
            expected_files,
            findings,
        )

    version = manifest.get("catalog_version")
    if not isinstance(version, str) or not version:
        version = "unknown"
    return _result(surface, skills, version, findings)


def _result(surface, skills, catalog_version, findings):
    healthy = not findings.issues
    return {
        "skill": SKILL,
        "status": HEALTHY if healthy else UNHEALTHY,
        "message": (
            "Workbench skills were imported successfully and are ready to use."
            if healthy
            else "Workbench skills are not ready to use."
        ),
        "catalog_version": catalog_version,
        "surface": surface,
        "skills": sorted(str(name) for name in skills),
        "issues": findings.issues,
        "remediation": findings.repairs,
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
    lines.extend(f"remediation: {repair}" for repair in result["remediation"])
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
