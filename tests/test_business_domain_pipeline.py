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
