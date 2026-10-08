"""Entry-point coverage: language gaps and likely missed entry-point markers.

Everything framework- or language-specific lives in
``data/entrypoint_markers.toml`` and in the adapter capability declarations of
``data/extraction.toml``. This module only applies them.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from .business_domain_schema import ENTRYPOINT_GAP_CODES

CATALOG_PATH = Path(__file__).parent / 'data' / 'entrypoint_markers.toml'

LANGUAGE_GAP = 'language_unavailable'
LIKELY_MISSED = 'likely_missed'
NONE_DETECTED = 'none_detected'
GAP_CODES = MappingProxyType(dict(ENTRYPOINT_GAP_CODES))

_IDENTIFIER = re.compile(r'[a-z][a-z0-9_]*\Z')


class MarkerCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Marker:
    framework: str
    framework_label: str
    id: str
    name: str
    kind: str
    pattern: re.Pattern
    # Optional: read the HTTP method and route the marker declares
    # (named groups ``method`` and ``path``), and the route-group prefix a
    # file declares (named group ``prefix``).
    operation: re.Pattern | None = None
    prefix: re.Pattern | None = None


@dataclass(frozen=True)
class Framework:
    id: str
    label: str
    paths: tuple[re.Pattern, ...]
    requires_all: tuple[re.Pattern, ...]
    markers: tuple[Marker, ...]


@dataclass(frozen=True)
class MarkerCatalog:
    kinds: Mapping[str, str]
    categories: frozenset[str]
    non_entrypoint_languages: frozenset[str]
    display_names: Mapping[str, str]
    frameworks: tuple[Framework, ...]

    def display_name(self, language: str) -> str:
        return self.display_names.get(language, language)

    def scans(self, path: str) -> bool:
        """Whether any framework searches this repository-relative path."""
        return any(pattern.fullmatch(path) for framework in self.frameworks
                   for pattern in framework.paths)


@dataclass(frozen=True)
class MarkerHit:
    marker: Marker
    path: str
    start: int
    end: int
    start_line: int
    end_line: int


def _compile(values, cause):
    if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values):
        raise MarkerCatalogError(cause)
    try:
        return tuple(re.compile(value) for value in values)
    except re.error:
        raise MarkerCatalogError(cause) from None


def parse_catalog(raw: Mapping) -> MarkerCatalog:
    """Validate one catalog document; reject anything it does not define."""
    if set(raw) - {'version', 'kinds', 'coverage', 'display_names', 'frameworks'} \
            or raw.get('version') != 1:
        raise MarkerCatalogError('entrypoint_catalog_invalid')
    kinds = raw.get('kinds')
    if not isinstance(kinds, dict) or not kinds or not all(
            _IDENTIFIER.fullmatch(key) and isinstance(value, str) and value
            for key, value in kinds.items()):
        raise MarkerCatalogError('entrypoint_catalog_kinds_invalid')
    coverage = raw.get('coverage')
    if (not isinstance(coverage, dict)
            or set(coverage) != {'categories', 'non_entrypoint_languages'}
            or not all(isinstance(value, list) and all(
                isinstance(item, str) and item for item in value)
                for value in coverage.values())):
        raise MarkerCatalogError('entrypoint_catalog_coverage_invalid')
    names = raw.get('display_names', {})
    if not isinstance(names, dict) or not all(
            isinstance(key, str) and isinstance(value, str) and value
            for key, value in names.items()):
        raise MarkerCatalogError('entrypoint_catalog_display_names_invalid')
    frameworks = []
    for identity, entry in sorted((raw.get('frameworks') or {}).items()):
        if (not _IDENTIFIER.fullmatch(identity) or not isinstance(entry, dict)
                or set(entry) - {'label', 'paths', 'requires_all', 'markers'}
                or not isinstance(entry.get('label'), str) or not entry['label']):
            raise MarkerCatalogError('entrypoint_catalog_framework_invalid')
        paths = _compile(entry.get('paths'), 'entrypoint_catalog_paths_invalid')
        if not paths:
            raise MarkerCatalogError('entrypoint_catalog_paths_invalid')
        requires = _compile(entry.get('requires_all', []),
                            'entrypoint_catalog_requires_invalid')
        markers = []
        raw_markers = entry.get('markers')
        if not isinstance(raw_markers, list) or not raw_markers:
            raise MarkerCatalogError('entrypoint_catalog_markers_invalid')
        for item in raw_markers:
            if (not isinstance(item, dict)
                    or not {'id', 'name', 'kind', 'pattern'} <= set(item)
                    or set(item) - {'id', 'name', 'kind', 'pattern', 'operation', 'prefix'}
                    or not _IDENTIFIER.fullmatch(str(item['id']))
                    or not isinstance(item['name'], str) or not item['name']
                    or item['kind'] not in kinds
                    or any(item['id'] == marker.id for marker in markers)):
                raise MarkerCatalogError('entrypoint_catalog_marker_invalid')
            pattern, = _compile([item['pattern']],
                                'entrypoint_catalog_marker_invalid')
            operation, prefix = (
                (_compile([item[key]], 'entrypoint_catalog_marker_invalid')[0]
                 if key in item else None) for key in ('operation', 'prefix'))
            if operation is not None and not {'method', 'path'} <= set(operation.groupindex):
                raise MarkerCatalogError('entrypoint_catalog_marker_invalid')
            if prefix is not None and 'prefix' not in prefix.groupindex:
                raise MarkerCatalogError('entrypoint_catalog_marker_invalid')
            markers.append(Marker(identity, entry['label'], item['id'],
                                  item['name'], item['kind'], pattern, operation, prefix))
        frameworks.append(Framework(identity, entry['label'], paths, requires,
                                    tuple(markers)))
    return MarkerCatalog(MappingProxyType(dict(kinds)),
        frozenset(coverage['categories']),
        frozenset(coverage['non_entrypoint_languages']),
        MappingProxyType(dict(names)), tuple(frameworks))


@lru_cache(maxsize=None)
def load_catalog(path: Path = CATALOG_PATH) -> MarkerCatalog:
    try:
        with open(path, 'rb') as stream:
            return parse_catalog(tomllib.load(stream))
    except (OSError, tomllib.TOMLDecodeError):
        raise MarkerCatalogError('entrypoint_catalog_unavailable') from None


def scan_markers(catalog: MarkerCatalog, files: Iterable[tuple[str, str]],
                 test_path_pattern: str | None = None) -> list[MarkerHit]:
    """Every catalog marker hit in *files* ((path, text) pairs), in order.

    Hits of one framework never overlap; test paths are not searched.
    """
    test_path = re.compile(test_path_pattern) if test_path_pattern else None
    hits = []
    for path, text in sorted(files):
        if test_path is not None and test_path.search(path):
            continue
        for framework in catalog.frameworks:
            if not any(pattern.fullmatch(path) for pattern in framework.paths):
                continue
            if not all(pattern.search(text) for pattern in framework.requires_all):
                continue
            found = sorted(((match.start(), match.end(), marker)
                for marker in framework.markers
                for match in marker.pattern.finditer(text)),
                key=lambda item: (item[0], -item[1], item[2].id))
            claimed_end = -1
            for start, end, marker in found:
                if start < claimed_end:
                    continue
                claimed_end = max(end, start + 1)
                hits.append(MarkerHit(marker, path, start, end,
                    text.count('\n', 0, start) + 1,
                    text.count('\n', 0, max(start, end - 1)) + 1))
    return hits


def route_key(path: str) -> str:
    """A route with parameter constraints and optional markers removed."""
    path = re.sub(r"\{([^{}:?=]+)[^{}]*\}", r"{\1}", path.strip())
    return "/" + "/".join(part for part in path.split("/") if part)


def declared_operations(hit: MarkerHit, text: str) -> list[tuple[str, str]]:
    """The ``(METHOD, route)`` pairs the marker at *hit* may declare.

    Without a route-group prefix the route is as written. With exactly one
    distinct prefix in the file it may also be prefixed; several distinct
    prefixes leave the prefixed form unknown.
    """
    marker = hit.marker
    if marker.operation is None:
        return []
    match = marker.operation.match(text, hit.start)
    if not match:
        return []
    method, route = match.group("method").upper(), route_key(match.group("path"))
    routes = [route]
    if marker.prefix is not None:
        prefixes = {route_key(item.group("prefix")) for item in marker.prefix.finditer(text)}
        if len(prefixes) == 1:
            routes.append(route_key(prefixes.pop() + route))
    return [(method, item) for item in routes]


def matching_entry_point(hit: MarkerHit, text: str,
                         operations: Mapping[tuple[str, str], list[str]]) -> str | None:
    """The one existing entry point whose method and route the marker declares."""
    found = {anchor for key in declared_operations(hit, text)
             for anchor in operations.get(key, ())}
    return found.pop() if len(found) == 1 else None


def covered(hit: MarkerHit, spans: Mapping[str, list[tuple[int, int]]]) -> bool:
    """An anchor span in the hit's file intersects the hit's lines."""
    return any(start <= hit.end_line and hit.start_line <= end
               for start, end in spans.get(hit.path, ()))


def gap_record(kind: str, message: str, *, language=None, files=None,
               hit: MarkerHit | None = None) -> dict:
    """One structured coverage entry; its diagnostic carries the same code and message."""
    marker = hit.marker if hit else None
    return {
        'kind': kind, 'code': GAP_CODES[kind], 'message': message,
        'language': language, 'files': files,
        'framework': marker.framework if marker else None,
        'marker': marker.id if marker else None,
        'marker_kind': marker.kind if marker else None,
        'path': hit.path if hit else None,
        'line': hit.start_line if hit else None,
    }
