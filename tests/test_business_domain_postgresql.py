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


# ── Call resolution: keywords, defaults, literal coercion, platforms ─────

def _call_edges(facts, caller):
    symbols = facts["symbols"]
    return [edge for edge in facts["edges"].values()
            if edge["kind"] == "calls"
            and symbols[edge["from_ref"]["id"]]["qualified_name"].split("::")[-1].split("(")[0]
                .rsplit(".", 1)[-1] == caller]


def _callee(facts, edge):
    target = edge["to_ref"]
    if not target:
        return None
    if target["kind"] == "symbol":
        return facts["symbols"][target["id"]]["qualified_name"].split("::")[-1].split("(")[0]
    return facts["resources"][target["id"]]


ROLES = """CREATE TYPE basejump.account_role AS ENUM ('owner', 'member');
CREATE FUNCTION basejump.has_role_on_account(account_id uuid,
    account_role basejump.account_role DEFAULT NULL) RETURNS boolean AS $$
  SELECT true;
$$ LANGUAGE sql;
"""


def _postgres_caller(body, name="caller"):
    return (f"CREATE FUNCTION public.{name}(account_id uuid) RETURNS json AS $$\n"
            f"BEGIN\n{body}\nEND;\n$$ LANGUAGE plpgsql;\n")


@pytest.mark.parametrize("body", [
    "  RETURN (SELECT json_agg(x) FROM accounts x);",
    "  IF (SELECT count(1) FROM accounts) > 0 THEN RETURN NULL; END IF;",
    "  RETURN QUERY (SELECT 1);",
])
def test_procedural_keywords_before_a_parenthesis_are_not_calls(tmp_path, body):
    facts, _ = _extract(tmp_path, {"supabase/migrations/1_caller.sql": _postgres_caller(body)})
    excerpts = [facts["evidence"][edge["evidence_ids"][0]]["excerpt"]
                for edge in _call_edges(facts, "caller")]
    assert not [text for text in excerpts if text.casefold().startswith(("return", "if", "query"))]


@pytest.mark.parametrize("call", [
    "basejump.has_role_on_account(account_id)",              # trailing default omitted
    "basejump.has_role_on_account(account_id, 'owner')",     # literal coerced to the enum
    "basejump.has_role_on_account(account_id => account_id)",
])
def test_defaults_and_literal_coercion_select_the_declared_function(tmp_path, call):
    facts, _ = _extract(tmp_path, {
        "supabase/migrations/1_caller.sql": ROLES + _postgres_caller(f"  PERFORM {call};")})
    [edge] = [edge for edge in _call_edges(facts, "caller")
              if "has_role_on_account" in facts["evidence"][edge["evidence_ids"][0]]["excerpt"]]
    assert edge["resolution"] == "resolved"
    assert _callee(facts, edge) == "basejump.has_role_on_account"


def test_a_required_parameter_cannot_be_omitted(tmp_path):
    roles = ROLES.replace("account_role basejump.account_role DEFAULT NULL",
                          "account_role basejump.account_role")
    facts, _ = _extract(tmp_path, {
        "supabase/migrations/1_caller.sql": roles + _postgres_caller(
            "  PERFORM basejump.has_role_on_account(account_id);")})
    [edge] = [edge for edge in _call_edges(facts, "caller")
              if "has_role_on_account" in facts["evidence"][edge["evidence_ids"][0]]["excerpt"]]
    assert edge["resolution"] == "unresolved" and edge["to_ref"] is None


def test_a_platform_routine_is_a_known_boundary_only_in_a_platform_layout(tmp_path):
    body = "  RETURN (SELECT auth.uid());"
    facts, _ = _extract(tmp_path, {
        "supabase/migrations/1_caller.sql": _postgres_caller(body),
        "db/2_other.sql": _postgres_caller(body, "other")})
    [platform] = _call_edges(facts, "caller")
    resource = _callee(facts, platform)
    assert resource["provider"] == "module:supabase/postgres"
    assert "Supabase" in platform["reason"]
    obligation = next(item for item in facts["trace_obligations"].values()
                      if item["edge_id"] == platform["id"])
    assert obligation["boundary"] == "library_call"
    # Outside a Supabase project layout nothing establishes the platform.
    [other] = _call_edges(facts, "other")
    assert other["resolution"] == "unresolved" and other["to_ref"] is None


