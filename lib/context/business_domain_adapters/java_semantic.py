"""Java semantic adapter built on the tree-sitter Java grammar.

Never runs build tools or repository code. Only declarations in the supplied
snapshots are resolved; missing imports stay as capability boundaries.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_java

from . import CATALOG, rules
from ..language_registry import registry
from .base import (MAX_SEMANTIC_CANDIDATES, SemanticResult, Unit, declare_operation_observation,
                   declare_trace_contract)
from ..business_domain_schema import identifier


_PARSER = Parser(Language(tree_sitter_java.language()))
_TYPE_NODES = {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}
_METHOD_NODES = {"method_declaration", "constructor_declaration"}
# Type nodes a heritage clause names directly (generic arguments are nested inside).
_HERITAGE_TYPE_NODES = {"type_identifier", "scoped_type_identifier", "generic_type"}
# Abstract classes are class_declarations too and can hold inherited bodies.
_CONCRETE_TYPE_KINDS = {"class_declaration", "enum_declaration", "record_declaration"}
# Bodyless declarations; calls to them are linked to the implementing methods.
_DISPATCH_ROLES = {"interface", "abstract_declaration"}
# Max heritage hops; guards against cycles in malformed code.
_MAX_HERITAGE_DEPTH = 8


def _children(node, kinds=None):
    for child in node.children:
        if child.is_named and (kinds is None or child.type in kinds):
            yield child


def _walk(node, kinds=None):
    if kinds is None or node.type in kinds:
        yield node
    for child in _children(node):
        yield from _walk(child, kinds)


def _text(source, node):
    return source.text.encode()[node.start_byte:node.end_byte].decode("utf-8")


def _char(source, byte_offset):
    return len(source.text.encode()[:byte_offset].decode("utf-8"))


def _simple(type_name):
    value = re.sub(r"<.*>", "", type_name or "").replace("[]", "").strip()
    return value.rsplit(".", 1)[-1]


def _type_text(source, node):
    if node is None:
        return "unknown"
    return re.sub(r"\s+", "", _text(source, node))


def _annotations(source, node):
    modifiers = next(_children(node, {"modifiers"}), None)
    result = []
    if modifiers:
        for annotation in _children(modifiers, {"annotation", "marker_annotation"}):
            name = annotation.child_by_field_name("name")
            if name is None:
                name = next(_children(annotation, {"identifier", "scoped_identifier"}), None)
            result.append({
                "name": _text(source, name).rsplit(".", 1)[-1] if name else "",
                "qualified_name": _text(source, name) if name else "",
                "text": _text(source, annotation),
                "start": _char(source, annotation.start_byte),
                "end": _char(source, annotation.end_byte),
                "arguments": _annotation_arguments(source, annotation),
            })
    return result


class JavaLiteralError(ValueError):
    def __init__(self, cause: str, start: int, end: int):
        super().__init__(cause)
        self.cause, self.start, self.end = cause, start, end


def _annotation_arguments(source, annotation):
    arguments = next(_children(annotation, {'annotation_argument_list'}), None)
    if arguments is None:
        return []
    result = []
    for child in _children(arguments):
        if child.type == 'element_value_pair':
            key = child.child_by_field_name('key')
            value = child.child_by_field_name('value')
            name = _text(source, key) if key is not None else ''
        else:
            name, value = 'value', child
        values = (list(_children(value))
            if value is not None and value.type == 'element_value_array_initializer'
            else [value])
        for item in values:
            if item is not None:
                result.append({'name': name, 'expression': _text(source, item),
                    'start': _char(source, item.start_byte),
                    'end': _char(source, item.end_byte)})
    return result


def _unicode_translate_java(token: str):
    translated, spans = [], []
    cursor = 0
    translated_backslash_run = 0
    last_raw_character_was_unicode_escape = False
    while cursor < len(token):
        eligible = (token[cursor] == '\\' and
            (last_raw_character_was_unicode_escape
             or translated_backslash_run % 2 == 0))
        if eligible:
            probe = cursor + 1
            while probe < len(token) and token[probe] == 'u':
                probe += 1
            if probe > cursor + 1 and probe + 4 <= len(token) \
                    and re.fullmatch(r'[0-9a-fA-F]{4}', token[probe:probe + 4]):
                character = chr(int(token[probe:probe + 4], 16))
                translated.append(character)
                spans.append((cursor, probe + 4))
                cursor = probe + 4
                translated_backslash_run = (
                    translated_backslash_run + 1
                    if character == '\\' else 0)
                last_raw_character_was_unicode_escape = True
                continue
        character = token[cursor]
        translated.append(character)
        spans.append((cursor, cursor + 1))
        cursor += 1
        translated_backslash_run = (translated_backslash_run + 1
            if character == '\\' else 0)
        last_raw_character_was_unicode_escape = False
    return ''.join(translated), tuple(spans)


def _literal_error(cause, spans, start, end):
    if start < len(spans):
        raw_start = spans[start][0]
        raw_end = spans[min(max(start, end - 1), len(spans) - 1)][1]
    else:
        raw_start = raw_end = spans[-1][1] if spans else 0
    raise JavaLiteralError(cause, raw_start, raw_end)


def _decode_java_string_literal(token: str) -> str:
    translated, spans = _unicode_translate_java(token)
    if (len(translated) < 2 or translated[0] != '"' or translated[-1] != '"'
            or translated.startswith('"""') or '\r' in translated
            or '\n' in translated):
        _literal_error('ordinary_string_literal_required', spans, 0,
            len(translated))
    result, cursor, end = [], 1, len(translated) - 1
    escapes = {'b': '\b', 't': '\t', 'n': '\n', 'f': '\f', 'r': '\r',
        's': ' ', '"': '"', "'": "'", '\\': '\\'}
    while cursor < end:
        char = translated[cursor]
        if char == '"':
            _literal_error('unescaped_quote', spans, cursor, cursor + 1)
        if char != '\\':
            codepoint, finish = ord(char), cursor + 1
        else:
            if cursor + 1 >= end:
                _literal_error('truncated_escape', spans, cursor, cursor + 1)
            escaped = translated[cursor + 1]
            if escaped in escapes:
                result.append(escapes[escaped])
                cursor += 2
                continue
            if escaped in '01234567':
                maximum = 3 if escaped in '0123' else 2
                finish = cursor + 2
                while finish < end and finish < cursor + 1 + maximum \
                        and translated[finish] in '01234567':
                    finish += 1
                result.append(chr(int(translated[cursor + 1:finish], 8)))
                cursor = finish
                continue
            _literal_error('invalid_escape', spans, cursor, cursor + 2)
        if 0xD800 <= codepoint <= 0xDBFF:
            if finish >= end:
                _literal_error('lone_high_surrogate', spans, cursor, finish)
            low = ord(translated[finish])
            if not 0xDC00 <= low <= 0xDFFF:
                _literal_error('invalid_surrogate_pair', spans, finish, finish + 1)
            result.append(chr(0x10000 + ((codepoint - 0xD800) << 10)
                              + low - 0xDC00))
            cursor = finish + 1
            continue
        if 0xDC00 <= codepoint <= 0xDFFF:
            _literal_error('lone_low_surrogate', spans, cursor, finish)
        result.append(chr(codepoint))
        cursor = finish
    return ''.join(result)


