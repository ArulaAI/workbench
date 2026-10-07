"""Repository operations reach the tables they read and write.

A miniature of the PetClinic repository layer: one repository interface with
JDBC, JPA and Spring Data implementations selected by @Profile, a Spring Data
@Query redeclaration and repository fragment, a service and a controller, and
a schema declaring the tables.
"""
import pytest

from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import DEFAULTS, validate_references


SCHEMA = """CREATE TABLE owners (
  id INTEGER PRIMARY KEY,
  last_name VARCHAR(30)
);
CREATE TABLE pets (
  id INTEGER PRIMARY KEY,
  owner_id INTEGER
);
"""

OWNER = """package com.example.model;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import java.util.Set;
@Entity
@Table(name = "owners")
public class Owner {
  private Set<Pet> pets;
}
"""

PET = """package com.example.model;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
@Entity
@Table(name = "pets")
public class Pet {
  private Owner owner;
}
"""

REPOSITORY = """package com.example.repository;
import com.example.model.Owner;
import java.util.Collection;
public interface OwnerRepository {
  void save(Owner owner);
  Collection<Owner> findByLastName(String lastName);
  void delete(Owner owner);
  Collection<Owner> findAll();
}
"""

JDBC = """package com.example.repository.jdbc;
import com.example.model.Owner;
import com.example.repository.OwnerRepository;
import java.util.Collection;
import javax.sql.DataSource;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.simple.SimpleJdbcInsert;
import org.springframework.stereotype.Repository;
@Repository
@Profile("jdbc")
public class JdbcOwnerRepositoryImpl implements OwnerRepository {
  private NamedParameterJdbcTemplate namedParameterJdbcTemplate;
  private SimpleJdbcInsert insertOwner;
  public JdbcOwnerRepositoryImpl(DataSource dataSource) {
    this.insertOwner = new SimpleJdbcInsert(dataSource).withTableName("owners");
    this.namedParameterJdbcTemplate = new NamedParameterJdbcTemplate(dataSource);
  }
  public void save(Owner owner) {
    if (owner.isNew()) {
      this.insertOwner.executeAndReturnKey(null);
    } else {
      this.namedParameterJdbcTemplate.update("UPDATE owners SET last_name=:lastName WHERE id=:id", null);
    }
  }
  public Collection<Owner> findByLastName(String lastName) {
    return this.namedParameterJdbcTemplate.query(
        "SELECT id, last_name FROM owners WHERE last_name like :lastName", null, null);
  }
  public void delete(Owner owner) {
    this.namedParameterJdbcTemplate.update("DELETE FROM pets WHERE owner_id=:id", null);
    this.namedParameterJdbcTemplate.update("DELETE FROM owners WHERE id=:id", null);
  }
  public Collection<Owner> findAll() {
    return this.namedParameterJdbcTemplate.query("SELECT id FROM ledger_entries", null, null);
  }
}
"""

JPA = """package com.example.repository.jpa;
import com.example.model.Owner;
import com.example.repository.OwnerRepository;
import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import java.util.Collection;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Repository;
@Repository
@Profile("jpa")
public class JpaOwnerRepositoryImpl implements OwnerRepository {
  @PersistenceContext
  private EntityManager em;
  public void save(Owner owner) {
    if (owner.getId() == null) {
      this.em.persist(owner);
    } else {
      this.em.merge(owner);
    }
  }
  public Collection<Owner> findByLastName(String lastName) {
    return this.em.createQuery("SELECT DISTINCT owner FROM Owner owner left join fetch owner.pets WHERE owner.lastName LIKE :lastName").getResultList();
  }
  public void delete(Owner owner) {
    this.em.remove(owner);
  }
  public Collection<Owner> findAll() {
    return this.em.createQuery("SELECT owner FROM Owner owner").getResultList();
  }
}
"""

