"""F-04 semantic trace completion conformance."""
from types import SimpleNamespace

import pytest

from lib.context import business_domain_extract as core
from lib.context.business_domain_adapters.base import Unit
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, DomainError, copy_facts, record, validate_references,
)
from lib.context.business_domain_work import whole_graph_scope
from lib.context.business_domains import accept_candidate
from tests.business_domains.adapter_fixture import install_fixture_adapter


def _selection_facts(tmp_path, monkeypatch, *, language="fixture",
                     implementations=1, produce=True,
                     relationship_capability="supported"):
    state = {}

    def extract(source):
        if source.text == "contract":
            unit = Unit(source, "entry", source.path + "::entry", 0, len(source.text),
                "declarative_operation", anchor_kind="workflow",
                anchor_resolution="resolved", trace_role="contract",
                required_relationships=("implementation_selection",),
                required_capabilities=("entrypoint_detection", "relationship_resolution"),
                valid_terminal=False)
            state["contract"] = unit
        else:
            unit = Unit(source, source.path, source.path + "::body", 0, len(source.text),
                "function", executable_body=True, trace_role="implementation",
                required_relationships=(), required_capabilities=(), valid_terminal=True)
            state.setdefault("implementations", []).append(unit)
        source.units = [unit]
        return [unit]

    def prepare(sources, units, diagnostics):
        for source in sources:
            source.semantic_relations = []
        if not produce:
            return
        contract = state["contract"]
        targets = state["implementations"]
        relation = {
            "source": contract,
            "target": targets[0] if len(targets) == 1 else None,
            "candidate_targets": [] if len(targets) == 1 else targets,
            "kind": "selects_implementation", "start": 0, "end": len(contract.source.text),
            "resolution": "resolved" if len(targets) == 1 else "ambiguous",
            "outcome": "exact" if len(targets) == 1 else "ambiguous",
            "reason": None if len(targets) == 1 else "Two implementation bodies remain viable.",
            "diagnostic_code": None if len(targets) == 1 else "IMPLEMENTATION_AMBIGUOUS",
        }
        contract.source.semantic_relations.append(relation)

    adapter = SimpleNamespace(
        extract=extract, prepare=prepare,
        relations=lambda source: source.semantic_relations,
        bindings=lambda unit: [], resources=lambda unit: [], calls=lambda unit: [],
        observations=lambda unit: [], operations=lambda unit: [],
        activation_evidence=lambda source: {},
    )
    capabilities = {
        "entrypoint_detection": "supported",
        "relationship_resolution": relationship_capability,
    }
    install_fixture_adapter(monkeypatch, adapter, {
        "language": language, "source_kind": "source", "adapter": "fixture",
        "capability": {"id": "fixture", "version": "1", "capabilities": capabilities,
                       "diagnostic_codes": ["FIXTURE_CAPABILITY_UNAVAILABLE"]},
    })
    (tmp_path / "contract.opaque").write_text("contract")
    for index in range(implementations):
        (tmp_path / f"body{index}.opaque").write_text(f"body {index}")
    facts, units = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    trace = next(iter(facts["traces"].values()))
    obligations = [facts["trace_obligations"][key] for key in trace["obligation_ids"]]
    return facts, units, trace, obligations


def test_anchor_adapter_must_declare_complete_trace_contract(tmp_path, monkeypatch):
    adapter = SimpleNamespace(
        extract=lambda source: [Unit(source, "entry", "entry", 0, len(source.text),
            "function", anchor_kind="workflow", anchor_resolution="resolved",
            executable_body=True)],
        bindings=lambda unit: [], resources=lambda unit: [], calls=lambda unit: [],
        observations=lambda unit: [], operations=lambda unit: [],
        activation_evidence=lambda source: {},
    )
    install_fixture_adapter(monkeypatch, adapter, {
        "language": "fixture", "source_kind": "source", "adapter": "fixture"})
    (tmp_path / "source.opaque").write_text("entry")
    with pytest.raises(DomainError, match="trace role"):
        Extractor(tmp_path, DEFAULTS).extract()


def test_exhausted_graph_remains_unresolved_when_implementation_is_missing(tmp_path, monkeypatch):
    _, _, trace, obligations = _selection_facts(
        tmp_path, monkeypatch, implementations=1, produce=False)

    assert trace["traversal_complete"] is True
    assert trace["resolution"] == "unresolved"
    assert any(item["reason_code"] == "IMPLEMENTATION_NOT_REACHED"
               for item in obligations)


