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
    })

    interaction = next(trace['ui_interaction'] for trace in facts['traces'].values()
                       if trace.get('ui_interaction'))
    assert any(event['handler_symbol_id'] for event in interaction['events'].values())
    assert interaction['calls']
    effect = next(iter(facts['effects'].values()))
    assert facts['resources'][effect['target']['id']]['name'] == '/api/orders'
    assert any(edge['kind'] == 'composes' and edge['resolution'] == 'resolved'
               for edge in facts['edges'].values())