SPRING_DATA = """package com.example.repository.springdatajpa;
import com.example.model.Owner;
import com.example.repository.OwnerRepository;
import java.util.Collection;
import org.springframework.context.annotation.Profile;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
@Profile("spring-data-jpa")
public interface SpringDataOwnerRepository extends OwnerRepository, Repository<Owner, Integer>, OwnerRepositoryOverride {
  @Override
  @Query("SELECT DISTINCT owner FROM Owner owner left join fetch owner.pets WHERE owner.lastName LIKE :lastName%")
  Collection<Owner> findByLastName(String lastName);
}
"""

OVERRIDE = """package com.example.repository.springdatajpa;
import com.example.model.Owner;
import org.springframework.context.annotation.Profile;
@Profile("spring-data-jpa")
public interface OwnerRepositoryOverride {
  void delete(Owner owner);
}
"""

FRAGMENT = """package com.example.repository.springdatajpa;
import com.example.model.Owner;
import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import org.springframework.context.annotation.Profile;
@Profile("spring-data-jpa")
public class SpringDataOwnerRepositoryImpl implements OwnerRepositoryOverride {
  @PersistenceContext
  private EntityManager em;
  public void delete(Owner owner) {
    this.em.createQuery("DELETE FROM Pet pet WHERE pet.owner.id=" + owner.getId()).executeUpdate();
    this.em.remove(owner);
  }
}
"""

SERVICE = """package com.example.service;
import com.example.model.Owner;
import java.util.Collection;
public interface ClinicService {
  void saveOwner(Owner owner);
  Collection<Owner> findOwnerByLastName(String lastName);
  void deleteOwner(Owner owner);
  Collection<Owner> findAllOwners();
}
"""

SERVICE_IMPL = """package com.example.service;
import com.example.model.Owner;
import com.example.repository.OwnerRepository;
import java.util.Collection;
import org.springframework.stereotype.Service;
@Service
public class ClinicServiceImpl implements ClinicService {
  private final OwnerRepository ownerRepository;
  public ClinicServiceImpl(OwnerRepository ownerRepository) { this.ownerRepository = ownerRepository; }
  @Override public void saveOwner(Owner owner) { ownerRepository.save(owner); }
  @Override public Collection<Owner> findOwnerByLastName(String lastName) { return ownerRepository.findByLastName(lastName); }
  @Override public void deleteOwner(Owner owner) { ownerRepository.delete(owner); }
  @Override public Collection<Owner> findAllOwners() { return ownerRepository.findAll(); }
}
"""

CONTROLLER = """package com.example.web;
import com.example.model.Owner;
import com.example.service.ClinicService;
import java.util.Collection;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
@RestController
@RequestMapping("/api")
public class OwnerController {
  private final ClinicService clinicService;
  OwnerController(ClinicService clinicService) { this.clinicService = clinicService; }
  @PostMapping("/owners") public void addOwner(Owner owner) { clinicService.saveOwner(owner); }
  @GetMapping("/owners") public Collection<Owner> listOwners(String lastName) { return clinicService.findOwnerByLastName(lastName); }
  @DeleteMapping("/owners") public void deleteOwner(Owner owner) { clinicService.deleteOwner(owner); }
  @GetMapping("/owners/all") public Collection<Owner> allOwners() { return clinicService.findAllOwners(); }
}
"""

JAVA = 'src/main/java/com/example/'
FILES = {
    'src/main/resources/db/hsqldb/initDB.sql': SCHEMA,
    JAVA + 'model/Owner.java': OWNER,
    JAVA + 'model/Pet.java': PET,
    JAVA + 'repository/OwnerRepository.java': REPOSITORY,
    JAVA + 'repository/jdbc/JdbcOwnerRepositoryImpl.java': JDBC,
    JAVA + 'repository/jpa/JpaOwnerRepositoryImpl.java': JPA,
    JAVA + 'repository/springdatajpa/SpringDataOwnerRepository.java': SPRING_DATA,
    JAVA + 'repository/springdatajpa/OwnerRepositoryOverride.java': OVERRIDE,
    JAVA + 'repository/springdatajpa/SpringDataOwnerRepositoryImpl.java': FRAGMENT,
    JAVA + 'service/ClinicService.java': SERVICE,
    JAVA + 'service/ClinicServiceImpl.java': SERVICE_IMPL,
    JAVA + 'web/OwnerController.java': CONTROLLER,
}
PROFILES = 'spring.profiles.active=hsqldb,spring-data-jpa\n'


