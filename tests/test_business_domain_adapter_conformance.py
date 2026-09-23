"""Conformance checks for the installed source-adapter boundary."""
from pathlib import Path
from shutil import copytree

import pytest

from lib.context.business_domain_adapters.base import SemanticResult, Source
from lib.context.language_registry import (
    LanguageRegistry,
    SOURCE_ADAPTER_CAPABILITIES,
    SOURCE_ADAPTER_CONTRACT_VERSION,
    SOURCE_ADAPTER_OUTPUT_VERSION,
)
from lib.context.treesitter_extract import _parse_ast_grep_matches, normalize_rule_outputs


def test_installed_adapters_declare_the_complete_capability_contract():
    registry = LanguageRegistry()

    assert registry.source_adapter_error is None
    assert registry._source_adapters
    for descriptor in registry._source_adapters.values():
        assert set(descriptor["capabilities"]) == SOURCE_ADAPTER_CAPABILITIES
        assert descriptor['contract_version'] == SOURCE_ADAPTER_CONTRACT_VERSION
        assert descriptor['normalized_output_version'] == SOURCE_ADAPTER_OUTPUT_VERSION


def test_sql_descriptors_reference_the_pinned_cross_platform_parser_artifact():
    registry = LanguageRegistry()
    parser = registry._trusted_parsers['sqlglot']

    assert 'sqlglot==30.18.0' in (Path(__file__).parents[1] / 'requirements.txt').read_text().splitlines()
    assert parser == {
        'distribution': 'sqlglot',
        'module': 'sqlglot',
        'version': '30.18.0',
        'implementation': 'pure-python',
        'wheel_tag': 'py3-none-any',
        'wheel_sha256': 'ee0f9a9f3e2193e763c326e52dfb377b96fdb4292f6305c3ff2d9a220e71c601',
    }
    for identity in ('oracle_plsql', 'postgresql'):
        descriptor = registry._source_adapters[identity]
        assert descriptor['parser'] == 'sqlglot'
        assert descriptor['parser_version'] == parser['version']


def test_trusted_parser_loader_rejects_repository_shadowing(tmp_path, monkeypatch):
    registry = LanguageRegistry()
    shadow = tmp_path / 'sqlglot' / '__init__.py'
    shadow.parent.mkdir()
    shadow.write_text('raise AssertionError("must not execute")')
    monkeypatch.setattr('lib.context.language_registry.importlib.util.find_spec',
        lambda _: type('Spec', (), {'origin': str(shadow)})())

    with pytest.raises(RuntimeError, match='shadowed'):
        registry.load_trusted_parser('sqlglot')


def test_capability_contract_separates_sql_semantic_dimensions():
    assert {
        'declaration_extraction', 'call_classification',
        'overload_resolution', 'data_access', 'rules', 'control_flow',
    } <= SOURCE_ADAPTER_CAPABILITIES


def test_incomplete_descriptor_is_rejected_without_losing_languages(tmp_path):
    data = tmp_path / "registry"
    data.mkdir()
    (data / "languages.toml").write_text(
        '[[language]]\nname="python"\nfile-types=["py"]\n'
    )
    (data / "extraction.toml").write_text(
        '[python]\nextraction="rules"\n'
        '[source_adapters.fixture]\nmodule="rules"\nversion="1"\n'
        'contract_version=1\nnormalized_output_version=1\nkind="adapter"\n'
        'conformance="fixture"\nextraction_level="rules"\n'
        '[source_adapters.fixture.capabilities]\nparsing="supported"\n'
    )

    registry = LanguageRegistry(data)

    assert registry.classify(".py") == ("source", "python")
    assert registry._source_adapters == {}
    assert registry.source_adapter_error == "ValueError"


def _fixture_capabilities(status: str = 'supported') -> str:
    return '\n'.join(f'{name}="{status}"' for name in sorted(SOURCE_ADAPTER_CAPABILITIES))


