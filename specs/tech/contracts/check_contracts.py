"""Check normative specimens and the boundary to the runtime contract copy."""
import copy
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).parent
SCHEMA = json.loads((ROOT / 'business-domain-artifacts.schema.json').read_text())
Draft202012Validator.check_schema(SCHEMA)

RUNTIME_SCHEMA_PATH = ROOT.parents[2] / 'lib/context/business_domain_artifacts.schema.json'
RUNTIME_SCHEMA = json.loads(RUNTIME_SCHEMA_PATH.read_text())


def validate_runtime_contract_alignment():
    """Reject any runtime/normative contract divergence."""
    Draft202012Validator.check_schema(RUNTIME_SCHEMA)
    assert canonical(RUNTIME_SCHEMA) == canonical(SCHEMA), (
        'Runtime and normative business-domain contracts differ',
    )

def validator(name):
    return Draft202012Validator({'$schema': SCHEMA['$schema'], '$defs': SCHEMA['$defs'],
                                '$ref': '#/$defs/' + name}, format_checker=FormatChecker())

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()

def sha(value):
    return hashlib.sha256(value).hexdigest()


validate_runtime_contract_alignment()

def request_key_material(request):
    return {key: value for key, value in request.items()
            if key not in ('request_id', 'deadline_at')}

def validate_limits(limits):
    assert limits['semantic_units_total'] == limits['semantic_units_validated'] + limits['semantic_units_pending']
    assert limits['effective_request_input_tokens'] <= limits['max_request_input_tokens']
    assert limits['effective_request_output_tokens'] <= limits['max_request_output_tokens']
    if limits['provider_context_tokens'] is not None:
        assert limits['effective_request_input_tokens'] <= limits['provider_context_tokens']
    if limits['provider_max_output_tokens'] is not None:
        assert limits['effective_request_output_tokens'] <= limits['provider_max_output_tokens']

def validate_graph(graph, published=False):
    closure(graph)
    anchor_ids = set(graph['anchors'])
    representations = {item['id']: item for anchor in graph['anchors'].values()
                       for item in anchor.get('representations', [])}
    correspondences = {item['id']: item for anchor in graph['anchors'].values()
                       for item in anchor.get('correspondences', [])}
    representation_ids = set(representations)
    assert all({item['from_representation'], *item['to_representations']}
               <= representation_ids for item in correspondences.values())
    assert all(anchor.get('canonical_anchor_id') in (None, anchor['id'])
               for anchor in graph['anchors'].values())
    if 'coverage' in graph:
        coverage = graph['coverage']
        correspondence_values = correspondences.values()
        canonicalized_representations = {
            ident for item in correspondence_values if item['state'] == 'resolved'
            for ident in {item['from_representation'], *item['to_representations']}}
        assert coverage['anchors_total'] == len(anchor_ids)
        assert coverage['representations_total'] == len(representation_ids)
        assert coverage['representations_canonicalized'] == len(canonicalized_representations)
        assert coverage['correspondences_ambiguous'] == sum(item['state'] == 'ambiguous' for item in correspondences.values())
        assert coverage['correspondences_unresolved'] == sum(item['state'] == 'unresolved' for item in correspondences.values())
        assert coverage['anchors_processed'] == sum(item['status'] == 'processed' for item in graph['anchors'].values())
        assert coverage['anchors_excluded'] == sum(item['status'] == 'excluded' for item in graph['anchors'].values())
        assert coverage['anchors_pending'] == sum(item['status'] in ('candidate', 'pending') for item in graph['anchors'].values())
    for trace in graph['traces'].values():
        obligations = [graph['trace_obligations'][ident] for ident in trace['obligation_ids']]
        if trace['resolution'] == 'unresolved':
            assert any(item['status'] != 'satisfied' for item in obligations), 'unresolved trace has no open obligation'
        if trace['resolution'] == 'resolved':
            assert all(item['status'] in ('satisfied', 'external') for item in obligations), 'resolved trace has open obligation'
    if published:
        assert all(anchor['status'] in ('processed', 'excluded') for anchor in graph['anchors'].values())

