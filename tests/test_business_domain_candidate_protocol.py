import copy
import json
from itertools import product

import pytest

from lib.context.business_domain_schema import (
    DEFINITIONS, DomainError, activity_closure, candidate_scope_findings, digest,
    information_use_closure, limits, record, required_scope_subjects, validate, validation_findings,
    verification_report_findings,
)
from lib.context.business_domain_synthesis import (
    CANDIDATE_RECORD_COLLECTIONS, POLICY, ProviderProjection, Synthesis,
    agent_instructions, allowed_evidence_ids, normalize_ids,
    normalize_repair_payload, wire_schema,
)
from lib.context.business_domains import accept_candidate, discover, paths
from tests.business_domains.provider_fixture import encode


def graph_scope(anchor_count=52):
    context = record('GraphContext')
    context['resources'] = {
        'resource:fixture': record(
            'Resource', id='resource:fixture', name='fixture.py',
            language='python', evidence_ids=['ev:fixture'],
            resolution='resolved')}
    anchor_ids = [f'anchor:fixture-{index:02d}'
                  for index in range(anchor_count)]
    context['anchors'] = {
        anchor_id: record(
            'Anchor', id=anchor_id, kind='http',
            source_id='resource:fixture', canonical_anchor_id=anchor_id,
            resolution='unresolved', reason='Protocol fixture trace is partial')
        for anchor_id in anchor_ids
    }
    context['traces'] = {
        'trace:fixture': record(
            'Trace', id='trace:fixture', anchor_id=anchor_ids[0],
            traversal_complete=True, resolution='unresolved',
            reason='Protocol fixture trace is partial')}
    evidence = record(
        'Evidence', id='ev:fixture', excerpt='Fixture business behavior.',
        content_hash='0' * 64, claim_kind='behavior', extractor='fixture',
        extractor_version='1')
    evidence['locator'].update(
        path='fixture.py', source_hash='1' * 64,
        snapshot_id='snapshot:fixture', pointer='fixture.py:1')
    context['evidence'] = {evidence['id']: evidence}
    context['source_snapshots'] = {
        'snapshot:fixture': record(
            'Snapshot', id='snapshot:fixture', resource_kind='repository_file',
            resource_identity='fixture.py', content_hash='1' * 64,
            local_blob_path='.speed/context/snapshots/fixture.json',
            retrieved_at='2026-01-01T00:00:00+00:00')}
    fingerprint = digest({'context': context, 'anchors': anchor_ids})
    graph = record(
        'GraphScope', scope_id='scope:fixture', input_fingerprint=fingerprint,
        context=context, canonical_anchor_ids=anchor_ids)
    validate(graph, 'GraphScope')
    return graph


def graph_scope_with_evidence(evidence_count):
    graph = graph_scope()
    for index in range(1, evidence_count):
        evidence_id = f'ev:fixture-{index:03d}'
        snapshot_id = f'snapshot:fixture-{index:03d}'
        source_hash = f'{index + 1:064x}'
        evidence = record(
            'Evidence', id=evidence_id,
            excerpt=f'Fixture business behavior {index}.',
            content_hash=f'{index:064x}', claim_kind='behavior',
            extractor='fixture', extractor_version='1')
        evidence['locator'].update(
            path='fixture.py', source_hash=source_hash,
            snapshot_id=snapshot_id, pointer=f'fixture.py:{index + 1}')
        graph['context']['evidence'][evidence_id] = evidence
        graph['context']['source_snapshots'][snapshot_id] = record(
            'Snapshot', id=snapshot_id, resource_kind='repository_file',
            resource_identity='fixture.py', content_hash=source_hash,
            local_blob_path=f'.speed/context/snapshots/fixture-{index:03d}.json',
            retrieved_at='2026-01-01T00:00:00+00:00')
    graph['input_fingerprint'] = digest({
        'context': graph['context'],
        'anchors': graph['canonical_anchor_ids'],
    })
    validate(graph, 'GraphScope')
    return graph


def model_for_graph(graph):
    model = record('DomainArtifact')
    for collection, values in graph['context'].items():
        if collection in model:
            model[collection] = copy.deepcopy(values)
    return model


def evidence_fields(schema):
    fields = []
    def visit(shape):
        for name, child in shape.get('properties', {}).items():
            if name == 'evidence_ids':
                fields.append(child)
            visit(child)
        if isinstance(shape.get('items'), dict):
            visit(shape['items'])
        for option in shape.get('anyOf', []):
            visit(option)
        for child in shape.get('$defs', {}).values():
            visit(child)
    visit(schema)
    return fields


def contains_schema_key(schema, key):
    if isinstance(schema, dict):
        return key in schema or any(
            contains_schema_key(child, key) for child in schema.values())
    if isinstance(schema, list):
        return any(contains_schema_key(child, key) for child in schema)
    return False


def one_activity_candidate(graph):
    activity = record(
        'Activity', id='activity:provider-one', name='Manage everything',
        description='One shape-valid but semantically over-broad activity.',
        anchor_ids=graph['canonical_anchor_ids'], trace_ids=['trace:fixture'],
        evidence_ids=['ev:fixture'], claim_ids=['claim:provider-one'],
        implementation_status='implementation_unresolved', support='partial')
    claim = record(
        'Claim', id='claim:provider-one', subject_id=activity['id'],
        text=activity['description'], kind='behavior',
        evidence_ids=['ev:fixture'], trace_ids=['trace:fixture'],
        semantic_review='uncertain')
    return record(
        'CandidatePayload', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'],
        activities={activity['id']: activity}, claims={claim['id']: claim},
        dispositions=[record(
            'ScopeDisposition', id=f'disposition:provider-{index}',
            subject_kind='anchor', subject_id=anchor_id,
            status='represented', activity_ids=[activity['id']])
            for index, anchor_id in enumerate(graph['canonical_anchor_ids'])])


def repaired_candidate(graph):
    return record(
        'CandidatePayload', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'],
        dispositions=[record(
            'ScopeDisposition', id=f'disposition:repair-{index}',
            subject_kind='anchor', subject_id=anchor_id, status='excluded',
            reason='No common business outcome is established by this fixture.',
            evidence_ids=['ev:fixture'])
            for index, anchor_id in enumerate(graph['canonical_anchor_ids'])])


def candidate_records(candidate):
    indexed = {}
    for collection in CANDIDATE_RECORD_COLLECTIONS:
        records = candidate.get(collection, {})
        records = records.values() if isinstance(records, dict) else records
        indexed.update((item['id'], item) for item in records)
    return indexed


def candidate_record_ids(candidate):
    return set(candidate_records(candidate))


def repair_payload(request, candidate):
    return record(
        'RepairPayload', parent_candidate_hash=request['parent_candidate_hash'],
        candidate=candidate)


def unresolved_candidate(graph, *, evidence_ids=('ev:fixture',)):
    return record(
        'CandidatePayload', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'],
        dispositions=[record(
            'ScopeDisposition', id=f'disposition:unresolved-{index}',
            subject_kind='anchor', subject_id=anchor_id, status='unresolved',
            reason='The exact fixture capability remains unresolved.',
            evidence_ids=list(evidence_ids))
            for index, anchor_id in enumerate(graph['canonical_anchor_ids'])])


