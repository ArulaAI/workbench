"""Section 4 frontend-reader acceptance tests."""
from lib.context.business_domain_adapters import descriptor, enricher_descriptors
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


def test_typescript_reader_and_react_enricher_are_registry_selected(tmp_path):
    assert descriptor('view.tsx')['adapter'] == 'ts_semantic'
    assert descriptor('view.jsx')['adapter'] == 'ts_semantic'
    selected = enricher_descriptors('view.tsx', {'imports': ['react']})
    assert [item['module'] for item in selected] == ['react_semantic']
    assert enricher_descriptors('view.tsx', {'imports': []}) == []
    _, units = _extract(tmp_path, {
        'View.jsx': "export default () => <button>Save</button>;\n",
    })
    assert any(unit.source.language == 'jsx' and unit.name == 'View.default'
               for unit in units)


def test_html_form_reader_emits_anchor_binding_effect_and_interaction(tmp_path):
    facts, _ = _extract(tmp_path, {'checkout.html': '''
<form action="/orders" method="post">
  <input name="customer" required>
  <button type="submit">Save</button>
</form>
'''})

    anchor = next(item for item in facts['anchors'].values()
                  if item['kind'] == 'ui')
    trace = next(item for item in facts['traces'].values()
                 if item['anchor_id'] == anchor['id'])
    effect = next(iter(facts['effects'].values()))
    assert effect['target']['id'] in facts['resources']
    assert facts['resources'][effect['target']['id']]['name'] == '/orders'
    assert any(item['name'] == 'customer' for item in facts['bindings'].values())
    assert trace['ui_interaction']['events']
    assert trace['ui_interaction']['validations']


def _form_anchors(facts):
    return [anchor for anchor in facts['anchors'].values()
            if anchor['kind'] == 'ui' and any(
                (item['identity_key'] or '').startswith('ui:repository:form:')
                for item in anchor['representations'])]


def test_html_form_identity_is_its_submission_not_its_file(tmp_path):
    facts, _ = _extract(tmp_path, {
        'owners/new.html': '''
<form action="/owners" METHOD="Post">
  <input name="name" required>
  <button type="submit">  Add
     Owner </button>
</form>
''',
        'owners/copy.html': '''<html><body>
<form action="/owners" method="post"><button>Add Owner</button></form>
</body></html>
''',
        'search.html': '<form action="/owners/find"><input type="submit" value="Find"></form>\n',
    })

    forms = {anchor['representations'][0]['identity_key']: anchor
             for anchor in _form_anchors(facts)}
    # The same submission written in two files is one entry point.
    assert set(forms) == {'ui:repository:form:POST:/owners:Add Owner',
                          'ui:repository:form:GET:/owners/find:Find'}
    create = forms['ui:repository:form:POST:/owners:Add Owner']
    assert len(create['representations']) == 2
    assert create['canonical_anchor_id'] == create['id']
    assert create['resolution'] == 'resolved'
    assert create['eligibility'] == 'eligible'
    assert (create['operation']['method'], create['operation']['path']) == ('POST', '/owners')
    assert {item['registration']['label'] for item in create['representations']} == {'Add Owner'}
    search = forms['ui:repository:form:GET:/owners/find:Find']
    assert (search['operation']['method'], search['operation']['path']) == ('GET', '/owners/find')


def test_html_form_identity_marks_parts_it_cannot_determine(tmp_path):
    facts, _ = _extract(tmp_path, {
        'thymeleaf.html': '''<form th:action="@{/owners}" method="post">
  <button type="submit" th:text="${label}">Add Owner</button>
</form>
''',
        'angular.html': '<form (ngSubmit)="save()"><button type="submit">Save</button></form>\n',
        'choices.html': '''<form action="/visits" method="post">
  <button name="draft">Save draft</button>
  <button>Publish</button>
</form>
''',
        'dialog.html': '<form action="/x" method="dialog"><button>Close</button></form>\n',
        'razor.cshtml': '<form asp-action="Logout"><button>Yes</button></form>\n',
    })

    forms = _form_anchors(facts)
    assert {anchor['representations'][0]['identity_key'] for anchor in forms} == {
        'ui:repository:form:POST:<unresolved>:<unresolved>@thymeleaf.html:0',
        'ui:repository:form:GET:<unresolved>:Save@angular.html:0',
        'ui:repository:form:POST:/visits:<unresolved>@choices.html:0',
        'ui:repository:form:<unresolved>:/x:Close@dialog.html:0',
        # A tag helper renders both the action and the method.
        'ui:repository:form:<unresolved>:<unresolved>:Yes@razor.cshtml:0',
    }
    for anchor in forms:
        assert anchor['resolution'] == 'unresolved'
        assert 'not statically determined' in anchor['reason']
        assert anchor['representations'][0]['registration']['resolution'] == 'unresolved'


def test_typescript_reader_resolves_local_imports_and_external_modules(tmp_path):
    facts, _ = _extract(tmp_path, {
        'api.ts': "export function send() { return fetch('/api/orders'); }\n",
        'submit.ts': '''
import { send } from './api';
import moment from 'moment';
export default function submit() { send(); return moment(); }
''',
    })

    calls = [edge for edge in facts['edges'].values()
             if edge['kind'] == 'calls']
    def excerpts(edge):
        return {facts['evidence'][eid]['excerpt']
                for eid in edge['evidence_ids']}
    local = next(edge for edge in calls if 'send()' in excerpts(edge))
    external = next(edge for edge in calls if 'moment()' in excerpts(edge))
    assert local['resolution'] == 'resolved'
    assert local['to_ref']['kind'] == 'symbol'
    assert external['to_ref']['kind'] == 'resource'
    effect = next(iter(facts['effects'].values()))
    assert facts['resources'][effect['target']['id']]['name'] == '/api/orders'


