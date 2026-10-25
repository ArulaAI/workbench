"""Support caps applied before Verify, and prompt-cache token accounting."""
import copy
import json
import os
import subprocess
from pathlib import Path

from lib.context.business_domain_schema import DEFINITIONS, record, required_scope_subjects
from lib.context.business_domain_synthesis import _reported_usage, normalize_ids
from tests.test_business_domain_candidate_protocol import (
    ProtocolProvider, graph_scope, one_activity_candidate, synthesis, validate_candidate)

ROOT = Path(__file__).resolve().parents[1]


def resolved(graph):
    graph = copy.deepcopy(graph)
    graph['context']['traces']['trace:fixture'].update(resolution='resolved', reason=None)
    return graph


def supported_candidate(graph):
    candidate = one_activity_candidate(graph)
    candidate['activities']['activity:provider-one']['support'] = 'supported'
    candidate['domains']['domain:all'] = record(
        'Domain', id='domain:all', name='All', summary='Everything.',
        boundary_rationale='One fixture domain.', evidence_ids=['ev:fixture'],
        claim_ids=['claim:provider-one'], support='supported',
        activity_memberships=[record('ActivityMembership', activity_id='activity:provider-one',
                                     role='primary', claim_ids=['claim:provider-one'])])
    return candidate


def only(records):
    [value] = records.values()
    return value


def test_a_supported_activity_on_an_unresolved_trace_is_partial_before_verify():
    graph = graph_scope(anchor_count=1)
    normalized = normalize_ids(supported_candidate(graph), graph)
    assert only(normalized['activities'])['support'] == 'partial'
    # Domain support is the provider's call; nothing deterministic changes it.
    assert only(normalized['domains'])['support'] == 'supported'


def test_a_supported_activity_on_resolved_traces_keeps_its_support():
    graph = resolved(graph_scope(anchor_count=1))
    normalized = normalize_ids(supported_candidate(graph), graph)
    assert only(normalized['activities'])['support'] == 'supported'
    assert only(normalized['domains'])['support'] == 'supported'


def test_an_activity_citing_a_trace_outside_the_graph_is_left_for_acceptance():
    graph = graph_scope(anchor_count=1)
    candidate = supported_candidate(graph)
    candidate['activities']['activity:provider-one']['trace_ids'] = ['trace:elsewhere']
    normalized = normalize_ids(candidate, graph)
    assert only(normalized['activities'])['support'] == 'supported'


def test_reported_usage_keeps_the_prompt_cache_split(tmp_path):
    path = tmp_path / 'usage.json'
    path.write_text(json.dumps({'inputTokens': 100, 'outputTokens': 5,
                                'cacheReadInputTokens': 80, 'cacheCreationInputTokens': 15}))
    assert _reported_usage(path) == {'inputTokens': 100, 'outputTokens': 5,
                                     'cacheReadInputTokens': 80,
                                     'cacheCreationInputTokens': 15}


class CachingProvider(ProtocolProvider):
    def generate(self, request, schema, *args):
        value, _ = super().generate(request, schema, *args)
        return value, {'last': {'inputTokens': 100, 'outputTokens': 10,
                                'cacheReadInputTokens': 70, 'cacheCreationInputTokens': 20}}


def test_a_run_adds_up_prompt_cache_tokens_and_records_them_per_response(tmp_path):
    graph = graph_scope()
    provider = CachingProvider(graph)
    runner = synthesis(tmp_path, provider)
    runner.run(graph, lambda value: validate_candidate(graph, value))
    calls = len(provider.requests)
    assert runner.counters['input_cache_read_tokens_reported'] == 70 * calls
    assert runner.counters['input_cache_creation_tokens_reported'] == 20 * calls
    responses = [json.loads(path.read_text())['response']
                 for path in (tmp_path / '.speed/context/business-domain-cache').glob('*.json')
                 if json.loads(path.read_text()).get('kind') == 'response']
    assert responses and all(response['usage']['cache_read_input_tokens'] == 70
                             for response in responses)


def test_claude_provider_reports_the_prompt_cache_split(tmp_path):
    events = tmp_path / 'events.jsonl'
    events.write_text(json.dumps({'type': 'result', 'usage': {
        'input_tokens': 10, 'cache_read_input_tokens': 900,
        'cache_creation_input_tokens': 90, 'output_tokens': 40}},
        separators=(',', ':')) + '\n')
    usage = tmp_path / 'usage.json'
    subprocess.run(['bash', '-c', f'source "{ROOT}/providers/claude-code.sh"; '
                    f'_claude_report_usage "{events}" "{usage}"'], check=True)
    reported = json.loads(usage.read_text())
    assert reported['inputTokens'] == 1000
    assert reported['cacheReadInputTokens'] == 900
    assert reported['cacheCreationInputTokens'] == 90