def validate_scope(scope):
    validate_graph(scope['context'])
    assert set(scope['source_representation_ids']) <= set(scope['context']['anchor_representations'])
    assert set(scope['canonical_anchor_ids']) <= set(scope['context']['anchors'])
    assert set(scope['cross_scope_edge_ids']) <= set(scope['context']['edges'])
    if scope['partition_strategy'] == 'execution_segment':
        obligations = scope['context']['trace_obligations'].values()
        assert any(item['kind'] == 'execution_segment' for item in obligations), 'execution segment lacks cut-edge obligation'
    if scope['scope_kind'] == 'whole_graph':
        assert set(scope['source_representation_ids']) == set(scope['context']['anchor_representations'])

def required_scope_subjects(scope):
    if scope['scope_kind'] == 'reconciliation':
        return {ident: 'child_scope' for ident in scope['child_scope_ids']}
    required = {ident: 'anchor' for ident in scope['canonical_anchor_ids']}
    supplied_representations = set(scope['source_representation_ids'])
    for ident, correspondence in scope['context']['anchor_correspondences'].items():
        if (correspondence['status'] in ('ambiguous', 'unresolved') and
                supplied_representations.intersection(correspondence['representation_ids'])):
            required[ident] = 'anchor_correspondence'
    return required

def validate_candidate(scope, candidate):
    if candidate is None:
        return
    dispositions = candidate['dispositions']
    assert len(dispositions) == len({item['subject_id'] for item in dispositions}), 'duplicate subject disposition'
    required = required_scope_subjects(scope)
    assert {item['subject_id'] for item in dispositions} == set(required), 'scope disposition coverage mismatch'
    for item in dispositions:
        assert item['subject_kind'] == required[item['subject_id']], 'scope disposition kind mismatch'
        assert set(item['activity_ids']) <= set(candidate['activities'])
        assert set(item['incorporated_record_ids']) <= (
            set(candidate['activities']) | set(candidate['domains']) | set(candidate['relationships']))

def closure(doc):
    ids = set()
    def collect(value):
        if isinstance(value, dict):
            if 'id' in value and isinstance(value['id'], str) and len(value) > 2:
                assert value['id'] not in ids, ('duplicate', value['id'])
                ids.add(value['id'])
            for key, item in value.items():
                if isinstance(item, dict) and 'id' in item and ':' in key:
                    assert key == item['id'], ('map key mismatch', key)
                collect(item)
        elif isinstance(value, list):
            for item in value: collect(item)
    collect(doc)
    def refs(value):
        if isinstance(value, dict):
            if set(value) == {'kind', 'id'}:
                assert value['id'] in ids, ('dangling typed reference', value)
            for key, item in value.items():
                if key.endswith('_ids') and isinstance(item, list):
                    for ident in item:
                        assert ident in ids, ('dangling reference', key, ident)
                if key.endswith('_id') and isinstance(item, str) and ':' in item:
                    assert item in ids, ('dangling reference', key, item)
                refs(item)
        elif isinstance(value, list):
            for item in value: refs(item)
    refs(doc)
    return ids

