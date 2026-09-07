"""YAML front-matter handling for SKILL.md.

Front matter is YAML, so it is read by a YAML implementation. ``parse`` runs
``yaml.safe_load`` over the block and then enforces the two structural rules
Workbench needs on top of it. A partial parser lived here before and misread
exactly the inputs a partial parser misreads: ``name: "demo"`` kept its quotes
and was reported as disagreeing with its own directory, a ``#`` comment became
a key, and every scalar arrived as a string.

Two jobs, with different reasons for their shape:

``parse``  loads the block as YAML and returns ``(meta, body)``. Quoting,
           comments, escapes, anchors, sequences, nested mappings, block
           scalars and scalar types are the library's business, not ours.
``inject`` sets Workbench's provenance keys in an existing block and leaves
           every other line byte-for-byte intact.

``inject`` deliberately does not round-trip through ``safe_dump``. Re-emitting
a parsed document reorders keys, drops comments, and rewrites an author's
quoting and block scalars, all of which would show up as a diff in a committed
projection. Editing the block in place means only the lines Workbench owns
change; the values it writes are still serialized by ``safe_dump``, so a skill
named ``true`` or ``on`` is quoted rather than projected as a boolean.

Boundary and newline policy, stated because both are observable:

* ``parse`` returns the body starting after the closing fence, with a single
  newline directly following that fence removed and nothing else touched. The
  body is never re-indented, re-wrapped, or re-encoded.
* ``inject`` writes its lines with the terminator the opening fence already
  uses, so a CRLF document stays CRLF instead of gaining mixed endings.
* Both work on ``str``. Decoding is the caller's job and is always UTF-8.
"""
from __future__ import annotations

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - install-time problem
    raise ModuleNotFoundError(
        "PyYAML is required to read skill front matter. It is declared in "
        "requirements.txt; install it with `python3 -m pip install -r "
        "requirements.txt`, or run Workbench through its managed interpreter."
    ) from exc

_FENCE = "---"
# Reserved for Workbench provenance. validate refuses these keys in a canonical
# package so that projection can set them without overwriting an author's data.
MANAGED_PREFIX = "x-workbench-"


class _NoDuplicateKeys(yaml.SafeLoader):
    """``SafeLoader`` that refuses a repeated key instead of keeping the last.

    YAML itself allows the duplicate and says nothing about it, so front matter
    declaring ``name`` twice would project under whichever line came last with
    the author never told the other was discarded.
    """

    def construct_mapping(self, node, deep=False):
        seen: list = []
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            # Membership by equality rather than a set: YAML permits a sequence
            # or mapping as a key, and those are unhashable.
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while reading front matter",
                    node.start_mark,
                    f"duplicate key '{key}'",
                    key_node.start_mark,
                )
            seen.append(key)
        return super().construct_mapping(node, deep=deep)


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


def _newline(line: str) -> str:
    """The terminator ``line`` ends with, so injected lines can match it."""
    return "\r\n" if line.endswith("\r\n") else "\n"


def parse(text: str) -> tuple[dict, str]:
    """Return ``(meta, body)``. No front matter -> ``({}, text)``.

    Raises ValueError when the block is opened but never closed, is not valid
    YAML, does not hold a mapping, or repeats a key. An empty or comment-only
    block is a mapping with nothing in it, not an error.
    """
    lines = text.splitlines(keepends=True)
    end = _closing_fence(lines)
    if end is None:
        return {}, text

    block = "".join(lines[1:end])
    try:
        loaded = yaml.load(block, Loader=_NoDuplicateKeys)
    except yaml.YAMLError as exc:
        raise ValueError(f"malformed front matter: {exc}") from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ValueError(
            "malformed front matter: expected a mapping of keys to values, "
            f"got {type(loaded).__name__}"
        )
    for key in loaded:
        # A non-string key cannot be a skill metadata field, and every consumer
        # downstream indexes meta by name.
        if not isinstance(key, str):
            raise ValueError(
                f"malformed front matter: key {key!r} is not a string"
            )

    body = "".join(lines[end + 1:])
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    return loaded, body


def _emit(key: str, value, newline: str) -> str:
    """One front-matter line, serialized by PyYAML so its type survives.

    ``safe_dump`` is what decides quoting, which is the point: ``True`` becomes
    the bare ``true`` a reader loads back as a boolean, while a string that
    would otherwise read as one (``true``, ``on``, ``null``) comes back quoted.
    ``width`` is set past any real value so a long one is never line-wrapped
    into a continuation this module would then have to model.
    """
    line = yaml.safe_dump(
        {key: value},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=10**9,
    ).rstrip("\n")
    return line + newline


def _without_managed(block: list) -> list:
    """Drop Workbench's own keys, so re-injecting replaces instead of appends."""
    out: list = []
    dropping = False
    for line in block:
        if _is_entry(line.rstrip("\r\n")):
            key = line.split(":", 1)[0].strip()
            dropping = key.startswith(MANAGED_PREFIX)
            if dropping:
                continue
        elif dropping:
            continue  # a continuation of the key just dropped
        out.append(line)
    return out


def _drop_one_break(text: str) -> str:
    """Remove at most one leading line break, CRLF counted as one."""
    for prefix in ("\r\n", "\n", "\r"):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def inject(text: str, extra: dict) -> str:
    """Return ``text`` with ``extra`` set in its front matter. Deterministic.

    Only ``x-workbench-*`` keys are rewritten; the rest of the block is copied
    verbatim, which is what keeps an author's comments, key order, quoting,
    sequences, nested mappings and block scalars exactly as written. An
    unterminated block raises rather than gaining a second one stacked on top.
    """
    lines = text.splitlines(keepends=True)
    end = _closing_fence(lines)
    newline = _newline(lines[0]) if lines else "\n"
    added = [_emit(key, value, newline) for key, value in extra.items()]
    if end is None:
        opening = "".join(
            [_FENCE + newline, *added, _FENCE + newline, newline]
        )
        # One separator, not a run. `opening` already ends with a blank line,
        # so a body that starts with one would double it up, but `lstrip`
        # deleted every leading blank line the author wrote rather than the
        # single one this is compensating for.
        return opening + _drop_one_break(text)
    kept = _without_managed(lines[1:end])
    return "".join([lines[0], *kept, *added, *lines[end:]])