def test_a_repository_declaration_outranks_the_platform_catalog(tmp_path):
    facts, _ = _extract(tmp_path, {"supabase/migrations/1_caller.sql": (
        "CREATE FUNCTION auth.uid() RETURNS uuid AS $$ SELECT NULL::uuid; $$ LANGUAGE sql;\n"
        + _postgres_caller("  RETURN (SELECT auth.uid());"))})
    [edge] = _call_edges(facts, "caller")
    assert _callee(facts, edge) == "auth.uid"


def test_a_platform_table_is_a_known_boundary_not_a_missing_table(tmp_path):
    facts, _ = _extract(tmp_path, {"supabase/migrations/1_caller.sql": _postgres_caller(
        "  RETURN (SELECT json_agg(u.email) FROM auth.users u);")})
    assert "SQL_PLATFORM_TABLE" in _codes(facts)
    assert "SQL_DATA_TARGET_UNRESOLVED" not in _codes(facts)
    [read] = [edge for edge in facts["edges"].values() if edge["kind"] == "reads_data"]
    obligation = next(item for item in facts["trace_obligations"].values()
                      if item["edge_id"] == read["id"])
    assert obligation["boundary"] == "library_call"


# ── Control conditions and declarations ──────────────────────────────────

def test_a_query_inside_an_if_condition_is_not_guarded_by_that_if(tmp_path):
    facts, units = _extract(tmp_path, {"supabase/migrations/1_caller.sql": _postgres_caller(
        "  IF (SELECT count(1) FROM accounts WHERE id = account_id) > 0 THEN\n"
        "    DELETE FROM accounts WHERE id = account_id;\n"
        "  END IF;")})
    assert "SQL_CONTROL_FLOW_UNRESOLVED" not in _codes(facts)
    unit = next(unit for unit in units if unit.name == "caller")
    condition = {statement["kind"].name: statement["control_condition"] for statement in unit.sql_dml}
    assert condition["SELECT"] is None
    assert condition["DELETE"].startswith("((SELECT count(1)")


ORACLE_CASE = """CREATE OR REPLACE PROCEDURE settle(p_id IN NUMBER) IS
  v_status VARCHAR2(10);
BEGIN
  v_status := CASE WHEN p_id > 0 THEN 'OK' ELSE 'BAD' END;
  UPDATE settlements SET status = v_status WHERE id = p_id;
  COMMIT;
EXCEPTION
  WHEN OTHERS THEN
    ROLLBACK;
    INSERT INTO exception_queue (id) VALUES (p_id);
END settle;
/
CREATE TABLE settlements (id NUMBER, status VARCHAR2(10));
CREATE TABLE exception_queue (id NUMBER);
"""


def test_a_case_expression_does_not_break_later_control_conditions(tmp_path):
    facts, units = _extract(tmp_path, {"settle.sql": ORACLE_CASE})
    assert "SQL_CONTROL_FLOW_UNRESOLVED" not in _codes(facts)
    unit = next(unit for unit in units if unit.name == "settle")
    handler = next(statement for statement in unit.sql_dml if statement["kind"].name == "INSERT")
    assert handler["control_condition"] == "(EXCEPTION WHEN OTHERS)"


def test_a_statement_inside_a_case_statement_branch_stays_incomplete(tmp_path):
    source = ORACLE_CASE.replace(
        "  v_status := CASE WHEN p_id > 0 THEN 'OK' ELSE 'BAD' END;\n",
        "  CASE WHEN p_id > 0 THEN\n    DELETE FROM settlements WHERE id = p_id;\n  END CASE;\n")
    _, units = _extract(tmp_path, {"settle.sql": source})
    unit = next(unit for unit in units if unit.name == "settle")
    delete = next(statement for statement in unit.sql_dml if statement["kind"].name == "DELETE")
    assert delete["control_complete"] is False


