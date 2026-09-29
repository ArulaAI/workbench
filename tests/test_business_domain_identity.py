import pytest

from lib.context.business_domain_identity import reconcile, reconcile_anchors
from lib.context.business_domain_schema import DomainError, record, validate, validate_references


def model(groups):
    result=record('DomainArtifact')
    result['domains']={did:record('Domain',id=did,name=did,activity_memberships=[
        record('ActivityMembership',activity_id=aid,role='primary') for aid in members]) for did,members in groups.items()}
    return result


def test_unique_mutual_overlap_preserves_identity_and_all_references():
    previous=model({'domain:old':['activity:'+str(i) for i in range(10)]})
    current=model({'domain:new':['activity:'+str(i) for i in range(9)]})
    current['claims']['claim:one']=record('Claim',id='claim:one',subject_id='domain:new')
    reconcile(current,previous)
    assert list(current['domains'])==['domain:old']
    assert current['claims']['claim:one']['subject_id']=='domain:old'
    assert current['identity_changes'][0]['kind']=='retained'


def test_ambiguous_split_keeps_new_ids_and_records_lineage():
    previous=model({'domain:old':['activity:1','activity:2']})
    current=model({'domain:a':['activity:1'],'domain:b':['activity:2']})
    reconcile(current,previous)
    assert set(current['domains'])=={'domain:a','domain:b'}
    assert current['identity_changes']==[record('IdentityChange',kind='split',from_ids=['domain:old'],
        to_ids=['domain:a','domain:b'],reason='Overlapping activity memberships have no unique mutual identity match.')]


def test_name_similarity_does_not_preserve_unrelated_identity():
    previous=model({'domain:old':['activity:1']})
    current=model({'domain:new':['activity:2']})
    current['domains']['domain:new']['name']=previous['domains']['domain:old']['name']
    reconcile(current,previous)
    assert list(current['domains'])==['domain:new']
    assert {c['kind'] for c in current['identity_changes']}=={'added','retired'}


def test_small_overlap_records_retirement_and_addition_without_reusing_identity():
    previous=model({'domain:old':['activity:1','activity:2','activity:3']})
    current=model({'domain:new':['activity:3','activity:4','activity:5']})
    reconcile(current,previous)
    assert list(current['domains'])==['domain:new']
    assert [(change['kind'],change['from_ids'],change['to_ids'])
            for change in current['identity_changes']]==[
        ('retired',['domain:old'],[]),('added',[],['domain:new'])]


def _operation():
    return record('Operation', protocol='http', name='owners', method='GET',
                  path='/owners', service_resource_id='resource:service')


def _representation(ident, role, identity_key, eligibility):
    return record('AnchorRepresentation', id='anchor_representation:'+ident,
                  role=role, identity_key=identity_key, source_id='resource:service',
                  symbol_id='symbol:'+ident, operation=_operation(),
                  eligibility=eligibility, visibility='external',
                  evidence_ids=['ev:'+ident], resolution='resolved', reason=None)


def _anchor(ident, representation):
    return record('Anchor', id='anchor:'+ident, kind='http',
                  source_id='resource:service', symbol_id=representation['symbol_id'],
                  operation=_operation(), status='candidate',
                  evidence_ids=representation['evidence_ids'], resolution='resolved',
                  reason=None, representations=[representation])


def test_anchor_component_is_order_independent_and_preserves_all_representations():
    registration = _representation('route', 'registration',
                                   'http:service:GET:/owners', 'eligible')
    implementation = _representation('z-method', 'implementation', None, 'supporting')
    route = _anchor('route', registration)
    route['correspondences'] = [record(
        'AnchorCorrespondence', id='anchor_correspondence:resolved',
        from_representation=registration['id'],
        to_representations=[implementation['id']],
        relationship_edges=['edge:selection'], state='resolved',
        evidence_ids=['ev:route', 'ev:z-method'], reason='Exact implementation link.')]
    current = {
        'anchors': {
            'anchor:route': route,
            'anchor:z-method': _anchor('z-method', implementation),
        },
        'traces': {
            'trace:route': {'anchor_id': 'anchor:route'},
            'trace:method': {'anchor_id': 'anchor:z-method'},
        },
        'coverage': record('Coverage'),
    }

    reconcile_anchors(current)

    assert len(current['anchors']) == 1
    canonical = next(iter(current['anchors'].values()))
    assert {item['id'] for item in canonical['representations']} == {
        registration['id'], implementation['id']}
    assert {trace['anchor_id'] for trace in current['traces'].values()} == {
        canonical['id']}
    assert current['coverage']['representations_total'] == 2
    assert current['coverage']['representations_canonicalized'] == 2


def test_inferred_anchor_correspondence_remains_reviewable_and_does_not_merge():
    registration = _representation('route', 'registration',
                                   'http:service:GET:/owners', 'eligible')
    implementation = _representation('method', 'implementation', None, 'supporting')
    route = _anchor('route', registration)
    route['correspondences'] = [record(
        'AnchorCorrespondence', id='anchor_correspondence:inferred',
        from_representation=registration['id'],
        to_representations=[implementation['id']], relationship_edges=[],
        state='inferred_review_required',
        evidence_ids=['ev:route', 'ev:method'], reason='Review required.')]
    current = {'anchors': {
        'anchor:route': route,
        'anchor:method': _anchor('method', implementation),
    }}

    reconcile_anchors(current)

    assert len(current['anchors']) == 2
    assert any(correspondence['state'] == 'inferred_review_required'
               for anchor in current['anchors'].values()
               for correspondence in anchor['correspondences'])


def test_anchor_correspondence_schema_bounds_candidates_and_closure_rejects_dangling():
    correspondence = record(
        'AnchorCorrespondence', id='anchor_correspondence:bounded',
        from_representation='anchor_representation:route',
        to_representations=['anchor_representation:'+str(index) for index in range(9)],
        relationship_edges=[], state='unresolved', evidence_ids=['ev:route'],
        reason='Candidates are bounded.')
    with pytest.raises(DomainError):
        validate(correspondence, 'AnchorCorrespondence')

    registration = _representation('route', 'registration',
                                   'http:service:GET:/owners', 'eligible')
    route = _anchor('route', registration)
    route['correspondences'] = [record(
        'AnchorCorrespondence', id='anchor_correspondence:dangling',
        from_representation=registration['id'],
        to_representations=['anchor_representation:missing'],
        relationship_edges=[], state='unresolved', evidence_ids=['ev:route'],
        reason='Missing target.')]
    current = {
        'resources': {'resource:service': {'id': 'resource:service'}},
        'symbols': {'symbol:route': {'id': 'symbol:route'}},
        'evidence': {'ev:route': {'id': 'ev:route'}},
        'anchors': {'anchor:route': route},
    }
    with pytest.raises(DomainError, match='missing representation'):
        validate_references(current)
