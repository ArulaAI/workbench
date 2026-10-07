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
from types import MappingProxyType
from typing import Mapping

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

_IDENTIFIER = re.compile(r'[a-z][a-z0-9_]*\Z')
_CATEGORIES = frozenset({'source', 'config', 'schema', 'asset'})
_DISPOSITIONS = frozenset({'analyze', 'supporting', 'reference_only', 'ignore'})
_ROUTABLE_CAPABILITIES = frozenset({
    'parsing', 'declaration_extraction', 'bindings', 'runtime_selection',
    'type_resolution',
})


class RegistryConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class PathClassification:
    path: str
    category: str
    language: str | None
    language_candidate_ids: tuple[str, ...]
    status: str
    reason: str | None = None


def _fail(cause: str) -> None:
    raise RegistryConfigurationError(cause)


def _freeze(value):
    if isinstance(value, (dict, MappingProxyType)):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _compile_patterns(values, cause):
    if not isinstance(values, (list, tuple)) or not values or not all(
            isinstance(value, str) and value for value in values):
        _fail(cause)
    try:
        return tuple(re.compile(value) for value in values)
    except re.error:
        _fail(cause)


def _evidence_clauses(descriptor):
    single = descriptor.get('evidence')
    alternatives = descriptor.get('evidence_any')
    if (single is None) == (alternatives is None):
        _fail('enricher_evidence_conflict')
    clauses = alternatives if alternatives is not None else [single]
    if not isinstance(clauses, list) or not clauses or not all(
            isinstance(clause, dict) and clause for clause in clauses):
        _fail('enricher_evidence_invalid')
    for clause in clauses:
        if set(clause) - SOURCE_ADAPTER_EVIDENCE_KEYS:
            _fail('enricher_evidence_invalid')
        for values in clause.values():
            _compile_patterns(values, 'enricher_evidence_invalid')
    return tuple(_freeze(clause) for clause in clauses)


