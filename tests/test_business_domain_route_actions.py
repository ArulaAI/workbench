"""Actions in composed components are anchored per route and labelled from literals.

A component composed by several routed pages shows its action once per route,
so each route gets its own action anchor. The visible label comes only from
string literals: a literal child, a conditional over literals, or a ``const``
assigned only literals. A choice between literals is made per route when the
page on that route passes a literal value for the flag the choice tests;
otherwise every candidate stays recorded as ambiguous. A label with a runtime
part leaves the action explicitly unlabeled.
"""
import pytest

from tests.test_business_domain_endpoint_links import (
    BACKEND, UTIL, VISIT_EDITOR, WEBPACK_DEV, _extract, _name)

ROUTES = """import * as React from 'react';
import { Route } from 'react-router';
import NewOwnerPage from './NewOwnerPage';
import EditOwnerPage from './EditOwnerPage';
import NewPetPage from './NewPetPage';
import EditPetPage from './EditPetPage';
import CreateTagPage from './CreateTagPage';
import EditTagPage from './EditTagPage';
import TagForm from './TagForm';
import NotesPage from './NotesPage';
import ArchivePage from './ArchivePage';
import VisitEditor from './VisitEditor';

export default () => (
  <Route>
    <Route path='/owners/new' component={NewOwnerPage} />
    <Route path='/owners/:ownerId/edit' component={EditOwnerPage} />
    <Route path='/pets/new' component={NewPetPage} />
    <Route path='/pets/:petId/edit' component={EditPetPage} />
    <Route path='/tags/new' component={CreateTagPage} />
    <Route path='/tags/:tagId/edit' component={EditTagPage} />
    <Route path='/tags/form' component={TagForm} />
    <Route path='/notes' component={NotesPage} />
    <Route path='/archive' component={ArchivePage} />
    <Route path='/visits/new' component={VisitEditor} />
  </Route>
);
"""

# The flag is read from state the constructor seeds from a prop.
OWNER_EDITOR = """import * as React from 'react';
import { submitForm } from './util';

export default class OwnerEditor extends React.Component<any, any> {
  constructor(props) {
    super(props);
    this.onSubmit = this.onSubmit.bind(this);
    this.state = { owner: Object.assign({}, props.initialOwner) };
  }

  onSubmit(event) {
    const { owner } = this.state;
    const url = owner.isNew ? '/api/owners' : '/api/owners/' + owner.id;
    submitForm(owner.isNew ? 'POST' : 'PUT', url, owner, status => status);
  }

  render() {
    const { owner } = this.state;
    return <button type='submit' onClick={this.onSubmit}>{owner.isNew ? 'Add Owner' : 'Update Owner'}</button>;
  }
}
"""

NEW_OWNER_PAGE = """import * as React from 'react';
import OwnerEditor from './OwnerEditor';

const newOwner = () => ({
  id: null,
  isNew: true
});

export default () => <OwnerEditor initialOwner={newOwner()} />;
"""

# A literal object without the flag leaves it undefined, which is falsy.
EDIT_OWNER_PAGE = """import * as React from 'react';
import OwnerEditor from './OwnerEditor';

export default () => <OwnerEditor initialOwner={{ id: 1, firstName: 'George' }} />;
"""

# The label is a const assigned only literals; the flag is a destructured prop.
PET_EDITOR = """import * as React from 'react';
import { submitForm } from './util';

export default class PetEditor extends React.Component<any, any> {
  constructor(props) {
    super(props);
    this.onSubmit = this.onSubmit.bind(this);
  }

  onSubmit(event) {
    submitForm('PUT', '/api/owners/1/pets/1', {}, status => status);
  }

  render() {
    const { pet } = this.props;
    const formLabel = pet.isNew ? 'Add Pet' : 'Update Pet';
    return <button type='submit' onClick={this.onSubmit}>{formLabel}</button>;
  }
}
"""

NEW_PET_PAGE = """import * as React from 'react';
import PetEditor from './PetEditor';

const NEW_PET = { id: null, isNew: true, name: '' };

export default () => <PetEditor pet={NEW_PET} />;
"""

# The pet comes from state loaded at runtime: nothing fixes the flag.
EDIT_PET_PAGE = """import * as React from 'react';
import PetEditor from './PetEditor';

export default class EditPetPage extends React.Component<any, any> {
  render() {
    return <PetEditor pet={this.state.pet} />;
  }
}
"""

# A function component with a destructured boolean prop, passed as a bare
# JSX flag on one page and as a literal on the other.
TAG_FORM = """import * as React from 'react';

function saveTag() {
  return null;
}

export default ({ isNew }) => <button onClick={saveTag}>{isNew ? 'Create Tag' : 'Save Tag'}</button>;
"""