def _parameters(source, node):
    params = node.child_by_field_name("parameters")
    result = []
    if not params:
        return result
    for param in _children(params, {"formal_parameter", "spread_parameter", "receiver_parameter"}):
        name = param.child_by_field_name("name")
        type_node = param.child_by_field_name("type")
        if type_node is None:
            named = list(_children(param))
            type_node = next((item for item in named if item is not name and item.type != "modifiers"), None)
        result.append((_text(source, name) if name else "arg", _type_text(source, type_node)))
    return result


def _heritage_nodes(clause):
    """Return the top-level type nodes of a heritage clause.

    Type arguments are skipped: ``extends Repository<Owner, Integer>`` has one parent.
    """
    if clause is None:
        return []
    lists = list(_children(clause, {"type_list"})) or [clause]
    return [item for parent in lists for item in _children(parent, _HERITAGE_TYPE_NODES)]


def _annotation_type(source, annotation):
    """Return an annotation's qualified name from its text or imports, else None."""
    written = annotation["text"].lstrip("@").split("(", 1)[0].strip()
    if "." in written:
        return written
    return source.semantic["imports"].get(written)


# MapStruct generates mapper implementations only when both are present.
_MAPSTRUCT_MAPPER = "org.mapstruct.Mapper"
_MAPSTRUCT_PROCESSOR = ("org.mapstruct", "mapstruct-processor")


def _keyword_modifiers(node):
    """Return a declaration's modifier keywords, e.g. ``{"public", "static"}``."""
    modifiers = next(_children(node, {"modifiers"}), None)
    return {child.type for child in modifiers.children if not child.is_named} if modifiers else set()


# Unqualified names only; a qualified name is never a type variable.
_TYPE_VARIABLE_NAME = re.compile(r"(?<![\w.$])[A-Za-z_$][\w$]*")


def _type_parameters(source, node):
    """Return ``{name: bound}`` for a declaration's type parameters.

    Uses the leftmost bound (the erasure); unbounded parameters map to ``Object``.
    """
    clause = node.child_by_field_name("type_parameters") if node is not None else None
    result = {}
    for parameter in _children(clause, {"type_parameter"}) if clause else ():
        name = next(_children(parameter, {"type_identifier", "identifier"}), None)
        bound_clause = next(_children(parameter, {"type_bound"}), None)
        bound = next(_children(bound_clause), None) if bound_clause else None
        if name:
            result[_text(source, name)] = _type_text(source, bound) if bound else "Object"
    return result


def _without_type_arguments(text):
    """Strip every ``<...>`` argument list from a written type."""
    kept, depth = [], 0
    for char in text or "":
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif depth == 0:
            kept.append(char)
    return "".join(kept)


def _type_arguments(text):
    """Return the top-level type arguments, or None for a raw type."""
    text = text or ""
    start = text.find("<")
    if start < 0:
        return None
    arguments, current, depth = [], [], 0
    for char in text[start + 1:]:
        if char == "<":
            depth += 1
        elif char == ">":
            if depth == 0:
                break
            depth -= 1
        elif char == "," and depth == 0:
            arguments.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    arguments.append("".join(current).strip())
    return arguments


def _substitute(text, mapping):
    """Replace type variables using *mapping*."""
    if not mapping:
        return text
    return _TYPE_VARIABLE_NAME.sub(lambda match: mapping.get(match.group(0), match.group(0)), text)


def _erased(text, variables, depth=0):
    """Return ``(simple name, array depth)`` of a written type after erasure.

    Type variables in *variables* erase to their bound.
    """
    base = _without_type_arguments(text).replace(" ", "")
    dimensions = base.count("[]")
    name = base.replace("[]", "").rsplit(".", 1)[-1]
    if name in variables and depth < _MAX_HERITAGE_DEPTH:
        bound_name, bound_dimensions = _erased(variables[name], variables, depth + 1)
        return bound_name, dimensions + bound_dimensions
    return name, dimensions


def _matching_unit(units, source, node, name):
    start, end = _char(source, node.start_byte), _char(source, node.end_byte)
    exact = [unit for unit in units if unit.source is source and unit.name == name
             and unit.start == start and unit.end == end]
    if exact:
        return exact[0]
    containing = [unit for unit in units if unit.source is source and unit.name == name
                  and unit.start <= start and end <= unit.end]
    return min(containing, key=lambda unit: unit.end-unit.start) if containing else None


def _literal_type(source, node, variables):
    kinds = {
        "string_literal": "java.lang.String", "character_literal": "char",
        "decimal_integer_literal": "int", "hex_integer_literal": "int",
        "octal_integer_literal": "int", "binary_integer_literal": "int",
        "decimal_floating_point_literal": "double", "hex_floating_point_literal": "double",
        "true": "boolean", "false": "boolean", "boolean_literal": "boolean",
        "null_literal": "null",
    }
    if node.type in kinds:
        return kinds[node.type]
    if node.type == "identifier":
        return variables.get(_text(source, node), "unknown")
    if node.type == "object_creation_expression":
        return _type_text(source, node.child_by_field_name("type"))
    if node.type == "cast_expression":
        return _type_text(source, node.child_by_field_name("type"))
    return "unknown"


