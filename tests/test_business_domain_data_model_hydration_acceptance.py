"""F-08 acceptance: normalized operations hydrate one canonical model."""
from __future__ import annotations

import ast
import copy
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.context import business_domain_extract as core
from lib.context.business_domain_adapters.base import (
    OPERATION_CONTRACT_VERSION, Source, Unit, declare_operation_observation,
)
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, DomainError, activity_closure, copy_facts, record, validate,
    validate_references,
)
from lib.context.business_domain_synthesis import (
    Synthesis, input_token_estimate, packet_for, wire_schema,
)


CAPABILITIES = {'data_access': 'supported', 'outputs': 'supported'}


def target(kind='table', name='orders', resolution='resolved', reason=None):
    return {'kind': kind, 'name': name, 'resolution': resolution, 'reason': reason}


def binding(name, position, end, value_type='unknown', expression=None):
    return {'name': name, 'value_type': value_type,
            'expression': expression or name, 'position': position, 'end': end,
            'resolution': 'resolved', 'reason': None}


def operation(unit, **values):
    values.setdefault('completion', 'declared')
    values.setdefault('projection_gaps', [])
    values.setdefault('resolution', 'resolved')
    values.setdefault('reason', None)
    return declare_operation_observation(unit, **values)


def fixture_facts(tmp_path, monkeypatch, specifications, two_units=False):
    text = 'read();write();invoke();noop()'
    units = lambda source: ([
        Unit(source, 'entry', 'fixture.entry', 0, 24, 'function',
             anchor_kind='workflow', anchor_resolution='resolved',
             executable_body=True, trace_role='implementation',
             required_relationships=(), required_capabilities=(), valid_terminal=True),
        Unit(source, 'other', 'fixture.other', 24, len(source.text), 'function',
             anchor_kind='workflow', anchor_resolution='resolved',
             executable_body=True, trace_role='implementation',
             required_relationships=(), required_capabilities=(), valid_terminal=True),
    ] if two_units else [
        Unit(source, 'entry', 'fixture.entry', 0, len(source.text), 'function',
             anchor_kind='workflow', anchor_resolution='resolved',
             executable_body=True, trace_role='implementation',
             required_relationships=(), required_capabilities=(), valid_terminal=True),
    ])
    adapter = SimpleNamespace(
        extract=units, bindings=lambda unit: [], resources=lambda unit: [],
        calls=lambda unit: [], observations=lambda unit: [],
        operations=lambda unit: [operation(unit, **item) for item in specifications]
            if unit.name == 'entry' else [],
    )
    descriptor = {'language': 'fixture', 'source_kind': 'source',
                  'capability': {'id': 'fixture', 'version': '1',
                                 'capabilities': CAPABILITIES}}
    monkeypatch.setattr(core, 'descriptor', lambda value: descriptor)
    monkeypatch.setattr(core, 'adapter_for', lambda source: adapter)
    (tmp_path / 'flow.opaque').write_text(text)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    return facts


def all_operations():
    return [
        {'position': 0, 'end': 7, 'kind': 'data_read', 'outcome': 'read()',
         'resource': target(), 'output_bindings': [binding('row', 0, 7)]},
        {'position': 7, 'end': 15, 'kind': 'data_write', 'outcome': 'write()',
         'resource': target(), 'input_bindings': [binding('change', 7, 15)],
         'condition': 'authorized', 'transaction_scope': 'caller_transaction',
         'completion': 'declared', 'resolution': 'unresolved',
         'reason': 'Runtime completion is not established.',
         'projection_gaps': [{'projection': 'completion',
             'code': 'WRITE_COMPLETION_UNRESOLVED',
             'reason': 'Runtime completion is not established.'}]},
        {'position': 15, 'end': 24, 'kind': 'external_action',
         'outcome': 'invoke()', 'resource': target('service', 'billing'),
         'input_bindings': [binding('request', 15, 24)],
         'output_bindings': [binding('response', 15, 24)],
         'protocol': 'http', 'completion': 'declared',
         'resolution': 'unresolved',
         'reason': 'Runtime completion is not established.',
         'projection_gaps': [{'projection': 'completion',
             'code': 'INVOKE_COMPLETION_UNRESOLVED',
             'reason': 'Runtime completion is not established.'}]},
    ]