def test_usage_fields_are_optional_in_saved_responses():
    usage = DEFINITIONS['ProviderUsage']
    assert set(usage['required']) == {'input_tokens', 'output_tokens'}
    assert {'cache_read_input_tokens', 'cache_creation_input_tokens'} <= set(usage['properties'])


# Repair answers keep their records' aliases

def repair_id_pattern(record_type):
    from lib.context.business_domain_synthesis import wire_schema
    schema = wire_schema('RepairPayload', graph_scope(anchor_count=1))
    return schema['$defs'][record_type]['properties']['id']['pattern']


def test_a_repair_answer_may_keep_a_record_under_its_alias():
    import re
    pattern = repair_id_pattern('Activity')
    assert re.match(pattern, '_ref:12')
    assert re.match(pattern, 'activity:_ref:12')
    assert re.match(pattern, 'activity:new-one')
    assert not re.match(pattern, 'claim:new-one')
    assert not re.match(pattern, 'Create orders')


def test_new_synthesis_records_still_need_their_prefix():
    import re
    from lib.context.business_domain_synthesis import wire_schema
    schema = wire_schema('CandidatePayload', graph_scope(anchor_count=1))
    assert not re.match(schema['$defs']['Activity']['properties']['id']['pattern'], '_ref:12')


def test_a_kept_alias_decodes_to_the_record_it_names(tmp_path):
    from lib.context.business_domain_synthesis import wire_schema
    graph = graph_scope()
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    candidate = normalize_ids(one_activity_candidate(graph), graph)
    activity_id = next(iter(candidate['activities']))
    report = record('VerificationReport', scope_id=graph['scope_id'],
                    input_fingerprint=graph['input_fingerprint'], verdict='fail',
                    findings=[record('VerificationFinding', id='verification_finding:x',
                                     category='incorrect_merge', severity='blocking',
                                     message='Split it.', subject_ids=[activity_id])],
                    checked_subject_ids=sorted(required_scope_subjects(graph)))
    request = runner.request_for('repair', graph, candidate, (), report)
    projected, _, projection = runner.project_exchange(
        request, wire_schema('RepairPayload', graph))
    shown = projected['candidate']['activities']
    [alias] = [key for key in shown]
    assert alias.startswith('_ref:') and shown[alias]['id'] == alias
    assert projection.decode_response(projected['candidate']) == candidate


def test_the_reference_rule_is_stated_once():
    from lib.context.business_domain_synthesis import PROJECTION_INSTRUCTIONS, wire_schema
    schema = json.dumps(wire_schema('RepairPayload', graph_scope(anchor_count=1)))
    assert 'References must identify' not in schema
    assert 'Kind: ' in schema
    assert 'never a name or another kind of record' in PROJECTION_INSTRUCTIONS


def test_verification_can_use_its_own_model(tmp_path):
    graph = graph_scope(anchor_count=1)
    runner = synthesis(tmp_path, ProtocolProvider(graph))
    runner.provider = None
    runner.agent_config = {'model': 'opus', 'verification_model': 'sonnet'}
    assert runner._model_for('verify') == 'sonnet'
    assert runner._model_for('synthesize') == 'opus'
    assert runner._model_for('repair') == 'opus'
    runner.agent_config = {'model': 'opus'}
    assert runner._model_for('verify') == 'opus'


def test_the_provider_config_lists_the_verification_model(tmp_path):
    (tmp_path / 'speed.toml').write_text('[agent]\nsupport_model = "opus"\n')
    command = ['bash', str(ROOT / 'lib/cmd/domains.sh'), 'config']
    plain = json.loads(subprocess.run(command, cwd=tmp_path, capture_output=True, text=True,
                                      check=True).stdout)
    assert plain['verification_model'] == plain['model']
    split = json.loads(subprocess.run(command, cwd=tmp_path, capture_output=True, text=True,
                                      check=True, env={**os.environ,
                                                       'SPEED_DISCOVER_VERIFICATION_MODEL': 'sonnet'}).stdout)
    assert split['verification_model'] == 'sonnet'
    assert 'sonnet' in split['models']
