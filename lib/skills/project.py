"""Pure projection: render a canonical package to a surface's files.

Returns relpath -> bytes and never touches the filesystem. SKILL.md is
re-serialized with injected provenance keys; every other file is copied verbatim.
Deterministic: identical inputs produce byte-identical output.
"""
from __future__ import annotations

from skills.catalog import SkillPackage
from skills.frontmatter import inject
from skills.targets import Surface


def render(pkg: SkillPackage, surface: Surface, catalog_version: str) -> dict:
    """Project ``pkg`` onto ``surface``.

    ``catalog_version`` identifies the SPEED install running the sync, not the
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
    source = pkg.files.get("SKILL.md", b"").decode()
    out["SKILL.md"] = inject(
        source,
        {"x-workbench-managed": "true", "x-workbench-source": pkg.name},
    ).encode()
    return out