def _validate_installed_policy(config, by_name, adapters):
    raw_consumers = config.get('supporting_consumers', {})
    raw_classifiers = config.get('path_classifiers', {})
    raw_dispositions = config.get('source_dispositions', {})
    if not all(isinstance(value, dict) for value in
            (raw_consumers, raw_classifiers, raw_dispositions)):
        _fail('installed_policy_table_invalid')

    consumers = {}
    consumer_fields = {'module', 'function', 'version', 'capabilities',
        'capability_status', 'diagnostic_codes'}
    for identity, raw in sorted(raw_consumers.items()):
        if not _IDENTIFIER.fullmatch(identity) or set(raw) != consumer_fields:
            _fail('supporting_consumer_invalid')
        if (not _IDENTIFIER.fullmatch(raw.get('module', ''))
                or not _IDENTIFIER.fullmatch(raw.get('function', ''))
                or not isinstance(raw.get('version'), str) or not raw['version']
                or raw.get('capability_status') not in {'supported', 'partial'}):
            _fail('supporting_consumer_invalid')
        capabilities = raw.get('capabilities')
        diagnostics = raw.get('diagnostic_codes')
        if (not isinstance(capabilities, list) or not capabilities
                or len(capabilities) != len(set(capabilities))
                or set(capabilities) - SOURCE_ADAPTER_CAPABILITIES
                or not isinstance(diagnostics, list) or not diagnostics
                or len(diagnostics) != len(set(diagnostics))
                or not all(isinstance(code, str)
                           and re.fullmatch(r'[A-Z][A-Z0-9_]*', code)
                           for code in diagnostics)):
            _fail('supporting_consumer_invalid')
        consumers[identity] = _freeze(raw)

    classifiers, claimed_extensions = [], set()
    for identity, raw in sorted(raw_classifiers.items()):
        if (not _IDENTIFIER.fullmatch(identity) or not isinstance(raw, dict)
                or set(raw) != {'extensions', 'category', 'reason'}
                or raw.get('category') not in _CATEGORIES
                or not isinstance(raw.get('reason'), str)
                or not _IDENTIFIER.fullmatch(raw['reason'])):
            _fail('path_classifier_invalid')
        extensions = raw.get('extensions')
        if not isinstance(extensions, list) or not extensions or not all(
                isinstance(value, str) and re.fullmatch(r'[a-z0-9]+', value)
                for value in extensions):
            _fail('path_classifier_invalid')
        normalized = tuple('.' + value for value in extensions)
        if claimed_extensions.intersection(normalized) \
                or len(set(normalized)) != len(normalized):
            _fail('path_classifier_extension_duplicate')
        claimed_extensions.update(normalized)
        classifiers.append(_freeze({'id': identity, **raw,
            'extensions': normalized}))

    dispositions = []
    allowed_fields = {'path_any', 'language', 'category', 'disposition',
        'owner', 'required_capabilities'}
    for identity, raw in sorted(raw_dispositions.items()):
        if (not _IDENTIFIER.fullmatch(identity) or not isinstance(raw, dict)
                or set(raw) - allowed_fields
                or raw.get('disposition') not in _DISPOSITIONS
                or not isinstance(raw.get('owner'), str)
                or not _IDENTIFIER.fullmatch(raw['owner'])
                or not ({'path_any', 'language', 'category'} & set(raw))):
            _fail('source_disposition_invalid')
        if raw.get('language') is not None and raw['language'] not in by_name:
            _fail('source_disposition_language_unknown')
        if raw.get('category') is not None \
                and raw['category'] not in _CATEGORIES:
            _fail('source_disposition_category_invalid')
        patterns = (_compile_patterns(raw['path_any'],
            'source_disposition_pattern_invalid') if 'path_any' in raw else ())
        required = raw.get('required_capabilities', [])
        if (not isinstance(required, list)
                or not all(isinstance(value, str) for value in required)
                or len(required) != len(set(required))
                or set(required) - _ROUTABLE_CAPABILITIES):
            _fail('source_disposition_capability_invalid')
        owner = raw['owner']
        if raw['disposition'] == 'analyze':
            descriptor = adapters.get(owner)
            if (descriptor is None or descriptor.get('kind') != 'adapter'
                    or raw.get('language') not in descriptor.get('languages', [])
                    or any(descriptor['capabilities'][capability] == 'unsupported'
                           for capability in required)):
                _fail('source_disposition_owner_invalid')
        elif raw['disposition'] == 'supporting':
            descriptor = consumers.get(owner)
            if descriptor is None or not set(required).issubset(
                    descriptor['capabilities']):
                _fail('source_disposition_owner_invalid')
        elif required:
            _fail('nonexecuting_disposition_has_capabilities')
        dispositions.append(_freeze({'id': identity, **raw,
            'required_capabilities': tuple(sorted(required)),
            '_path_patterns': patterns}))

    supporting_owners = {item['owner'] for item in dispositions
        if item['disposition'] == 'supporting'}
    if supporting_owners != set(consumers):
        _fail('supporting_consumer_owner_mismatch')
    analyze_owners = {item['owner'] for item in dispositions
        if item['disposition'] == 'analyze'}
    for identity, descriptor in adapters.items():
        decoder = descriptor.get('decoder')
        if decoder is not None and (not isinstance(decoder, str)
                or not _IDENTIFIER.fullmatch(decoder)
                or identity not in analyze_owners):
            _fail('source_adapter_decoder_invalid')
    return (MappingProxyType(consumers), tuple(classifiers),
            tuple(dispositions))


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
    rules_language: str          # shared declarative rule catalog identity
    ambient_globals: tuple[str, ...] = ()  # bound by the language, never declared


