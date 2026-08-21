"""Phase 0: Config file reading and convention extraction.

Scans the project root for 16 supported config file types and maps
their rules to ConventionEntry objects with confidence='established'
and source='config'.

Missing files are silently skipped. Empty files produce no entries.
Malformed content logs a warning and returns no entries for that file.
"""

import configparser
import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from lib.learn.conventions import ConventionEntry

# tomllib is in stdlib as of Python 3.11; fall back to tomli for older versions
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            tomllib = None  # type: ignore[assignment]

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ── ID and entry helpers ──────────────────────────────────────────────


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _entry(
    config_file: Path,
    key: str,
    convention: str,
    tags: list[str],
    scope: list[str] | None = None,
) -> ConventionEntry:
    stem = _slug(config_file.name.lstrip(".") or config_file.name)
    entry_id = f"conv-{stem}-{_slug(key)}"[:80]
    return ConventionEntry(
        id=entry_id,
        convention=convention,
        scope=scope or ["."],
        confidence="established",
        canonical_example=str(config_file),
        exceptions=None,
        evolution=None,
        tags=tags,
        evidence={"config_file": str(config_file)},
        source="config",
    )


def _collect(
    out: list[ConventionEntry],
    path: Path,
    parser,
) -> None:
    """Call parser on path and append results to out. Skip if file absent."""
    if not path.exists():
        return
    out.extend(parser(path))


# ── Per-config parsers ────────────────────────────────────────────────


