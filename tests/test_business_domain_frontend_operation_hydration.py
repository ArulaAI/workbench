"""F-08 frontend operation hydration and PetClinic acceptance."""
from pathlib import Path
import uuid

import pytest

from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, copy_facts, record, validate_references,
)
from lib.context.business_domain_work import whole_graph_scope
from lib.context.business_domains import accept_candidate


PETCLINIC = Path('/private/tmp/speed-domain-petclinic')


def _extract(root, files):
    for name, text in files.items():
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, units = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    return facts, units


@pytest.fixture(scope='module')
def petclinic():
    if not PETCLINIC.is_dir():
        pytest.skip('PetClinic trial repository is unavailable')
    facts, units = Extractor(PETCLINIC, DEFAULTS).extract()
    validate_references(facts)
    return facts, units


def test_registered_event_reaches_imported_wrapper_and_http_operation(tmp_path):
    facts, units = _extract(tmp_path, {
        'api.tsx': """export const send = (target, request) => {
  return fetch(target, request);
};
""",
        'Form.tsx': """import { send } from './api';
function submit(event) {
  event.preventDefault();
  return send('/orders', {method: 'POST'});
}
export default () => <form onSubmit={submit}><button>Send</button></form>;
""",
    })
    effect = next(iter(facts['effects'].values()))
    operation_edge = facts['edges'][effect['edge_id']]
    wrapper = next(unit for unit in units
                   if unit.symbol_id == effect['origin_ref']['id'])
    action = next(anchor for anchor in facts['anchors'].values()
        if any((item.get('registration') or {}).get('kind') == 'action'
               for item in anchor['representations']))
    trace = next(trace for trace in facts['traces'].values()
                 if trace['anchor_id'] == action['id'])

    assert operation_edge['kind'] == 'invokes_endpoint'
    assert effect['id'] in {eid for eid, item in facts['effects'].items()
                            if trace['id'] in item['trace_ids']}
    assert effect['edge_id'] in trace['edge_ids']
    assert effect['input_binding_ids'] and effect['output_binding_ids']
    assert wrapper.symbol_id in trace['symbol_ids']
    assert wrapper.anchor_id is None
    interaction = trace['ui_interaction']
    assert any(set(call['request_binding_ids']) == set(effect['input_binding_ids'])
               and set(call['response_binding_ids']) == set(effect['output_binding_ids'])
               for call in interaction['calls'].values())


def test_literal_constant_template_and_dynamic_http_identities(tmp_path):
    facts, _ = _extract(tmp_path, {'Calls.tsx': """export function calls(ownerId, target) {
  const fixed = url('/api/types');
  fetch('/api/owners');
  fetch(fixed);
  fetch(url(`/api/owners/${ownerId}`));
  fetch(target);
}
"""})
    resources = {item['name']: item for item in facts['resources'].values()
                 if item['kind'] == 'service' and item['evidence_ids']}
    assert resources['/api/owners']['resolution'] == 'resolved'
    assert resources['/api/types']['resolution'] == 'resolved'
    assert resources['/api/owners/{ownerId}']['resolution'] == 'resolved'
    dynamic = next(item for name, item in resources.items()
                   if name.endswith('::target'))
    assert dynamic['resolution'] == 'unresolved' and dynamic['reason']
    effects = list(facts['effects'].values())
    assert len(effects) == 4
    assert all(effect['edge_id'] and effect['input_binding_ids']
               and effect['output_binding_ids'] for effect in effects)
    assert all(any(effect['edge_id'] in diagnostic['subject_ids']
                   for diagnostic in facts['warnings']) for effect in effects)
    assert all(any(diagnostic['code'] == 'HTTP_RESPONSE_MAPPING_UNRESOLVED'
                   and effect['edge_id'] in diagnostic['subject_ids']
                   for diagnostic in facts['warnings']) for effect in effects)


