"""Agent-surface targets and detection.

Phase 1 ships claude_code only. Adding Codex is an additive Surface entry plus
its detection marker; no workflow change elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Surface:
    id: str
    skills_root: str
    marker: str


SURFACES = [
    Surface(id="claude_code", skills_root=".claude/skills", marker=".claude"),
]


def detect_surfaces(project_root: Path) -> list:
    project_root = Path(project_root)
    return [s for s in SURFACES if (project_root / s.marker).is_dir()]


def dest_dir(surface: Surface, skill_name: str, project_root: Path) -> Path:
    return Path(project_root) / surface.skills_root / skill_name
