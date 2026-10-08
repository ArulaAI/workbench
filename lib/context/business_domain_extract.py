"""Language-independent evidence inventory, normalization and bounded tracing.

All syntax and framework recognition lives behind the source adapter contract.
"""
from __future__ import annotations
import json
import math
import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path, PurePosixPath
from types import MappingProxyType, ModuleType
from typing import Mapping
from .business_domain_adapters import (CATALOG, descriptor_for_route,
    enricher_descriptors, load_installed)
from .business_domain_adapters.base import (
    MAX_SEMANTIC_CANDIDATES, TRACE_ROLES, DecodedSource, SemanticResult, Source,
    SupportingConsumerResult, Unit, http_url_parts, normalize_operation_observation,
    resolve_anchor_identity,
)
from .business_domain_identity import reconcile_anchors
from .business_domain_entrypoints import (GAP_CODES, LANGUAGE_GAP, LIKELY_MISSED,
    NONE_DETECTED, MarkerCatalogError, covered, gap_record, load_catalog,
    matching_entry_point, route_key, scan_markers)
from .language_registry import (SOURCE_ADAPTER_CAPABILITIES, PathClassification,
    RegistryConfigurationError, registry)
from .business_domain_schema import (DEFAULTS, DomainError, account_artifact_bytes,
    atomic_write, digest, identifier, implementation_hash, limits, now, record,
    validate, validate_source_warning_coverage, read_json)
from .utils import is_credential_path

IGNORED = set(CATALOG['ignored_directories'])
# Structural, test and documentation edges describe a symbol; tracing does not
# follow them, so they cannot show that a path continues past that symbol.
NON_TRAVERSAL_EDGES = frozenset({'implements', 'inherits', 'has_field',
    'accepts_type', 'returns_type', 'tests_behavior', 'documents_behavior',
    'exposes_endpoint'})
# Which unsatisfied obligations are known boundaries rather than gaps.
TRACE_BOUNDARIES = MappingProxyType(json.loads(
    (Path(__file__).parent / 'data' / 'trace_boundaries.json').read_text()))


def _known_provider(language, provider):
    """Whether the trace-boundary catalog lists *provider* as a library of *language*."""
    known = TRACE_BOUNDARIES['known_libraries'].get(language or '')
    if not known or not provider or ':' not in provider:
        return False
    kind, names = provider.split(':', 1)
    # ``a|b`` lists candidate providers: known only when every one is.
    candidates = names.split('|')
    if kind == 'global':
        return bool(known.get('ambient'))
    if kind == 'module':
        return all(any(name == module or name.startswith(module + '/')
                       for module in known.get('modules', ())) for name in candidates)
    if kind == 'type':
        return all(any(name.startswith(prefix) for prefix in known.get('prefixes', ()))
                   for name in candidates)
    return False


def trace_boundary(obligation, edge, codes, resource):
    """The boundary kind of one unsatisfied obligation, or None when it is a gap.

    *codes* are the adapter diagnostic codes attached to the obligation's edge
    and *resource* is the edge's target resource, if any. Only catalogued
    evidence makes a boundary; anything else stays a gap.
    """
    if obligation['status'] == 'satisfied':
        return None
    kind = TRACE_BOUNDARIES['obligation_codes'].get(obligation['reason_code'])
    if kind or edge is None:
        return kind
    if (obligation['kind'], obligation['status']) in {
            ('implementation_selection', 'external'), ('data_target', 'unresolved')}:
        kinds = {TRACE_BOUNDARIES['diagnostic_codes'].get(code) for code in codes}
        if not edge['to_ref'] or not kinds or None in kinds:
            return None
        return min(kinds, key=TRACE_BOUNDARIES['kind_order'].index)
    if (obligation['kind'] == 'external_boundary' and edge['kind'] == 'calls' and resource
            and set(codes) & set(TRACE_BOUNDARIES['library_codes'])
            and _known_provider(resource.get('language'), resource.get('provider'))):
        return 'library_call'
    return None


def _conditional_alternatives(selections):
    """Selections that are each taken under a declared condition, or [].

    A declaration whose every selects_implementation relationship names one
    target under an evidenced activation condition (a profile, a property) is
    a set of conditional paths, not an unknown choice. Each must name its
    target: an ambiguous or unnamed selection keeps the choice a gap.
    """
    if len(selections) < 2 or any(not edge['condition'] or not edge['to_ref']
                                  or edge['resolution'] == 'ambiguous'
                                  for edge in selections):
        return []
    if len({edge['to_ref']['id'] for edge in selections}) < 2:
        return []
    return sorted(selections, key=lambda edge: (edge['to_ref']['id'], edge['id']))


def source_paths(root: Path) -> list[str]:
    try:
        result = subprocess.run(['git', '-C', str(root), 'ls-files', '-co', '--exclude-standard', '-z'], capture_output=True, timeout=30, check=True)
        paths = result.stdout.decode().split('\0')
    except (subprocess.SubprocessError, UnicodeError):
        paths = []
        for directory, folders, files in os.walk(root, followlinks=False):
            folders[:] = [name for name in folders if name not in IGNORED and not (Path(directory)/name).is_symlink()]
            paths.extend((Path(directory)/name).relative_to(root).as_posix() for name in files)
    return sorted({p for p in paths if p and not any(part in IGNORED for part in Path(p).parts)
                   and not is_credential_path(Path(p))})

@dataclass(frozen=True)
class SourceRoute:
    classification: PathClassification
    matched_rule_ids: tuple[str, ...]
    disposition: str
    expected_owner: str | None
    required_capabilities: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class SourceInventory:
    routes: tuple[SourceRoute, ...]
    retained_bytes: Mapping[str, bytes]
    diagnostics: tuple[dict, ...]
    # Bytes of ignored paths that the entry-point marker catalog searches.
    # They are never decoded into Sources or analyzed.
    marker_bytes: Mapping[str, bytes] = MappingProxyType({})


def _entrypoint_catalog():
    try:
        return load_catalog()
    except MarkerCatalogError as error:
        raise DomainError('ADAPTER_REGISTRY_INVALID', str(error)) from None


def _read_contained(root: Path, relative: str, limit: int) -> bytes | None:
    """Bytes of one contained regular file within *limit*, else None."""
    path = root / relative
    if (path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(root)):
        return None
    try:
        with path.open('rb') as stream:
            raw = stream.read(limit + 1)
    except OSError:
        return None
    return raw if len(raw) <= limit else None


@dataclass(frozen=True)
class DecodedSourceInventory:
    routes: tuple[SourceRoute, ...]
    sources: tuple[Source, ...]
    diagnostics: tuple[dict, ...]
    provisional_decoders: Mapping[str, ModuleType]


@dataclass(frozen=True)
class SourceSelection:
    route: SourceRoute
    selected_descriptor: Mapping | None
    candidate_owner_ids: tuple[str, ...]
    status: str


@dataclass
class SourceExecution:
    source: Source
    selection: SourceSelection
    loaded_owner: ModuleType | None = None
    output: tuple[Unit, ...] = ()
    diagnostics: list[dict] = dataclass_field(default_factory=list)
    state: str = 'unresolved'
    cause: str | None = None


def _route(path: str, classification: PathClassification) -> SourceRoute:
    """The installed disposition of one path, decided before any byte is read."""
    matches = []
    for rule in registry.source_dispositions():
        patterns = rule.get('_path_patterns', ())
        if patterns and not any(pattern.fullmatch(path) for pattern in patterns):
            continue
        if rule.get('language') is not None \
                and rule['language'] != classification.language:
            continue
        if rule.get('category') is not None \
                and rule['category'] != classification.category:
            continue
        matches.append(rule)
    # A rule naming the path outranks one that only matches its category or
    # language, so `.vscode/icon.svg` is developer tooling, not just an asset.
    if any(rule.get('_path_patterns') for rule in matches):
        matches = [rule for rule in matches if rule.get('_path_patterns')]
    if not matches:
        if classification.category == 'asset' and classification.status == 'unrecognized':
            return SourceRoute(classification, (), 'ignore', 'unrecognized_asset',
                (), 'routed')
        return SourceRoute(classification, (), 'analyze', None, (), 'routed')
    signatures = {
        (rule['disposition'], rule['owner'], rule.get('language'),
         tuple(rule.get('required_capabilities', ())))
        for rule in matches
    }
    matched_ids = tuple(sorted(rule['id'] for rule in matches))
    if len(signatures) > 1 and {rule['disposition'] for rule in matches} == {'ignore'}:
        # Rules that all ignore a path agree on what happens to it.
        owner = min(rule['id'] for rule in matches)
        return SourceRoute(classification, matched_ids, 'ignore',
            next(rule['owner'] for rule in matches if rule['id'] == owner), (), 'routed')
    if len(signatures) != 1:
        return SourceRoute(classification, matched_ids, 'analyze', None, (), 'overlap')
    disposition, owner, _language, capabilities = next(iter(signatures))
    return SourceRoute(classification, matched_ids, disposition, owner,
        tuple(sorted(capabilities)), 'routed')


def scan_inventory(root: Path, config: dict) -> SourceInventory:
    """Classify and route every path, and read retained bytes; nothing is decoded."""
    root = root.resolve()
    routes = tuple(_route(path, registry.classify_path(path))
        for path in source_paths(root))
    overlaps = [route for route in routes if route.status == 'overlap']
    if overlaps:
        paths = ','.join(sorted(route.classification.path for route in overlaps))
        raise DomainError('ADAPTER_REGISTRY_INVALID',
            f'conflicting_source_dispositions:{paths}')
    retained = {}
    marker_bytes = {}
    diagnostics = []
    catalog = _entrypoint_catalog()
    for route in routes:
        if route.disposition == 'ignore':
            relative = route.classification.path
            if catalog.scans(relative):
                raw = _read_contained(root, relative, config['max_source_bytes'])
                if raw is not None:
                    marker_bytes[relative] = raw
            continue
        relative = route.classification.path
        path = root / relative
        if (path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to(root)):
            diagnostics.append(record('Diagnostic', code='UNSAFE_SOURCE',
                message=f'Excluded unsafe source: {relative}',
                subject_ids=[], evidence_ids=[]))
            continue
        try:
            with path.open('rb') as stream:
                raw = stream.read(config['max_source_bytes'] + 1)
        except OSError:
            diagnostics.append(record('Diagnostic', code='SOURCE_UNAVAILABLE',
                message=f'Cannot read source: {relative}',
                subject_ids=[], evidence_ids=[]))
            continue
        if len(raw) > config['max_source_bytes']:
            diagnostics.append(record('Diagnostic', code='SOURCE_LIMIT',
                message=f'Excluded oversized source: {relative}',
                subject_ids=[], evidence_ids=[]))
            continue
        retained[relative] = raw
    return SourceInventory(routes, MappingProxyType(retained), tuple(diagnostics),
        MappingProxyType(marker_bytes))


def inventory(scan: SourceInventory, config: dict) -> DecodedSourceInventory:
    """Decode retained bytes into Sources without rereading or selecting owners.

    Only an explicitly routed decoder is loaded here; everything else is
    strict UTF-8.
    """
    routes = {route.classification.path: route for route in scan.routes}
    sources = []
    diagnostics = list(scan.diagnostics)
    provisional = {}
    decoder_modules = {}
    decoder_load_failures = set()
    markers = set(CATALOG.get('service_scope_markers', ()))
    scope_directories = {PurePosixPath(route.classification.path).parent.as_posix()
        for route in scan.routes
        if PurePosixPath(route.classification.path).name in markers}
    for relative, raw in scan.retained_bytes.items():
        route = routes[relative]
        decoded = None
        failure = None
        descriptor = (registry.source_adapter_descriptor(route.expected_owner)
            if route.disposition == 'analyze' and route.expected_owner else None)
        decoder_name = descriptor.get('decoder') if descriptor else None
        if decoder_name:
            module = None
            module_key = (descriptor['id'], descriptor['module'])
            if module_key in decoder_load_failures:
                failure = 'owner_load_failed'
            else:
                try:
                    module = decoder_modules.get(module_key)
                    if module is None:
                        module = load_installed(descriptor['module'])
                        decoder_modules[module_key] = module
                    decoder = getattr(module, decoder_name, None)
                    if not callable(decoder):
                        raise TypeError('Installed decoder is not callable')
                    decoded = decoder(raw)
                    if (not isinstance(decoded, DecodedSource)
                            or not isinstance(decoded.text, str)
                            or not isinstance(decoded.encoding, str)
                            or decoded.original_byte_length != len(raw)):
                        raise TypeError(
                            'Installed decoder returned an invalid result')
                except Exception:
                    failure = ('owner_load_failed' if module is None
                               else 'owner_execution_failed')
                    if module is None:
                        decoder_load_failures.add(module_key)
            if failure:
                # A reversible one-character-per-byte view, kept only as
                # failure evidence; it is never parsed.
                decoded = DecodedSource(raw.decode('iso-8859-1'),
                    'failure-evidence-iso-8859-1', len(raw))
            if module is not None:
                provisional[identifier('resource', relative)] = module
        else:
            try:
                decoded = DecodedSource(raw.decode('utf-8'), 'utf-8', len(raw))
            except UnicodeDecodeError:
                diagnostics.append(record('Diagnostic', code='SOURCE_ENCODING',
                    message=f'Unsupported source encoding: {relative}',
                    subject_ids=[], evidence_ids=[]))
                continue
        source = Source(path=relative, language=route.classification.language,
            text=decoded.text, source_hash=digest(raw),
            resource_id=identifier('resource', relative),
            original_byte_length=decoded.original_byte_length,
            decoder_failure=failure,
            evidence_redaction_required=bool(failure))
        parents = {parent.as_posix() for parent in PurePosixPath(relative).parents}
        service_scope = max((scope for scope in scope_directories if scope in parents),
            key=lambda value: len(PurePosixPath(value).parts), default=None)
        source.service_scope = ('repository' if service_scope in {None, '.'}
            else service_scope)
        sources.append(source)
    return DecodedSourceInventory(scan.routes, tuple(sources), tuple(diagnostics),
        MappingProxyType(provisional))


def select_source(source: Source, route: SourceRoute) -> SourceSelection:
    """The one final primary-owner decision for a retained source."""
    if route.disposition in {'ignore', 'reference_only'}:
        return SourceSelection(route, None, (), 'ignored')
    candidates = descriptor_for_route(source, route)
    candidate_ids = tuple(sorted(candidate['id'] for candidate in candidates))
    if (route.expected_owner is None
            and route.classification.status == 'ambiguous'):
        return SourceSelection(route, None, candidate_ids, 'ambiguous')
    if len(candidates) == 1:
        return SourceSelection(route, MappingProxyType(dict(candidates[0])),
            candidate_ids, 'selected')
    return SourceSelection(route, None, candidate_ids,
        'ambiguous' if candidates else 'unavailable')


def load_selection(source: Source, selection: SourceSelection,
        provisional_decoder: ModuleType | None = None,
        module_cache: dict[tuple[str, str, str], ModuleType] | None = None
        ) -> SourceExecution:
    """Load the selected owner once and run its per-source extract hook."""
    execution = SourceExecution(source, selection)
    if selection.route.disposition in {'ignore', 'reference_only'}:
        return execution
    if source.decoder_failure:
        execution.loaded_owner = provisional_decoder
        execution.cause = source.decoder_failure
        return execution
    descriptor = selection.selected_descriptor
    if selection.status != 'selected' or descriptor is None:
        execution.cause = (
            'ambiguous_language'
            if (selection.status == 'ambiguous'
                and selection.route.classification.status == 'ambiguous')
            else 'multiple_owners' if selection.status == 'ambiguous'
            else 'owner_not_installed')
        return execution
    cache = module_cache if module_cache is not None else {}
    try:
        module = provisional_decoder
        cache_key = (selection.route.disposition, descriptor['id'],
            descriptor['module'])
        if module is None:
            module = cache.get(cache_key)
        if module is None:
            module = load_installed(descriptor['module'])
            cache[cache_key] = module
        execution.loaded_owner = module
        if selection.route.disposition == 'analyze':
            extract = getattr(module, 'extract', None)
            if not callable(extract):
                raise AttributeError('Installed adapter extract hook is unavailable')
            execution.output = tuple(extract(source))
        execution.state = 'resolved'
    except Exception:
        execution.cause = ('owner_load_failed' if execution.loaded_owner is None
            else 'owner_execution_failed')
        if descriptor.get('decoder'):
            source.evidence_redaction_required = True
        execution.loaded_owner = None
        execution.output = ()
        execution.state = 'unresolved'
    return execution