def _parse_editorconfig(path: Path) -> list[ConventionEntry]:
    """Parse .editorconfig for indent_style, indent_size, charset, etc."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    entries: list[ConventionEntry] = []
    section = "*"

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            section = line[1:line.find("]")] if "]" in line else line[1:]
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip().lower(), v.strip().lower()
        scope = [section] if section != "*" else ["."]
        # Include section in key so multiple sections produce distinct IDs
        key_id = f"{k}_{section}"

        if k == "indent_style":
            style = "spaces" if v == "space" else "tabs"
            entries.append(_entry(
                path, key_id,
                f"Use {style} for indentation",
                ["formatting", "indentation"], scope,
            ))
        elif k == "indent_size":
            unit = "space" if v == "1" else "spaces"
            entries.append(_entry(
                path, key_id,
                f"Indent with {v} {unit}",
                ["formatting", "indentation"], scope,
            ))
        elif k == "charset":
            entries.append(_entry(
                path, key_id,
                f"Use {v.upper()} file encoding",
                ["formatting", "encoding"], scope,
            ))
        elif k == "trim_trailing_whitespace" and v == "true":
            entries.append(_entry(
                path, key_id,
                "Trim trailing whitespace",
                ["formatting", "whitespace"], scope,
            ))
        elif k == "insert_final_newline" and v == "true":
            entries.append(_entry(
                path, key_id,
                "Insert final newline at end of file",
                ["formatting", "whitespace"], scope,
            ))

    return entries


def _parse_pyproject_toml(path: Path) -> list[ConventionEntry]:
    """Parse pyproject.toml [tool.ruff], [tool.black], [tool.pylint] sections."""
    if tomllib is None:
        logging.warning("tomllib unavailable, skipping %s", path)
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    try:
        data = tomllib.loads(text)
    except Exception as e:
        logging.warning("Failed to parse %s: %s", path, e)
        return []

    entries: list[ConventionEntry] = []
    tool = data.get("tool", {}) if isinstance(data, dict) else {}

    # [tool.ruff]
    ruff = tool.get("ruff", {})
    if ruff:
        select = ruff.get("select", [])
        if isinstance(select, str):
            select = [select]
        if "I" in select:
            entries.append(_entry(
                path, "ruff-import-ordering",
                "Enforce import ordering (isort via ruff)",
                ["imports", "ordering"],
            ))
        if "N" in select:
            entries.append(_entry(
                path, "ruff-naming",
                "Enforce PEP 8 naming conventions",
                ["naming"],
            ))
        if any(c in select for c in ("E", "W")):
            entries.append(_entry(
                path, "ruff-pep8",
                "Enforce PEP 8 style rules",
                ["style"],
            ))

        line_length = ruff.get("line-length") or ruff.get("line_length")
        if line_length:
            entries.append(_entry(
                path, "ruff-line-length",
                f"Maximum line length of {line_length} characters",
                ["formatting", "line-length"],
            ))

        # Banned imports
        banned = ruff.get("banned-imports") or ruff.get("banned_imports") or []
        if banned:
            entries.append(_entry(
                path, "ruff-banned-imports",
                f"Banned imports: {', '.join(str(b) for b in banned[:5])}",
                ["imports"],
            ))

        isort = ruff.get("isort", {})
        kfp = isort.get("known-first-party") or isort.get("known_first_party", [])
        if kfp:
            entries.append(_entry(
                path, "ruff-isort-first-party",
                f"First-party import namespaces: {', '.join(str(k) for k in kfp)}",
                ["imports", "ordering"],
            ))

    # [tool.black]
    black = tool.get("black", {})
    if black:
        line_length = black.get("line-length") or black.get("line_length")
        if line_length:
            entries.append(_entry(
                path, "black-line-length",
                f"Maximum line length of {line_length} characters",
                ["formatting", "line-length"],
            ))
        sn = black.get("string-normalization") or black.get("string_normalization")
        if sn is False:
            entries.append(_entry(
                path, "black-no-string-normalization",
                "Do not normalize string quotes (black)",
                ["formatting", "quotes"],
            ))
        tv = black.get("target-version") or black.get("target_version")
        if tv:
            vs = tv if isinstance(tv, list) else [tv]
            entries.append(_entry(
                path, "black-target-version",
                f"Target Python version: {', '.join(str(v) for v in vs)}",
                ["compatibility"],
            ))

    # [tool.pylint]
    pylint = tool.get("pylint", {})
    if pylint:
        max_line = (
            pylint.get("format", {}).get("max-line-length")
            or pylint.get("format", {}).get("max_line_length")
        )
        if max_line:
            entries.append(_entry(
                path, "pylint-max-line-length",
                f"Maximum line length of {max_line} characters",
                ["formatting", "line-length"],
            ))
        disable = (
            pylint.get("messages_control", {}).get("disable", [])
            or pylint.get("disable", [])
        )
        if disable:
            entries.append(_entry(
                path, "pylint-disable",
                f"Disable {len(disable)} pylint rule(s)",
                ["linting"],
            ))

    return entries


def _parse_flake8_style(path: Path, section: str = "flake8") -> list[ConventionEntry]:
    """Parse .flake8 or setup.cfg [flake8] section via configparser."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    config = configparser.ConfigParser()
    try:
        config.read_string(text)
    except Exception as e:
        logging.warning("Failed to parse %s: %s", path, e)
        return []

    if not config.has_section(section):
        return []

    entries: list[ConventionEntry] = []
    fl = dict(config[section])

    max_line = fl.get("max-line-length") or fl.get("max_line_length")
    if max_line:
        entries.append(_entry(
            path, f"{section}-max-line-length",
            f"Maximum line length of {max_line.strip()} characters",
            ["formatting", "line-length"],
        ))

    ignore_val = fl.get("extend-ignore") or fl.get("extend_ignore") or fl.get("ignore")
    if ignore_val:
        codes = [c.strip() for c in re.split(r"[,\s]+", ignore_val) if c.strip()]
        if codes:
            entries.append(_entry(
                path, f"{section}-ignored-rules",
                f"Ignore flake8 rules: {', '.join(codes[:5])}",
                ["linting"],
            ))

    per_file = fl.get("per-file-ignores") or fl.get("per_file_ignores")
    if per_file:
        entries.append(_entry(
            path, f"{section}-per-file-ignores",
            "Apply per-file flake8 rule overrides",
            ["linting"],
        ))

    return entries


def _eslint_severity(val) -> str:
    if val in (0, "off"):
        return "off"
    if isinstance(val, list) and val and val[0] in (0, "off"):
        return "off"
    return "on"