def test_petclinic_all_supported_fetches_have_complete_graph_dispositions(petclinic):
    facts, _ = petclinic
    operations = [edge for edge in facts['edges'].values()
                  if edge['kind'] == 'invokes_endpoint']
    effects = list(facts['effects'].values())

    assert len(operations) == len(effects) == 10
    assert {effect['edge_id'] for effect in effects} == {
        edge['id'] for edge in operations}
    assert all(effect['target'] and effect['input_binding_ids']
               and effect['output_binding_ids'] and effect['trace_ids']
               for effect in effects)
    assert all(any(effect['edge_id'] in diagnostic['subject_ids']
                   for diagnostic in facts['warnings']) for effect in effects)
    assert all(edge['to_ref'] and edge['binding_ids'] and edge['evidence_ids']
               for edge in operations)
    assert all(any(facts['evidence'][eid]['excerpt'].lstrip().startswith('fetch(')
                   for eid in edge['evidence_ids']) for edge in operations)

    # The whole graph supplied to synthesis retains every operation closure.
    model = copy_facts(facts, str(uuid.uuid4()))
    context = whole_graph_scope(model)['context']
    for effect in effects:
        for trace_id in effect['trace_ids']:
            assert effect['id'] in context['effects']
            assert effect['edge_id'] in context['edges']
            assert set(effect['input_binding_ids'] + effect['output_binding_ids']) \
                <= set(context['bindings'])


def test_petclinic_route_lifecycle_and_activity_closure_are_hydrated(petclinic):
    facts, _ = petclinic
    route_symbols = {anchor['symbol_id'] for anchor in facts['anchors'].values()
        if any((item.get('registration') or {}).get('kind') == 'route'
               for item in anchor['representations'])}
    lifecycle_edges = [edge for edge in facts['edges'].values()
        if edge['kind'] == 'composes' and edge['to_ref']
        and edge['from_ref']['id'] in route_symbols]
    assert lifecycle_edges
    assert all(edge['resolution'] == 'resolved' and len(edge['evidence_ids']) == 2
               for edge in lifecycle_edges)

    called_symbols = {edge['to_ref']['id'] for edge in facts['edges'].values()
        if edge['kind'] == 'calls' and edge['to_ref']
        and edge['to_ref']['kind'] == 'symbol'}
    wrapper_effect = next(effect for effect in facts['effects'].values()
        if effect['origin_ref']['id'] in called_symbols
        and any(trace['id'] in effect['trace_ids'] and trace['ui_interaction']
                and trace['ui_interaction']['calls']
                for trace in facts['traces'].values()))
    trace = next(trace for trace in facts['traces'].values()
        if trace['id'] in wrapper_effect['trace_ids'] and trace['ui_interaction']
        and trace['ui_interaction']['calls'])
    model = copy_facts(facts, str(uuid.uuid4()))
    graph = whole_graph_scope(model)
    evidence_ids = sorted(graph['context']['evidence'])
    activity = record('Activity', id='activity:frontend-operation',
        name='Frontend operation', description='Evidenced frontend operation',
        anchor_ids=[trace['anchor_id']], trace_ids=[trace['id']],
        evidence_ids=evidence_ids, claim_ids=['claim:frontend-operation'],
        support='partial')
    claim = record('Claim', id='claim:frontend-operation',
        subject_id=activity['id'], text=activity['description'], kind='behavior',
        evidence_ids=evidence_ids, trace_ids=[trace['id']],
        semantic_review='uncertain')
    payload = record('CandidatePayload', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'],
        activities={activity['id']: activity}, claims={claim['id']: claim},
        dispositions=[record('ScopeDisposition',
            id=f'disposition:frontend-{index}', subject_kind='anchor',
            subject_id=anchor_id,
            status=('represented' if anchor_id == trace['anchor_id'] else 'excluded'),
            activity_ids=([activity['id']] if anchor_id == trace['anchor_id'] else []),
            reason=(None if anchor_id == trace['anchor_id'] else
                    'Outside the activity under test.'),
            evidence_ids=([] if anchor_id == trace['anchor_id'] else evidence_ids))
            for index, anchor_id in enumerate(graph['canonical_anchor_ids'])])
    accept_candidate(model, graph, payload)
    accepted = model['activities'][activity['id']]

    assert wrapper_effect['id'] in accepted['effect_ids']
    assert set(wrapper_effect['input_binding_ids']) <= set(
        accepted['input_binding_ids'])
    assert set(wrapper_effect['output_binding_ids']) <= set(
        accepted['output_binding_ids'])
    validate_references(model)
