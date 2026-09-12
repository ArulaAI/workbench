"""Trusted HSQLDB adapter boundary using SQLGlot's compatible SQL parser."""

from .sql import *  # noqa: F401,F403
from . import sql as _sql

PARSER_ID = "sqlglot"
PARSER_VERSION = "30.18.0"
PARSER_DIALECT = "sqlite"


def extract(source):
    source.sql_dialect = "hsqldb"
    source.sql_parser_dialect = PARSER_DIALECT
    return _sql.extract(source)
