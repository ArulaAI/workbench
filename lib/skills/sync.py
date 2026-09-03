"""The only writer: plan filesystem operations from an inspection, then apply.

Three steps, each usable on its own:

``plan``   turns a read-only ``Inspection`` plus the ``--force`` choice into a
           list of ``SkillPlan`` operations. Pure: it touches nothing.
``apply``  performs those operations, rewrites the manifest, appends the event
           log, and reports a ``SyncOutcome`` per skill.
``sync``   composes inspect -> plan -> apply for the CLI.

Every projection change in the system originates in ``apply``. The manifest and
the event log are written by ``manifest.py`` and ``events.py``, which only this
module calls.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from skills import is_valid_skill_name
from skills.events import append_events, new_transaction, now_iso
from skills.inspect import inspect
from skills.manifest import (
    HARNESSES_KEY,
    SELECTED_KEY,
    hash_bytes,
    save_manifest,
)
from skills.models import (
    CONFLICT,
    INSTALLED,
    PRESERVE,
    REMOVE,
    REMOVED,
    UPDATED,
    WRITE,
    SkillPlan,
    SkillState,
    SyncOutcome,
)
from skills.targets import get_harness


def _remove_path(path: Path) -> None:
    """Delete whatever occupies a projection path: link, file, or directory."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _write_projection(dest: Path, rendered: dict) -> None:
    """Swap a complete projection into place, never a half-written one.

    Files land in a staging directory beside the destination first. Only once
    every byte is written does the old projection move aside and the staged one
    take its name, so a failure part-way through leaves the skill exactly as it
    was instead of stranding a skill with, say, a SKILL.md and no scripts.

    Renaming also handles the cases where the path holds something else: a
    regular file or a symlink is moved aside untouched, and nothing is ever
    written through a link.
    """
    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    stamp = uuid.uuid4().hex[:8]
    staging = parent / f".{dest.name}.new-{stamp}"
    replaced = parent / f".{dest.name}.old-{stamp}"
    try:
        staging.mkdir()
        for rel, content in rendered.items():
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        if dest.is_symlink() or dest.exists():
            os.rename(dest, replaced)
        try:
            os.rename(staging, dest)
        except BaseException:
            if replaced.is_symlink() or replaced.exists():
                os.rename(replaced, dest)
            raise
    finally:
        if staging.is_symlink() or staging.exists():
            _remove_path(staging)
        # The superseded copy goes only once something occupies the destination
        # again, whether that is the new projection or the restored old one. If
        # both renames failed, it is the sole surviving copy and is left in
        # place under its staging name rather than deleted.
        if (replaced.is_symlink() or replaced.exists()) and (
            dest.is_symlink() or dest.exists()
        ):
            _remove_path(replaced)


def _operation(item, force: bool) -> str | None:
    """Which filesystem operation one inspected skill calls for, if any."""
    orphan = item.rendered is None
    if item.state is SkillState.ORPHANED or (
        orphan and force and item.state is SkillState.CONFLICTED
    ):
        return REMOVE
    if item.state in (SkillState.ABSENT, SkillState.STALE) or (
        item.state is SkillState.CONFLICTED and force and not orphan
    ):
        return WRITE
    if item.state is SkillState.CONFLICTED:
        return PRESERVE
    return None


def plan(inspection, *, force: bool = False) -> list:
    """The operations needed to converge this inspection. Writes nothing."""
    plans: list = []
    for item in inspection.skills:
        operation = _operation(item, force)
        if operation is None:
            continue
        plans.append(
            SkillPlan(
                harness=item.harness,
                skill=item.skill,
                state=item.state,
                operation=operation,
                rendered=item.rendered,
                dest=item.dest,
                version=item.version,
                prev_version=item.prev_version,
            )
        )
    return plans


def _prune_unsafe_names(manifest) -> None:
    """Drop manifest entries whose key is not a legal skill name.

    Such an entry cannot describe a projection Workbench made, and leaving it in
    place would keep offering an unusable name to every later sync.
    """
    for record in manifest.get(HARNESSES_KEY, {}).values():
        skills = record.get("skills", {})
        for name in [n for n in skills if not is_valid_skill_name(n)]:
            del skills[name]


