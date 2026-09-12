import copy
from pathlib import Path
import pytest

from lib.context.business_domains import discover, load, build_lock, paths
from lib.context.business_domain_schema import (
    DomainError, DEFINITIONS, REFERENCE_TARGETS, record, validate_evidence, validate_references, atomic_write,
    read_json,
)
from lib.context.business_domain_synthesis import STAGES


def encode(value, schema):
    if '$ref' in schema:
        return encode(value,DEFINITIONS[schema['$ref'].rsplit('/',1)[1]])
    if value is None:
        return None
    if 'anyOf' in schema:
        return encode(value,schema['anyOf'][0])
    if schema.get('type') == 'object' and isinstance(schema.get('additionalProperties'),dict):
        return [encode(v,schema['additionalProperties']) for v in value.values()]
    if schema.get('type') == 'object':
        return {k:encode(v,schema['properties'][k]) for k,v in value.items()}
    if schema.get('type') == 'array':
        return [encode(v,schema['items']) for v in value]
    return value


class Provider:
    """Control-flow fixture, deliberately not a domain-accuracy oracle."""
    model = 'fixture'
    def __init__(self):
        self.calls = 0
        self.fail = False

    def generate(self, request, schema, *args):
        self.calls += 1
        if self.fail:
            raise DomainError('PROVIDER_FAILED','Fixture provider unavailable')
        packet = request['packet']; stage = packet['stage']; context = packet['context']
        evidence = list(context['evidence'])
        if stage == 'grouping':
            evidence += [k for k,v in context['record_refs'].items() if v['collection'] == 'evidence']
        if stage == 'activity':
            activity = record('Activity',id='activity:fixture',name='Fixture activity',
                description='Behavior supplied by the control-flow fixture',
                anchor_ids=packet['anchor_ids'],trace_ids=list(context['traces']),
                evidence_ids=evidence,claim_ids=['claim:activity'],
                support=('supported' if all(trace['resolution'] == 'resolved'
                    for trace in context['traces'].values()) else 'partial'))
            payload = record('ActivityPayload',activities={activity['id']:activity},
                claims={'claim:activity':record('Claim',id='claim:activity',subject_id=activity['id'],
                    text=activity['description'],kind='behavior',evidence_ids=evidence,
                    trace_ids=list(context['traces']),semantic_review='uncertain')})
        elif stage == 'grouping':
            activity_ids = (list(context['activities'])
                            if context['activities'] else sorted({
                                membership['activity_id']
                                for domain in context['domains'].values()
                                for membership in domain['activity_memberships']}))
            domain = record('Domain',id='domain:fixture',name='Fixture responsibility',
                summary='Fixture grouping',boundary_rationale='Fixture evidence',evidence_ids=evidence,
                activity_memberships=[record('ActivityMembership',activity_id=activity_id,
                    role='primary',claim_ids=['claim:domain'])
                    for activity_id in activity_ids],claim_ids=['claim:domain'])
            payload = record('GroupingPayload',domains={domain['id']:domain},
                claims={'claim:domain':record('Claim',id='claim:domain',subject_id=domain['id'],
                    text=domain['boundary_rationale'],kind='boundary',evidence_ids=evidence,
                    semantic_review='uncertain')})
        else:
            payload = record('ReviewPayload',verdicts=[{'claim_id':cid,'verdict':'supported',
                'evidence_ids':evidence,'explanation':'Fixture verdict'} for cid in packet['claim_ids']])
        return encode(payload,DEFINITIONS[STAGES[stage][1]]), {'last':{'inputTokens':10,'outputTokens':10}}


def source(root):
    (root/'service.py').write_text("@app.post('/orders')\ndef create(order):\n    return order\n")


def replace_claims(model, claims):
    """Keep synthetic test models reference-closed after replacing claims."""
    model['claims'] = claims
    claim_ids = sorted(claims)
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'claim_ids':
                    value[key] = claim_ids
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for key, value in model.items():
        if key != 'claims':
            walk(value)


def test_provider_caps_are_identical_in_facts_status_and_published_model(tmp_path):
    class CappedProvider(Provider):
        provider_context_tokens = 15999
        provider_max_output_tokens = 1000
        output_limit_enforcement = 'provider'

        def generate(self,request,schema,*args):
            assert request['budget']['max_output_tokens'] == 1000
            return super().generate(request,schema,*args)

    source(tmp_path)
    model,status=discover(tmp_path,provider=CappedProvider())
    facts=read_json(paths(tmp_path)['facts'])
    expected={
        'provider_context_tokens':15999,
        'provider_max_output_tokens':1000,
        'effective_request_input_tokens':15999,
        'effective_request_output_tokens':1000,
        'output_limit_enforcement':'provider',
    }
    for artifact in (facts,status,model):
        assert {key:artifact['limits'][key] for key in expected} == expected


def test_refresh_publishes_evidence_and_unchanged_refresh_reuses_cache(tmp_path, monkeypatch):
    source(tmp_path); provider = Provider()
    model,status = discover(tmp_path,provider=provider)
    assert status['phase'] == 'partial', status
    assert len(model['domains']) == 1
    assert status['limits']['model_ready_graph_tokens'] > 0
    assert status['limits']['semantic_units_total'] > 0
    assert status['limits']['semantic_units_validated'] == status['limits']['semantic_units_total']
    assert status['limits']['semantic_units_pending'] == 0
    assert status['limits']['artifact_bytes'] == len(paths(tmp_path)['model'].read_bytes())
    assert model['limits']['semantic_units_total'] == status['limits']['semantic_units_total']
    assert model['limits']['semantic_units_validated'] == status['limits']['semantic_units_validated']
    assert model['limits']['semantic_units_pending'] == status['limits']['semantic_units_pending']
    validate_evidence(tmp_path,model)
    calls = provider.calls
    from lib.context.business_domain_synthesis import Synthesis
    def unexpected_probe(self):
        pytest.fail('A cache-only refresh entered the provider gate')
    monkeypatch.setattr(Synthesis, '_await_provider_gate', unexpected_probe)
    again,status = discover(tmp_path,provider=provider)
    assert status['phase'] == 'partial', status
    assert provider.calls == calls
    assert again['domains'] == model['domains']


def test_provider_implementation_change_promotes_valid_semantic_checkpoints(tmp_path):
    class ReplacementProvider(Provider):
        pass

    source(tmp_path)
    original = Provider()
    first, status = discover(tmp_path, provider=original)
    assert first and original.calls > 0, status

    replacement = ReplacementProvider()
    second, status = discover(tmp_path, provider=replacement)
    assert second and status['phase'] == 'partial', status
    assert replacement.calls == 0
    assert second['domains'] == first['domains']


def test_independent_verifier_repairs_shape_valid_fabricated_candidate(tmp_path):
    class VerifyingProvider(Provider):
        def __init__(self):
            super().__init__()
            self.requests = []

        def generate(self, request, schema, *args):
            self.requests.append(copy.deepcopy(request))
            value, usage = super().generate(request, schema, *args)
            if request['packet']['stage'] == 'activity':
                repaired = 'validation_feedback' in request
                value['claims'][0]['text'] = (
                    'Evidenced behavior' if repaired else 'Fabricated behavior')
            elif request['packet']['stage'] == 'evidence_review':
                claim = next(iter(request['packet']['context']['claims'].values()))
                value['verdicts'][0]['verdict'] = (
                    'unsupported' if claim['text'] == 'Fabricated behavior'
                    else 'supported')
            return value, usage

    source(tmp_path)
    provider = VerifyingProvider()
    model, status = discover(tmp_path, provider=provider)
    assert model and status['phase'] == 'partial', status
    repair = next(request['validation_feedback'] for request in provider.requests
                  if request['packet']['stage'] == 'activity'
                  and 'validation_feedback' in request)
    assert repair['repair_kind'] == 'semantic'
    assert repair['verification_report']
    assert repair['findings'][0]['code'] == 'SEMANTIC_VERIFICATION_FAILED'
    assert all(claim['text'] != 'Fabricated behavior'
               for claim in model['claims'].values())


def test_provider_failure_keeps_last_published_model(tmp_path):
    source(tmp_path); provider = Provider()
    model,status = discover(tmp_path,provider=provider)
    assert model
    (tmp_path/'service.py').write_text("@app.post('/orders')\ndef create(order):\n    return {'order':order}\n")
    provider.fail = True
    preserved,status = discover(tmp_path,provider=provider)
    assert status['phase'] == 'unavailable'
    assert preserved == model
    assert paths(tmp_path)['facts'].exists()


def test_legacy_publication_remains_readable_and_byte_preserved_on_failed_refresh(tmp_path):
    import json
    source(tmp_path)
    model, _ = discover(tmp_path, provider=Provider())
    model['schema_version'] = 1
    model.pop('trace_obligations')
    for trace in model['traces'].values():
        trace.pop('obligation_ids')
    publication = paths(tmp_path)['model']
    publication.write_text(json.dumps(model, indent=4)+'\n')
    original = publication.read_bytes()
    assert load(tmp_path)[0] == model
    (tmp_path/'service.py').write_text("@app.get('/changed')\ndef changed():\n    return 2\n")
    provider = Provider()
    provider.fail = True
    preserved, status = discover(tmp_path, provider=provider)
    assert status['phase'] == 'unavailable' and preserved == model
    assert publication.read_bytes() == original


def test_supported_review_cannot_promote_contract_only_behavior_to_implementation(tmp_path):
    (tmp_path/'api.yaml').write_text(
        'openapi: 3.0.1\npaths:\n  /visits:\n    post:\n      operationId: addVisit\n')
    model, status = discover(tmp_path, provider=Provider())
    assert model and status['phase'] == 'partial', status
    assert all(c['semantic_review'] == 'supported' for c in model['claims'].values())
    assert all(a['support'] == 'partial' for a in model['activities'].values())
    assert all(d['support'] == 'partial' and d['symbol_memberships'] == [] for d in model['domains'].values())


def test_publication_status_is_derived_from_coverage_and_declared_gaps():
    from lib.context.business_domains import publication_status
    from lib.context.business_domain_schema import DEFAULTS, limits

    model = record('DomainArtifact', limits=limits(DEFAULTS))
    assert publication_status(model, 'not_applicable') == 'complete'

    model['coverage']['anchors_pending'] = 1
    assert publication_status(model, 'not_applicable') == 'partial'
    model['coverage']['anchors_pending'] = 0
    model['capabilities'] = [record('Capability', adapter='fixture',
                                    adapter_version='1', feature='parsing',
                                    status='partial')]
    assert publication_status(model, 'not_applicable') == 'partial'