def _parse_eslint(path: Path) -> list[ConventionEntry]:
    """Parse ESLint config files (JSON, YAML, or JS with comments stripped)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    data = None
    # Try JSON first
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try YAML (handles .yaml/.yml and JSON supersets)
    if data is None and _YAML_AVAILABLE:
        try:
            data = _yaml.safe_load(text)
        except Exception:
            pass

    # Try stripping JS comments and re-parsing as JSON
    if data is None:
        stripped = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
        stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL)
        try:
            data = json.loads(stripped)
        except Exception as e:
            logging.warning("Failed to parse %s: %s", path, e)
            return []

    if not isinstance(data, dict):
        return []

    entries: list[ConventionEntry] = []
    rules = data.get("rules", {}) if isinstance(data.get("rules"), dict) else {}

    naming_rules = {
        "@typescript-eslint/naming-convention",
        "camelcase",
        "id-match",
        "naming-convention",
    }
    for rule_name in naming_rules:
        if rule_name in rules and _eslint_severity(rules[rule_name]) != "off":
            entries.append(_entry(
                path, f"eslint-{_slug(rule_name)}",
                f"Enforce naming conventions ({rule_name})",
                ["naming"],
            ))

    import_rules = {
        "import/order": "import ordering",
        "import/no-cycle": "no circular imports",
        "import/no-unresolved": "no unresolved imports",
        "no-restricted-imports": "restrict certain imports",
    }
    for rule_name, desc in import_rules.items():
        if rule_name in rules and _eslint_severity(rules[rule_name]) != "off":
            entries.append(_entry(
                path, f"eslint-{_slug(rule_name)}",
                f"Enforce {desc}",
                ["imports"],
            ))

    if "no-console" in rules and _eslint_severity(rules["no-console"]) != "off":
        entries.append(_entry(
            path, "eslint-no-console",
            "Ban console statements",
            ["style"],
        ))

    parser_val = data.get("parser")
    if parser_val and isinstance(parser_val, str):
        entries.append(_entry(
            path, "eslint-parser",
            f"Use {parser_val} as ESLint parser",
            ["tooling"],
        ))

    return entries


def _parse_prettierrc(path: Path) -> list[ConventionEntry]:
    """Parse .prettierrc and prettier.config.* (JSON or YAML)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        if _YAML_AVAILABLE:
            try:
                data = _yaml.safe_load(text)
            except Exception as e:
                logging.warning("Failed to parse %s: %s", path, e)
                return []
        else:
            logging.warning("Failed to parse %s: invalid JSON and yaml unavailable", path)
            return []

    if not isinstance(data, dict):
        return []

    entries: list[ConventionEntry] = []

    if "singleQuote" in data:
        q = "single" if data["singleQuote"] else "double"
        entries.append(_entry(
            path, "prettier-quote-style",
            f"Use {q} quotes",
            ["formatting", "quotes"],
        ))

    if "semi" in data:
        desc = "required" if data["semi"] else "omit"
        entries.append(_entry(
            path, "prettier-semi",
            f"Semicolons: {desc}",
            ["formatting", "style"],
        ))

    if "tabWidth" in data:
        entries.append(_entry(
            path, "prettier-tab-width",
            f"Indent with {data['tabWidth']} spaces",
            ["formatting", "indentation"],
        ))

    if "useTabs" in data:
        style = "tabs" if data["useTabs"] else "spaces"
        entries.append(_entry(
            path, "prettier-use-tabs",
            f"Use {style} for indentation",
            ["formatting", "indentation"],
        ))

    if "trailingComma" in data:
        entries.append(_entry(
            path, "prettier-trailing-comma",
            f"Trailing commas: {data['trailingComma']}",
            ["formatting", "style"],
        ))

    if "printWidth" in data:
        entries.append(_entry(
            path, "prettier-print-width",
            f"Maximum line length of {data['printWidth']} characters",
            ["formatting", "line-length"],
        ))

    return entries