@pytest.mark.parametrize("declaration, routine", [
    ("CREATE GLOBAL TEMPORARY TABLE scratch (id NUMBER) ON COMMIT DELETE ROWS;",
     "CREATE OR REPLACE PROCEDURE purge IS\nBEGIN\n  DELETE FROM scratch;\nEND purge;\n/\n"),
    ("CREATE TEMPORARY TABLE scratch (id integer);",
     "CREATE FUNCTION purge() RETURNS void AS $$\nBEGIN\n  DELETE FROM scratch;\nEND;\n"
     "$$ LANGUAGE plpgsql;\n"),
    ("CREATE UNLOGGED TABLE IF NOT EXISTS scratch (id integer);",
     "CREATE FUNCTION purge() RETURNS void AS $$\nBEGIN\n  DELETE FROM scratch;\nEND;\n"
     "$$ LANGUAGE plpgsql;\n"),
])
def test_temporary_and_unlogged_tables_are_declared_tables(tmp_path, declaration, routine):
    facts, _ = _extract(tmp_path, {"job.sql": declaration + "\n" + routine})
    [table] = [resource for resource in facts["resources"].values()
               if resource["kind"] == "table" and resource["name"] == "scratch"]
    assert table["resolution"] == "resolved"


def test_oracle_dual_is_a_platform_table(tmp_path):
    facts, _ = _extract(tmp_path, {"job.sql": (
        "CREATE OR REPLACE PROCEDURE tick(p_id IN NUMBER) IS\n  v_now VARCHAR2(20);\nBEGIN\n"
        "  SELECT SYSDATE INTO v_now FROM dual;\nEND tick;\n/\n")})
    assert "SQL_PLATFORM_TABLE" in _codes(facts)
    assert "SQL_DATA_TARGET_UNRESOLVED" not in _codes(facts)


# ── IF as a statement vs IF() in an expression; platform trigger functions ─

LATE_FEES = """CREATE FUNCTION public.get_customer_balance(p_customer_id integer) RETURNS numeric
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_overfees INTEGER;
    v_payments DECIMAL(5,2);
BEGIN
    SELECT COALESCE(SUM(IF(rental.return_date > rental.rental_date, 1, 0)), 0) INTO v_overfees
    FROM rental WHERE rental.customer_id = p_customer_id;
    SELECT COALESCE(SUM(payment.amount), 0) INTO v_payments
    FROM payment WHERE payment.customer_id = p_customer_id;
    IF v_payments > 0 THEN
        DELETE FROM payment WHERE customer_id = p_customer_id;
    END IF;
    RETURN v_overfees - v_payments;
END
$$;
"""


def test_if_inside_an_expression_is_not_a_control_statement(tmp_path):
    facts, units = _extract(tmp_path, {"schema.sql": LATE_FEES})
    codes = _codes(facts)
    assert "SQL_MATERIAL_PARSE_ERROR" not in codes
    assert "SQL_CONTROL_FLOW_UNRESOLVED" not in codes
    unit = next(unit for unit in units if unit.name == "get_customer_balance")
    conditions = [(statement["kind"].name, statement["control_condition"])
                  for statement in unit.sql_dml]
    # Only the statement inside the real IF ... THEN is guarded.
    assert conditions == [("SELECT", None), ("SELECT", None),
                          ("DELETE", "(v_payments > 0)")]


def test_if_at_statement_start_is_still_a_block_and_not_a_call(tmp_path):
    facts, _ = _extract(tmp_path, {"schema.sql": LATE_FEES})
    excerpts = [facts["evidence"][edge["evidence_ids"][0]]["excerpt"]
                for edge in facts["edges"].values() if edge["kind"] == "calls"]
    assert not [text for text in excerpts if text.casefold().startswith("if")]


FULLTEXT = """CREATE TABLE film (film_id integer, fulltext tsvector, title text);
CREATE FUNCTION last_updated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.last_update = CURRENT_TIMESTAMP;
    RETURN NEW;
END $$;
CREATE TRIGGER film_fulltext_trigger BEFORE INSERT OR UPDATE ON film
    FOR EACH ROW EXECUTE FUNCTION tsvector_update_trigger('fulltext', 'pg_catalog.english', 'title');
"""


