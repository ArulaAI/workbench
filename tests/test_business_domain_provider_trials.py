import threading
import time

from lib.context import business_domains as discovery
from lib.context.business_domain_schema import DEFINITIONS, DomainError, identifier, record
from lib.context.business_domain_synthesis import Synthesis, packet_for
from lib.context.business_domain_work import ActivityScope
from lib.context.business_domains import discover, paths
from tests.test_business_domain_pipeline import Provider, encode


def grocery_sources(root, count=24):
    for index in range(count):
        (root / f'service_{index:02}.py').write_text(
            f"@app.post('/orders/{index}')\n"
            f'def create_{index}(order):\n'
            '    return order\n')


def singleton_hierarchy(self, model, anchor_ids):
    return [ActivityScope(
        identifier('scope', 'grocery-trial', anchor_id),
        'entrypoint_bundle', packet_for(model, 'activity', [anchor_id]))
        for anchor_id in sorted(anchor_ids)]


def authorization_error():
    failure = {'schema_version': 1, 'category': 'authorization_denied',
               'scope': 'provider', 'retryable': False,
               'native_status': '403', 'message': 'Provider access denied',
               'diagnostic_log': '.speed/logs/provider-403.json'}
    return DomainError('PROVIDER_UNAVAILABLE', failure['message'],
                       retryable=False, provider_failure=failure)


class GroceryProvider(Provider):
    """Produces one root activity per cached/validated hierarchical leaf."""

    def __init__(self):
        super().__init__()
        self.refresh_failure = False
        self.refresh_activity_calls = 0
        self.refresh_failed_calls = 0
        self.lock = threading.Lock()

    def _root_payload(self, context):
        evidence_id = sorted(context['evidence'])[0]
        activities, claims = {}, {}
        for index, child in enumerate(sorted(
                context['activities'].values(), key=lambda item: item['anchor_ids'])):
            activity_id = f'activity:root-{index}'
            claim_id = f'claim:root-{index}'
            activity = record(
                'Activity', id=activity_id, name=f'Grocery activity {index}',
                description='Reconciled validated hierarchical activity',
                anchor_ids=child['anchor_ids'], trace_ids=child['trace_ids'],
                evidence_ids=[evidence_id], claim_ids=[claim_id], support='partial')
            claim = record(
                'Claim', id=claim_id, subject_id=activity_id,
                text=activity['description'], kind='behavior',
                evidence_ids=[evidence_id], trace_ids=child['trace_ids'],
                semantic_review='uncertain')
            activities[activity_id] = activity
            claims[claim_id] = claim
        return record('ActivityPayload', activities=activities, claims=claims)

    def generate(self, request, schema, *args):
        packet = request['packet']
        if packet['stage'] == 'activity' and packet['context']['activities']:
            self.calls += 1
            payload = self._root_payload(packet['context'])
            return encode(payload, DEFINITIONS['ActivityPayload']), {
                'last': {'inputTokens': 10, 'outputTokens': 10}}
        if self.refresh_failure and packet['stage'] == 'activity':
            with self.lock:
                self.refresh_activity_calls += 1
                fail = self.refresh_activity_calls > 1
                if fail:
                    self.refresh_failed_calls += 1
                    self.calls += 1
            if fail:
                raise authorization_error()
        value, usage = super().generate(request, schema, *args)
        if packet['stage'] == 'grouping':
            value['domains'][0]['activity_memberships'] = [
                record('ActivityMembership', activity_id=activity_id,
                       role='primary', claim_ids=['claim:domain'])
                for activity_id in packet['activity_ids']]
        return value, usage


class InitialAuthorizationProvider(Provider):
    def generate(self, *args):
        self.calls += 1
        raise authorization_error()


class RepairCircuitProvider(Provider):
    def __init__(self):
        super().__init__()
        self.fail_repair = False
        self.repair_calls = 0

    def generate(self, request, schema, *args):
        if self.fail_repair and request['packet']['stage'] == 'activity':
            self.calls += 1
            self.repair_calls += 1
            if self.repair_calls == 1:
                # Wire-valid, but semantic coverage validation rejects it and
                # requests correction through the existing repair path.
                return encode(record('ActivityPayload'),
                              DEFINITIONS['ActivityPayload']), {
                    'last': {'inputTokens': 10, 'outputTokens': 10}}
            raise authorization_error()
        return super().generate(request, schema, *args)


def test_petclinic_sized_initial_403_stops_fanout_without_budget_relabel(
        tmp_path, monkeypatch):
    monkeypatch.setattr(Synthesis, 'activity_work', singleton_hierarchy)
    for index in range(95):
        (tmp_path / f'controller_{index:03}.py').write_text(
            f"@app.get('/owners/{index}')\n"
            f'def owner_{index}():\n'
            f'    return {index}\n')
    provider = InitialAuthorizationProvider()
    config = {'business_domains': {'provider_concurrency': 4}}
    started = time.monotonic()
    model, status = discover(tmp_path, config, provider)
    elapsed = time.monotonic() - started

    assert model is None and not paths(tmp_path)['model'].exists()
    assert paths(tmp_path)['facts'].exists()
    assert status['coverage']['anchors_total'] == 95
    assert status['phase'] == 'unavailable'
    assert status['freshness'] == 'missing'
    assert status['execution_mode'] == 'hierarchical'
    assert status['root_reconciled'] is False
    assert status['error']['code'] == 'PROVIDER_UNAVAILABLE'
    assert status['error']['retryable'] is False
    assert status['error']['provider_failure']['category'] == 'authorization_denied'
    assert status['limits']['requests'] == provider.calls == 1
    assert status['limits']['retries'] == 0
    assert status['limits']['truncated'] is False
    assert all(warning['code'] != 'BUILD_BUDGET'
               for warning in status['warnings'])
    assert elapsed < 10