def _parse(source, units):
    root = _PARSER.parse(source.text.encode()).root_node
    package_node = next(_walk(root, {"package_declaration"}), None)
    package = ""
    if package_node:
        package = re.sub(r"^package\s+|;$", "", _text(source, package_node).strip())
    imports, wildcards = {}, []
    for node in _walk(root, {"import_declaration"}):
        value = re.sub(r"^import\s+(?:static\s+)?|;$", "", _text(source, node).strip())
        if value.endswith(".*"):
            wildcards.append(value[:-2])
        elif not value.endswith(".*"):
            imports[value.rsplit(".", 1)[-1]] = value
    info = {"package": package, "imports": imports, "wildcards": wildcards,
            "types": [], "methods": [], "invocations": []}
    type_for_node = {}
    for node in _walk(root, _TYPE_NODES):
        name_node = node.child_by_field_name("name")
        if not name_node:
            continue
        name = _text(source, name_node)
        unit = _matching_unit(units, source, node, name)
        if not unit:
            continue
        owner_node = next((parent for parent in _walk(root, _TYPE_NODES)
                           if parent is not node and parent.start_byte < node.start_byte
                           and node.end_byte < parent.end_byte), None)
        owner_name = _text(source, owner_node.child_by_field_name("name")) if owner_node else None
        fqname = ".".join(filter(None, [package, owner_name, name]))
        if node.type == "interface_declaration":
            # Interfaces list parents under extends_interfaces, not the interfaces field.
            base_nodes = _heritage_nodes(next(_children(node, {"extends_interfaces"}), None))
            interface_nodes = []
        else:
            base_nodes = _heritage_nodes(node.child_by_field_name("superclass"))
            interface_nodes = _heritage_nodes(node.child_by_field_name("interfaces"))
        bases = [_type_text(source, item) for item in base_nodes]
        implemented = [_type_text(source, item) for item in interface_nodes]
        entry = {"node": node, "unit": unit, "name": name, "fqname": fqname,
                 "kind": node.type, "bases": bases, "interfaces": implemented,
                 "type_parameters": _type_parameters(source, node),
                 "annotations": _annotations(source, node), "fields": {},
                 "field_units": [], "methods": []}
        unit.semantic_identity = fqname
        unit.semantic_kind = "interface" if node.type == "interface_declaration" else "type"
        unit.semantic_annotations = entry["annotations"]
        unit.semantic_type = entry
        info["types"].append(entry)
        type_for_node[id(node)] = entry
    for node in _walk(root, _METHOD_NODES):
        name_node = node.child_by_field_name("name")
        if not name_node:
            continue
        name = _text(source, name_node)
        unit = _matching_unit(units, source, node, name)
        if not unit:
            continue
        owner = min((item for item in info["types"] if item["node"].start_byte < node.start_byte
                     and node.end_byte < item["node"].end_byte),
                    key=lambda item:item["node"].end_byte-item["node"].start_byte, default=None)
        params = _parameters(source, node)
        return_node = node.child_by_field_name("type")
        if return_node is None and node.type == "method_declaration":
            return_node = next(_children(node, {"type_identifier", "generic_type", "void_type",
                                                "integral_type", "floating_point_type", "boolean_type"}), None)
        return_type = _type_text(source, return_node)
        owner_fq = owner["fqname"] if owner else info["package"]
        signature = ",".join(value for _, value in params)
        unit.owner = owner["name"] if owner else unit.owner
        unit.params = params
        unit.qualified = source.path + "::" + ".".join(filter(None, [unit.owner, name])) + f"({signature})"
        unit.semantic_identity = f"{owner_fq}.{name}({signature})"
        unit.semantic_annotations = _annotations(source, node)
        modifiers = next(_children(node, {"modifiers"}), None)
        modifier_text = _text(source, modifiers) if modifiers else ""
        if owner and owner["kind"] == "interface_declaration":
            unit.trace_role = "interface"
        elif not unit.executable_body:
            unit.trace_role = "abstract_declaration" if re.search(r"\babstract\b", modifier_text) else "declaration"
        else:
            unit.trace_role = "implementation"
        declare_trace_contract(unit, unit.trace_role)
        method = {"node": node, "unit": unit, "name": name, "owner": owner,
                  "params": params, "return_type": return_type,
                  "type_parameters": _type_parameters(source, node),
                  "annotations": unit.semantic_annotations, "variables": dict(params),
                  "invocations": []}
        unit.semantic_method = method
        info["methods"].append(method)
        if owner:
            owner["methods"].append(method)
    for type_info in info["types"]:
        body = type_info["node"].child_by_field_name("body")
        if not body:
            continue
        for field in _children(body, {"field_declaration"}):
            type_node = field.child_by_field_name("type")
            if type_node is None:
                type_node = next(_children(field, {"type_identifier", "generic_type", "integral_type",
                                                    "floating_point_type", "boolean_type"}), None)
            for declarator in _children(field, {"variable_declarator"}):
                name_node = declarator.child_by_field_name("name")
                if name_node:
                    field_name = _text(source, name_node)
                    field_type = _type_text(source, type_node)
                    type_info["fields"][field_name] = field_type
                    field_unit = Unit(
                        source, field_name,
                        source.path + "::" + type_info["name"] + "." + field_name,
                        _char(source, field.start_byte), _char(source, field.end_byte),
                        "field", owner=type_info["name"],
                    )
                    field_unit.semantic_identity = type_info["fqname"] + "." + field_name
                    field_unit.semantic_declared_type = field_type
                    units.append(field_unit)
                    type_info["field_units"].append(field_unit)
    for method in info["methods"]:
        variables = {**(method["owner"]["fields"] if method["owner"] else {}), **method["variables"]}
        for name, written in _local_declarations(source, method["node"]).items():
            variables[name] = written
        for call in _walk(method["node"], {"method_invocation"}):
            name_node = call.child_by_field_name("name")
            object_node = call.child_by_field_name("object")
            args_node = call.child_by_field_name("arguments")
            named_args = list(_children(args_node)) if args_node else []
            invocation = {
                "receiver": _text(source, object_node) if object_node else None,
                "receiver_node": object_node,
                "name": _text(source, name_node) if name_node else "",
                "position": _char(source, call.start_byte)-method["unit"].start,
                "end": _char(source, call.end_byte)-method["unit"].start,
                "argument_types": [_literal_type(source, item, variables) for item in named_args],
                "variables": variables,
                "method": method,
            }
            method["invocations"].append(invocation)
            info["invocations"].append(invocation)
    source.semantic = info
    return info


# Used when a local name is declared with conflicting types; block scope isn't tracked.
_UNKNOWN_LOCAL_TYPE = "<unknown local type>"


def _local_declarations(source, node):
    """Map each local name in a method body to its written type.

    Covers locals, enhanced-for, try-with-resources and catch parameters. Names with
    conflicting types and multi-catch parameters map to _UNKNOWN_LOCAL_TYPE.
    """
    found = {}

    def declare(name_node, written):
        if name_node is None or not written:
            return
        name = _text(source, name_node)
        found.setdefault(name, set()).add(written)

    for local in _walk(node, {"local_variable_declaration"}):
        written = _type_text(source, local.child_by_field_name("type"))
        for declarator in _children(local, {"variable_declarator"}):
            declare(declarator.child_by_field_name("name"), written)
    for item in _walk(node, {"enhanced_for_statement", "resource"}):
        type_node = item.child_by_field_name("type")
        if type_node is not None:
            declare(item.child_by_field_name("name"), _type_text(source, type_node))
    for parameter in _walk(node, {"catch_formal_parameter"}):
        catch_type = next(iter(_children(parameter, {"catch_type"})), None)
        written = _text(source, catch_type) if catch_type is not None else None
        declare(parameter.child_by_field_name("name"),
                _UNKNOWN_LOCAL_TYPE if written and "|" in written else written)
    return {name: next(iter(types)) if len(types) == 1 else _UNKNOWN_LOCAL_TYPE
            for name, types in found.items()}


def extract(source):
    units = rules.extract(source)
    _parse(source, units)
    return units


def _resolve_type(source, raw, types_by_fq, types_by_short):
    name = re.sub(r"<.*>", "", raw or "").replace("[]", "").strip()
    simple = _simple(name)
    candidates = []
    if "." in name and name in types_by_fq:
        candidates = [types_by_fq[name]]
    elif simple in source.semantic["imports"]:
        target = source.semantic["imports"][simple]
        candidates = [types_by_fq[target]] if target in types_by_fq else []
        if not candidates:
            # Missing project types are unresolved; anything else is an external dependency.
            local = any(target.startswith(namespace + ".")
                        for namespace in source.semantic.get("local_namespaces", ()))
            return ("unresolved" if local else "external"), []
    else:
        same = ".".join(filter(None, [source.semantic["package"], simple]))
        if same in types_by_fq:
            candidates = [types_by_fq[same]]
        else:
            candidates = [entry for entry in types_by_short.get(simple, [])
                          if any(entry["fqname"].startswith(prefix + ".")
                                 for prefix in source.semantic["wildcards"])]
    if len(candidates) == 1:
        return "resolved", candidates
    if len(candidates) > 1:
        return "ambiguous", sorted(candidates, key=lambda item:item["fqname"])[:8]
    if name in (simple, f"java.lang.{simple}") and simple in _java_lang():
        return "external", []
    if _TYPE_NAME.fullmatch(name) and _external_wildcards(source, simple, types_by_short):
        return "external", []
    return "unresolved", []


