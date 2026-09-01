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


def detect_surfaces(project_root: Path) -> list:
    project_root = Path(project_root)
    return [s for s in SURFACES if (project_root / s.marker).is_dir()]


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
    """Resolve where a skill projects to, refusing names that escape the root.

    Names reach this function from the committed manifest as well as from the
    catalog, so a corrupted or hostile entry must never be able to steer a
    caller's write or rmtree at a path outside the surface's skills root.
    """
    if not is_valid_skill_name(skill_name):
        raise ValueError(f"unsafe skill name '{skill_name}'")
    return Path(project_root) / surface.skills_root / skill_name
