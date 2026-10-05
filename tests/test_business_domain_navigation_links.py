"""React Router navigation links a router call to what the new location runs.

Reuses the miniature PetClinic of the endpoint-link tests and adds the
search-page shape: a route component whose button pushes its own route with a
new query, and whose ``componentWillReceiveProps`` loads the owners again.
"""
from tests.test_business_domain_endpoint_links import (
    BACKEND, CLIENT, _action_trace, _extract, _name, _trace, _trace_names)


ROUTES = """import * as React from 'react';
import { Route } from 'react-router';
import VetsPage from './VetsPage';
import OwnerEditor from './OwnerEditor';
import FindOwnersPage from './FindOwnersPage';
import OwnerPage from './OwnerPage';
import VetsShortcut from './VetsShortcut';
import OwnerJump from './OwnerJump';
import PlainJump from './PlainJump';

export default () => (
  <Route>
    <Route path='/vets' component={VetsPage} />
    <Route path='/owners/list' component={FindOwnersPage} />
    <Route path='/owners/new' component={OwnerEditor} />
    <Route path='/owners/:ownerId' component={OwnerPage} />
    <Route path='/shortcut' component={VetsShortcut} />
    <Route path='/jump' component={OwnerJump} />
    <Route path='/plain' component={PlainJump} />
  </Route>
);
"""


def _routed(name, method, body, label, imports="import { IRouter } from 'react-router';\n",
            extra=''):
    return f"""import * as React from 'react';
{imports}import {{ url }} from './util';

export default class {name} extends React.Component<any, any> {{
  context: any;

  static contextTypes = {{
    router: React.PropTypes.object.isRequired
  }};

  constructor(props) {{
    super(props);
    this.{method} = this.{method}.bind(this);
  }}
{extra}
  {method}() {{
    {body}
  }}

  render() {{
    return <button type='button' onClick={{this.{method}}}>{label}</button>;
  }}
}}
"""


FIND_OWNERS_PAGE = _routed('FindOwnersPage', 'submitSearchForm', """const { filter } = this.state;
    this.context.router.push({
      pathname: '/owners/list',
      query: { 'lastName': filter || '' }
    });""", 'Find Owner', extra="""
  componentWillReceiveProps(nextProps) {
    this.fetchData(nextProps.location.query.lastName);
  }

  fetchData(filter: string) {
    const query = filter ? encodeURIComponent(filter) : '';
    fetch(url('api/owners?lastName=' + query));
  }
""")
OWNER_PAGE = """import * as React from 'react';
export default class OwnerPage extends React.Component<any, any> {
  render() {
    return <div />;
  }
}
"""
VETS_SHORTCUT = _routed('VetsShortcut', 'openVets', "this.context.router.replace('/vets');", 'Open Vets')
OWNER_JUMP = _routed('OwnerJump', 'jump', "this.context.router.push({ pathname: '/owners/' + this.state.id });",
                     'Open Owner')
PLAIN_JUMP = _routed('PlainJump', 'jump', "this.context.router.push('/vets');", 'Go', imports='')

NAVIGATION = {
    'client/src/routes.tsx': ROUTES,
    'client/src/FindOwnersPage.tsx': FIND_OWNERS_PAGE,
    'client/src/OwnerPage.tsx': OWNER_PAGE,
    'client/src/VetsShortcut.tsx': VETS_SHORTCUT,
    'client/src/OwnerJump.tsx': OWNER_JUMP,
    'client/src/PlainJump.tsx': PLAIN_JUMP,
}


def _project(root):
    return _extract(root, {**BACKEND, **CLIENT, **NAVIGATION})


def _navigations(facts, origin):
    return [edge for edge in facts['edges'].values() if edge['kind'] == 'navigates_to'
            and _name(facts, edge['from_ref']['id']) == origin]


def test_push_to_own_route_reaches_the_props_update_lifecycle(tmp_path):
    facts = _project(tmp_path)
    edge, = _navigations(facts, 'FindOwnersPage.submitSearchForm')
    assert edge['resolution'] == 'resolved' and edge['reason'] is None
    # The route renders this component, so it stays mounted and receives props.
    assert _name(facts, edge['to_ref']['id']) == 'FindOwnersPage.componentWillReceiveProps'
    excerpts = ' '.join(facts['evidence'][item]['excerpt'] for item in edge['evidence_ids'])
    assert 'this.context.router.push' in excerpts and 'contextTypes' in excerpts
    assert "path='/owners/list'" in excerpts


def test_search_button_trace_reaches_the_service_implementation(tmp_path):
    facts = _project(tmp_path)
    trace = _action_trace(facts, 'FindOwnersPage.submitSearchForm')
    names = _trace_names(facts, trace)
    assert {'FindOwnersPage.submitSearchForm', 'FindOwnersPage.componentWillReceiveProps',
            'FindOwnersPage.fetchData', 'OwnerController.listOwners',
            'ClinicService.findOwners', 'ClinicServiceImpl.findOwners'} <= names
    kinds = {facts['edges'][edge_id]['kind'] for edge_id in trace['edge_ids']
             if facts['edges'][edge_id]['resolution'] == 'resolved'}
    assert {'navigates_to', 'routes_to', 'selects_implementation'} <= kinds


def test_replace_to_another_route_reaches_that_route_registration(tmp_path):
    facts = _project(tmp_path)
    edge, = _navigations(facts, 'VetsShortcut.openVets')
    assert edge['resolution'] == 'resolved'
    vets = _trace(facts, 'ui:client:route:/vets')
    assert edge['to_ref']['id'] == facts['anchors'][vets['anchor_id']]['symbol_id']
    names = _trace_names(facts, _action_trace(facts, 'VetsShortcut.openVets'))
    assert {'VetsPage.componentDidMount', 'OwnerController.listVets',
            'ClinicServiceImpl.findVets'} <= names


def test_dynamic_segment_never_resolves_to_a_literal_route(tmp_path):
    facts = _project(tmp_path)
    edge, = _navigations(facts, 'OwnerJump.jump')
    assert edge['resolution'] == 'ambiguous' and edge['to_ref'] is None
    routes = {facts['symbols'][item]['qualified_name']: item for item in edge['candidate_target_ids']}
    patterns = sorted(facts['anchors'][anchor_id]['representations'][0]['identity_key']
                      for anchor_id, anchor in facts['anchors'].items()
                      if anchor['symbol_id'] in routes.values())
    # Routes are tried in order: '/owners/list' and '/owners/new' come before
    # '/owners/:ownerId', and a runtime id could equal either literal.
    assert patterns == ['ui:client:route:/owners/:ownerId', 'ui:client:route:/owners/list',
                        'ui:client:route:/owners/new']
    assert 'runtime path segment' in edge['reason']
    names = _trace_names(facts, _action_trace(facts, 'OwnerJump.jump'))
    assert 'FindOwnersPage.componentWillReceiveProps' not in names


def test_router_without_react_router_evidence_is_not_linked(tmp_path):
    facts = _project(tmp_path)
    assert not _navigations(facts, 'PlainJump.jump')