def test_a_trigger_running_a_platform_function_is_a_bounded_entry_point(tmp_path):
    facts, _ = _extract(tmp_path, {"schema.sql": FULLTEXT})
    assert "SQL_IMPLEMENTATION_UNAVAILABLE" not in _codes(facts)
    anchor = _trigger_anchors(facts)["film_fulltext_trigger"]
    assert anchor["resolution"] == "resolved"
    trace = next(trace for trace in facts["traces"].values() if trace["anchor_id"] == anchor["id"])
    assert (trace["resolution"], trace["completion"]) == ("unresolved", "bounded")
    [assumption] = trace["assumptions"]
    assert assumption["kind"] == "library_call"
    assert "tsvector_update_trigger" in assumption["statement"]


def test_an_unknown_qualified_trigger_function_is_still_unavailable(tmp_path):
    facts, _ = _extract(tmp_path, {"schema.sql": FULLTEXT.replace(
        "tsvector_update_trigger('fulltext'", "vendor.tsvector_update_trigger('fulltext'")})
    assert "SQL_IMPLEMENTATION_UNAVAILABLE" in _codes(facts)


@pytest.mark.parametrize("text", [
    "CREATE EXTENSION IF NOT EXISTS btree_gist;\nCREATE TABLE t (id integer);\n",
    "SELECT pg_catalog.set_config('search_path', '', false);\nCREATE TABLE t (id integer);\n",
    "CREATE TABLE t (id integer, doc jsonb);\n",
    "\\set ON_ERROR_STOP on\nCREATE TABLE t (id integer);\n",
])
def test_postgresql_only_markers_establish_the_dialect(tmp_path, text):
    facts, _ = _extract(tmp_path, {"setup.sql": text})
    assert "SQL_DIALECT_UNDETERMINED" not in _codes(facts)


# ── Oracle writes: MERGE branches, record inserts, WHERE CURRENT OF ──────

ORACLE_WRITES = """CREATE TABLE counters (card_id NUMBER, txn_count NUMBER, total NUMBER,
  CONSTRAINT pk_counters PRIMARY KEY (card_id));
CREATE TABLE lines (line_id NUMBER, amount NUMBER, line_type VARCHAR2(10));
CREATE TABLE holds (hold_id NUMBER, amount NUMBER, reason VARCHAR2(30));
CREATE OR REPLACE PACKAGE BODY pkg_writes IS
  PROCEDURE roll_up(p_card_id IN NUMBER) IS
  BEGIN
    MERGE INTO counters c
    USING (SELECT p_card_id AS card_id, 1 AS txn_count, 0 AS total FROM dual) s
       ON (c.card_id = s.card_id)
     WHEN MATCHED THEN
       UPDATE SET c.txn_count = c.txn_count + s.txn_count,
                  c.total     = s.total
     WHEN NOT MATCHED THEN
       INSERT (card_id, txn_count, total) VALUES (s.card_id, s.txn_count, s.total);
  END roll_up;

  PROCEDURE add_line(p_amount IN NUMBER) IS
    v_line lines%ROWTYPE;
    TYPE t_lines IS TABLE OF lines%ROWTYPE INDEX BY PLS_INTEGER;
    v_batch t_lines;
    v_other VARCHAR2(10);
  BEGIN
    v_line.amount := p_amount;
    INSERT INTO lines VALUES v_line;
    FORALL i IN 1 .. v_batch.COUNT
      INSERT INTO lines VALUES v_batch(i);
    INSERT INTO lines VALUES v_other;
  END add_line;

  PROCEDURE release_holds IS
    CURSOR c_stale IS SELECT hold_id FROM holds FOR UPDATE;
  BEGIN
    FOR r IN c_stale LOOP
      UPDATE holds SET amount = 0, reason = 'EXPIRED' WHERE CURRENT OF c_stale;
    END LOOP;
  END release_holds;
END pkg_writes;
/
"""


@pytest.fixture(scope="module")
def oracle_writes(tmp_path_factory):
    return _extract(tmp_path_factory.mktemp("oracle_writes"), {"writes.sql": ORACLE_WRITES})


