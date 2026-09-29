"""F-05 SQL call-classification and resolution acceptance coverage."""
from pathlib import Path

import pytest

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


def _calls(facts):
    return [edge for edge in facts["edges"].values() if edge["kind"] == "calls"]


NOISE = """
CREATE TABLE billed_items (bill_id NUMBER, amount NUMBER);
CREATE TABLE bills (id NUMBER, amount NUMBER);
CREATE TABLE items (id NUMBER);
CREATE OR REPLACE PROCEDURE analyze_noise(p_id IN NUMBER) IS
  TYPE number_map IS TABLE OF NUMBER INDEX BY PLS_INTEGER;
  v_sum number_map;
BEGIN
  INSERT INTO billed_items (bill_id, amount) VALUES (p_id, 1);
  SELECT NVL(SUM(b.amount), 0), MAX(b.amount), TRUNC(SYSDATE),
         ROUND(b.amount), SUBSTR('x', 1), TO_NUMBER('1'), TO_CHAR(SYSDATE),
         CEIL(b.amount), NUMTODSINTERVAL(1, 'day')
    INTO p_id, p_id, p_id, p_id, p_id, p_id, p_id, p_id, p_id
    FROM bills b JOIN items i ON (b.id = i.id);
  v_sum(p_id) := 1;
  IF p_id IN (1, 2) THEN NULL; END IF;
END;
/
"""


def test_grocery_negative_contexts_are_typed_not_false_calls(tmp_path):
    facts, units = _extract(tmp_path, {"noise.sql": NOISE})

    assert _calls(facts) == []
    observations = [item["native_expression"]
        for item in facts["rule_observations"].values()]
    assert any(item.upper().startswith("ON (") for item in observations)
    for name in ("NVL", "SUM", "MAX", "TRUNC", "ROUND", "SUBSTR",
            "TO_NUMBER", "TO_CHAR", "CEIL", "NUMTODSINTERVAL", "v_sum"):
        assert any(item.casefold().startswith(name.casefold() + "(")
            for item in observations)
    assert not any(item.casefold().startswith(("on(", "in(", "as(",
        "using(", "when(")) for item in observations)

    write = next(edge for edge in facts["edges"].values()
        if edge["kind"] == "writes_data")
    assert facts["resources"][write["to_ref"]["id"]]["name"] == "billed_items"
    assert write["resolution"] == "unresolved"
    assert "completion remains caller-controlled" in write["reason"]
    binding_names = {facts["bindings"][key]["name"] for key in write["binding_ids"]}
    assert any(name.startswith("billed_items.bill_id@") for name in binding_names)
    assert any(name.startswith("billed_items.amount@") for name in binding_names)
    assert facts["evidence"][write["evidence_ids"][0]]["excerpt"].lstrip().startswith(
        "INSERT INTO billed_items")
    assert next(unit for unit in units if unit.name == "analyze_noise").valid_terminal is True


def test_sql_keywords_before_parentheses_never_become_call_targets(tmp_path):
    facts, _ = _extract(tmp_path, {"keywords.sql": """
CREATE OR REPLACE PROCEDURE keyword_contexts IS
BEGIN
  FOR item IN (SELECT 1 AS value FROM dual) LOOP NULL; END LOOP;
  CASE WHEN (1 = 1) THEN NULL; END CASE;
  EXECUTE IMMEDIATE 'SELECT 1 FROM dual' USING (1);
END;
/
"""})
    excerpts = [facts["evidence"][edge["evidence_ids"][0]]["excerpt"]
        for edge in _calls(facts)]
    assert excerpts == ["EXECUTE IMMEDIATE 'SELECT 1 FROM dual' USING (1);"]
    assert all(not excerpt.casefold().startswith(("in(", "as(", "using(", "when("))
        for excerpt in excerpts)


