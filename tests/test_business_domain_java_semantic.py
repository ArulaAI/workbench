"""Java/Spring semantic adapter conformance and PetClinic regressions."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, digest, identifier, record, validate_references,
)
from lib.context.business_domain_synthesis import Synthesis
from lib.context.business_domain_adapters.base import Source
from lib.context.business_domain_adapters import documents, java_semantic, rules, spring_semantic


def _extract(root: Path, files: dict[str, str]):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    facts = Extractor(root, DEFAULTS).extract()[0]
    validate_references(facts)
    return facts


def _edge_names(facts, kind=None):
    symbols = facts["symbols"]
    return [(symbols[edge["from_ref"]["id"]]["qualified_name"],
             (symbols[edge["to_ref"]["id"]]["qualified_name"]
              if edge["to_ref"] and edge["to_ref"]["kind"] == "symbol"
              else facts["resources"][edge["to_ref"]["id"]]["name"]
              if edge["to_ref"] else None),
             edge)
            for edge in facts["edges"].values()
            if (kind is None or edge["kind"] == kind)]


def test_java_import_and_inheritance_resolve_exact_declaration(tmp_path):
    facts = _extract(tmp_path, {
        "src/alpha/Contract.java": "package alpha; public interface Contract {}",
        "src/beta/Contract.java": "package beta; public interface Contract {}",
        "src/app/Controller.java": """
            package app;
            import alpha.Contract;
            public class Controller implements Contract {}
        """,
    })

    resolved = [(left, right) for left, right, edge in _edge_names(facts, "implements")
                if edge["resolution"] == "resolved"]
    assert any("Controller" in left and "src/alpha/Contract.java" in right
               for left, right in resolved)
    assert not any("Controller" in left and "src/beta/Contract.java" in right
                   for left, right in resolved)


def test_java_overload_uses_receiver_type_and_argument_types(tmp_path):
    facts = _extract(tmp_path, {
        "src/app/Service.java": """
            package app;
            public class Service {
              public String find(String value) { return value; }
              public String find(int value) { return String.valueOf(value); }
            }
        """,
        "src/app/Controller.java": """
            package app;
            public class Controller {
              private Service service;
              public String run() { return service.find(42); }
            }
        """,
    })

    calls = [(left, right, edge) for left, right, edge in _edge_names(facts, "calls")
             if "Controller.run" in left and edge["resolution"] == "resolved"]
    assert len(calls) == 1
    assert "Service.find(int)" in calls[0][1]
    assert facts["evidence"][calls[0][2]["evidence_ids"][0]]["excerpt"] == "service.find(42)"


def test_spring_interface_mapping_is_inherited_with_exact_method_identity(tmp_path):
    facts = _extract(tmp_path, {
        "src/app/PetsApi.java": """
            package app;
            import org.springframework.web.bind.annotation.GetMapping;
            public interface PetsApi {
              @GetMapping("/pets/{id}") String getPet(int id);
            }
        """,
        "src/app/PetController.java": """
            package app;
            import org.springframework.web.bind.annotation.RestController;
            import org.springframework.web.bind.annotation.RequestMapping;
            @RestController @RequestMapping("/api")
            public class PetController implements PetsApi {
              public String getPet(int id) { return "pet"; }
            }
        """,
    })

    anchors = list(facts["anchors"].values())
    controller = next((anchor, representation) for anchor in anchors
        for representation in anchor["representations"]
        if "PetController.java" in facts["symbols"][representation["symbol_id"]]["file"])
    anchor, representation = controller
    assert anchor["resolution"] == "resolved"
    assert representation["role"] == "implementation"
    assert representation["operation"]["method"] == "GET"
    assert representation["operation"]["path"] == "/api/pets/{id}"
    assert anchor["operation"]["path"] == "/api/pets/{id}"
    implemented = [(left, right, edge) for left, right, edge in _edge_names(facts, "implements")
                   if "PetController.getPet(int)" in left]
    assert len(implemented) == 1
    assert "PetsApi.getPet(int)" in implemented[0][1]
    assert implemented[0][2]["resolution"] == "resolved"


def test_direct_spring_mapping_composes_class_and_method_with_separate_evidence(tmp_path):
    facts = _extract(tmp_path, {"src/app/OrderController.java": """
        package app;
        import org.springframework.web.bind.annotation.RestController;
        import org.springframework.web.bind.annotation.RequestMapping;
        import org.springframework.web.bind.annotation.PostMapping;
        @RestController @RequestMapping("/api")
        public class OrderController {
          @PostMapping("/orders") public void create() {}
        }
    """})

    anchor = next(iter(facts["anchors"].values()))
    assert anchor["resolution"] == "resolved"
    assert anchor["operation"]["method"] == "POST"
    assert anchor["operation"]["path"] == "/api/orders"
    excerpts = [facts["evidence"][ident]["excerpt"] for ident in anchor["evidence_ids"]]
    assert any('@RequestMapping("/api")' in excerpt for excerpt in excerpts)
    assert any('@PostMapping("/orders")' in excerpt for excerpt in excerpts)


def test_root_request_mapping_retains_route_but_not_a_guessed_http_method(tmp_path):
    facts = _extract(tmp_path, {"src/app/RootRestController.java": """
        package app;
        import org.springframework.web.bind.annotation.RestController;
        import org.springframework.web.bind.annotation.RequestMapping;
        @RestController @RequestMapping("/")
        public class RootRestController {
          @RequestMapping(value = "/") public void redirectToSwagger() {}
        }
    """})

    anchor = next(iter(facts["anchors"].values()))
    assert anchor["operation"]["path"] == "/"
    assert anchor["operation"]["method"] is None
    assert anchor["resolution"] == "unresolved" and anchor["reason"]
    assert any('@RequestMapping' in facts["evidence"][ident]["excerpt"]
               for ident in anchor["evidence_ids"])


def test_conflicting_spring_paths_remain_ambiguous_with_mapping_evidence(tmp_path):
    facts = _extract(tmp_path, {"src/app/SearchController.java": """
        package app;
        import org.springframework.web.bind.annotation.RestController;
        import org.springframework.web.bind.annotation.GetMapping;
        @RestController public class SearchController {
          @GetMapping({"/people", "/owners"}) public void search() {}
        }
    """})

    anchor = next(iter(facts["anchors"].values()))
    assert anchor["resolution"] == "ambiguous"
    assert anchor["operation"]["method"] == "GET"
    assert anchor["operation"]["path"] is None
    assert anchor["reason"]
    assert any('/people' in facts["evidence"][ident]["excerpt"]
               and '/owners' in facts["evidence"][ident]["excerpt"]
               for ident in anchor["evidence_ids"])


def test_missing_generated_interface_and_external_dependency_are_distinct(tmp_path):
    facts = _extract(tmp_path, {
        "src/org/example/controller/PetController.java": """
            package org.example.controller;
            import org.example.api.GeneratedPetsApi;
            import java.time.Clock;
            import org.springframework.web.bind.annotation.RestController;
            @RestController
            public class PetController implements GeneratedPetsApi {
              private Clock clock;
              public Object now() { return clock.instant(); }
            }
        """,
    })

    codes = {warning["code"] for warning in facts["warnings"]}
    assert "JAVA_TYPE_DECLARATION_UNAVAILABLE" in codes
    assert "JAVA_EXTERNAL_CALL" in codes
    edge = next(edge for _, _, edge in _edge_names(facts, "implements"))
    assert edge["resolution"] == "unresolved"
    assert edge["to_ref"] is None
    anchor = next(iter(facts["anchors"].values()))
    assert anchor["resolution"] == "unresolved"
    assert anchor["operation"]["method"] is None
    assert anchor["operation"]["path"] is None
    assert anchor["reason"]


def test_maven_generated_interface_links_openapi_contract_to_controller(tmp_path):
    facts = _extract(tmp_path, {
        "a/src/app/PetController.java": """
            package app;
            import generated.api.PetsApi;
            import org.springframework.web.bind.annotation.RestController;
            import org.springframework.web.bind.annotation.RequestMapping;
            @RestController @RequestMapping("/api")
            public class PetController implements PetsApi {
              public String getPet(int id) { return "pet"; }
            }
        """,
        # Deliberately sorts after the Java source: build metadata preparation
        # must be phase ordered rather than dependent on inventory path order.
        "z/pom.xml": """
          <project><build><plugins><plugin>
            <artifactId>openapi-generator-maven-plugin</artifactId>
            <configuration>
              <inputSpec>src/main/resources/openapi.yml</inputSpec>
              <apiPackage>generated.api</apiPackage>
              <configOptions><interfaceOnly>true</interfaceOnly></configOptions>
            </configuration>
          </plugin></plugins></build></project>
        """,
        "z/openapi.yml": """
          openapi: 3.0.1
          paths:
            /pets/{id}:
              get:
                operationId: getPet
                responses:
                  '200': {description: pet}
        """,
    })

    class_edge = next(edge for left, right, edge in _edge_names(facts, "implements")
                      if left.endswith("PetController") and right
                      and "generated-interface:generated.api.PetsApi" in right)
    assert class_edge["resolution"] == "resolved"
    method_edge = next(edge for left, right, edge in _edge_names(facts, "implements")
                       if "PetController.getPet(int)" in left and right
                       and "GET /pets/{id}" in right)
    assert method_edge["resolution"] == "resolved"
    anchor = next(anchor for anchor in facts["anchors"].values()
                  if anchor["operation"]["path"] == "/pets/{id}")
    assert anchor["resolution"] == "resolved"
    assert not any(warning["code"] == "JAVA_TYPE_DECLARATION_UNAVAILABLE"
                   for warning in facts["warnings"])


def test_java_ambiguity_retains_bounded_candidate_symbol_ids(tmp_path):
    facts = _extract(tmp_path, {
        "src/a/Contract.java": "package a; public interface Contract {}",
        "src/b/Contract.java": "package b; public interface Contract {}",
        "src/app/Controller.java": """
            package app;
            import a.*;
            import b.*;
            public class Controller implements Contract {}
        """,
    })

    edge = next(edge for left, _, edge in _edge_names(facts, "implements")
                if "Controller" in left)
    assert edge["resolution"] == "ambiguous"
    assert len(edge["candidate_target_ids"]) == 2
    assert set(edge["candidate_target_ids"]) <= set(facts["symbols"])
    assert any(item["code"] == "JAVA_TYPE_AMBIGUOUS" for item in facts["warnings"])


def test_whole_graph_retains_ambiguous_call_candidate_symbols(tmp_path):
    facts = _extract(tmp_path, {
        "Controller.java": """
            import org.springframework.web.bind.annotation.GetMapping;
            import org.springframework.web.bind.annotation.RestController;

            @RestController class Controller {
              private Mapper mapper;

              @GetMapping("/x")
              public Object entry(Object dto) {
                return mapper.map(dto);
              }
            }

            class Mapper {
              Object map(A dto) { return dto; }
              Object map(B dto) { return dto; }
            }

            class A {}
            class B {}
        """,
    })
    edge = next(
        edge for edge in facts["edges"].values()
        if edge["kind"] == "calls" and edge["resolution"] == "ambiguous")
    candidate_ids = set(edge["candidate_target_ids"])

    assert len(candidate_ids) == 2

    synthesis = Synthesis(
        tmp_path, DEFAULTS, SimpleNamespace(model="fixture"), record("Limits"))
    graph = synthesis.graph_scope(facts)

    assert edge["id"] in graph["context"]["edges"]
    assert candidate_ids <= set(graph["context"]["symbols"])
    assert graph["context"]["record_refs"] == {}


def test_tests_and_documentation_remain_distinct_supporting_relationships(tmp_path):
    facts = _extract(tmp_path, {
        "src/main/java/app/PetController.java": """
            package app;
            import org.springframework.web.bind.annotation.GetMapping;
            import org.springframework.web.bind.annotation.RestController;
            @RestController public class PetController {
              @GetMapping("/pets") public String listPets() { return "pets"; }
            }
        """,
        "src/test/java/app/PetControllerTest.java": """
            package app;
            public class PetControllerTest {
              private PetController controller;
              public void listsPets() { controller.listPets(); }
            }
        """,
        "README.md": "Use GET /pets to list pets through listPets.",
    })

    assert any(edge["kind"] == "tests_behavior" and edge["resolution"] == "resolved"
               for edge in facts["edges"].values())
    document_edge = next(edge for edge in facts["edges"].values()
                         if edge["kind"] == "documents_behavior")
    assert document_edge["from_ref"]["kind"] == "resource"
    assert document_edge["to_ref"]["kind"] == "anchor"
    assert facts["resources"][document_edge["from_ref"]["id"]]["name"] == "README.md"


def _source(path, language, text):
    return Source(path, language, text, digest(text.encode()), identifier("resource", path))


def test_contract_and_rule_adapters_declare_explicit_trace_contracts():
    api = _source("api.yaml", "yaml",
        "openapi: 3.0.1\npaths:\n  /visits:\n    post:\n      operationId: addVisit\n")
    contract = documents.extract(api)[0]
    assert (contract.trace_role, contract.required_relationships,
            contract.required_capabilities, contract.valid_terminal) == (
                "contract", ("implementation_selection",),
                ("entrypoint_detection", "relationship_resolution"), False)

    python = _source("service.py", "python", "@app.get('/leaf')\ndef leaf():\n    return 1\n")
    implementation = next(unit for unit in rules.extract(python) if unit.anchor_kind)
    assert (implementation.trace_role, implementation.required_relationships,
            implementation.required_capabilities, implementation.valid_terminal) == (
                "implementation", (), ("entrypoint_detection",), True)


def test_java_distinguishes_abstract_and_implementation_trace_roles():
    source = _source("Controller.java", "java", """
        @RestController abstract class Controller {
          abstract void pending();
          void leaf() {}
        }
    """)
    units = java_semantic.extract(source)
    pending = next(unit for unit in units if unit.name == "pending")
    leaf = next(unit for unit in units if unit.name == "leaf")
    assert pending.anchor_kind and pending.trace_role == "abstract_declaration"
    assert pending.required_relationships == ("implementation_selection",)
    assert pending.valid_terminal is False
    assert leaf.anchor_kind and leaf.trace_role == "implementation"
    assert leaf.required_relationships == () and leaf.valid_terminal is True


def test_spring_inherited_anchor_retains_implementation_terminal_contract():
    api = _source("PetsApi.java", "java", """
        package app;
        import org.springframework.web.bind.annotation.GetMapping;
        interface PetsApi { @GetMapping("/pets") String pets(); }
    """)
    controller = _source("PetController.java", "java", """
        package app;
        import org.springframework.web.bind.annotation.RestController;
        @RestController class PetController implements PetsApi {
          public String pets() { return "pets"; }
        }
    """)
    units = java_semantic.extract(api) + java_semantic.extract(controller)
    java_semantic.prepare([api, controller], units, [])
    spring_semantic.prepare([api, controller], units, [])
    method = next(unit for unit in units if unit.source is controller and unit.name == "pets")
    assert method.anchor_resolution == "resolved"
    assert (method.trace_role, method.required_relationships,
            method.required_capabilities, method.valid_terminal) == (
                "implementation", (), ("entrypoint_detection",), True)


# Phase 2A: an import the snapshot does not declare is a missing project type
# only under the project's own namespaces; anything else is a dependency.

def _heritage(facts, kind):
    """(origin, resolved target or the reason naming the parent, target kind) per edge."""
    return {(source.rsplit("::", 1)[-1],
             target if edge["to_ref"] and edge["to_ref"]["kind"] == "symbol" else edge["reason"],
             edge["to_ref"]["kind"] if edge["to_ref"] else None)
            for source, target, edge in _edge_names(facts, kind)}


def _codes(facts):
    return [warning["code"] for warning in facts["warnings"]]


def test_dependency_sharing_the_projects_first_segment_is_external(tmp_path):
    facts = _extract(tmp_path, {"src/org/acme/app/Api.java": """
        package org.acme.app;
        import org.springframework.core.Ordered;
        import org.springframework.http.HttpHeaders;
        public class Api implements Ordered {
          public void respond() {
            HttpHeaders headers = new HttpHeaders();
            headers.setLocation(null);
          }
        }
    """})

    [(_, reason, ref_kind)] = _heritage(facts, "implements")
    assert ref_kind == "resource" and "target Ordered is external" in reason
    call = next(edge for _, _, edge in _edge_names(facts, "calls")
                if "setLocation" in (edge["reason"] or ""))
    assert "setLocation is external" in call["reason"] and call["to_ref"]["kind"] == "resource"
    assert "JAVA_EXTERNAL_TYPE" in _codes(facts)
    assert "JAVA_TYPE_DECLARATION_UNAVAILABLE" not in _codes(facts)


def test_missing_type_under_the_projects_own_namespace_stays_unresolved(tmp_path):
    facts = _extract(tmp_path, {"src/org/acme/app/web/Page.java": """
        package org.acme.app.web;
        import org.acme.app.domain.MissingContract;
        public class Page implements MissingContract {}
    """})

    [(_, reason, ref_kind)] = _heritage(facts, "implements")
    assert ref_kind is None and "target MissingContract is unresolved" in reason
    assert "JAVA_TYPE_DECLARATION_UNAVAILABLE" in _codes(facts)
    assert "JAVA_EXTERNAL_TYPE" not in _codes(facts)


_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId></parent>
  <groupId>org.acme</groupId>
  <artifactId>shop</artifactId>
  {plugins}
</project>
"""
_GENERATOR = """<build><plugins><plugin>
  <artifactId>openapi-generator-maven-plugin</artifactId>
  <configuration><apiPackage>com.vendor.api</apiPackage><modelPackage>com.vendor.model</modelPackage></configuration>
</plugin></plugins></build>"""


