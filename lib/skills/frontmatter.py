"""Minimal, stdlib-only YAML front-matter parse/serialize for SKILL.md.

Handles exactly what a canonical SKILL.md needs: simple ``key: value`` pairs and
folded scalars introduced by ``key: >`` (following more-indented lines joined
with spaces). It intentionally does not depend on PyYAML: the engine only ever
reads front matter and copies every other file byte-for-byte.
"""
from __future__ import annotations

_FENCE = "---"


def parse(text: str) -> tuple[dict, str]:
    """Return ``(meta, body)``. No front matter -> ``({}, text)``."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FENCE:
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            end = i
            break
    if end is None:
        return {}, text
    meta = _parse_block([ln.rstrip("\n") for ln in lines[1:end]])
    body = "".join(lines[end + 1:])
    if body.startswith("\n"):
        body = body[1:]
    return meta, body


def _parse_block(raw: list) -> dict:
    meta: dict = {}
    i = 0
    while i < len(raw):
        line = raw[i]
        if not line.strip():
            i += 1
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val == ">":
            folded: list = []
            i += 1
            while i < len(raw) and (raw[i].startswith((" ", "\t")) or not raw[i].strip()):
                if raw[i].strip():
                    folded.append(raw[i].strip())
                i += 1
            meta[key] = " ".join(folded)
        else:
            meta[key] = val
            i += 1
    return meta


def serialize(meta: dict, body: str) -> str:
    """Emit front matter (insertion order) + body. Deterministic."""
    out = [_FENCE]
    for key, val in meta.items():
        if "\n" in val:
            out.append(f"{key}: >")
            for part in val.split("\n"):
                out.append(f"  {part}")
        else:
            out.append(f"{key}: {val}")
    out.append(_FENCE)
    out.append("")
    return "\n".join(out) + "\n" + body.lstrip("\n")
