"""Focused repair packets: a repair round sends only the graph its findings need."""
import copy

from lib.context.business_domain_schema import record, required_scope_subjects, validate
from lib.context.business_domain_synthesis import (
    COMPLETE_PACKET_INSTRUCTIONS, FOCUSED_PACKET_INSTRUCTIONS, ProviderProjection, wire_schema)
from lib.context.business_domain_work import repair_focus, restore_unseen_incorporations
from tests.test_business_domain_candidate_protocol import (
    ProtocolProvider, graph_scope_with_evidence, synthesis, validate_candidate)


def evidence_graph():
    """52 anchors, one trace and 60 evidence records, of which the candidate cites one."""
    return graph_scope_with_evidence(60)


def finding(subject_ids, evidence_ids=(), severity='blocking'):
    return record('VerificationFinding', id='verification_finding:test',
                  category='incorrect_merge', severity=severity, message='Split it.',
                  subject_ids=list(subject_ids), evidence_ids=list(evidence_ids))


def report(*findings):
    return {'findings': list(findings)}


def failing_report(graph, subject_ids):
    return record('VerificationReport', scope_id=graph['scope_id'],
                  input_fingerprint=graph['input_fingerprint'], verdict='fail',
                  findings=[finding(subject_ids)],
                  checked_subject_ids=sorted(required_scope_subjects(graph)))


def deterministic(subject_ids):
    return record('ValidationFinding', code='INVALID_COVERAGE', severity='error',
                  message='Cover it.', subject_ids=list(subject_ids), evidence_ids=[])


def focus_for(graph, candidate, findings=(), verification=None):
    return repair_focus(graph, candidate, list(findings), verification)


def candidate_for(graph):
    from tests.test_business_domain_candidate_protocol import one_activity_candidate
    return one_activity_candidate(graph)


def reference_graph():
    """A reconciliation-style context: two activities with their own rules and evidence."""
    graph = evidence_graph()
    context = graph['context']
    anchor = graph['canonical_anchor_ids'][0]
    for name, evidence_id in (('a', 'ev:fixture-001'), ('b', 'ev:fixture-002')):
        context['rules'][f'rule:{name}'] = record(
            'Rule', id=f'rule:{name}', name=f'Rule {name}', description=f'Rule {name}.',
            activity_ids=[f'activity:{name}'], evidence_ids=[evidence_id],
            basis=['source_observed'], support='partial')
        context['claims'][f'claim:{name}'] = record(
            'Claim', id=f'claim:{name}', subject_id=f'activity:{name}', text=f'Does {name}.',
            kind='behavior', evidence_ids=[evidence_id], trace_ids=['trace:fixture'],
            semantic_review='uncertain')
        context['activities'][f'activity:{name}'] = record(
            'Activity', id=f'activity:{name}', name=f'Activity {name}',
            description=f'Activity {name}.', anchor_ids=[anchor], trace_ids=['trace:fixture'],
            rule_ids=[f'rule:{name}'], claim_ids=[f'claim:{name}'], evidence_ids=[evidence_id],
            implementation_status='implementation_unresolved', support='partial')
    context['domains']['domain:all'] = record(
        'Domain', id='domain:all', name='All', summary='Everything.',
        boundary_rationale='One fixture domain.', evidence_ids=['ev:fixture-003'],
        activity_memberships=[
            record('ActivityMembership', activity_id=f'activity:{name}', role='primary',
                   claim_ids=[f'claim:{name}'])
            for name in ('a', 'b')])
    validate(graph, 'GraphScope')
    return graph


# Choosing the focus

def test_focus_keeps_what_the_named_record_rests_on_and_leaves_out_the_rest():
    graph = reference_graph()
    focus = set(focus_for(graph, candidate_for(graph), [finding(['activity:a'])]))
    assert {'activity:a', 'rule:a', 'claim:a', 'ev:fixture-001'} <= focus
    assert not {'activity:b', 'rule:b', 'claim:b', 'ev:fixture-002'} & focus
    # Groupings are always shown, but not the evidence behind them.
    assert 'domain:all' in focus and 'ev:fixture-003' not in focus
    assert set(graph['canonical_anchor_ids']) <= focus


def test_focus_keeps_whole_traces_of_named_anchors():
    graph = evidence_graph()
    anchor = graph['canonical_anchor_ids'][0]
    focus = set(focus_for(graph, candidate_for(graph), [finding([anchor])]))
    assert {'trace:fixture', 'resource:fixture', 'ev:fixture'} <= focus
    assert 'ev:fixture-001' not in focus