def _writes(facts, routine):
    bindings = facts["bindings"]
    result = []
    for edge in facts["edges"].values():
        if edge["kind"] != "writes_data":
            continue
        owner = facts["symbols"][edge["from_ref"]["id"]]["qualified_name"]
        if f".{routine}" not in owner:
            continue
        written = sorted((bindings[item]["name"].split("@")[0].rsplit(".", 1)[-1],
                          bindings[item]["expression"])
                         for item in edge["binding_ids"]
                         if bindings[item]["direction"] == "input" and "@" in bindings[item]["name"])
        result.append((facts["resources"][edge["to_ref"]["id"]]["name"], edge["reason"] or "", written))
    return result


def test_merge_writes_the_columns_of_both_branches(oracle_writes):
    facts, _ = oracle_writes
    [(table, reason, written)] = _writes(facts, "roll_up")
    assert table == "counters" and "Changed fields" not in reason
    assert written == [
        ("card_id", "s.card_id"),
        ("total", "s.total"), ("total", "s.total"),
        ("txn_count", "c.txn_count + s.txn_count"), ("txn_count", "s.txn_count")]


def test_a_rowtype_record_insert_writes_every_declared_column(oracle_writes):
    facts, _ = oracle_writes
    writes = _writes(facts, "add_line")
    columns = [("amount", "{0}.amount"), ("line_id", "{0}.line_id"), ("line_type", "{0}.line_type")]
    expected = {"v_line": [(name, value.format("v_line")) for name, value in columns],
                "v_batch(i)": [(name, value.format("v_batch(i)")) for name, value in columns]}
    found = {written[0][1].rsplit(".", 1)[0]: written for _, _, written in writes if written}
    assert found == expected
    # A record of another type writes columns the extractor cannot name.
    assert any(not written and "Changed fields" in reason for _, reason, written in writes)


def test_where_current_of_parses_and_keeps_its_predicate(oracle_writes):
    facts, units = oracle_writes
    assert "SQL_MATERIAL_PARSE_ERROR" not in _codes(facts)
    unit = next(unit for unit in units if unit.name == "release_holds")
    [update] = [statement for statement in unit.sql_dml if statement["kind"].name == "UPDATE"]
    assert update["ast"] is not None
    assert update["predicate"] == "WHERE CURRENT OF c_stale"
    [(table, _, written)] = _writes(facts, "release_holds")
    assert table == "holds" and written == [("amount", "0"), ("reason", "'EXPIRED'")]


def test_declared_columns_skip_table_constraints():
    from lib.context.business_domain_adapters.sql import _declared_columns
    assert _declared_columns(
        'CREATE TABLE t (id NUMBER(12) NOT NULL, "Name" VARCHAR2(30) DEFAULT \'x,y\',\n'
        '  amount NUMBER(18,2), CONSTRAINT pk_t PRIMARY KEY (id), UNIQUE (amount));') == [
        "id", "Name", "amount"]


# ── Dynamic SQL: evaluated statement text, runtime pieces stay gaps ──────

def _dynamic_body(body):
    return ("CREATE TABLE apps (id NUMBER, name VARCHAR2(30), status VARCHAR2(10));\n"
            "CREATE OR REPLACE PACKAGE BODY pkg_dyn IS\n"
            "  PROCEDURE run(p_table IN VARCHAR2, p_before IN DATE) IS\n"
            "    v_sql VARCHAR2(2000);\n"
            "  BEGIN\n" + body + "\n  END run;\nEND pkg_dyn;\n/\n")


def _dynamic_facts(tmp_path, body):
    facts, units = _extract(tmp_path, {"dyn.sql": _dynamic_body(body)})
    unit = next(unit for unit in units if unit.name == "run")
    return facts, unit


def test_a_static_target_with_a_runtime_source_becomes_known_operations(tmp_path):
    facts, unit = _dynamic_facts(tmp_path,
        "    v_sql := 'INSERT INTO apps (id, name) SELECT s.id, s.name FROM ' || p_table || ' s';\n"
        "    EXECUTE IMMEDIATE v_sql;")
    [statement] = [item for item in unit.sql_dml if "dynamic" in item]
    assert (statement["kind"].name, statement["write_target"]) == ("INSERT", "apps")
    assert statement["tables"] == ["apps", "(runtime: p_table)"]
    assert statement["columns"] == ["id", "name"]
    assert not getattr(unit, "sql_calls", [])
    codes = _codes(facts)
    assert "SQL_DYNAMIC_TABLE" in codes and "SQL_DYNAMIC_CALL" not in codes
    runtime = next(resource for resource in facts["resources"].values()
                   if resource["name"] == "(runtime: p_table)")
    assert "chosen at runtime from p_table" in runtime["reason"]


