"""Managed-file identity: hashing, manifest persistence, and classification.

The manifest records the hash of each file as Workbench last projected it.
Matching hashes are evidence that a projection is unchanged since then, which is
the only reliable way to tell a managed file from a user edit and what keeps sync
from clobbering local changes.

Because that record is the sole authority for "this may be overwritten", it is
read and written defensively: the file is committed, so a bad merge or a hand
edit reaches this module as untrusted input, and a half-written manifest would
make every projection look hand-edited forever.

Classification returns findings alongside the state. A state tells sync what to
do; the findings carry the comparison it was decided from, so doctor can show
the user which file differs and how instead of restating the state in prose.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:  # POSIX only; Workbench ships for macOS and Linux.
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

from skills import PATHS, is_junk
from skills.frontmatter import MANAGED_PREFIX
from skills.models import (
    MANIFEST_RECORD_MISSING,
    ORPHANED_PROJECTION,
    ORPHANED_PROJECTION_MODIFIED,
    ORPHANED_RECORD,
    PROJECTED_FILE_MISSING,
    PROJECTED_FILE_MODIFIED,
    PROJECTED_FILE_UNEXPECTED,
    PROJECTION_MISSING,
    PROJECTION_OUTDATED,
    PROJECTION_PATH_OCCUPIED,
    PROJECTION_SYMLINK,
    Finding,
    SkillState,
)

# Manifest presence, for callers that need to tell a first run apart from a
# record that went missing under existing projections.
MANIFEST_NEW = "new"
MANIFEST_PRESENT = "present"
MANIFEST_LOST = "lost"

# Top-level manifest keys. Named once so a rename cannot half-land.
HARNESSES_KEY = "harnesses"
SELECTED_KEY = "selected_harnesses"


@dataclass(frozen=True)
class WrongType:
    """A projection path holding something Workbench could not have written.

    Returned instead of a hash map so that a regular file, a symlink, or a tree
    containing one is never confused with an empty directory, which is what
    ``absent`` means and what licenses sync to write. ``kind`` and ``path`` are
    the evidence a diagnostic needs to name what is actually in the way.
    """

    kind: str  # "occupied" | "symlink"
    path: str | None = None

    def __bool__(self) -> bool:  # pragma: no cover - guards a truthiness bug
        # `not disk` must never read as "nothing on disk" for a wrong type.
        return True


def hash_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def hash_disk(dest: Path):
    """Hash a projection, or return a ``WrongType`` if the path is not one.

    Walks with ``followlinks=False`` and rejects every symlink it meets. A
    projection contains copied bytes only, so a link inside one was not written
    by Workbench, and hashing through it would read a file outside the managed
    directory and then report the result as the skill's own state.

    Junk is discarded before anything is tested for link-ness, matching the
    catalog reader entry for entry. Excluding it only from the hash was not
    enough: a Finder-synced ``.DS_Store`` alias landing beside a projection
    would condemn the skill as ``conflicted`` and demand ``--force``, even
    though the same file as a regular file is ignored outright.
    """
    dest = Path(dest)
    if dest.is_symlink():
        return WrongType("symlink")
    if dest.exists() and not dest.is_dir():
        return WrongType("occupied")
    if not dest.is_dir():
        return {}
    out: dict = {}
    for dirpath, dirnames, filenames in os.walk(dest, followlinks=False):
        here = Path(dirpath)
        kept: list = []
        for name in sorted(dirnames):
            rel = (here / name).relative_to(dest).as_posix()
            if is_junk(rel):
                continue
            if (here / name).is_symlink():
                return WrongType("symlink", rel)
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = here / name
            rel = path.relative_to(dest).as_posix()
            if is_junk(rel):
                continue
            if path.is_symlink():
                return WrongType("symlink", rel)
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


def _check_harness(path: Path, where: str, harness) -> None:
    if not isinstance(harness, dict):
        _fail(path, where, "expected an object")
    if "root" in harness and not isinstance(harness["root"], str):
        _fail(path, f"{where}.root", "expected a string")
    skills = harness.get("skills", {})
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
    selected = data.get(SELECTED_KEY)
    if selected is not None:
        if not isinstance(selected, list):
            _fail(path, SELECTED_KEY, "expected a list of harness ids")
        for index, item in enumerate(selected):
            if not isinstance(item, str):
                _fail(path, f"{SELECTED_KEY}[{index}]", "expected a harness id")
    harnesses = data.get(HARNESSES_KEY, {})
    if not isinstance(harnesses, dict):
        _fail(path, HARNESSES_KEY, "expected an object of harness id -> record")
    for harness_id, harness in harnesses.items():
        _check_harness(path, f"{HARNESSES_KEY}.{harness_id}", harness)
    return data


def load_manifest(project_root: Path) -> dict:
    path = Path(project_root) / PATHS.manifest
    if not path.exists():
        return {"catalog_version": None, HARNESSES_KEY: {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid skill manifest ({path}): {exc}") from exc
    return validate_manifest(path, data)


def recorded_skills(manifest: dict, harness_id: str) -> dict:
    """The manifest's skill records for one harness, or an empty mapping."""
    return manifest.get(HARNESSES_KEY, {}).get(harness_id, {}).get("skills", {})


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
    from skills.models import HARNESSES

    for harness in HARNESSES:
        root = project_root / harness.skills_root
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir() and _carries_provenance(child):
                return MANIFEST_LOST
    return MANIFEST_NEW