class LanguageRegistry:
    """TOML-backed language registry.

    Reads two files at construction time:
    - ``languages.toml`` (vendored from Helix) for extension-to-name mapping
    - ``extraction.toml`` (SPEED-specific) for extraction depth, categories,
      grammar overrides, and fence labels

    If either file is missing or malformed, or installed policy fails
    validation, nothing is published: ``load_error`` holds the normalized
    cause and every public query raises it.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        if data_dir is None:
            data_dir = Path(__file__).parent / "data"

        self._by_extension: Mapping[str, Language] = MappingProxyType({})
        self._by_name: Mapping[str, Language] = MappingProxyType({})
        self._extension_candidates: Mapping[str, tuple[Language, ...]] = MappingProxyType({})
        self._installed: set[str] = set()
        self._source_adapters: Mapping[str, Mapping] = MappingProxyType({})
        self._supporting_consumers: Mapping[str, Mapping] = MappingProxyType({})
        self._path_classifiers: tuple[Mapping, ...] = ()
        self._source_dispositions: tuple[Mapping, ...] = ()
        self._trusted_parsers: Mapping[str, Mapping] = MappingProxyType({})
        self.load_error: RegistryConfigurationError | None = None
        try:
            state = self._load(data_dir)
        except RegistryConfigurationError as error:
            self.load_error = error
        else:
            self._by_name = state['by_name']
            self._by_extension = state['by_extension']
            self._extension_candidates = state['extension_candidates']
            self._source_adapters = state['source_adapters']
            self._supporting_consumers = state['supporting_consumers']
            self._path_classifiers = state['path_classifiers']
            self._source_dispositions = state['source_dispositions']
            self._trusted_parsers = state['trusted_parsers']
            self._scan_installed_grammars()

    @property
    def source_adapter_error(self) -> str | None:
        """Normalized load cause for legacy callers; None when valid."""
        return str(self.load_error) if self.load_error is not None else None

    def require_valid(self) -> None:
        if self.load_error is not None:
            raise self.load_error

    def _load(self, data_dir: Path) -> Mapping:
        try:
            return self._load_candidate(data_dir)
        except RegistryConfigurationError:
            raise
        except FileNotFoundError:
            _fail('registry_file_missing')
        except PermissionError:
            _fail('registry_file_unreadable')
        except tomllib.TOMLDecodeError:
            _fail('registry_toml_invalid')
        except json.JSONDecodeError:
            _fail('trusted_parser_manifest_json_invalid')
        except (OSError, KeyError, TypeError, ValueError, re.error):
            _fail('registry_value_invalid')

    def _load_candidate(self, data_dir: Path) -> Mapping:
        """Parse and validate installed metadata without mutating self."""
        by_name = {}
        extension_claimants = {}
        adapters = {}
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

        try:
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
                if kind == 'enricher':
                    evidence_clauses = _evidence_clauses(descriptor)
                elif ('evidence' in descriptor or 'evidence_any' in descriptor):
                    raise ValueError('Ordinary adapters cannot declare activation evidence')
                else:
                    evidence_clauses = ({},)
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
                for pattern in (descriptor.get('detect_any', [])
                                + descriptor.get('exclude_any', [])):
                    re.compile(pattern)
                descriptor = {'kind': kind, **descriptor,
                              '_evidence_clauses': evidence_clauses}
                adapters[name] = descriptor
        except (TypeError, ValueError, re.error):
            raise

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
            rules_language = speed_cfg.get("rules_language", name)
            if not isinstance(rules_language, str) or not re.fullmatch(
                    r"[a-z][a-z0-9_-]*", rules_language):
                raise ValueError("Rule language must name an installed catalog")
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
                rules_language=rules_language,
                ambient_globals=tuple(sorted(set(ambient))),
            )

            by_name[name] = lang
            for extension in extensions:
                extension_claimants.setdefault(extension, []).append(lang)

        # Catalog order never chooses between claimants: a duplicate extension
        # has an owner only when installed configuration names one.
        configured_owners = extraction_config.get('extension_owners', {})
        if not isinstance(configured_owners, dict):
            _fail('extension_owners_invalid')
        by_extension = {}
        extension_candidates = {}
        used_owners = set()
        for extension, claimants in sorted(extension_claimants.items()):
            unique = {candidate.name: candidate for candidate in claimants}
            extension_candidates[extension] = tuple(
                unique[name] for name in sorted(unique))
            if len(unique) == 1:
                by_extension[extension] = next(iter(unique.values()))
                continue
            configured = configured_owners.get(extension.removeprefix('.'))
            if configured is None:
                continue
            if configured not in unique:
                _fail('extension_owner_not_claimant')
            by_extension[extension] = unique[configured]
            used_owners.add(extension.removeprefix('.'))
        if set(configured_owners) != used_owners:
            _fail('extension_owner_unused')

        supporting_consumers, path_classifiers, source_dispositions = \
            _validate_installed_policy(extraction_config, by_name, adapters)
        return {
            'by_name': MappingProxyType(by_name),
            'by_extension': MappingProxyType(by_extension),
            'extension_candidates': MappingProxyType(extension_candidates),
            'source_adapters': MappingProxyType({identity: _freeze(descriptor)
                for identity, descriptor in adapters.items()}),
            'supporting_consumers': supporting_consumers,
            'path_classifiers': path_classifiers,
            'source_dispositions': source_dispositions,
            'trusted_parsers': MappingProxyType({identity: _freeze(parser)
                for identity, parser in trusted_parsers.items()}),
        }

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

    def source_adapter_descriptor(self, owner_id: str) -> Mapping | None:
        self.require_valid()
        descriptor = self._source_adapters.get(owner_id)
        return _freeze({'id': owner_id, **descriptor}) if descriptor else None

    def supporting_consumer_descriptor(self, owner_id: str) -> Mapping | None:
        self.require_valid()
        descriptor = self._supporting_consumers.get(owner_id)
        return _freeze({'id': owner_id, **descriptor}) if descriptor else None

    def source_dispositions(self) -> tuple[Mapping, ...]:
        self.require_valid()
        return self._source_dispositions

    def classify_path(self, path: str) -> PathClassification:
        """Classify one repository path; duplicate claimants stay ambiguous."""
        self.require_valid()
        extension = Path(path).suffix.lower()
        candidates = self._extension_candidates.get(extension, ())
        language = self._by_extension.get(extension)
        if language is not None:
            result = PathClassification(path, language.category, language.name,
                tuple(candidate.name for candidate in candidates), 'classified')
        elif candidates:
            categories = {candidate.category for candidate in candidates}
            result = PathClassification(path,
                next(iter(categories)) if len(categories) == 1 else 'source',
                None, tuple(candidate.name for candidate in candidates), 'ambiguous')
        else:
            result = PathClassification(path, 'asset', None, (), 'unrecognized')
        matches = [item for item in self._path_classifiers
            if extension in item['extensions']]
        if len(matches) > 1:
            _fail('path_classifier_overlap')
        if matches:
            match = matches[0]
            result = PathClassification(path, match['category'], result.language,
                result.language_candidate_ids, result.status, match['reason'])
        return result

    def classify(self, ext: str) -> tuple[str, str | None]:
        """Classify a file extension into (category, language_name).

        Returns ("asset", None) for unknown extensions and no language for an
        unresolved duplicate extension.
        """
        result = self.classify_path('file' + ext)
        return result.category, result.language

    def classify_by_shebang(self, abs_path: str) -> tuple[str, str | None]:
        """Fallback classification by reading the file's shebang line.

        Used when the file has no extension (e.g., the ``speed`` CLI script).
        Returns ("asset", None) if no shebang or unrecognized interpreter.
        """
        self.require_valid()
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
        self.require_valid()
        return name in self._by_name and name in self._installed

    def grammar(self, name: str) -> tuple[str, str] | None:
        """Return (grammar_module, grammar_func) for a language, or None."""
        self.require_valid()
        lang = self._by_name.get(name)
        if lang is None:
            return None
        return lang.grammar_module, lang.grammar_func

    def extraction_level(self, name: str) -> str:
        """Return the extraction level for a language: "rules", "skeleton", or "none"."""
        self.require_valid()
        lang = self._by_name.get(name)
        if lang is None:
            return "none"
        return lang.extraction

    def rules_language(self, name: str) -> str:
        """Return the declarative catalog shared by this parser language."""
        self.require_valid()
        lang = self._by_name.get(name)
        return lang.rules_language if lang else name

    def ambient_globals(self, name: str) -> frozenset[str]:
        """Return the names this language binds without any declaration.

        Empty for a language that declares none, so a caller can ask about any
        language without knowing which ones have an ambient environment.
        """
        self.require_valid()
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
        self.require_valid()
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
            detection = descriptor.get('detect_any', ())
            if detection and (source_text is None or not any(re.search(p, source_text) for p in detection)):
                continue
            if source_text is not None and any(re.search(p, source_text) for p in descriptor.get('exclude_any', [])):
                continue
            clauses = descriptor.get('_evidence_clauses', ({},))
            if not any(all(any(re.search(pattern, value)
                    for pattern in patterns
                    for value in supplied.get(key.removesuffix('_any'), []))
                    for key, patterns in clause.items()) for clause in clauses):
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
        self.require_valid()
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
        self.require_valid()
        for ext in sorted(self._by_extension, key=len, reverse=True):
            if path.endswith(ext):
                return self._by_extension[ext].fence_label
        return ""


# ── Module-level singleton ────────────────────────────────────

registry = LanguageRegistry()
