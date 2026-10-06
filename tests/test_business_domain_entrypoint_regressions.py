"""Regression coverage for entry-point detection and UI-to-endpoint linking."""
import pytest

from lib.context.business_domain_adapters.base import http_route_key
from lib.context.business_domain_adapters.rules import (
    _declared_route_method, _handler_name, _literal_request_method)
from lib.context.business_domain_adapters.spring_semantic import _DYNAMIC_ROUTE, _paths
from lib.context.business_domain_adapters.sql import _parameter_list, _parameters
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import DEFAULTS, validate_references


def _extract(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, units = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    return facts, units


def _http_anchors(facts):
    return {(anchor['operation']['method'], anchor['operation']['path']): anchor
            for anchor in facts['anchors'].values() if anchor['kind'] == 'http'}


def _ui_calls(facts):
    return [call for trace in facts['traces'].values()
            if trace.get('ui_interaction')
            for call in trace['ui_interaction']['calls'].values()]


OWNER_CONTROLLER = '''package demo;
import org.springframework.web.bind.annotation.*;
@RestController
public class OwnerController {
    @GetMapping("/api/owners/{ownerId}")
    public String owner() { return "x"; }
    @PostMapping("/api/owners")
    public String create() { return "x"; }
}
'''


# ── Spring ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('text, expected', [
    ('@GetMapping("/owners")', ['/owners']),
    ('@GetMapping(value = "/owners", produces = "application/json")', ['/owners']),
    ('@GetMapping(path = {"/a", "/b"}, consumes = "application/json")', ['/a', '/b']),
    ('@GetMapping(produces = "application/json")', ['']),
    ('@GetMapping', ['']),
    ('@GetMapping(OWNERS)', [_DYNAMIC_ROUTE]),
    ('@GetMapping("/owners/" + ID)', [_DYNAMIC_ROUTE]),
])
def test_spring_paths_read_only_route_attributes(text, expected):
    assert _paths(text) == expected


def test_spring_mapping_attributes_and_constants_do_not_invent_routes(tmp_path):
    facts, _ = _extract(tmp_path, {'OwnerController.java': '''package demo;
import org.springframework.web.bind.annotation.*;
import static org.springframework.web.bind.annotation.RequestMethod.GET;
@RestController
@RequestMapping("/api")
public class OwnerController {
    static final String PETS = "/pets";
    @GetMapping(value = "/owners", produces = "application/json")
    public String owners() { return "x"; }
    @GetMapping(PETS)
    public String pets() { return "x"; }
    @RequestMapping(value = "/vets", method = GET)
    public String vets() { return "x"; }
}
'''})
    anchors = _http_anchors(facts)
    assert anchors[('GET', '/api/owners')]['resolution'] == 'resolved'
    assert anchors[('GET', '/api/vets')]['resolution'] == 'resolved'
    assert ('GET', '/api') not in anchors
    constant = anchors[('GET', None)]
    assert constant['resolution'] == 'unresolved'
    assert all(item['identity_key'] is None for item in constant['representations'])


def test_feign_client_does_not_shadow_the_exposed_endpoint(tmp_path):
    facts, _ = _extract(tmp_path, {
        'OwnerController.java': OWNER_CONTROLLER,
        'OwnerClient.java': '''package demo;
import org.springframework.web.bind.annotation.*;
@FeignClient(name = "owners")
public interface OwnerClient {
    @PostMapping("/api/owners")
    String create();
}
''',
    })
    endpoints = [anchor for anchor in facts['anchors'].values()
                 if anchor['operation']['path'] == '/api/owners']
    assert len(endpoints) == 1
    assert endpoints[0]['eligibility'] == 'eligible'
    assert endpoints[0]['resolution'] == 'resolved'


