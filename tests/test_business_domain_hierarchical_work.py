import copy
import math
import uuid

from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, DomainError, canonical, copy_facts, digest, identifier, limits,
    record,
)
from lib.context.business_domain_synthesis import (
    Synthesis, input_token_estimate, packet_for, wire_schema,
    _reference_manifest,
)
from lib.context.business_domain_work import (
    ValidatedActivityChild, plan_activity_scopes, reconciliation_packet,
)
from lib.context.business_domains import accept_activity_child, discover, paths
from tests.test_business_domain_pipeline import Provider


def chain(root, length=4):
    calls = ["@app.post('/orders')", 'def node_0():', '    return node_1()']
    for index in range(1, length):
        calls.extend((f'def node_{index}():',
                      f'    return node_{index + 1}()' if index + 1 < length
                      else '    return 1'))
    (root / 'service.py').write_text('\n'.join(calls) + '\n')


def segmented(model):
    def fits(packet):
        return any(obligation['kind'] == 'execution_segment'
                   for obligation in packet['context'].get(
                       'trace_obligations', {}).values())
    return plan_activity_scopes(model, model['anchors'], packet_for, fits)


def fragment(packet):
    evidence = sorted(packet['context']['evidence'])
    activity = record('Activity', id='activity:fragment', name='Fragment',
                      description='Validated child fragment',
                      anchor_ids=packet['anchor_ids'],
                      trace_ids=sorted(packet['context']['traces']),
                      evidence_ids=evidence, claim_ids=['claim:fragment'],
                      support='partial')
    claim = record('Claim', id='claim:fragment', subject_id=activity['id'],
                   text=activity['description'], kind='behavior',
                   evidence_ids=evidence, trace_ids=activity['trace_ids'],
                   semantic_review='uncertain')
    return record('ActivityPayload', activities={activity['id']: activity},
                  claims={claim['id']: claim})


def test_whole_graph_is_preferred_and_bundles_are_canonical(tmp_path):
    (tmp_path / 'service.py').write_text('\n'.join(
        f"@app.post('/orders/{index}')\ndef create_{index}():\n    return {index}"
        for index in range(3)))
    model, _ = Extractor(tmp_path, DEFAULTS).extract()
    anchors = sorted(model['anchors'])
    whole = plan_activity_scopes(model, reversed(anchors), packet_for,
                                 lambda packet: True)
    assert len(whole) == 1 and whole[0].strategy == 'whole_graph'
    assert whole[0].packet['anchor_ids'] == anchors
    bundles = plan_activity_scopes(
        model, reversed(anchors), packet_for,
        lambda packet: len(packet['anchor_ids']) <= 2)
    assert [scope.strategy for scope in bundles] == [
        'entrypoint_bundle', 'entrypoint_bundle']
    assert [scope.packet['anchor_ids'] for scope in bundles] == [
        anchors[:2], anchors[2:]]


def test_compact_preflight_avoids_canonical_size_partitioning(tmp_path):
    import tiktoken

    (tmp_path / 'service.py').write_text('\n'.join(
        f"@app.post('/orders/{index}')\ndef create_{index}():\n    return {index}"
        for index in range(8)))
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    model = copy_facts(facts, str(uuid.uuid4()))
    anchors = sorted(model['anchors'])

    uncapped = Synthesis(tmp_path, DEFAULTS, Provider(), limits(DEFAULTS))
    whole = packet_for(model, 'activity', anchors)
    request = uncapped.request_for(whole)
    schema = wire_schema('ActivityPayload', whole)
    encoded = canonical({'request':request, 'output_schema':schema}).decode('utf-8')
    base = len(tiktoken.get_encoding('o200k_base').encode(
        encoded, disallowed_special=()))
    former_estimate = math.ceil(base * 1.15) + 512
    assert input_token_estimate(request, schema) > former_estimate
    projected_estimate = uncapped.estimate_input(request, schema)
    assert projected_estimate + 2000 <= former_estimate

    provider = Provider()
    provider.provider_context_tokens = former_estimate
    provider.provider_max_output_tokens = 1000
    synthesis = Synthesis(tmp_path, DEFAULTS, provider, limits(DEFAULTS))
    scopes = synthesis.activity_work(model, anchors)
    assert len(scopes) == 1
    assert scopes[0].strategy == 'whole_graph'
    assert [anchor for scope in scopes for anchor in scope.packet['anchor_ids']] == anchors