@contextlib.contextmanager
def sync_lock(project_root):
    """Serialize one project's manifest read-modify-write across processes.

    A sync loads the manifest, decides what to write from it, and saves it back.
    Two syncs that both load before either saves each hold a copy that predates
    the other's work, and the second save replaces the first wholesale: the
    projections land on disk correctly, but one harness's records vanish from
    the record that licenses overwriting them. Every skill it described then
    classifies ``conflicted``, and clearing that needs ``--force`` on files
    nobody touched.

    The window spans the whole sync, so the lock is taken before the load and
    dropped after the save rather than wrapped around the write. Read-only
    commands do not take it: ``save_manifest`` swaps the file atomically, so a
    reader sees one version or the other and never a blend.

    Locking here rather than in the shell wrapper covers every entrance,
    including ``python -m skills``, and avoids contending with the SPEED
    project lock that ``init`` already holds while it calls sync.
    """
    path = Path(project_root) / PATHS.lock
    path.parent.mkdir(parents=True, exist_ok=True)
    # "a" so the descriptor exists to be locked without truncating a rival's
    # file; nothing is ever written to it. Closing would release the lock on
    # its own, and it is dropped explicitly to keep the pairing visible.
    with path.open("a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


def _file_findings(recorded: dict, disk: dict) -> list:
    """One finding per file that differs between the record and the disk."""
    out: list = []
    for rel in sorted(recorded):
        if rel not in disk:
            out.append(Finding(PROJECTED_FILE_MISSING, rel, recorded[rel], None))
        elif disk[rel] != recorded[rel]:
            out.append(
                Finding(PROJECTED_FILE_MODIFIED, rel, recorded[rel], disk[rel])
            )
    for rel in sorted(set(disk) - set(recorded)):
        out.append(Finding(PROJECTED_FILE_UNEXPECTED, rel, None, disk[rel]))
    return out


def _wrong_type_finding(disk: WrongType) -> Finding:
    code = PROJECTION_SYMLINK if disk.kind == "symlink" else PROJECTION_PATH_OCCUPIED
    return Finding(code, disk.path)


def inspect_skill(rendered, disk, entry) -> tuple:
    """Return ``(state, findings)`` for one (harness, skill) pair.

    rendered: relpath->bytes of the would-be projection, or None if the skill is
              no longer in the catalog (orphan candidate).
    disk:     relpath->hash currently on disk, or a ``WrongType`` when the path
              holds something a projection never could.
    entry:    the manifest record for this pair, or None.
    """
    if isinstance(disk, WrongType):
        # A file, a symlink, or a projection with a link inside it. Whatever it
        # is, Workbench did not write it, so report the collision and let the
        # user decide instead of quietly writing over it.
        return SkillState.CONFLICTED, [_wrong_type_finding(disk)]

    recorded = (entry or {}).get("files", {})

    if rendered is None:
        if not disk:
            # The skill left the catalog and its projection is already gone. The
            # manifest still names it, so treat the record itself as the orphan:
            # sync drops the entry and the manifest converges.
            return SkillState.ORPHANED, [Finding(ORPHANED_RECORD)]
        if disk == recorded:
            return SkillState.ORPHANED, [Finding(ORPHANED_PROJECTION)]
        return SkillState.CONFLICTED, [
            Finding(ORPHANED_PROJECTION_MODIFIED),
            *_file_findings(recorded, disk),
        ]

    if entry is None:
        if not disk:
            return SkillState.ABSENT, [Finding(PROJECTION_MISSING)]
        # Files are there with nothing recording who wrote them.
        return SkillState.CONFLICTED, [
            Finding(MANIFEST_RECORD_MISSING, rel, None, digest)
            for rel, digest in sorted(disk.items())
        ]

    if not disk:
        # The projection is gone entirely (git clean, an ignored harness root,
        # a manual delete). There are no local edits to preserve, so re-project
        # rather than demand --force to restore files nobody touched.
        return SkillState.ABSENT, [Finding(PROJECTION_MISSING)]

    if disk != recorded:
        return SkillState.CONFLICTED, _file_findings(recorded, disk)

    wanted = _rendered_hashes(rendered)
    if wanted == recorded:
        return SkillState.CURRENT, []
    findings = [
        Finding(PROJECTION_OUTDATED, rel, wanted.get(rel), recorded.get(rel))
        for rel in sorted(set(wanted) | set(recorded))
        if wanted.get(rel) != recorded.get(rel)
    ]
    return SkillState.STALE, findings


def classify_skill(rendered, disk, entry) -> SkillState:
    """The state-only view of ``inspect_skill``, for callers ignoring evidence."""
    state, _ = inspect_skill(rendered, disk, entry)
    return state
