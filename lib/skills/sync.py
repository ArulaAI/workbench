"""Sync/status orchestration: detect -> classify -> apply -> rewrite manifest.

This is the only module that writes to disk. Rendering stays pure in project.py;
classification stays pure in manifest.py.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from skills import (
    ABSENT,
    CURRENT,
    STALE,
    CONFLICTED,
    ORPHANED,
    UNSUPPORTED,
    is_valid_skill_name,
)
from skills.catalog import load_catalog
from skills.targets import SURFACES, detect_surfaces, dest_dir, get_surface
from skills.project import render
from skills.events import append_events, new_transaction, now_iso
from skills.manifest import (
    hash_bytes,
    hash_disk,
    load_manifest,
    save_manifest,
    classify_skill,
)


@dataclass
class SkillState:
    surface: str
    skill: str
    state: str
    action: str = ""


def _classify_all(project_root, skills_dir, catalog_version, surfaces):
    pkgs = load_catalog(skills_dir)
    by_name = {p.name: p for p in pkgs}
    manifest = load_manifest(project_root)
    rows: list = []
    plans: list = []  # (surface, skill, state, rendered_or_None, dest, version)
    for surface in surfaces:
        surf_entry = (
            manifest.get("surfaces", {}).get(surface.id, {}).get("skills", {})
        )
        seen = set()
        for name, pkg in by_name.items():
            seen.add(name)
            rendered = render(pkg, surface, catalog_version)
            dest = dest_dir(surface, name, project_root)
            state = classify_skill(rendered, hash_disk(dest), surf_entry.get(name))
            rows.append(SkillState(surface.id, name, state))
            plans.append((surface, name, state, rendered, dest, pkg.meta.get("version")))
        for name, entry in surf_entry.items():
            if name in seen:
                continue
            if not is_valid_skill_name(name):
                # Nothing SPEED wrote can carry this key, so there is no
                # projection to reconcile. Skipping keeps dest_dir out of it.
                continue
            dest = dest_dir(surface, name, project_root)
            if not dest.exists():
                continue
            state = classify_skill(None, hash_disk(dest), entry)
            rows.append(SkillState(surface.id, name, state))
            plans.append((surface, name, state, None, dest, None))
    return rows, plans, manifest


def _prune_unsafe_names(manifest) -> None:
    """Drop manifest entries whose key is not a legal skill name.

    Such an entry cannot describe a projection SPEED made, and leaving it in
    place would keep offering an unusable name to every later sync.
    """
    for surf in manifest.get("surfaces", {}).values():
        skills = surf.get("skills", {})
        for name in [n for n in skills if not is_valid_skill_name(n)]:
            del skills[name]


def _detected(project_root, only_surface):
    if only_surface is not None:
        # Explicit selection is authoritative. Sync can therefore create a
        # missing harness root instead of requiring its marker to pre-exist.
        return [get_surface(only_surface)]
    # A selection made at init time is remembered, so a later bare sync cannot
    # fan out to harnesses the project never opted into.
    recorded = load_manifest(project_root).get("selected_surfaces") or []
    if recorded:
        return [get_surface(item) for item in recorded]
    return [
        s
        for s in detect_surfaces(Path(project_root))
    ]


def _unsupported_rows(only_surface):
    return [
        SkillState(s.id, "*", UNSUPPORTED)
        for s in SURFACES
        if only_surface in (None, s.id)
    ]


def status(project_root, skills_dir, catalog_version, *, only_surface=None):
    surfaces = _detected(project_root, only_surface)
    if not surfaces:
        return _unsupported_rows(only_surface)
    rows, _, _ = _classify_all(
        Path(project_root), Path(skills_dir), catalog_version, surfaces
    )
    return rows


def _persist(project_root, manifest, before, events) -> None:
    """Write the manifest and event log if either has anything new to say.

    Called from a ``finally`` so that a sync which dies part-way still records
    the projections it already wrote. Forgetting them would leave those files
    indistinguishable from hand edits, i.e. permanently ``conflicted``.
    """
    if json.dumps(manifest, sort_keys=True) != before:
        save_manifest(project_root, manifest)
    append_events(project_root, events)


def sync(project_root, skills_dir, catalog_version, *, force=False, only_surface=None):
    project_root = Path(project_root)
    skills_dir = Path(skills_dir)
    surfaces = _detected(project_root, only_surface)
    if not surfaces:
        return _unsupported_rows(only_surface)

    rows, plans, manifest = _classify_all(
        project_root, skills_dir, catalog_version, surfaces
    )
    before = json.dumps(manifest, sort_keys=True)
    manifest.setdefault("surfaces", {})
    _prune_unsafe_names(manifest)

    transaction = new_transaction()
    ts = now_iso()
    events: list = []
    mutated = False

    try:
        for row, (surface, name, state, rendered, dest, version) in zip(rows, plans):
            surf = manifest["surfaces"].setdefault(
                surface.id, {"root": surface.skills_root, "skills": {}}
            )
            prev_version = surf["skills"].get(name, {}).get("version")
            remove = state == ORPHANED or (
                rendered is None and force and state == CONFLICTED
            )
            write = state in (ABSENT, STALE) or (
                state == CONFLICTED and force and rendered is not None
            )
            action = None
            if remove:
                if dest.exists():
                    shutil.rmtree(dest)
                surf["skills"].pop(name, None)
                action = "removed"
                row.state = ABSENT
                version = None
                mutated = True
            elif write:
                if dest.exists():
                    shutil.rmtree(dest)
                for rel, content in rendered.items():
                    target = dest / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                surf["skills"][name] = {
                    "files": {
                        rel: hash_bytes(content) for rel, content in rendered.items()
                    },
                    "projected_at_version": catalog_version,
                    "version": version,
                }
                action = "installed" if state == ABSENT else "updated"
                row.state = CURRENT
                mutated = True
            elif state == CONFLICTED:
                action = "conflict"

            if action is not None:
                row.action = action
                events.append({
                    "transaction": transaction,
                    "ts": ts,
                    "catalog_version": catalog_version,
                    "surface": surface.id,
                    "skill": name,
                    "action": action,
                    "prev_version": prev_version,
                    "new_version": version,
                })

        if only_surface is not None:
            # Accumulate: choosing a second harness must not strand the first
            # one's projection outside the set that status, doctor, and sync
            # can see.
            chosen = {get_surface(only_surface).id}
            chosen |= set(manifest.get("selected_surfaces") or [])
            manifest["selected_surfaces"] = sorted(chosen)
        if mutated:
            # Record the projecting install only when a projection actually
            # changed. Stamping it on every run would make a teammate on a
            # different SPEED build rewrite the committed manifest each sync.
            manifest["catalog_version"] = catalog_version
    finally:
        _persist(project_root, manifest, before, events)
    return rows
