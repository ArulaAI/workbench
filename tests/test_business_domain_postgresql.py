"""PostgreSQL triggers, row-level security, body bounds and SQL test scripts."""
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


def _codes(facts):
    return [item["code"] for item in facts["warnings"]]


def _trigger_anchors(facts):
    return {anchor["operation"]["name"]: anchor
            for anchor in facts["anchors"].values()
            if any((item["registration"] or {}).get("kind") == "database_trigger"
                   for item in anchor["representations"])}


AUDIT_FUNCTION = """CREATE FUNCTION audit_order() RETURNS trigger AS $$
BEGIN
  INSERT INTO order_audit(order_id) VALUES (NEW.id);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


@pytest.mark.parametrize("statement, expected", [
    ("CREATE TRIGGER order_audit AFTER INSERT ON orders "
     "FOR EACH ROW EXECUTE FUNCTION audit_order();",
     {"timing": "AFTER", "event": "INSERT", "target": "orders",
      "scope": "row", "condition": None}),
    ("CREATE OR REPLACE TRIGGER order_audit BEFORE UPDATE OF status ON public.orders\n"
     "  FOR EACH STATEMENT EXECUTE PROCEDURE public.audit_order();",
     {"timing": "BEFORE", "event": "UPDATE OF STATUS", "target": "public.orders",
      "scope": "statement", "condition": None}),
    ("CREATE CONSTRAINT TRIGGER order_audit AFTER INSERT OR DELETE ON orders\n"
     "  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW\n"
     "  WHEN (NEW.total > 100) EXECUTE FUNCTION audit_order('large');",
     {"timing": "AFTER", "event": "INSERT OR DELETE", "target": "orders",
      "scope": "row", "condition": "NEW.total > 100"}),
])
def test_create_trigger_is_an_entry_point_that_selects_its_function(
        tmp_path, statement, expected):
    facts, units = _extract(tmp_path, {"audit.sql": AUDIT_FUNCTION + statement + "\n"})

    anchors = _trigger_anchors(facts)
    assert list(anchors) == ["order_audit"]
    anchor = anchors["order_audit"]
    registration = next(item for item in anchor["representations"]
                        if item["role"] == "registration")
    assert registration["eligibility"] == "eligible"
    assert {key: registration["registration"][key] for key in expected} == expected
    assert registration["registration"]["resolution"] == "resolved"
    evidence = facts["evidence"][registration["registration"]["evidence_ids"][0]]
    assert "EXECUTE" in evidence["excerpt"]

    function = next(unit for unit in units if unit.name == "audit_order")
    edge = next(edge for edge in facts["edges"].values()
                if edge["kind"] == "selects_implementation")
    assert edge["resolution"] == "resolved"
    assert edge["from_ref"]["id"] == registration["symbol_id"]
    assert edge["to_ref"]["id"] == function.symbol_id
    assert {(item["role"], item["eligibility"], item["symbol_id"])
            for item in anchor["representations"]} == {
        ("registration", "eligible", registration["symbol_id"]),
        ("implementation", "supporting", function.symbol_id)}
    assert [item["state"] for item in anchor["correspondences"]] == ["resolved"]
    # A trigger function cannot be called directly; the trigger is its entry point.
    assert len(facts["anchors"]) == 1
    trace = next(iter(facts["traces"].values()))
    assert function.symbol_id in trace["symbol_ids"] and edge["id"] in trace["edge_ids"]


def test_trigger_selects_a_function_declared_later_in_another_file(tmp_path):
    facts, units = _extract(tmp_path, {
        "a_triggers.sql": "CREATE TRIGGER order_audit AFTER INSERT ON billing.orders\n"
                          "FOR EACH ROW EXECUTE FUNCTION billing.audit_order();\n",
        "b_functions.sql": AUDIT_FUNCTION.replace("audit_order()", "billing.audit_order()", 1),
    })

    function = next(unit for unit in units if unit.name == "audit_order")
    edge = next(edge for edge in facts["edges"].values()
                if edge["kind"] == "selects_implementation")
    assert edge["resolution"] == "resolved"
    assert edge["to_ref"]["id"] == function.symbol_id
    assert list(_trigger_anchors(facts)) == ["order_audit"]
    trace = next(iter(facts["traces"].values()))
    assert function.symbol_id in trace["symbol_ids"] and edge["id"] in trace["edge_ids"]
    assert not [item for item in trace["obligation_ids"]
                if facts["trace_obligations"][item]["reason_code"]
                == "IMPLEMENTATION_NOT_REACHED"]


def test_trigger_whose_function_is_not_declared_stays_unresolved(tmp_path):
    facts, _ = _extract(tmp_path, {
        "triggers.sql": "CREATE TRIGGER order_audit AFTER INSERT ON orders\n"
                        "FOR EACH ROW EXECUTE FUNCTION missing_audit();\n"})

    anchor = _trigger_anchors(facts)["order_audit"]
    representation = anchor["representations"][0]
    assert anchor["resolution"] == "unresolved"
    assert "missing_audit() is not declared" in anchor["reason"]
    assert representation["eligibility"] == "unresolved"
    assert representation["registration"]["resolution"] == "unresolved"
    assert [item["state"] for item in anchor["correspondences"]] == ["unresolved"]
    assert not [edge for edge in facts["edges"].values()
                if edge["kind"] == "selects_implementation"]
    assert "SQL_IMPLEMENTATION_UNAVAILABLE" in _codes(facts)
    assert next(iter(facts["traces"].values()))["resolution"] == "unresolved"


def test_trigger_function_declared_twice_is_ambiguous(tmp_path):
    facts, units = _extract(tmp_path, {
        "one.sql": AUDIT_FUNCTION,
        "two.sql": AUDIT_FUNCTION,
        "triggers.sql": "CREATE TRIGGER order_audit AFTER INSERT ON orders\n"
                        "FOR EACH ROW EXECUTE FUNCTION audit_order();\n"})

    anchor = _trigger_anchors(facts)["order_audit"]
    edge = next(edge for edge in facts["edges"].values()
                if edge["kind"] == "selects_implementation")
    functions = sorted(unit.symbol_id for unit in units if unit.name == "audit_order")
    assert edge["resolution"] == "ambiguous" and edge["to_ref"] is None
    assert sorted(edge["candidate_target_ids"]) == functions
    assert anchor["resolution"] == "ambiguous"
    assert "SQL_IMPLEMENTATION_AMBIGUOUS" in _codes(facts)


POLICIES = """CREATE TABLE accounts (id uuid, owner_id uuid, personal boolean);
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
create policy "Accounts are viewable by owners" on accounts
    for select
    to authenticated
    using (owner_id = auth.uid());
