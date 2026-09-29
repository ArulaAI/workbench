"""F-07 SQL registration, visibility, and trigger identity coverage."""
from pathlib import Path

import pytest

from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import DEFAULTS, validate_references


def _extract(tmp_path, text):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "entrypoints.sql").write_text(text)
    facts, units = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    return facts, units


def test_public_contract_selects_body_while_private_helper_stays_supporting(tmp_path):
    facts, units = _extract(tmp_path, """
CREATE OR REPLACE PACKAGE payroll AS
  PROCEDURE process(run_date IN DATE);
END payroll;
/
CREATE OR REPLACE PACKAGE BODY payroll AS
  PROCEDURE helper(run_date IN DATE) IS BEGIN NULL; END helper;
  PROCEDURE process(run_date IN DATE) IS BEGIN helper(run_date); END process;
END payroll;
/
""")

    assert len(facts["anchors"]) == 1
    anchor = next(iter(facts["anchors"].values()))
    assert {(item["role"], item["eligibility"], item["visibility"])
            for item in anchor["representations"]} == {
        ("contract", "eligible", "public"),
        ("implementation", "supporting", "internal"),
    }
    helper = next(unit for unit in units if unit.name == "helper")
    process = next(unit for unit in units
        if unit.name == "process" and unit.executable_body)
    assert helper.anchor_id is None
    assert (helper.anchor_role, helper.anchor_eligibility, helper.anchor_visibility) == (
        "implementation", "supporting", "internal")
    call = next(edge for edge in facts["edges"].values()
        if edge["kind"] == "calls" and edge["from_ref"]["id"] == process.symbol_id)
    assert call["resolution"] == "resolved"
    assert call["to_ref"]["id"] == helper.symbol_id
    trace = next(iter(facts["traces"].values()))
    assert helper.symbol_id in trace["symbol_ids"]


def test_trigger_registration_is_structured_and_selects_its_body(tmp_path):
    facts, _ = _extract(tmp_path, """
CREATE TABLE staff (job_id NUMBER);
CREATE OR REPLACE TRIGGER update_job_history_trigger
AFTER INSERT OR UPDATE OF job_id ON staff FOR EACH ROW
WHEN (NEW.job_id != OLD.job_id)
BEGIN
  NULL;
END update_job_history_trigger;
/
CREATE OR REPLACE TRIGGER logon_trigger
AFTER LOGON ON SCHEMA
BEGIN
  NULL;
END logon_trigger;
/
""")

    assert len(facts["anchors"]) == 2
    by_name = {anchor["operation"]["name"]: anchor
               for anchor in facts["anchors"].values()}
    expected = {
        "update_job_history_trigger": {
            "event": "INSERT OR UPDATE OF JOB_ID", "timing": "AFTER",
            "target": "staff", "scope": "row",
            "condition": "NEW.job_id != OLD.job_id",
        },
        "logon_trigger": {
            "event": "LOGON", "timing": "AFTER", "target": "SCHEMA",
            "scope": "schema", "condition": None,
        },
    }
    for name, fields in expected.items():
        anchor = by_name[name]
        assert anchor["canonical_anchor_id"] == anchor["id"]
        assert {(item["role"], item["eligibility"], item["visibility"])
                for item in anchor["representations"]} == {
            ("registration", "eligible", "public"),
            ("implementation", "supporting", "internal"),
        }
        representation = next(item for item in anchor["representations"]
                              if item["role"] == "registration")
        registration = representation["registration"]
        assert registration["kind"] == "database_trigger"
        assert {key: registration[key] for key in fields} == fields
        assert registration["resolution"] == "resolved"
        assert registration["reason"] is None
        assert registration["evidence_ids"]
        evidence = facts["evidence"][registration["evidence_ids"][0]]["excerpt"]
        assert fields["event"].casefold() in " ".join(evidence.split()).casefold()
        edge = next(edge for edge in facts["edges"].values()
            if edge["kind"] == "selects_implementation"
            and edge["from_ref"]["id"] == representation["symbol_id"])
        implementation = next(item for item in anchor["representations"]
                              if item["role"] == "implementation")
        assert edge["resolution"] == "resolved"
        assert edge["to_ref"]["id"] == implementation["symbol_id"]
        trace = next(item for item in facts["traces"].values()
                     if item["anchor_id"] == anchor["id"])
        assert edge["id"] in trace["edge_ids"]


