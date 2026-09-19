#!/usr/bin/env python3
"""diagnose_engine.py — Rule engine for `speed diagnose`.

Counts mechanical signals for a project's declared failure classes against
one change. It never decides whether a class is plausible — that field is
reserved for a human on every class, always, regardless of what fired.

SPEED itself carries no domain knowledge here: the classes, and the regex
rules that hint at them, are entirely supplied by the project's own
classes.yaml (pointed to by speed.toml's [diagnose] classes_file). This
script only knows how to run five generic "look" kinds against a diff:

    added-lines                        — regex over lines the diff added
    changed-files-outside-declared     — diff touched a file the task didn't
                                          declare
    changed-source-without-test-change — a changed source file has no
                                          matching test file also changed
    changed-source-with-test-change    — a changed source file DOES have a
                                          matching test file also changed
    new-names-absent-from-spec         — an identifier introduced by the
                                          diff never appears in the
                                          project's spec file

`added-lines` is project-customized via `match`. The other four are
structural — they need no `match`, no domain vocabulary, and work the same
way on any project.

These are routing hints, never evidence — no look here executes or
approximates the real downstream check (typecheck, mutation, differential,
etc.) that would actually produce a verdict.

Usage:
    python3 diagnose_engine.py <classes_yaml> <diff_file> <files_touched_json> [spec_file]

<files_touched_json> is a JSON array of the paths the task declared it would
touch (may be "[]"). <spec_file> is optional; when omitted,
new-names-absent-from-spec rules produce no signal (not an error — that
rule's own input is simply unavailable) rather than block the class it
should not be silently invented.

Output (stdout): JSON —
    {"classes": [{"id", "title", "signals": [{"observed", "where"}]}]}

A class with no rule that produced a count still appears, with
"signals": []. That means nothing was countable, not that the failure is
absent — the plausible/costOfMissing/findableByReading fields belong to the
human reading this output, and this script never touches them.

Exit code: 0 on a successful run. Non-zero only for usage errors or a
classes file that doesn't parse — never because of what the rules found.
"""

import json
import os
import re
import sys


# ── classes.yaml parsing ──────────────────────────────────────────
#
# Tries PyYAML first (already an optional dependency elsewhere in this
# codebase, e.g. lib/deps.sh). Falls back to a minimal hand-parser scoped
# to exactly the grammar classes.yaml uses, the same pattern lib/toml.py
# already follows for speed.toml.

def _parse_classes_yaml(path):
    try:
        import yaml  # noqa: PLC0415 (optional dependency, see docstring)
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return data.get("classes", []) if data else []
    except ImportError:
        return _hand_parse_classes_yaml(path)


