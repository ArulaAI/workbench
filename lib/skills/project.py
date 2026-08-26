"""Pure projection: render a canonical package to a surface's files.

Returns relpath -> bytes and never touches the filesystem. SKILL.md is
re-serialized with injected provenance keys; every other file is copied verbatim.
Deterministic: identical inputs produce byte-identical output.
"""
from __future__ import annotations

from skills.catalog import SkillPackage
from skills.frontmatter import serialize
from skills.targets import Surface


def render(pkg: SkillPackage, surface: Surface, catalog_version: str) -> dict:
    out: dict = {}
    for rel, content in pkg.files.items():
        if rel != "SKILL.md":
            out[rel] = content
    meta = dict(pkg.meta)
    meta["x-speed-managed"] = "true"
    meta["x-speed-source"] = pkg.name
    meta["x-speed-catalog-version"] = catalog_version
    out["SKILL.md"] = serialize(meta, pkg.body).encode()
    return out
