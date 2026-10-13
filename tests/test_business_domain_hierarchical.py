"""Hierarchical business-domain discovery for repositories too large for one request.

The tech spec ("Large-repository hierarchical mode", BD-14, BD-40) selects
hierarchical mode when a scope's complete synthesis, verification, repair and
reverification sequence does not fit one request. The fixtures here are small
and `max_request_input_tokens` is lowered to the allowance that forces each
partition; see tests/business_domains/oversized_fixture.py.

The first section holds the foundation: fixtures, calibration and the fit rule
that selects the mode. The second holds BD-40's acceptance behaviour. Each of
those tests is a strict expected failure until the phase named in its marker
implemented it; every marker has now come off.
"""
import copy


from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import copy_facts, settings
from lib.context.business_domain_synthesis import Synthesis
from lib.context.business_domains import discover, load
from tests.business_domains.oversized_fixture import (
    InterruptingProvider, ReconcilingProvider, calibrate, force_split, write_long_chain,
    write_monolith, write_monorepo,
)
from tests.business_domains.provider_fixture import PassingProvider, write_service


def _facts(root):
    facts, _ = Extractor(root, settings({})).extract()
    return facts


def _names(facts, trace):
    return {facts['symbols'][symbol_id]['qualified_name'].split('::')[-1]
            for symbol_id in trace['symbol_ids']}


def _synthesis(root, config=None):
    facts = _facts(root)
    model = copy_facts(facts, 'fit')
    synthesis = Synthesis(root, settings(config or {}), PassingProvider(),
                          copy.deepcopy(facts['limits']))
    return synthesis, synthesis.graph_scope(copy.deepcopy(model))


# ── Foundation: fixtures ───────────────────────────────────────────────

def test_the_monolith_has_entry_points_that_share_one_helper_module(tmp_path):
    facts = _facts(write_monolith(tmp_path, entry_points=8))

    assert len(facts['anchors']) == 8
    assert all(anchor['resolution'] == 'resolved' for anchor in facts['anchors'].values())
    # Every entry point's trace reaches the shared helpers: overlapping shared code.
    assert all({'normalise', 'audit'} <= _names(facts, trace)
               for trace in facts['traces'].values())


def test_the_long_chain_is_one_entry_point_with_one_large_trace(tmp_path):
    facts = _facts(write_long_chain(tmp_path, steps=24))

    [trace] = facts['traces'].values()
    assert len(facts['anchors']) == 1
    assert {f'step_{index}' for index in range(24)} <= _names(facts, trace)


def test_the_monorepo_has_one_deployable_boundary_per_service(tmp_path):
    facts = _facts(write_monorepo(tmp_path, entry_points=3))

    services = {resource['name'] for resource in facts['resources'].values()
                if resource['kind'] == 'service'}
    assert services == {'services/billing', 'services/catalog', 'services/shipping'}
    assert len(facts['anchors']) == 9


# ── Foundation: calibration and the fit rule ───────────────────────────

def test_calibration_finds_an_allowance_that_splits_the_monolith(tmp_path):
    calibration = calibrate(write_monolith(tmp_path, entry_points=8))
    allowance = calibration.splitting_allowance()

    assert len(calibration.anchors) == 8
    assert all(calibration.allowance(size) <= allowance
               for size in calibration.anchors.values())
    assert calibration.allowance(calibration.whole) > allowance


def test_the_whole_graph_fits_under_the_default_allowance(tmp_path):
    synthesis, graph = _synthesis(write_monolith(tmp_path))

    assert synthesis.sequence_fits(graph)


def test_a_lowered_request_allowance_makes_the_whole_graph_not_fit(tmp_path):
    root = write_monolith(tmp_path)
    allowance = calibrate(root).splitting_allowance()

    synthesis, graph = _synthesis(root, force_split(allowance))

    assert not synthesis.sequence_fits(graph)