def _hand_parse_classes_yaml(path):
    """Minimal parser for the fixed classes.yaml shape:

    classes:
      - id: F1
        title: Some project-declared failure mode
        rules:
          - look: added-lines
            match: '...'
            say: "..."
          - look: new-names-absent-from-spec
            say: "..."

    Supports only what that shape needs: 2-space-indented list items,
    quoted or bare scalar values, no anchors/multi-doc/flow-style.
    """
    classes = []
    current_class = None
    current_rules = None
    current_rule = None

    # YAML's short escape list for double-quoted scalars, plus its
    # fixed-width numeric forms (\xHH, \uHHHH, \UHHHHHHHH). An escape
    # outside this set genuinely is invalid YAML — PyYAML rejects it too
    # (confirmed: yaml.safe_load('"\\d"') raises "found unknown escape
    # character 'd'") — this fallback does the same instead of silently
    # producing a regex that doesn't mean what it looks like.
    _dq_escapes = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "r": "\r",
                   "0": "\0", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
    _dq_hex_escapes = {"x": 2, "u": 4, "U": 8}

    def _decode_double_quoted(body, line_no):
        out = []
        i = 0
        while i < len(body):
            c = body[i]
            if c == "\\" and i + 1 < len(body):
                nxt = body[i + 1]
                if nxt in _dq_hex_escapes:
                    width = _dq_hex_escapes[nxt]
                    digits = body[i + 2:i + 2 + width]
                    if len(digits) < width or not all(d in "0123456789abcdefABCDEF" for d in digits):
                        raise ValueError(
                            f"classes.yaml line {line_no}: '\\{nxt}' needs {width} hex "
                            f"digits in a double-quoted value, got {digits!r}"
                        )
                    codepoint = int(digits, 16)
                    try:
                        out.append(chr(codepoint))
                    except ValueError:
                        raise ValueError(
                            f"classes.yaml line {line_no}: '\\{nxt}{digits}' is not a "
                            f"valid Unicode code point"
                        )
                    i += 2 + width
                    continue
                if nxt not in _dq_escapes:
                    raise ValueError(
                        f"classes.yaml line {line_no}: unsupported escape '\\{nxt}' in a "
                        "double-quoted value — use single quotes for regex patterns "
                        f"(they need no escaping), or double the backslash (\\\\{nxt})"
                    )
                out.append(_dq_escapes[nxt])
                i += 2
                continue
            out.append(c)
            i += 1
        return "".join(out)

    def _scalar(value, line_no):
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            return _decode_double_quoted(value[1:-1], line_no)
        if value.startswith("'") and value.endswith("'"):
            return value[1:-1]
        return value

    with open(path, "r") as f:
        lines = f.readlines()

    for line_no, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if stripped == "classes:" and indent == 0:
            continue
        elif stripped.startswith("- id:") and indent == 2:
            if current_class is not None:
                classes.append(current_class)
            current_class = {"id": _scalar(stripped[len("- id:"):], line_no), "title": "", "rules": []}
            current_rules = current_class["rules"]
            current_rule = None
        elif stripped.startswith("title:") and current_class is not None and current_rule is None:
            current_class["title"] = _scalar(stripped[len("title:"):], line_no)
        elif stripped == "rules:" and current_class is not None:
            continue
        elif stripped == "rules: []" and current_class is not None:
            continue
        elif stripped.startswith("- look:"):
            if current_rules is None:
                raise ValueError(
                    f"classes.yaml line {line_no}: '- look:' found before any '- id:' class "
                    "— check indentation (a class entry must be '- id:' at 2 spaces)"
                )
            current_rule = {"look": _scalar(stripped[len("- look:"):], line_no), "match": None, "say": ""}
            current_rules.append(current_rule)
        elif stripped.startswith("match:") and current_rule is not None:
            current_rule["match"] = _scalar(stripped[len("match:"):], line_no)
        elif stripped.startswith("say:") and current_rule is not None:
            current_rule["say"] = _scalar(stripped[len("say:"):], line_no)
        else:
            raise ValueError(
                f"classes.yaml line {line_no}: unrecognized syntax: {stripped!r} — this "
                "hand-parser only understands the fixed classes.yaml shape documented "
                "above (2-space-indented '- id:'/'- look:' entries); install PyYAML for "
                "full YAML support"
            )

    if current_class is not None:
        classes.append(current_class)

    return classes


# ── diff parsing ───────────────────────────────────────────────────

# A "+++ <path>" path is either bare ("b/foo.py", which may itself contain
# spaces — nothing else follows it on the line, so that's unambiguous) or,
# when git quotes it (the default for non-ASCII filenames), a double-quoted
# C-style-escaped string ("b/caf\303\251.py" for "café.py").
_QUOTED_B_TOKEN = re.compile(r'^"b/((?:[^"\\]|\\.)*)"$')
_FILE_HEADER = re.compile(r"^\+\+\+ (.+)$")


def _git_unquote(body):
    """Decode the inside of a git-quoted path (C-style octal/backslash
    escapes) back to the real filename."""
    out = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in "01234567":
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
            out.extend({
                "a": b"\a", "b": b"\b", "f": b"\f", "n": b"\n", "r": b"\r",
                "t": b"\t", "v": b"\v", '"': b'"', "\\": b"\\",
            }.get(nxt, nxt.encode()))
            i += 2
            continue
        out.append(ord(c))
        i += 1
    return out.decode("utf-8", errors="replace")


