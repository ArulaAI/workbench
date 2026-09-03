"""Pure projection: render a canonical package to one harness's files.

Returns relpath -> bytes and never touches the filesystem. SKILL.md is
re-serialized with injected provenance keys; every other file is copied verbatim.
Deterministic: identical inputs produce byte-identical output.
"""
from __future__ import annotations

from skills.frontmatter import MANAGED_PREFIX, inject
from skills.models import Harness, SkillPackage

# Provenance keys stamped into every projected SKILL.md. The values are written
# as raw, unquoted YAML scalars, so ``true`` reaches the harness as the boolean
# true rather than the string "true"; validate reserves the MANAGED_PREFIX
# namespace so a package can never declare these and lose them at projection.
_PROVENANCE_MANAGED = f"{MANAGED_PREFIX}managed"
_PROVENANCE_SOURCE = f"{MANAGED_PREFIX}source"


def render(pkg: SkillPackage, harness: Harness, catalog_version: str) -> dict:
    """Project ``pkg`` onto ``harness``.

    ``catalog_version`` identifies the Workbench install running the sync, not the
    catalog content, so it is deliberately kept out of the returned bytes:
    projections are committed, and stamping the local install into them would
    make every teammate's sync rewrite the files and flip them stale. The
    install is recorded in the manifest instead, where it costs nothing.

    SKILL.md is edited in place rather than rebuilt from ``pkg.meta``, so front
    matter this module does not model (lists, nested mappings, quoted or folded
    values) reaches the harness exactly as the author wrote it.
    """
    out: dict = {}
    for rel, content in pkg.files.items():
        if rel != "SKILL.md":
            out[rel] = content
    source = pkg.files.get("SKILL.md", b"").decode("utf-8")
    out["SKILL.md"] = inject(
        source,
        {_PROVENANCE_MANAGED: "true", _PROVENANCE_SOURCE: pkg.name},
    ).encode("utf-8")
    return out