CREATE POLICY accounts_insert ON public.accounts AS RESTRICTIVE FOR INSERT
    TO authenticated, service_role
    WITH CHECK (
        -- personal accounts are created by the signup trigger
        personal = false);
CREATE POLICY ledger_update ON ledger FOR UPDATE
    USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
"""


def test_row_level_security_policies_become_authorization_rule_observations(tmp_path):
    facts, units = _extract(tmp_path, {"rls.sql": POLICIES})

    observations = {item["native_expression"]: item
                    for item in facts["rule_observations"].values()}
    viewable = observations['CREATE POLICY "Accounts are viewable by owners" ON accounts '
                            'AS PERMISSIVE FOR SELECT TO authenticated '
                            'using (owner_id = auth.uid())']
    assert viewable["source_location_kind"] == "sql"
    assert viewable["scope"]["actor"] == "authenticated"
    assert "USING predicate" in viewable["reason"]
    assert "enablement for this table is declared" in viewable["reason"]
    assert viewable["resolution"] == "unresolved"
    table = facts["resources"][viewable["dependency_ids"][0]]
    assert (table["kind"], table["name"], table["resolution"]) == (
        "table", "accounts", "resolved")
    assert facts["evidence"][viewable["evidence_ids"][0]]["excerpt"] == (
        "using (owner_id = auth.uid())")

    insert = observations['CREATE POLICY "accounts_insert" ON public.accounts '
                          'AS RESTRICTIVE FOR INSERT TO authenticated, service_role '
                          'WITH CHECK ( personal = false)']
    assert insert["scope"]["actor"] == "authenticated, service_role"
    assert "WITH CHECK predicate" in insert["reason"]

    ledger = [item for item in facts["rule_observations"].values()
              if item["native_expression"].startswith('CREATE POLICY "ledger_update"')]
    assert len(ledger) == 2
    assert all("was not observed" in item["reason"] for item in ledger)

    enabled = observations["ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;"]
    assert "Row-level security is enabled on accounts" in enabled["reason"]

    policy_units = [unit for unit in units
                    if getattr(unit, "sql_declaration_kind", None) == "row_security_policy"]
    assert len(policy_units) == 3
    assert {facts["symbols"][unit.symbol_id]["kind"] for unit in policy_units} == {"module"}
    assert not facts["anchors"]
    assert "SQL_DIALECT_UNDETERMINED" not in _codes(facts)


def test_language_sql_body_ends_at_its_dollar_quote(tmp_path):
    facts, units = _extract(tmp_path, {"accounts.sql": """
create or replace function has_role(account_id uuid)
    returns boolean language sql security definer
as $$
select exists(select 1 from account_user wu where wu.account_id = has_role.account_id);
$$;

grant execute on function has_role(uuid) to authenticated;
comment on function has_role(uuid) is 'Membership check';

create policy "members" on accounts for select using (has_role(id) = true);

create function touch() returns integer language plpgsql as $$
begin
  return 1;