def _extract(root, profiles=PROFILES):
    files = dict(FILES)
    if profiles is not None:
        files['src/main/resources/application.properties'] = profiles
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, _ = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    return facts


def _name(facts, symbol_id):
    return facts['symbols'][symbol_id]['qualified_name'].split('::', 1)[1]


def _data(facts, origin):
    """``(kind, table, resolution)`` of every data edge from one method."""
    return sorted((edge['kind'], facts['resources'][edge['to_ref']['id']]['name'], edge['resolution'])
                  for edge in facts['edges'].values()
                  if edge['kind'] in ('reads_data', 'writes_data')
                  and _name(facts, edge['from_ref']['id']).startswith(origin + '('))


def _selections(facts, origin):
    return [edge for edge in facts['edges'].values() if edge['kind'] == 'selects_implementation'
            and _name(facts, edge['from_ref']['id']).startswith(origin + '(')]


def _trace(facts, path, method):
    return next(trace for trace in facts['traces'].values()
                if any(item['identity_key'] == f'http:repository:{method}:{path}'
                       for item in facts['anchors'][trace['anchor_id']]['representations']))


def _trace_tables(facts, trace):
    return sorted({facts['resources'][facts['edges'][edge_id]['to_ref']['id']]['name']
                   for edge_id in trace['edge_ids']
                   if facts['edges'][edge_id]['kind'] in ('reads_data', 'writes_data')})


@pytest.fixture(scope='module')
def facts(tmp_path_factory):
    return _extract(tmp_path_factory.mktemp('persistence'))


def test_jdbc_select_reads_its_table(facts):
    assert ('reads_data', 'owners', 'resolved') in _data(facts, 'JdbcOwnerRepositoryImpl.findByLastName')


def test_jdbc_statements_write_their_tables_and_writes_stay_unresolved(facts):
    assert _data(facts, 'JdbcOwnerRepositoryImpl.delete') == [
        ('writes_data', 'owners', 'unresolved'), ('writes_data', 'pets', 'unresolved')]
    write = next(edge for edge in facts['edges'].values() if edge['kind'] == 'writes_data'
                 and _name(facts, edge['from_ref']['id']).startswith('JdbcOwnerRepositoryImpl.delete('))
    assert 'commits at runtime is not established' in write['reason']
    assert any(effect['edge_id'] == write['id'] for effect in facts['effects'].values())


def test_simple_jdbc_insert_writes_its_declared_table(facts):
    excerpts = [facts['evidence'][edge['evidence_ids'][0]]['excerpt']
                for edge in facts['edges'].values() if edge['kind'] == 'writes_data'
                and _name(facts, edge['from_ref']['id']).startswith('JdbcOwnerRepositoryImpl.save(')]
    assert any('insertOwner.executeAndReturnKey' in excerpt for excerpt in excerpts)
    assert _data(facts, 'JdbcOwnerRepositoryImpl.save') == [
        ('writes_data', 'owners', 'unresolved'), ('writes_data', 'owners', 'unresolved')]


def test_undeclared_table_is_kept_unresolved_not_invented(facts):
    assert _data(facts, 'JdbcOwnerRepositoryImpl.findAll') == [
        ('reads_data', 'ledger_entries', 'unresolved')]
    table = next(resource for resource in facts['resources'].values()
                 if resource['kind'] == 'table' and resource['name'] == 'ledger_entries')
    assert table['resolution'] == 'unresolved' and 'not declared' in table['reason']


def test_entity_manager_persist_and_merge_write_the_entity_table(facts):
    assert _data(facts, 'JpaOwnerRepositoryImpl.save') == [
        ('writes_data', 'owners', 'unresolved'), ('writes_data', 'owners', 'unresolved')]


