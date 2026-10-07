"""OpenAPI model classes are built from the committed schema, one per schema.

openapi-generator-maven-plugin writes one Java class per object schema into
``modelPackage``, named ``<modelNamePrefix><Schema><modelNameSuffix>``, with a
bean getter and setter per property (``allOf`` parts included). The snapshot
never contains those classes, so the build adapter synthesizes them from the
plugin configuration and the schema. Accessor calls and overloads taking them
then resolve exactly; anything the configuration does not pin stays unresolved.
"""
import pytest

from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import DEFAULTS, validate_references

POM = """<project>
  <groupId>com.example</groupId>
  <artifactId>clinic</artifactId>
  <build><plugins>
    <plugin>
      <groupId>org.openapitools</groupId>
      <artifactId>openapi-generator-maven-plugin</artifactId>
      <executions><execution><configuration>
        <inputSpec>{spec}</inputSpec>
        {suffix}
        <modelPackage>com.example.dto</modelPackage>
        {extra}
      </configuration></execution></executions>
    </plugin>
  </plugins></build>
</project>
"""

SPEC = """openapi: 3.0.1
paths:
  /pets:
    post:
      operationId: addPet
      responses:
        "201":
          description: Created
components:
  schemas:
    PetFields:
      type: object
      properties:
        name:
          type: string
        birthDate:
          type: string
          format: date
        vaccinated:
          type: boolean
        tags:
          type: array
          items:
            type: string
        status:
          type: string
          enum: [available, sold]
    Pet:
      allOf:
        - $ref: '#/components/schemas/PetFields'
        - type: object
          properties:
            id:
              type: integer
              format: int64
"""

MAPPER = """package com.example.mapper;
import com.example.dto.PetDto;
import com.example.dto.PetFieldsDto;
public interface PetMapper {
  Object toPet(PetDto petDto);
  Object toPet(PetFieldsDto petFieldsDto);
}
"""

CONTROLLER = """package com.example.web;
import com.example.dto.*;
import com.example.mapper.PetMapper;
public class PetController {
  private PetMapper mapper;
  public void add(PetDto petDto) { mapper.toPet(petDto); }
  public void addFields(PetFieldsDto fields) { mapper.toPet(fields); }
  public String name(PetFieldsDto fields) { return fields.getName(); }
  public void rename(PetDto pet) { pet.setName("Leo"); }
  public Long id(PetDto pet) { return pet.getId(); }
  public void missing(PetDto pet) { pet.getOwner(); }
}
"""

SPEC_PATH = 'src/main/resources/openapi.yml'


