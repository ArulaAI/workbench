import copy

from lib.context.business_domain_identity import reconcile_anchors
from lib.context.business_domain_schema import DEFAULTS, identifier, record, validate


def operation(name, method, path):
    return record('Operation', protocol='http', name=name, method=method, path=path,
                  service_resource_id='resource:service')


def representation(ident, role, identity_key, symbol, eligibility, evidence):
    return record('AnchorRepresentation', id='anchor_representation:'+ident, role=role,
                  identity_key=identity_key, source_id='resource:service', symbol_id=symbol,
                  operation=operation('same-name', 'GET', '/'+ident), eligibility=eligibility,
                  visibility='external' if eligibility == 'eligible' else 'internal',
                  evidence_ids=[evidence], resolution='resolved', reason=None)


def anchor(ident, representation):
    return record('Anchor', id='anchor:'+ident, kind='http', source_id='resource:service',
                  symbol_id=representation['symbol_id'], operation=representation['operation'],
                  status='candidate', evidence_ids=representation['evidence_ids'],
                  resolution='resolved', reason=None, representations=[representation])


def correspondence(source, target, state='resolved'):
    return record('AnchorCorrespondence', id='anchor_correspondence:'+source['id'].split(':')[1],
                  from_representation=source['id'], to_representations=[target['id']],
                  relationship_edges=['edge:selection'], state=state,
                  evidence_ids=source['evidence_ids'] + target['evidence_ids'],
                  reason='Adapter resolved the registered operation to this implementation.')


def test_resolved_registration_and_implementation_get_one_stable_canonical_anchor():
    registered = representation('route', 'registration', 'http:service:GET:/owners',
                                'symbol:route', 'eligible', 'ev:route')
    implementation = representation('method', 'implementation', None,
                                     'symbol:method', 'supporting', 'ev:method')
    route = anchor('route', registered)
    route['correspondences'] = [correspondence(registered, implementation)]
    model = {'anchors': {'anchor:method': anchor('method', implementation), 'anchor:route': route},
             'traces': {'trace:route': {'anchor_id': 'anchor:route'},
                        'trace:method': {'anchor_id': 'anchor:method'}}}

    replacements = reconcile_anchors(model)

    canonical_id = identifier('anchor', 'canonical', 'http:service:GET:/owners')
    assert set(model['anchors']) == {canonical_id}
    assert replacements == {'anchor:method': canonical_id, 'anchor:route': canonical_id}
    assert {item['id'] for item in model['anchors'][canonical_id]['representations']} == {
        registered['id'], implementation['id']}
    assert {trace['anchor_id'] for trace in model['traces'].values()} == {canonical_id}
    validate(model['anchors'][canonical_id], 'Anchor')

    reordered = {'anchors': dict(reversed(list(copy.deepcopy({
        'anchor:method': anchor('method', implementation), 'anchor:route': route}).items())))}
    reconcile_anchors(reordered)
    assert set(reordered['anchors']) == {canonical_id}


def test_equal_names_and_identity_keys_without_correspondence_do_not_merge():
    first = representation('first', 'registration', 'http:shared', 'symbol:first', 'eligible', 'ev:first')
    second = representation('second', 'registration', 'http:shared', 'symbol:second', 'eligible', 'ev:second')
    model = {'anchors': {'anchor:first': anchor('first', first),
                         'anchor:second': anchor('second', second)}}

    assert reconcile_anchors(model) == {}
    assert set(model['anchors']) == {'anchor:first', 'anchor:second'}
    assert {item['eligibility'] for item in model['anchors'].values()} == {'unresolved'}
    assert all('without a resolved correspondence' in item['reason'] for item in model['anchors'].values())


def test_ambiguous_correspondence_is_preserved_and_cannot_absorb_implementation():
    registered = representation('route', 'registration', 'http:route',
                                'symbol:route', 'eligible', 'ev:route')
    implementation = representation('method', 'implementation', None,
                                     'symbol:method', 'supporting', 'ev:method')
    route = anchor('route', registered)
    route['correspondences'] = [correspondence(registered, implementation, 'ambiguous')]
    model = {'anchors': {'anchor:route': route, 'anchor:method': anchor('method', implementation)}}

    reconcile_anchors(model)

    canonical_id = identifier('anchor', 'canonical', 'http:route')
    assert set(model['anchors']) == {canonical_id, 'anchor:method'}
    assert model['anchors']['anchor:method']['eligibility'] == 'supporting'
    assert model['anchors'][canonical_id]['correspondences'][0]['state'] == 'ambiguous'


def test_implementation_body_alone_is_supporting_not_an_entrypoint():
    implementation = representation('helper', 'implementation', None,
                                     'symbol:helper', 'supporting', 'ev:helper')
    model = {'anchors': {'anchor:helper': anchor('helper', implementation)}}

    assert reconcile_anchors(model) == {}
    assert model['anchors']['anchor:helper']['canonical_anchor_id'] is None
    assert model['anchors']['anchor:helper']['eligibility'] == 'supporting'


def test_extraction_reconciles_canonical_identity_before_tracing_and_scheduling(tmp_path, monkeypatch):
    from lib.context.business_domain_extract import Extractor
    from lib.context.business_domain_synthesis import packet_for

    (tmp_path/'service.py').write_text(
        "@app.get('/owners')\ndef owners():\n    return []\n")
    observe = Extractor._observations

    def observe_with_adapter_identity(extractor):
        observe(extractor)
        anchor = next(iter(extractor.facts['anchors'].values()))
        anchor['representations'] = [record(
            'AnchorRepresentation', id='anchor_representation:owners-route',
            role='registration', identity_key='http:service:GET:/owners',
            source_id=anchor['source_id'], symbol_id=anchor['symbol_id'],
            operation=anchor['operation'], eligibility='eligible', visibility='external',
            evidence_ids=anchor['evidence_ids'], resolution='resolved', reason=None)]

    monkeypatch.setattr(Extractor, '_observations', observe_with_adapter_identity)
    facts, units = Extractor(tmp_path, DEFAULTS).extract()

    canonical_id = identifier('anchor', 'canonical', 'http:service:GET:/owners')
    assert set(facts['anchors']) == {canonical_id}
    assert {unit.anchor_id for unit in units if unit.anchor_id} == {canonical_id}
    trace = next(iter(facts['traces'].values()))
    assert trace['anchor_id'] == canonical_id
    packet = packet_for(facts, 'activity', [canonical_id])
    assert packet['anchor_ids'] == [canonical_id]
    assert {item['anchor_id'] for item in packet['context']['traces'].values()} == {canonical_id}


def test_extraction_uses_adapter_declared_route_identity(tmp_path):
    from lib.context.business_domain_extract import Extractor

    (tmp_path/'service.py').write_text(
        "@app.get('/owners')\ndef owners():\n    return []\n")
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()

    anchor = next(iter(facts['anchors'].values()))
    assert anchor['canonical_anchor_id'] == identifier(
        'anchor', 'canonical', 'http:repository:GET:/owners')
    assert anchor['eligibility'] == 'eligible'
    assert [item['role'] for item in anchor['representations']] == ['registration']
    assert [item['state'] for item in anchor['correspondences']] == ['resolved']