def test_activity_materialization_retains_deterministic_effects_and_bindings(tmp_path):
    (tmp_path/'billing.sql').write_text('''CREATE OR REPLACE PROCEDURE pay(amount IN NUMBER) IS
BEGIN
  INSERT INTO payments VALUES (amount);
END;
''')
    model, status = discover(tmp_path, provider=Provider())
    assert model and status['phase'] == 'partial', status
    activity = next(iter(model['activities'].values()))
    # Provider's fixture returns empty operation lists; the accepted trace owns closure.
    assert activity['effect_ids'] == sorted(model['effects'])
    assert activity['input_binding_ids'] == sorted(
        bid for bid, binding in model['bindings'].items() if binding['direction'] == 'input')
    assert activity['effect_ids'] and activity['input_binding_ids']
    assert activity['support'] == 'partial'
    activity['effect_ids'] = []
    with pytest.raises(DomainError, match='operation closure'):
        validate_references(model)


def test_information_use_materializes_from_selected_typed_operation(tmp_path):
    class InformationProvider(Provider):
        def generate(self, request, schema, *args):
            value, usage = super().generate(request, schema, *args)
            if request['packet']['stage'] != 'activity':
                return value, usage
            context = request['packet']['context']
            edge = next(edge for edge in context['edges'].values() if edge['kind'] == 'reads_data')
            concept = record('Concept', id='concept:order', name='Order')
            use = record('InformationUse', id='information_use:order-read',
                activity_id='activity:fixture', concept_id=concept['id'],
                resource_ids=[edge['to_ref']['id']], access='reads',
                evidence_ids=edge['evidence_ids'], resolution='unresolved',
                reason='Read is present; semantic interpretation remains partial.')
            value['activities'][0]['concept_ids'] = [concept['id']]
            value['concepts'].append(encode(concept, DEFINITIONS['Concept']))
            value['information_uses'].append(encode(use, DEFINITIONS['InformationUse']))
            return value, usage

    (tmp_path/'orders.sql').write_text('''CREATE OR REPLACE PROCEDURE load_order(order_id IN NUMBER) IS
BEGIN
  SELECT status INTO current_status FROM orders WHERE id = order_id;
END;
''')
    model, status = discover(tmp_path, provider=InformationProvider())
    assert model and status['phase'] == 'partial', status
    activity = next(iter(model['activities'].values()))
    use = next(iter(model['information_uses'].values()))
    edge = next(edge for edge in model['edges'].values() if edge['kind'] == 'reads_data')
    assert activity['information_use_ids'] == [use['id']]
    assert use['trace_ids'] == activity['trace_ids']
    assert use['binding_ids'] == edge['binding_ids']
    assert use['effect_ids'] == []
    assert set(edge['evidence_ids']) <= set(use['evidence_ids'])
    use['trace_ids'] = []
    with pytest.raises(DomainError, match='Information-use operation closure'):
        validate_references(model)