def test_build_coordinates_and_generated_packages_are_project_namespaces(tmp_path):
    page = """
        package org.acme.app.web;
        import org.acme.billing.Invoice;
        import com.vendor.api.OrdersApi;
        import com.vendor.model.OrderDto;
        import org.springframework.boot.SpringApplication;
        public class Page implements Invoice, OrdersApi, OrderDto, SpringApplication {}
    """
    without_build = _extract(tmp_path / "plain", {"src/org/acme/app/web/Page.java": page})
    with_build = _extract(tmp_path / "maven", {
        "pom.xml": _POM.format(plugins=_GENERATOR),
        "src/org/acme/app/web/Page.java": page,
    })

    def classified(facts):
        return {edge["reason"].split(" target ")[1].split(" is ")[0]:
                ("external" if edge["to_ref"] else "unresolved")
                for _, _, edge in _edge_names(facts, "implements")}

    # The project's parent package (org.acme.app) does not cover org.acme.billing;
    # the Maven groupId does. Generated packages are the project's even outside
    # its own coordinates. The <parent> groupId (Spring Boot) never is.
    assert classified(without_build) == {
        "Invoice": "external", "OrdersApi": "external",
        "OrderDto": "external", "SpringApplication": "external"}
    assert classified(with_build) == {
        "Invoice": "unresolved", "OrdersApi": "unresolved",
        "OrderDto": "unresolved", "SpringApplication": "external"}


