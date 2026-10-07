"""Repair rounds keep what the provider cited and what the graph determines.

Three deterministic behaviours are covered: ``_ref:N`` aliases keep naming the
same record across requests, restoring an unrequested revision also restores
the retired records it references, and an information use is never resolved
while its operation facts are unresolved.
"""
import copy

from lib.context.business_domain_schema import record
from lib.context.business_domain_synthesis import (
    AliasRegistry, ProviderProjection, Synthesis, _candidate_records,
    derive_identity_changes, normalize_ids, wire_schema,
)
from tests.test_business_domain_candidate_protocol import (
    ProtocolProvider, closure_candidate, closure_graph, graph_scope, synthesis,
)


# R1: run-level aliases

def _concepts(graph, *names):
    concepts = [record('Concept', id=f'concept:{name.lower()}', name=name,
                       qualified_type_names=[f'fixture.{name}'],
                       evidence_ids=['ev:fixture']) for name in names]
    return normalize_ids(record(
        'CandidatePayload', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'],
        concepts={item['id']: item for item in concepts}), graph)


def _project(runner, graph, candidate):
    request = runner.request_for('verify', graph, candidate)
    _, _, projection = runner.project_exchange(
        request, wire_schema('VerificationReport', graph))
    return projection


def _concept_id(candidate, name):
    return next(cid for cid, item in candidate['concepts'].items() if item['name'] == name)


def _number(projection, record_id):
    return int(projection.aliases[record_id].split(':')[1])


def _with_concept_first(graph, candidate, name):
    """Add a concept whose ID sorts before every existing concept."""
    for attempt in range(200):
        extra = _concepts(graph, f'{name}{attempt}')
        new_id, = extra['concepts']
        if new_id < min(candidate['concepts']):
            grown = copy.deepcopy(candidate)
            grown['concepts'].update(extra['concepts'])
            return grown, new_id
    raise AssertionError('No fixture concept sorts first')


def test_records_keep_their_alias_when_the_candidate_grows(tmp_path):
    graph = graph_scope(anchor_count=1)
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    first = _concepts(graph, 'Owner', 'Vet')
    before = _project(runner, graph, first)
    grown, new_id = _with_concept_first(graph, first, 'Visit')

    after = _project(runner, graph, grown)

    for record_id in first['concepts']:
        assert after.aliases[record_id] == before.aliases[record_id]
    # A new record gets a fresh number above every number already handed out.
    assert _number(after, new_id) > max(_number(before, rid) for rid in first['concepts'])
    # Without the registry the same growth renumbers the existing records.
    unregistered = ProviderProjection(graph)
    unregistered.extend_aliases(grown)
    assert any(unregistered.aliases[rid] != before.aliases[rid] for rid in first['concepts'])


def test_retired_aliases_are_never_reused(tmp_path):
    graph = graph_scope(anchor_count=1)
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    first = _concepts(graph, 'Owner', 'Vet')
    before = _project(runner, graph, first)
    owner = _concept_id(first, 'Owner')
    replacement = copy.deepcopy(first)
    del replacement['concepts'][owner]
    replacement['concepts'].update(_concepts(graph, 'Specialty')['concepts'])

    after = _project(runner, graph, replacement)

    used = {before.aliases[rid] for rid in first['concepts']}
    specialty = _concept_id(replacement, 'Specialty')
    assert after.aliases[specialty] not in used
    assert before.aliases[owner] not in after.canonical_ids


def test_reidentified_record_inherits_the_alias_the_provider_kept(tmp_path):
    graph = graph_scope(anchor_count=1)
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    first = _concepts(graph, 'Owner', 'Vet')
    request = _project(runner, graph, first)
    owner, vet = _concept_id(first, 'Owner'), _concept_id(first, 'Vet')
    revised = _concepts(graph, 'Pet owner', 'Veterinarian')
    pet_owner = _concept_id(revised, 'Pet owner')
    veterinarian = _concept_id(revised, 'Veterinarian')
    owner_number = _number(request, owner)

    # The provider continues Owner as concept:<its number> and Vet under its
    # exact alias, which decodes to the previous canonical ID.
    inherited = runner._inherit_aliases(graph, request, {
        f'concept:{owner_number}': pet_owner, vet: veterinarian}, revised)
    after = _project(runner, graph, revised)

    assert sorted(inherited) == sorted([(owner, pet_owner), (vet, veterinarian)])
    assert after.aliases[pet_owner] == request.aliases[owner]
    assert after.aliases[veterinarian] == request.aliases[vet]


