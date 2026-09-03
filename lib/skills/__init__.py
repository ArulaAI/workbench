"""Workbench skill system: canonical catalog projection engine.

Module map, in the order a sync moves through them:

``models``      shared vocabulary: states, harnesses, packages, plans, findings
``catalog``     discovers and reads canonical packages from the built-in catalog
``validate``    enforces the package contract and reports violations with codes
``frontmatter`` loads SKILL.md front matter as YAML, injects provenance in place
``project``     renders one package for one harness, purely, as relpath -> bytes
``manifest``    hashes projections, persists the manifest, classifies each skill
``targets``     the harness registry, marker detection, and bounded destinations
``bootstrap``   init policy resolution, persistence, migration, and verification
``inspect``     read-only: assembles the whole picture as an ``Inspection``
``sync``        the only writer: plans from an inspection, then applies
``doctor``      read-only: turns inspection findings into coded diagnostics
``events``      appends the per-transaction install log
``__main__``    the CLI the ``workbench skills`` wrapper delegates to
"""

import re
from dataclasses import dataclass
from pathlib import Path

from skills.models import (  # noqa: F401  (re-exported vocabulary)
    HARNESSES,
    HARNESS_IDS,
    STATES,
    Harness,
    SkillState,
)

# Where the skill system keeps its project state, relative to the project root.
# Every module that touches these files derives its path from here, and the
# gitignore policy and the standalone health helper are tested against it. The
# alternative, which this replaced, was the same literal written out in five
# places, and it had already let the engine require a tracked manifest while
# initialization ignored the directory containing it.
_STATE_ROOT = Path(".speed/skills")


@dataclass(frozen=True)
class SkillPaths:
    state_root: Path = _STATE_ROOT
    manifest: Path = _STATE_ROOT / "manifest.json"
    events: Path = _STATE_ROOT / "events.jsonl"


PATHS = SkillPaths()


# A legal skill name is also the only legal path segment for a projection
# directory. Keeping the pattern here lets both the package contract and the
# path builder enforce the same rule without importing each other.
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def is_valid_skill_name(name) -> bool:
    return bool(isinstance(name, str) and SKILL_NAME_RE.match(name))


# Generated/OS junk that must never become part of a package, its projection,
# or the on-disk hash a projection is compared against. render() cannot emit
# these, so finding one next to a projection says nothing about drift.
_EXCLUDE_DIRS = {"__pycache__", ".git"}
_EXCLUDE_SUFFIXES = (".pyc", ".pyo")
_EXCLUDE_NAMES = {".DS_Store"}


def is_junk(rel: str) -> bool:
    parts = rel.split("/")
    if any(part in _EXCLUDE_DIRS for part in parts):
        return True
    if parts[-1] in _EXCLUDE_NAMES:
        return True
    return rel.endswith(_EXCLUDE_SUFFIXES)