files = list((ROOT / 'examples').glob('*.json'))
documents = []
for path in files:
    doc = json.loads(path.read_text())
    name = next((v for suffix,v in {
        '.domain.json':'DomainArtifact', '.facts.json':'FactsArtifact',
        '.snapshot.json':'SnapshotArtifact', '.status.json':'StatusArtifact',
        '.overrides.json':'OverridesArtifact', '-request-cache.json':'CacheArtifact',
        '.digest-projection.json':'DigestDomainProjection', '-response-cache.json':'CacheArtifact',
    }.items() if path.name.endswith(suffix)), None)
    assert name, path
    validator(name).validate(doc)
    documents.append((path, name, doc))
    if name in ('DomainArtifact','FactsArtifact'):
        validate_graph(doc, published=name == 'DomainArtifact')
        fp = {k:v for k,v in doc['fingerprint'].items() if k != 'value'}
        assert sha(canonical(fp)) == doc['fingerprint']['value']
        for evidence in doc['evidence'].values():
            snapshot = doc['source_snapshots'][evidence['locator']['snapshot_id']]
            blob = json.loads((path.parent / snapshot['local_blob_path']).read_text())
            assert blob['source_hash'] == snapshot['content_hash']
            fragment = blob['fragments'][0]
            assert evidence['locator']['pointer'] == '/fragments/0/text'
            assert fragment['text'] == evidence['excerpt']
            assert sha(fragment['text'].encode()) == fragment['excerpt_hash'] == evidence['content_hash']
        for activity in doc.get('activities',{}).values():
            for direction in ('input','output'):
                assert all(doc['bindings'][i]['direction'] == direction for i in activity[direction+'_binding_ids'])
        limits = doc['limits']
        validate_limits(limits)
        if name == 'DomainArtifact':
            assert limits['semantic_units_pending'] == 0, 'published domain artifact contains unfinished semantic work'
    if name == 'StatusArtifact':
        limits = doc['limits']
        validate_limits(limits)
        if doc['phase'] in ('complete', 'partial'):
            assert limits['semantic_units_pending'] == 0, 'published status contains unfinished semantic work'
            assert doc['root_reconciled'], 'published status was not reconciled to its root scope'
    if name == 'DigestDomainProjection':
        status = doc['domain_status']
        limits = status['limits']
        validate_limits(limits)
        if status['phase'] in ('complete', 'partial'):
            assert limits['semantic_units_pending'] == 0, 'digest projects unfinished semantic work'
            assert status['root_reconciled'], 'digest projects an unreconciled hierarchy'
    if name == 'CacheArtifact':
        if doc['kind'] == 'request':
            request = doc['request']
            assert sha(canonical(request_key_material(request))) == doc['key']
            validate_scope(request['graph'])
            assert request['input_fingerprint'] == request['graph']['input_fingerprint']
            if request['candidate'] is not None:
                assert request['candidate']['scope_id'] == request['graph']['scope_id']
                assert request['candidate']['input_fingerprint'] == request['input_fingerprint']
            validate_candidate(request['graph'], request['candidate'])
        else:
            inputs = {k:doc[k] for k in ('request_key','prompt_hash','output_schema_hash','provider_fingerprint')}
            assert sha(canonical(inputs)) == doc['key']

request_cache = {doc['key']: doc['request'] for _, name, doc in documents
                 if name == 'CacheArtifact' and doc['kind'] == 'request'}
response_cache = {doc['key']: doc for _, name, doc in documents
                  if name == 'CacheArtifact' and doc['kind'] == 'response'}
for path, name, doc in documents:
    if name != 'CacheArtifact' or doc['kind'] != 'response':
        continue
    request = request_cache[doc['request_key']]
    response = doc['response']
    assert response['request_id'] == request['request_id'], path
    assert response['operation'] == request['operation'], path
    assert response['input_fingerprint'] == request['input_fingerprint'], path
    validate_candidate(request['graph'], response['candidate'])
    if response['verification_report'] is not None:
        report = response['verification_report']
        assert report['scope_id'] == request['graph']['scope_id'], path
        assert report['input_fingerprint'] == request['input_fingerprint'], path
        assert set(report['checked_subject_ids']) == set(required_scope_subjects(request['graph'])), path
    if response['operation'] == 'verify':
        assert doc['verification_response_key'] is None, path
    else:
        verification = response_cache[doc['verification_response_key']]
        verification_response = verification['response']
        assert verification_response['operation'] == 'verify', path
        assert verification_response['verification_report']['verdict'] == 'pass', path
        verification_request = request_cache[verification['request_key']]
        assert verification_request['candidate'] == response['candidate'], path
