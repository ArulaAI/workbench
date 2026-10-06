"""Adapter registry. Discovery consumes contracts, not language names."""
import importlib
import json
from pathlib import Path
from ..language_registry import registry
from .base import Source

CATALOG = json.loads(Path(__file__).with_name('catalog.json').read_text())


def descriptor(
    path: str | Source,
    source_text: str | None = None,
    evidence: dict | None = None,
) -> dict | None:
    if isinstance(path, Source):
        path, source_text = path.path, path.text
    category, language = registry.classify(Path(path).suffix.lower())
    if not language:
        return None
    # Repository-relative location is admissible, deterministic dialect
    # evidence (for example db/postgresql/*.sql). Keep it visibly separated
    # from file contents so descriptors can opt into it explicitly.
    detection_text = (source_text or '') + '\nSPEED_PATH:' + path
    candidates = registry.source_adapters(
        language, detection_text, evidence=evidence, kind='adapter')
    selected = candidates[0] if len(candidates) == 1 else None
    return {'language':language, 'adapter':selected.get('module') if selected else None,
            'capability':selected, 'candidates':[c['id'] for c in candidates],
            'registry_error':registry.source_adapter_error,
            'source_kind':CATALOG['source_kind_by_category'].get(category, 'source')}


def enricher_descriptors(
    path: str | Source,
    evidence: dict[str, list[str] | tuple[str, ...] | str],
) -> list[dict]:
    """Select installed framework enrichers solely from declared evidence."""
    if isinstance(path, Source):
        source_text, path = path.text, path.path
    else:
        source_text = None
    _, language = registry.classify(Path(path).suffix.lower())
    if not language:
        return []
    return registry.source_adapters(
        language, source_text, evidence=evidence, kind='enricher',
    )


def load_installed(module_name: str):
    if not module_name or not isinstance(module_name, str):
        raise ValueError('Installed module name is required')
    installed = Path(__file__).parent.resolve()
    module = (installed/(module_name+'.py')).resolve()
    if not module.is_relative_to(installed) or not module.is_file():
        raise ValueError('Selected source adapter is not installed in the trusted package')
    return importlib.import_module('.' + module_name, __name__)


def descriptor_for_route(source: Source, route) -> list[dict]:
    """Candidate installed owners for one routed source; selection is the caller's.

    An explicit route names its owner. Otherwise the language candidates are
    matched against installed adapters, excluding any adapter that requires an
    explicit pre-decode route, so fallback matching never reaches a decoder.
    """
    if route.disposition in {'ignore', 'reference_only'}:
        return []
    if route.expected_owner:
        descriptor = (registry.supporting_consumer_descriptor(route.expected_owner)
            if route.disposition == 'supporting'
            else registry.source_adapter_descriptor(route.expected_owner))
        return [dict(descriptor)] if descriptor else []
    supplied_languages = route.classification.language_candidate_ids or (
        (route.classification.language,) if route.classification.language else ())
    matches = {}
    detection_text = source.text + '\nSPEED_PATH:' + source.path
    for language in supplied_languages:
        for descriptor in registry.source_adapters(language, detection_text,
                kind='adapter'):
            if descriptor.get('decoder'):
                continue
            matches[descriptor['id']] = descriptor
    return [matches[key] for key in sorted(matches)]


def enrichers_for(path: str | Source, evidence: dict) -> list:
    """Load only evidence-selected enrichers from the installed package."""
    return [load_installed(item['module']) for item in enricher_descriptors(path, evidence)
            if item.get('module')]


def adapter_for(path: str | Source):
    entry = descriptor(path)
    if not entry or not entry['adapter']:
        return None
    return load_installed(entry['adapter'])
