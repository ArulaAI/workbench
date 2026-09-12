from lib.context.business_domains import discover
from lib.context.business_domain_context import participation
from lib.context.cross_task import build_cross_task_analysis,normalize_cross_task_analysis
from lib.context.assembly import assemble_architect
from test_business_domain_pipeline import Provider,source


def test_file_tasks_have_potential_business_participation_and_separate_cluster_overlap(tmp_path):
    source(tmp_path);model,_ = discover(tmp_path,provider=Provider())
    tasks=[{'id':'one','files_touched':['service.py']},{'id':'two','files_touched':['service.py']}]
    csg={'nodes':[{'id':'symbol','name':'service','file':'service.py','cluster':'cluster-code'}], 'edges':[]}
    result=build_cross_task_analysis(tasks,csg,business_model=model)
    assert result['schema_version']==2
    assert result['domain_overlap'][0]['domain_id'] in model['domains']
    assert result['domain_overlap'][0]['participation']=='potential'
    assert result['cluster_overlap'][0]['cluster']=='cluster-code'
    assert all(row['participation']=='potential' for row in participation(tasks,model))


def test_missing_business_model_does_not_turn_file_overlap_into_a_domain():
    tasks=[{'id':'one','files_touched':['shared']},{'id':'two','files_touched':['shared']}]
    result=build_cross_task_analysis(tasks)
    assert result['domain_overlap']==[] and result['business_status']=='unknown'
    assert result['file_overlap'][0]['file']=='shared'


def test_legacy_cross_task_records_are_projected_as_structure_without_mutation():
    old={'domain_overlap':[{'cluster':'old','tasks_touching':['one','two']}],'degraded':False}
    current=normalize_cross_task_analysis(old)
    assert current['domain_overlap']==[] and current['cluster_overlap']==old['domain_overlap']
    assert 'schema_version' not in old


def test_architect_gets_canonical_business_responsibility(tmp_path):
    source(tmp_path);model,_ = discover(tmp_path,provider=Provider())
    text=assemble_architect({}, {},business_model=model)
    assert 'Business Responsibilities' in text
    assert next(iter(model['domains'].values()))['name'] in text
    assert 'domain clusters' not in text


def test_shared_file_participation_does_not_require_a_shared_activity():
    from lib.context.business_domain_context import file_participation
    from lib.context.business_domain_schema import record
    model = record('DomainArtifact')
    for suffix in ('a','b'):
        sid, did = 'symbol:'+suffix, 'domain:'+suffix
        model['symbols'][sid] = record('Symbol', id=sid, file='service.ext')
        model['domains'][did] = record('Domain', id=did, support='partial',
            activity_memberships=[record('ActivityMembership',activity_id='activity:'+suffix,role='primary')],
            symbol_memberships=[record('SymbolMembership',symbol_id=sid,activity_id='activity:'+suffix)])
    assert file_participation(model) == {'service.ext':{'domain:a','domain:b'}}
    model['domains']['domain:b']['review_state'] = 'rejected'
    assert file_participation(model) == {'service.ext':{'domain:a'}}