def test_focus_keeps_evidence_findings_cite():
    graph = reference_graph()
    focus = set(focus_for(graph, candidate_for(graph),
                          [finding(['activity:a'], ['ev:fixture-040'])]))
    assert 'ev:fixture-040' in focus


def test_focus_follows_named_candidate_records_into_the_graph():
    graph = evidence_graph()
    candidate = candidate_for(graph)
    focus = set(focus_for(graph, candidate, [finding(['activity:provider-one'])]))
    assert {'trace:fixture', 'ev:fixture'} <= focus
    assert 'ev:fixture-001' not in focus


def test_focus_falls_back_to_the_whole_scope_when_it_is_not_safe():
    graph = reference_graph()
    candidate = candidate_for(graph)
    # A blocking finding with no subject could be about anything.
    assert focus_for(graph, candidate, [finding([])]) is None
    # A subject SPEED can't find, such as a provider-temporary ID.
    assert focus_for(graph, candidate, [finding(['activity:_ref:3'])]) is None
    # A warning without subjects doesn't stop the focus.
    assert focus_for(graph, candidate, [finding(['activity:a']),
                                        finding([], severity='warning')]) is not None


def test_focus_falls_back_when_it_would_keep_most_of_the_scope():
    graph = reference_graph()
    every_record = sorted(record_id for collection, records in graph['context'].items()
                          if isinstance(records, dict) for record_id in records)
    assert focus_for(graph, candidate_for(graph), [finding(every_record)]) is None


def test_focus_reads_findings_from_the_verification_report_too():
    graph = reference_graph()
    focus = set(focus_for(graph, candidate_for(graph), (), report(finding(['activity:b']))))
    assert 'rule:b' in focus and 'rule:a' not in focus


def test_focus_is_deterministic():
    graph = reference_graph()
    candidate = candidate_for(graph)
    first = focus_for(graph, candidate, [finding(['activity:a', 'activity:b'])])
    second = focus_for(copy.deepcopy(graph), copy.deepcopy(candidate),
                       [finding(['activity:b', 'activity:a'])])
    assert first == second == sorted(first)


# Projecting a focused packet

def test_record_ref_hashes_stay_local_and_round_trip():
    graph = reference_graph()
    graph['context']['record_refs']['rule:elsewhere'] = {
        'id': 'rule:elsewhere', 'collection': 'rules', 'content_hash': 'f' * 64}
    graph['context']['activities']['activity:a']['rule_ids'].append('rule:elsewhere')
    projection = ProviderProjection(graph)
    assert 'f' * 64 not in projection.wire_packet['strings']
    assert projection.decode_packet(projection.wire_packet) == graph


def test_focused_projection_round_trips_and_keeps_aliases_and_schema():
    graph = reference_graph()
    candidate = candidate_for(graph)
    focus = focus_for(graph, candidate, [finding(['activity:a'])])
    whole = ProviderProjection(graph)
    narrow = ProviderProjection(graph, focus=focus)
    assert narrow.aliases == whole.aliases
    schema = wire_schema('RepairPayload', graph)
    assert narrow.project_schema(schema) == whole.project_schema(schema)
    assert narrow.decode_packet(narrow.wire_packet) == graph
    assert narrow.omitted_records > 0
    strings = narrow.wire_packet['strings']
    assert 'Fixture business behavior 1.' in strings
    assert 'Fixture business behavior 2.' not in strings
    assert len(str(narrow.wire_packet)) < len(str(whole.wire_packet))


def test_focused_projection_lists_left_out_records_that_are_still_referenced():
    graph = reference_graph()
    candidate = candidate_for(graph)
    focus = focus_for(graph, candidate, [finding(['activity:a'])])
    # The domain is shown and names activity:b, which is left out.
    narrow = ProviderProjection(graph, focus=focus, referenced=['rule:b'])
    wire = narrow._rewrite(narrow._unpack(narrow.wire_packet), narrow.canonical_ids)
    references = wire['context']['record_refs']
    assert references['activity:b'] == {'id': 'activity:b', 'collection': 'activities'}
    assert references['rule:b'] == {'id': 'rule:b', 'collection': 'rules'}
    assert 'activity:b' not in wire['context']['activities']
    # A left-out record nothing mentions isn't listed.
    assert 'ev:fixture-050' not in references
    assert 'ev:fixture-050' not in wire['context']['evidence']


# Requests and the repair chain

