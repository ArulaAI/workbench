"""Generated DTOs resolve to the model the generator writes from a committed schema.

A Maven OpenAPI generator writes model classes at build time; the snapshot
never contains them. When the configured model package, affixes and a literal
input spec map a name onto a committed schema exactly, the class is built from
that schema and a relation to it resolves; its symbol cites the generator
configuration and the schema. A generated name with no matching schema stays
unresolved, its reason naming the generated type. Nothing is invented.
"""
import pytest

from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import DEFAULTS, validate_references

GENERATOR = """<project>
  <groupId>com.example</groupId>
  <artifactId>clinic</artifactId>
  <build><plugins>
    <plugin>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-maven-plugin</artifactId>
    </plugin>
    <plugin>
      <groupId>org.openapitools</groupId>
      <artifactId>openapi-generator-maven-plugin</artifactId>
      <executions><execution><configuration>
        <inputSpec>{spec}</inputSpec>
        {suffix}
        <apiPackage>com.example.api</apiPackage>
        <modelPackage>com.example.dto</modelPackage>
        <configOptions><interfaceOnly>true</interfaceOnly></configOptions>
      </configuration></execution></executions>
    </plugin>
  </plugins></build>
</project>
"""

SPEC = """openapi: 3.0.1
paths:
  /owners:
    post:
      operationId: addOwner
      responses:
        "201":
          description: Created
components:
  schemas:
    OwnerFields:
      type: object
      properties:
        firstName:
          type: string
"""

CONTROLLER = """package com.example.web;
import com.example.dto.*;
import com.example.dto.PetDto;
import com.example.domain.Missing;
import com.example.domain.Owner;
public class OwnerController {
  public OwnerDto create(OwnerFieldsDto fields) { return null; }
  public void pet(PetDto pet) { }
  public void missing(Missing missing) { }
  public void other(Thing thing) { }
  public void local(Owner owner) { }
}
"""

OWNER = 'package com.example.domain;\npublic class Owner { }\n'


