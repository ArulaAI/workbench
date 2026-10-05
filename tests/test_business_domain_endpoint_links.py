"""Client HTTP requests link to the server endpoints that answer them.

A miniature of the PetClinic shape: a Spring controller under a context path,
an OpenAPI contract with one operation no controller implements, and a React
client whose requests go through ``url(path)`` and ``submitForm(method, path)``
helpers with build-time base URLs from two webpack configurations.
"""
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import DEFAULTS, validate_references


SERVICE = """package com.example;
public interface ClinicService {
  String findVets();
  String findOwners();
  String saveOwner();
  String saveVisit();
}
"""

SERVICE_IMPL = """package com.example;
import org.springframework.stereotype.Service;
@Service
public class ClinicServiceImpl implements ClinicService {
  @Override public String findVets() { return "vets"; }
  @Override public String findOwners() { return "owners"; }
  @Override public String saveOwner() { return "owner"; }
  @Override public String saveVisit() { return "visit"; }
}
"""

CONTROLLER = """package com.example;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.PathVariable;
@RestController
@RequestMapping("/api")
public class OwnerController {
  private final ClinicService clinicService;
  OwnerController(ClinicService clinicService) { this.clinicService = clinicService; }
  @GetMapping("/vets") public String listVets() { return clinicService.findVets(); }
  @GetMapping("/owners") public String listOwners() { return clinicService.findOwners(); }
  @GetMapping("/owners/{ownerId}") public String getOwner(@PathVariable int ownerId) { return clinicService.findOwners(); }
  @PostMapping("/owners") public String addOwner() { return clinicService.saveOwner(); }
  @PutMapping("/owners/{ownerId}") public String updateOwner(@PathVariable int ownerId) { return clinicService.saveOwner(); }
  @PostMapping("/owners/{ownerId}/visits") public String addVisit(@PathVariable int ownerId) { return clinicService.saveVisit(); }
}
"""

CONTRACT = """openapi: 3.0.1
servers:
  - url: http://localhost:9966/petclinic/api
paths:
  /owners/{ownerId}/pets/{petId}:
    put:
      operationId: updateOwnersPet
      responses:
        '204':
          description: updated
"""

UTIL = """declare var __API_SERVER_URL__;
const BACKEND_URL = (typeof __API_SERVER_URL__ === 'undefined' ? 'http://localhost:9966/petclinic' : __API_SERVER_URL__);

export const url = (path: string): string => `${BACKEND_URL}/${path}`;

export const submitForm = (method: string, path: string, data: any, onSuccess: (status: number) => void) => {
  const requestUrl = url(path);
  const fetchParams = {
    method: method,
    headers: { 'Accept': 'application/json' },
    body: JSON.stringify(data)
  };
  return fetch(requestUrl, fetchParams).then(response => onSuccess(response.status));
};
"""

WEBPACK_DEV = """var webpack = require('webpack');
module.exports = {
  plugins: [
    new webpack.DefinePlugin({
      __API_SERVER_URL__: JSON.stringify('http://localhost:9966/petclinic')
    })
  ]
};
"""

WEBPACK_PROD = """var webpack = require('webpack');
module.exports = {
  plugins: [
    // Production builds talk to a server on the default port.
    new webpack.DefinePlugin({
      'process.env': { 'NODE_ENV': JSON.stringify('production') },
      __API_SERVER_URL__: JSON.stringify('http://localhost:8080')
    })
  ]
};
"""

ROUTES = """import * as React from 'react';
import { Route } from 'react-router';
import VetsPage from './VetsPage';
import OwnerEditor from './OwnerEditor';
import VisitEditor from './VisitEditor';
import PetEditor from './PetEditor';

export default () => (
  <Route>
    <Route path='/vets' component={VetsPage} />
    <Route path='/owners/new' component={OwnerEditor} />
    <Route path='/visits/new' component={VisitEditor} />
    <Route path='/pets/edit' component={PetEditor} />
  </Route>
);
"""

