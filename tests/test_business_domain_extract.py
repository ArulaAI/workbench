"""Regression tests for evidence boundaries, not label/count snapshots."""
from pathlib import Path

import pytest

from lib.context.business_domain_extract import Extractor, Source
from lib.context.business_domain_adapters.sql import extract as sql_units
from lib.context.business_domain_schema import DEFAULTS, digest, identifier, validate_references


def extract(tmp_path, files, **limits):
    for name, text in files.items():
        path = tmp_path/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, units = Extractor(tmp_path, {**DEFAULTS, **limits}).extract()
    validate_references(facts)
    return facts, units


def test_unrelated_receiver_does_not_resolve_by_unique_name(tmp_path):
    facts, _ = extract(tmp_path, {
        'Checkout.java': '@RestController class Checkout { Missing gateway; public void pay() { gateway.save(); } }',
        'Employee.java': 'class Employee { public void save() {} }',
    })
    calls = [e for e in facts['edges'].values() if 'save' in (e['reason'] or '')]
    assert calls and all(e['resolution'] == 'unresolved' and e['to_ref'] is None for e in calls)


@pytest.mark.parametrize('kind', ['Anchor', 'Edge'])
def test_normalized_boundary_producer_must_decide_resolution(kind):
    from lib.context.business_domain_schema import DomainError, record
    with pytest.raises(DomainError, match='explicit resolution'):
        record(kind)
    with pytest.raises(DomainError, match='explicit resolution'):
        record(kind, resolution=None)


@pytest.mark.parametrize('missing', ['method', 'path', 'operation'])
def test_resolved_http_anchor_requires_complete_identity(missing):
    from lib.context.business_domain_schema import DomainError, record, validate
    anchor = record('Anchor', id='anchor:fixture', source_id='resource:fixture',
        kind='http', resolution='resolved',
        operation=record('Operation', protocol='http', name='create', method='POST', path='/orders'))
    validate(anchor, 'Anchor')
    if missing == 'operation':
        anchor['operation'] = None
    else:
        anchor['operation'][missing] = None
    with pytest.raises(DomainError):
        validate(anchor, 'Anchor')


@pytest.mark.parametrize(('resolution', 'reason'), [
    ('unresolved', None), ('ambiguous', ''), ('resolved', 'not actually resolved'),
])
def test_anchor_resolution_and_reason_must_agree(resolution, reason):
    from lib.context.business_domain_schema import DomainError, record, validate
    anchor = record('Anchor', id='anchor:fixture', source_id='resource:fixture',
        kind='sql', resolution=resolution, reason=reason)
    with pytest.raises(DomainError):
        validate(anchor, 'Anchor')


def test_incomplete_controller_identity_is_explicitly_unresolved(tmp_path):
    facts, _ = extract(tmp_path, {'Controller.java':
        '@RestController class Controller { public void create() {} }'})
    anchor = next(iter(facts['anchors'].values()))
    assert anchor['operation']['method'] is None and anchor['operation']['path'] is None
    assert anchor['resolution'] == 'unresolved' and anchor['reason']


def test_sql_standalone_body_has_exact_evidenced_anchor_identity(tmp_path):
    facts, _ = extract(tmp_path, {'routine.sql':
        'CREATE PROCEDURE calculate IS BEGIN NULL; END;\n/\n'})
    anchor = next(iter(facts['anchors'].values()))
    assert anchor['resolution'] == 'resolved'
    assert anchor['reason'] is None


def test_dialect_selection_uses_installed_descriptors_and_source_evidence(tmp_path):
    from lib.context.business_domain_adapters import descriptor
    oracle = 'CREATE OR REPLACE PACKAGE BODY billing AS PROCEDURE pay IS BEGIN NULL; END; END;'
    postgres = 'CREATE FUNCTION pay() RETURNS void AS $$ BEGIN NULL; END; $$ LANGUAGE plpgsql;'
    assert descriptor('billing.sql', oracle)['capability']['id'] == 'oracle_plsql'
    selected = descriptor('billing.sql', postgres)
    assert selected['capability']['id'] == 'postgresql' and selected['adapter'] == 'sql_postgresql'
    assert descriptor('billing.sql', 'SELECT 1;')['adapter'] == 'sql_unknown'
    facts, _ = extract(tmp_path, {'billing.sql': postgres})
    assert facts['anchors']
    assert all(c['adapter'] == 'postgresql' for c in facts['capabilities'])
    assert any(c['status'] == 'partial' for c in facts['capabilities'])


def test_ambiguous_installed_adapters_do_not_select_by_order(tmp_path, monkeypatch):
    from lib.context.language_registry import registry
    descriptors = dict(registry._source_adapters)
    descriptors['another_oracle'] = dict(descriptors['oracle_plsql'])
    monkeypatch.setattr(registry, '_source_adapters', descriptors)
    facts, _ = extract(tmp_path, {'billing.sql':
        'CREATE OR REPLACE PACKAGE BODY billing AS PROCEDURE pay IS BEGIN NULL; END; END;'})
    assert not facts['anchors']
    assert any(w['code'] == 'AMBIGUOUS_ADAPTER' for w in facts['warnings'])


