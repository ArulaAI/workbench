"""Install a fixture source adapter by patching the extractor's routing hooks."""
from lib.context import business_domain_extract as core
from lib.context.language_registry import PathClassification

FIXTURE_SUFFIXES = ('.opaque', '.fixture')


def install_fixture_adapter(monkeypatch, adapter, legacy, suffixes=FIXTURE_SUFFIXES):
    """Route fixture-suffixed paths to *adapter*.

    *legacy* has a ``language`` key and an optional ``capability`` dict of
    descriptor fields.
    """
    language = legacy['language']
    capability = dict(legacy.get('capability') or {})
    descriptor = {'id': capability.get('id', 'fixture'), 'module': 'fixture_adapter',
                  'version': capability.get('version', '1'),
                  'capabilities': dict(capability.get('capabilities', {})),
                  'diagnostic_codes': list(capability.get('diagnostic_codes', []))}
    for key in ('parser', 'parser_version', 'framework', 'framework_version'):
        if key in capability:
            descriptor[key] = capability[key]
    classify_path = core.registry.classify_path
    descriptor_for_route = core.descriptor_for_route
    load_installed = core.load_installed

    def classify(path):
        if path.endswith(suffixes):
            return PathClassification(path, 'source', language, (language,), 'classified')
        return classify_path(path)

    def candidates(source, route):
        if source.path.endswith(suffixes):
            return [dict(descriptor)]
        return descriptor_for_route(source, route)

    def load(module_name):
        return adapter if module_name == 'fixture_adapter' else load_installed(module_name)

    monkeypatch.setattr(core.registry, 'classify_path', classify)
    monkeypatch.setattr(core, 'descriptor_for_route', candidates)
    monkeypatch.setattr(core, 'load_installed', load)
    return descriptor
