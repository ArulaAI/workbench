#!/usr/bin/env python3
"""Pre-plan spec grounding: verify spec claims against actual codebase.

Parses a spec markdown file for file paths and table definitions, then
compares them against the real codebase. Extracts structural context
(class names, fields, function signatures) from directories declared in
the agent file so the architect gets grounded context without full file reads.

Runs before the architect so discrepancies surface BEFORE they cascade
into task descriptions and generated code.

Usage:
    python3 spec_ground.py <spec_file> <project_root>

Output: JSON with {warnings, codebase_context, stats}
Exit code: 0 always (warnings inform, they don't block planning)
"""

import json
import os
import re
import sys


# ── Spec parsing ─────────────────────────────────────────────────


def parse_spec_tables(spec_content):
    """Extract table definitions from markdown spec tables.

    Looks for:
        ### `table_name`
        | Column | Type | Constraints | Notes |
        |--------|------|-------------|-------|
        | col1   | TYPE | ...         | ...   |

    Returns: {table_name: {columns: {col_name: {type: str}}}}
    """
    tables = {}
    current_table = None
    in_table = False
    separator_seen = False

    for line in spec_content.split("\n"):
        # Match ### `table_name`
        m = re.match(r"^###\s+`(\w+)`", line)
        if m:
            current_table = m.group(1)
            tables[current_table] = {"columns": {}}
            in_table = False
            separator_seen = False
            continue

        if current_table is None:
            continue

        # Match table header row: | Column | Type | ...
        if not in_table and re.match(r"^\|\s*Column\s*\|", line, re.IGNORECASE):
            in_table = True
            separator_seen = False
            continue

        # Skip separator row: |---|---|...|
        if in_table and not separator_seen and re.match(r"^\|[-|\s:]+\|$", line):
            separator_seen = True
            continue

        # Parse data rows
        if in_table and separator_seen and line.startswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 2:
                col_name = cells[0].strip()
                col_type = cells[1].strip()
                if col_name and not col_name.startswith("-"):
                    tables[current_table]["columns"][col_name] = {"type": col_type}
            continue

        # End of table on non-empty, non-table line
        if in_table and separator_seen and not line.startswith("|"):
            if line.strip() == "":
                continue  # blank lines within table section OK
            in_table = False
            current_table = None

    return tables


def parse_spec_file_paths(spec_content):
    """Extract file paths mentioned in the spec.

    Finds backtick-wrapped paths and Python comment paths.
    Returns: set of path strings
    """
    paths = set()

    # Backtick-wrapped paths starting with known directories
    for m in re.finditer(r"`((?:src|app|migrations|speed)/[^`\s]+)`", spec_content):
        paths.add(m.group(1))

    # Python comment paths: # app/models/foo.py
    for m in re.finditer(r"#\s+(app/[^\s(]+\.py)", spec_content):
        paths.add(m.group(1))

    return paths


# ── Agent file directory parsing ──────────────────────────────────