def _parse_biome_json(path: Path) -> list[ConventionEntry]:
    """Parse biome.json for formatter and linter config."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logging.warning("Failed to parse %s: %s", path, e)
        return []

    if not isinstance(data, dict):
        return []

    entries: list[ConventionEntry] = []
    formatter = data.get("formatter", {})

    if isinstance(formatter, dict) and formatter.get("enabled") is not False:
        indent_style = formatter.get("indentStyle")
        if indent_style:
            style = "spaces" if indent_style == "space" else "tabs"
            entries.append(_entry(
                path, "biome-indent-style",
                f"Use {style} for indentation",
                ["formatting", "indentation"],
            ))

        indent_width = formatter.get("indentWidth") or formatter.get("indentSize")
        if indent_width is not None:
            entries.append(_entry(
                path, "biome-indent-width",
                f"Indent with {indent_width} spaces",
                ["formatting", "indentation"],
            ))

        line_width = formatter.get("lineWidth") or formatter.get("printWidth")
        if line_width is not None:
            entries.append(_entry(
                path, "biome-line-width",
                f"Maximum line length of {line_width} characters",
                ["formatting", "line-length"],
            ))

    linter = data.get("linter", {})
    if isinstance(linter, dict) and linter.get("enabled", True):
        rules = linter.get("rules", {})
        if isinstance(rules, dict) and rules.get("recommended"):
            entries.append(_entry(
                path, "biome-recommended-rules",
                "Enable biome recommended lint rules",
                ["linting"],
            ))

    return entries


def _parse_tsconfig(path: Path) -> list[ConventionEntry]:
    """Parse tsconfig.json for strict mode, path aliases, and module resolution."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    # tsconfig allows JS-style comments
    stripped = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
    stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL)
    try:
        data = json.loads(stripped)
    except Exception as e:
        logging.warning("Failed to parse %s: %s", path, e)
        return []

    if not isinstance(data, dict):
        return []

    entries: list[ConventionEntry] = []
    opts = data.get("compilerOptions", {}) if isinstance(data.get("compilerOptions"), dict) else {}

    if opts.get("strict"):
        entries.append(_entry(
            path, "tsconfig-strict",
            "Enable TypeScript strict mode",
            ["type-safety", "typescript"],
        ))

    if opts.get("noImplicitAny"):
        entries.append(_entry(
            path, "tsconfig-no-implicit-any",
            "Disallow implicit 'any' types",
            ["type-safety", "typescript"],
        ))

    paths = opts.get("paths")
    if isinstance(paths, dict) and paths:
        entries.append(_entry(
            path, "tsconfig-path-aliases",
            f"Define {len(paths)} TypeScript path alias(es)",
            ["imports", "typescript"],
        ))

    module = opts.get("module")
    if module:
        entries.append(_entry(
            path, "tsconfig-module",
            f"Use {module} module resolution",
            ["typescript"],
        ))

    target = opts.get("target")
    if target:
        entries.append(_entry(
            path, "tsconfig-target",
            f"Compile to {target} JavaScript",
            ["compatibility", "typescript"],
        ))

    return entries


def _parse_golangci(path: Path) -> list[ConventionEntry]:
    """Parse .golangci.yml for enabled/disabled linters and settings."""
    if not _YAML_AVAILABLE:
        logging.warning("PyYAML not available, skipping %s", path)
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    try:
        data = _yaml.safe_load(text)
    except Exception as e:
        logging.warning("Failed to parse %s: %s", path, e)
        return []

    if not isinstance(data, dict):
        return []

    entries: list[ConventionEntry] = []
    linters = data.get("linters", {}) or {}

    enable = linters.get("enable") or []
    if enable:
        entries.append(_entry(
            path, "golangci-enabled-linters",
            f"Enable Go linters: {', '.join(str(l) for l in enable[:5])}",
            ["linting", "go"],
        ))

    disable = linters.get("disable") or []
    if disable:
        entries.append(_entry(
            path, "golangci-disabled-linters",
            f"Disable Go linters: {', '.join(str(l) for l in disable[:5])}",
            ["linting", "go"],
        ))

    settings = data.get("linters-settings", {}) or {}
    goimports = settings.get("goimports", {}) or {}
    local_prefixes = goimports.get("local-prefixes")
    if local_prefixes:
        entries.append(_entry(
            path, "golangci-local-prefixes",
            f"Local import prefixes: {local_prefixes}",
            ["imports", "go"],
        ))

    run = data.get("run", {}) or {}
    go_version = run.get("go")
    if go_version:
        entries.append(_entry(
            path, "golangci-go-version",
            f"Minimum Go version: {go_version}",
            ["compatibility", "go"],
        ))

    return entries


