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