def test_repository_descriptor_cannot_register_or_shadow_executable_adapter(tmp_path):
    from lib.context.business_domain_adapters import adapter_for, rules
    text = "@app.get('/orders')\ndef orders():\n    return 1\n"
    (tmp_path/'extraction.toml').write_text(
        '[source_adapters.rules]\nmodule="malicious"\nversion="1"\ncontract_version=1\n')
    (tmp_path/'rules.py').write_text("raise RuntimeError('target adapter must never execute')\n")
    (tmp_path/'malicious.py').write_text("raise RuntimeError('target descriptor must never execute')\n")
    facts, units = extract(tmp_path, {'service.py': text})
    service = next(u.source for u in units if u.source.path == 'service.py')
    assert adapter_for(service) is rules
    assert any(c['adapter'] == 'rules' and c['feature'] == 'callable_resolution'
               for c in facts['capabilities'])


def test_invalid_installed_adapter_descriptor_preserves_language_registry_and_is_visible(tmp_path, monkeypatch):
    from lib.context.language_registry import LanguageRegistry, registry
    data = tmp_path/'registry'
    data.mkdir()
    (data/'languages.toml').write_text('[[language]]\nname="python"\nfile-types=["py"]\n')
    (data/'extraction.toml').write_text('''[python]
extraction="rules"
[source_adapters.Invalid]
module="rules"
version="1"
contract_version=1
[source_adapters.Invalid.capabilities]
entrypoints="partial"
''')
    isolated = LanguageRegistry(data)
    assert isolated.classify('.py') == ('source', 'python')
    assert isolated._source_adapters == {} and isolated.source_adapter_error == 'ValueError'

    monkeypatch.setattr(registry, '_source_adapters', {})
    monkeypatch.setattr(registry, 'source_adapter_error', 'ValueError')
    facts, _ = extract(tmp_path, {'service.py':'def run():\n    return 1\n'})
    assert any(w['code'] == 'ADAPTER_REGISTRY_INVALID' for w in facts['warnings'])
    capability = next(c for c in facts['capabilities'] if c['adapter'] == 'unavailable')
    assert capability['diagnostic_codes'] == ['ADAPTER_REGISTRY_INVALID']


def test_contract_only_trace_retains_missing_implementation_obligation(tmp_path):
    from lib.context.business_domain_schema import DomainError, copy_facts
    from lib.context.business_domain_work import whole_graph_scope
    facts, _ = extract(tmp_path, {'api.yaml':
        'openapi: 3.0.1\npaths:\n  /visits:\n    post:\n      operationId: addVisit\n'})
    trace = next(iter(facts['traces'].values()))
    assert trace['edge_ids'] == [] and trace['resolution'] == 'unresolved'
    obligations = [facts['trace_obligations'][oid] for oid in trace['obligation_ids']]
    assert any(o['reason_code'] == 'IMPLEMENTATION_NOT_REACHED' for o in obligations)
    graph = whole_graph_scope(copy_facts(facts, 'fixture'))
    assert graph['context']['trace_obligations'] == facts['trace_obligations']
    trace['frontier_ids'] = []
    trace['resolution'] = 'resolved'
    with pytest.raises(DomainError, match='satisfied implementation'):
        validate_references(facts)


def test_executable_leaf_requires_positive_adapter_evidence(tmp_path, monkeypatch):
    from lib.context.business_domain_adapters import rules
    files = {'service.py': "@app.get('/leaf')\ndef leaf():\n    return 1\n"}
    facts, _ = extract(tmp_path, files)
    trace = next(iter(facts['traces'].values()))
    assert trace['resolution'] == 'resolved' and trace['edge_ids'] == []
    assert all(facts['trace_obligations'][oid]['status'] == 'satisfied' for oid in trace['obligation_ids'])
    original = rules._parse_ast_grep_matches

    def without_body_evidence(*args):
        definitions, references, schemas = original(*args)
        for definition in definitions:
            definition.executable_body = False
        return definitions, references, schemas

    monkeypatch.setattr(rules, '_parse_ast_grep_matches', without_body_evidence)
    facts, _ = extract(tmp_path, files)
    trace = next(iter(facts['traces'].values()))
    assert trace['resolution'] == 'unresolved' and trace['edge_ids'] == []
    assert 'implementation_not_reached' in trace['stop_reasons']


def test_java_body_evidence_preserves_abstract_declarations(tmp_path):
    _, units = extract(tmp_path, {'Service.java':
        'abstract class Service { abstract void declared(); void implemented() {} Service() {} }'})
    assert next(u for u in units if u.name == 'declared').executable_body is False
    assert next(u for u in units if u.name == 'implemented').executable_body is True
    assert next(u for u in units if u.name == 'Service' and u.kind == 'method').executable_body is True