@pytest.mark.parametrize("body, kind, tables", [
    ("    EXECUTE IMMEDIATE 'DELETE FROM apps WHERE status = ''OLD''';", "DELETE", ["apps"]),
    ("    v_sql := 'DELETE FROM ' || p_table || ' WHERE created < :1';\n"
     "    EXECUTE IMMEDIATE v_sql USING p_before;", "DELETE", ["(runtime: p_table)"]),
])
def test_literal_and_numbered_bind_statements_are_evaluated(tmp_path, body, kind, tables):
    _, unit = _dynamic_facts(tmp_path, body)
    [statement] = [item for item in unit.sql_dml if "dynamic" in item]
    assert (statement["kind"].name, statement["tables"]) == (kind, tables)


@pytest.mark.parametrize("body", [
    # A branch between the assignment and the EXECUTE: which text runs is unknown.
    "    v_sql := 'DELETE FROM apps';\n    IF p_before IS NULL THEN\n"
    "      v_sql := 'DELETE FROM ' || p_table;\n    END IF;\n    EXECUTE IMMEDIATE v_sql;",
    # Text that does not parse as SQL stays dynamic.
    "    v_sql := p_table;\n    EXECUTE IMMEDIATE v_sql;",
])
def test_unknowable_dynamic_text_stays_a_dynamic_call(tmp_path, body):
    facts, unit = _dynamic_facts(tmp_path, body)
    assert not [item for item in unit.sql_dml if "dynamic" in item]
    assert [call["classification"] for call in unit.sql_calls] == ["dynamic"]


def test_a_case_expression_in_a_merge_set_value_is_not_a_branch(tmp_path):
    _, units = _extract(tmp_path, {"m.sql": (
        "CREATE TABLE t (id NUMBER, a NUMBER, b NUMBER);\n"
        "CREATE OR REPLACE PROCEDURE upd(p_id IN NUMBER) IS\nBEGIN\n"
        "  MERGE INTO t USING (SELECT p_id AS id, 1 AS x, 2 AS b FROM dual) s ON (t.id = s.id)\n"
        "  WHEN MATCHED THEN UPDATE SET t.a = CASE WHEN s.x > 0 THEN s.x ELSE 0 END, t.b = s.b\n"
        "  WHEN NOT MATCHED THEN INSERT (id, a, b) VALUES (s.id, s.x, s.b);\n"
        "END upd;\n/\n")})
    [statement] = next(unit for unit in units if unit.name == "upd").sql_dml
    assert list(zip(statement["columns"], [value["expression"] for value in statement["column_values"]])) == [
        ("a", "CASE WHEN s.x > 0 THEN s.x ELSE 0 END"), ("b", "s.b"),
        ("id", "s.id"), ("a", "s.x"), ("b", "s.b")]


@pytest.mark.parametrize("path, test_evidence", [
    ("supabase/seed.sql", True),
    ("db/seeds/users.sql", True),
    ("seed_data.sql", True),
    ("db/migration/V7__create_seed_audit_trigger.sql", False),
    ("supabase/migrations/20240301120000_seed_roles_and_policies.sql", False),
])
def test_only_seed_files_are_test_evidence_not_migrations_mentioning_seed(path, test_evidence):
    import json
    import re
    from pathlib import Path
    catalog = json.loads((Path(__file__).parents[1]
                          / "lib/context/business_domain_adapters/catalog.json").read_text())
    assert bool(re.search(catalog["test_path_pattern"], path)) is test_evidence


def test_a_migration_mentioning_seed_keeps_its_trigger_entry_point(tmp_path):
    facts, _ = _extract(tmp_path, {
        "supabase/migrations/20240301120000_seed_roles_and_policies.sql":
            AUDIT_FUNCTION + "CREATE TRIGGER order_audit AFTER INSERT ON orders "
                             "FOR EACH ROW EXECUTE FUNCTION audit_order();\n"})
    assert list(_trigger_anchors(facts)) == ["order_audit"]