# Rejection checks exercise contract boundaries, not model quality.
m = json.loads((ROOT/'examples/api.domain.json').read_text())
for mutate in [lambda x: x.update(unexpected=True),
               lambda x: x.pop('effects'),
               lambda x: x['activities']['activity:api'].pop('output_binding_ids'),
               lambda x: x.update(status='failed')]:
    broken=copy.deepcopy(m); mutate(broken)
    try: validator('DomainArtifact').validate(broken)
    except ValidationError: pass
    else: raise AssertionError('invalid document accepted')
broken=copy.deepcopy(m)
broken['activities']['activity:api']['effect_ids']=['effect:missing']
try: closure(broken)
except AssertionError: pass
else: raise AssertionError('dangling effect accepted')

def assert_rejected(definition, document, message):
    try: validator(definition).validate(document)
    except ValidationError: pass
    else: raise AssertionError(message)

synthesis_request = json.loads((ROOT/'examples/api.synthesis-request-cache.json').read_text())['request']
invalid = copy.deepcopy(synthesis_request)
invalid['candidate'] = json.loads((ROOT/'examples/api.verification-request-cache.json').read_text())['request']['candidate']
assert_rejected('SemanticRequest', invalid, 'synthesis request with candidate accepted')

invalid = copy.deepcopy(synthesis_request['graph'])
invalid['context']['record_refs']['record:omitted'] = {
    'id': 'record:omitted', 'collection': 'symbols', 'content_hash': '0' * 64}
assert_rejected('GraphScope', invalid, 'whole graph with omitted record reference accepted')

verification_request = json.loads((ROOT/'examples/api.verification-request-cache.json').read_text())['request']
invalid = copy.deepcopy(verification_request)
invalid['operation'] = 'repair'
invalid['verification_report'] = {
    'scope_id': invalid['graph']['scope_id'],
    'input_fingerprint': invalid['input_fingerprint'],
    'verdict': 'pass', 'findings': [], 'checked_subject_ids': []}
assert_rejected('SemanticRequest', invalid, 'repair request with passing report accepted')

invalid = {
    'id': 'disposition:child', 'subject_kind': 'child_scope',
    'subject_id': 'scope:child', 'status': 'represented',
    'activity_ids': [], 'incorporated_record_ids': [], 'reason': None,
    'evidence_ids': []}
assert_rejected('ScopeDisposition', invalid, 'represented child with no incorporated records accepted')

synthesis_response = json.loads((ROOT/'examples/api.synthesis-response-cache.json').read_text())
invalid = copy.deepcopy(synthesis_response)
invalid['verification_response_key'] = None
assert_rejected('CacheArtifact', invalid, 'candidate response without verifier link accepted')

invalid = copy.deepcopy(m)
invalid['anchors']['anchor:api']['status'] = 'pending'
try: validate_graph(invalid, published=True)
except AssertionError: pass
else: raise AssertionError('published pending anchor accepted')

assert_rejected('Unassigned', {'subject_kind': 'anchor', 'subject_id': 'anchor:api',
                               'status': 'pending', 'reason': 'unfinished'},
                'published pending unassigned record accepted')

correspondence = copy.deepcopy(
    m['anchors']['anchor:api']['correspondences'][0])
correspondence['to_representations'] = []
assert_rejected('AnchorCorrespondence', correspondence,
                'correspondence without a target accepted')

correspondence = copy.deepcopy(
    m['anchors']['anchor:api']['correspondences'][0])
correspondence['state'] = 'ambiguous'
correspondence['reason'] = ''
assert_rejected('AnchorCorrespondence', correspondence,
                'ambiguous correspondence without a reason accepted')

print(f'PASS: schema, {len(files)} specimens, reference closure, source/excerpt hashes, semantic-unit accounting, request/response cache linkage, binding directions and 14 invalid variants.')
