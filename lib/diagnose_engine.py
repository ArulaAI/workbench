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

    def _scalar(value):
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            return value[1:-1]
        return value

    with open(path, "r") as f:
        lines = f.readlines()

    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if stripped == "classes:" and indent == 0:
            continue

        if stripped.startswith("- id:") and indent == 2:
            if current_class is not None:
                classes.append(current_class)
            current_class = {"id": _scalar(stripped[len("- id:"):]), "title": "", "rules": []}
            current_rules = current_class["rules"]
            current_rule = None
            continue

        if stripped.startswith("title:") and current_class is not None and current_rule is None:
            current_class["title"] = _scalar(stripped[len("title:"):])
            continue

        if stripped == "rules:" and current_class is not None:
            continue

        if stripped.startswith("- look:"):
            current_rule = {"look": _scalar(stripped[len("- look:"):]), "match": None, "say": ""}
            current_rules.append(current_rule)
            continue

        if stripped.startswith("match:") and current_rule is not None:
            current_rule["match"] = _scalar(stripped[len("match:"):])
            continue

        if stripped.startswith("say:") and current_rule is not None:
            current_rule["say"] = _scalar(stripped[len("say:"):])
            continue

    if current_class is not None:
        classes.append(current_class)

    return classes


# ── diff parsing ───────────────────────────────────────────────────

_FILE_HEADER = re.compile(r"^\+\+\+ b/(.+)$")

# "diff --git a/X b/Y" appears once per file, for every change type. Unlike
# "+++ b/...", it doesn't go missing for a deleted file ("+++ /dev/null")
# or a 100%-similarity rename (which has no +++/--- lines at all).
_DIFF_GIT_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")


def _added_lines_by_file(diff_text):
    """[(file_path, added_line_content), ...] — one entry per '+' line,
    excluding the '+++ b/...' file header itself."""
    result = []
    current_file = None
    for line in diff_text.splitlines():
        m = _FILE_HEADER.match(line)
        if m:
            current_file = m.group(1)
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") and current_file:
            result.append((current_file, line[1:]))
    return result


def _changed_files(diff_text):
    files = []
    for line in diff_text.splitlines():
        m = _DIFF_GIT_HEADER.match(line)
        if m and m.group(2) not in files:
            files.append(m.group(2))
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


def _looks_like_test_file(path):
    return bool(re.search(r"(^|/)(test|tests|spec|specs|__tests__)(/|$)|\.(test|spec)\.", path))


def _test_file_stem(path):
    base = re.sub(r"\.[A-Za-z0-9]+$", "", os.path.basename(path))
    base = re.sub(r"\.(test|spec)$", "", base)
    base = re.sub(r"^(test|spec)[_-]", "", base)
    base = re.sub(r"[_-](test|spec)$", "", base)
    return base


def _has_matching_test_change(source_path, changed_files):
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", os.path.basename(source_path))
    for f in changed_files:
        if f == source_path:
            continue
        if not _looks_like_test_file(f):
            continue
        if _test_file_stem(f) == stem:
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
