#!/usr/bin/env python3
"""
toml.py — Read speed.toml and emit shell-eval-safe variable assignments.

Usage: python3 toml.py <path-to-speed.toml>

Output (stdout):
    TOML_AGENT_PROVIDER='claude-code'
    TOML_AGENT_PLANNING_MODEL='opus'
    TOML_WORKTREE_SYMLINKS='src/frontend/node_modules:src/frontend/node_modules ...'
    TOML_SUBSYSTEMS='frontend:src/frontend/** backend:src/backend/**'
    TOML_SPECS_VISION_FILE='specs/product/overview.md'

If the file cannot be parsed, emits nothing (exit 0). All defaults apply.
"""

import sys
import os


def parse_toml(path: str) -> dict:
    """Parse a TOML file using the best available method."""
    # 1. tomllib (Python 3.11+ stdlib)
    try:
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        pass

    # 2. tomli (pip package, same API)
    try:
        import tomli
        with open(path, "rb") as f:
            return tomli.load(f)
    except ImportError:
        pass

    # 3. Minimal hand-parser for flat key=value TOML
    return _hand_parse(path)


def _strip_comment(text: str) -> str:
    """Drop a trailing # comment that sits outside any string.

    Comments were only recognised on whole lines. An inline comment on an
    interior array item swallowed every later item, and a trailing comment
    containing "]" produced a bogus "]" element that then ran as a command.
    """
    quote, i = None, 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return text[:i].rstrip()
        i += 1
    return text


def _array_complete(text: str) -> bool:
    """True once an array opened in text has been closed outside of a string."""
    depth, quote, i = 0, None, 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return True
        i += 1
    return False


def _split_array(text: str) -> list[str]:
    """Items of a TOML array of scalars. A quoted item keeps its spaces.

    Without this, an array reached the emitter as the literal text
    '["pytest -q", "npm test"]', which then ran as a shell command.
    """
    items: list[str] = []
    buf, quote, started, i = "", None, False, 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < len(text):
                buf += text[i + 1]
                i += 2
                continue
            if ch == quote:
                quote, started = None, False
                items.append(buf)
                buf = ""
            else:
                buf += ch
        elif ch in "\"'":
            quote, started, buf = ch, True, ""
        elif ch == ",":
            if started and buf.strip():
                items.append(buf.strip())
            buf, started = "", False
        elif ch == "#":
            break
        elif not ch.isspace() or started:
            buf += ch
            started = True
        i += 1
    if started and buf.strip():
        items.append(buf.strip())
    return items


def _hand_parse(path: str) -> dict:
    """Minimal TOML parser for the flat structure speed.toml uses.

    Supports:
    - [section] and [section.subsection] headers
    - key = "value" assignments
    - key = ["a", "b"] arrays, including ones spanning several lines
    - # comments and blank lines
    - Ignores commented-out lines (# key = "value")
    """
    data: dict = {}
    current_section: list[str] = []

    with open(path, "r") as f:
        lines = f.read().splitlines()

    index = 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Section header
        if line.startswith("[") and line.endswith("]") and "=" not in line:
            header = line[1:-1].strip()
            current_section = header.split(".")
            # Ensure nested dicts exist
            d = data
            for part in current_section:
                d = d.setdefault(part, {})
            continue

        # Key = value
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = _strip_comment(value).strip()

            parsed: object
            if value.startswith("["):
                while not _array_complete(value) and index < len(lines):
                    value += " " + _strip_comment(lines[index].strip())
                    index += 1
                if not _array_complete(value):
                    raise ValueError(f"Unterminated array for key '{key}' in {path}")
                parsed = _split_array(value[value.index("[") + 1:value.rindex("]")])
            else:
                # Strip quotes
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                parsed = value

            # Navigate to current section
            d = data
            for part in current_section:
                d = d.setdefault(part, {})
            d[key] = parsed

    return data


def shell_escape(value: str) -> str:
    """Escape a value for safe shell eval (single-quoted)."""
    return value.replace("'", "'\\''")


