"""Actions in shared UI components are anchored once per caller route.

A component composed by several routed pages shows its action on each of
those routes, so each route gets its own route-scoped action anchor, evidenced
by the route and the composition that displays it. Every caller still reaches
the shared component and its effects through the graph, and the branch each
caller takes keeps its own endpoint.
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


def _per_route(facts):
    return {anchor['operation']['path']: anchor for anchor in _actions(facts, 'OwnerEditor')}


def test_shared_action_has_one_anchor_per_caller_route(facts):
    # Was: exactly one OwnerEditor.onSubmit anchor. Now one per route whose
    # page composes OwnerEditor, and no extra component-scoped anchor.
    actions = _per_route(facts)
    assert set(actions) == set(CALLER_ROUTES)
    for anchor in actions.values():
        registration = _registration(anchor)['registration']
        assert registration['target'] == 'OwnerEditor.onSubmit'
        assert registration['event'] == 'onClick'
    assert len([anchor for anchor in facts['anchors'].values()
                if _registration(anchor)
                and _registration(anchor)['registration']['target']
                == 'OwnerEditor.onSubmit']) == len(CALLER_ROUTES)


def test_shared_action_is_not_dropped(facts):
    # Unchanged intent, now checked for every per-route anchor.
    for action in _actions(facts, 'OwnerEditor'):
        trace = _trace(facts, action)
        assert {'OwnerEditor.render', 'OwnerEditor.onSubmit'} <= _symbols(facts, trace)
        assert any(facts['edges'][edge]['kind'] == 'routes_to' for edge in trace['edge_ids'])


def test_every_caller_route_reaches_the_shared_component_and_shared_effects(facts):
    actions = _per_route(facts)
    effect = next(effect for effect in facts['effects'].values()
                  if effect['origin_ref']['kind'] == 'symbol'
                  and _name(facts, effect['origin_ref']['id']) == 'loadVets')
    for route in CALLER_ROUTES:
        trace = _route_trace(facts, route)
        assert 'OwnerEditor.render' in _symbols(facts, trace)
        # The route's own action and its page meet at the shared component.
        action_trace = _trace(facts, actions[route])
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


def test_shared_action_is_scoped_to_each_caller_route(facts):
    # Was: identity and scope named OwnerEditor.render and the path was None.
    # Now each anchor's identity, scope and operation path are its route.
    for route, action in _per_route(facts).items():
        representation = _registration(action)
        assert representation['identity_key'].startswith(f'ui:client:action:{route}:onClick:')
        assert representation['registration']['scope'] == route
        assert representation['registration']['label'] == 'Save Owner'
        assert action['operation']['path'] == route


def test_shared_action_anchor_never_takes_another_caller_route(facts):
    # Was: no caller route appeared in the single anchor. Now each anchor names
    # exactly its own route and no component-scoped identity remains.
    for route, action in _per_route(facts).items():
        representation = _registration(action)
        for other in CALLER_ROUTES:
            if other != route:
                assert f':{other}:' not in representation['identity_key']
        assert 'OwnerEditor.render' not in representation['identity_key']
    # The contrast is unchanged: a directly routed component is route-scoped.
    [direct] = _actions(facts, 'VisitEditor')
    assert _registration(direct)['identity_key'].startswith(
        'ui:client:action:/visits/new:onClick:')
    assert direct['operation']['path'] == '/visits/new'