def _file_header_path(token):
    """Decode the path from a '+++ <token>' header: unquote it if git
    quoted it (stripping the 'b/' prefix that then lives inside the
    quotes), otherwise just drop the leading 'b/' — git may append a
    trailing tab to a bare, potentially-ambiguous filename."""
    token = token.rstrip("\t")
    m = _QUOTED_B_TOKEN.match(token)
    if m:
        return _git_unquote(m.group(1))
    if token.startswith("b/"):
        return token[2:]
    return token


_QUOTED_TOKEN = re.compile(r'^"((?:[^"\\]|\\.)*)"$')
_RENAME_OR_COPY_TO = re.compile(r"^(?:rename|copy) to (.+)$")


def _rename_target_path(token):
    """Decode the path from a 'rename to <token>' / 'copy to <token>'
    header — unlike '+++'/'diff --git' tokens, these carry no 'a/'/'b/'
    prefix, quoted C-style when needed, bare otherwise."""
    m = _QUOTED_TOKEN.match(token)
    return _git_unquote(m.group(1)) if m else token


def _diff_git_line_paths(line):
    """Parse 'diff --git <a> <b>' into (a_path, b_path), or None. Handles
    git's quoted (non-ASCII) form unambiguously via the quotes themselves.
    Bare paths may contain spaces, which makes splitting the line into its
    two tokens ambiguous in general — but for the overwhelmingly common
    case the two sides are identical (a rename is the only time they
    differ), so that identity is what resolves the split, rather than
    guessing where one token ends and the next begins. A bare rename
    (differing, unquoted paths) is genuinely ambiguous here; callers
    resolve it via the unambiguous 'rename to'/'copy to' header that git
    always emits alongside it (see _changed_files)."""
    prefix = "diff --git "
    if not line.startswith(prefix):
        return None
    rest = line[len(prefix):]
    if rest.startswith('"'):
        m = re.match(r'^"a/((?:[^"\\]|\\.)*)" "b/((?:[^"\\]|\\.)*)"$', rest)
        return (_git_unquote(m.group(1)), _git_unquote(m.group(2))) if m else None
    if not rest.startswith("a/"):
        return None
    body = rest[2:]
    # A single greedy regex split picks one candidate " b/" occurrence,
    # which is wrong when the path itself contains that substring (e.g. a
    # directory literally named "foo b"). Try every occurrence instead and
    # take the one where both sides agree — identity is what resolves the
    # split for the common (non-rename) case, so trying all candidates
    # rather than assuming the regex's greedy pick is the only way to
    # actually make that heuristic correct.
    start = 0
    while True:
        idx = body.find(" b/", start)
        if idx == -1:
            return None
        a_path, b_path = body[:idx], body[idx + len(" b/"):]
        if a_path == b_path:
            return a_path, b_path
        start = idx + 1


# "diff --git a/X b/Y" appears once per file, for every change type. Unlike
# "+++ b/...", it doesn't go missing for a deleted file ("+++ /dev/null")
# or a 100%-similarity rename (which has no +++/--- lines at all).


def _added_lines_by_file(diff_text):
    """[(file_path, added_line_content), ...] — one entry per '+' line,
    excluding the '+++ b/...' file header itself."""
    result = []
    current_file = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            current_file = _file_header_path(line[len("+++ "):])
            continue
        if line.startswith("--- "):
            continue
        if line.startswith("+") and current_file:
            result.append((current_file, line[1:]))
    return result


def _changed_files(diff_text):
    files = []
    lines = diff_text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("diff --git "):
            continue
        paths = _diff_git_line_paths(line)
        if paths:
            b_path = paths[1]
        else:
            # Ambiguous bare rename/copy (differing, unquoted paths) —
            # resolve via the 'rename to'/'copy to' line git always
            # emits alongside a detected rename or copy.
            b_path = None
            for nxt in lines[i + 1:]:
                if nxt.startswith("diff --git "):
                    break
                m = _RENAME_OR_COPY_TO.match(nxt)
                if m:
                    b_path = _rename_target_path(m.group(1))
                    break
        if b_path and b_path not in files:
            files.append(b_path)
    return files