@pytest.mark.parametrize('filename', ['service.ts', 'service.tsx', 'service.js'])
def test_function_body_evidence_uses_the_shared_rule_contract(tmp_path, filename):
    _, units = extract(tmp_path, {filename:'function implemented() { return 1; }'})
    assert next(u for u in units if u.name == 'implemented').executable_body is True


@pytest.mark.parametrize('removed', ['obligation_ids', 'trace_obligations'])
def test_current_artifacts_cannot_omit_trace_obligations(tmp_path, removed):
    from lib.context.business_domain_schema import DomainError, validate
    facts, _ = extract(tmp_path, {'service.py': "@app.get('/leaf')\ndef leaf():\n    return 1\n"})
    assert facts['schema_version'] == 2
    if removed == 'obligation_ids':
        next(iter(facts['traces'].values())).pop(removed)
    else:
        facts.pop(removed)
    with pytest.raises(DomainError):
        validate(facts, 'FactsArtifact')


@pytest.mark.parametrize('filename,text,kind,target', [
    ('Controller.java', 'class Controller implements MissingApi {}', 'implements', 'MissingApi'),
    ('Child.java', 'class Child extends MissingBase {}', 'inherits', 'MissingBase'),
    ('child.py', 'class Child(MissingBase):\n    pass\n', 'inherits', 'MissingBase'),
    ('types.ts', 'interface INamedEntity extends IBaseEntity {}', 'inherits', 'IBaseEntity'),
])
def test_structural_declarations_reach_csg_and_business_facts(tmp_path, filename, text, kind, target):
    from lib.context.csg import build_layer_a
    from lib.context.treesitter_extract import ExtractionResult
    facts, units = extract(tmp_path, {filename: text})
    source = units[0].source
    _, csg_edges = build_layer_a({filename: ExtractionResult(
        filename, source.language, definitions=source.definitions)})
    assert any(e['type'] == kind and e['to'] == 'unresolved::'+target for e in csg_edges)
    edges = [e for e in facts['edges'].values() if e['kind'] == kind]
    assert len(edges) == 1
    edge = edges[0]
    assert edge['resolution'] == 'unresolved' and edge['to_ref'] is None
    assert target in edge['reason']
    assert facts['evidence'][edge['evidence_ids'][0]]['excerpt'] == text.rstrip()


def test_petclinic_controller_interface_relationships_are_not_dropped(tmp_path):
    controllers = {
        'OwnerRestController': 'OwnersApi',
        'PetRestController': 'PetsApi',
        'PetTypeRestController': 'PetTypesApi',
        'SpecialtyRestController': 'SpecialtiesApi',
        'UserRestController': 'UsersApi',
        'VetRestController': 'VetsApi',
        'VisitRestController': 'VisitsApi',
    }
    facts, _ = extract(tmp_path, {
        f'{controller}.java': f'public class {controller} implements {interface} {{}}'
        for controller, interface in controllers.items()
    })

    relationships = [edge for edge in facts['edges'].values()
                     if edge['kind'] == 'implements']
    assert len(relationships) == 7
    assert all(edge['resolution'] == 'unresolved' and edge['to_ref'] is None
               and len(edge['evidence_ids']) == 1 for edge in relationships)
    assert {facts['symbols'][edge['from_ref']['id']]['qualified_name'].split('::')[1].split(':')[0]
            for edge in relationships} == set(controllers)


def test_rules_adapter_consumes_shared_normalized_definitions_and_calls(tmp_path, monkeypatch):
    from lib.context.business_domain_adapters import rules
    original = rules._parse_ast_grep_matches

    def normalized(*args):
        definitions, references, schemas = original(*args)
        for definition in definitions:
            if definition.name == 'original':
                definition.name = 'normalized'
        for reference in references:
            if reference.kind == 'call':
                reference.callee_name = 'normalized'
        return definitions, references, schemas

    monkeypatch.setattr(rules, '_parse_ast_grep_matches', normalized)
    facts, units = extract(tmp_path, {'service.py':
        "def original():\n    pass\n@app.get('/run')\ndef run():\n    original()\n"})
    target = next(u for u in units if u.name == 'normalized')
    assert not any(u.name == 'original' for u in units)
    assert target.source.matches == []
    assert target.source.rule_outputs
    assert any(e['kind'] == 'calls' and e['to_ref'] == {'kind':'symbol','id':target.symbol_id}
               for e in facts['edges'].values())


def test_inventory_bounds_the_read_even_when_source_grows(tmp_path, monkeypatch):
    import io
    from lib.context import business_domain_extract as module
    path = tmp_path/'service.py'
    path.write_text('x')
    monkeypatch.setattr(module, 'source_paths', lambda root: ['service.py'])
    sizes = []
    class GrowingSource(io.BytesIO):
        def read(self, size=-1):
            sizes.append(size)
            return super().read(size)
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: GrowingSource(b'x' * 100))
    sources, diagnostics = module.inventory(tmp_path, {**DEFAULTS, 'max_source_bytes': 10})
    assert sizes == [11]
    assert sources == []
    assert [item['code'] for item in diagnostics] == ['SOURCE_LIMIT']