def test_exact_selection_resolves_and_removing_producer_creates_obligation(tmp_path, monkeypatch):
    facts, units, trace, obligations = _selection_facts(tmp_path, monkeypatch)
    implementation = next(unit for unit in units if unit.trace_role == "implementation")

    assert trace["traversal_complete"] is True and trace["resolution"] == "resolved"
    assert implementation.symbol_id in trace["symbol_ids"]
    assert any(item["kind"] == "implementation_selection"
               and item["status"] == "satisfied" for item in obligations)


@pytest.mark.parametrize("language", ["java", "python"])
def test_ambiguous_implementations_have_same_bounded_outcome_across_languages(
        tmp_path, monkeypatch, language):
    facts, _, trace, obligations = _selection_facts(
        tmp_path, monkeypatch, language=language, implementations=2)
    selection = next(item for item in obligations
                     if item["kind"] == "implementation_selection")

    assert trace["traversal_complete"] is True and trace["resolution"] == "ambiguous"
    assert selection["status"] == "ambiguous"
    assert 2 <= len(selection["candidate_target_ids"]) <= 8
    assert set(selection["candidate_target_ids"]) <= set(facts["symbols"])


def test_declaring_adapter_gap_does_not_block_selected_implementation_in_graph(
        tmp_path, monkeypatch):
    facts, _, trace, obligations = _selection_facts(
        tmp_path, monkeypatch, relationship_capability="unsupported")
    graph = whole_graph_scope(facts)

    assert trace["traversal_complete"] is True and trace["resolution"] == "resolved"
    assert not any(item["reason_code"] == "CAPABILITY_UNAVAILABLE"
                   for item in obligations)
    assert graph["context"]["capabilities"] == facts["capabilities"]
    assert graph["context"]["trace_obligations"] == facts["trace_obligations"]
    assert graph["context"]["traces"][trace["id"]]["stop_reasons"] == []


def test_supported_activity_cannot_claim_obligation_incomplete_trace(tmp_path, monkeypatch):
    facts, _, trace, _ = _selection_facts(
        tmp_path, monkeypatch, implementations=1, produce=False)
    model = copy_facts(facts, facts["build_id"])
    graph = whole_graph_scope(model)
    evidence = list(graph["context"]["evidence"])
    activity = record("Activity", id="activity:fixture", name="Fixture",
        description="Overstated", anchor_ids=[trace["anchor_id"]],
        trace_ids=[trace["id"]], evidence_ids=evidence,
        claim_ids=["claim:fixture"], support="supported")
    payload = record("CandidatePayload", scope_id=graph["scope_id"],
        input_fingerprint=graph["input_fingerprint"],
        activities={activity["id"]: activity},
        claims={"claim:fixture": record("Claim", id="claim:fixture",
            subject_id=activity["id"], text="Overstated", kind="behavior",
            evidence_ids=evidence, trace_ids=[trace["id"]],
            semantic_review="uncertain")},
        dispositions=[record("ScopeDisposition", id="disposition:fixture",
            subject_kind="anchor", subject_id=trace["anchor_id"],
            status="represented", activity_ids=[activity["id"]])])

    with pytest.raises(DomainError, match="resolved implementation"):
        accept_candidate(model, graph, payload)


@pytest.mark.parametrize(("filename", "text"), [
    ("service.py", "@app.get('/leaf')\ndef leaf():\n    return 1\n"),
    ("Controller.java", """
        import org.springframework.web.bind.annotation.RestController;
        import org.springframework.web.bind.annotation.GetMapping;
        @RestController class Controller {
          @GetMapping("/leaf") public void leaf() {}
        }
    """),
])
def test_java_and_non_java_concrete_leaf_share_terminal_outcome(tmp_path, filename, text):
    (tmp_path / filename).write_text(text)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    trace = next(iter(facts["traces"].values()))

    assert trace["traversal_complete"] is True and trace["resolution"] == "resolved"
    selection = next(facts["trace_obligations"][key] for key in trace["obligation_ids"]
                     if facts["trace_obligations"][key]["kind"] == "implementation_selection")
    assert selection["status"] == "satisfied"