def test_focused_request_carries_the_focus_and_sends_focused_instructions(tmp_path):
    graph = reference_graph()
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    candidate = candidate_for(graph)
    findings = [deterministic(['activity:a'])]
    verification = failing_report(graph, ['activity:a'])
    focus = focus_for(graph, candidate, findings, verification)
    request = runner.request_for('repair', graph, candidate, findings, verification,
                                 focus=focus)
    validate(request, 'SemanticRequest')
    assert request['graph'] == graph
    assert request['provider_focus'] == {'version': 1, 'record_ids': focus}
    projected, _, _ = runner.project_exchange(request, wire_schema('RepairPayload', graph))
    assert 'provider_focus' not in projected
    assert projected['provider_projection']['instructions'].endswith(FOCUSED_PACKET_INSTRUCTIONS)
    plain = runner.request_for('repair', graph, candidate, findings, verification)
    assert 'provider_focus' not in plain
    projected, _, _ = runner.project_exchange(plain, wire_schema('RepairPayload', graph))
    assert projected['provider_projection']['instructions'].endswith(COMPLETE_PACKET_INSTRUCTIONS)


def test_focus_is_part_of_the_request_key(tmp_path):
    graph = reference_graph()
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    candidate = candidate_for(graph)
    findings = [deterministic(['activity:a'])]
    verification = failing_report(graph, ['activity:a'])
    focus = focus_for(graph, candidate, findings, verification)
    focused = runner.request_for('repair', graph, candidate, findings, verification,
                                 focus=focus)
    again = runner.request_for('repair', graph, candidate, findings, verification,
                               focus=list(focus))
    whole = runner.request_for('repair', graph, candidate, findings, verification)
    assert runner._request_key(focused) == runner._request_key(again)
    assert runner._request_key(focused) != runner._request_key(whole)


def run_chain(tmp_path, monkeypatch, focused):
    if not focused:
        monkeypatch.setenv('SPEED_DISCOVER_FOCUSED_REPAIR', '0')
    graph = evidence_graph()
    provider = ProtocolProvider(graph)
    result = synthesis(tmp_path, provider).run(
        graph, lambda value: validate_candidate(graph, value))
    return provider, result


def test_repair_chain_sends_a_focused_repair_with_the_same_result(tmp_path, monkeypatch):
    provider, result = run_chain(tmp_path/'focused', monkeypatch, focused=True)
    assert [request['operation'] for request in provider.requests] == [
        'synthesize', 'verify', 'repair', 'verify']
    repair = provider.requests[2]
    focus = set(repair['provider_focus']['record_ids'])
    assert 'trace:fixture' in focus and 'ev:fixture-001' not in focus
    # Verification still judges the whole scope.
    assert 'provider_focus' not in provider.requests[3]
    whole_provider, whole_result = run_chain(tmp_path/'whole', monkeypatch, focused=False)
    assert 'provider_focus' not in whole_provider.requests[2]
    assert result == whole_result


def test_focused_repair_reuses_the_cache_on_the_next_run(tmp_path, monkeypatch):
    first, result = run_chain(tmp_path, monkeypatch, focused=True)
    second, again = run_chain(tmp_path, monkeypatch, focused=True)
    assert again == result
    assert second.requests == []


def test_switching_focus_off_sends_the_whole_scope(tmp_path, monkeypatch):
    provider, _ = run_chain(tmp_path, monkeypatch, focused=False)
    assert all('provider_focus' not in request for request in provider.requests)


# Reconciliation safety net

def child_disposition(subject_id, incorporated):
    return {'id': f'disposition:{subject_id}', 'subject_kind': 'child_scope',
            'subject_id': subject_id, 'status': 'represented',
            'incorporated_record_ids': list(incorporated), 'activity_ids': []}


def compact(*dispositions, **collections):
    candidate = {'dispositions': list(dispositions), 'activities': {}, 'rules': {}}
    candidate.update(collections)
    return candidate


def test_records_a_focused_repair_could_not_see_are_kept():
    previous = compact(child_disposition('scope:a', ['activity:seen', 'activity:unseen']))
    repaired = compact(child_disposition('scope:a', []))
    restored, ids = restore_unseen_incorporations(
        previous, repaired, {'activity:seen'}, {'activity:seen', 'activity:unseen'})
    assert ids == ['activity:unseen']
    assert restored['dispositions'][0]['incorporated_record_ids'] == ['activity:unseen']
    assert repaired['dispositions'][0]['incorporated_record_ids'] == []


def test_records_a_repair_returns_or_saw_are_left_to_the_repair():
    previous = compact(child_disposition('scope:a', ['activity:merged', 'activity:seen']))
    repaired = compact(child_disposition('scope:a', []),
                       activities={'activity:merged': {'id': 'activity:merged'}})
    _, ids = restore_unseen_incorporations(
        previous, repaired, {'activity:seen'}, {'activity:merged', 'activity:seen'})
    assert ids == []


