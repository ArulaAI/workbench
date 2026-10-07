"""Activities that share one UI trace own only their own request branch.

A miniature of the PetClinic editor shape: one submit handler sends POST for a
new owner and PUT for an existing one, chosen by ``owner.isNew``.  Only the
POST branch reaches a database write.  A second handler sends POST and GET one
after the other, so both requests are its own work.
"""
import uuid

from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, activity_closure, copy_facts, record, validate_references,
)
from lib.context.business_domain_synthesis import normalize_ids
from lib.context.business_domain_work import whole_graph_scope
from lib.context.business_domains import accept_candidate


SERVICE = """package com.example;
public interface ClinicService {
  void createOwner();
  void renameOwner(int ownerId);
  String findOwners();
}
"""

SERVICE_IMPL = """package com.example;
import javax.sql.DataSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
@Service
public class ClinicServiceImpl implements ClinicService {
  private NamedParameterJdbcTemplate template;
  public ClinicServiceImpl(DataSource dataSource) {
    this.template = new NamedParameterJdbcTemplate(dataSource);
  }
  @Override public void createOwner() {
    this.template.update("INSERT INTO owners (last_name) VALUES (:lastName)", null);
  }
  @Override public void renameOwner(int ownerId) { }
  @Override public String findOwners() {
    return this.template.query("SELECT id, last_name FROM owners", null, null).toString();
  }
}
"""

CONTROLLER = """package com.example;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
@RestController
@RequestMapping("/api")
public class OwnerController {
  private final ClinicService clinicService;
  OwnerController(ClinicService clinicService) { this.clinicService = clinicService; }
  @PostMapping("/owners") public void addOwner() { clinicService.createOwner(); }
  @PutMapping("/owners/{ownerId}") public void updateOwner(@PathVariable int ownerId) { clinicService.renameOwner(ownerId); }
  @GetMapping("/owners") public String listOwners() { return clinicService.findOwners(); }
}
"""

UTIL = """declare var __API_SERVER_URL__;
const BACKEND_URL = (typeof __API_SERVER_URL__ === 'undefined' ? 'http://localhost:9966/petclinic' : __API_SERVER_URL__);
export const url = (path: string): string => `${BACKEND_URL}/${path}`;
export const submitForm = (method: string, path: string, data: any, onSuccess: (status: number) => void) => {
  return fetch(url(path), { method: method, body: JSON.stringify(data) }).then(response => onSuccess(response.status));
};
"""

WEBPACK = """var webpack = require('webpack');
module.exports = {
  plugins: [
    new webpack.DefinePlugin({
      __API_SERVER_URL__: JSON.stringify('http://localhost:9966/petclinic')
    })
  ]
};
"""


def _editor(name, body, label):
    return f"""import * as React from 'react';
import {{ submitForm, url }} from './util';

export default class {name} extends React.Component<any, any> {{
  constructor(props) {{
    super(props);
    this.onSubmit = this.onSubmit.bind(this);
  }}

  onSubmit(event) {{
    const {{ owner }} = this.state;
    {body}
  }}

  render() {{
    return <button type='submit' onClick={{this.onSubmit}}>{label}</button>;
  }}
}}
"""


FILES = {
    'pom.xml': '<project><groupId>com.example</groupId><artifactId>clinic</artifactId></project>\n',
    'src/main/resources/application.properties':
        'server.port=9966\nserver.servlet.context-path=/petclinic/\n',
    'src/main/resources/db/hsqldb/initDB.sql':
        'CREATE TABLE owners (\n  id INTEGER PRIMARY KEY,\n  last_name VARCHAR(30)\n);\n',
    'src/main/java/com/example/ClinicService.java': SERVICE,
    'src/main/java/com/example/ClinicServiceImpl.java': SERVICE_IMPL,
    'src/main/java/com/example/OwnerController.java': CONTROLLER,
    'client/package.json': '{"name": "client"}\n',
    'client/webpack.config.js': WEBPACK,
    'client/src/util/index.tsx': UTIL,
    'client/src/OwnerEditor.tsx': _editor('OwnerEditor', """const path = owner.isNew ? 'api/owners' : 'api/owners/' + owner.id;
    submitForm(owner.isNew ? 'POST' : 'PUT', path, owner, status => status);""", 'Save Owner'),
    'client/src/QuickAdd.tsx': _editor('QuickAdd', """submitForm('POST', 'api/owners', owner, status => status);
    fetch(url('api/owners'));""", 'Quick Add'),
}