def test_provider_circuit_during_semantic_repair_preserves_publication_and_cache(
        tmp_path):
    (tmp_path / 'service.py').write_text(
        "@app.post('/orders')\ndef create(order):\n    return order\n")
    provider = RepairCircuitProvider()
    previous, status = discover(tmp_path, provider=provider)
    assert previous and status['phase'] == 'partial'
    publication = paths(tmp_path)['model']
    published = publication.read_bytes()
    cache_dir = tmp_path / '.speed/context/business-domain-cache'
    cached = {path: path.read_bytes() for path in cache_dir.glob('*.json')}

    (tmp_path / 'service.py').write_text(
        "@app.post('/orders')\ndef create(order):\n    return {'changed': order}\n")
    provider.fail_repair = True
    preserved, failed = discover(tmp_path, provider=provider)

    assert preserved == previous and publication.read_bytes() == published
    assert failed['phase'] == 'unavailable' and failed['freshness'] == 'stale'
    assert failed['error']['code'] == 'PROVIDER_UNAVAILABLE'
    assert failed['error']['provider_failure']['category'] == 'authorization_denied'
    assert failed['limits']['requests'] == provider.repair_calls == 3
    assert failed['limits']['retries'] == 2
    assert failed['limits']['truncated'] is False
    assert all(warning['code'] != 'BUILD_BUDGET'
               for warning in failed['warnings'])
    assert all(path.read_bytes() == content for path, content in cached.items())
    assert {path for path in cache_dir.glob('*.json')
            if not path.name.startswith('pending-')} == set(cached)


def test_grocery_shaped_cached_hierarchy_repeated_403_preserves_24_activities(
        tmp_path, monkeypatch):
    monkeypatch.setattr(Synthesis, 'activity_work', singleton_hierarchy)
    grocery_sources(tmp_path)
    provider = GroceryProvider()
    config = {'business_domains': {
        'provider_concurrency': 1,
        'max_request_input_tokens': 100000,
        'max_request_output_tokens': 10000,
        'max_build_input_tokens': 1000000,
    }}

    previous, status = discover(tmp_path, config, provider)
    assert previous and status['phase'] == 'partial', status
    assert status['execution_mode'] == 'hierarchical'
    assert status['root_reconciled'] is True
    assert len(previous['activities']) == 24
    publication = paths(tmp_path)['model']
    published = publication.read_bytes()
    cache_dir = tmp_path / '.speed/context/business-domain-cache'
    cached = {path: path.read_bytes() for path in cache_dir.glob('*.json')}

    # The first six stable scopes remain cached. Of the other eighteen, one
    # validates before the next scope receives the repeated 403: the discarded
    # in-memory candidate is therefore the seven-activity Grocery shape.
    ordered_anchors = sorted(previous['anchors'])
    changed_paths = [
        tmp_path / previous['resources'][previous['anchors'][anchor_id][
            'source_id']]['name']
        for anchor_id in ordered_anchors[6:]
    ]
    assert len(changed_paths) == 18
    for path in changed_paths:
        path.write_text(path.read_text().replace('return order',
                                                "return {'changed': order}"))
    provider.refresh_failure = True
    validated_children = []
    original_accept_child = discovery.accept_activity_child

    def observe_child(model, packet, payload):
        if provider.refresh_failure:
            validated_children.append(tuple(packet['anchor_ids']))
        return original_accept_child(model, packet, payload)

    monkeypatch.setattr(discovery, 'accept_activity_child', observe_child)
    started = time.monotonic()
    preserved, failed = discover(tmp_path, config, provider)
    elapsed = time.monotonic() - started

    assert preserved == previous and len(preserved['activities']) == 24
    assert publication.read_bytes() == published
    assert failed['phase'] == 'unavailable'
    assert failed['freshness'] == 'stale'
    assert failed['execution_mode'] == 'hierarchical'
    assert failed['root_reconciled'] is False
    assert failed['error']['code'] == 'PROVIDER_UNAVAILABLE'
    assert failed['error']['retryable'] is False
    assert failed['error']['provider_failure']['category'] == 'authorization_denied'
    assert failed['error']['provider_failure']['native_status'] == '403'
    assert failed['limits']['requests'] == 4
    assert failed['limits']['retries'] == 1
    assert failed['limits']['truncated'] is False
    assert provider.refresh_activity_calls == 3
    assert provider.refresh_failed_calls == 2
    assert len(set(validated_children)) == 7
    assert all(warning['code'] != 'BUILD_BUDGET'
               for warning in failed['warnings'])
    assert any(warning['code'] == 'PROVIDER_UNAVAILABLE'
               and warning['subject_ids'] for warning in failed['warnings'])
    assert paths(tmp_path)['facts'].exists()
    assert elapsed < 10
    assert all(path.read_bytes() == content for path, content in cached.items())
    # Exactly one changed leaf and its independent verification completed.
    # Each has packet, exact-response and stable-checkpoint artifacts; neither
    # failed 403 produced cache artifacts.
    assert len(set(cache_dir.glob('*.json')) - set(cached)) == 6

    provider.refresh_failure = False
    provider.refresh_activity_calls = 0
    recovered, recovered_status = discover(tmp_path, config, provider)
    assert recovered and recovered['build_id'] != previous['build_id']
    assert recovered_status['phase'] == 'partial'
    assert recovered_status['execution_mode'] == 'hierarchical'
    assert recovered_status['root_reconciled'] is True