def test_new_language_adapter_is_selected_from_installed_descriptor_without_core_change(tmp_path, monkeypatch):
    data = tmp_path / 'installed'
    data.mkdir()
    (data / 'languages.toml').write_text(
        '[[language]]\nname="fixture-lang"\nfile-types=["fx"]\n'
    )
    (data / 'extraction.toml').write_text(
        '[fixture-lang]\nextraction="rules"\n'
        '[source_adapters.fixture]\nmodule="documents"\nversion="1.2.3"\n'
        'contract_version=1\nnormalized_output_version=1\nkind="adapter"\n'
        'conformance="fixture"\nlanguages=["fixture_lang"]\n'
        '[source_adapters.fixture.evidence]\nsource_any=["openapi"]\n'
        '[source_adapters.fixture.capabilities]\n' + _fixture_capabilities('partial')
    )

    registry = LanguageRegistry(data)
    selected = registry.source_adapters('fixture_lang', 'openapi: 3.0.1')

    assert registry.classify('.fx') == ('source', 'fixture_lang')
    assert [item['id'] for item in selected] == ['fixture']
    assert selected[0]['module'] == 'documents'

    import lib.context.business_domain_adapters as adapters
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS
    monkeypatch.setattr(adapters, 'registry', registry)
    repository = tmp_path / 'repository'
    repository.mkdir()
    (repository / 'contract.fx').write_text(
        'openapi: 3.0.1\npaths:\n  /fixture:\n    get:\n      operationId: fixture\n'
    )
    facts, _ = Extractor(repository, DEFAULTS).extract()

    assert len(facts['anchors']) == 1
    assert {item['adapter'] for item in facts['capabilities']} == {'fixture'}


def test_framework_enricher_activates_only_from_declared_evidence(monkeypatch):
    from lib.context.business_domain_adapters import enrichers_for
    from lib.context.business_domain_adapters import rules
    from lib.context.language_registry import registry

    descriptor = {
        'kind':'enricher', 'module':'rules', 'version':'1', 'contract_version':1,
        'normalized_output_version':1, 'conformance':'fixture', 'framework':'fixture',
        'languages':['python'], 'capabilities':{name:'unsupported' for name in SOURCE_ADAPTER_CAPABILITIES},
        'evidence':{
            'imports_any':['fixture_framework'],
            'annotations_any':['FixtureEndpoint'],
            'dependencies_any':['fixture-runtime'],
        },
    }
    descriptor['capabilities']['framework_enrichment'] = 'supported'
    monkeypatch.setattr(registry, '_source_adapters', {
        **registry._source_adapters, 'fixture_framework':descriptor,
    })
    source = Source('service.py', 'python', '@FixtureEndpoint\nimport fixture_framework',
                    '0' * 64, 'resource:service')

    assert enrichers_for(source, {
        'imports':['fixture_framework'], 'annotations':['FixtureEndpoint'],
        'dependencies':['fixture-runtime:1.0'],
    }) == [rules]
    assert enrichers_for(source, {
        'imports':['fixture_framework'], 'annotations':['FixtureEndpoint'],
        'dependencies':['different-runtime'],
    }) == []


@pytest.mark.parametrize('outcome', ['exact', 'ambiguous', 'unresolved', 'external', 'unsupported'])
def test_cross_language_semantic_results_have_one_normalized_shape(outcome):
    values = {
        'capability':'callable_resolution', 'outcome':outcome,
        'subject_id':'symbol:caller', 'evidence_ids':('ev:call',),
    }
    if outcome == 'exact':
        values['target_id'] = 'symbol:target'
    elif outcome == 'ambiguous':
        values.update(candidate_target_ids=('symbol:one', 'symbol:two'),
                      diagnostic_code='AMBIGUOUS_CALL', reason='Two viable targets')
    elif outcome == 'external':
        values.update(target_id='resource:runtime', diagnostic_code='EXTERNAL_CALL',
                      reason='Dependency-owned implementation')
    else:
        values.update(diagnostic_code=outcome.upper() + '_CALL', reason='No proven local target')

    java = SemanticResult(**values).normalized()
    non_java = SemanticResult(**values).normalized()

    assert java == non_java
    assert set(java) == {
        'contract_version', 'capability', 'outcome', 'subject_id', 'target_id',
        'candidate_target_ids', 'evidence_ids', 'diagnostic_code', 'reason',
    }


def test_java_and_rules_adapters_emit_the_same_evidenced_result_contract(tmp_path):
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS

    (tmp_path/'Service.java').write_text(
        'class Service { void helper() {} void run() { this.helper(); } }')
    (tmp_path/'service.py').write_text(
        'def helper():\n    pass\ndef run():\n    helper()\n')
    facts, units = Extractor(tmp_path, DEFAULTS).extract()
    results = {
        language: [result for unit in units if unit.source.language == language
                   for result in unit.source.semantic_results
                   if result['capability'] == 'callable_resolution' and result['outcome'] == 'exact']
        for language in ('java', 'python')
    }

    assert all(results.values())
    assert set(results['java'][0]) == set(results['python'][0])
    for result in results['java'] + results['python']:
        assert result['subject_id'] in facts['symbols']
        assert result['target_id'] in facts['symbols']
        assert set(result['evidence_ids']) <= set(facts['evidence'])


