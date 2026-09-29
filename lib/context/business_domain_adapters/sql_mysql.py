"""Trusted MySQL adapter boundary using the shared normalized SQL owner."""

from .sql import *  # noqa: F401,F403
from . import sql as _sql

PARSER_ID = "sqlglot"
PARSER_VERSION = "30.18.0"
PARSER_DIALECT = "mysql"


def extract(source):
    source.sql_dialect = PARSER_DIALECT
    source.sql_parser_dialect = PARSER_DIALECT
    return _sql.extract(source)