def _extract(root):
    for name, text in FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, _ = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    return facts


def _anchor(facts, kind, method, name):
    return next(anchor for anchor in facts['anchors'].values()
                if anchor['kind'] == kind and anchor['operation']['method'] == method
                and (anchor['operation']['path'] or anchor['operation']['name']) == name)


def _traces(facts, *anchors):
    by_anchor = {trace['anchor_id']: trace['id'] for trace in facts['traces'].values()}
    return [by_anchor[anchor['id']] for anchor in anchors]


def _owner_write(facts):
    effect, = [effect for effect in facts['effects'].values() if effect['kind'] == 'data_write']
    return effect['id']


def _candidate(graph, activities):
    evidence = sorted(graph['context']['evidence'])
    owners = {}
    for activity in activities:
        activity.update(evidence_ids=evidence, claim_ids=['claim:' + activity['id'].split(':')[1]])
        for anchor_id in activity['anchor_ids']:
            owners.setdefault(anchor_id, []).append(activity['id'])
    claims = [record('Claim', id=activity['claim_ids'][0], subject_id=activity['id'],
                     text=activity['description'], kind='behavior', evidence_ids=evidence,
                     trace_ids=activity['trace_ids'], semantic_review='uncertain')
              for activity in activities]
    return record(
        'CandidatePayload', scope_id=graph['scope_id'],
        input_fingerprint=graph['input_fingerprint'],
        activities={activity['id']: activity for activity in activities},
        claims={claim['id']: claim for claim in claims},
        dispositions=[record(
            'ScopeDisposition', id=f'disposition:{index}', subject_kind='anchor',
            subject_id=anchor_id, status='represented' if anchor_id in owners else 'excluded',
            activity_ids=owners.get(anchor_id, []),
            reason=None if anchor_id in owners else 'Outside the activities under test.',
            evidence_ids=[] if anchor_id in owners else evidence)
            for index, anchor_id in enumerate(graph['canonical_anchor_ids'])])


def _activity(name, facts, *anchors):
    return record('Activity', id=f'activity:{name.lower()}', name=name,
                  description=f'{name} an owner.', anchor_ids=[a['id'] for a in anchors],
                  trace_ids=_traces(facts, *anchors), support='partial')


def test_conditional_branch_effect_belongs_only_to_the_branch_that_reaches_it(tmp_path):
    facts = _extract(tmp_path)
    save = _anchor(facts, 'ui', 'onClick', 'Save Owner')
    create = _activity('Create', facts, save, _anchor(facts, 'http', 'POST', '/api/owners'))
    update = _activity('Update', facts, save, _anchor(facts, 'http', 'PUT', '/api/owners/{ownerId}'))
    write = _owner_write(facts)
    shared, = _traces(facts, save)
    assert shared in facts['effects'][write]['trace_ids']
    model = copy_facts(facts, str(uuid.uuid4()))
    graph = whole_graph_scope(model)

    normalized = normalize_ids(_candidate(graph, [create, update]), graph)
    accept_candidate(model, graph, normalized)
    validate_references(model)

    accepted = {activity['name']: activity for activity in model['activities'].values()}
    assert write in accepted['Create']['effect_ids']
    assert write not in accepted['Update']['effect_ids']
    for activity in accepted.values():
        proposed = next(item for item in normalized['activities'].values()
                        if item['name'] == activity['name'])
        for field, expected in activity_closure(model, activity).items():
            assert set(activity[field]) == expected
            if field != 'information_use_ids':
                assert sorted(proposed[field]) == sorted(expected)
    # The create branch owns the write through the shared trace alone.
    assert write in activity_closure(model, {**create, 'trace_ids': [shared]})['effect_ids']


def test_sequential_requests_keep_the_work_of_every_request(tmp_path):
    facts = _extract(tmp_path)
    quick_add = _anchor(facts, 'ui', 'onClick', 'Quick Add')
    listing = _anchor(facts, 'http', 'GET', '/api/owners')
    write = _owner_write(facts)
    trace, = _traces(facts, quick_add)
    model = copy_facts(facts, str(uuid.uuid4()))
    activity = {'id': 'activity:list', 'anchor_ids': [quick_add['id'], listing['id']],
                'trace_ids': [trace]}

    # The submit always POSTs before it GETs: claiming the GET endpoint does
    # not make the POST an alternative branch.
    assert write in activity_closure(model, activity)['effect_ids']