def _facts(root, spec='${project.basedir}/src/main/resources/openapi.yml',
           suffix='<modelNameSuffix>Dto</modelNameSuffix>'):
    files = {
        'pom.xml': GENERATOR.format(spec=spec, suffix=suffix),
        'src/main/resources/openapi.yml': SPEC,
        'src/main/java/com/example/web/OwnerController.java': CONTROLLER,
        'src/main/java/com/example/domain/Owner.java': OWNER,
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
    return _facts(tmp_path_factory.mktemp('generated'))


def _edge(facts, method, kind):
    [edge] = [edge for edge in facts['edges'].values() if edge['kind'] == kind
              and facts['symbols'][edge['from_ref']['id']]['qualified_name']
              .split('::')[-1].startswith(f'OwnerController.{method}(')]
    return edge


def _evidence(facts, edge):
    return {facts['evidence'][evidence_id]['locator']['path']: facts['evidence'][evidence_id]
            for evidence_id in edge['evidence_ids']}


def _target(facts, edge):
    return facts['symbols'][edge['to_ref']['id']]


def test_generated_dto_with_a_matching_schema_resolves_to_the_generated_type(facts):
    edge = _edge(facts, 'create', 'accepts_type')
    assert edge['resolution'] == 'resolved' and edge['reason'] is None
    target = _target(facts, edge)
    assert target['kind'] == 'type'
    assert target['qualified_name'] == 'pom.xml::generated-model:com.example.dto.OwnerFieldsDto'


def test_the_generated_type_cites_the_generator_plugin_and_the_matching_schema(facts):
    target = _target(facts, _edge(facts, 'create', 'accepts_type'))
    evidence = {facts['evidence'][evidence_id]['locator']['path']: facts['evidence'][evidence_id]
                for evidence_id in target['evidence_ids']}
    assert set(evidence) == {'pom.xml', 'src/main/resources/openapi.yml'}
    plugin = evidence['pom.xml']['excerpt']
    assert plugin.startswith('<plugin>') and plugin.endswith('</plugin>')
    assert 'openapi-generator-maven-plugin' in plugin
    assert 'spring-boot-maven-plugin' not in plugin
    schema = evidence['src/main/resources/openapi.yml']['excerpt']
    assert schema.startswith('OwnerFields:') and schema.endswith('type: string')


@pytest.mark.parametrize('method, kind, name, qualified', [
    ('create', 'returns_type', 'OwnerDto', 'com.example.dto.OwnerDto'),
    ('pet', 'accepts_type', 'PetDto', 'com.example.dto.PetDto'),
])
def test_generated_dto_without_a_matching_schema_invents_no_schema_evidence(
        facts, method, kind, name, qualified):
    edge = _edge(facts, method, kind)
    assert edge['resolution'] == 'unresolved'
    assert edge['reason'] == (
        f'Java {kind} target {name} is the generated DTO {qualified}, which '
        'openapi-generator-maven-plugin produces at build time from an OpenAPI schema '
        'that could not be matched; its declaration is unavailable at analysis time.')
    assert 'src/main/resources/openapi.yml' not in _evidence(facts, edge)
    assert 'pom.xml' in _evidence(facts, edge)


def test_only_the_schema_backed_dto_and_its_accessors_are_created(facts):
    dto = [symbol for symbol in facts['symbols'].values()
           if 'Dto' in symbol['qualified_name'].rsplit('::', 1)[-1].split('(')[0]
           or symbol['file'].endswith('Dto.java')]
    assert sorted(symbol['qualified_name'].split('::', 1)[1] for symbol in dto) == [
        'generated-model:com.example.dto.OwnerFieldsDto',
        'generated-model:com.example.dto.OwnerFieldsDto.getFirstName()',
        'generated-model:com.example.dto.OwnerFieldsDto.setFirstName(String)',
    ]
    assert {symbol['file'] for symbol in dto} == {'pom.xml'}
    assert not [resource for resource in facts['resources'].values()
                if 'Dto' in resource['name']]
    assert not [anchor for anchor in facts['anchors'].values()
                if 'Dto' in (anchor['operation'].get('name') or '')]


@pytest.mark.parametrize('method, name', [('missing', 'Missing'), ('other', 'Thing')])
def test_ordinary_missing_types_are_unchanged(facts, method, name):
    edge = _edge(facts, method, 'accepts_type')
    assert edge['resolution'] == 'unresolved'
    assert edge['reason'] == f'Java accepts_type target {name} is unresolved.'
    assert set(_evidence(facts, edge)) == {'src/main/java/com/example/web/OwnerController.java'}


def test_declared_project_types_still_resolve(facts):
    edge = _edge(facts, 'local', 'accepts_type')
    assert edge['resolution'] == 'resolved'
    assert facts['symbols'][edge['to_ref']['id']]['qualified_name'].endswith('Owner')


def test_wildcard_dto_needs_the_configured_affix_to_be_recognized(tmp_path):
    facts = _facts(tmp_path, suffix='')
    edge = _edge(facts, 'create', 'accepts_type')
    assert edge['reason'] == 'Java accepts_type target OwnerFieldsDto is unresolved.'
    # Without the suffix the generator names the schema's class OwnerFields.
    assert [symbol['qualified_name'] for symbol in facts['symbols'].values()
            if symbol['kind'] == 'type' and 'generated-model:' in symbol['qualified_name']] == [
        'pom.xml::generated-model:com.example.dto.OwnerFields']
    # An explicit import from the model package is still generated.
    assert 'generated DTO com.example.dto.PetDto' in _edge(facts, 'pet', 'accepts_type')['reason']


def test_a_non_literal_input_spec_establishes_no_schema(tmp_path):
    facts = _facts(tmp_path, spec='${spec.directory}/openapi.yml')
    edge = _edge(facts, 'create', 'accepts_type')
    assert 'could not be matched' in edge['reason']
    assert 'src/main/resources/openapi.yml' not in _evidence(facts, edge)
    assert not [symbol for symbol in facts['symbols'].values()
                if 'generated-model:' in symbol['qualified_name']]