def _facts(root, spec='${project.basedir}/src/main/resources/openapi.yml',
           suffix='<modelNameSuffix>Dto</modelNameSuffix>', extra=''):
    files = {
        'pom.xml': POM.format(spec=spec, suffix=suffix, extra=extra),
        SPEC_PATH: SPEC,
        'src/main/java/com/example/mapper/PetMapper.java': MAPPER,
        'src/main/java/com/example/web/PetController.java': CONTROLLER,
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, _ = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    return facts


@pytest.fixture(scope='module')
def facts(tmp_path_factory):
    return _facts(tmp_path_factory.mktemp('models'))


def _generated(facts, kind=None):
    return {symbol['qualified_name'].split('generated-model:', 1)[1]: symbol
            for symbol in facts['symbols'].values()
            if 'generated-model:' in symbol['qualified_name']
            and (kind is None or symbol['kind'] == kind)}


def _call(facts, method, name):
    [edge] = [edge for edge in facts['edges'].values() if edge['kind'] == 'calls'
              and facts['symbols'][edge['from_ref']['id']]['qualified_name']
              .split('::')[-1].startswith(f'PetController.{method}(')
              and facts['evidence'][edge['evidence_ids'][0]]['excerpt'].split('(')[0]
              .endswith('.' + name)]
    return edge


def _target(facts, edge):
    assert edge['resolution'] == 'resolved', edge['reason']
    return facts['symbols'][edge['to_ref']['id']]['qualified_name'].split('::')[-1]


def _evidence(facts, symbol):
    return {facts['evidence'][evidence_id]['locator']['path']:
            facts['evidence'][evidence_id]['excerpt'] for evidence_id in symbol['evidence_ids']}


def test_one_type_per_schema_in_the_model_package_with_the_suffix(facts):
    assert sorted(_generated(facts, 'type')) == ['com.example.dto.PetDto',
                                                 'com.example.dto.PetFieldsDto']
    assert {symbol['file'] for symbol in _generated(facts).values()} == {'pom.xml'}


def test_bean_accessors_include_allof_properties_with_mapped_types(facts):
    accessors = {name.split('Dto.', 1)[1] for name in _generated(facts, 'method')
                 if name.startswith('com.example.dto.PetDto.')}
    assert accessors == {
        'getName()', 'setName(String)',
        'getBirthDate()', 'setBirthDate(java.time.LocalDate)',
        # openapi-generator's Java default boolean getter prefix is "get".
        'getVaccinated()', 'setVaccinated(Boolean)',
        'getTags()', 'setTags(java.util.List<String>)',
        # An inline enum becomes a generator-named inner type: left unknown.
        'getStatus()', 'setStatus(unknown)',
        'getId()', 'setId(Long)',
    }
    fields = {name.split('Dto.', 1)[1] for name in _generated(facts, 'method')
              if name.startswith('com.example.dto.PetFieldsDto.')}
    assert 'getId()' not in fields and 'getName()' in fields


def test_accessor_calls_on_generated_dtos_resolve(facts):
    assert _target(facts, _call(facts, 'name', 'getName')) == \
        'generated-model:com.example.dto.PetFieldsDto.getName()'
    assert _target(facts, _call(facts, 'rename', 'setName')) == \
        'generated-model:com.example.dto.PetDto.setName(String)'
    assert _target(facts, _call(facts, 'id', 'getId')) == \
        'generated-model:com.example.dto.PetDto.getId()'


def test_a_property_the_schema_does_not_declare_stays_unresolved(facts):
    edge = _call(facts, 'missing', 'getOwner')
    assert edge['resolution'] == 'unresolved' and edge['to_ref'] is None


@pytest.mark.parametrize('method, argument', [('add', 'PetDto'), ('addFields', 'PetFieldsDto')])
def test_overloads_taking_generated_dtos_resolve_exactly(facts, method, argument):
    assert _target(facts, _call(facts, method, 'toPet')) == f'PetMapper.toPet({argument})'


def test_type_and_accessor_evidence_cite_the_plugin_and_the_schema(facts):
    pet = _evidence(facts, _generated(facts, 'type')['com.example.dto.PetDto'])
    assert set(pet) == {'pom.xml', SPEC_PATH}
    assert pet['pom.xml'].startswith('<plugin>') and pet['pom.xml'].endswith('</plugin>')
    assert pet[SPEC_PATH].startswith('Pet:\n') and pet[SPEC_PATH].endswith('format: int64')
    # An allOf property is evidenced where it is declared: in PetFields.
    name = _evidence(facts, _generated(facts)['com.example.dto.PetDto.getName()'])
    assert name[SPEC_PATH] == 'name:\n          type: string'
    assert 'openapi-generator-maven-plugin' in name['pom.xml']


def test_the_type_declares_its_accessors(facts):
    types = _generated(facts, 'type')
    declared = sorted(facts['symbols'][edge['to_ref']['id']]['qualified_name'].split('Dto.', 1)[1]
                      for edge in facts['edges'].values() if edge['kind'] == 'declares'
                      and edge['from_ref']['id'] == types['com.example.dto.PetFieldsDto']['id'])
    assert declared == sorted(['getName()', 'setName(String)', 'getBirthDate()',
                               'setBirthDate(java.time.LocalDate)', 'getVaccinated()',
                               'setVaccinated(Boolean)', 'getTags()',
                               'setTags(java.util.List<String>)', 'getStatus()',
                               'setStatus(unknown)'])


def test_a_non_literal_input_spec_synthesizes_nothing(tmp_path):
    facts = _facts(tmp_path, spec='${spec.directory}/openapi.yml')
    assert not _generated(facts)
    [edge] = [edge for edge in facts['edges'].values() if edge['kind'] == 'accepts_type'
              and 'PetController.name(' in facts['symbols'][edge['from_ref']['id']]['qualified_name']]
    assert edge['resolution'] == 'unresolved'
    assert 'could not be matched' in edge['reason']
    assert _call(facts, 'name', 'getName')['resolution'] == 'unresolved'


def test_without_the_suffix_the_dto_names_are_not_generated(tmp_path):
    facts = _facts(tmp_path, suffix='')
    assert sorted(_generated(facts, 'type')) == ['com.example.dto.Pet',
                                                 'com.example.dto.PetFields']
    assert _call(facts, 'name', 'getName')['resolution'] == 'unresolved'
    assert _call(facts, 'add', 'toPet')['resolution'] != 'resolved'


def test_a_type_mapping_withholds_synthesis(tmp_path):
    facts = _facts(tmp_path, extra='<typeMappings>Pet=com.example.Custom</typeMappings>')
    assert not _generated(facts)