CREATE_TAG_PAGE = """import * as React from 'react';
import TagForm from './TagForm';

export default () => <TagForm isNew />;
"""

EDIT_TAG_PAGE = """import * as React from 'react';
import TagForm from './TagForm';

export default () => <TagForm isNew={false} />;
"""

NOTES_PAGE = """import * as React from 'react';

export default class NotesPage extends React.Component<any, any> {
  constructor(props) {
    super(props);
    this.onSave = this.onSave.bind(this);
  }

  onSave() {
    return null;
  }

  render() {
    return <button onClick={this.onSave}>{this.state.saveLabel}</button>;
  }
}
"""

# Literal values, but the identifier is reassigned, so it is not a constant.
ARCHIVE_PAGE = """import * as React from 'react';

function archive() {
  return null;
}

export default ({ done }) => {
  let label = 'Archive';
  if (done) {
    label = 'Restore';
  }
  return <button onClick={archive}>{label}</button>;
};
"""

CLIENT = {
    'client/package.json': '{"name": "client"}\n',
    'client/webpack.config.js': WEBPACK_DEV,
    'client/src/util/index.tsx': UTIL,
    'client/src/routes.tsx': ROUTES,
    'client/src/OwnerEditor.tsx': OWNER_EDITOR,
    'client/src/NewOwnerPage.tsx': NEW_OWNER_PAGE,
    'client/src/EditOwnerPage.tsx': EDIT_OWNER_PAGE,
    'client/src/PetEditor.tsx': PET_EDITOR,
    'client/src/NewPetPage.tsx': NEW_PET_PAGE,
    'client/src/EditPetPage.tsx': EDIT_PET_PAGE,
    'client/src/TagForm.tsx': TAG_FORM,
    'client/src/CreateTagPage.tsx': CREATE_TAG_PAGE,
    'client/src/EditTagPage.tsx': EDIT_TAG_PAGE,
    'client/src/NotesPage.tsx': NOTES_PAGE,
    'client/src/ArchivePage.tsx': ARCHIVE_PAGE,
    'client/src/VisitEditor.tsx': VISIT_EDITOR,
}


@pytest.fixture(scope='module')
def facts(tmp_path_factory):
    return _extract(tmp_path_factory.mktemp('route-actions'), {**BACKEND, **CLIENT})


def _registration(anchor):
    return next((item for item in anchor['representations']
                 if item['role'] == 'registration'), None)


def _actions(facts, component):
    return [anchor for anchor in facts['anchors'].values()
            if anchor['kind'] == 'ui' and _registration(anchor)
            and _registration(anchor)['registration']['kind'] == 'action'
            and facts['symbols'][anchor['symbol_id']]['file'].endswith(f'/{component}.tsx')]


def _by_route(facts, component):
    return {anchor['operation']['path']: anchor for anchor in _actions(facts, component)}


def _warnings(facts, code):
    return [item['message'] for item in facts['warnings'] if item['code'] == code]


def test_a_composed_component_has_one_action_anchor_per_route(facts):
    actions = _by_route(facts, 'OwnerEditor')
    assert set(actions) == {'/owners/new', '/owners/:ownerId/edit'}
    for route, anchor in actions.items():
        representation = _registration(anchor)
        assert representation['identity_key'].startswith(
            f'ui:client:action:{route}:onClick:')
        assert representation['registration']['scope'] == route
        assert representation['registration']['target'] == 'OwnerEditor.onSubmit'
    assert len({anchor['id'] for anchor in actions.values()}) == 2


def test_each_route_anchor_is_evidenced_by_its_route_and_composition(facts):
    for route, page in (('/owners/new', 'NewOwnerPage'),
                        ('/owners/:ownerId/edit', 'EditOwnerPage')):
        registration = _registration(_by_route(facts, 'OwnerEditor')[route])['registration']
        excerpts = [facts['evidence'][item]['excerpt'] for item in registration['evidence_ids']]
        assert any(f"path='{route}'" in excerpt for excerpt in excerpts)
        assert any(excerpt.startswith('<OwnerEditor') for excerpt in excerpts)
        assert any(facts['evidence'][item]['locator']['path'].endswith(f'/{page}.tsx')
                   for item in registration['evidence_ids'])


def test_each_route_anchor_reaches_the_shared_handler(facts):
    for anchor in _actions(facts, 'OwnerEditor'):
        trace = next(trace for trace in facts['traces'].values()
                     if trace['anchor_id'] == anchor['id'])
        names = {_name(facts, symbol) for symbol in trace['symbol_ids']}
        assert {'OwnerEditor.render', 'OwnerEditor.onSubmit'} <= names


