"""Managed-file identity: hashing, manifest persistence, and state classification.

The manifest records the hash of each file as Workbench last projected it.
Matching hashes are evidence that a projection is unchanged since then, which is
the only reliable way to tell a managed file from a user edit and what keeps sync
from clobbering local changes.

Because that record is the sole authority for "this may be overwritten", it is
read and written defensively: the file is committed, so a bad merge or a hand
edit reaches this module as untrusted input, and a half-written manifest would
make every projection look hand-edited forever.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from skills.frontmatter import MANAGED_PREFIX
from skills import PATHS, ABSENT, CURRENT, STALE, CONFLICTED, ORPHANED, is_junk


# Manifest presence, for callers that need to tell a first run apart from a
# record that went missing under existing projections.
MANIFEST_NEW = "new"
MANIFEST_PRESENT = "present"
MANIFEST_LOST = "lost"


class _WrongType:
    """Marker for a projection path holding something Workbench could not have written.

    Returned instead of a hash map so that a regular file, a symlink, or a tree
    containing one is never confused with an empty directory, which is what
    ``absent`` means and what licenses sync to write.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<wrong-type>"


WRONG_TYPE = _WrongType()


def hash_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def hash_disk(dest: Path):
    """Hash a projection, or return ``WRONG_TYPE`` if the path is not one.

    Walks with ``followlinks=False`` and rejects every symlink it meets. A
    projection contains copied bytes only, so a link inside one was not written
    by Workbench, and hashing through it would read a file outside the managed
    directory and then report the result as the skill's own state.
    """
    dest = Path(dest)
    if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
        return WRONG_TYPE
    if not dest.is_dir():
        return {}
    out: dict = {}
    for dirpath, dirnames, filenames in os.walk(dest, followlinks=False):
        here = Path(dirpath)
        for name in list(dirnames):
            if (here / name).is_symlink():
                return WRONG_TYPE
        for name in filenames:
            path = here / name
            if path.is_symlink():
                return WRONG_TYPE
            rel = path.relative_to(dest).as_posix()
            # Same exclusions the catalog reader applies, so a Finder visit or a
            # stray __pycache__ cannot be mistaken for a hand edit.
            if is_junk(rel):
                continue
            out[rel] = hash_bytes(path.read_bytes())
    return dict(sorted(out.items()))


def _fail(path: Path, where: str, message: str):
    raise ValueError(f"invalid skill manifest ({path}): {where}: {message}")


def _check_files(path: Path, where: str, files) -> None:
    if not isinstance(files, dict):
        _fail(path, where, "expected an object of relative path -> hash")
    for rel, digest in files.items():
        if not isinstance(digest, str):
            _fail(path, f"{where}.{rel}", "expected a hash string")


def _check_surface(path: Path, where: str, surface) -> None:
    if not isinstance(surface, dict):
        _fail(path, where, "expected an object")
    if "root" in surface and not isinstance(surface["root"], str):
        _fail(path, f"{where}.root", "expected a string")
    skills = surface.get("skills", {})
    if not isinstance(skills, dict):
        _fail(path, f"{where}.skills", "expected an object of skill name -> record")
    for name, entry in skills.items():
        if not isinstance(entry, dict):
            _fail(path, f"{where}.skills.{name}", "expected an object")
        if "files" in entry:
            _check_files(path, f"{where}.skills.{name}.files", entry["files"])


def validate_manifest(path: Path, data) -> dict:
    """Reject a manifest sync cannot classify against, naming where it broke.

    Every level below is walked before classification starts. Left unchecked, a
    ``null`` or a list one level down surfaces later as an ``AttributeError``
    from deep inside sync, which tells the user nothing about the file they need
    to repair.
    """
    if not isinstance(data, dict):
        _fail(path, "document root", "expected an object")
    if "catalog_version" in data and not isinstance(
        data["catalog_version"], (str, type(None))
    ):
        _fail(path, "catalog_version", "expected a string or null")
    selected = data.get("selected_surfaces")
    if selected is not None:
        if not isinstance(selected, list):
            _fail(path, "selected_surfaces", "expected a list of surface ids")
        for index, item in enumerate(selected):
            if not isinstance(item, str):
                _fail(path, f"selected_surfaces[{index}]", "expected a surface id")
    surfaces = data.get("surfaces", {})
    if not isinstance(surfaces, dict):
        _fail(path, "surfaces", "expected an object of surface id -> record")
    for surface_id, surface in surfaces.items():
        _check_surface(path, f"surfaces.{surface_id}", surface)
    return data