def test_f08_ac01_one_versioned_contract_projects_into_the_canonical_model(tmp_path, monkeypatch):
    facts = fixture_facts(tmp_path, monkeypatch, all_operations())
    assert OPERATION_CONTRACT_VERSION == 1
    assert 'operations' not in facts
    assert set(facts['edges']) and set(facts['resources']) and set(facts['bindings'])
    targets = {edge['to_ref']['id'] for edge in facts['edges'].values()
               if edge['to_ref'] and edge['to_ref']['kind'] == 'resource'}
    for resource_id in targets:
        operation_evidence = {evidence_id for edge in facts['edges'].values()
            if edge['to_ref'] == {'kind': 'resource', 'id': resource_id}
            for evidence_id in edge['evidence_ids']}
        assert set(facts['resources'][resource_id]['evidence_ids']) == operation_evidence


def test_f08_ac02_each_supported_operation_hydrates_applicable_records(tmp_path, monkeypatch):
    facts = fixture_facts(tmp_path, monkeypatch, all_operations())
    edges = {edge['kind']: edge for edge in facts['edges'].values()
             if edge['kind'] in {'reads_data', 'writes_data', 'invokes_endpoint'}}
    assert set(edges) == {'reads_data', 'writes_data', 'invokes_endpoint'}
    assert all(edge['to_ref'] and edge['binding_ids'] for edge in edges.values())
    assert {effect['kind'] for effect in facts['effects'].values()} == {
        'data_write', 'external_action'}


def test_f08_ac03_operation_edge_kinds_are_canonical(tmp_path, monkeypatch):
    facts = fixture_facts(tmp_path, monkeypatch, all_operations())
    assert {edge['kind'] for edge in facts['edges'].values()} == {
        'reads_data', 'writes_data', 'invokes_endpoint'}


def test_f08_ac04_evidence_overlap_cannot_attach_an_effect_to_an_unreachable_trace(tmp_path, monkeypatch):
    facts = fixture_facts(tmp_path, monkeypatch, [all_operations()[1]], two_units=True)
    effect = next(iter(facts['effects'].values()))
    owning = facts['traces'][effect['trace_ids'][0]]
    other = next(trace for trace in facts['traces'].values() if trace['id'] != owning['id'])
    other['evidence_ids'] = sorted(set(other['evidence_ids']) | set(effect['evidence_ids']))
    validate_references(facts)
    assert effect['trace_ids'] == [owning['id']]
    effect['trace_ids'].append(other['id'])
    with pytest.raises(DomainError, match='operation reachability'):
        validate_references(facts)


def test_f08_ac05_effects_retain_exact_complete_operation_projection(tmp_path, monkeypatch):
    facts = fixture_facts(tmp_path, monkeypatch, all_operations())
    for effect in facts['effects'].values():
        edge = facts['edges'][effect['edge_id']]
        assert effect['origin_ref'] == edge['from_ref']
        assert effect['target'] == edge['to_ref']
        assert set(edge['evidence_ids']) <= set(effect['evidence_ids'])
        assert set(edge['binding_ids']) == set(effect['input_binding_ids']) | set(effect['output_binding_ids'])
        assert effect['completion'] == 'declared'
        assert effect['resolution'] == 'unresolved' and effect['reason']


def test_f08_ac06_activity_closure_is_deterministic_and_provider_cannot_erase_it(tmp_path, monkeypatch):
    facts = fixture_facts(tmp_path, monkeypatch, all_operations())
    model = copy_facts(facts, str(uuid.uuid4()))
    trace = next(iter(model['traces'].values()))
    activity = record('Activity', id='activity:fixture', anchor_ids=[trace['anchor_id']],
                      trace_ids=[trace['id']])
    model['activities'][activity['id']] = activity
    closure = activity_closure(model, activity)
    for field, identifiers in closure.items():
        activity[field] = sorted(identifiers)
    validate_references(model)
    assert activity['effect_ids'] == sorted(model['effects'])
    activity['effect_ids'] = []
    with pytest.raises(DomainError, match='Activity operation closure'):
        validate_references(model)


def test_f08_ac07_unresolved_projection_has_diagnostic_and_partial_trace(tmp_path, monkeypatch):
    reason = 'Runtime destination cannot be proven.'
    facts = fixture_facts(tmp_path, monkeypatch, [{
        'position': 15, 'end': 24, 'kind': 'external_action',
        'outcome': 'invoke()', 'resource': None, 'protocol': 'http',
        'completion': 'declared', 'resolution': 'unresolved', 'reason': reason,
        'projection_gaps': [{'projection': 'target',
            'code': 'OPERATION_TARGET_UNRESOLVED', 'reason': reason}],
    }])
    edge = next(iter(facts['edges'].values()))
    effect = next(iter(facts['effects'].values()))
    assert edge['to_ref'] is None and effect['target'] is None
    assert edge['resolution'] == effect['resolution'] == 'unresolved'
    assert any(warning['code'] == 'OPERATION_TARGET_UNRESOLVED'
               and edge['id'] in warning['subject_ids'] for warning in facts['warnings'])
    assert next(iter(facts['traces'].values()))['resolution'] == 'unresolved'


