"""Tests for `speed discover domains --export ddd`."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from lib.context import business_domain_export as export
from lib.context.business_domain_cli import main
from lib.context.business_domains import discover, paths
from tests.business_domains.provider_fixture import PassingProvider, write_service

ROOT = Path(__file__).resolve().parents[1]


# Small models built by hand, so each renderer can be checked exactly

def evidence(identifier, path, line, excerpt='', kind='source'):
    return {'id': identifier, 'excerpt': excerpt, 'source_kind': kind,
            'locator': {'path': path, 'start_line': line, 'end_line': line}}


def symbol(identifier, name, file, kind='method', evidence_ids=()):
    return {'id': identifier, 'qualified_name': f'{file}::{name}', 'file': file, 'kind': kind,
            'evidence_ids': list(evidence_ids), 'resolution': 'resolved'}


def edge(identifier, kind, source, target, evidence_ids=(), condition=None, resolution='resolved',
         target_kind='symbol'):
    return {'id': identifier, 'kind': kind, 'from_ref': {'kind': 'symbol', 'id': source},
            'to_ref': {'kind': target_kind, 'id': target} if target else None,
            'evidence_ids': list(evidence_ids), 'condition': condition, 'resolution': resolution}


def service_model():
    """POST /owners: controller -> service -> repository (profile-bound) -> owners table."""
    controller = 'src/OwnerRestController.java'
    service = 'src/ClinicServiceImpl.java'
    symbols = {
        'symbol:root': symbol('symbol:root', 'OwnerRestController.addOwner(OwnerDto)', controller),
        'symbol:map': symbol('symbol:map', 'OwnerMapper.toOwner(OwnerDto)', 'src/OwnerMapper.java'),
        'symbol:getter': symbol('symbol:getter', 'BaseEntity.getId()', 'src/BaseEntity.java'),
        'symbol:svc': symbol('symbol:svc', 'ClinicService.saveOwner(Owner)', 'src/ClinicService.java'),
        'symbol:svcimpl': symbol('symbol:svcimpl', 'ClinicServiceImpl.saveOwner(Owner)', service),
        'symbol:repo': symbol('symbol:repo', 'OwnerRepository.save(Owner)', 'src/OwnerRepository.java'),
        'symbol:jdbc': symbol('symbol:jdbc', 'JdbcOwnerRepositoryImpl.save(Owner)', 'src/Jdbc.java'),
        'symbol:jdbcmore': symbol('symbol:jdbcmore', 'KeyHolder.next()', 'src/KeyHolder.java'),
    }
    evidences = {
        'ev:map': evidence('ev:map', controller, 20),
        'ev:get': evidence('ev:get', controller, 15),
        'ev:save': evidence('ev:save', controller, 30),
        'ev:repo': evidence('ev:repo', service, 40),
    }
    edges = {
        # Stored out of order: the diagram must follow the call-site lines.
        'edge:save': edge('edge:save', 'calls', 'symbol:root', 'symbol:svc', ['ev:save']),
        'edge:map': edge('edge:map', 'calls', 'symbol:root', 'symbol:map', ['ev:map']),
        'edge:get': edge('edge:get', 'calls', 'symbol:root', 'symbol:getter', ['ev:get']),
        'edge:impl': edge('edge:impl', 'selects_implementation', 'symbol:svc', 'symbol:svcimpl'),
        'edge:repo': edge('edge:repo', 'calls', 'symbol:svcimpl', 'symbol:repo', ['ev:repo']),
        'edge:active': edge('edge:active', 'selects_implementation', 'symbol:repo', 'resource:gen',
                            condition='@Profile("spring-data-jpa") on SpringDataOwnerRepository '
                                      'matches the active Spring profiles', target_kind='resource'),
        'edge:other': edge('edge:other', 'selects_implementation', 'symbol:repo', 'symbol:jdbc',
                           condition='@Profile("jdbc") on JdbcOwnerRepositoryImpl matches the '
                                     'active Spring profiles'),
        'edge:jdbcmore': edge('edge:jdbcmore', 'calls', 'symbol:jdbc', 'symbol:jdbcmore'),
        'edge:write': edge('edge:write', 'writes_data', 'symbol:repo', 'resource:owners',
                           condition='spring.profiles.active=hsqldb,spring-data-jpa declared in x',
                           resolution='unresolved', target_kind='resource'),
    }
    anchor = {'id': 'anchor:post', 'kind': 'http', 'symbol_id': 'symbol:contract',
              'operation': {'method': 'post', 'path': '/owners', 'name': 'addOwner'},
              'representations': [{'role': 'contract', 'symbol_id': 'symbol:contract'},
                                  {'role': 'implementation', 'symbol_id': 'symbol:root'}]}
    trace = {'id': 'trace:post', 'anchor_id': 'anchor:post', 'edge_ids': sorted(edges),
             'resolution': 'unresolved', 'completion': 'bounded'}
    activity = {'id': 'activity:add', 'name': 'Register a new owner', 'description': 'Adds an owner.',
                'anchor_ids': ['anchor:post'], 'trace_ids': ['trace:post'],
                'actor': 'Caller declared to need the OWNER_ADMIN role', 'information_use_ids': [],
                'implementation_status': 'implementation_unresolved', 'support': 'partial',
                'evidence_ids': ['ev:save'], 'unresolved_questions': []}
    return {
        'build_id': 'build-1', 'generated_at': '2026-10-25T11:51:57+00:00', 'status': 'partial',
        'coverage': {'anchors_total': 1, 'anchors_processed': 1},
        'symbols': symbols, 'evidence': evidences, 'edges': edges,
        'resources': {'resource:owners': {'id': 'resource:owners', 'kind': 'table', 'name': 'owners'},
                      'resource:gen': {'id': 'resource:gen', 'kind': 'service', 'name': 'External type'}},
        'anchors': {'anchor:post': anchor}, 'traces': {'trace:post': trace},
        'activities': {'activity:add': activity},
        'rules': {'rule:auth': {
            'id': 'rule:auth', 'name': 'Owner admins only', 'category': 'authorization',
            'activity_ids': ['activity:add'], 'predicate_or_formula': 'hasAnyRole(@roles.OWNER_ADMIN, @roles.VET_ADMIN)',
            'outcome': 'Forbidden otherwise', 'enforcement_status': 'conditional', 'support': 'partial',
            'enforcement_sites': [], 'basis': ['source_observed'], 'evidence_ids': [], 'scope': {},
            'evaluation_kind': 'predicate', 'conflicts': [], 'unresolved_questions': []}},
        'domains': {'domain:owners': {
            'id': 'domain:owners', 'name': 'Owner "Records" | <main>', 'summary': 'Keeps owners. More text.',
            'activity_memberships': [{'activity_id': 'activity:add', 'role': 'primary', 'claim_ids': []}],
            'concepts': [], 'rules': ['rule:auth'], 'ownership_ids': [], 'boundary_rationale': 'Owners only.',
            'alternatives': [], 'exclusions': [], 'support': 'partial', 'review_state': 'proposed',
            'unresolved_questions': []}},
        'concepts': {}, 'ownerships': {}, 'relationships': {}, 'information_uses': {}, 'claims': {},
        'unassigned': [], 'warnings': [],
    }


def test_a_call_sequence_follows_source_lines_and_the_active_profile():
    index = export.Model(service_model())
    [(title, caption, diagram)], skipped = export.Sequences(index).diagrams(index.activities['activity:add'])
    assert skipped == []
    assert title == 'POST /owners'
    assert 'not observed runtime' in caption
    lines = diagram.splitlines()
    messages = [line.strip() for line in lines if '->>' in line and not line.strip().startswith('Client')]
    # toOwner (line 20) comes before saveOwner (line 30); getId() is an accessor and is left out.
    assert [message.split(': ')[1] for message in messages] == [
        'toOwner()', 'saveOwner()', 'save()', 'write owners']
    # The write is unresolved, so it is dotted; the profile-bound JDBC path is not drawn.
    assert messages[-1].split(':')[0].endswith('-->>P5')
    assert 'KeyHolder' not in diagram
    assert ('runs SpringDataOwnerRepository, generated at runtime#59; '
            'not on the declared profile: JdbcOwnerRepositoryImpl') in diagram
    assert 'declared profile (hsqldb, spring-data-jpa, from spring.profiles.active)' in caption
    # The single implementation of ClinicService is followed on the interface's lifeline.
    assert 'participant P3 as ClinicService' in diagram
    assert 'participant P5 as owners table' in diagram


def test_without_a_profile_the_sequence_stops_at_the_interface():
    model = service_model()
    del model['edges']['edge:write']
    index = export.Model(model)
    [(_, _, diagram)], _ = export.Sequences(index).diagrams(index.activities['activity:add'])
    assert 'KeyHolder' not in diagram
    assert 'declared profile' not in diagram
    assert 'chosen at runtime by profile, not drawn: JdbcOwnerRepositoryImpl, SpringDataOwnerRepository' in diagram


def test_an_implementation_the_model_says_it_activates_is_followed():
    model = service_model()
    model['edges']['edge:other']['condition'] = (
        'spring.profiles.active=hsqldb,spring-data-jpa declared in application.properties activates '
        'JdbcOwnerRepositoryImpl (@Profile("spring-data-jpa")); inactive under it: JpaImpl')
    model['edges']['edge:jdbcwrite'] = edge('edge:jdbcwrite', 'writes_data', 'symbol:jdbc', 'resource:owners',
                                            target_kind='resource')
    model['traces']['trace:post']['edge_ids'].append('edge:jdbcwrite')
    index = export.Model(model)
    [(_, _, diagram)], _ = export.Sequences(index).diagrams(index.activities['activity:add'])
    # The activated implementation runs on the repository's lifeline, and its resolved
    # write replaces the interface's unresolved one.
    assert re.search(r'P4->>P\d+: write owners', diagram)
    assert 'P4-->>' not in diagram
    assert 'next()' in diagram
    assert 'not on the declared profile' not in diagram


def test_duplicate_or_unconditioned_implementation_edges_are_not_called_profile_choices():
    model = service_model()
    model['edges']['edge:dup'] = dict(model['edges']['edge:impl'], id='edge:dup')
    index = export.Model(model)
    [(_, _, diagram)], _ = export.Sequences(index).diagrams(index.activities['activity:add'])
    assert 'ClinicServiceImpl' not in diagram
    assert 'P3->>P4: save()' in diagram


def test_inner_calls_on_one_line_come_first_and_guards_become_opt_blocks():
    model = service_model()
    model['evidence']['ev:map'] = evidence('ev:map', 'src/OwnerRestController.java', 30,
                                           'return mapper.toOwner(clinicService.saveOwner(owner));')
    model['evidence']['ev:save'] = evidence('ev:save', 'src/OwnerRestController.java', 30,
                                            'return mapper.toOwner(clinicService.saveOwner(owner));')
    model['edges']['edge:map']['condition'] = 'owner.isNew() && __API_SERVER_URL__ === "x"'
    index = export.Model(model)
    [(_, _, diagram)], _ = export.Sequences(index).diagrams(index.activities['activity:add'])
    calls = [line.split(': ')[1] for line in diagram.splitlines() if '->>' in line and 'Client' not in line]
    assert calls.index('saveOwner()') < calls.index('toOwner()')
    assert 'opt owner.isNew()' in diagram and '__API_SERVER_URL__' not in diagram


def test_roles_come_from_authorization_predicates():
    index = export.Model(service_model())
    assert index.roles(index.activities['activity:add']) == ['OWNER_ADMIN', 'VET_ADMIN']
    assert index.access(index.activities['activity:add']) == (['OWNER_ADMIN', 'VET_ADMIN'], False)
    # A use case needs a role every one of its steps allows.
    model = service_model()
    model['rules']['rule:strict'] = dict(model['rules']['rule:auth'], id='rule:strict',
                                         predicate_or_formula='hasRole(@roles.OWNER_ADMIN)')
    assert export.Model(model).roles(model['activities']['activity:add']) == ['OWNER_ADMIN']
    model = service_model()
    model['rules'] = {}
    index = export.Model(model)
    assert index.roles(index.activities['activity:add']) == ['OWNER_ADMIN']
    model['activities']['activity:add']['actor'] = 'A clinic user'
    assert export.Model(model).roles(model['activities']['activity:add']) == ['no role declared']


def test_labels_and_ids_are_safe_for_mermaid():
    assert export.label('Owner "Records" | <main> #1;') == 'Owner #quot;Records#quot; | #lt;main#gt; #35;1#59;'
    assert re.fullmatch(r'D_[A-Za-z0-9]+', export.node('D', 'domain:ab-cd:0123456789'))
    diagram = export.context_map(export.Model(service_model()))
    assert '"Owner #quot;Records#quot; | #lt;main#gt;' in diagram
    assert '<main>' not in diagram


def entity_model():
    model = service_model()
    owner_file = 'src/main/java/org/example/model/Owner.java'
    pet_file = 'src/main/java/org/example/model/Pet.java'
    model['symbols'].update({
        'symbol:Owner': symbol('symbol:Owner', 'Owner', owner_file, 'class', ['ev:Owner']),
        'symbol:Person': symbol('symbol:Person', 'Person', 'src/main/java/org/example/model/Person.java', 'class'),
        'symbol:Pet': symbol('symbol:Pet', 'Pet:0', pet_file, 'class', ['ev:Pet']),
        'symbol:pets': symbol('symbol:pets', 'Owner.pets()', owner_file, 'field', ['ev:pets']),
        'symbol:city': symbol('symbol:city', 'Owner.city()', owner_file, 'field', ['ev:city']),
        'symbol:owner': symbol('symbol:owner', 'Pet.owner()', pet_file, 'field', ['ev:owner']),
    })
    model['evidence'].update({
        'ev:Owner': evidence('ev:Owner', owner_file, 1, '@Entity @Table(name = "owners") public class Owner'),
        'ev:Pet': evidence('ev:Pet', pet_file, 1, '@Entity public class Pet'),
        'ev:pets': evidence('ev:pets', owner_file, 9, '@OneToMany(mappedBy = "owner") private Set<Pet> pets;'),
        'ev:city': evidence('ev:city', owner_file, 5, '@Column(name = "city") @NotEmpty private String city;'),
        'ev:owner': evidence('ev:owner', pet_file, 7, '@ManyToOne @JoinColumn(name = "owner_id") private Owner owner;'),
    })
    model['edges'].update({
        'edge:f1': edge('edge:f1', 'has_field', 'symbol:Owner', 'symbol:pets'),
        'edge:f2': edge('edge:f2', 'has_field', 'symbol:Owner', 'symbol:city'),
        'edge:f3': edge('edge:f3', 'has_field', 'symbol:Pet', 'symbol:owner'),
        'edge:i1': edge('edge:i1', 'inherits', 'symbol:Owner', 'symbol:Person'),
    })
    model['concepts'] = {
        'concept:owner': {'id': 'concept:owner', 'name': 'Pet owner', 'symbol_ids': [],
                          'qualified_type_names': ['org.example.model.Owner']},
        'concept:pet': {'id': 'concept:pet', 'name': 'Pet', 'symbol_ids': [],
                        'qualified_type_names': ['org.example.model.Pet']},
        'concept:link': {'id': 'concept:link', 'name': 'Vet specialty assignment', 'symbol_ids': [],
                         'qualified_type_names': []},
    }
    model['domains']['domain:owners']['concepts'] = ['concept:owner', 'concept:pet', 'concept:link']
    return model


def test_the_class_diagram_reads_fields_associations_and_tables():
    index = export.Model(entity_model())
    entities = export.Entities(index)
    diagram = entities.diagram(['concept:owner', 'concept:pet', 'concept:link'])
    assert 'class Owner["Owner (owners)"] {' in diagram
    assert '+String city' in diagram
    assert 'Person <|-- Owner' in diagram
    # Both sides of the JPA association become one line, and its field is not an attribute.
    assert diagram.count('Owner "1" --> "*" Pet : pets') + diagram.count('Pet "*" --> "1" Owner : owner') == 1
    assert 'class Person["Person"]' in diagram
    assert '+Set~Pet~ pets' not in diagram
    # The :N suffix of a symbol name is stripped.
    assert 'class Pet["Pet"]' in diagram
    assert '["Vet specialty assignment"]' in diagram and '<<table>>' in diagram
    assert entities.constraints(['concept:owner']) == [('Owner', 'city', ('NotEmpty',))]


def test_rules_say_where_a_declared_rule_comes_from():
    rule = {'enforcement_status': 'declared_only', 'basis': ['contract_declared']}
    assert export.rule_status(rule) == 'declared in the API contract only'
    assert export.rule_status(dict(rule, basis=['test_expected'])) == 'expected by tests only'
    assert export.rule_status(dict(rule, basis=['source_observed', 'test_expected'])).startswith('declared in code')
    assert export.rule_status({'enforcement_status': 'conditional'}) == 'depends on preconditions'


def test_a_model_without_rules_or_data_renders_clean_tables():
    model = service_model()
    model['rules'] = {}
    model['domains']['domain:owners']['rules'] = []
    files = export.export_ddd(model)
    assert 'No rules were extracted.' in files['rules.md']
    for text in files.values():
        for header, delimiter in re.findall(r'^(\|.*\|)\n(\|[-:|]+\|)$', text, re.M):
            assert header.count('|') == delimiter.count('|'), header


def test_export_is_byte_identical_and_independent_of_insertion_order():
    first = export.export_ddd(entity_model())
    reordered = entity_model()
    for key in ('symbols', 'edges', 'evidence', 'concepts'):
        reordered[key] = dict(reversed(list(reordered[key].items())))
    assert export.export_ddd(reordered) == first
    assert set(first) == {'README.md', 'rules.md', 'glossary.md', 'gaps.md',
                          'contexts/owner-records-main.md'}


def test_every_page_carries_the_model_status_and_no_unescaped_mermaid():
    files = export.export_ddd(entity_model())
    assert '**Model status: partial.**' in files['README.md']
    assert '**Model status: partial.**' in files['gaps.md']
    for text in files.values():
        for block in re.findall(r'```mermaid\n(.*?)\n```', text, re.S):
            assert 'database ' not in block
            for line in block.splitlines():
                if '["' in line:
                    assert line.count('"') % 2 == 0, line


# The command

def published(tmp_path):
    write_service(tmp_path)
    model, _ = discover(tmp_path, provider=PassingProvider())
    assert model is not None
    return model


def test_export_without_a_published_model_is_an_error(tmp_path, capsys):
    assert main(['--root', str(tmp_path), '--export', 'ddd']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['error']['code'] == 'DOMAIN_DISCOVERY_MISSING'
    assert not (tmp_path / export.EXPORT_DIRECTORY).exists()


def test_export_writes_the_documents_and_a_manifest(tmp_path, capsys):
    published(tmp_path)
    assert main(['--root', str(tmp_path), '--export', 'ddd']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['ok'] and result['mode'] == 'export' and result['format'] == 'ddd'
    directory = tmp_path / result['directory']
    assert result['directory'] == export.EXPORT_DIRECTORY
    for name in result['files']:
        assert (directory / name).is_file()
    manifest = json.loads((directory / export.MANIFEST).read_text())
    assert set(manifest['files']) == set(result['files'])
    readme = (directory / 'README.md').read_text()
    assert 'Order management' in readme and '```mermaid' in readme


def test_export_refuses_to_overwrite_files_it_did_not_write(tmp_path, capsys):
    published(tmp_path)
    directory = tmp_path / 'docs'
    directory.mkdir()
    (directory / 'README.md').write_text('project readme')
    assert main(['--root', str(tmp_path), '--export', 'ddd', '--out', str(directory)]) == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'EXPORT_CONFLICT'
    assert (directory / 'README.md').read_text() == 'project readme'


def test_a_write_failure_is_reported_as_json(tmp_path, capsys):
    published(tmp_path)
    blocker = tmp_path / 'blocker'
    blocker.write_text('a file, not a directory')
    assert main(['--root', str(tmp_path), '--export', 'ddd', '--out', str(blocker / 'out')]) == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'EXPORT_WRITE_FAILED'


def test_export_to_a_chosen_directory_removes_only_its_own_stale_files(tmp_path, capsys, monkeypatch):
    published(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(['--root', str(tmp_path), '--export', 'ddd', '--out', 'docs/model']) == 0
    directory = tmp_path / 'docs/model'
    (directory / 'contexts/old-context.md').write_text('mine')
    manifest = json.loads((directory / export.MANIFEST).read_text())
    manifest['files']['contexts/retired.md'] = 'x'
    (directory / 'contexts/retired.md').write_text('stale')
    (directory / export.MANIFEST).write_text(json.dumps(manifest))
    capsys.readouterr()
    assert main(['--root', str(tmp_path), '--export', 'ddd', '--out', str(directory)]) == 0
    assert not (directory / 'contexts/retired.md').exists()
    assert (directory / 'contexts/old-context.md').read_text() == 'mine'


@pytest.mark.parametrize('argv', [['--out', 'x'], ['--export', 'ddd', '--status'], ['--export', 'uml']])
def test_invalid_export_arguments_are_rejected(tmp_path, argv):
    with pytest.raises(SystemExit):
        main(['--root', str(tmp_path), *argv])


def test_the_shell_prints_where_the_documents_went(tmp_path):
    result = tmp_path / 'result.json'
    result.write_text(json.dumps({
        'ok': True, 'mode': 'export', 'build_id': 'b1', 'directory': '.speed/context/business-domain-ddd',
        'files': ['README.md', 'rules.md'],
        'counts': {'contexts': 2, 'use_cases': 3, 'entities': 4, 'rules': 5, 'links': 1}}))
    output = subprocess.run(
        ['bash', '-c', f'source "{ROOT}/lib/cmd/domains.sh"; _domains_render_export "{result}"'],
        capture_output=True, text=True, check=True).stdout
    assert 'Wrote 2 documents for build b1 to .speed/context/business-domain-ddd/' in output
    assert '2 bounded contexts · 3 use cases · 4 entities · 5 business rules' in output
    assert '\x1b[' not in output


@pytest.mark.skipif(not os.environ.get('SPEED_PETCLINIC_MODEL'),
                    reason='set SPEED_PETCLINIC_MODEL to a published PetClinic business-domains.json')
def test_petclinic_export():
    model = json.loads(Path(os.environ['SPEED_PETCLINIC_MODEL']).read_text())
    files = export.export_ddd(model)
    contexts = [name for name in files if name.startswith('contexts/')]
    assert len(contexts) == len(model['domains'])
    assert files['rules.md'].count('<a id="rule-') == len(model['rules'])
    assert 'runs SpringData' in ''.join(files[name] for name in contexts)


def test_a_dense_trace_renders_quickly_and_says_steps_were_left_out():
    model = service_model()
    trace = model['traces']['trace:post']
    # Every method calls every other: an exponential walk would never finish.
    names = [f'symbol:m{position}' for position in range(14)]
    for position, name in enumerate(names):
        model['symbols'][name] = symbol(name, f'Service{position}.run{position}()', f'src/S{position}.java')
    for source in ['symbol:root', *names]:
        for target in names:
            if source != target:
                identifier = f'edge:{source[-3:]}-{target[-3:]}'
                model['edges'][identifier] = edge(identifier, 'calls', source, target)
                trace['edge_ids'].append(identifier)
    index = export.Model(model)
    started = time.monotonic()
    [(_, _, diagram)], _ = export.Sequences(index).diagrams(index.activities['activity:add'])
    assert time.monotonic() - started < 5
    assert 'more steps not drawn' in diagram


def test_an_unresolved_api_call_from_a_page_is_drawn_dotted():
    model = service_model()
    model['edges']['edge:api'] = edge('edge:api', 'invokes_endpoint', 'symbol:root', None, resolution='unresolved')
    model['traces']['trace:post']['edge_ids'].append('edge:api')
    index = export.Model(model)
    [(_, _, diagram)], _ = export.Sequences(index).diagrams(index.activities['activity:add'])
    assert re.search(r'P1-->>P\d+: request \(target not resolved\)', diagram)
    assert 'as unresolved endpoint' in diagram


def test_conflicting_role_rules_are_not_merged():
    model = service_model()
    model['rules']['rule:vet'] = dict(model['rules']['rule:auth'], id='rule:vet',
                                      predicate_or_formula='hasRole(@roles.VET_ADMIN)')
    model['rules']['rule:owner'] = dict(model['rules']['rule:auth'], id='rule:owner',
                                        predicate_or_formula='hasRole(@roles.OWNER_ADMIN)')
    assert export.Model(model).roles(model['activities']['activity:add']) == [export.CONFLICTING_ROLES]


def test_contract_and_test_basis_is_named_as_both():
    rule = {'enforcement_status': 'declared_only', 'basis': ['contract_declared', 'test_expected']}
    assert export.rule_status(rule) == 'declared in the API contract and expected by tests'


def test_a_foreign_manifest_is_not_trusted(tmp_path, capsys):
    published(tmp_path)
    directory = tmp_path / 'out'
    directory.mkdir()
    (directory / 'keep.md').write_text('mine')
    (directory / export.MANIFEST).write_text(json.dumps({'files': {'keep.md': 'x'}}))
    assert main(['--root', str(tmp_path), '--export', 'ddd', '--out', str(directory)]) == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'EXPORT_CONFLICT'
    assert (directory / 'keep.md').read_text() == 'mine'


def test_an_interrupted_export_does_not_lock_its_directory(tmp_path, capsys, monkeypatch):
    published(tmp_path)
    directory = tmp_path / 'out'
    real = export._write_text
    calls = {'count': 0}

    def failing(base, relative, text):
        calls['count'] += 1
        if calls['count'] == 3:
            raise OSError('disk full')
        return real(base, relative, text)
    monkeypatch.setattr(export, '_write_text', failing)
    assert main(['--root', str(tmp_path), '--export', 'ddd', '--out', str(directory)]) == 1
    monkeypatch.setattr(export, '_write_text', real)
    capsys.readouterr()
    assert main(['--root', str(tmp_path), '--export', 'ddd', '--out', str(directory)]) == 0