def test_com_project_classification_is_unchanged(tmp_path):
    facts = _extract(tmp_path, {"src/com/acme/app/Api.java": """
        package com.acme.app;
        import com.acme.app.domain.MissingContract;
        import org.springframework.http.HttpHeaders;
        public class Api implements MissingContract {
          public void respond() {
            HttpHeaders headers = new HttpHeaders();
            headers.setLocation(null);
          }
        }
    """})

    [(_, reason, ref_kind)] = _heritage(facts, "implements")
    assert ref_kind is None and "target MissingContract is unresolved" in reason
    call = next(edge for _, _, edge in _edge_names(facts, "calls")
                if "setLocation" in (edge["reason"] or ""))
    assert "setLocation is external" in call["reason"]


def test_petclinic_spring_data_repository_parent_is_external(tmp_path):
    base = "src/main/java/org/springframework/samples/petclinic"
    facts = _extract(tmp_path, {
        "pom.xml": _POM.format(plugins="").replace(
            "<groupId>org.acme</groupId>", "<groupId>org.springframework.samples</groupId>"),
        f"{base}/model/Owner.java": "package org.springframework.samples.petclinic.model;\npublic class Owner {}\n",
        f"{base}/repository/OwnerRepository.java": """
            package org.springframework.samples.petclinic.repository;
            import org.springframework.samples.petclinic.model.Owner;
            public interface OwnerRepository { void save(Owner owner); }
        """,
        f"{base}/repository/springdatajpa/SpringDataOwnerRepository.java": """
            package org.springframework.samples.petclinic.repository.springdatajpa;
            import org.springframework.data.repository.Repository;
            import org.springframework.samples.petclinic.model.Owner;
            import org.springframework.samples.petclinic.repository.OwnerRepository;
            public interface SpringDataOwnerRepository extends OwnerRepository, Repository<Owner, Integer> {}
        """,
    })

    parents = {(target.rsplit("::", 1)[-1] if ref == "symbol" else target, ref)
               for source, target, ref in _heritage(facts, "inherits")
               if source == "SpringDataOwnerRepository"}
    assert ("OwnerRepository", "symbol") in parents
    [(reason, _)] = [item for item in parents if item[1] == "resource"]
    assert "target Repository<Owner,Integer> is external" in reason
    assert not any(warning["code"] == "JAVA_TYPE_DECLARATION_UNAVAILABLE"
                   and "Repository" in warning["message"] for warning in facts["warnings"])


# Phase 2B: generic signature matching. A descendant's heritage supplies type
# arguments that are substituted for the declaring type's variables before the
# erased parameter lists are compared.

_ENTITIES = {
    "BaseEntity.java": "class BaseEntity {}\n",
    "Owner.java": "class Owner extends BaseEntity {}\n",
    "Pet.java": "class Pet extends BaseEntity {}\n",
}


def _selected(tmp_path, files, declaration):
    facts = _extract(tmp_path, {**_ENTITIES, **files})
    symbols = facts["symbols"]
    name_of = lambda symbol: symbols[symbol]["qualified_name"].split("::")[-1]
    edges = [edge for edge in facts["edges"].values() if edge["kind"] == "selects_implementation"
             and name_of(edge["from_ref"]["id"]) == declaration]
    if not edges:
        return []
    [edge] = edges
    return ([name_of(edge["to_ref"]["id"])] if edge["to_ref"]
            else sorted(map(name_of, edge["candidate_target_ids"])))


_GENERIC_REPOSITORY = "interface Repository<T> { T save(T value); }\n"


def test_type_argument_is_substituted_for_the_declaring_variable(tmp_path):
    assert _selected(tmp_path, {
        "Repository.java": _GENERIC_REPOSITORY,
        "OwnerRepository.java": """
            class OwnerRepository implements Repository<Owner> {
              public Owner save(Owner value) { return value; }
            }
        """,
    }, "Repository.save(T)") == ["OwnerRepository.save(Owner)"]


def test_incompatible_concrete_parameter_is_not_an_implementation(tmp_path):
    assert _selected(tmp_path, {
        "Repository.java": _GENERIC_REPOSITORY,
        "OwnerRepository.java": """
            class OwnerRepository implements Repository<Owner> {
              public Pet save(Pet value) { return value; }
            }
        """,
    }, "Repository.save(T)") == []


@pytest.mark.parametrize(("parameter", "expected"), [
    ("Object", ["RawRepository.save(Object)"]),
    ("Owner", []),
])
def test_raw_supertype_compares_by_erasure(tmp_path, parameter, expected):
    assert _selected(tmp_path, {
        "Repository.java": _GENERIC_REPOSITORY,
        "RawRepository.java": f"""
            class RawRepository implements Repository {{
              public Object save({parameter} value) {{ return value; }}
            }}
        """,
    }, "Repository.save(T)") == expected


