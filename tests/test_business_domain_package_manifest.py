"""package.json as a supporting input owned by one named consumer (F1)."""
import pytest

from lib.context.business_domain_adapters import package_manifest
from lib.context.business_domain_adapters.base import Source
from lib.context.business_domain_adapters.package_manifest import (
    PackageJsonError, parse_package_json)
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, digest, identifier, validate_references, validate_source_warning_coverage)


def _source(path, text):
    return Source(path, 'json', text, digest(text.encode()), identifier('resource', path))


def _extract(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, units = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    validate_source_warning_coverage(facts)
    return facts, units


def test_parser_normalizes_engines_and_dependencies_and_never_reads_scripts():
    manifest = parse_package_json('{"engines": {"node": ">=18"}, '
        '"dependencies": {"react": "^18", "b": "1"}, "devDependencies": {"react": "^17"}, '
        '"scripts": {"postinstall": "rm -rf /"}}')
    assert manifest.engines == ({'name': 'node', 'constraint': '>=18'},)
    assert manifest.dependencies == (
        {'name': 'b', 'constraint': '1', 'dependency_kind': 'runtime'},
        {'name': 'react', 'constraint': '^18', 'dependency_kind': 'runtime'},
        {'name': 'react', 'constraint': '^17', 'dependency_kind': 'development'})
    assert 'rm -rf' not in repr(manifest)


@pytest.mark.parametrize('text, cause, span', [
    ('', 'json_syntax_invalid', (0, 0)),
    ('{"a": ', 'json_syntax_invalid', (6, 6)),
    ('{"a" 1}', 'json_syntax_invalid', (5, 6)),
    ('[]', 'top_level_must_be_object', (0, 2)),
    ('{"engines": []}', 'engines_must_be_object', (0, 15)),
    ('{"dependencies": {"a": 1}}', 'dependencies_values_must_be_strings', (0, 26)),
])
def test_strict_parser_errors_carry_exact_spans(text, cause, span):
    with pytest.raises(PackageJsonError) as raised:
        parse_package_json(text)
    assert (raised.value.cause, raised.value.start, raised.value.end) == (cause, *span)


def test_tolerant_sections_do_not_suppress_each_other():
    broken_dependencies = '{"engines": {"node": "18"}, "dependencies": [1]}'
    assert parse_package_json(broken_dependencies, ('engines',), strict=False).engines == (
        {'name': 'node', 'constraint': '18'},)
    broken_engines = '{"engines": 7, "dependencies": {"react": "18", "x": 3}}'
    tolerant = parse_package_json(broken_engines, ('dependencies', 'devDependencies'),
                                  strict=False)
    assert [(item['name'], item['constraint']) for item in tolerant.dependencies] == [
        ('react', '18'), ('x', None)]
    for text in (broken_dependencies, broken_engines):
        with pytest.raises(PackageJsonError):
            parse_package_json(text)


def test_consumer_accounts_for_every_source_exactly_once():
    good = _source('client/package.json', '{"dependencies": {"react": "18"}}')
    bad = _source('package.json', '{oops')
    result = package_manifest.consume((good, bad), ())
    assert result.consumed_source_ids == (good.resource_id,)
    assert [item['source_id'] for item in result.diagnostics] == [bad.resource_id]
    assert result.diagnostics[0]['code'] == 'PACKAGE_JSON_INVALID'
    [normalized] = result.normalized_inputs
    assert (normalized['scope_dir'], normalized['document_kind']) == ('client', 'package')


def test_package_dependencies_reach_compatible_primary_sources(tmp_path):
    facts, units = _extract(tmp_path, {
        'client/package.json': '{"dependencies": {"react": "18.2.0"}}',
        'client/src/App.tsx': 'export const App = () => 1;\n',
        'server/main.py': 'def run():\n    return 1\n',
    })
    by_path = {unit.source.path: unit.source for unit in units}
    package = by_path['client/src/App.tsx'].supporting_inputs['package_manifest']['package']
    assert [item['name'] for item in package['dependencies']] == ['react']
    assert 'package_manifest' not in by_path['server/main.py'].supporting_inputs
    resource = facts['resources'][identifier('resource', 'client/package.json')]
    assert resource['resolution'] == 'resolved' and resource['evidence_ids']
    assert any(item['adapter'] == 'package_manifest' and item['status'] == 'partial'
               for item in facts['capabilities'])


def test_malformed_package_is_a_format_diagnostic_not_unsupported(tmp_path):
    facts, _ = _extract(tmp_path, {'package.json': '{"dependencies": 3}'})
    resource_id = identifier('resource', 'package.json')
    [warning] = [w for w in facts['warnings'] if w['subject_ids'] == [resource_id]]
    assert warning['code'] == 'PACKAGE_JSON_INVALID'
    assert warning['message'] == 'dependencies_must_be_object' and warning['evidence_ids']
    assert facts['resources'][resource_id]['resolution'] == 'unresolved'
    assert facts['coverage']['unsupported_source_ids'] == []


def test_consumer_contract_failure_fails_its_whole_group(tmp_path, monkeypatch):
    original = package_manifest.consume

    def duplicated(supporting, primary):
        result = original(supporting, primary)
        return type(result)(result.consumed_source_ids * 2, result.normalized_inputs, ())
    monkeypatch.setattr(package_manifest, 'consume', duplicated)
    facts, _ = _extract(tmp_path, {'a/package.json': '{}', 'b/package.json': '{}'})
    warnings = [w for w in facts['warnings'] if w['code'] == 'ADAPTER_UNAVAILABLE']
    assert len(warnings) == 2
    assert all('cause=consumer_contract_invalid' in w['message'] for w in warnings)
    assert all('lost_facts=[framework_activation]' in w['message'] for w in warnings)
    assert sorted(facts['coverage']['unsupported_source_ids']) == sorted(
        identifier('resource', path) for path in ('a/package.json', 'b/package.json'))


def test_thrown_consumer_fails_every_source_in_its_group(tmp_path, monkeypatch):
    def broken(supporting, primary):
        raise RuntimeError('repository text must not leak')
    monkeypatch.setattr(package_manifest, 'consume', broken)
    facts, _ = _extract(tmp_path, {'a/package.json': '{}', 'b/package.json': '{}'})
    warnings = [w for w in facts['warnings'] if w['code'] == 'ADAPTER_UNAVAILABLE']
    assert len(warnings) == 2
    assert all('cause=owner_execution_failed' in w['message'] for w in warnings)
    assert 'repository text' not in str(facts)