# ── Python ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('decorator, expected', [
    ("@app.route('/orders')", 'GET'),
    ("@app.route('/orders', methods=['POST'])", 'POST'),
    ("@app.route('/orders', methods=('put',))", 'PUT'),
    ("@app.route('/orders', methods=['GET', 'POST'])", None),
    ("@app.route('/orders', methods=ORDER_METHODS)", None),
    ("@app.route('/orders', defaults=dict(methods=['POST']))", 'GET'),
    ("@app.route('/orders', endpoint='a,methods=[\\'POST\\']')", 'GET'),
])
def test_generic_route_method_selection(decorator, expected):
    assert _declared_route_method(decorator) == expected


def test_flask_route_uses_its_declared_http_method(tmp_path):
    facts, _ = _extract(tmp_path, {'app.py': '''from flask import Flask
app = Flask(__name__)

@app.route('/orders', methods=['POST'])
def create_order():
    return 'ok'

@app.route('/orders/<order_id>')
def show_order(order_id):
    return 'ok'
'''})
    anchors = _http_anchors(facts)
    assert set(anchors) == {('POST', '/orders'), ('GET', '/orders/<order_id>')}
    assert all(anchor['eligibility'] == 'eligible' for anchor in anchors.values())


@pytest.mark.parametrize('elsewhere', [
    '@limiter.limit("5/minute", methods=["POST"])\n@app.route(\'/orders\')\ndef list_orders():\n    return \'ok\'\n',
    '@app.route(\'/orders\')\ndef list_orders():\n    session.request(methods=[\'DELETE\'])\n    return \'ok\'\n',
    '@app.route(\'/orders\')\ndef list_orders():\n    options = dict(methods=ALLOWED)\n    return \'ok\'\n',
])
def test_flask_method_comes_from_the_route_decorator_only(tmp_path, elsewhere):
    facts, _ = _extract(tmp_path, {'app.py': 'from flask import Flask\napp = Flask(__name__)\n\n' + elsewhere})
    assert set(_http_anchors(facts)) == {('GET', '/orders')}


def _fastapi(tmp_path, text):
    facts, _ = _extract(tmp_path, {'api.py': 'from fastapi import FastAPI, APIRouter\n' + text})
    return _http_anchors(facts)


def test_fastapi_router_and_include_prefixes_compose_onto_the_route(tmp_path):
    anchors = _fastapi(tmp_path, '''app = FastAPI()
orders = APIRouter(prefix="/orders")
v1 = APIRouter(prefix="/v1")

@orders.get("/{order_id}")
def show(order_id: int):
    return {}

@orders.post("")
def create():
    return {}

v1.include_router(orders)
app.include_router(v1, prefix="/api")
''')
    assert set(anchors) == {('GET', '/api/v1/orders/{order_id}'), ('POST', '/api/v1/orders')}
    assert all(anchor['resolution'] == 'resolved' for anchor in anchors.values())


def test_fastapi_app_routes_keep_their_declared_path(tmp_path):
    anchors = _fastapi(tmp_path, '''app = FastAPI(title="Orders")

@app.get("/items")
def items():
    return {}
''')
    assert set(anchors) == {('GET', '/items')}
    assert anchors[('GET', '/items')]['resolution'] == 'resolved'


@pytest.mark.parametrize('wiring, reason', [
    ('', 'not included in this source'),
    ('app.include_router(router, prefix=API)\n', 'not a literal string'),
    ('app.include_router(router, prefix="/a")\napp.include_router(router, prefix="/b")\n',
     'several prefixes'),
])
def test_fastapi_router_route_without_a_known_mount_is_unresolved(tmp_path, wiring, reason):
    anchors = _fastapi(tmp_path, '''app = FastAPI()
router = APIRouter(prefix="/orders")

@router.get("/{order_id}")
def show(order_id: int):
    return {}

''' + wiring)
    [anchor] = anchors.values()
    assert anchor['resolution'] == 'unresolved'
    assert anchor['eligibility'] != 'eligible'
    assert reason in anchor['reason']