def emit(data: dict) -> None:
    """Emit shell-eval-safe variable assignments to stdout."""
    # [agent] section
    agent = data.get("agent", {})
    if isinstance(agent, dict):
        for key in ("provider", "planning_model", "support_model", "cli_command", "ollama_base_url", "timeout", "max_turns"):
            val = agent.get(key)
            if val is not None:
                var_name = f"TOML_AGENT_{key.upper()}"
                print(f"{var_name}='{shell_escape(str(val))}'")
        for key in ("cli_models", "api_providers", "ceremony_models"):
            val = agent.get(key)
            if val is not None:
                if isinstance(val, list):
                    joined = " ".join(str(item) for item in val)
                else:
                    joined = str(val)
                var_name = f"TOML_AGENT_{key.upper()}"
                print(f"{var_name}='{shell_escape(joined)}'")

    # [project] section
    project = data.get("project", {})
    if isinstance(project, dict):
        val = project.get("agents_file")
        if val is not None:
            print(f"TOML_PROJECT_AGENT_FILE='{shell_escape(str(val))}'")

    # [worktree.symlinks] section — emit as space-separated key:value pairs
    worktree = data.get("worktree", {})
    if isinstance(worktree, dict):
        symlinks = worktree.get("symlinks", {})
        if isinstance(symlinks, dict) and symlinks:
            pairs = " ".join(f"{k}:{v}" for k, v in symlinks.items())
            print(f"TOML_WORKTREE_SYMLINKS='{shell_escape(pairs)}'")

    # [subsystems] section — emit as space-separated name:glob pairs
    subsystems = data.get("subsystems", {})
    if isinstance(subsystems, dict) and subsystems:
        pairs = []
        for name, globs in subsystems.items():
            if isinstance(globs, list):
                # Multiple globs per subsystem — join with comma
                pairs.append(f"{name}:{','.join(globs)}")
            else:
                pairs.append(f"{name}:{globs}")
        print(f"TOML_SUBSYSTEMS='{shell_escape(' '.join(pairs))}'")

    # [specs] section
    specs = data.get("specs", {})
    if isinstance(specs, dict):
        for key in ("vision_file", "auto_derive_siblings"):
            val = specs.get(key)
            if val is not None:
                var_name = f"TOML_SPECS_{key.upper()}"
                print(f"{var_name}='{shell_escape(str(val))}'")

    # [ui] section
    ui = data.get("ui", {})
    if isinstance(ui, dict):
        for key in ("theme", "ascii", "verbosity"):
            val = ui.get(key)
            if val is not None:
                var_name = f"TOML_UI_{key.upper()}"
                # Normalize verbosity names to numeric values
                if key == "verbosity":
                    verbosity_map = {"quiet": "0", "normal": "1", "verbose": "2", "debug": "3"}
                    val = verbosity_map.get(str(val).lower(), str(val))
                print(f"{var_name}='{shell_escape(str(val))}'")


    # [security] section
    security = data.get("security", {})
    if isinstance(security, dict):
        for key in ("sast_cmd", "sca_cmd", "severity_threshold"):
            val = security.get(key)
            if val is not None:
                var_name = f"TOML_SECURITY_{key.upper()}"
                print(f"{var_name}='{shell_escape(str(val))}'")
        for key in ("secrets_patterns", "secrets_exclude"):
            val = security.get(key)
            if val is not None:
                if isinstance(val, list):
                    joined = " ".join(str(item) for item in val)
                else:
                    joined = str(val)
                var_name = f"TOML_SECURITY_{key.upper()}"
                print(f"{var_name}='{shell_escape(joined)}'")

    # [context] section
    context = data.get("context", {})
    if isinstance(context, dict):
        for key in ("related_spec_budget", "related_spec_threshold", "related_spec_candidate_cap"):
            val = context.get(key)
            if val is not None:
                var_name = f"TOML_CONTEXT_{key.upper()}"
                print(f"{var_name}='{shell_escape(str(val))}'")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <speed.toml>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.isfile(path):
        # No config file — emit nothing, all defaults apply
        sys.exit(0)

    try:
        data = parse_toml(path)
        emit(data)
    except Exception as e:
        # Parse failure — emit nothing, all defaults apply
        print(f"Warning: could not parse {path}: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