def test_local_and_external_calls_have_exact_evidence_and_distinct_outcomes(tmp_path):
    facts, units = _extract(tmp_path, {"demo.sql": """
CREATE OR REPLACE PACKAGE demo AS
  PROCEDURE helper(p_id IN NUMBER);
  PROCEDURE run(p_id IN NUMBER);
END demo;
/
CREATE OR REPLACE PACKAGE BODY demo AS
  PROCEDURE helper(p_id IN NUMBER) IS BEGIN NULL; END helper;
  PROCEDURE run(p_id IN NUMBER) IS BEGIN
    HeLpEr(p_id);
    DBMS_OUTPUT.PUT_LINE(p_id);
  END run;
END demo;
/
"""})
    calls = _calls(facts)
    assert len(calls) == 2
    local = next(edge for edge in calls if edge["resolution"] == "resolved")
    external = next(edge for edge in calls if edge["to_ref"]["kind"] == "resource")
    assert facts["symbols"][local["to_ref"]["id"]]["qualified_name"].casefold().endswith(
        "::demo.helper")
    assert facts["evidence"][local["evidence_ids"][0]]["excerpt"] == "HeLpEr(p_id)"
    assert facts["evidence"][external["evidence_ids"][0]]["excerpt"] == "DBMS_OUTPUT.PUT_LINE(p_id)"
    assert "external package call" in external["reason"]
    assert all(facts["evidence"][edge["evidence_ids"][0]]["extractor"].endswith(
        "/sqlglot") for edge in calls)
    results = [result for unit in units for result in unit.source.semantic_results]
    assert any(result["outcome"] == "external"
        and result["diagnostic_code"] == "SQL_EXTERNAL_PACKAGE_CALL"
        for result in results)


def test_package_and_schema_qualified_call_resolves_exact_member(tmp_path):
    facts, _ = _extract(tmp_path, {"packages.sql": """
CREATE OR REPLACE PACKAGE app.jta_error AS
  PROCEDURE log_error(p_code IN NUMBER, p_message IN VARCHAR2);
END jta_error;
/
CREATE OR REPLACE PACKAGE BODY app.jta_error AS
  PROCEDURE log_error(p_code IN NUMBER, p_message IN VARCHAR2) IS BEGIN NULL; END;
END jta_error;
/
CREATE OR REPLACE PACKAGE app.worker AS
  PROCEDURE run;
END worker;
/
CREATE OR REPLACE PACKAGE BODY app.worker AS
  PROCEDURE run IS BEGIN
    app.jta_error.log_error(1, 'bad');
  END;
END worker;
/
"""})
    call = next(edge for edge in _calls(facts)
        if facts["evidence"][edge["evidence_ids"][0]]["excerpt"].startswith("app."))
    assert call["resolution"] == "resolved"
    assert facts["symbols"][call["to_ref"]["id"]]["qualified_name"].casefold().endswith(
        "::app.jta_error.log_error")


def test_overloads_use_types_and_named_arguments_or_remain_bounded_ambiguous(tmp_path):
    facts, _ = _extract(tmp_path, {"overloads.sql": """
CREATE OR REPLACE PACKAGE choose AS
  PROCEDURE save(value IN NUMBER);
  PROCEDURE save(value IN DATE);
  PROCEDURE pick(p_num IN NUMBER);
  PROCEDURE pick(p_text IN VARCHAR2);
  PROCEDURE run(p_unknown IN mystery_type);
END choose;
/
CREATE OR REPLACE PACKAGE BODY choose AS
  PROCEDURE save(value IN NUMBER) IS BEGIN NULL; END;
  PROCEDURE save(value IN DATE) IS BEGIN NULL; END;
  PROCEDURE pick(p_num IN NUMBER) IS BEGIN NULL; END;
  PROCEDURE pick(p_text IN VARCHAR2) IS BEGIN NULL; END;
  PROCEDURE run(p_unknown IN mystery_type) IS BEGIN
    save(1);
    pick(p_text => 'chosen');
    save(NULL);
  END;
END choose;
/
"""})
    calls = sorted(_calls(facts),
        key=lambda edge: facts["evidence"][edge["evidence_ids"][0]]["excerpt"])
    numeric = next(edge for edge in calls
        if facts["evidence"][edge["evidence_ids"][0]]["excerpt"] == "save(1)")
    named = next(edge for edge in calls
        if facts["evidence"][edge["evidence_ids"][0]]["excerpt"].startswith("pick("))
    ambiguous = next(edge for edge in calls
        if "NULL" in facts["evidence"][edge["evidence_ids"][0]]["excerpt"])
    assert numeric["resolution"] == named["resolution"] == "resolved"
    assert "IN NUMBER" in facts["symbols"][numeric["to_ref"]["id"]]["signature"]
    assert "p_text" in facts["evidence"][named["evidence_ids"][0]]["excerpt"]
    assert ambiguous["resolution"] == "ambiguous"
    assert len(ambiguous["candidate_target_ids"]) == 2


