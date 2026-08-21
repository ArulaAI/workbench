"""Language Registry — TOML-backed single source of truth for language metadata.

Loads Helix's vendored languages.toml for extension-to-name mapping (~325 languages)
and SPEED's extraction.toml for extraction depth, category overrides, grammar
exceptions, and fence label overrides.

Consumers (project_map, treesitter_extract, assembly) query the singleton
``registry`` instance instead of maintaining separate hardcoded dicts.

Usage:
    from lib.context.language_registry import registry
    category, lang = registry.classify(".tsx")       # ("source", "tsx")
    grammar = registry.grammar("tsx")                # ("tree_sitter_typescript", "language_tsx")
    can = registry.can_parse("python")               # True
    level = registry.extraction_level("python")      # "rules"
    fence = registry.fence_label_for("app/user.py")  # "python"
"""

from __future__ import annotations

import importlib.metadata
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Shebang interpreter → language name (used when file has no extension)
_SHEBANG_MAP: dict[str, str] = {
    "bash": "bash",
    "sh": "bash",
    "zsh": "bash",
    "python": "python",
    "python3": "python",
    "node": "javascript",
    "ruby": "ruby",
    "perl": "perl",
}

_SHEBANG_RE = re.compile(r"^#!\s*(?:/usr/bin/env\s+)?(?:\S*/)?(\w+)")


@dataclass(frozen=True)
class Language:
    """A single language known to SPEED."""
    name: str                    # "python", "c_sharp"
    extensions: tuple[str, ...]  # (".py", ".pyi")
    category: str                # "source", "config", "schema"
    fence_label: str             # "python", "csharp"
    grammar_module: str          # "tree_sitter_python"
    grammar_func: str            # "language"
    extraction: str              # "rules" | "skeleton" | "none"


class LanguageRegistry:
    """TOML-backed language registry.

    Reads two files at construction time:
    - ``languages.toml`` (vendored from Helix) for extension-to-name mapping
    - ``extraction.toml`` (SPEED-specific) for extraction depth, categories,
      grammar overrides, and fence labels

    If either file is missing or malformed, the registry initializes empty and
    ``classify()`` returns ``("asset", None)`` for every extension.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        if data_dir is None:
            data_dir = Path(__file__).parent / "data"

        self._by_extension: dict[str, Language] = {}
        self._by_name: dict[str, Language] = {}
        self._installed: set[str] = set()

        try:
            self._load(data_dir)
        except Exception:
            # Graceful degradation: empty registry, classify returns ("asset", None)
            self._by_extension = {}
            self._by_name = {}

        self._scan_installed_grammars()

    def _load(self, data_dir: Path) -> None:
        """Parse both TOML files and build lookup dicts."""
        # Load Helix languages.toml
        with open(data_dir / "languages.toml", "rb") as f:
            helix = tomllib.load(f)

        # Load SPEED extraction.toml
        with open(data_dir / "extraction.toml", "rb") as f:
            extraction_config = tomllib.load(f)

        # Build Language objects for every Helix [[language]] entry
        for entry in helix.get("language", []):
            raw_name = entry.get("name", "")
            if not raw_name:
                continue

            # Normalize: hyphens to underscores (c-sharp -> c_sharp)
            name = raw_name.replace("-", "_")

            # Build extensions: prepend ".", skip glob objects
            extensions: list[str] = []
            for ft in entry.get("file-types", []):
                if isinstance(ft, str):
                    extensions.append(f".{ft}")
                # Skip dict/glob entries like {"glob": "Dockerfile"}

            if not extensions:
                continue

            # Look up SPEED extraction config (keyed by raw Helix name)
            speed_cfg = extraction_config.get(raw_name, {})

            category = speed_cfg.get("category", "source")
            extraction = speed_cfg.get("extraction", "none")
            fence_label = speed_cfg.get("fence_label", name)
            grammar_module = speed_cfg.get("grammar_module", f"tree_sitter_{name}")
            grammar_func = speed_cfg.get("grammar_func", "language")

            lang = Language(
                name=name,
                extensions=tuple(extensions),
                category=category,
                fence_label=fence_label,
                grammar_module=grammar_module,
                grammar_func=grammar_func,
                extraction=extraction,
            )

            self._by_name[name] = lang
            for ext in extensions:
                # First language to claim an extension wins
                if ext not in self._by_extension:
                    self._by_extension[ext] = lang

    def _scan_installed_grammars(self) -> None:
        """Detect installed tree-sitter grammar packages via importlib.metadata."""
        try:
            for dist in importlib.metadata.distributions():
                dist_name = dist.name
                if dist_name.startswith("tree-sitter-") and dist_name != "tree-sitter":
                    lang_name = dist_name[len("tree-sitter-"):].replace("-", "_")
                    self._installed.add(lang_name)
        except Exception:
            pass

    # ── Public query methods ──────────────────────────────────

    def classify(self, ext: str) -> tuple[str, str | None]:
        """Classify a file extension into (category, language_name).

        Returns ("asset", None) for unknown extensions.
        """
        lang = self._by_extension.get(ext)
        if lang is None:
            return "asset", None
        return lang.category, lang.name

    def classify_by_shebang(self, abs_path: str) -> tuple[str, str | None]:
        """Fallback classification by reading the file's shebang line.

        Used when the file has no extension (e.g., the ``speed`` CLI script).
        Returns ("asset", None) if no shebang or unrecognized interpreter.
        """
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline(256)
        except (OSError, UnicodeDecodeError):
            return "asset", None

        m = _SHEBANG_RE.match(first_line)
        if not m:
            return "asset", None

        interpreter = m.group(1)
        lang_name = _SHEBANG_MAP.get(interpreter)
        if lang_name is None:
            return "asset", None

        lang = self._by_name.get(lang_name)
        if lang is None:
            return "source", lang_name
        return lang.category, lang.name

    def can_parse(self, name: str) -> bool:
        """Check whether a language is known AND has its grammar installed."""
        return name in self._by_name and name in self._installed

    def grammar(self, name: str) -> tuple[str, str] | None:
        """Return (grammar_module, grammar_func) for a language, or None."""
        lang = self._by_name.get(name)
        if lang is None:
            return None
        return lang.grammar_module, lang.grammar_func

    def extraction_level(self, name: str) -> str:
        """Return the extraction level for a language: "rules", "skeleton", or "none"."""
        lang = self._by_name.get(name)
        if lang is None:
            return "none"
        return lang.extraction

    def fence_label_for(self, path: str) -> str:
        """Return the code fence language label for a file path."""
        for ext in sorted(self._by_extension, key=len, reverse=True):
            if path.endswith(ext):
                return self._by_extension[ext].fence_label
        return ""


# ── Module-level singleton ────────────────────────────────────

registry = LanguageRegistry()
