"""Activities of one anchor that derive identical lists divide one behaviour.

SPEED derives an activity's inputs, outputs and effects from the traces it
selects. Activities of one anchor whose derived lists are identical cannot be
told apart, and no repair of those lists can separate them. Acceptance reports
the split before verification, so repair merges the activities instead of a
verifier rejecting the derived lists round after round.
"""
from lib.context.business_domains import discover
from tests.business_domains.oversized_fixture import SplittingProvider, write_monolith


def test_a_split_trace_is_sent_to_repair_as_a_deterministic_finding(tmp_path):
    write_monolith(tmp_path, entry_points=2)
    provider = SplittingProvider()

    model, status = discover(tmp_path, provider=provider)

    [repair] = [request for request in provider.requests if request['operation'] == 'repair']
    codes = {finding['code'] for finding in repair['deterministic_findings']}
    assert 'INCORRECT_SPLIT' in codes
    assert model is not None and status['phase'] in {'complete', 'partial'}
    per_anchor = [anchor for activity in model['activities'].values()
                  for anchor in activity['anchor_ids']]
    assert len(per_anchor) == len(set(per_anchor))


def test_activities_of_one_anchor_with_distinct_traces_stay_valid():
    from tests.test_business_domain_candidate_protocol import (
        graph_scope, model_for_graph, shared_anchor_candidate)
    from lib.context.business_domain_synthesis import normalize_ids
    graph = graph_scope()

    candidate = normalize_ids(shared_anchor_candidate(graph), graph)

    traces = [tuple(activity['trace_ids']) for activity in candidate['activities'].values()]
    assert len(traces) == 2 and len(set(traces)) == 2
    assert model_for_graph(graph) is not None
