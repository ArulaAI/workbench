"""Oracle PL/SQL syntax and semantic adapter. Never executes SQL.

Call classification is driven by the pinned sqlglot Oracle tokenizer/AST plus
repository declarations. There is deliberately no ``WORD(`` regex fallback.
"""
from __future__ import annotations

import re

from ..language_registry import registry

sqlglot = registry.load_trusted_parser("sqlglot")
from sqlglot import Dialect, parse_one
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


def _parameters(text: str, dialect: str) -> list[tuple[str, str]]:
    """Normalize Oracle and PostgreSQL argument ordering to ``(name, type)``."""
    result = []
    for segment in _parameter_segments(text):
        if dialect == "postgres":
            match = re.match(
                r"(?is)^(?:(INOUT|IN\s+OUT|IN|OUT|VARIADIC)\s+)?"
                r"([\w$#]+)\s+(.+)$", segment)
            if not match:
                continue
            mode, name, type_name = match.groups()
            mode = "IN OUT" if mode and mode.casefold() == "inout" else mode
        else:
            match = re.match(
                r"(?is)^([\w$#]+)\s+(?:(IN\s+OUT|IN|OUT)\s+)?(.+)$",
                segment,
            )
            if not match:
                continue
            name, mode, type_name = match.groups()
        type_name = re.split(
            r"(?i)\s+(?:DEFAULT|:=)\s*|\s+=\s*", type_name, maxsplit=1,
        )[0].strip()
        normalized_mode = re.sub(r"\s+", " ", mode or "").upper()
        normalized = f"{normalized_mode} {type_name}".strip()
        result.append((name, normalized))
    return result