def test_jpql_resolves_entities_and_join_paths_to_tables(facts):
    assert _data(facts, 'JpaOwnerRepositoryImpl.findByLastName') == [
        ('reads_data', 'owners', 'resolved'), ('reads_data', 'pets', 'resolved')]


def test_query_annotation_declares_its_reads(facts):
    assert _data(facts, 'SpringDataOwnerRepository.findByLastName') == [
        ('reads_data', 'owners', 'resolved'), ('reads_data', 'pets', 'resolved')]


def test_declared_profile_adds_a_conditioned_selection_and_keeps_the_alternatives(facts):
    selections = _selections(facts, 'OwnerRepository.delete')
    declared = [edge for edge in selections
                if 'spring.profiles.active' in (edge['condition'] or '')]
    assert len(declared) == 1
    edge = declared[0]
    assert edge['resolution'] == 'resolved'
    assert _name(facts, edge['to_ref']['id']).startswith('SpringDataOwnerRepositoryImpl.delete(')
    assert 'spring.profiles.active=hsqldb,spring-data-jpa' in edge['condition']
    assert 'runtime profile override' in edge['condition']
    assert 'JdbcOwnerRepositoryImpl' in edge['condition'] and 'JpaOwnerRepositoryImpl' in edge['condition']
    # Every implementation names its @Profile, so each stays a path under its
    # own condition rather than one ambiguous choice.
    assert not [edge for edge in selections if edge['resolution'] == 'ambiguous']
    assert sorted(_name(facts, edge['to_ref']['id']).split('.')[0] for edge in selections) == [
        'JdbcOwnerRepositoryImpl', 'JpaOwnerRepositoryImpl', 'SpringDataOwnerRepositoryImpl']
    assert all(edge['condition'] for edge in selections)
    # The Java adapter's earlier ambiguity report is withdrawn, including the
    # one rewritten when the Spring Data fragment joined the candidates.
    assert not [warning for warning in facts['warnings']
                if warning['code'] == 'JAVA_IMPLEMENTATION_AMBIGUOUS'
                and 'OwnerRepository.delete(' in warning['message']]
    query = [edge for edge in _selections(facts, 'OwnerRepository.findByLastName')
             if 'spring.profiles.active' in (edge['condition'] or '')]
    assert [_name(facts, edge['to_ref']['id']).split('(')[0] for edge in query] == [
        'SpringDataOwnerRepository.findByLastName']


def test_generated_spring_data_operation_is_an_unresolved_boundary(facts):
    assert _data(facts, 'OwnerRepository.save') == [('writes_data', 'owners', 'unresolved')]
    assert _data(facts, 'OwnerRepository.findAll') == [('reads_data', 'owners', 'unresolved')]
    read = next(edge for edge in facts['edges'].values() if edge['kind'] == 'reads_data'
                and _name(facts, edge['from_ref']['id']).startswith('OwnerRepository.findAll('))
    assert 'generated SQL is not in source' in read['reason'] and read['condition']
    assert any(edge['to_ref'] and edge['to_ref']['kind'] == 'resource'
               for edge in _selections(facts, 'OwnerRepository.save'))


def test_traces_reach_tables_through_the_declared_profile(facts):
    find = _trace(facts, '/api/owners', 'GET')
    names = {_name(facts, symbol_id).split('(')[0] for symbol_id in find['symbol_ids']}
    assert {'ClinicServiceImpl.findOwnerByLastName', 'OwnerRepository.findByLastName',
            'SpringDataOwnerRepository.findByLastName'} <= names
    # Every profile alternative is followed; the choice is a config_selected
    # boundary with its assumption, never a resolution.
    assert 'JdbcOwnerRepositoryImpl.findByLastName' in names
    conditional = [facts['trace_obligations'][oid] for oid in find['obligation_ids']
                   if facts['trace_obligations'][oid]['reason_code'] == 'CONDITIONAL_IMPLEMENTATION']
    assert conditional and all(item['boundary'] == 'config_selected' for item in conditional)
    assert {item['obligation_id'] for item in find['assumptions']} >= {
        item['id'] for item in conditional}
    assert _trace_tables(facts, find) == ['owners', 'pets']
    delete = _trace(facts, '/api/owners', 'DELETE')
    assert 'SpringDataOwnerRepositoryImpl.delete' in {
        _name(facts, symbol_id).split('(')[0] for symbol_id in delete['symbol_ids']}
    assert _trace_tables(facts, delete) == ['owners', 'pets']
    assert delete['resolution'] != 'resolved'


