"""Public discovery lifecycle tests for the whole-graph protocol."""
from lib.context.business_domain_schema import read_json
from lib.context.business_domains import discover, load, paths
from tests.business_domains.provider_fixture import PassingProvider, write_service


def test_provider_limits_are_identical_in_facts_status_and_model(tmp_path):
    write_service(tmp_path)
    provider = PassingProvider()

    model, status = discover(tmp_path, provider=provider)
    facts = read_json(paths(tmp_path)['facts'])
    expected = {
        'provider_context_tokens': 200_000,
        'provider_max_output_tokens': 8_000,
        'effective_request_input_tokens': 200_000,
        'effective_request_output_tokens': 8_000,
        'output_limit_enforcement': 'provider',
    }

    for artifact in (facts, status, model):
        assert {key: artifact['limits'][key] for key in expected} == expected


def test_refresh_publishes_verified_whole_graph_candidate(tmp_path):
    write_service(tmp_path)
    provider = PassingProvider()

    model, status = discover(tmp_path, provider=provider)

    assert model is not None and model['domains']
    assert status['root_reconciled'] is True
    assert status['execution_mode'] == 'whole_graph'
    assert status['limits']['semantic_units_total'] == 1
    assert status['limits']['semantic_units_validated'] == 1
    assert load(tmp_path)[0]['build_id'] == model['build_id']


def test_failed_refresh_preserves_last_verified_publication(tmp_path):
    write_service(tmp_path)
    provider = PassingProvider()
    published, _ = discover(tmp_path, provider=provider)
    original = paths(tmp_path)['model'].read_bytes()
    (tmp_path / 'service.py').write_text(
        "@app.post('/orders')\n"
        "def create(order):\n"
        "    return {'accepted': order}\n")
    provider.fail = True

    retained, status = discover(tmp_path, provider=provider)

    assert retained['build_id'] == published['build_id']
    assert paths(tmp_path)['model'].read_bytes() == original
    assert status['phase'] == 'unavailable'
    assert status['error']['code'] == 'PROVIDER_UNAVAILABLE'


# ── F1: fatal source-ownership faults and supersession keep publication ──

import pytest


def _published(tmp_path):
    write_service(tmp_path)
    provider = PassingProvider()
    published, _ = discover(tmp_path, provider=provider)
    return provider, published, paths(tmp_path)['model'].read_bytes()


@pytest.mark.parametrize('fault, code', [('registry', 'ADAPTER_REGISTRY_INVALID'),
                                         ('prepare', 'ADAPTER_UNAVAILABLE')])
def test_fatal_ownership_faults_keep_publication_and_write_no_new_facts(
        tmp_path, monkeypatch, fault, code):
    from lib.context import business_domain_extract
    from lib.context.business_domain_adapters import rules
    from lib.context.language_registry import RegistryConfigurationError
    provider, published, original = _published(tmp_path)
    facts_before = paths(tmp_path)['facts'].read_bytes()
    if fault == 'registry':
        monkeypatch.setattr(business_domain_extract.registry, 'load_error',
                            RegistryConfigurationError('registry_value_invalid'))
    else:
        monkeypatch.setattr(rules, 'prepare',
                            lambda *args: (_ for _ in ()).throw(RuntimeError('detail')))

    retained, status = discover(tmp_path, provider=provider)

    assert retained['build_id'] == published['build_id']
    assert paths(tmp_path)['model'].read_bytes() == original
    assert paths(tmp_path)['facts'].read_bytes() == facts_before
    assert status['error']['code'] == code
    assert 'detail' not in status['error']['message']


def test_source_change_before_publication_supersedes_the_attempt(tmp_path, monkeypatch):
    from lib.context import business_domains
    provider, published, original = _published(tmp_path)
    scan = business_domains.scan_inventory

    def changed_then_scanned(root, config):
        (tmp_path / 'service.py').write_text(
            "@app.get('/orders')\ndef list_orders():\n    return []\n")
        return scan(root, config)
    monkeypatch.setattr(business_domains, 'scan_inventory', changed_then_scanned)
    (tmp_path / 'service.py').write_text(
        "@app.post('/orders')\ndef create(order):\n    return order\n")

    retained, status = discover(tmp_path, provider=provider)

    assert status['phase'] == 'superseded'
    assert status['error']['code'] == 'SUPERSEDED'
    assert retained['build_id'] == published['build_id']
    assert paths(tmp_path)['model'].read_bytes() == original


def test_artifact_contract_states_the_attempt_boundary():
    from pathlib import Path
    contract = (Path(__file__).resolve().parents[1] /
                'specs/tech/contracts/business-domain-artifacts.md').read_text()
    assert ('may write its attempt FactsArtifact and StatusArtifact and may add immutable '
            'snapshot blobs, but it cannot replace the prior validated DomainArtifact, '
            'published build ID, baseline or history') in contract


# ── G2: entry-point gaps make a published run partial and are listed ─────

def _publish(root, extra=None):
    root.mkdir(parents=True, exist_ok=True)
    write_service(root)
    for name, text in (extra or {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return discover(root, provider=PassingProvider())


def test_an_entry_point_gap_publishes_partial_and_lists_the_gaps(tmp_path):
    from lib.context.business_domains import publication_status
    clean, _ = _publish(tmp_path / 'clean')
    gapped, status = _publish(tmp_path / 'gapped', {
        'src/OrdersApi.cs': 'app.MapGet("/orders", () => Results.Ok());\n'})
    assert clean is not None and gapped is not None
    # The fixture's rules adapter is partial on its own; set that aside so the
    # entry-point gap is the only difference between the two publications.
    def without_capability_gaps(model):
        return publication_status({**model, 'capabilities': []}, status['external_freshness'])
    assert not clean['coverage'].get('entrypoint_gaps')
    assert without_capability_gaps(clean) == 'complete'
    assert without_capability_gaps(gapped) == 'partial'
    assert gapped['status'] == 'partial'
    # The published model and the status artifact both list every gap.
    gaps = gapped['coverage']['entrypoint_gaps']
    assert {gap['code'] for gap in gaps} == {'ENTRYPOINT_DETECTION_UNAVAILABLE',
                                             'ENTRYPOINT_LIKELY_MISSED'}
    missed = next(gap for gap in gaps if gap['code'] == 'ENTRYPOINT_LIKELY_MISSED')
    assert (missed['path'], missed['line']) == ('src/OrdersApi.cs', 1)
    listed = {(warning['code'], warning['message']) for warning in status['warnings']}
    assert {(gap['code'], gap['message']) for gap in gaps} <= listed