def test_external_semantic_result_is_not_an_unresolved_local_target():
    result = SemanticResult(
        capability='callable_resolution', outcome='external', subject_id='symbol:caller',
        target_id='resource:jdk-runtime', evidence_ids=('ev:call',),
        diagnostic_code='EXTERNAL_RUNTIME_TARGET', reason='Runtime-owned behavior',
    ).normalized()

    assert result['outcome'] == 'external'
    assert result['target_id'] == 'resource:jdk-runtime'


def test_adapter_provenance_and_exact_diagnostic_and_call_evidence(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from lib.context import business_domain_extract as core
    from lib.context.business_domain_adapters.base import Unit, declare_trace_contract
    from lib.context.business_domain_schema import DEFAULTS

    text = 'function caller() { target(); /*gap*/ }\nfunction target() {}\n'
    captured = {}

    def extract(source):
        caller_end = text.index('\n')
        caller = Unit(source, 'caller', 'fixture::caller', 0, caller_end,
            'function', executable_body=True)
        target_start = caller_end + 1
        target = Unit(source, 'target', 'fixture::target', target_start, len(text),
            'function', executable_body=True)
        declare_trace_contract(caller)
        declare_trace_contract(target)
        return [caller, target]

    def calls(unit):
        if unit.name != 'caller':
            return []
        position = unit.text.index('target()')
        return [{'receiver':None, 'name':'target', 'position':position,
                 'end':position + len('target()')}]

    def candidates(unit, receiver, name, available, position=None):
        return [candidate for candidate in available if candidate.name == name]

    def resolve_call(unit, receiver, name, candidates, position, evidence_id):
        captured['evidence_id'] = evidence_id
        return SemanticResult(capability='callable_resolution', outcome='exact',
            subject_id=unit.symbol_id, target_id=candidates[0].symbol_id,
            evidence_ids=(evidence_id,))

    adapter = SimpleNamespace(
        extract=extract, calls=calls, candidates=candidates, resolve_call=resolve_call,
        bindings=lambda unit: [], resources=lambda unit: [], observations=lambda unit: [],
        operations=lambda unit: [], diagnostics=lambda source: [{
            'code':'FIXTURE_PARSE_GAP', 'reason':'Fixture parser gap.',
            'span':(text.index('/*gap*/'), text.index('/*gap*/') + len('/*gap*/')),
        }],
    )
    capability = {
        'id':'fixture_parser', 'version':'9.4',
        'capabilities':{name:'supported' for name in SOURCE_ADAPTER_CAPABILITIES},
        'diagnostic_codes':['FIXTURE_PARSE_GAP'],
    }
    selected = {'language':'fixture', 'adapter':'fixture_parser',
        'capability':capability, 'candidates':['fixture_parser'],
        'registry_error':None, 'source_kind':'source'}
    monkeypatch.setattr(core, 'descriptor', lambda path: selected)
    monkeypatch.setattr(core, 'adapter_for', lambda source: adapter)
    path = tmp_path / 'source.fixture'
    path.write_text(text)

    facts, units = core.Extractor(tmp_path, DEFAULTS).extract()

    edge = next(edge for edge in facts['edges'].values() if edge['kind'] == 'calls')
    result = next(result for result in units[0].source.semantic_results
                  if result['capability'] == 'callable_resolution')
    call_evidence = facts['evidence'][edge['evidence_ids'][0]]
    warning = next(item for item in facts['warnings'] if item['code'] == 'FIXTURE_PARSE_GAP')
    diagnostic_evidence = facts['evidence'][warning['evidence_ids'][0]]
    assert edge['evidence_ids'] == result['evidence_ids'] == [captured['evidence_id']]
    assert call_evidence['excerpt'] == 'target()'
    assert diagnostic_evidence['excerpt'] == '/*gap*/'
    assert call_evidence['extractor'] == diagnostic_evidence['extractor'] == 'fixture_parser'
    assert call_evidence['extractor_version'] == diagnostic_evidence['extractor_version'] == '9.4'


def test_semantic_result_rejects_unbounded_or_unevidenced_claims():
    with pytest.raises(ValueError, match='bounded'):
        SemanticResult(
            capability='type_resolution', outcome='ambiguous', subject_id='symbol:subject',
            candidate_target_ids=tuple(f'symbol:{value}' for value in range(9)),
            evidence_ids=('ev:type',), diagnostic_code='AMBIGUOUS_TYPE', reason='Nine candidates',
        )
    with pytest.raises(ValueError, match='evidence'):
        SemanticResult(
            capability='type_resolution', outcome='exact', subject_id='symbol:subject',
            target_id='symbol:target',
        )


def test_core_bounds_ambiguous_adapter_candidates(tmp_path):
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS

    declarations = ''.join(f'def choose(value{i}=None):\n    return {i}\n' for i in range(9))
    (tmp_path/'service.py').write_text(declarations + 'def run():\n    choose()\n')
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    edge = next(edge for edge in facts['edges'].values()
                if edge['kind'] == 'calls' and edge['resolution'] == 'ambiguous')

    assert len(edge['candidate_target_ids']) == 8
    assert edge['candidate_target_ids'] == sorted(edge['candidate_target_ids'])


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"produces": "future_record"}, "Unsupported extraction output"),
        ({"produces": "edge", "edge_type": "future_edge"}, "Unsupported structural edge"),
    ],
)
def test_canonical_rule_decoder_rejects_unmapped_outputs(metadata, message):
    match = {
        "ruleId": "fixture-rule",
        "metadata": metadata,
        "text": "class Example",
        "range": {
            "start": {"line": 0, "column": 0},
            "end": {"line": 0, "column": 13},
        },
        "metaVariables": {"single": {"NAME": {"text": "Example"}}},
    }

    with pytest.raises(ValueError, match=message):
        _parse_ast_grep_matches([match], "Example.java", "Example.java")