def _parse_clippy_toml(path: Path) -> list[ConventionEntry]:
    """Parse clippy.toml / .clippy.conf for lint levels."""
    if tomllib is None:
        logging.warning("tomllib unavailable, skipping %s", path)
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    try:
        data = tomllib.loads(text)
    except Exception as e:
        logging.warning("Failed to parse %s: %s", path, e)
        return []

    if not isinstance(data, dict):
        return []

    entries: list[ConventionEntry] = []
    stem = _slug(path.name.lstrip(".") or path.name)

    for k, v in data.items():
        if isinstance(v, str) and v in ("deny", "warn", "allow", "forbid"):
            entries.append(_entry(
                path, f"{stem}-{k}",
                f"Clippy {k}: {v}",
                ["linting", "rust"],
            ))
        elif k == "cognitive-complexity-threshold":
            entries.append(_entry(
                path, f"{stem}-complexity-threshold",
                f"Clippy cognitive complexity threshold: {v}",
                ["complexity", "rust"],
            ))
        elif k == "msrv":
            entries.append(_entry(
                path, f"{stem}-msrv",
                f"Minimum supported Rust version: {v}",
                ["compatibility", "rust"],
            ))

    return entries


def _parse_xml_style(path: Path) -> list[ConventionEntry]:
    """Parse checkstyle.xml or pmd.xml for naming and style rules."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        logging.warning("Failed to parse %s: %s", path, e)
        return []

    entries: list[ConventionEntry] = []
    tag = root.tag.lower()
    stem = _slug(path.name.lstrip(".") or path.name)

    if "checkstyle" in tag or "module" in tag:
        for module in root.iter("module"):
            name = module.get("name", "")
            if "Naming" in name or "naming" in name:
                entries.append(_entry(
                    path, f"{stem}-{_slug(name)}",
                    f"Enforce naming convention: {name}",
                    ["naming", "java"],
                ))
            elif "LineLength" in name:
                for prop in module.iter("property"):
                    if prop.get("name") == "max":
                        entries.append(_entry(
                            path, f"{stem}-line-length",
                            f"Maximum line length of {prop.get('value', '?')} characters",
                            ["formatting", "line-length"],
                        ))
            elif "Import" in name:
                entries.append(_entry(
                    path, f"{stem}-{_slug(name)}",
                    f"Enforce import rule: {name}",
                    ["imports", "java"],
                ))
    elif "ruleset" in tag or "pmd" in tag:
        for rule in root.iter("rule"):
            ref = rule.get("ref", "")
            if "naming" in ref.lower():
                rule_label = ref.split("/")[-1] if "/" in ref else ref
                entries.append(_entry(
                    path, f"{stem}-naming-{_slug(rule_label)}"[:60],
                    f"PMD naming rule: {rule_label}",
                    ["naming", "java"],
                ))

    return entries


def _parse_rubocop(path: Path) -> list[ConventionEntry]:
    """Parse .rubocop.yml for naming, style, and layout cops."""
    if not _YAML_AVAILABLE:
        logging.warning("PyYAML not available, skipping %s", path)
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    try:
        data = _yaml.safe_load(text)
    except Exception as e:
        logging.warning("Failed to parse %s: %s", path, e)
        return []

    if not isinstance(data, dict):
        return []

    entries: list[ConventionEntry] = []

    all_cops = data.get("AllCops", {}) or {}
    target_ruby = all_cops.get("TargetRubyVersion")
    if target_ruby:
        entries.append(_entry(
            path, "rubocop-target-ruby",
            f"Target Ruby version: {target_ruby}",
            ["compatibility", "ruby"],
        ))

    for cop_name, cop_config in data.items():
        if cop_name == "AllCops" or not isinstance(cop_config, dict):
            continue
        if cop_config.get("Enabled") is False:
            continue
        category = cop_name.split("/")[0] if "/" in cop_name else ""
        if category in ("Naming", "Style", "Layout"):
            entries.append(_entry(
                path, f"rubocop-{_slug(cop_name)}",
                f"Enforce rubocop cop: {cop_name}",
                [category.lower(), "ruby"],
            ))
        if len(entries) >= 20:
            break

    return entries


def _parse_clang_format(path: Path) -> list[ConventionEntry]:
    """Parse .clang-format (YAML) for indent, brace style, and column limit."""
    if not _YAML_AVAILABLE:
        logging.warning("PyYAML not available, skipping %s", path)
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    try:
        data = _yaml.safe_load(text)
    except Exception as e:
        logging.warning("Failed to parse %s: %s", path, e)
        return []

    if not isinstance(data, dict):
        return []

    entries: list[ConventionEntry] = []

    style = data.get("BasedOnStyle")
    if style:
        entries.append(_entry(
            path, "clang-format-base-style",
            f"Base formatting style: {style}",
            ["formatting", "cpp"],
        ))

    indent = data.get("IndentWidth")
    if indent is not None:
        entries.append(_entry(
            path, "clang-format-indent-width",
            f"Indent with {indent} spaces",
            ["formatting", "indentation"],
        ))

    brace = data.get("BreakBeforeBraces")
    if brace:
        entries.append(_entry(
            path, "clang-format-brace-style",
            f"Brace style: {brace}",
            ["formatting", "cpp"],
        ))

    col_limit = data.get("ColumnLimit")
    if col_limit is not None:
        entries.append(_entry(
            path, "clang-format-column-limit",
            f"Maximum line length of {col_limit} characters",
            ["formatting", "line-length"],
        ))

    use_tabs = data.get("UseTab")
    if use_tabs and use_tabs != "Never":
        entries.append(_entry(
            path, "clang-format-use-tab",
            f"Use tabs for indentation: {use_tabs}",
            ["formatting", "indentation"],
        ))

    return entries


def _parse_clang_tidy(path: Path) -> list[ConventionEntry]:
    """Parse .clang-tidy (YAML) for enabled checks and naming options."""
    if not _YAML_AVAILABLE:
        logging.warning("PyYAML not available, skipping %s", path)
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    try:
        data = _yaml.safe_load(text)
    except Exception as e:
        logging.warning("Failed to parse %s: %s", path, e)
        return []

    if not isinstance(data, dict):
        return []

    entries: list[ConventionEntry] = []

    checks = data.get("Checks", "")
    if checks:
        enabled = [
            c.strip()
            for c in checks.split(",")
            if c.strip() and not c.strip().startswith("-")
        ]
        if enabled:
            entries.append(_entry(
                path, "clang-tidy-checks",
                f"Enable clang-tidy checks: {', '.join(enabled[:3])}",
                ["linting", "cpp"],
            ))

    check_options = data.get("CheckOptions", [])
    if isinstance(check_options, list):
        for opt in check_options:
            if isinstance(opt, dict):
                k = opt.get("key", "")
                v = opt.get("value", "")
                if "NamingConvention" in k or "Case" in k:
                    entries.append(_entry(
                        path, f"clang-tidy-{_slug(k)}"[:60],
                        f"Naming convention: {k} = {v}",
                        ["naming", "cpp"],
                    ))

    return entries


def _parse_stylecop(path: Path) -> list[ConventionEntry]:
    """Parse stylecop.json for naming and layout rules."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logging.warning("Failed to parse %s: %s", path, e)
        return []

    if not isinstance(data, dict):
        return []

    entries: list[ConventionEntry] = []
    settings = data.get("settings", {}) or {}

    naming = settings.get("namingRules", {}) or {}
    for rule_name, enabled in naming.items():
        if enabled:
            entries.append(_entry(
                path, f"stylecop-naming-{_slug(rule_name)}",
                f"Enforce StyleCop naming rule: {rule_name}",
                ["naming", "csharp"],
            ))

    layout = settings.get("layoutRules", {}) or {}
    for rule_name, enabled in layout.items():
        if enabled:
            entries.append(_entry(
                path, f"stylecop-layout-{_slug(rule_name)}",
                f"Enforce StyleCop layout rule: {rule_name}",
                ["formatting", "csharp"],
            ))

    return entries