def source_fingerprint(scan: SourceInventory) -> str:
    """Routing decisions for every path plus raw-byte hashes of retained paths."""
    marker_bytes = ({'marker_bytes': {path: digest(raw)
        for path, raw in sorted(scan.marker_bytes.items())}}
        if scan.marker_bytes else {})
    return digest({
        **marker_bytes,
        'routes': [{
            'path': route.classification.path,
            'category': route.classification.category,
            'language': route.classification.language,
            'language_candidate_ids': list(route.classification.language_candidate_ids),
            'classification_status': route.classification.status,
            'classification_reason': route.classification.reason,
            'matched_rule_ids': list(route.matched_rule_ids),
            'disposition': route.disposition,
            'owner': route.expected_owner,
            'required_capabilities': list(route.required_capabilities),
            'route_status': route.status,
        } for route in scan.routes],
        'retained_bytes': {path: digest(raw)
            for path, raw in sorted(scan.retained_bytes.items())},
    })


# One sensitive-name predicate decides every redaction below.
# A sensitive word is a whole name segment: delimited by `.`, `_`, `-` or a
# camelCase boundary (dbPassword, clientSecret), never a fragment (tokenizer).
_SENSITIVE_NAME_RE = re.compile(
    r'(?:^|[._-]|(?<=[a-z0-9])(?=[A-Z]))'
    r'(?i:password|passwd|secret|credential|token|api[_-]?key|access[_-]?token)'
    r'(?:$|[._-]|(?=[A-Z0-9]))')


def _sensitive_name(name: str) -> bool:
    return bool(_SENSITIVE_NAME_RE.search(name))


def _validate_named_value_spans(source, candidates):
    if (not isinstance(candidates, (tuple, list))
            or not all(isinstance(item, (tuple, list)) and len(item) == 3
                and (item[0] is None or isinstance(item[0], str))
                and type(item[1]) is int and type(item[2]) is int
                and 0 <= item[1] <= item[2] <= len(source.text)
                for item in candidates)):
        raise DomainError('INVALID_ADAPTER_CONTRACT',
            'named_value_spans_invalid')
    return tuple(tuple(item) for item in candidates)


def _register_named_value_spans(source, candidates) -> None:
    candidates = _validate_named_value_spans(source, candidates)
    spans = [*source.redaction_spans,
        *((start, end) for name, start, end in candidates
          if name is None or _sensitive_name(name))]
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    source.redaction_spans[:] = merged


def _register_redaction_spans(units) -> None:
    for unit in units:
        declaration = unit.configuration
        if declaration is not None:
            _register_named_value_spans(unit.source,
                tuple((declaration.key, start, end)
                      for start, end in declaration.value_spans))
        for observation in getattr(unit, 'configuration_observations', ()):
            _register_named_value_spans(
                unit.source, observation.get('named_value_spans', ()))


_ASSIGNMENT_RE = re.compile(
    r'(?m)^([ \t\f]*([^=:\s]+)[ \t\f]*(?:=(?![=>])|:)[ \t\f]*)([^\r\n]*)')
_JSON_ASSIGNMENT_RE = re.compile(
    r'(?m)("(?:\\.|[^"\\])+")([ \t\f]*:[ \t\f]*)'
    r'("(?:\\.|[^"\\])*"|[^,{}\[\]\r\n]+)')
_JSON_KEY_RE = re.compile(
    r'("(?:\\.|[^"\\])+")[ \t\f\r\n]*:[ \t\f\r\n]*')
_INLINE_ASSIGNMENT_PREFIX_RE = re.compile(
    r'(?i)(["\']?)([A-Za-z0-9_.-]+)\1([ \t\f]*(?:=(?![=>])|:)[ \t\f]*)')


def _redact_assignment(match):
    return (match.group(1) + '[REDACTED]'
        if _sensitive_name(match.group(2)) else match.group(0))


def _redact_json_assignment(match):
    try:
        name = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return match.group(0)
    return (match.group(1) + match.group(2) + '"[REDACTED]"'
            if isinstance(name, str) and _sensitive_name(name) else match.group(0))


def _redact_inline_assignments(text):
    spans = []
    for match in _INLINE_ASSIGNMENT_PREFIX_RE.finditer(text):
        if not _sensitive_name(match.group(2)):
            continue
        start = match.end()
        if text.startswith('[REDACTED]', start):
            continue
        line_end = len(text)
        for terminator in ('\r', '\n'):
            found = text.find(terminator, start)
            if found >= 0:
                line_end = min(line_end, found)
        quote = text[start:start + 1]
        if quote in {'"', "'"}:
            cursor, escaped = start + 1, False
            while cursor < line_end:
                character = text[cursor]
                if character == quote and not escaped:
                    break
                escaped = character == '\\' and not escaped
                if character != '\\':
                    escaped = False
                cursor += 1
            value_start, value_end = start + 1, cursor
        else:
            value_start, value_end = start, line_end
        spans.append((value_start, value_end))
    selected = []
    for start, end in sorted(spans):
        if any(parent_start <= start and end <= parent_end
               for parent_start, parent_end in selected):
            continue
        selected.append((start, end))
    for start, end in reversed(selected):
        text = text[:start] + '[REDACTED]' + text[end:]
    return text


def _redact_json_members(text):
    spans = []
    decoder = json.JSONDecoder()
    for match in _JSON_KEY_RE.finditer(text):
        try:
            name = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(name, str) or not _sensitive_name(name):
            continue
        start = match.end()
        try:
            _value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        spans.append((start, end))
    non_overlapping = []
    for start, end in sorted(spans):
        if any(parent_start <= start and end <= parent_end
               for parent_start, parent_end in non_overlapping):
            continue
        non_overlapping.append((start, end))
    for start, end in reversed(non_overlapping):
        replacement = '"[REDACTED]"' + ('\n' * text[start:end].count('\n'))
        text = text[:start] + replacement + text[end:]
    return text


def redacted(text: str) -> str:
    """Remove every value assigned to a sensitive name, through its line end."""
    text = _redact_json_members(text)
    text = _JSON_ASSIGNMENT_RE.sub(_redact_json_assignment, text)
    text = _ASSIGNMENT_RE.sub(_redact_assignment, text)
    return _redact_inline_assignments(text)


def redact_named_value(name, value):
    return '[REDACTED]' if isinstance(name, str) and _sensitive_name(name) \
        else redacted(value) if isinstance(value, str) else redact_values(value)


def redact_values(value):
    """Apply the same credential filter to normalized expressions as excerpts."""
    if isinstance(value, str):
        return redacted(value)
    if isinstance(value, list):
        return [redact_values(item) for item in value]
    if isinstance(value, dict):
        result = dict(value)
        name_key = next((key for key in ('name', 'key') if key in value), None)
        value_key = next((key for key in ('expression', 'value') if key in value), None)
        if name_key is not None and value_key is not None:
            result[value_key] = redact_named_value(value[name_key], value[value_key])
        return {key: (item if key == value_key else redact_values(item))
            for key, item in result.items()}
    return value


def binding_id(unit, name, direction):
    return identifier('binding', unit.symbol_id, name, direction)