@pytest.mark.parametrize(("filename", "text"), [
    ("api.yaml", "openapi: 3.0.1\npaths:\n  /pending:\n    get:\n      operationId: pending\n"),
    ("Controller.java", """
        import org.springframework.web.bind.annotation.RestController;
        import org.springframework.web.bind.annotation.GetMapping;
        @RestController abstract class Controller {
          @GetMapping("/pending") public abstract void pending();
        }
    """),
])
def test_java_and_non_java_declarations_require_implementation(
        tmp_path, filename, text):
    (tmp_path / filename).write_text(text)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    trace = next(iter(facts["traces"].values()))
    obligations = [facts["trace_obligations"][key] for key in trace["obligation_ids"]]

    assert trace["traversal_complete"] is True and trace["resolution"] == "unresolved"
    assert any(item["reason_code"] == "IMPLEMENTATION_NOT_REACHED"
               for item in obligations)


@pytest.mark.parametrize(("filename", "text"), [
    ("Form.tsx", """
        function send() { return fetch('/external'); }
        export default () => <button onClick={send}>Send</button>;
    """),
    ("Controller.java", """
        import org.springframework.web.bind.annotation.RestController;
        import org.springframework.web.bind.annotation.GetMapping;
        import java.time.Clock;
        @RestController class Controller {
          private Clock clock;
          @GetMapping("/external") public long external() {
            return clock.millis();
          }
        }
    """),
])
def test_java_and_non_java_external_boundaries_are_explicit(
        tmp_path, filename, text):
    (tmp_path / filename).write_text(text)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    trace = next(iter(facts["traces"].values()))
    obligations = [facts["trace_obligations"][key] for key in trace["obligation_ids"]]

    assert trace["traversal_complete"] is True and trace["resolution"] == "unresolved"
    assert "external_boundary" in trace["stop_reasons"]
    assert any(item["kind"] == "external_boundary" and item["status"] == "external"
               for item in obligations)


def test_symbol_limit_is_visible_and_cannot_resolve_trace(tmp_path):
    (tmp_path / "service.py").write_text("""
@app.get('/start')
def start():
    middle()
def middle():
    finish()
def finish():
    return 1
""")
    facts, _ = Extractor(tmp_path, {**DEFAULTS, "max_symbols_per_activity": 1}).extract()
    validate_references(facts)
    trace = next(iter(facts["traces"].values()))
    obligations = [facts["trace_obligations"][key] for key in trace["obligation_ids"]]

    assert trace["traversal_complete"] is False and trace["resolution"] == "unresolved"
    assert trace["stop_reasons"] == ["symbol_limit"]
    assert any(item["kind"] == "symbol_limit" and item["status"] == "limit_reached"
               for item in obligations)


# Interface -> implementation dispatch reached mid-trace. The entry point is a
# concrete controller method; the declaration its call lands on is selected
# through the Java adapter's selects_implementation relationships.

_ORDER = "class Order {}\n"
_CONTROLLER = """
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
@RestController class OrderController {
  private final OrderService service;
  OrderController(OrderService service) { this.service = service; }
  @PostMapping("/orders") public void create(Order order) { this.service.save(order); }
}
"""


def _dispatch_trace(tmp_path, files):
    for name, content in {"Order.java": _ORDER, "OrderController.java": _CONTROLLER,
                          **files}.items():
        (tmp_path / name).write_text(content)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    symbols = facts["symbols"]
    trace = next(item for item in facts["traces"].values()
                 if facts["anchors"][item["anchor_id"]]["operation"]["path"] == "/orders")
    obligations = [facts["trace_obligations"][key] for key in trace["obligation_ids"]]
    reached = {symbols[symbol]["qualified_name"].split("::")[-1]
               for symbol in trace["symbol_ids"]}
    name_of = lambda symbol: symbols[symbol]["qualified_name"].split("::")[-1]
    selections = {name_of(edge["from_ref"]["id"]): edge for edge in facts["edges"].values()
                  if edge["kind"] == "selects_implementation"}
    return facts, trace, obligations, reached, selections, name_of


def _selection_of(obligations, name_of, declaration):
    return [item for item in obligations if item["kind"] == "implementation_selection"
            and name_of(item["origin_ref"]["id"]) == declaration]