# Conventional Java type name: capitalized, with at least one lowercase letter
# (excludes ALL_CAPS constants).
_TYPE_NAME = re.compile(r"[A-Z](?=[A-Za-z0-9_]*[a-z])[A-Za-z0-9_]*")


# Receivers typed by their expression rather than by a name.
_EXPRESSION_RECEIVERS = frozenset({"method_invocation", "object_creation_expression",
                                   "parenthesized_expression", "cast_expression",
                                   "string_literal"})
_PRIMITIVES = frozenset({"void", "boolean", "byte", "char", "short", "int", "long",
                         "float", "double"})
_MAX_CHAIN = 8


@lru_cache(maxsize=1)
def _library_signatures():
    path = Path(__file__).parents[1] / "data" / "library_signatures.json"
    return json.loads(path.read_text()).get("java", {})


def _library_return(qualified, name, count):
    """Return the catalogued return type of a library method, or None."""
    methods = _library_signatures().get(re.sub(r"<.*>", "", qualified), {})
    return methods.get(f"{name}/{count}") or methods.get(f"{name}/*")


def _java_lang():
    """Return the simple names implicitly imported from ``java.lang``."""
    return registry.ambient_globals("java")


def _external_wildcards(source, simple, types_by_short):
    """Return the external wildcard imports a simple type name must come from.

    Returns [] if any wildcard import is local or an analyzed type has that name.
    """
    wildcards = source.semantic["wildcards"]
    if not wildcards or types_by_short.get(simple):
        return []
    namespaces = source.semantic.get("local_namespaces", ())
    if any(prefix == namespace or prefix.startswith(namespace + ".")
           or namespace.startswith(prefix + ".") for prefix in wildcards
           for namespace in namespaces):
        return []
    return sorted(wildcards)


def _external_provider(source, raw, types_by_short):
    """Return ``type:<qualified name>`` for an external receiver type, or None."""
    name = re.sub(r"<.*>", "", raw or "").replace("[]", "").strip()
    simple = _simple(name)
    if "." in name and name[0].islower():
        return f"type:{name}"
    if simple in source.semantic["imports"]:
        return f"type:{source.semantic['imports'][simple]}"
    if simple in _java_lang():
        return f"type:java.lang.{simple}"
    wildcards = (_external_wildcards(source, simple, types_by_short)
                 if _TYPE_NAME.fullmatch(name) else [])
    # With several wildcard packages, the catalog decides whether all are known libraries.
    return ("type:" + "|".join(f"{package}.{simple}" for package in wildcards)
            if wildcards else None)


def _generated_model(source, raw):
    """Return ``(config, qualified name)`` if *raw* is a generated model type, else None.

    Requires an explicit import from the model package, or a single matching
    wildcard import plus the configured name prefix/suffix.
    """
    name = re.sub(r"<.*>", "", raw or "").replace("[]", "").strip()
    simple = _simple(name)
    configs = [config for config in getattr(source, "generated_source_config", ())
               if config.get("model_package")]
    imported = source.semantic["imports"].get(simple)
    if imported:
        found = [config for config in configs
                 if imported.rsplit(".", 1)[0] == config["model_package"]]
        return (found[0], imported) if len(found) == 1 else None
    found = [config for config in configs
             if config["model_package"] in source.semantic["wildcards"]
             and (config.get("model_name_suffix") or config.get("model_name_prefix"))
             and simple.startswith(config.get("model_name_prefix") or "")
             and simple.endswith(config.get("model_name_suffix") or "")
             and len(simple) > len((config.get("model_name_prefix") or "")
                                   + (config.get("model_name_suffix") or ""))]
    if len(found) != 1:
        return None
    return found[0], f"{found[0]['model_package']}.{simple}"


def _generated_model_relation(kind, raw, generated):
    """Return the reason and evidence for a relation to a generated model type."""
    config, qualified = generated
    simple = qualified.rsplit(".", 1)[-1]
    prefix = config.get("model_name_prefix") or ""
    suffix = config.get("model_name_suffix") or ""
    schema_name = simple[len(prefix):len(simple) - len(suffix) if suffix else None]
    schema = config.get("schemas", {}).get(schema_name)
    evidence = [config["generator_evidence"]] if config.get("generator_evidence") else []
    if schema:
        evidence.append(schema)
        origin = (f"from OpenAPI schema {schema_name} in {schema[0].path}")
    else:
        origin = "from an OpenAPI schema that could not be matched"
    return (f"Java {kind} target {raw} is the generated DTO {qualified}, which "
            f"openapi-generator-maven-plugin produces at build time {origin}; its "
            "declaration is unavailable at analysis time."), evidence


def _generated_model_type(unit):
    """Build a type entry for a generated model class and its accessors."""
    entry = {"node": None, "unit": unit, "name": unit.name, "fqname": unit.generated_model_name,
             "kind": "class_declaration", "bases": [], "interfaces": [], "type_parameters": [],
             "annotations": [], "fields": {}, "field_units": [], "methods": []}
    for accessor in getattr(unit, "generated_accessors", ()):
        method = {"node": None, "unit": accessor, "name": accessor.name, "owner": entry,
                  "params": list(accessor.params), "return_type": accessor.generated_return_type,
                  "type_parameters": [], "annotations": [], "variables": dict(accessor.params),
                  "invocations": []}
        entry["methods"].append(method)
    return entry


def _qualified_type(source, raw, types_by_fq, types_by_short):
    """Return the fully qualified name of *raw* in *source*, or None."""
    if not hasattr(source, "semantic"):
        # Generated declarations use fully qualified project types.
        name = re.sub(r"<.*>", "", raw or "").replace("[]", "").strip()
        return name if name in types_by_fq else None
    state, matches = _resolve_type(source, raw, types_by_fq, types_by_short)
    if state == "resolved":
        return matches[0]["fqname"]
    imported = source.semantic["imports"].get(_simple(re.sub(r"<.*>", "", raw or "")))
    if imported:
        return imported
    generated = _generated_model(source, raw)
    return generated[1] if generated else None


def _same_type(argument_source, argument, parameter_source, parameter,
               types_by_fq, types_by_short):
    """Return True if both types resolve to the same fully qualified name."""
    if (argument or "").count("[]") != (parameter or "").count("[]"):
        return False
    left = _qualified_type(argument_source, argument, types_by_fq, types_by_short)
    right = _qualified_type(parameter_source, parameter, types_by_fq, types_by_short)
    return left is not None and left == right


