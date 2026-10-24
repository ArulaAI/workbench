"""Support caps applied before Verify, and prompt-cache token accounting."""
import copy
import json
import subprocess
from pathlib import Path

from lib.context.business_domain_schema import DEFINITIONS, record
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