def test_canonical_rule_decoder_projects_raw_matches_once_for_consumers():
    raw = {
        "ruleId": "fixture-binding",
        "metadata": {"produces": "binding", "direction": "input", "name_var": "NAME"},
        "text": "customerId",
        "range": {"start": {"line": 2, "column": 4}, "end": {"line": 2, "column": 14}},
        "metaVariables": {"single": {"NAME": {"text": "customerId"}}},
    }

    output = normalize_rule_outputs([raw])[0]

    assert output.output_type == "binding"
    assert output.attributes == {"direction": "input", "name_var": "NAME"}
    assert output.captures == {"NAME": "customerId"}
    assert output.source_range == raw["range"]


def test_failed_adapter_reports_only_unsupported_capabilities(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import lib.context.business_domain_extract as core
    from lib.context.business_domain_schema import DEFAULTS

    selected = {
        'language': 'fixture', 'adapter': 'fixture_parser',
        'capability': {
            'id': 'fixture_parser', 'version': '1',
            'capabilities': {name: 'supported' for name in SOURCE_ADAPTER_CAPABILITIES},
            'diagnostic_codes': ['FIXTURE_FAILURE'],
        },
        'candidates': ['fixture_parser'], 'registry_error': None,
        'source_kind': 'source',
    }
    adapter = SimpleNamespace(extract=lambda source: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(core, 'descriptor', lambda path: selected)
    monkeypatch.setattr(core, 'adapter_for', lambda source: adapter)
    (tmp_path / 'source.fixture').write_text('fixture source')

    facts, _ = core.Extractor(tmp_path, DEFAULTS).extract()

    capabilities = [item for item in facts['capabilities']
                    if item['adapter'] == 'fixture_parser']
    assert capabilities
    assert {item['status'] for item in capabilities} == {'unsupported'}
    assert all('ADAPTER_UNAVAILABLE' in item['diagnostic_codes']
               for item in capabilities)
    assert any(item['code'] == 'ADAPTER_UNAVAILABLE' for item in facts['warnings'])


@pytest.mark.parametrize(('case', 'adapter', 'enricher'), [
    ('typescript', 'ts_semantic', None),
    ('html', 'html_semantic', None),
    ('react', 'ts_semantic', 'react_semantic'),
    ('angular', 'ts_semantic', 'angular_semantic'),
])
def test_frontend_adapter_fixture_uses_installed_contract(
        tmp_path, case, adapter, enricher):
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS, validate_references

    source = Path(__file__).parent / 'fixtures/business_domains/adapters' / case
    copytree(source, tmp_path, dirs_exist_ok=True)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)

    adapters = {item['adapter'] for item in facts['capabilities']}
    assert adapter in adapters
    if enricher:
        assert enricher in adapters