def test_a_page_passed_literal_flag_pairs_the_conditional_label_with_its_route(facts):
    anchor = _by_route(facts, 'OwnerEditor')['/owners/new']
    registration = _registration(anchor)['registration']
    assert registration['label'] == 'Add Owner'
    assert anchor['operation']['name'] == 'Add Owner'
    assert registration['condition'] == 'owner.isNew'
    assert registration['resolution'] == 'resolved' and registration['reason'] is None
    excerpts = ' '.join(facts['evidence'][item]['excerpt']
                        for item in registration['evidence_ids'])
    assert 'isNew: true' in excerpts


def test_a_literal_object_without_the_flag_selects_the_other_branch(facts):
    registration = _registration(
        _by_route(facts, 'OwnerEditor')['/owners/:ownerId/edit'])['registration']
    assert registration['label'] == 'Update Owner'
    assert registration['condition'] == '!(owner.isNew)'
    assert registration['resolution'] == 'resolved'


def test_an_identifier_assigned_only_literals_is_a_label(facts):
    registration = _registration(_by_route(facts, 'PetEditor')['/pets/new'])['registration']
    assert registration['label'] == 'Add Pet'
    assert registration['condition'] == 'pet.isNew'
    assert registration['resolution'] == 'resolved'


def test_a_bare_jsx_flag_and_a_literal_flag_pair_function_component_labels(facts):
    actions = _by_route(facts, 'TagForm')
    assert _registration(actions['/tags/new'])['registration']['label'] == 'Create Tag'
    assert _registration(actions['/tags/:tagId/edit'])['registration']['label'] == 'Save Tag'


def test_a_runtime_flag_leaves_every_candidate_label_ambiguous(facts):
    anchor = _by_route(facts, 'PetEditor')['/pets/:petId/edit']
    registration = _registration(anchor)['registration']
    assert registration['label'] is None
    assert registration['resolution'] == 'ambiguous'
    assert anchor['resolution'] == 'ambiguous'
    assert anchor['operation']['name'] == 'unlabeled action'
    assert "'Add Pet', 'Update Pet'" in registration['reason']
    assert 'EditPetPage.render passes pet as `this.state.pet`, a runtime value' in (
        registration['reason'])
    assert registration['reason'] in _warnings(facts, 'UI_ACTION_LABEL_AMBIGUOUS')


def test_a_directly_routed_conditional_label_has_no_flag_and_stays_ambiguous(facts):
    registration = _registration(_by_route(facts, 'TagForm')['/tags/form'])['registration']
    assert registration['label'] is None
    assert registration['resolution'] == 'ambiguous'
    assert "one of 'Create Tag', 'Save Tag'" in registration['reason']
    assert 'renders this component itself' in registration['reason']


def test_a_runtime_label_is_an_explicit_unlabeled_gap(facts):
    [anchor] = _actions(facts, 'NotesPage')
    registration = _registration(anchor)['registration']
    assert anchor['operation']['name'] == 'unlabeled action'
    assert registration['label'] is None
    assert registration['resolution'] == 'unresolved'
    assert registration['reason'] == (
        'Visible action label on /notes is the runtime expression `this.state.saveLabel`; '
        'no literal text names this action.')
    assert registration['reason'] in _warnings(facts, 'UI_ACTION_LABEL_RUNTIME')
    # The gap is about the label only: the handler itself is resolved.
    assert registration['target'] == 'NotesPage.onSave'


def test_a_reassigned_identifier_is_not_a_literal_label(facts):
    [anchor] = _actions(facts, 'ArchivePage')
    registration = _registration(anchor)['registration']
    assert registration['label'] is None
    assert registration['resolution'] == 'unresolved'
    assert 'runtime expression `label`' in registration['reason']
    assert registration['reason'] in _warnings(facts, 'UI_ACTION_LABEL_RUNTIME')


def test_a_directly_routed_literal_action_is_unchanged(facts):
    [anchor] = _actions(facts, 'VisitEditor')
    representation = _registration(anchor)
    registration = representation['registration']
    assert representation['identity_key'].startswith('ui:client:action:/visits/new:onClick:')
    assert anchor['operation']['path'] == '/visits/new'
    assert registration['label'] == 'Add Visit'
    assert registration['condition'] is None
    assert registration['resolution'] == 'resolved'
    # Only the action's own span: no composition was needed to place it.
    assert len(registration['evidence_ids']) == 1