def test_dynamic_sql_is_exactly_evidenced_and_remains_on_frontier(tmp_path):
    facts, units = _extract(tmp_path, {"dynamic.sql": """
CREATE OR REPLACE PROCEDURE dispatch(p_sql IN VARCHAR2) IS
BEGIN
  EXECUTE IMMEDIATE p_sql USING 1;
END;
/
"""})
    edge = _calls(facts)[0]
    assert edge["resolution"] == "unresolved" and edge["to_ref"] is None
    assert "runtime" in edge["reason"]
    assert facts["evidence"][edge["evidence_ids"][0]]["excerpt"] == \
        "EXECUTE IMMEDIATE p_sql USING 1;"
    trace = next(iter(facts["traces"].values()))
    assert edge["id"] in trace["edge_ids"] and edge["id"] in trace["frontier_ids"]
    assert trace["resolution"] == "unresolved"
    assert any(result["diagnostic_code"] == "SQL_DYNAMIC_CALL"
        for result in units[0].source.semantic_results)


def test_material_parse_gap_has_exact_diagnostic_and_invalid_terminal(tmp_path):
    facts, units = _extract(tmp_path, {"broken.sql": """
CREATE OR REPLACE PROCEDURE broken IS
BEGIN
  SELECT id FROM;
END;
/
"""})
    warning = next(item for item in facts["warnings"]
        if item["code"] == "SQL_MATERIAL_PARSE_ERROR")
    evidence = facts["evidence"][warning["evidence_ids"][0]]
    assert evidence["excerpt"] and evidence["extractor"].endswith("/sqlglot")
    assert "sqlglot/oracle 30.18.0" in warning["message"]
    unit = next(unit for unit in units if unit.name == "broken")
    assert unit.valid_terminal is False
    assert {"call_classification", "callable_resolution"} <= set(
        unit.required_capabilities)


def test_honest_unresolved_call_remains_after_false_frontiers_are_removed(tmp_path):
    facts, _ = _extract(tmp_path, {"missing.sql": """
CREATE OR REPLACE PROCEDURE run IS
BEGIN
  unavailable_application_procedure();
  SELECT NVL(SUM(amount), 0) INTO total FROM missing_table t
    JOIN another_table a ON (a.id = t.id);
END;
/
"""})
    calls = _calls(facts)
    assert len(calls) == 1
    assert calls[0]["resolution"] == "unresolved"
    assert "unavailable_application_procedure" in calls[0]["reason"]
    assert not any(token in calls[0]["reason"].casefold()
        for token in (" on", "nvl", "sum", "missing_table"))
    trace = next(iter(facts["traces"].values()))
    assert calls[0]["id"] in trace["edge_ids"]


GROCERY = Path("/private/tmp/speed-domain-grocery")


@pytest.mark.skipif(not (GROCERY / "JTA_Packages.sql").is_file(),
    reason="optional local Grocery corpus is unavailable")
def test_live_grocery_corpus_has_no_false_call_frontiers(tmp_path):
    for name in ("JTA_Create_Database.sql", "JTA_Packages.sql"):
        (tmp_path / name).write_text((GROCERY / name).read_text())
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    forbidden = {"on", "in", "as", "using", "when", "billed_items",
        "nvl", "sum", "max", "trunc", "round", "substr", "to_number",
        "to_char", "ceil", "numtodsinterval", "v_all", "v_sum"}
    false_edges = []
    for edge in _calls(facts):
        excerpt = facts["evidence"][edge["evidence_ids"][0]]["excerpt"].strip()
        callee = excerpt.split("(", 1)[0].rsplit(".", 1)[-1].casefold()
        if callee in forbidden:
            false_edges.append(edge)
    assert false_edges == []
    assert any(edge["resolution"] == "resolved" for edge in _calls(facts))
    assert any(trace["resolution"] == "resolved"
        for trace in facts["traces"].values())
    assert all("source candidates" not in (edge["reason"] or "")
        for edge in _calls(facts) if edge["to_ref"]
        and edge["to_ref"]["kind"] == "resource")
