"""Extract-stage call resolution: exact Java overloads and TSX callback props.

Both only add proof that is in the source. An overload resolves when the
argument's static type is exactly one candidate's parameter type; a callback
prop reaches the handlers every rendering of the component passes.
"""
import pytest

from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import DEFAULTS, validate_references


def _extract(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, _ = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    return facts


def _name(facts, symbol_id):
    return facts['symbols'][symbol_id]['qualified_name'].split('::')[-1]


def _call(facts, caller, excerpt):
    [edge] = [edge for edge in facts['edges'].values()
              if edge['kind'] == 'calls' and _name(facts, edge['from_ref']['id']).startswith(caller)
              and excerpt in facts['evidence'][edge['evidence_ids'][0]]['excerpt']]
    return edge


# ── Java overloads ───────────────────────────────────────────────────────

MAPPER = """package com.example.mapper;
import com.example.dto.OwnerDto;
import com.example.dto.OwnerFieldsDto;
public interface OwnerMapper {
  Owner toOwner(OwnerDto dto);
  Owner toOwner(OwnerFieldsDto dto);
  Owner toOwner(OwnerFieldsDto[] dtos);
}
"""


def _controller(parameter, argument, imports='import com.example.dto.*;\n'):
    return f"""package com.example.web;
import com.example.mapper.OwnerMapper;
{imports}public class Controller {{
  private OwnerMapper mapper;
  public void create({parameter}) {{ mapper.toOwner({argument}); }}
}}
"""


def test_an_exact_reference_type_selects_its_overload(tmp_path):
    facts = _extract(tmp_path, {
        'src/com/example/mapper/OwnerMapper.java': MAPPER,
        'src/com/example/web/Controller.java': _controller(
            'OwnerFieldsDto fields', 'fields', 'import com.example.dto.OwnerFieldsDto;\n')})
    edge = _call(facts, 'Controller.create', 'toOwner')
    assert edge['resolution'] == 'resolved'
    assert _name(facts, edge['to_ref']['id']) == 'OwnerMapper.toOwner(OwnerFieldsDto)'


def test_array_depth_is_part_of_the_exact_type(tmp_path):
    facts = _extract(tmp_path, {
        'src/com/example/mapper/OwnerMapper.java': MAPPER,
        'src/com/example/web/Controller.java': _controller(
            'OwnerFieldsDto[] fields', 'fields', 'import com.example.dto.OwnerFieldsDto;\n')})
    edge = _call(facts, 'Controller.create', 'toOwner')
    assert _name(facts, edge['to_ref']['id']) == 'OwnerMapper.toOwner(OwnerFieldsDto[])'


def test_equal_simple_names_from_different_packages_stay_ambiguous(tmp_path):
    facts = _extract(tmp_path, {
        'src/com/example/mapper/OwnerMapper.java': MAPPER,
        'src/com/example/web/Controller.java': _controller(
            'OwnerFieldsDto fields', 'fields', 'import com.other.OwnerFieldsDto;\n')})
    edge = _call(facts, 'Controller.create', 'toOwner')
    assert edge['resolution'] == 'ambiguous'


def test_an_argument_of_unknown_type_stays_ambiguous(tmp_path):
    facts = _extract(tmp_path, {
        'src/com/example/mapper/OwnerMapper.java': MAPPER,
        'src/com/example/web/Controller.java': _controller(
            'java.util.List<OwnerFieldsDto> all', 'all.get(0)')})
    edge = _call(facts, 'Controller.create', 'toOwner')
    assert edge['resolution'] == 'ambiguous'
    assert sorted(_name(facts, target) for target in edge['candidate_target_ids']) == [
        'OwnerMapper.toOwner(OwnerDto)', 'OwnerMapper.toOwner(OwnerFieldsDto)']


GENERATOR = """<project><groupId>com.example</groupId><artifactId>app</artifactId>
<build><plugins><plugin>
  <groupId>org.openapitools</groupId>
  <artifactId>openapi-generator-maven-plugin</artifactId>
  <executions><execution><configuration>
    <modelNameSuffix>Dto</modelNameSuffix>
    <apiPackage>com.example.api</apiPackage>
    <modelPackage>com.example.dto</modelPackage>
  </configuration></execution></executions>
</plugin></plugins></build></project>
"""


def test_a_wildcard_imported_generated_dto_selects_its_overload(tmp_path):
    facts = _extract(tmp_path, {
        'pom.xml': GENERATOR,
        'src/com/example/mapper/OwnerMapper.java': MAPPER,
        'src/com/example/web/Controller.java': _controller('OwnerFieldsDto fields', 'fields')})
    edge = _call(facts, 'Controller.create', 'toOwner')
    assert edge['resolution'] == 'resolved'
    assert _name(facts, edge['to_ref']['id']) == 'OwnerMapper.toOwner(OwnerFieldsDto)'


# ── TSX callback props ───────────────────────────────────────────────────

FIELD = """import * as React from 'react';

export default ({name, onChange}: {name: string, onChange: any}) => {
  const handleOnChange = event => {
    onChange(name, event.target.value);
  };
  return <input name={name} onChange={handleOnChange} />;
};
"""


def _page(name, attribute="onChange={this.onFieldChange}", extra=''):
    return f"""import * as React from 'react';
import Field from './Field';

export default class {name} extends React.Component<any, any> {{
  onFieldChange(name, value) {{
    this.setState({{ [name]: value }});
  }}

  render() {{
    {extra}
    return <Field name='a' {attribute} />;
  }}
}}
"""


def _callback(facts):
    return _call(facts, 'Field.default.handleOnChange', 'onChange(')


def test_a_callback_prop_rendered_once_resolves_to_its_handler(tmp_path):
    facts = _extract(tmp_path, {'Field.tsx': FIELD, 'PageA.tsx': _page('PageA')})
    edge = _callback(facts)
    assert edge['resolution'] == 'resolved'
    assert _name(facts, edge['to_ref']['id']) == 'PageA.onFieldChange'


def test_a_callback_prop_rendered_by_several_callers_is_bounded_ambiguous(tmp_path):
    facts = _extract(tmp_path, {'Field.tsx': FIELD, 'PageA.tsx': _page('PageA'),
                                'PageB.tsx': _page('PageB')})
    edge = _callback(facts)
    assert edge['resolution'] == 'ambiguous'
    assert sorted(_name(facts, target) for target in edge['candidate_target_ids']) == [
        'PageA.onFieldChange', 'PageB.onFieldChange']


@pytest.mark.parametrize('second', [
    _page('PageB', attribute='onChange={(n, v) => this.setState({})}'),
    _page('PageB', attribute='{...this.props}'),
    _page('PageB', attribute=''),
    _page('PageB', extra='const Alias = Field;'),
])
def test_an_unknowable_rendering_keeps_the_callback_unresolved(tmp_path, second):
    facts = _extract(tmp_path, {'Field.tsx': FIELD, 'PageA.tsx': _page('PageA'),
                                'PageB.tsx': second})
    edge = _callback(facts)
    assert edge['resolution'] == 'unresolved' and edge['to_ref'] is None


def test_a_local_declaration_shadows_the_prop(tmp_path):
    shadowed = FIELD.replace('  const handleOnChange',
                             '  const onChange = (n, v) => v;\n  const handleOnChange')
    facts = _extract(tmp_path, {'Field.tsx': shadowed, 'PageA.tsx': _page('PageA')})
    edge = _callback(facts)
    assert not (edge['to_ref'] and _name(facts, edge['to_ref']['id']) == 'PageA.onFieldChange')


def test_test_renderings_do_not_widen_a_production_callback(tmp_path):
    test_page = """import * as React from 'react';
import Field from '../Field';
describe('Field', () => {
  it('renders', () => { const r = <Field name='a' onChange={jest.fn()} />; });
});
"""
    facts = _extract(tmp_path, {'Field.tsx': FIELD, 'PageA.tsx': _page('PageA'),
                                '__tests__/Field.test.tsx': test_page})
    edge = _callback(facts)
    assert edge['resolution'] == 'resolved'
    assert _name(facts, edge['to_ref']['id']) == 'PageA.onFieldChange'


# ── Review regressions ───────────────────────────────────────────────────

def test_a_conversion_never_outranks_another_candidate(tmp_path):
    # javac's strict phase picks f(Integer, Bar); f(int, Foo) needs unboxing.
    facts = _extract(tmp_path, {
        'src/com/ex/Bar.java': 'package com.ex;\npublic class Bar {}\n',
        'src/com/ex/Foo.java': 'package com.ex;\npublic class Foo extends Bar {}\n',
        'src/com/ex/Svc.java': 'package com.ex;\npublic class Svc {\n'
                               '  public void f(int a, Foo b) {}\n'
                               '  public void f(Integer a, Bar b) {}\n}\n',
        'src/com/ex/Caller.java': 'package com.ex;\npublic class Caller {\n  private Svc svc;\n'
                                  '  public void run(Integer n, Foo foo) { svc.f(n, foo); }\n}\n'})
    edge = _call(facts, 'Caller.run', 'svc.f(')
    assert edge['resolution'] == 'ambiguous'


def test_a_bare_handler_name_never_means_a_class_method(tmp_path):
    page = _page('PageA', attribute='onChange={onFieldChange}').replace(
        "import Field from './Field';",
        "import Field from './Field';\nimport { onFieldChange } from './handlers';")
    facts = _extract(tmp_path, {
        'Field.tsx': FIELD, 'PageA.tsx': page,
        'handlers.ts': 'export function onFieldChange(name, value) { return value; }\n'})
    edge = _callback(facts)
    assert not (edge['to_ref'] and _name(facts, edge['to_ref']['id']) == 'PageA.onFieldChange')


@pytest.mark.parametrize('declaration', [
    'const { onChange } = useForm();', 'let [onChange] = useState(null);',
    'const items = list.map(onChange => onChange);'])
def test_destructuring_and_parameters_shadow_the_prop(tmp_path, declaration):
    shadowed = FIELD.replace('  const handleOnChange', f'  {declaration}\n  const handleOnChange')
    facts = _extract(tmp_path, {'Field.tsx': shadowed, 'PageA.tsx': _page('PageA')})
    edge = _callback(facts)
    assert not (edge['to_ref'] and _name(facts, edge['to_ref']['id']) == 'PageA.onFieldChange')


def test_a_nested_element_inside_an_attribute_keeps_its_own_props(tmp_path):
    page = _page('PageA', attribute=(
        "footer={<Field name='b' onChange={this.onFieldChange} />} onChange={this.other}"
    )).replace('  render() {', '  other(name, value) {\n    return value;\n  }\n\n  render() {')
    facts = _extract(tmp_path, {'Field.tsx': FIELD, 'PageA.tsx': page})
    edge = _callback(facts)
    assert edge['resolution'] == 'ambiguous'
    assert sorted(_name(facts, target) for target in edge['candidate_target_ids']) == [
        'PageA.onFieldChange', 'PageA.other']


# ── Java local declarations and implicit/on-demand imports ───────────────

ENTITY = """package com.example.model;
public class BaseEntity { public Integer getId() { return null; } }
"""
PET = 'package com.example.model;\npublic class Pet extends BaseEntity {}\n'
VET = 'package com.example.model;\npublic class Vet extends BaseEntity { public String getName() { return null; } }\n'


def _service(body, imports='import com.example.model.*;\nimport java.util.*;\n'):
    return {
        'src/com/example/model/BaseEntity.java': ENTITY,
        'src/com/example/model/Pet.java': PET,
        'src/com/example/model/Vet.java': VET,
        'src/com/example/service/Service.java': (
            f'package com.example.service;\n{imports}public class Service {{\n'
            f'  public void run(List<Pet> pets, java.io.InputStream input) {{\n{body}\n  }}\n}}\n'),
    }


def _calls(facts, name):
    return [edge for edge in facts['edges'].values()
            if edge['kind'] == 'calls' and _name(facts, edge['from_ref']['id']).startswith('Service.run')
            and f'.{name}(' in facts['evidence'][edge['evidence_ids'][0]]['excerpt']]


@pytest.mark.parametrize('declaration', [
    'for (Pet pet : pets) { pet.getId(); }',
    'for (final Pet pet : pets) { pet.getId(); }',
    'try (Pet pet = load()) { pet.getId(); }',
])
def test_loop_and_resource_variables_have_their_declared_type(tmp_path, declaration):
    facts = _extract(tmp_path, _service(declaration))
    [edge] = _calls(facts, 'getId')
    # getId is inherited from BaseEntity through Pet's heritage.
    assert edge['resolution'] == 'resolved'
    assert _name(facts, edge['to_ref']['id']) == 'BaseEntity.getId()'


def test_a_name_declared_with_two_types_is_not_guessed(tmp_path):
    facts = _extract(tmp_path, _service(
        'if (pets.isEmpty()) { Pet item = null; item.getId(); }\n'
        'else { Vet item = null; item.getName(); }'))
    for name in ('getId', 'getName'):
        [edge] = _calls(facts, name)
        assert edge['resolution'] != 'resolved' and edge['to_ref'] is None


def test_catch_parameters_are_typed_and_multi_catch_is_unknown(tmp_path):
    facts = _extract(tmp_path, _service(
        'try { } catch (IllegalStateException e) { e.getMessage(); }\n'
        'try { } catch (IllegalStateException | IllegalArgumentException both) { both.getCause(); }'))
    [single] = _calls(facts, 'getMessage')
    assert single['resolution'] == 'unresolved' and single['to_ref']['kind'] == 'resource'
    assert facts['resources'][single['to_ref']['id']]['provider'] == 'type:java.lang.IllegalStateException'
    [multi] = _calls(facts, 'getCause')
    assert multi['to_ref'] is None


def test_java_lang_types_are_implicitly_imported_library_types(tmp_path):
    facts = _extract(tmp_path, _service('Number key = null; key.intValue();'))
    [edge] = _calls(facts, 'intValue')
    assert facts['resources'][edge['to_ref']['id']]['provider'] == 'type:java.lang.Number'


def test_a_same_package_type_shadows_java_lang(tmp_path):
    files = _service('Number key = null; key.intValue();')
    files['src/com/example/service/Number.java'] = (
        'package com.example.service;\npublic class Number { public int intValue() { return 0; } }\n')
    facts = _extract(tmp_path, files)
    [edge] = _calls(facts, 'intValue')
    assert _name(facts, edge['to_ref']['id']) == 'Number.intValue()'


def test_a_type_only_a_library_wildcard_can_supply_is_external(tmp_path):
    facts = _extract(tmp_path, _service(
        'Map<String, Object> params = new HashMap<>(); params.put("id", 1);',
        imports='import com.example.model.Pet;\nimport java.util.*;\n'))
    [edge] = _calls(facts, 'put')
    assert edge['to_ref'] and edge['to_ref']['kind'] == 'resource'
    assert facts['resources'][edge['to_ref']['id']]['provider'] == 'type:java.util.Map'


def test_several_library_wildcards_leave_the_provider_unnamed(tmp_path):
    facts = _extract(tmp_path, _service(
        'Map<String, Object> params = null; params.put("id", 1);',
        imports='import com.example.model.Pet;\nimport java.util.*;\nimport java.util.concurrent.*;\n'))
    [edge] = _calls(facts, 'put')
    # External; each on-demand package is a candidate provider.
    assert edge['to_ref']['kind'] == 'resource'
    assert facts['resources'][edge['to_ref']['id']]['provider'] == (
        'type:java.util.Map|java.util.concurrent.Map')


@pytest.mark.parametrize('body', [
    'pets.forEach(item -> item.getName());',          # untyped lambda parameter
    'pets.iterator().next().getName();',              # receiver is an expression
    'LIMIT.getName();',                               # an ALL_CAPS constant
])
def test_only_a_type_name_can_come_from_a_wildcard(tmp_path, body):
    facts = _extract(tmp_path, _service(body, imports='import com.example.model.Pet;\nimport java.util.*;\n'))
    [edge] = [edge for edge in _calls(facts, 'getName')
              if 'forEach' not in facts['evidence'][edge['evidence_ids'][0]]['excerpt']]
    assert edge['to_ref'] is None


def test_a_local_wildcard_keeps_an_undeclared_name_unresolved(tmp_path):
    # com.example.model is the project's; a missing type there is a gap.
    facts = _extract(tmp_path, _service('Owner owner = null; owner.getName();',
                                        imports='import com.example.model.*;\n'))
    [edge] = _calls(facts, 'getName')
    assert edge['resolution'] == 'unresolved' and edge['to_ref'] is None



def test_a_library_wildcard_beside_a_local_one_is_not_enough(tmp_path):
    # Map could still be a project type the snapshot lacks in com.example.model.
    facts = _extract(tmp_path, _service('Map<String, Object> params = null; params.put("id", 1);'))
    [edge] = _calls(facts, 'put')
    assert edge['resolution'] == 'unresolved' and edge['to_ref'] is None


# ── Chained calls: declared and catalogued return types ──────────────────

REPOSITORY = """package com.example.service;
import jakarta.persistence.EntityManager;
import org.springframework.web.util.UriComponentsBuilder;
import com.example.model.*;
import java.util.List;
public class Repo {
  private EntityManager em;
  public void run(Pet pet, Vet vet, List<Vet> vets) {
    this.em.createQuery("DELETE FROM Pet").executeUpdate();
    this.em.createQuery("SELECT p FROM Pet p", Pet.class).getResultList();
    this.em.createQuery("SELECT p FROM Pet p", Pet.class).getSingleResult().getId();
    UriComponentsBuilder.newInstance().path("/pets/{id}").buildAndExpand(1).toUri();
    pet.getOwner().getName();
    pet.getId().toString().trim();
    pet.getOwner().equals(vet);
    vets.stream().map(item -> item).filter(item -> true);
    pet.unknown().getName();
  }
}
"""
OWNED = {
    'src/com/example/model/BaseEntity.java': ENTITY,
    'src/com/example/model/Owner.java': ('package com.example.model;\n'
        'public class Owner extends BaseEntity { public String getName() { return null; } }\n'),
    'src/com/example/model/Pet.java': ('package com.example.model;\n'
        'public class Pet extends BaseEntity { public Owner getOwner() { return null; } }\n'),
    'src/com/example/model/Vet.java': VET,
    'src/com/example/service/Repo.java': REPOSITORY,
}


@pytest.fixture(scope='module')
def chains(tmp_path_factory):
    return _extract(tmp_path_factory.mktemp('chains'), OWNED)


def _chained(facts, name, excerpt=''):
    return [edge for edge in facts['edges'].values() if edge['kind'] == 'calls'
            and _name(facts, edge['from_ref']['id']).startswith('Repo.run')
            and facts['evidence'][edge['evidence_ids'][0]]['excerpt'].endswith(f'{name}()' if not excerpt else excerpt)]


def _provider(facts, edge):
    return facts['resources'][edge['to_ref']['id']]['provider'] if edge['to_ref'] else None


@pytest.mark.parametrize('name, provider', [
    ('executeUpdate', 'type:jakarta.persistence.Query'),
    ('getResultList', 'type:jakarta.persistence.TypedQuery'),
    ('toUri', 'type:org.springframework.web.util.UriComponents'),
    ('trim', 'type:java.lang.String'),
])
def test_a_catalogued_library_return_types_the_next_call(chains, name, provider):
    [edge] = _chained(chains, name)
    assert _provider(chains, edge) == provider


def test_a_project_method_return_types_the_next_call(chains):
    [edge] = _chained(chains, 'getName', 'pet.getOwner().getName()')
    assert edge['resolution'] == 'resolved'
    assert _name(chains, edge['to_ref']['id']) == 'Owner.getName()'


def test_object_members_are_inherited_by_every_class(chains):
    [edge] = _chained(chains, 'equals', 'pet.getOwner().equals(vet)')
    assert _provider(chains, edge) == 'type:java.lang.Object'


def test_a_raw_generic_library_type_keeps_the_chain_typed(chains):
    [edge] = _chained(chains, 'filter', 'vets.stream().map(item -> item).filter(item -> true)')
    assert _provider(chains, edge) == 'type:java.util.stream.Stream'


@pytest.mark.parametrize('name, excerpt', [
    # TypedQuery<X>.getSingleResult() returns a type parameter: not catalogued.
    ('getId', 'getSingleResult().getId()'),
    # An undeclared project method has no return type to follow.
    ('getName', 'pet.unknown().getName()'),
])
def test_an_unknown_return_type_ends_the_chain_as_a_gap(chains, name, excerpt):
    [edge] = _chained(chains, name, excerpt)
    assert edge['resolution'] == 'unresolved' and edge['to_ref'] is None


def test_the_library_signature_catalog_is_well_formed():
    import json
    import re
    from pathlib import Path
    catalog = json.loads((Path(__file__).parents[1] / 'lib/context/data/library_signatures.json').read_text())
    primitives = {'void', 'boolean', 'byte', 'char', 'short', 'int', 'long', 'float', 'double'}
    for owner, methods in catalog['java'].items():
        assert re.fullmatch(r'[a-z]\w*(\.\w+)+', owner), owner
        for key, returned in methods.items():
            assert re.fullmatch(r'\w+/(\d+|\*)', key), (owner, key)
            # Qualified or primitive: never a type parameter or a simple name.
            assert returned in primitives or re.fullmatch(r'[a-z]\w*(\.\w+)+', returned), (owner, key)