def test_trace_cycle_and_depth_are_bounded(tmp_path):
    facts, _ = extract(tmp_path, {'service.py': '''
@app.post('/orders')
def create():
    reserve()
def reserve():
    charge()
def charge():
    reserve()
'''}, max_trace_depth=1)
    trace = next(iter(facts['traces'].values()))
    assert len(trace['symbol_ids']) == 2
    assert trace['traversal_complete'] is False and trace['resolution'] == 'unresolved'
    assert trace['stop_reasons'] == ['depth_limit']
    assert trace['frontier_ids']


def test_sql_comments_strings_and_nested_end_do_not_split_routine():
    text = """CREATE OR REPLACE PACKAGE BODY payroll AS
PROCEDURE pay(p_id IN NUMBER) IS
BEGIN
  IF p_id > 0 THEN
    -- END; PROCEDURE imaginary IS BEGIN
    INSERT INTO notes VALUES ('END; FUNCTION fake IS BEGIN');
  END IF;
END pay;
FUNCTION balance(p_id IN NUMBER) RETURN NUMBER IS
BEGIN
 RETURN 1;
END balance;
END payroll;
/
"""
    source = Source('payroll.sql', 'sql', text, digest(text.encode()), identifier('resource', 'payroll.sql'))
    units = sql_units(source)
    assert [u.qualified for u in units] == ['payroll.sql::payroll.pay', 'payroll.sql::payroll.balance']
    assert units[0].text.endswith('END pay;')
    assert units[1].text.endswith('END balance;')


def test_unregistered_ui_implementations_are_supporting_symbols_not_anchors(tmp_path):
    facts, units = extract(tmp_path, {'NewOrder.tsx': "export default () => <OrderForm />;",
        'OrderForm.tsx': 'class OrderForm extends React.Component { render() { return <form />; } }'})
    assert facts['anchors'] == {}
    implementations = [unit for unit in units if getattr(unit, 'ui_implementation', False)]
    assert len(implementations) == 2
    assert all(unit.anchor_kind is None and unit.anchor_role == 'implementation'
               and unit.anchor_eligibility == 'supporting' for unit in implementations)


def test_secret_literals_and_outside_symlinks_are_excluded(tmp_path):
    (tmp_path/'outside.py').symlink_to('/etc/passwd')
    facts, _ = extract(tmp_path, {'api.py': '''
@app.get('/status')
def status():
    password = "do-not-copy-this-value"
    return password
'''})
    assert 'do-not-copy-this-value' not in str(facts)
    assert any(w['code'] == 'UNSAFE_SOURCE' for w in facts['warnings'])
    for evidence in facts['evidence'].values():
        assert digest(evidence['excerpt'].encode()) == evidence['content_hash']


def test_no_source_execution(tmp_path):
    facts, _ = extract(tmp_path, {'dag.py': "raise RuntimeError('must not import')\n@dag\ndef billing():\n    invoice()\n"})
    assert len(facts['anchors']) == 1


