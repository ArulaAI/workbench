"""Focused trace-obligation and operation-hydration regressions."""
from types import SimpleNamespace

import pytest

from lib.context import business_domain_extract as core
from lib.context.business_domain_adapters.base import Unit, declare_operation_observation
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, DomainError, activity_closure, information_use_closure, record,
    validate_references,
)


def extract_operation(tmp_path, monkeypatch, operation):
    def normalized(unit):
        value = dict(operation)
        resource = value.get('resource')
        if resource:
            resource = dict(resource)
            resource.setdefault('resolution', value['resolution'])
            resource.setdefault('reason', value['reason'])
            value['resource'] = resource
        value.setdefault('projection_gaps', [] if value['resolution'] == 'resolved' else [{
            'projection': 'target', 'code': 'FIXTURE_TARGET_UNRESOLVED',
            'reason': value['reason']}])
        return declare_operation_observation(unit, **value)
    adapter = SimpleNamespace(
        extract=lambda source: [Unit(source, 'entry', 'entry', 0, len(source.text),
            'function', anchor_kind='workflow', anchor_resolution='resolved', executable_body=True,
            trace_role='implementation', required_relationships=(),
            required_capabilities=(), valid_terminal=True)],
        bindings=lambda unit: [], resources=lambda unit: [], calls=lambda unit: [],
        observations=lambda unit: [], operations=lambda unit: [normalized(unit)],
    )
    monkeypatch.setattr(core, 'descriptor', lambda path: {'language':'fixture','source_kind':'source',
        'capability': {'id':'fixture', 'version':'1', 'capabilities': {
            'data_access':'supported', 'outputs':'supported'}}})
    monkeypatch.setattr(core, 'adapter_for', lambda source: adapter)
    (tmp_path/'flow.opaque').write_text('operation()')
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    return facts


def test_unresolved_data_operation_has_typed_target_obligation(tmp_path, monkeypatch):
    facts = extract_operation(tmp_path, monkeypatch, {
        'position':0, 'end':11, 'kind':'data_read', 'outcome':'operation()',
        'resource':{'kind':'table','name':'orders'},
        'resolution':'unresolved', 'reason':'Table visibility is unresolved.',
    })
    trace = next(iter(facts['traces'].values()))
    edge = next(iter(facts['edges'].values()))
    obligations = [facts['trace_obligations'][oid] for oid in trace['obligation_ids']]
    target = next(item for item in obligations if item['edge_id'] == edge['id'])
    assert target['kind'] == 'data_target' and target['status'] == 'unresolved'


def test_external_operation_stops_at_explicit_boundary(tmp_path, monkeypatch):
    facts = extract_operation(tmp_path, monkeypatch, {
        'position':0, 'end':11, 'kind':'external_action', 'outcome':'operation()',
        'resource':{'kind':'service','name':'https://billing.example/pay',
                    'resolution':'resolved','reason':None},
        'completion':'declared', 'resolution':'unresolved',
        'reason':'Runtime completion is not established.',
        'projection_gaps':[{'projection':'completion',
            'code':'FIXTURE_COMPLETION_UNRESOLVED',
            'reason':'Runtime completion is not established.'}],
    })
    trace = next(iter(facts['traces'].values()))
    edge = next(iter(facts['edges'].values()))
    obligations = [facts['trace_obligations'][oid] for oid in trace['obligation_ids']]
    boundary = next(item for item in obligations if item['edge_id'] == edge['id'])
    assert boundary['kind'] == 'external_boundary' and boundary['status'] == 'external'
    assert boundary['candidate_target_ids'] == [edge['to_ref']['id']]
    assert trace['resolution'] == 'unresolved' and 'external_boundary' in trace['stop_reasons']


def test_operation_obligations_are_complete_and_not_orphaned(tmp_path, monkeypatch):
    facts = extract_operation(tmp_path, monkeypatch, {
        'position':0, 'end':11, 'kind':'data_read', 'outcome':'operation()',
        'resource':{'kind':'table','name':'orders'},
        'completion':'declared', 'resolution':'resolved', 'reason':None,
    })
    trace = next(iter(facts['traces'].values()))
    operation_id = next(iter(facts['edges']))
    obligation_id = next(oid for oid in trace['obligation_ids']
                         if facts['trace_obligations'][oid]['edge_id'] == operation_id)
    trace['obligation_ids'].remove(obligation_id)
    facts['trace_obligations'].pop(obligation_id)
    with pytest.raises(DomainError, match='typed obligation'):
        validate_references(facts)

    facts = extract_operation(tmp_path, monkeypatch, {
        'position':0, 'end':11, 'kind':'data_read', 'outcome':'operation()',
        'resource':{'kind':'table','name':'orders'},
        'completion':'declared', 'resolution':'resolved', 'reason':None,
    })
    trace = next(iter(facts['traces'].values()))
    existing = facts['trace_obligations'][trace['obligation_ids'][0]]
    orphan = record('TraceObligation', **{**existing, 'id':'trace_obligation:orphan'})
    facts['trace_obligations'][orphan['id']] = orphan
    with pytest.raises(DomainError, match='Every trace obligation'):
        validate_references(facts)


def test_information_use_cannot_resolve_over_unresolved_read(tmp_path, monkeypatch):
    model = extract_operation(tmp_path, monkeypatch, {
        'position':0, 'end':11, 'kind':'data_read', 'outcome':'operation()',
        'resource':{'kind':'table','name':'orders'},
        'resolution':'unresolved', 'reason':'Table visibility is unresolved.',
    })
    model.update({key:{} for key in ('activities','concepts','information_uses')})
    trace = next(iter(model['traces'].values()))
    edge = next(iter(model['edges'].values()))
    concept = record('Concept', id='concept:orders', name='Orders')
    activity = record('Activity', id='activity:orders', anchor_ids=[trace['anchor_id']],
        trace_ids=[trace['id']], concept_ids=[concept['id']])
    model['concepts'][concept['id']] = concept
    model['activities'][activity['id']] = activity
    use = record('InformationUse', id='information_use:orders', activity_id=activity['id'],
        concept_id=concept['id'], resource_ids=[edge['to_ref']['id']], access='reads',
        resolution='resolved', reason=None)
    model['information_uses'][use['id']] = use
    closure = information_use_closure(model, use)
    for field in ('trace_ids', 'binding_ids', 'effect_ids', 'evidence_ids'):
        use[field] = sorted(closure[field])
    for field, values in activity_closure(model, activity).items():
        activity[field] = sorted(values)
    with pytest.raises(DomainError, match='resolved operation facts'):
        validate_references(model)
