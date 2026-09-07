"""Harness lookup, explicit selection, and marker-based detection.

The registry itself lives in ``models`` so that every consumer, including the
Bash commands which query it through ``python -m skills harnesses``, reads one
list. This module is the policy on top of it: which harnesses a project has,
which one the user asked for, and where a skill is allowed to be written.
"""
from __future__ import annotations

from pathlib import Path

from skills import is_valid_skill_name
from skills.models import HARNESSES, Harness


def _real_dir(project_root: Path, marker: str):
    """The marker directory, or None if reaching it crosses a symlink.

    ``is_dir()`` follows links, so a ``.claude`` pointing anywhere at all would
    otherwise read as a detected harness and licence sync to write through it.
    Every component is checked, because the escape can sit on a parent
    (``.github`` -> /elsewhere) as easily as on the marker itself.
    """
    path = Path(project_root)
    for part in marker.split("/"):
        path = path / part
        if path.is_symlink():
            return None
    return path if path.is_dir() else None


def detect_harnesses(project_root: Path) -> list:
    project_root = Path(project_root)
    return [h for h in HARNESSES if _real_dir(project_root, h.marker) is not None]


def get_harness(harness_id: str) -> Harness:
    normalized = (harness_id or "").strip().lower()
    for harness in HARNESSES:
        if normalized == harness.id:
            return harness
    choices = ", ".join(h.id for h in HARNESSES)
    raise ValueError(f"unknown harness '{harness_id}' (expected: {choices})")


def dest_dir(harness: Harness, skill_name: str, project_root: Path) -> Path:
    """Resolve where a skill projects to, refusing anything outside the project.

    Names reach this function from the committed manifest as well as from the
    catalog, so a corrupted or hostile entry must never be able to steer a
    caller's write or rmtree at a path outside the harness's skills root.

    Validating the name is only half of it. A symlink on any component of the
    skills root moves every projection with it, so the root is resolved and
    checked against the resolved project root before a path is handed back. A
    project that itself lives under a symlink stays legal: both sides are
    resolved, so only a genuine escape trips the check.

    The skill directory itself is deliberately not resolved. A symlink sitting
    there is one skill's problem, and inspection reports it as a conflict the
    user can see and repair, rather than failing the whole sync.
    """
    if not is_valid_skill_name(skill_name):
        raise ValueError(f"unsafe skill name '{skill_name}'")
    project_root = Path(project_root)
    root = project_root / harness.skills_root
    try:
        root.resolve().relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"skills root for harness '{harness.id}' resolves outside the "
            f"project: {root} -> {root.resolve()}"
        ) from exc
    return root / skill_name