def test_interface_reached_mid_trace_selects_its_single_implementation(tmp_path):
    facts, trace, obligations, reached, selections, name_of = _dispatch_trace(tmp_path, {
        "OrderService.java": "interface OrderService { void save(Order order); }\n",
        "OrderServiceImpl.java": """
            class OrderServiceImpl implements OrderService {
              public void save(Order order) { record(order); }
              private void record(Order order) {}
            }
        """,
    })

    edge = selections["OrderService.save(Order)"]
    assert edge["resolution"] == "resolved"
    assert name_of(edge["to_ref"]["id"]) == "OrderServiceImpl.save(Order)"
    assert {"OrderService.save(Order)", "OrderServiceImpl.save(Order)",
            "OrderServiceImpl.record(Order)"} <= reached
    [selection] = _selection_of(obligations, name_of, "OrderService.save(Order)")
    assert (selection["status"], selection["reason_code"]) == ("satisfied", "IMPLEMENTATION_REACHED")
    assert [name_of(target) for target in selection["candidate_target_ids"]] == [
        "OrderServiceImpl.save(Order)"]
    assert trace["traversal_complete"] is True and trace["resolution"] == "resolved"


def test_multiple_implementations_keep_every_candidate_and_make_the_trace_ambiguous(tmp_path):
    facts, trace, obligations, reached, selections, name_of = _dispatch_trace(tmp_path, {
        "OrderService.java": "interface OrderService { void save(Order order); }\n",
        "JpaOrderService.java":
            "class JpaOrderService implements OrderService { public void save(Order order) {} }\n",
        "JdbcOrderService.java":
            "class JdbcOrderService implements OrderService { public void save(Order order) {} }\n",
    })

    edge = selections["OrderService.save(Order)"]
    candidates = sorted(name_of(target) for target in edge["candidate_target_ids"])
    assert edge["resolution"] == "ambiguous" and edge["to_ref"] is None
    assert candidates == ["JdbcOrderService.save(Order)", "JpaOrderService.save(Order)"]
    [recorded] = [item for item in obligations if item["edge_id"] == edge["id"]]
    assert (recorded["kind"], recorded["status"], recorded["reason_code"]) == (
        "implementation_selection", "ambiguous", "IMPLEMENTATION_AMBIGUOUS")
    assert sorted(map(name_of, recorded["candidate_target_ids"])) == candidates
    assert trace["resolution"] == "ambiguous"
    assert "implementation_ambiguous" in trace["stop_reasons"]
    assert any(item["code"] == "JAVA_IMPLEMENTATION_AMBIGUOUS" for item in facts["warnings"])


@pytest.mark.parametrize("declaration", ["void save(Order order);", "Order save(Order order);"])
def test_interface_without_implementation_cannot_resolve_through_structural_edges(
        tmp_path, declaration):
    # The declaration's accepts_type / returns_type edges to Order used to make
    # it look like a finished leaf, which marked the whole trace resolved.
    facts, trace, obligations, reached, selections, name_of = _dispatch_trace(tmp_path, {
        "OrderService.java": f"interface OrderService {{ {declaration} }}\n",
    })

    method = next(symbol for symbol in trace["symbol_ids"]
                  if name_of(symbol) == "OrderService.save(Order)")
    assert {edge["kind"] for edge in facts["edges"].values()
            if edge["from_ref"]["id"] == method} <= core.NON_TRAVERSAL_EDGES
    assert "OrderService.save(Order)" not in selections
    [selection] = _selection_of(obligations, name_of, "OrderService.save(Order)")
    assert (selection["status"], selection["reason_code"]) == (
        "unresolved", "IMPLEMENTATION_NOT_REACHED")
    assert trace["resolution"] == "unresolved"
    assert "implementation_not_reached" in trace["stop_reasons"]


def test_dispatch_repeats_at_every_interface_on_the_path(tmp_path):
    facts, trace, obligations, reached, selections, name_of = _dispatch_trace(tmp_path, {
        "OrderService.java": "interface OrderService { void save(Order order); }\n",
        "OrderRepository.java": "interface OrderRepository { void store(Order order); }\n",
        "OrderServiceImpl.java": """
            class OrderServiceImpl implements OrderService {
              private final OrderRepository repository;
              OrderServiceImpl(OrderRepository repository) { this.repository = repository; }
              public void save(Order order) { this.repository.store(order); }
            }
        """,
        "SqlOrderRepository.java":
            "class SqlOrderRepository implements OrderRepository { public void store(Order order) {} }\n",
    })

    assert {"OrderServiceImpl.save(Order)", "OrderRepository.store(Order)",
            "SqlOrderRepository.store(Order)"} <= reached
    for declaration in ("OrderService.save(Order)", "OrderRepository.store(Order)"):
        [selection] = _selection_of(obligations, name_of, declaration)
        assert selection["status"] == "satisfied"
    assert trace["resolution"] == "resolved"


