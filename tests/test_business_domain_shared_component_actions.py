"""Actions in shared UI components keep one conservative, component-scoped anchor.

A component composed by several routed pages exposes its action once. The
action names no caller route, because choosing one caller would misattribute
it; each caller reaches the shared component and its effects through the
graph instead, and the branch each caller takes keeps its own endpoint.
"""
import pytest

from tests.test_business_domain_endpoint_links import (
    BACKEND, OWNER_EDITOR, UTIL, VISIT_EDITOR, WEBPACK_DEV, _extract, _name, _resolved)

ROUTES = """import * as React from 'react';
import { Route } from 'react-router';
import NewOwnerPage from './NewOwnerPage';
import EditOwnerPage from './EditOwnerPage';
import VisitEditor from './VisitEditor';

export default () => (
  <Route>
    <Route path='/owners/new' component={NewOwnerPage} />
    <Route path='/owners/:ownerId/edit' component={EditOwnerPage} />
    <Route path='/visits/new' component={VisitEditor} />
  </Route>
);
"""

SHARED_LOADER = """import { url } from './util';

export function loadVets() {
  return fetch(url('api/vets')).then(response => response.json());
}
"""


def _caller(name):
    return f"""import * as React from 'react';
import OwnerEditor from './OwnerEditor';
import {{ loadVets }} from './loadVets';

export default class {name} extends React.Component<any, any> {{
  componentDidMount() {{
    loadVets();
  }}

  render() {{
    return <OwnerEditor />;
  }}
}}
"""


CLIENT = {
    'client/package.json': '{"name": "client"}\n',
    'client/webpack.config.js': WEBPACK_DEV,
    'client/src/util/index.tsx': UTIL,
    'client/src/routes.tsx': ROUTES,
    'client/src/loadVets.tsx': SHARED_LOADER,
    'client/src/OwnerEditor.tsx': OWNER_EDITOR,
    'client/src/NewOwnerPage.tsx': _caller('NewOwnerPage'),
    'client/src/EditOwnerPage.tsx': _caller('EditOwnerPage'),
    'client/src/VisitEditor.tsx': VISIT_EDITOR,
}

CALLER_ROUTES = ('/owners/new', '/owners/:ownerId/edit')


@pytest.fixture(scope='module')
def facts(tmp_path_factory):
    return _extract(tmp_path_factory.mktemp('shared'), {**BACKEND, **CLIENT})


def _registration(anchor):
    return next((item for item in anchor['representations']
                 if item['role'] == 'registration'), None)


def _actions(facts, component):
    return [anchor for anchor in facts['anchors'].values()
            if anchor['kind'] == 'ui' and _registration(anchor)
            and _registration(anchor)['registration']['kind'] == 'action'
            and facts['symbols'][anchor['symbol_id']]['file'].endswith(f'/{component}.tsx')]


def _trace(facts, anchor):
    return next(trace for trace in facts['traces'].values()
                if trace['anchor_id'] == anchor['id'])


def _route_trace(facts, route):
    key = f'ui:client:route:{route}'
    anchor = next(anchor for anchor in facts['anchors'].values()
                  if _registration(anchor) and _registration(anchor)['identity_key'] == key)
    return _trace(facts, anchor)


def _symbols(facts, trace):
    return {_name(facts, symbol) for symbol in trace['symbol_ids']}


def test_shared_action_is_one_anchor_regardless_of_caller_count(facts):
    [action] = _actions(facts, 'OwnerEditor')
    registration = _registration(action)['registration']
    assert registration['target'] == 'OwnerEditor.onSubmit'
    assert registration['event'] == 'onClick'
    assert len([anchor for anchor in facts['anchors'].values()
                if _registration(anchor)
                and _registration(anchor)['registration']['target']
                == 'OwnerEditor.onSubmit']) == 1


def test_shared_action_is_not_dropped(facts):
    [action] = _actions(facts, 'OwnerEditor')
    trace = _trace(facts, action)
    assert {'OwnerEditor.render', 'OwnerEditor.onSubmit'} <= _symbols(facts, trace)
    assert any(facts['edges'][edge]['kind'] == 'routes_to' for edge in trace['edge_ids'])


def test_every_caller_route_reaches_the_shared_component_and_shared_effects(facts):
    [action] = _actions(facts, 'OwnerEditor')
    action_trace = _trace(facts, action)
    effect = next(effect for effect in facts['effects'].values()
                  if effect['origin_ref']['kind'] == 'symbol'
                  and _name(facts, effect['origin_ref']['id']) == 'loadVets')
    for route in CALLER_ROUTES:
        trace = _route_trace(facts, route)
        assert 'OwnerEditor.render' in _symbols(facts, trace)
        # The action and the caller's page meet at the shared component.
        assert _symbols(facts, trace) & _symbols(facts, action_trace) >= {'OwnerEditor.render'}
        # One effect record, attached to every caller that reaches it.
        assert trace['id'] in effect['trace_ids']
    assert len([item for item in facts['effects'].values()
                if item['origin_ref'] == effect['origin_ref']
                and item['kind'] == effect['kind']]) == 1


def test_each_caller_branch_keeps_its_own_endpoint(facts):
    assert _resolved(facts, 'OwnerEditor.onSubmit') == [
        'OwnerController.addOwner()', 'OwnerController.updateOwner(int)']
    conditions = {_name(facts, edge['to_ref']['id']): edge['condition']
                  for edge in facts['edges'].values()
                  if edge['kind'] == 'routes_to' and edge['resolution'] == 'resolved'
                  and _name(facts, edge['from_ref']['id']).startswith('OwnerEditor.onSubmit')}
    assert conditions['OwnerController.addOwner()'].startswith('owner.isNew')
    assert conditions['OwnerController.updateOwner(int)'].startswith('!(owner.isNew)')


def test_shared_action_stays_component_scoped(facts):
    [action] = _actions(facts, 'OwnerEditor')
    representation = _registration(action)
    assert representation['identity_key'].startswith(
        'ui:client:action:client/src/OwnerEditor.tsx::OwnerEditor.render:onClick:')
    assert representation['registration']['scope'] == (
        'client/src/OwnerEditor.tsx::OwnerEditor.render')
    assert action['operation']['path'] is None


def test_shared_action_never_takes_one_caller_route_identity(facts):
    [action] = _actions(facts, 'OwnerEditor')
    representation = _registration(action)
    for route in CALLER_ROUTES:
        assert route not in representation['identity_key']
        assert representation['registration']['scope'] != route
    # The contrast: an action in a directly routed component is route-scoped.
    [direct] = _actions(facts, 'VisitEditor')
    assert _registration(direct)['identity_key'].startswith(
        'ui:client:action:/visits/new:onClick:')
    assert direct['operation']['path'] == '/visits/new'