def test_oversized_singleton_splits_only_at_stable_typed_edges_with_closure(tmp_path):
    chain(tmp_path)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    model = copy_facts(facts, str(uuid.uuid4()))
    scopes = segmented(model)
    again = segmented(model)
    assert len(scopes) > 1
    assert [(scope.id, scope.cut_edge_ids) for scope in scopes] == [
        (scope.id, scope.cut_edge_ids) for scope in again]
    original_edges = {edge_id for trace in model['traces'].values()
                      for edge_id in trace['edge_ids']}
    reached_edges = set()
    for scope in scopes:
        assert scope.strategy == 'execution_segment' and scope.cut_edge_ids
        context = scope.packet['context']
        reached_edges.update(context['edges'])
        for cut_id in scope.cut_edge_ids:
            edge = context['edges'][cut_id]
            assert edge['from_ref']['id'] in context['symbols']
            assert edge['to_ref']['id'] in context['symbols']
            assert set(edge['evidence_ids']) <= set(context['evidence'])
            obligations = [item for item in context['trace_obligations'].values()
                           if item['kind'] == 'execution_segment'
                           and item['edge_id'] == cut_id]
            assert obligations and all(
                set(item['evidence_ids']) <= set(context['evidence'])
                for item in obligations)
    assert reached_edges == original_edges


def test_multitrace_segments_never_cross_attach_obligations(tmp_path):
    chain(tmp_path)
    model, _ = Extractor(tmp_path, DEFAULTS).extract()
    original = next(iter(model['traces'].values()))
    duplicate = copy.deepcopy(original)
    duplicate['id'] = identifier('trace', original['id'], 'duplicate')
    duplicate_obligations = []
    for obligation_id in original['obligation_ids']:
        cloned = copy.deepcopy(model['trace_obligations'][obligation_id])
        cloned['id'] = identifier('trace_obligation', duplicate['id'], obligation_id)
        cloned['trace_id'] = duplicate['id']
        model['trace_obligations'][cloned['id']] = cloned
        duplicate_obligations.append(cloned['id'])
    duplicate['obligation_ids'] = duplicate_obligations
    model['traces'][duplicate['id']] = duplicate
    for scope in segmented(model):
        for trace in scope.packet['context']['traces'].values():
            assert all(scope.packet['context']['trace_obligations'][oid]['trace_id']
                       == trace['id'] for oid in trace['obligation_ids'])


def test_segment_children_reconcile_through_compact_root_before_publication(
        tmp_path, monkeypatch):
    chain(tmp_path)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    model = copy_facts(facts, str(uuid.uuid4()))
    scopes = segmented(model)
    payloads = [fragment(scope.packet) for scope in scopes]
    for scope, payload in zip(scopes, payloads):
        accept_activity_child(copy.deepcopy(model), scope.packet, payload)
    children = [ValidatedActivityChild(scope.id, scope.strategy,
                scope.cut_edge_ids, payload)
                for scope, payload in zip(scopes, payloads)]
    root = reconciliation_packet(model, children, packet_for, _reference_manifest)
    reordered = reconciliation_packet(
        model, reversed(children), packet_for, _reference_manifest)
    full = packet_for(model, 'activity', sorted(model['anchors']))
    assert len(canonical(root)) < len(canonical(full))
    assert root['context']['activities'] and root['context']['record_refs']
    assert len(root['context']['evidence']) == 1
    assert canonical(root) == canonical(reordered)
    coverage = [claim for claim in root['context']['claims'].values()
                if claim['kind'] == 'coverage_manifest']
    assert {claim['subject_id'] for claim in coverage} == {
        child.scope_id for child in children}
    assert all('typed cut edges:' in claim['text'] for claim in coverage)

    calls = []
    def force_hierarchy(self, packet):
        if packet['context']['activities']:
            calls.append('reconciliation')
            return True
        return any(obligation['kind'] == 'execution_segment'
                   for obligation in packet['context'].get(
                       'trace_obligations', {}).values())
    monkeypatch.setattr(Synthesis, '_activity_fits', force_hierarchy)

    class ReconciliationProvider(Provider):
        def generate(self, request, schema, *args):
            value, usage = super().generate(request, schema, *args)
            packet = request['packet']
            if packet['stage'] == 'activity' and packet['context']['activities']:
                calls.append('provider_reconciliation')
                value['activities'][0]['trace_ids'] = sorted({
                    trace_id for activity in packet['context']['activities'].values()
                    for trace_id in activity['trace_ids']})
                value['claims'][0]['trace_ids'] = value['activities'][0]['trace_ids']
            return value, usage

    published, status = discover(tmp_path, provider=ReconciliationProvider())
    assert published and status['phase'] == 'partial'
    assert status['execution_mode'] == 'hierarchical'
    assert status['root_reconciled'] is True and status['current_scope_id'] is None
    assert calls.count('reconciliation') == 1
    assert calls.count('provider_reconciliation') == 1