def test_trigger_firing_semantics_participate_in_canonical_identity(tmp_path):
    first, _ = _extract(tmp_path / "first", """
CREATE OR REPLACE TRIGGER audit_trigger AFTER INSERT ON invoices
BEGIN NULL; END audit_trigger;
/
""")
    second, _ = _extract(tmp_path / "second", """
CREATE OR REPLACE TRIGGER audit_trigger BEFORE DELETE ON invoices
BEGIN NULL; END audit_trigger;
/
""")

    first_anchor = next(iter(first["anchors"].values()))
    second_anchor = next(iter(second["anchors"].values()))
    assert first_anchor["id"] != second_anchor["id"]


def test_standalone_schema_routine_has_normalized_callable_registration(tmp_path):
    facts, _ = _extract(tmp_path, """
CREATE OR REPLACE PROCEDURE reconcile_invoice(invoice_id IN NUMBER) IS
BEGIN NULL; END reconcile_invoice;
/
""")

    anchor = next(iter(facts["anchors"].values()))
    representation = anchor["representations"][0]
    assert representation["role"] == "registration"
    assert representation["eligibility"] == "eligible"
    assert representation["visibility"] == "public"
    assert representation["registration"] == {
        "kind": "callable_exposure", "event": "invoke", "timing": None,
        "target": "reconcile_invoice", "scope": "schema", "condition": None,
        "label": None,
        "candidate_targets": [],
        "evidence_ids": representation["registration"]["evidence_ids"],
        "resolution": "resolved", "reason": None,
    }
    evidence = facts["evidence"][representation["registration"]["evidence_ids"][0]]
    assert "PROCEDURE reconcile_invoice" in evidence["excerpt"]


GROCERY = Path("/private/tmp/speed-domain-grocery")


@pytest.mark.skipif(not (GROCERY / "JTA_Packages.sql").is_file(),
    reason="optional local Grocery corpus is unavailable")
def test_live_grocery_accounts_for_all_29_prior_body_candidates():
    facts, units = Extractor(GROCERY, DEFAULTS).extract()
    validate_references(facts)
    bodies = [unit for unit in units if getattr(unit, "sql_declaration_kind", None)
              in {"package_body", "trigger_body"}]
    specs = [unit for unit in units
             if getattr(unit, "sql_declaration_kind", None) == "package_spec"]
    trigger_registrations = [unit for unit in units
        if getattr(unit, "sql_declaration_kind", None) == "trigger_registration"]

    assert len(specs) == 24
    assert len(bodies) == 29
    assert len(trigger_registrations) == 4
    assert len(facts["anchors"]) == 28
    helper = next(unit for unit in bodies if unit.name == "get_hours")
    assert helper.anchor_id is None and helper.anchor_eligibility == "supporting"
    payroll = next(unit for unit in bodies if unit.name == "process_payroll")
    payroll_trace = next(trace for trace in facts["traces"].values()
                         if trace["anchor_id"] == payroll.anchor_id)
    assert helper.symbol_id in payroll_trace["symbol_ids"]
    assert all(unit.symbol_id in facts["symbols"] for unit in bodies)
    assert sum(unit.anchor_id is not None for unit in bodies) == 28
    trigger_anchors = [anchor for anchor in facts["anchors"].values()
        if any(item["registration"] is not None
               for item in anchor["representations"])]
    assert len(trigger_anchors) == 4
    assert all({item["role"] for item in anchor["representations"]}
               == {"registration", "implementation"}
               for anchor in trigger_anchors)
    registrations = {
        anchor["operation"]["name"]: next(item["registration"]
            for item in anchor["representations"] if item["registration"])
        for anchor in trigger_anchors
    }
    assert {name: {field: registration[field] for field in
            ("event", "timing", "target", "scope", "condition")}
            for name, registration in registrations.items()} == {
        "update_job_history_trigger": {
            "event": "INSERT OR UPDATE OF JOB_ID", "timing": "AFTER",
            "target": "staff", "scope": "row",
            "condition": "NEW.job_id != OLD.job_id",
        },
        "email_on_inv_trigger": {
            "event": "UPDATE OF QUANTITY", "timing": "AFTER",
            "target": "inventory_by_location", "scope": "row",
            "condition": "NEW.quantity < OLD.quantity",
        },
        "logon_trigger": {
            "event": "LOGON", "timing": "AFTER", "target": "SCHEMA",
            "scope": "schema", "condition": None,
        },
        "logoff_trigger": {
            "event": "LOGOFF", "timing": "BEFORE", "target": "SCHEMA",
            "scope": "schema", "condition": None,
        },
    }
    for registration in registrations.values():
        excerpt = facts["evidence"][registration["evidence_ids"][0]]["excerpt"]
        assert registration["event"].casefold() in " ".join(excerpt.split()).casefold()
        if registration["condition"]:
            assert registration["condition"] in excerpt