def test_abstract_method_selects_the_subclass_override(tmp_path):
    controller = _CONTROLLER.replace("OrderService service", "BaseService service")
    facts, trace, obligations, reached, selections, name_of = _dispatch_trace(tmp_path, {
        "OrderController.java": controller,
        "BaseService.java": "abstract class BaseService { public abstract void save(Order order); }\n",
        "OrderService.java":
            "class OrderService extends BaseService { public void save(Order order) {} }\n",
    })

    assert name_of(selections["BaseService.save(Order)"]["to_ref"]["id"]) == "OrderService.save(Order)"
    assert "OrderService.save(Order)" in reached
    assert trace["resolution"] == "resolved"


def test_class_implementing_a_sub_interface_answers_for_the_base_declaration(tmp_path):
    facts, trace, obligations, reached, selections, name_of = _dispatch_trace(tmp_path, {
        "OrderService.java": "interface OrderService { void save(Order order); }\n",
        "AuditedOrderService.java": "interface AuditedOrderService extends OrderService {}\n",
        "AuditedOrderServiceImpl.java": """
            class AuditedOrderServiceImpl implements AuditedOrderService {
              public void save(Order order) {}
            }
        """,
    })

    inherits = [edge for edge in facts["edges"].values() if edge["kind"] == "inherits"
                and name_of(edge["from_ref"]["id"]) == "AuditedOrderService"]
    assert [(edge["resolution"], name_of(edge["to_ref"]["id"])) for edge in inherits] == [
        ("resolved", "OrderService")]
    assert "AuditedOrderServiceImpl.save(Order)" in reached
    assert trace["resolution"] == "resolved"


def test_test_doubles_and_static_methods_never_answer_for_a_declaration(tmp_path):
    (tmp_path / "test").mkdir()
    facts, trace, obligations, reached, selections, name_of = _dispatch_trace(tmp_path, {
        "OrderService.java": "interface OrderService { void save(Order order); }\n",
        "OrderServiceImpl.java":
            "class OrderServiceImpl implements OrderService { public void save(Order order) {} }\n",
        "StaticSaver.java":
            "class StaticSaver implements OrderService { public static void save(Order order) {} }\n",
        "test/FakeOrderService.java":
            "class FakeOrderService implements OrderService { public void save(Order order) {} }\n",
    })

    edge = selections["OrderService.save(Order)"]
    assert edge["resolution"] == "resolved"
    assert name_of(edge["to_ref"]["id"]) == "OrderServiceImpl.save(Order)"


_DEFAULT_SERVICE = ("interface OrderService {\n"
                    "  default void save(Order order) { audit(order); }\n"
                    "  default void audit(Order order) {}\n"
                    "}\n")


def test_default_method_nobody_overrides_selects_its_own_body(tmp_path):
    facts, trace, obligations, reached, selections, name_of = _dispatch_trace(tmp_path, {
        "OrderService.java": _DEFAULT_SERVICE,
        "PlainOrderService.java": "class PlainOrderService implements OrderService {}\n",
    })

    for declaration in ("OrderService.save(Order)", "OrderService.audit(Order)"):
        edge = selections[declaration]
        assert edge["resolution"] == "resolved"
        assert name_of(edge["to_ref"]["id"]) == declaration
        [selection] = _selection_of(obligations, name_of, declaration)
        assert (selection["status"], selection["reason_code"]) == (
            "satisfied", "IMPLEMENTATION_REACHED")
    assert trace["resolution"] == "resolved"


