"""Reusable, normalized command discovery.

Reads project instructions and manifests for runtime/dev/build/test/lint/
typecheck commands. Not dashboard-specific — the digest builder is one
consumer, not the owner, of this registry (see RFC > Builder Design >
Commands and > File Impact).

Never executes anything it discovers.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterator

from .repository_digest_schema import is_within, line_number, load_toml_file, make_evidence, manifest_paths, safe_read_text

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - PyYAML is a project dependency
    yaml = None  # type: ignore

# Heading text (case-insensitive) → command purpose.
_HEADING_PURPOSE: dict[str, str] = {
    "test": "test", "tests": "test", "testing": "test",
    "lint": "lint", "linting": "lint",
    "typecheck": "typecheck", "type check": "typecheck", "type-check": "typecheck",
    "build": "build",
    "run": "run", "running": "run",
    "development": "develop", "develop": "develop", "dev": "develop",
    "format": "format", "formatting": "format",
    "migrate": "migrate", "migration": "migrate", "migrations": "migrate",
}

# package.json script-name → purpose, by substring, checked in order.
_NPM_SCRIPT_PURPOSE: list[tuple[str, str]] = [
    ("typecheck", "typecheck"), ("type-check", "typecheck"),
    ("lint", "lint"),
    ("test", "test"),
    ("format", "format"), ("fmt", "format"),
    ("migrate", "migrate"),
    ("build", "build"),
    ("dev", "develop"), ("start", "run"), ("serve", "run"),
]

_HEADING_RE = re.compile(r"^#{1,6}\s*(.+?)\s*$", re.MULTILINE)
# Any fence language tag (or none) is accepted — the heading text is what
# scopes this to a recognized command section, not the fence's language.
_FENCE_RE = re.compile(r"```[A-Za-z0-9_+-]*\n(.*?)```", re.DOTALL)


def _purpose_for_heading(text: str) -> str | None:
    key = text.strip().lower().rstrip(":")
    return _HEADING_PURPOSE.get(key)


def _commands_from_fence(block: str) -> list[str]:
    lines = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line[1:].strip() if line.startswith("$") else line
        if line:
            lines.append(line)
    return lines


def discover_from_project_instructions(project_root: Path) -> list[dict[str, Any]]:
    """CLAUDE.md / AGENTS.md: commands under a recognized heading."""
    results: list[dict[str, Any]] = []
    for filename in ("CLAUDE.md", "AGENTS.md"):
        text = safe_read_text(project_root / filename, project_root)
        if text is None:
            continue

        headings = list(_HEADING_RE.finditer(text))
        for idx, match in enumerate(headings):
            purpose = _purpose_for_heading(match.group(1))
            if purpose is None:
                continue
            section_end = headings[idx + 1].start() if idx + 1 < len(headings) else len(text)
            section = text[match.end():section_end]
            line_no = line_number(text, match.start())
            for fence in _FENCE_RE.finditer(section):
                for cmd in _commands_from_fence(fence.group(1)):
                    results.append({
                        "purpose": purpose,
                        "command": cmd,
                        "working_directory": ".",
                        "confidence": "confirmed",
                        "evidence": [make_evidence(
                            "project_instructions", f"Documented under '{match.group(1).strip()}'",
                            path=filename, line=line_no,
                        )],
                    })
    return results


def _npm_script_purpose(name: str) -> str:
    lowered = name.lower()
    for needle, mapped in _NPM_SCRIPT_PURPOSE:
        if needle in lowered:
            return mapped
    return "other"


def _scripts_from_package_json(path: Path, working_directory: str, project_root: Path) -> list[dict[str, Any]]:
    text = safe_read_text(path, project_root)
    if text is None:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return []

    display_path = f"{working_directory}/package.json" if working_directory != "." else "package.json"
    results: list[dict[str, Any]] = []
    for name, script in scripts.items():
        if not isinstance(script, str) or not script.strip():
            continue
        results.append({
            "purpose": _npm_script_purpose(name),
            "command": f"npm run {name}",
            "working_directory": working_directory,
            "confidence": "confirmed",
            "evidence": [make_evidence(
                "manifest", f"{display_path} scripts.{name}", path=display_path,
                artifact_key=f"/scripts/{name}",
            )],
        })
    return results


def _workspace_patterns(data: dict[str, Any]) -> list[str]:
    workspaces = data.get("workspaces")
    if isinstance(workspaces, list):
        return [p for p in workspaces if isinstance(p, str)]
    if isinstance(workspaces, dict) and isinstance(workspaces.get("packages"), list):
        return [p for p in workspaces["packages"] if isinstance(p, str)]
    return []


def discover_from_package_json(
    project_root: Path, project_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Root package.json scripts, plus each npm/yarn workspace member's own
    scripts with that member's own working_directory retained (RFC >
    Builder Design > Commands: "workspace working directory retained") —
    plus, when project_map is available, every *other* package.json it
    already knows about (a nested manifest that isn't part of a declared
    workspace still has its own real scripts worth surfacing, e.g. a
    dashboard frontend or docs site living alongside a Python root that has
    no root package.json at all).
    """
    results: list[dict[str, Any]] = []
    seen_dirs: set[Path] = set()

    root_manifest = project_root / "package.json"
    root_text = safe_read_text(root_manifest, project_root)
    if root_text is not None:
        try:
            data = json.loads(root_text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            results.extend(_scripts_from_package_json(root_manifest, ".", project_root))
            seen_dirs.add(project_root.resolve())
            for pattern in _workspace_patterns(data):
                try:
                    matches = sorted(project_root.glob(pattern))
                except (OSError, ValueError):
                    continue
                for match in matches:
                    if not match.is_dir():
                        continue
                    resolved = match.resolve()
                    if resolved in seen_dirs:
                        continue
                    seen_dirs.add(resolved)
                    member_manifest = match / "package.json"
                    try:
                        working_directory = str(resolved.relative_to(project_root.resolve())).replace(os.sep, "/")
                    except ValueError:
                        continue
                    results.extend(_scripts_from_package_json(member_manifest, working_directory, project_root))

    for rel_path in manifest_paths(project_map, "package.json"):
        manifest_path = project_root / rel_path
        resolved_dir = manifest_path.parent.resolve()
        if resolved_dir in seen_dirs:
            continue
        seen_dirs.add(resolved_dir)
        working_directory = "." if resolved_dir == project_root.resolve() else rel_path.rsplit("/", 1)[0]
        results.extend(_scripts_from_package_json(manifest_path, working_directory, project_root))

    return results


def discover_from_pyproject_toml(project_root: Path) -> list[dict[str, Any]]:
    pyproject_path = project_root / "pyproject.toml"
    if not is_within(pyproject_path, project_root):
        return []
    data = load_toml_file(pyproject_path)
    if not data:
        return []

    scripts = (
        data.get("project", {}).get("scripts")
        or data.get("tool", {}).get("poetry", {}).get("scripts")
        or {}
    )
    results: list[dict[str, Any]] = []
    for name in scripts:
        results.append({
            "purpose": "other",
            "command": name,
            "working_directory": ".",
            "confidence": "confirmed",
            "evidence": [make_evidence(
                "manifest", f"pyproject.toml registered script {name!r}", path="pyproject.toml",
            )],
        })
    return results


_MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9_.\-]+):(?!=)", re.MULTILINE)
_MAKE_PURPOSE_HINTS: list[tuple[str, str]] = [
    ("test", "test"), ("lint", "lint"), ("typecheck", "typecheck"),
    ("fmt", "format"), ("format", "format"), ("build", "build"),
    ("migrate", "migrate"), ("run", "run"), ("dev", "develop"),
]


