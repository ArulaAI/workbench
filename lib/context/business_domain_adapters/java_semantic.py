"""Trusted Java semantic adapter.

The adapter parses contained source snapshots with the installed tree-sitter
Java grammar.  It never invokes Maven, Gradle, annotation processors, or code
from the repository being inspected.  Resolution is deliberately closed-world:
only declarations present in the supplied snapshots are resolved; imported
declarations that are absent remain explicit capability boundaries.
"""
from __future__ import annotations

import re
from collections import defaultdict

from tree_sitter import Language, Parser
import tree_sitter_java

from . import rules
from .base import SemanticResult, Unit, declare_trace_contract
from ..business_domain_schema import identifier


_PARSER = Parser(Language(tree_sitter_java.language()))
_TYPE_NODES = {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}
_METHOD_NODES = {"method_declaration", "constructor_declaration"}


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
                "text": _text(source, annotation),
                "start": _char(source, annotation.start_byte),
                "end": _char(source, annotation.end_byte),
            })
    return result


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


def _declared_types(source, node):
    return [_type_text(source, item) for item in _walk(node, {
        "type_identifier", "scoped_type_identifier", "generic_type", "integral_type",
        "floating_point_type", "boolean_type", "void_type",
    })]


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
        superclass = node.child_by_field_name("superclass")
        interfaces = node.child_by_field_name("interfaces")
        bases = _declared_types(source, superclass) if superclass else []
        implemented = _declared_types(source, interfaces) if interfaces else []
        entry = {"node": node, "unit": unit, "name": name, "fqname": fqname,
                 "kind": node.type, "bases": bases, "interfaces": implemented,
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
        for local in _walk(method["node"], {"local_variable_declaration"}):
            type_node = local.child_by_field_name("type")
            for declarator in _children(local, {"variable_declarator"}):
                name_node = declarator.child_by_field_name("name")
                if name_node:
                    variables[_text(source, name_node)] = _type_text(source, type_node)
        for call in _walk(method["node"], {"method_invocation"}):
            name_node = call.child_by_field_name("name")
            object_node = call.child_by_field_name("object")
            args_node = call.child_by_field_name("arguments")
            named_args = list(_children(args_node)) if args_node else []
            invocation = {
                "receiver": _text(source, object_node) if object_node else None,
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
            local_roots = {entry["fqname"].split(".")[0] for entry in types_by_fq.values()
                           if "." in entry["fqname"]}
            return ("unresolved" if target.split(".")[0] in local_roots else "external"), []
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
    if simple in {"String", "Object", "Class", "Integer", "Long", "Boolean", "Exception", "RuntimeException"}:
        return "external", []
    return "unresolved", []


# The Java language definition, not a heuristic. Eight primitives, their
# java.lang boxes, String and void; boxing in both directions and the widening
# order from JLS 5.1.2. Closed by the specification, so it cannot drift. The
# tree-sitter grammar already recognises the primitive halves as integral_type,
# floating_point_type, boolean_type and void_type, used for node selection at
# lines 93-94, 186-187 and 220-221; the boxes are ordinary type_identifier
# nodes and only their names distinguish them.
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
    """True when provably compatible, False when provably not, None when unknown.

    Only the scalar types above are judged, and boxing is transparent in both
    directions. Reference types need a type hierarchy this adapter does not
    build, so they return None rather than a false negative that would veto an
    otherwise unambiguous call.
    """
    # `_simple` erases array depth, so compare it before normalising. Without
    # this, int[] and int look identical and an overload pair such as
    # f(int) / f(int[]) both match.
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


def prepare(sources, units, diagnostics=None):
    diagnostics = diagnostics if diagnostics is not None else []
    java_sources = [source for source in sources if hasattr(source, "semantic")]
    types = [entry for source in java_sources for entry in source.semantic["types"]]
    types.extend({unit.generated_interface_name: {
        "node": None, "unit": unit, "name": unit.name,
        "fqname": unit.generated_interface_name,
        "kind": "interface_declaration", "bases": [], "interfaces": [],
        "annotations": [], "fields": {}, "field_units": [], "methods": [],
    } for unit in units if getattr(unit, "generated_interface_name", None)}.values())
    types_by_fq = {entry["fqname"]: entry for entry in types}
    types_by_short = defaultdict(list)
    for entry in types:
        types_by_short[entry["name"]].append(entry)
    methods_by_owner = defaultdict(list)
    for entry in types:
        methods_by_owner[entry["fqname"]].extend(entry["methods"])
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
                    "reason": None if state == "resolved" else
                        f"Java {kind} target {type_name} is {state}.",
                })
        for method in source.semantic["methods"]:
            for invocation in method["invocations"]:
                receiver = invocation["receiver"]
                # A receiver written `this.field` or `super.field` arrives as the
                # whole expression, while `variables` is keyed by bare names. Strip
                # the qualifier so field receivers resolve to their declared type.
                bare = receiver
                if receiver and receiver.split(".")[0] in {"this", "super"}:
                    bare = receiver.split(".", 1)[1] if "." in receiver else None
                owner_states = []
                if bare is None and method["owner"]:
                    owner_states = [("resolved", [method["owner"]])]
                elif bare:
                    raw_type = invocation["variables"].get(bare, bare)
                    owner_states = [_resolve_type(source, raw_type, types_by_fq, types_by_short)]
                state, owners = owner_states[0] if owner_states else ("unresolved", [])
                candidates = [candidate for owner in owners for candidate in methods_by_owner[owner["fqname"]]
                              if candidate["name"] == invocation["name"]
                              and len(candidate["params"]) == len(invocation["argument_types"])]
                exact = [candidate for candidate in candidates if all(
                    _assignable(argument, parameter[1]) is True
                    for argument, parameter in zip(invocation["argument_types"], candidate["params"]))]
                # A candidate is plausible when no argument is provably incompatible.
                # `_assignable` returns None for pairs it cannot judge, which is the
                # normal case for reference types, and None must not veto a match.
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
    # Used by candidate resolution without any global mutable adapter state.
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
        "annotations": sorted({annotation["name"]
            for item in semantic.get("types", []) + semantic.get("methods", [])
            for annotation in item.get("annotations", [])}),
    }


def relations(source):
    return getattr(source, "semantic_relations", [])


def symbol_key(name):
    return name


bindings = rules.bindings
resources = rules.resources
observations = rules.observations
operations = rules.operations
interaction = rules.interaction