def test_react_reader_classifies_runtime_and_projects_state_transition(tmp_path):
    facts, _ = _extract(tmp_path, {'Counter.tsx': '''
import React, { Component } from 'react';
export class Counter extends Component {
  constructor() { this.state = {count: 0}; }
  increment() { this.setState({count: 1}); }
  render() { return <button onClick={this.increment}>Increment</button>; }
}
'''})

    interaction = next(trace['ui_interaction'] for trace in facts['traces'].values()
                       if trace.get('ui_interaction'))
    assert interaction['states']
    assert interaction['transitions']
    set_state = next(edge for edge in facts['edges'].values()
                     if any(facts['evidence'][eid]['excerpt'].startswith('this.setState')
                            for eid in edge['evidence_ids']))
    assert set_state['to_ref']['kind'] == 'resource'


def test_angular_template_handler_reaches_http_client_effect(tmp_path):
    facts, _ = _extract(tmp_path, {
        'orders.component.ts': '''
import { Component } from '@angular/core';
import { HttpClient } from '@angular/common/http';
@Component({templateUrl: './orders.component.html'})
export class OrdersComponent {
  constructor(private http: HttpClient) {}
  save() { return this.http.post('/api/orders', {}); }
}
''',
        'orders.component.html': '''
<form (ngSubmit)="save()">
  <input formControlName="customer">
  <button type="submit">Save</button>
</form>
''',
        'openapi.yml': '''
openapi: 3.0.0
paths:
  /api/orders:
    post:
      operationId: createOrder
      responses:
        "200":
          description: Created
''',
    })

    interaction = next(trace['ui_interaction'] for trace in facts['traces'].values()
                       if trace.get('ui_interaction'))
    assert any(event['handler_symbol_id'] for event in interaction['events'].values())
    assert interaction['calls']
    effect = next(iter(facts['effects'].values()))
    assert facts['resources'][effect['target']['id']]['name'] == '/api/orders'
    call = next(iter(interaction['calls'].values()))
    endpoint = facts['anchors'][call['target_anchor_id']]
    assert effect['target_identity_key'] == 'http:repository:POST:/api/orders'
    assert endpoint['operation']['method'] == 'POST'
    assert endpoint['operation']['path'] == '/api/orders'
    assert call['resolution'] == 'resolved'
    assert any(edge['kind'] == 'composes' and edge['resolution'] == 'resolved'
               for edge in facts['edges'].values())


def test_fetch_get_links_to_exact_http_anchor(tmp_path):
    facts, _ = _extract(tmp_path, {
        'Owners.tsx': '''
function loadOwners() { return fetch('/api/owners'); }
export default () => <button onClick={loadOwners}>Load owners</button>;
''',
        'openapi.yml': '''
openapi: 3.0.0
paths:
  /api/owners:
    get:
      operationId: listOwners
      responses:
        "200":
          description: Owners
''',
    })

    effect = next(iter(facts['effects'].values()))
    interaction = next(trace['ui_interaction'] for trace in facts['traces'].values()
                       if trace.get('ui_interaction')
                       and trace['ui_interaction']['calls'])
    call = next(iter(interaction['calls'].values()))
    endpoint = facts['anchors'][call['target_anchor_id']]
    assert effect['target_identity_key'] == 'http:repository:GET:/api/owners'
    assert endpoint['operation']['method'] == 'GET'
    assert endpoint['operation']['path'] == '/api/owners'
    assert call['resolution'] == 'resolved'
    assert call['reason'] is None


def test_fetch_does_not_link_to_same_path_with_different_method(tmp_path):
    facts, _ = _extract(tmp_path, {
        'Owners.tsx': '''
function loadOwners() { return fetch('/api/owners'); }
export default () => <button onClick={loadOwners}>Load owners</button>;
''',
        'openapi.yml': '''
openapi: 3.0.0
paths:
  /api/owners:
    post:
      operationId: createOwner
      responses:
        "200":
          description: Owner
''',
    })

    call = next(call for trace in facts['traces'].values()
                if trace.get('ui_interaction')
                for call in trace['ui_interaction']['calls'].values())
    assert call['target_anchor_id'] is None
    assert call['resolution'] == 'unresolved'
    assert call['reason']


def test_fetch_with_dynamic_options_does_not_guess_method(tmp_path):
    facts, _ = _extract(tmp_path, {
        'Owners.tsx': '''
function loadOwners(options) { return fetch('/api/owners', options); }
export default () => <button onClick={loadOwners}>Load owners</button>;
''',
        'openapi.yml': '''
openapi: 3.0.0
paths:
  /api/owners:
    get:
      operationId: listOwners
      responses:
        "200":
          description: Owners
''',
    })

    effect = next(iter(facts['effects'].values()))
    call = next(call for trace in facts['traces'].values()
                if trace.get('ui_interaction')
                for call in trace['ui_interaction']['calls'].values())
    assert effect['target_identity_key'] is None
    assert call['target_anchor_id'] is None
    assert call['resolution'] == 'unresolved'


def test_javascript_fetch_uses_the_same_get_identity(tmp_path):
    facts, _ = _extract(tmp_path, {
        'owners.js': "export function loadOwners() { return fetch('/api/owners'); }\n",
    })

    effect = next(iter(facts['effects'].values()))
    assert effect['target_identity_key'] == 'http:repository:GET:/api/owners'