def test_the_fit_rule_also_honours_the_build_budget(tmp_path):
    root = write_monolith(tmp_path)
    synthesis, graph = _synthesis(root)
    budget = 4 * graph['estimated_input_tokens'] + 4 * synthesis.effective_request_output_tokens

    # The request cap may not exceed the build cap, so both are lowered; each
    # request still fits, but four of them do not fit the build.
    tight, _ = _synthesis(root, {'business_domains': {
        'max_build_input_tokens': budget - 1, 'max_request_input_tokens': budget - 1}})

    assert synthesis.sequence_fits(graph)
    assert not tight.sequence_fits(graph)


# ── Foundation: what must not change ───────────────────────────────────

def test_a_repository_that_fits_still_runs_as_one_whole_graph_scope(tmp_path):
    write_service(tmp_path)

    model, status = discover(tmp_path, provider=PassingProvider())

    assert model is not None
    assert status['execution_mode'] == 'whole_graph'
    assert status['limits']['semantic_units_total'] == 1


# ── BD-40 acceptance ───────────────────────────────────────────────────

def _split_monolith(root, entry_points=8, concurrency=None):
    write_monolith(root, entry_points=entry_points)
    config = force_split(calibrate(root).splitting_allowance())
    if concurrency is not None:
        # An interruption after N synthesis requests names N validated slices
        # only when slices run one at a time.
        config['business_domains']['provider_concurrency'] = concurrency
    return config


def _requests(provider, kind, operation='synthesize'):
    return [request['graph'] for request in provider.requests
            if request['operation'] == operation
            and request['graph']['scope_kind'] == kind]




def test_an_oversized_monolith_publishes_through_entry_point_bundles(tmp_path):
    config = _split_monolith(tmp_path)
    provider = ReconcilingProvider()

    model, status = discover(tmp_path, config, provider=provider)

    slices = _requests(provider, 'slice')
    [root] = _requests(provider, 'reconciliation')
    assert model is not None and status['phase'] in {'complete', 'partial'}
    assert status['execution_mode'] == 'hierarchical' and status['root_reconciled']
    assert len(slices) >= 2
    assert {graph['partition_strategy'] for graph in slices} == {'entrypoint_bundle'}
    # Every canonical anchor is in exactly one bundle, and the root reconciles
    # every bundle.
    bundled = [anchor for graph in slices for anchor in graph['canonical_anchor_ids']]
    assert sorted(bundled) == sorted(model['anchors'])
    assert sorted(root['child_scope_ids']) == sorted(graph['scope_id'] for graph in slices)
    assert status['limits']['semantic_units_total'] == len(slices) + 1
    assert status['limits']['semantic_units_pending'] == 0


def test_every_anchor_is_accounted_for_after_root_reconciliation(tmp_path):
    config = _split_monolith(tmp_path)

    model, _ = discover(tmp_path, config, provider=ReconcilingProvider())

    represented = {anchor for activity in model['activities'].values()
                   for anchor in activity['anchor_ids']}
    unassigned = {item['subject_id'] for item in model['unassigned']}
    assert represented | unassigned == set(model['anchors'])


def test_unfinished_slice_work_never_publishes(tmp_path):
    config = _split_monolith(tmp_path, concurrency=1)

    provider = InterruptingProvider(allowed=1)

    model, status = discover(tmp_path, config, provider=provider)

    # One bundle validated before the interruption; none of it is published.
    assert status['execution_mode'] == 'hierarchical'
    assert len(_requests(provider, 'slice')) >= 1
    assert model is None and load(tmp_path)[0] is None
    assert status['phase'] in {'failed', 'unavailable'}
    assert status['root_reconciled'] is False
    assert status['limits']['semantic_units_pending'] > 0


