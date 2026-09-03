"""Read-only diagnosis: turn inspection findings into coded diagnostics.

A lifecycle state says what sync will do about a skill. It does not say what is
wrong with it, and `conflicted` alone covers a modified file, a missing file, an
unexpected file, a symlink, an occupied path, and a projection with no manifest
record. Mapping one state to one sentence of prose therefore told the user which
bucket their problem fell into and nothing else.

So the states stay small and closed, and the explanations live in a catalog
keyed by diagnostic code. Each definition owns its severity, its wording, its
repair command, and whether that repair can destroy work. Inspection supplies
the evidence (path, expected hash, actual hash) and this module never
recomputes it.

Nothing here imports ``sync``. Diagnosis reads an ``Inspection`` and cannot
write.
"""
from __future__ import annotations

from dataclasses import dataclass

from skills import PATHS
from skills.manifest import MANIFEST_LOST
from skills.models import (
    HARNESS_UNSUPPORTED,
    INTERNAL_UNKNOWN_STATE,
    MANIFEST_LOST as CODE_MANIFEST_LOST,
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

ERROR = "error"
WARNING = "warning"
NOTE = "note"

_SYNC = "workbench skills sync"
_FORCE = "workbench skills sync --harness {harness} --force"
_INIT = "workbench init --harness <claude|codex|copilot>"


@dataclass(frozen=True)
class Diagnostic:
    """One finding, with the evidence behind it and exactly one repair.

    ``code`` is stable and is what a caller should branch on. ``expected`` and
    ``actual`` are the hashes the classification was made from, so the output
    shows the comparison instead of asserting its conclusion. ``destructive``
    marks a repair that can overwrite local work, which is what a wrapper needs
    in order to decide whether to confirm before running it.
    """

    code: str
    severity: str
    harness: str
    skill: str
    state: SkillState
    message: str
    repair_command: str
    destructive: bool = False
    path: str | None = None
    expected: str | None = None
    actual: str | None = None


@dataclass(frozen=True)
class _Definition:
    severity: str
    message: str
    repair_command: str
    destructive: bool = False


# The catalog. Workbench owns these definitions; a project cannot add to them.
# `{path}`, `{harness}` and `{skill}` are substituted from the finding.
_CATALOG = {
    PROJECTION_MISSING: _Definition(
        WARNING,
        "The catalog skill '{skill}' is not projected into {harness}.",
        _SYNC,
    ),
    PROJECTION_OUTDATED: _Definition(
        WARNING,
        "'{path}' differs from the current catalog for skill '{skill}'.",
        _SYNC,
    ),
    PROJECTED_FILE_MODIFIED: _Definition(
        ERROR,
        "'{path}' changed after Workbench projected it.",
        _FORCE,
        destructive=True,
    ),
    PROJECTED_FILE_MISSING: _Definition(
        ERROR,
        "'{path}' is recorded in the manifest but is no longer on disk.",
        _FORCE,
        destructive=True,
    ),
    PROJECTED_FILE_UNEXPECTED: _Definition(
        ERROR,
        "'{path}' sits inside the projection but Workbench never wrote it.",
        _FORCE,
        destructive=True,
    ),
    PROJECTION_PATH_OCCUPIED: _Definition(
        ERROR,
        "Something other than a managed projection occupies the path for "
        "skill '{skill}'.",
        _FORCE,
        destructive=True,
    ),
    PROJECTION_SYMLINK: _Definition(
        ERROR,
        "A symlink sits where managed bytes belong for skill '{skill}'. "
        "Workbench copies files and never projects a link.",
        _FORCE,
        destructive=True,
    ),
    MANIFEST_RECORD_MISSING: _Definition(
        ERROR,
        "'{path}' is projected for skill '{skill}' with nothing in the "
        "manifest recording that Workbench wrote it.",
        _FORCE,
        destructive=True,
    ),
    ORPHANED_PROJECTION: _Definition(
        WARNING,
        "Skill '{skill}' is projected into {harness} but no longer exists in "
        "the catalog.",
        _SYNC,
    ),
    ORPHANED_RECORD: _Definition(
        WARNING,
        "The manifest still records skill '{skill}' for {harness}, but it has "
        "left the catalog and its projection is already gone.",
        _SYNC,
    ),
    ORPHANED_PROJECTION_MODIFIED: _Definition(
        ERROR,
        "Skill '{skill}' has left the catalog and its projection was edited, "
        "so removing it would discard those edits.",
        _FORCE,
        destructive=True,
    ),
    CODE_MANIFEST_LOST: _Definition(
        ERROR,
        "Skills are projected into this project but '"
        + PATHS.manifest.as_posix()
        + "' is missing, so none of them can be told apart from a local edit.",
        "Restore '"
        + PATHS.manifest.as_posix()
        + "' from version control. If it was never committed, run "
        "`workbench skills sync --force` to re-project and record the skills "
        "again.",
        destructive=True,
    ),
    HARNESS_UNSUPPORTED: _Definition(
        NOTE,
        "No supported agent harness was detected in this project.",
        _INIT,
    ),
    INTERNAL_UNKNOWN_STATE: _Definition(
        ERROR,
        "Internal error: skill '{skill}' on {harness} is '{state}' with no "
        "diagnostic evidence. This is a Workbench bug, not a problem with the "
        "project.",
        "Report this with the output of `workbench skills status --json`.",
    ),
}


# Every code the engine can emit must have a definition, or a real finding would
# reach the user as a bare code. Checking at import turns that into a failure the
# author sees rather than one the user reads.
_EMITTED = {
    PROJECTION_MISSING,
    PROJECTION_OUTDATED,
    PROJECTED_FILE_MODIFIED,
    PROJECTED_FILE_MISSING,
    PROJECTED_FILE_UNEXPECTED,
    PROJECTION_PATH_OCCUPIED,
    PROJECTION_SYMLINK,
    MANIFEST_RECORD_MISSING,
    ORPHANED_PROJECTION,
    ORPHANED_RECORD,
    ORPHANED_PROJECTION_MODIFIED,
    CODE_MANIFEST_LOST,
    HARNESS_UNSUPPORTED,
    INTERNAL_UNKNOWN_STATE,
}
_UNDEFINED = _EMITTED - set(_CATALOG)
if _UNDEFINED:
    raise RuntimeError(
        "the doctor catalog is missing a definition for: "
        + ", ".join(sorted(_UNDEFINED))
    )


def _fill(template: str, **values) -> str:
    # Plain substitution rather than str.format, so a future message is free to
    # contain a brace without having to escape it.
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _build(harness, skill, state, finding: Finding) -> Diagnostic:
    definition = _CATALOG.get(finding.code)
    if definition is None:
        definition = _CATALOG[INTERNAL_UNKNOWN_STATE]
    values = {
        "harness": harness,
        "skill": skill,
        "state": state,
        "path": finding.path or "-",
    }
    return Diagnostic(
        code=finding.code,
        severity=definition.severity,
        harness=harness,
        skill=skill,
        state=state,
        message=_fill(definition.message, **values),
        repair_command=_fill(definition.repair_command, **values),
        destructive=definition.destructive,
        path=finding.path,
        expected=finding.expected,
        actual=finding.actual,
    )


def diagnose(inspection) -> list:
    """Every non-current finding in ``inspection``, as coded diagnostics."""
    if inspection.manifest_state == MANIFEST_LOST:
        # Every projection would otherwise classify as conflicted and be
        # reported as a local edit. On a fresh clone that is the opposite of
        # what happened: the files are untouched and the record of them is
        # what went missing.
        return [
            _build("-", "*", SkillState.CONFLICTED, Finding(CODE_MANIFEST_LOST))
        ]
    if inspection.skills and all(
        item.state is SkillState.UNSUPPORTED for item in inspection.skills
    ):
        # Having no harness is one fact about the project, not one per harness
        # Workbench knows how to project into.
        return [
            _build("-", "*", SkillState.UNSUPPORTED, Finding(HARNESS_UNSUPPORTED))
        ]
    out: list = []
    for item in inspection.skills:
        if item.state is SkillState.CURRENT:
            continue
        findings = item.findings or [Finding(INTERNAL_UNKNOWN_STATE)]
        for finding in findings:
            out.append(_build(item.harness, item.skill, item.state, finding))
    return out
