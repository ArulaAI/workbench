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


def _load_installed(module_name: str):
    if not module_name or not isinstance(module_name, str):
        return None
    installed = Path(__file__).parent.resolve()
    module = (installed/(module_name+'.py')).resolve()
    if not module.is_relative_to(installed) or not module.is_file():
        raise ValueError('Selected source adapter is not installed in the trusted package')
    return importlib.import_module('.' + module_name, __name__)


def enrichers_for(path: str | Source, evidence: dict) -> list:
    """Load only evidence-selected enrichers from the installed package."""
    return [_load_installed(item['module']) for item in enricher_descriptors(path, evidence)
            if item.get('module')]


def adapter_for(path: str | Source):
    entry = descriptor(path)
    if not entry or not entry['adapter']:
        return None
    return _load_installed(entry['adapter'])
