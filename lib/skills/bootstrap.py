"""Initialization policy for the Workbench skill lifecycle.

This module owns the decisions that used to be spread across project.sh,
skills.sh, the manifest, and marker detection.  It is intentionally small: the
project initializer still owns the general SPEED scaffold, while this module
inspects skill state, resolves one harness policy, persists that policy, and
verifies the resulting projections.

Policy precedence during initialization is:

    explicit --harness > WORKBENCH_HARNESSES > [skills].harnesses
        > legacy manifest selection > marker detection

The manifest fallback exists only to migrate projects created by the first
skill-system revision.  Once the policy is persisted, project configuration is
the durable source of truth and the legacy manifest key is removed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

try:  # Python 3.11+; managed installs also carry the backport for older hosts.
    import tomllib
except ImportError:  # pragma: no cover - exercised only by older interpreters
    import tomli as tomllib

from skills.catalog import load_catalog
from skills.inspect import inspect
from skills.manifest import SELECTED_KEY, load_manifest, save_manifest
from skills.models import HARNESS_IDS, SkillState
from skills.targets import detect_harnesses, get_harness


@dataclass(frozen=True)
class BootstrapPlan:
    """The complete skill-specific decision made before init writes anything."""

    harnesses: tuple[str, ...]
    source: str
    persist_required: bool


def _normalize(values, *, source: str) -> tuple[str, ...]:
    """Validate and de-duplicate harness ids without changing their order."""
    result = []
    for raw in values or ():
        for value in str(raw).replace(",", " ").split():
            harness = value.strip().lower()
            if not harness:
                continue
            try:
                get_harness(harness)
            except ValueError as exc:
                expected = ", ".join(HARNESS_IDS)
                raise ValueError(
                    f"unknown harness '{harness}' from {source} "
                    f"(expected: {expected})"
                ) from exc
            if harness not in result:
                result.append(harness)
    return tuple(result)


def configured_harnesses(config_path: Path) -> tuple[str, ...]:
    """Read the durable [skills].harnesses policy from speed.toml."""
    config_path = Path(config_path)
    if not config_path.exists():
        return ()
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid project configuration ({config_path}): {exc}") from exc
    skills = data.get("skills", {})
    if not isinstance(skills, dict):
        raise ValueError(f"invalid project configuration ({config_path}): skills must be a table")
    values = skills.get("harnesses")
    if values is None:
        return ()
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError(
            f"invalid project configuration ({config_path}): "
            "skills.harnesses must be an array of strings"
        )
    result = _normalize(values, source="speed.toml")
    if not result:
        raise ValueError(
            f"invalid project configuration ({config_path}): "
            "skills.harnesses must name at least one harness"
        )
    return result


def plan_initialization(
    project_root,
    skills_dir,
    *,
    explicit=(),
    environment=(),
    config_path=None,
) -> BootstrapPlan:
    """Inspect and resolve initialization policy without modifying the project."""
    project_root = Path(project_root)
    config_path = Path(config_path or project_root / "speed.toml")

    # A missing or invalid canonical catalog is an installation failure.  Do
    # this before policy resolution so no init scenario can write first.
    load_catalog(Path(skills_dir))

    configured = configured_harnesses(config_path)
    manifest = load_manifest(project_root)
    candidates = (
        ("command line", _normalize(explicit, source="command line")),
        ("environment", _normalize(environment, source="WORKBENCH_HARNESSES")),
        ("project configuration", configured),
        (
            "legacy manifest",
            _normalize(
                manifest.get(SELECTED_KEY) or (),
                source="legacy manifest",
            ),
        ),
        (
            "auto-detection",
            tuple(item.id for item in detect_harnesses(project_root)),
        ),
    )
    source = ""
    harnesses: tuple[str, ...] = ()
    for candidate_source, candidate in candidates:
        if candidate:
            source, harnesses = candidate_source, candidate
            break
    if not harnesses:
        expected = "|".join(HARNESS_IDS)
        raise ValueError(
            "no skill harness policy could be resolved; run "
            f"`workbench init --harness <{expected}>`"
        )

    legacy_selection_present = SELECTED_KEY in manifest
    return BootstrapPlan(
        harnesses=harnesses,
        source=source,
        persist_required=configured != harnesses or legacy_selection_present,
    )


def _policy_line(harnesses) -> str:
    values = ", ".join(json.dumps(value) for value in harnesses)
    return f"harnesses = [{values}]"


def _replace_policy(text: str, harnesses) -> str:
    """Insert or replace [skills].harnesses while preserving all other text."""
    policy = _policy_line(harnesses)
    lines = text.splitlines()
    section_start = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        match = re.match(r"^\s*\[([^]]+)\]\s*(?:#.*)?$", line)
        if not match:
            continue
        if section_start is not None:
            section_end = index
            break
        if match.group(1).strip() == "skills":
            section_start = index

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[skills]", policy])
        return "\n".join(lines) + "\n"

    for index in range(section_start + 1, section_end):
        if re.match(r"^\s*harnesses\s*=", lines[index]):
            lines[index] = policy
            return "\n".join(lines) + "\n"
    lines.insert(section_start + 1, policy)
    return "\n".join(lines) + "\n"


def persist_policy(config_path, harnesses, *, template_path=None, project_root=None) -> None:
    """Atomically persist the resolved policy and retire manifest-era intent."""
    config_path = Path(config_path)
    harnesses = _normalize(harnesses, source="resolved policy")
    if not harnesses:
        raise ValueError("cannot persist an empty skill harness policy")
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
    elif template_path is not None:
        text = Path(template_path).read_text(encoding="utf-8")
    else:
        text = ""
    updated = _replace_policy(text, harnesses)

    # Validate the complete result before replacing the user's file.
    tomllib.loads(updated)
    if updated != text:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            dir=str(config_path.parent), prefix=f".{config_path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, config_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    if project_root is not None:
        manifest = load_manifest(Path(project_root))
        if SELECTED_KEY in manifest:
            del manifest[SELECTED_KEY]
            save_manifest(Path(project_root), manifest)


def verify_installation(project_root, skills_dir, catalog_version, harnesses) -> dict:
    """Verify the selected harnesses are present and fully current."""
    inspection = inspect(
        project_root,
        skills_dir,
        catalog_version,
        only_harness=tuple(harnesses),
    )
    rows = [
        {"harness": item.harness, "skill": item.skill, "state": str(item.state)}
        for item in inspection.skills
    ]
    healthy = bool(rows) and all(item.state is SkillState.CURRENT for item in inspection.skills)
    return {"status": "healthy" if healthy else "unhealthy", "rows": rows}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m skills.bootstrap")
    sub = parser.add_subparsers(dest="command", required=True)

    configured = sub.add_parser("configured")
    configured.add_argument("--config", required=True)

    planned = sub.add_parser("plan")
    planned.add_argument("--project-root", required=True)
    planned.add_argument("--skills-dir", required=True)
    planned.add_argument("--config", required=True)
    planned.add_argument("--harness", action="append", default=[])
    planned.add_argument("--environment", action="append", default=[])

    persisted = sub.add_parser("persist")
    persisted.add_argument("--project-root", required=True)
    persisted.add_argument("--config", required=True)
    persisted.add_argument("--template", required=True)
    persisted.add_argument("--harness", action="append", required=True)

    verified = sub.add_parser("verify")
    verified.add_argument("--project-root", required=True)
    verified.add_argument("--skills-dir", required=True)
    verified.add_argument("--catalog-version", required=True)
    verified.add_argument("--harness", action="append", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "configured":
            print("\n".join(configured_harnesses(Path(args.config))))
            return 0
        if args.command == "plan":
            result = plan_initialization(
                args.project_root,
                args.skills_dir,
                explicit=args.harness,
                environment=args.environment,
                config_path=args.config,
            )
            print(json.dumps(asdict(result)))
            return 0
        if args.command == "persist":
            persist_policy(
                args.config,
                args.harness,
                template_path=args.template,
                project_root=args.project_root,
            )
            return 0
        result = verify_installation(
            args.project_root,
            args.skills_dir,
            args.catalog_version,
            args.harness,
        )
        print(json.dumps(result))
        return 0 if result["status"] == "healthy" else 1
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