def test_only_represented_children_are_restored():
    previous = compact(child_disposition('scope:a', ['activity:unseen']))
    excluded = child_disposition('scope:a', [])
    excluded['status'] = 'excluded'
    _, ids = restore_unseen_incorporations(previous, compact(excluded), set(),
                                           {'activity:unseen'})
    assert ids == []


def test_requests_without_a_focus_send_every_record(tmp_path):
    graph = reference_graph()
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    candidate = candidate_for(graph)
    for operation, args in (('synthesize', ()), ('verify', (candidate,)),
                            ('repair', (candidate, [deterministic(['activity:a'])],
                                        failing_report(graph, ['activity:a'])))):
        request = runner.request_for(operation, graph, *args)
        assert 'provider_focus' not in request
        output_type = {'synthesize': 'CandidatePayload', 'verify': 'VerificationReport',
                       'repair': 'RepairPayload'}[operation]
        projected, _, projection = runner.project_exchange(
            request, wire_schema(output_type, graph))
        assert projection.omitted_records == 0
        strings = projected['graph']['strings']
        assert all(evidence['excerpt'] in strings
                   for evidence in graph['context']['evidence'].values())


def test_a_focus_on_a_request_other_than_repair_is_ignored(tmp_path):
    graph = reference_graph()
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    request = runner.request_for('synthesize', graph)
    request['provider_focus'] = {'version': 1, 'record_ids': []}
    _, _, projection = runner.project_exchange(request, wire_schema('CandidatePayload', graph))
    assert projection.omitted_records == 0


def test_projection_version_moved_with_the_wire_format():
    # Checkpoints record this version and are discarded when it changes.
    assert ProviderProjection.VERSION == 2


def test_ids_a_finding_asks_the_repair_to_remove_are_not_restored():
    # The child never contributed the anchor; the finding names it, so the
    # repair dropping it is the fix, not a loss.
    previous = compact(child_disposition('scope:a', ['activity:unseen', 'anchor:wrong']))
    repaired = compact(child_disposition('scope:a', []))
    restorable = {'activity:unseen'}
    restored, ids = restore_unseen_incorporations(previous, repaired, set(), restorable)
    assert ids == ['activity:unseen']
    assert 'anchor:wrong' not in restored['dispositions'][0]['incorporated_record_ids']


def test_focus_keeps_information_uses_of_a_named_concept():
    graph = reference_graph()
    context = graph['context']
    context['concepts']['concept:order'] = record('Concept', id='concept:order', name='Order')
    context['information_uses']['information_use:order'] = record(
        'InformationUse', id='information_use:order', concept_id='concept:order',
        activity_id='activity:b', evidence_ids=['ev:fixture-004'])
    focus = set(focus_for(graph, candidate_for(graph), [finding(['concept:order'])]))
    assert {'information_use:order', 'ev:fixture-004'} <= focus


def test_a_focused_repair_is_offered_only_evidence_it_can_see(tmp_path):
    graph = reference_graph()
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    candidate = candidate_for(graph)
    findings = [deterministic(['activity:a'])]
    verification = failing_report(graph, ['activity:a'])
    focus = focus_for(graph, candidate, findings, verification)
    request = runner.request_for('repair', graph, candidate, findings, verification, focus=focus)
    projected, schema, projection = runner.project_exchange(
        request, wire_schema('RepairPayload', graph))
    offered = {projection.canonical_ids[alias]
               for alias in schema['$defs']['AllowedEvidenceId']['enum']}
    assert offered == {projection.canonical_ids[alias]
                       for alias in projected['allowed_evidence_ids']}
    assert {'ev:fixture-001', 'ev:fixture'} <= offered
    assert 'ev:fixture-002' not in offered
    # The request itself still allows the whole graph's evidence for validation.
    assert 'ev:fixture-002' in request['allowed_evidence_ids']


def test_a_repair_answer_may_cite_its_own_candidate_records():
    # A small scope fixes graph references to an enum of the supplied IDs; the
    # candidate's own claims, activities and domains must stay citable.
    graph = reference_graph()
    schema = wire_schema('RepairPayload', graph)
    membership = schema['$defs']['ActivityMembership']['properties']
    assert 'enum' not in membership['claim_ids']['items']
    assert 'enum' not in membership['activity_id']
    synthesis_schema = wire_schema('CandidatePayload', graph)
    assert (synthesis_schema['$defs']['ActivityMembership']['properties']['claim_ids']
            == membership['claim_ids'])
