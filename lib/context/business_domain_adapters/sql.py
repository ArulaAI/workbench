"""Oracle PL/SQL syntax and semantic adapter. Never executes SQL.

Call classification is driven by the pinned sqlglot Oracle tokenizer/AST plus
repository declarations. There is deliberately no ``WORD(`` regex fallback.
"""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from ..language_registry import registry

sqlglot = registry.load_trusted_parser("sqlglot")
from sqlglot import Dialect, exp, parse_one
from sqlglot.errors import ErrorLevel, ParseError, TokenError
from sqlglot.tokens import TokenType

from ..business_domain_schema import identifier
from .base import (MAX_SEMANTIC_CANDIDATES, SemanticResult, Source, Unit,
                   declare_anchor_registration, declare_anchor_representation,
                   declare_operation_observation, declare_trace_contract)

SQLGLOT_VERSION = "30.18.0"
PARSER_ID = "sqlglot"
_IDENTIFIERS = frozenset({TokenType.VAR, TokenType.IDENTIFIER})
_EXTERNAL_PACKAGES = frozenset({
    "dbms_alert", "dbms_application_info", "dbms_crypto", "dbms_job",
    "dbms_lob", "dbms_lock", "dbms_output", "dbms_pipe", "dbms_scheduler",
    "dbms_session", "dbms_sql", "dbms_utility", "utl_file", "utl_http",
    "utl_mail", "utl_raw", "utl_smtp", "utl_tcp",
})
_ORACLE_RUNTIME_ROUTINES = frozenset({"raise_application_error"})


def _ensure_parser() -> None:
    if sqlglot.__version__ != SQLGLOT_VERSION:
        raise RuntimeError(
            f"Trusted SQL parser version mismatch: expected {SQLGLOT_VERSION}, "
            f"found {sqlglot.__version__}")


def _dialect(source: Source) -> str:
    return getattr(source, "sql_dialect", "oracle")


def _parser_dialect(source: Source) -> str:
    return getattr(source, "sql_parser_dialect", _dialect(source))


def _mask_oracle_q_literals(text: str) -> str:
    """Replace only Oracle Q literals, preserving all offsets."""
    result = list(text)
    pattern = re.compile(r"(?i)q'(.)")
    position = 0
    while match := pattern.search(text, position):
        delimiter = match.group(1)
        closing = {"[": "]", "{": "}", "(": ")", "<": ">"}.get(delimiter, delimiter)
        finish = text.find(closing + "'", match.end())
        end = len(text) if finish < 0 else finish + 2
        replacement = "''" + " " * max(0, end - match.start() - 2)
        result[match.start():end] = replacement
        position = end
    return "".join(result)


def mask_sql(text: str) -> str:
    pattern = re.compile(r"--[^\n]*|/\*[\s\S]*?\*/|(?:[nN])?[qQ]'(.)|'(?:''|[^'])*'")
    result = list(text); position = 0
    while match := pattern.search(text, position):
        start, end = match.span()
        if match.group(1):
            delimiter = match.group(1)
            closing = {"[": "]", "{": "}", "(": ")", "<": ">"}.get(delimiter, delimiter)
            finish = text.find(closing + "'", end)
            end = len(text) if finish < 0 else finish + 2
        result[start:end] = ["\n" if char == "\n" else " " for char in text[start:end]]
        position = end
    return "".join(result)


def symbol_key(name):
    return name.casefold()


def _package_at(packages, code, position):
    prior = [package for package in packages if package.start() < position]
    if not prior or re.search(r"(?m)^\s*/\s*$", code[prior[-1].end():position]):
        return None
    return prior[-1]


def _signature(params):
    return tuple(re.sub(r"\s+", " ", type_name).strip().casefold() for _, type_name in params)


def _parameter_segments(text: str) -> list[str]:
    """Split a routine parameter list without splitting type arguments."""
    result, start, depth = [], 0, 0
    for index, character in enumerate(text):
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        elif character == "," and depth == 0:
            result.append(text[start:index])
            start = index + 1
    result.append(text[start:])
    return [segment.strip() for segment in result if segment.strip()]


def _parameter_list(header: str) -> str:
    """Return the text inside a routine's own parameter parentheses.

    Matching the first ``(`` keeps a following ``RETURNS numeric(10,2)`` out
    of the parameter list, and so out of the routine identity.
    """
    start = header.find("(")
    if start < 0:
        return ""
    depth = 0
    for index in range(start, len(header)):
        if header[index] == "(":
            depth += 1
        elif header[index] == ")":
            depth -= 1
            if depth == 0:
                return header[start + 1:index]
    return header[start + 1:]


# PostgreSQL argument names are optional. These type names contain spaces,
# so their first word must not be mistaken for an argument name.
_POSTGRES_MULTIWORD_TYPE = re.compile(
    r"(?is)^(?:double\s+precision|character\s+varying|bit\s+varying"
    r"|(?:timestamp|time)(?:\s*\(\s*\d+\s*\))?\s+with(?:out)?\s+time\s+zone)\b")


def _postgres_parameter(segment: str) -> tuple[str | None, str | None, str] | None:
    """Split one PostgreSQL argument into ``(mode, name, type)``."""
    match = re.match(r"(?is)^(?:(INOUT|IN\s+OUT|IN|OUT|VARIADIC)\s+)?(.+)$", segment)
    if not match:
        return None
    mode, rest = match.groups()
    rest = rest.strip()
    named = re.match(r"(?is)^([\w$#]+)\s+(.+)$", rest)
    if (named and not _POSTGRES_MULTIWORD_TYPE.match(rest)
            and not re.match(r"(?i)(?:DEFAULT\b|=)", named.group(2))):
        return mode, named.group(1), named.group(2)
    return mode, None, rest


def _parameters(text: str, dialect: str) -> list[tuple[str, str]]:
    """Normalize Oracle and PostgreSQL argument ordering to ``(name, type)``."""
    return _parameters_and_defaults(text, dialect)[0]


def _parameters_and_defaults(text: str, dialect: str) -> tuple[list, tuple]:
    """``(_parameters(...), defaults)``: whether each parameter declares a default.

    A parameter written with ``DEFAULT``, ``:=`` or ``=`` may be omitted by a
    caller; one without may not.
    """
    result, defaults = [], []
    for position, segment in enumerate(_parameter_segments(text)):
        if dialect == "postgres":
            parsed = _postgres_parameter(segment)
            if not parsed:
                continue
            mode, name, type_name = parsed
            name = name or f"${position + 1}"
            mode = "IN OUT" if mode and mode.casefold() == "inout" else mode
        else:
            match = re.match(
                r"(?is)^([\w$#]+)\s+(?:(IN\s+OUT|IN|OUT)\s+)?(.+)$",
                segment,
            )
            if not match:
                continue
            name, mode, type_name = match.groups()
        pieces = re.split(
            r"(?i)\s+(?:DEFAULT|:=)\s*|\s+=\s*", type_name, maxsplit=1,
        )
        type_name = pieces[0].strip()
        normalized_mode = re.sub(r"\s+", " ", mode or "").upper()
        normalized = f"{normalized_mode} {type_name}".strip()
        result.append((name, normalized))
        defaults.append(len(pieces) > 1)
    return result, tuple(defaults)


