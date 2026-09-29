"""Trusted PostgreSQL/PLpgSQL adapter boundary."""

# Dialect-specific behavior remains adapter-owned while normalized projection
# is shared with the SQL implementation.
from .sql import *  # noqa: F401,F403
from . import sql as _sql

PARSER_ID = "sqlglot"
PARSER_VERSION = "30.18.0"
PARSER_DIALECT = "postgres"


def extract(source):
    source.sql_dialect = PARSER_DIALECT
    return _sql.extract(source)
