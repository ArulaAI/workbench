"""Exercise the public schema against persisted canonical artifacts."""
import asyncio

from dashboard.backend.schema import schema
from lib.context.business_domains import discover
from tests.business_domains.provider_fixture import PassingProvider, write_service


def execute(tmp_path, query, variables=None):
    result = asyncio.run(schema.execute(query,variable_values=variables,
        context_value={'project_root':str(tmp_path)}))
    assert not result.errors,result.errors
    return result.data


def test_detail_and_cursors_are_scoped_to_published_build(tmp_path):
    write_service(tmp_path); model,_ = discover(tmp_path,provider=PassingProvider())
    did = next(iter(model['domains']))
    query = '''query($id:ID!,$build:ID!,$after:String) {
      domain(id:$id,expectedBuildId:$build) {
        error {code currentBuildId}
        domain {name activityCount activities(first:1,after:$after) {
          edges {cursor node {id name outputBindingIds}}
          pageInfo {endCursor hasNextPage} error {code}
        }}
      }
    }'''
    variables = {'id':did,'build':model['build_id']}
    result = execute(tmp_path,query,variables)['domain']
    assert result['error'] is None
    assert result['domain']['activityCount'] == 1
    cursor = result['domain']['activities']['pageInfo']['endCursor']
    page = execute(tmp_path,query,{**variables,'after':cursor})['domain']['domain']['activities']
    assert page['edges'] == [] and page['error'] is None
    invalid = execute(tmp_path,query,{**variables,'after':'bad cursor'})['domain']['domain']['activities']
    assert invalid['error']['code'] == 'INVALID_CURSOR'
    stale = execute(tmp_path,query,{**variables,'build':'old-build'})['domain']
    assert stale['domain'] is None and stale['error']['currentBuildId'] == model['build_id']
    missing = execute(tmp_path,query,{**variables,'id':'domain:missing'})['domain']
    assert missing['domain'] is None and missing['error']['code'] == 'DOMAIN_NOT_FOUND'


def test_review_mutation_and_unavailable_cancel_return_typed_results(tmp_path):
    write_service(tmp_path); model,_ = discover(tmp_path,provider=PassingProvider())
    did = next(iter(model['domains']))
    result = execute(tmp_path,'''mutation($input:DomainReviewInput!) {
      reviewDomain(input:$input) {accepted buildId domainIds error {code}}
    }''',{'input':{'expectedBuildId':model['build_id'],'operation':'RENAME',
                  'domainIds':[did],'name':'Reviewed name','explanation':'Business terminology'}})['reviewDomain']
    assert result['accepted'] and result['domainIds'] == [did] and result['error'] is None
    status = execute(tmp_path,'{domainDiscoveryStatus {phase publishedBuildId executionMode currentScopeId rootReconciled coverage {anchorsTotal}}}')
    assert status['domainDiscoveryStatus']['publishedBuildId'] == result['buildId']
    assert status['domainDiscoveryStatus']['executionMode'] == 'whole_graph'
    assert status['domainDiscoveryStatus']['currentScopeId'] is None
    assert status['domainDiscoveryStatus']['rootReconciled'] is True
    cancel = execute(tmp_path,'mutation {cancelDomainBuild(buildId:"finished") {accepted error {code}}}')
    assert cancel['cancelDomainBuild'] == {'accepted':False,'error':{'code':'BUILD_NOT_RUNNING'}}


def test_status_read_on_missing_repository_does_not_create_artifacts(tmp_path):
    result = execute(tmp_path,'{domainDiscoveryStatus {phase attemptBuildId publishedBuildId executionMode currentScopeId rootReconciled}}')
    assert result['domainDiscoveryStatus'] == {'phase':'idle','attemptBuildId':None,
        'publishedBuildId':None,'executionMode':None,'currentScopeId':None,
        'rootReconciled':False}
    assert not (tmp_path/'.speed').exists()


def test_trace_obligations_are_typed_and_scoped_to_the_published_activity(tmp_path):
    (tmp_path/'api.yaml').write_text(
        'openapi: 3.0.1\npaths:\n  /visits:\n    post:\n      operationId: addVisit\n')
    model, _ = discover(tmp_path, provider=PassingProvider())
    query = '''query($id:ID!,$build:ID!) {
      domain(id:$id,expectedBuildId:$build) {domain {activities(first:1) {
        edges {node {traces {id obligationIds obligations {id traceId kind status reasonCode originRef {kind id}}}}}
      }}}
    }'''
    result = execute(tmp_path, query, {'id':next(iter(model['domains'])), 'build':model['build_id']})
    trace = result['domain']['domain']['activities']['edges'][0]['node']['traces'][0]
    assert sorted(o['id'] for o in trace['obligations']) == sorted(trace['obligationIds'])
    assert all(o['traceId'] == trace['id'] for o in trace['obligations'])
    assert any(o['reasonCode'] == 'IMPLEMENTATION_NOT_REACHED' for o in trace['obligations'])