@pytest.mark.parametrize(("parameter", "expected"), [
    ("Owner[] values", ["OwnerRepository.save(Owner[])"]),
    ("Owner values", []),
])
def test_substitution_keeps_array_depth(tmp_path, parameter, expected):
    assert _selected(tmp_path, {
        "Repository.java": "interface Repository<T> { void save(T[] values); }\n",
        "OwnerRepository.java": f"""
            class OwnerRepository implements Repository<Owner> {{
              public void save({parameter}) {{}}
            }}
        """,
    }, "Repository.save(T[])") == expected


@pytest.mark.parametrize(("heritage", "parameter", "expected"), [
    ("Repository", "BaseEntity", ["EntityRepository.save(BaseEntity)"]),
    ("Repository", "Owner", []),
    ("Repository<Owner>", "Owner", ["EntityRepository.save(Owner)"]),
    ("Repository<Owner>", "BaseEntity", []),
])
def test_bounded_variable_erases_to_its_bound(tmp_path, heritage, parameter, expected):
    assert _selected(tmp_path, {
        "Repository.java": "interface Repository<T extends BaseEntity> { void save(T value); }\n",
        "EntityRepository.java": f"""
            class EntityRepository implements {heritage} {{
              public void save({parameter} value) {{}}
            }}
        """,
    }, "Repository.save(T)") == expected


def test_method_level_type_variable_follows_override_rules(tmp_path):
    # <V> V convert(V) and the erased Object convert(Object) both override
    # <U> U convert(U); Owner convert(Owner) does not.
    assert _selected(tmp_path, {
        "Converter.java": "interface Converter { <U> U convert(U value); }\n",
        "GenericConverter.java": """
            class GenericConverter implements Converter {
              public <V> V convert(V value) { return value; }
            }
        """,
        "ErasedConverter.java": """
            class ErasedConverter implements Converter {
              public Object convert(Object value) { return value; }
            }
        """,
        "OwnerConverter.java": """
            class OwnerConverter implements Converter {
              public Owner convert(Owner value) { return value; }
            }
        """,
    }, "Converter.convert(U)") == ["ErasedConverter.convert(Object)", "GenericConverter.convert(V)"]


@pytest.mark.parametrize(("parameter", "expected"), [
    ("Owner", ["OwnerStore.save(Owner)"]),
    ("Pet", []),
])
def test_substitution_composes_through_a_generic_sub_interface(tmp_path, parameter, expected):
    assert _selected(tmp_path, {
        "Repository.java": _GENERIC_REPOSITORY,
        "Store.java": "interface Store<U> extends Repository<U> {}\n",
        "OwnerStore.java": f"""
            class OwnerStore implements Store<Owner> {{
              public {parameter} save({parameter} value) {{ return value; }}
            }}
        """,
    }, "Repository.save(T)") == expected


def test_implementation_inherited_from_a_generic_superclass(tmp_path):
    assert _selected(tmp_path, {
        "Repository.java": _GENERIC_REPOSITORY,
        "BaseRepository.java": """
            class BaseRepository<X> implements Repository<X> {
              public X save(X value) { return value; }
            }
        """,
        "OwnerRepository.java": "class OwnerRepository extends BaseRepository<Owner> {}\n",
    }, "Repository.save(T)") == ["BaseRepository.save(X)"]


# Phase 2C: implementations outside the analyzed source.

_PROCESSOR_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>org.acme</groupId><artifactId>shop</artifactId>
  <build><plugins><plugin><artifactId>maven-compiler-plugin</artifactId><configuration>
    <annotationProcessorPaths><path>
      <groupId>org.mapstruct</groupId><artifactId>mapstruct-processor</artifactId>
    </path></annotationProcessorPaths>
  </configuration></plugin></plugins></build>