def test_f08_ac08_semantic_validation_rejects_shape_valid_orphans(tmp_path, monkeypatch):
    facts = fixture_facts(tmp_path, monkeypatch, [all_operations()[1]])
    effect = next(iter(facts['effects'].values()))
    effect['trace_ids'] = []
    validate(facts, 'FactsArtifact')
    with pytest.raises(DomainError, match='operation reachability'):
        validate_references(facts)


def test_f08_ac11_unknown_transaction_state_remains_explicit(tmp_path, monkeypatch):
    reason = 'Transaction boundary is not established.'
    specification = all_operations()[1] | {
        'resolution': 'unresolved', 'reason': reason,
        'transaction_scope': None, 'completion': 'declared',
        'projection_gaps': [{'projection': 'transaction_scope',
            'code': 'TRANSACTION_SCOPE_UNRESOLVED', 'reason': reason}],
    }
    facts = fixture_facts(tmp_path, monkeypatch, [specification])
    effect = next(iter(facts['effects'].values()))
    assert effect['transaction_scope'] is None
    assert effect['completion'] == 'declared'
    assert effect['resolution'] == 'unresolved' and effect['reason'] == reason


def test_f08_ac12_common_hydration_has_no_technology_branch():
    banned = {'java', 'spring', 'typescript', 'tsx', 'react', 'oracle',
              'postgres', 'postgresql', 'plsql', 'sql'}
    for name in ('business_domain_extract.py', 'business_domain_schema.py',
                 'business_domains.py'):
        tree = ast.parse((Path(core.__file__).with_name(name)).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.IfExp, ast.Match)):
                assert not ({value.value.casefold() for value in ast.walk(node)
                             if isinstance(value, ast.Constant)
                             and isinstance(value.value, str)} & banned)


def test_f08_ac13_new_adapter_uses_the_same_normalized_contract():
    source = Source('flow.future', 'future', 'work()', '0' * 64, 'resource:future',
                    adapter_id='future-adapter', adapter_version='7',
                    declared_capabilities=CAPABILITIES)
    unit = Unit(source, 'work', 'future.work', 0, 6, 'function',
                symbol_id='symbol:future')
    value = operation(unit, position=0, end=6, kind='data_read',
                      outcome='work()', resource=target())
    assert value['contract_version'] == OPERATION_CONTRACT_VERSION
    assert value['origin_ref'] == {'kind': 'symbol', 'id': 'symbol:future'}
    assert value['adapter_id'] == 'future-adapter' and value['capability'] == 'data_access'


def test_f08_ac14_structural_hydration_does_not_require_a_provider(tmp_path, monkeypatch):
    facts = fixture_facts(tmp_path, monkeypatch, all_operations())
    validate_references(facts)
    assert facts['edges'] and facts['effects'] and facts['traces']


def test_f08_contract_rejects_loose_unversioned_or_undeclared_operations():
    source = Source('flow.future', 'future', 'work()', '0' * 64, 'resource:future')
    unit = Unit(source, 'work', 'future.work', 0, 6, 'function',
                symbol_id='symbol:future')
    with pytest.raises(ValueError, match='declared capability'):
        operation(unit, position=0, end=6, kind='data_read',
                  outcome='work()', resource=target())


def test_f08_contract_rejects_a_resolved_write_without_transaction_evidence():
    source = Source('flow.future', 'future', 'work()', '0' * 64, 'resource:future',
                    declared_capabilities=CAPABILITIES)
    unit = Unit(source, 'work', 'future.work', 0, 6, 'function',
                symbol_id='symbol:future')
    with pytest.raises(ValueError, match='unresolved completion'):
        operation(unit, position=0, end=6, kind='data_write',
                  outcome='work()', resource=target(), completion='declared')


def test_f08_contract_rejects_resolved_or_ungapped_incomplete_bindings():
    source = Source('flow.future', 'future', 'work()', '0' * 64, 'resource:future',
                    declared_capabilities=CAPABILITIES)
    unit = Unit(source, 'work', 'future.work', 0, 6, 'function',
                symbol_id='symbol:future')
    incomplete = {'name': 'request', 'value_type': 'object',
                  'expression': 'work()', 'position': 0, 'end': 6,
                  'resolution': 'unresolved', 'reason': 'Shape is dynamic.'}
    with pytest.raises(ValueError, match='cannot contain incomplete bindings'):
        operation(unit, position=0, end=6, kind='external_action',
                  outcome='work()', resource=target(kind='endpoint'),
                  input_bindings=[incomplete])
    with pytest.raises(ValueError, match='matching projection gap'):
        operation(unit, position=0, end=6, kind='external_action',
                  outcome='work()', resource=target(kind='endpoint'),
                  input_bindings=[incomplete], resolution='unresolved',
                  reason='Runtime completion is unknown.', projection_gaps=[{
                      'projection': 'completion', 'code': 'completion_unknown',
                      'reason': 'Runtime completion is unknown.'}])