def test_legacy_trace_without_new_optional_fields_remains_queryable(tmp_path):
    from lib.context.business_domains import paths
    from lib.context.business_domain_schema import atomic_write
    write_service(tmp_path)
    model, _ = discover(tmp_path, provider=PassingProvider())
    model['schema_version'] = 1
    model.pop('trace_obligations')
    for trace in model['traces'].values():
        trace.pop('obligation_ids')
    atomic_write(paths(tmp_path)['model'], model)
    result = execute(tmp_path, '''query($id:ID!,$build:ID!) {
      domain(id:$id,expectedBuildId:$build) {domain {activities(first:1) {
        edges {node {traces {obligationIds obligations {id}}}}
      }}}
    }''', {'id':next(iter(model['domains'])), 'build':model['build_id']})
    traces = result['domain']['domain']['activities']['edges'][0]['node']['traces']
    assert all(t == {'obligationIds':[], 'obligations':[]} for t in traces)


def test_frontend_documents_match_the_real_schema():
    import re
    from pathlib import Path
    from graphql import parse,validate
    directory = Path(__file__).parents[1]/'dashboard/frontend/lib/graphql/queries'
    for name in ('business-domains.ts','repository-digest.ts'):
        for document in re.findall(r'gql`(.*?)`', (directory/name).read_text(),re.S):
            assert not validate(schema._schema,parse(document)),name


def test_domain_reasoning_pages_include_unknown_ownership_and_scoped_claims(tmp_path):
    from lib.context.business_domain_schema import record, atomic_write
    from lib.context.business_domains import paths
    write_service(tmp_path); model,_ = discover(tmp_path,provider=PassingProvider())
    did = next(iter(model['domains'])); domain = model['domains'][did]
    concept = record('Concept',id='concept:purchase',name='Purchase request')
    model['concepts'][concept['id']] = concept; domain['concepts'] = [concept['id']]
    ownership = record('Ownership',id='ownership:purchase',concept_id=concept['id'],domain_id=did,
        kind='unknown',rationale='Reading the request does not establish authority',support='partial')
    model['ownerships'][ownership['id']] = ownership; domain['ownership_ids'] = [ownership['id']]
    domain['alternatives'] = [record('BoundaryItem',explanation='Receiving may warrant a separate responsibility')]
    atomic_write(paths(tmp_path)['model'],model)
    result = execute(tmp_path,'''query($id:ID!,$build:ID!) {
      domain(id:$id,expectedBuildId:$build) {domain {
        alternatives {explanation}
        concepts(first:1) {edges {cursor node {name}} error {code}}
        ownerships(first:1) {edges {node {kind rationale concept {name}}} error {code}}
        claims(first:1) {edges {node {text semanticReview}} pageInfo {hasNextPage} error {code}}
      }}
    }''',{'id':did,'build':model['build_id']})['domain']['domain']
    assert result['concepts']['edges'][0]['node']['name'] == 'Purchase request'
    assert result['ownerships']['edges'][0]['node']['kind'] == 'unknown'
    assert result['ownerships']['edges'][0]['node']['concept']['name'] == 'Purchase request'
    assert result['alternatives'][0]['explanation'].startswith('Receiving')
    assert result['claims']['edges'] and result['claims']['pageInfo']['hasNextPage']
    from dashboard.backend.resolvers.business_domains import connection
    cursor = result['concepts']['edges'][0]['cursor']
    assert connection(tmp_path,model['build_id'],did,'claims',1,cursor).error.code == 'INVALID_CURSOR'


def test_unassigned_pages_preserve_reasons_and_reject_other_builds(tmp_path):
    from lib.context.business_domain_schema import record, atomic_write
    from lib.context.business_domains import paths
    write_service(tmp_path); model,_ = discover(tmp_path,provider=PassingProvider())
    aid = next(iter(model['activities']))
    model['unassigned'] = [record('Unassigned',subject_id=aid,status=state,reason=reason)
        for state,reason in [('pending','Grouping budget reached'),('excluded','No business-purpose evidence')]]
    atomic_write(paths(tmp_path)['model'],model)
    query = '''query($build:ID!,$after:String) {
      domainUnassigned(expectedBuildId:$build,first:1,after:$after) {
        edges {cursor node {subjectId status reason}}
        pageInfo {endCursor hasNextPage} error {code}
      }
    }'''
    variables = {'build':model['build_id']}
    first = execute(tmp_path,query,variables)['domainUnassigned']
    assert first['edges'][0]['node']['reason'] == 'Grouping budget reached'
    assert first['pageInfo']['hasNextPage']
    second = execute(tmp_path,query,{**variables,'after':first['pageInfo']['endCursor']})['domainUnassigned']
    assert second['edges'][0]['node']['reason'] == 'No business-purpose evidence'
    assert not second['pageInfo']['hasNextPage']
    stale = execute(tmp_path,query,{'build':'different'})['domainUnassigned']
    assert stale['error']['code'] == 'STALE_BUILD' and not stale['edges']