# Primitives, their boxes, String and void. Widening order per JLS 5.1.2.
BOXED_PRIMITIVES = {
    "Integer": "int", "Long": "long", "Double": "double", "Float": "float",
    "Short": "short", "Byte": "byte", "Boolean": "boolean", "Character": "char",
}
WIDENING_ORDER = ("byte", "short", "int", "long", "float", "double")
SCALAR_TYPES = (frozenset(BOXED_PRIMITIVES)
                | frozenset(BOXED_PRIMITIVES.values())
                | {"String", "void"})


def _unboxed(name):
    return BOXED_PRIMITIVES.get(name, name)


def _assignable(argument, parameter):
    """Return True/False for scalar type compatibility, None if it can't be judged.

    Reference types always return None so they never veto a call.
    """
    # _simple drops array depth, so check it first (f(int) vs f(int[])).
    if (argument or "").count("[]") != (parameter or "").count("[]"):
        return False
    left, right = _simple(argument), _simple(parameter)
    if left in {"unknown", "null"}:
        return None
    if left not in SCALAR_TYPES or right not in SCALAR_TYPES:
        return None
    if left == right:
        return True
    left, right = _unboxed(left), _unboxed(right)
    if left == right:
        return True
    if left in WIDENING_ORDER and right in WIDENING_ORDER:
        return WIDENING_ORDER.index(left) <= WIDENING_ORDER.index(right)
    if left == "char" and right in WIDENING_ORDER:
        return WIDENING_ORDER.index("int") <= WIDENING_ORDER.index(right)
    return False


def _local_namespaces(java_sources):
    """Return the package namespaces that belong to this project.

    Includes each root package, its parent when that has two or more segments,
    build groupIds and generator output packages.
    """
    declared = {source.semantic["package"] for source in java_sources
                if source.semantic.get("package")}
    roots = {package for package in declared
             if not any(package.startswith(other + ".") for other in declared)}
    namespaces = set(roots)
    namespaces.update(root.rsplit(".", 1)[0] for root in roots if root.count(".") >= 2)
    for source in java_sources:
        namespaces.update(getattr(source, "build_namespaces", ()))
        for config in getattr(source, "generated_source_config", ()):
            namespaces.update(filter(None, (config.get("api_package"),
                                            config.get("model_package"))))
    return tuple(sorted(namespaces))


def _implementation_relations(java_sources, types_by_fq, types_by_short, diagnostics):
    """Add selects_implementation relations from interface/abstract methods to concrete ones.

    Matches by name and erased parameter types after type-argument substitution,
    falling back to inherited default methods. Static, private and test-source
    methods are skipped. Several matches make the relation ambiguous.
    """
    test_path = re.compile(CATALOG["test_path_pattern"])
    source_of = {id(entry): source for source in java_sources
                 for entry in source.semantic["types"]}
    entries = {id(entry): entry for source in java_sources
               for entry in source.semantic["types"]}

    def parents_of(entry):
        source = source_of[id(entry)]
        found = []
        for name in entry["bases"] + entry["interfaces"]:
            state, matches = _resolve_type(source, name, types_by_fq, types_by_short)
            if state == "resolved" and id(matches[0]) in entries and matches[0] is not entry:
                found.append((matches[0], _type_arguments(name)))
        return found

    parents = {key: parents_of(entry) for key, entry in entries.items()}
    children = defaultdict(list)
    for key, found in parents.items():
        for parent, _ in found:
            children[id(parent)].append(entries[key])

    def descendants(entry):
        seen, queue, found = {id(entry)}, [(entry, 0)], []
        while queue:
            current, depth = queue.pop(0)
            if depth >= _MAX_HERITAGE_DEPTH:
                continue
            for child in children.get(id(current), ()):
                if id(child) not in seen:
                    seen.add(id(child))
                    found.append(child)
                    queue.append((child, depth + 1))
        return found

    def parameterized(parent, arguments, context):
        """Map *parent*'s type parameters to the arguments supplied by the subtype.

        Raw or mismatched arguments fall back to the declared bounds (erasure).
        """
        declared = list(parent.get("type_parameters", {}).items())
        if (arguments is None or len(arguments) != len(declared)
                or any(argument.startswith("?") for argument in arguments)):
            return dict(declared)
        return {name: _substitute(argument, context)
                for (name, _), argument in zip(declared, arguments)}

    supertype_cache = {}

    def supertypes(entry):
        """Return (supertype, type-argument mapping) pairs for *entry*, nearest first."""
        cached = supertype_cache.get(id(entry))
        if cached is not None:
            return cached
        found, seen, queue = [], {id(entry)}, [(entry, {}, 0)]
        while queue:
            current, context, depth = queue.pop(0)
            if depth >= _MAX_HERITAGE_DEPTH:
                continue
            for parent, arguments in parents.get(id(current), ()):
                if id(parent) not in seen:
                    seen.add(id(parent))
                    mapping = parameterized(parent, arguments, context)
                    found.append((parent, mapping))
                    queue.append((parent, mapping, depth + 1))
        supertype_cache[id(entry)] = found
        return found

    def signature(method, mapping, scope):
        """Return the method name and erased parameter types as seen from *scope*.

        The method's own type variables shadow *mapping* and erase to their bounds.
        """
        own = method.get("type_parameters", {})
        visible = {name: value for name, value in mapping.items() if name not in own}
        variables = {**scope.get("type_parameters", {}),
                     **{name: _substitute(bound, visible) for name, bound in own.items()}}
        return method["name"], tuple(_erased(_substitute(value, visible), variables)
                                     for _, value in method["params"])

    def concrete_method(entry, wanted):
        """Return the concrete method *entry* runs for *wanted*, searching superclasses."""
        chain = [(entry, {})] + [(parent, mapping) for parent, mapping in supertypes(entry)
                                 if parent["kind"] in _CONCRETE_TYPE_KINDS]
        for owner, mapping in chain:
            for method in owner["methods"]:
                unit = method["unit"]
                if (unit.trace_role == "implementation" and unit.executable_body
                        and not _keyword_modifiers(method["node"]) & {"static", "private"}
                        and signature(method, mapping, entry) == wanted):
                    return unit
        return None

    def inherited_default(entry, wanted):
        """Return the nearest inherited interface ``default`` method matching *wanted*."""
        for owner, mapping in supertypes(entry):
            if owner["kind"] != "interface_declaration":
                continue
            for method in owner["methods"]:
                unit = method["unit"]
                if (unit.executable_body and "default" in _keyword_modifiers(method["node"])
                        and signature(method, mapping, entry) == wanted):
                    return unit
        return None

    def mapstruct_evidence(source, entry):
        """Return (annotation, processor) if MapStruct generates *entry*, else None."""
        annotation = next((item for item in entry["annotations"]
                           if _annotation_type(source, item) == _MAPSTRUCT_MAPPER), None)
        processor = next((item for item in getattr(source, "build_processors", ())
                          if item[3:5] == _MAPSTRUCT_PROCESSOR), None)
        return (annotation, processor) if annotation and processor else None

    for source in java_sources:
        if test_path.search(source.path):
            continue
        for entry in source.semantic["types"]:
            generated = mapstruct_evidence(source, entry)
            if generated and any(declaration["unit"].trace_role in _DISPATCH_ROLES
                                 and not declaration["unit"].executable_body
                                 for declaration in entry["methods"]):
                diagnostics.append({"code": "JAVA_GENERATED_IMPLEMENTATION",
                    "message": f"MapStruct generates the implementation of {entry['fqname']} "
                               "at build time; it is not in the analyzed source snapshot.",
                    "subject_ids": [source.resource_id], "evidence_ids": []})
            for declaration in entry["methods"]:
                base = declaration["unit"]
                if base.trace_role not in _DISPATCH_ROLES:
                    continue
                if generated and not base.executable_body:
                    # Implementation is only in build output; point at an external resource.
                    annotation, (build_source, start, end, group, artifact) = generated
                    source.semantic_relations.append({
                        "source": base, "target": None, "candidate_targets": [],
                        "kind": "selects_implementation", "start": base.start, "end": base.end,
                        "resolution": "unresolved", "outcome": "external",
                        "diagnostic_code": "JAVA_GENERATED_IMPLEMENTATION",
                        "external_target_id": identifier(
                            "resource", "generated-implementation", "mapstruct", entry["fqname"]),
                        "reason": (f"MapStruct generates the implementation of {base.semantic_identity} "
                                   f"at build time ({annotation['text'].split('(', 1)[0]} with "
                                   f"annotation processor {group}:{artifact}); it is not in the "
                                   "analyzed source snapshot."),
                        "evidence_spans": [(source, annotation["start"], annotation["end"]),
                                           (build_source, start, end)],
                    })
                found = {}
                for descendant in descendants(entry):
                    if (descendant["kind"] not in _CONCRETE_TYPE_KINDS
                            or test_path.search(source_of[id(descendant)].path)):
                        continue
                    # Substitute the descendant's type arguments into the declaration.
                    mapping = next((mapping for parent, mapping in supertypes(descendant)
                                    if parent is entry), {})
                    wanted = signature(declaration, mapping, descendant)
                    # Prefer a concrete method; fall back to an inherited default.
                    unit = (concrete_method(descendant, wanted)
                            or inherited_default(descendant, wanted))
                    if unit is not None:
                        found[id(unit)] = unit
                implementations = sorted(found.values(), key=lambda unit: unit.qualified)
                if not implementations:
                    continue
                kept = implementations[:MAX_SEMANTIC_CANDIDATES]
                relation = {"source": base, "kind": "selects_implementation",
                            "start": base.start, "end": base.end,
                            "evidence_spans": [(unit.source, unit.start, unit.end) for unit in kept]}
                if len(implementations) == 1:
                    relation.update(target=implementations[0], candidate_targets=implementations,
                                    resolution="resolved", outcome="exact", reason=None)
                else:
                    reason = (f"{len(implementations)} concrete methods implement "
                              f"{base.semantic_identity}; which one runs is not established "
                              "statically.")
                    if len(implementations) > len(kept):
                        reason += f" The first {len(kept)} are retained as candidates."
                    relation.update(target=None, candidate_targets=kept,
                                    resolution="ambiguous", outcome="ambiguous",
                                    diagnostic_code="JAVA_IMPLEMENTATION_AMBIGUOUS", reason=reason)
                    diagnostics.append({"code": "JAVA_IMPLEMENTATION_AMBIGUOUS", "message": reason,
                                        "subject_ids": [source.resource_id], "evidence_ids": []})
                source.semantic_relations.append(relation)