def test_f08_hydrator_rejects_unknown_named_bindings(tmp_path, monkeypatch):
    observed = [{
        'position': 0, 'end': 6, 'kind': 'data_read', 'outcome': 'work()',
        'resource': target(), 'input_binding_names': ['missing'],
    }]
    with pytest.raises(ValueError, match='unknown input binding names'):
        fixture_facts(tmp_path, monkeypatch, observed)


def test_f08_validator_requires_headers_in_effect_and_edge_input_closure(
        tmp_path, monkeypatch):
    facts = fixture_facts(tmp_path, monkeypatch, [all_operations()[2]])
    effect = next(iter(facts['effects'].values()))
    header_id = effect['input_binding_ids'][0]
    effect['header_binding_ids'] = [header_id]
    effect['input_binding_ids'] = []
    with pytest.raises(DomainError, match='included in its input bindings'):
        validate_references(facts)


def test_f08_partial_selected_implementation_still_hydrates_reachable_operations(
        tmp_path, monkeypatch):
    text = 'contract body-read'
    def units(source):
        source.units = [
            Unit(source, 'contract', 'fixture.contract', 0, 8, 'declarative_operation',
                 anchor_kind='workflow', anchor_resolution='resolved',
                 trace_role='contract', required_relationships=('implementation_selection',),
                 required_capabilities=(), valid_terminal=False),
            Unit(source, 'body', 'fixture.body', 9, len(source.text), 'declarative_operation',
                 executable_body=True, trace_role='implementation',
                 required_relationships=(), required_capabilities=(), valid_terminal=False),
        ]
        return source.units
    adapter = SimpleNamespace(
        extract=units, bindings=lambda unit: [], resources=lambda unit: [],
        calls=lambda unit: [], observations=lambda unit: [],
        operations=lambda unit: [operation(unit, position=0, end=len(unit.text),
            kind='data_read', outcome=unit.text, resource=target())]
            if unit.name == 'body' else [],
        relations=lambda source: [{'source': source.units[0], 'target': source.units[1],
            'candidate_targets': [], 'kind': 'selects_implementation',
            'start': 0, 'end': len(source.text), 'resolution': 'resolved',
            'outcome': 'exact', 'reason': None}],
    )
    descriptor = {'language': 'fixture', 'source_kind': 'source',
                  'capability': {'id': 'fixture', 'version': '1',
                                 'capabilities': CAPABILITIES}}
    monkeypatch.setattr(core, 'descriptor', lambda value: descriptor)
    monkeypatch.setattr(core, 'adapter_for', lambda source: adapter)
    (tmp_path / 'flow.opaque').write_text(text)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    trace = next(iter(facts['traces'].values()))
    read = next(edge for edge in facts['edges'].values()
                if edge['kind'] == 'reads_data')
    assert read['id'] in trace['edge_ids']
    assert read['from_ref']['id'] in trace['symbol_ids']
    assert trace['resolution'] == 'unresolved'
    assert any(facts['trace_obligations'][oid]['kind'] == 'implementation_selection'
               and facts['trace_obligations'][oid]['status'] == 'unresolved'
               for oid in trace['obligation_ids'])
    validate_references(facts)


def test_f08_smallest_sql_write_closure_fits_the_runtime_default(tmp_path):
    (tmp_path / 'billing.sql').write_text('''CREATE OR REPLACE PROCEDURE pay(amount IN NUMBER) IS
BEGIN
  INSERT INTO payments VALUES (amount);
END;
''')
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    packet = packet_for(facts, 'activity', list(facts['anchors']))
    provider = SimpleNamespace(model='fixture')
    synthesis = Synthesis(tmp_path, DEFAULTS, provider, record('Limits'))
    tokens = synthesis.estimate_input(
        synthesis.request_for(packet), wire_schema('ActivityPayload', packet))
    canonical_tokens = input_token_estimate(
        synthesis.request_for(packet), wire_schema('ActivityPayload', packet))
    assert tokens < canonical_tokens
    assert tokens <= DEFAULTS['max_request_input_tokens'] == 2_000_000
