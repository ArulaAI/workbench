"""SPEED skill system: canonical catalog projection engine."""

import re

# Projection state vocabulary (single source of truth).
ABSENT = "absent"
CURRENT = "current"
STALE = "stale"
CONFLICTED = "conflicted"
ORPHANED = "orphaned"
UNSUPPORTED = "unsupported"

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
