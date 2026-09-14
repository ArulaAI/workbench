"""Java/Spring semantic adapter conformance and PetClinic regressions."""
from pathlib import Path
from types import SimpleNamespace

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