# Decision 4 through component state: the flag reaches the editor only along
# Promise.resolve(literal) -> Promise.all(...).then(results => ({...})) ->
# .then(model => this.setState(model)) -> <Editor {...this.state} />.
MODEL_ROUTES = """import * as React from 'react';
import { Route } from 'react-router';
import NewModelPage from './NewModelPage';
import BoundModelPage from './BoundModelPage';
import LoadedModelPage from './LoadedModelPage';
import ExtraStatePage from './ExtraStatePage';
import MutatedModelPage from './MutatedModelPage';
import UnknownModelPage from './UnknownModelPage';
import CatchModelPage from './CatchModelPage';
import UnguardedModelPage from './UnguardedModelPage';
import OpaqueModelPage from './OpaqueModelPage';

export default () => (
  <Route>
    <Route path='/models/new' component={NewModelPage} />
    <Route path='/models/bound' component={BoundModelPage} />
    <Route path='/models/:petId/edit' component={LoadedModelPage} />
    <Route path='/models/extra' component={ExtraStatePage} />
    <Route path='/models/mutated' component={MutatedModelPage} />
    <Route path='/models/unknown' component={UnknownModelPage} />
    <Route path='/models/catch' component={CatchModelPage} />
    <Route path='/models/unguarded' component={UnguardedModelPage} />
    <Route path='/models/opaque' component={OpaqueModelPage} />
  </Route>
);
"""

MODEL_EDITOR = """import * as React from 'react';
import { submitForm } from '../util';

export default class ModelEditor extends React.Component<any, any> {
  constructor(props) {
    super(props);
    this.onSubmit = this.onSubmit.bind(this);
    this.state = { editablePet: Object.assign({}, props.pet) };
  }

  onSubmit(event) {
    submitForm('PUT', '/api/owners/1/pets/1', {}, status => status);
  }

  render() {
    const { editablePet } = this.state;
    const formLabel = editablePet.isNew ? 'Add Pet' : 'Update Pet';
    return <button type='submit' onClick={this.onSubmit}>{formLabel}</button>;
  }
}
"""

CREATE_MODEL = """import { url } from '../util';

export default (ownerId: string, petLoaderPromise: Promise<any>): Promise<any> => {
  return Promise.all(
    [fetch(url('/api/pettypes')).then(response => response.json()),
     fetch(url('/api/owner/' + ownerId)).then(response => response.json()),
     petLoaderPromise,
    ]
  ).then(results => ({
    pettypes: results[0],
    owner: results[1],
    pet: results[2]
  }));
};
"""

# Its last return has the Promise.all shape, but an earlier one resolves to
# another object: no single model.
UNKNOWN_MODEL = """export default (ownerId: string, petLoaderPromise: Promise<any>): Promise<any> => {
  if (!ownerId) {
    return Promise.resolve({ pet: { isNew: false } });
  }
  return Promise.all([petLoaderPromise]).then(results => ({ pet: results[0] }));
};
"""

# A body this step does not model at all.
OPAQUE_MODEL = """export default (ownerId: string, petLoaderPromise: Promise<any>): Promise<any> =>
  petLoaderPromise.then(pet => ({ pet, ownerId }));
"""


def _model_page(name, body, pet='NEW_PET', load='createModel', extra=''):
    return f"""import * as React from 'react';
import ModelEditor from './ModelEditor';
import {load} from './{load}';

const {pet} = {{ id: null, isNew: true, name: '' }};
{extra}
export default class {name} extends React.Component<any, any> {{
{body}
  render() {{
    if (!this.state) {{
      return null;
    }}

    return <ModelEditor {{...this.state}} />;
  }}
}}
"""


_DID_MOUNT = """  componentDidMount() {
    createModel(this.props.params.ownerId, Promise.resolve(NEW_PET))
      .then(model => this.setState(model));
  }
"""