def load_manifest(project_root: Path) -> dict:
    path = Path(project_root) / PATHS.manifest
    if not path.exists():
        return {"catalog_version": None, "surfaces": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid skill manifest ({path}): {exc}") from exc
    return validate_manifest(path, data)


def _carries_provenance(skill_dir: Path) -> bool:
    """True when this directory's SKILL.md was stamped by a Workbench projection.

    A harness skills root also holds skills the user wrote themselves. Counting
    those as a lost projection would tell someone their manifest went missing
    when Workbench never wrote anything there. The provenance key exists for
    exactly this question, so it is what gets asked, rather than the presence of
    a directory.
    """
    skill_md = skill_dir / "SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    prefix = f"{MANAGED_PREFIX}managed"
    return any(line.startswith(prefix) for line in text.splitlines())


def manifest_state(project_root: Path) -> str:
    """Report whether the manifest is present, new, or lost.

    ``new`` and ``lost`` both mean "no manifest", and the difference decides what
    a user should be told. With projections already on disk and no record of who
    wrote them, every skill classifies as ``conflicted`` and only ``--force``
    clears it, so a diagnostic that says the record went missing saves a long
    hunt for the edit nobody made.
    """
    project_root = Path(project_root)
    if (project_root / PATHS.manifest).exists():
        return MANIFEST_PRESENT
    # Imported here rather than at module scope: targets pulls in the surface
    # table, and only this function needs it.
    from skills.targets import SURFACES

    for surface in SURFACES:
        root = project_root / surface.skills_root
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir() and _carries_provenance(child):
                return MANIFEST_LOST
    return MANIFEST_NEW


def save_manifest(project_root: Path, data: dict) -> None:
    """Write the manifest atomically, so an interrupted run cannot truncate it.

    A half-written manifest is worse than a stale one: the file is what proves a
    projected byte is unchanged, and losing it downgrades every managed skill
    to ``conflicted`` until someone forces a rewrite.
    """
    path = Path(project_root) / PATHS.manifest
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".manifest-", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        # The rename never happened, so the previous manifest is still the one
        # on disk. Clear the staging file rather than leaving litter beside it.
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _rendered_hashes(rendered: dict) -> dict:
    return {k: hash_bytes(v) for k, v in rendered.items()}


def classify_skill(rendered, disk, entry) -> str:
    """Return one of ABSENT/CURRENT/STALE/CONFLICTED/ORPHANED.

    rendered: relpath->bytes of the would-be projection, or None if the skill is
              no longer in the catalog (orphan candidate).
    disk:     relpath->hash currently on disk, or WRONG_TYPE when the path holds
              something a projection never could.
    entry:    the manifest record for this (surface, skill), or None.
    """
    if disk is WRONG_TYPE:
        # A file, a symlink, or a projection with a link inside it. Whatever it
        # is, Workbench did not write it, so report the collision and let the user
        # decide instead of quietly writing over it.
        return CONFLICTED
    recorded = (entry or {}).get("files", {})
    if rendered is None:
        if not disk:
            # The skill left the catalog and its projection is already gone. The
            # manifest still names it, so treat the record itself as the orphan:
            # sync drops the entry and the manifest converges.
            return ORPHANED
        return ORPHANED if disk == recorded else CONFLICTED
    if entry is None:
        return ABSENT if not disk else CONFLICTED
    if not disk:
        # The projection is gone entirely (git clean, an ignored harness root,
        # a manual delete). There are no local edits to preserve, so re-project
        # rather than demand --force to restore files nobody touched.
        return ABSENT
    if disk != recorded:
        return CONFLICTED
    return CURRENT if _rendered_hashes(rendered) == recorded else STALE