def multiple_activity_candidate(graph):
    candidate = record(
        'CandidatePayload', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'])
    halves = (graph['canonical_anchor_ids'][:26],
              graph['canonical_anchor_ids'][26:])
    for index, anchors in enumerate(halves):
        activity_id = f'activity:provider-{index}'
        claim_id = f'claim:provider-{index}'
        candidate['activities'][activity_id] = record(
            'Activity', id=activity_id, name=f'Outcome {index}',
            description=f'Distinct fixture business outcome {index}.',
            anchor_ids=anchors, trace_ids=['trace:fixture'],
            evidence_ids=['ev:fixture'], claim_ids=[claim_id],
            implementation_status='implementation_unresolved', support='partial')
        candidate['claims'][claim_id] = record(
            'Claim', id=claim_id, subject_id=activity_id,
            text=f'Distinct fixture business outcome {index}.', kind='behavior',
            evidence_ids=['ev:fixture'], trace_ids=['trace:fixture'],
            semantic_review='uncertain')
        candidate['dispositions'].extend(record(
            'ScopeDisposition', id=f'disposition:multiple-{anchor_id}',
            subject_kind='anchor', subject_id=anchor_id,
            status='represented', activity_ids=[activity_id])
            for anchor_id in anchors)
    return candidate


def shared_anchor_candidate(graph, activity_ids=('activity:a', 'activity:b')):
    candidate = record(
        'CandidatePayload', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'])
    evidence = (
        ('trace:update', 'effect:update', 'Update the stored order status'),
        ('trace:notify', 'effect:notify', 'Notify the customer'),
    )
    for activity_id, (trace_id, effect_id, name) in zip(
            activity_ids, evidence):
        candidate['activities'][activity_id] = record(
            'Activity', id=activity_id, name=name,
            anchor_ids=[graph['canonical_anchor_ids'][0]],
            trace_ids=[trace_id], effect_ids=[effect_id])
    candidate['domains']['domain:orders'] = record(
        'Domain', id='domain:orders',
        activity_memberships=[
            record('ActivityMembership', activity_id=activity_ids[0],
                   role='primary'),
            record('ActivityMembership', activity_id=activity_ids[1],
                   role='supporting'),
        ])
    candidate['dispositions'] = [record(
        'ScopeDisposition', id='disposition:cancel-order',
        subject_kind='anchor',
        subject_id=graph['canonical_anchor_ids'][0], status='represented',
        activity_ids=list(activity_ids))]
    validate(candidate, 'CandidatePayload')
    return candidate


class ProtocolProvider:
    model = 'fixture'
    provider_context_tokens = 200_000
    provider_max_output_tokens = 8_000
    output_limit_enforcement = 'provider'

    def __init__(self, graph, incomplete_check=False, fail_after_repair=False,
                 missing_disposition=False):
        self.graph = graph
        self.incomplete_check = incomplete_check
        self.fail_after_repair = fail_after_repair
        self.missing_disposition = missing_disposition
        self.requests = []
        self.responses = []

    def generate(self, request, schema, *_):
        self.requests.append(copy.deepcopy(request))
        operation = request['operation']
        if operation == 'synthesize':
            payload = one_activity_candidate(self.graph)
            if self.missing_disposition:
                payload['dispositions'].pop()
        elif operation == 'repair':
            payload = repair_payload(
                request, repaired_candidate(self.graph))
        else:
            checked = sorted(required_scope_subjects(self.graph))
            if self.incomplete_check:
                checked = checked[:-1]
            repaired = len([item for item in self.requests
                            if item['operation'] == 'verify']) > 1
            passes = repaired and not self.fail_after_repair
            findings = [] if passes else [record(
                'VerificationFinding', id='verification_finding:provider',
                category='incorrect_merge', severity='blocking',
                message='The 52 anchors do not implement one business outcome.',
                subject_ids=sorted({
                    *self.graph['canonical_anchor_ids'],
                    *candidate_record_ids(request['candidate']),
                }))]
            payload = record(
                'VerificationReport', scope_id=self.graph['scope_id'],
                input_fingerprint=self.graph['input_fingerprint'],
                verdict=('pass' if passes else 'fail'), findings=findings,
                checked_subject_ids=checked)
        self.responses.append(copy.deepcopy(payload))
        return encode(payload, DEFINITIONS[
            'VerificationReport' if operation == 'verify'
            else 'RepairPayload' if operation == 'repair'
            else 'CandidatePayload']), {
                'last': {'inputTokens': 10, 'outputTokens': 10}}


class InvalidFindingPrefixOnceProvider(ProtocolProvider):
    def generate(self, request, schema, *args):
        value, usage = super().generate(request, schema, *args)
        verify_count = sum(
            item['operation'] == 'verify'
            for item in self.requests)

        if request['operation'] == 'verify' and verify_count == 1:
            value['findings'][0]['id'] = 'finding:provider'

        return value, usage


def synthesis(tmp_path, provider):
    config = {
        'max_trace_depth': 6, 'max_symbols_per_activity': 200,
        'max_request_input_tokens': 200_000,
        'max_request_output_tokens': 8_000,
        'max_build_input_tokens': 8_000_000,
        'max_build_output_tokens': 512_000,
        'provider_concurrency': 1, 'deadline_seconds': 3_600,
        'max_source_bytes': 500_000, 'max_artifact_bytes': 25_000_000,
        'cache_retention_days': 30, 'snapshot_manifest': None,
    }
    return Synthesis(tmp_path, config, provider, limits(config))


def validate_candidate(graph, candidate):
    return []


def _record_id_patterns(shape):
    patterns = []
    properties = shape.get('properties', {})
    if 'id' in properties:
        patterns.append(properties['id']['pattern'])

    for keyword in ('anyOf', 'oneOf', 'allOf'):
        for variant in shape.get(keyword, []):
            patterns.extend(_record_id_patterns(variant))

    return patterns


@pytest.mark.parametrize(('output_type', 'record_type', 'prefix'), [
    ('CandidatePayload', 'Activity', 'activity'),
    ('CandidatePayload', 'Rule', 'rule'),
    ('CandidatePayload', 'Concept', 'concept'),
    ('CandidatePayload', 'InformationUse', 'information_use'),
    ('CandidatePayload', 'Ownership', 'ownership'),
    ('CandidatePayload', 'RuleRelationship', 'rule_relationship'),
    ('CandidatePayload', 'Claim', 'claim'),
    ('CandidatePayload', 'Domain', 'domain'),
    ('CandidatePayload', 'Relationship', 'relationship'),
    ('CandidatePayload', 'ScopeDisposition', 'disposition'),
    ('VerificationReport', 'VerificationFinding',
     'verification_finding'),
])
def test_wire_schema_requires_provider_record_prefix(
        output_type, record_type, prefix):
    schema = wire_schema(output_type, graph_scope())

    assert set(_record_id_patterns(schema['$defs'][record_type])) == {
        f'^{prefix}:[^ ]+$'
    }


def test_repair_provider_schema_excludes_orchestrator_identity_ledger():
    schema = wire_schema('RepairPayload', graph_scope())

    assert set(schema['properties']) == {
        'parent_candidate_hash', 'candidate'}
    assert set(schema['required']) == {
        'parent_candidate_hash', 'candidate'}
    assert schema['additionalProperties'] is False


def test_invalid_verification_finding_prefix_uses_schema_retry(tmp_path):
    graph = graph_scope()
    provider = InvalidFindingPrefixOnceProvider(graph)
    runner = synthesis(tmp_path, provider)

    runner.run(
        graph,
        lambda candidate: validate_candidate(graph, candidate))

    assert [request['operation'] for request in provider.requests] == [
        'synthesize', 'verify', 'verify']
    assert runner.counters['retries'] == 1


def test_all_evidence_fields_are_constrained_above_generic_enum_limit():
    graph = graph_scope_with_evidence(129)
    schema = wire_schema('CandidatePayload', graph)
    allowed = allowed_evidence_ids(graph)
    reference = '#/$defs/AllowedEvidenceId'

    assert len(allowed) == 129
    assert schema['$defs']['AllowedEvidenceId'] == {
        'type': 'string', 'enum': allowed}
    fields = evidence_fields(schema)
    variants = schema['$defs']['ScopeDisposition']['anyOf']
    assert len(fields) == 10+len(variants)
    assert all(field['items'] == {'$ref': reference} for field in fields)


def test_projected_evidence_constraint_contains_only_evidence_aliases():
    graph = graph_scope_with_evidence(129)
    projection = ProviderProjection(graph)
    schema = projection.project_schema(wire_schema('CandidatePayload', graph))
    allowed = allowed_evidence_ids(graph)
    evidence_aliases = schema['$defs']['AllowedEvidenceId']['enum']

    assert evidence_aliases == [projection.aliases[item] for item in allowed]
    assert projection.aliases['resource:fixture'] not in evidence_aliases
    assert projection.decode_response(
        {'evidence_ids': [evidence_aliases[0]]}) == {
            'evidence_ids': [allowed[0]]}


def test_repair_projection_aliases_and_restores_candidate_owned_ids(tmp_path):
    graph = graph_scope()
    candidate = normalize_ids(multiple_activity_candidate(graph), graph)
    activity_id = next(iter(candidate['activities']))
    report = record(
        'VerificationReport', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'], verdict='fail',
        findings=[record(
            'VerificationFinding', id='verification_finding:provider',
            category='incorrect_merge', severity='blocking',
            message='The candidate requires repair.',
            subject_ids=[activity_id])],
        checked_subject_ids=sorted(required_scope_subjects(graph)))
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    request = runner.request_for('repair', graph, candidate, (), report)
    schema = wire_schema('CandidatePayload', graph)

    projected, projected_schema, projection = runner.project_exchange(
        request, schema)
    alias = projection.aliases[activity_id]

    assert alias in projected['candidate']['activities']
    assert activity_id not in projected['candidate']['activities']
    assert projected['verification_report']['findings'][0][
        'subject_ids'] == [alias]
    assert projection.decode_response(projected['candidate']) == candidate
    assert projection.decode_response(
        projected['verification_report']) == report

    unaliased = copy.deepcopy(projected)
    unaliased['candidate'] = candidate
    unaliased['verification_report'] = report
    assert runner.estimate_input(
        projected, projected_schema) < runner.estimate_input(
            unaliased, projected_schema)


def test_invalid_evidence_is_rejected_by_schema_and_local_backstop():
    graph = graph_scope_with_evidence(129)
    candidate = one_activity_candidate(graph)
    candidate['activities']['activity:provider-one']['evidence_ids'] = [
        'resource:fixture']
    encoded = encode(candidate, DEFINITIONS['CandidatePayload'])

    assert validation_findings(
        encoded, wire_schema('CandidatePayload', graph), 'candidate',
        code='INVALID_PROVIDER_OUTPUT')
    findings = Synthesis._citation_findings(
        candidate, set(allowed_evidence_ids(graph)))
    assert findings
    assert {finding['code'] for finding in findings} == {'INVALID_EVIDENCE'}


def test_candidate_provider_schema_compiles_canonical_conditionals():
    graph = graph_scope()
    schema = wire_schema('CandidatePayload', graph)
    projected = ProviderProjection(graph).project_schema(schema)
    variants = schema['$defs']['ScopeDisposition']['anyOf']

    assert len(variants) == 3
    assert not contains_schema_key(schema, 'allOf')
    assert not contains_schema_key(projected, 'allOf')
    assert all(variant['additionalProperties'] is False for variant in variants)
    assert all(set(variant['required']) == set(variant['properties'])
               for variant in variants)


def test_zero_activity_candidate_with_unresolved_anchors_is_vacuous():
    graph = graph_scope()
    candidate = unresolved_candidate(graph)

    findings = candidate_scope_findings(graph, candidate)

    assert 'VACUOUS_BUSINESS_MODEL' in {
        finding['code'] for finding in findings
    }


def test_unresolved_disposition_requires_evidence():
    graph = graph_scope()
    candidate = unresolved_candidate(graph, evidence_ids=())

    with pytest.raises(DomainError, match='evidence_ids'):
        validate(candidate, 'CandidatePayload')


def test_evidenced_all_excluded_candidate_is_not_mechanically_vacuous():
    graph = graph_scope()
    candidate = repaired_candidate(graph)

    assert 'VACUOUS_BUSINESS_MODEL' not in {
        finding['code']
        for finding in candidate_scope_findings(graph, candidate)
    }


def test_synthesis_prompt_contains_completion_gate():
    prompt = agent_instructions()['synthesis']

    assert '## Completion gate' in prompt
    assert 'Do not return until all of these conditions hold' in prompt
    assert 'The output schema constrains representation' in prompt
    assert 'repeated generic unresolved dispositions' in prompt


def test_synthesis_prompt_defines_bindings_and_orchestrator_owned_repair_diff():
    prompt = agent_instructions()['synthesis']

    assert '`input_binding_ids`' in prompt
    assert '`output_binding_ids`' in prompt
    assert (
        "bindings reachable through that activity's selected traces"
        in prompt)
    assert 'Input bindings carry request or parameter shapes' in prompt
    assert 'reachable ambiguous or unresolved bindings' in prompt
    assert 'orchestrator normalizes the replacement and derives' in prompt
    assert 'do not return an identity ledger' in prompt


def test_verification_prompt_requires_global_completeness_review():
    prompt = agent_instructions()['verification']

    assert 'minimum required finding set' in prompt
    assert 'perform this global completion check' in prompt
    assert 'zero activities is blocking' in prompt
    assert 'repeated generic disposition reasons' in prompt.lower()


@pytest.mark.parametrize(
    'subject_kind,status,activity_ids,incorporated_record_ids,reason',
    list(product(
        ('anchor', 'anchor_correspondence', 'child_scope'),
        ('represented', 'excluded', 'unresolved'),
        ([], ['activity:provider-one']),
        ([], ['claim:provider-one']),
        (None, '', 'Disposition explanation.'),
    )),
)
def test_candidate_wire_matches_all_canonical_disposition_conditions(
        subject_kind, status, activity_ids, incorporated_record_ids, reason):
    graph = graph_scope()
    candidate = one_activity_candidate(graph)
    candidate['dispositions'][0].update(
        subject_kind=subject_kind, status=status,
        activity_ids=activity_ids,
        incorporated_record_ids=incorporated_record_ids, reason=reason)
    encoded = encode(candidate, DEFINITIONS['CandidatePayload'])
    canonical_schema = {
        '$defs': DEFINITIONS,
        '$ref': '#/$defs/CandidatePayload',
    }

    canonical_valid = not validation_findings(
        candidate, canonical_schema, 'canonical candidate')
    wire_valid = not validation_findings(
        encoded, wire_schema('CandidatePayload', graph), 'provider candidate')
    assert wire_valid == canonical_valid


def test_all_52_anchors_are_one_request_and_can_form_multiple_activities(tmp_path):
    graph = graph_scope()
    class MultipleActivityProvider(ProtocolProvider):
        def generate(self, request, schema, *_):
            self.requests.append(copy.deepcopy(request))
            if request['operation'] == 'synthesize':
                payload = multiple_activity_candidate(self.graph)
            else:
                payload = record(
                    'VerificationReport', scope_id=self.graph['scope_id'],
                    input_fingerprint=self.graph['input_fingerprint'],
                    verdict='pass', checked_subject_ids=sorted(
                        required_scope_subjects(self.graph)))
            self.responses.append(copy.deepcopy(payload))
            return encode(payload, DEFINITIONS[
                'VerificationReport' if request['operation'] == 'verify'
                else 'CandidatePayload']), {'last': {}}

    provider = MultipleActivityProvider(graph)
    result = synthesis(tmp_path, provider).run(
        graph, lambda value: validate_candidate(graph, value))
    assert len(provider.requests[0]['graph']['canonical_anchor_ids']) == 52
    assert [request['operation'] for request in provider.requests] == [
        'synthesize', 'verify']
    assert len(result['activities']) == 2


def test_normalization_is_grounded_and_provider_label_invariant():
    graph = graph_scope(anchor_count=1)
    original = normalize_ids(shared_anchor_candidate(graph), graph)
    relabeled = normalize_ids(
        shared_anchor_candidate(graph, ('activity:x', 'activity:y')), graph)

    assert original == relabeled
    assert len(original['activities']) == 2
    memberships = next(iter(original['domains'].values()))[
        'activity_memberships']
    assert {member['activity_id'] for member in memberships} == set(
        original['activities'])


def test_normalization_coalesces_only_equal_complete_records():
    graph = graph_scope(anchor_count=1)
    candidate = shared_anchor_candidate(graph)
    duplicate = copy.deepcopy(candidate['activities']['activity:a'])
    duplicate['id'] = 'activity:x'
    candidate['activities'][duplicate['id']] = duplicate
    candidate['dispositions'][0]['activity_ids'].append(duplicate['id'])
    normalized = normalize_ids(candidate, graph)
    assert len(normalized['activities']) == 2
    assert len(normalized['dispositions'][0]['activity_ids']) == 2

    candidate = shared_anchor_candidate(graph)
    conflict = copy.deepcopy(candidate['activities']['activity:a'])
    conflict.update(id='activity:x', description='Different provider prose')
    candidate['activities'][conflict['id']] = conflict
    with pytest.raises(DomainError) as raised:
        normalize_ids(candidate, graph)
    assert raised.value.code == 'CANONICAL_ID_COLLISION'
    assert raised.value.repair_kind == 'semantic'
    assert raised.value.rejected_candidate == candidate


def test_normalization_validates_provider_id_ownership():
    graph = graph_scope(anchor_count=1)
    candidate = shared_anchor_candidate(graph)
    candidate['activities']['claim:wrong'] = candidate['activities'].pop(
        'activity:a')
    candidate['activities']['claim:wrong']['id'] = 'claim:wrong'
    with pytest.raises(DomainError) as raised:
        normalize_ids(candidate, graph)
    assert raised.value.code == 'INVALID_ID'
    assert raised.value.repair_kind == 'semantic'

    candidate = shared_anchor_candidate(graph)
    candidate['activities']['activity:key'] = candidate['activities'].pop(
        'activity:a')
    with pytest.raises(DomainError) as raised:
        normalize_ids(candidate, graph)
    assert raised.value.code == 'INVALID_PROVIDER_OUTPUT'
    assert raised.value.repair_kind == 'schema'


def concept_candidate(graph, concepts):
    return record(
        'CandidatePayload', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'],
        concepts={item['id']: item for item in concepts})


def test_repair_payload_derives_retired_and_added_records_for_a_merge():
    graph = graph_scope(anchor_count=1)
    previous = normalize_ids(concept_candidate(graph, [
        record('Concept', id='concept:a', name='Owner',
               qualified_type_names=['Owner']),
        record('Concept', id='concept:b', name='Customer',
               qualified_type_names=['Customer']),
    ]), graph)
    merged = concept_candidate(graph, [record(
        'Concept', id='concept:merged', name='Customer owner',
        qualified_type_names=['Customer', 'Owner'])])
    response = record(
        'RepairPayload', parent_candidate_hash=digest(previous),
        candidate=merged)

    normalized = normalize_repair_payload(
        response, graph, previous, digest(previous))
    merged_id = next(iter(normalized['candidate']['concepts']))

    retired = [change for change in normalized['identity_changes']
               if change['kind'] == 'retired']
    added = [change for change in normalized['identity_changes']
             if change['kind'] == 'added']
    assert {change['from_ids'][0] for change in retired} == set(
        previous['concepts'])
    assert [change['to_ids'][0] for change in added] == [merged_id]


def test_repair_payload_derives_retired_and_added_records_for_a_split():
    graph = graph_scope(anchor_count=1)
    previous = normalize_ids(concept_candidate(graph, [record(
        'Concept', id='concept:party', name='Party',
        qualified_type_names=['Owner', 'Veterinarian'])]), graph)
    split = concept_candidate(graph, [
        record('Concept', id='concept:owner', name='Owner',
               qualified_type_names=['Owner']),
        record('Concept', id='concept:vet', name='Veterinarian',
               qualified_type_names=['Veterinarian']),
    ])
    old_id = next(iter(previous['concepts']))
    response = record(
        'RepairPayload', parent_candidate_hash=digest(previous),
        candidate=split)

    normalized = normalize_repair_payload(
        response, graph, previous, digest(previous))

    retired = [change for change in normalized['identity_changes']
               if change['kind'] == 'retired']
    added = [change for change in normalized['identity_changes']
             if change['kind'] == 'added']
    assert [change['from_ids'][0] for change in retired] == [old_id]
    assert {change['to_ids'][0] for change in added} == set(
        normalized['candidate']['concepts'])


def test_repair_payload_rejects_the_wrong_parent_candidate():
    graph = graph_scope(anchor_count=1)
    previous = concept_candidate(graph, [])
    response = record(
        'RepairPayload', parent_candidate_hash=digest('another candidate'),
        candidate=copy.deepcopy(previous))

    with pytest.raises(DomainError) as raised:
        normalize_repair_payload(
            response, graph, previous, digest(previous))

    assert raised.value.code == 'INVALID_REPAIR_PARENT'
    assert raised.value.repair_kind == 'semantic'


def test_repair_payload_derives_complete_identity_change_coverage():
    graph = graph_scope(anchor_count=1)
    previous = normalize_ids(concept_candidate(graph, [record(
        'Concept', id='concept:party', name='Party')]), graph)
    replacement = concept_candidate(graph, [])
    response = record(
        'RepairPayload', parent_candidate_hash=digest(previous),
        candidate=replacement)

    normalized = normalize_repair_payload(
        response, graph, previous, digest(previous))

    assert normalized['identity_changes'] == [record(
        'IdentityChange', kind='retired',
        from_ids=[next(iter(previous['concepts']))], to_ids=[],
        reason='Record is absent from the complete replacement candidate.')]


def test_repair_payload_derives_lineage_for_a_same_id_body_change():
    graph = graph_scope(anchor_count=1)
    previous = normalize_ids(repaired_candidate(graph), graph)
    replacement = copy.deepcopy(previous)
    disposition_id = replacement['dispositions'][0]['id']
    replacement['dispositions'][0]['reason'] = (
        'The fixture still establishes no supported business outcome.')
    assert normalize_ids(replacement, graph)['dispositions'][0][
        'id'] == disposition_id

    response = record(
        'RepairPayload', parent_candidate_hash=digest(previous),
        candidate=replacement)
    normalized = normalize_repair_payload(
        response, graph, previous, digest(previous))

    assert normalized['candidate'] == replacement
    assert normalized['identity_changes'] == [record(
        'IdentityChange', kind='revised',
        from_ids=[disposition_id], to_ids=[disposition_id],
        reason='Record body changed under its stable canonical identity.')]


def test_repair_regression_allows_only_the_finding_dependency_closure():
    graph = graph_scope(anchor_count=1)
    previous = normalize_ids(shared_anchor_candidate(graph), graph)
    activity_id = next(iter(previous['activities']))
    domain_id = next(iter(previous['domains']))
    unrelated_activity = sorted(previous['activities'])[-1]
    changes = [record(
        'IdentityChange', kind='revised', from_ids=[domain_id],
        to_ids=['domain:replacement'], reason='Membership IDs changed.'),
        record('IdentityChange', kind='revised',
               from_ids=[unrelated_activity], to_ids=['activity:replacement'],
               reason='Unrelated content changed.')]
    findings = [{'subject_ids': [activity_id]}]

    assert Synthesis._repair_regressions(
        previous, changes, findings, None) == [unrelated_activity]


def test_short_hash_collision_uses_stable_full_basis(monkeypatch):
    from lib.context import business_domain_synthesis as module

    graph = graph_scope(anchor_count=1)
    monkeypatch.setattr(
        module, 'identifier', lambda kind, *_: f'{kind}:forced')
    normalized = module.normalize_ids(shared_anchor_candidate(graph), graph)
    assert len(normalized['activities']) == 2
    assert all(activity_id.startswith('activity:forced:')
               for activity_id in normalized['activities'])


def test_incorrect_merge_repairs_exact_candidate_and_reverifies(tmp_path):
    graph = graph_scope()
    provider = ProtocolProvider(graph)
    result = synthesis(tmp_path, provider).run(
        graph, lambda value: validate_candidate(graph, value))
    assert [request['operation'] for request in provider.requests] == [
        'synthesize', 'verify', 'repair', 'verify']
    rejected = provider.requests[1]['candidate']
    repair = provider.requests[2]
    assert repair['candidate'] == rejected
    assert repair['verification_report'] == normalize_ids(
        provider.responses[1], graph)
    assert repair['verification_report']['findings'][0][
        'category'] == 'incorrect_merge'
    assert result['activities'] == {}
    repair_responses = [
        json.loads(path.read_text())['response']
        for path in (tmp_path/'.speed/context/business-domain-cache').glob(
            '*.json')
        if ('"kind":"response"' in path.read_text()
            and '"operation":"repair"' in path.read_text())]
    assert len(repair_responses) == 1
    assert repair_responses[0]['identity_changes']
    assert all(change['reason'] for change in
               repair_responses[0]['identity_changes'])


def test_normalization_collision_uses_existing_repair_and_verified_cache(
        tmp_path):
    graph = graph_scope(anchor_count=1)

    class CollisionProvider(ProtocolProvider):
        def generate(self, request, schema, *_):
            self.requests.append(copy.deepcopy(request))
            operation = request['operation']
            if operation == 'synthesize':
                payload = record(
                    'CandidatePayload', scope_id=graph['scope_id'],
                    input_fingerprint=graph['input_fingerprint'],
                    dispositions=[
                        record(
                            'ScopeDisposition', id='disposition:a',
                            subject_kind='anchor',
                            subject_id=graph['canonical_anchor_ids'][0],
                            status='excluded', reason='No business outcome.',
                            evidence_ids=['ev:fixture']),
                        record(
                            'ScopeDisposition', id='disposition:b',
                            subject_kind='anchor',
                            subject_id=graph['canonical_anchor_ids'][0],
                            status='unresolved', reason='Needs review.',
                            evidence_ids=['ev:fixture']),
                    ])
            elif operation == 'repair':
                payload = repair_payload(
                    request, repaired_candidate(graph))
            else:
                repaired = any(item['operation'] == 'repair'
                               for item in self.requests)
                payload = record(
                    'VerificationReport', scope_id=graph['scope_id'],
                    input_fingerprint=graph['input_fingerprint'],
                    verdict='pass' if repaired else 'fail',
                    checked_subject_ids=sorted(
                        required_scope_subjects(graph)),
                    findings=[] if repaired else [record(
                        'VerificationFinding',
                        id='verification_finding:collision',
                        category='other', severity='blocking',
                        message='Conflicting dispositions require repair.')])
            self.responses.append(copy.deepcopy(payload))
            return encode(payload, DEFINITIONS[
                'VerificationReport' if operation == 'verify'
                else 'RepairPayload' if operation == 'repair'
                else 'CandidatePayload']), {'last': {}}

    provider = CollisionProvider(graph)
    result = synthesis(tmp_path, provider).run(
        graph, lambda value: validate_candidate(graph, value))
    assert [request['operation'] for request in provider.requests] == [
        'synthesize', 'verify', 'repair', 'verify']
    assert result == normalize_ids(repaired_candidate(graph), graph)
    responses = [path for path in
                 (tmp_path/'.speed/context/business-domain-cache').glob(
                     '*.json')
                 if '"kind":"response"' in path.read_text()]
    synthesis_responses = [path for path in responses
                           if '"operation":"synthesize"' in path.read_text()]
    assert len(synthesis_responses) == 1
    cached = synthesis_responses[0].read_text()
    assert '"verification_response_key":null' not in cached
    assert '"usage":{"input_tokens":null,"output_tokens":null}' in cached

    cached_provider = CollisionProvider(graph)
    assert synthesis(tmp_path, cached_provider).run(
        graph, lambda value: validate_candidate(graph, value)) == result
    assert cached_provider.requests == []


def test_incomplete_checked_subject_ids_cannot_pass(tmp_path):
    graph = graph_scope()
    provider = ProtocolProvider(graph, incomplete_check=True)
    with pytest.raises(DomainError, match='check every required scope subject'):
        synthesis(tmp_path, provider).run(
            graph, lambda value: validate_candidate(graph, value))


def test_missing_disposition_is_sent_to_repair_as_deterministic_finding(tmp_path):
    graph = graph_scope()
    provider = ProtocolProvider(graph, missing_disposition=True)
    synthesis(tmp_path, provider).run(
        graph, lambda value: validate_candidate(graph, value))
    assert [request['operation'] for request in provider.requests] == [
        'synthesize', 'verify', 'repair', 'verify']
    assert provider.requests[2]['candidate'] == provider.requests[1]['candidate']
    assert [finding['code'] for finding in
            provider.requests[2]['deterministic_findings']] == [
                'INVALID_COVERAGE']


def test_nonpassing_repaired_candidate_is_not_cached(tmp_path):
    graph = graph_scope()
    provider = ProtocolProvider(graph, fail_after_repair=True)
    with pytest.raises(DomainError, match='did not pass'):
        synthesis(tmp_path, provider).run(
            graph, lambda value: validate_candidate(graph, value))
    cache = tmp_path/'.speed/context/business-domain-cache'
    responses = [read for read in cache.glob('*.json')
                 if '"kind":"response"' in read.read_text()]
    assert responses
    assert all('"operation":"verify"' in path.read_text()
               for path in responses)
    assert sum(request['operation'] == 'repair'
               for request in provider.requests) == 2


class RepairChainProvider(ProtocolProvider):
    def __init__(self, graph, pass_after=None):
        super().__init__(graph)
        self.pass_after = pass_after

    def generate(self, request, schema, *_):
        self.requests.append(copy.deepcopy(request))
        operation = request['operation']
        if operation == 'synthesize':
            payload = one_activity_candidate(self.graph)
            output_type = 'CandidatePayload'
        elif operation == 'repair':
            candidate = copy.deepcopy(request['candidate'])
            repair_count = sum(
                item['operation'] == 'repair' for item in self.requests)
            concept_id = f'concept:chain-{repair_count}'
            candidate['concepts'][concept_id] = record(
                'Concept', id=concept_id, name=f'Chain {repair_count}')
            activity_id = next(iter(candidate['activities']))
            candidate['activities'][activity_id]['concept_ids'].append(
                concept_id)
            payload = record(
                'RepairPayload',
                parent_candidate_hash=request['parent_candidate_hash'],
                candidate=candidate)
            output_type = 'RepairPayload'
        else:
            verify_count = sum(
                item['operation'] == 'verify' for item in self.requests)
            passing = (self.pass_after is not None
                       and verify_count >= self.pass_after)
            categories = (
                'incorrect_merge', 'missing_activity',
                'unsupported_claim', 'missing_alternative')
            payload = record(
                'VerificationReport', scope_id=self.graph['scope_id'],
                input_fingerprint=self.graph['input_fingerprint'],
                verdict='pass' if passing else 'fail',
                findings=[] if passing else [record(
                    'VerificationFinding',
                    id=f'verification_finding:chain-{verify_count}',
                    category=categories[verify_count - 1],
                    severity='blocking',
                    message=f'Distinct repair defect {verify_count}.',
                    subject_ids=sorted({
                        *self.graph['canonical_anchor_ids'],
                        *candidate_record_ids(request['candidate']),
                    }))],
                checked_subject_ids=sorted(
                    required_scope_subjects(self.graph)))
            output_type = 'VerificationReport'
        self.responses.append(copy.deepcopy(payload))
        return encode(payload, DEFINITIONS[output_type]), {
            'last': {'inputTokens': 10, 'outputTokens': 10}}


def test_distinct_semantic_repairs_continue_until_verification_passes(
        tmp_path, monkeypatch):
    graph = graph_scope()
    monkeypatch.setitem(POLICY, 'semantic_repair_limit', 4)
    provider = RepairChainProvider(graph, pass_after=3)

    result = synthesis(tmp_path, provider).run(
        graph, lambda value: validate_candidate(graph, value))

    assert result
    assert [request['operation'] for request in provider.requests] == [
        'synthesize', 'verify', 'repair', 'verify', 'repair', 'verify']


def test_distinct_semantic_repairs_stop_at_the_configured_limit(
        tmp_path, monkeypatch):
    graph = graph_scope()
    monkeypatch.setitem(POLICY, 'semantic_repair_limit', 2)
    provider = RepairChainProvider(graph)

    with pytest.raises(
            DomainError, match='reached the configured repair limit') as raised:
        synthesis(tmp_path, provider).run(
            graph, lambda value: validate_candidate(graph, value))

    assert raised.value.code == 'SEMANTIC_VERIFICATION_FAILED'
    assert sum(request['operation'] == 'repair'
               for request in provider.requests) == 2


def test_unchanged_verified_scope_uses_zero_provider_calls(tmp_path):
    graph = graph_scope()
    first = ProtocolProvider(graph)
    expected = synthesis(tmp_path, first).run(
        graph, lambda value: validate_candidate(graph, value))
    second = ProtocolProvider(graph)
    actual = synthesis(tmp_path, second).run(
        graph, lambda value: validate_candidate(graph, value))
    assert actual == expected
    assert second.requests == []


class DiscoverProvider:
    model = 'fixture'
    provider_context_tokens = 200_000
    provider_max_output_tokens = 8_000
    output_limit_enforcement = 'provider'

    def __init__(self, passing):
        self.passing = passing
        self.requests = []

    def generate(self, request, schema, *_):
        self.requests.append(copy.deepcopy(request))
        graph = request['graph']
        if request['operation'] == 'verify':
            findings = [] if self.passing else [record(
                'VerificationFinding', id='verification_finding:failed',
                category='incorrect_merge', severity='blocking',
                message='The candidate remains semantically invalid.',
                subject_ids=sorted(required_scope_subjects(graph)))]
            payload = record(
                'VerificationReport', scope_id=graph['scope_id'],
                input_fingerprint=graph['input_fingerprint'],
                verdict=('pass' if self.passing else 'fail'),
                findings=findings,
                checked_subject_ids=sorted(required_scope_subjects(graph)))
            output_type = 'VerificationReport'
        else:
            dispositions = []
            evidence_id = sorted(request['allowed_evidence_ids'])[0]
            for index, (subject_id, subject_kind) in enumerate(
                    sorted(required_scope_subjects(graph).items())):
                dispositions.append(record(
                    'ScopeDisposition', id=f'disposition:discover-{index}',
                    subject_kind=subject_kind, subject_id=subject_id,
                    status='excluded',
                    reason='No business outcome is asserted by this fixture.',
                    evidence_ids=[evidence_id]))
            payload = record(
                'CandidatePayload', scope_id=graph['scope_id'],
                input_fingerprint=graph['input_fingerprint'],
                dispositions=dispositions)
            output_type = 'CandidatePayload'
            if request['operation'] == 'repair':
                payload = repair_payload(request, payload)
                output_type = 'RepairPayload'
        return encode(payload, DEFINITIONS[output_type]), {'last': {}}


@pytest.mark.parametrize('passing', [True, False])
def test_discover_publishes_only_a_passing_candidate(tmp_path, passing):
    (tmp_path/'service.py').write_text(
        "@app.post('/orders')\ndef create(order):\n    return order\n")
    provider = DiscoverProvider(passing)
    model, status = discover(tmp_path, provider=provider)
    if passing:
        assert model is not None
        assert paths(tmp_path)['model'].is_file()
        assert status['root_reconciled'] is True
    else:
        assert model is None
        assert not paths(tmp_path)['model'].exists()
        assert status['error']['code'] == 'SEMANTIC_VERIFICATION_FAILED'


def test_candidate_validation_reports_all_independent_rule_failures():
    graph = graph_scope()
    model = model_for_graph(graph)
    original = copy.deepcopy(model)
    candidate = one_activity_candidate(graph)
    activity = next(iter(candidate['activities'].values()))
    activity['support'] = 'supported'
    missing_rule_ids = [f'rule:missing-{index:02d}' for index in range(19)]
    activity['rule_ids'] = [*missing_rule_ids, 'rule:verified']
    candidate['rules']['rule:verified'] = record(
        'Rule', id='rule:verified', name='Verified rule',
        description='A rule whose enforcement requires a resolved trace.',
        activity_ids=[activity['id']], evidence_ids=['ev:fixture'],
        basis=['source_observed'], enforcement_status='verified_on_trace',
        support='supported')

    with pytest.raises(DomainError) as raised:
        accept_candidate(model, graph, candidate)

    assert raised.value.findings == [
        {
            'code': 'INVALID_ENFORCEMENT',
            'severity': 'error',
            'message': 'Verified rule enforcement requires resolved traces',
            'subject_ids': [
                activity['id'], 'rule:verified', 'trace:fixture'],
            'evidence_ids': [],
        },
        {
            'code': 'INVALID_REFERENCE',
            'severity': 'error',
            'message': 'Activity references a rule absent from the candidate',
            'subject_ids': sorted([activity['id'], *missing_rule_ids]),
            'evidence_ids': [],
        },
        {
            'code': 'INVALID_TRACE',
            'severity': 'error',
            'message': (
                'Supported activity requires resolved implementation traces'),
            'subject_ids': [activity['id'], 'trace:fixture'],
            'evidence_ids': [],
        },
    ]
    assert model == original


def test_missing_trace_does_not_hide_missing_rule_or_raise_key_error():
    graph = graph_scope()
    model = model_for_graph(graph)
    candidate = one_activity_candidate(graph)
    activity = next(iter(candidate['activities'].values()))
    activity['trace_ids'] = ['trace:absent']
    activity['rule_ids'] = ['rule:absent']

    with pytest.raises(DomainError) as raised:
        accept_candidate(model, graph, candidate)

    assert {(finding['code'], tuple(finding['subject_ids']))
            for finding in raised.value.findings} == {
        ('INVALID_REFERENCE', (activity['id'], 'rule:absent')),
        ('INVALID_TRACE', (activity['id'], 'trace:absent')),
    }


def test_candidate_finding_order_is_independent_of_provider_rule_order():
    graph = graph_scope()
    rule_ids = ['rule:zeta', 'rule:alpha', 'rule:middle']
    findings = []
    for ordering in (rule_ids, list(reversed(rule_ids))):
        candidate = one_activity_candidate(graph)
        next(iter(candidate['activities'].values()))['rule_ids'] = ordering
        with pytest.raises(DomainError) as raised:
            accept_candidate(model_for_graph(graph), graph, candidate)
        findings.append(raised.value.findings)

    assert findings[0] == findings[1]
    assert findings[0][0]['subject_ids'] == [
        'activity:provider-one', 'rule:alpha', 'rule:middle', 'rule:zeta']


def test_candidate_fingerprint_finding_names_the_graph_scope():
    graph = graph_scope()
    candidate = one_activity_candidate(graph)
    candidate['input_fingerprint'] = 'f' * 64

    findings = candidate_scope_findings(graph, candidate)

    fingerprint = next(
        finding for finding in findings
        if finding['message'] == (
            'Candidate input fingerprint differs from its graph scope'))
    assert fingerprint['subject_ids'] == [graph['scope_id']]


def test_verification_envelope_findings_name_affected_subjects():
    graph = graph_scope()
    anchor_id = graph['canonical_anchor_ids'][0]
    report = record(
        'VerificationReport', scope_id='scope:other',
        input_fingerprint='f' * 64, verdict='pass',
        checked_subject_ids=sorted(required_scope_subjects(graph)),
        findings=[record(
            'VerificationFinding', id='verification_finding:blocking',
            category='missing_activity', severity='blocking',
            message='A required activity is missing.',
            subject_ids=[anchor_id])])

    findings = verification_report_findings(graph, report)

    assert len(findings) == 3
    assert all(finding['subject_ids'] for finding in findings)
    passing = next(
        finding for finding in findings
        if finding['message'] == (
            'Passing verification cannot contain a blocking finding'))
    assert passing['subject_ids'] == [anchor_id, graph['scope_id']]


def test_semantic_outcome_summary_exposes_verdict_and_record_counts():
    graph = graph_scope(1)
    candidate = one_activity_candidate(graph)
    report = record(
        'VerificationReport', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'], verdict='fail',
        findings=[record(
            'VerificationFinding', id='verification_finding:blocking',
            category='missing_activity', severity='blocking',
            message='A required activity is missing.',
            subject_ids=graph['canonical_anchor_ids'])],
        checked_subject_ids=graph['canonical_anchor_ids'])

    verification = Synthesis._outcome_summary('verify', report)
    synthesis = Synthesis._outcome_summary('synthesize', candidate)

    assert verification == {
        'summary': 'verdict fail, 1 finding(s), 1 blocking',
        'level': 'warning',
        'details': {
            'verdict': 'fail',
            'finding_count': 1,
            'blocking_finding_count': 1,
        },
    }
    assert synthesis == {
        'summary': '1 activities, 0 rules, 0 domains',
        'level': 'step',
        'details': {
            'record_counts': {
                'activities': 1,
                'rules': 0,
                'domains': 0,
            },
        },
    }


# Deterministic closure fields and repair scope
#
# An activity's bindings and effects, an information use's traces, bindings
# and effects, and the support ceiling of a rule on an unresolved trace are
# derived from the graph. They are set before identities are allocated, so a
# provider is never judged on them and an identity never moves because of them.

def closure_graph():
    graph = graph_scope(anchor_count=1)
    context = graph['context']
    context['resources']['resource:owners'] = record(
        'Resource', id='resource:owners', kind='table', name='owners',
        evidence_ids=['ev:fixture'], resolution='resolved')
    context['traces']['trace:fixture'].update(
        symbol_ids=['symbol:handler'], edge_ids=['edge:write'])
    context['edges'] = {'edge:write': record(
        'Edge', id='edge:write', kind='writes_data',
        from_ref={'kind': 'symbol', 'id': 'symbol:handler'},
        to_ref={'kind': 'resource', 'id': 'resource:owners'},
        binding_ids=['binding:in'], evidence_ids=['ev:fixture'],
        resolution='unresolved', reason='Commit is not established.')}
    context['bindings'] = {
        'binding:in': record(
            'Binding', id='binding:in', name='owner', direction='input',
            source={'kind': 'symbol', 'id': 'symbol:handler'},
            target={'kind': 'resource', 'id': 'resource:owners'},
            evidence_ids=['ev:fixture'], resolution='resolved'),
        'binding:out': record(
            'Binding', id='binding:out', name='saved', direction='output',
            source={'kind': 'symbol', 'id': 'symbol:handler'},
            target={'kind': 'symbol', 'id': 'symbol:handler'},
            evidence_ids=['ev:fixture'], resolution='resolved')}
    context['effects'] = {'effect:write': record(
        'Effect', id='effect:write', kind='data_write', edge_id='edge:write',
        origin_ref={'kind': 'symbol', 'id': 'symbol:handler'},
        target={'kind': 'resource', 'id': 'resource:owners'},
        trace_ids=['trace:fixture'], evidence_ids=['ev:fixture'],
        resolution='unresolved', reason='Commit is not established.')}
    return graph


def closure_candidate(graph, *, bindings=(), effects=(), rule_status='conditional',
                      use_resources=('resource:owners',)):
    candidate = record(
        'CandidatePayload', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'])
    candidate['concepts']['concept:owner'] = record(
        'Concept', id='concept:owner', name='Owner',
        qualified_type_names=['fixture.Owner'], evidence_ids=['ev:fixture'])
    candidate['rules']['rule:admin'] = record(
        'Rule', id='rule:admin', name='Owner writes require a role',
        predicate_or_formula='hasRole(OWNER_ADMIN)', outcome='403 otherwise',
        evaluation_kind='predicate', category='authorization',
        basis=['source_observed'], enforcement_status=rule_status,
        evidence_ids=['ev:fixture'])
    candidate['activities']['activity:register'] = record(
        'Activity', id='activity:register', name='Register owner',
        description='Register a pet owner.',
        anchor_ids=graph['canonical_anchor_ids'], trace_ids=['trace:fixture'],
        concept_ids=['concept:owner'], rule_ids=['rule:admin'],
        input_binding_ids=list(bindings), output_binding_ids=list(bindings),
        effect_ids=list(effects), evidence_ids=['ev:fixture'],
        implementation_status='implementation_unresolved', support='partial')
    candidate['information_uses']['information_use:register'] = record(
        'InformationUse', id='information_use:register',
        activity_id='activity:register', concept_id='concept:owner',
        access='creates', resource_ids=list(use_resources),
        evidence_ids=['ev:fixture'])
    return candidate


def test_normalization_derives_activity_closure_fields_from_the_graph():
    graph = closure_graph()
    normalized = normalize_ids(closure_candidate(graph), graph)
    activity, = normalized['activities'].values()
    assert activity['input_binding_ids'] == ['binding:in']
    assert activity['output_binding_ids'] == ['binding:out']
    assert activity['effect_ids'] == ['effect:write']
    use, = normalized['information_uses'].values()
    assert activity['information_use_ids'] == [use['id']]


def test_activity_identity_ignores_provider_closure_lists():
    graph = closure_graph()
    empty = normalize_ids(closure_candidate(graph), graph)
    copied = normalize_ids(closure_candidate(
        graph, bindings=['binding:in'], effects=['effect:write']), graph)
    assert sorted(empty['activities']) == sorted(copied['activities'])
    assert empty == copied


def test_information_use_closure_fields_are_derived_and_ungrounded_uses_are_kept():
    graph = closure_graph()
    use, = normalize_ids(closure_candidate(graph), graph)['information_uses'].values()
    assert (use['trace_ids'], use['binding_ids'], use['effect_ids']) == (
        ['trace:fixture'], ['binding:in'], ['effect:write'])
    # A use naming a resource its activity never reaches is left as proposed,
    # for acceptance and Verify to reject.
    graph['context']['resources']['resource:pets'] = record(
        'Resource', id='resource:pets', kind='table', name='pets',
        evidence_ids=['ev:fixture'], resolution='resolved')
    stray, = normalize_ids(closure_candidate(
        graph, use_resources=('resource:pets',)), graph)['information_uses'].values()
    assert (stray['trace_ids'], stray['binding_ids'], stray['effect_ids']) == ([], [], [])


def test_rule_enforcement_on_an_unresolved_trace_is_capped_before_verification():
    graph = closure_graph()
    normalized = normalize_ids(closure_candidate(graph, rule_status='verified_on_trace'), graph)
    rule, = normalized['rules'].values()
    assert rule['enforcement_status'] == 'declared_only'
    plain = normalize_ids(closure_candidate(graph), graph)
    assert sorted(plain['rules']) == sorted(normalized['rules'])
    graph['context']['traces']['trace:fixture'].update(resolution='resolved', reason=None)
    resolved = normalize_ids(closure_candidate(graph, rule_status='verified_on_trace'), graph)
    assert next(iter(resolved['rules'].values()))['enforcement_status'] == 'verified_on_trace'


def test_repair_restores_unasked_same_identity_revisions():
    graph = graph_scope(anchor_count=1)
    previous = normalize_ids(shared_anchor_candidate(graph), graph)
    named, unnamed = sorted(previous['activities'])
    repaired = copy.deepcopy(previous)
    repaired['activities'][named]['description'] = 'Requested correction.'
    repaired['activities'][unnamed]['description'] = 'Unrequested rewording.'
    changes = normalize_repair_payload(record(
        'RepairPayload', parent_candidate_hash=digest(previous), candidate=repaired),
        graph, previous, digest(previous))['identity_changes']
    findings = [{'subject_ids': [named]}]

    kept, remaining, restored = Synthesis._restore_out_of_scope_revisions(
        previous, repaired, changes, findings, None)

    assert restored == [unnamed]
    assert kept['activities'][unnamed] == previous['activities'][unnamed]
    assert kept['activities'][named]['description'] == 'Requested correction.'
    assert Synthesis._repair_regressions(previous, remaining, findings, None) == []


def test_repair_still_rejects_out_of_scope_changes_it_cannot_restore():
    graph = graph_scope(anchor_count=1)
    previous = normalize_ids(shared_anchor_candidate(graph), graph)
    named, unnamed = sorted(previous['activities'])
    replacement = copy.deepcopy(previous)
    # Re-identifying an unnamed activity is not a same-identity revision.
    replacement['activities'][unnamed]['anchor_ids'] = []
    replacement = normalize_ids(replacement, graph)
    changes = normalize_repair_payload(record(
        'RepairPayload', parent_candidate_hash=digest(previous), candidate=replacement),
        graph, previous, digest(previous))['identity_changes']
    findings = [{'subject_ids': [named]}]

    kept, remaining, restored = Synthesis._restore_out_of_scope_revisions(
        previous, replacement, changes, findings, None)

    assert restored == []
    assert unnamed in Synthesis._repair_regressions(previous, remaining, findings, None)


# Branch-scoped closure
#
# One UI action can route the same submit to different endpoints under
# different conditions (PetEditor: POST for a new pet, PUT for an existing
# one).  An activity that claims one branch's endpoint anchor owns that
# branch's work only; the sibling branch belongs to the activity claiming it.

def ref(kind, identifier):
    return {'kind': kind, 'id': identifier}


def forked_model(*, put_reaches_save=False, root_symbol='symbol:submit'):
    def edge(identifier, kind, source, target, bindings=(), condition=None):
        return {'id': identifier, 'kind': kind, 'from_ref': ref('symbol', source),
                'to_ref': target, 'binding_ids': list(bindings), 'evidence_ids': [],
                'condition': condition}
    edges = [
        edge('edge:request', 'calls', 'symbol:submit', ref('symbol', 'symbol:send')),
        edge('edge:post', 'routes_to', 'symbol:submit', ref('symbol', 'symbol:add'),
             condition='pet.isNew'),
        edge('edge:put', 'routes_to', 'symbol:submit', ref('symbol', 'symbol:update'),
             condition='!(pet.isNew)'),
        edge('edge:save', 'calls', 'symbol:add', ref('symbol', 'symbol:save')),
        edge('edge:write', 'writes_data', 'symbol:save', ref('resource', 'resource:pets'),
             ['binding:pet']),
    ]
    if put_reaches_save:
        edges.append(edge('edge:put-save', 'calls', 'symbol:update', ref('symbol', 'symbol:save')))
    anchors = {
        'anchor:submit': {'symbol_id': root_symbol, 'representations': []},
        'anchor:post': {'symbol_id': None,
                        'representations': [{'symbol_id': 'symbol:add'}]},
        'anchor:put': {'symbol_id': 'symbol:update', 'representations': []},
    }
    bindings = {
        bid: {'id': bid, 'direction': 'input', 'source': ref('symbol', source),
              'evidence_ids': []}
        for bid, source in (('binding:pet', 'symbol:save'), ('binding:form', 'symbol:send'),
                            ('binding:contract', 'symbol:update'))}
    effects = {
        'effect:request': {'id': 'effect:request', 'edge_id': 'edge:request',
                           'trace_ids': ['trace:submit'], 'evidence_ids': []},
        'effect:write': {'id': 'effect:write', 'edge_id': 'edge:write',
                         'trace_ids': ['trace:submit'], 'evidence_ids': []},
    }
    trace = {'id': 'trace:submit', 'anchor_id': 'anchor:submit',
             'symbol_ids': ['symbol:submit', 'symbol:send', 'symbol:add',
                            'symbol:update', 'symbol:save'],
             'edge_ids': [item['id'] for item in edges]}
    return {'anchors': anchors, 'traces': {'trace:submit': trace},
            'edges': {item['id']: item for item in edges},
            'bindings': bindings, 'effects': effects, 'information_uses': {}}


def forked_activity(*anchor_ids):
    return {'id': 'activity:fork', 'anchor_ids': ['anchor:submit', *anchor_ids],
            'trace_ids': ['trace:submit'], 'concept_ids': ['concept:pet']}


def test_activity_closure_excludes_the_sibling_branch_it_does_not_claim():
    model = forked_model()
    update = activity_closure(model, forked_activity('anchor:put'))
    assert update['effect_ids'] == {'effect:request'}
    assert update['input_binding_ids'] == {'binding:form', 'binding:contract'}
    create = activity_closure(model, forked_activity('anchor:post'))
    assert create['effect_ids'] == {'effect:request', 'effect:write'}
    assert create['input_binding_ids'] == {'binding:form', 'binding:pet'}


def test_activity_closure_keeps_the_whole_trace_without_a_branch_claim():
    model = forked_model()
    everything = {'effect:request', 'effect:write'}
    assert activity_closure(model, forked_activity())['effect_ids'] == everything
    assert activity_closure(
        model, forked_activity('anchor:post', 'anchor:put'))['effect_ids'] == everything
    # Models without anchor records keep the trace-wide closure.
    assert activity_closure({**model, 'anchors': {}},
                            forked_activity('anchor:put'))['effect_ids'] == everything


def test_activity_closure_keeps_work_reached_through_the_claimed_branch():
    model = forked_model(put_reaches_save=True)
    assert activity_closure(model, forked_activity('anchor:put'))['effect_ids'] == {
        'effect:request', 'effect:write'}


def test_information_use_cannot_claim_a_sibling_branch_write():
    model = forked_model()
    use = {'activity_id': 'activity:fork', 'concept_id': 'concept:pet',
           'access': 'creates', 'resource_ids': ['resource:pets']}
    model['activities'] = {'activity:fork': forked_activity('anchor:post')}
    assert information_use_closure(model, use)['effect_ids'] == {'effect:write'}
    model['activities'] = {'activity:fork': forked_activity('anchor:put')}
    with pytest.raises(DomainError) as error:
        information_use_closure(model, use)
    assert error.value.code == 'INVALID_REFERENCE'


def test_normalization_scopes_shared_trace_effects_to_the_claimed_branch():
    graph = closure_graph()
    context = graph['context']
    context['anchors']['anchor:fixture-00']['symbol_id'] = 'symbol:handler'
    for name in ('create', 'update'):
        context['anchors'][f'anchor:{name}'] = record(
            'Anchor', id=f'anchor:{name}', kind='http', source_id='resource:fixture',
            canonical_anchor_id=f'anchor:{name}', symbol_id=f'symbol:{name}',
            resolution='unresolved', reason='Fixture endpoint')
        context['edges'][f'edge:{name}'] = record(
            'Edge', id=f'edge:{name}', kind='routes_to',
            from_ref={'kind': 'symbol', 'id': 'symbol:handler'},
            to_ref={'kind': 'symbol', 'id': f'symbol:{name}'},
            condition='pet.isNew' if name == 'create' else '!(pet.isNew)',
            evidence_ids=['ev:fixture'], resolution='resolved')
    # The write moves behind the create branch.
    context['edges']['edge:write']['from_ref'] = {'kind': 'symbol', 'id': 'symbol:create'}
    context['traces']['trace:fixture'].update(
        symbol_ids=['symbol:handler', 'symbol:create', 'symbol:update'],
        edge_ids=['edge:create', 'edge:update', 'edge:write'])
    candidate = closure_candidate(graph, use_resources=())
    candidate['information_uses'] = {}
    activity = candidate['activities']['activity:register']

    activity['anchor_ids'] = [*graph['canonical_anchor_ids'], 'anchor:update']
    update, = normalize_ids(candidate, graph)['activities'].values()
    activity['anchor_ids'] = [*graph['canonical_anchor_ids'], 'anchor:create']
    create, = normalize_ids(candidate, graph)['activities'].values()

    assert update['effect_ids'] == []
    assert create['effect_ids'] == ['effect:write']


def test_routes_without_exclusive_conditions_are_not_sibling_branches():
    everything = {'effect:request', 'effect:write'}
    for post, put in (('pet.isNew', 'pet.isNew'), (None, None), ('pet.isNew', None),
                      ('pet.isNew', 'owner.isNew')):
        model = forked_model()
        model['edges']['edge:post']['condition'] = post
        model['edges']['edge:put']['condition'] = put
        # Both requests may run in one submit, so the save stays this activity's work.
        assert activity_closure(model, forked_activity('anchor:put'))['effect_ids'] == everything


def test_trace_anchor_without_a_symbol_keeps_the_whole_trace():
    model = forked_model(root_symbol=None)
    assert activity_closure(model, forked_activity('anchor:put'))['effect_ids'] == {
        'effect:request', 'effect:write'}
    use = {'activity_id': 'activity:fork', 'concept_id': 'concept:pet',
           'access': 'creates', 'resource_ids': ['resource:pets']}
    model['activities'] = {'activity:fork': forked_activity('anchor:put')}
    assert information_use_closure(model, use)['effect_ids'] == {'effect:write'}
