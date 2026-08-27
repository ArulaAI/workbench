"""Sync/status orchestration: detect -> classify -> apply -> rewrite manifest.

This is the only module that writes to disk. Rendering stays pure in project.py;
classification stays pure in manifest.py.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from skills import ABSENT, STALE, CONFLICTED, ORPHANED, UNSUPPORTED
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
            dest = dest_dir(surface, name, project_root)
            if not dest.exists():
                continue
            state = classify_skill(None, hash_disk(dest), entry)
            rows.append(SkillState(surface.id, name, state))
            plans.append((surface, name, state, None, dest, None))
    return rows, plans, manifest


def _detected(project_root, only_surface):
    if only_surface is not None:
        # Explicit selection is authoritative. Sync can therefore create a
        # missing harness root instead of requiring its marker to pre-exist.
        return [get_surface(only_surface)]
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

    transaction = new_transaction()
    ts = now_iso()
    events: list = []

    for surface, name, state, rendered, dest, version in plans:
        surf = manifest["surfaces"].setdefault(
            surface.id, {"root": surface.skills_root, "skills": {}}
        )
        prev_version = surf["skills"].get(name, {}).get("version")
        remove = state == ORPHANED or (
            rendered is None and force and state == CONFLICTED
        )
        write = state in (ABSENT, STALE) or (state == CONFLICTED and force and rendered is not None)
        action = None
        if remove:
            if dest.exists():
                shutil.rmtree(dest)
            surf["skills"].pop(name, None)
            action = "removed"
            version = None
        elif write:
            if dest.exists():
                shutil.rmtree(dest)
            for rel, content in rendered.items():
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            surf["skills"][name] = {
                "files": {rel: hash_bytes(content) for rel, content in rendered.items()},
                "projected_at_version": catalog_version,
                "version": version,
            }
            action = "installed" if state == ABSENT else "updated"
        elif state == CONFLICTED:
            action = "conflict"

        if action is not None:
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

    manifest["catalog_version"] = catalog_version
    after = json.dumps(manifest, sort_keys=True)
    if after != before:
        save_manifest(project_root, manifest)
    append_events(project_root, events)
    return rows