def test_default_method_overridden_by_one_implementer_keeps_both_bodies(tmp_path):
    facts, trace, obligations, reached, selections, name_of = _dispatch_trace(tmp_path, {
        "OrderService.java": _DEFAULT_SERVICE,
        "PlainOrderService.java": "class PlainOrderService implements OrderService {}\n",
        "CustomOrderService.java":
            "class CustomOrderService implements OrderService { public void save(Order order) {} }\n",
    })

    edge = selections["OrderService.save(Order)"]
    assert edge["resolution"] == "ambiguous"
    assert sorted(map(name_of, edge["candidate_target_ids"])) == [
        "CustomOrderService.save(Order)", "OrderService.save(Order)"]
    [selection] = _selection_of(obligations, name_of, "OrderService.save(Order)")
    assert (selection["status"], selection["reason_code"]) == ("ambiguous", "IMPLEMENTATION_AMBIGUOUS")
    assert trace["resolution"] == "ambiguous"


def test_every_parent_of_a_type_keeps_its_own_heritage_edge(tmp_path):
    files = {
        "A.java": "interface A { void a(); }\n",
        "B.java": "interface B<T> { void b(); }\n",
        "Owner.java": "class Owner {}\n",
        "C.java": "class C implements A, B<Owner> { public void a() {} public void b() {} }\n",
        "D.java": "interface D extends A, B<Owner> {}\n",
    }
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    symbols = facts["symbols"]
    name_of = lambda symbol: symbols[symbol]["qualified_name"].split("::")[-1]
    heritage = sorted((edge["kind"], name_of(edge["from_ref"]["id"]),
                       name_of(edge["to_ref"]["id"]) if edge["to_ref"] else None, edge["resolution"])
                      for edge in facts["edges"].values() if edge["kind"] in {"implements", "inherits"})

    # Both parents survive, and a type argument (Owner) is never a parent.
    assert heritage == [
        ("implements", "C", "A", "resolved"), ("implements", "C", "B", "resolved"),
        ("inherits", "D", "A", "resolved"), ("inherits", "D", "B", "resolved")]


# Phase 2C: a selection reached mid-trace, in each semantic shape, from an
# adapter that names no language or framework.

def _mid_trace_selection(tmp_path, monkeypatch, shape):
    state = {"bodies": []}

    def extract(source):
        role = {"contract": "contract", "declaration": "declaration"}.get(source.text, "implementation")
        unit = Unit(source, source.text, source.path + "::" + source.text, 0, len(source.text),
                    "declarative_operation" if role == "contract" else "function",
                    executable_body=role == "implementation", trace_role=role,
                    required_relationships=() if role == "implementation" else ("implementation_selection",),
                    required_capabilities=(), valid_terminal=role == "implementation",
                    anchor_kind="workflow" if role == "contract" else None,
                    anchor_resolution="resolved" if role == "contract" else None)
        if role == "implementation" and source.text != "entry":
            state["bodies"].append(unit)
        state[source.text] = unit
        source.units = [unit]
        return [unit]

    def relation(origin, kind, **fields):
        origin.source.semantic_relations.append({"source": origin, "kind": kind, "start": 0,
            "end": len(origin.source.text), "target": None, "candidate_targets": [],
            "resolution": "resolved", "reason": None, **fields})

    def prepare(sources, units, diagnostics):
        for source in sources:
            source.semantic_relations = []
        relation(state["contract"], "selects_implementation", target=state["entry"],
                 outcome="exact")
        relation(state["entry"], "calls", target=state["declaration"], outcome="exact")
        bodies = sorted(state["bodies"], key=lambda unit: unit.qualified)
        declaration = state["declaration"]
        if shape == "source":
            relation(declaration, "selects_implementation", target=bodies[0], outcome="exact")
        elif shape == "ambiguous":
            relation(declaration, "selects_implementation", candidate_targets=bodies,
                     resolution="ambiguous", outcome="ambiguous",
                     diagnostic_code="FIXTURE_AMBIGUOUS", reason="Two bodies remain viable.")
        elif shape == "external":
            relation(declaration, "selects_implementation", resolution="unresolved",
                     outcome="external", external_target_id="resource:fixture-generated",
                     diagnostic_code="FIXTURE_EXTERNAL",
                     reason="The implementation is produced outside the analyzed source.")

    adapter = SimpleNamespace(
        extract=extract, prepare=prepare, relations=lambda source: source.semantic_relations,
        bindings=lambda unit: [], resources=lambda unit: [], calls=lambda unit: [],
        observations=lambda unit: [], operations=lambda unit: [],
        activation_evidence=lambda source: {})
    install_fixture_adapter(monkeypatch, adapter, {
        "language": "fixture", "source_kind": "source", "adapter": "fixture",
        "capability": {"id": "fixture", "version": "1", "capabilities": {
            "entrypoint_detection": "supported", "relationship_resolution": "supported"},
            "diagnostic_codes": []}})
    for name in ("contract", "entry", "declaration", "body0", "body1"):
        (tmp_path / f"{name}.opaque").write_text(name)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    trace = next(iter(facts["traces"].values()))
    declaration = state["declaration"].symbol_id
    obligations = [facts["trace_obligations"][key] for key in trace["obligation_ids"]
                   if facts["trace_obligations"][key]["origin_ref"]["id"] == declaration
                   and facts["trace_obligations"][key]["kind"] == "implementation_selection"]
    return facts, trace, obligations


