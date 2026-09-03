"""Shared vocabulary for the skill system: states, harnesses, packages, plans.

Every other module in the package depends on this one and, apart from the
narrow exceptions noted below, not on each other. Catalog loading, validation,
rendering, inspection, planning and application all speak in these types, which
is what lets the read-only half of the system exist without importing the half
that writes.

The types here are deliberately dumb. They hold no I/O and no policy, so a test
can build any state of the world in memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class SkillState(str, Enum):
    """The closed set of states a (harness, skill) pair can be in.

    A string-backed enum rather than bare constants, because these values cross
    every boundary in the system: inspection produces them, planning branches on
    them, diagnostics are keyed by them, JSON carries them, and exit codes are
    derived from them. As plain strings a typo reached the user as a state; as
    members, an unknown value cannot be constructed by accident, and a consumer
    can be checked against ``STATES`` for exhaustiveness at import time.

    ``__str__`` and ``__format__`` are pinned to the value so text output is
    identical on every supported interpreter. Python 3.11 changed mixin-enum
    formatting to include the class name, which would otherwise have turned a
    status row into ``SkillState.ABSENT``.
    """

    ABSENT = "absent"
    CURRENT = "current"
    STALE = "stale"
    CONFLICTED = "conflicted"
    ORPHANED = "orphaned"
    UNSUPPORTED = "unsupported"

    def __str__(self) -> str:
        return self.value

    def __format__(self, spec: str) -> str:
        return format(self.value, spec)


STATES = frozenset(SkillState)


# ── Diagnostic codes ────────────────────────────────────────────────────────
#
# A lifecycle state says what sync will do; a code says what is actually wrong.
# One state covers several causes: `conflicted` alone is raised by a modified
# file, a missing file, an unexpected file, a symlink, an occupied path, and a
# projection with no manifest record, and those need different evidence and
# different repairs. Keeping the states small and the codes extensible is what
# lets doctor explain a finding instead of relabelling a state.
PROJECTION_MISSING = "projection_missing"
PROJECTION_OUTDATED = "projection_outdated"
PROJECTED_FILE_MODIFIED = "projected_file_modified"
PROJECTED_FILE_MISSING = "projected_file_missing"
PROJECTED_FILE_UNEXPECTED = "projected_file_unexpected"
PROJECTION_PATH_OCCUPIED = "projection_path_occupied"
PROJECTION_SYMLINK = "projection_symlink"
MANIFEST_RECORD_MISSING = "manifest_record_missing"
MANIFEST_LOST = "manifest_lost"
ORPHANED_PROJECTION = "orphaned_projection"
ORPHANED_RECORD = "orphaned_record"
ORPHANED_PROJECTION_MODIFIED = "orphaned_projection_modified"
HARNESS_UNSUPPORTED = "harness_unsupported"
INTERNAL_UNKNOWN_STATE = "internal_unknown_state"


@dataclass(frozen=True)
class Finding:
    """One machine-readable reason a skill is not ``current``.

    ``expected`` and ``actual`` carry the hashes the classification was made
    from, so a diagnostic can show the comparison rather than assert its
    conclusion. Both are None for a finding about the projection as a whole.
    """

    code: str
    path: str | None = None
    expected: str | None = None
    actual: str | None = None


# ── Harnesses ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Harness:
    """One agent harness Workbench can project skills into.

    ``id`` is the harness name the user types at the CLI. There is deliberately
    no second identifier: an earlier revision carried both a `surface` id
    (`claude_code`) and a harness name (`claude`) for the same thing, which
    meant the manifest, the JSON output, the diagnostics and the two CLI flags
    disagreed about what to call it while never once behaving differently.
    """

    id: str
    skills_root: str
    marker: str


HARNESSES = (
    Harness(id="claude", skills_root=".claude/skills", marker=".claude"),
    Harness(id="codex", skills_root=".agents/skills", marker=".agents"),
    Harness(id="copilot", skills_root=".github/skills", marker=".github/skills"),
)

HARNESS_IDS = tuple(h.id for h in HARNESSES)


# ── Packages ────────────────────────────────────────────────────────────────

# Stated here because both the loader and the validator enforce it: the loader
# refuses a symlink before it reads through one, and the validator reports the
# same rule against a package built in memory. The two have to word it
# identically or deduplication stops recognising the two reports as one fact.
NO_SYMLINKS = "package files must not be symlinks"


@dataclass
class SkillPackage:
    """A canonical package as read from the catalog, valid or not.

    Owned here rather than by the loader so that rendering and validation can
    take one without depending on catalog I/O. ``errors`` carries contract
    failures found during the read, which ``validate`` turns into violations.
    """

    name: str
    root: Path
    meta: dict
    body: str
    files: dict = field(default_factory=dict)
    # (relative path or None, reason) pairs found while reading the package.
    errors: list = field(default_factory=list)


# ── Inspection (read-only) ──────────────────────────────────────────────────


@dataclass
class SkillInspection:
    """What one (harness, skill) pair looks like right now.

    Carries the evidence behind ``state`` plus everything a plan needs, so
    planning is a pure function of an inspection and never re-reads the disk.
    """

    harness: str
    skill: str
    state: SkillState
    findings: list = field(default_factory=list)
    # None when the skill is no longer in the catalog (an orphan candidate).
    rendered: dict | None = None
    dest: Path | None = None
    version: str | None = None
    prev_version: str | None = None


@dataclass
class Inspection:
    """The whole read-only picture: what is installed, and what should be.

    Produced by ``skills.inspect``, consumed by ``doctor`` for diagnosis and by
    ``sync`` for planning. Nothing that holds one of these has written anything.
    """

    project_root: Path
    catalog_version: str
    manifest: dict
    manifest_state: str
    harnesses: list = field(default_factory=list)
    skills: list = field(default_factory=list)

    @property
    def supported(self) -> bool:
        return bool(self.harnesses)


# ── Planning and application (write) ────────────────────────────────────────

WRITE = "write"
REMOVE = "remove"
PRESERVE = "preserve"

INSTALLED = "installed"
UPDATED = "updated"
REMOVED = "removed"
CONFLICT = "conflict"


@dataclass
class SkillPlan:
    """One filesystem operation sync intends to perform.

    A named record rather than the positional six-tuple this replaced: the
    fields steer a write and an ``rmtree``, and confusing two of them by
    position is the kind of mistake that deletes a user's work.
    """

    harness: str
    skill: str
    state: SkillState
    operation: str
    rendered: dict | None = None
    dest: Path | None = None
    version: str | None = None
    prev_version: str | None = None


@dataclass
class SyncOutcome:
    """What sync did to one skill, and where that left it.

    ``previous_state`` is the classification sync acted on and ``final_state``
    is the classification after acting, which is what the CLI prints and what
    exit codes derive from. Reporting only the pre-run state made a successful
    ``--force`` repair report ``conflicted`` and exit 2 while the very next
    ``status`` said ``current``.
    """

    harness: str
    skill: str
    previous_state: SkillState
    action: str
    final_state: SkillState
