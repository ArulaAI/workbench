"""Read-only diagnostics and one repair path for every non-current skill state."""
from __future__ import annotations

from dataclasses import dataclass

from skills import ABSENT, CONFLICTED, CURRENT, ORPHANED, STALE, UNSUPPORTED
from skills.sync import status


@dataclass(frozen=True)
class Diagnostic:
    surface: str
    skill: str
    state: str
    diagnosis: str
    repair: str


_GUIDANCE = {
    ABSENT: (
        "The catalog skill has not been imported into this agent surface.",
        "Run `workbench skills sync`.",
    ),
    STALE: (
        "The imported skill is older than or differs from the current catalog.",
        "Run `workbench skills sync`.",
    ),
    CONFLICTED: (
        "The projected skill differs from its managed manifest.",
        "Review or back up local edits, then run `workbench skills sync --force`.",
    ),
    ORPHANED: (
        "The managed skill is installed but no longer exists in the catalog.",
        "Run `workbench skills sync` to remove the obsolete projection.",
    ),
    UNSUPPORTED: (
        "No supported agent skill surface was detected in this project.",
        "Open the project in a supported agent to create its surface, then run "
        "`workbench skills sync`.",
    ),
}


def diagnose(project_root, skills_dir, catalog_version, *, only_surface=None):
    """Return diagnostics for non-current states without changing project files."""
    rows = status(
        project_root,
        skills_dir,
        catalog_version,
        only_surface=only_surface,
    )
    if rows and all(row.state == UNSUPPORTED for row in rows):
        # Having no harness is one fact about the project, not one per harness
        # SPEED knows how to project into.
        diagnosis, repair = _GUIDANCE[UNSUPPORTED]
        return [
            Diagnostic(
                surface="-",
                skill="*",
                state=UNSUPPORTED,
                diagnosis=diagnosis,
                repair=repair,
            )
        ]
    diagnostics = []
    for row in rows:
        if row.state == CURRENT:
            continue
        diagnosis, repair = _GUIDANCE.get(
            row.state,
            (
                f"The skill is in an unknown state: {row.state}.",
                "Run `workbench skills status --json` and inspect the reported state.",
            ),
        )
        diagnostics.append(
            Diagnostic(
                surface=row.surface,
                skill=row.skill,
                state=row.state,
                diagnosis=diagnosis,
                repair=repair,
            )
        )
    return diagnostics
