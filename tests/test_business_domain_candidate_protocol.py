import copy
from itertools import product

import pytest

from lib.context.business_domain_schema import (
    DEFINITIONS, DomainError, candidate_scope_findings, digest, limits, record,
    required_scope_subjects, validate, validation_findings,
)
from lib.context.business_domain_synthesis import (
    ProviderProjection, Synthesis, agent_instructions, allowed_evidence_ids,
    normalize_ids, wire_schema,
)
from lib.context.business_domains import discover, paths


def encode(value, schema):
    if '$ref' in schema:
        return encode(value, DEFINITIONS[schema['$ref'].rsplit('/', 1)[1]])
    if value is None:
        return None
    if 'anyOf' in schema:
        return encode(value, schema['anyOf'][0])
    if (schema.get('type') == 'object'
            and isinstance(schema.get('additionalProperties'), dict)):
        return [encode(item, schema['additionalProperties'])
                for item in value.values()]
    if schema.get('type') == 'object':
        return {key: encode(item, schema['properties'][key])
                for key, item in value.items()}
    if schema.get('type') == 'array':
        return [encode(item, schema['items']) for item in value]
    return value


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
            payload = repaired_candidate(self.graph)
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
                subject_ids=self.graph['canonical_anchor_ids'])]
            payload = record(
                'VerificationReport', scope_id=self.graph['scope_id'],
                input_fingerprint=self.graph['input_fingerprint'],
                verdict=('pass' if passes else 'fail'), findings=findings,
                checked_subject_ids=checked)
        self.responses.append(copy.deepcopy(payload))
        return encode(payload, DEFINITIONS[
            'VerificationReport' if operation == 'verify'
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
                payload = repaired_candidate(graph)
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