def parse_agent_file_dirs(project_root):
    """Parse the agent file's File Organization section for declared directories.

    Reads the agent file, finds ### File Organization section
    (bounded by next ##/### heading), extracts backtick-wrapped paths
    ending with '/'.

    Frontend path fallback: if a path starting with src/frontend/ doesn't
    exist, tries src/frontend/src/{suffix}.

    Returns: [(label, resolved_abs_path)] in declaration order.
    Only paths that resolve to existing directories.
    Returns [] if agent file missing or section absent.
    """
    agent_file = os.path.join(project_root, os.environ.get("SPEED_AGENT_FILE") or "CLAUDE.md")
    try:
        with open(agent_file) as f:
            content = f.read()
    except OSError:
        return []

    # Find ### File Organization section
    section_match = re.search(
        r"^### File Organization\s*\n(.*?)(?=^##|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not section_match:
        return []

    section = section_match.group(1)

    dirs = []
    for m in re.finditer(r"`([^`]+/)`", section):
        rel_path = m.group(1)
        abs_path = os.path.join(project_root, rel_path)

        if os.path.isdir(abs_path):
            dirs.append((rel_path, abs_path))
        elif rel_path.startswith("src/frontend/"):
            # Fallback: src/frontend/X/ -> src/frontend/src/X/
            suffix = rel_path[len("src/frontend/"):]
            fallback = os.path.join(project_root, "src", "frontend", "src", suffix)
            if os.path.isdir(fallback):
                dirs.append((rel_path, fallback))

    return dirs


# ── Structural extraction ────────────────────────────────────────


# Python structural patterns
_PY_PATTERNS = [
    re.compile(r"^from\s"),
    re.compile(r"^import\s"),
    re.compile(r"^class \w+"),
    re.compile(r"^\s+__tablename__"),
    re.compile(r"^\s+\w+: Mapped\["),
    re.compile(r"^\s+\w+:\s+\S"),
    re.compile(r"^\s+def \w+\("),
    re.compile(r"^\w+\s*=\s*Table\("),
    re.compile(r"^@strawberry\.(type|input|enum)"),
]

# TypeScript structural patterns
_TS_PATTERNS = [
    re.compile(r"^import\s"),
    re.compile(r"""^['"]use (client|server)"""),
    re.compile(r"^export\s"),
    re.compile(r"""^\s+\w+\??\s*:\s*[\w\["']"""),
]


def extract_structural_lines(filepath):
    """Extract structural lines from a single file based on extension.

    Returns only lines that match language-aware structural patterns
    (class names, fields, function signatures, imports, exports).
    Returns [] for unrecognized extensions or read errors.
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".py":
        patterns = _PY_PATTERNS
    elif ext in (".ts", ".tsx"):
        patterns = _TS_PATTERNS
    else:
        return []

    try:
        with open(filepath) as f:
            lines = f.readlines()
    except OSError:
        return []

    result = []
    for line in lines:
        stripped = line.rstrip("\n")
        for pat in patterns:
            if pat.search(stripped):
                result.append(stripped)
                break

    return result


# ── Project tree ─────────────────────────────────────────────────

_TREE_EXCLUDE = {
    ".git", "node_modules", "__pycache__", "dist", ".next",
    "venv", ".venv", ".speed", ".claude", ".ruff_cache",
    ".pytest_cache", ".egg-info",
}


def build_project_tree(project_root, max_depth=3):
    """Build an indented tree of the project structure.

    Excludes common non-source directories. Dirs listed before files,
    alphabetical within each group. ~300-500 tokens.
    """
    lines = []

    def _walk(path, depth, prefix=""):
        if depth > max_depth:
            return

        try:
            entries = sorted(os.listdir(path))
        except OSError:
            return

        dirs = []
        files = []
        for e in entries:
            if e.startswith("."):
                continue
            if e in _TREE_EXCLUDE:
                continue
            if e.endswith(".egg-info"):
                continue
            full = os.path.join(path, e)
            if os.path.isdir(full):
                dirs.append(e)
            else:
                files.append(e)

        for d in dirs:
            lines.append(f"{prefix}{d}/")
            _walk(os.path.join(path, d), depth + 1, prefix + "  ")

        for f in files:
            lines.append(f"{prefix}{f}")

    _walk(project_root, 0)
    return "\n".join(lines)


# ── Codebase scanning ────────────────────────────────────────────


def scan_declared_dirs(project_root, declared_dirs):
    """Walk each declared directory and return files organized by label.

    Args:
        project_root: project root path
        declared_dirs: [(label, abs_path)] from parse_agent_file_dirs

    Returns: {label: [relative_paths]}
    """
    result = {}

    for label, abs_dir in declared_dirs:
        files = []
        for root, dirs, filenames in os.walk(abs_dir, followlinks=False):
            dirs[:] = [
                d for d in dirs
                if d not in _TREE_EXCLUDE and not d.startswith(".")
            ]
            for fname in sorted(filenames):
                if fname.startswith(".") or fname.endswith(".pyc"):
                    continue
                rel_path = os.path.relpath(os.path.join(root, fname), project_root)
                files.append(rel_path)
        if files:
            result[label] = files

    return result


# ── Comparison ───────────────────────────────────────────────────


def compare_spec_with_codebase(spec_tables, spec_paths, project_root):
    """Compare spec claims against actual codebase. Returns list of warnings."""
    warnings = []

    # ── 1. Spec table declarations (informational) ───────────────
    for table_name in spec_tables:
        warnings.append({
            "type": "spec_table",
            "severity": "info",
            "table": table_name,
            "message": f"Spec declares table '{table_name}' with {len(spec_tables[table_name]['columns'])} columns",
        })

    # ── 2. File path checks ─────────────────────────────────────
    for path in sorted(spec_paths):
        found = False
        for base in [
            project_root,
            os.path.join(project_root, "src", "backend"),
            os.path.join(project_root, "src", "frontend"),
        ]:
            full = os.path.join(base, path)
            if os.path.exists(full):
                found = True
                break
        if not found:
            warnings.append({
                "type": "path_not_found",
                "severity": "warn",
                "path": path,
                "message": f"Path '{path}' in spec does not exist on disk",
            })

    return warnings


# ── Context builder ──────────────────────────────────────────────


def build_codebase_context(project_root, project_files, token_budget=10000):
    """Build a text block describing what actually exists in the codebase.

    Includes a project tree and structural extracts from declared dirs.
    Token budget controls how much structural detail is included before
    degrading to filename-only listings.
    """
    lines = [
        "## Codebase Reality (auto-generated by spec grounding)",
        "",
        "Use this as the source of truth for what already exists. "
        "If the spec contradicts this section, trust this section.",
        "",
    ]

    # Project tree
    tree = build_project_tree(project_root)
    tree_section = ["### Project Structure", "", tree, ""]
    tree_text = "\n".join(tree_section)
    tree_cost = len(tree_text) // 4
    remaining = token_budget - tree_cost

    lines.extend(tree_section)
    lines.append("### Source Files by Directory")
    lines.append("")

    if not project_files:
        lines.append(f"(no source directories declared in {os.environ.get('SPEED_AGENT_FILE') or 'agent file'})")
        lines.append("")
        return "\n".join(lines)

    # Emit directories in insertion order (agent file declaration order)
    for label, files in project_files.items():
        lines.append(f"**{label}** ({len(files)} files)")

        for fpath in files:
            abs_path = os.path.join(project_root, fpath)
            structural = extract_structural_lines(abs_path)
            file_block = [f"--- {fpath} ---"]
            file_block.extend(structural)
            file_text = "\n".join(file_block)
            file_cost = len(file_text) // 4

            if structural and remaining >= file_cost:
                lines.extend(file_block)
                remaining -= file_cost
            else:
                # Degrade to filename-only
                lines.append(f"  - `{fpath}`")

        lines.append("")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────


def main():
    if len(sys.argv) != 3:
        print(json.dumps({"error": f"Usage: {sys.argv[0]} <spec_file> <project_root>"}))
        sys.exit(2)

    spec_file = sys.argv[1]
    project_root = sys.argv[2]

    try:
        with open(spec_file) as f:
            spec_content = f.read()
    except OSError as e:
        print(json.dumps({"error": f"Cannot read spec: {e}"}))
        sys.exit(2)

    # ── Scan codebase ────────────────────────────────────────────
    declared_dirs = parse_agent_file_dirs(project_root)
    project_files = scan_declared_dirs(project_root, declared_dirs)

    # ── Parse spec claims ────────────────────────────────────────
    spec_tables = parse_spec_tables(spec_content)
    spec_paths = parse_spec_file_paths(spec_content)

    # ── Compare ──────────────────────────────────────────────────
    warnings = compare_spec_with_codebase(spec_tables, spec_paths, project_root)

    # ── Build context ────────────────────────────────────────────
    try:
        token_budget = int(os.environ.get("SPEC_GROUND_TOKEN_BUDGET", "10000"))
    except (ValueError, TypeError):
        token_budget = 10000

    codebase_context = build_codebase_context(project_root, project_files, token_budget)

    # ── Output ───────────────────────────────────────────────────
    errors = len([w for w in warnings if w["severity"] == "error"])
    warns = len([w for w in warnings if w["severity"] == "warn"])
    infos = len([w for w in warnings if w["severity"] == "info"])

    output = {
        "warnings": warnings,
        "codebase_context": codebase_context,
        "stats": {
            "spec_tables": len(spec_tables),
            "declared_dirs": len(declared_dirs),
            "errors": errors,
            "warnings": warns,
            "infos": infos,
        },
    }

    print(json.dumps(output))
    sys.exit(0)  # Always 0 — warnings inform, they don't block


if __name__ == "__main__":
    main()