# ── look implementations ────────────────────────────────────────────

_DECL_PATTERNS = [
    re.compile(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
    re.compile(r"\bclass\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
    re.compile(r"\binterface\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
    re.compile(r"\btype\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*="),
    re.compile(r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*="),
]


def _look_added_lines(added, rule):
    """Count added lines matching rule['match']. where = files they're in."""
    if not rule.get("match"):
        return 0, [], None
    pattern = re.compile(rule["match"])
    count = 0
    where = []
    for file_path, content in added:
        if pattern.search(content):
            count += 1
            if file_path not in where:
                where.append(file_path)
    return count, where, None


def _look_changed_files_outside_declared(diff_text, declared_files, rule):
    changed = _changed_files(diff_text)
    extra = [f for f in changed if f not in declared_files]
    return len(extra), extra, extra


_TEST_DIR_NAMES = ("test", "tests", "spec", "specs", "__tests__")


def _looks_like_test_file(path):
    if re.search(r"(^|/)(test|tests|spec|specs|__tests__)(/|$)|\.(test|spec)\.", path):
        return True
    # Colocated Python/Go conventions: test_foo.py, foo_test.go. Kept as a
    # separate, basename-only check so a directory merely containing
    # "test" as part of a longer word (testing_utils.py) doesn't match.
    base = os.path.basename(path)
    return bool(re.match(r"^(test|spec)[_-]", base) or re.search(r"[_-](test|spec)\.[A-Za-z0-9]+$", base))


def _test_file_stem(path):
    base = re.sub(r"\.[A-Za-z0-9]+$", "", os.path.basename(path))
    base = re.sub(r"\.(test|spec)$", "", base)
    base = re.sub(r"^(test|spec)[_-]", "", base)
    base = re.sub(r"[_-](test|spec)$", "", base)
    return base


def _non_test_dirs(path):
    """Directory segments of path, excluding recognized test-directory
    names, so a flat top-level test root (test/, tests/, ...) and a
    per-module nested one (mypkg/tests/) both normalize the same way a
    project layout intends, without treating an unrelated directory that
    merely shares a file's basename stem (frontend/service.test.ts vs
    backend/service.py) as if it were that file's test."""
    return [p for p in os.path.dirname(path).split("/") if p and p.lower() not in _TEST_DIR_NAMES]


def _has_matching_test_change(source_path, changed_files):
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", os.path.basename(source_path))
    source_dirs = _non_test_dirs(source_path)
    for f in changed_files:
        if f == source_path:
            continue
        if not _looks_like_test_file(f):
            continue
        test_stem = _test_file_stem(f)
        # Either the test's stem matches the source exactly (test_foo.py,
        # foo.test.ts, foo_test.go), or the source's stem appears as one
        # whole hyphen/underscore-delimited word within a feature-named
        # test's stem (refund-retry.test.ts testing retry.ts) — a real
        # naming convention, not a stem-equality fit. Splitting on
        # separators (rather than substring search) keeps a raw
        # substring like "pay" from matching "repay.test.ts".
        if test_stem != stem and stem not in re.split(r"[-_]", test_stem):
            continue
        test_dirs = _non_test_dirs(f)
        # An empty test_dirs means a flat top-level test root (test/foo.test.ts
        # covers any src/**/foo.ts) — that wildcard only applies to the test
        # side. A root-level *source* file (empty source_dirs) does not mean
        # "any test file anywhere is mine"; it still has to actually match
        # test_dirs, same as any other source file.
        if not test_dirs or source_dirs == test_dirs:
            return True
    return False


def _look_changed_source_without_test_change(diff_text, rule):
    changed = _changed_files(diff_text)
    flagged = [
        f for f in changed
        if not _looks_like_test_file(f) and not _has_matching_test_change(f, changed)
    ]
    return len(flagged), flagged, flagged


def _look_changed_source_with_test_change(diff_text, rule):
    """Inverse of _look_changed_source_without_test_change: source files
    whose matching test also changed."""
    changed = _changed_files(diff_text)
    flagged = [
        f for f in changed
        if not _looks_like_test_file(f) and _has_matching_test_change(f, changed)
    ]
    return len(flagged), flagged, flagged


def _look_new_names_absent_from_spec(added, spec_file, rule):
    if not spec_file or not os.path.isfile(spec_file):
        return 0, [], None  # this rule's own input is missing — no signal, not an error

    with open(spec_file, "r", errors="ignore") as f:
        spec_text = f.read()

    names = []
    for _file_path, content in added:
        for pattern in _DECL_PATTERNS:
            for m in pattern.finditer(content):
                name = m.group(1)
                if name not in names:
                    names.append(name)

    missing = [n for n in names if not re.search(r"\b" + re.escape(n) + r"\b", spec_text)]
    return len(missing), [], missing


# ── driver ───────────────────────────────────────────────────────────

def _run_rule(rule, ctx):
    """Returns (count, where, list_items) for one rule."""
    look = rule.get("look")
    if look == "added-lines":
        return _look_added_lines(ctx["added"], rule)
    if look == "changed-files-outside-declared":
        return _look_changed_files_outside_declared(ctx["diff_text"], ctx["declared_files"], rule)
    if look == "changed-source-without-test-change":
        return _look_changed_source_without_test_change(ctx["diff_text"], rule)
    if look == "changed-source-with-test-change":
        return _look_changed_source_with_test_change(ctx["diff_text"], rule)
    if look == "new-names-absent-from-spec":
        return _look_new_names_absent_from_spec(ctx["added"], ctx["spec_file"], rule)
    raise ValueError(f"Unknown look type: {look}")


def _format_say(say, n, list_items):
    text = say.replace("{n}", str(n))
    if "{list}" in text:
        text = text.replace("{list}", ", ".join(list_items) if list_items else "(none)")
    return text


def diagnose(classes_yaml, diff_text, declared_files, spec_file=None):
    classes = _parse_classes_yaml(classes_yaml)
    added = _added_lines_by_file(diff_text)
    ctx = {
        "added": added,
        "diff_text": diff_text,
        "declared_files": declared_files,
        "spec_file": spec_file,
    }

    result = []
    for cls in classes:
        signals = []
        for rule in cls.get("rules", []):
            count, where, list_items = _run_rule(rule, ctx)
            if count > 0:
                signals.append({
                    "observed": _format_say(rule.get("say", ""), count, list_items),
                    "where": where,
                })
        result.append({"id": cls["id"], "title": cls.get("title", cls["id"]), "signals": signals})
    return result


def main():
    if len(sys.argv) not in (4, 5):
        print(f"Usage: {sys.argv[0]} <classes_yaml> <diff_file> <files_touched_json> [spec_file]", file=sys.stderr)
        sys.exit(2)

    classes_yaml, diff_file, files_touched_json = sys.argv[1:4]
    spec_file = sys.argv[4] if len(sys.argv) == 5 else None

    if not os.path.isfile(classes_yaml):
        print(f"Error: classes file not found: {classes_yaml}", file=sys.stderr)
        sys.exit(3)

    with open(diff_file, "r", errors="ignore") as f:
        diff_text = f.read()

    try:
        declared_files = json.loads(files_touched_json)
    except json.JSONDecodeError:
        declared_files = []

    try:
        classes = diagnose(classes_yaml, diff_text, declared_files, spec_file)
    except Exception as e:
        print(f"Error: could not parse classes file: {e}", file=sys.stderr)
        sys.exit(3)

    print(json.dumps({"classes": classes}))


if __name__ == "__main__":
    main()