def _freeze_runtime(value):
    if isinstance(value, (dict, MappingProxyType)):
        return MappingProxyType({key: _freeze_runtime(item)
            for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_runtime(item) for item in value)
    return value


def _runtime_value_is_valid(value):
    if value is None or type(value) in {bool, int, float, str}:
        return not isinstance(value, float) or math.isfinite(value)
    if isinstance(value, (list, tuple)):
        return all(_runtime_value_is_valid(item) for item in value)
    if isinstance(value, dict):
        return (all(isinstance(key, str) for key in value)
            and all(_runtime_value_is_valid(item) for item in value.values()))
    return False


_LOST_FACTS = {
    'parsing': ('evidence',),
    'declaration_extraction': ('symbols',),
    'bindings': ('bindings',),
    'runtime_selection': ('framework_activation',),
    'type_resolution': ('module_relationships', 'type_relationships'),
}
_FORMAT_DIAGNOSTIC_CODES = frozenset({'JAVA_PROPERTIES_SYNTAX_INVALID',
    'PACKAGE_JSON_INVALID', 'TYPESCRIPT_MODULE_RESOLUTION_INVALID',
    'SPRING_PROPERTY_CONDITION_UNAVAILABLE'})


def _validate_endpoint_request(unit: Unit, request: dict) -> None:
    """Reject a loose adapter request record at the common boundary."""
    expected = {'position', 'end', 'method', 'method_reason', 'url', 'url_reason',
                'conditions', 'evidence_spans'}
    if not isinstance(request, dict) or set(request) != expected:
        raise ValueError('Adapter endpoint request does not match the normalized contract')
    if (type(request['position']) is not int or type(request['end']) is not int
            or not 0 <= request['position'] < request['end'] <= len(unit.text)):
        raise ValueError('Adapter endpoint request requires a valid unit-relative span')
    for field, reason in (('method', 'method_reason'), ('url', 'url_reason')):
        if (request[field] is None) == (request[reason] is None):
            raise ValueError(f'Adapter endpoint request needs exactly one of {field} and {reason}')
    if any(not isinstance(item, (list, tuple)) or len(item) != 2
           or not isinstance(item[0], str) or not isinstance(item[1], bool)
           for item in request['conditions']):
        raise ValueError('Adapter endpoint request conditions must be (test, taken) pairs')
    if not request['evidence_spans'] or any(
            not isinstance(span, (list, tuple)) or len(span) != 3
            or not isinstance(span[0], Source)
            or type(span[1]) is not int or type(span[2]) is not int
            or not 0 <= span[1] < span[2] <= len(span[0].text)
            for span in request['evidence_spans']):
        raise ValueError('Adapter endpoint request requires exact evidence spans')


def _request_path(path: str) -> str:
    """The path of a request URL without its query string or fragment."""
    depth = 0
    for index, character in enumerate(path):
        if character == '{':
            depth += 1
        elif character == '}':
            depth -= 1
        elif depth == 0 and character in '?#':
            return path[:index]
    return path


_PATH_VARIABLE = re.compile(r'\{[^{}]*\}')


def _segment_match(client: str, server: str) -> str | None:
    """'exact', 'possible' (a runtime value could match) or None."""
    if _PATH_VARIABLE.fullmatch(server):
        return 'possible' if ':' in server else 'exact'
    if '{' in client:
        pattern = ''.join('.+' if _PATH_VARIABLE.fullmatch(piece) else re.escape(piece)
                          for piece in re.split(r'(\{[^{}]*\})', client) if piece)
        literal = '{' not in server
        return 'possible' if not literal or re.fullmatch(pattern, server) else None
    if '{' in server:
        pattern = ''.join('[^/]+' if _PATH_VARIABLE.fullmatch(piece) else re.escape(piece)
                          for piece in re.split(r'(\{[^{}]*\})', server) if piece)
        return 'exact' if re.fullmatch(pattern, client) else None
    return 'exact' if client == server else None


def _path_match(client: str, server: str) -> str | None:
    client_segments = [item for item in client.split('/') if item]
    server_segments = [item for item in server.split('/') if item]
    if len(client_segments) != len(server_segments):
        return None
    results = [_segment_match(left, right)
               for left, right in zip(client_segments, server_segments)]
    if None in results:
        return None
    return 'possible' if 'possible' in results else 'exact'


def _same_origin_endpoint(facts: dict, request: dict) -> str | None:
    """The one endpoint anchor a root-relative request reaches, or None.

    ``fetch('/api/owners')`` has no origin to match a declared server base, but
    the call's operation already resolves to its endpoint by method and route.
    An unresolved ``routes_to`` edge would only add a spurious obligation.
    """
    url = request['url']
    if not request['method'] or not url or not url.startswith('/') or url.startswith('//'):
        return None
    anchor_id, resolution, _ = resolve_anchor_identity(
        facts, f"http::{request['method']}:{_request_path(url)}")
    return anchor_id if resolution == 'resolved' else None


def _route_request(request: dict, bases: list[dict], served: list) -> dict | None:
    """The server endpoint(s) one client request reaches, or why none does."""
    method, url = request['method'], request['url']
    if url is None:
        # The destination is dynamic; the call's own operation edge records it.
        return None

    def outcome(resolution, reason=None, target=None, candidates=(),
                evidence_ids=(), evidence_spans=(), conditions=(), notes=(), request_path=None):
        # ``key`` names the edge; ``request_path`` (the path below whichever
        # base was applied) only lets variants of one request find each other.
        return {'resolution': resolution, 'reason': reason, 'target': target,
                'candidates': tuple(candidates), 'evidence_ids': tuple(evidence_ids),
                'evidence_spans': tuple(evidence_spans), 'conditions': tuple(conditions),
                'notes': tuple(notes), 'request_path': request_path,
                'key': (method, target, tuple(candidates), resolution, reason)}

    if method is None:
        return outcome('unresolved', f'The request to {url} has no established HTTP '
                       f'method: {request["method_reason"]}')
    parts = http_url_parts(url)
    if parts is None:
        return outcome('unresolved', f'The request URL {url} has no fixed origin: it is '
                       'relative or its host is a runtime value, and the source does not '
                       'establish which server receives it.')
    scheme, host, port, raw_path = parts
    written = _request_path(raw_path) or '/'
    path = re.sub(r'/{2,}', '/', written)
    notes = []
    if path != written:
        notes.append(('HTTP_TARGET_PATH_NOT_NORMALIZED',
            f'The request URL {url} contains an empty path segment (//). It was '
            f'collapsed to {path} to match endpoints, but the server receives the '
            'URL as written and may reject or route it differently.'))
    trailing = len(path) > 1 and path.endswith('/')
    if trailing:
        path = path[:-1]
    under = [base for base in bases if base['port'] == port and (
        not base['path'] or path == base['path'] or path.startswith(base['path'] + '/'))]
    if not under:
        declared = '; '.join(sorted({f"port {base['port']} at {base['path'] or '/'} "
                                     f"({base['label']})" for base in bases})) or 'none'
        return outcome('unresolved', f'The request to {scheme}://{host}:{port}{path} '
                       f'is under no declared server base (declared: {declared}).',
                       request_path=path)
    matches = []
    for base in under:
        rest = path[len(base['path']):] or '/'
        for representation, scope in served:
            operation = representation['operation']
            if operation['method'].upper() != method:
                continue
            if base['role'] == 'contract':
                if (representation['role'] != 'contract'
                        or representation['source_id'] != base['source_id']):
                    continue
            elif representation['role'] == 'contract' or scope != base['scope']:
                continue
            matched = _path_match(rest, operation['path'])
            if matched:
                matches.append((base, representation, matched))
    used = {id(base): base for base, _, _ in matches} or {id(base): base for base in under}
    evidence_spans = [span for base in used.values() for span in base['evidence_spans']]
    # Each answering base is an alternative: one that always applies makes the
    # route unconditional, and distinct conditions hold in either case.
    alternatives = sorted({base['condition'] for base in used.values()},
                          key=lambda condition: condition or '')
    conditions = ([] if not alternatives or None in alternatives else
                  [(alternatives[0], True)] if len(alternatives) == 1 else
                  [('(' + ') || ('.join(alternatives) + ')', True)])
    if not matches:
        labels = '; '.join(sorted({base['label'] for base in under}))
        return outcome('unresolved', f'No declared {method} endpoint matches {path} '
                       f'under its server base ({labels}).',
                       evidence_spans=evidence_spans, notes=notes)
    if trailing and any(not representation['operation']['path'].endswith('/')
                        for _, representation, _ in matches):
        notes.append(('HTTP_TARGET_TRAILING_SLASH_MISMATCH',
            f'The request path of {url} ends with /, but the matched endpoint is '
            'declared without one. Whether the server treats them as equal is '
            'runtime configuration.'))
    symbols = sorted({representation['symbol_id'] for _, representation, _ in matches})
    evidence_ids = sorted({evidence_id for _, representation, _ in matches
                           for evidence_id in representation['evidence_ids']})
    endpoints = ', '.join(sorted({f"{representation['operation']['method']} "
                                  f"{representation['operation']['path']}"
                                  for _, representation, _ in matches}))
    # A runtime value standing where an endpoint has a literal segment matches
    # only if it happens to equal that literal. Such a match widens the
    # candidates but never establishes a route on its own.
    if not any(matched == 'exact' for _, _, matched in matches):
        return outcome('unresolved', f'{method} {path} reaches {endpoints} only if a runtime '
                       'value equals a literal path segment, which the source does not '
                       'establish.', evidence_spans=evidence_spans, notes=notes)
    if len(symbols) == 1:
        base = next(base for base, _, _ in matches)
        return outcome('resolved', target=symbols[0], evidence_ids=evidence_ids,
                       evidence_spans=evidence_spans, conditions=conditions, notes=notes,
                       request_path=path[len(base['path']):] or '/')
    return outcome('ambiguous', f'{len(symbols)} declared endpoints can answer {method} '
                   f'{path}: {endpoints}.', candidates=symbols[:MAX_SEMANTIC_CANDIDATES],
                   evidence_ids=evidence_ids, evidence_spans=evidence_spans,
                   conditions=conditions, notes=notes)


def _route_condition(alternatives: list[list]) -> str | None:
    """Render the branch choices under which a request takes one route."""
    rendered = [[test if taken else f'!({test})' for test, taken in conditions]
                for conditions in alternatives]
    if not rendered or any(not item for item in rendered):
        return None
    common = [term for term in rendered[0] if all(term in other for other in rendered[1:])]
    rests = []
    for item in rendered:
        rest = [term for term in item if term not in common]
        if rest not in rests:
            rests.append(rest)
    if any(not rest for rest in rests):
        clause = None
    elif len(rests) == 1:
        clause = ' && '.join(rests[0])
    else:
        clause = '(' + ' || '.join('(' + ' && '.join(rest) + ')' for rest in rests) + ')'
    return ' && '.join(common + ([clause] if clause else [])) or None


def _merged_descriptor(descriptors) -> dict:
    """One owner view over the descriptors that share an installed module."""
    descriptors = list(descriptors)
    return {**descriptors[0], 'diagnostic_codes': sorted({code
        for descriptor in descriptors
        for code in descriptor.get('diagnostic_codes', ())})}


class Extractor:
    def __init__(self, root: Path, config: dict, build_id: str | None = None):
        self.root=root.resolve();self.config=config
        try:
            registry.require_valid()
        except RegistryConfigurationError as error:
            raise DomainError('ADAPTER_REGISTRY_INVALID', str(error)) from None
        self.scan = scan_inventory(self.root, config)
        decoded = inventory(self.scan, config)
        self.sources = list(decoded.sources)
        self.routes = {route.classification.path: route for route in decoded.routes}
        self.provisional_decoders = dict(decoded.provisional_decoders)
        self.diagnostics = list(decoded.diagnostics)
        self.selections_by_source_id = {}
        self.executions_by_source_id = {}
        self.owner_module_cache = {}
        self.enricher_descriptors_by_source_id = {}
        self.selected_modules = []
        self.facts=record('FactsArtifact',generated_at=now(),build_id=build_id or str(uuid.uuid4()),limits=limits(config))
        self.facts['warnings']=self.diagnostics
        self.units: list[Unit]=[]
        self.anchor_units: dict[int, tuple[str, str]] = {}
        # Evidence id of a root-relative request -> the endpoint anchor it reaches.
        self.same_origin_requests: dict[str, str] = {}
        # Edge id -> adapter diagnostic codes of the semantic result behind it.
        self.edge_codes: dict[str, set[str]] = {}
        self.snapshot_objects: dict[str,dict]={}
        self.external_freshness = 'not_applicable'
        self.snapshot_inputs = {}
        previous = read_json(self.root/'.speed/context/business-domain-facts.json')
        self.previous_snapshots = previous.get('source_snapshots', {}) if previous else {}

    def _owner(self, source: Source):
        """The primary owner loaded for *source*, or None; never reselected."""
        execution = self.executions_by_source_id.get(source.resource_id)
        return (execution.loaded_owner
                if execution is not None and execution.state == 'resolved' else None)

    def evidence(self, source: Source, start: int, end: int) -> str:
        if source.evidence_redaction_required:
            excerpt = '[REDACTED]'
        else:
            excerpt = source.text[start:end]
            intersections = [(max(span_start, start) - start,
                              min(span_end, end) - start)
                for span_start, span_end in source.redaction_spans
                if span_start < end and start < span_end]
            for local_start, local_end in reversed(intersections):
                excerpt = excerpt[:local_start] + '[REDACTED]' + excerpt[local_end:]
            excerpt = redacted(excerpt)
        sid=identifier('snapshot',source.path,source.source_hash,start,end)
        eid=identifier('ev',source.path,source.source_hash,start,end)
        if eid in self.facts['evidence']:return eid
        snapshot=record('SnapshotArtifact',snapshot_id=sid,source_hash=source.source_hash,fragments=[{
            'id':identifier('fragment',eid),'original_locator':source.path,'text':excerpt,'excerpt_hash':digest(excerpt.encode())}])
        blob=digest(snapshot)
        self.snapshot_objects[blob]=snapshot
        path=f'.speed/context/business-domain-snapshots/{blob}.json'
        previous = self.previous_snapshots.get(sid)
        captured_at = previous['retrieved_at'] if previous and previous['content_hash'] == source.source_hash else now()
        route = self.routes.get(source.path)
        category = (route.classification.category if route
                    else registry.classify_path(source.path).category)
        self.facts['source_snapshots'][sid] = record('Snapshot', id=sid,
            resource_kind=source.language or category,
            resource_identity=source.path, content_hash=source.source_hash,
            local_blob_path=path, retrieved_at=captured_at)
        kind = ('test' if re.search(CATALOG['test_path_pattern'], source.path)
            else CATALOG['source_kind_by_category'].get(category, 'source'))
        self.facts['evidence'][eid]=record('Evidence',id=eid,source_kind=kind,locator={'kind':'repository_span','path':source.path,'start_line':source.text.count('\n',0,start)+1,'end_line':source.text.count('\n',0,max(start,end-1))+1,'source_hash':source.source_hash,'snapshot_id':sid,'pointer':'/fragments/0/text'},content_hash=digest(excerpt.encode()),excerpt=excerpt,claim_kind='source_observation',extractor=source.adapter_id,extractor_version=source.adapter_version)
        return eid

    def add_unit(self, unit: Unit) -> None:
        unit.symbol_id=identifier('symbol',unit.qualified)
        unit.evidence_id=self.evidence(unit.source,unit.start,unit.end)
        supporting = []
        for source, start, end in unit.supporting_evidence_spans:
            if (not isinstance(source, Source) or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(source.text)):
                raise ValueError('Unit supporting evidence requires a valid source span')
            evidence_id = self.evidence(source, start, end)
            if evidence_id != unit.evidence_id and evidence_id not in supporting:
                supporting.append(evidence_id)
        self.facts['symbols'][unit.symbol_id]=record('Symbol',id=unit.symbol_id,qualified_name=unit.qualified,signature=unit.name+'('+','.join(t for _,t in unit.params)+')',kind=unit.kind,file=unit.source.path,evidence_ids=[unit.evidence_id, *supporting])
        if self.facts['evidence'][unit.evidence_id]['source_kind']=='test':unit.anchor_kind=None
        trace_contract = (
            getattr(unit, 'trace_role', None),
            getattr(unit, 'required_relationships', None),
            getattr(unit, 'required_capabilities', None),
            getattr(unit, 'valid_terminal', None),
        )
        if unit.kind in {'function', 'method', 'declarative_operation'}:
            if any(value is None for value in trace_contract):
                raise DomainError('INVALID_ADAPTER_CONTRACT',
                    'Callable producer must declare its trace role, relationship and capability obligations, and terminal status')
            if unit.trace_role not in TRACE_ROLES \
                    or set(unit.required_relationships) - {'implementation_selection'} \
                    or set(unit.required_capabilities) - SOURCE_ADAPTER_CAPABILITIES \
                    or type(unit.valid_terminal) is not bool \
                    or (unit.valid_terminal and (
                        unit.trace_role != 'implementation' or not unit.executable_body)) \
                    or (unit.trace_role not in {'implementation', 'external_boundary'}
                        and 'implementation_selection' not in unit.required_relationships):
                raise DomainError('INVALID_ADAPTER_CONTRACT',
                    'Callable producer supplied an inconsistent normalized trace contract')
        if unit.anchor_kind:
            unit.anchor_id=identifier('anchor',unit.qualified,unit.anchor_kind)
            anchor_evidence = {unit.evidence_id}
            anchor_evidence.update(self.evidence(source, start, end)
                for source, start, end in unit.anchor_evidence_spans)
            service_id = identifier('resource', 'service', unit.source.service_scope)
            self.facts['resources'].setdefault(service_id, record('Resource',
                id=service_id, kind='service', name=unit.source.service_scope,
                language=None, evidence_ids=[], resolution='resolved', reason=None))
            operation=record('Operation',protocol=unit.anchor_kind,name=unit.name,
                method=unit.method,path=unit.route,service_resource_id=service_id)
            role = getattr(unit, 'anchor_role', None) or (
                'contract' if unit.trace_role in {'contract', 'interface', 'declaration'}
                else 'implementation')
            if role in {'registration', 'exposure'} and unit.anchor_registration is None:
                raise DomainError('INVALID_ADAPTER_CONTRACT',
                    'Entry-point registration representation requires normalized registration metadata')
            identity_key = getattr(unit, 'anchor_identity_key', None)
            eligibility = getattr(unit, 'anchor_eligibility', None) or (
                'eligible' if unit.anchor_resolution == 'resolved' and identity_key
                and role in {'registration', 'exposure', 'contract'} else 'supporting'
                if role == 'implementation' else 'unresolved')
            representation_id = identifier('anchor_representation', unit.qualified, role)
            registration = None
            if unit.anchor_registration is not None:
                spans = unit.anchor_registration_evidence_spans or [
                    (unit.source, unit.start, unit.end)]
                registration = record('EntryPointRegistration',
                    **unit.anchor_registration,
                    evidence_ids=sorted({self.evidence(source, start, end)
                        for source, start, end in spans}))
                anchor_evidence.update(registration['evidence_ids'])
            representation = record('AnchorRepresentation', id=representation_id,
                role=role, identity_key=identity_key, source_id=unit.source.resource_id,
                symbol_id=unit.symbol_id, operation=operation, eligibility=eligibility,
                visibility=getattr(unit, 'anchor_visibility', None) or
                    ('external' if eligibility == 'eligible' else 'internal'),
                registration=registration, evidence_ids=sorted(anchor_evidence), resolution=unit.anchor_resolution,
                reason=unit.anchor_reason)
            self.facts['anchors'][unit.anchor_id]=record('Anchor',id=unit.anchor_id,
                kind=unit.anchor_kind,source_id=unit.source.resource_id,
                symbol_id=unit.symbol_id,operation=operation,status='candidate',
                evidence_ids=sorted(anchor_evidence),resolution=unit.anchor_resolution,
                reason=unit.anchor_reason,representations=[representation])
            if unit.anchor_kind in {'http', 'rpc', 'graphql'}:
                endpoint_edge = identifier('edge', unit.symbol_id,
                                           'exposes_endpoint', unit.anchor_id)
                self.facts['edges'][endpoint_edge] = record(
                    'Edge', id=endpoint_edge,
                    from_ref={'kind':'symbol', 'id':unit.symbol_id},
                    to_ref={'kind':'anchor', 'id':unit.anchor_id},
                    kind='exposes_endpoint', evidence_ids=sorted(anchor_evidence),
                    resolution='resolved', reason=None)
                self.facts['coverage']['edges_resolved'] += 1
            self.anchor_units[id(unit)] = (unit.anchor_id, representation_id)
        owner = self._owner(unit.source)
        for binding in owner.bindings(unit) if owner else ():
            binding = redact_values(binding)
            position = binding.pop('position', None)
            end = binding.pop('end', None)
            if (position is None) != (end is None) or (position is not None and (
                    type(position) is not int or type(end) is not int
                    or not 0 <= position < end <= len(unit.text))):
                raise ValueError('Adapter binding requires a valid unit-relative span')
            evidence_id = (unit.evidence_id if position is None else
                self.evidence(unit.source, unit.start+position, unit.start+end))
            bid=binding_id(unit,binding['name'],binding['direction'])
            self.facts['bindings'][bid]=record('Binding',id=bid,
                source={'kind':'symbol','id':unit.symbol_id},target={'kind':'symbol','id':unit.symbol_id},
                evidence_ids=[evidence_id],**binding)

    def _execute_installed_owners(self):
        """Select, load and run every installed owner exactly once per source."""
        primary_groups = {}
        for source in self.sources:
            route = self.routes[source.path]
            self.facts['resources'][source.resource_id] = record('Resource',
                id=source.resource_id, kind='repository_file', name=source.path,
                language=source.language)
            selection = select_source(source, route)
            execution = load_selection(source, selection,
                self.provisional_decoders.get(source.resource_id),
                self.owner_module_cache)
            self.selections_by_source_id[source.resource_id] = selection
            self.executions_by_source_id[source.resource_id] = execution
            descriptor = selection.selected_descriptor or {}
            if descriptor and route.disposition == 'analyze':
                parser_id = descriptor.get('parser')
                source.adapter_id = (f"{descriptor['id']}/{parser_id}"
                    if parser_id else descriptor['id'])
                source.adapter_version = (descriptor.get('parser_version')
                    or descriptor.get('version', '1'))
                source.declared_capabilities = registry.effective_capabilities(
                    descriptor, source.language)
                source.parser_required = bool(parser_id)
            self.units.extend(execution.output)
            if execution.output:
                _register_redaction_spans(execution.output)
            if (route.disposition == 'analyze'
                    and execution.state == 'resolved'
                    and execution.loaded_owner is not None):
                # Several descriptors may share one module; it prepares its
                # sources once, as one group.
                group = primary_groups.setdefault(id(execution.loaded_owner),
                    (execution.loaded_owner, {}, []))
                group[1][descriptor['id']] = descriptor
                group[2].append(source)

        self._run_supporting_consumers()

        # Resolve cross-file semantics through installed provider hooks. Core
        # orchestration does not inspect language or framework identities.
        selected_modules = []
        for module, descriptors, sources in sorted(primary_groups.values(),
                key=lambda item: (getattr(item[0], 'PREPARE_PHASE', 100),
                                  getattr(item[0], '__name__', type(item[0]).__name__))):
            selected_modules.append((module, sources))
            owner = _merged_descriptor(descriptors.values())
            prepare = getattr(module, 'prepare', None)
            if prepare:
                try:
                    pending = prepare(sources, self.units, self.diagnostics)
                except DomainError:
                    raise
                except Exception:
                    raise DomainError('ADAPTER_UNAVAILABLE',
                        'primary_prepare_failed') from None
                if pending is not None:
                    if not isinstance(pending, list) or not all(
                            isinstance(item, dict) for item in pending):
                        raise DomainError('INVALID_ADAPTER_CONTRACT',
                            'primary_prepare_result_invalid')
                    for item in pending:
                        self._project_adapter_diagnostic(owner, item)
            diagnostics = getattr(module, 'diagnostics', None)
            if diagnostics:
                for source in sources:
                    descriptor = self.selections_by_source_id[
                        source.resource_id].selected_descriptor
                    for item in diagnostics(source):
                        self._project_adapter_diagnostic(
                            descriptor, item, source)

        enricher_groups = {}
        for source in self.sources:
            owner = self._owner(source)
            if owner is None or self.routes[source.path].disposition != 'analyze':
                continue
            evidence = dict(getattr(owner, 'activation_evidence',
                lambda _source: {})(source))
            package = source.supporting_inputs.get('package_manifest', {}).get(
                'package')
            if package:
                evidence['dependencies'] = sorted({
                    *evidence.get('dependencies', ()),
                    *(item['name'] for item in package['dependencies'])})
            descriptors = tuple(enricher_descriptors(source, evidence))
            self.enricher_descriptors_by_source_id[source.resource_id] = descriptors
            # Several descriptors can name one module (Spring Web, Data and
            # beans all run spring_semantic); the module still gets each source
            # once.
            modules = {}
            for descriptor in descriptors:
                try:
                    cache_key = ('enricher', descriptor['id'],
                        descriptor['module'])
                    module = self.owner_module_cache.get(cache_key)
                    if module is None:
                        module = load_installed(descriptor['module'])
                        self.owner_module_cache[cache_key] = module
                except Exception:
                    raise DomainError('ADAPTER_UNAVAILABLE',
                        'enricher_load_failed') from None
                modules.setdefault(id(module), (module, []))[1].append(descriptor)
            for module, module_descriptors in modules.values():
                group = enricher_groups.setdefault(id(module), (module, {}, []))
                group[1].update((item['id'], item) for item in module_descriptors)
                group[2].append(source)
        for module, descriptors, sources in sorted(enricher_groups.values(),
                key=lambda item: getattr(item[0], '__name__', type(item[0]).__name__)):
            selected_modules.append((module, sources))
            owner = _merged_descriptor(descriptors.values())
            # Repository configuration (properties, YAML) has no units of its
            # own; an enricher that interprets it reads it here, before it
            # prepares the sources it was selected for.
            configure = getattr(module, 'configure', None)
            if configure:
                configure(sources, self.sources)
            prepare = getattr(module, 'prepare', None)
            if prepare:
                try:
                    pending = prepare(sources, self.units, self.diagnostics)
                except DomainError:
                    raise
                except Exception:
                    raise DomainError('ADAPTER_UNAVAILABLE',
                        'enricher_prepare_failed') from None
                _register_redaction_spans(self.units)
                if pending is not None:
                    if not isinstance(pending, list) or not all(
                            isinstance(item, dict) for item in pending):
                        raise DomainError('INVALID_ADAPTER_CONTRACT',
                            'enricher_prepare_result_invalid')
                    for item in pending:
                        self._project_adapter_diagnostic(owner, item)
        self.selected_modules = sorted(selected_modules,
            key=lambda item: getattr(item[0], '__name__', type(item[0]).__name__))

    def _validate_adapter_diagnostic(self, descriptor, diagnostic, source=None):
        if not isinstance(diagnostic, dict):
            raise DomainError('INVALID_ADAPTER_CONTRACT',
                'adapter_diagnostic_invalid')
        if set(diagnostic) - {
                'source_id', 'code', 'reason', 'span', 'named_value_spans'}:
            raise DomainError('INVALID_ADAPTER_CONTRACT',
                'adapter_diagnostic_fields_invalid')
        source_id = diagnostic.get('source_id')
        if source is None:
            source = next((item for item in self.sources
                if item.resource_id == source_id), None)
        elif source_id is not None and source_id != source.resource_id:
            raise DomainError('INVALID_ADAPTER_CONTRACT',
                'adapter_diagnostic_source_invalid')
        span = diagnostic.get('span')
        reason = diagnostic.get('reason')
        code = diagnostic.get('code')
        named_spans = diagnostic.get('named_value_spans', ())
        if (source is None
                or not isinstance(span, (tuple, list)) or len(span) != 2
                or any(type(value) is not int for value in span)
                or not 0 <= span[0] <= span[1] <= len(source.text)
                or code not in (descriptor or {}).get('diagnostic_codes', ())
                or not isinstance(reason, str) or not reason
                or '\n' in reason or '\r' in reason):
            raise DomainError('INVALID_ADAPTER_CONTRACT',
                'adapter_diagnostic_invalid')
        _validate_named_value_spans(source, named_spans)
        return source

    def _project_adapter_diagnostic(self, descriptor, diagnostic, source=None):
        """Project one adapter, consumer or enricher diagnostic with exact evidence."""
        source = self._validate_adapter_diagnostic(
            descriptor, diagnostic, source)
        span = diagnostic['span']
        named_spans = diagnostic.get('named_value_spans', ())
        _register_named_value_spans(source, named_spans)
        evidence_id = self.evidence(source, span[0], span[1])
        self.diagnostics.append(record('Diagnostic', code=diagnostic['code'],
            message=diagnostic['reason'], subject_ids=[source.resource_id],
            evidence_ids=[evidence_id]))

    def _run_supporting_consumers(self):
        """Run each supporting owner once over its group; apply only valid results."""
        grouped = {}
        for execution in self.executions_by_source_id.values():
            if execution.selection.route.disposition == 'supporting' \
                    and execution.state == 'resolved':
                owner_id = execution.selection.selected_descriptor['id']
                grouped.setdefault(owner_id, []).append(execution)
        for owner_id, executions in sorted(grouped.items()):
            descriptor = executions[0].selection.selected_descriptor
            module = executions[0].loaded_owner
            consume = getattr(module, descriptor['function'], None)
            if not callable(consume):
                for execution in executions:
                    execution.state = 'unresolved'
                    execution.cause = 'owner_execution_failed'
                continue
            sources = tuple(item.source for item in executions)
            primary_sources = tuple(execution.source for execution
                in self.executions_by_source_id.values()
                if execution.selection.route.disposition == 'analyze'
                and execution.state == 'resolved')
            try:
                result = consume(sources, primary_sources)
            except Exception:
                for execution in executions:
                    execution.state = 'unresolved'
                    execution.cause = 'owner_execution_failed'
                continue
            try:
                if not isinstance(result, SupportingConsumerResult):
                    raise TypeError('supporting_result_invalid')
                expected = {source.resource_id for source in sources}
                if (not all(isinstance(item, str)
                            for item in result.consumed_source_ids)
                        or not all(isinstance(item, dict)
                                   for item in result.diagnostics)
                        or not all(isinstance(item, dict)
                                   for item in result.normalized_inputs)):
                    raise TypeError('supporting_result_element_invalid')
                if not all(_runtime_value_is_valid(item)
                           for item in result.normalized_inputs):
                    raise TypeError('supporting_input_value_invalid')
                consumed = list(result.consumed_source_ids)
                diagnosed = [item.get('source_id') for item in result.diagnostics]
                if (len(consumed) != len(set(consumed))
                        or len(diagnosed) != len(set(diagnosed))
                        or set(consumed) & set(diagnosed)
                        or set(consumed) | set(diagnosed) != expected
                        or any(item.get('source_id') not in expected
                               for item in result.diagnostics)):
                    raise ValueError('supporting_consumption_invalid')
                diagnostic_plan = tuple((item,
                    self._validate_adapter_diagnostic(descriptor, item))
                    for item in result.diagnostics)
                if any(not {'source_id', 'scope_dir', 'document_kind'} <= set(item)
                       or not all(isinstance(item[key], str) and item[key]
                                  for key in ('source_id', 'scope_dir',
                                              'document_kind'))
                       for item in result.normalized_inputs):
                    raise ValueError('supporting_input_shape_invalid')
                normalized_ids = [item.get('source_id')
                    for item in result.normalized_inputs]
                if (len(normalized_ids) != len(set(normalized_ids))
                        or set(normalized_ids) != set(consumed)):
                    raise ValueError('supporting_inputs_invalid')
                assignment_plan = self._supporting_assignment_plan(
                    owner_id, result.normalized_inputs, primary_sources)
            except Exception:
                for execution in executions:
                    execution.state = 'unresolved'
                    execution.cause = 'consumer_contract_invalid'
                continue
            by_id = {execution.source.resource_id: execution
                for execution in executions}
            for diagnostic, source in diagnostic_plan:
                by_id[source.resource_id].diagnostics.append(diagnostic)
                by_id[source.resource_id].state = 'unresolved'
                self._project_adapter_diagnostic(
                    descriptor, diagnostic, source)
            for source, selected in assignment_plan:
                current = dict(source.supporting_inputs)
                current[owner_id] = _freeze_runtime(selected)
                source.supporting_inputs = MappingProxyType(current)

    def _supporting_assignment_plan(self, owner_id, records, primary_sources):
        """The deepest compatible record of each kind for every primary source."""
        del owner_id
        by_kind = {}
        for item in records:
            by_kind.setdefault(item['document_kind'], []).append(item)
        plan = []
        for source in primary_sources:
            selected = {}
            source_parts = PurePosixPath(source.path).parts[:-1]
            for kind, candidates in by_kind.items():
                compatible = []
                for item in candidates:
                    scope = () if item['scope_dir'] == '.' else tuple(
                        PurePosixPath(item['scope_dir']).parts)
                    if source_parts[:len(scope)] == scope:
                        compatible.append((len(scope), item))
                if not compatible:
                    continue
                depth = max(entry[0] for entry in compatible)
                winners = [entry[1] for entry in compatible if entry[0] == depth]
                if len(winners) != 1:
                    raise ValueError('supporting_scope_ambiguous')
                selected[kind] = winners[0]
            if selected:
                plan.append((source, selected))
        return tuple(plan)

    def _blocking_source_diagnostic(self, execution):
        """The one blocking diagnostic, Resource state and coverage entry of a source."""
        selection, route, source = (execution.selection,
            execution.selection.route, execution.source)
        cause = execution.cause
        code = ('AMBIGUOUS_ADAPTER'
                if cause in {'ambiguous_language', 'multiple_owners'} else
                'SOURCE_CAPABILITY_UNAVAILABLE'
                if cause == 'owner_not_installed' else 'ADAPTER_UNAVAILABLE')
        lost = sorted({fact for capability in route.required_capabilities
            for fact in _LOST_FACTS[capability]})
        language = route.classification.language or 'null'
        owner = route.expected_owner or 'null'
        required = ','.join(route.required_capabilities)
        candidates = ','.join(selection.candidate_owner_ids)
        message = (f'{source.path}: language={language}; '
            f'disposition={route.disposition}; required=[{required}]; '
            f'owner={owner}; candidates=[{candidates}]; cause={cause}; '
            f'lost_facts=[{",".join(lost)}].')
        evidence_id = self.evidence(source, 0, min(len(source.text), 4096))
        self.diagnostics.append(record('Diagnostic', code=code,
            message=message, subject_ids=[source.resource_id],
            evidence_ids=[evidence_id]))
        resource = self.facts['resources'][source.resource_id]
        resource.update(resolution='unresolved', reason=message,
            evidence_ids=[evidence_id])
        unsupported = self.facts['coverage']['unsupported_source_ids']
        if source.resource_id not in unsupported:
            unsupported.append(source.resource_id)

    def _finalize_source_resources(self):
        """Settle each selected source's own Resource; ignored sources have none."""
        unit_evidence = {}
        for unit in self.units:
            if unit.evidence_id:
                unit_evidence.setdefault(id(unit.source), set()).add(unit.evidence_id)
        format_subjects = {subject for diagnostic in self.diagnostics
                           if diagnostic['code'] in _FORMAT_DIAGNOSTIC_CODES
                           for subject in diagnostic.get('subject_ids', ())}
        for source in self.sources:
            route = self.routes[source.path]
            execution = self.executions_by_source_id[source.resource_id]
            if execution.cause is not None:
                self._blocking_source_diagnostic(execution)
                continue
            resource = self.facts['resources'][source.resource_id]
            if route.disposition == 'reference_only':
                evidence_id = self.evidence(source, 0, min(len(source.text), 4096))
                resource.update(evidence_ids=[evidence_id], resolution='unresolved',
                    reason=f'Reference-only {route.expected_owner}: retained for context; '
                           'no business semantics were inferred.')
                continue
            evidence_ids = sorted(unit_evidence.get(id(source), ()))
            if not evidence_ids:
                evidence_ids = [self.evidence(source, 0,
                    min(len(source.text), 4096))]
            has_format_error = source.resource_id in format_subjects
            resource.update(evidence_ids=evidence_ids,
                resolution='unresolved' if has_format_error else 'resolved',
                reason=('Selected source reported invalid input.'
                        if has_format_error else None))

    def extract(self) -> tuple[dict,list[Unit]]:
        self._execute_installed_owners()
        for unit in self.units:
            self.add_unit(unit)
        self._connections()
        self._anchor_correspondences()
        self._observations()
        self._canonicalize_anchors()
        self._endpoint_links()
        self._documentation_edges()
        self._finalize_source_resources()
        self._capabilities()
        self._traces()
        self._entrypoint_coverage()
        from .business_domain_snapshots import capture_supplied
        self.external_freshness,self.snapshot_inputs = capture_supplied(self)
        self.facts['coverage']['anchors_total']=len(self.facts['anchors'])
        self.facts['coverage']['anchors_pending']=len(self.facts['anchors'])
        self.facts['coverage']['evidence_valid']=len(self.facts['evidence'])
        self.facts['limits']['source_bytes']=sum(
            source.original_byte_length for source in self.sources)
        self.facts['limits']['semantic_units_total']=len(self.facts['traces'])
        self.facts['limits']['semantic_units_pending']=len(self.facts['traces'])
        return self._finalize_artifact()

    def _finalize_artifact(self):
        installed = Path(__file__).parent
        fp = dict(sources=source_fingerprint(self.scan),
            configuration=digest(self.config),
            extractors=implementation_hash(Path(__file__),installed/'business_domain_adapters',
                installed/'rules',installed/'data',installed/'language_registry.py',
                installed/'treesitter_extract.py',installed/'business_domain_schema.py',
                installed/'business_domain_snapshots.py',
                installed/'business_domain_identity.py',installed/'business_domain_policies.json',
                installed/'business_domain_reference_targets.json',
                installed/'business_domain_artifacts.schema.json',
                installed/'layer1_domain_clustering.py'),
            prompts=digest({}),provider=digest({}),overrides=digest({}),
            snapshots=digest({'records':self.facts['source_snapshots'],'inputs':self.snapshot_inputs}))
        fp['value']=digest(fp);self.facts['fingerprint']=fp
        for blob,snapshot in self.snapshot_objects.items():atomic_write(self.root/'.speed/context/business-domain-snapshots'/f'{blob}.json',snapshot)
        account_artifact_bytes(self.facts)
        validate_source_warning_coverage(self.facts)
        validate(self.facts,'FactsArtifact')
        return self.facts,self.units

    def _anchor_correspondences(self) -> None:
        """Materialize adapter-provided identity evidence without source rules."""
        entries = []
        for unit in self.units:
            owned = self.anchor_units.get(id(unit))
            if not owned or owned[0] not in self.facts['anchors']:
                continue
            anchor = self.facts['anchors'][owned[0]]
            entries.append((unit, anchor, anchor['representations'][0]))
        by_unit = {id(unit): (anchor, representation)
            for unit, anchor, representation in entries}
        assigned = set()
        resolved_pairs = set()
        ambiguous_groups = set()

        def relationship_edges(representations):
            symbols = {item['symbol_id'] for item in representations if item['symbol_id']}
            return sorted(edge['id'] for edge in self.facts['edges'].values()
                if edge['from_ref']['id'] in symbols and (
                    edge['to_ref'] and edge['to_ref']['kind'] == 'symbol'
                    and edge['to_ref']['id'] in symbols
                    or set(edge.get('candidate_target_ids', [])) & symbols))

        def add(source, targets, state, reason):
            source_anchor, source_representation = source
            target_representations = sorted(
                {target[1]['id']: target[1] for target in targets}.values(),
                key=lambda item: item['id'])[:MAX_SEMANTIC_CANDIDATES]
            if not target_representations:
                target_representations = [source_representation]
            all_representations = [source_representation, *target_representations]
            edge_ids = relationship_edges(all_representations)
            evidence_ids = sorted({evidence_id for item in all_representations
                for evidence_id in item['evidence_ids']} | {
                evidence_id for edge_id in edge_ids
                for evidence_id in self.facts['edges'][edge_id]['evidence_ids']})
            correspondence_id = identifier('anchor_correspondence',
                source_representation['id'], sorted(item['id'] for item in target_representations), state)
            source_anchor['correspondences'].append(record('AnchorCorrespondence',
                id=correspondence_id,
                from_representation=source_representation['id'],
                to_representations=sorted({item['id'] for item in target_representations}),
                relationship_edges=edge_ids, state=state,
                evidence_ids=evidence_ids, reason=reason))
            assigned.update(item['id'] for item in all_representations)
            target_ids = frozenset(item['id'] for item in target_representations)
            if state == 'resolved':
                resolved_pairs.update(frozenset((source_representation['id'], target_id))
                    for target_id in target_ids)
            elif state == 'ambiguous':
                ambiguous_groups.add(frozenset({source_representation['id'], *target_ids}))

        def contextual_target(source, unit):
            """Retain a supporting implementation without promoting its body."""
            source_anchor, source_representation = source
            representation_id = identifier('anchor_representation',
                source_representation['id'], unit.qualified, 'implementation')
            existing = next((item for item in source_anchor['representations']
                if item['id'] == representation_id), None)
            if existing:
                return source_anchor, existing
            service_id = identifier('resource', 'service', unit.source.service_scope)
            self.facts['resources'].setdefault(service_id, record('Resource',
                id=service_id, kind='service', name=unit.source.service_scope,
                language=None, evidence_ids=[], resolution='resolved', reason=None))
            operation = record('Operation', protocol=source_anchor['kind'],
                name=unit.name, service_resource_id=service_id)
            representation = record('AnchorRepresentation', id=representation_id,
                role='implementation', identity_key=source_representation['identity_key'],
                source_id=unit.source.resource_id, symbol_id=unit.symbol_id,
                operation=operation, registration=None, eligibility='supporting',
                visibility='internal', evidence_ids=[unit.evidence_id],
                resolution='resolved', reason=None)
            source_anchor['representations'].append(representation)
            return source_anchor, representation

        # Exact semantic links (for example, SQL contract/body selection) take
        # precedence over protocol-key and unresolved-candidate grouping.
        for unit, _, representation in entries:
            declared_targets = getattr(unit, 'anchor_correspondence_units', [])
            targets = [(by_unit[id(target)] if id(target) in by_unit else
                        contextual_target(by_unit[id(unit)], target))
                       for target in declared_targets]
            if not declared_targets:
                continue
            state = getattr(unit, 'anchor_correspondence_state', None) or (
                'resolved' if len(targets) == 1 else 'ambiguous')
            add(by_unit[id(unit)], targets, state,
                getattr(unit, 'anchor_correspondence_reason', None) or
                ('Adapter resolved these source representations.' if state == 'resolved'
                 else 'Several adapter-supported source representations remain viable.'))

        exact = {}
        for unit, anchor, representation in entries:
            if representation['identity_key']:
                exact.setdefault(representation['identity_key'], []).append(
                    (unit, anchor, representation))
        for group in exact.values():
            if len(group) < 2:
                continue
            implementations = [item for item in group
                if item[2]['role'] == 'implementation']
            registrations = [item for item in group
                if item[2]['role'] == 'registration']
            state = ('ambiguous' if len(implementations) > 1
                     or len(registrations) > 1 else 'resolved')
            source = next((item for item in group
                if item[2]['role'] in {'registration', 'exposure', 'contract'}), group[0])
            targets = [by_unit[id(item[0])] for item in group if item is not source]
            if state == 'resolved':
                for target in targets:
                    pair = frozenset((source[2]['id'], target[1]['id']))
                    if pair not in resolved_pairs:
                        add(by_unit[id(source[0])], [target], state,
                            'Exact adapter-established operation identity links these representations.')
            else:
                group_ids = frozenset(item[2]['id'] for item in group)
                if group_ids not in ambiguous_groups:
                    add(by_unit[id(source[0])], targets, state,
                        'Exact operation identity has multiple viable implementations or registrations.')

        candidates = {}
        for unit, anchor, representation in entries:
            key = getattr(unit, 'anchor_candidate_key', None) or (
                unit.source.service_scope, unit.anchor_kind, unit.name.casefold())
            if representation['id'] not in assigned and key:
                candidates.setdefault(key, []).append((unit, anchor, representation))
        for group in candidates.values():
            contracts = [item for item in group if item[2]['role'] == 'contract']
            implementations = [item for item in group if item[2]['role'] == 'implementation']
            if not contracts or not implementations:
                continue
            for source in contracts:
                targets = [by_unit[id(item[0])] for item in implementations]
                add(by_unit[id(source[0])], targets,
                    'ambiguous' if len(targets) > 1 else 'unresolved',
                    'A possible contract/implementation correspondence lacks exact relationship evidence.')

        for unit, anchor, representation in entries:
            if representation['id'] in assigned:
                continue
            resolved = (representation['eligibility'] == 'eligible'
                and representation['role'] in {'registration', 'exposure'})
            add(by_unit[id(unit)], [], 'resolved' if resolved else 'unresolved',
                'The registration directly establishes this canonical entry point.'
                if resolved else 'No exact implementation correspondence is available.')

    def _capabilities(self) -> None:
        """Project the stored selections' capabilities; nothing is reselected."""
        capabilities = {}
        for source in self.sources:
            route = self.routes[source.path]
            if route.disposition == 'reference_only':
                continue
            execution = self.executions_by_source_id[source.resource_id]
            descriptor = execution.selection.selected_descriptor
            providers = []
            if descriptor and route.disposition == 'supporting':
                status = ('unsupported' if execution.cause else
                          descriptor['capability_status'])
                providers.append((descriptor, {
                    feature: status for feature in descriptor['capabilities']}))
            elif descriptor:
                statuses = registry.effective_capabilities(
                    descriptor, source.language)
                if execution.cause:
                    statuses = {feature: 'unsupported'
                        for feature in SOURCE_ADAPTER_CAPABILITIES}
                providers.append((descriptor, statuses))
                providers.extend((enricher, registry.effective_capabilities(
                        enricher, source.language))
                    for enricher in self.enricher_descriptors_by_source_id.get(
                        source.resource_id, ()))
            else:
                providers.append(({'id': 'unavailable', 'version': '1',
                    'diagnostic_codes': [
                        'AMBIGUOUS_ADAPTER' if execution.selection.status == 'ambiguous'
                        else 'SOURCE_CAPABILITY_UNAVAILABLE']},
                    {feature: 'unsupported'
                     for feature in SOURCE_ADAPTER_CAPABILITIES}))
            source.capability_statuses = {}
            for provider, statuses in providers:
                for feature, status in statuses.items():
                    source.capability_statuses.setdefault(feature, set()).add(status)
                    capability = record('Capability', language=source.language,
                        framework=provider.get('framework'),
                        version=provider.get('framework_version'),
                        adapter=provider['id'],
                        adapter_version=provider.get('version', '1'),
                        feature=feature, status=status,
                        diagnostic_codes=sorted(set(provider.get('diagnostic_codes', ())) |
                            ({'ADAPTER_UNAVAILABLE'} if execution.cause else set())))
                    capabilities[digest(capability)] = capability
        self.facts['capabilities'] = [capabilities[key]
            for key in sorted(capabilities)]

    def _entrypoint_coverage(self) -> None:
        """Report every entry-point gap: language gaps, likely misses, silent zero.

        Which languages can host entry points, and which markers denote one,
        come from data/entrypoint_markers.toml; whether a language's selected
        adapters detect entry points comes from their declared capabilities.
        """
        catalog = _entrypoint_catalog()
        gaps = []
        analyzed = [source for source in self.sources
            if self.routes[source.path].disposition == 'analyze']
        by_language = {}
        for source in analyzed:
            classification = self.routes[source.path].classification
            if (classification.language is None
                    or classification.category not in catalog.categories
                    or classification.language in catalog.non_entrypoint_languages):
                continue
            statuses = source.capability_statuses.get(
                'entrypoint_detection', {'unsupported'})
            if statuses <= {'unsupported'}:
                by_language.setdefault(classification.language, []).append(source)
        for language, sources in sorted(by_language.items()):
            name = catalog.display_name(language)
            count = len(sources)
            message = (f'{name}: {count} file{"" if count == 1 else "s"}, '
                       'entry-point detection unavailable')
            gaps.append((gap_record(LANGUAGE_GAP, message, language=language,
                                    files=count), [], []))

        spans = {}
        for anchor in self.facts['anchors'].values():
            evidence_ids = set(anchor['evidence_ids'])
            for representation in anchor.get('representations', ()):
                evidence_ids.update(representation['evidence_ids'])
                if representation.get('registration'):
                    evidence_ids.update(
                        representation['registration']['evidence_ids'])
            for evidence_id in evidence_ids:
                locator = self.facts['evidence'][evidence_id]['locator']
                spans.setdefault(locator['path'], []).append(
                    (locator['start_line'], locator['end_line']))
        texts = {source.path: source for source in self.sources
                 if catalog.scans(source.path)}
        for relative, raw in self.scan.marker_bytes.items():
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                continue
            texts[relative] = Source(path=relative,
                language=self.routes[relative].classification.language,
                text=text, source_hash=digest(raw),
                resource_id=identifier('resource', relative),
                original_byte_length=len(raw))
        # A byte-order mark is encoding, not content; dropping it keeps
        # offsets on the same lines and lets `^` match the first line.
        bom = {path: source.text.startswith('\ufeff')
               for path, source in texts.items()}
        hits = scan_markers(catalog, ((path, source.text[1:] if bom[path]
            else source.text) for path, source in texts.items()),
            CATALOG['test_path_pattern'])
        # Entry points by declared operation, so a marker whose method and
        # route equal one already known (from a contract, say) is not missed.
        operations = {}
        for anchor in self.facts['anchors'].values():
            operation = anchor.get('operation') or {}
            if operation.get('method') and operation.get('path'):
                key = (operation['method'].upper(), route_key(operation['path']))
                operations.setdefault(key, []).append(anchor['id'])
        matched = 0
        for hit in hits:
            if covered(hit, spans):
                continue
            # A marker declaring the same operation as a known entry point (from
            # its contract, say) is still missed: the code implementing it was
            # not detected. The message names the matching entry point.
            body = (texts[hit.path].text[1:] if bom[hit.path] else texts[hit.path].text)
            known = matching_entry_point(hit, body, operations)
            matched += bool(known)
            source = texts[hit.path]
            offset = 1 if bom[hit.path] else 0
            message = (f'{hit.path}:{hit.start_line}: likely missed '
                       f'{hit.marker.kind} entry point ({hit.marker.framework_label}: '
                       f'{hit.marker.name})')
            if known:
                operation = self.facts['anchors'][known]['operation']
                message += (f'; also declared as {operation["method"]} {operation["path"]} '
                            'by a known entry point')
            evidence_id = self.evidence(source, hit.start + offset,
                                        hit.end + offset)
            subjects = ([source.resource_id]
                        if source.resource_id in self.facts['resources'] else [])
            gaps.append((gap_record(LIKELY_MISSED, message, hit=hit),
                         subjects, [evidence_id]))

        if not self.facts['anchors'] and not gaps:
            count = len(analyzed)
            message = ('No entry points detected; no entry-point markers found '
                       f'in {count} analyzed file{"" if count == 1 else "s"}')
            gaps.append((gap_record(NONE_DETECTED, message, files=count), [], []))
        self.facts['coverage']['entrypoint_gaps'] = [gap for gap, _, _ in gaps]
        self.facts['coverage']['entrypoint_markers_matched'] = matched
        for gap, subjects, evidence_ids in gaps:
            self.diagnostics.append(record('Diagnostic', code=GAP_CODES[gap['kind']],
                message=gap['message'], subject_ids=subjects,
                evidence_ids=evidence_ids))

    def _documentation_edges(self) -> None:
        """Link authored documentation to exact operations or its service scope."""
        service_by_scope = {resource['name']: resource['id']
            for resource in self.facts['resources'].values()
            if resource['kind'] == 'service'}
        for source in self.sources:
            if source.language != 'markdown' or not source.text.strip():
                continue
            targets = set()
            lowered = source.text.casefold()
            for anchor in self.facts['anchors'].values():
                operation = anchor.get('operation') or {}
                tokens = [operation.get('path'), operation.get('name')]
                if any(token and len(token) > 2 and token.casefold() in lowered
                       for token in tokens):
                    targets.add(('anchor', anchor['id']))
            service_id = service_by_scope.get(source.service_scope)
            if not targets and service_id:
                targets.add(('resource', service_id))
            if not targets:
                continue
            evidence_id = self.evidence(source, 0, len(source.text))
            for kind, target_id in sorted(targets):
                edge_id = identifier('edge', source.resource_id,
                                     'documents_behavior', target_id)
                self.facts['edges'][edge_id] = record(
                    'Edge', id=edge_id,
                    from_ref={'kind':'resource', 'id':source.resource_id},
                    to_ref={'kind':kind, 'id':target_id},
                    kind='documents_behavior', evidence_ids=[evidence_id],
                    resolution='resolved', reason=None)
                self.facts['coverage']['edges_resolved'] += 1

    def _endpoint_links(self) -> None:
        """Link each client request to the server endpoint that answers it.

        Adapters state both halves. A client adapter states each request as its
        source composes it: method, full URL, the branch choices selecting it,
        and evidence. A server adapter states where its endpoints are served: a
        port and base path per service, or per contract. Matching is exact. The
        request must fall under a declared base, its method must be the
        endpoint's, and its path must have the endpoint's segments, literal for
        literal. A match is a ``routes_to`` edge from the requesting symbol to
        the endpoint's handler, which traversal follows like any call; several
        matches stay ambiguous, and a request no base or endpoint answers stays
        unresolved with its reason.
        """
        bases = []
        for module, sources in getattr(self, 'selected_modules', []):
            provider = getattr(module, 'endpoint_bases', None)
            if provider:
                bases.extend(provider(sources, self.sources))
        served = []
        for anchor in self.facts['anchors'].values():
            if anchor['kind'] != 'http':
                continue
            handled = any(item['role'] != 'contract' and item['operation'].get('path')
                          for item in anchor['representations'])
            for representation in anchor['representations']:
                operation = representation['operation']
                if (not representation['symbol_id'] or not operation.get('method')
                        or not operation.get('path')):
                    continue
                # A contract answers only for an operation no source handler
                # implements; otherwise the handler is what runs.
                if representation['role'] == 'contract' and handled:
                    continue
                service = self.facts['resources'].get(operation['service_resource_id']) or {}
                served.append((representation, service.get('name')))
        for unit in self.units:
            requester = getattr(self._owner(unit.source), 'endpoint_requests', None)
            if not requester or not unit.symbol_id:
                continue
            groups = {}
            for request in requester(unit):
                _validate_endpoint_request(unit, request)
                endpoint = _same_origin_endpoint(self.facts, request)
                if endpoint:
                    for source, start, end in request['evidence_spans']:
                        self.same_origin_requests[self.evidence(source, start, end)] = endpoint
                    continue
                outcome = _route_request(request, bases, served)
                if outcome is None:
                    continue
                group = groups.setdefault(
                    (request['position'], request['end'], outcome['key']),
                    {'outcome': outcome, 'members': [], 'notes': set()})
                group['members'].append((request, outcome))
                group['notes'].update(outcome['notes'])
            for (position, end, key), group in sorted(groups.items(), key=lambda item: repr(item[0])):
                self._add_route(unit, position, end, key, group, groups)

    def _add_route(self, unit, position, end, key, group, groups=None) -> None:
        outcome = group['outcome']
        members = group['members']
        reason = outcome['reason']
        if outcome['resolution'] == 'unresolved' and outcome['request_path']:
            # The same request (same call, method and path below its base)
            # resolved under another configuration: this variant is scoped to
            # its own configuration, not a statement about the request.
            method = key[0]
            siblings = sorted({self.facts['symbols'][other['outcome']['target']]['qualified_name']
                               .split('::', 1)[-1]
                               for (other_position, other_end, other_key), other in (groups or {}).items()
                               if (other_position, other_end) == (position, end)
                               and other_key[0] == method
                               and other['outcome']['resolution'] == 'resolved'
                               and other['outcome']['request_path'] == outcome['request_path']})
            if siblings:
                scope_condition = _route_condition([[*request['conditions'], *routed['conditions']]
                                                    for request, routed in members])
                reason += (f" This applies only when {scope_condition}; under the other declared "
                           f"configuration(s) the same request routes to {', '.join(siblings)}."
                           if scope_condition else
                           f" Under other declared configuration(s) the same request routes to "
                           f"{', '.join(siblings)}.")
        request_evidence = sorted({self.evidence(source, start, finish)
            for request, _ in members
            for source, start, finish in request['evidence_spans']})
        evidence_ids = sorted(set(request_evidence)
            | {self.evidence(source, start, finish) for _, routed in members
               for source, start, finish in routed['evidence_spans']}
            | {evidence_id for _, routed in members for evidence_id in routed['evidence_ids']})
        conditions = [[*request['conditions'], *routed['conditions']]
                      for request, routed in members]
        edge_id = identifier('edge', unit.symbol_id, 'routes_to', position, end, *map(str, key))
        target = outcome['target']
        self.facts['edges'][edge_id] = record('Edge', id=edge_id,
            from_ref={'kind': 'symbol', 'id': unit.symbol_id},
            to_ref={'kind': 'symbol', 'id': target} if target else None,
            candidate_target_ids=list(outcome['candidates']), kind='routes_to',
            condition=_route_condition(conditions), evidence_ids=evidence_ids,
            resolution=outcome['resolution'], reason=reason)
        self.facts['coverage']['edges_' + outcome['resolution']] += 1
        for code, message in sorted(group['notes']):
            self.diagnostics.append(record('Diagnostic', code=code, message=message,
                subject_ids=[edge_id], evidence_ids=request_evidence))

    def _canonicalize_anchors(self) -> None:
        """Reconcile adapter-established identities before traces are scheduled."""
        replacements = reconcile_anchors(self.facts)
        # Reconciliation rebuilds containers while rewriting identifiers. Keep
        # subsequent adapter/snapshot diagnostics attached to the artifact.
        self.diagnostics = self.facts['warnings']
        for unit in self.units:
            if unit.anchor_id:
                unit.anchor_id = replacements.get(unit.anchor_id, unit.anchor_id)

    def _ref_name(self, ref) -> str:
        if ref['kind'] == 'symbol':
            return self.facts['symbols'][ref['id']]['qualified_name'].split('::', 1)[-1]
        return self.facts['resources'][ref['id']]['name']

    def _traces(self) -> None:
        """Evaluate mechanical traversal and semantic completion independently."""
        outgoing: dict[str, list[dict]] = {}
        for edge in self.facts['edges'].values():
            outgoing.setdefault(edge['from_ref']['id'], []).append(edge)
        units_by_symbol = {unit.symbol_id: unit for unit in self.units}
        # Every adapter code an edge carries: its semantic result's and the
        # projection gaps reported against it.
        edge_codes = {edge_id: set(codes) for edge_id, codes in self.edge_codes.items()}
        for warning in self.facts['warnings']:
            for subject in warning.get('subject_ids') or ():
                if subject in self.facts['edges']:
                    edge_codes.setdefault(subject, set()).add(warning['code'])
        units_by_anchor: dict[str, list[Unit]] = {}
        for unit in self.units:
            if unit.anchor_id:
                units_by_anchor.setdefault(unit.anchor_id, []).append(unit)
        for anchor in self.facts['anchors'].values():
            tid = identifier('trace', anchor['id'])
            obligations = []
            def require(kind, symbol, status, code, reason, edge=None, targets=(), identity=None):
                oid = identifier('trace_obligation', tid, kind, symbol, edge, code, identity)
                evidence_ids = (self.facts['edges'][edge] if edge else self.facts['symbols'][symbol])['evidence_ids']
                self.facts['trace_obligations'][oid] = record('TraceObligation', id=oid,
                    trace_id=tid, kind=kind, origin_ref={'kind':'symbol','id':symbol},
                    edge_id=edge, candidate_target_ids=sorted(targets), status=status,
                    reason_code=code, reason=reason, evidence_ids=evidence_ids)
                obligations.append(oid)
            start = units_by_symbol[anchor['symbol_id']]
            role = start.trace_role
            required_relationships = tuple(start.required_relationships)
            queue = [(anchor['symbol_id'], 0)]
            seen, edges, frontier, reasons = set(), set(), set(), set()
            requests = []
            if anchor['resolution'] != 'resolved':
                frontier.add(anchor['symbol_id']); reasons.add('unresolved_anchor')
                require('capability', anchor['symbol_id'], anchor['resolution'], 'UNRESOLVED_ANCHOR',
                        anchor['reason'] or 'Entry-point identity is not resolved.')

            def require_capabilities(unit, demonstrated=frozenset()):
                for capability in unit.required_capabilities or ():
                    statuses = unit.source.capability_statuses.get(capability, set())
                    # A capability this run exercised for this symbol is present,
                    # whatever the adapter owning the declaring file declares. An
                    # endpoint is anchored where it is declared, so a contract in
                    # openapi.yml would otherwise be judged by the YAML reader for
                    # work the Java enricher did.
                    available = (bool(statuses & {'supported', 'partial'})
                                 or capability in demonstrated)
                    require('capability', unit.symbol_id, 'satisfied' if available else 'unresolved',
                            'CAPABILITY_AVAILABLE' if available else 'CAPABILITY_UNAVAILABLE',
                            (f'The selected adapter provides {capability} for this evidenced source.' if available
                             else f'No selected adapter provides required capability {capability} for this source.'),
                            identity=capability)
                    if not available:
                        frontier.add(unit.symbol_id); reasons.add('capability_gap')

            # Implementation selection is a normalized obligation.  An
            # implementation may satisfy it itself only when its adapter has
            # positively identified a valid executable terminal.  Contracts
            # select through normalized relationships, including the reverse
            # direction of implementation-to-contract declarations.
            selection_status = None
            selection_targets: list[str] = []
            selection_reason = ''
            selection_edges: list[dict] = []
            selection_edge_id = None
            selected_target = None
            if role == 'implementation' and start.valid_terminal and start.executable_body:
                selection_status = 'satisfied'
                selection_targets = [start.symbol_id]
                selection_reason = 'The adapter identified the anchor symbol as a concrete executable terminal.'
            elif 'implementation_selection' in required_relationships:
                for edge in self.facts['edges'].values():
                    if edge['kind'] == 'selects_implementation' and edge['from_ref']['id'] == start.symbol_id:
                        selection_edges.append(edge)
                        if edge['to_ref'] and edge['to_ref']['kind'] == 'symbol':
                            selection_targets.append(edge['to_ref']['id'])
                        selection_targets.extend(edge['candidate_target_ids'])
                    elif edge['kind'] == 'implements' and (
                            (edge['to_ref'] and edge['to_ref']['id'] == start.symbol_id)
                            or start.symbol_id in edge['candidate_target_ids']):
                        selection_edges.append(edge)
                        selection_targets.append(edge['from_ref']['id'])
                selection_targets = sorted(set(selection_targets))[:MAX_SEMANTIC_CANDIDATES]
                exact = [target for target in selection_targets
                         if target in units_by_symbol
                         and units_by_symbol[target].trace_role == 'implementation'
                         and units_by_symbol[target].valid_terminal
                         and units_by_symbol[target].executable_body]
                traversable = [target for target in selection_targets
                         if target in units_by_symbol
                         and units_by_symbol[target].trace_role == 'implementation'
                         and units_by_symbol[target].executable_body]
                uncertain = any(edge['resolution'] != 'resolved' for edge in selection_edges)
                # Every selection names an implementation outside the analyzed
                # source: the entry point ends at that external boundary.
                external = [edge for edge in selection_edges
                            if edge['kind'] == 'selects_implementation' and edge['to_ref']
                            and edge['to_ref']['kind'] != 'symbol']
                # Every implementation is a selection taken under its own
                # condition (a profile, say): one conditional path each.
                alternatives = _conditional_alternatives(
                    [edge for edge in selection_edges if edge['kind'] == 'selects_implementation'])
                chosen = {edge['to_ref']['id'] for edge in alternatives}
                implementers = {edge['from_ref']['id'] for edge in selection_edges
                                if edge['kind'] == 'implements'}
                if alternatives and implementers <= chosen:
                    selection_status = 'conditional'
                    selection_targets = sorted(target for target in chosen
                                               if target in units_by_symbol)
                    selection_reason = (
                        'Configuration selects which implementation runs; each alternative is '
                        'a conditional path: ' + '; '.join(
                            f"{self._ref_name(edge['to_ref'])} when {edge['condition']}"
                            for edge in alternatives) + '.')
                    queue.extend((target, 1) for target in selection_targets)
                elif external and len(external) == len(selection_edges) == 1:
                    selection_status = 'external'
                    selection_edge_id = external[0]['id']
                    selection_targets = [external[0]['to_ref']['id']]
                    selection_reason = (external[0]['reason']
                        or 'The selected implementation is outside the analyzed source.')
                elif len(exact) == 1 and len(selection_targets) == 1 and not uncertain:
                    selection_status = 'satisfied'
                    selected_target = exact[0]
                    selection_reason = 'One evidenced implementation relationship selects a concrete executable terminal.'
                    queue.append((selected_target, 1))
                elif len(traversable) == 1 and len(selection_targets) == 1 and not uncertain:
                    selection_status = 'unresolved'
                    selected_target = traversable[0]
                    selection_reason = ('One evidenced implementation is available for partial traversal, '
                        'but its adapter did not establish a valid executable terminal.')
                    queue.append((selected_target, 1))
                elif len(selection_targets) > 1 or uncertain:
                    selection_status = 'ambiguous'
                    selection_reason = 'Multiple or ambiguous implementation relationships remain viable.'
                else:
                    selection_status = 'unresolved'
                    selection_reason = 'No evidenced relationship selects a concrete executable implementation.'
                edges.update(edge['id'] for edge in selection_edges)
            else:
                selection_status = 'external' if role == 'external_boundary' else 'unresolved'
                selection_reason = ('The entry point terminates at an explicit external implementation boundary.'
                    if role == 'external_boundary' else
                    'The adapter did not authorize this declaration as an executable implementation terminal.')

            # Capability obligations are answered after the relationships they
            # govern have been attempted, so an exercised capability can settle
            # its own question.
            require_capabilities(start, demonstrated=(
                frozenset({'relationship_resolution'})
                if selection_status == 'satisfied' else frozenset()))

            while queue:
                symbol, depth = queue.pop(0)
                if symbol in seen:
                    continue
                if len(seen) >= self.config['max_symbols_per_activity']:
                    require('symbol_limit', anchor['symbol_id'], 'limit_reached', 'SYMBOL_LIMIT',
                            'Symbol budget prevents completing this path.', targets=[symbol])
                    frontier.add(symbol); reasons.add('symbol_limit'); continue
                seen.add(symbol)
                for edge in outgoing.get(symbol, []):
                    if edge['kind'] in NON_TRAVERSAL_EDGES or (
                            edge['kind'] == 'selects_implementation'
                            and symbol == start.symbol_id
                            and 'implementation_selection' in required_relationships):
                        continue
                    edges.add(edge['id'])
                    if edge['kind'] in ('reads_data', 'writes_data'):
                        obligation_kind = 'data_target'
                    elif edge['kind'] in ('invokes_endpoint', 'emits') or (
                            edge['to_ref'] and edge['to_ref']['kind'] == 'resource'
                            and edge['kind'] == 'calls'):
                        obligation_kind = 'external_boundary'
                    else:
                        obligation_kind = 'call_target'
                    if (edge['kind'] == 'selects_implementation' and edge['to_ref']
                            and edge['to_ref']['kind'] != 'symbol'):
                        # The selected implementation is a resource outside the
                        # analyzed source, so the selection ends at an external
                        # boundary.
                        require('implementation_selection', symbol, 'external',
                                'EXTERNAL_IMPLEMENTATION_UNAVAILABLE',
                                edge['reason'] or 'The selected implementation is outside the analyzed source.',
                                edge['id'], [edge['to_ref']['id']])
                        frontier.add(edge['id']); reasons.add('external_boundary')
                        continue
                    if edge['resolution'] != 'resolved' or not edge['to_ref']:
                        status = ('external' if obligation_kind == 'external_boundary' and edge['to_ref']
                                  else 'ambiguous' if edge['resolution']=='ambiguous' else 'unresolved')
                        code, reason = 'UNRESOLVED_TARGET', edge['resolution']
                        if edge['kind'] == 'selects_implementation':
                            # An unsettled selection is an implementation-selection
                            # obligation wherever the trace meets it.
                            obligation_kind = 'implementation_selection'
                            code, reason = (('IMPLEMENTATION_AMBIGUOUS', 'implementation_ambiguous')
                                            if status == 'ambiguous' else
                                            ('IMPLEMENTATION_NOT_REACHED', 'implementation_not_reached'))
                        obligation = (obligation_kind, symbol, status,
                                      code, edge['reason'] or 'Relationship target is not resolved.',
                                      edge['id'], edge['candidate_target_ids'] or (
                                          [edge['to_ref']['id']] if edge['to_ref'] else []))
                        if status == 'external' and edge['kind'] == 'invokes_endpoint':
                            requests.append((edge, obligation))
                            continue
                        require(*obligation)
                        frontier.add(edge['id'])
                        reasons.add('external_boundary' if status == 'external' else reason)
                        continue
                    target = edge['to_ref']['id']
                    if edge['to_ref']['kind'] != 'symbol':
                        external = obligation_kind == 'external_boundary'
                        obligation = (obligation_kind, symbol, 'external' if external else 'satisfied',
                                      'EXTERNAL_IMPLEMENTATION_UNAVAILABLE' if external else 'RESOLVED_RESOURCE_TARGET',
                                      ('The operation reaches an external resource whose implementation is unavailable.'
                                       if external else 'The relationship identifies a resource terminal.'),
                                      edge['id'], [target])
                        if external and edge['kind'] == 'invokes_endpoint':
                            requests.append((edge, obligation))
                            continue
                        require(*obligation)
                        if external:
                            frontier.add(edge['id']); reasons.add('external_boundary')
                        continue
                    if target in seen:
                        continue
                    if depth >= self.config['max_trace_depth']:
                        require('depth_limit', symbol, 'limit_reached', 'DEPTH_LIMIT',
                                'Depth budget prevents completing this relationship.', edge['id'], [target])
                        frontier.add(target); reasons.add('depth_limit'); continue
                    queue.append((target, depth + 1))

            # A client HTTP request always leaves the client process, so it stays
            # an external boundary. Once the trace is walked, its reason says
            # where it goes: answered in the analyzed source through a resolved
            # routes_to edge of this trace that carries the same request, answered
            # by the one endpoint a root-relative URL reaches, or neither.
            routed = [self.facts['edges'][edge_id] for edge_id in sorted(edges)
                      if self.facts['edges'][edge_id]['kind'] == 'routes_to'
                      and self.facts['edges'][edge_id]['resolution'] == 'resolved']
            for edge, obligation in requests:
                kind, symbol, status, code, reason, edge_id, targets = obligation
                spans = set(edge['evidence_ids'])
                routes = [route for route in routed if spans & set(route['evidence_ids'])]
                endpoint = next((self.same_origin_requests[evidence_id] for evidence_id in sorted(spans)
                                 if evidence_id in self.same_origin_requests), None)
                if routes:
                    handlers = sorted({self.facts['symbols'][route['to_ref']['id']]['qualified_name']
                                       .split('::', 1)[-1] for route in routes})
                    code, stop = 'ROUTED_REQUEST', 'routed_request'
                    reason = ('The request leaves the client and is answered in the analyzed source by '
                              f"{', '.join(handlers)} (routes_to {', '.join(route['id'] for route in routes)}).")
                elif endpoint:
                    operation = self.facts['anchors'][endpoint]['operation']
                    code, stop = 'SAME_ORIGIN_REQUEST', 'same_origin_endpoint'
                    reason = ('The root-relative request leaves the client and is answered in the '
                              f"analyzed source by {operation['method']} {operation['path']} "
                              f'(anchor {endpoint}), whose own trace covers the server.')
                else:
                    stop = 'external_boundary'
                require(kind, symbol, status, code, reason, edge_id, targets)
                frontier.add(edge_id); reasons.add(stop)

            for symbol in sorted(seen - {start.symbol_id}):
                require_capabilities(units_by_symbol[symbol])

            # Implementation selection is required of every declaration the
            # trace reaches, not only of its entry point: a call that lands on
            # a contract has not reached the code that runs until one of the
            # contract's selects_implementation relationships has been followed.
            # An ambiguous, unresolved or external selection was already
            # recorded as the traversal met it; a contract with no selection at
            # all is recorded here, whatever structural edges it carries.
            for symbol in sorted(seen - {start.symbol_id}):
                unit = units_by_symbol[symbol]
                if 'implementation_selection' not in (unit.required_relationships or ()):
                    continue
                selections = [edge for edge in outgoing.get(symbol, [])
                              if edge['kind'] == 'selects_implementation']
                alternatives = _conditional_alternatives(selections)
                if alternatives:
                    require('implementation_selection', symbol, 'conditional',
                            'CONDITIONAL_IMPLEMENTATION',
                            'Configuration selects which implementation runs; each alternative is '
                            'a conditional path: ' + '; '.join(
                                f"{self._ref_name(edge['to_ref'])} when {edge['condition']}"
                                for edge in alternatives) + '.',
                            targets=sorted({edge['to_ref']['id'] for edge in alternatives
                                            if edge['to_ref']['kind'] == 'symbol'}))
                    frontier.add(symbol); reasons.add('conditional_implementation')
                    continue
                if any(edge['resolution'] != 'resolved' or not edge['to_ref']
                       or edge['to_ref']['kind'] != 'symbol' for edge in selections):
                    continue
                targets = sorted(edge['to_ref']['id'] for edge in selections)
                reached = [target for target in targets if target in seen]
                if reached:
                    require('implementation_selection', symbol, 'satisfied',
                            'IMPLEMENTATION_REACHED',
                            'The traversal followed an evidenced implementation of this declaration.',
                            targets=reached)
                    continue
                require('implementation_selection', symbol, 'unresolved',
                        'IMPLEMENTATION_NOT_REACHED',
                        ('The selected implementation was not reached within traversal limits.'
                         if targets else
                         'No evidenced relationship selects a concrete executable implementation.'),
                        targets=targets)
                frontier.add(symbol); reasons.add('implementation_not_reached')

            if selection_status == 'satisfied' and selected_target and selected_target not in seen:
                selection_status = 'unresolved'
                selection_reason = 'The selected implementation was not reached within traversal limits.'
            reason_code = {
                'satisfied': 'IMPLEMENTATION_REACHED',
                'conditional': 'CONDITIONAL_IMPLEMENTATION',
                'ambiguous': 'IMPLEMENTATION_AMBIGUOUS',
                'external': 'EXTERNAL_IMPLEMENTATION_UNAVAILABLE',
                'unresolved': 'IMPLEMENTATION_NOT_REACHED',
            }[selection_status]
            require('implementation_selection', anchor['symbol_id'], selection_status,
                    reason_code, selection_reason, edge=selection_edge_id,
                    targets=selection_targets)
            if selection_status != 'satisfied':
                # An external selection stops at its edge; its target is a
                # resource, not a traversable symbol.
                frontier.update([selection_edge_id] if selection_edge_id
                                else [anchor['symbol_id']] if selection_status == 'conditional'
                                else selection_targets or [anchor['symbol_id']])
                reasons.add('implementation_ambiguous' if selection_status == 'ambiguous'
                            else 'conditional_implementation' if selection_status == 'conditional'
                            else 'external_boundary' if selection_status == 'external'
                            else 'implementation_not_reached')
            # A leaf is judged by the relationships traversal can follow from it.
            # Structural edges such as accepts_type describe the declaration and
            # cannot make it a terminal. Declarations that require implementation
            # selection were judged by that obligation above.
            for symbol in sorted(seen):
                unit = units_by_symbol[symbol]
                traversed = [edge for edge in outgoing.get(symbol, [])
                             if edge['kind'] not in NON_TRAVERSAL_EDGES]
                if symbol != anchor['symbol_id'] and not traversed \
                        and 'implementation_selection' not in (unit.required_relationships or ()) \
                        and not (unit.valid_terminal and unit.executable_body):
                    require('capability', symbol, 'unresolved', 'UNPROVEN_TERMINAL',
                            'Empty adjacency does not establish an executable terminal.')
                    frontier.add(symbol); reasons.add('unproven_terminal')
            evidence = sorted(
                {eid for sid in seen for eid in self.facts['symbols'][sid]['evidence_ids']}
                | {eid for edge_id in edges
                   for eid in self.facts['edges'][edge_id]['evidence_ids']})
            incomplete = any(self.facts['trace_obligations'][oid]['status'] != 'satisfied' for oid in obligations)
            # A conditional selection is never ambiguous: each alternative is a
            # path under its condition. The trace is still not resolved,
            # because which condition holds is decided at runtime.
            hard_incomplete = any(self.facts['trace_obligations'][oid]['status'] in {
                'unresolved', 'external', 'limit_reached', 'conditional'} for oid in obligations)
            has_ambiguity = any(self.facts['trace_obligations'][oid]['status'] == 'ambiguous'
                                for oid in obligations)
            resolution = 'unresolved' if hard_incomplete else 'ambiguous' if has_ambiguity else 'resolved'
            # Completion keeps resolution as it is and says whether what stops
            # the trace is a known boundary, with its assumption, or a gap.
            assumptions, gaps = [], 0
            for oid in sorted(set(obligations)):
                obligation = self.facts['trace_obligations'][oid]
                edge = self.facts['edges'].get(obligation['edge_id'] or '')
                resource = (self.facts['resources'].get(edge['to_ref']['id'])
                            if edge and edge['to_ref'] and edge['to_ref']['kind'] == 'resource'
                            else None)
                boundary = trace_boundary(obligation, edge,
                                          edge_codes.get(edge['id'], ()) if edge else (), resource)
                obligation['boundary'] = boundary
                if boundary:
                    assumptions.append({'obligation_id': oid, 'kind': boundary,
                        'statement': TRACE_BOUNDARIES['assumptions'][boundary].format(
                            reason=obligation['reason'],
                            provider=(resource or {}).get('provider') or ''),
                        'evidence_ids': list(obligation['evidence_ids'])})
                elif obligation['status'] != 'satisfied':
                    gaps += 1
            completion = ('incomplete' if gaps else 'bounded' if assumptions else 'complete')
            traversal_complete = not any(reason in {'depth_limit', 'symbol_limit'} for reason in reasons)
            self.facts['traces'][tid] = record('Trace', id=tid, anchor_id=anchor['id'],
                symbol_ids=sorted(seen), edge_ids=sorted(edges), frontier_ids=sorted(frontier),
                obligation_ids=sorted(set(obligations)), stop_reasons=sorted(reasons), evidence_ids=evidence,
                traversal_complete=traversal_complete, resolution=resolution,
                completion=completion, assumptions=assumptions,
                reason='Trace has unsatisfied implementation, capability or traversal obligations.' if incomplete else None)
            # The canonical representation's unit owns the anchor's display and
            # registration fields; fall back only for symbol-id collisions.
            unit = (start if start.anchor_id == anchor['id']
                    else units_by_anchor[anchor['id']][0])
            owner = self._owner(unit.source)
            interaction = getattr(owner, 'interaction', None) if owner else None
            if interaction:
                self.facts['traces'][tid]['ui_interaction'] = interaction(unit,self.evidence,self.facts)
            for effect in self.facts['effects'].values():
                origin = effect.get('origin_ref')
                if origin and origin['kind']=='symbol' and origin['id'] in seen and (
                        not effect.get('edge_id') or effect['edge_id'] in edges):
                    effect['trace_ids'].append(tid)
                    self.facts['traces'][tid]['evidence_ids'] = sorted(
                        set(self.facts['traces'][tid]['evidence_ids'])
                        | set(effect['evidence_ids']))
        for effect in self.facts['effects'].values():
            effect['trace_ids'] = sorted(set(effect['trace_ids']))

    def _connections(self) -> None:
        by_name:dict[str,list[Unit]]={}
        by_symbol = {unit.symbol_id: unit for unit in self.units}
        for u in self.units:
            owner = self._owner(u.source)
            normalize = getattr(owner, 'symbol_key', lambda name: name)
            by_name.setdefault(normalize(u.name),[]).append(u)
        for unit in self.units:
            if unit.kind=='class':continue
            adapter = self._owner(unit.source)
            if adapter is None:
                continue
            for call in adapter.calls(unit):
                if isinstance(call, dict):
                    receiver = call.get('receiver')
                    name = call.get('name')
                    call_position = call.get('position')
                    call_end = call.get('end')
                    if (not isinstance(name, str) or not name
                            or type(call_position) is not int or type(call_end) is not int
                            or not 0 <= call_position < call_end <= len(unit.text)):
                        raise ValueError('Adapter call record requires a name and valid unit-relative span')
                    call_evidence_id = self.evidence(unit.source,
                        unit.start + call_position, unit.start + call_end)
                else:
                    if unit.source.parser_required:
                        raise ValueError('Parser-backed adapter call records require exact source spans')
                    receiver, name, call_position = call
                    call_evidence_id = unit.evidence_id
                normalize = getattr(adapter,'symbol_key',lambda name:name)
                candidates = adapter.candidates(unit, receiver, name,
                    by_name.get(normalize(name), []), call_position)
                if len(candidates) > 1:
                    candidates = sorted(candidates, key=lambda candidate: candidate.symbol_id)[
                        :MAX_SEMANTIC_CANDIDATES]
                resolver = getattr(adapter, 'resolve_call', None)
                if resolver:
                    semantic = resolver(unit, receiver, name, candidates, call_position,
                        call_evidence_id)
                else:
                    target = candidates[0] if len(candidates) == 1 else None
                    semantic = SemanticResult(
                        capability='callable_resolution',
                        outcome='exact' if target else ('ambiguous' if candidates else 'unresolved'),
                        subject_id=unit.symbol_id,
                        target_id=target.symbol_id if target else None,
                        candidate_target_ids=tuple(sorted(candidate.symbol_id for candidate in candidates))
                            if len(candidates) > 1 else (),
                        evidence_ids=(call_evidence_id,),
                        diagnostic_code=None if target else
                            ('CALL_TARGET_AMBIGUOUS' if candidates else 'CALL_TARGET_UNRESOLVED'),
                        reason=None if target else f'Call target {name}: {len(candidates)} source candidates',
                    )
                result = semantic.normalized()
                if call_evidence_id not in result['evidence_ids']:
                    raise ValueError('Semantic call result must retain call-site evidence')
                unit.source.semantic_results.append(result)
                target = by_symbol.get(result['target_id']) if result['outcome'] == 'exact' else None
                if result['outcome'] == 'exact' and target is None:
                    raise ValueError('Semantic call result targets an unknown symbol')
                external_ref = None
                if result['outcome'] == 'external':
                    external_ref = {'kind':'resource', 'id':result['target_id']}
                    self.facts['resources'].setdefault(result['target_id'], record('Resource',
                        id=result['target_id'], kind='service', name=f'External call: {receiver or unit.owner}.{name}',
                        language=unit.source.language, evidence_ids=list(result['evidence_ids']),
                        resolution='unresolved', reason=result['reason'],
                        provider=getattr(semantic, 'provider', None)))
                edgeid=identifier('edge',unit.symbol_id,call_position,name)
                if result['diagnostic_code']:
                    self.edge_codes.setdefault(edgeid, set()).add(result['diagnostic_code'])
                self.facts['edges'][edgeid]=record('Edge',id=edgeid,
                    from_ref={'kind':'symbol','id':unit.symbol_id},
                    to_ref={'kind':'symbol','id':target.symbol_id} if target else external_ref,
                    candidate_target_ids=result['candidate_target_ids'],
                    kind='calls',evidence_ids=result['evidence_ids'],
                    resolution='resolved' if result['outcome']=='exact' else
                               'ambiguous' if result['outcome']=='ambiguous' else 'unresolved',
                    reason=result['reason'])
                if (target and self.facts['evidence'][unit.evidence_id]['source_kind'] == 'test'
                        and self.facts['evidence'][target.evidence_id]['source_kind'] != 'test'):
                    test_edge_id = identifier('edge', unit.symbol_id,
                                              'tests_behavior', target.symbol_id,
                                              call_position)
                    self.facts['edges'][test_edge_id] = record(
                        'Edge', id=test_edge_id,
                        from_ref={'kind':'symbol', 'id':unit.symbol_id},
                        to_ref={'kind':'symbol', 'id':target.symbol_id},
                        kind='tests_behavior', evidence_ids=[call_evidence_id],
                        resolution='resolved', reason=None)
                    self.facts['coverage']['edges_resolved'] += 1
                key='edges_resolved' if target else ('edges_ambiguous'
                    if result['outcome']=='ambiguous' else 'edges_unresolved');self.facts['coverage'][key]+=1
        relation_targets: dict[str, tuple] = {}
        for source in self.sources:
            owner = self._owner(source)
            relations = getattr(owner, 'relations', None) if owner else None
            if not relations:
                continue
            for relation in relations(source):
                origin,target = relation['source'],relation['target']
                eid = self.evidence(source,relation['start'],relation['end'])
                evidence_ids = {eid}
                for evidence_source, start, end in relation.get('evidence_spans', []):
                    if (not isinstance(evidence_source, Source)
                            or type(start) is not int or type(end) is not int
                            or not 0 <= start < end <= len(evidence_source.text)):
                        raise ValueError('Semantic relation has an invalid evidence span')
                    evidence_ids.add(self.evidence(evidence_source, start, end))
                evidence_ids = sorted(evidence_ids)
                candidates = sorted(candidate.symbol_id
                    for candidate in relation.get('candidate_targets', []))
                outcome = relation.get('outcome') or ('exact' if target else
                    'ambiguous' if relation['resolution']=='ambiguous' else 'unresolved')
                semantic = SemanticResult(
                    capability='relationship_resolution', outcome=outcome,
                    subject_id=origin.symbol_id,
                    target_id=(target.symbol_id if outcome=='exact' else
                               relation.get('external_target_id') if outcome=='external' else None),
                    candidate_target_ids=tuple(candidates) if outcome=='ambiguous' else (),
                    evidence_ids=tuple(evidence_ids),
                    diagnostic_code=None if outcome=='exact' else relation.get(
                        'diagnostic_code', 'RELATIONSHIP_'+outcome.upper()),
                    reason=None if outcome=='exact' else relation['reason'],
                ).normalized()
                source.semantic_results.append(semantic)
                edge_id = identifier('edge',origin.symbol_id,relation['kind'],relation['start'],relation['end'])
                # Relations are keyed by origin, kind and span, and one span can
                # carry several relations of a kind: ``class C implements A, B``
                # is evidenced by the whole declaration. A relation naming a
                # different target than the one already holding the key gets
                # its own edge rather than replacing it; a repeated relation to
                # the same target still replaces itself. The reason tells apart
                # only relations with nothing else to name: an explanation added
                # to a targeted relation must not change its identity.
                named = target.symbol_id if target else semantic['target_id']
                target_key = (named, tuple(candidates),
                              None if named or candidates else relation.get('reason'))
                if relation_targets.setdefault(edge_id, target_key) != target_key:
                    edge_id = identifier('edge', origin.symbol_id, relation['kind'],
                                         relation['start'], relation['end'], *map(str, target_key))
                    relation_targets[edge_id] = target_key
                external_ref = None
                if outcome == 'external' and semantic['target_id']:
                    external_ref = {'kind':'resource', 'id':semantic['target_id']}
                    self.facts['resources'].setdefault(semantic['target_id'], record(
                        'Resource', id=semantic['target_id'], kind='service',
                        name=f'External type: {relation.get("external_target_id")}',
                        language=source.language, evidence_ids=evidence_ids,
                        resolution='resolved', reason=None))
                if semantic['diagnostic_code']:
                    self.edge_codes.setdefault(edge_id, set()).add(semantic['diagnostic_code'])
                self.facts['edges'][edge_id] = record('Edge',id=edge_id,
                    from_ref={'kind':'symbol','id':origin.symbol_id},
                    to_ref={'kind':'symbol','id':target.symbol_id} if target else external_ref,
                    candidate_target_ids=semantic['candidate_target_ids'],
                    kind=relation['kind'], resolution=relation['resolution'],
                    reason=None if relation['resolution']=='resolved' else relation['reason'],
                    condition=relation.get('condition'), evidence_ids=evidence_ids)
                self.facts['coverage']['edges_'+relation['resolution']] += 1

    def _observations(self) -> None:
        for unit in self.units:
            adapter = self._owner(unit.source)
            if not adapter:
                continue
            for resource in adapter.resources(unit):
                rid = identifier('resource',resource['kind'],resource['name'].casefold())
                stored = self.facts['resources'].setdefault(rid,record('Resource',id=rid,
                    evidence_ids=[],**resource))
                if unit.evidence_id not in stored['evidence_ids']:
                    stored['evidence_ids'].append(unit.evidence_id)
            for observation in adapter.observations(unit):
                if not isinstance(observation, dict):
                    raise DomainError('INVALID_ADAPTER_CONTRACT',
                        'adapter_observation_invalid')
                observation = dict(observation)
                named_spans = observation.pop('named_value_spans', ())
                _register_named_value_spans(unit.source, named_spans)
                projection_fields = {
                    'declaration_units', 'binding_name', 'binding_direction'}
                present_projection_fields = projection_fields & set(observation)
                if (present_projection_fields
                        and present_projection_fields != projection_fields):
                    raise DomainError('INVALID_ADAPTER_CONTRACT',
                        'observation_binding_projection_incomplete')
                has_binding_projection = bool(present_projection_fields)
                declarations = observation.pop('declaration_units', ())
                binding_name = observation.pop('binding_name', None)
                binding_direction = observation.pop('binding_direction', None)
                identity_key = observation.pop('identity_key', None)
                if (has_binding_projection
                        and (not isinstance(declarations, tuple)
                             or not all(isinstance(item, Unit)
                                        for item in declarations)
                             or not isinstance(binding_name, str)
                             or binding_direction != 'internal')):
                    raise DomainError('INVALID_ADAPTER_CONTRACT',
                        'observation_binding_projection_invalid')
                if has_binding_projection:
                    observation['native_expression'] = redact_named_value(
                        binding_name, observation.get('native_expression'))
                observation = redact_values(observation)
                start, end = observation.pop('span')
                eid = self.evidence(unit.source, unit.start+start, unit.start+end)
                evidence_ids, binding_ids = {eid}, []
                if has_binding_projection:
                    for declaration in declarations:
                        candidate = binding_id(
                            declaration, binding_name, binding_direction)
                        binding = self.facts['bindings'].get(candidate)
                        if binding is None or not binding['evidence_ids']:
                            raise DomainError('INVALID_ADAPTER_CONTRACT',
                                'observation_binding_missing')
                        binding_ids.append(candidate)
                        evidence_ids.update(binding['evidence_ids'])
                resource = observation.pop('resource',None)
                if resource:
                    rid = identifier('resource',resource['kind'],resource['name'].casefold())
                    self.facts['resources'].setdefault(rid,record('Resource',id=rid,evidence_ids=[eid],**resource))
                    observation.setdefault('dependency_ids',[]).append(rid)
                oid = identifier('observation', unit.symbol_id,
                    identity_key if identity_key is not None else start)
                self.facts['rule_observations'][oid] = record('RuleObservation', id=oid,
                    input_binding_ids=sorted(binding_ids),
                    evidence_ids=sorted(evidence_ids), **{'resolution':'unresolved',
                    'reason':'Condition observed; outcome and enforcement scope require trace interpretation.',
                    **observation})
            for observed in adapter.operations(unit):
                self._hydrate_operation(unit, redact_values(observed))

    def _hydrate_operation(self, unit: Unit, raw: dict) -> None:
        """Atomically project one normalized operation into canonical facts."""
        observed = normalize_operation_observation(unit, raw)
        position, end = observed['position'], observed['end']
        origin = observed['origin_ref']
        target = observed['resource']
        target_ref = ({'kind': 'resource', 'id': identifier(
            'resource', target['kind'], target['name'].casefold())}
            if target else None)

        binding_ids = {'input': set(observed['input_binding_ids']),
                       'output': set(observed['output_binding_ids'])}
        binding_ids['input'].update(observed['header_binding_ids'])
        for direction in ('input', 'output'):
            names = set(observed[direction+'_binding_names'])
            matched = {
                bid for bid, binding in self.facts['bindings'].items()
                if binding['source'] == origin and binding['direction'] == direction
                and binding['name'] in names}
            matched_names = {self.facts['bindings'][bid]['name'] for bid in matched}
            if names - matched_names:
                raise ValueError(
                    f'Normalized operation references unknown {direction} binding names')
            binding_ids[direction].update(matched)

        gap_projections = {gap['projection'] for gap in observed['projection_gaps']}
        for direction in ('input', 'output'):
            missing_ids = binding_ids[direction] - self.facts['bindings'].keys()
            if missing_ids:
                raise ValueError(
                    f'Normalized operation references unknown {direction} binding IDs')
            incomplete = any(
                self.facts['bindings'][bid]['resolution'] != 'resolved'
                for bid in binding_ids[direction]) or any(
                    binding['resolution'] != 'resolved'
                    for binding in observed[direction+'_bindings'])
            projection = direction + '_bindings'
            if incomplete and (observed['resolution'] == 'resolved'
                               or projection not in gap_projections):
                raise ValueError(
                    'Incomplete operation binding requires an unresolved operation '
                    'and matching projection gap')

        evidence_id = self.evidence(unit.source, unit.start+position, unit.start+end)
        supporting_evidence_ids = sorted({self.evidence(unit.source,
            unit.start+start, unit.start+finish)
            for start, finish in observed['supporting_evidence_spans']})
        effect_evidence_ids = sorted({evidence_id, *supporting_evidence_ids})
        if target:
            rid = target_ref['id']
            stored = self.facts['resources'].setdefault(rid, record('Resource', id=rid,
                evidence_ids=[], **target))
            if evidence_id not in stored['evidence_ids']:
                stored['evidence_ids'].append(evidence_id)
        for direction in ('input', 'output'):
            for binding in observed[direction+'_bindings']:
                bid = identifier('binding', unit.symbol_id, direction, binding['name'],
                                 binding['position'], binding['end'])
                binding_evidence = self.evidence(unit.source,
                    unit.start+binding['position'], unit.start+binding['end'])
                source = origin if direction == 'input' or not target_ref else target_ref
                destination = target_ref if direction == 'input' and target_ref else origin
                self.facts['bindings'][bid] = record('Binding', id=bid,
                    name=binding['name'], value_type=binding['value_type'],
                    direction=direction, source=source, target=destination,
                    expression=binding['expression'], evidence_ids=[binding_evidence],
                    resolution=binding['resolution'], reason=binding['reason'])
                binding_ids[direction].add(bid)

        edge_kind = CATALOG['operation_edge_kinds'].get(observed['kind'])
        if edge_kind is None:
            raise ValueError('Normalized operation kind has no canonical edge projection')
        edge_id = identifier('edge', unit.symbol_id, edge_kind, position, target_ref)
        all_bindings = sorted(binding_ids['input'] | binding_ids['output'])
        self.facts['edges'][edge_id] = record('Edge', id=edge_id,
            from_ref=origin, to_ref=target_ref, kind=edge_kind,
            binding_ids=all_bindings, condition=observed['condition'],
            evidence_ids=[evidence_id], resolution=observed['resolution'],
            reason=observed['reason'])
        self.facts['coverage']['edges_'+observed['resolution']] += 1

        effect_id = None
        if observed['kind'] != 'data_read':
            effect_id = identifier('effect', unit.symbol_id, position)
            self.facts['effects'][effect_id] = record('Effect', id=effect_id,
                kind=observed['kind'], target=target_ref, origin_ref=origin,
                edge_id=edge_id, input_binding_ids=sorted(binding_ids['input']),
                output_binding_ids=sorted(binding_ids['output']),
                condition=observed['condition'], outcome=observed['outcome'],
                protocol=observed['protocol'], status=observed['status'],
                target_identity_key=observed['target_identity_key'],
                media_type=observed['media_type'],
                header_binding_ids=observed['header_binding_ids'],
                transaction_scope=observed['transaction_scope'],
                completion=observed['completion'], evidence_ids=effect_evidence_ids,
                resolution=observed['resolution'], reason=observed['reason'])

        if observed['resolution'] != 'resolved':
            subjects = [edge_id]
            for gap in observed['projection_gaps']:
                self.diagnostics.append(record('Diagnostic',
                    code=gap['code'],
                    message=f"{gap['projection']}: {gap['reason']}",
                    subject_ids=subjects, evidence_ids=effect_evidence_ids))


def extraction_measurements(facts: dict) -> dict:
    """Summarize normalized extraction without invoking semantic synthesis."""
    traces = list(facts['traces'].values())
    obligations = list(facts['trace_obligations'].values())
    languages_by_path = {
        resource['name']: resource['language']
        for resource in facts['resources'].values()
        if resource.get('kind') == 'repository_file' and resource.get('language')
    }

    def obligation_language(obligation):
        origin = obligation['origin_ref']
        if origin['kind'] != 'symbol':
            return 'unknown'
        symbol = facts['symbols'].get(origin['id'])
        if not symbol:
            return 'unknown'
        return languages_by_path.get(symbol['file'], 'unknown')

    # Relationships that are not resolved: where they come from, how many
    # stop at a catalogued boundary, and how many no trace reaches at all.
    edge_codes = {}
    for warning in facts.get('warnings', []):
        for subject in warning.get('subject_ids') or ():
            edge_codes.setdefault(subject, set()).add(warning['code'])
    traced_edges = {edge_id for trace in traces for edge_id in trace.get('edge_ids', [])}
    open_edges = [edge for edge in facts.get('edges', {}).values()
                  if edge['resolution'] != 'resolved']
    open_by_language = {}
    for edge in open_edges:
        symbol = facts['symbols'].get(edge['from_ref']['id']) if edge['from_ref']['kind'] == 'symbol' else None
        language = languages_by_path.get(symbol['file'], 'unknown') if symbol else 'unknown'
        open_by_language[language] = open_by_language.get(language, 0) + 1
    boundary_codes = set(TRACE_BOUNDARIES['diagnostic_codes'])

    def at_boundary(edge):
        if edge_codes.get(edge['id']):
            return edge_codes[edge['id']] <= boundary_codes
        # A call into a catalogued library or platform carries no warning;
        # its target resource names the provider.
        target = edge.get('to_ref') or {}
        resource = (facts['resources'].get(target.get('id'))
                    if target.get('kind') == 'resource' else None)
        return bool(resource) and _known_provider(resource.get('language'),
                                                  resource.get('provider'))

    at_boundaries = sum(at_boundary(edge) for edge in open_edges)
    untraced = sum(edge['id'] not in traced_edges for edge in open_edges)

    unresolved_calls = [
        obligation for obligation in obligations
        if obligation['kind'] == 'call_target'
        and obligation['status'] == 'unresolved'
    ]
    unresolved_by_language = {}
    for obligation in unresolved_calls:
        language = obligation_language(obligation)
        unresolved_by_language[language] = \
            unresolved_by_language.get(language, 0) + 1
    # The same call site is an obligation of every trace that reaches it, so
    # sites are counted once, by edge (or by obligation when it has none).
    unresolved_sites = {}
    for obligation in unresolved_calls:
        unresolved_sites.setdefault(obligation.get('edge_id') or obligation['id'],
                                    obligation_language(obligation))
    sites_by_language = {}
    for language in unresolved_sites.values():
        sites_by_language[language] = sites_by_language.get(language, 0) + 1

    ui_anchor_ids = {
        anchor['id'] for anchor in facts['anchors'].values()
        if anchor['kind'] == 'ui'
    }
    ui_traces = [
        trace for trace in traces if trace['anchor_id'] in ui_anchor_ids
    ]
    return {
        'schema_version': 1,
        'traces': {
            'total': len(traces),
            'resolved': sum(trace['resolution'] == 'resolved' for trace in traces),
            'ambiguous': sum(trace['resolution'] == 'ambiguous' for trace in traces),
            'unresolved': sum(trace['resolution'] == 'unresolved' for trace in traces),
            **{level: sum(trace.get('completion') == level for trace in traces)
               for level in ('complete', 'bounded', 'incomplete')},
        },
        'relationships': {
            'open': len(open_edges),
            'open_by_language': dict(sorted(open_by_language.items(),
                                            key=lambda item: (-item[1], item[0]))),
            'open_at_boundaries': at_boundaries,
            'open_outside_traces': untraced,
        },
        'call_targets': {
            'unresolved': len(unresolved_calls),
            'unresolved_by_language': dict(sorted(unresolved_by_language.items())),
            'unresolved_sites': len(unresolved_sites),
            'unresolved_sites_by_language': dict(sorted(sites_by_language.items())),
        },
        'ui_interactions': {
            'eligible_traces': len(ui_traces),
            'populated_traces': sum(
                trace.get('ui_interaction') is not None for trace in ui_traces),
        },
    }