def discover_from_makefile(project_root: Path) -> list[dict[str, Any]]:
    text = safe_read_text(project_root / "Makefile", project_root)
    if text is None:
        return []

    results: list[dict[str, Any]] = []
    for match in _MAKE_TARGET_RE.finditer(text):
        target = match.group(1)
        if target.startswith(".") or target == "PHONY":
            continue
        purpose = "other"
        lowered = target.lower()
        for needle, mapped in _MAKE_PURPOSE_HINTS:
            if needle in lowered:
                purpose = mapped
                break
        line_no = line_number(text, match.start())
        results.append({
            "purpose": purpose,
            "command": f"make {target}",
            "working_directory": ".",
            "confidence": "confirmed",
            "evidence": [make_evidence(
                "manifest", f"Makefile target '{target}'", path="Makefile", line=line_no,
            )],
        })
    return results


def discover_from_procfile(project_root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name in ("Procfile", "Procfile.dev"):
        text = safe_read_text(project_root / name, project_root)
        if text is None:
            continue
        for i, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            process_name, _, command = line.partition(":")
            command = command.strip()
            if not command:
                continue
            purpose = "worker" if "worker" in process_name.lower() else "run"
            results.append({
                "purpose": purpose,
                "command": command,
                "working_directory": ".",
                "confidence": "confirmed",
                "evidence": [make_evidence(
                    "manifest", f"{name} process '{process_name.strip()}'", path=name, line=i,
                )],
            })
    return results


def discover_from_cargo_toml(project_root: Path) -> list[dict[str, Any]]:
    """Always empty: the RFC forbids guessing `cargo test` just because
    Cargo.toml exists, and unlike package.json/pyproject.toml there's no
    scripts table to read instead. Kept as an explicit no-op rather than
    an absent source.
    """
    return []


_CI_WORKFLOW_GLOBS = (".github/workflows/*.yml", ".github/workflows/*.yaml")


def discover_from_ci_workflows(project_root: Path) -> list[dict[str, Any]]:
    """Extract `run:` step commands from GitHub Actions workflow files.

    Returns raw (command, evidence) candidates keyed by normalized command
    text — discover_commands() uses these only to corroborate (add
    evidence to) a command already discovered from a stronger source. A CI
    command with no match elsewhere is never promoted to a standalone
    command (RFC > Builder Design > Commands: "Commands may corroborate a
    command but are not promoted alone when they require CI-only
    environment setup").
    """
    if yaml is None:
        return []

    results: list[dict[str, Any]] = []
    for pattern in _CI_WORKFLOW_GLOBS:
        for path in sorted(project_root.glob(pattern)):
            text = safe_read_text(path, project_root)
            if text is None:
                continue
            try:
                doc = yaml.safe_load(text)
            except Exception:
                continue
            rel_path = str(path.relative_to(project_root)).replace(os.sep, "/")
            for job_name, line in _iter_run_lines(doc):
                results.append({
                    "command": line,
                    "evidence": [make_evidence("manifest", f"CI workflow job '{job_name}'", path=rel_path)],
                })
    return results


def _iter_run_lines(doc: Any) -> Iterator[tuple[str, str]]:
    """Yield (job_name, command_line) for every non-empty, non-comment line
    of every `run:` step in a parsed GitHub Actions workflow document.
    """
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
        return
    for job_name, job in doc["jobs"].items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                continue
            for line in step["run"].splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    yield job_name, line


def discover_commands(
    project_root: Path, project_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run every source, merge same normalized (command, working_directory)
    pairs by unioning evidence, and keep conflicting same-purpose commands
    as separate records — the digest builder turns those into a
    'conflicting_commands' gap, this function only discovers and merges.

    project_map (already-loaded project-map.json) is optional so every
    other caller of this module keeps working unchanged — passing it lets
    discover_from_package_json() also pick up nested package.json manifests
    it already knows about, not just the repository root's.

    CI workflow commands are folded in separately, as corroborating
    evidence on an already-discovered command only — see
    discover_from_ci_workflows().
    """
    raw: list[dict[str, Any]] = [
        *discover_from_project_instructions(project_root),
        *discover_from_package_json(project_root, project_map),
        *discover_from_pyproject_toml(project_root),
        *discover_from_makefile(project_root),
        *discover_from_procfile(project_root),
        *discover_from_cargo_toml(project_root),
    ]

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in raw:
        key = (entry["command"].strip(), entry["working_directory"])
        if key in merged:
            merged[key]["evidence"].extend(entry["evidence"])
        else:
            merged[key] = dict(entry)

    by_command_text: dict[str, list[dict[str, Any]]] = {}
    for entry in merged.values():
        by_command_text.setdefault(entry["command"].strip(), []).append(entry)

    for ci_entry in discover_from_ci_workflows(project_root):
        matches = by_command_text.get(ci_entry["command"].strip())
        if not matches:
            continue  # never promoted alone — no corroborated source, discarded
        for match in matches:
            match["evidence"].extend(ci_entry["evidence"])

    return list(merged.values())