def _persist(project_root, manifest, before, events) -> None:
    """Write the manifest and event log if either has anything new to say.

    Called from a ``finally`` so that a sync which dies part-way still records
    the projections it already wrote. Forgetting them would leave those files
    indistinguishable from hand edits, i.e. permanently ``conflicted``.
    """
    if json.dumps(manifest, sort_keys=True) != before:
        save_manifest(project_root, manifest)
    append_events(project_root, events)


def apply(inspection, plans, *, only_harness=None) -> list:
    """Perform ``plans``, record what happened, and report where each skill ended.

    Returns one ``SyncOutcome`` per inspected skill, including the untouched
    ones, so the caller's table and exit code describe the project after the run
    rather than the classification it started from.
    """
    project_root = Path(inspection.project_root)
    catalog_version = inspection.catalog_version
    manifest = inspection.manifest
    before = json.dumps(manifest, sort_keys=True)
    manifest.setdefault(HARNESSES_KEY, {})
    _prune_unsafe_names(manifest)

    by_key = {(p.harness, p.skill): p for p in plans}
    transaction = new_transaction()
    ts = now_iso()
    events: list = []
    outcomes: list = []
    mutated = False

    try:
        for item in inspection.skills:
            outcome = SyncOutcome(
                harness=item.harness,
                skill=item.skill,
                previous_state=item.state,
                action="",
                final_state=item.state,
            )
            outcomes.append(outcome)
            step = by_key.get((item.harness, item.skill))
            if step is None:
                continue

            harness = get_harness(item.harness)
            record = manifest[HARNESSES_KEY].setdefault(
                harness.id, {"root": harness.skills_root, "skills": {}}
            )
            version = step.version
            if step.operation == REMOVE:
                if step.dest.is_symlink() or step.dest.exists():
                    _remove_path(step.dest)
                record["skills"].pop(item.skill, None)
                outcome.action = REMOVED
                outcome.final_state = SkillState.ABSENT
                version = None
                mutated = True
            elif step.operation == WRITE:
                _write_projection(step.dest, step.rendered)
                record["skills"][item.skill] = {
                    "files": {
                        rel: hash_bytes(content)
                        for rel, content in step.rendered.items()
                    },
                    "projected_at_version": catalog_version,
                    "version": version,
                }
                outcome.action = (
                    INSTALLED if step.state is SkillState.ABSENT else UPDATED
                )
                outcome.final_state = SkillState.CURRENT
                mutated = True
            else:
                outcome.action = CONFLICT
                outcome.final_state = SkillState.CONFLICTED
                # Nothing was installed, so the catalog's version has no place
                # in the record: a reader must not see a version bump that
                # never happened.
                version = None

            events.append({
                "transaction": transaction,
                "ts": ts,
                "catalog_version": catalog_version,
                "harness": item.harness,
                "skill": item.skill,
                "action": outcome.action,
                "prev_version": step.prev_version,
                "new_version": version,
            })

        if only_harness is not None:
            # Accumulate: choosing a second harness must not strand the first
            # one's projection outside the set that status, doctor, and sync
            # can see.
            chosen = {get_harness(only_harness).id}
            chosen |= set(manifest.get(SELECTED_KEY) or [])
            manifest[SELECTED_KEY] = sorted(chosen)
        if mutated:
            # Record the projecting install only when a projection actually
            # changed. Stamping it on every run would make a teammate on a
            # different Workbench build rewrite the committed manifest each sync.
            manifest["catalog_version"] = catalog_version
    finally:
        _persist(project_root, manifest, before, events)
    return outcomes


def sync(project_root, skills_dir, catalog_version, *, force=False, only_harness=None) -> list:
    """Converge this project's projections, and report where each skill ended."""
    inspection = inspect(
        project_root, skills_dir, catalog_version, only_harness=only_harness
    )
    if not inspection.supported:
        return [
            SyncOutcome(
                harness=item.harness,
                skill=item.skill,
                previous_state=item.state,
                action="",
                final_state=item.state,
            )
            for item in inspection.skills
        ]
    return apply(inspection, plan(inspection, force=force), only_harness=only_harness)