def test_child_validation_rejects_cross_segment_operation_references(tmp_path):
    chain(tmp_path)
    model, _ = Extractor(tmp_path, DEFAULTS).extract()
    scopes = segmented(model)
    packet = scopes[0].packet
    payload = fragment(packet)
    next(iter(payload['activities'].values()))['effect_ids'] = ['effect:outside']
    try:
        accept_activity_child(copy.deepcopy(model), packet, payload)
    except Exception as exc:
        assert getattr(exc, 'code', None) == 'INVALID_REFERENCE'
    else:
        raise AssertionError('Cross-segment effect reference was accepted')


def test_terminal_provider_failure_during_root_reconciliation_preserves_publication(
        tmp_path, monkeypatch):
    (tmp_path / 'service.py').write_text(
        "@app.post('/orders')\ndef create():\n    return 1\n")
    previous, _ = discover(tmp_path, provider=Provider())
    published = paths(tmp_path)['model'].read_bytes()
    chain(tmp_path)

    def force_hierarchy(self, packet):
        if packet['context']['activities']:
            return True
        return any(obligation['kind'] == 'execution_segment'
                   for obligation in packet['context'].get(
                       'trace_obligations', {}).values())
    monkeypatch.setattr(Synthesis, '_activity_fits', force_hierarchy)

    class FailReconciliation(Provider):
        def generate(self, request, schema, *args):
            if (request['packet']['stage'] == 'activity'
                    and request['packet']['context']['activities']):
                raise DomainError('PROVIDER_CAPABILITY_UNAVAILABLE',
                                  'Reconciliation provider is unavailable')
            return super().generate(request, schema, *args)

    preserved, status = discover(tmp_path, provider=FailReconciliation())
    assert preserved == previous
    assert paths(tmp_path)['model'].read_bytes() == published
    assert status['phase'] == 'unavailable'
    assert status['error']['code'] == 'PROVIDER_UNAVAILABLE'
    assert status['execution_mode'] == 'hierarchical'
    assert status['root_reconciled'] is False and status['current_scope_id'] is None


def test_oversized_root_reconciliation_rolls_children_up_recursively(tmp_path):
    chain(tmp_path)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    model = copy_facts(facts, str(uuid.uuid4()))
    scopes = segmented(model)
    payloads = [fragment(scope.packet) for scope in scopes]
    extra = copy.deepcopy(payloads[0])
    next(iter(extra['activities'].values()))['description'] = 'Distinct child summary'
    payloads.append(extra)
    synthesis = Synthesis(tmp_path, DEFAULTS, Provider(), record('Limits'))
    synthesis._activity_fits = lambda packet: (
        0 < len(packet['context']['activities']) <= 2)
    dispatched = []
    def run(packet, validator):
        dispatched.append(sorted(packet['context']['activities']))
        trace_ids = sorted({trace_id for activity in packet['context']['activities'].values()
                            for trace_id in activity['trace_ids']})
        evidence_ids = sorted(packet['context']['evidence'])
        activity_id = identifier('activity', packet['anchor_ids'],
                                 sorted(packet['context']['activities']))
        claim_id = identifier('claim', activity_id)
        activity = record('Activity', id=activity_id, name='Rolled activity',
                          description='Recursively reconciled activity',
                          anchor_ids=packet['anchor_ids'], trace_ids=trace_ids,
                          evidence_ids=evidence_ids, claim_ids=[claim_id],
                          support='partial')
        claim = record('Claim', id=claim_id, subject_id=activity_id,
                       text=activity['description'], kind='behavior',
                       evidence_ids=evidence_ids, trace_ids=trace_ids,
                       semantic_review='uncertain')
        payload = record('ActivityPayload', activities={activity_id: activity},
                         claims={claim_id: claim})
        validator(payload)
        return payload
    synthesis.run = run
    _, _, root = synthesis.reconcile_activity_children(
        model, payloads, lambda packet, payload:
        accept_activity_child(copy.deepcopy(model), packet, payload))
    assert len(dispatched) >= 3
    assert len(root['activities']) == 1


def test_atomic_child_summary_reports_its_exact_stable_scope(tmp_path):
    chain(tmp_path)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    model = copy_facts(facts, str(uuid.uuid4()))
    payload = fragment(segmented(model)[0].packet)
    synthesis = Synthesis(tmp_path, DEFAULTS, Provider(), record('Limits'))
    synthesis._activity_fits = lambda packet: False
    try:
        synthesis.reconcile_activity_children(
            model, [payload], lambda packet, value: None)
    except DomainError as exc:
        assert exc.code == 'OVERSIZED_ATOMIC_RECORD'
        assert exc.field == identifier('scope', 'validated_child', digest(payload))
    else:
        raise AssertionError('Oversized root reconciliation was dispatched')
