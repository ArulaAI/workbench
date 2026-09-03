"""Agent-harness targets, explicit selection, and marker-based detection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skills import is_valid_skill_name


@dataclass(frozen=True)
class Surface:
    id: str
    harness: str
    skills_root: str
    marker: str


SURFACES = [
    Surface(
        id="claude_code",
        harness="claude",
        skills_root=".claude/skills",
        marker=".claude",
    ),
    Surface(
        id="codex",
        harness="codex",
        skills_root=".agents/skills",
        marker=".agents",
    ),
    Surface(
        id="copilot",
        harness="copilot",
        skills_root=".github/skills",
        marker=".github/skills",
    ),
]


def _real_dir(project_root: Path, marker: str):
    """The marker directory, or None if reaching it crosses a symlink.

    ``is_dir()`` follows links, so a ``.claude`` pointing anywhere at all would
    otherwise read as a detected surface and licence sync to write through it.
    Every component is checked, because the escape can sit on a parent
    (``.github`` -> /elsewhere) as easily as on the marker itself.
    """
    path = Path(project_root)
    for part in marker.split("/"):
        path = path / part
        if path.is_symlink():
            return None
    return path if path.is_dir() else None


def detect_surfaces(project_root: Path) -> list:
    project_root = Path(project_root)
    return [s for s in SURFACES if _real_dir(project_root, s.marker) is not None]


def get_surface(surface_id: str) -> Surface:
    normalized = (surface_id or "").strip().lower()
    for surface in SURFACES:
        if normalized in (surface.id, surface.harness):
            return surface
    choices = ", ".join(surface.harness for surface in SURFACES)
    raise ValueError(
        f"unknown skill surface or harness '{surface_id}' (expected: {choices})"
    )


def surface_for_harness(harness: str) -> Surface:
    normalized = (harness or "").strip().lower()
    surface = get_surface(normalized)
    if surface.harness != normalized:
        choices = ", ".join(item.harness for item in SURFACES)
        raise ValueError(f"unknown harness '{harness}' (expected: {choices})")
    return surface


def dest_dir(surface: Surface, skill_name: str, project_root: Path) -> Path:
    """Resolve where a skill projects to, refusing anything outside the project.

    Names reach this function from the committed manifest as well as from the
    catalog, so a corrupted or hostile entry must never be able to steer a
    caller's write or rmtree at a path outside the surface's skills root.

    Validating the name is only half of it. A symlink on any component of the
    skills root moves every projection with it, so the root is resolved and
    checked against the resolved project root before a path is handed back. A
    project that itself lives under a symlink stays legal: both sides are
    resolved, so only a genuine escape trips the check.

    The skill directory itself is deliberately not resolved. A symlink sitting
    there is one skill's problem, and classification reports it as a conflict
    the user can see and repair, rather than failing the whole sync.
    """
    if not is_valid_skill_name(skill_name):
        raise ValueError(f"unsafe skill name '{skill_name}'")
    project_root = Path(project_root)
    root = project_root / surface.skills_root
    try:
        root.resolve().relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"skills root for surface '{surface.id}' resolves outside the "
            f"project: {root} -> {root.resolve()}"
        ) from exc
    return root / skill_name