def test_fastapi_router_with_a_non_literal_prefix_is_unresolved(tmp_path):
    anchors = _fastapi(tmp_path, '''app = FastAPI()
router = APIRouter(prefix=settings.ORDERS)

@router.get("/{order_id}")
def show(order_id: int):
    return {}

app.include_router(router)
''')
    [anchor] = anchors.values()
    assert anchor['resolution'] == 'unresolved'
    assert 'not a literal string' in anchor['reason']


# ── Frontend calls ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('request_text, expected', [
    ("{method: 'POST'}", 'POST'),
    ('{ "method": "delete", body }', 'DELETE'),
    ("{headers: {}}", 'GET'),
    ("{...defaults, method: 'POST'}", None),
    ('{method: verb}', None),
    ('options', None),
])
def test_literal_fetch_options_method(request_text, expected):
    assert _literal_request_method(request_text) == expected


@pytest.mark.parametrize('expression, expected', [
    ('() => save()', 'save'),
    ('(event) => this.submit(event)', 'this.submit'),
    ('e => save(e)', 'save'),
    ('save', 'save'),
    ('() => { save(); other(); }', '() => { save(); other(); }'),
])
def test_single_call_arrow_handlers_unwrap(expression, expected):
    assert _handler_name(expression) == expected


@pytest.mark.parametrize('left, right', [
    ('http:client:GET:/api/owners/{id}', 'http:server:GET:/api/owners/{ownerId}'),
    ('http:client:GET:/api/owners/', 'http:server:GET:/api/owners'),
    ('http:client:GET:/api/owners?lastName=x', 'http:server:GET:/api/owners'),
    ('http:client:GET:http://localhost:8080/api/owners', 'http:server:GET:/api/owners'),
    ('http:client:GET:/api/owners/:id', 'http:server:GET:/api/owners/{id}'),
])
def test_http_route_key_ignores_scope_and_spelling(left, right):
    assert http_route_key(left) == http_route_key(right)


def test_http_route_key_keeps_method_and_distinct_routes():
    assert http_route_key('http:a:GET:/api/owners') != http_route_key('http:a:POST:/api/owners')
    assert http_route_key('http:a:GET:/api/owners') != http_route_key('http:a:GET:/api/vets')
    assert http_route_key('ui:a:route:/owners') is None


def test_ui_call_links_to_an_endpoint_in_another_service_scope(tmp_path):
    facts, _ = _extract(tmp_path, {
        'server/pom.xml': '<project/>\n',
        'server/src/OwnerController.java': OWNER_CONTROLLER,
        'client/package.json': '{}\n',
        'client/src/Owners.tsx': '''
function loadOwner(ownerId) { return fetch(`/api/owners/${ownerId}`); }
export default () => <button onClick={loadOwner}>Load owner</button>;
''',
    })
    endpoint = _http_anchors(facts)[('GET', '/api/owners/{ownerId}')]
    assert endpoint['representations'][0]['identity_key'].startswith('http:server:')
    calls = _ui_calls(facts)
    assert len(calls) == 1
    assert calls[0]['target_anchor_id'] == endpoint['id']
    assert calls[0]['resolution'] == 'resolved'


def test_cross_scope_match_stays_ambiguous_when_several_services_match(tmp_path):
    facts, _ = _extract(tmp_path, {
        'billing/pom.xml': '<project/>\n',
        'billing/src/OwnerController.java': OWNER_CONTROLLER,
        'crm/pom.xml': '<project/>\n',
        'crm/src/OwnerController.java': OWNER_CONTROLLER.replace('package demo;', 'package crm;'),
        'client/package.json': '{}\n',
        'client/src/Owners.tsx': '''
function create() { return fetch('/api/owners', {method: 'POST'}); }
export default () => <button onClick={create}>Create owner</button>;
''',
    })
    calls = _ui_calls(facts)
    assert len(calls) == 1
    assert calls[0]['target_anchor_id'] is None
    assert calls[0]['resolution'] == 'ambiguous'