def test_a_slice_carries_the_shared_code_its_entry_points_reach(tmp_path):
    config = _split_monolith(tmp_path)
    provider = ReconcilingProvider()

    discover(tmp_path, config, provider=provider)

    slices = _requests(provider, 'slice')
    assert len(slices) >= 2
    for graph in slices:
        names = {symbol['qualified_name'].split('::')[-1]
                 for symbol in graph['context']['symbols'].values()}
        assert {'normalise', 'audit'} <= names
        # Shared code is overlap, not a boundary: its edges are declared
        # cross-scope so reconciliation can recognise the shared records.
        assert graph['cross_scope_edge_ids']


def test_the_partition_is_deterministic(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir(); second.mkdir()
    providers = []
    for root in (first, second):
        config = _split_monolith(root)
        providers.append(ReconcilingProvider())
        discover(root, config, provider=providers[-1])

    # Slices run concurrently, so requests arrive in any order; the plan does not.
    plans = [sorted((graph['partition_strategy'], graph['canonical_anchor_ids'])
                    for graph in _requests(provider, 'slice')) for provider in providers]
    assert len(plans[0]) >= 2 and plans[0] == plans[1]


def test_a_single_oversized_trace_is_cut_into_execution_segments(tmp_path):
    root = write_long_chain(tmp_path, steps=24)
    calibration = calibrate(root)
    config = force_split(calibration.allowance(int(calibration.whole * 0.8)))
    provider = ReconcilingProvider()

    model, status = discover(root, config, provider=provider)

    segments = _requests(provider, 'slice')
    assert model is not None and status['root_reconciled']
    assert len(segments) >= 2
    assert {graph['partition_strategy'] for graph in segments} == {'execution_segment'}
    cuts = [obligation for graph in segments
            for obligation in graph['context']['trace_obligations'].values()
            if obligation['kind'] == 'execution_segment']
    assert cuts and all(graph['cross_scope_edge_ids'] for graph in segments)
    # Segments cannot dispose of the anchor; only the root does.
    [anchor_id] = model['anchors']
    represented = {anchor for activity in model['activities'].values()
                   for anchor in activity['anchor_ids']}
    assert anchor_id in represented | {item['subject_id'] for item in model['unassigned']}


def test_an_interrupted_run_resumes_from_its_validated_slices(tmp_path):
    config = _split_monolith(tmp_path, concurrency=1)
    discover(tmp_path, config, provider=InterruptingProvider(allowed=1))
    # The same provider, no longer interrupted: cached responses are keyed by
    # the provider, so a different one would rightly start afresh.
    resumed = InterruptingProvider(allowed=100)

    model, status = discover(tmp_path, config, provider=resumed)

    total_slices = status['limits']['semantic_units_total'] - 1
    assert model is not None and status['root_reconciled']
    # The slice validated before the interruption is reused, not re-requested.
    assert len(_requests(resumed, 'slice')) == total_slices - 1


def test_progress_counts_validated_slices_before_root_reconciliation(tmp_path):
    config = _split_monolith(tmp_path, concurrency=1)

    _, status = discover(tmp_path, config, provider=InterruptingProvider(allowed=1))

    assert status['limits']['semantic_units_validated'] == 1
    assert status['limits']['semantic_units_pending'] == status['limits']['semantic_units_total'] - 1


def test_a_monorepo_is_sliced_by_application_boundary_first(tmp_path):
    root = write_monorepo(tmp_path, entry_points=3)
    config = force_split(calibrate(root).splitting_allowance())
    provider = ReconcilingProvider()

    model, status = discover(root, config, provider=provider)

    slices = _requests(provider, 'slice')
    assert model is not None and status['root_reconciled']
    assert {graph['partition_strategy'] for graph in slices} <= {
        'application_boundary', 'entrypoint_bundle'}
    services = {}
    for graph in slices:
        files = {model['symbols'][model['anchors'][anchor]['symbol_id']]['file'].split('/')[1]
                 for anchor in graph['canonical_anchor_ids']}
        assert len(files) == 1, 'a slice never mixes services'
        services.setdefault(files.pop(), []).append(graph)
    assert set(services) == {'billing', 'catalog', 'shipping'}


# ── Phase 2 details: the root, the budget and the provider boundary ────

class _Capture(ReconcilingProvider):
    """Record every scope sent for synthesis."""

    @property
    def scopes(self):
        return [request['graph'] for request in self.requests
                if request['operation'] == 'synthesize']


def _root_context(provider):
    return next(graph['context'] for graph in provider.scopes
                if graph['scope_kind'] == 'reconciliation')


def test_the_root_carries_semantic_records_not_the_raw_graph(tmp_path):
    config = _split_monolith(tmp_path)
    provider = _Capture()

    discover(tmp_path, config, provider=provider)

    [root] = [graph for graph in provider.scopes if graph['scope_kind'] == 'reconciliation']
    slices = [graph for graph in provider.scopes if graph['scope_kind'] == 'slice']
    context = root['context']
    # Raw graph records stay identity-only references...
    assert not context['traces'] and not context['edges'] and not context['bindings']
    assert {ref['collection'] for ref in context['record_refs'].values()} >= {'traces', 'anchors'}
    # ...while every slice's activities arrive, one per anchor it held, with the
    # excerpts they cite.
    held = sorted(anchor for graph in slices for anchor in graph['canonical_anchor_ids'])
    assert sorted(anchor for activity in context['activities'].values()
                  for anchor in activity['anchor_ids']) == held
    cited = {eid for activity in context['activities'].values()
             for eid in activity['evidence_ids']}
    assert cited <= set(context['evidence'])
    assert root['estimated_input_tokens'] < sum(graph['estimated_input_tokens'] for graph in slices)


def test_each_child_has_its_own_coverage_manifest_and_citations(tmp_path):
    config = _split_monolith(tmp_path)
    provider = _Capture()

    discover(tmp_path, config, provider=provider)

    context = _root_context(provider)
    slices = [graph for graph in provider.scopes if graph['scope_kind'] == 'slice']
    manifests = {claim['subject_id']: claim for claim in context['claims'].values()
                 if claim['kind'] == 'coverage_manifest'}
    assert set(manifests) == {graph['scope_id'] for graph in slices}
    for graph in slices:
        manifest = manifests[graph['scope_id']]
        assert all(anchor_id in manifest['text'] for anchor_id in graph['canonical_anchor_ids'])
        # A manifest cites its own child's evidence, never another child's.
        assert set(manifest['evidence_ids']) <= set(graph['context']['evidence'])


def test_the_build_budget_is_reserved_for_the_root_before_any_request(tmp_path):
    config = _split_monolith(tmp_path)
    # Each bundle's own sequence fits four requests' worth of budget; the
    # bundles plus the root's reserved allowance do not.
    config['business_domains']['max_build_input_tokens'] = (
        config['business_domains']['max_request_input_tokens'] * 4)
    provider = ReconcilingProvider()

    model, status = discover(tmp_path, config, provider=provider)

    assert model is None and provider.calls == 0
    assert status['error']['code'] == 'BUILD_BUDGET'
    assert 'root reconciliation' in status['error']['message']
    assert 'nothing was dispatched' in status['error']['message']


def test_the_reservation_covers_every_slice_and_the_complete_root(tmp_path):
    config = _split_monolith(tmp_path)
    output = ReconcilingProvider.provider_max_output_tokens
    # Two slices' synthesis and verification plus the root's four requests,
    # less one token: the run must not start.
    config['business_domains'].update(max_request_output_tokens=output,
                                      max_build_output_tokens=(2 * 2 + 4) * output - 1)

    model, status = discover(tmp_path, config, provider=ReconcilingProvider())

    assert model is None and status['error']['code'] == 'BUILD_BUDGET'
    assert 'max_build_output_tokens' in status['error']['message']
    assert status['limits']['semantic_units_validated'] == 0


def test_a_budget_too_small_for_one_entry_point_names_the_budget(tmp_path):
    config = _split_monolith(tmp_path)
    config['business_domains']['max_build_input_tokens'] = (
        config['business_domains']['max_request_input_tokens'])

    model, status = discover(tmp_path, config, provider=ReconcilingProvider())

    assert model is None and status['error']['code'] == 'BUILD_BUDGET'
    assert 'max_build_input_tokens' in status['error']['message']


def _slice(anchors, dispositions, activities):
    from lib.context.business_domain_work import SEMANTIC_COLLECTIONS, slice_unit
    scope = {'scope_id': 'scope:child', 'canonical_anchor_ids': anchors,
             'cross_scope_edge_ids': [], 'partition_strategy': 'entrypoint_bundle'}
    payload = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    payload['activities'] = {activity_id: {'anchor_ids': anchor_ids}
                             for activity_id, anchor_ids in activities.items()}
    payload['dispositions'] = [
        {'subject_kind': 'anchor', 'subject_id': anchor_id, 'status': status,
         'reason': reason, 'evidence_ids': ['ev:x'] if reason else []}
        for anchor_id, status, reason in dispositions]
    return slice_unit(scope, payload)


def test_a_root_that_drops_a_represented_anchor_is_sent_back_for_repair():
    from lib.context.business_domain_work import reconciliation_findings
    child = _slice(['anchor:a', 'anchor:b'],
                   [('anchor:a', 'represented', None), ('anchor:b', 'represented', None)],
                   {'activity:a': ['anchor:a'], 'activity:b': ['anchor:b']})
    root = {collection: {} for collection in ('activities', 'information_uses',
                                              'relationships', 'domains', 'rules')}
    root['activities'] = {'activity:a': {'anchor_ids': ['anchor:a']}}
    root['dispositions'] = [{'subject_kind': 'child_scope', 'subject_id': 'scope:child',
                             'status': 'represented',
                             'incorporated_record_ids': ['activity:a', 'activity:z']}]

    findings = reconciliation_findings({}, [child], root)

    assert {finding['code'] for finding in findings} == {'INVALID_COVERAGE'}
    assert ['anchor:b'] in [finding['subject_ids'] for finding in findings]
    assert any('activity:z' in finding['subject_ids'] for finding in findings)


def test_an_anchor_a_child_excluded_keeps_that_disposition():
    from lib.context.business_domain_work import reconciled_unit, unassigned_anchors
    child = _slice(['anchor:a', 'anchor:x'],
                   [('anchor:a', 'represented', None), ('anchor:x', 'excluded', 'Test support only.')],
                   {'activity:a': ['anchor:a']})
    root = reconciled_unit({'scope_id': 'scope:root'},
                           {'activities': {'activity:a': {'anchor_ids': ['anchor:a']}}}, [child])

    [kept] = unassigned_anchors(root)

    assert (kept['subject_id'], kept['status'], kept['reason']) == (
        'anchor:x', 'excluded', 'Test support only.')


def test_slices_and_the_root_cross_the_projected_provider_wire(tmp_path):
    from lib.context.business_domain_synthesis import ProviderProjection
    config = _split_monolith(tmp_path)
    provider = _Capture()

    discover(tmp_path, config, provider=provider)

    # The CLI provider receives the compact projection, which must close every
    # reference and round-trip exactly; construction proves both.
    kinds = set()
    for graph in provider.scopes:
        ProviderProjection(graph)
        kinds.add(graph['scope_kind'])
    assert kinds == {'slice', 'reconciliation'}


def test_published_coverage_counts_every_anchor(tmp_path):
    config = _split_monolith(tmp_path)

    model, status = discover(tmp_path, config, provider=ReconcilingProvider())

    assert model['coverage']['anchors_processed'] == len(model['anchors'])
    assert model['coverage']['anchors_pending'] == 0
    assert status['coverage'] == model['coverage']


# ── Phase 3: recursion and durable repair ──────────────────────────────

def test_a_root_too_large_for_one_request_is_reconciled_in_levels(tmp_path):
    root = write_monolith(tmp_path, entry_points=16)
    calibration = calibrate(root)
    # Room for one entry point per bundle: sixteen bundles, whose records
    # together exceed one reconciliation request.
    config = force_split(calibration.allowance(max(calibration.anchors.values())) + 400)
    # Sixteen slices' synthesis and verification, the root and its levels.
    config['business_domains']['max_build_output_tokens'] = 1_000_000
    provider = _Capture()

    model, status = discover(root, config, provider=provider)

    reconciliations = [graph for graph in provider.scopes
                       if graph['scope_kind'] == 'reconciliation']
    [top] = [graph for graph in reconciliations if graph['parent_scope_id'] is None]
    levels = [graph for graph in reconciliations if graph['parent_scope_id'] is not None]
    slices = [graph for graph in provider.scopes if graph['scope_kind'] == 'slice']
    assert model is not None and status['root_reconciled']
    assert levels and set(top['child_scope_ids']) <= {graph['scope_id'] for graph in
                                                      levels + slices}
    assert {graph['scope_id'] for graph in levels} <= set(top['child_scope_ids'])
    represented = {anchor for activity in model['activities'].values()
                   for anchor in activity['anchor_ids']}
    assert represented == set(model['anchors'])
    assert status['limits']['semantic_units_total'] == len(slices) + len(levels) + 1
    assert status['limits']['semantic_units_validated'] == status['limits']['semantic_units_total']


def _pending(root):
    return sorted((root / '.speed/context/business-domain-pending').glob('*.json'))


def test_an_interrupted_repair_chain_resumes_where_it_stopped(tmp_path):
    from tests.business_domains.oversized_fixture import RepairingProvider
    write_service(tmp_path)

    _, failed = discover(tmp_path, provider=RepairingProvider(rejections=1, interruptions=9))
    [checkpoint] = _pending(tmp_path)
    resumed = RepairingProvider(rejections=0)
    model, status = discover(tmp_path, provider=resumed)

    assert failed['phase'] in {'failed', 'unavailable'}
    assert model is not None and status['phase'] in {'complete', 'partial'}
    # The candidate and its rejection were kept: the chain continues with a
    # repair, not a fresh synthesis.
    assert [request['operation'] for request in resumed.requests][0] == 'repair'
    assert not any(request['operation'] == 'synthesize' for request in resumed.requests)
    assert not checkpoint.exists() and not _pending(tmp_path)


def test_a_completed_or_exhausted_repair_chain_leaves_no_checkpoint(tmp_path):
    from tests.business_domains.oversized_fixture import RepairingProvider
    write_service(tmp_path)

    model, _ = discover(tmp_path, provider=RepairingProvider(rejections=1))

    assert model is not None and not _pending(tmp_path)

    other = tmp_path / 'exhausted'
    other.mkdir()
    write_service(other)
    _, status = discover(other, provider=RepairingProvider(rejections=99))

    assert status['error']['code'] == 'SEMANTIC_VERIFICATION_FAILED'
    assert not _pending(other)


def test_a_checkpoint_from_another_provider_is_discarded(tmp_path):
    from tests.business_domains.oversized_fixture import RepairingProvider
    write_service(tmp_path)
    discover(tmp_path, provider=RepairingProvider(rejections=1, interruptions=9))
    [checkpoint] = _pending(tmp_path)

    model, _ = discover(tmp_path, provider=ReconcilingProvider())

    assert model is not None and not checkpoint.exists()


def test_a_slice_interrupted_mid_repair_resumes_in_hierarchical_mode(tmp_path):
    from tests.business_domains.oversized_fixture import RepairingProvider
    config = _split_monolith(tmp_path, concurrency=1)

    discover(tmp_path, config, provider=RepairingProvider(rejections=1, interruptions=9))
    assert len(_pending(tmp_path)) == 1
    resumed = RepairingProvider(rejections=0)
    model, status = discover(tmp_path, config, provider=resumed)

    assert model is not None and status['root_reconciled']
    assert resumed.requests[0]['operation'] == 'repair'
    assert not _pending(tmp_path)


def test_the_provider_schema_names_exactly_the_subjects_a_scope_requires(tmp_path):
    from lib.context.business_domain_schema import required_scope_subjects
    from lib.context.business_domain_synthesis import wire_schema
    config = _split_monolith(tmp_path)
    provider = _Capture()

    discover(tmp_path, config, provider=provider)

    for graph in provider.scopes:
        required = sorted(required_scope_subjects(graph))
        report = wire_schema('VerificationReport', graph)
        candidate = wire_schema('CandidatePayload', graph)
        assert report['properties']['checked_subject_ids']['items']['enum'] == required
        assert all(variant['properties']['subject_id']['enum'] == required
                   for variant in candidate['$defs']['ScopeDisposition']['anyOf'])



# ── Phase 4: application boundaries ────────────────────────────────────

def _services(model, graph):
    return {model['symbols'][model['anchors'][anchor]['symbol_id']]['file'].split('/')[1]
            for anchor in graph['canonical_anchor_ids']}


def test_each_service_that_fits_is_one_application_boundary_slice(tmp_path):
    root = write_monorepo(tmp_path, entry_points=3)
    calibration = calibrate(root)
    provider = _Capture()

    model, status = discover(root, force_split(calibration.splitting_allowance()),
                             provider=provider)

    slices = [graph for graph in provider.scopes if graph['scope_kind'] == 'slice']
    assert model is not None and status['root_reconciled']
    assert sorted(graph['partition_strategy'] for graph in slices) == ['application_boundary'] * 3
    assert sorted(_services(model, graph).pop() for graph in slices) == [
        'billing', 'catalog', 'shipping']
    assert all(len(graph['canonical_anchor_ids']) == 3 for graph in slices)


def test_a_service_too_large_for_one_request_is_bundled_within_itself(tmp_path):
    root = write_monorepo(tmp_path, services=('billing', 'catalog'), entry_points=2)
    write_monorepo(tmp_path, services=('ledger',), entry_points=8)
    calibration = calibrate(root)
    provider = _Capture()

    model, status = discover(root, force_split(calibration.splitting_allowance()),
                             provider=provider)

    slices = [graph for graph in provider.scopes if graph['scope_kind'] == 'slice']
    by_strategy = {}
    for graph in slices:
        assert len(_services(model, graph)) == 1, 'a slice never spans two services'
        by_strategy.setdefault(graph['partition_strategy'], set()).update(
            _services(model, graph))
    assert model is not None and status['root_reconciled']
    assert by_strategy['entrypoint_bundle'] == {'ledger'}
    assert by_strategy['application_boundary'] == {'billing', 'catalog'}


def test_a_single_service_repository_goes_straight_to_entry_point_bundles(tmp_path):
    config = _split_monolith(tmp_path)
    provider = _Capture()

    discover(tmp_path, config, provider=provider)

    assert {graph['partition_strategy'] for graph in provider.scopes
            if graph['scope_kind'] == 'slice'} == {'entrypoint_bundle'}


def test_the_root_receives_a_structured_manifest_for_every_child(tmp_path):
    config = _split_monolith(tmp_path)
    provider = _Capture()

    discover(tmp_path, config, provider=provider)

    [root] = [graph for graph in provider.scopes if graph['scope_kind'] == 'reconciliation']
    slices = {graph['scope_id']: graph for graph in provider.scopes
              if graph['scope_kind'] == 'slice'}
    manifests = {item['child_scope_id']: item for item in root['coverage_manifests']}
    assert set(manifests) == set(slices) == set(root['child_scope_ids'])
    for scope_id, manifest in manifests.items():
        represented = {item['anchor_id'] for item in manifest['represented']}
        assert represented == set(slices[scope_id]['canonical_anchor_ids'])
        contributed = set(manifest['contributed_record_ids'])
        assert {activity for item in manifest['represented']
                for activity in item['activity_ids']} <= contributed
        assert contributed <= {record_id for collection in ('activities', 'claims', 'domains',
                                                            'rules', 'concepts')
                               for record_id in root['context'][collection]}


# ── Compact reconciliation ─────────────────────────────────────────────

def test_the_root_answers_with_changes_and_keeps_the_rest_by_id(tmp_path):
    config = _split_monolith(tmp_path)
    provider = _Capture()

    model, _ = discover(tmp_path, config, provider=provider)

    [root] = [graph for graph in provider.scopes if graph['scope_kind'] == 'reconciliation']
    root_answer = provider._reconcile(root, set())
    # One activity per anchor in every slice: nothing to merge, everything kept.
    assert root_answer['activities'] == {}
    kept = {record_id for disposition in root_answer['dispositions']
            for record_id in disposition['incorporated_record_ids']}
    assert kept == set(root['context']['activities'])
    # The published model holds every kept activity with the claims it rests on.
    assert len(model['activities']) == len(model['anchors'])
    assert all(set(activity['claim_ids']) <= set(model['claims'])
               for activity in model['activities'].values())


def test_expansion_carries_kept_records_and_drops_merged_ones():
    from lib.context.business_domain_work import SEMANTIC_COLLECTIONS, expand_reconciliation
    context = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    context['activities'] = {
        'activity:kept': {'id': 'activity:kept', 'anchor_ids': ['anchor:a'],
                          'claim_ids': ['claim:kept'], 'rule_ids': ['rule:r']},
        'activity:part1': {'id': 'activity:part1', 'anchor_ids': ['anchor:b'],
                           'claim_ids': ['claim:part1'], 'rule_ids': []},
        'activity:part2': {'id': 'activity:part2', 'anchor_ids': ['anchor:b'],
                           'claim_ids': ['claim:part2'], 'rule_ids': []}}
    context['claims'] = {name: {'id': name, 'subject_id': subject, 'kind': 'behavior'}
                         for name, subject in (('claim:kept', 'activity:kept'),
                                               ('claim:part1', 'activity:part1'),
                                               ('claim:part2', 'activity:part2'))}
    context['rules'] = {'rule:r': {'id': 'rule:r'}}
    scope = {'scope_kind': 'reconciliation', 'context': context}
    answer = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    answer['activities'] = {'activity:merged': {'id': 'activity:merged', 'anchor_ids': ['anchor:b'],
                                                'claim_ids': [], 'rule_ids': []}}
    answer['dispositions'] = [{'subject_kind': 'child_scope', 'subject_id': 'scope:child',
                               'status': 'represented',
                               'incorporated_record_ids': ['activity:kept', 'activity:part1',
                                                           'activity:part2']}]

    complete = expand_reconciliation(scope, answer)

    assert set(complete['activities']) == {'activity:kept', 'activity:merged'}
    # The merged activity states no claims of its own, so the claims about the
    # parts it replaced now describe it.
    assert {claim_id: claim['subject_id'] for claim_id, claim in complete['claims'].items()} == {
        'claim:kept': 'activity:kept', 'claim:part1': 'activity:merged',
        'claim:part2': 'activity:merged'}
    assert set(complete['rules']) == {'rule:r'}


def test_segments_reconcile_into_one_activity_per_anchor(tmp_path):
    root = write_long_chain(tmp_path, steps=24)
    calibration = calibrate(root)
    config = force_split(calibration.allowance(int(calibration.whole * 0.8)))

    model, _ = discover(root, config, provider=ReconcilingProvider())

    [activity] = model['activities'].values()
    assert activity['anchor_ids'] == list(model['anchors'])