def test_alias_is_not_inherited_by_another_kind_or_while_its_owner_remains(tmp_path):
    graph = graph_scope(anchor_count=1)
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    first = _concepts(graph, 'Owner', 'Vet')
    request = _project(runner, graph, first)
    owner = _concept_id(first, 'Owner')
    number = _number(request, owner)
    grown, new_id = _with_concept_first(graph, first, 'Visit')

    # Owner is still present, and a rule cannot continue a concept.
    assert runner._inherit_aliases(graph, request, {
        f'concept:{number}': new_id, f'rule:{number}': 'rule:other'}, grown) == []
    assert _project(runner, graph, grown).aliases[owner] == request.aliases[owner]


def test_prose_citation_keeps_naming_the_cited_record_across_rounds(tmp_path):
    graph = graph_scope(anchor_count=1)
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    first = _concepts(graph, 'Owner', 'Vet')
    request = _project(runner, graph, first)
    vet = _concept_id(first, 'Vet')
    citation = f'_ref:{_number(request, vet)}'
    grown, _ = _with_concept_first(graph, first, 'Visit')
    owner = _concept_id(grown, 'Owner')
    grown['claims'] = {'claim:cites': record(
        'Claim', id='claim:cites', subject_id=owner, kind='behavior',
        text=f'An owner takes pets to the {citation} for care.',
        evidence_ids=['ev:fixture'], trace_ids=['trace:fixture'],
        semantic_review='uncertain')}

    for _ in range(3):
        later = _project(runner, graph, grown)
        assert later.canonical_ids[citation] == vet
        grown, _ = _with_concept_first(graph, grown, 'Extra')


def test_registry_numbers_start_after_graph_aliases_and_never_repeat():
    registry = AliasRegistry()
    assert registry.assign(['a', 'b'], 10) == {'a': 10, 'b': 11}
    assert registry.assign(['b', 'c'], 10) == {'b': 11, 'c': 12}
    assert registry.inherit('a', 'a2') and not registry.inherit('a', 'a3')
    assert registry.assign(['a', 'a2'], 10) == {'a': 13, 'a2': 10}


# R2: information-use resolution ceiling

def _normalized_use(graph, resolution, reason=None):
    candidate = closure_candidate(graph)
    use, = candidate['information_uses'].values()
    use.update(resolution=resolution, reason=reason)
    normalized = normalize_ids(candidate, graph)
    return next(iter(normalized['information_uses'].items()))


def test_resolved_use_over_unresolved_write_facts_is_capped_with_a_reason():
    graph = closure_graph()
    use_id, use = _normalized_use(graph, 'resolved')
    assert use['resolution'] == 'unresolved'
    assert use['reason'] == ('The operation facts of this use are unresolved: '
                             'Commit is not established.')
    # Resolution is not identity: the capped use keeps its ID.
    assert use_id == _normalized_use(graph, 'unresolved', 'Provider reason.')[0]


def test_ambiguous_facts_cap_at_ambiguous_and_resolved_facts_are_kept():
    graph = closure_graph()
    for kind, key in (('edges', 'edge:write'), ('effects', 'effect:write')):
        graph['context'][kind][key]['resolution'] = 'ambiguous'
    assert _normalized_use(graph, 'resolved')[1]['resolution'] == 'ambiguous'
    for kind, key in (('edges', 'edge:write'), ('effects', 'effect:write')):
        graph['context'][kind][key].update(resolution='resolved', reason=None)
    assert _normalized_use(graph, 'resolved')[1]['resolution'] == 'resolved'


def test_resolution_is_never_upgraded_and_provider_reasons_are_kept():
    graph = closure_graph()
    for resolution in ('ambiguous', 'unresolved'):
        use = _normalized_use(graph, resolution, 'Provider reason.')[1]
        assert (use['resolution'], use['reason']) == (resolution, 'Provider reason.')
    assert _normalized_use(graph, 'resolved', 'Provider reason.')[1]['reason'] == 'Provider reason.'


# R3: referentially closed restoration

def _candidate(**collections):
    return {name: copy.deepcopy(records) for name, records in collections.items()}


