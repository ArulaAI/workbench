"""F-04 semantic trace completion conformance."""
from types import SimpleNamespace

import pytest

from lib.context import business_domain_extract as core
from lib.context.business_domain_adapters.base import Unit
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, DomainError, copy_facts, record, validate_references,
)
from lib.context.business_domain_synthesis import packet_for
from lib.context.business_domains import accept_activity


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
    monkeypatch.setattr(core, "descriptor", lambda value: {
        "language": language, "source_kind": "source", "adapter": "fixture",
        "capability": {"id": "fixture", "version": "1", "capabilities": capabilities,
                       "diagnostic_codes": ["FIXTURE_CAPABILITY_UNAVAILABLE"]},
    })
    monkeypatch.setattr(core, "adapter_for", lambda source: adapter)
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
    monkeypatch.setattr(core, "descriptor", lambda value: {
        "language": "fixture", "source_kind": "source", "adapter": "fixture"})
    monkeypatch.setattr(core, "adapter_for", lambda source: adapter)
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


def test_capability_gap_blocks_selected_implementation_and_reaches_packet(
        tmp_path, monkeypatch):
    facts, _, trace, obligations = _selection_facts(
        tmp_path, monkeypatch, relationship_capability="unsupported")
    packet = packet_for(facts, "activity", [trace["anchor_id"]])

    assert trace["traversal_complete"] is True and trace["resolution"] == "unresolved"
    assert any(item["reason_code"] == "CAPABILITY_UNAVAILABLE" for item in obligations)
    assert packet["context"]["capabilities"] == facts["capabilities"]
    assert packet["context"]["trace_obligations"] == facts["trace_obligations"]
    assert packet["context"]["traces"][trace["id"]]["stop_reasons"] == ["capability_gap"]


def test_supported_activity_cannot_claim_obligation_incomplete_trace(tmp_path, monkeypatch):
    facts, _, trace, _ = _selection_facts(
        tmp_path, monkeypatch, implementations=1, produce=False)
    model = copy_facts(facts, facts["build_id"])
    packet = packet_for(model, "activity", [trace["anchor_id"]])
    evidence = list(packet["context"]["evidence"])
    activity = record("Activity", id="activity:fixture", name="Fixture",
        description="Overstated", anchor_ids=[trace["anchor_id"]],
        trace_ids=[trace["id"]], evidence_ids=evidence,
        claim_ids=["claim:fixture"], support="supported")
    payload = record("ActivityPayload", activities={activity["id"]: activity},
        claims={"claim:fixture": record("Claim", id="claim:fixture",
            subject_id=activity["id"], text="Overstated", kind="behavior",
            evidence_ids=evidence, trace_ids=[trace["id"]])})

    with pytest.raises(DomainError, match="semantically complete"):
        accept_activity(model, packet, payload)


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