def prepare(sources, units, diagnostics=None):
    diagnostics = diagnostics if diagnostics is not None else []
    java_sources = [source for source in sources if hasattr(source, "semantic")]
    namespaces = _local_namespaces(java_sources)
    for source in java_sources:
        source.semantic["local_namespaces"] = namespaces
    types = [entry for source in java_sources for entry in source.semantic["types"]]
    types.extend({unit.generated_interface_name: {
        "node": None, "unit": unit, "name": unit.name,
        "fqname": unit.generated_interface_name,
        "kind": "interface_declaration", "bases": [], "interfaces": [],
        "annotations": [], "fields": {}, "field_units": [], "methods": [],
    } for unit in units if getattr(unit, "generated_interface_name", None)}.values())
    types.extend(_generated_model_type(unit) for unit in
                 {unit.generated_model_name: unit for unit in units
                  if getattr(unit, "generated_model_name", None)}.values())
    types_by_fq = {entry["fqname"]: entry for entry in types}
    types_by_short = defaultdict(list)
    for entry in types:
        types_by_short[entry["name"]].append(entry)
    methods_by_owner = defaultdict(list)
    for entry in types:
        methods_by_owner[entry["fqname"]].extend(entry["methods"])
    declaring_source = {id(entry): source for source in java_sources
                        for entry in source.semantic["types"]}
    reachable = {}

    def typed_state(context, written):
        """Return ``(state, owners, provider)`` for a written type.

        A None *context* means *written* is already fully qualified (catalog types).
        """
        if context is not None:
            state, owners = _resolve_type(context, written, types_by_fq, types_by_short)
            return state, owners, (_external_provider(context, written, types_by_short)
                                   if state == "external" else None)
        name = re.sub(r"<.*>", "", written)
        if name in types_by_fq:
            return "resolved", [types_by_fq[name]], None
        if name in _PRIMITIVES or any(name.startswith(namespace + ".")
                                      for namespace in namespaces):
            return "unresolved", [], None
        return "external", [], f"type:{name}"

    def expression_type(source, method, node, variables, depth=0):
        """Return ``(context, written type)`` for a receiver expression, or None.

        Method calls use the declared or catalogued return type; generic,
        uncatalogued or conflicting return types give None.
        """
        if node is None or depth > _MAX_CHAIN:
            return None
        kind = node.type
        if kind == "parenthesized_expression":
            return expression_type(source, method, next(_children(node), None), variables, depth + 1)
        if kind == "string_literal":
            return None, "java.lang.String"
        if kind in {"object_creation_expression", "cast_expression"}:
            written = node.child_by_field_name("type")
            return (source, _type_text(source, written)) if written is not None else None
        if kind == "identifier":
            name = _text(source, node)
            return source, variables.get(name, name)
        if kind == "field_access":
            target, field = node.child_by_field_name("object"), node.child_by_field_name("field")
            if target is not None and target.type in {"this", "super"} and field is not None:
                written = variables.get(_text(source, field))
                return (source, written) if written else None
            return None
        if kind != "method_invocation":
            return None
        target = node.child_by_field_name("object")
        name = _text(source, node.child_by_field_name("name"))
        arguments = node.child_by_field_name("arguments")
        count = len(list(_children(arguments))) if arguments is not None else 0
        if target is None:
            if not method["owner"]:
                return None
            state, owners, provider = "resolved", [method["owner"]], None
        else:
            typed = expression_type(source, method, target, variables, depth + 1)
            if typed is None:
                return None
            state, owners, provider = typed_state(*typed)
        if state == "resolved" and len(owners) == 1:
            found = [candidate for candidate in callable_methods(owners[0])
                     if candidate["name"] == name and len(candidate["params"]) == count]
            returns = {(id(candidate["unit"].source), candidate["return_type"]) for candidate in found}
            if not found:
                # Fall back to java.lang.Object members.
                inherited = _library_return("java.lang.Object", name, count)
                return (None, inherited) if inherited and inherited not in _PRIMITIVES else None
            if len(returns) != 1:
                return None
            chosen = found[0]
            written = chosen["return_type"]
            generic = {parameter if isinstance(parameter, str) else parameter[0]
                       for parameter in chosen.get("type_parameters") or ()}
            if (not written or written in _PRIMITIVES
                    or re.sub(r"<.*>|\[\]", "", written) in generic):
                return None
            declaring = chosen["unit"].source
            if getattr(declaring, "semantic", None):
                return declaring, written
            # Generated declarations have no imports; only qualified or java.lang names resolve.
            if "." in written:
                return None, written
            simple = re.sub(r"<.*>", "", written)
            return (None, f"java.lang.{written}") if simple in _java_lang() else None
        if state == "external" and provider:
            returns = {_library_return(candidate, name, count)
                       for candidate in provider.split(":", 1)[1].split("|")}
            if len(returns) == 1:
                written = returns.pop()
                if written and written not in _PRIMITIVES:
                    return None, written
        return None

    def callable_methods(owner):
        """Return methods callable on *owner*, nearest first, with overridden ones hidden."""
        if id(owner) in reachable:
            return reachable[id(owner)]
        found, signatures = [], set()
        seen, level = {id(owner)}, [owner]
        for _ in range(_MAX_HERITAGE_DEPTH + 1):
            parents = []
            for entry in level:
                for method in methods_by_owner[entry["fqname"]]:
                    signature = (method["name"],
                                 tuple(_erased(value, {}) for _, value in method["params"]))
                    if signature not in signatures:
                        signatures.add(signature)
                        found.append(method)
                source = declaring_source.get(id(entry))
                for name in (entry["bases"] + entry["interfaces"]) if source else ():
                    state, matches = _resolve_type(source, name, types_by_fq, types_by_short)
                    if state == "resolved" and id(matches[0]) not in seen:
                        seen.add(id(matches[0]))
                        parents.append(matches[0])
            if not parents:
                break
            level = parents
        reachable[id(owner)] = found
        return found
    for source in java_sources:
        source.semantic_relations = []
        source.semantic_results = []
        for origin in source.semantic["types"]:
            for member in [item["unit"] for item in origin["methods"]] + origin["field_units"]:
                source.semantic_relations.append({
                    "source": origin["unit"], "target": member,
                    "candidate_targets": [member], "kind": "declares",
                    "start": member.start, "end": member.end,
                    "resolution": "resolved", "reason": None,
                })
            for field in origin["field_units"]:
                source.semantic_relations.append({
                    "source": origin["unit"], "target": field,
                    "candidate_targets": [field], "kind": "has_field",
                    "start": field.start, "end": field.end,
                    "resolution": "resolved", "reason": None,
                })
            for kind, names in (("inherits", origin["bases"]), ("implements", origin["interfaces"])):
                for name in names:
                    state, matches = _resolve_type(source, name, types_by_fq, types_by_short)
                    result_code = ("JAVA_TYPE_AMBIGUOUS" if state == "ambiguous" else
                                   "JAVA_EXTERNAL_TYPE" if state == "external" else
                                   "JAVA_TYPE_DECLARATION_UNAVAILABLE")
                    relation = {"source": origin["unit"],
                        "target": matches[0]["unit"] if state == "resolved" else None,
                        "candidate_targets": [item["unit"] for item in matches], "kind": kind,
                        "start": _char(source, origin["node"].start_byte),
                        "end": _char(source, origin["node"].end_byte),
                        "resolution": "resolved" if state == "resolved" else
                                      "ambiguous" if state == "ambiguous" else "unresolved",
                        "outcome": "exact" if state == "resolved" else state,
                        "diagnostic_code": None if state == "resolved" else result_code,
                        "external_target_id": identifier('resource', 'java-external-type',
                            source.semantic["imports"].get(_simple(name), name)) if state == "external" else None,
                        "reason": None if state == "resolved" else
                            f"Java {kind} target {name} is {state}; semantic candidates: " +
                            (", ".join(item["fqname"] for item in matches) if matches else "none")}
                    source.semantic_relations.append(relation)
                    if state != "resolved":
                        diagnostics.append({"code": result_code,
                            "message": relation["reason"], "subject_ids": [source.resource_id], "evidence_ids": []})
        for method in source.semantic["methods"]:
            typed = [("accepts_type", value) for _, value in method["params"]]
            typed.append(("returns_type", method["return_type"]))
            for kind, type_name in typed:
                if not type_name or _simple(type_name) in {"void", "unknown"}:
                    continue
                state, matches = _resolve_type(source, type_name, types_by_fq, types_by_short)
                target = matches[0]["unit"] if state == "resolved" else None
                external = state == "external"
                generated = _generated_model(source, type_name) if state == "unresolved" else None
                reason, evidence_spans = (_generated_model_relation(kind, type_name, generated)
                    if generated else (f"Java {kind} target {type_name} is {state}.", []))
                source.semantic_relations.append({
                    "source": method["unit"], "target": target,
                    "candidate_targets": [item["unit"] for item in matches],
                    "kind": kind, "start": method["unit"].start,
                    "end": method["unit"].end,
                    "resolution": "resolved" if state == "resolved" or external else
                                  "ambiguous" if state == "ambiguous" else "unresolved",
                    "outcome": "exact" if state == "resolved" else state,
                    "diagnostic_code": None if state == "resolved" else
                        "JAVA_EXTERNAL_TYPE" if external else
                        "JAVA_TYPE_AMBIGUOUS" if state == "ambiguous" else
                        "JAVA_TYPE_DECLARATION_UNAVAILABLE",
                    "external_target_id": identifier(
                        "resource", "java-type", source.semantic["imports"].get(
                            _simple(type_name), _simple(type_name))) if external else None,
                    "reason": None if state == "resolved" else reason,
                    "evidence_spans": evidence_spans,
                })
        for method in source.semantic["methods"]:
            for invocation in method["invocations"]:
                receiver = invocation["receiver"]
                # Strip this./super. so field receivers match keys in `variables`.
                bare = receiver
                if receiver and receiver.split(".")[0] in {"this", "super"}:
                    bare = receiver.split(".", 1)[1] if "." in receiver else None
                owner_states = []
                node = invocation.get("receiver_node")
                if node is not None and node.type in _EXPRESSION_RECEIVERS:
                    # Chained call: type the receiver expression.
                    typed = expression_type(source, method, node, invocation["variables"])
                    state, owners, provider = (typed_state(*typed) if typed
                                               else ("unresolved", [], None))
                    invocation["provider"] = provider if state == "external" else None
                else:
                    if bare is None and method["owner"]:
                        owner_states = [("resolved", [method["owner"]])]
                    elif bare:
                        raw_type = invocation["variables"].get(bare, bare)
                        owner_states = [_resolve_type(source, raw_type, types_by_fq, types_by_short)]
                    state, owners = owner_states[0] if owner_states else ("unresolved", [])
                    invocation["provider"] = (_external_provider(
                        source, invocation["variables"].get(bare, bare), types_by_short)
                        if state == "external" and bare else None)
                candidates = [candidate for owner in owners for candidate in callable_methods(owner)
                              if candidate["name"] == invocation["name"]
                              and len(candidate["params"]) == len(invocation["argument_types"])]
                if (state == "resolved" and not candidates and owners
                        and _library_return("java.lang.Object", invocation["name"],
                                            len(invocation["argument_types"]))):
                    # Not redeclared, so it's an inherited java.lang.Object method.
                    state, owners = "external", []
                    invocation["provider"] = "type:java.lang.Object"
                # An exact parameter match always wins Java overload resolution.
                identical = [candidate for candidate in candidates if all(
                    (_simple(argument) in SCALAR_TYPES
                     and argument.count("[]") == parameter[1].count("[]")
                     and _simple(argument) == _simple(parameter[1]))
                    or _same_type(source, argument, candidate["unit"].source, parameter[1],
                                  types_by_fq, types_by_short)
                    for argument, parameter in zip(invocation["argument_types"], candidate["params"]))]
                exact = (identical if len(identical) == 1 else
                         [candidate for candidate in candidates if all(
                             _assignable(argument, parameter[1]) is True
                             for argument, parameter in zip(invocation["argument_types"],
                                                            candidate["params"]))])
                # Plausible = no argument is provably incompatible (None doesn't veto).
                plausible = [candidate for candidate in candidates if not any(
                    _assignable(argument, parameter[1]) is False
                    for argument, parameter in zip(invocation["argument_types"], candidate["params"]))]
                if len(exact) == 1:
                    candidates, state = exact, "resolved"
                elif len(exact) > 1:
                    candidates, state = exact[:8], "ambiguous"
                elif len(plausible) == 1:
                    candidates, state = plausible, "resolved"
                elif len(plausible) > 1:
                    candidates, state = sorted(plausible, key=lambda item:item["unit"].semantic_identity)[:8], "ambiguous"
                elif len(candidates) > 1:
                    candidates, state = sorted(candidates, key=lambda item:item["unit"].semantic_identity)[:8], "ambiguous"
                elif state == "resolved":
                    candidates, state = [], "unresolved"
                invocation["state"] = state
                invocation["candidates"] = [candidate["unit"] for candidate in candidates]
                call_reason = f"Java call {invocation['name']} is {state}; candidates: " + (
                    ", ".join(item.semantic_identity for item in invocation["candidates"])
                    if invocation["candidates"] else "none")
                call_code = ("JAVA_CALL_AMBIGUOUS" if state == "ambiguous" else
                             "JAVA_EXTERNAL_CALL" if state == "external" else
                             "JAVA_CALL_UNRESOLVED")
                if state in {"ambiguous", "external"}:
                    diagnostics.append({"code": call_code, "message": call_reason,
                        "subject_ids": [source.resource_id], "evidence_ids": []})
    # Must run after all sources are rebuilt; relations land in the declaring source.
    _implementation_relations(java_sources, types_by_fq, types_by_short, diagnostics)
    # Stored per source for candidate resolution, avoiding module-level state.
    for source in java_sources:
        source.semantic_types_by_fq = types_by_fq
        source.semantic_types_by_short = types_by_short


