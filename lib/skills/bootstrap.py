"""Initialization policy for the Workbench skill lifecycle.

This module owns the decisions that used to be spread across project.sh,
skills.sh, the manifest, and marker detection.  It is intentionally small: the
project initializer still owns the general SPEED scaffold, while this module
inspects skill state, resolves one harness policy, persists that policy,
verifies the resulting projections, and reconciles the Git ignore policy that
decides which of those files git carries.

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

from skills import PATHS
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


def _atomic_write(path: Path, text: str) -> None:
    """Replace a file in one step, so no reader ever sees a partial write."""
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


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
        _atomic_write(config_path, updated)

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


# ── Git ignore policy ────────────────────────────────────────────
#
# Each ignore file Workbench maintains holds exactly one delimited block that
# Workbench rewrites whole. Appending rules one at a time cannot retire one,
# and a header comment is no evidence that the rules beneath it are current: a
# project initialized before a rule existed already carries the header, so the
# rule would never reach it. That was the bug. Rewriting the block converges on
# additions, edits, and removals alike.
#
# The version in the begin marker is what lets a later Workbench recognize a
# block an earlier one wrote: the finder matches any version, the renderer
# always emits the current one. Detecting a change needs nothing cleverer than
# comparing the rendered file to the file on disk.

MANAGED_VERSION = 1
MANAGED_BEGIN = f"# >>> workbench managed (v{MANAGED_VERSION}) >>>"
MANAGED_END = "# <<< workbench managed <<<"
_BEGIN_RE = re.compile(r"^#\s*>>>\s*workbench managed \(v\d+\)\s*>>>$")
_END_RE = re.compile(r"^#\s*<<<\s*workbench managed\s*<<<$")

_HANDS_OFF = (
    "# Workbench rewrites every line between these markers.",
    "# Rules outside the block are yours and are left untouched.",
)

# Both ignore files describe one state layout from two directories, so the
# paths come from SkillPaths instead of being restated per file.
_STATE_DIR = PATHS.state_root.parent
_SPEED = _STATE_DIR.as_posix()


def _under_state_dir(path) -> str:
    """A canonical path rewritten relative to `.speed/`, for `.speed/.gitignore`."""
    return Path(path).relative_to(_STATE_DIR).as_posix()


_PROJECT_RULES = (
    *_HANDS_OFF,
    f"{_SPEED}/logs/",
    f"{_SPEED}/features/*/logs/",
    f"{_SPEED}/features/*/state.json",
    f"{_SPEED}/features/*/failure_history.jsonl",
    f"{_SPEED}/active_feature",
    f"{_SPEED}/state.json",
    f"{_SPEED}/running/",
    f"{_SPEED}/worktrees/",
    "",
    "# The manifest is the only record of which bytes Workbench wrote, so git",
    "# carries it alongside the projections it describes. The event log is",
    "# per-machine history that no classification reads.",
    f"!{PATHS.state_root.as_posix()}/",
    f"!{PATHS.manifest.as_posix()}",
    PATHS.events.as_posix(),
)

_STATE_RULES = (
    *_HANDS_OFF,
    "# Multi-player mode: shared/ and the skill manifest are committed;",
    f"# everything else under {_SPEED}/ belongs to this machine.",
    "*",
    "!shared/",
    "!shared/**",
    "!.gitignore",
    f"!{_under_state_dir(PATHS.state_root)}/",
    f"!{_under_state_dir(PATHS.manifest)}",
    _under_state_dir(PATHS.events),
)


def _rules_only(rules) -> frozenset:
    return frozenset(rule for rule in rules if rule and not rule.startswith("#"))


@dataclass(frozen=True)
class IgnorePolicy:
    """One ignore file, maintained as a single delimited block.

    `legacy_headers` and `legacy_rules` describe the loose blocks earlier
    Workbench versions appended. Migration removes a run of `legacy_rules` only
    when it starts at a `legacy_headers` comment Workbench itself wrote and
    stops at the first line it did not, which is why a user's rules can never
    become candidates for removal. Every legacy rule is either still in `rules`
    or deliberately retired, so nothing is dropped that the block does not
    restore.
    """

    relpath: str
    rules: tuple
    legacy_headers: frozenset
    legacy_rules: frozenset


IGNORE_POLICIES = {
    "project": IgnorePolicy(
        relpath=".gitignore",
        rules=_PROJECT_RULES,
        legacy_headers=frozenset(
            {"# SPEED runtime state", "# Workbench skill state policy v2"}
        ),
        # `.speed/skills/` is the retired one: ignoring the directory wholesale
        # took the manifest with it, which is what left fresh clones reporting
        # every projected skill as conflicted.
        legacy_rules=_rules_only(_PROJECT_RULES)
        | {f"{PATHS.state_root.as_posix()}/"},
    ),
    "state": IgnorePolicy(
        relpath=f"{_SPEED}/.gitignore",
        rules=_STATE_RULES,
        legacy_headers=frozenset(
            {
                "# Multi-player mode: only shared/ is committed, "
                "everything else is local",
                "# Multi-player mode: only shared/ and the skill manifest are "
                "committed, everything else is local",
            }
        ),
        legacy_rules=_rules_only(_STATE_RULES),
    ),
}


def render_ignore_block(policy) -> tuple:
    """The complete managed block, markers included, as lines."""
    return (MANAGED_BEGIN, *policy.rules, MANAGED_END)


def _managed_spans(lines) -> list:
    """Locate every managed block as an inclusive (begin, end) line pair."""
    spans = []
    index = 0
    while index < len(lines):
        if _BEGIN_RE.match(lines[index].strip()):
            for end in range(index + 1, len(lines)):
                if _END_RE.match(lines[end].strip()):
                    spans.append((index, end))
                    index = end
                    break
            else:
                raise ValueError(
                    f"the managed block opened on line {index + 1} has no "
                    f"closing '{MANAGED_END}' marker, so Workbench cannot tell "
                    "where its own rules end; restore the marker or delete the "
                    "whole block"
                )
        index += 1
    return spans


def _without_managed(lines) -> list:
    kept = []
    cursor = 0
    for start, end in _managed_spans(lines):
        kept.extend(lines[cursor:start])
        cursor = end + 1
    kept.extend(lines[cursor:])
    return kept


def _without_legacy(lines, policy) -> list:
    kept = []
    index = 0
    while index < len(lines):
        if lines[index].strip() not in policy.legacy_headers:
            kept.append(lines[index])
            index += 1
            continue
        index += 1
        while index < len(lines) and lines[index].strip() in policy.legacy_rules:
            index += 1
        # Those blocks were appended after a blank separator line of their own.
        if kept and not kept[-1].strip():
            kept.pop()
    return kept


def reconcile_ignore(project_root, scope) -> bool:
    """Bring one ignore file's managed block up to date.

    Returns True when the file changed. An already-current block is left
    byte-identical rather than rewritten, so a repeated init does not dirty a
    clean working tree.
    """
    if scope not in IGNORE_POLICIES:
        expected = ", ".join(sorted(IGNORE_POLICIES))
        raise ValueError(f"unknown ignore scope '{scope}' (expected: {expected})")
    policy = IGNORE_POLICIES[scope]
    path = Path(project_root) / policy.relpath
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    body = original[:-1] if original.endswith("\n") else original
    lines = body.split("\n") if body else []
    block = list(render_ignore_block(policy))

    spans = _managed_spans(lines)
    if spans:
        # Replace the first block where it sits and drop any later duplicate,
        # so a version bump cannot leave two generations of rules behind.
        start, end = spans[0]
        prefix = _without_legacy(lines[:start], policy)
        suffix = _without_legacy(_without_managed(lines[end + 1:]), policy)
        result = [*prefix, *block, *suffix]
    else:
        prefix = _without_legacy(lines, policy)
        if prefix and prefix[-1].strip():
            # Separate the region from the last rule, but only when the file
            # does not already end in blank lines the user put there.
            prefix.append("")
        result = [*prefix, *block]

    updated = "\n".join(result) + "\n"
    if updated == original:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, updated)
    return True


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

    ignored = sub.add_parser("ignore")
    ignored.add_argument("--project-root", required=True)
    ignored.add_argument("--scope", required=True, choices=sorted(IGNORE_POLICIES))
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
        if args.command == "ignore":
            # The caller logs the outcome, so say which one it was on stdout
            # rather than through the exit status, which is reserved for
            # reporting that the policy could not be applied at all.
            changed = reconcile_ignore(args.project_root, args.scope)
            print("changed" if changed else "unchanged")
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
