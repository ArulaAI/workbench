"""Read-only diagnostics and one repair path for every non-current skill state."""
from __future__ import annotations

from dataclasses import dataclass

from skills import (
    ABSENT,
    CONFLICTED,
    CURRENT,
    ORPHANED,
    STALE,
    STATES,
    UNSUPPORTED,
)
from skills.manifest import MANIFEST_LOST, manifest_state
from skills.sync import status


@dataclass(frozen=True)
class Diagnostic:
    surface: str
    skill: str
    state: str
    diagnosis: str
    repair: str


# Repair strings may reference `{surface}`, which is filled from the row the
# diagnosis came from.
#
# Only the `--force` path is scoped, because only it can destroy work: run
# unscoped, it overwrites every conflict on every detected harness, far beyond
# the single finding it was printed under. The other repairs converge to the
# catalog, and the state machine already refuses to remove a modified orphan,
# so running them project-wide loses nothing that sync cannot rebuild.
#
# `--surface` is the narrowest scope sync accepts today, so a harness carrying
# two conflicts still repairs both. Per-skill scoping would need a new flag.
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
        "The projected skill does not match its managed manifest: it was "
        "edited, or something other than the managed projection occupies "
        "its path.",
        "Review or back up anything local at that path, then run "
        "`workbench skills sync --surface {surface} --force`.",
    ),
    ORPHANED: (
        "The managed skill is installed but no longer exists in the catalog.",
        "Run `workbench skills sync` to remove the obsolete projection.",
    ),
    UNSUPPORTED: (
        "No supported agent skill surface was detected in this project.",
        "Run `workbench init --harness <claude|codex|copilot>` to create a "
        "supported agent surface and import the catalog.",
    ),
}


# A state with no guidance would reach a user as generic prose, hiding the fact
# that the classifier and this catalog disagree. Checking at import turns that
# into a failure the author sees, not one the user reads.
_UNCOVERED = (STATES - {CURRENT}) - set(_GUIDANCE)
if _UNCOVERED:
    raise RuntimeError(
        "doctor guidance is not exhaustive; no diagnostic defined for: "
        + ", ".join(sorted(_UNCOVERED))
    )


def _guidance_for(state, surface) -> tuple:
    if state not in _GUIDANCE:
        # Unreachable through the import check above, so getting here means the
        # classifier invented a state at runtime. Say that plainly rather than
        # dressing a Workbench bug up as advice the user can act on.
        return (
            f"Internal error: the classifier returned '{state}', which is not "
            "one of the states doctor defines. This is a Workbench bug, not a "
            "problem with the project.",
            "Report this with the output of `workbench skills status --json`.",
        )
    diagnosis, repair = _GUIDANCE[state]
    # A plain substitution, not str.format: a future repair string is free to
    # contain a brace without having to escape it.
    return diagnosis, repair.replace("{surface}", surface)


def diagnose(project_root, skills_dir, catalog_version, *, only_surface=None):
    """Return diagnostics for non-current states without changing project files."""
    rows = status(
        project_root,
        skills_dir,
        catalog_version,
        only_surface=only_surface,
    )
    if manifest_state(project_root) == MANIFEST_LOST:
        # Every projection would otherwise classify as conflicted and be
        # reported as a local edit. On a fresh clone that is the opposite of
        # what happened: the files are untouched and the record of them is
        # what went missing.
        return [
            Diagnostic(
                surface="-",
                skill="*",
                state=CONFLICTED,
                diagnosis=(
                    "Skills are projected into this project but "
                    "`.speed/skills/manifest.json` is missing, so none of them "
                    "can be told apart from a local edit."
                ),
                repair=(
                    "Restore `.speed/skills/manifest.json` from version "
                    "control. If it was never committed, run "
                    "`workbench skills sync --force` to re-project and record "
                    "the skills again."
                ),
            )
        ]
    if rows and all(row.state == UNSUPPORTED for row in rows):
        # Having no harness is one fact about the project, not one per harness
        # SPEED knows how to project into.
        diagnosis, repair = _guidance_for(UNSUPPORTED, "-")
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
        diagnosis, repair = _guidance_for(row.state, row.surface)
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
