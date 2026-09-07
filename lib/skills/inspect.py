"""Read-only inspection: what is installed, and what the catalog says it should be.

This module answers every question ``status`` and ``doctor`` ask, and it writes
nothing. Sync plans from the ``Inspection`` it returns rather than repeating the
work, which is what removed the old arrangement where a read-only command built
a set of filesystem mutations and then threw them away.

Nothing here imports ``sync``. That is the point: the read path cannot reach the
write path even by accident.
"""
from __future__ import annotations

from pathlib import Path

from skills import is_valid_skill_name
from skills.catalog import load_catalog
from skills.manifest import (
    SELECTED_KEY,
    hash_disk,
    inspect_skill,
    load_manifest,
    manifest_state,
    recorded_skills,
)
from skills.models import (
    HARNESSES,
    Finding,
    HARNESS_UNSUPPORTED,
    Inspection,
    SkillInspection,
    SkillState,
)
from skills.project import render
from skills.targets import dest_dir, detect_harnesses, get_harness


def resolve_harnesses(project_root, only_harness=None) -> list:
    """The harnesses a command should act on, in precedence order.

    An explicit flag wins, because sync can create a harness root the project
    does not have yet. Otherwise a selection recorded at init time is honored,
    so a later bare sync cannot fan out to harnesses the project never opted
    into. Detection is the last resort.
    """
    if only_harness is not None:
        selected = (
            [only_harness] if isinstance(only_harness, str) else list(only_harness)
        )
        return [get_harness(item) for item in selected]
    recorded = load_manifest(project_root).get(SELECTED_KEY) or []
    if recorded:
        return [get_harness(item) for item in recorded]
    return detect_harnesses(Path(project_root))


def _unsupported(only_harness) -> list:
    selected = (
        None
        if only_harness is None
        else {only_harness}
        if isinstance(only_harness, str)
        else set(only_harness)
    )
    return [
        SkillInspection(
            harness=h.id,
            skill="*",
            state=SkillState.UNSUPPORTED,
            findings=[Finding(HARNESS_UNSUPPORTED)],
        )
        for h in HARNESSES
        if selected is None or h.id in selected
    ]


def inspect(project_root, skills_dir, catalog_version, *, only_harness=None) -> Inspection:
    """Assemble the full read-only picture of this project's projections."""
    project_root = Path(project_root)
    harnesses = resolve_harnesses(project_root, only_harness)
    if not harnesses:
        return Inspection(
            project_root=project_root,
            catalog_version=catalog_version,
            manifest={},
            manifest_state=manifest_state(project_root),
            harnesses=[],
            skills=_unsupported(only_harness),
        )

    packages = {p.name: p for p in load_catalog(Path(skills_dir))}
    manifest = load_manifest(project_root)
    rows: list = []
    for harness in harnesses:
        recorded = recorded_skills(manifest, harness.id)
        for name, pkg in packages.items():
            rendered = render(pkg, harness, catalog_version)
            dest = dest_dir(harness, name, project_root)
            entry = recorded.get(name)
            state, findings = inspect_skill(rendered, hash_disk(dest), entry)
            rows.append(
                SkillInspection(
                    harness=harness.id,
                    skill=name,
                    state=state,
                    findings=findings,
                    rendered=rendered,
                    dest=dest,
                    version=pkg.meta.get("version"),
                    prev_version=(entry or {}).get("version"),
                )
            )
        for name, entry in recorded.items():
            if name in packages:
                continue
            if not is_valid_skill_name(name):
                # Nothing Workbench wrote can carry this key, so there is no
                # projection to reconcile. Skipping keeps dest_dir out of it;
                # sync prunes the record separately.
                continue
            dest = dest_dir(harness, name, project_root)
            # An entry whose projection is already gone still gets a row. Left
            # out, a skill that has both left the catalog and lost its files
            # would keep its manifest record for good, and the manifest would
            # never converge on what is actually installed.
            state, findings = inspect_skill(None, hash_disk(dest), entry)
            rows.append(
                SkillInspection(
                    harness=harness.id,
                    skill=name,
                    state=state,
                    findings=findings,
                    rendered=None,
                    dest=dest,
                    version=None,
                    prev_version=(entry or {}).get("version"),
                )
            )
    return Inspection(
        project_root=project_root,
        catalog_version=catalog_version,
        manifest=manifest,
        manifest_state=manifest_state(project_root),
        harnesses=list(harnesses),
        skills=rows,
    )