def calls(unit):
    method = getattr(unit, "semantic_method", None)
    if not method:
        return []
    return [{key:item[key] for key in ("receiver", "name", "position", "end")}
            for item in method["invocations"]]


def resolve_call(unit, receiver, name, candidates, position, evidence_id=None):
    """Return the shared semantic result after Java-owned overload resolution."""
    method = getattr(unit, "semantic_method", None)
    invocation = next((item for item in method["invocations"]
                       if item["receiver"] == receiver and item["name"] == name
                       and item["position"] == position), None) if method else None
    state = invocation.get("state", "unresolved") if invocation else "unresolved"
    outcome = "exact" if state == "resolved" and len(candidates) == 1 else (
        "ambiguous" if state == "ambiguous" else
        "external" if state == "external" else "unresolved")
    reason = None if outcome == "exact" else f"Java call {name} is {outcome}; candidates: " + (
        ", ".join(candidate.semantic_identity for candidate in candidates) if candidates else "none")
    code = None if outcome == "exact" else (
        "JAVA_CALL_AMBIGUOUS" if outcome == "ambiguous" else
        "JAVA_EXTERNAL_CALL" if outcome == "external" else "JAVA_CALL_UNRESOLVED")
    return SemanticResult(
        capability="callable_resolution", outcome=outcome, subject_id=unit.symbol_id,
        target_id=(candidates[0].symbol_id if outcome == "exact" else
                   identifier('resource', 'java-external-call', receiver or unit.owner, name)
                   if outcome == "external" else None),
        candidate_target_ids=tuple(sorted(candidate.symbol_id for candidate in candidates))
            if outcome == "ambiguous" else (),
        evidence_ids=(evidence_id or unit.evidence_id,), diagnostic_code=code, reason=reason,
        provider=invocation.get("provider") if invocation and outcome == "external" else None,
    )


