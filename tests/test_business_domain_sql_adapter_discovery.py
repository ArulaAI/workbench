"""F-02 SQL dialect capability discovery conformance."""
from pathlib import Path

from lib.context.business_domain_adapters import adapter_for, descriptor
from lib.context.business_domain_adapters.base import Source
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import DEFAULTS, digest, identifier, validate_references
from lib.context.language_registry import SOURCE_ADAPTER_CAPABILITIES


FIXTURES = Path(__file__).parents[1] / "specs/tech/fixtures/business-domains"


def _source(text: str) -> Source:
    return Source("invoice.sql", "sql", text, digest(text.encode()), identifier("resource", "invoice.sql"))


def test_oracle_and_postgresql_fixtures_select_evidenced_trusted_descriptors():
    oracle_text = (FIXTURES / "invoice_oracle.sql").read_text()
    postgres_text = (FIXTURES / "invoice_postgresql.sql").read_text()

    oracle = descriptor("invoice.sql", oracle_text)
    postgres = descriptor("invoice.sql", postgres_text)

    assert oracle["candidates"] == ["oracle_plsql"]
    assert oracle["capability"]["dialects"] == ["oracle_plsql"]
    assert oracle["capability"]["conformance"] == "semantic"
    assert oracle["capability"]["parser"] == "sqlglot"
    assert oracle["capability"]["parser_version"] == "30.18.0"
    assert oracle["capability"]["parser_dialect"] == "oracle"
    assert oracle["adapter"] == "sql"
    assert adapter_for(_source(oracle_text)).__name__.endswith(".sql")

    assert postgres["candidates"] == ["postgresql"]
    assert postgres["capability"]["dialects"] == ["postgresql_plpgsql"]
    assert postgres["capability"]["conformance"] == "semantic"
    assert postgres["capability"]["parser"] == "sqlglot"
    assert postgres["capability"]["parser_version"] == "30.18.0"
    assert postgres["capability"]["parser_dialect"] == "postgres"
    assert postgres["adapter"] == "sql_postgresql"
    assert adapter_for(_source(postgres_text)).__name__.endswith(".sql_postgresql")


def test_unknown_sql_uses_explicit_fallback_capability_contract(tmp_path):
    text = "CREATE TABLE invoice (id INTEGER PRIMARY KEY);\nSELECT * FROM invoice;\n"
    selected = descriptor("invoice.sql", text)

    assert selected["candidates"] == ["unknown_sql"]
    assert selected["capability"]["conformance"] == "unavailable"
    assert set(selected["capability"]["capabilities"]) == SOURCE_ADAPTER_CAPABILITIES
    assert set(selected["capability"]["capabilities"].values()) == {"unsupported"}
    assert selected["capability"]["diagnostic_codes"] == ["SQL_DIALECT_UNDETERMINED"]
    assert selected["adapter"] == "sql_unknown"

    (tmp_path / "invoice.sql").write_text(text)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)

    capabilities = [item for item in facts["capabilities"] if item["adapter"] == "unknown_sql"]
    assert {item["feature"] for item in capabilities} == SOURCE_ADAPTER_CAPABILITIES
    assert all(item["status"] == "unsupported" for item in capabilities)
    assert all(item["diagnostic_codes"] == ["SQL_DIALECT_UNDETERMINED"] for item in capabilities)
    assert not facts["anchors"]
    assert not any(item["adapter"] == "oracle_plsql" for item in facts["capabilities"])
    assert any(item["code"] == "SQL_DIALECT_UNDETERMINED" for item in facts["warnings"])


def test_dialect_neutral_trigger_syntax_does_not_silently_select_oracle():
    text = """CREATE TRIGGER audit_insert AFTER INSERT ON invoice
BEGIN
  INSERT INTO audit_log VALUES (NEW.id);
END;
"""

    selected = descriptor("audit.sql", text)

    assert selected["candidates"] == ["unknown_sql"]
    assert selected["capability"]["diagnostic_codes"] == ["SQL_DIALECT_UNDETERMINED"]