def _normalized_clause(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _trigger_registration(header: str) -> tuple[dict, str | None]:
    match = re.match(
        r"(?is)^\s*(BEFORE|AFTER|INSTEAD\s+OF)\s+(.+?)\s+ON\s+([\w$#.]+)\b(.*)$",
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


def extract(source: Source) -> list[Unit]:
    _ensure_parser()
    code = mask_sql(source.text)
    packages = list(re.finditer(
        r"(?i)\bCREATE\s+(?:OR\s+REPLACE\s+)?PACKAGE\s+(BODY\s+)?([\w$#]+(?:\.[\w$#]+)*)", code))
    units = []
    for match in re.finditer(r"(?i)\b(PROCEDURE|FUNCTION|TRIGGER)\s+([\w.$#]+)", code):
        tail = code[match.end():]
        intro = re.search(r"(?i)\b(IS|AS|BEGIN)\b|;", tail)
        if not intro:
            continue
        start_body = match.end() + intro.start()
        package = _package_at(packages, code, match.start())
        owner = package.group(2) if package else None
        package_body = bool(package and package.group(1))
        header = code[match.end():start_body]
        param_text = header[header.find("(") + 1:header.rfind(")")] if "(" in header else ""
        params = _parameters(param_text, _dialect(source))
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
            unit.sql_routine_kind = match.group(1).casefold()
            unit.sql_contract_key = (owner.casefold(), unit.sql_routine_kind,
                unit.name.casefold(), _signature(params))
            declare_trace_contract(unit, "contract")
            declare_anchor_representation(unit, "contract",
                _routine_identity(unit), "eligible", "public")
            units.append(unit)
            continue
        begin = re.search(r"(?i)\bBEGIN\b", code[start_body:])
        if not begin:
            continue
        begin_at = start_body + begin.start()
        tokens = list(re.finditer(r"(?i)\b(BEGIN|IF|LOOP|CASE|END)\b|;", code[begin_at:]))
        depth, finish, skip_qualifier = 0, len(code), False
        for token in tokens:
            word = token.group().upper()
            if skip_qualifier and word in ("IF", "LOOP", "CASE"):
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
        unit.sql_routine_kind = match.group(1).casefold()
        unit.sql_contract_key = ((owner.casefold(), unit.sql_routine_kind,
            unit.name.casefold(), _signature(params)) if package_body else None)
        unit.sql_body_start = begin_at - unit.start
        unit.sql_material_start = (match.end() + intro.end()) - unit.start
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
            r"(?i)\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.$#]+)\s*\(",
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
        result.append({"name": named, "type": _argument_type(part, unit)})
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
    for index in range(start_index, len(tokens)):
        if tokens[index].token_type == TokenType.SEMICOLON:
            return index
    return len(tokens) - 1


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
    expressions_end = into if into is not None else from_index
    if expressions_end is None:
        return []
    expressions = [_token_expression(unit, part) for part in
        _split_tokens(tokens, start_index + 1, expressions_end)]
    expressions = [item for item in expressions if item]
    destinations = []
    if into is not None and from_index is not None and into < from_index:
        destinations = [unit.text[part[0].start:part[-1].end + 1].strip()
            for part in _split_tokens(tokens, into + 1, from_index)]
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
        elif word == "end":
            complete &= pop("block")
        elif token.token_type == TokenType.BEGIN:
            frames.append({"kind": "block", "condition": None,
                           "condition_span": None, "exception": False})
        elif word in {"if", "elsif"}:
            then = next_text(index, "then")
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
    try:
        parsed = parse_one(statement.rstrip().rstrip(";"), read=_parser_dialect(unit.source),
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


def _statement_level(tokens, receiver_start: int) -> bool:
    prior = receiver_start - 1
    return prior < 0 or tokens[prior].token_type in {
        TokenType.BEGIN, TokenType.SEMICOLON, TokenType.THEN,
        TokenType.ELSE,
    }


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
    dml_starts = {TokenType.WITH, TokenType.SELECT, TokenType.INSERT,
                  TokenType.UPDATE, TokenType.DELETE}
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
    return {"kind": "table", "name": name, "language": unit.source.language,
        "resolution": "resolved" if resolved else "unresolved",
        "reason": None if resolved else
            "Table identity is syntactically present; repository declaration was not found."}


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
    arguments = call["arguments"]
    if len(arguments) != len(candidate.params):
        return None
    parameters = {name.casefold(): (index, _base_type(type_name))
        for index, (name, type_name) in enumerate(candidate.params)}
    score = 0
    for index, argument in enumerate(arguments):
        parameter_index = index
        if argument["name"]:
            selected = parameters.get(argument["name"])
            if selected is None:
                return None
            parameter_index = selected[0]
        argument_type = argument["type"]
        parameter_type = _base_type(candidate.params[parameter_index][1])
        if argument_type != "unknown" and parameter_type != "unknown":
            if argument_type != parameter_type:
                return None
            score += 1
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
    qualified = f"{receiver}." if receiver else ""
    return SemanticResult(capability="callable_resolution", outcome="unresolved",
        subject_id=unit.symbol_id, evidence_ids=evidence,
        diagnostic_code="SQL_CALL_UNRESOLVED",
        reason=(f"{dialect_name} call {qualified}{name} has no repository declaration "
            "matching package, arity, names and types."))


def observations(unit):
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
            gaps.append({"projection": "target", "code": "SQL_DATA_TARGET_UNRESOLVED",
                "reason": resource["reason"]})
        if statement["diagnostic"]:
            gaps.append({"projection": "condition", "code": "SQL_OPERATION_PARSE_GAP",
                "reason": statement["diagnostic"]["message"]})
        if not statement.get("control_complete", True):
            gaps.append({"projection": "condition", "code": "SQL_CONTROL_FLOW_UNRESOLVED",
                "reason": "The enclosing procedural control condition could not be completely decoded."})
        if kind == "data_write" and statement["kind"] in {
                TokenType.INSERT, TokenType.UPDATE} and not inline_inputs:
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
            for index, column in enumerate(statement["columns"]):
                if index >= len(statement["column_values"]):
                    continue
                value = statement["column_values"][index]
                inline_inputs.append(binding(value,
                    f"{statement['write_target']}.{column}@{statement['start']}"))
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