def test_core_accepts_an_unknown_language_without_language_branches(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from lib.context import business_domain_extract as core
    from lib.context.business_domain_adapters.base import Unit, declare_operation_observation
    adapter = SimpleNamespace(
        extract=lambda source: [Unit(source, 'entry', 'entry', 0, len(source.text),
                                    'function', anchor_kind='workflow', anchor_resolution='unresolved',
                                    anchor_reason='Fixture registration is not resolved',
                                    trace_role='declaration',
                                    required_relationships=('implementation_selection',),
                                    required_capabilities=(), valid_terminal=False)],
        parameter_direction=lambda name: 'input',
        bindings=lambda unit: [], resources=lambda unit: [],
        calls=lambda unit: [], candidates=lambda *args: [],
        observations=lambda unit: [{'span':(0,len(unit.text)),
            'source_location_kind':'workflow', 'native_expression':unit.text}],
        operations=lambda unit: [])
    monkeypatch.setattr(core, 'descriptor', lambda path: {
        'language':'unregistered-language', 'source_kind':'source', 'adapter':'fixture'})
    monkeypatch.setattr(core, 'adapter_for', lambda path: adapter)
    facts, _ = extract(tmp_path, {'flow.opaque':'input -> decision -> output'})
    assert len(facts['traces']) == 1
    assert len(facts['rule_observations']) == 1
    assert next(iter(facts['resources'].values()))['language'] == 'unregistered-language'


def test_api_contract_records_address_inputs_and_all_declared_responses(tmp_path):
    facts,_ = extract(tmp_path,{'api.yaml':'''openapi: 3.0.1
paths:
  /purchases/{id}:
    get:
      operationId: lookupPurchase
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            minLength: 1
      responses:
        200:
          description: Purchase found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Purchase'
        404:
          description: No such purchase
'''})
    anchor = next(iter(facts['anchors'].values()))
    assert anchor['operation']['method'] == 'GET'
    assert anchor['operation']['path'] == '/purchases/{id}'
    assert facts['symbols'][anchor['symbol_id']]['kind'] == 'declarative_operation'
    bindings = list(facts['bindings'].values())
    assert {v['name'] for v in bindings if v['direction']=='input'} == {'id'}
    assert {v['name'] for v in bindings if v['direction']=='output'} == {'response:200:application/json','response:404'}
    assert all(v['resolution']=='unresolved' for v in bindings)
    assert facts['rule_observations']


def test_nested_function_inputs_and_rules_stay_with_their_owner(tmp_path):
    facts,_ = extract(tmp_path,{'service.py':'''@app.post('/purchase')
def purchase(purchase_id):
    def calculate(discount):
        if discount > 10:
            return discount
        return 0
    return calculate(5)
'''})
    assert len(facts['anchors']) == 1
    anchor = next(iter(facts['anchors'].values()))
    assert anchor['operation']['method'] == 'POST'
    assert anchor['operation']['path'] == '/purchase'
    direct_inputs = {v['name'] for v in facts['bindings'].values() if v['direction']=='input'
                     and v['source']['id']==anchor['symbol_id']}
    assert direct_inputs == {'purchase_id'}
    assert len(facts['rule_observations']) == 1
    trace = next(iter(facts['traces'].values()))
    assert len(trace['symbol_ids']) == 2


def test_ui_records_controls_events_native_validation_and_route_identity(tmp_path):
    facts,_ = extract(tmp_path,{'Form.tsx':'''function submit(event) { event.preventDefault(); }
export default () => { return <form onSubmit={submit}><input name="reason" required /><button>Send</button></form>; };
''','Routes.tsx':'''export default () => <Route path='/purchases/:id' component={PurchaseForm} />;'''})
    interactions = [t['ui_interaction'] for t in facts['traces'].values() if t['ui_interaction']]
    forms = [ui for ui in interactions if ui['validations']]
    assert len(forms) == 1
    form = forms[0]
    assert len([e for e in form['elements'].values() if e['kind']=='control']) == 3
    assert any(e['trigger']=='onSubmit' and e['handler_symbol_id'] for e in form['events'].values())
    assert all(v['rule_observation_id'] and v['resolution']=='unresolved' for v in form['validations'].values())
    assert form['outputs']
    form_trace = next(t for t in facts['traces'].values() if t['ui_interaction'] == form)
    handler_ids = {e['handler_symbol_id'] for e in form['events'].values() if e['handler_symbol_id']}
    assert handler_ids <= set(form_trace['symbol_ids'])
    assert any(e['kind']=='selects_implementation' and e['resolution']=='resolved' for e in facts['edges'].values())
    routes = [e for ui in interactions for e in ui['elements'].values() if e['route_patterns']]
    assert len(routes) == 1 and routes[0]['route_patterns'][0]['pattern']=='/purchases/:id'
    assert routes[0]['label'] == 'PurchaseForm' and routes[0]['symbol_id']


def test_workflow_dependencies_and_callable_outputs_are_traced_without_imports(tmp_path):
    facts,_ = extract(tmp_path,{'billing.py':'''raise RuntimeError('do not import this DAG')
def calculate():
    return "invoice ready"
with DAG(dag_id="billing", schedule="@daily") as billing:
    prepare = PythonOperator(task_id="prepare", python_callable=calculate)
    post = BashOperator(task_id="post", bash_command="never execute this")
    prepare >> post
'''})
    names = {s['id']:s['signature'].split('(')[0] for s in facts['symbols'].values()}
    dependencies = [e for e in facts['edges'].values() if e['kind']=='depends_on']
    assert len(dependencies) == 1
    assert names[dependencies[0]['from_ref']['id']]=='post'
    assert names[dependencies[0]['to_ref']['id']]=='prepare'
    callbacks = [e for e in facts['edges'].values() if e['kind']=='calls' and e['to_ref'] and names[e['to_ref']['id']]=='calculate']
    assert callbacks and names[callbacks[0]['from_ref']['id']]=='prepare'
    assert any(b['direction']=='output' and b['expression']=='"invoice ready"' for b in facts['bindings'].values())


def test_non_workflow_operators_and_bit_shifts_do_not_create_workflow_edges(tmp_path):
    facts,_ = extract(tmp_path,{'numeric.py':'''def shift(a,b):
    operator = NumericOperator()
    return a >> b
'''})
    assert not facts['anchors']
    assert not [e for e in facts['edges'].values() if e['kind']=='depends_on']


def test_sql_alternative_quoted_strings_do_not_create_conditions_or_routines(tmp_path):
    facts,_ = extract(tmp_path,{'quotes.sql':'''CREATE OR REPLACE PROCEDURE process_order IS
BEGIN
  dbms_output.put_line(q'[customer's text:
IF fake THEN
END; FUNCTION imaginary IS BEGIN END;
]');
END;
/
'''})
    assert len(facts['anchors']) == 1
    assert not facts['rule_observations']


def test_sql_parser_classifies_calls_without_word_parenthesis_fallback(tmp_path):
    facts,_ = extract(tmp_path,{'orders.sql':'''CREATE OR REPLACE PACKAGE BODY orders AS
PROCEDURE SAVE_ORDER IS BEGIN NULL; END;
PROCEDURE submit IS BEGIN
  save_order();
  INSERT INTO billed_items (bill_id) VALUES (1);
  SELECT NVL(SUM(amount), 0) INTO total FROM bills b JOIN items i ON (b.id = i.bill_id);
  DBMS_OUTPUT.put_line(total);
  total := values_by_id(idx);
END;
END;
/
'''})
    names = {key:value['qualified_name'] for key,value in facts['symbols'].items()}
    calls = [edge for edge in facts['edges'].values() if edge['kind'] == 'calls']
    assert len(calls) == 2
    assert any(edge['resolution'] == 'resolved' and edge['to_ref']
               and names[edge['to_ref']['id']].endswith('.SAVE_ORDER') for edge in calls)
    assert any(edge['resolution'] == 'unresolved' and edge['to_ref']
               and edge['to_ref']['kind'] == 'resource' for edge in calls)
    assert all(facts['evidence'][edge['evidence_ids'][0]]['excerpt']
               in {'save_order()', 'DBMS_OUTPUT.put_line(total)'} for edge in calls)
    observed = [item['native_expression'].casefold()
                for item in facts['rule_observations'].values()]
    assert any(value.startswith('on (') for value in observed)
    assert any('nvl(' in value for value in observed)
    assert any('sum(' in value for value in observed)
    assert any('values_by_id(' in value for value in observed)
    assert any(edge['kind'] == 'writes_data' for edge in facts['edges'].values())
    assert any(edge['kind'] == 'reads_data' for edge in facts['edges'].values())
    capability = next(item for item in facts['capabilities'] if item['adapter'] == 'oracle_plsql')
    assert any(item['adapter'] == 'oracle_plsql' and item['feature'] == 'callable_resolution'
               and item['status'] == 'partial' for item in facts['capabilities'])
    assert 'PARTIAL_DIALECT_PARSER' in capability['diagnostic_codes']


def test_duplicate_private_body_routines_keep_distinct_source_identity_without_public_anchors(tmp_path):
    facts,_ = extract(tmp_path,{'one.sql':'''CREATE OR REPLACE PACKAGE BODY orders AS
PROCEDURE save(value IN NUMBER) IS BEGIN NULL; END;
PROCEDURE save(value IN DATE) IS BEGIN NULL; END;
END;
/
''','two.sql':'''CREATE OR REPLACE PACKAGE BODY orders AS
PROCEDURE save(value IN NUMBER) IS BEGIN NULL; END;
END;
/
'''})
    assert len(facts['symbols']) == 3
    assert facts['anchors'] == {}


def test_sql_table_constraints_follow_the_resource_into_activity_evidence(tmp_path):
    from lib.context.business_domain_work import whole_graph_scope
    facts,_ = extract(tmp_path,{'orders.sql':'''CREATE TABLE orders (
  id NUMBER PRIMARY KEY,
  amount NUMBER CHECK (
    amount >= 0
  )
);
CREATE OR REPLACE PROCEDURE place_order(id IN NUMBER, amount IN NUMBER) IS
BEGIN
  INSERT INTO orders VALUES (id, amount);
END;
/
'''})
    assert len(facts['anchors'])==1
    context=whole_graph_scope(facts)['context']
    observations=context['rule_observations'].values()
    assert any('CHECK' in o['native_expression'] and 'amount >= 0' in o['native_expression'] for o in observations)
    assert all(eid in context['evidence'] for o in observations for eid in o['evidence_ids'])


def test_sql_read_is_a_typed_operation_without_fabricated_effect(tmp_path):
    from lib.context.business_domain_work import whole_graph_scope
    facts, _ = extract(tmp_path, {'orders.sql': '''CREATE OR REPLACE PROCEDURE load_order(
  order_id IN NUMBER
) IS
BEGIN
  SELECT status
    INTO current_status
    FROM orders
   WHERE id = order_id;
END;
/
'''})
    reads = [edge for edge in facts['edges'].values() if edge['kind'] == 'reads_data']
    assert len(reads) == 1
    edge = reads[0]
    assert edge['from_ref']['kind'] == 'symbol' and edge['to_ref']['kind'] == 'resource'
    assert facts['resources'][edge['to_ref']['id']]['name'] == 'orders'
    assert facts['evidence'][edge['evidence_ids'][0]]['excerpt'].lstrip().startswith('SELECT status')
    bindings = [facts['bindings'][bid] for bid in edge['binding_ids']]
    assert {(binding['name'], binding['direction']) for binding in bindings} == {
        ('order_id', 'input'), ('current_status', 'output')}
    selected = next(binding for binding in bindings
                    if binding['name'] == 'current_status')
    assert selected['expression'] == 'status'
    assert facts['evidence'][selected['evidence_ids'][0]]['excerpt'] == 'status'
    assert not facts['effects']
    trace = next(iter(facts['traces'].values()))
    assert edge['id'] in trace['edge_ids']
    context = whole_graph_scope(facts)['context']
    assert edge['to_ref']['id'] in context['resources']
    assert edge['evidence_ids'][0] in context['evidence']
    assert set(edge['binding_ids']) <= set(context['bindings'])


def test_operation_integrity_rejects_orphaned_write_and_read_effect(tmp_path):
    from lib.context.business_domain_schema import DomainError, record
    facts, _ = extract(tmp_path, {'orders.sql': '''CREATE OR REPLACE PROCEDURE change_order(
  order_id IN NUMBER
) IS
BEGIN
  SELECT status INTO current_status FROM orders WHERE id = order_id;
  UPDATE orders SET status = 'done' WHERE id = order_id;
END;
/
'''})
    write = next(edge for edge in facts['edges'].values() if edge['kind'] == 'writes_data')
    effect = next(effect for effect in facts['effects'].values() if effect['edge_id'] == write['id'])
    del facts['effects'][effect['id']]
    with pytest.raises(DomainError, match='missing its effect'):
        validate_references(facts)
    facts['effects'][effect['id']] = effect
    read = next(edge for edge in facts['edges'].values() if edge['kind'] == 'reads_data')
    fabricated = record('Effect', id='effect:fabricated', kind='data_write',
        target=read['to_ref'], origin_ref=read['from_ref'], edge_id=read['id'],
        outcome='fabricated', evidence_ids=read['evidence_ids'],
        trace_ids=[trace['id'] for trace in facts['traces'].values() if read['id'] in trace['edge_ids']],
        resolution='unresolved',
        reason='fixture')
    facts['effects'][fabricated['id']] = fabricated
    with pytest.raises(DomainError, match='Data reads cannot fabricate effects'):
        validate_references(facts)


def test_ui_event_captures_reachable_http_call_without_claiming_remote_success(tmp_path):
    facts,_=extract(tmp_path,{'Form.tsx':'''function submit(event) {
  event.preventDefault();
  return fetch('/refund-requests', {method:'POST'});
}
export default () => <form onSubmit={submit}><button>Send</button></form>;
'''})
    effects=list(facts['effects'].values())
    assert len(effects)==1
    assert effects[0]['completion']=='declared' and effects[0]['resolution']=='unresolved'
    target=facts['resources'][effects[0]['target']['id']]
    assert target['name']=='/refund-requests'
    ui=next(t['ui_interaction'] for t in facts['traces'].values() if t['ui_interaction'])
    assert len(ui['calls'])==1
    call=next(iter(ui['calls'].values()))
    assert call['target_anchor_id'] is None
    assert call['resolution']=='unresolved'
    effect = effects[0]
    edge = facts['edges'][effect['edge_id']]
    assert edge['kind'] == 'invokes_endpoint' and edge['from_ref'] == effect['origin_ref']
    assert effect['trace_ids']
    assert all(effect['edge_id'] in facts['traces'][tid]['edge_ids'] for tid in effect['trace_ids'])
    assert facts['evidence'][effect['evidence_ids'][0]]['excerpt'] == "fetch('/refund-requests', {method:'POST'})"


def test_effect_reachability_does_not_depend_on_overlapping_evidence(tmp_path):
    from lib.context.business_domain_schema import DomainError
    facts, _ = extract(tmp_path, {'billing.sql': '''CREATE OR REPLACE PACKAGE billing AS
PROCEDURE pay;
PROCEDURE unrelated;
END billing;
/
CREATE OR REPLACE PACKAGE BODY billing AS
PROCEDURE pay IS BEGIN INSERT INTO payments VALUES (1); END;
PROCEDURE unrelated IS BEGIN NULL; END;
END billing;
/
'''} )
    effect = next(iter(facts['effects'].values()))
    assert facts['evidence'][effect['evidence_ids'][0]]['excerpt'] == 'INSERT INTO payments VALUES (1);'
    assert effect['origin_ref']['id'] not in effect['evidence_ids']
    assert len(effect['trace_ids']) == 1
    trace = facts['traces'][effect['trace_ids'][0]]
    assert effect['edge_id'] in trace['edge_ids']
    assert set(effect['evidence_ids']) <= set(trace['evidence_ids'])
    other = next(t for t in facts['traces'].values() if t['id'] != trace['id'])
    other['evidence_ids'] = sorted(set(other['evidence_ids']) | set(effect['evidence_ids']))
    validate_references(facts)
    effect['trace_ids'].append(other['id'])
    with pytest.raises(DomainError, match='operation reachability'):
        validate_references(facts)


def test_resolved_resource_edge_is_a_terminal_not_a_callable(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from lib.context import business_domain_extract as core
    from lib.context.business_domain_adapters.base import Unit, declare_operation_observation
    adapter = SimpleNamespace(
        extract=lambda source: [Unit(source, 'entry', 'entry', 0, len(source.text),
            'function', anchor_kind='workflow', anchor_resolution='resolved', executable_body=True,
            trace_role='implementation', required_relationships=(),
            required_capabilities=(), valid_terminal=True)],
        bindings=lambda unit: [], resources=lambda unit: [], calls=lambda unit: [],
        observations=lambda unit: [], operations=lambda unit: [declare_operation_observation(unit,
            position=0, end=len(unit.text), kind='data_write', outcome='Fixture write',
            resource={'kind':'table','name':'fixture','resolution':'resolved','reason':None},
            transaction_scope='fixture_transaction', completion='declared',
            projection_gaps=[{'projection':'completion',
                'code':'FIXTURE_COMPLETION_UNRESOLVED',
                'reason':'Runtime completion is not established.'}],
            resolution='unresolved', reason='Runtime completion is not established.')])
    monkeypatch.setattr(core, 'descriptor', lambda path: {'language':'fixture','source_kind':'source',
        'capability':{'id':'fixture','version':'1','capabilities':{
            'data_access':'supported','outputs':'supported'}}})
    monkeypatch.setattr(core, 'adapter_for', lambda source: adapter)
    facts, _ = extract(tmp_path, {'flow.opaque':'write(value)'})
    trace = next(iter(facts['traces'].values()))
    effect = next(iter(facts['effects'].values()))
    assert trace['resolution'] == 'unresolved'
    assert effect['target']['id'] not in trace['symbol_ids']
    assert effect['edge_id'] in trace['edge_ids'] and effect['trace_ids'] == [trace['id']]


def test_activity_packet_keeps_typed_resource_edge_closure_without_effect(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from lib.context import business_domain_extract as core
    from lib.context.business_domain_adapters.base import Unit, declare_operation_observation
    from lib.context.business_domain_work import whole_graph_scope
    adapter = SimpleNamespace(
        extract=lambda source: [Unit(source, 'entry', 'entry', 0, len(source.text),
            'function', anchor_kind='workflow', anchor_resolution='resolved', executable_body=True,
            trace_role='implementation', required_relationships=(),
            required_capabilities=(), valid_terminal=True)],
        bindings=lambda unit: [], resources=lambda unit: [], calls=lambda unit: [],
        observations=lambda unit: [], operations=lambda unit: [declare_operation_observation(unit,
            position=0, end=len(unit.text), kind='data_read', outcome='Fixture read',
            resource={'kind':'table','name':'fixture','resolution':'resolved','reason':None},
            resolution='resolved', reason=None)])
    monkeypatch.setattr(core, 'descriptor', lambda path: {'language':'fixture','source_kind':'source',
        'capability':{'id':'fixture','version':'1','capabilities':{
            'data_access':'supported','outputs':'supported'}}})
    monkeypatch.setattr(core, 'adapter_for', lambda source: adapter)
    facts, _ = extract(tmp_path, {'flow.opaque':'write(value)'})
    edge = next(edge for edge in facts['edges'].values() if edge['to_ref']['kind'] == 'resource')
    resource = facts['resources'][edge['to_ref']['id']]
    exact_evidence = edge['evidence_ids'][0]
    context = whole_graph_scope(facts)['context']

    assert context['resources'][resource['id']] == resource
    assert context['evidence'][exact_evidence] == facts['evidence'][exact_evidence]
    snapshot_id = facts['evidence'][exact_evidence]['locator']['snapshot_id']
    assert context['source_snapshots'][snapshot_id] == facts['source_snapshots'][snapshot_id]
    assert resource['id'] not in context['record_refs']


def test_receiver_parameter_in_sibling_method_cannot_resolve_call(tmp_path):
    facts,_ = extract(tmp_path,{'Service.java':'''class Service {
    void setup(Repository store) { }
    void execute() { store.save(); }
}
class Repository { void save() { } }
'''})
    calls = [e for e in facts['edges'].values() if e['kind']=='calls']
    assert len(calls) == 1
    assert calls[0]['resolution']=='unresolved' and calls[0]['to_ref'] is None


def test_receiver_parameter_in_current_method_resolves_call(tmp_path):
    facts,_ = extract(tmp_path,{'Service.java':'''class Service {
    void execute(Repository store) { store.save(); }
}
class Repository { void save() { } }
'''})
    calls = [e for e in facts['edges'].values() if e['kind']=='calls']
    assert len(calls) == 1
    assert calls[0]['resolution']=='resolved'
    target = facts['symbols'][calls[0]['to_ref']['id']]
    assert 'Repository.save' in target['qualified_name']