def test_repository_dialect_directories_select_plain_ddl_and_dml():
    cases = {
        "src/main/resources/db/postgresql/initDB.sql": ("CREATE TABLE pets (id SERIAL);", "postgresql"),
        "src/main/resources/db/mysql/populateDB.sql": ("INSERT INTO pets VALUES (1);", "mysql"),
        "src/main/resources/db/hsqldb/initDB.sql": ("CREATE TABLE pets (id INTEGER);", "hsqldb"),
    }
    for path, (text, expected) in cases.items():
        selected = descriptor(path, text)
        assert selected["candidates"] == [expected]
        assert selected["adapter"] == "sql_" + expected


def test_plain_dialect_files_extract_constraints_and_top_level_dml(tmp_path):
    files = {
        "src/main/resources/db/postgresql/initDB.sql":
            "CREATE TABLE IF NOT EXISTS pets (id INTEGER PRIMARY KEY);",
        "src/main/resources/db/postgresql/populateDB.sql":
            "INSERT INTO pets (id) VALUES (1);",
        "src/main/resources/db/mysql/initDB.sql":
            "CREATE TABLE pets (id INTEGER UNIQUE);",
        "src/main/resources/db/mysql/populateDB.sql":
            "UPDATE pets SET id = 2 WHERE id = 1;",
        "src/main/resources/db/hsqldb/initDB.sql":
            "CREATE TABLE pets (id INTEGER NOT NULL);",
        "src/main/resources/db/hsqldb/populateDB.sql":
            "DELETE FROM pets WHERE id = 2;",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    facts, units = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)

    assert not any(item["code"] == "SQL_DIALECT_UNDETERMINED"
                   for item in facts["warnings"])
    assert {unit.source.adapter_id for unit in units} == {
        "postgresql/sqlglot", "mysql/sqlglot", "hsqldb/sqlglot"}
    assert {unit.source.path for unit in units} == set(files)
    assert all(any(evidence["locator"]["path"] == path
                   for evidence in facts["evidence"].values())
               for path in files)
    assert len(facts["rule_observations"]) >= 3


def test_mixed_sql_repository_preserves_adapter_identity_and_fact_contract(tmp_path):
    (tmp_path / "oracle.sql").write_text(
        (FIXTURES / "invoice_oracle.sql").read_text())
    (tmp_path / "postgres.sql").write_text(
        (FIXTURES / "invoice_postgresql.sql").read_text())
    (tmp_path / "generic.sql").write_text(
        "CREATE TABLE item (id INTEGER);\nSELECT * FROM item;\n")

    facts, units = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)

    assert {item["adapter"] for item in facts["capabilities"]} == {
        "oracle_plsql", "postgresql", "unknown_sql"}
    assert {unit.source.adapter_id for unit in units} == {
        "oracle_plsql/sqlglot", "postgresql/sqlglot"}
    assert {item["extractor"] for item in facts["evidence"].values()} >= {
        "oracle_plsql/sqlglot", "postgresql/sqlglot", "unknown_sql"}
    assert not any(item["code"] == "SQL_MATERIAL_PARSE_ERROR"
        for item in facts["warnings"])
    assert any(item["code"] == "SQL_DIALECT_UNDETERMINED"
        for item in facts["warnings"])


def test_postgresql_schema_qualified_call_uses_shared_semantic_contract(tmp_path):
    (tmp_path / "procedures.sql").write_text("""
CREATE PROCEDURE public.pg_helper(IN p_id bigint) LANGUAGE plpgsql AS $$
BEGIN NULL; END;
$$;
CREATE PROCEDURE public.pg_run(IN p_id bigint) LANGUAGE plpgsql AS $$
BEGIN CALL public.pg_helper(p_id); END;
$$;
""")

    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    call = next(item for item in facts["edges"].values()
        if item["kind"] == "calls")

    assert call["resolution"] == "resolved"
    assert facts["symbols"][call["to_ref"]["id"]]["qualified_name"].endswith(
        "::public.pg_helper")
    evidence = facts["evidence"][call["evidence_ids"][0]]
    assert evidence["excerpt"] == "public.pg_helper(p_id)"
    assert evidence["extractor"] == "postgresql/sqlglot"