def candidates(unit, receiver, name, available, position=None):
    method = getattr(unit, "semantic_method", None)
    if not method:
        return []
    matches = [item for item in method["invocations"]
               if item["receiver"] == receiver and item["name"] == name
               and (position is None or item["position"] == position)]
    viable = [candidate for item in matches for candidate in item.get("candidates", [])]
    allowed = {id(candidate) for candidate in available}
    return [candidate for candidate in viable if id(candidate) in allowed][:8]


def activation_evidence(source):
    """Return only parsed evidence categories understood by installed enrichers."""
    semantic = getattr(source, "semantic", {})
    return {
        "imports": sorted({*semantic.get("imports", {}).values(),
                           *semantic.get("wildcards", [])}),
        "annotations": sorted({value
            for item in semantic.get("types", []) + semantic.get("methods", [])
            for annotation in item.get("annotations", [])
            for value in (annotation["name"], annotation["qualified_name"])}),
    }


def relations(source):
    return getattr(source, "semantic_relations", [])


def symbol_key(name):
    return name


bindings = rules.bindings
resources = rules.resources
def observations(unit):
    return [*rules.observations(unit),
            *getattr(unit, 'configuration_observations', ())]


def operations(unit):
    """Return rule operations plus persistence operations recorded by framework enrichers."""
    result = rules.operations(unit)
    for item in getattr(unit, "persistence_operations", []):
        gaps = list(item["gaps"])
        if item["kind"] == "data_write":
            gaps.append({"projection": "completion", "code": "JAVA_PERSISTENCE_COMPLETION_UNRESOLVED",
                         "reason": "The write is declared in source; whether its transaction "
                                   "commits at runtime is not established statically."})
        reason = "; ".join(gap["reason"] for gap in gaps) or None
        result.append(declare_operation_observation(unit,
            position=item["position"], end=item["end"], kind=item["kind"],
            outcome=unit.text[item["position"]:item["end"]], resource=item["resource"],
            condition=item["condition"], protocol=item["protocol"],
            supporting_evidence_spans=item["supporting"], projection_gaps=gaps,
            resolution="unresolved" if gaps else "resolved", reason=reason))
    return result
interaction = rules.interaction