def _normalized_clause(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


_SQL_NAME = r'(?:"[^"]+"|[\w$#]+)(?:\s*\.\s*(?:"[^"]+"|[\w$#]+))*'


def _sql_name(value: str) -> str:
    """Normalize a possibly quoted, possibly qualified SQL name."""
    return ".".join(part.strip().strip('"')
                    for part in re.findall(r'"[^"]+"|[^.\s]+', value))


def _trigger_registration(header: str) -> tuple[dict, str | None]:
    match = re.match(
        r"(?is)^\s*(BEFORE|AFTER|INSTEAD\s+OF)\s+(.+?)\s+ON\s+(" + _SQL_NAME + r")(?![\w$#])(.*)$",
        header,
    )
    if not match:
        return ({'event': None, 'timing': None, 'target': None,
                 'scope': None, 'condition': None},
                'Trigger firing timing, event, or target could not be resolved.')
    timing = _normalized_clause(match.group(1)).upper()
    event = _normalized_clause(match.group(2)).upper()
    target = _normalized_clause(match.group(3))
    tail = match.group(4)
    if re.search(r"(?i)\bFOR\s+EACH\s+ROW\b", tail):
        scope = 'row'
    elif target.casefold() in {'schema', 'database'}:
        scope = target.casefold()
    else:
        scope = 'statement'
    condition_match = re.search(r"(?is)\bWHEN\s*\((.*)\)\s*$", tail)
    condition = (_normalized_clause(condition_match.group(1))
                 if condition_match else None)
    return ({'event': event, 'timing': timing, 'target': target,
             'scope': scope, 'condition': condition}, None)


def _routine_identity(unit: Unit) -> str | None:
    scope = unit.source.service_scope.strip() if unit.source.service_scope else "repository"
    if unit.sql_routine_kind == 'trigger':
        registration = getattr(unit, 'sql_trigger_registration', None)
        if not registration or any(registration.get(field) is None
                for field in ('event', 'timing', 'target', 'scope')):
            return None
        firing_identity = identifier('registration', *(
            _normalized_clause(registration.get(field) or '').casefold()
            for field in ('timing', 'event', 'target', 'scope', 'condition'))).split(':', 1)[1]
        return (f"sql:{scope or 'repository'}:{_dialect(unit.source)}:"
                f"trigger:{unit.name}:{firing_identity}").casefold()
    owner = (unit.owner + ".") if unit.owner else ""
    signature = ",".join(_signature(unit.params))
    return (f"sql:{scope or 'repository'}:{_dialect(unit.source)}:"
            f"{unit.sql_routine_kind}:{owner}{unit.name}({signature})").casefold()


# PostgreSQL routine and trigger declarations are always CREATE statements.
# GRANT/COMMENT/ALTER/DROP ... FUNCTION and EXECUTE FUNCTION inside CREATE
# TRIGGER name a routine without declaring one.
_POSTGRES_CREATE = re.compile(
    r"(?i)\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:CONSTRAINT\s+)?$")
_DOLLAR_QUOTE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def _statement_semicolon(code: str, position: int) -> int:
    """First statement-terminating semicolon outside parentheses, or -1."""
    depth = 0
    for index in range(position, len(code)):
        character = code[index]
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        elif character == ";" and depth == 0:
            return index
    return -1


def _dollar_body(code: str, position: int) -> tuple[int, int, int, int] | None:
    """Locate a PostgreSQL dollar-quoted routine body after a header.

    Returns ``(open_start, body_start, body_end, close_end)``. A header ended by
    ``;`` first has no dollar-quoted body (for example a string-literal body).
    """
    opener = _DOLLAR_QUOTE.search(code, position)
    semicolon = code.find(";", position)
    if not opener or 0 <= semicolon < opener.start():
        return None
    close = code.find(opener.group(), opener.end())
    if close < 0:
        return opener.start(), opener.end(), len(code), len(code)
    return opener.start(), opener.end(), close, close + len(opener.group())


def _postgres_language(code: str, header_start: int, span) -> str | None:
    open_start, _, _, close_end = span
    finish = code.find(";", close_end)
    tail = code[close_end:len(code) if finish < 0 else finish]
    language = (re.search(r"(?i)\bLANGUAGE\s+'?([\w]+)", code[header_start:open_start])
                or re.search(r"(?i)\bLANGUAGE\s+'?([\w]+)", tail))
    return language.group(1).casefold() if language else None


def _postgres_trigger(source: Source, code: str, match) -> list[Unit]:
    """Model ``CREATE TRIGGER ... EXECUTE FUNCTION f()`` as a registration.

    The registration selects the named function in ``prepare`` once every
    PostgreSQL source has been extracted; the function may be declared later
    or in another file.
    """
    semicolon = _statement_semicolon(code, match.end())
    finish = len(code) if semicolon < 0 else semicolon + 1
    statement = code[match.end():finish]
    execute = re.search(
        r"(?is)\bEXECUTE\s+(?:FUNCTION|PROCEDURE)\s+(" + _SQL_NAME + r")\s*\(",
        statement)
    header = statement[:execute.start()] if execute else statement.rstrip(";")
    fields, reason = _trigger_registration(header)
    function = _sql_name(execute.group(1)) if execute else None
    if reason is None and function is None:
        reason = "Trigger function could not be resolved from the EXECUTE clause."
    name = match.group(2)
    resolution = "unresolved" if reason else "resolved"
    registration = Unit(source, name.split(".")[-1],
        source.path + "::trigger-registration:" + name,
        match.start(), finish, "declarative_operation", [], None,
        anchor_kind="sql", anchor_resolution=resolution,
        executable_body=False, anchor_reason=reason)
    registration.sql_declaration_kind = "trigger_registration"
    registration.sql_routine_kind = "trigger"
    registration.sql_trigger_registration = fields
    registration.sql_trigger_function = function
    declare_trace_contract(registration, "contract")
    declare_anchor_registration(registration, "database_trigger",
        **fields, label=None, resolution=resolution, reason=reason,
        evidence_spans=[(source, match.start(), finish)])
    declare_anchor_representation(registration, "registration",
        _routine_identity(registration),
        "unresolved" if reason else "eligible", "public")
    return [registration]


def _parenthesized(code: str, open_index: int) -> int:
    """Index just after the parenthesis closing the one at ``open_index``."""
    depth = 0
    for index in range(open_index, len(code)):
        if code[index] == "(":
            depth += 1
        elif code[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(code)


_POLICY = re.compile(
    r"(?is)\bCREATE\s+POLICY\s+(" + _SQL_NAME + r")\s+ON\s+(" + _SQL_NAME + r")")
_ROW_SECURITY = re.compile(
    r"(?is)\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(" + _SQL_NAME + r")"
    r"\s+(ENABLE|FORCE)\s+ROW\s+LEVEL\s+SECURITY\b")


def _postgres_policies(source: Source, code: str) -> list[Unit]:
    """Row-level security declarations as non-callable rule-bearing units."""
    units = []
    for match in _POLICY.finditer(code):
        semicolon = _statement_semicolon(code, match.end())
        finish = len(code) if semicolon < 0 else semicolon + 1
        tail = code[match.end():finish]
        clauses = {}
        for key, pattern in (("using", r"\bUSING\s*\("),
                             ("with_check", r"\bWITH\s+CHECK\s*\(")):
            found = re.search(r"(?is)" + pattern, tail)
            if found:
                start = match.end() + found.start()
                clauses[key] = (start, _parenthesized(code, match.end() + found.end() - 1))
        first_clause = min((start for start, _ in clauses.values()), default=finish)
        head = code[match.end():first_clause]
        mode = re.search(r"(?i)\bAS\s+(PERMISSIVE|RESTRICTIVE)\b", head)
        command = re.search(r"(?i)\bFOR\s+(ALL|SELECT|INSERT|UPDATE|DELETE)\b", head)
        roles = re.search(r"(?is)\bTO\s+(.+?)\s*$", head)
        table = _sql_name(match.group(2))
        name = _sql_name(match.group(1))
        unit = Unit(source, name, source.path + "::policy:" + table + ":" + name,
            match.start(), finish, "module")
        unit.sql_declaration_kind = "row_security_policy"
        unit.sql_policy = {
            "name": name, "table": table,
            "mode": mode.group(1).upper() if mode else "PERMISSIVE",
            "command": command.group(1).upper() if command else "ALL",
            "roles": (", ".join(_normalized_clause(role) for role in
                roles.group(1).split(",")) if roles else None),
            "clauses": {key: (start - match.start(), end - match.start())
                        for key, (start, end) in clauses.items()},
        }
        units.append(unit)
    for match in _ROW_SECURITY.finditer(code):
        semicolon = _statement_semicolon(code, match.end())
        finish = len(code) if semicolon < 0 else semicolon + 1
        table = _sql_name(match.group(1))
        unit = Unit(source, table, source.path + "::row-security:" + table
            + ":" + match.group(2).casefold(), match.start(), finish, "module")
        unit.sql_declaration_kind = "row_security_enablement"
        unit.sql_policy = {"table": table, "mode": match.group(2).upper()}
        units.append(unit)
    return units


def extract(source: Source) -> list[Unit]:
    _ensure_parser()
    code = mask_sql(source.text)
    postgres = _dialect(source) == "postgres"
    packages = list(re.finditer(
        r"(?i)\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:NON)?EDITIONABLE\s+)?"
        r"PACKAGE\s+(BODY\s+)?([\w$#]+(?:\.[\w$#]+)*)", code))
    units = []
    for match in re.finditer(r"(?i)\b(PROCEDURE|FUNCTION|TRIGGER)\s+([\w.$#]+)", code):
        # PostgreSQL's `RETURNS trigger` is a return type, not a declaration.
        if (match.group(1).casefold() == 'trigger' and
                re.search(r"(?i)\bRETURNS\s+$", code[max(0, match.start() - 64):match.start()])):
            continue
        dollar = None
        if postgres:
            if not _POSTGRES_CREATE.search(code[max(0, match.start() - 64):match.start()]):
                continue
            if match.group(1).casefold() == 'trigger':
                units.extend(_postgres_trigger(source, code, match))
                continue
            # A PostgreSQL routine body is the dollar-quoted string. Bounding
            # the body by its quotes keeps a LANGUAGE sql body (no BEGIN) from
            # absorbing the following statements up to some later BEGIN.
            dollar = _dollar_body(code, match.end())
            if dollar is None:
                continue
            language = _postgres_language(code, match.end(), dollar)
            if language not in {None, "plpgsql", "sql"}:
                continue
        tail = code[match.end():]
        intro = re.search(r"(?i)\b(IS|AS|BEGIN)\b|;", tail)
        if not intro:
            continue
        start_body = match.end() + intro.start()
        if dollar is not None:
            start_body = min(start_body, dollar[0])
        package = _package_at(packages, code, match.start())
        owner = package.group(2) if package else None
        package_body = bool(package and package.group(1))
        header = code[match.end():start_body]
        param_text = _parameter_list(header)
        params, defaults = _parameters_and_defaults(param_text, _dialect(source))
        if intro.group() == ";":
            if not owner or package_body:
                continue
            finish = match.end() + intro.end()
            qualified = source.path + "::package-spec:" + owner + "." + match.group(2)
            unit = Unit(source, match.group(2).split(".")[-1], qualified,
                match.start(), finish, "declarative_operation", params, owner,
                anchor_kind="sql", anchor_resolution="resolved", executable_body=False,
                anchor_reason=None)
            unit.sql_declaration_kind = "package_spec"
            unit.sql_param_defaults = defaults
            unit.sql_routine_kind = match.group(1).casefold()
            unit.sql_contract_key = (owner.casefold(), unit.sql_routine_kind,
                unit.name.casefold(), _signature(params))
            declare_trace_contract(unit, "contract")
            declare_anchor_representation(unit, "contract",
                _routine_identity(unit), "eligible", "public")
            units.append(unit)
            continue
        body_limit = dollar[2] if dollar is not None else len(code)
        begin = re.search(r"(?i)\bBEGIN\b", code[start_body:body_limit])
        if dollar is not None and (not begin or language == "sql"):
            # LANGUAGE sql: the dollar-quoted body is the SQL statement list.
            begin = None
            begin_at = dollar[1]
            tokens = []
            depth, finish = 0, dollar[2]
        elif not begin:
            continue
        else:
            begin_at = start_body + begin.start()
            tokens = list(re.finditer(r"(?i)\b(BEGIN|IF|LOOP|CASE|END)\b|;",
                                      code[begin_at:body_limit]))
            depth, finish = 0, body_limit
        skip_qualifier = False
        for token in tokens:
            word = token.group().upper()
            if skip_qualifier and word in ("IF", "LOOP", "CASE"):
                skip_qualifier = False
                continue
            if word == "IF" and not _STATEMENT_START.search(
                    code[begin_at:begin_at + token.start()]):
                # ``IF(...)`` inside an expression is a function call, not a block.
                skip_qualifier = False
                continue
            if word in ("BEGIN", "IF", "LOOP", "CASE"):
                depth += 1
            elif word == "END":
                depth -= 1
                skip_qualifier = True
                if depth == 0:
                    semicolon = code.find(";", begin_at + token.end())
                    finish = len(code) if semicolon < 0 else semicolon + 1
                    break
            else:
                skip_qualifier = False
        name = match.group(2)
        unit_owner = owner or (name.rsplit(".", 1)[0] if "." in name else None)
        if match.group(1).casefold() == 'trigger':
            registration_fields, registration_reason = _trigger_registration(
                code[match.end():begin_at])
            resolution = 'unresolved' if registration_reason else 'resolved'
            registration = Unit(source, name.split(".")[-1],
                source.path + "::trigger-registration:" + name,
                match.start(), begin_at, "declarative_operation", [], unit_owner,
                anchor_kind="sql", anchor_resolution=resolution,
                executable_body=False, anchor_reason=registration_reason)
            registration.sql_declaration_kind = 'trigger_registration'
            registration.sql_routine_kind = 'trigger'
            registration.sql_trigger_registration = registration_fields
            declare_trace_contract(registration, 'contract')
            declare_anchor_registration(registration, 'database_trigger',
                **registration_fields, label=None, resolution=resolution,
                reason=registration_reason,
                evidence_spans=[(source, match.start(), begin_at)])
            declare_anchor_representation(registration, 'registration',
                _routine_identity(registration),
                'unresolved' if registration_reason else 'eligible', 'public')

            body = Unit(source, name.split(".")[-1],
                source.path + "::trigger-body:" + name,
                match.start(), finish, "declarative_operation", [], unit_owner,
                anchor_kind="sql", anchor_resolution=resolution,
                executable_body=True, anchor_reason=registration_reason)
            body.sql_declaration_kind = 'trigger_body'
            body.sql_routine_kind = 'trigger'
            body.sql_trigger_registration = registration_fields
            body.sql_body_start = begin_at - body.start
            body.sql_material_start = begin_at - body.start
            body.sql_declaration_complete = depth == 0
            declare_trace_contract(body, 'implementation')
            declare_anchor_representation(body, 'implementation',
                _routine_identity(body), 'supporting', 'internal')
            body.valid_terminal = False
            body.required_capabilities = tuple(sorted(
                set(body.required_capabilities)
                | {'call_classification', 'callable_resolution'}))
            registration.anchor_correspondence_units = [body]
            registration.anchor_correspondence_state = 'resolved'
            registration.anchor_correspondence_reason = (
                'The trigger declaration directly selects its executable body.')
            registration.anchor_correspondence_relationship_kind = 'selects_implementation'
            registration.sql_trigger_body = body
            units.extend((registration, body))
            continue
        qualified = source.path + "::" + (f"{owner}.{name}" if owner and "." not in name else name)
        standalone = not package_body
        unit = Unit(source, name.split(".")[-1], qualified, match.start(), finish,
            "declarative_operation", params, unit_owner,
            anchor_kind="sql",
            anchor_resolution="resolved" if standalone else "unresolved",
            executable_body=True,
            anchor_reason=None if standalone else
                "Routine body is present; dialect and public package-contract visibility have not been established.")
        unit.sql_declaration_kind = "package_body" if package_body else "standalone_body"
        unit.sql_param_defaults = defaults
        unit.sql_routine_kind = match.group(1).casefold()
        unit.sql_contract_key = ((owner.casefold(), unit.sql_routine_kind,
            unit.name.casefold(), _signature(params)) if package_body else None)
        unit.sql_body_start = begin_at - unit.start
        unit.sql_material_start = ((match.end() + intro.end()) if begin
                                   else begin_at) - unit.start
        unit.sql_statement_body = begin is None
        unit.sql_declaration_complete = depth == 0
        declare_trace_contract(unit, "implementation")
        declare_anchor_representation(unit,
            "implementation" if package_body else "registration",
            _routine_identity(unit),
            "supporting" if package_body else "eligible",
            "internal" if package_body else "public")
        if standalone:
            declare_anchor_registration(unit, 'callable_exposure',
                event='invoke', target=(f'{unit_owner}.{unit.name}'
                    if unit_owner else unit.name), scope='schema',
                timing=None, condition=None, label=None,
                resolution='resolved', reason=None,
                evidence_spans=[(source, match.start(), begin_at)])
        unit.valid_terminal = False
        unit.required_capabilities = tuple(sorted(
            set(unit.required_capabilities)
            | {"call_classification", "callable_resolution"}))
        units.append(unit)
    if postgres:
        units.extend(_postgres_policies(source, code))
    groups = {}
    for unit in units:
        groups.setdefault(unit.qualified.casefold(), []).append(unit)
    for peers in groups.values():
        if len(peers) < 2:
            continue
        for unit in peers:
            signature = ",".join(re.sub(r"\s+", " ", value).casefold() for _, value in unit.params)
            same_signature = [other for other in peers if ",".join(
                re.sub(r"\s+", " ", value).casefold() for _, value in other.params) == signature]
            unit.qualified += "(" + signature + ")"
            if len(same_signature) > 1:
                unit.qualified += ":" + str(same_signature.index(unit))
    for match in re.finditer(
            r"(?i)\bCREATE\s+(?:(?:GLOBAL|LOCAL|PRIVATE)\s+)?(?:(?:TEMPORARY|TEMP|UNLOGGED)\s+)?"
            r"TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.$#]+)\s*\(",
            code):
        depth = 1; end = match.end()
        while end < len(code) and depth:
            depth += (code[end] == "(") - (code[end] == ")")
            end += 1
        if depth:
            continue
        name = match.group(1)
        table = Unit(source, name, source.path + "::table:" + name,
            match.start(), end, "type")
        table.sql_declaration_kind = "table"
        units.append(table)
    # Seed and migration files often contain only top-level DML. Keep one
    # non-callable file symbol so the shared SQL operation projection can emit
    # its reads_data/writes_data evidence.
    if not any(unit.kind == "declarative_operation" for unit in units) and re.search(
            r"(?i)\b(?:WITH|SELECT|INSERT|UPDATE|DELETE)\b", code):
        module = Unit(source, source.path.rsplit('/', 1)[-1],
            source.path + "::statements", 0, len(source.text), "module")
        module.sql_declaration_kind = "statements"
        module.sql_body_start = 0
        module.sql_material_start = 0
        module.sql_declaration_complete = True
        units.append(module)
    return units


# Procedural statement keywords the tokenizer reads as plain names. Followed
# by a parenthesis they open an expression (``RETURN (SELECT ...)``,
# ``IF (...) THEN``), never a call. A quoted or qualified name is a call.
_STATEMENT_KEYWORDS = frozenset({
    "return", "if", "elsif", "elseif", "while", "perform", "raise",
})
_PROCEDURAL_KEYWORDS = frozenset({
    "when", "case", "then", "else", "and", "or", "not", "in", "exists",
    "into", "using", "returning", "values",
})
# Keywords that open an expression only after ``RETURN`` (``RETURN QUERY (...)``).
_RETURN_KEYWORDS = frozenset({"query", "next"})


def _procedural_keyword(tokens, index: int) -> bool:
    token = tokens[index]
    if token.token_type != TokenType.VAR or (index and tokens[index - 1].token_type == TokenType.DOT):
        return False
    word = token.text.casefold()
    if word in _STATEMENT_KEYWORDS:
        # ``RETURN (...)`` and ``IF (...)`` open statements; mid-expression the
        # same word followed by a parenthesis is a call (``SUM(IF(...))``).
        return _statement_start(tokens, index)
    return word in _PROCEDURAL_KEYWORDS or (
        word in _RETURN_KEYWORDS and index > 0
        and tokens[index - 1].text.casefold() == "return")


def _is_identifier(token) -> bool:
    return token.token_type in _IDENTIFIERS


def _tokenize(text: str, source: Source):
    _ensure_parser()
    dialect = Dialect.get_or_raise(_parser_dialect(source))
    if _dialect(source) == "postgres":
        text = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$",
            lambda match: " " * len(match.group()), text)
        text = re.sub(r"(?i)\bCALL\b", lambda match: " " * len(match.group()), text)
    return dialect.tokenizer_class().tokenize(text)


def _paren_pairs(tokens) -> dict[int, int]:
    stack, pairs = [], {}
    for index, token in enumerate(tokens):
        if token.token_type == TokenType.L_PAREN:
            stack.append(index)
        elif token.token_type == TokenType.R_PAREN and stack:
            pairs[stack.pop()] = index
    return pairs


def _split_tokens(tokens, start: int, end: int) -> list[list]:
    result, current, depth = [], [], 0
    for token in tokens[start:end]:
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth -= 1
        if token.token_type == TokenType.COMMA and depth == 0:
            result.append(current); current = []
        else:
            current.append(token)
    result.append(current)
    return [part for part in result if part]


def _base_type(type_name: str) -> str:
    value = " ".join(type_name.casefold().split())
    for mode in ("in out ", "in ", "out "):
        if value.startswith(mode):
            value = value[len(mode):]
    if "%type" in value or "%rowtype" in value:
        return "unknown"
    value = value.split("(", 1)[0]
    if any(word in value for word in ("number", "integer", "decimal", "numeric", "float", "double")):
        return "number"
    if any(word in value for word in ("char", "text", "clob")):
        return "string"
    if "date" in value or "timestamp" in value:
        return "date"
    if "bool" in value:
        return "boolean"
    return value or "unknown"


def _argument_type(tokens, unit: Unit) -> str:
    values = [token for token in tokens if token.token_type != TokenType.FARROW]
    if not values:
        return "unknown"
    first = values[0]
    if first.token_type == TokenType.NUMBER:
        return "number"
    if first.token_type == TokenType.STRING:
        return "string"
    if first.text.casefold() == "null":
        return "unknown"
    variables = {name.casefold(): _base_type(type_name) for name, type_name in unit.params}
    if _is_identifier(first):
        return variables.get(first.text.casefold(), "unknown")
    return "unknown"


def _arguments(tokens, open_index: int, close_index: int, unit: Unit) -> list[dict]:
    result = []
    for part in _split_tokens(tokens, open_index + 1, close_index):
        named = None
        for index, token in enumerate(part):
            if token.token_type == TokenType.FARROW and index and _is_identifier(part[index - 1]):
                named = part[index - 1].text.casefold()
                part = part[index + 1:]
                break
        values = [token for token in part if token.token_type != TokenType.FARROW]
        result.append({"name": named, "type": _argument_type(part, unit),
                       "literal": len(values) == 1 and values[0].token_type == TokenType.STRING})
    return result


def _collection_types(tokens, end_index: int) -> set[str]:
    result = set()
    for index, token in enumerate(tokens[:end_index]):
        if token.text.casefold() != "type" or index + 3 >= end_index:
            continue
        if (not _is_identifier(tokens[index + 1])
                or tokens[index + 2].token_type != TokenType.IS):
            continue
        cursor = index + 3
        while cursor < end_index and tokens[cursor].token_type != TokenType.SEMICOLON:
            if (tokens[cursor].token_type == TokenType.TABLE
                    or tokens[cursor].text.casefold() == "varray"):
                result.add(tokens[index + 1].text.casefold())
                break
            cursor += 1
    return result


def _collection_names(tokens, body_index: int, inherited_types=()) -> set[str]:
    collection_types = set(inherited_types) | _collection_types(tokens, body_index)
    variables = set()
    for index in range(max(0, body_index - 1)):
        if (_is_identifier(tokens[index]) and _is_identifier(tokens[index + 1])
                and tokens[index + 1].text.casefold() in collection_types):
            variables.add(tokens[index].text.casefold())
    return variables


def _statement_end(tokens, start_index: int) -> int:
    """Last token of the statement starting at ``start_index``.

    A statement nested in an enclosing parenthesis, such as the scalar
    subquery in ``IF (SELECT ...) THEN`` or ``x := (SELECT ...);``, ends
    before the parenthesis that closes it.
    """
    depth = 0
    for index in range(start_index, len(tokens)):
        token_type = tokens[index].token_type
        if token_type == TokenType.SEMICOLON:
            return index
        if token_type == TokenType.L_PAREN:
            depth += 1
        elif token_type == TokenType.R_PAREN:
            if depth == 0:
                return max(start_index, index - 1)
            depth -= 1
    return len(tokens) - 1


_CLAUSE_TOKENS = frozenset({
    TokenType.FROM, TokenType.WHERE, TokenType.GROUP_BY, TokenType.ORDER_BY,
    TokenType.HAVING, TokenType.LIMIT, TokenType.OFFSET, TokenType.FETCH,
    TokenType.UNION, TokenType.EXCEPT, TokenType.INTERSECT, TokenType.FOR,
    TokenType.WINDOW, TokenType.SEMICOLON})


def _plpgsql_into(tokens, start_index: int, end_index: int) -> tuple[int, int] | None:
    """Token range of a PL/pgSQL ``INTO [STRICT] target[, ...]`` clause.

    In PL/pgSQL, ``SELECT ... INTO`` assigns variables and may appear after
    the select list or at the end of the statement; it is not SQL.
    """
    into = _top_level_token(tokens, start_index + 1, end_index,
                            kinds=(TokenType.INTO,))
    if into is None:
        return None
    cursor = into + 1
    if cursor <= end_index and tokens[cursor].text.casefold() == "strict":
        cursor += 1
    last = None
    # Target variables may share a spelling with a non-reserved keyword
    # (for example ``name``), so accept any word that does not open a clause.
    while (cursor <= end_index
           and re.fullmatch(r"[A-Za-z_][\w$]*|\"[^\"]+\"", tokens[cursor].text)
           and tokens[cursor].token_type not in _CLAUSE_TOKENS):
        last = cursor
        cursor += 1
        if cursor <= end_index and tokens[cursor].token_type in {
                TokenType.DOT, TokenType.COMMA}:
            cursor += 1
            continue
        break
    return (into, last) if last is not None else None


def _table_after(tokens, index: int):
    cursor = index + 1
    if cursor < len(tokens) and tokens[cursor].token_type == TokenType.TABLE:
        cursor += 1
    parts = []
    while cursor < len(tokens):
        if _is_identifier(tokens[cursor]):
            parts.append(tokens[cursor].text)
            cursor += 1
            if cursor < len(tokens) and tokens[cursor].token_type == TokenType.DOT:
                cursor += 1
                continue
            break
        break
    return ".".join(parts), cursor - 1


_TABLE_CONSTRAINTS = frozenset({"constraint", "primary", "foreign", "unique", "check",
                                "exclude", "like", "period"})


def _declared_columns(text: str) -> list[str]:
    """Column names a ``CREATE TABLE`` declares, in order; table constraints skipped."""
    masked = mask_sql(text)
    opening = masked.find("(")
    if opening < 0:
        return []
    depth, start, columns = 0, opening + 1, []
    for index in range(opening, len(masked)):
        character = masked[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if (character == "," and depth == 1) or depth == 0:
            segment = text[start:index].strip()
            name = re.match(r'\s*("[^"]+"|[\w$#]+)', segment)
            if name and name.group(1).casefold() not in _TABLE_CONSTRAINTS:
                columns.append(name.group(1).strip('"'))
            start = index + 1
            if depth == 0:
                break
    return columns


def _rowtype_record(unit: Unit, record: str, table: str, element: bool = False) -> bool:
    """Whether *record* is declared in *unit* as ``table%ROWTYPE``.

    With *element*, *record* is a collection whose element type is
    ``table%ROWTYPE`` (``TYPE t IS TABLE OF table%ROWTYPE``).
    """
    code = mask_sql(unit.text)
    rowtype = re.escape(table) + r"\s*%\s*ROWTYPE\b"
    if not element:
        return bool(re.search(r"(?im)^\s*" + re.escape(record) + r"\s+" + rowtype, code))
    declared = re.search(r"(?im)^\s*" + re.escape(record) + r"\s+([\w$#]+)\s*;", code)
    return bool(declared and re.search(
        r"(?is)\bTYPE\s+" + re.escape(declared.group(1)) + r"\s+IS\s+(?:TABLE|VARRAY\s*\([^)]*\))\s+OF\s+"
        + rowtype, code))


def _merge_values(unit: Unit, tokens, start_index: int, end_index: int,
                  target: str) -> tuple[list[str], list[dict]]:
    """Columns and values MERGE's WHEN branches write: UPDATE SET and INSERT."""
    columns, values = [], []
    branches = [index for index in range(start_index, end_index + 1)
                if tokens[index].text.casefold() == "when"
                and _top_level_token(tokens, index, index, texts=("when",)) is not None]
    branches = [index for index in branches
                if _top_level_token(tokens, start_index, index, texts=("when",)) is not None]
    bounds = list(zip(branches, branches[1:] + [end_index + 1]))
    pairs = _paren_pairs(tokens)
    for begin, finish in bounds:
        last = finish - 1
        update = _top_level_token(tokens, begin, last, kinds=(TokenType.UPDATE,))
        insert = _top_level_token(tokens, begin, last, kinds=(TokenType.INSERT,))
        if update is not None:
            # ``_update_values`` stops before its end token: give it the next
            # WHEN (or the statement end) so the last SET item is kept.
            branch_columns, branch_values = _update_values(
                unit, tokens, update, min(finish, end_index), target)
            columns += branch_columns; values += branch_values
        elif insert is not None:
            opening = insert + 1
            if opening <= last and tokens[opening].token_type == TokenType.L_PAREN \
                    and opening in pairs and pairs[opening] <= last:
                names = [part[-1].text for part in _split_tokens(tokens, opening + 1, pairs[opening])
                         if part and _is_identifier(part[-1])]
                values_index = _top_level_token(tokens, pairs[opening] + 1, last,
                                                kinds=(TokenType.VALUES,))
                if (values_index is not None and values_index + 1 <= last
                        and tokens[values_index + 1].token_type == TokenType.L_PAREN
                        and values_index + 1 in pairs):
                    parts = _split_tokens(tokens, values_index + 2, pairs[values_index + 1])
                    if len(parts) == len(names):
                        columns += names
                        values += [_token_expression(unit, part) for part in parts]
    return columns, values


def _token_expression(unit: Unit, part: list) -> dict | None:
    if not part:
        return None
    start, end = part[0].start, part[-1].end + 1
    return {"expression": unit.text[start:end].strip(),
            "position": start, "end": end}


def _top_level_token(tokens, start: int, end: int, kinds=(), texts=()) -> int | None:
    depth = 0
    lowered = {text.casefold() for text in texts}
    for index in range(start, end + 1):
        token = tokens[index]
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth = max(0, depth - 1)
        elif depth == 0 and (token.token_type in kinds
                or token.text.casefold() in lowered):
            return index
    return None


def _select_outputs(unit: Unit, tokens, start_index: int, end_index: int) -> list[dict]:
    into = _top_level_token(tokens, start_index + 1, end_index,
                            kinds=(TokenType.INTO,))
    from_index = _top_level_token(tokens, start_index + 1, end_index,
                                  kinds=(TokenType.FROM,))
    trailing_into = (into is not None and from_index is not None
                     and into > from_index)
    expressions_end = (from_index if trailing_into
                       else into if into is not None else from_index)
    if expressions_end is None:
        return []
    expressions = [_token_expression(unit, part) for part in
        _split_tokens(tokens, start_index + 1, expressions_end)]
    expressions = [item for item in expressions if item]
    destinations = []
    if into is not None and from_index is not None and into < from_index:
        destinations = [unit.text[part[0].start:part[-1].end + 1].strip()
            for part in _split_tokens(tokens, into + 1, from_index)]
    elif trailing_into:
        # PL/pgSQL also accepts INTO after the FROM/WHERE/LIMIT clauses.
        clause = _plpgsql_into(tokens, into - 1, end_index)
        if clause:
            destinations = [unit.text[part[0].start:part[-1].end + 1].strip()
                for part in _split_tokens(tokens, into + 1, clause[1] + 1)]
    destinations = [re.sub(r"(?i)^STRICT\s+", "", item) for item in destinations]
    result = []
    for index, expression in enumerate(expressions):
        destination = destinations[index] if index < len(destinations) else None
        result.append({**expression,
            "name": destination or f"result@{tokens[start_index].start}:{index}"})
    return result


def _update_values(unit: Unit, tokens, start_index: int, end_index: int,
                   target: str) -> tuple[list[str], list[dict]]:
    set_index = _top_level_token(tokens, start_index + 1, end_index,
                                 texts=("set",))
    if set_index is None:
        return [], []
    finish = _top_level_token(tokens, set_index + 1, end_index,
                              kinds=(TokenType.WHERE,), texts=("returning",))
    finish = finish if finish is not None else end_index
    columns, values = [], []
    for part in _split_tokens(tokens, set_index + 1, finish):
        equals = next((index for index, token in enumerate(part)
            if token.token_type == TokenType.EQ), None)
        if equals is None or not part[:equals] or not part[equals + 1:]:
            continue
        column = unit.text[part[0].start:part[equals - 1].end + 1].strip()
        expression = _token_expression(unit, part[equals + 1:])
        columns.append(column.rsplit(".", 1)[-1])
        values.append(expression)
    return columns, values


def _statement_predicate(unit: Unit, tokens, start_index: int,
                         end_index: int) -> str | None:
    where = _top_level_token(tokens, start_index + 1, end_index,
                             kinds=(TokenType.WHERE,))
    if where is None:
        return None
    finish = _top_level_token(tokens, where + 1, end_index,
        texts=("returning", "group", "order", "having", "limit"))
    finish = (finish - 1) if finish is not None else end_index
    while finish >= where and tokens[finish].token_type == TokenType.SEMICOLON:
        finish -= 1
    return _normalized_clause(unit.text[tokens[where].start:tokens[finish].end + 1])


def _with_operation(tokens, start_index: int, end_index: int) -> tuple[int, set[str]]:
    """Locate the outer DML verb and CTE aliases in a WITH statement."""
    if tokens[start_index].token_type != TokenType.WITH:
        return start_index, set()
    aliases, depth = set(), 0
    operation = start_index
    for index in range(start_index + 1, end_index + 1):
        token = tokens[index]
        if depth == 0 and _is_identifier(token) and index + 2 <= end_index \
                and tokens[index + 1].text.casefold() == "as" \
                and tokens[index + 2].token_type == TokenType.L_PAREN:
            aliases.add(token.text.casefold())
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth = max(0, depth - 1)
        elif depth == 0 and token.token_type in {
                TokenType.SELECT, TokenType.INSERT, TokenType.UPDATE,
                TokenType.DELETE}:
            operation = index
            break
    return operation, aliases


def _control_condition(unit: Unit, tokens, position: int) -> tuple[
        str | None, bool, list[tuple[int, int]]]:
    """Return token-derived enclosing control predicates for one statement."""
    frames, skip = [], set()

    def next_text(index: int, value: str) -> int | None:
        depth = 0
        for cursor in range(index + 1, len(tokens)):
            token = tokens[cursor]
            if token.start >= position:
                break
            depth += token.token_type == TokenType.L_PAREN
            depth -= token.token_type == TokenType.R_PAREN
            if depth == 0 and token.text.casefold() == value:
                return cursor
            if depth == 0 and token.token_type == TokenType.SEMICOLON:
                break
        return None

    def deciding(index: int) -> bool:
        """Whether the statement lies inside the condition this IF/ELSIF opens.

        The THEN closing the condition follows the statement, with no
        statement end between: the statement is evaluated to decide the
        branch, so this IF does not guard it.
        """
        depth = 0
        for cursor in range(index + 1, len(tokens)):
            token = tokens[cursor]
            depth += token.token_type == TokenType.L_PAREN
            depth -= token.token_type == TokenType.R_PAREN
            if depth == 0 and token.text.casefold() == "then":
                return token.start >= position
            if depth == 0 and token.token_type == TokenType.SEMICOLON:
                return False
        return False

    def pop(kind: str) -> bool:
        for index in range(len(frames) - 1, -1, -1):
            if frames[index]["kind"] == kind:
                del frames[index:]
                return True
        return False

    complete = True
    for index, token in enumerate(tokens):
        if token.start >= position:
            break
        if index in skip:
            continue
        word = token.text.casefold()
        following = tokens[index + 1].text.casefold() if index + 1 < len(tokens) else ""
        if word == "end" and following in {"if", "loop", "case"}:
            complete &= pop(following)
            skip.add(index + 1)
        elif word == "end" and frames and frames[-1]["kind"] == "case":
            # ``CASE ... END`` closes a CASE expression, not a block.
            frames.pop()
        elif word == "end":
            complete &= pop("block")
        elif word == "case":
            frames.append({"kind": "case", "condition": None,
                           "condition_span": None, "exception": False})
        elif frames and frames[-1]["kind"] == "case" and word in {"when", "else"}:
            # A CASE branch, never an IF's ELSE or an exception handler.
            continue
        elif token.token_type == TokenType.BEGIN:
            frames.append({"kind": "block", "condition": None,
                           "condition_span": None, "exception": False})
        elif word == "if" and not _statement_start(tokens, index):
            # ``IF(...)`` inside an expression is a function call.
            continue
        elif word in {"if", "elsif"}:
            then = next_text(index, "then")
            if then is None and deciding(index):
                # Evaluating an ELSIF condition happens only once every
                # earlier branch of its IF was false.
                selected = next((frame for frame in reversed(frames)
                                 if frame["kind"] == "if"), None) if word == "elsif" else None
                if word == "elsif" and selected is None:
                    complete = False
                elif selected:
                    selected["condition"] = "NOT (" + " OR ".join(selected["branches"]) + ")"
                    selected["condition_span"] = (token.start, token.end + 1)
                continue
            if then is None:
                complete = False
                continue
            condition = _normalized_clause(
                unit.text[token.end + 1:tokens[then].start])
            if word == "elsif":
                selected = next((frame for frame in reversed(frames)
                                 if frame["kind"] == "if"), None)
                if selected:
                    selected["condition"] = condition
                    selected["branches"].append(condition)
                    selected["condition_span"] = (
                        token.start, tokens[then].end + 1)
                else:
                    complete = False
            else:
                frames.append({"kind": "if", "condition": condition,
                               "branches": [condition],
                               "condition_span": (
                                   token.start, tokens[then].end + 1),
                               "exception": False})
        elif word == "else":
            selected = next((frame for frame in reversed(frames)
                             if frame["kind"] == "if"), None)
            if selected:
                selected["condition"] = "NOT (" + " OR ".join(
                    selected["branches"]) + ")"
                selected["condition_span"] = (token.start, token.end + 1)
            else:
                complete = False
        elif word in {"for", "while"}:
            loop = next_text(index, "loop")
            if loop is not None:
                frames.append({"kind": "loop", "condition": _normalized_clause(
                    unit.text[token.start:tokens[loop].start]),
                    "condition_span": (token.start, tokens[loop].end + 1),
                    "exception": False})
        elif word == "loop" and not any(
                frame["kind"] == "loop" for frame in frames[-1:]):
            frames.append({"kind": "loop", "condition": "LOOP",
                           "condition_span": (token.start, token.end + 1),
                           "exception": False})
        elif word == "exception":
            block = next((frame for frame in reversed(frames)
                          if frame["kind"] == "block"), None)
            if block:
                block["exception"] = True
                block["condition"] = None
                block["condition_span"] = None
            else:
                complete = False
        elif word == "when":
            block = next((frame for frame in reversed(frames)
                          if frame["kind"] == "block" and frame["exception"]), None)
            if block:
                then = next_text(index, "then")
                if then is None:
                    complete = False
                else:
                    block["condition"] = "EXCEPTION WHEN " + _normalized_clause(
                        unit.text[token.end + 1:tokens[then].start])
                    block["condition_span"] = (token.start, tokens[then].end + 1)
    # A statement inside a CASE statement's branch runs under a WHEN this
    # decoder does not record, so its condition is incomplete.
    if any(frame["kind"] == "case" for frame in frames):
        complete = False
    conditions = [frame["condition"] for frame in frames if frame["condition"]]
    spans = [frame["condition_span"] for frame in frames
             if frame.get("condition_span")]
    return (" AND ".join(f"({value})" for value in conditions) or None,
            complete, spans)


def _transaction_observation(unit: Unit, tokens) -> dict:
    material = getattr(unit, "sql_material_start", 0)
    relevant = [token for token in tokens if token.start >= material]
    commits = [token for token in relevant if token.token_type == TokenType.COMMIT]
    rollbacks = [token for token in relevant if token.token_type == TokenType.ROLLBACK]
    autonomous = bool(re.search(
        r"(?i)\bPRAGMA\s+AUTONOMOUS_TRANSACTION\s*;", mask_sql(unit.text)))
    pragma_span = None
    pragma = re.search(
        r"(?i)\bPRAGMA\s+AUTONOMOUS_TRANSACTION\s*;", mask_sql(unit.text))
    if pragma:
        pragma_span = (pragma.start(), pragma.end())
    return {
        "scope": ("autonomous_transaction" if autonomous else
                  "routine_transaction" if commits or rollbacks else
                  "caller_transaction"),
        "commits": [token.start for token in commits],
        "rollbacks": [token.start for token in rollbacks],
        "pragma_span": pragma_span,
        "completion_spans": {token.start: (token.start, token.end + 1)
                             for token in commits + rollbacks},
    }


def _parse_dml(unit: Unit, tokens, start_index: int, end_index: int) -> dict:
    start = tokens[start_index].start
    end = tokens[end_index].end + 1
    statement = unit.text[start:end]
    parsed = None
    diagnostic = None
    parse_text = statement
    if _dialect(unit.source) == "postgres":
        select_index, _ = _with_operation(tokens, start_index, end_index)
        clause = (_plpgsql_into(tokens, select_index, end_index)
                  if tokens[select_index].token_type == TokenType.SELECT else None)
        if clause:
            # Blank the variable assignment, preserving offsets for errors.
            first = tokens[clause[0]].start - start
            last = tokens[clause[1]].end + 1 - start
            parse_text = (statement[:first] + " " * (last - first)
                          + statement[last:])
    # ``WHERE CURRENT OF cursor`` names the row a cursor last fetched; the
    # parser has no grammar for it. Parse with a neutral predicate of the
    # same length; the statement predicate keeps the real text.
    parse_text = re.sub(r"(?i)\bWHERE\s+CURRENT\s+OF\s+[\w$#]+",
                        lambda match: "WHERE 1 = 1".ljust(len(match.group())), parse_text)
    try:
        parsed = parse_one(parse_text.rstrip().rstrip(";"), read=_parser_dialect(unit.source),
            error_level=ErrorLevel.RAISE)
    except ParseError as error:
        detail = error.errors[0] if error.errors else {}
        context = detail.get("start_context", "")
        highlight = detail.get("highlight", "") or statement[:1]
        error_start = min(end - 1, start + len(context))
        diagnostic = {"code": "SQL_MATERIAL_PARSE_ERROR",
            "message": f"{PARSER_ID}/{_dialect(unit.source)} {SQLGLOT_VERSION}: {detail.get('description', str(error))}",
            "start": error_start,
            "end": min(end, error_start + max(1, len(highlight)))}
    tables = []
    write_target = None
    columns, column_values, output_values = [], [], []
    operation_index, cte_aliases = _with_operation(tokens, start_index, end_index)
    kind = tokens[operation_index].token_type
    cursor = operation_index
    pairs = _paren_pairs(tokens)
    if kind == TokenType.INSERT:
        while cursor <= end_index and tokens[cursor].token_type != TokenType.INTO:
            cursor += 1
        if cursor <= end_index:
            write_target, table_index = _table_after(tokens, cursor)
            if write_target:
                tables.append(write_target)
            open_index = table_index + 1
            if open_index <= end_index and tokens[open_index].token_type == TokenType.L_PAREN \
                    and open_index in pairs and pairs[open_index] <= end_index:
                columns = [part[0].text for part in _split_tokens(
                    tokens, open_index + 1, pairs[open_index])
                    if len(part) == 1 and _is_identifier(part[0])]
                values_index = pairs[open_index] + 1
                while values_index <= end_index and tokens[values_index].token_type != TokenType.VALUES:
                    values_index += 1
                if values_index + 1 <= end_index \
                        and tokens[values_index + 1].token_type == TokenType.L_PAREN:
                    close = pairs.get(values_index + 1)
                    if close is not None:
                        for part in _split_tokens(tokens, values_index + 2, close):
                            column_values.append(_token_expression(unit, part))
            record_index = table_index + 2
            if (not column_values and table_index + 1 <= end_index
                    and tokens[table_index + 1].token_type == TokenType.VALUES
                    and record_index <= end_index and _is_identifier(tokens[record_index])):
                # ``INSERT INTO t VALUES rec`` with ``rec t%ROWTYPE`` (or an
                # element ``recs(i)`` of a collection of them) writes every
                # declared column of t from the matching record field.
                record = tokens[record_index]
                after = record_index + 1
                element = (after <= end_index and tokens[after].token_type == TokenType.L_PAREN
                           and after in pairs)
                closing = pairs[after] + 1 if element else after
                declared = getattr(unit, "sql_table_columns", {}).get(
                    write_target.casefold().rsplit(".", 1)[-1]) if write_target else None
                if (declared and (closing > end_index
                                  or tokens[closing].token_type == TokenType.SEMICOLON)
                        and _rowtype_record(unit, record.text, write_target, element)):
                    reference = unit.text[record.start:(tokens[pairs[after]].end + 1
                                                        if element else record.end + 1)]
                    columns = list(declared)
                    column_values = [{"expression": f"{reference}.{column}",
                                      "position": record.start,
                                      "end": tokens[closing - 1].end + 1}
                                     for column in declared]
            if not column_values:
                select_index = _top_level_token(tokens, table_index + 1,
                    end_index, kinds=(TokenType.SELECT,))
                if select_index is not None:
                    output_values = _select_outputs(
                        unit, tokens, select_index, end_index)
                    column_values = [{key: value[key]
                        for key in ("expression", "position", "end")}
                        for value in output_values]
    elif kind == TokenType.UPDATE:
        write_target, _ = _table_after(tokens, operation_index)
        if write_target:
            tables.append(write_target)
            columns, column_values = _update_values(
                unit, tokens, start_index, end_index, write_target)
    elif kind == TokenType.MERGE:
        while cursor <= end_index and tokens[cursor].token_type != TokenType.INTO:
            cursor += 1
        if cursor <= end_index:
            write_target, _ = _table_after(tokens, cursor)
            if write_target:
                tables.append(write_target)
            if write_target:
                columns, column_values = _merge_values(
                    unit, tokens, operation_index, end_index, write_target)
        using = _top_level_token(tokens, operation_index + 1, end_index,
                                 kinds=(TokenType.USING,))
        if using is not None:
            source_table, _ = _table_after(tokens, using)
            if source_table:
                tables.append(source_table)
    elif kind == TokenType.DELETE:
        while cursor <= end_index and tokens[cursor].token_type != TokenType.FROM:
            cursor += 1
        if cursor <= end_index:
            write_target, _ = _table_after(tokens, cursor)
            if write_target:
                tables.append(write_target)
    if kind == TokenType.SELECT:
        output_values = _select_outputs(unit, tokens, operation_index, end_index)
    existing = {name.casefold() for name in tables}
    for cursor in range(start_index, end_index + 1):
        if tokens[cursor].token_type in {TokenType.FROM, TokenType.JOIN}:
            table, _ = _table_after(tokens, cursor)
            if (table and table.casefold() not in cte_aliases
                    and table.casefold() not in existing):
                tables.append(table); existing.add(table.casefold())
    if diagnostic is not None:
        diagnostic["recoverable"] = bool(tables)
    return {"start": start, "end": end, "kind": kind, "ast": parsed,
        "diagnostic": diagnostic, "tables": tables, "write_target": write_target,
        "columns": columns, "column_values": column_values,
        "output_values": output_values,
        "predicate": _statement_predicate(unit, tokens, operation_index, end_index),
        "cte_aliases": sorted(cte_aliases)}


def _on_observations(unit: Unit, tokens, pairs, body_index: int) -> list[dict]:
    result = []
    for index in range(body_index, len(tokens)):
        if tokens[index].token_type != TokenType.ON:
            continue
        end_index = index
        if index + 1 < len(tokens) and tokens[index + 1].token_type == TokenType.L_PAREN:
            end_index = pairs.get(index + 1, index + 1)
        else:
            depth = 0
            for cursor in range(index + 1, len(tokens)):
                depth += tokens[cursor].token_type == TokenType.L_PAREN
                depth -= tokens[cursor].token_type == TokenType.R_PAREN
                if depth == 0 and (tokens[cursor].token_type in {
                        TokenType.JOIN, TokenType.WHERE, TokenType.SEMICOLON}
                        or tokens[cursor].text.casefold() in {"group", "order"}):
                    break
                end_index = cursor
        start, end = tokens[index].start, tokens[end_index].end + 1
        result.append({"span": (start, end), "source_location_kind": "sql",
            "native_expression": unit.text[start:end].strip()})
    return result


def _inside(position: int, record: dict) -> bool:
    return record["start"] <= position < record["end"]


def _is_table_column_list(tokens, name_index: int) -> bool:
    return (name_index > 1 and tokens[name_index - 1].token_type == TokenType.INTO
        and tokens[name_index - 2].token_type == TokenType.INSERT)


# Text before a token that starts a statement: the end of the previous
# statement, or a keyword that opens a statement list.
_STATEMENT_START = re.compile(r"(?is)(?:;|\b(?:BEGIN|THEN|ELSE|LOOP|DECLARE)\b|^)\s*$")


def _statement_start(tokens, index: int) -> bool:
    """Whether ``tokens[index]`` begins a procedural statement."""
    prior = index - 1
    return prior < 0 or tokens[prior].token_type in {
        TokenType.BEGIN, TokenType.SEMICOLON, TokenType.THEN, TokenType.ELSE,
    } or tokens[prior].text.casefold() in {"loop", "declare"}


def _statement_level(tokens, receiver_start: int) -> bool:
    prior = receiver_start - 1
    return prior < 0 or tokens[prior].token_type in {
        TokenType.BEGIN, TokenType.SEMICOLON, TokenType.THEN,
        TokenType.ELSE,
    }


# Keywords between an assignment and its EXECUTE IMMEDIATE that make the
# path between them conditional: the assignment might not be the one run.
_BRANCHING = frozenset({"if", "elsif", "else", "case", "when", "loop", "end",
                        "exception", "goto", "return", "exit", "continue"})
_RUNTIME = "speed_runtime_"
_DYNAMIC_KINDS = {exp.Insert: TokenType.INSERT, exp.Update: TokenType.UPDATE,
                  exp.Delete: TokenType.DELETE, exp.Merge: TokenType.MERGE,
                  exp.Select: TokenType.SELECT}


def _dynamic_text(unit: Unit, tokens, execute_index: int, end_index: int):
    """The statement text an ``EXECUTE IMMEDIATE`` runs, or None.

    String literals are kept; every other concatenated piece becomes a named
    runtime placeholder. A variable is followed to its one assignment in the
    straight-line code before the EXECUTE; a branch, another assignment or an
    ``INTO`` of that variable in between leaves the text unknown.
    Returns ``(text, {placeholder: source expression}, evidence spans)``.
    """
    # The tokenizer reads ``EXECUTE`` as a command and hands back the rest
    # of the statement as one string: tokenize that body on its own.
    if execute_index + 1 > end_index:
        return None
    body_start = tokens[execute_index].end + 1
    body_text = unit.text[body_start:tokens[execute_index + 1].end + 1]
    try:
        body = _tokenize(body_text, unit.source)
    except (TokenError, ValueError):
        return None
    if not body or body[0].text.casefold() != "immediate":
        return None
    stop = next((index for index in range(1, len(body))
                 if body[index].token_type in {TokenType.INTO, TokenType.USING,
                                               TokenType.RETURNING, TokenType.SEMICOLON}
                 or body[index].text.casefold() == "bulk"), len(body))
    pieces = body[1:stop]
    text_of = lambda first, last: body_text[first.start:last.end + 1]
    spans = []
    if len(pieces) == 1 and _is_identifier(pieces[0]):
        name = pieces[0].text.casefold()
        assignment = None
        for index in range(execute_index - 1, -1, -1):
            token = tokens[index]
            if (token.token_type == TokenType.COLON_EQ and index
                    and tokens[index - 1].text.casefold() == name):
                assignment = index
                break
        if assignment is None:
            return None
        finish = _statement_end(tokens, assignment)
        between = tokens[finish + 1:execute_index]
        if any(token.text.casefold() in _BRANCHING for token in between) or any(
                token.text.casefold() == name for token in between):
            return None
        pieces = [token for token in tokens[assignment + 1:finish + 1]
                  if token.token_type != TokenType.SEMICOLON]
        text_of = lambda first, last: unit.text[first.start:last.end + 1]
        spans.append((tokens[assignment - 1].start, tokens[finish].end + 1))
    parts, runtime, current = [], {}, []
    for token in pieces + [None]:
        if token is None or token.token_type == TokenType.DPIPE:
            if not current:
                return None
            if len(current) == 1 and current[0].token_type == TokenType.STRING:
                parts.append(current[0].text)
            else:
                placeholder = f"{_RUNTIME}{len(runtime) + 1}"
                runtime[placeholder] = text_of(current[0], current[-1]).strip()
                parts.append(placeholder)
            current = []
        else:
            current.append(token)
    if not runtime and not any(parts):
        return None
    return "".join(parts), runtime, spans


def _dynamic_statement(unit: Unit, tokens, execute_index: int, end_index: int):
    """A DML statement for a resolvable ``EXECUTE IMMEDIATE``, or None."""
    evaluated = _dynamic_text(unit, tokens, execute_index, end_index)
    if evaluated is None:
        return None
    text, runtime, spans = evaluated
    # Numbered binds (``:1``) have no grammar in the parser; name them,
    # never touching quoted literal text.
    masked = mask_sql(text)
    parse_text = "".join(
        f":b{text[match.start() + 1:match.end()]}" if masked[match.start()] == ":" else match.group()
        for match in re.finditer(r":\d+|[^:]+|:", text))
    try:
        parsed = parse_one(parse_text.rstrip().rstrip(";"), read=_parser_dialect(unit.source),
                           error_level=ErrorLevel.RAISE)
    except (ParseError, TokenError, ValueError):
        return None
    kind = next((value for node, value in _DYNAMIC_KINDS.items()
                 if isinstance(parsed, node)), None)
    if kind is None:
        return None

    def name_of(table):
        name = ".".join(part for part in (table.db, table.name) if part)
        if _RUNTIME not in name:
            return name
        source = ", ".join(expression for placeholder, expression in runtime.items()
                           if placeholder in name)
        return f"(runtime: {source})"

    write_target = None
    if kind != TokenType.SELECT:
        target = parsed.this
        target = target.this if isinstance(target, exp.Schema) else target
        write_target = name_of(target) if isinstance(target, exp.Table) else None
    tables = []
    for table in parsed.find_all(exp.Table):
        name = name_of(table)
        if name and name.casefold() not in {item.casefold() for item in tables}:
            tables.append(name)
    start, end = tokens[execute_index].start, tokens[end_index].end + 1
    columns, values = [], []
    if isinstance(parsed, exp.Update):
        for assignment in parsed.expressions:
            if isinstance(assignment, exp.EQ) and isinstance(assignment.this, exp.Column):
                columns.append(assignment.this.name)
                values.append({"expression": assignment.expression.sql(), "position": start, "end": end})
    elif isinstance(parsed, exp.Insert) and isinstance(parsed.this, exp.Schema):
        names = [column.name for column in parsed.this.expressions]
        source = parsed.expression
        selected = (source.expressions if isinstance(source, exp.Select) else
                    source.expressions[0].expressions if isinstance(source, exp.Values)
                    and source.expressions else [])
        if len(selected) == len(names):
            columns = names
            values = [{"expression": item.sql(), "position": start, "end": end}
                      for item in selected]
    return {"start": start, "end": end, "kind": kind, "ast": parsed, "diagnostic": None,
            "tables": tables, "write_target": write_target, "columns": columns,
            "column_values": values, "output_values": [], "predicate": None,
            "cte_aliases": [], "dynamic": {"text": text, "runtime": runtime,
                                           "spans": spans}}


def _analyze_unit(unit: Unit, routines: list[Unit], declared_tables: set[str]) -> None:
    unit.sql_calls = []
    unit.sql_observations = []
    unit.sql_dml = []
    unit.sql_material_diagnostics = []
    unit.sql_declared_tables = declared_tables
    if not unit.executable_body:
        return
    try:
        tokens = _tokenize(unit.text, unit.source)
    except TokenError:
        normalized = _mask_oracle_q_literals(unit.text)
        try:
            tokens = _tokenize(normalized, unit.source)
        except Exception as error:
            unit.sql_material_diagnostics.append({"code": "SQL_MATERIAL_PARSE_ERROR",
                "message": f"{PARSER_ID}/{_dialect(unit.source)} {SQLGLOT_VERSION}: {type(error).__name__}",
                "start": 0, "end": max(1, len(unit.text))})
            return
        match = re.search(r"(?i)q'(.)", unit.text)
        start = match.start() if match else 0
        unit.sql_material_diagnostics.append({"code": "SQL_Q_LITERAL_NORMALIZED",
            "message": (f"{PARSER_ID}/{_dialect(unit.source)} {SQLGLOT_VERSION}: "
                "Oracle Q literal required bounded lexical normalization."),
            "start": start, "end": min(len(unit.text), start + 2)})
    except Exception as error:
        unit.sql_material_diagnostics.append({"code": "SQL_MATERIAL_PARSE_ERROR",
            "message": f"{PARSER_ID}/{_dialect(unit.source)} {SQLGLOT_VERSION}: {type(error).__name__}",
            "start": 0, "end": max(1, len(unit.text))})
        return
    body_position = getattr(unit, "sql_body_start", 0)
    if getattr(unit, "sql_statement_body", False):
        # A statement-list body has no BEGIN; scanning starts at its first
        # token, so the routine's own declaration is never read as a call.
        body_index = next((index for index, token in enumerate(tokens)
            if token.start >= body_position), len(tokens)) - 1
        body_index = max(0, body_index)
    else:
        body_index = next((index for index, token in enumerate(tokens)
            if token.start >= body_position and token.token_type == TokenType.BEGIN), 0)
    material_position = getattr(unit, "sql_material_start", body_position)
    material_index = next((index for index, token in enumerate(tokens)
        if token.start >= material_position), body_index)
    pairs = _paren_pairs(tokens)
    unmatched_opens = [index for index, token in enumerate(tokens)
        if token.token_type == TokenType.L_PAREN and index not in pairs]
    close_count = sum(token.token_type == TokenType.R_PAREN for token in tokens)
    if unmatched_opens or close_count > len(pairs):
        token = (tokens[unmatched_opens[0]] if unmatched_opens else
            next(item for item in tokens if item.token_type == TokenType.R_PAREN))
        unit.sql_material_diagnostics.append({"code": "SQL_MATERIAL_PARSE_ERROR",
            "message": f"{PARSER_ID}/{_dialect(unit.source)} {SQLGLOT_VERSION}: unmatched parenthesis",
            "start": token.start, "end": token.end + 1})
    if not getattr(unit, "sql_declaration_complete", True):
        unit.sql_material_diagnostics.append({"code": "SQL_MATERIAL_PARSE_ERROR",
            "message": f"{PARSER_ID}/{_dialect(unit.source)} {SQLGLOT_VERSION}: incomplete BEGIN/END block",
            "start": max(0, len(unit.text) - 1), "end": len(unit.text)})
    collections = _collection_names(tokens, body_index,
        getattr(unit.source, "sql_collection_types", ()))
    # MERGE is one statement: its WHEN ... UPDATE/INSERT branches and USING
    # subquery are parts of it, not statements of their own.
    dml_starts = {TokenType.WITH, TokenType.SELECT, TokenType.INSERT,
                  TokenType.UPDATE, TokenType.DELETE, TokenType.MERGE}
    cursor = material_index
    while cursor < len(tokens):
        if tokens[cursor].token_type in dml_starts:
            end_index = _statement_end(tokens, cursor)
            statement = _parse_dml(unit, tokens, cursor, end_index)
            unit.sql_dml.append(statement)
            if statement["diagnostic"]:
                unit.sql_material_diagnostics.append(statement["diagnostic"])
            cursor = end_index
        cursor += 1
    dynamic_executes = set()
    for index in range(material_index, len(tokens) - 1):
        if (tokens[index].token_type == TokenType.EXECUTE
                and tokens[index + 1].text.casefold().startswith("immediate")):
            dynamic = _dynamic_statement(unit, tokens, index, _statement_end(tokens, index))
            if dynamic is not None:
                unit.sql_dml.append(dynamic)
                dynamic_executes.add(tokens[index].start)
    unit.sql_dml.sort(key=lambda statement: statement["start"])
    for statement in unit.sql_dml:
        control, complete, spans = _control_condition(
            unit, tokens, statement["start"])
        trigger_condition = (getattr(unit, "sql_trigger_registration", {})
                             or {}).get("condition")
        if trigger_condition:
            control = " AND ".join(value for value in (
                trigger_condition, control) if value)
            header = mask_sql(unit.text)[:body_position]
            trigger_span = re.search(r"(?is)\bWHEN\s*\(.*\)\s*$", header)
            if trigger_span:
                spans.append((trigger_span.start(), trigger_span.end()))
        statement["control_condition"] = control
        statement["control_complete"] = complete
        statement["control_spans"] = spans
    unit.sql_transaction = _transaction_observation(unit, tokens)
    unit.sql_observations.extend(_on_observations(unit, tokens, pairs, body_index))
    local_names = {candidate.name.casefold() for candidate in routines}
    dialect = Dialect.get_or_raise(_parser_dialect(unit.source))
    builtin_names = {name.casefold() for name in dialect.parser_class.FUNCTIONS}
    seen = set()
    for name_index in range(body_index + 1, len(tokens) - 1):
        name_token = tokens[name_index]
        if (not _is_identifier(name_token)
                or tokens[name_index + 1].token_type != TokenType.L_PAREN):
            continue
        if _procedural_keyword(tokens, name_index):
            continue
        open_index = name_index + 1
        if open_index not in pairs or _is_table_column_list(tokens, name_index):
            continue
        close_index = pairs[open_index]
        receiver_parts = []
        receiver_start = name_index
        scan = name_index - 1
        while (scan >= 1 and tokens[scan].token_type == TokenType.DOT
                and _is_identifier(tokens[scan - 1])):
            receiver_parts.insert(0, tokens[scan - 1].text)
            receiver_start = scan - 1
            scan -= 2
        receiver = ".".join(receiver_parts) or None
        start, end = tokens[receiver_start].start, tokens[close_index].end + 1
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        name = name_token.text
        lowered = name.casefold()
        dml = next((statement for statement in unit.sql_dml
            if _inside(start, statement)), None)
        qualified_name = ".".join(part for part in (receiver, name) if part)
        if (dml and dml["write_target"]
                and qualified_name.casefold() == dml["write_target"].casefold()):
            continue
        arguments = _arguments(tokens, open_index, close_index, unit)
        if lowered in collections and receiver is None:
            unit.sql_observations.append({"span": (start, end),
                "source_location_kind": "sql",
                "native_expression": unit.text[start:end].strip()})
            continue
        if receiver and receiver.casefold().rsplit(".", 1)[-1] in _EXTERNAL_PACKAGES:
            classification = "external"
        elif lowered in local_names:
            classification = "local"
        elif receiver:
            classification = "qualified"
        elif (dml or lowered in builtin_names
                or (_dialect(unit.source) == "oracle"
                    and lowered in _ORACLE_RUNTIME_ROUTINES)
                or not _statement_level(tokens, receiver_start)):
            unit.sql_observations.append({"span": (start, end),
                "source_location_kind": "sql",
                "native_expression": unit.text[start:end].strip()})
            continue
        else:
            classification = "local"
        unit.sql_calls.append({"receiver": receiver, "name": name,
            "position": start, "start": start, "end": end,
            "arguments": arguments, "classification": classification})
    for index, token in enumerate(tokens[body_index + 1:], body_index + 1):
        if token.token_type != TokenType.EXECUTE:
            continue
        end_index = _statement_end(tokens, index)
        start, end = token.start, tokens[end_index].end + 1
        statement = unit.text[start:end].strip()
        if token.start in dynamic_executes:
            # Its statement text was evaluated: the EXECUTE is that statement.
            continue
        if statement.casefold().startswith("execute immediate"):
            unit.sql_calls.append({"receiver": None, "name": "dynamic_sql",
                "position": start, "start": start, "end": end,
                "arguments": [], "classification": "dynamic"})
    unit.sql_calls.sort(key=lambda item: (item["position"], item["name"].casefold()))
    unit.sql_observations.sort(key=lambda item: item["span"])
    fatal_diagnostics = [item for item in unit.sql_material_diagnostics
                         if not item.get("recoverable", False)]
    if fatal_diagnostics:
        unit.valid_terminal = False
        unit.required_capabilities = tuple(sorted(
            set(unit.required_capabilities or ())
            | {"call_classification", "callable_resolution"}))
    else:
        unit.valid_terminal = True
        unit.required_capabilities = tuple(sorted(
            set(unit.required_capabilities or ())
            | {"call_classification", "callable_resolution"}))
        if getattr(unit, "sql_declaration_kind", None) == "standalone_body":
            unit.anchor_resolution = "resolved"
            unit.anchor_reason = None


def _select_trigger_functions(routines: list[Unit]) -> None:
    """Select the function a PostgreSQL ``CREATE TRIGGER`` executes.

    ``EXECUTE FUNCTION f(args)`` passes literal trigger arguments; trigger
    functions themselves declare no parameters. A qualified reference must
    match the declaring schema; an unqualified one matches an unqualified or
    ``public`` declaration.
    """
    functions = {}
    for unit in routines:
        if (getattr(unit, "sql_declaration_kind", None) == "standalone_body"
                and unit.sql_routine_kind == "function" and not unit.params):
            owner = (unit.owner or "public").casefold()
            functions.setdefault((owner, unit.name.casefold()), []).append(unit)
    for registration in routines:
        reference = getattr(registration, "sql_trigger_function", None)
        if not reference or registration.anchor_resolution != "resolved":
            continue
        schema, _, name = reference.rpartition(".")
        matches = sorted(functions.get(((schema or "public").casefold(),
                                        name.casefold()), []),
                         key=lambda unit: unit.qualified)[:MAX_SEMANTIC_CANDIDATES]
        span = (registration.start, registration.end)
        registration.anchor_correspondence_relationship_kind = "selects_implementation"
        if len(matches) == 1:
            function = matches[0]
            registration.anchor_correspondence_units = [function]
            registration.anchor_correspondence_state = "resolved"
            registration.anchor_correspondence_reason = (
                f"The trigger's EXECUTE clause names {reference}(), the one "
                "matching function declared in the analyzed SQL.")
            registration.source.semantic_relations.append({
                "source": registration, "target": function,
                "candidate_targets": [], "kind": "selects_implementation",
                "start": span[0], "end": span[1], "resolution": "resolved",
                "outcome": "exact", "reason": None,
                "evidence_spans": [(function.source, function.start,
                    function.start + max(1, function.sql_body_start))]})
            # PostgreSQL rejects direct calls to a trigger function; the
            # trigger is its entry point and the function its implementation.
            function.anchor_kind = None
            function.anchor_resolution = None
            function.anchor_reason = None
            continue
        if matches:
            reason = (f"Trigger function {reference}() matches {len(matches)} "
                      "declarations in the analyzed SQL.")
            code = "SQL_IMPLEMENTATION_AMBIGUOUS"
            registration.anchor_correspondence_units = matches
            registration.anchor_correspondence_state = "ambiguous"
            registration.anchor_correspondence_reason = reason
            registration.source.semantic_relations.append({
                "source": registration, "target": None,
                "candidate_targets": matches, "kind": "selects_implementation",
                "start": span[0], "end": span[1], "resolution": "ambiguous",
                "outcome": "ambiguous", "diagnostic_code": code,
                "reason": reason})
        elif (platform := _platform_routine(registration, schema or None, name)):
            # A routine the platform provides: the trigger runs documented
            # platform behavior, an external implementation, never a gap.
            registration.source.semantic_relations.append({
                "source": registration, "target": None, "candidate_targets": [],
                "kind": "selects_implementation", "start": span[0], "end": span[1],
                "resolution": "unresolved", "outcome": "external",
                "diagnostic_code": "SQL_PLATFORM_CALL",
                "external_target_id": identifier("resource", "sql-platform-routine",
                                                 platform["name"].casefold(),
                                                 reference.casefold()),
                "reason": (f"The trigger executes {reference}(), which the "
                           f"{platform['name']} platform provides; its behavior is "
                           "documented, not declared in the repository.")})
            continue
        else:
            reason = (f"Trigger function {reference}() is not declared in the "
                      "analyzed SQL.")
            code = "SQL_IMPLEMENTATION_UNAVAILABLE"
            registration.anchor_correspondence_state = "unresolved"
            registration.anchor_correspondence_reason = reason
        # The firing registration is evidenced, but the entry point's behavior
        # is not, so the registration is not an eligible canonical anchor.
        registration.anchor_resolution = (
            "ambiguous" if matches else "unresolved")
        registration.anchor_reason = reason
        registration.anchor_registration = {
            **registration.anchor_registration,
            "candidate_targets": sorted({unit.qualified for unit in matches}),
            "resolution": registration.anchor_resolution, "reason": reason}
        registration.anchor_eligibility = "unresolved"
        registration.source.sql_diagnostics.append({
            "code": code, "reason": reason, "span": span})


def prepare(sources, units, diagnostics=None):
    """Analyze SQL syntax, select package bodies, and establish local scope."""
    diagnostics = diagnostics if diagnostics is not None else []
    source_ids = {id(source) for source in sources}
    routines = [unit for unit in units if id(unit.source) in source_ids
        and unit.kind == "declarative_operation"]
    tables = [unit for unit in units if id(unit.source) in source_ids
        and getattr(unit, "sql_declaration_kind", None) == "table"]
    declared_tables = {unit.name.casefold() for unit in tables}
    declared_tables.update(unit.name.rsplit(".", 1)[-1].casefold() for unit in tables)
    table_columns = {}
    for table in tables:
        columns = _declared_columns(table.text)
        table_columns.setdefault(table.name.casefold(), columns)
        table_columns.setdefault(table.name.rsplit(".", 1)[-1].casefold(), columns)
    for source in sources:
        source.semantic_relations = []
        source.sql_diagnostics = []
        try:
            source_tokens = _tokenize(source.text, source)
        except TokenError:
            source_tokens = _tokenize(_mask_oracle_q_literals(source.text), source)
        source.sql_collection_types = _collection_types(
            source_tokens, len(source_tokens))
    for unit in routines:
        unit.sql_table_columns = table_columns
        _analyze_unit(unit, routines, declared_tables)
        for item in unit.sql_material_diagnostics:
            unit.source.sql_diagnostics.append({"code": item["code"],
                "reason": item["message"],
                "span": (unit.start + item["start"],
                    unit.start + item["end"])})
    for registration in routines:
        body = getattr(registration, 'sql_trigger_body', None)
        if body is None:
            continue
        registration.source.semantic_relations.append({
            'source': registration, 'target': body, 'candidate_targets': [],
            'kind': 'selects_implementation', 'start': registration.start,
            'end': registration.end, 'resolution': 'resolved',
            'outcome': 'exact', 'reason': None,
        })
    _select_trigger_functions(routines)
    policies = [unit for unit in units if id(unit.source) in source_ids
        and getattr(unit, "sql_declaration_kind", None) in {
            "row_security_policy", "row_security_enablement"}]
    secured = {unit.sql_policy["table"].casefold() for unit in policies
        if unit.sql_declaration_kind == "row_security_enablement"}
    for unit in policies:
        unit.sql_declared_tables = declared_tables
        unit.sql_row_security_enabled = (
            unit.sql_policy["table"].casefold() in secured)
    contracts = [unit for unit in routines
        if getattr(unit, "sql_declaration_kind", None) == "package_spec"]
    bodies_by_key = {}
    for unit in routines:
        if getattr(unit, "sql_declaration_kind", None) == "package_body":
            bodies_by_key.setdefault(unit.sql_contract_key, []).append(unit)
    for contract in contracts:
        matches = sorted(bodies_by_key.get(contract.sql_contract_key, []),
            key=lambda unit: unit.qualified)[:MAX_SEMANTIC_CANDIDATES]
        contract.anchor_correspondence_units = matches
        contract.anchor_correspondence_relationship_kind = "selects_implementation"
        if len(matches) == 1:
            contract.anchor_correspondence_state = "resolved"
            contract.anchor_correspondence_reason = (
                "Exact package, routine kind, name, arity, and parameter types select this body.")
            contract.anchor_resolution = "resolved"
            contract.anchor_reason = None
            matches[0].anchor_resolution = "resolved"
            matches[0].anchor_reason = None
            relation = {"source": contract, "target": matches[0],
                "candidate_targets": [], "kind": "selects_implementation",
                "start": contract.start, "end": contract.end,
                "resolution": "resolved", "outcome": "exact", "reason": None}
        elif matches:
            contract.anchor_correspondence_state = "ambiguous"
            contract.anchor_correspondence_reason = (
                "Multiple package bodies match this public routine contract.")
            selection_reason = "Multiple package bodies match this public routine contract."
            for candidate in matches:
                candidate.anchor_resolution = "ambiguous"
                candidate.anchor_reason = "Multiple executable bodies share this public routine identity."
            relation = {"source": contract, "target": None,
                "candidate_targets": matches, "kind": "selects_implementation",
                "start": contract.start, "end": contract.end,
                "resolution": "ambiguous", "outcome": "ambiguous",
                "diagnostic_code": "SQL_IMPLEMENTATION_AMBIGUOUS",
                "reason": selection_reason}
            diagnostics.append({"code": "SQL_IMPLEMENTATION_AMBIGUOUS",
                "message": selection_reason,
                "subject_ids": [contract.source.resource_id], "evidence_ids": []})
        else:
            contract.anchor_correspondence_state = "unresolved"
            contract.anchor_correspondence_reason = (
                "No package body matches this public routine contract.")
            relation = None
            diagnostics.append({"code": "SQL_IMPLEMENTATION_UNAVAILABLE",
                "message": contract.anchor_correspondence_reason,
                "subject_ids": [contract.source.resource_id], "evidence_ids": []})
        if relation:
            contract.source.semantic_relations.append(relation)
    public_contract_keys = {contract.sql_contract_key for contract in contracts}
    for bodies in bodies_by_key.values():
        for body in bodies:
            if body.sql_contract_key not in public_contract_keys:
                # A body-only package routine has no evidenced public contract.
                # Keep its callable symbol, but do not expose it as an entry point.
                body.anchor_kind = None
                body.anchor_resolution = None
                body.anchor_reason = None


def relations(source):
    return getattr(source, "semantic_relations", [])


def diagnostics(source):
    return list(getattr(source, "sql_diagnostics", []))


def parameter_direction(type_name):
    return "output" if re.match(r"(?i)OUT\b", type_name) else "input"


def bindings(unit):
    result = []
    for name, type_name in unit.params:
        directions = (["input", "output"]
            if re.match(r"(?i)IN\s+OUT\b", type_name)
            else [parameter_direction(type_name)])
        result.extend({"name": name, "value_type": type_name,
            "direction": direction, "expression": name}
            for direction in directions)
    code = mask_sql(unit.text)
    for match in re.finditer(r"(?i)\bRETURN\b([^;]*);", code):
        begin = re.search(r"(?i)\bBEGIN\b", code)
        if not begin or match.start() < begin.start():
            continue
        result.append({"name": "return@" + str(match.start()),
            "value_type": "unknown", "direction": "output",
            "expression": unit.text[match.start(1):match.end(1)].strip()})
    return result


def _resource(unit: Unit, name: str) -> dict:
    known = getattr(unit, "sql_declared_tables", set())
    resolved = (name.casefold() in known
        or name.rsplit(".", 1)[-1].casefold() in known)
    platform = None if resolved else _platform_table(unit, name)
    runtime = name.startswith("(runtime: ")
    return {"kind": "table", "name": name, "language": unit.source.language,
        "resolution": "resolved" if resolved else "unresolved",
        "reason": None if resolved else
            (f"The table is chosen at runtime from {name[10:-1]}; the rest of the "
             "dynamic statement is static text." if runtime else
             f"Table {name} is provided by the {platform['name']} platform this repository "
             "targets; no repository declaration describes it." if platform else
             "Table identity is syntactically present; repository declaration was not found.")}


def resources(unit):
    if unit.kind == "type":
        return [{"kind": "table", "name": unit.name,
            "language": unit.source.language,
            "resolution": "resolved", "reason": None}]
    # Operation targets are projected atomically from ``operations`` with
    # exact statement evidence; this hook owns declarations only.
    return []


def calls(unit):
    return [{"receiver": item["receiver"], "name": item["name"],
        "position": item["position"], "end": item["end"]}
        for item in getattr(unit, "sql_calls", [])]


def _call(unit: Unit, receiver, name, position):
    return next((item for item in getattr(unit, "sql_calls", [])
        if item["receiver"] == receiver and item["name"] == name
        and item["position"] == position), None)


def call_span(unit: Unit, position: int) -> tuple[int, int]:
    call = next((item for item in getattr(unit, "sql_calls", [])
        if item["position"] == position), None)
    return ((call["start"], call["end"])
        if call else (position, position + 1))


def _candidate_score(call: dict, candidate: Unit):
    """How well a call's arguments match *candidate*, or None when they cannot.

    A parameter the call omits must declare a default. In PostgreSQL a quoted
    literal has no type of its own until it is matched, so it is accepted for
    any parameter type (an enum or a domain, for instance), scoring below an
    exact type match; other dialects require the types to agree.
    """
    arguments = call["arguments"]
    defaults = getattr(candidate, "sql_param_defaults", ()) or ()
    if len(arguments) > len(candidate.params):
        return None
    parameters = {name.casefold(): (index, _base_type(type_name))
        for index, (name, type_name) in enumerate(candidate.params)}
    coerces_literals = _dialect(candidate.source) == "postgres"
    score, provided = 0, set()
    for index, argument in enumerate(arguments):
        parameter_index = index
        if argument["name"]:
            selected = parameters.get(argument["name"])
            if selected is None:
                return None
            parameter_index = selected[0]
        if parameter_index in provided:
            return None
        provided.add(parameter_index)
        argument_type = argument["type"]
        parameter_type = _base_type(candidate.params[parameter_index][1])
        if argument_type != "unknown" and parameter_type != "unknown":
            if argument_type == parameter_type:
                score += 1
            elif not (coerces_literals and argument.get("literal")):
                return None
    if any(index not in provided and not (index < len(defaults) and defaults[index])
           for index in range(len(candidate.params))):
        return None
    return score


def candidates(unit, receiver, name, available, position=None):
    call = _call(unit, receiver, name, position)
    if not call or call["classification"] in {"external", "dynamic"}:
        return []
    choices = [candidate for candidate in available
        if candidate.kind == "declarative_operation"]
    if receiver:
        receiver_key = receiver.casefold()
        choices = [candidate for candidate in choices if candidate.owner and (
            candidate.owner.casefold() == receiver_key
            or candidate.owner.casefold().rsplit(".", 1)[-1] == receiver_key)]
    elif unit.owner:
        scoped = [candidate for candidate in choices if candidate.owner
            and candidate.owner.casefold() == unit.owner.casefold()]
        if scoped:
            choices = scoped
    implementations = [candidate for candidate in choices
        if candidate.executable_body]
    if implementations:
        choices = implementations
    scored = [(score, candidate) for candidate in choices
        if (score := _candidate_score(call, candidate)) is not None]
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return sorted((candidate for score, candidate in scored if score == best),
        key=lambda candidate: candidate.qualified)[:MAX_SEMANTIC_CANDIDATES]


@functools.lru_cache(maxsize=1)
def _platform_catalog():
    path = Path(__file__).parents[1] / "data" / "sql_platform_routines.json"
    return tuple(json.loads(path.read_text())["platforms"])


def _platform_table(unit, name):
    """The catalogued platform that provides table *name* here, or None."""
    table = name.casefold().replace('"', "")
    dialect = _dialect(unit.source)
    return next((platform for platform in _platform_catalog()
                 if dialect in platform["dialects"]
                 and table in {item.casefold() for item in platform.get("tables", ())}
                 and re.search(platform["path_pattern"], unit.source.path)), None)


def _platform_routine(unit, receiver, name):
    """The catalogued platform that provides ``receiver.name`` here, or None.

    An unqualified name matches only in a schema the platform always puts on
    the search path (``implicit_schemas``).
    """
    dialect = _dialect(unit.source)
    for platform in _platform_catalog():
        if dialect not in platform["dialects"] or not re.search(
                platform["path_pattern"], unit.source.path):
            continue
        routines = {item.casefold() for item in platform["routines"]}
        schemas = ([receiver] if receiver else platform.get("implicit_schemas", []))
        if any(f"{schema}.{name}".casefold() in routines for schema in schemas):
            return platform
    return None


def resolve_call(unit, receiver, name, candidates, position, evidence_id=None):
    call = _call(unit, receiver, name, position)
    evidence = (evidence_id or unit.evidence_id,)
    if not call:
        return SemanticResult(capability="callable_resolution",
            outcome="unresolved", subject_id=unit.symbol_id,
            evidence_ids=evidence, diagnostic_code="SQL_CALL_UNRESOLVED",
            reason="SQL call metadata is unavailable.")
    classification = call["classification"]
    dialect_name = _parser_dialect(unit.source)
    if classification == "external":
        target = identifier("resource", "sql-external-package",
            (receiver or "unknown").casefold(), name.casefold())
        return SemanticResult(capability="callable_resolution",
            outcome="external", subject_id=unit.symbol_id, target_id=target,
            evidence_ids=evidence, diagnostic_code="SQL_EXTERNAL_PACKAGE_CALL",
            reason=f"{dialect_name} external package call {(receiver or 'unknown')}.{name}; implementation is outside the repository.")
    if classification == "dynamic":
        return SemanticResult(capability="callable_resolution",
            outcome="unresolved", subject_id=unit.symbol_id,
            evidence_ids=evidence, diagnostic_code="SQL_DYNAMIC_CALL",
            reason="Dynamic SQL target is selected at runtime and cannot be resolved statically.")
    if len(candidates) == 1:
        return SemanticResult(capability="callable_resolution", outcome="exact",
            subject_id=unit.symbol_id, target_id=candidates[0].symbol_id,
            evidence_ids=evidence)
    if len(candidates) > 1:
        return SemanticResult(capability="callable_resolution", outcome="ambiguous",
            subject_id=unit.symbol_id,
            candidate_target_ids=tuple(sorted(
                candidate.symbol_id for candidate in candidates)),
            evidence_ids=evidence, diagnostic_code="SQL_CALL_AMBIGUOUS",
            reason=f"{dialect_name} call {name} has {len(candidates)} equally supported overloads.")
    platform = _platform_routine(unit, receiver, name)
    if platform:
        routine = f"{receiver}.{name}".casefold()
        return SemanticResult(capability="callable_resolution", outcome="external",
            subject_id=unit.symbol_id,
            target_id=identifier("resource", "sql-platform-routine",
                                 platform["name"].casefold(), routine),
            evidence_ids=evidence, diagnostic_code="SQL_PLATFORM_CALL",
            reason=(f"{dialect_name} call {routine} is provided by the {platform['name']} "
                    f"platform this repository targets ({unit.source.path}); no repository "
                    "declaration answers it."),
            provider=platform["provider"])
    qualified = f"{receiver}." if receiver else ""
    return SemanticResult(capability="callable_resolution", outcome="unresolved",
        subject_id=unit.symbol_id, evidence_ids=evidence,
        diagnostic_code="SQL_CALL_UNRESOLVED",
        reason=(f"{dialect_name} call {qualified}{name} has no repository declaration "
            "matching package, arity, names and types."))


_POLICY_EFFECT = {
    "using": "existing rows are visible or targetable only when the USING predicate holds",
    "with_check": "new or updated rows are accepted only when the WITH CHECK predicate holds",
}


def _without_comments(text: str) -> str:
    pattern = re.compile(r"--[^\n]*|/\*[\s\S]*?\*/|'(?:''|[^'])*'")
    return pattern.sub(lambda match: match.group()
                       if match.group().startswith("'") else " ", text)


def _row_security_observations(unit: Unit) -> list[dict]:
    """PostgreSQL row-level security declarations as authorization rules."""
    policy = unit.sql_policy
    table = policy["table"]
    resource = _resource(unit, table)
    statement = _normalized_clause(_without_comments(unit.text))
    if unit.sql_declaration_kind == "row_security_enablement":
        return [{"span": (0, len(unit.text)), "identity_key": "row_security",
            "source_location_kind": "sql", "native_expression": statement,
            "resource": resource, "resolution": "unresolved",
            "reason": (f"Row-level security is {'forced' if policy['mode'] == 'FORCE' else 'enabled'} "
                       f"on {table}: rows are denied unless a policy permits the command; "
                       "the permitting policies and the roles that bypass them "
                       "require trace interpretation.")}]
    enabled = ("row-level security enablement for this table is declared in the analyzed SQL"
               if getattr(unit, "sql_row_security_enabled", False) else
               "row-level security enablement for this table was not observed in the analyzed SQL")
    head = f'CREATE POLICY "{policy["name"]}" ON {table} AS {policy["mode"]} FOR {policy["command"]}'
    if policy["roles"]:
        head += f' TO {policy["roles"]}'
    scope = {"environment": None, "tenant": None, "actor": policy["roles"],
             "profile": None, "effective_from": None, "effective_to": None,
             "version": None, "entrypoint_ids": None}
    clauses = policy["clauses"] or {"statement": (0, len(unit.text))}
    result = []
    for key, (start, end) in sorted(clauses.items(), key=lambda item: item[1]):
        clause = _normalized_clause(_without_comments(unit.text[start:end]))
        effect = _POLICY_EFFECT.get(key, "the policy declares no row predicate")
        result.append({"span": (start, end), "identity_key": f"policy:{key}",
            "source_location_kind": "sql",
            "native_expression": (head + " " + clause) if key in _POLICY_EFFECT else statement,
            "resource": resource, "scope": scope, "resolution": "unresolved",
            "reason": (f"{policy['mode'].capitalize()} row-level security policy for "
                       f"{policy['command']} on {table}: {effect}; {enabled}.")})
    return result


def observations(unit):
    if getattr(unit, "sql_declaration_kind", None) in {
            "row_security_policy", "row_security_enablement"}:
        return _row_security_observations(unit)
    if unit.kind == "type":
        result = []
        code = mask_sql(unit.text)
        for match in re.finditer(
                r"(?im)^.*\b(?:NOT\s+NULL|PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK)\b[^\n]*",
                code):
            end = match.end()
            check = re.search(r"(?i)\bCHECK\s*\(", match.group())
            if check:
                position = match.start() + check.end(); depth = 1
                while position < len(code) and depth:
                    depth += (code[position] == "(") - (code[position] == ")")
                    position += 1
                end = max(end, position)
            result.append({"span": (match.start(), end),
                "source_location_kind": "sql",
                "native_expression": unit.text[match.start():end].strip(),
                "resource": {"kind": "table", "name": unit.name,
                    "language": unit.source.language,
                    "resolution": "resolved", "reason": None}})
        return result
    result = list(getattr(unit, "sql_observations", []))
    code = mask_sql(unit.text)
    result.extend({"span": (match.start(), match.end()),
            "source_location_kind": "sql",
            "native_expression": unit.text[match.start():match.end()].strip()}
        for match in re.finditer(
            r"(?im)^\s*(?:IF\s+|CHECK\s*\(|UNIQUE\s*\(|FOREIGN KEY\s*\()[^\n]+",
            code))
    unique = {(item["span"], item["native_expression"]): item
        for item in result}
    return [unique[key] for key in sorted(unique)]


def operations(unit):
    result = []
    parameter_names = {name.casefold(): name for name, type_name in unit.params
        if not re.match(r"(?i)OUT\b", type_name)}
    assigned_outputs = {name.casefold(): name for name, type_name in unit.params
        if re.match(r"(?i)(?:IN\s+OUT|OUT)\b", type_name)}
    code = mask_sql(unit.text)
    assigned_outputs = sorted(name for lowered, name in assigned_outputs.items()
        if re.search(rf"(?i)\b{re.escape(lowered)}\b\s*:=", code))
    transaction = getattr(unit, "sql_transaction", {
        "scope": None, "commits": [], "rollbacks": [], "pragma_span": None,
        "completion_spans": {}})

    def binding(value: dict, name: str) -> dict:
        return {"name": name, "value_type": "unknown",
            "expression": value["expression"], "position": value["position"],
            "end": value["end"], "resolution": "resolved", "reason": None}

    def projection(statement: dict, resource: dict, kind: str,
                   input_names=(), inline_inputs=(), inline_outputs=(),
                   output_names=()):
        gaps = []
        if resource["resolution"] != "resolved":
            # A platform-provided table is a known boundary, not a missing one.
            gaps.append({"projection": "target",
                "code": ("SQL_DYNAMIC_TABLE" if resource["name"].startswith("(runtime: ")
                         else "SQL_PLATFORM_TABLE" if _platform_table(unit, resource["name"])
                         else "SQL_DATA_TARGET_UNRESOLVED"),
                "reason": resource["reason"]})
        if statement["diagnostic"]:
            gaps.append({"projection": "condition", "code": "SQL_OPERATION_PARSE_GAP",
                "reason": statement["diagnostic"]["message"]})
        if not statement.get("control_complete", True):
            gaps.append({"projection": "condition", "code": "SQL_CONTROL_FLOW_UNRESOLVED",
                "reason": "The enclosing procedural control condition could not be completely decoded."})
        if kind == "data_write" and statement["kind"] in {
                TokenType.INSERT, TokenType.UPDATE, TokenType.MERGE} and not inline_inputs:
            gaps.append({"projection": "input_bindings", "code": "SQL_CHANGED_VALUES_UNRESOLVED",
                "reason": "Changed fields or their value expressions could not be completely decoded."})
        if kind == "data_write" and not transaction["scope"]:
            gaps.append({"projection": "transaction_scope", "code": "SQL_TRANSACTION_SCOPE_UNRESOLVED",
                "reason": "The write transaction scope could not be established."})
        commits_after = [position for position in transaction["commits"]
                         if position > statement["end"]]
        rollbacks_after = [position for position in transaction["rollbacks"]
                           if position > statement["end"]]
        if kind == "data_write" and commits_after:
            completion = "declared"
            status = ("explicit_commit_and_rollback_declared" if rollbacks_after
                      else "explicit_commit_declared")
            gaps.append({"projection": "completion", "code": "SQL_COMPLETION_UNRESOLVED",
                "reason": "Commit syntax is declared, but static evidence cannot establish runtime completion."})
        elif kind == "data_write" and rollbacks_after:
            completion = "declared"
            status = "explicit_rollback_declared"
            gaps.append({"projection": "completion", "code": "SQL_COMMIT_NOT_ESTABLISHED",
                "reason": "Rollback syntax is observed, but no completing commit is established."})
        elif kind == "data_write":
            completion = "declared"
            status = "caller_completion_unobserved"
            gaps.append({"projection": "completion", "code": "SQL_COMPLETION_UNRESOLVED",
                "reason": "No completion is established; transaction completion remains caller-controlled."})
        else:
            completion, status = "declared", None
        reason = "; ".join(gap["reason"] for gap in gaps) or None
        condition = " AND ".join(value for value in (
            statement.get("control_condition"), statement.get("predicate")) if value) or None
        supporting = list(statement.get("control_spans", []))
        if kind == "data_write" and transaction["pragma_span"]:
            supporting.append(transaction["pragma_span"])
        if kind == "data_write":
            supporting.extend(transaction["completion_spans"][position]
                for position in commits_after + rollbacks_after)
        return declare_operation_observation(unit,
            position=statement["start"], end=statement["end"], kind=kind,
            outcome=unit.text[statement["start"]:statement["end"]],
            resource=resource, input_binding_names=input_names,
            output_binding_names=output_names,
            input_bindings=list(inline_inputs), output_bindings=list(inline_outputs),
            condition=condition, protocol="sql", status=status,
            transaction_scope=transaction["scope"], completion=completion,
            supporting_evidence_spans=supporting,
            projection_gaps=gaps,
            resolution="unresolved" if gaps else "resolved", reason=reason)

    for statement in getattr(unit, "sql_dml", []):
        text = unit.text[statement["start"]:statement["end"]]
        try:
            statement_tokens = _tokenize(text, unit.source)
        except Exception:
            statement_tokens = []
        inputs = sorted({parameter_names[token.text.casefold()]
            for token in statement_tokens if _is_identifier(token)
            and token.text.casefold() in parameter_names})
        inline_inputs = []
        if statement["write_target"]:
            used = set()
            for index, column in enumerate(statement["columns"]):
                if index >= len(statement["column_values"]) or not statement["column_values"][index]:
                    continue
                value = statement["column_values"][index]
                name = f"{statement['write_target']}.{column}@{statement['start']}"
                if name in used:
                    # The same column written by another MERGE branch.
                    name = f"{statement['write_target']}.{column}@{value['position']}"
                used.add(name)
                inline_inputs.append(binding(value, name))
        inline_outputs = [binding(value, value["name"])
                          for value in statement["output_values"]]
        if statement["kind"] == TokenType.SELECT:
            for table in statement["tables"]:
                resource = _resource(unit, table)
                result.append(projection(statement, resource, "data_read",
                    input_names=inputs, inline_outputs=inline_outputs))
        elif statement["write_target"]:
            resource = _resource(unit, statement["write_target"])
            result.append(projection(statement, resource, "data_write",
                inputs, inline_inputs, inline_outputs, assigned_outputs))
            for table in statement["tables"]:
                if table.casefold() != statement["write_target"].casefold():
                    result.append(projection(statement, _resource(unit, table),
                        "data_read", input_names=inputs,
                        inline_outputs=inline_outputs))
    return result
