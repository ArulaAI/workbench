"""Whole-graph provider fixtures shared by public discovery tests."""
import copy

from lib.context.business_domain_schema import (
    DEFINITIONS, DomainError, record, required_scope_subjects,
)


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


def write_service(root):
    (root / 'service.py').write_text(
        "@app.post('/orders')\n"
        "def create(order):\n"
        "    return order\n")


class PassingProvider:
    """Produce one evidenced domain and pass independent verification."""

    model = 'fixture'
    provider_context_tokens = 200_000
    provider_max_output_tokens = 8_000
    output_limit_enforcement = 'provider'

    def __init__(self):
        self.requests = []
        self.fail = False

    @property
    def calls(self):
        return len(self.requests)

    def generate(self, request, schema, *_):
        self.requests.append(copy.deepcopy(request))
        if self.fail:
            raise DomainError('PROVIDER_FAILED', 'Fixture provider unavailable',
                              retryable=True)
        operation = request['operation']
        graph = request['graph']
        evidence_ids = sorted(request['allowed_evidence_ids'])
        trace_ids = sorted(graph['context']['traces'])
        anchor_ids = sorted(graph['canonical_anchor_ids'])

        if operation == 'verify':
            payload = record('VerificationReport', scope_id=graph['scope_id'],
                input_fingerprint=graph['input_fingerprint'], verdict='pass',
                findings=[], checked_subject_ids=sorted(required_scope_subjects(graph)))
            output_type = 'VerificationReport'
        elif operation == 'synthesize':
            support = ('supported' if all(
                trace['resolution'] == 'resolved'
                for trace in graph['context']['traces'].values()) else 'partial')
            activity = record('Activity', id='activity:fixture', name='Create orders',
                description='Accept an order through the evidenced endpoint.',
                anchor_ids=anchor_ids, trace_ids=trace_ids,
                evidence_ids=evidence_ids, claim_ids=['claim:activity-fixture'],
                support=support)
            domain = record('Domain', id='domain:fixture', name='Order management',
                summary='Owns evidenced order behavior.',
                boundary_rationale='The supplied endpoint changes order state.',
                activity_memberships=[record('ActivityMembership',
                    activity_id=activity['id'], role='primary',
                    claim_ids=['claim:domain-fixture'])],
                evidence_ids=evidence_ids, claim_ids=['claim:domain-fixture'],
                support=support)
            claims = {
                'claim:activity-fixture': record('Claim',
                    id='claim:activity-fixture', subject_id=activity['id'],
                    text=activity['description'], kind='behavior',
                    evidence_ids=evidence_ids, trace_ids=trace_ids,
                    semantic_review='uncertain'),
                'claim:domain-fixture': record('Claim', id='claim:domain-fixture',
                    subject_id=domain['id'], text=domain['boundary_rationale'],
                    kind='boundary', evidence_ids=evidence_ids,
                    semantic_review='uncertain'),
            }
            dispositions = []
            for index, (subject_id, subject_kind) in enumerate(
                    sorted(required_scope_subjects(graph).items())):
                values = {'status': 'represented',
                          'activity_ids': [activity['id']]}
                if subject_kind != 'anchor':
                    values = {
                        'status': 'excluded',
                        'reason': 'The unresolved correspondence adds no separate behavior.',
                        'evidence_ids': evidence_ids,
                    }
                dispositions.append(record('ScopeDisposition',
                    id=f'disposition:fixture-{index}',
                    subject_kind=subject_kind, subject_id=subject_id, **values))
            payload = record('CandidatePayload', scope_id=graph['scope_id'],
                input_fingerprint=graph['input_fingerprint'],
                activities={activity['id']: activity}, domains={domain['id']: domain},
                claims=claims, dispositions=dispositions)
            output_type = 'CandidatePayload'
        else:
            raise AssertionError('Valid fixture candidate must not require repair')
        return encode(payload, DEFINITIONS[output_type]), {
            'last': {'inputTokens': 10, 'outputTokens': 10}}