def _restore(previous, repaired, *subject_ids):
    changes = derive_identity_changes(previous, repaired)
    findings = [{'subject_ids': list(subject_ids)}]
    restored_candidate, remaining, restored = Synthesis._restore_out_of_scope_revisions(
        previous, repaired, changes, findings, None)
    return restored_candidate, restored, Synthesis._repair_regressions(
        previous, remaining, findings, None)


def _dangling(candidate):
    records = _candidate_records(candidate)
    return [(rid, ref) for rid, (_, body) in records.items()
            for ref in body.get('claim_ids', []) + body.get('rule_ids', [])
            if ref not in records]


def test_restoring_a_concept_restores_the_claims_its_old_body_cites():
    """A repair rewrote a concept's claim under a new ID that no finding asked for."""
    previous = _candidate(
        activities={'activity:a': {'id': 'activity:a', 'name': 'Named'}},
        concepts={'concept:owner': {'id': 'concept:owner', 'claim_ids': ['claim:old']}},
        claims={'claim:old': {'id': 'claim:old', 'subject_id': 'concept:owner',
                              'text': 'Owner is a pet owner.'}})
    repaired = _candidate(
        activities={'activity:a': {'id': 'activity:a', 'name': 'Renamed as asked'}},
        concepts={'concept:owner': {'id': 'concept:owner', 'claim_ids': ['claim:new']}},
        claims={'claim:new': {'id': 'claim:new', 'subject_id': 'concept:owner',
                              'text': 'An owner keeps pets.'}})

    restored_candidate, restored, regressions = _restore(previous, repaired, 'activity:a')

    assert restored == ['claim:old', 'concept:owner']
    assert restored_candidate['concepts'] == previous['concepts']
    assert restored_candidate['claims']['claim:old'] == previous['claims']['claim:old']
    assert restored_candidate['activities'] == repaired['activities']
    assert _dangling(restored_candidate) == []
    assert regressions == []


def test_restoration_is_transitive_over_retired_dependencies():
    previous = _candidate(
        concepts={'concept:owner': {'id': 'concept:owner', 'claim_ids': ['claim:one']}},
        claims={'claim:one': {'id': 'claim:one', 'subject_id': 'concept:owner',
                              'rule_ids': ['rule:one']}},
        rules={'rule:one': {'id': 'rule:one', 'claim_ids': ['claim:two']},
               'rule:named': {'id': 'rule:named', 'name': 'Named'}},
        relationships={})
    previous['claims']['claim:two'] = {'id': 'claim:two', 'subject_id': 'rule:one'}
    repaired = _candidate(
        concepts={'concept:owner': {'id': 'concept:owner', 'claim_ids': []}},
        claims={},
        rules={'rule:named': {'id': 'rule:named', 'name': 'Renamed'}},
        relationships={})

    restored_candidate, restored, regressions = _restore(previous, repaired, 'rule:named')

    assert restored == ['claim:one', 'claim:two', 'concept:owner', 'rule:one']
    assert _candidate_records(restored_candidate).keys() == _candidate_records(previous).keys()
    assert _dangling(restored_candidate) == []
    assert regressions == []


def test_in_scope_changes_are_not_restored():
    previous = _candidate(
        concepts={'concept:owner': {'id': 'concept:owner', 'claim_ids': ['claim:old']}},
        claims={'claim:old': {'id': 'claim:old', 'subject_id': 'concept:owner',
                              'text': 'Wrong.'}})
    repaired = _candidate(
        concepts={'concept:owner': {'id': 'concept:owner', 'claim_ids': ['claim:new']}},
        claims={'claim:new': {'id': 'claim:new', 'subject_id': 'concept:owner',
                              'text': 'Corrected as asked.'}})

    # The finding names the old claim: replacing it is the requested change.
    restored_candidate, restored, regressions = _restore(previous, repaired, 'claim:old')

    assert restored == []
    assert restored_candidate == repaired
    assert regressions == []


def test_regression_guard_still_rejects_unneeded_out_of_scope_retirements():
    previous = _candidate(
        activities={'activity:a': {'id': 'activity:a', 'name': 'Named'}},
        rules={'rule:unrelated': {'id': 'rule:unrelated', 'name': 'Unrelated'}})
    repaired = _candidate(
        activities={'activity:a': {'id': 'activity:a', 'name': 'Renamed as asked'}},
        rules={})

    restored_candidate, restored, regressions = _restore(previous, repaired, 'activity:a')

    # Nothing restored needs the rule, so its retirement stays a regression.
    assert restored == []
    assert regressions == ['rule:unrelated']