VETS_PAGE = """import * as React from 'react';
import { url } from './util';

export default class VetsPage extends React.Component<any, any> {
  componentDidMount() {
    const requestUrl = url('api/vets');
    fetch(requestUrl).then(response => response.json());
  }

  render() {
    return <div />;
  }
}
"""


def _editor(name, call, label):
    return f"""import * as React from 'react';
import {{ submitForm }} from './util';

export default class {name} extends React.Component<any, any> {{
  constructor(props) {{
    super(props);
    this.onSubmit = this.onSubmit.bind(this);
  }}

  onSubmit(event) {{
    const {{ owner, pet }} = this.state;
    {call}
  }}

  render() {{
    return <button type='submit' onClick={{this.onSubmit}}>{label}</button>;
  }}
}}
"""


OWNER_EDITOR = _editor('OwnerEditor', """const url = owner.isNew ? '/api/owners' : '/api/owners/' + owner.id;
    submitForm(owner.isNew ? 'POST' : 'PUT', url, owner, status => status);""", 'Save Owner')
VISIT_EDITOR = _editor('VisitEditor', """const url = '/api/owners/' + owner.id + '/visits';
    submitForm('POST', url, owner, status => status);""", 'Add Visit')
PET_EDITOR = _editor('PetEditor', """submitForm('PUT', '/api/owners/' + owner.id + '/pets/' + pet.id, pet, status => status);""",
                     'Update Pet')

BACKEND = {
    'pom.xml': '<project><groupId>com.example</groupId><artifactId>clinic</artifactId></project>\n',
    'src/main/resources/application.properties':
        'server.port=9966\nserver.servlet.context-path=/petclinic/\n',
    'src/main/resources/openapi.yml': CONTRACT,
    'src/main/java/com/example/ClinicService.java': SERVICE,
    'src/main/java/com/example/ClinicServiceImpl.java': SERVICE_IMPL,
    'src/main/java/com/example/OwnerController.java': CONTROLLER,
}

CLIENT = {
    'client/package.json': '{"name": "client"}\n',
    'client/webpack.config.js': WEBPACK_DEV,
    'client/webpack.config.prod.js': WEBPACK_PROD,
    'client/src/util/index.tsx': UTIL,
    'client/src/routes.tsx': ROUTES,
    'client/src/VetsPage.tsx': VETS_PAGE,
    'client/src/OwnerEditor.tsx': OWNER_EDITOR,
    'client/src/VisitEditor.tsx': VISIT_EDITOR,
    'client/src/PetEditor.tsx': PET_EDITOR,
}