@pytest.mark.parametrize(("shape", "status", "code", "resolution"), [
    ("source", "satisfied", "IMPLEMENTATION_REACHED", "resolved"),
    ("ambiguous", "ambiguous", "IMPLEMENTATION_AMBIGUOUS", "ambiguous"),
    ("external", "external", "EXTERNAL_IMPLEMENTATION_UNAVAILABLE", "unresolved"),
    ("none", "unresolved", "IMPLEMENTATION_NOT_REACHED", "unresolved"),
])
def test_mid_trace_selection_shapes_use_one_vocabulary(tmp_path, monkeypatch, shape, status,
                                                       code, resolution):
    facts, trace, obligations = _mid_trace_selection(tmp_path, monkeypatch, shape)

    [selection] = obligations
    assert (selection["status"], selection["reason_code"]) == (status, code)
    assert trace["resolution"] == resolution
    if shape == "external":
        assert selection["candidate_target_ids"] == ["resource:fixture-generated"]
        assert facts["resources"]["resource:fixture-generated"]
        assert "external_boundary" in trace["stop_reasons"]
        assert "implementation_not_reached" not in trace["stop_reasons"]


_MAVEN_MAPSTRUCT = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>org.acme</groupId><artifactId>shop</artifactId>
  <build><plugins><plugin><artifactId>maven-compiler-plugin</artifactId><configuration>
    <annotationProcessorPaths><path>
      <groupId>org.mapstruct</groupId><artifactId>mapstruct-processor</artifactId>
    </path></annotationProcessorPaths>
  </configuration></plugin></plugins></build>
</project>
"""


def test_generated_mapper_reached_mid_trace_is_an_external_boundary(tmp_path):
    facts, trace, obligations, reached, selections, name_of = _dispatch_trace(tmp_path, {
        "pom.xml": _MAVEN_MAPSTRUCT,
        "OrderService.java": ("import org.mapstruct.Mapper;\n"
                              "@Mapper interface OrderService { void save(Order order); }\n"),
    })

    edge = selections["OrderService.save(Order)"]
    assert edge["to_ref"]["kind"] == "resource" and "MapStruct" in edge["reason"]
    [selection] = _selection_of(obligations, name_of, "OrderService.save(Order)")
    assert (selection["status"], selection["reason_code"]) == (
        "external", "EXTERNAL_IMPLEMENTATION_UNAVAILABLE")
    assert trace["resolution"] == "unresolved" and "external_boundary" in trace["stop_reasons"]


def test_spring_evidence_does_not_resolve_an_ambiguous_trace(tmp_path):
    imports = ("import org.springframework.context.annotation.Primary;\n"
               "import org.springframework.stereotype.Repository;\n")
    facts, trace, obligations, reached, selections, name_of = _dispatch_trace(tmp_path, {
        "OrderService.java": "interface OrderService { void save(Order order); }\n",
        "JpaOrderService.java": imports + "@Repository @Primary\n"
            "class JpaOrderService implements OrderService { public void save(Order order) {} }\n",
        "JdbcOrderService.java": imports + "@Repository\n"
            "class JdbcOrderService implements OrderService { public void save(Order order) {} }\n",
    })

    [selection] = _selection_of(obligations, name_of, "OrderService.save(Order)")
    assert (selection["status"], selection["reason_code"]) == ("ambiguous", "IMPLEMENTATION_AMBIGUOUS")
    assert "JpaOrderService: @Repository, @Primary" in selection["reason"]
    assert trace["resolution"] == "ambiguous"