def test_no_provider_keeps_facts_without_fake_domains(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEED_PROVIDER", "missing-test-provider")
    source(tmp_path)
    model,status = discover(tmp_path)
    assert model is None
    assert status['phase'] == 'unavailable'
    assert paths(tmp_path)['facts'].exists()


@pytest.mark.parametrize('stage', ['activity', 'grouping', 'evidence_review'])
@pytest.mark.parametrize('code', ['BUILD_BUDGET', 'BUILD_TIMEOUT', 'PACKET_LIMIT', 'PROVIDER_BUDGET'])
def test_incomplete_semantic_work_never_replaces_publication(tmp_path, monkeypatch, stage, code):
    from lib.context.business_domain_synthesis import Synthesis
    source(tmp_path)
    provider = Provider()
    previous, status = discover(tmp_path, provider=provider)
    assert previous and status['phase'] == 'partial'
    published = paths(tmp_path)['model'].read_bytes()
    cache = {p: p.read_bytes() for p in
             (tmp_path/'.speed/context/business-domain-cache').glob('*.json')}
    (tmp_path/'service.py').write_text(
        "@app.post('/orders')\ndef create(order):\n    return {'changed': order}\n")
    original = Synthesis._run_once
    attempted_stages = []

    def limited(self, packet, *args):
        attempted_stages.append(packet['stage'])
        if packet['stage'] == stage:
            raise DomainError(code, 'Fixture semantic work limit')
        return original(self, packet, *args)

    monkeypatch.setattr(Synthesis, '_run_once', limited)
    preserved, status = discover(tmp_path, provider=provider)
    assert preserved == previous
    assert paths(tmp_path)['model'].read_bytes() == published
    assert paths(tmp_path)['facts'].exists()
    assert all(p.read_bytes() == content for p, content in cache.items())
    assert status['phase'] == 'failed' and status['freshness'] == 'stale'
    assert status['error']['code'] == code
    assert status['limits']['truncated'] is True
    diagnostic = next(w for w in status['warnings'] if w['code'] == code)
    assert diagnostic['subject_ids']
    assert attempted_stages[-1] == stage


def test_preflight_refuses_unit_when_complete_sequence_cannot_fit(tmp_path):
    class UnreportedUsageProvider(Provider):
        def generate(self, *args):
            value, _ = super().generate(*args)
            return value, {}

    source(tmp_path)
    provider = UnreportedUsageProvider()
    config = {'business_domains': {
        'max_request_output_tokens': 1000, 'max_build_output_tokens': 1000}}
    for _ in range(2):
        model, status = discover(tmp_path, config, provider)
        assert model is None and not paths(tmp_path)['model'].exists()
        assert status['phase'] == 'failed' and status['error']['code'] == 'BUILD_BUDGET'
        assert status['freshness'] == 'missing'
        assert provider.calls == 0
        assert status['limits']['completion_output_tokens_reserved'] == 0


def test_oversized_grouping_partitions_reconciles_and_reuses_cache(tmp_path, monkeypatch):
    from lib.context import business_domain_synthesis as synthesis
    source(tmp_path)
    provider = Provider()
    previous, _ = discover(tmp_path, provider=provider)
    published = paths(tmp_path)['model'].read_bytes()
    (tmp_path/'service.py').write_text('\n'.join(
        f"@app.post('/orders/{i}')\ndef create_{i}(order):\n    return order\n"
        for i in range(2)))
    def singleton_work(self, model, anchor_ids):
        from lib.context.business_domain_work import ActivityScope
        return [ActivityScope(f'scope:test-{index}', 'whole_graph',
                synthesis.packet_for(model, 'activity', [anchor_id]))
                for index, anchor_id in enumerate(sorted(anchor_ids))]

    monkeypatch.setattr(synthesis.Synthesis, 'activity_work', singleton_work)
    monkeypatch.setattr(
        synthesis.Synthesis, '_grouping_fits',
        lambda self, packet: (len(packet['activity_ids']) <= 1
                              or bool(packet['context']['domains'])))
    completed, status = discover(tmp_path, provider=provider)
    assert completed and completed != previous, status
    assert len(next(iter(completed['domains'].values()))[
        'activity_memberships']) == 2
    calls = provider.calls
    again, status = discover(tmp_path, provider=provider)
    assert again and status['phase'] == 'partial'
    assert provider.calls == calls


def test_deadline_expiring_during_final_validation_preserves_publication(tmp_path, monkeypatch):
    from lib.context import business_domains as discovery
    source(tmp_path)
    provider = Provider()
    previous, _ = discover(tmp_path, provider=provider)
    published = paths(tmp_path)['model'].read_bytes()
    baseline_dir = tmp_path/'.speed/context/business-domain-baselines'
    baselines = {path: path.read_bytes() for path in baseline_dir.glob('*.json')}
    (tmp_path/'service.py').write_text(
        "@app.post('/orders')\ndef create(order):\n    return {'changed': order}\n")
    clock = [100.0]
    monkeypatch.setattr(discovery.time, 'monotonic', lambda: clock[0])
    original = discovery.validate_evidence

    def validation_crosses_deadline(*args):
        result = original(*args)
        clock[0] = 1_000_000_000.0
        return result

    monkeypatch.setattr(discovery, 'validate_evidence', validation_crosses_deadline)
    preserved, status = discover(tmp_path, provider=provider)
    assert preserved == previous
    assert paths(tmp_path)['model'].read_bytes() == published
    assert {path: path.read_bytes() for path in baseline_dir.glob('*.json')} == baselines
    assert status['phase'] == 'failed' and status['error']['code'] == 'BUILD_TIMEOUT'


@pytest.mark.parametrize('stage', ['activity', 'grouping', 'evidence_review'])
def test_repeated_provider_failure_at_each_stage_preserves_publication(tmp_path, stage):
    class FailingStageProvider(Provider):
        failing_stage = None
        failures = 0

        def generate(self, request, schema, *args):
            if request['packet']['stage'] == self.failing_stage:
                self.failures += 1
                raise DomainError('PROVIDER_FAILED', 'Fixture transport failure')
            return super().generate(request, schema, *args)

    source(tmp_path)
    provider = FailingStageProvider()
    model, status = discover(tmp_path, provider=provider)
    assert model and status['phase'] == 'partial'
    published = paths(tmp_path)['model'].read_bytes()
    cache = {p: p.read_bytes() for p in
             (tmp_path/'.speed/context/business-domain-cache').glob('*.json')}
    (tmp_path/'service.py').write_text(
        "@app.post('/orders')\ndef create(order):\n    return {'changed': order}\n")
    provider.failing_stage = stage
    preserved, status = discover(tmp_path, provider=provider)
    assert status['phase'] == 'unavailable', status
    assert status['error']['code'] == 'PROVIDER_UNAVAILABLE'
    assert status['error']['retryable'] is False
    assert provider.failures == 2
    assert preserved == model
    assert paths(tmp_path)['model'].read_bytes() == published
    assert paths(tmp_path)['facts'].exists()
    assert all(p.read_bytes() == content for p, content in cache.items())
    provider.failing_stage = None
    recovered, status = discover(tmp_path, provider=provider)
    assert status['phase'] == 'partial' and recovered['build_id'] != model['build_id']


@pytest.mark.parametrize('concurrency', [1, 4])
def test_many_anchors_do_not_receive_independent_provider_retries(tmp_path, concurrency):
    (tmp_path/'service.py').write_text('\n'.join(
        f"@app.post('/orders/{i}')\ndef create_{i}(order):\n    return order\n"
        for i in range(20)))
    provider = Provider()
    provider.fail = True
    model, status = discover(tmp_path, {'business_domains': {'provider_concurrency': concurrency}}, provider=provider)
    assert model is None and status['phase'] == 'unavailable', status
    assert provider.calls == 2
    assert status['limits']['requests'] == 2
    assert status['limits']['retries'] == 1
    assert not list((tmp_path/'.speed/context/business-domain-cache').glob('*.json'))


@pytest.mark.parametrize('failure', [None, 'PROVIDER_FAILED', 'PROVIDER_CAPABILITY_UNAVAILABLE'])
def test_first_real_request_gates_fanout_before_reservations(tmp_path, monkeypatch, failure):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from lib.context.business_domain_synthesis import Synthesis, packet_for

    entered = threading.Event()
    release = threading.Event()
    arrivals_lock = threading.Lock()
    arrivals = []
    instances = []
    original_gate = Synthesis._await_provider_gate

    def observed_gate(self):
        with arrivals_lock:
            arrivals.append(threading.get_ident())
            instances.append(self)
            if len(arrivals) == 4:
                entered.set()
        return original_gate(self)

    monkeypatch.setattr(Synthesis, '_await_provider_gate', observed_gate)

    def singleton_work(self, model, anchor_ids):
        from lib.context.business_domain_work import ActivityScope
        return [ActivityScope(f'scope:test-{index}', 'whole_graph',
                packet_for(model, 'activity', [anchor_id]))
                for index, anchor_id in enumerate(sorted(anchor_ids))]

    monkeypatch.setattr(Synthesis, 'activity_work', singleton_work)

    class GatedProvider(Provider):
        dispatches = 0

        def generate(self, request, schema, *args):
            with arrivals_lock:
                self.dispatches += 1
                first = self.dispatches == 1
            if first:
                assert release.wait(5), 'Test did not release initial request'
            if failure:
                raise DomainError(failure, 'Fixture provider failure')
            value, usage = super().generate(request, schema, *args)
            if request['packet']['stage'] == 'grouping':
                value['domains'][0]['activity_memberships'] = [
                    record('ActivityMembership', activity_id=aid, role='primary',
                           claim_ids=['claim:domain'])
                    for aid in request['packet']['activity_ids']]
            return value, usage

    (tmp_path/'service.py').write_text('\n'.join(
        f"@app.post('/orders/{i}')\ndef create_{i}(order):\n    return order\n"
        for i in range(5)))
    provider = GatedProvider()
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(discover, tmp_path,
                                 {'business_domains': {'provider_concurrency': 4}}, provider)
        try:
            assert entered.wait(5), 'Workers did not reach the provider gate'
            with arrivals_lock:
                synthesis = instances[0]
            with synthesis.accounting_lock:
                # The fourth arrival may still be acquiring the gate; the
                # first dispatch holds the probe until explicitly released.
                assert synthesis.counters['requests'] <= 1
                assert synthesis.output_reserved <= synthesis.config['max_request_output_tokens']
            assert provider.dispatches <= 1
        finally:
            release.set()
        model, status = result.result(timeout=10)
    if failure:
        assert model is None and status['phase'] == 'unavailable', status
        assert provider.dispatches == (2 if failure == 'PROVIDER_FAILED' else 1)
        assert status['limits']['requests'] == provider.dispatches
    else:
        assert model and status['phase'] == 'partial', status['error']
        assert status['coverage']['anchors_processed'] == 5


@pytest.mark.parametrize('recovery_fails', [False, True])
@pytest.mark.parametrize('late_fails', [False, True])
def test_midbuild_recovery_pauses_dispatch_and_ignores_late_success(
        tmp_path, monkeypatch, recovery_fails, late_fails):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS, limits
    from lib.context.business_domain_synthesis import Synthesis, packet_for

    (tmp_path/'service.py').write_text('\n'.join(
        f"@app.post('/orders/{i}')\ndef create_{i}(order):\n    return order\n"
        for i in range(4)))
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    anchors = sorted(facts['anchors'])
    packets = [packet_for(facts, 'activity', [anchor]) for anchor in anchors]
    late_started = threading.Event()
    release_late = threading.Event()
    recovering = threading.Event()
    release_recovery = threading.Event()
    waiters_ready = threading.Event()
    gate_waiters = []
    lock = threading.Lock()
    calls = {}

    class RecoveringProvider(Provider):
        def generate(self, request, schema, *args):
            anchor = request['packet']['anchor_ids'][0]
            with lock:
                calls[anchor] = calls.get(anchor, 0) + 1
                attempt = calls[anchor]
            if anchor == anchors[1] and attempt == 1:
                late_started.set()
                assert release_late.wait(5)
                if late_fails:
                    raise DomainError('PROVIDER_FAILED', 'Concurrent transport failure')
            if anchor == anchors[2]:
                if attempt == 1:
                    raise DomainError('PROVIDER_FAILED', 'Transport failure')
                recovering.set()
                assert release_recovery.wait(5)
                if recovery_fails:
                    raise DomainError('PROVIDER_FAILED', 'Transport failure')
            return super().generate(request, schema, *args)

    synthesis = Synthesis(tmp_path, DEFAULTS, RecoveringProvider(), limits(DEFAULTS))
    synthesis.run(packets[0])  # Establish health using real extraction/validation.
    original_gate = synthesis._await_provider_gate

    def observed_gate():
        if (not synthesis.provider_healthy and
                synthesis.provider_probe_owner != threading.get_ident()):
            gate_waiters.append(threading.get_ident())
            if len(gate_waiters) == (2 if late_fails else 1):
                waiters_ready.set()
        return original_gate()

    monkeypatch.setattr(synthesis, '_await_provider_gate', observed_gate)
    with ThreadPoolExecutor(max_workers=3) as executor:
        late = executor.submit(synthesis.run, packets[1])
        try:
            assert late_started.wait(5)
            recovery = executor.submit(synthesis.run, packets[2])
            assert recovering.wait(5)
            reserved = synthesis.counters['input_tokens_reserved']
            release_late.set()
            if not late_fails:
                assert late.result(timeout=5)
                # Account for the late response's usage reconciliation.
                reserved = synthesis.counters['input_tokens_reserved']
            fresh = executor.submit(synthesis.run, packets[3])
            assert waiters_ready.wait(5)
            with synthesis.accounting_lock:
                assert not synthesis.provider_healthy
                assert synthesis.counters['requests'] == 4
                assert synthesis.counters['input_tokens_reserved'] == reserved
            assert calls == {anchors[0]: 1, anchors[1]: 1, anchors[2]: 2}
        finally:
            release_late.set()
            release_recovery.set()
        for future in (recovery, fresh, *([late] if late_fails else [])):
            if recovery_fails:
                with pytest.raises(DomainError) as error:
                    future.result(timeout=5)
                assert error.value.code == 'PROVIDER_UNAVAILABLE'
            else:
                assert future.result(timeout=5)
    assert calls[anchors[2]] == 2
    assert calls.get(anchors[3], 0) == (0 if recovery_fails else 1)
    assert calls[anchors[1]] == (2 if late_fails and not recovery_fails else 1)


def test_busy_lock_does_not_start_or_write_attempt(tmp_path):
    source(tmp_path)
    with build_lock(tmp_path):
        with pytest.raises(DomainError,match='already running'):
            discover(tmp_path,provider=Provider())
    assert not paths(tmp_path)['status'].exists()


def test_read_does_not_scan_source_or_call_provider(tmp_path,monkeypatch):
    from lib.context import business_domains as module
    source(tmp_path); discover(tmp_path,provider=Provider())
    def forbidden(*args,**kwargs):
        raise AssertionError('Read attempted discovery')
    monkeypatch.setattr(module,'inventory',forbidden)
    monkeypatch.setattr(module,'Extractor',forbidden)
    assert load(tmp_path)[0]['domains']


def test_evidence_tampering_and_wrong_reference_kinds_are_rejected(tmp_path):
    source(tmp_path); model,_ = discover(tmp_path,provider=Provider())
    broken = copy.deepcopy(model)
    next(iter(broken['evidence'].values()))['excerpt'] = 'altered'
    with pytest.raises(DomainError,match='hash mismatch'):
        validate_evidence(tmp_path,broken)
    broken = copy.deepcopy(model)
    binding = next(iter(broken['bindings'].values()))
    binding['source']['kind'] = 'resource'
    with pytest.raises(DomainError,match='Wrong reference kind'):
        validate_references(broken)


@pytest.mark.parametrize('field', ['rules', 'concepts'])
def test_domain_lists_reject_existing_ids_of_wrong_kind(tmp_path, field):
    source(tmp_path)
    model, _ = discover(tmp_path, provider=Provider())
    next(iter(model['domains'].values()))[field] = [next(iter(model['evidence']))]
    with pytest.raises(DomainError, match='Wrong reference kind'):
        validate_references(model)


def test_rule_dependency_and_callable_enforcement_references(tmp_path):
    source(tmp_path)
    model, _ = discover(tmp_path, provider=Provider())
    symbol_id = next(iter(model['symbols']))
    dependency = record('Rule', id='rule:dependency')
    dependent = record('Rule', id='rule:dependent', dependency_ids=[dependency['id']],
                       enforcement_sites=[record('Site', source_id=symbol_id)])
    model['rules'].update({dependency['id']: dependency, dependent['id']: dependent})
    validate_references(model)
    assert 'effect' in REFERENCE_TARGETS['dependency_ids']
    dependent['dependency_ids'] = [next(iter(model['evidence']))]
    with pytest.raises(DomainError, match='Wrong reference kind'):
        validate_references(model)


def test_review_rename_accept_and_refresh_preserve_identity_without_model_calls(tmp_path):
    from lib.context.business_domain_review import review
    source(tmp_path);provider = Provider();model,_ = discover(tmp_path,provider=provider)
    did = next(iter(model['domains']));calls = provider.calls
    result = review(tmp_path,model['build_id'],{'operation':'rename','domain_id':did,'name':'Reviewed responsibility'},
                    'Preferred terminology',author='fixture reviewer')
    renamed,_ = load(tmp_path)
    assert renamed['domains'][did]['name'] == 'Reviewed responsibility'
    assert renamed['domains'][did]['review_state'] == 'needs_review'
    review(tmp_path,result['build_id'],{'operation':'accept','domain_id':did},'Reviewed the evidence','fixture reviewer')
    refreshed,status = discover(tmp_path,provider=provider)
    assert status['phase'] == 'partial',status
    assert refreshed['domains'][did]['name'] == 'Reviewed responsibility'
    assert refreshed['domains'][did]['review_state'] == 'accepted'
    assert provider.calls == calls
    validate_evidence(tmp_path,refreshed)


def test_review_recount_keeps_only_satisfied_implementation_selections():
    from lib.context.business_domain_review import _recount
    activity_id, trace_id = 'activity:test', 'trace:test'
    entry_id, implementation_id = 'symbol:entry', 'symbol:implementation'
    model = {
        'activities': {activity_id: {'trace_ids': [trace_id], 'concept_ids': [], 'rule_ids': []}},
        'traces': {trace_id: {
            'symbol_ids': [entry_id, implementation_id],
            'obligation_ids': ['trace_obligation:implementation'],
        }},
        'trace_obligations': {'trace_obligation:implementation': {
            'kind': 'implementation_selection', 'status': 'satisfied',
            'candidate_target_ids': [implementation_id],
        }},
        'symbols': {
            entry_id: {'file': 'routes.py'},
            implementation_id: {'file': 'service.py'},
        },
        'ownerships': {},
    }
    domain = {'id': 'domain:test', 'activity_memberships': [{'activity_id': activity_id}]}

    _recount(model, domain)

    assert [membership['symbol_id'] for membership in domain['symbol_memberships']] == [implementation_id]
    assert domain['symbol_count'] == 1
    assert domain['file_count'] == 1


def test_stale_review_does_not_write_decision(tmp_path):
    from lib.context.business_domain_review import review
    source(tmp_path);model,_ = discover(tmp_path,provider=Provider());did=next(iter(model['domains']))
    with pytest.raises(DomainError,match='reload before reviewing'):
        review(tmp_path,'stale',{'operation':'accept','domain_id':did},'Checked','reviewer')
    assert not paths(tmp_path)['overrides'].exists()


def test_cancel_rejects_a_finished_build(tmp_path):
    from lib.context.business_domains import cancel_build
    source(tmp_path);model,_ = discover(tmp_path,provider=Provider())
    with pytest.raises(DomainError,match='not running'):
        cancel_build(tmp_path,model['build_id'])
    assert not paths(tmp_path)['cancel'].exists()


def test_review_rejects_extraneous_fields_and_empty_names(tmp_path):
    from lib.context.business_domain_review import review
    source(tmp_path);model,_ = discover(tmp_path,provider=Provider());did=next(iter(model['domains']))
    for operation in ({'operation':'accept','domain_id':did,'name':'Unexpected'},
                      {'operation':'rename','domain_id':did,'name':'   '}):
        with pytest.raises(DomainError):
            review(tmp_path,model['build_id'],operation,'Checked','reviewer')
    assert not paths(tmp_path)['overrides'].exists()


def test_split_then_merge_preserves_history_and_references(tmp_path):
    from lib.context.business_domain_review import review
    source(tmp_path); model,_ = discover(tmp_path,provider=Provider())
    did = next(iter(model['domains'])); first = next(iter(model['activities']))
    second = 'activity:second'
    model['activities'][second] = dict(copy.deepcopy(model['activities'][first]),id=second)
    model['domains'][did]['activity_memberships'].append(record('ActivityMembership',activity_id=second,role='primary'))
    atomic_write(paths(tmp_path)['model'],model)
    split = review(tmp_path,model['build_id'],{'operation':'split','domain_id':did,'groups':[
        {'name':'First responsibility','activity_ids':[first]},
        {'name':'Second responsibility','activity_ids':[second]}]},'Separate responsibilities','reviewer')
    divided,_ = load(tmp_path)
    assert did not in divided['domains']
    assert len(divided['domains']) == 2
    merged = review(tmp_path,split['build_id'],{'operation':'merge','domain_ids':split['domain_ids'],
        'name':'Combined responsibility'},'Shared ownership established','reviewer')
    combined,_ = load(tmp_path)
    assert set(combined['domains']) == set(merged['domain_ids'])
    assert {m['activity_id'] for m in next(iter(combined['domains'].values()))['activity_memberships']} == {first,second}
    assert len(combined['identity_changes']) == 2
    validate_references(combined); validate_evidence(tmp_path,combined)
    assert (tmp_path/'.speed/context/business-domain-history'/f'{model["build_id"]}.json').exists()


def test_packet_keeps_call_graph_when_it_fits(tmp_path):
    from lib.context.business_domain_synthesis import packet_for, fit_packet
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS, canonical
    (tmp_path/'service.py').write_text("@app.post('/orders')\ndef create():\n    return reserve()\ndef reserve():\n    return 1\n")
    facts,_ = Extractor(tmp_path,DEFAULTS).extract()
    packet = packet_for(facts,'activity',list(facts['anchors']))
    original = canonical(packet)
    assert packet['context']['edges']
    fit_packet(packet,len(original)+1)
    assert canonical(packet) == original


def test_packet_limit_does_not_delete_graph_or_evidence(tmp_path):
    from lib.context.business_domain_synthesis import packet_for, fit_packet
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS, canonical
    (tmp_path/'service.py').write_text(
        "@app.post('/orders')\ndef create():\n    return reserve()\ndef reserve():\n    return 1\n")
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    packet = packet_for(facts, 'activity', list(facts['anchors']))
    original = canonical(packet)
    with pytest.raises(DomainError, match='Complete graph scope'):
        fit_packet(packet, len(original)-1)
    assert canonical(packet) == original


def test_provider_projection_is_deterministic_and_round_trips_exactly(tmp_path):
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS, canonical, digest
    from lib.context.business_domain_synthesis import ProviderProjection, packet_for

    source(tmp_path)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    packet = packet_for(facts, 'activity', sorted(facts['anchors']))
    first = ProviderProjection(packet)
    second = ProviderProjection(copy.deepcopy(packet))
    assert canonical(first.wire_packet) == canonical(second.wire_packet)
    assert first.decode_packet(first.wire_packet) == packet
    assert first.canonical_hash == digest(packet)
    assert first.reference_gaps == set()
    encoded = canonical(first.wire_packet)
    assert b'source_snapshots' not in encoded
    assert b'extractor_version' not in encoded
    storage_only = copy.deepcopy(packet)
    next(iter(storage_only['context']['source_snapshots'].values()))[
        'retrieved_at'] = '2030-01-01T00:00:00+00:00'
    storage_projection = ProviderProjection(storage_only)
    assert storage_projection.semantic_hash == first.semantic_hash
    assert storage_projection.canonical_hash != first.canonical_hash
    assert storage_projection.decode_packet(
        storage_projection.wire_packet) == storage_only


def test_provider_projection_restores_canonical_response_ids(tmp_path):
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS
    from lib.context.business_domain_synthesis import ProviderProjection, packet_for

    source(tmp_path)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    packet = packet_for(facts, 'activity', sorted(facts['anchors']))
    projection = ProviderProjection(packet)
    anchor_id = packet['anchor_ids'][0]
    response = {'anchor_ids': [projection.aliases[anchor_id]]}
    assert projection.decode_response(response) == {'anchor_ids': [anchor_id]}


def test_provider_projection_identity_invalidates_when_evidence_changes(tmp_path):
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS
    from lib.context.business_domain_synthesis import packet_for, provider_packet_identity

    source(tmp_path)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    packet = packet_for(facts, 'activity', sorted(facts['anchors']))
    first, projection = provider_packet_identity(packet)
    changed = copy.deepcopy(packet)
    next(iter(changed['context']['evidence'].values()))['excerpt'] += '\nchanged'
    second, changed_projection = provider_packet_identity(changed)
    assert first != second
    assert projection.semantic_hash != changed_projection.semantic_hash
    bumped = copy.copy(projection)
    bumped.VERSION = projection.VERSION + 1
    version_key, _ = provider_packet_identity(packet, bumped)
    assert version_key != first


def test_provider_projection_rejects_corrupt_wire_before_dispatch(tmp_path):
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS
    from lib.context.business_domain_synthesis import ProviderProjection, packet_for

    source(tmp_path)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    packet = packet_for(facts, 'activity', sorted(facts['anchors']))
    projection = ProviderProjection(packet)
    corrupt = copy.deepcopy(projection.wire_packet)
    corrupt['semantic_hash'] = '0' * 64
    with pytest.raises(DomainError, match='identity is invalid'):
        projection.decode_packet(corrupt)


def test_projected_provider_response_is_unaliased_before_canonical_validation(tmp_path):
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_schema import DEFAULTS, limits
    from lib.context.business_domain_synthesis import (
        ProviderProjection, Synthesis, packet_for, wire_schema,
    )

    class ProjectedProvider(Provider):
        accepts_projected_wire = True

        def generate(self, request, schema, *args):
            assert request['packet']['format'] == 'speed-domain-wire'
            canonical_request = copy.deepcopy(request)
            canonical_request['packet'] = self.projection.packet
            canonical_schema = wire_schema('ActivityPayload', self.projection.packet)
            value, usage = super().generate(canonical_request, canonical_schema, *args)
            return self.projection._rewrite(value, self.projection.aliases), usage

    source(tmp_path)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    packet = packet_for(facts, 'activity', sorted(facts['anchors']))
    provider = ProjectedProvider()
    provider.projection = ProviderProjection(packet)
    payload = Synthesis(tmp_path, DEFAULTS, provider, limits(DEFAULTS)).run(packet)
    activity = next(iter(payload['activities'].values()))
    assert activity['anchor_ids'] == packet['anchor_ids']


def test_removed_packet_count_limit_is_rejected_before_provider_work(tmp_path):
    source(tmp_path)
    provider = Provider()
    with pytest.raises(DomainError, match='Unknown or invalid'):
        discover(tmp_path, {'business_domains':{'max_evidence_per_packet':1}}, provider)
    assert provider.calls == 0


def test_grouping_work_partitions_without_omitting_activities(tmp_path, monkeypatch):
    from lib.context.business_domain_synthesis import Synthesis
    from lib.context.business_domain_schema import DEFAULTS, limits
    source(tmp_path); model,_ = discover(tmp_path,provider=Provider())
    first = next(iter(model['activities']))
    second = 'activity:zzzz'
    model['activities'][second] = dict(copy.deepcopy(model['activities'][first]),id=second)
    synthesis = Synthesis(tmp_path, DEFAULTS, Provider(), limits(DEFAULTS))
    monkeypatch.setattr(synthesis, '_grouping_fits',
                        lambda packet: len(packet['activity_ids']) <= 1)
    packets = synthesis.grouping_work(model)
    assert [packet['activity_ids'] for packet in packets] == [[first], [second]]


def test_grouping_work_uses_token_fit_not_only_bytes(tmp_path):
    from lib.context.business_domain_synthesis import Synthesis, packet_for, wire_schema
    from lib.context.business_domain_schema import DEFAULTS, limits
    source(tmp_path); model,_ = discover(tmp_path,provider=Provider())
    first = next(iter(model['activities']))
    second = 'activity:zzzz'
    model['activities'][second] = dict(copy.deepcopy(model['activities'][first]),id=second)
    synthesis = Synthesis(tmp_path, DEFAULTS, Provider(), limits(DEFAULTS))
    one = packet_for(model, 'grouping', [first])
    both = packet_for(model, 'grouping', [first, second])
    tokens = lambda packet: synthesis.estimate_input(
        synthesis.request_for(packet), wire_schema('GroupingPayload', packet))
    repair_headroom = 2*synthesis.effective_request_output_tokens
    synthesis.effective_request_input_tokens = max(
        tokens(packet_for(model, 'grouping', [activity_id]))
        for activity_id in sorted(model['activities'])) + repair_headroom
    assert tokens(both)+repair_headroom > synthesis.effective_request_input_tokens
    packets = synthesis.grouping_work(model)
    assert len(packets) == 2
    assert all(tokens(packet)+repair_headroom <= synthesis.effective_request_input_tokens
               for packet in packets)


def test_activity_work_reserves_repair_headroom_while_chunking(tmp_path):
    from lib.context.business_domain_synthesis import Synthesis, packet_for, wire_schema
    from lib.context.business_domain_schema import DEFAULTS, limits
    source(tmp_path); model,_ = discover(tmp_path,provider=Provider())
    first = next(iter(model['anchors']))
    second = 'anchor:second'
    model['anchors'][second] = dict(copy.deepcopy(model['anchors'][first]), id=second)
    config = {**DEFAULTS, 'max_request_output_tokens':1000}
    synthesis = Synthesis(tmp_path, config, Provider(), limits(config))
    one = packet_for(model, 'activity', [first])
    both = packet_for(model, 'activity', [first, second])
    tokens = lambda packet: synthesis.estimate_input(
        synthesis.request_for(packet), wire_schema('ActivityPayload', packet))
    synthesis.effective_request_input_tokens = tokens(one)+2000
    assert tokens(both)+2000 > synthesis.effective_request_input_tokens
    scopes = synthesis.activity_work(model, [first, second])
    assert len(scopes) == 2
    assert all(tokens(scope.packet)+2000 <= synthesis.effective_request_input_tokens
               for scope in scopes)


def test_reported_usage_reconciles_reservations_before_next_stage(tmp_path):
    source(tmp_path);provider = Provider()
    model,status = discover(tmp_path,config={'business_domains':{
        'max_request_input_tokens':20000,'max_request_output_tokens':2000,
        'max_build_input_tokens':80000,'max_build_output_tokens':8000}},provider=provider)
    assert model and model['domains'],status
    assert provider.calls == 4
    assert model['limits']['input_tokens_reserved'] == model['limits']['input_tokens_reported'] == 40


def test_review_batches_respect_output_allowance(tmp_path):
    from lib.context.business_domain_synthesis import Synthesis
    from lib.context.business_domain_schema import DEFAULTS,limits
    source(tmp_path);model,_ = discover(tmp_path,provider=Provider())
    claim = next(iter(model['claims'].values()))
    replace_claims(model, {
        f'claim:{i}':dict(copy.deepcopy(claim), id=f'claim:{i}')
        for i in range(20)})
    config = {**DEFAULTS, 'max_request_output_tokens':512}
    synthesis = Synthesis(tmp_path,config,Provider(),limits(config))
    batches = list(synthesis.review_batches(model))
    assert {cid for p in batches for cid in p['claim_ids']} == set(model['claims'])
    assert max(len(p['claim_ids']) for p in batches) <= 2


def test_review_batches_split_on_tokens_without_losing_claims_or_evidence(tmp_path, monkeypatch):
    from lib.context.business_domain_synthesis import Synthesis, packet_for, wire_schema, input_token_estimate
    from lib.context.business_domain_schema import DEFAULTS, limits
    source(tmp_path);model,_ = discover(tmp_path,provider=Provider())
    claim = next(iter(model['claims'].values()))
    # Long identifier-like text has more tokens per byte than ordinary prose.
    text = ' '.join(f'field_{i:05x}' for i in range(600))
    replace_claims(model, {
        f'claim:{i}':dict(copy.deepcopy(claim), id=f'claim:{i}',
                          text=f'{text} unique_{i}')
        for i in range(3)})
    config = dict(DEFAULTS)
    synthesis = Synthesis(tmp_path,config,Provider(),limits(config))
    def tokens(packet):
        return synthesis.estimate_input(
            synthesis.request_for(packet), wire_schema('ReviewPayload', packet))
    singles = [packet_for(model,'evidence_review',[cid]) for cid in model['claims']]
    input_limit = max(map(tokens,singles))
    config = {**DEFAULTS, 'max_request_input_tokens':input_limit}
    synthesis = Synthesis(tmp_path,config,Provider(),limits(config))
    assert tokens(packet_for(model,'evidence_review',list(model['claims'])[:2])) > input_limit
    # Isolate the token constraint: byte/evidence/output limits accept all claims.
    monkeypatch.setattr(synthesis,'packet_allowance',lambda stage:10**9)
    batches = list(synthesis.review_batches(model))
    assert len(batches) == 3
    assert sorted(cid for packet in batches for cid in packet['claim_ids']) == sorted(model['claims'])
    for packet in batches:
        assert tokens(packet) <= config['max_request_input_tokens']
        cid = packet['claim_ids'][0]
        assert packet['context']['claims'][cid] == {
            **model['claims'][cid], 'semantic_review': 'uncertain'}
        assert set(packet['context']['evidence']) == set(claim['evidence_ids'])


def test_unexpected_provider_failure_records_terminal_status(tmp_path):
    source(tmp_path);good,_ = discover(tmp_path,provider=Provider())
    (tmp_path/'service.py').write_text("@app.post('/other')\ndef changed():\n    return 3\n")
    class Broken(Provider):
        def generate(self,*args):
            raise RuntimeError('unexpected implementation failure')
    model,status = discover(tmp_path,provider=Broken())
    assert model == good
    assert status['phase'] == 'failed' and status['error']['code'] == 'INTERNAL_ERROR'


def test_invalid_grouping_after_repair_preserves_published_domains(tmp_path):
    source(tmp_path); good,_ = discover(tmp_path,provider=Provider())
    original = paths(tmp_path)['model'].read_bytes()
    (tmp_path/'service.py').write_text("@app.post('/changed')\ndef changed(order):\n    return order\n")
    class InvalidGrouping(Provider):
        def generate(self,request,schema,*args):
            if request['packet']['stage']=='grouping':
                self.calls += 1
                return {}, {'last':{'inputTokens':10,'outputTokens':10}}
            return super().generate(request,schema,*args)
    model,status = discover(tmp_path,provider=InvalidGrouping())
    assert model == good
    assert paths(tmp_path)['model'].read_bytes() == original
    assert status['phase']=='failed' and status['error']['code']=='INVALID_PROVIDER_OUTPUT'


@pytest.mark.parametrize('published_before', [False, True])
def test_exhausted_review_repair_preserves_publication_and_reuses_valid_work(tmp_path, published_before):
    class InvalidReview(Provider):
        invalid = True

        def __init__(self):
            super().__init__()
            self.stages = []

        def generate(self, request, schema, *args):
            stage = request['packet']['stage']
            self.stages.append(stage)
            if self.invalid and stage == 'evidence_review':
                self.calls += 1
                payload = record('ReviewPayload', verdicts=[])
                return encode(payload, DEFINITIONS['ReviewPayload']), {
                    'last': {'inputTokens': 10, 'outputTokens': 10}}
            return super().generate(request, schema, *args)

    source(tmp_path)
    previous = discover(tmp_path, provider=Provider())[0] if published_before else None
    publication = paths(tmp_path)['model']
    published_bytes = publication.read_bytes() if published_before else None
    cache_dir = tmp_path/'.speed/context/business-domain-cache'
    old_cache = {p: p.read_bytes() for p in cache_dir.glob('*.json')
                 if not p.name.startswith('pending-')}
    (tmp_path/'service.py').write_text(
        "@app.post('/orders')\ndef create(order):\n    return {'changed': order}\n")
    provider = InvalidReview()
    preserved, status = discover(tmp_path, provider=provider)
    assert preserved == previous
    assert status['phase'] == 'failed'
    assert status['error']['code'] == 'INVALID_REVIEW'
    assert status['freshness'] == ('stale' if published_before else 'missing')
    assert status['limits']['retries'] == 1
    assert provider.stages == ['activity', 'evidence_review', 'evidence_review']
    if published_before:
        assert publication.read_bytes() == published_bytes
    else:
        assert not publication.exists()
    assert paths(tmp_path)['facts'].exists()
    assert all(p.read_bytes() == content for p, content in old_cache.items())
    retained_cache = {p: p.read_bytes() for p in cache_dir.glob('*.json')
                      if not p.name.startswith('pending-')}
    assert retained_cache == old_cache

    provider.invalid = False
    provider.stages.clear()
    recovered, status = discover(tmp_path, provider=provider)
    assert recovered and status['phase'] == 'partial', status
    assert provider.stages == [
        'activity', 'evidence_review', 'grouping', 'evidence_review']
    assert all(p.read_bytes() == content for p, content in retained_cache.items())
    validate_evidence(tmp_path, recovered)


def test_exhausted_activity_repair_cannot_publish_a_validated_prefix(tmp_path, monkeypatch):
    from lib.context import business_domain_synthesis as synthesis

    (tmp_path/'service.py').write_text('\n'.join(
        f"@app.post('/orders/{i}')\ndef create_{i}(order):\n    return order\n"
        for i in range(2)))

    def singleton_work(self, model, anchor_ids):
        from lib.context.business_domain_work import ActivityScope
        return [ActivityScope(f'scope:test-{index}', 'whole_graph',
                synthesis.packet_for(model, 'activity', [anchor_id]))
                for index, anchor_id in enumerate(sorted(anchor_ids))]

    monkeypatch.setattr(synthesis.Synthesis, 'activity_work', singleton_work)

    class InvalidSecondActivity(Provider):
        activity_requests = 0

        def generate(self, request, schema, *args):
            if request['packet']['stage'] == 'activity':
                self.activity_requests += 1
                if self.activity_requests > 1:
                    self.calls += 1
                    return {}, {'last': {'inputTokens': 10, 'outputTokens': 10}}
            return super().generate(request, schema, *args)

    provider = InvalidSecondActivity()
    model, status = discover(tmp_path, provider=provider)
    assert model is None and not paths(tmp_path)['model'].exists()
    assert status['phase'] == 'failed'
    assert status['error']['code'] == 'INVALID_PROVIDER_OUTPUT'
    assert status['limits']['truncated'] is False
    assert status['limits']['semantic_units_validated'] == 1
    assert status['limits']['semantic_units_pending'] == 1
    assert paths(tmp_path)['facts'].exists()
    assert list((tmp_path/'.speed/context/business-domain-cache').glob('*.json'))


def test_rejected_rule_claim_cannot_retain_verified_enforcement():
    from lib.context.business_domains import apply_verdicts
    model = record('DomainArtifact')
    model['rules']['rule:example'] = record('Rule', id='rule:example', support='supported', enforcement_status='verified_on_trace')
    model['claims']['claim:rule'] = record('Claim', id='claim:rule', subject_id='rule:example', semantic_review='uncertain')
    apply_verdicts(model, ['claim:rule'], {'verdicts':[{'claim_id':'claim:rule','verdict':'unsupported'}]})
    assert model['rules']['rule:example']['support'] == 'insufficient'
    assert model['rules']['rule:example']['enforcement_status'] == 'unresolved'


def test_semantic_verification_requires_exact_claim_coverage():
    from lib.context.business_domains import apply_verdicts
    model = record('DomainArtifact')
    model['claims']['claim:one'] = record('Claim', id='claim:one', subject_id='activity:one', semantic_review='uncertain')
    model['claims']['claim:two'] = record('Claim', id='claim:two', subject_id='activity:two', semantic_review='uncertain')
    with pytest.raises(DomainError, match='cover every submitted claim exactly once'):
        apply_verdicts(model, ['claim:one', 'claim:two'], {'verdicts':[
            {'claim_id':'claim:one', 'verdict':'supported', 'evidence_ids':[], 'explanation':'checked'}]})
    assert all(claim['semantic_review'] == 'uncertain' for claim in model['claims'].values())


def test_corrupt_response_cache_is_rebuilt_instead_of_blocking_refresh(tmp_path):
    import json
    source(tmp_path); provider = Provider()
    first,_ = discover(tmp_path,provider=provider)
    assert first
    response_files = [p for p in (tmp_path/'.speed/context/business-domain-cache').glob('*.json')
                      if json.loads(p.read_text())['kind']=='response']
    for path in response_files:
        cached = json.loads(path.read_text())
        assert cached['provider_projection_version'] == 1
        assert len(cached['semantic_hash']) == 64
    for path in response_files:
        path.write_text('{broken')
    calls=provider.calls
    rebuilt,status=discover(tmp_path,provider=provider)
    assert rebuilt and status['phase']=='partial'
    assert provider.calls > calls


def test_refresh_quarantines_a_malformed_model_and_recovers_on_next_success(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEED_PROVIDER", "missing-test-provider")
    source(tmp_path)
    locations = paths(tmp_path)
    locations['model'].parent.mkdir(parents=True)
    invalid = b'{invalid stored model'
    locations['model'].write_bytes(invalid)
    model, status = discover(tmp_path)
    assert model is None and status['phase']=='unavailable'
    assert not locations['model'].exists()
    quarantined = list(locations['quarantine'].glob('*.invalid.json'))
    assert len(quarantined) == 1 and quarantined[0].read_bytes() == invalid
    model, status = discover(tmp_path,provider=Provider())
    assert model and model['domains'], status
    assert load(tmp_path)[0]['build_id'] == model['build_id']


@pytest.mark.parametrize('failure', ['transient', 'invalid'])
def test_provider_recovery_is_bounded_and_charged(tmp_path, failure):
    class RecoveringProvider(Provider):
        def __init__(self):
            super().__init__()
            self.requests = []
        def generate(self, request, schema, *args):
            self.requests.append(copy.deepcopy(request))
            if len(self.requests) == 1:
                if failure == 'transient':
                    raise DomainError('PROVIDER_FAILED', 'Temporary transport failure')
                return {}, {'last': {'inputTokens': 10, 'outputTokens': 10}}
            return super().generate(request, schema, *args)
    source(tmp_path)
    provider = RecoveringProvider()
    model, status = discover(tmp_path, provider=provider)
    assert model and model['domains'], status
    assert status['limits']['retries'] == 1
    assert status['limits']['requests'] == len(provider.requests)
    if failure == 'invalid':
        assert provider.requests[1]['validation_feedback']['code'] == 'INVALID_PROVIDER_OUTPUT'
    assert status['limits']['input_tokens_reserved'] >= status['limits']['input_tokens_reported']


def test_repeated_invalid_response_stops_after_one_repair(tmp_path):
    class InvalidProvider(Provider):
        def generate(self, request, schema, *args):
            self.calls += 1
            return {}, {'last': {'inputTokens': 10, 'outputTokens': 10}}
    source(tmp_path)
    provider = InvalidProvider()
    model, status = discover(tmp_path, provider=provider)
    assert model is None
    assert provider.calls == 2
    assert status['limits']['retries'] == 1
    pending = list((tmp_path/'.speed/context/business-domain-cache').glob(
        'pending-*.json'))
    assert pending
    state = read_json(pending[0])
    assert state['next_operation'] == 'repair'
    assert state['provider_projection_version'] == 1
    assert len(state['semantic_hash']) == 64
    assert state['correction']['rejected_candidate'] == {}
    assert state['correction']['findings']


def test_pending_repair_resumes_with_candidate_and_clears_after_success(tmp_path):
    from lib.context.business_domain_schema import DEFAULTS, digest, limits
    from lib.context.business_domain_synthesis import Synthesis

    packet = record('ReviewPacket', input_fingerprint=digest('pending-repair'))

    class AlwaysInvalid(Provider):
        def generate(self, request, schema, *args):
            self.calls += 1
            return {}, {'last': {'inputTokens': 10, 'outputTokens': 10}}

    with pytest.raises(DomainError, match='required'):
        Synthesis(tmp_path, DEFAULTS, AlwaysInvalid(), limits(DEFAULTS)).run(packet)

    class Recovered(Provider):
        def __init__(self):
            super().__init__()
            self.requests = []

        def generate(self, request, schema, *args):
            self.calls += 1
            self.requests.append(copy.deepcopy(request))
            payload = encode(record('ReviewPayload'), DEFINITIONS['ReviewPayload'])
            return payload, {'last': {'inputTokens': 10, 'outputTokens': 10}}

    provider = Recovered()
    result = Synthesis(tmp_path, DEFAULTS, provider, limits(DEFAULTS)).run(packet)
    assert result == record('ReviewPayload')
    assert provider.requests[0]['validation_feedback']['rejected_candidate'] == {}
    assert not list((tmp_path/'.speed/context/business-domain-cache').glob(
        'pending-*.json'))


def test_verifier_contract_pending_is_not_routed_to_candidate_stage(tmp_path):
    from lib.context.business_domain_schema import DEFAULTS, digest, limits
    from lib.context.business_domain_synthesis import Synthesis

    packet = record('ReviewPacket', input_fingerprint=digest('verifier-owner'))
    synthesis = Synthesis(tmp_path, DEFAULTS, Provider(), limits(DEFAULTS))
    correction = {
        'code': 'INVALID_REVIEW',
        'message': 'Verifier omitted a claim',
        'repair_kind': 'verifier_contract',
        'rejected_candidate': {},
        'findings': [],
        'verification_report': None,
        'instruction': 'Repair the verifier response.',
    }
    synthesis._persist_pending_repair(packet, correction)
    path = synthesis._pending_repair_path(packet)
    assert path.exists()

    assert synthesis._load_pending_repair(packet) == (None, set())
    assert not path.exists()


def test_schema_and_semantic_repairs_receive_exact_candidate_and_cache_success(tmp_path):
    from lib.context.business_domain_schema import DEFAULTS, digest, limits
    from lib.context.business_domain_synthesis import Synthesis

    valid = encode(record('ReviewPayload'), DEFINITIONS['ReviewPayload'])

    class RepairingProvider(Provider):
        def __init__(self):
            super().__init__()
            self.requests = []

        def generate(self, request, schema, *args):
            self.calls += 1
            self.requests.append(copy.deepcopy(request))
            response = {} if self.calls == 1 else copy.deepcopy(valid)
            return response, {'last': {'inputTokens': 10, 'outputTokens': 10}}

    provider = RepairingProvider()
    counters = limits(DEFAULTS)
    synthesis = Synthesis(tmp_path, DEFAULTS, provider, counters)
    packet = record('ReviewPacket', input_fingerprint=digest('repair'))
    semantic_attempts = 0

    def semantic_validator(payload):
        nonlocal semantic_attempts
        semantic_attempts += 1
        if semantic_attempts == 1:
            raise DomainError('INVALID_COVERAGE', 'Every anchor needs a disposition')

    assert synthesis.run(packet, semantic_validator) == record('ReviewPayload')
    assert provider.calls == 3
    schema_feedback = provider.requests[1]['validation_feedback']
    assert schema_feedback['repair_kind'] == 'schema'
    assert schema_feedback['rejected_candidate'] == {}
    assert len(schema_feedback['findings']) == len(record('ReviewPayload'))
    semantic_feedback = provider.requests[2]['validation_feedback']
    assert semantic_feedback['repair_kind'] == 'semantic'
    assert semantic_feedback['rejected_candidate'] == valid
    assert semantic_feedback['findings'][0]['code'] == 'INVALID_COVERAGE'

    assert synthesis.run(packet, semantic_validator) == record('ReviewPayload')
    assert provider.calls == 3
    assert synthesis.cache_hits == 1


def test_distinct_semantic_failures_self_heal_in_one_run(tmp_path):
    from lib.context.business_domain_schema import DEFAULTS, digest, limits
    from lib.context.business_domain_synthesis import Synthesis

    valid = encode(record('ReviewPayload'), DEFINITIONS['ReviewPayload'])

    class RepairingProvider(Provider):
        def __init__(self):
            super().__init__()
            self.requests = []

        def generate(self, request, schema, *args):
            self.calls += 1
            self.requests.append(copy.deepcopy(request))
            return copy.deepcopy(valid), {
                'last': {'inputTokens': 10, 'outputTokens': 10}}

    attempts = 0

    def semantic_validator(payload):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise DomainError(
                'INVALID_TRACE', 'Trace closure is incomplete',
                findings=[{'code': 'INVALID_TRACE', 'severity': 'error',
                           'message': 'Trace closure is incomplete',
                           'subject_ids': ['trace:first'], 'evidence_ids': []}])
        if attempts == 2:
            raise DomainError(
                'SEMANTIC_VERIFICATION_FAILED',
                'Independent verification rejected one claim',
                findings=[{'code': 'SEMANTIC_VERIFICATION_FAILED',
                           'severity': 'error',
                           'message': 'Independent verification rejected one claim',
                           'subject_ids': ['claim:second'], 'evidence_ids': []}],
                repair_kind='semantic', verification_report=[])

    provider = RepairingProvider()
    counters = limits(DEFAULTS)
    synthesis = Synthesis(tmp_path, DEFAULTS, provider, counters)
    packet = record('ReviewPacket', input_fingerprint=digest('distinct-repairs'))

    assert synthesis.run(packet, semantic_validator) == record('ReviewPayload')
    assert provider.calls == 3
    assert counters['retries'] == 2
    assert provider.requests[1]['validation_feedback']['code'] == 'INVALID_TRACE'
    assert provider.requests[2]['validation_feedback']['code'] == \
        'SEMANTIC_VERIFICATION_FAILED'


def test_equivalent_semantic_failure_stops_across_resume(tmp_path):
    from lib.context.business_domain_schema import DEFAULTS, digest, limits
    from lib.context.business_domain_synthesis import Synthesis

    valid = encode(record('ReviewPayload'), DEFINITIONS['ReviewPayload'])

    class ValidProvider(Provider):
        def generate(self, request, schema, *args):
            self.calls += 1
            return copy.deepcopy(valid), {
                'last': {'inputTokens': 10, 'outputTokens': 10}}

    def reject(payload):
        raise DomainError(
            'INVALID_COVERAGE', 'Anchor coverage is incomplete',
            findings=[{'code': 'INVALID_COVERAGE', 'severity': 'error',
                       'message': 'Anchor coverage is incomplete',
                       'subject_ids': ['anchor:same'], 'evidence_ids': []}])

    packet = record('ReviewPacket', input_fingerprint=digest('repeat-resume'))
    first = ValidProvider()
    with pytest.raises(DomainError, match='coverage'):
        Synthesis(tmp_path, DEFAULTS, first, limits(DEFAULTS)).run(packet, reject)
    assert first.calls == 2

    pending = next((tmp_path/'.speed/context/business-domain-cache').glob(
        'pending-*.json'))
    state = read_json(pending)
    assert len(state['attempted_repair_signatures']) == 1

    resumed = ValidProvider()
    with pytest.raises(DomainError, match='coverage'):
        Synthesis(tmp_path, DEFAULTS, resumed, limits(DEFAULTS)).run(packet, reject)
    assert resumed.calls == 1


def test_distinct_semantic_repair_chain_stops_at_hard_limit(tmp_path, monkeypatch):
    from lib.context.business_domain_schema import DEFAULTS, digest, limits
    from lib.context.business_domain_synthesis import POLICY, Synthesis

    valid = encode(record('ReviewPayload'), DEFINITIONS['ReviewPayload'])

    class ValidProvider(Provider):
        def generate(self, request, schema, *args):
            self.calls += 1
            return copy.deepcopy(valid), {
                'last': {'inputTokens': 10, 'outputTokens': 10}}

    attempts = 0

    def reject_distinct(payload):
        nonlocal attempts
        attempts += 1
        raise DomainError(
            'INVALID_COVERAGE', f'Distinct coverage failure {attempts}',
            findings=[{'code': 'INVALID_COVERAGE', 'severity': 'error',
                       'message': f'Distinct coverage failure {attempts}',
                       'subject_ids': [f'anchor:{attempts}'],
                       'evidence_ids': []}])

    monkeypatch.setitem(POLICY, 'semantic_repair_limit', 2)
    provider = ValidProvider()
    packet = record('ReviewPacket', input_fingerprint=digest('repair-limit'))
    with pytest.raises(DomainError, match='failure 3'):
        Synthesis(tmp_path, DEFAULTS, provider, limits(DEFAULTS)).run(
            packet, reject_distinct)
    assert provider.calls == 3


def test_provider_schema_explains_reference_targets_before_generation():
    from lib.context.business_domain_synthesis import wire_schema
    schema = wire_schema('ActivityPayload')
    assert 'kind: anchor.' in schema['$defs']['Scope']['properties']['entrypoint_ids']['description']
    assert 'kind: resource, symbol.' in schema['$defs']['Site']['properties']['source_id']['description']

    packet = record('ReviewPacket', claim_ids=['claim:first', 'claim:second'])
    packet['context']['claims'] = {
        claim_id: record('Claim', id=claim_id)
        for claim_id in packet['claim_ids']
    }
    review_schema = wire_schema('ReviewPayload', packet)
    claim_id = review_schema['properties']['verdicts']['items'][
        'properties']['claim_id']
    assert claim_id['enum'] == packet['claim_ids']


def test_review_repair_receives_exact_claim_and_evidence_catalogs():
    from lib.context.business_domain_synthesis import Synthesis

    packet = record('ReviewPacket', claim_ids=['claim:first', 'claim:second'])
    packet['context']['evidence'] = {
        'ev:first': record('Evidence', id='ev:first'),
        'ev:second': record('Evidence', id='ev:second'),
    }
    feedback = Synthesis._repair_feedback(
        DomainError('INVALID_REVIEW',
                    'Semantic verification must cover every submitted claim exactly once'),
        'semantic', packet)

    assert feedback['allowed_reference_ids'] == {
        'claim_ids': ['claim:first', 'claim:second'],
        'evidence_ids': ['ev:first', 'ev:second'],
    }
    assert 'exactly one verdict for every ID' in feedback['instruction']


def test_grouping_repair_uses_record_reference_evidence_catalog(tmp_path):
    from lib.context.business_domain_schema import DEFAULTS, limits
    from lib.context.business_domain_synthesis import Synthesis

    packet = record('GroupingPacket')
    packet['context']['record_refs'] = {
        'ev:grouping': {'collection': 'evidence', 'content_hash': '0'*64},
    }
    feedback = Synthesis._repair_feedback(
        DomainError('INVALID_EVIDENCE', 'Evidence is outside grouping scope'),
        'semantic', packet)

    assert feedback['allowed_reference_ids']['evidence_ids'] == ['ev:grouping']

    # Old pending feedback is refreshed from the current packet on resume.
    feedback['allowed_reference_ids']['evidence_ids'] = []
    synthesis = Synthesis(tmp_path, DEFAULTS, Provider(), limits(DEFAULTS))
    synthesis._persist_pending_repair(packet, feedback)
    resumed, _ = synthesis._load_pending_repair(packet)
    assert resumed['allowed_reference_ids']['evidence_ids'] == ['ev:grouping']


def test_invalid_evidence_equivalence_ignores_generated_subject_ids():
    from lib.context.business_domain_synthesis import Synthesis

    def failure(subject, evidence):
        return DomainError(
            'INVALID_EVIDENCE', 'Provider cited evidence outside its packet',
            findings=[{'code': 'INVALID_EVIDENCE', 'severity': 'error',
                       'message': 'Provider cited evidence outside its packet',
                       'subject_ids': [subject], 'evidence_ids': [evidence]}])

    first = Synthesis._repair_signature(
        failure('claim:first', 'ev:forbidden'), 'semantic')
    repeated = Synthesis._repair_signature(
        failure('claim:regenerated', 'ev:forbidden'), 'semantic')
    distinct = Synthesis._repair_signature(
        failure('claim:first', 'ev:other'), 'semantic')

    assert first == repeated
    assert first != distinct


def test_provider_schema_rejects_human_review_state_and_empty_information_use():
    from jsonschema import Draft202012Validator, ValidationError
    from lib.context.business_domain_synthesis import wire_schema

    activity_schema = wire_schema('ActivityPayload')
    assert activity_schema['$defs']['Activity']['properties']['review_state']['enum'] == ['proposed']
    resources = activity_schema['$defs']['InformationUse']['properties']['resource_ids']
    assert resources['minItems'] == 1
    with pytest.raises(ValidationError):
        Draft202012Validator(resources).validate([])

    grouping_schema = wire_schema('GroupingPayload')
    assert grouping_schema['$defs']['Domain']['properties']['review_state']['enum'] == ['proposed']
    assert grouping_schema['$defs']['Ownership']['properties']['review_state']['enum'] == ['proposed']


def test_provider_schema_encodes_all_field_local_acceptance_rules():
    from lib.context.business_domain_synthesis import wire_schema

    activity = wire_schema('ActivityPayload')['$defs']['Activity']['properties']
    assert all(activity[field]['minItems'] == 1
               for field in ('trace_ids', 'evidence_ids', 'claim_ids'))

    grouping = wire_schema('GroupingPayload')['$defs']
    relationship = grouping['RuleRelationship']['properties']
    assert relationship['verification']['enum'] == ['inferred', 'unresolved']
    assert relationship['evidence_ids']['minItems'] == 1
    assert relationship['explanation']['minLength'] == 1
    domain = grouping['Domain']['properties']
    assert all(domain[field]['minItems'] == 1
               for field in ('activity_memberships', 'evidence_ids', 'claim_ids'))
    assert domain['boundary_rationale']['minLength'] == 1
    assert grouping['ActivityMembership']['properties']['claim_ids']['minItems'] == 1


def test_grouping_schema_constrains_existing_concepts_without_constraining_new_domains():
    from lib.context.business_domain_synthesis import wire_schema
    from jsonschema import Draft202012Validator, ValidationError
    packet = record('GroupingPacket')
    packet['context']['concepts']['concept:known'] = record('Concept',id='concept:known',name='Known concept')
    schema = wire_schema('GroupingPayload',packet)
    field = schema['$defs']['Ownership']['properties']['concept_id']
    assert field['enum'] == ['concept:known']
    with pytest.raises(ValidationError):
        Draft202012Validator(field).validate('concept:invented')
    assert 'enum' not in schema['$defs']['Ownership']['properties']['domain_id']['anyOf'][0]


def test_rules_with_shared_predicate_and_different_outcomes_keep_distinct_identity():
    from lib.context.business_domain_synthesis import normalize_ids
    payload = record('ActivityPayload', rules={
        name: record('Rule', id=name, predicate_or_formula='amount > 0', outcome=outcome)
        for name,outcome in [('rule:a','Decrease outstanding balance'),('rule:b','Record a payment')]
    })
    normalized = normalize_ids(payload, {'stage':'activity','anchor_ids':['anchor:one']})
    assert len(normalized['rules']) == 2
    assert {rule['outcome'] for rule in normalized['rules'].values()} == {
        'Decrease outstanding balance','Record a payment'}


def test_input_estimate_counts_unicode_and_literal_token_markers_as_data():
    import tiktoken
    from lib.context.business_domain_synthesis import input_token_estimate, POLICY
    from lib.context.business_domain_schema import canonical
    request = {'evidence':'退款条件 <|endoftext|> '*100}
    schema = {'type':'object'}
    raw = canonical({'request':request,'output_schema':schema}).decode('utf-8')
    actual = len(tiktoken.get_encoding(POLICY['input_token_encoding']).encode(raw,disallowed_special=()))
    assert input_token_estimate(request,schema) >= actual + POLICY['input_framing_tokens']


@pytest.mark.parametrize('operation',[None,{'operation':'rename','domain_id':'domain:a','name':42},
    {'operation':'split','domain_id':'domain:a','groups':[None]}])
def test_malformed_review_returns_a_structured_error(operation):
    from lib.context.business_domain_review import _operation
    with pytest.raises(DomainError):
        _operation(operation)


def test_agent_definition_changes_invalidate_the_affected_interpretation(tmp_path,monkeypatch):
    from lib.context import business_domain_synthesis as synthesis
    agents=tmp_path/'installed-agents';agents.mkdir()
    for path in synthesis.AGENTS.glob('business-domain-*.md'):
        (agents/path.name).write_text(path.read_text())
    monkeypatch.setattr(synthesis,'AGENTS',agents)
    repo=tmp_path/'repo';repo.mkdir();source(repo)
    provider=Provider(); first,_=discover(repo,provider=provider)
    calls=provider.calls
    path=agents/'business-domain-activity.md'
    path.write_text(path.read_text()+'\nRetain evidence scope explicitly.\n')
    second,status=discover(repo,provider=provider)
    assert second and status['phase']=='partial'
    assert second['fingerprint']['prompts']!=first['fingerprint']['prompts']
    assert provider.calls == calls


def test_missing_agent_definition_preserves_the_previous_model(tmp_path,monkeypatch):
    from lib.context import business_domain_synthesis as synthesis
    source(tmp_path);first,_=discover(tmp_path,provider=Provider())
    monkeypatch.setattr(synthesis,'AGENTS',tmp_path/'missing-definitions')
    preserved,status=discover(tmp_path,provider=Provider())
    assert preserved==first
    assert status['error']['code']=='AGENT_UNAVAILABLE'


@pytest.mark.parametrize('verdict', ['supported', 'uncertain', 'unsupported'])
def test_rule_relationships_are_reviewed_with_observations_and_conflict_links(tmp_path, verdict):
    from lib.context.business_domain_synthesis import from_wire
    class RuleProvider(Provider):
        def generate(self, request, schema, *args):
            value, usage = super().generate(request, schema, *args)
            packet = request['packet']; stage = packet['stage']; context = packet['context']
            payload = from_wire(value, DEFINITIONS[STAGES[stage][1]])
            if stage == 'activity':
                activity = next(iter(payload['activities'].values()))
                observations = list(context['rule_observations'].values())[:2]
                assert len(observations) == 2
                for index, observation in enumerate(observations):
                    rid, cid = 'rule:'+str(index), 'claim:rule'+str(index)
                    payload['rules'][rid] = record('Rule', id=rid, observation_ids=[observation['id']],
                        activity_ids=[activity['id']], predicate_or_formula=observation['native_expression'],
                        outcome='Fixture constraint outcome', evidence_ids=observation['evidence_ids'],basis=['source_observed'])
                    payload['claims'][cid] = record('Claim',id=cid,subject_id=rid,
                        text='Fixture rule claim',evidence_ids=observation['evidence_ids'])
                    activity['rule_ids'].append(rid)
            elif stage == 'grouping':
                observations = list(context['rule_observations'])
                assert len(observations) == 2
                next(iter(payload['domains'].values()))['rules'] = list(context['rules'])
                evidence = [eid for observation in context['rule_observations'].values()
                            for eid in observation['evidence_ids']]
                relation = record('RuleRelationship',id='rule_relationship:fixture',
                    from_observation_id=observations[0],to_observation_id=observations[1],
                    kind='conflicts_with',verification='inferred',evidence_ids=evidence,
                    explanation='Fixture conflicting conditions in a shared scope')
                payload['rule_relationships'][relation['id']] = relation
                payload['claims']['claim:relation'] = record('Claim',id='claim:relation',
                    subject_id=relation['id'],text=relation['explanation'],evidence_ids=evidence)
            else:
                for item in payload['verdicts']:
                    subject = context['claims'][item['claim_id']]['subject_id']
                    if subject in context['rule_relationships']:
                        assert len(context['rule_observations']) == 2
                        item['verdict'] = verdict
            encoded = encode(payload,DEFINITIONS[STAGES[stage][1]])
            from jsonschema import Draft202012Validator
            errors = list(Draft202012Validator(schema).iter_errors(encoded))
            assert not errors
            return encoded, usage
    (tmp_path/'service.py').write_text("@app.post('/orders')\ndef create(amount):\n    if amount > 10:\n        return 'allowed'\n    if amount < 5:\n        return 'blocked'\n")
    model, status = discover(tmp_path, provider=RuleProvider())
    if verdict != 'supported':
        assert model is None
        assert status['error']['code'] == 'SEMANTIC_VERIFICATION_FAILED'
        return
    assert model and model['rule_relationships'], status
    relation = next(iter(model['rule_relationships'].values()))
    assert relation['verification'] == ('inferred' if verdict=='supported' else 'unresolved')
    for rule in model['rules'].values():
        assert rule['conflicts'] == ([relation['id']] if verdict=='supported' else [])
        observation = model['rule_observations'][rule['observation_ids'][0]]
        assert observation['rule_id'] == rule['id']
        assert observation['activity_ids'] == rule['activity_ids']
    from dashboard.backend.resolvers.business_domains import connection
    page = connection(tmp_path,model['build_id'],next(iter(model['domains'])),'rules',20,None)
    assert page.error is None and len(page.edges)==2
    assert all(edge.node._observation_records and edge.node._relationship_records for edge in page.edges)


def test_semantic_grouping_cannot_verify_a_rule_relationship():
    from lib.context.business_domains import accept_grouping
    relation = record('RuleRelationship',id='rule_relationship:one',verification='verified')
    payload = record('GroupingPayload',rule_relationships={relation['id']:relation})
    packet = record('GroupingPacket')
    with pytest.raises(DomainError,match='Semantic proposals cannot establish verified'):
        accept_grouping(record('DomainArtifact'),packet,payload)


def test_refresh_cleans_expired_disposable_objects_only_after_publication(tmp_path):
    import os
    source(tmp_path)
    cache = tmp_path/'.speed/context/business-domain-cache/expired.json'
    snapshot = tmp_path/'.speed/context/business-domain-snapshots/expired.json'
    for path in (cache,snapshot):
        atomic_write(path,{'disposable':True})
        os.utime(path,(1,1))
    model,status = discover(tmp_path,provider=Provider())
    assert model and status['published_build_id'] == model['build_id']
    assert not cache.exists() and not snapshot.exists()
    validate_evidence(tmp_path,model)
    # Reads must leave disposable storage untouched.
    atomic_write(cache,{'disposable':True});os.utime(cache,(1,1))
    load(tmp_path)
    assert cache.exists()


def test_cleanup_failure_does_not_turn_published_discovery_into_failure(tmp_path):
    import os
    source(tmp_path)
    cache = tmp_path/'.speed/context/business-domain-cache/expired.json'
    atomic_write(cache,{'disposable':True});os.utime(cache,(1,1))
    # Unknown retained references must prevent deletion, rather than be skipped.
    history = tmp_path/'.speed/context/business-domain-history/unreadable.json'
    history.parent.mkdir(parents=True)
    history.write_text('{broken')
    model,status = discover(tmp_path,provider=Provider())
    assert model and status['phase'] == model['status']
    assert status['published_build_id'] == model['build_id']
    assert status['error'] is None
    assert any(w['code']=='CLEANUP_FAILED' for w in status['warnings'])
    assert cache.exists() and history.exists()
    validate_evidence(tmp_path,model)


@pytest.mark.parametrize('explain',[False,True])
def test_grouping_requires_explicit_activity_exclusion_and_preserves_anchor_counts(tmp_path,explain):
    source(tmp_path)
    class ExcludingProvider(Provider):
        def generate(self,request,schema,*args):
            if request['packet']['stage'] != 'grouping':
                return super().generate(request,schema,*args)
            self.calls += 1
            packet = request['packet']
            payload = record('GroupingPayload')
            if explain:
                aid = packet['activity_ids'][0]
                evidence = packet['context']['activities'][aid]['evidence_ids']
                payload['claims']['claim:exclusion'] = record('Claim',id='claim:exclusion',
                    subject_id=aid,kind='boundary',text='The fixture activity lacks evidence of a business responsibility.',
                    evidence_ids=evidence,semantic_review='uncertain')
            return encode(payload,DEFINITIONS['GroupingPayload']),{'last':{'inputTokens':10,'outputTokens':10}}
    model,status = discover(tmp_path,provider=ExcludingProvider())
    if not explain:
        assert model is None
        assert status['phase'] == 'failed'
        assert status['error']['code'] == 'INVALID_COVERAGE'
    else:
        assert model and not model['domains']
        aid = next(iter(model['activities']))
        assert any(u['subject_id']==aid and u['status']=='excluded' and u['reason'] for u in model['unassigned'])
        assert model['coverage']['anchors_processed'] == 1
        assert model['coverage']['anchors_excluded'] == 0
        assert model['coverage']['anchors_pending'] == 0
        validate_references(model)


def test_missing_usage_reserves_estimated_input_instead_of_request_cap(tmp_path):
    from lib.context.business_domain_synthesis import input_token_estimate
    source(tmp_path)
    class NoUsage(Provider):
        def __init__(self):
            super().__init__()
            self.estimated = 0
        def generate(self,request,schema,*args):
            self.estimated += input_token_estimate(request,schema)
            payload,_ = super().generate(request,schema,*args)
            return payload,{}
    provider = NoUsage()
    model,status = discover(tmp_path,config={'business_domains':{
        'max_request_input_tokens':500000,'max_build_input_tokens':2000000}},provider=provider)
    assert model and model['domains'],status
    assert provider.calls == 4
    assert status['limits']['input_tokens_reserved'] == provider.estimated < 2000000
    assert status['limits']['input_tokens_reported'] is None
