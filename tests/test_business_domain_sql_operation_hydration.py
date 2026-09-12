"""F-08 Oracle/PostgreSQL operation hydration and Grocery acceptance."""
from pathlib import Path

import pytest

from lib.context.business_domain_adapters import adapter_for
from lib.context.business_domains import accept_activity, materialize_observed_rules
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, copy_facts, record, validate_references,
)
from lib.context.business_domain_synthesis import packet_for


FIXTURES = Path(__file__).parents[1] / "specs/tech/fixtures/business-domains"
GROCERY = Path("/private/tmp/speed-domain-grocery")


def _extract(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, units = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    return facts, units


def test_observed_constraint_becomes_trace_linked_rule_after_activity_acceptance(tmp_path):
    facts, _ = _extract(tmp_path, {"rule.sql": """
      CREATE OR REPLACE PROCEDURE update_pet(p_id IN NUMBER) AS
      BEGIN
        IF p_id > 0 THEN UPDATE pets SET id = p_id WHERE id = p_id; END IF;
      END;
    """})
    trace = next(iter(facts["traces"].values()))
    model = copy_facts(facts, "00000000-0000-4000-8000-000000000010")
    packet = packet_for(model, "activity", [trace["anchor_id"]])
    evidence = sorted(packet["context"]["evidence"])
    activity = record("Activity", id="activity:update-pet", name="Update pet",
        description="Updates an evidenced pet", anchor_ids=[trace["anchor_id"]],
        trace_ids=[trace["id"]], evidence_ids=evidence,
        claim_ids=["claim:update-pet"], support="partial")
    claim = record("Claim", id="claim:update-pet", subject_id=activity["id"],
        text=activity["description"], kind="behavior", evidence_ids=evidence,
        trace_ids=[trace["id"]], semantic_review="uncertain")
    accept_activity(model, packet, record("ActivityPayload",
        activities={activity["id"]: activity}, claims={claim["id"]: claim}))

    materialize_observed_rules(model)

    observation = next(iter(model["rule_observations"].values()))
    assert observation["rule_id"] in model["rules"]
    assert observation["activity_ids"] == [activity["id"]]
    assert observation["resolution"] == "resolved"
    assert observation["rule_id"] in model["activities"][activity["id"]]["rule_ids"]
    validate_references(model)


@pytest.mark.parametrize("fixture,adapter", [
    ("invoice_oracle.sql", "oracle_plsql/sqlglot"),
    ("invoice_postgresql.sql", "postgresql/sqlglot"),
])
def test_dialects_hydrate_equivalent_write_closure_without_claiming_commit(
        tmp_path, fixture, adapter):
    facts, units = _extract(tmp_path, {
        fixture: (FIXTURES / fixture).read_text()})
    unit = next(item for item in units if item.executable_body)
    edge = next(item for item in facts["edges"].values()
                if item["kind"] == "writes_data")
    effect = next(item for item in facts["effects"].values()
                  if item["edge_id"] == edge["id"])
    trace = next(item for item in facts["traces"].values()
                 if edge["id"] in item["edge_ids"])

    assert [name for name, _ in unit.params] == [
        "p_tenant_id", "p_invoice_number", "p_result"]
    assert [kind.split()[0] for _, kind in unit.params] == ["IN", "IN", "OUT"]
    assert effect["origin_ref"] == edge["from_ref"] == {
        "kind": "symbol", "id": unit.symbol_id}
    assert effect["target"] == edge["to_ref"]
    assert effect["trace_ids"] == [trace["id"]]
    assert effect["transaction_scope"] == "caller_transaction"
    assert effect["completion"] == "declared"
    assert effect["status"] == "caller_completion_unobserved"
    assert effect["resolution"] == edge["resolution"] == "unresolved"
    assert "completion remains caller-controlled" in effect["reason"]
    assert facts["evidence"][edge["evidence_ids"][0]]["excerpt"].lstrip().startswith(
        "INSERT INTO")
    assert facts["evidence"][edge["evidence_ids"][0]]["extractor"] == adapter
    inputs = {facts["bindings"][key]["name"]
              for key in effect["input_binding_ids"]}
    assert {"p_tenant_id", "p_invoice_number"} <= inputs
    assert any(name.endswith(".tenant_id@163") or ".tenant_id@" in name
               for name in inputs)
    assert any(name.endswith(".invoice_number@163") or ".invoice_number@" in name
               for name in inputs)
    assert {facts["bindings"][key]["name"]
            for key in effect["output_binding_ids"]} == {"p_result"}
    assert set(edge["binding_ids"]) == set(effect["input_binding_ids"]) | set(
        effect["output_binding_ids"])
    assert any(item["code"] == "SQL_COMPLETION_UNRESOLVED"
               and edge["id"] in item["subject_ids"]
               for item in facts["warnings"])


def test_oracle_and_postgresql_emit_the_same_normalized_operation_contract(
        tmp_path):
    records = []
    for fixture in ("invoice_oracle.sql", "invoice_postgresql.sql"):
        facts, units = _extract(tmp_path / fixture.removesuffix(".sql"), {
            fixture: (FIXTURES / fixture).read_text()})
        unit = next(item for item in units if item.executable_body)
        records.append(adapter_for(unit.source).operations(unit)[0])
        assert facts["effects"]

    oracle, postgres = records
    assert set(oracle) == set(postgres)
    for record in records:
        assert record["contract_version"] == 1
        assert record["capability"] == "data_access"
        assert record["origin_ref"]["kind"] == "symbol"
        assert record["kind"] == "data_write"
        assert record["protocol"] == "sql"
        assert record["projection_gaps"] == [{
            "projection": "completion",
            "code": "SQL_COMPLETION_UNRESOLVED",
            "reason": ("No completion is established; transaction completion "
                       "remains caller-controlled."),
        }]
    assert oracle["adapter_id"] == "oracle_plsql/sqlglot"
    assert postgres["adapter_id"] == "postgresql/sqlglot"


def test_operation_only_resource_has_exact_statement_evidence_not_symbol_evidence(
        tmp_path):
    facts, _ = _extract(tmp_path, {"write.sql": """
CREATE OR REPLACE PROCEDURE save_order(p_id IN NUMBER) IS
BEGIN
  INSERT INTO undeclared_orders (id) VALUES (p_id);
END;
/
"""})
    edge = next(item for item in facts["edges"].values()
                if item["kind"] == "writes_data")
    resource = facts["resources"][edge["to_ref"]["id"]]
    excerpts = {facts["evidence"][key]["excerpt"] for key in resource["evidence_ids"]}

    assert resource["resolution"] == "unresolved"
    assert excerpts == {"INSERT INTO undeclared_orders (id) VALUES (p_id);"}
    assert edge["evidence_ids"] == resource["evidence_ids"]


def test_cursor_and_insert_select_preserve_reads_changed_values_and_conditions(
        tmp_path):
    facts, _ = _extract(tmp_path, {"copy.sql": """
CREATE TABLE source_orders (id NUMBER, status VARCHAR2(20));
CREATE TABLE archived_orders (id NUMBER, status VARCHAR2(20));
CREATE OR REPLACE PROCEDURE archive_orders(p_min IN NUMBER) IS
  CURSOR candidates IS
    SELECT id, status FROM source_orders WHERE id >= p_min;
BEGIN
  IF p_min > 0 THEN
    INSERT INTO archived_orders (id, status)
      SELECT id, status FROM source_orders WHERE id >= p_min;
  END IF;
END;
/
"""})
    reads = [item for item in facts["edges"].values()
             if item["kind"] == "reads_data"]
    write = next(item for item in facts["edges"].values()
                 if item["kind"] == "writes_data")
    effect = next(item for item in facts["effects"].values()
                  if item["edge_id"] == write["id"])

    assert len(reads) == 2
    assert {facts["resources"][item["to_ref"]["id"]]["name"]
            for item in reads} == {"source_orders"}
    assert all(item["id"] in next(iter(facts["traces"].values()))["edge_ids"]
               for item in reads + [write])
    assert "p_min > 0" in write["condition"]
    assert "WHERE id >= p_min" in write["condition"]
    changed = {facts["bindings"][key]["name"]:
               facts["bindings"][key]["expression"]
               for key in effect["input_binding_ids"]
               if facts["bindings"][key]["name"].startswith("archived_orders.")}
    assert len(changed) == 2
    assert set(changed.values()) == {"id", "status"}
    selected = [facts["bindings"][key] for item in reads
                for key in item["binding_ids"]
                if facts["bindings"][key]["direction"] == "output"]
    assert {item["expression"] for item in selected} >= {"id", "status"}
    assert all(facts["evidence"][item["evidence_ids"][0]]["excerpt"]
               == item["expression"] for item in selected)


def test_autonomous_write_retains_commit_and_transaction_evidence(tmp_path):
    facts, _ = _extract(tmp_path, {"audit.sql": """
CREATE TABLE audit_log (id NUMBER, message VARCHAR2(100));
CREATE OR REPLACE PROCEDURE log_error(p_id IN NUMBER, p_message IN VARCHAR2) IS
  PRAGMA autonomous_transaction;
BEGIN
  INSERT INTO audit_log (id, message) VALUES (p_id, p_message);
  COMMIT;
END;
/
"""})
    edge = next(item for item in facts["edges"].values()
                if item["kind"] == "writes_data")
    effect = next(item for item in facts["effects"].values())
    excerpts = {facts["evidence"][key]["excerpt"].strip()
                for key in effect["evidence_ids"]}

    assert edge["resolution"] == effect["resolution"] == "unresolved"
    assert effect["transaction_scope"] == "autonomous_transaction"
    assert effect["completion"] == "declared"
    assert effect["status"] == "explicit_commit_declared"
    assert "cannot establish runtime completion" in effect["reason"]
    assert any(value.startswith("INSERT INTO audit_log") for value in excerpts)
    assert "PRAGMA autonomous_transaction;" in excerpts
    assert "COMMIT" in excerpts
    assert facts["evidence"][edge["evidence_ids"][0]]["excerpt"].lstrip().startswith(
        "INSERT INTO audit_log")


def test_trigger_condition_constrains_its_write(tmp_path):
    facts, _ = _extract(tmp_path, {"trigger.sql": """
CREATE TABLE inventory (id NUMBER, quantity NUMBER);
CREATE OR REPLACE TRIGGER audit_inventory
AFTER UPDATE OF quantity ON inventory FOR EACH ROW
WHEN (NEW.quantity < OLD.quantity)
BEGIN
  UPDATE inventory SET quantity = :NEW.quantity WHERE id = :NEW.id;
END audit_inventory;
/
"""})
    edge = next(item for item in facts["edges"].values()
                if item["kind"] == "writes_data")
    effect = next(iter(facts["effects"].values()))
    evidence = {facts["evidence"][key]["excerpt"]
                for key in effect["evidence_ids"]}

    assert "NEW.quantity < OLD.quantity" in edge["condition"]
    assert "WHERE id = :NEW.id" in edge["condition"]
    assert edge["condition"] == effect["condition"]
    assert any("WHEN (NEW.quantity < OLD.quantity)" in item
               for item in evidence)


@pytest.mark.skipif(not (GROCERY / "JTA_Packages.sql").is_file(),
    reason="optional local Grocery corpus is unavailable")
def test_live_grocery_every_supported_dml_operation_has_reachable_closure():
    facts, units = Extractor(GROCERY, DEFAULTS).extract()
    validate_references(facts)
    data_edges = [item for item in facts["edges"].values()
                  if item["kind"] in {"reads_data", "writes_data"}]
    write_edges = [item for item in data_edges if item["kind"] == "writes_data"]
    expected_writes = sum(bool(statement["write_target"])
        for unit in units for statement in getattr(unit, "sql_dml", []))
    expected_reads = sum(
        len(statement["tables"]) if statement["kind"].name == "SELECT" else
        sum(table.casefold() != (statement["write_target"] or "").casefold()
            for table in statement["tables"])
        for unit in units for statement in getattr(unit, "sql_dml", []))

    assert len(write_edges) == expected_writes > 0
    assert len(data_edges) - len(write_edges) == expected_reads > 0
    effects_by_edge = {item["edge_id"]: item for item in facts["effects"].values()}
    assert set(effects_by_edge) == {item["id"] for item in write_edges}
    for edge in data_edges:
        assert edge["evidence_ids"]
        assert any(edge["id"] in trace["edge_ids"]
                   and edge["from_ref"]["id"] in trace["symbol_ids"]
                   for trace in facts["traces"].values())
        excerpt = facts["evidence"][edge["evidence_ids"][0]]["excerpt"].lstrip()
        assert excerpt.upper().startswith(
            ("WITH", "SELECT", "INSERT", "UPDATE", "DELETE"))
    for edge in write_edges:
        effect = effects_by_edge[edge["id"]]
        reachable = sorted(trace["id"] for trace in facts["traces"].values()
                           if edge["id"] in trace["edge_ids"])
        assert effect["trace_ids"] == reachable

    log_error = next(unit for unit in units
        if unit.name == "log_error" and unit.executable_body)
    effect = next(item for item in facts["effects"].values()
                  if item["origin_ref"]["id"] == log_error.symbol_id)
    excerpts = {facts["evidence"][key]["excerpt"].strip()
                for key in effect["evidence_ids"]}
    assert effect["transaction_scope"] == "autonomous_transaction"
    assert effect["completion"] == "declared"
    assert effect["status"] == "explicit_commit_declared"
    assert "cannot establish runtime completion" in effect["reason"]
    assert "PRAGMA autonomous_transaction;" in excerpts
    assert "COMMIT" in excerpts
    assert all(effect["edge_id"] in facts["traces"][key]["edge_ids"]
               for key in effect["trace_ids"])

    profits = next(unit for unit in units
        if unit.name == "get_profits_for" and unit.executable_body)
    profit_resources = {facts["resources"][edge["to_ref"]["id"]]["name"]
        for edge in data_edges if edge["from_ref"]["id"] == profits.symbol_id}
    assert profit_resources == {
        "cost_sales_tracker", "billed_items", "customer_bills"}
    assert not profit_resources & {"avg_cost", "total_cost", "net_gain"}

    payroll = next(unit for unit in units
        if unit.name == "process_payroll" and unit.executable_body)
    trace = next(trace for trace in facts["traces"].values()
        if payroll.symbol_id in trace["symbol_ids"]
        and any(facts["edges"][key]["kind"] == "writes_data"
                for key in trace["edge_ids"]))
    selected_edges = [facts["edges"][key] for key in trace["edge_ids"]]
    read = next(edge for edge in selected_edges if edge["kind"] == "reads_data")
    model = copy_facts(facts, "00000000-0000-4000-8000-000000000008")
    packet = packet_for(model, "activity", [trace["anchor_id"]])
    activity = record("Activity", id="activity:grocery-f08",
        name="Grocery operation closure",
        description="Evidenced Grocery SQL operation closure",
        anchor_ids=[trace["anchor_id"]], trace_ids=[trace["id"]],
        concept_ids=["concept:grocery-resource"],
        evidence_ids=trace["evidence_ids"], claim_ids=["claim:grocery-f08"],
        support="partial")
    concept = record("Concept", id="concept:grocery-resource",
                     name="Grocery resource")
    use = record("InformationUse", id="information_use:grocery-f08",
        activity_id=activity["id"], concept_id=concept["id"],
        resource_ids=[read["to_ref"]["id"]], access="reads",
        evidence_ids=read["evidence_ids"], resolution="resolved", reason=None)
    claim = record("Claim", id="claim:grocery-f08",
        subject_id=activity["id"], text=activity["description"],
        kind="behavior", evidence_ids=activity["evidence_ids"],
        trace_ids=[trace["id"]], semantic_review="uncertain")
    payload = record("ActivityPayload",
        activities={activity["id"]: activity},
        concepts={concept["id"]: concept},
        information_uses={use["id"]: use}, claims={claim["id"]: claim})

    accept_activity(model, packet, payload)
    accepted = model["activities"][activity["id"]]
    expected_effects = sorted(effect["id"] for effect in model["effects"].values()
        if trace["id"] in effect["trace_ids"])
    assert accepted["effect_ids"] == expected_effects
    assert accepted["input_binding_ids"]
    assert accepted["output_binding_ids"]
    assert accepted["information_use_ids"] == [use["id"]]
    stored_use = model["information_uses"][use["id"]]
    assert stored_use["trace_ids"] == [trace["id"]]
    assert stored_use["binding_ids"] == read["binding_ids"]
    assert stored_use["effect_ids"] == []
    validate_references(model)
