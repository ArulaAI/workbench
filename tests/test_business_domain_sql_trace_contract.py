"""F-04 Oracle package-contract terminal conformance."""
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import DEFAULTS, validate_references


def _extract(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, units = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    return facts, units


SPEC = """CREATE OR REPLACE PACKAGE orders AS
  PROCEDURE submit(order_id IN NUMBER);
END orders;
/
"""

BODY = """CREATE OR REPLACE PACKAGE BODY orders AS
  PROCEDURE submit(order_id IN NUMBER) IS
  BEGIN
    NULL;
  END submit;
END orders;
/
"""


def test_package_spec_without_body_stays_visible_and_unresolved_after_false_calls_removed(tmp_path):
    facts, units = _extract(tmp_path, {"orders.sql": SPEC})

    contract = next(unit for unit in units if unit.trace_role == "contract")
    trace = next(trace for trace in facts["traces"].values()
        if trace["anchor_id"] == contract.anchor_id)
    obligations = [facts["trace_obligations"][key] for key in trace["obligation_ids"]]

    assert contract.executable_body is False and contract.valid_terminal is False
    assert contract.required_relationships == ("implementation_selection",)
    assert not [item for item in facts["edges"].values()
        if item["kind"] == "selects_implementation"]
    assert not [item for item in facts["edges"].values() if item["kind"] == "calls"]
    assert trace["traversal_complete"] is True and trace["resolution"] == "unresolved"
    assert any(item["reason_code"] == "IMPLEMENTATION_NOT_REACHED" for item in obligations)
    assert any(item["code"] == "SQL_IMPLEMENTATION_UNAVAILABLE" for item in facts["warnings"])


def test_exact_package_spec_selects_body_and_both_executable_leaf_traces_resolve(tmp_path):
    facts, units = _extract(tmp_path, {"orders.sql": SPEC + BODY})

    contract = next(unit for unit in units if unit.trace_role == "contract")
    body = next(unit for unit in units
        if getattr(unit, "sql_declaration_kind", None) == "package_body")
    edge = next(edge for edge in facts["edges"].values()
        if edge["kind"] == "selects_implementation")
    contract_trace = next(trace for trace in facts["traces"].values()
        if trace["anchor_id"] == contract.anchor_id)

    assert body.trace_role == "implementation"
    assert body.executable_body is True and body.valid_terminal is True
    assert body.anchor_id == contract.anchor_id
    assert edge["resolution"] == "resolved"
    assert edge["from_ref"]["id"] == contract.symbol_id
    assert edge["to_ref"]["id"] == body.symbol_id
    assert edge["evidence_ids"] and all(key in facts["evidence"] for key in edge["evidence_ids"])
    assert contract_trace["resolution"] == "resolved"
    assert contract_trace["symbol_ids"] == sorted([contract.symbol_id, body.symbol_id])
    assert contract_trace["edge_ids"] == [edge["id"]]
    assert sum(trace["anchor_id"] == contract.anchor_id
               for trace in facts["traces"].values()) == 1


def test_duplicate_package_bodies_remain_bounded_and_ambiguous(tmp_path):
    facts, units = _extract(tmp_path, {
        "orders_spec.sql": SPEC,
        "orders_body_one.sql": BODY,
        "orders_body_two.sql": BODY,
    })

    contract = next(unit for unit in units if unit.trace_role == "contract")
    bodies = [unit for unit in units
        if getattr(unit, "sql_declaration_kind", None) == "package_body"]
    edge = next(edge for edge in facts["edges"].values()
        if edge["kind"] == "selects_implementation")
    trace = next(trace for trace in facts["traces"].values()
        if trace["anchor_id"] == contract.anchor_id)

    assert edge["resolution"] == "ambiguous" and edge["to_ref"] is None
    assert edge["candidate_target_ids"] == sorted(unit.symbol_id for unit in bodies)
    assert len(edge["candidate_target_ids"]) == 2
    assert trace["traversal_complete"] is True and trace["resolution"] == "ambiguous"
    assert "implementation_ambiguous" in trace["stop_reasons"]
    assert any(item["code"] == "SQL_IMPLEMENTATION_AMBIGUOUS" for item in facts["warnings"])