MODEL_CLIENT = {
    'client/src/models/routes.tsx': MODEL_ROUTES,
    'client/src/models/ModelEditor.tsx': MODEL_EDITOR,
    'client/src/models/createModel.ts': CREATE_MODEL,
    'client/src/models/unknownModel.ts': UNKNOWN_MODEL,
    'client/src/models/opaqueModel.ts': OPAQUE_MODEL,
    'client/src/models/OpaqueModelPage.tsx': _model_page('OpaqueModelPage', """  componentDidMount() {
    opaqueModel(this.props.params.ownerId, Promise.resolve(NEW_PET))
      .then(model => this.setState(model));
  }
""", load='opaqueModel'),
    'client/src/models/NewModelPage.tsx': _model_page('NewModelPage', _DID_MOUNT),
    'client/src/models/BoundModelPage.tsx': _model_page('BoundModelPage', """  componentDidMount() {
    createModel(this.props.params.ownerId, Promise.resolve(NEW_PET))
      .then(this.setState.bind(this));
  }
"""),
    'client/src/models/LoadedModelPage.tsx': _model_page('LoadedModelPage', """  componentDidMount() {
    const loadPetPromise = fetch('/api/pets/' + this.props.params.petId).then(response => response.json());
    createModel(this.props.params.ownerId, loadPetPromise)
      .then(model => this.setState(model));
  }
"""),
    'client/src/models/ExtraStatePage.tsx': _model_page('ExtraStatePage', _DID_MOUNT + """
  onReset() {
    this.setState({ pet: { isNew: false } });
  }
"""),
    'client/src/models/MutatedModelPage.tsx': _model_page(
        'MutatedModelPage', _DID_MOUNT, extra='NEW_PET.isNew = false;\n'),
    'client/src/models/UnknownModelPage.tsx': _model_page('UnknownModelPage', """  componentDidMount() {
    unknownModel(this.props.params.ownerId, Promise.resolve(NEW_PET))
      .then(model => this.setState(model));
  }
""", load='unknownModel'),
    'client/src/models/CatchModelPage.tsx': _model_page('CatchModelPage', """  componentDidMount() {
    createModel(this.props.params.ownerId, Promise.resolve(NEW_PET))
      .then(model => this.setState(model))
      .catch(() => this.setState({ pet: { isNew: false } }));
  }
"""),
    'client/src/models/UnguardedModelPage.tsx': _model_page('UnguardedModelPage', _DID_MOUNT).replace(
        """    if (!this.state) {
      return null;
    }
""", ''),
}


@pytest.fixture(scope='module')
def model_facts(tmp_path_factory):
    return _extract(tmp_path_factory.mktemp('route-actions-state'),
                    {**BACKEND, **CLIENT, **MODEL_CLIENT})


def _model_registration(model_facts, route):
    return _registration(_by_route(model_facts, 'ModelEditor')[route])['registration']


@pytest.mark.parametrize('route', ['/models/new', '/models/bound'])
def test_a_literal_resolved_into_state_and_spread_pairs_the_label(model_facts, route):
    anchor = _by_route(model_facts, 'ModelEditor')[route]
    registration = _registration(anchor)['registration']
    assert registration['label'] == 'Add Pet'
    assert anchor['operation']['name'] == 'Add Pet'
    assert registration['condition'] == 'editablePet.isNew'
    assert registration['resolution'] == 'resolved' and registration['reason'] is None
    excerpts = ' '.join(model_facts['evidence'][item]['excerpt']
                        for item in registration['evidence_ids'])
    for step in ('isNew: true', 'Promise.resolve(NEW_PET)', 'Promise.all(',
                 '{...this.state}', 'if (!this.state)'):
        assert step in excerpts


@pytest.mark.parametrize('route, why', [
    ('/models/:petId/edit', 'createModel() resolves pet from `fetch('),
    ('/models/extra', 'ExtraStatePage sets state in 2 places'),
    ('/models/mutated', 'NEW_PET is also used on line 6, so the object may be changed'),
    ('/models/unknown', 'unknownModel() has 2 return statements'),
    ('/models/opaque', 'opaqueModel() does not return Promise.all([...]).then('),
    ('/models/catch', 'CatchModelPage sets state in 2 places'),
    ('/models/unguarded', 'may render it before UnguardedModelPage sets state'),
])
def test_a_state_flag_not_fixed_by_every_step_stays_ambiguous(model_facts, route, why):
    anchor = _by_route(model_facts, 'ModelEditor')[route]
    registration = _registration(anchor)['registration']
    assert registration['label'] is None
    assert registration['resolution'] == 'ambiguous'
    assert anchor['operation']['name'] == 'unlabeled action'
    assert "'Add Pet', 'Update Pet'" in registration['reason']
    assert 'spreads this.state into the component, and' in registration['reason']
    assert why in registration['reason']
    assert registration['reason'] in _warnings(model_facts, 'UI_ACTION_LABEL_AMBIGUOUS')


def test_state_spread_leaves_the_props_passed_labels_unchanged(model_facts):
    owner = _by_route(model_facts, 'OwnerEditor')
    assert _registration(owner['/owners/new'])['registration']['label'] == 'Add Owner'
    assert _registration(owner['/owners/:ownerId/edit'])['registration']['label'] == 'Update Owner'
    assert _registration(_by_route(model_facts, 'PetEditor')['/pets/:petId/edit'])[
        'registration']['resolution'] == 'ambiguous'