def test_literal_post_fetch_and_arrow_handler_link_to_the_endpoint(tmp_path):
    facts, _ = _extract(tmp_path, {
        'OwnerController.java': OWNER_CONTROLLER,
        'Owners.tsx': '''
function create() { return fetch('/api/owners', { method: 'POST' }); }
export default () => <button onClick={() => create()}>Create owner</button>;
''',
    })
    endpoint = _http_anchors(facts)[('POST', '/api/owners')]
    effect = next(iter(facts['effects'].values()))
    assert effect['target_identity_key'] == 'http:repository:POST:/api/owners'
    calls = _ui_calls(facts)
    assert [call['target_anchor_id'] for call in calls] == [endpoint['id']]
    assert calls[0]['resolution'] == 'resolved'


# ── SQL ────────────────────────────────────────────────────────────────────

def test_editionable_oracle_package_is_detected_and_canonicalized(tmp_path):
    facts, _ = _extract(tmp_path, {'pay.sql': '''CREATE OR REPLACE EDITIONABLE PACKAGE pay AS
  PROCEDURE settle(d IN DATE);
END pay;
/
CREATE OR REPLACE EDITIONABLE PACKAGE BODY pay AS
  PROCEDURE helper(d IN DATE) IS BEGIN NULL; END helper;
  PROCEDURE settle(d IN DATE) IS BEGIN helper(d); END settle;
END pay;
/
'''})
    eligible = [anchor for anchor in facts['anchors'].values()
                if anchor['eligibility'] == 'eligible']
    assert [anchor['representations'][0]['identity_key'] for anchor in eligible] == [
        'sql:repository:oracle:procedure:pay.settle(in date)']


@pytest.mark.parametrize('segment, expected', [
    ('integer', [('$1', 'integer')]),
    ('a integer', [('a', 'integer')]),
    ('IN a text', [('a', 'IN text')]),
    ('double precision', [('$1', 'double precision')]),
    ('timestamp with time zone', [('$1', 'timestamp with time zone')]),
    ('int DEFAULT 1', [('$1', 'int')]),
])
def test_postgres_parameters_allow_unnamed_arguments(segment, expected):
    assert _parameters(segment, 'postgres') == expected


def test_parameter_list_stops_at_its_own_closing_parenthesis():
    assert _parameter_list('(p int) RETURNS numeric(10,2) ') == 'p int'
    assert _parameter_list('(p numeric(10,2), q int) RETURNS int ') == 'p numeric(10,2), q int'
    assert _parameter_list(' RETURNS int ') == ''


def test_postgres_overloads_have_distinct_identities(tmp_path):
    facts, _ = _extract(tmp_path, {'f.sql': '''CREATE FUNCTION f(integer) RETURNS numeric(10,2) AS $$
BEGIN RETURN 1; END;
$$ LANGUAGE plpgsql;
CREATE FUNCTION f(text) RETURNS integer AS $$
BEGIN RETURN 2; END;
$$ LANGUAGE plpgsql;
'''})
    keys = sorted(anchor['representations'][0]['identity_key']
                  for anchor in facts['anchors'].values())
    assert keys == ['sql:repository:postgres:function:f(integer)',
                    'sql:repository:postgres:function:f(text)']
    assert all(anchor['eligibility'] == 'eligible' for anchor in facts['anchors'].values())


def test_postgres_trigger_return_type_is_not_a_trigger_declaration(tmp_path):
    facts, _ = _extract(tmp_path, {'audit.sql': '''CREATE FUNCTION audit_order() RETURNS trigger AS $$
BEGIN
  INSERT INTO audit(id) VALUES (NEW.id);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
'''})
    anchors = list(facts['anchors'].values())
    assert [anchor['operation']['name'] for anchor in anchors] == ['audit_order']
    assert anchors[0]['representations'][0]['identity_key'] == (
        'sql:repository:postgres:function:audit_order()')
