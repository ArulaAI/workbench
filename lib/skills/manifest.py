"""Managed-file identity: hashing, manifest persistence, and state classification.

The manifest records the hash of each file *as SPEED wrote it*. Comparing the
recomputed on-disk hash against that record is the only reliable way to tell a
SPEED-managed file from a user edit, which is what keeps sync from clobbering
local changes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from skills import ABSENT, CURRENT, STALE, CONFLICTED, ORPHANED

_MANIFEST_REL = ".speed/skills/manifest.json"


def hash_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def hash_disk(dest: Path) -> dict:
    dest = Path(dest)
    out: dict = {}
    if not dest.is_dir():
        return out
    for p in sorted(dest.rglob("*")):
        if p.is_file():
            out[p.relative_to(dest).as_posix()] = hash_bytes(p.read_bytes())
    return out


def load_manifest(project_root: Path) -> dict:
    path = Path(project_root) / _MANIFEST_REL
    if path.exists():
        return json.loads(path.read_text())
    return {"catalog_version": None, "surfaces": {}}


def save_manifest(project_root: Path, data: dict) -> None:
    path = Path(project_root) / _MANIFEST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _rendered_hashes(rendered: dict) -> dict:
    return {k: hash_bytes(v) for k, v in rendered.items()}


def classify_skill(rendered, disk: dict, entry) -> str:
    """Return one of ABSENT/CURRENT/STALE/CONFLICTED/ORPHANED.

    rendered: relpath->bytes of the would-be projection, or None if the skill is
              no longer in the catalog (orphan candidate).
    disk:     relpath->hash currently on disk.
    entry:    the manifest record for this (surface, skill), or None.
    """
    recorded = (entry or {}).get("files", {})
    if rendered is None:
        if not disk:
            return CURRENT  # nothing on disk; caller skips it
        return ORPHANED if disk == recorded else CONFLICTED
    if entry is None:
        return ABSENT if not disk else CONFLICTED
    if disk != recorded:
        return CONFLICTED
    return CURRENT if _rendered_hashes(rendered) == recorded else STALE
