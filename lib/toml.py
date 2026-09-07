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

A missing file emits nothing and exits 0, so every default applies. A file
that exists but cannot be parsed is a configuration error instead: the parser
detail goes to stderr and the exit status is 3, which lib/config.sh turns into
an aborted command rather than a silent fall back to defaults.
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


def _hand_parse(path: str) -> dict:
    """Minimal TOML parser for the flat structure speed.toml uses.

    Supports:
    - [section] and [section.subsection] headers
    - key = "value" assignments (string values only)
    - # comments and blank lines
    - Ignores commented-out lines (# key = "value")
    """
    data: dict = {}
    current_section: list[str] = []

    with open(path, "r") as f:
        for line in f:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Section header
            if line.startswith("[") and line.endswith("]"):
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
                value = value.strip()

                # Strip quotes
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]

                # Navigate to current section
                d = data
                for part in current_section:
                    d = d.setdefault(part, {})
                d[key] = value

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

    # [skills] section — independent from [agent].provider. The provider
    # selects the execution backend; harnesses select skill projection roots.
    skills = data.get("skills", {})
    if isinstance(skills, dict):
        val = skills.get("harnesses")
        if val is not None:
            if isinstance(val, list):
                joined = " ".join(str(item) for item in val)
            else:
                joined = str(val)
            print(f"TOML_SKILLS_HARNESSES='{shell_escape(joined)}'")

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
        # The shell owns user-facing context and severity. Emit only the parser
        # detail so it can produce one message rather than nesting prefixes.
        print(str(e), file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
