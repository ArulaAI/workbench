"""Minimal, stdlib-only YAML front-matter handling for SKILL.md.

Two jobs, both deliberately narrow:

``parse``  reads the scalar keys the engine needs (``name``, ``description``,
           ``version``) and skips anything it cannot model rather than
           inventing a key for it.
``inject`` sets Workbench's provenance keys in an existing block and leaves
           every other line byte-for-byte intact.

Rebuilding a block from a parsed dict would corrupt it: real front matter
carries sequences, nested mappings, quoted strings and folded scalars, and a
serializer that models only ``key: value`` silently emits invalid YAML. Editing
in place sidesteps that entirely, so PyYAML stays an unnecessary dependency.
"""
from __future__ import annotations

_FENCE = "---"
# Reserved for Workbench provenance. validate refuses these keys in a canonical
# package so that projection can set them without overwriting an author's data.
MANAGED_PREFIX = "x-workbench-"


def _closing_fence(lines: list):
    """Index of the closing fence, or None when the file has no front matter.

    A block that opens and never closes raises instead. Reporting it as "no
    front matter" would hand the caller a document with no metadata at all, and
    the author would then be told the description is missing rather than that
    the fence is.
    """
    if not lines or lines[0].strip() != _FENCE:
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            return i
    raise ValueError(
        "malformed front matter: the opening '---' has no closing '---'"
    )


def _is_entry(line: str) -> bool:
    """True for a top-level ``key: ...`` line inside the block."""
    return bool(line) and not line[0].isspace() and ":" in line


def _continuation(raw: list, i: int):
    """Collect the blank and more-indented lines belonging to entry ``i``."""
    out: list = []
    i += 1
    while i < len(raw) and (not raw[i].strip() or raw[i][0].isspace()):
        out.append(raw[i])
        i += 1
    return out, i


def _dedent(block: list) -> list:
    filled = [line for line in block if line.strip()]
    if not filled:
        return []
    pad = min(len(line) - len(line.lstrip()) for line in filled)
    return [line[pad:] if line.strip() else "" for line in block]


def _reject_duplicate(meta: dict, key: str) -> None:
    """Refuse a repeated key instead of letting the last one win.

    Silently keeping the final value means a package whose front matter declares
    `name` twice projects under whichever came last, with nothing telling the
    author the other line was discarded.
    """
    if key in meta:
        raise ValueError(f"malformed front matter: duplicate key '{key}'")


def _parse_block(raw: list) -> dict:
    meta: dict = {}
    i = 0
    while i < len(raw):
        line = raw[i]
        if not _is_entry(line):
            # A sequence item or an orphaned continuation. Naming it would put
            # values like "- Read" in meta as if they were keys.
            i += 1
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith(">"):
            folded, i = _continuation(raw, i)
            _reject_duplicate(meta, key)
            meta[key] = " ".join(part.strip() for part in folded if part.strip())
        elif val.startswith("|"):
            literal, i = _continuation(raw, i)
            _reject_duplicate(meta, key)
            meta[key] = "\n".join(_dedent(literal)).strip("\n")
        elif val:
            _reject_duplicate(meta, key)
            meta[key] = val
            i += 1
        else:
            # A bare "key:" introduces a sequence or a nested mapping, neither
            # of which this module models. Leave the key out rather than guess.
            _, i = _continuation(raw, i)
    return meta


def parse(text: str) -> tuple[dict, str]:
    """Return ``(meta, body)``. No front matter -> ``({}, text)``.

    Raises ValueError when a front-matter block is opened but never closed.
    """
    lines = text.splitlines(keepends=True)
    end = _closing_fence(lines)
    if end is None:
        return {}, text
    meta = _parse_block([line.rstrip("\n") for line in lines[1:end]])
    body = "".join(lines[end + 1:])
    if body.startswith("\n"):
        body = body[1:]
    return meta, body


def _without_managed(block: list) -> list:
    """Drop Workbench's own keys, so re-injecting replaces instead of appends."""
    out: list = []
    dropping = False
    for line in block:
        if _is_entry(line.rstrip("\n")):
            key = line.split(":", 1)[0].strip()
            dropping = key.startswith(MANAGED_PREFIX)
            if dropping:
                continue
        elif dropping:
            continue  # a continuation of the key just dropped
        out.append(line)
    return out


def inject(text: str, extra: dict) -> str:
    """Return ``text`` with ``extra`` set in its front matter. Deterministic.

    Only ``x-workbench-*`` keys are rewritten; the rest of the block is copied
    verbatim, which is what keeps lists, nested mappings, quoted values and
    folded scalars valid in the projection. An unterminated block raises rather
    than gaining a second one stacked on top of it.
    """
    added = [f"{key}: {val}\n" for key, val in extra.items()]
    lines = text.splitlines(keepends=True)
    end = _closing_fence(lines)
    if end is None:
        opening = "".join([_FENCE + "\n", *added, _FENCE + "\n", "\n"])
        return opening + text.lstrip("\n")
    kept = _without_managed(lines[1:end])
    return "".join([lines[0], *kept, *added, *lines[end:]])