def test_without_a_declared_profile_selection_stays_unresolved(tmp_path):
    facts = _extract(tmp_path, profiles=None)
    # Only @Profile conditions remain; no declared property selects anything.
    assert not [edge for edge in facts['edges'].values()
                if edge['kind'] == 'selects_implementation'
                and 'spring.profiles.active' in (edge['condition'] or '')]
    assert _data(facts, 'OwnerRepository.save') == []
    find = _trace(facts, '/api/owners', 'GET')
    names = {_name(facts, symbol_id).split('(')[0] for symbol_id in find['symbol_ids']}
    assert 'ClinicServiceImpl.findOwnerByLastName' in names
    assert find['resolution'] != 'resolved'
    # The source statements are still facts about their methods.
    assert _data(facts, 'JdbcOwnerRepositoryImpl.findByLastName') == [('reads_data', 'owners', 'resolved')]


def test_service_implementation_reach_is_unchanged_by_persistence(tmp_path):
    with_profile = _extract(tmp_path / 'declared')
    without = _extract(tmp_path / 'undeclared', profiles=None)

    def reach(facts):
        return {item['identity_key']: any('ServiceImpl.' in facts['symbols'][symbol_id]['qualified_name']
                                          for symbol_id in trace['symbol_ids'])
                for trace in facts['traces'].values()
                for item in facts['anchors'][trace['anchor_id']]['representations'][:1]}

    assert reach(with_profile) == reach(without)
    assert sum(reach(with_profile).values()) == 4


def test_unavailable_sql_parser_is_reported_and_extraction_continues(tmp_path, monkeypatch):
    # The SQL language adapter loads its own parser on import; load it first so
    # only the Spring enricher sees the failing loader.
    from lib.context.business_domain_adapters import spring_semantic, sql  # noqa: F401

    def unavailable(identity):
        raise RuntimeError(f'Trusted parser version mismatch: {identity}')

    monkeypatch.setattr(spring_semantic, '_SQL_PARSER', {})
    monkeypatch.setattr(spring_semantic.registry, 'load_trusted_parser', unavailable)
    facts = _extract(tmp_path)

    jdbc = next(resource_id for resource_id, resource in facts['resources'].items()
                if resource['name'].endswith('JdbcOwnerRepositoryImpl.java'))
    reports = [item for item in facts['warnings'] if item['code'] == 'SPRING_SQL_PARSER_UNAVAILABLE'
               and item['subject_ids'] == [jdbc]]
    assert len(reports) == 1 and 'sqlglot RuntimeError' in reports[0]['message']
    # SQL text is left unparsed; writes that need no SQL parsing are still found.
    assert _data(facts, 'JdbcOwnerRepositoryImpl.delete') == []
    assert _data(facts, 'JdbcOwnerRepositoryImpl.save') == [('writes_data', 'owners', 'unresolved')]
    assert ('reads_data', 'owners', 'resolved') in _data(facts, 'SpringDataOwnerRepository.findByLastName')


def test_sql_parser_is_loaded_once_per_process(tmp_path, monkeypatch):
    from lib.context.business_domain_adapters import spring_semantic, sql  # noqa: F401
    loads = []
    original = spring_semantic.registry.load_trusted_parser

    def counting(identity):
        loads.append(identity)
        return original(identity)

    monkeypatch.setattr(spring_semantic, '_SQL_PARSER', {})
    monkeypatch.setattr(spring_semantic.registry, 'load_trusted_parser', counting)
    facts = _extract(tmp_path)
    assert loads == ['sqlglot']
    assert ('reads_data', 'owners', 'resolved') in _data(facts, 'JdbcOwnerRepositoryImpl.findByLastName')
