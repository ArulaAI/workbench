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

import base64
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import re
import sysconfig
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

# Version-one descriptors use one language-neutral vocabulary. Keeping it with
# the installed registry prevents adapters from inventing capability names.
SOURCE_ADAPTER_CONTRACT_VERSION = 1
SOURCE_ADAPTER_OUTPUT_VERSION = 1
SOURCE_ADAPTER_CAPABILITIES = frozenset({
    "parsing", "declaration_extraction", "entrypoint_detection",
    "call_classification", "callable_resolution", "overload_resolution",
    "type_resolution", "relationship_resolution", "framework_enrichment",
    "bindings", "data_access", "rules", "control_flow", "outputs",
    "runtime_selection",
})
SOURCE_ADAPTER_CAPABILITY_STATUSES = frozenset({"supported", "partial", "unsupported"})
SOURCE_ADAPTER_KINDS = frozenset({"adapter", "enricher"})
SOURCE_ADAPTER_CONFORMANCE = frozenset({"fixture", "declaration", "semantic", "unavailable"})
SOURCE_ADAPTER_EVIDENCE_KEYS = frozenset({
    "source_any", "imports_any", "annotations_any", "dependencies_any",
    "configuration_any", "generated_sources_any",
})


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
    ambient_globals: tuple[str, ...] = ()  # bound by the language, never declared


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
        self._source_adapters: dict[str, dict] = {}
        self._trusted_parsers: dict[str, dict] = {}
        self.source_adapter_error: str | None = None

        try:
            self._load(data_dir)
        except Exception:
            # Graceful degradation: empty registry, classify returns ("asset", None)
            self._by_extension = {}
            self._by_name = {}
            self._source_adapters = {}
            self._trusted_parsers = {}
            self.source_adapter_error = "REGISTRY_LOAD_FAILED"

        self._scan_installed_grammars()

    def _load(self, data_dir: Path) -> None:
        """Parse both TOML files and build lookup dicts."""
        # Load Helix languages.toml
        with open(data_dir / "languages.toml", "rb") as f:
            helix = tomllib.load(f)

        # Load SPEED extraction.toml
        with open(data_dir / "extraction.toml", "rb") as f:
            extraction_config = tomllib.load(f)

        parser_manifest_path = data_dir / "trusted_parser_manifest.json"
        parser_manifest = (json.loads(parser_manifest_path.read_text())
                           if parser_manifest_path.is_file()
                           else {"manifest_version": 1, "parsers": {}})
        if parser_manifest.get("manifest_version") != 1 \
                or not isinstance(parser_manifest.get("parsers"), dict):
            raise ValueError('Invalid trusted parser manifest')
        trusted_parsers = parser_manifest["parsers"]
        for identity, parser in trusted_parsers.items():
            if not re.fullmatch(r'[a-z][a-z0-9_]*', identity) \
                    or parser.get('implementation') != 'pure-python' \
                    or parser.get('wheel_tag') != 'py3-none-any' \
                    or not re.fullmatch(r'[a-z][a-z0-9_.]*', parser.get('module', '')) \
                    or not isinstance(parser.get('version'), str) \
                    or not re.fullmatch(r'[0-9a-f]{64}', parser.get('wheel_sha256', '')):
                raise ValueError('Invalid trusted parser artifact')
        self._trusted_parsers = trusted_parsers

        try:
            adapters = {}
            for name, descriptor in extraction_config.get('source_adapters', {}).items():
                if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
                    raise ValueError('Invalid installed source adapter identity')
                if descriptor.get('module') and not re.fullmatch(r'[a-z][a-z0-9_]*', descriptor['module']):
                    raise ValueError('Invalid installed source adapter module')
                if (descriptor.get('contract_version') != SOURCE_ADAPTER_CONTRACT_VERSION
                        or descriptor.get('normalized_output_version') != SOURCE_ADAPTER_OUTPUT_VERSION
                        or not isinstance(descriptor.get('version'), str)):
                    raise ValueError('Unsupported source adapter contract')
                kind = descriptor.get('kind')
                if kind not in SOURCE_ADAPTER_KINDS:
                    raise ValueError('Invalid source provider kind')
                if descriptor.get('conformance') not in SOURCE_ADAPTER_CONFORMANCE:
                    raise ValueError('Invalid source adapter conformance level')
                if kind == 'adapter' and not descriptor.get('languages') and not descriptor.get('extraction_level'):
                    raise ValueError('Source adapter must declare language or extraction capability')
                if kind == 'enricher' and not descriptor.get('evidence'):
                    raise ValueError('Framework enricher must declare activation evidence')
                if kind == 'enricher' and not isinstance(descriptor.get('framework'), str):
                    raise ValueError('Framework enricher must declare framework identity')
                capabilities = descriptor.get('capabilities', {})
                if set(capabilities) != SOURCE_ADAPTER_CAPABILITIES:
                    raise ValueError('Source adapter must declare the complete contract capability set')
                if any(v not in SOURCE_ADAPTER_CAPABILITY_STATUSES for v in capabilities.values()):
                    raise ValueError('Source adapter must declare capability status')
                if (any(status != 'unsupported' for status in capabilities.values())
                        and not descriptor.get('module')):
                    raise ValueError('Available source capability requires an installed module')
                if (kind == 'enricher'
                        and capabilities['framework_enrichment'] == 'unsupported'):
                    raise ValueError('Framework enricher must provide framework enrichment')
                if kind == 'enricher' and descriptor.get('fallback'):
                    raise ValueError('Framework enricher cannot be a fallback provider')
                parser_id = descriptor.get('parser')
                if parser_id:
                    parser = trusted_parsers.get(parser_id)
                    if not parser or descriptor.get('parser_version') != parser.get('version'):
                        raise ValueError('Source adapter references an untrusted parser')
                    if (not isinstance(descriptor.get('parser_dialect'), str)
                            or not descriptor['parser_dialect']
                            or not isinstance(descriptor.get('supported_versions'), list)
                            or not descriptor['supported_versions']
                            or not all(isinstance(value, str) and value
                                       for value in descriptor['supported_versions'])
                            or not isinstance(descriptor.get('recognized_extensions'), list)
                            or not descriptor['recognized_extensions']
                            or not all(re.fullmatch(r'\.[a-z0-9]+', value)
                                       for value in descriptor['recognized_extensions'])):
                        raise ValueError('Parser-backed adapter has an incomplete dialect contract')
                evidence = descriptor.get('evidence', {})
                if set(evidence) - SOURCE_ADAPTER_EVIDENCE_KEYS:
                    raise ValueError('Unsupported source adapter evidence kind')
                for values in evidence.values():
                    if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
                        raise ValueError('Source adapter evidence predicates must be arrays')
                for pattern in (descriptor.get('detect_any', []) + descriptor.get('exclude_any', [])
                                + [p for values in evidence.values() for p in values]):
                    re.compile(pattern)
                descriptor = {'kind':kind, **descriptor}
                adapters[name] = descriptor
            self._source_adapters = adapters
        except (TypeError, ValueError, re.error) as exc:
            # Adapter registration is an optional capability layer. Preserve
            # the primary language registry and make the deployment fault visible.
            self._source_adapters = {}
            self.source_adapter_error = type(exc).__name__

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
            ambient = speed_cfg.get("ambient_globals", [])
            if isinstance(ambient, str):
                ambient = extraction_config.get(
                    "ambient_environments", {}).get(ambient)
                if ambient is None:
                    raise ValueError("Unknown ambient binding environment")
            if not isinstance(ambient, list) or not all(
                    isinstance(value, str) and re.fullmatch(r"[A-Za-z_$][\w$]*", value)
                    for value in ambient):
                raise ValueError("Ambient global bindings must be identifier strings")

            lang = Language(
                name=name,
                extensions=tuple(extensions),
                category=category,
                fence_label=fence_label,
                grammar_module=grammar_module,
                grammar_func=grammar_func,
                extraction=extraction,
                ambient_globals=tuple(sorted(set(ambient))),
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

    def ambient_globals(self, name: str) -> frozenset[str]:
        """Return the names this language binds without any declaration.

        Empty for a language that declares none, so a caller can ask about any
        language without knowing which ones have an ambient environment.
        """
        lang = self._by_name.get(name)
        return frozenset(lang.ambient_globals) if lang else frozenset()

    def source_adapters(
        self,
        name: str,
        source_text: str | None = None,
        *,
        evidence: dict[str, list[str] | tuple[str, ...] | str] | None = None,
        kind: str = 'adapter',
    ) -> list[dict]:
        """Select installed capability descriptors from classification and source evidence.

        Descriptors come only from this registry's installed data directory.
        Target repositories supply text to match, never executable configuration.
        Multiple matches are returned explicitly rather than selected by order.
        """
        supplied = {'source': [source_text] if source_text is not None else []}
        for key, values in (evidence or {}).items():
            supplied[key] = [values] if isinstance(values, str) else list(values)
        matches = []
        for identity, descriptor in self._source_adapters.items():
            if descriptor.get('kind', 'adapter') != kind:
                continue
            if descriptor.get('languages') and name not in descriptor['languages']:
                continue
            if descriptor.get('extraction_level') and self.extraction_level(name) != descriptor['extraction_level']:
                continue
            detection = descriptor.get('detect_any', [])
            if detection and (source_text is None or not any(re.search(p, source_text) for p in detection)):
                continue
            if source_text is not None and any(re.search(p, source_text) for p in descriptor.get('exclude_any', [])):
                continue
            required = descriptor.get('evidence', {})
            if any(not any(re.search(pattern, value) for pattern in patterns
                           for value in supplied.get(key.removesuffix('_any'), []))
                   for key, patterns in required.items()):
                continue
            matches.append({'id':identity, **descriptor})
        specific = [candidate for candidate in matches if not candidate.get('fallback')]
        return specific or [candidate for candidate in matches if candidate.get('fallback')]

    def load_trusted_parser(self, identity: str):
        """Load a pinned pure-Python parser only from this interpreter's library.

        Wheel identity is pinned by the installed manifest. RECORD hashes are
        checked before import so a target repository cannot shadow or alter the
        parser implementation that an adapter executes.
        """
        parser = self._trusted_parsers.get(identity)
        if not parser:
            raise RuntimeError(f"Trusted parser is not registered: {identity}")
        distribution = importlib.metadata.distribution(parser['distribution'])
        if distribution.version != parser['version']:
            raise RuntimeError(
                f"Trusted parser version mismatch: expected {parser['version']}, "
                f"found {distribution.version}")
        module_name = parser['module']
        module_path = Path(*module_name.split('.'))
        expected = Path(distribution.locate_file(module_path / '__init__.py')).resolve()
        allowed_roots = {
            Path(path).resolve() for path in {
                sysconfig.get_path('purelib'), sysconfig.get_path('platlib')
            } if path
        }
        if not any(expected.is_relative_to(root) for root in allowed_roots):
            raise RuntimeError("Trusted parser is outside the interpreter library")
        specification = importlib.util.find_spec(module_name)
        if (not specification or not specification.origin
                or Path(specification.origin).resolve() != expected):
            raise RuntimeError("Trusted parser import is shadowed by an untrusted location")
        checked = 0
        prefix = module_name.replace('.', '/') + '/'
        for item in distribution.files or ():
            relative = str(item)
            if not relative.startswith(prefix) or not relative.endswith('.py'):
                continue
            if not item.hash:
                raise RuntimeError(f"Trusted parser file lacks a RECORD hash: {relative}")
            location = Path(distribution.locate_file(item)).resolve()
            if not location.is_relative_to(expected.parent):
                raise RuntimeError("Trusted parser RECORD escapes its package")
            digest = hashlib.new(item.hash.mode, location.read_bytes()).digest()
            actual = base64.urlsafe_b64encode(digest).decode().rstrip('=')
            if actual != item.hash.value:
                raise RuntimeError(f"Trusted parser integrity check failed: {relative}")
            checked += 1
        if not checked:
            raise RuntimeError("Trusted parser has no checksummed implementation files")
        return importlib.import_module(module_name)

    def fence_label_for(self, path: str) -> str:
        """Return the code fence language label for a file path."""
        for ext in sorted(self._by_extension, key=len, reverse=True):
            if path.endswith(ext):
                return self._by_extension[ext].fence_label
        return ""


# ── Module-level singleton ────────────────────────────────────

registry = LanguageRegistry()