</project>
"""
_MAPPER = """
package org.acme.mapper;
{imports}
{annotation}
public interface OwnerMapper {{
  OwnerDto toDto(Owner owner);
  default String label(Owner owner) {{ return "owner"; }}
}}
"""
_MAPPER_TYPES = {
    "src/org/acme/mapper/Owner.java": "package org.acme.mapper;\npublic class Owner {}\n",
    "src/org/acme/mapper/OwnerDto.java": "package org.acme.mapper;\npublic class OwnerDto {}\n",
}


def _selections_from(facts, declaration):
    """[(resolution, target kind, target name or candidates, edge)] for one declaration."""
    symbols = facts["symbols"]
    name_of = lambda symbol: symbols[symbol]["qualified_name"].split("::")[-1]
    rows = []
    for edge in facts["edges"].values():
        if edge["kind"] != "selects_implementation" or name_of(edge["from_ref"]["id"]) != declaration:
            continue
        if edge["to_ref"] and edge["to_ref"]["kind"] == "resource":
            rows.append((edge["resolution"], "resource", edge["to_ref"]["id"], edge))
        elif edge["to_ref"]:
            rows.append((edge["resolution"], "symbol", name_of(edge["to_ref"]["id"]), edge))
        else:
            rows.append((edge["resolution"], "candidates",
                         sorted(name_of(item) for item in edge["candidate_target_ids"]), edge))
    return sorted(rows, key=lambda row: row[:2])


def test_mapstruct_mapper_with_processor_is_a_generated_implementation(tmp_path):
    facts = _extract(tmp_path, {**_MAPPER_TYPES, "pom.xml": _PROCESSOR_POM,
        "src/org/acme/mapper/OwnerMapper.java": _MAPPER.format(
            imports="import org.mapstruct.Mapper;", annotation="@Mapper(uses = Object.class)")})

    [(resolution, kind, target, edge)] = _selections_from(facts, "OwnerMapper.toDto(Owner)")
    assert (resolution, kind) == ("unresolved", "resource")
    assert "MapStruct generates the implementation" in edge["reason"]
    assert "org.mapstruct:mapstruct-processor" in edge["reason"]
    excerpts = [facts["evidence"][item]["excerpt"] for item in edge["evidence_ids"]]
    assert any(excerpt.startswith("@Mapper") for excerpt in excerpts)
    assert any("mapstruct-processor" in excerpt for excerpt in excerpts)
    # A default method has its own body: MapStruct does not implement it.
    assert not any(kind == "resource" for _, kind, _, _ in _selections_from(facts, "OwnerMapper.label(Owner)"))
    assert "JAVA_GENERATED_IMPLEMENTATION" in [warning["code"] for warning in facts["warnings"]]


@pytest.mark.parametrize(("pom", "imports", "annotation"), [
    (False, "import org.mapstruct.Mapper;", "@Mapper"),          # no processor in the build
    (True, "import org.mapstruct.*;", "@Mapper"),                # name not proven by an import
    (True, "import org.acme.other.Mapper;", "@Mapper"),          # a different Mapper annotation
    (True, "", ""),                                              # a plain interface
])
def test_mapper_without_sufficient_evidence_is_not_generated(tmp_path, pom, imports, annotation):
    files = {**_MAPPER_TYPES, "src/org/acme/mapper/OwnerMapper.java":
             _MAPPER.format(imports=imports, annotation=annotation)}
    if pom:
        files["pom.xml"] = _PROCESSOR_POM
    facts = _extract(tmp_path, files)

    assert _selections_from(facts, "OwnerMapper.toDto(Owner)") == []
    assert "JAVA_GENERATED_IMPLEMENTATION" not in [warning["code"] for warning in facts["warnings"]]


_SPRING_DATA = "src/org/acme/repository"


def _repositories(extra):
    return {
        f"{_SPRING_DATA}/Owner.java": "package org.acme.repository;\npublic class Owner {}\n",
        f"{_SPRING_DATA}/OwnerRepository.java": """
            package org.acme.repository;
            public interface OwnerRepository {
              void save(Owner owner);
              Owner findById(int id);
            }
        """,
        f"{_SPRING_DATA}/SpringDataOwnerRepository.java": """
            package org.acme.repository;
            import org.springframework.context.annotation.Profile;
            import org.springframework.data.repository.Repository;
            @Profile("spring-data-jpa")
            public interface SpringDataOwnerRepository extends OwnerRepository, Repository<Owner, Integer> {
              Owner findByName(String name);
            }
        """,
        **extra,
    }


def test_spring_data_repository_methods_gain_an_external_runtime_implementation(tmp_path):
    facts = _extract(tmp_path, _repositories({}))

    for declaration in ("OwnerRepository.save(Owner)", "OwnerRepository.findById(int)",
                        "SpringDataOwnerRepository.findByName(String)"):
        [(resolution, kind, target, edge)] = _selections_from(facts, declaration)
        assert (resolution, kind) == ("unresolved", "resource")
        assert "Spring Data implements" in edge["reason"]
        assert "org.springframework.data.repository.Repository" in edge["reason"]
        # The evidence names the Spring Data parent in the extends clause.
        assert "Repository" in [facts["evidence"][item]["excerpt"] for item in edge["evidence_ids"]]
    assert "SPRING_DATA_RUNTIME_IMPLEMENTATION" in [warning["code"] for warning in facts["warnings"]]


def test_spring_data_candidate_sits_beside_source_implementations_without_narrowing(tmp_path):
    facts = _extract(tmp_path, _repositories({
        f"{_SPRING_DATA}/JdbcOwnerRepository.java": """
            package org.acme.repository;
            import org.springframework.context.annotation.Profile;
            @Profile("jdbc")
            public class JdbcOwnerRepository implements OwnerRepository {
              public void save(Owner owner) {}
              public Owner findById(int id) { return null; }
            }
        """,
        f"{_SPRING_DATA}/JpaOwnerRepository.java": """
            package org.acme.repository;
            import org.springframework.context.annotation.Profile;
            @Profile("jpa")
            public class JpaOwnerRepository implements OwnerRepository {
              public void save(Owner owner) {}
              public Owner findById(int id) { return null; }
            }
        """,
    }))

    # Every alternative names its @Profile, so the choice is configuration:
    # one conditional selection per alternative, the proxy's included.
    rows = _selections_from(facts, "OwnerRepository.save(Owner)")
    assert [(resolution, kind) for resolution, kind, _, _ in rows] == [
        ("resolved", "symbol"), ("resolved", "symbol"), ("unresolved", "resource")]
    assert [row[2] for row in rows[:2]] == ["JdbcOwnerRepository.save(Owner)",
                                            "JpaOwnerRepository.save(Owner)"]
    assert [row[3]["condition"].split(" on ")[0] for row in rows] == [
        '@Profile("jdbc")', '@Profile("jpa")', '@Profile("spring-data-jpa")']
    assert "JAVA_IMPLEMENTATION_AMBIGUOUS" not in [warning["code"] for warning in facts["warnings"]]


def test_an_alternative_without_a_profile_keeps_the_choice_ambiguous(tmp_path):
    facts = _extract(tmp_path, _repositories({
        f"{_SPRING_DATA}/JdbcOwnerRepository.java": """
            package org.acme.repository;
            import org.springframework.context.annotation.Profile;
            @Profile("jdbc")
            public class JdbcOwnerRepository implements OwnerRepository {
              public void save(Owner owner) {}
              public Owner findById(int id) { return null; }
            }
        """,
        f"{_SPRING_DATA}/JpaOwnerRepository.java": """
            package org.acme.repository;
            public class JpaOwnerRepository implements OwnerRepository {
              public void save(Owner owner) {}
              public Owner findById(int id) { return null; }
            }
        """,
    }))

    rows = _selections_from(facts, "OwnerRepository.save(Owner)")
    assert [(resolution, kind) for resolution, kind, _, _ in rows] == [
        ("ambiguous", "candidates"), ("unresolved", "resource")]
    assert rows[1][3]["condition"] is None


_FRAGMENT = {
    f"{_SPRING_DATA}/Pet.java": "package org.acme.repository;\npublic class Pet {}\n",
    f"{_SPRING_DATA}/PetRepository.java": """
        package org.acme.repository;
        public interface PetRepository {
          void save(Pet pet);
          void delete(Pet pet);
        }
    """,
    f"{_SPRING_DATA}/PetRepositoryOverride.java": """
        package org.acme.repository;
        public interface PetRepositoryOverride { void delete(Pet pet); }
    """,
    f"{_SPRING_DATA}/SpringDataPetRepository.java": """
        package org.acme.repository;
        import org.springframework.data.repository.Repository;
        public interface SpringDataPetRepository
            extends PetRepository, Repository<Pet, Integer>, PetRepositoryOverride {}
    """,
}


@pytest.mark.parametrize("implementation_name", ["SpringDataPetRepositoryImpl", "PetRepositoryOverrideImpl"])
def test_spring_data_fragment_is_a_source_implementation(tmp_path, implementation_name):
    facts = _extract(tmp_path, {**_FRAGMENT, f"{_SPRING_DATA}/{implementation_name}.java": f"""
        package org.acme.repository;
        public class {implementation_name} implements PetRepositoryOverride {{
          public void delete(Pet pet) {{}}
        }}
    """})

    assert [(resolution, kind, target) for resolution, kind, target, _ in
            _selections_from(facts, "PetRepository.delete(Pet)")] == [
        ("resolved", "symbol", f"{implementation_name}.delete(Pet)")]
    # Methods no fragment provides are still the runtime proxy's.
    assert [(resolution, kind) for resolution, kind, _, _ in
            _selections_from(facts, "PetRepository.save(Pet)")] == [("unresolved", "resource")]


def test_fragment_needs_spring_data_naming_to_be_routed(tmp_path):
    facts = _extract(tmp_path, {**_FRAGMENT, f"{_SPRING_DATA}/PetDeletion.java": """
        package org.acme.repository;
        public class PetDeletion implements PetRepositoryOverride { public void delete(Pet pet) {} }
    """})

    assert [(resolution, kind) for resolution, kind, _, _ in
            _selections_from(facts, "PetRepository.delete(Pet)")] == [("unresolved", "resource")]


def test_fragment_and_source_implementations_stay_ambiguous(tmp_path):
    facts = _extract(tmp_path, {**_FRAGMENT,
        f"{_SPRING_DATA}/SpringDataPetRepositoryImpl.java": """
            package org.acme.repository;
            public class SpringDataPetRepositoryImpl implements PetRepositoryOverride {
              public void delete(Pet pet) {}
            }
        """,
        f"{_SPRING_DATA}/JdbcPetRepository.java": """
            package org.acme.repository;
            public class JdbcPetRepository implements PetRepository {
              public void save(Pet pet) {}
              public void delete(Pet pet) {}
            }
        """,
    })

    rows = _selections_from(facts, "PetRepository.delete(Pet)")
    assert [(resolution, kind, target) for resolution, kind, target, _ in rows] == [
        ("ambiguous", "candidates", ["JdbcPetRepository.delete(Pet)", "SpringDataPetRepositoryImpl.delete(Pet)"])]
    assert "repository fragment" in rows[0][3]["reason"]


# Phase 2D: Spring evidence on implementation candidates. Evidence explains a
# selection; it never resolves one.

_APP = "src/org/acme/app"
_ORDER_TYPES = {
    f"{_APP}/Order.java": "package org.acme.app;\npublic class Order {}\n",
    f"{_APP}/OrderRepository.java": "package org.acme.app;\npublic interface OrderRepository { void save(Order order); }\n",
}


def _candidate(name, annotations="", imports=""):
    return {f"{_APP}/{name}.java": f"""
        package org.acme.app;
        {imports}
        {annotations}
        public class {name} implements OrderRepository {{
          public void save(Order order) {{}}
        }}
    """}


def _order_selection(tmp_path, *files):
    merged = dict(_ORDER_TYPES)
    for item in files:
        merged.update(item)
    facts = _extract(tmp_path, merged)
    # The static selection: a declared profile may add a separate conditioned
    # selection beside it, but never changes this one. When every candidate
    # names its @Profile the selection is one conditional path per candidate,
    # and the first (Jdbc) stands for them.
    rows = [row for row in _selections_from(facts, "OrderRepository.save(Order)")
            if row[3]["condition"] is None
            or row[3]["condition"].startswith("@Profile(")][:1]
    [(resolution, kind, target, edge)] = rows
    excerpts = [facts["evidence"][item]["excerpt"] for item in edge["evidence_ids"]]
    return resolution, target, edge, excerpts


@pytest.mark.parametrize("stereotype", ["Service", "Component", "Repository"])
def test_stereotype_is_candidate_evidence(tmp_path, stereotype):
    imports = f"import org.springframework.stereotype.{stereotype};"
    resolution, target, edge, excerpts = _order_selection(
        tmp_path, _candidate("JpaOrderRepository", f"@{stereotype}", imports),
        _candidate("JdbcOrderRepository", f"@{stereotype}", imports))

    assert resolution == "ambiguous"
    assert target == ["JdbcOrderRepository.save(Order)", "JpaOrderRepository.save(Order)"]
    assert f"JpaOrderRepository: @{stereotype}" in edge["reason"]
    assert f"@{stereotype}" in excerpts


def test_bean_method_is_candidate_evidence(tmp_path):
    resolution, target, edge, excerpts = _order_selection(tmp_path,
        _candidate("BeanOrderRepository"), _candidate("JdbcOrderRepository"),
        {f"{_APP}/OrderConfig.java": """
            package org.acme.app;
            import org.springframework.context.annotation.Bean;
            import org.springframework.context.annotation.Configuration;
            @Configuration
            public class OrderConfig {
              @Bean public OrderRepository orders() { return new BeanOrderRepository(); }
            }
        """})

    assert resolution == "ambiguous"
    assert "BeanOrderRepository: @Bean OrderConfig.orders()" in edge["reason"]
    assert "JdbcOrderRepository: no Spring stereotype or @Bean declaration" in edge["reason"]
    assert "@Bean" in excerpts


def test_primary_is_evidence_and_does_not_resolve_the_selection(tmp_path):
    imports = ("import org.springframework.context.annotation.Primary;\n"
               "import org.springframework.stereotype.Repository;")
    resolution, target, edge, excerpts = _order_selection(tmp_path,
        _candidate("JpaOrderRepository", "@Repository @Primary", imports),
        _candidate("JdbcOrderRepository", "@Repository", imports))

    assert resolution == "ambiguous" and len(target) == 2
    assert "JpaOrderRepository: @Repository, @Primary" in edge["reason"]
    assert "@Primary" in excerpts


def test_candidate_qualifier_is_evidence(tmp_path):
    imports = "import org.springframework.beans.factory.annotation.Qualifier;"
    resolution, target, edge, excerpts = _order_selection(tmp_path,
        _candidate("JpaOrderRepository", '@Qualifier("jpa")', imports),
        _candidate("JdbcOrderRepository", '@Qualifier("jdbc")', imports))

    assert resolution == "ambiguous"
    assert 'JpaOrderRepository: @Qualifier("jpa")' in edge["reason"]
    assert 'JdbcOrderRepository: @Qualifier("jdbc")' in edge["reason"]


def test_injection_point_qualifier_is_recorded_without_narrowing(tmp_path):
    resolution, target, edge, excerpts = _order_selection(tmp_path,
        _candidate("JpaOrderRepository"), _candidate("JdbcOrderRepository"),
        {f"{_APP}/OrderService.java": """
            package org.acme.app;
            import org.springframework.beans.factory.annotation.Qualifier;
            public class OrderService {
              @Qualifier("jpa") private final OrderRepository repository;
              OrderService(OrderRepository repository) { this.repository = repository; }
            }
        """})

    assert resolution == "ambiguous" and len(target) == 2
    assert 'injection points: @Qualifier("jpa") OrderRepository repository' in edge["reason"]
    assert any(excerpt.startswith('@Qualifier("jpa")') for excerpt in excerpts)


def test_profile_is_evidence_and_configuration_is_not_proof(tmp_path):
    imports = "import org.springframework.context.annotation.Profile;"
    resolution, target, edge, excerpts = _order_selection(tmp_path,
        _candidate("JpaOrderRepository", '@Profile("jpa")', imports),
        _candidate("JdbcOrderRepository", '@Profile("jdbc")', imports),
        {"src/main/resources/application.properties": "spring.profiles.active=jpa\n"})

    assert resolution == "resolved" and target == "JdbcOrderRepository.save(Order)"
    assert edge["condition"].startswith('@Profile("jdbc") on JdbcOrderRepository')
    assert '@Profile("jdbc")' in excerpts
    # The declared profile conditions its alternative; the property is a
    # default a runtime override can change, so it is a condition, not proof,
    # and the other alternative stays a path.
    facts = _extract(tmp_path, {**_ORDER_TYPES,
        **_candidate("JpaOrderRepository", '@Profile("jpa")', imports),
        **_candidate("JdbcOrderRepository", '@Profile("jdbc")', imports),
        "src/main/resources/application.properties": "spring.profiles.active=jpa\n"})
    rows = _selections_from(facts, "OrderRepository.save(Order)")
    assert [(resolution, target) for resolution, _, target, _ in rows] == [
        ("resolved", "JdbcOrderRepository.save(Order)"), ("resolved", "JpaOrderRepository.save(Order)")]
    edge = rows[1][3]
    assert "spring.profiles.active=jpa" in edge["condition"]
    assert "runtime profile override" in edge["condition"]
    assert 'JdbcOrderRepository (@Profile("jdbc"))' in edge["condition"]


def test_candidate_without_stereotype_is_kept(tmp_path):
    imports = "import org.springframework.stereotype.Repository;"
    resolution, target, edge, excerpts = _order_selection(tmp_path,
        _candidate("JpaOrderRepository", "@Repository", imports),
        _candidate("PlainOrderRepository"))

    assert target == ["JpaOrderRepository.save(Order)", "PlainOrderRepository.save(Order)"]
    assert "PlainOrderRepository: no Spring stereotype or @Bean declaration" in edge["reason"]


def test_single_spring_candidate_keeps_its_exact_selection(tmp_path):
    resolution, target, edge, excerpts = _order_selection(tmp_path, _candidate(
        "JpaOrderRepository", "@Service", "import org.springframework.stereotype.Service;"))

    assert (resolution, target, edge["reason"]) == ("resolved", "JpaOrderRepository.save(Order)", None)
    assert "@Service" in excerpts


def test_spring_data_runtime_candidate_gains_its_profile(tmp_path):
    facts = _extract(tmp_path, _repositories({}))

    [(resolution, kind, _, edge)] = _selections_from(facts, "OwnerRepository.save(Owner)")
    assert (resolution, kind) == ("unresolved", "resource")
    assert 'SpringDataOwnerRepository: @Profile("spring-data-jpa")' in edge["reason"]
    assert '@Profile("spring-data-jpa")' in [facts["evidence"][item]["excerpt"] for item in edge["evidence_ids"]]


def test_spring_evidence_is_deterministic(tmp_path):
    imports = ("import org.springframework.context.annotation.Profile;\n"
               "import org.springframework.stereotype.Repository;")
    files = [_candidate("JpaOrderRepository", '@Repository @Profile("jpa")', imports),
             _candidate("JdbcOrderRepository", '@Repository @Profile("jdbc")', imports)]
    first = _order_selection(tmp_path / "first", *files)
    second = _order_selection(tmp_path / "second", *reversed(files))

    assert first[2]["condition"] == second[2]["condition"]
    assert sorted(first[3]) == sorted(second[3])


def test_spring_evidence_does_not_change_selection_edge_identity(tmp_path):
    # OwnerRepository.save has an ambiguous source edge and an external Spring
    # Data edge on the same declaration span; evidence must not rename either.
    def implementations(annotated):
        return {f"{_SPRING_DATA}/{name}OwnerRepository.java": f"""
            package org.acme.repository;
            {"import org.springframework.stereotype.Repository;" if annotated else ""}
            {"@Repository" if annotated else ""}
            public class {name}OwnerRepository implements OwnerRepository {{
              public void save(Owner owner) {{}}
              public Owner findById(int id) {{ return null; }}
            }}
        """ for name in ("Jdbc", "Jpa")}

    def selection_ids(root, annotated):
        files = _repositories(implementations(annotated))
        if not annotated:
            path = f"{_SPRING_DATA}/SpringDataOwnerRepository.java"
            files[path] = files[path].replace('@Profile("spring-data-jpa")', "")
        facts = _extract(root, files)
        return sorted(edge["id"] for _, _, _, edge in _selections_from(facts, "OwnerRepository.save(Owner)"))

    plain, explained = selection_ids(tmp_path / "plain", False), selection_ids(tmp_path / "explained", True)
    assert len(plain) == 2 and plain == explained


# Inherited methods: a call resolves against the receiver type and, nearest
# first, the project supertypes it inherits from.

def _call_targets(facts, caller):
    return sorted((right, edge["resolution"]) for left, right, edge in _edge_names(facts, "calls")
                  if caller in left)


ENTITIES = {
    "src/model/BaseEntity.java": """
        package model;
        public class BaseEntity {
          public Integer getId() { return 1; }
          public String describe() { return "base"; }
          public String find(String value) { return value; }
        }
    """,
    "src/model/Person.java": """
        package model;
        public class Person extends BaseEntity {
          public String getFirstName() { return "Ann"; }
          @Override public String describe() { return "person"; }
        }
    """,
    "src/model/Owner.java": """
        package model;
        public class Owner extends Person {
          public String find(int value) { return String.valueOf(value); }
        }
    """,
}


def test_inherited_superclass_methods_resolve_through_the_chain(tmp_path):
    facts = _extract(tmp_path, {**ENTITIES, "src/app/Use.java": """
        package app;
        import model.Owner;
        public class Use {
          public Object id(Owner owner) { return owner.getId(); }
          public Object first(Owner owner) { return owner.getFirstName(); }
        }
    """})
    assert _call_targets(facts, "Use.id") == [("src/model/BaseEntity.java::BaseEntity.getId()", "resolved")]
    assert _call_targets(facts, "Use.first") == [("src/model/Person.java::Person.getFirstName()", "resolved")]


def test_nearest_override_wins_and_overloads_span_the_hierarchy(tmp_path):
    facts = _extract(tmp_path, {**ENTITIES, "src/app/Use.java": """
        package app;
        import model.Owner;
        public class Use {
          public Object text(Owner owner) { return owner.describe(); }
          public Object byNumber(Owner owner) { return owner.find(42); }
          public Object byName(Owner owner) { return owner.find("x"); }
        }
    """})
    assert _call_targets(facts, "Use.text") == [("src/model/Person.java::Person.describe()", "resolved")]
    assert _call_targets(facts, "Use.byNumber") == [("src/model/Owner.java::Owner.find(int)", "resolved")]
    assert _call_targets(facts, "Use.byName") == [("src/model/BaseEntity.java::BaseEntity.find(String)", "resolved")]


def test_interface_methods_resolve_through_extended_interfaces_and_defaults(tmp_path):
    facts = _extract(tmp_path, {
        "src/app/Base.java": "package app; public interface Base { String ping(); }",
        "src/app/Sub.java": "package app; public interface Sub extends Base {}",
        "src/app/Greeter.java": "package app; public interface Greeter { default String hi() { return \"hi\"; } }",
        "src/app/Polite.java": "package app; public class Polite implements Greeter {}",
        "src/app/Use.java": """
            package app;
            public class Use {
              public String ping(Sub sub) { return sub.ping(); }
              public String hi(Polite polite) { return polite.hi(); }
            }
        """,
    })
    assert _call_targets(facts, "Use.ping") == [("src/app/Base.java::Base.ping()", "resolved")]
    assert _call_targets(facts, "Use.hi") == [("src/app/Greeter.java::Greeter.hi()", "resolved")]


def test_methods_inherited_from_a_generic_supertype_resolve(tmp_path):
    facts = _extract(tmp_path, {
        "src/app/Item.java": "package app; public class Item {}",
        "src/app/Store.java": "package app; public class Store<T> { public void save(T value) {} }",
        "src/app/ItemStore.java": "package app; public class ItemStore extends Store<Item> {}",
        "src/app/Use.java": """
            package app;
            public class Use {
              public void keep(ItemStore store, Item item) { store.save(item); }
            }
        """,
    })
    assert _call_targets(facts, "Use.keep") == [("src/app/Store.java::Store.save(T)", "resolved")]


def test_a_method_no_project_type_declares_stays_unresolved(tmp_path):
    facts = _extract(tmp_path, {**ENTITIES,
        "src/app/Loop.java": "package app; public class Loop extends Knot {}",
        "src/app/Knot.java": "package app; public class Knot extends Loop {}",
        "src/app/Use.java": """
            package app;
            import model.Owner;
            public class Use {
              public Object missing(Owner owner) { return owner.missing(); }
              public Object cycle(Loop loop) { return loop.spin(); }
            }
        """})
    assert all(resolution == "unresolved" for _, resolution in
               _call_targets(facts, "Use.missing") + _call_targets(facts, "Use.cycle"))


def test_annotated_superclass_is_recognised_and_its_methods_inherited(tmp_path):
    # PetClinic's shape: @MappedSuperclass ends in "class", which once named the
    # base class after the next word ("public"), leaving it out of the hierarchy.
    facts = _extract(tmp_path, {
        "src/model/BaseEntity.java": """
            package model;
            @MappedSuperclass
            public class BaseEntity {
              public Integer getId() { return 1; }
            }
        """,
        "src/model/Pet.java": "package model; public class Pet extends BaseEntity {}",
        "src/app/Use.java": """
            package app;
            import model.Pet;
            public class Use {
              public Object id(Pet pet) { return pet.getId(); }
            }
        """,
    })
    assert ("src/model/Pet.java::Pet", "src/model/BaseEntity.java::BaseEntity") in [
        (left, right) for left, right, edge in _edge_names(facts, "inherits")
        if edge["resolution"] == "resolved"]
    assert _call_targets(facts, "Use.id") == [("src/model/BaseEntity.java::BaseEntity.getId()", "resolved")]


# ── F1: Spring property conditions link to repository declarations ──────

import json as _json

_CONDITION_IMPORT = 'import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;\n'
_MAIN_PROPERTIES = 'src/main/resources/application.properties'


def _configuration_class(annotation, imports=_CONDITION_IMPORT, name='SecurityConfig',
                         path='src/main/java/demo'):
    return {f'{path}/{name}.java': f'package demo;\n{imports}{annotation}\npublic class {name} {{}}\n'}


def _conditions(facts):
    return sorted((item for item in facts['rule_observations'].values()
                   if item['source_location_kind'] == 'configuration'),
                  key=lambda item: item['native_expression'])


def _linked(facts, observation):
    return sorted((facts['bindings'][bid]['expression'],
                   facts['bindings'][bid]['scope']['environment'])
                  for bid in observation['input_binding_ids'])


def test_production_conditions_link_only_to_the_main_unprofiled_declaration(tmp_path):
    facts = _extract(tmp_path, {
        _MAIN_PROPERTIES: 'petclinic.security.enable=false\n',
        'src/main/resources/application-prod.properties': 'petclinic.security.enable=true\n',
        'src/test/resources/application.properties': 'petclinic.security.enable=true\n',
        'src/main/resources/messages/messages.properties': 'petclinic.security.enable=x\n',
        **_configuration_class(
            '@ConditionalOnProperty(name = "petclinic.security.enable", havingValue = "true")',
            name='BasicAuthenticationConfig'),
        **_configuration_class(
            '@ConditionalOnProperty(name = "petclinic.security.enable", havingValue = "false")',
            name='DisableSecurityConfig'),
    })
    true_condition, false_condition = _conditions(facts)[::-1]
    assert false_condition['native_expression'] == 'property["petclinic.security.enable"] == "false"'
    assert true_condition['native_expression'] == 'property["petclinic.security.enable"] == "true"'
    for observation in (true_condition, false_condition):
        assert _linked(facts, observation) == [('false', 'main')]
        assert observation['resolution'] == 'unresolved'
        assert observation['scope']['environment'] == 'main'
        assert 'effective deployment precedence was not evaluated' in observation['reason']
        for evidence_id in observation['evidence_ids']:
            assert evidence_id in facts['evidence']
    assert true_condition['id'] != false_condition['id']


def test_test_consumers_keep_main_and_test_candidates(tmp_path):
    facts = _extract(tmp_path, {
        _MAIN_PROPERTIES: 'feature.on=false\n',
        'src/test/resources/application.properties': 'feature.on=true\n',
        **_configuration_class('@ConditionalOnProperty("feature.on")',
                               path='src/test/java/demo'),
    })
    [observation] = _conditions(facts)
    assert _linked(facts, observation) == [('false', 'main'), ('true', 'test')]
    assert observation['native_expression'] == 'property["feature.on"] is present and not false'


@pytest.mark.parametrize('annotation, expressions', [
    ('@ConditionalOnProperty(prefix = "app", name = {"a", "b"}, havingValue = "on", '
     'matchIfMissing = true)',
     ['property["app.a"] == "on" or missing', 'property["app.b"] == "on" or missing']),
    ('@ConditionalOnProperty(prefix = "app.", value = "a")',
     ['property["app.a"] is present and not false']),
    ('@ConditionalOnProperty(name = "caf\\u00e9")',
     ['property["café"] is present and not false']),
])
def test_condition_normalization(tmp_path, annotation, expressions):
    facts = _extract(tmp_path, {_MAIN_PROPERTIES: 'app.a=1\napp.b=2\ncafé=3\n',
                                **_configuration_class(annotation)})
    observations = _conditions(facts)
    assert [item['native_expression'] for item in observations] == expressions
    assert all(item['input_binding_ids'] for item in observations)


@pytest.mark.parametrize('annotation, cause', [
    ('@ConditionalOnProperty(name = KEY)', 'ordinary_string_literal_required'),
    ('@ConditionalOnProperty(name = "a" + "b")', 'unescaped_quote'),
    ('@ConditionalOnProperty(name = "a", value = "b")', 'exactly_one_of_name_or_value_is_required'),
    ('@ConditionalOnProperty(havingValue = "x")', 'exactly_one_of_name_or_value_is_required'),
    ('@ConditionalOnProperty(name = "a", matchIfMissing = FLAG)',
     'matchIfMissing_must_be_boolean_literal'),
    ('@ConditionalOnProperty(name = "a", unknown = "b")', 'unsupported_conditional_property_argument'),
])
def test_dynamic_or_invalid_conditions_have_evidenced_diagnostics(tmp_path, annotation, cause):
    facts = _extract(tmp_path, {_MAIN_PROPERTIES: 'a=1\n', **_configuration_class(annotation)})
    assert not _conditions(facts)
    [warning] = [w for w in facts['warnings']
                 if w['code'] == 'SPRING_PROPERTY_CONDITION_UNAVAILABLE']
    assert warning['message'] == cause and warning['evidence_ids']


def test_condition_without_a_matching_declaration_is_kept_and_diagnosed(tmp_path):
    facts = _extract(tmp_path, _configuration_class('@ConditionalOnProperty("missing.key")'))
    [observation] = _conditions(facts)
    assert observation['input_binding_ids'] == []
    assert any(w['message'] == 'matching_repository_declaration_unavailable'
               for w in facts['warnings'])


def test_profiled_and_message_declarations_never_link(tmp_path):
    facts = _extract(tmp_path, {
        'src/main/resources/application-prod.properties': 'k=1\n',
        'src/main/resources/messages.properties': 'k=2\n',
        **_configuration_class('@ConditionalOnProperty("k")'),
    })
    [observation] = _conditions(facts)
    assert observation['input_binding_ids'] == []


@pytest.mark.parametrize('annotation, imports, active', [
    ('@ConditionalOnProperty("k")', _CONDITION_IMPORT, True),
    ('@ConditionalOnProperty("k")',
     'import org.springframework.boot.autoconfigure.condition.*;\n', True),
    ('@org.springframework.boot.autoconfigure.condition.ConditionalOnProperty("k")', '', True),
    ('@ConditionalOnProperty("k")', 'import other.ConditionalOnProperty;\n', False),
    ('@ConditionalOnProperty("k")', '', False),
])
def test_spring_activation_requires_exact_evidence(tmp_path, annotation, imports, active):
    facts = _extract(tmp_path, {_MAIN_PROPERTIES: 'k=1\n',
                                **_configuration_class(annotation, imports)})
    assert bool(_conditions(facts)) is active


def test_sensitive_condition_values_never_persist(tmp_path):
    facts = _extract(tmp_path, {
        _MAIN_PROPERTIES: 'db.password=alpha beta\n',
        **_configuration_class('@ConditionalOnProperty(name = "db.password", '
                               'havingValue = "alpha beta")'),
        **_configuration_class('@ConditionalOnProperty(name = KEY, havingValue = "gamma delta")',
                               name='Dynamic'),
        **_configuration_class('@ConditionalOnProperty(prefix = PREFIX, name = "db.password", '
                               'havingValue = "epsilon zeta")', name='Prefixed'),
    })
    [observation] = _conditions(facts)
    assert observation['native_expression'] == '[REDACTED]'
    snapshots = ''.join(path.read_text() for path in
        (tmp_path / '.speed/context/business-domain-snapshots').glob('*.json'))
    persisted = _json.dumps(facts) + snapshots
    for secret in ('alpha beta', 'gamma delta', 'epsilon zeta'):
        assert secret not in persisted


def test_observation_binding_projection_is_all_or_nothing(tmp_path, monkeypatch):
    from lib.context.business_domain_schema import DomainError
    original = java_semantic.observations

    def partial(unit):
        return [{**item, 'binding_name': item.get('binding_name', 'x')}
                for item in original(unit)
                if item.get('source_location_kind') != 'configuration'] + [
            {'span': (0, 1), 'source_location_kind': 'configuration',
             'native_expression': 'x', 'binding_name': 'x'}]
    monkeypatch.setattr(java_semantic, 'observations', partial)
    with pytest.raises(DomainError, match='observation_binding_projection_incomplete'):
        _extract(tmp_path, _configuration_class('@Deprecated'))


@pytest.mark.parametrize('token, expected', [
    ('"plain"', 'plain'),
    ('"caf\\u00e9"', 'café'),
    ('"\\uuuu0041"', 'A'),
    ('"a\\u0022b"', None),
    ('"\\u005c\\u005c"', '\\'),
    ('"\\t\\b\\n\\f\\r\\s\\"\\\'\\\\"', '\t\b\n\f\r "\'\\'),
    ('"\\0\\101\\477\\8"', None),
    ('"\\101\\477"', 'A\x277'),
    ('"\\ud83d\\ude00"', '😀'),
    ('"\\ude00"', None),
    ('"\\ude00\\ud83d"', None),
    ('"""text"""', None),
    ('"a\nb"', None),
    ('CONSTANT', None),
    ('"a" + "b"', None),
    ('call()', None),
])
def test_java_string_literals_decode_exactly(token, expected):
    if expected is None:
        with pytest.raises(java_semantic.JavaLiteralError):
            java_semantic._decode_java_string_literal(token)
    else:
        assert java_semantic._decode_java_string_literal(token) == expected


def test_empty_having_value_means_present_and_not_false(tmp_path):
    facts = _extract(tmp_path, {_MAIN_PROPERTIES: 'app.feature=on\n', **_configuration_class(
        '@ConditionalOnProperty(name = "app.feature", havingValue = "")')})
    [observation] = _conditions(facts)
    assert observation['native_expression'] == 'property["app.feature"] is present and not false'


def test_conditions_link_declarations_through_relaxed_binding(tmp_path):
    facts = _extract(tmp_path, {_MAIN_PROPERTIES: 'app.featureEnabled=true\n', **_configuration_class(
        '@ConditionalOnProperty(prefix = "app", name = "feature-enabled")')})
    [observation] = _conditions(facts)
    assert _linked(facts, observation) == [('true', 'main')]
    assert not [w for w in facts['warnings']
                if w['code'] == 'SPRING_PROPERTY_CONDITION_UNAVAILABLE']