def _extract(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, _ = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    return facts


def _project(root, calls=None, extra=None):
    """The fixture, with optional client request functions in Calls.tsx."""
    files = {**BACKEND, **CLIENT, **(extra or {})}
    if calls:
        files['client/src/Calls.tsx'] = (
            "import { url, submitForm } from './util';\n\n" + calls)
    return _extract(root, files)


def _name(facts, symbol_id):
    return facts['symbols'][symbol_id]['qualified_name'].split('::', 1)[1]


def _routes(facts, origin):
    return [edge for edge in facts['edges'].values() if edge['kind'] == 'routes_to'
            and _name(facts, edge['from_ref']['id']).split('(')[0] == origin]


def _resolved(facts, origin):
    return sorted(_name(facts, edge['to_ref']['id']) for edge in _routes(facts, origin)
                  if edge['resolution'] == 'resolved')


def _diagnostics(facts, edge, code):
    return [warning for warning in facts['warnings']
            if warning['code'] == code and edge['id'] in warning['subject_ids']]


def _trace(facts, identity):
    return next(trace for trace in facts['traces'].values()
                if any(item['identity_key'] == identity for item in
                       facts['anchors'][trace['anchor_id']]['representations']))


def _action_trace(facts, handler):
    """The trace of the UI action whose registered callback is handler."""
    return next(trace for trace in facts['traces'].values()
                if any((item['registration'] or {}).get('kind') == 'action'
                       and (item['registration'] or {}).get('target') == handler
                       for item in facts['anchors'][trace['anchor_id']]['representations']))


def _trace_names(facts, trace):
    return {_name(facts, symbol_id).split('(')[0] for symbol_id in trace['symbol_ids']}


def test_relative_and_leading_slash_paths_reach_the_same_endpoint(tmp_path):
    facts = _project(tmp_path, calls="""export function relative() { return fetch(url('api/vets')); }
export function rooted() { return fetch(url('/api/vets')); }
""")
    assert _resolved(facts, 'relative') == ['OwnerController.listVets()']
    assert _resolved(facts, 'rooted') == ['OwnerController.listVets()']


def test_double_slash_is_collapsed_for_matching_and_diagnosed(tmp_path):
    facts = _project(tmp_path, calls="""export function relative() { return fetch(url('api/vets')); }
export function rooted() { return fetch(url('/api/vets')); }
""")
    rooted = next(edge for edge in _routes(facts, 'rooted') if edge['resolution'] == 'resolved')
    relative = next(edge for edge in _routes(facts, 'relative') if edge['resolution'] == 'resolved')
    diagnostic, = _diagnostics(facts, rooted, 'HTTP_TARGET_PATH_NOT_NORMALIZED')
    assert '//api/vets' in diagnostic['message'] and diagnostic['evidence_ids']
    assert not _diagnostics(facts, relative, 'HTTP_TARGET_PATH_NOT_NORMALIZED')


def test_query_string_is_dropped_for_matching(tmp_path):
    facts = _project(tmp_path, calls="""export function search(query) {
  return fetch(url('api/owners?lastName=' + query));
}
""")
    assert _resolved(facts, 'search') == ['OwnerController.listOwners()']


def test_template_and_concatenated_values_match_path_variables(tmp_path):
    facts = _project(tmp_path, calls="""export function templated(params) {
  return fetch(url(`/api/owners/${params.ownerId}`));
}
export function concatenated(owner) {
  const target = '/api/owners/' + owner.id;
  return fetch(url(target));
}
""")
    assert _resolved(facts, 'templated') == ['OwnerController.getOwner(int)']
    assert _resolved(facts, 'concatenated') == ['OwnerController.getOwner(int)']


def test_trailing_slash_mismatch_is_diagnosed(tmp_path):
    facts = _project(tmp_path, calls="""export function trailing() { return fetch(url('api/vets/')); }
""")
    edge = next(edge for edge in _routes(facts, 'trailing') if edge['resolution'] == 'resolved')
    assert _name(facts, edge['to_ref']['id']) == 'OwnerController.listVets()'
    assert _diagnostics(facts, edge, 'HTTP_TARGET_TRAILING_SLASH_MISMATCH')


def test_client_base_must_match_server_port_and_context_path(tmp_path):
    facts = _project(tmp_path, calls="""export function vets() { return fetch(url('api/vets')); }
export function elsewhere() { return fetch('http://localhost:9966/other/api/vets'); }
""")
    routes = _routes(facts, 'vets')
    resolved, = [edge for edge in routes if edge['resolution'] == 'resolved']
    # Each configuration's value is stated next to the file that declares it.
    assert "__API_SERVER_URL__ = 'http://localhost:9966/petclinic' (client/webpack.config.js)" \
        in resolved['condition']
    assert ("source default 'http://localhost:9966/petclinic' (client/src/util/index.tsx)"
            in resolved['condition'])
    assert 'webpack.config.prod.js' not in resolved['condition']
    assert 'http://localhost:8080' not in resolved['condition']
    production, = [edge for edge in routes if edge['resolution'] == 'unresolved']
    assert production['to_ref'] is None and not production['candidate_target_ids']
    assert production['condition'] == \
        "__API_SERVER_URL__ = 'http://localhost:8080' (client/webpack.config.prod.js)"
    assert '9966' not in production['condition']
    assert 'http://localhost:8080/api/vets' in production['reason']
    assert 'no declared server base' in production['reason']
    other, = _routes(facts, 'elsewhere')
    assert other['resolution'] == 'unresolved' and 'no declared server base' in other['reason']


def test_unresolved_configuration_names_its_resolved_sibling(tmp_path):
    facts = _project(tmp_path, calls="""export function vets() { return fetch(url('api/vets')); }
""")
    production, = [edge for edge in _routes(facts, 'vets') if edge['resolution'] == 'unresolved']
    assert ("This applies only when __API_SERVER_URL__ = 'http://localhost:8080' "
            "(client/webpack.config.prod.js)") in production['reason']
    assert ('under the other declared configuration(s) the same request routes to '
            'OwnerController.listVets()') in production['reason']
    # Correlated branches name the sibling of their own method and path only.
    owner = {edge['condition'].split(' && ')[0]: edge['reason']
             for edge in _routes(facts, 'OwnerEditor.onSubmit') if edge['resolution'] == 'unresolved'}
    assert owner['owner.isNew'].endswith('routes to OwnerController.addOwner().')
    assert owner['!(owner.isNew)'].endswith('routes to OwnerController.updateOwner(int).')


def test_request_without_a_resolved_sibling_gets_no_sibling_claim(tmp_path):
    facts = _project(tmp_path, calls="""export function singular(ownerId) {
  return fetch(url('/api/owner/' + ownerId));
}
export function elsewhere() { return fetch('http://localhost:9966/other/api/vets'); }
""")
    routes = _routes(facts, 'singular') + _routes(facts, 'elsewhere')
    assert routes and all(edge['resolution'] == 'unresolved' for edge in routes)
    assert not [edge for edge in routes if 'routes to' in edge['reason']
                or 'This applies only when' in edge['reason']]


def test_route_wording_leaves_identity_resolution_and_evidence_unchanged(tmp_path, monkeypatch):
    from lib.context import business_domain_extract as extract

    def routes(facts):
        return {edge['id']: (edge['resolution'], edge['to_ref'], edge['candidate_target_ids'],
                             edge['evidence_ids'])
                for edge in facts['edges'].values() if edge['kind'] == 'routes_to'}

    worded = _project(tmp_path / 'worded')
    original = extract.Extractor._add_route
    # The same extraction with no condition text and no sibling statement.
    monkeypatch.setattr(extract, '_route_condition', lambda alternatives: None)
    monkeypatch.setattr(extract.Extractor, '_add_route',
                        lambda self, unit, position, end, key, group, groups=None:
                        original(self, unit, position, end, key, group, None))
    bare = _project(tmp_path / 'bare')
    assert routes(worded) == routes(bare)
    assert any(edge['condition'] for edge in worded['edges'].values() if edge['kind'] == 'routes_to')
    assert not any(edge['condition'] for edge in bare['edges'].values() if edge['kind'] == 'routes_to')


def test_fetch_methods_are_read_from_the_call(tmp_path):
    facts = _project(tmp_path, calls="""export function implicit() { return fetch(url('api/vets')); }
export function headersOnly() { return fetch(url('api/vets'), { headers: {} }); }
export function explicit() { return fetch(url('api/owners'), { method: 'post', body: '{}' }); }
export function opaque(options) { return fetch(url('api/vets'), options); }
export function mismatched() { return fetch(url('api/vets'), { method: 'DELETE' }); }
""")
    assert _resolved(facts, 'implicit') == ['OwnerController.listVets()']
    assert _resolved(facts, 'headersOnly') == ['OwnerController.listVets()']
    assert _resolved(facts, 'explicit') == ['OwnerController.addOwner()']
    assert all(edge['resolution'] == 'unresolved' and 'no established HTTP method' in edge['reason']
               for edge in _routes(facts, 'opaque'))
    assert _routes(facts, 'opaque')
    assert not _resolved(facts, 'mismatched')
    assert any('No declared DELETE endpoint' in edge['reason'] for edge in _routes(facts, 'mismatched'))


def test_several_matching_endpoints_stay_ambiguous(tmp_path):
    duplicate = """package com.example;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.GetMapping;
@RestController
public class {name} {{
  @GetMapping("/api/shared") public String shared() {{ return "{name}"; }}
}}
"""
    facts = _project(tmp_path, calls="""export function shared() { return fetch(url('api/shared')); }
""", extra={f'src/main/java/com/example/{name}.java': duplicate.format(name=name)
            for name in ('FirstController', 'SecondController')})
    edge, = [edge for edge in _routes(facts, 'shared') if edge['resolution'] != 'unresolved']
    assert edge['resolution'] == 'ambiguous' and edge['to_ref'] is None
    assert sorted(_name(facts, item) for item in edge['candidate_target_ids']) == [
        'FirstController.shared()', 'SecondController.shared()']
    assert '2 declared endpoints' in edge['reason']


def test_a_different_literal_segment_never_matches(tmp_path):
    facts = _project(tmp_path, calls="""export function singular(ownerId) {
  return fetch(url('/api/owner/' + ownerId));
}
""")
    assert not _resolved(facts, 'singular')
    assert any('No declared GET endpoint matches /petclinic/api/owner/{ownerId}' in edge['reason']
               for edge in _routes(facts, 'singular'))


def test_runtime_segment_never_resolves_against_literal_endpoints(tmp_path):
    facts = _project(tmp_path, calls="""export function collection(kind) {
  return fetch(url('api/' + kind));
}
""")
    assert not _resolved(facts, 'collection')
    reason, = {edge['reason'] for edge in _routes(facts, 'collection')
               if 'only if a runtime value' in (edge['reason'] or '')}
    assert 'GET /api/owners' in reason and 'GET /api/vets' in reason


def test_correlated_ternaries_give_one_route_per_branch(tmp_path):
    facts = _project(tmp_path)
    routes = [edge for edge in _routes(facts, 'OwnerEditor.onSubmit')
              if edge['resolution'] == 'resolved']
    by_target = {_name(facts, edge['to_ref']['id']): edge['condition'] for edge in routes}
    assert set(by_target) == {'OwnerController.addOwner()', 'OwnerController.updateOwner(int)'}
    assert by_target['OwnerController.addOwner()'].startswith('owner.isNew && ')
    assert by_target['OwnerController.updateOwner(int)'].startswith('!(owner.isNew) && ')
    # Correlated branches never pair POST with the item path or PUT with the collection.
    assert not [edge for edge in _routes(facts, 'OwnerEditor.onSubmit')
                if edge['resolution'] == 'unresolved' and 'No declared' in (edge['reason'] or '')]


def test_uncorrelated_ternaries_keep_every_combination(tmp_path):
    facts = _project(tmp_path, calls="""export function crossed(owner, creating) {
  const path = owner.isNew ? '/api/owners' : '/api/owners/' + owner.id;
  return submitForm(creating ? 'POST' : 'PUT', path, owner, status => status);
}
""")
    assert _resolved(facts, 'crossed') == ['OwnerController.addOwner()',
                                           'OwnerController.updateOwner(int)']
    unmatched = sorted(edge['reason'].split(' matches ')[0] for edge in _routes(facts, 'crossed')
                       if edge['resolution'] == 'unresolved' and 'No declared' in edge['reason'])
    assert unmatched == ['No declared POST endpoint', 'No declared PUT endpoint']


def test_shared_helper_keeps_its_own_edge_and_callers_stay_isolated(tmp_path):
    facts = _project(tmp_path)
    helper = next(symbol_id for symbol_id in facts['symbols']
                  if _name(facts, symbol_id) == 'submitForm')
    assert not [edge for edge in facts['edges'].values()
                if edge['kind'] == 'routes_to' and edge['from_ref']['id'] == helper]
    operation, = [edge for edge in facts['edges'].values()
                  if edge['kind'] == 'invokes_endpoint' and edge['from_ref']['id'] == helper]
    assert operation['resolution'] == 'unresolved' and operation['to_ref']['kind'] == 'resource'
    assert _resolved(facts, 'VisitEditor.onSubmit') == ['OwnerController.addVisit(int)']

    owner = _trace_names(facts, _action_trace(facts, 'OwnerEditor.onSubmit'))
    visit = _trace_names(facts, _action_trace(facts, 'VisitEditor.onSubmit'))
    assert {'OwnerController.addOwner', 'OwnerController.updateOwner'} <= owner
    assert 'OwnerController.addVisit' not in owner
    assert 'OwnerController.addVisit' in visit
    assert not {'OwnerController.addOwner', 'OwnerController.updateOwner'} & visit


def test_contract_only_operation_is_reached_but_no_implementation_is(tmp_path):
    facts = _project(tmp_path)
    edge, = [edge for edge in _routes(facts, 'PetEditor.onSubmit') if edge['resolution'] == 'resolved']
    assert _name(facts, edge['to_ref']['id']) == 'PUT /owners/{ownerId}/pets/{petId}'
    trace = _action_trace(facts, 'PetEditor.onSubmit')
    assert edge['id'] in trace['edge_ids']
    assert not any('ServiceImpl' in name for name in _trace_names(facts, trace))
    obligations = [facts['trace_obligations'][key] for key in trace['obligation_ids']]
    assert any(item['kind'] == 'implementation_selection'
               and item['origin_ref']['id'] == edge['to_ref']['id']
               and item['reason_code'] == 'IMPLEMENTATION_NOT_REACHED' for item in obligations)


def test_route_trace_reaches_service_implementation_through_the_endpoint(tmp_path):
    facts = _project(tmp_path)
    trace = _trace(facts, 'ui:client:route:/vets')
    names = _trace_names(facts, trace)
    assert {'VetsPage.componentDidMount', 'OwnerController.listVets',
            'ClinicService.findVets', 'ClinicServiceImpl.findVets'} <= names
    edges = [facts['edges'][edge_id] for edge_id in trace['edge_ids']]
    route, = [edge for edge in edges if edge['kind'] == 'routes_to' and edge['resolution'] == 'resolved']
    assert _name(facts, route['from_ref']['id']) == 'VetsPage.componentDidMount'
    assert _name(facts, route['to_ref']['id']) == 'OwnerController.listVets()'
    # The link carries the request, the client base and the server base as evidence.
    excerpts = ' '.join(facts['evidence'][evidence_id]['excerpt'] for evidence_id in route['evidence_ids'])
    assert "url('api/vets')" in excerpts and 'server.port=9966' in excerpts
    assert 'server.servlet.context-path=/petclinic/' in excerpts
    obligations = [facts['trace_obligations'][key] for key in trace['obligation_ids']]
    assert any(item['kind'] == 'implementation_selection' and item['status'] == 'satisfied'
               and _name(facts, item['origin_ref']['id']) == 'ClinicService.findVets()'
               for item in obligations)


def test_backend_traces_are_unchanged_by_client_links(tmp_path):
    backend = _extract(tmp_path / 'backend', BACKEND)
    combined = _project(tmp_path / 'combined')

    def backend_traces(facts):
        return {facts['anchors'][trace['anchor_id']]['representations'][0]['identity_key']: (
            trace['symbol_ids'], trace['edge_ids'], trace['stop_reasons'], trace['resolution'],
            sorted((item['kind'], item['status'], item['reason_code'], item['origin_ref']['id'])
                   for item in (facts['trace_obligations'][key] for key in trace['obligation_ids'])))
            for trace in facts['traces'].values()
            if facts['anchors'][trace['anchor_id']]['kind'] == 'http'}

    assert backend_traces(backend) == backend_traces(combined)
    assert not [edge for edge in backend['edges'].values() if edge['kind'] == 'routes_to']