def _parse_shellcheckrc(path: Path) -> list[ConventionEntry]:
    """Parse .shellcheckrc for disabled checks and shell dialect."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    except Exception as e:
        logging.warning("Failed to read %s: %s", path, e)
        return []

    if not text.strip():
        return []

    entries: list[ConventionEntry] = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("disable="):
            codes = [c.strip() for c in line[len("disable="):].split(",") if c.strip()]
            if codes:
                entries.append(_entry(
                    path, "shellcheck-disable",
                    f"Disable shellcheck rules: {', '.join(codes)}",
                    ["linting", "shell"],
                ))
        elif line.startswith("enable="):
            codes = [c.strip() for c in line[len("enable="):].split(",") if c.strip()]
            if codes:
                entries.append(_entry(
                    path, "shellcheck-enable",
                    f"Enable shellcheck rules: {', '.join(codes)}",
                    ["linting", "shell"],
                ))
        elif line.startswith("shell="):
            shell = line[len("shell="):].strip()
            if shell:
                entries.append(_entry(
                    path, "shellcheck-shell",
                    f"Default shell dialect: {shell}",
                    ["linting", "shell"],
                ))
        elif line.startswith("severity="):
            sev = line[len("severity="):].strip()
            if sev:
                entries.append(_entry(
                    path, "shellcheck-severity",
                    f"Minimum shellcheck severity: {sev}",
                    ["linting", "shell"],
                ))

    return entries


# ── Public API ─────────────────────────────────────────────────────────


def _extract_config_conventions(project_root: Path) -> list[ConventionEntry]:
    """Scan project_root for supported config files and return conventions.

    Checks 16 config file types. For each type:
    - Missing files are silently skipped.
    - Empty files produce no entries (no warning).
    - Malformed content logs a warning and produces no entries.

    Every returned entry has source='config', confidence='established',
    and canonical_example set to the config file path string.
    """
    root = project_root
    results: list[ConventionEntry] = []

    _collect(results, root / ".editorconfig", _parse_editorconfig)
    _collect(results, root / "pyproject.toml", _parse_pyproject_toml)
    _collect(results, root / ".flake8", lambda p: _parse_flake8_style(p, "flake8"))
    _collect(results, root / "setup.cfg", lambda p: _parse_flake8_style(p, "flake8"))

    # ESLint: use the first matching config file found
    for name in (
        ".eslintrc",
        ".eslintrc.json",
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".eslintrc.yaml",
        ".eslintrc.yml",
        "eslint.config.js",
        "eslint.config.cjs",
        "eslint.config.mjs",
    ):
        candidate = root / name
        if candidate.exists():
            _collect(results, candidate, _parse_eslint)
            break

    # Prettier: use the first matching config file found
    for name in (
        ".prettierrc",
        ".prettierrc.json",
        ".prettierrc.yaml",
        ".prettierrc.yml",
        ".prettierrc.js",
        "prettier.config.js",
        "prettier.config.cjs",
    ):
        candidate = root / name
        if candidate.exists():
            _collect(results, candidate, _parse_prettierrc)
            break

    _collect(results, root / "biome.json", _parse_biome_json)
    _collect(results, root / "tsconfig.json", _parse_tsconfig)

    # golangci: .yml or .yaml
    for name in (".golangci.yml", ".golangci.yaml"):
        candidate = root / name
        if candidate.exists():
            _collect(results, candidate, _parse_golangci)
            break

    # Clippy: TOML format
    for name in ("clippy.toml", ".clippy.conf"):
        candidate = root / name
        if candidate.exists():
            _collect(results, candidate, _parse_clippy_toml)
            break

    # Checkstyle
    for name in ("checkstyle.xml", ".checkstyle", "checkstyle-rules.xml"):
        candidate = root / name
        if candidate.exists():
            _collect(results, candidate, _parse_xml_style)
            break

    # PMD
    for name in ("pmd.xml", ".pmd", "pmd-rules.xml", "ruleset.xml"):
        candidate = root / name
        if candidate.exists():
            _collect(results, candidate, _parse_xml_style)
            break

    # RuboCop
    for name in (".rubocop.yml", ".rubocop.yaml"):
        candidate = root / name
        if candidate.exists():
            _collect(results, candidate, _parse_rubocop)
            break

    candidate = root / ".clang-format"
    if candidate.exists():
        _collect(results, candidate, _parse_clang_format)

    candidate = root / ".clang-tidy"
    if candidate.exists():
        _collect(results, candidate, _parse_clang_tidy)

    # StyleCop
    for name in ("stylecop.json", ".stylecop.json"):
        candidate = root / name
        if candidate.exists():
            _collect(results, candidate, _parse_stylecop)
            break

    _collect(results, root / ".shellcheckrc", _parse_shellcheckrc)

    return results