end;
$$;
"""})

    has_role = next(unit for unit in units if unit.name == "has_role")
    assert has_role.text.rstrip().endswith("has_role.account_id);")
    assert [unit.name for unit in units if unit.kind == "declarative_operation"] == [
        "has_role", "touch"]
    assert "SQL_MATERIAL_PARSE_ERROR" not in _codes(facts)
    assert not [edge for edge in facts["edges"].values() if edge["kind"] == "calls"
                and edge["from_ref"]["id"] == has_role.symbol_id]
    reads = [edge for edge in facts["edges"].values() if edge["kind"] == "reads_data"
             and edge["from_ref"]["id"] == has_role.symbol_id]
    assert reads and all(edge["resolution"] for edge in reads)


def test_plpgsql_into_and_parenthesized_subqueries_parse(tmp_path):
    facts, units = _extract(tmp_path, {"lookup.sql": """
create function lookup(p_token text) returns json language plpgsql as $$
declare
    name text;
    active boolean;
    cfg record;
begin
    SELECT * from config limit 1 into cfg;
    select account_name, id is not null
    into strict name, active
    from invitations where token = p_token;
    if (select count(*) from invitations where token = p_token) = 0 then
        raise exception 'missing';
    end if;
    name := (select account_name from invitations where token = p_token);
    return json_build_object('active', active, 'name', name);
end;
$$;
"""})

    assert "SQL_MATERIAL_PARSE_ERROR" not in _codes(facts)
    unit = next(unit for unit in units if unit.name == "lookup")
    assert len(unit.sql_dml) == 4
    assert all(statement["ast"] is not None for statement in unit.sql_dml)
    trailing = unit.sql_dml[0]
    assert [value["name"] for value in trailing["output_values"]] == ["cfg"]
    leading = unit.sql_dml[1]
    assert [value["name"] for value in leading["output_values"]] == ["name", "active"]


def test_unparseable_postgresql_statement_is_still_reported(tmp_path):
    facts, _ = _extract(tmp_path, {"broken.sql": """
create function broken() returns void language plpgsql as $$
begin
    update accounts set = 1 where id = 2;
end;
$$;
"""})

    assert "SQL_MATERIAL_PARSE_ERROR" in _codes(facts)


def test_test_seed_and_ci_sql_scripts_are_reference_only_test_evidence(tmp_path):
    script = "BEGIN;\nselect plan(1);\nselect has_table('accounts');\nROLLBACK;\n"
    facts, units = _extract(tmp_path, {
        "supabase/tests/database/01-accounts.sql": script,
        "supabase/seed.sql": "insert into accounts(id) values (1);\n",
        "db/seeds/users.sql": "insert into users(id) values (1);\n",
        ".github/workflows/setup-testing.sql": "create extension pgtap;\n",
        "supabase/migrations/001_accounts.sql": AUDIT_FUNCTION,
    })

    scripts = {"supabase/tests/database/01-accounts.sql", "supabase/seed.sql",
               "db/seeds/users.sql", ".github/workflows/setup-testing.sql"}
    assert not [unit for unit in units if unit.source.path in scripts]
    assert "SQL_DIALECT_UNDETERMINED" not in _codes(facts)
    resources = {item["name"]: item for item in facts["resources"].values()
                 if item["kind"] == "repository_file"}
    for path in scripts:
        assert resources[path]["reason"].startswith(
            "Reference-only sql_test_and_provisioning_script")
        assert all(facts["evidence"][key]["source_kind"] == "test"
                   for key in resources[path]["evidence_ids"])
    assert [anchor["operation"]["name"] for anchor in facts["anchors"].values()] == [
        "audit_order"]
    assert all(facts["evidence"][key]["source_kind"] == "source"
               for anchor in facts["anchors"].values()
               for key in anchor["evidence_ids"])


def test_merge_is_one_statement_writing_its_target(tmp_path):
    # Bounding nested subqueries must not split MERGE's WHEN branches into
    # free-standing UPDATE/INSERT fragments.
    facts, units = _extract(tmp_path, {"merge.sql": """
CREATE OR REPLACE PROCEDURE roll_up(p_card_id IN NUMBER) IS
BEGIN
  MERGE INTO velocity_counters vc
  USING (SELECT card_id, COUNT(1) AS txn_count FROM transactions t
          WHERE t.card_id = p_card_id GROUP BY card_id) s
     ON (vc.card_id = s.card_id)
  WHEN MATCHED THEN
    UPDATE SET vc.txn_count = s.txn_count
  WHEN NOT MATCHED THEN
    INSERT (card_id, txn_count) VALUES (s.card_id, s.txn_count);
END roll_up;
/
"""})

    unit = next(unit for unit in units if unit.name == "roll_up")
    assert "SQL_MATERIAL_PARSE_ERROR" not in _codes(facts)
    assert len(unit.sql_dml) == 1 and unit.sql_dml[0]["ast"] is not None
    assert unit.valid_terminal is True
    targets = {(edge["kind"], facts["resources"][edge["to_ref"]["id"]]["name"])
               for edge in facts["edges"].values()
               if edge["kind"] in {"reads_data", "writes_data"}}
    assert targets == {("writes_data", "velocity_counters"),
                       ("reads_data", "transactions")}
