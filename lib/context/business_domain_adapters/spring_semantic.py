"""Spring enricher for Java units: endpoints, bean selection and persistence."""
from __future__ import annotations

import json
import re

from . import CATALOG, java_semantic
from ..language_registry import registry
from .base import (MAX_SEMANTIC_CANDIDATES, declare_anchor_registration,
                   declare_anchor_representation, declare_trace_contract, http_base_path,
                   http_identity)
from ..business_domain_schema import identifier


_MAPPING_METHODS = {
    "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
    "PatchMapping": "PATCH", "DeleteMapping": "DELETE",
}
# Outbound HTTP clients; their mappings describe the remote endpoint.
_CLIENT_ANNOTATIONS = frozenset({"FeignClient", "HttpExchange"})
# Placeholder for a route we could not evaluate, so it is not mistaken for "".
_DYNAMIC_ROUTE = "\0dynamic"
_STRING_LITERAL = r'"(?:[^"\\]|\\.)*"'


def _paths(text):
    """Return the routes from a mapping annotation's value/path or first positional argument."""
    args = text[text.find("(") + 1:text.rfind(")")] if "(" in text else ""
    named = re.search(r"\b(?:value|path)\s*=\s*(\{[^}]*\}|" + _STRING_LITERAL + r"|[^,)]+)", args)
    if named:
        args = named.group(1)
    elif re.match(r"\s*\w+\s*=", args):
        return [""]
    else:
        args = re.split(r",\s*\w+\s*=", args, maxsplit=1)[0]
    if re.search(r"[A-Za-z_$]", re.sub(_STRING_LITERAL, "", args)):
        return [_DYNAMIC_ROUTE]
    return [literal[1:-1] for literal in re.findall(_STRING_LITERAL, args)] or [""]


# Compile-time String constants (JLS 15.29): literals, +, parentheses and
# static final String fields from the analyzed sources. Anything else is dynamic.
_CONSTANT_TOKEN = re.compile(r'\s*(?:(' + _STRING_LITERAL + r')|([A-Za-z_$][\w$]*)|([+().]))')
_STRING_TYPES = frozenset({"String", "java.lang.String"})
_STATIC_IMPORT = re.compile(r'^\s*import\s+static\s+([\w$.]+?)(\.\*)?\s*;', re.MULTILINE)
_MAX_CONSTANT_DEPTH = 16
_UNKNOWN = "unknown"


class _Constants:
    """Resolve String constants used in mapping annotations.

    A name resolves only if Java's lookup order finds exactly one constant in
    the analyzed sources; anything missing or ambiguous leaves it unevaluated.
    """

    def __init__(self, sources):
        by_fq = {}
        self.by_short = {}
        self.fields = {}
        self.enclosing = {}
        self.static_imports = {}
        self.memo = {}
        for source in sources:
            entries = [entry for entry in source.semantic.get("types", [])
                       if entry.get("node") is not None]
            for entry in entries:
                by_fq.setdefault(entry["fqname"], []).append(entry)
                self.by_short.setdefault(entry["name"], []).append(entry)
                self.fields[id(entry)] = self._declared(source, entry)
                self.enclosing[id(entry)] = sorted(
                    (item for item in entries if item is not entry
                     and item["node"].start_byte < entry["node"].start_byte
                     and entry["node"].end_byte < item["node"].end_byte),
                    key=lambda item: item["node"].start_byte, reverse=True)
            singles, wildcards = {}, []
            for found in _STATIC_IMPORT.finditer(source.text):
                if found.group(2):
                    wildcards.append(found.group(1))
                else:
                    singles[found.group(1).rsplit(".", 1)[-1]] = found.group(1)
            self.static_imports[id(source)] = (singles, wildcards)
        # Skip names declared more than once.
        self.unique = {name: entries[0] for name, entries in by_fq.items()
                       if len(entries) == 1}

    @staticmethod
    def _declared(source, entry):
        """Return ``{field: (initializer, start, end) | None}``; None means not a constant."""
        body = entry["node"].child_by_field_name("body")
        fields = {}
        if body is None:
            return fields
        interface = entry["kind"] == "interface_declaration"
        for field in java_semantic._children(body, {"field_declaration", "constant_declaration"}):
            constant = interface or {"static", "final"} <= java_semantic._keyword_modifiers(field)
            string = java_semantic._type_text(
                source, field.child_by_field_name("type")) in _STRING_TYPES
            for declarator in java_semantic._children(field, {"variable_declarator"}):
                name = declarator.child_by_field_name("name")
                value = declarator.child_by_field_name("value")
                if name is None:
                    continue
                fields[java_semantic._text(source, name)] = (
                    (java_semantic._text(source, value),
                     java_semantic._char(source, field.start_byte),
                     java_semantic._char(source, field.end_byte))
                    if constant and string and value is not None else None)
        return fields

    def route(self, entry, expression, member):
        """Return ``(value, declaration spans)`` for a route expression, or None.

        Pass member=False for a type-level annotation, where the type's own
        members are not in scope.
        """
        chain = ([entry] if member else []) + self.enclosing.get(id(entry), [])
        return self._evaluate(expression, entry["unit"].source, chain, frozenset())

    def _evaluate(self, expression, source, chain, active):
        tokens, position = [], 0
        while expression[position:].strip():
            found = _CONSTANT_TOKEN.match(expression, position)
            if not found:
                return None
            tokens.append(found.groups())
            position = found.end()
        index = 0

        def operand():
            nonlocal index
            if index >= len(tokens):
                return None
            literal, name, symbol = tokens[index]
            index += 1
            if literal:
                try:
                    return java_semantic._decode_java_string_literal(literal), []
                except java_semantic.JavaLiteralError:
                    return None
            if symbol == "(":
                inner = concatenation()
                if inner is None or index >= len(tokens) or tokens[index][2] != ")":
                    return None
                index += 1
                return inner
            if not name:
                return None
            parts = [name]
            while (index + 1 < len(tokens) and tokens[index][2] == "."
                   and tokens[index + 1][1]):
                parts.append(tokens[index + 1][1])
                index += 2
            return self._name(parts, source, chain, active)

        def concatenation():
            nonlocal index
            result = operand()
            while result is not None and index < len(tokens) and tokens[index][2] == "+":
                index += 1
                following = operand()
                result = (None if following is None else
                          (result[0] + following[0], result[1] + following[1]))
            return result

        result = concatenation()
        return result if index == len(tokens) else None

    def _name(self, parts, source, chain, active):
        if len(parts) == 1:
            key = self._simple(parts[0], source, chain)
        else:
            owners = self._types(parts[:-1], source, chain)
            key = (self._member(owners[0], parts[-1], frozenset())
                   if len(owners) == 1 else None)
        return self._constant(key, active) if isinstance(key, tuple) else None

    def _constant(self, key, active):
        entry, name = key
        marker = (id(entry), name)
        if marker in self.memo:
            return self.memo[marker]
        if marker in active or len(active) >= _MAX_CONSTANT_DEPTH:
            return None
        expression, start, end = self.fields[id(entry)][name]
        source = entry["unit"].source
        result = self._evaluate(expression, source,
            [entry] + self.enclosing.get(id(entry), []), active | {marker})
        if result is not None:
            result = (result[0], [(source, start, end)] + result[1])
        if not active:
            self.memo[marker] = result
        return result

    def _member(self, entry, name, seen):
        """Look up a declared or inherited field: ``(entry, name)``, ``_UNKNOWN`` or None."""
        fields = self.fields.get(id(entry), {})
        if name in fields:
            return (entry, name) if fields[name] is not None else _UNKNOWN
        if id(entry) in seen or len(seen) >= _MAX_CONSTANT_DEPTH:
            return _UNKNOWN
        found = {}
        for written in entry["bases"] + entry["interfaces"]:
            parents = self._types(
                java_semantic._without_type_arguments(written).split("."),
                entry["unit"].source, self.enclosing.get(id(entry), []))
            if len(parents) != 1:
                return _UNKNOWN
            inherited = self._member(parents[0], name, seen | {id(entry)})
            if inherited == _UNKNOWN:
                return _UNKNOWN
            if inherited:
                found[(id(inherited[0]), inherited[1])] = inherited
        if len(found) > 1:
            return _UNKNOWN
        return next(iter(found.values()), None)

    def _simple(self, name, source, chain):
        for entry in chain:
            found = self._member(entry, name, frozenset())
            if found:
                return found
        singles, wildcards = self.static_imports.get(id(source), ({}, []))
        if name in singles:
            owner = self.unique.get(singles[name].rsplit(".", 1)[0])
            return self._member(owner, name, frozenset()) if owner else None
        matches = []
        for qualified in wildcards:
            owner = self.unique.get(qualified)
            found = self._member(owner, name, frozenset()) if owner else _UNKNOWN
            if found == _UNKNOWN:
                return None
            if found:
                matches.append(found)
        return matches[0] if len(matches) == 1 else None

    def _types(self, parts, source, chain):
        """Return the declarations a written type name refers to."""
        candidates = []
        written = ".".join(parts)
        if written in self.unique:
            candidates.append(self.unique[written])
        first, rest = parts[0], parts[1:]
        heads = [self.unique[fq] for fq in (entry["fqname"] + "." + first for entry in chain)
                 if fq in self.unique][:1]
        if not heads:
            semantic = source.semantic
            imported = semantic.get("imports", {}).get(first)
            same = ".".join(filter(None, [semantic.get("package"), first]))
            if imported:
                heads = [self.unique[imported]] if imported in self.unique else []
            elif same in self.unique:
                heads = [self.unique[same]]
            else:
                heads = [entry for entry in self.by_short.get(first, [])
                         if any(entry["fqname"] == prefix + "." + first
                                for prefix in semantic.get("wildcards", []))]
        for head in heads:
            target = ".".join([head["fqname"], *rest])
            if target in self.unique and self.unique[target] not in candidates:
                candidates.append(self.unique[target])
        return candidates


def _resolve_route_constants(units):
    """Evaluate mapping routes built from String constants and store them on the annotation."""
    sources = {id(unit.source): unit.source for unit in units
               if unit.source.language == "java"
               and getattr(unit.source, "semantic", {}).get("types")}
    constants = _Constants(sources.values())
    for source in sources.values():
        for entry in source.semantic["types"]:
            targets = [(annotation, False) for annotation in entry["annotations"]]
            targets.extend((annotation, True) for method in entry["methods"]
                           for annotation in method["annotations"])
            for annotation, member in targets:
                if (annotation["name"] not in _MAPPING_METHODS
                        and annotation["name"] != "RequestMapping"
                        or _paths(annotation["text"]) != [_DYNAMIC_ROUTE]):
                    continue
                results = [constants.route(entry, argument["expression"], member)
                           for argument in annotation["arguments"]
                           if argument["name"] in {"value", "path"}]
                if not results or None in results:
                    continue
                annotation["route_values"] = [value for value, _ in results]
                annotation["route_evidence"] = list({
                    (span[0].path, span[1], span[2]): span
                    for _, spans in results for span in spans}.values())


def _request_methods(text):
    """Return HTTP methods selected by a RequestMapping ``method`` attribute."""
    selected = re.search(r"\bmethod\s*=\s*(\{[^}]*\}|[\w.]+)", text)
    if not selected:
        return []
    return re.findall(r"(?:\bRequestMethod\.|\b)(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b",
                      selected.group(1))


def _mappings(annotations):
    mappings = []
    for annotation in annotations:
        name, text = annotation["name"], annotation["text"]
        paths = annotation.get("route_values") or _paths(text)
        if name in _MAPPING_METHODS:
            mappings.extend((_MAPPING_METHODS[name], path, annotation) for path in paths)
        elif name == "RequestMapping":
            methods = _request_methods(text)
            mappings.extend((method if methods else None, path, annotation)
                            for method in (methods or [None]) for path in paths)
    return mappings


def _join(*parts):
    if _DYNAMIC_ROUTE in parts:
        return None
    values = [part.strip("/") for part in parts if part not in (None, "", "/")]
    return "/" + "/".join(values) if values else "/"


def _same_signature(left, right):
    if left["name"] != right["name"] or len(left["params"]) != len(right["params"]):
        return False
    simple = lambda value: re.sub(r"<.*>", "", value).replace("[]", "").rsplit(".", 1)[-1]
    return all(simple(a[1]) == simple(b[1]) for a, b in zip(left["params"], right["params"]))


def _combinations(owner, method, mappings=None):
    effective = ([(*mapping, method) for mapping in _mappings(method["annotations"])]
                 if mappings is None else mappings)
    bases = _mappings(owner["annotations"]) or [(None, "", None)]
    return [(http_method or base_method
             if not (http_method and base_method and http_method != base_method)
             else None, _join(base_path, route), base_annotation,
             mapping_annotation, mapping_owner)
            for http_method, route, mapping_annotation, mapping_owner in effective
            for base_method, base_path, base_annotation in bases]


def _apply_endpoint(unit, combinations, base_owner, diagnostics, source):
    if len(combinations) == 1:
        http_method, route, base_annotation, mapping_annotation, mapping_owner = combinations[0]
        unit.anchor_kind = "http"
        unit.method = http_method
        unit.route = route
        unit.anchor_evidence_spans = [
            span for owner, annotation in ((base_owner, base_annotation),
                (mapping_owner, mapping_annotation))
            if annotation
            for span in [(owner["unit"].source, annotation["start"], annotation["end"]),
                         *annotation.get("route_evidence", ())]
        ]
        unit.anchor_resolution = "resolved" if http_method and route else "unresolved"
        unit.anchor_reason = (None if http_method and route else
            "Spring route is evidenced through a constant or expression that is not statically resolved."
            if http_method else
            "Spring route is evidenced, but RequestMapping does not select one HTTP method.")
    elif len(combinations) > 1:
        unit.anchor_kind = "http"
        methods = {item[0] for item in combinations}
        routes = {item[1] for item in combinations}
        unit.method = next(iter(methods)) if len(methods) == 1 else None
        unit.route = next(iter(routes)) if len(routes) == 1 else None
        spans = [(base_owner["unit"].source, item[2]["start"], item[2]["end"])
                 for item in combinations if item[2]]
        spans.extend((item[4]["unit"].source, item[3]["start"], item[3]["end"])
                     for item in combinations if item[3])
        spans.extend(span for item in combinations for annotation in (item[2], item[3])
                     if annotation for span in annotation.get("route_evidence", ()))
        unit.anchor_evidence_spans = list({
            (span[0].path, span[1], span[2]): span for span in spans
        }.values())
        unit.anchor_evidence_spans.sort(key=lambda item: (item[0].path, item[1], item[2]))
        unit.anchor_resolution = "ambiguous"
        unit.anchor_reason = "Multiple evidenced Spring endpoint mappings remain viable."
        diagnostics.append({"code": "SPRING_ENDPOINT_AMBIGUOUS",
            "message": unit.anchor_reason,
            "subject_ids": [source.resource_id], "evidence_ids": []})


def _link_contract(contract, implementation):
    targets = contract.anchor_correspondence_units
    if not any(target is implementation for target in targets):
        targets.append(implementation)
    contract.anchor_correspondence_relationship_kind = "implements"
    if len(targets) == 1:
        contract.anchor_correspondence_state = "resolved"
        contract.anchor_correspondence_reason = (
            "Exact Java type and callable signatures select this implementation.")
    else:
        contract.anchor_correspondence_state = "ambiguous"
        contract.anchor_correspondence_reason = (
            "Multiple concrete methods implement this interface contract.")


# @ConditionalOnProperty links to the declarations of its key. We do not pick
# which one applies at deploy time.
_CONDITIONAL_ON_PROPERTY_FQN = (
    'org.springframework.boot.autoconfigure.condition.ConditionalOnProperty')
_CONDITIONAL_ON_PROPERTY_PACKAGE = (
    'org.springframework.boot.autoconfigure.condition')
_CONDITION_REASON = (
    'Repository declarations were linked; effective deployment precedence '
    'was not evaluated.')


class _ConditionError(ValueError):
    def __init__(self, cause, start, end):
        super().__init__(cause)
        self.cause, self.start, self.end = cause, start, end


def _string(argument):
    try:
        return java_semantic._decode_java_string_literal(argument['expression'])
    except java_semantic.JavaLiteralError as error:
        raise _ConditionError(error.cause,
            argument['start'] + error.start,
            argument['start'] + error.end) from None


def _scope_for_java(path):
    parts = tuple(path.split('/'))
    for index in range(len(parts) - 2):
        if parts[index:index + 3] == ('src', 'main', 'java'):
            return 'main'
        if parts[index:index + 3] == ('src', 'test', 'java'):
            return 'test'
    return None


def _condition_expression(key, having_value, match_if_missing):
    quoted_key = json.dumps(key, ensure_ascii=False, separators=(',', ':'))
    if having_value is None:
        expression = f'property[{quoted_key}] is present and not false'
    else:
        quoted_value = json.dumps(having_value, ensure_ascii=False,
                                  separators=(',', ':'))
        expression = f'property[{quoted_key}] == {quoted_value}'
    return expression + (' or missing' if match_if_missing else '')


def _condition_redaction_candidates(annotation):
    grouped = {}
    for argument in annotation['arguments']:
        grouped.setdefault(argument['name'], []).append(argument)
    decoded_names, unknown_key_component = [], False
    for argument in (*grouped.get('name', ()), *grouped.get('value', ())):
        try:
            decoded_names.append(_string(argument))
        except _ConditionError:
            unknown_key_component = True
    decoded_prefixes = []
    for argument in grouped.get('prefix', ()):
        try:
            decoded_prefixes.append(_string(argument))
        except _ConditionError:
            unknown_key_component = True
    prefixes = decoded_prefixes or ['']
    keys = [prefix + ('.' if prefix and not prefix.endswith('.') else '') + name
        for prefix in prefixes for name in decoded_names]
    keys_or_unknown = [*keys,
        *([None] if unknown_key_component or not keys else [])]
    return tuple((key, argument['start'], argument['end'])
        for key in keys_or_unknown
        for argument in grouped.get('havingValue', ()))


def _property_condition(annotation):
    grouped = {}
    for argument in annotation['arguments']:
        grouped.setdefault(argument['name'], []).append(argument)
    if set(grouped) - {'name', 'value', 'prefix', 'havingValue',
                       'matchIfMissing'}:
        raise ValueError('unsupported_conditional_property_argument')
    names = grouped.get('name', [])
    values = grouped.get('value', [])
    if bool(names) == bool(values):
        raise ValueError('exactly_one_of_name_or_value_is_required')
    for scalar in ('prefix', 'havingValue', 'matchIfMissing'):
        if len(grouped.get(scalar, [])) > 1:
            raise ValueError(f'{scalar}_must_not_repeat')
    decoded_names = [_string(item) for item in (names or values)]
    prefix = (_string(grouped['prefix'][0])
        if grouped.get('prefix') else '')
    # Spring treats an empty havingValue like an omitted one: the property
    # must be present and not "false".
    having_value = (_string(grouped['havingValue'][0])
        if grouped.get('havingValue') else None) or None
    value_spans = (((grouped['havingValue'][0]['start'],
                     grouped['havingValue'][0]['end']),)
        if having_value is not None else ())
    match_if_missing = False
    if grouped.get('matchIfMissing'):
        literal = grouped['matchIfMissing'][0]['expression']
        if literal not in {'true', 'false'}:
            raise ValueError('matchIfMissing_must_be_boolean_literal')
        match_if_missing = literal == 'true'
    separator = '.' if prefix and not prefix.endswith('.') else ''
    return ([prefix + separator + name for name in decoded_names],
        having_value, match_if_missing, value_spans)


def _condition_units(sources):
    for source in sources:
        semantic = getattr(source, 'semantic', {})
        for owner in semantic.get('types', []):
            yield owner['unit'], owner.get('annotations', [])
            for method in owner.get('methods', []):
                yield method['unit'], method.get('annotations', [])


def _is_condition_annotation(source, annotation):
    qualified = annotation['qualified_name']
    if qualified == _CONDITIONAL_ON_PROPERTY_FQN:
        return True
    if qualified != 'ConditionalOnProperty':
        return False
    semantic = getattr(source, 'semantic', {})
    return (semantic.get('imports', {}).get('ConditionalOnProperty')
            == _CONDITIONAL_ON_PROPERTY_FQN
        or _CONDITIONAL_ON_PROPERTY_PACKAGE in semantic.get('wildcards', ()))


def _prepare_property_conditions(sources, units):
    pending = []
    declarations = [unit for unit in units
        if unit.configuration is not None
        and unit.configuration.role == 'application_configuration'
        and unit.configuration.profile is None]
    for consumer, consumer_annotations in _condition_units(sources):
        environment = _scope_for_java(consumer.source.path)
        if environment is None:
            continue
        observations = getattr(consumer, 'configuration_observations', None)
        if observations is None:
            observations = []
            consumer.configuration_observations = observations
        ordinal = 0
        for annotation in consumer_annotations:
            if not _is_condition_annotation(consumer.source, annotation):
                continue
            redaction_candidates = _condition_redaction_candidates(annotation)
            try:
                (keys, having_value, match_if_missing,
                 value_spans) = _property_condition(annotation)
            except _ConditionError as error:
                pending.append({'source_id': consumer.source.resource_id,
                    'code': 'SPRING_PROPERTY_CONDITION_UNAVAILABLE',
                    'reason': error.cause, 'span': (error.start, error.end),
                    'named_value_spans': redaction_candidates})
                continue
            except ValueError as error:
                pending.append({'source_id': consumer.source.resource_id,
                    'code': 'SPRING_PROPERTY_CONDITION_UNAVAILABLE',
                    'reason': str(error),
                    'span': (annotation['start'], annotation['end']),
                    'named_value_spans': redaction_candidates})
                continue
            for key in keys:
                allowed = {'main'} if environment == 'main' else {'main', 'test'}
                candidates = tuple(unit for unit in declarations
                    if _relaxed(unit.configuration.key) == _relaxed(key)
                    and unit.configuration.environment in allowed)
                # Relaxed binding matches app.featureEnabled to app.feature-enabled.
                # If spellings differ, keep only the exact match.
                spellings = {unit.configuration.key for unit in candidates}
                if len(spellings) > 1:
                    candidates = tuple(unit for unit in candidates
                                       if unit.configuration.key == key)
                    spellings = {key} if candidates else set()
                binding_name = next(iter(spellings)) if spellings else key
                if not candidates:
                    pending.append({'source_id': consumer.source.resource_id,
                        'code': 'SPRING_PROPERTY_CONDITION_UNAVAILABLE',
                        'reason': 'matching_repository_declaration_unavailable',
                        'span': (annotation['start'], annotation['end']),
                        'named_value_spans': redaction_candidates})
                observations.append(
                    {'identity_key': f'configuration:{key}:{ordinal}',
                     'source_location_kind': 'configuration',
                     'native_expression': _condition_expression(
                         key, having_value, match_if_missing),
                     'declaration_units': candidates,
                     'binding_name': binding_name, 'binding_direction': 'internal',
                     'span': (annotation['start'] - consumer.start,
                              annotation['end'] - consumer.start),
                     'scope': {'environment': environment, 'tenant': None,
                            'actor': None, 'profile': None,
                            'effective_from': None, 'effective_to': None,
                            'version': None, 'entrypoint_ids': None},
                     'resolution': 'unresolved', 'reason': _CONDITION_REASON,
                     'named_value_spans': tuple((key, start, end)
                         for start, end in value_spans)})
                ordinal += 1
    return pending


def prepare(sources, units, diagnostics=None):
    diagnostics = diagnostics if diagnostics is not None else []
    pending = _prepare_property_conditions(sources, units)
    _resolve_route_constants(units)
    all_types = [item for source in sources for item in getattr(source, "semantic", {}).get("types", [])]
    by_unit = {id(item["unit"]): item for item in all_types}
    for interface in (item for item in all_types
                      if item["kind"] == "interface_declaration"
                      and not _CLIENT_ANNOTATIONS & {annotation["name"]
                          for annotation in item["annotations"]}):
        for method in interface["methods"]:
            combinations = _combinations(interface, method)
            _apply_endpoint(method["unit"], combinations, interface,
                            diagnostics, method["unit"].source)
            unit = method["unit"]
            if unit.anchor_kind:
                identity_key = (http_identity(unit.source, unit.method, unit.route)
                                if unit.anchor_resolution == "resolved" else None)
                declare_anchor_representation(unit, "registration", identity_key,
                    "eligible" if identity_key else "unresolved", "external")
                declare_anchor_registration(unit, "http_route", event=unit.method,
                    target='.'.join(filter(None, [unit.owner, unit.name])),
                    scope=unit.source.service_scope,
                    resolution=unit.anchor_resolution, reason=unit.anchor_reason,
                    evidence_spans=unit.anchor_evidence_spans)
                declare_trace_contract(unit, unit.trace_role or "interface")
    for source in sources:
        relations = getattr(source, "semantic_relations", [])
        resolved_interfaces = {}
        for relation in relations:
            if relation["kind"] == "implements" and relation["target"]:
                resolved_interfaces.setdefault(id(relation["source"]), []).append(
                    by_unit.get(id(relation["target"])))
        for controller in getattr(source, "semantic", {}).get("types", []):
            annotation_names = {item["name"] for item in controller["annotations"]}
            if "RestController" not in annotation_names and "Controller" not in annotation_names:
                continue
            interfaces = [item for item in resolved_interfaces.get(id(controller["unit"]), []) if item]
            generated_packages = [config["api_package"] for config in
                getattr(source, "generated_source_config", [])
                if config.get("interface_only")]
            generated = any(
                source.semantic.get("imports", {}).get(name.rsplit(".", 1)[-1], name)
                .startswith(package + ".")
                for name in controller.get("interfaces", [])
                for package in generated_packages)
            api_contracts = [unit for unit in units
                             if unit.source.language in {"yaml", "json"}
                             and unit.anchor_kind == "http"] if generated else []
            for method in controller["methods"]:
                mappings = [(*mapping, method) for mapping in _mappings(method["annotations"])]
                inherited = []
                inherited_methods = []
                for interface in interfaces:
                    for contract in interface["methods"]:
                        if _same_signature(method, contract):
                            contract_mappings = [(*mapping, contract)
                                                 for mapping in _mappings(contract["annotations"])]
                            inherited.extend(contract_mappings)
                            inherited_methods.append(contract)
                if generated and not inherited:
                    matches = [contract for contract in api_contracts
                               if contract.name == method["name"]]
                    if len(matches) == 1:
                        contract = matches[0]
                        inherited = [(contract.method, contract.route, None, contract)]
                effective = mappings or inherited
                unit = method["unit"]
                if inherited and len(inherited[0]) == 4 and isinstance(inherited[0][3], type(unit)):
                    contract = inherited[0][3]
                    combinations = [(contract.method, _join(
                        next((path for _, path, _ in _mappings(controller["annotations"])), ""),
                        contract.route), None, None, method)]
                else:
                    contract = None
                    combinations = _combinations(controller, method, effective)
                _apply_endpoint(unit, combinations, controller, diagnostics, source)
                if unit.anchor_kind:
                    role = "registration" if mappings else "implementation"
                    identity_key = (http_identity(unit.source, unit.method, unit.route)
                                    if unit.anchor_resolution == "resolved" else None)
                    declare_anchor_representation(unit, role, identity_key,
                        ("eligible" if role == "registration" and identity_key else
                         "supporting" if role == "implementation" else "unresolved"),
                        "external")
                    if role == "registration":
                        declare_anchor_registration(unit, "http_route", event=unit.method,
                            target='.'.join(filter(None, [unit.owner, unit.name])),
                            scope=unit.source.service_scope,
                            resolution=unit.anchor_resolution, reason=unit.anchor_reason,
                            evidence_spans=unit.anchor_evidence_spans)
                    declare_trace_contract(unit, unit.trace_role or
                                           ('implementation' if unit.executable_body else 'declaration'))
                if contract is not None and unit.anchor_kind:
                    _link_contract(contract, unit)
                    relation = {"source": unit, "target": contract,
                        "candidate_targets": [contract], "kind": "implements",
                        "start": unit.start, "end": unit.end,
                        "resolution": "resolved", "reason": None}
                    if not any(existing["source"] is unit and
                               existing["target"] is contract and
                               existing["kind"] == "implements"
                               for existing in relations):
                        relations.append(relation)
                for contract in inherited_methods:
                    _link_contract(contract["unit"], method["unit"])
                    contract_unit = contract["unit"]
                    if contract_unit.anchor_correspondence_state == "resolved":
                        contract_unit.method = unit.method
                        contract_unit.route = unit.route
                        contract_unit.anchor_identity_key = http_identity(
                            contract_unit.source, unit.method, unit.route)
                        contract_unit.anchor_evidence_spans = list({
                            (span[0].path, span[1], span[2]): span
                            for span in (contract_unit.anchor_evidence_spans
                                         + unit.anchor_evidence_spans)
                        }.values())
                    else:
                        contract_unit.anchor_identity_key = None
                        contract_unit.anchor_eligibility = "unresolved"
                        contract_unit.anchor_resolution = "ambiguous"
                        contract_unit.anchor_reason = (
                            "Multiple concrete endpoint registrations implement this interface contract.")
                    reverse = {"source": contract["unit"], "target": method["unit"],
                        "candidate_targets": [method["unit"]],
                        "kind": "selects_implementation",
                        "start": contract["unit"].start, "end": contract["unit"].end,
                        "resolution": "resolved", "reason": None}
                    contract_relations = getattr(
                        contract["unit"].source, "semantic_relations", [])
                    # The Java adapter may already have a relation for this method.
                    if not any(existing["source"] is reverse["source"] and
                               existing["kind"] == reverse["kind"] and
                               (existing["target"] is reverse["target"] or any(
                                   candidate is reverse["target"]
                                   for candidate in existing.get("candidate_targets", [])))
                               for existing in contract_relations):
                        contract_relations.append(reverse)
                    relation = {"source": method["unit"], "target": contract["unit"],
                        "candidate_targets": [contract["unit"]], "kind": "implements",
                        "start": method["unit"].start, "end": method["unit"].end,
                        "resolution": "resolved", "reason": None}
                    if not any(existing["source"] is relation["source"] and
                               existing["target"] is relation["target"] and
                               existing["kind"] == relation["kind"] for existing in relations):
                        relations.append(relation)
            unresolved = [relation for relation in relations
                          if relation["source"] is controller["unit"]
                          and relation["kind"] == "implements"
                          and relation["resolution"] != "resolved"]
            if unresolved:
                diagnostics.append({"code": "SPRING_CONTRACT_DECLARATION_UNAVAILABLE",
                    "message": "Controller contract source is unavailable; inherited endpoint mappings remain unresolved.",
                    "subject_ids": [source.resource_id], "evidence_ids": []})
    _spring_data_implementations(sources, diagnostics)
    _spring_selection_evidence(sources, units)
    _persistence(sources, units, diagnostics)
    _profile_alternatives(units, diagnostics)
    return pending


# Interfaces extending these are implemented by a Spring Data proxy at runtime.
_SPRING_DATA_PACKAGE = "org.springframework.data."


def _spring_data_base(source, entry):
    """Return ``(qualified name, written name)`` of the Spring Data type *entry* extends."""
    if entry["kind"] != "interface_declaration":
        return None
    for name in entry["bases"]:
        written = re.sub(r"<.*>", "", name)
        simple = written.rsplit(".", 1)[-1]
        qualified = written if "." in written else source.semantic["imports"].get(simple, "")
        if qualified.startswith(_SPRING_DATA_PACKAGE) and simple.endswith("Repository"):
            return qualified, simple
    return None


def _heritage_span(entry, simple):
    """Return the span of *simple* in the extends clause, or the whole declaration."""
    unit = entry["unit"]
    text = unit.source.text[unit.start:unit.end]
    match = re.search(r"\bextends\b[^{]*?\b" + re.escape(simple) + r"\b", text)
    if not match:
        return unit.source, unit.start, unit.end
    start = unit.start + match.end() - len(simple)
    return unit.source, start, start + len(simple)


def _selection(declaration):
    """Return the Java adapter's implementation relation for *declaration*, if any."""
    return next((relation for relation in getattr(declaration.source, "semantic_relations", [])
                 if relation["source"] is declaration
                 and relation["kind"] == "selects_implementation"
                 and relation.get("outcome") != "external"), None)


def _selected(relation):
    if relation is None:
        return []
    return [relation["target"]] if relation.get("target") else list(relation["candidate_targets"])


def _add_source_candidates(declaration, additions, evidence_spans, diagnostics):
    """Add *additions* to the implementation candidates of *declaration*."""
    relation = _selection(declaration)
    current = _selected(relation)
    merged = sorted({id(unit): unit for unit in current + additions}.values(),
                    key=lambda unit: unit.qualified)
    if len(merged) == len(current):
        return
    if relation is None:
        relation = {"source": declaration, "kind": "selects_implementation",
                    "start": declaration.start, "end": declaration.end, "evidence_spans": []}
        declaration.source.semantic_relations.append(relation)
    relation["evidence_spans"] = list(relation.get("evidence_spans", [])) + evidence_spans
    if len(merged) == 1:
        relation.update(target=merged[0], candidate_targets=merged, resolution="resolved",
                        outcome="exact", reason=None, diagnostic_code=None)
        return
    kept = merged[:MAX_SEMANTIC_CANDIDATES]
    fragments = ", ".join(sorted(unit.semantic_identity for unit in additions))
    reason = (f"{len(merged)} concrete methods implement {declaration.semantic_identity}, "
              f"including the Spring Data repository fragment {fragments}; which one runs "
              "is not established statically.")
    if len(merged) > len(kept):
        reason += f" The first {len(kept)} are retained as candidates."
    relation.update(target=None, candidate_targets=kept, resolution="ambiguous",
                    outcome="ambiguous", diagnostic_code="JAVA_IMPLEMENTATION_AMBIGUOUS",
                    reason=reason)
    if len(current) < 2:
        diagnostics.append({"code": "JAVA_IMPLEMENTATION_AMBIGUOUS", "message": reason,
                            "subject_ids": [declaration.source.resource_id], "evidence_ids": []})


def _spring_data_implementations(sources, diagnostics):
    """Add the Spring Data proxy as an implementation candidate for repository methods.

    Methods backed by a ``<Fragment>Impl`` or ``<Repository>Impl`` class get that
    class as a candidate instead of the proxy.
    """
    for source in sources:
        for entry in getattr(source, "semantic", {}).get("types", []):
            base = _spring_data_base(source, entry)
            if base is None:
                continue
            qualified_base, simple_base = base
            heritage = _heritage_span(entry, simple_base)
            # Collect the repository and the project interfaces it inherits.
            interfaces, queue = [entry], [entry]
            while queue and len(interfaces) <= 32:
                current = queue.pop(0)
                for relation in getattr(current["unit"].source, "semantic_relations", []):
                    parent = getattr(relation.get("target"), "semantic_type", None)
                    if (relation["source"] is current["unit"] and relation["kind"] == "inherits"
                            and parent is not None and parent["kind"] == "interface_declaration"
                            and all(parent is not seen for seen in interfaces)):
                        interfaces.append(parent)
                        queue.append(parent)
            fragment_owners = {f"{entry['name']}Impl"} | {f"{item['name']}Impl" for item in interfaces}
            fragments = {}
            for interface in interfaces[1:]:
                for method in interface["methods"]:
                    implementations = [unit for unit in _selected(_selection(method["unit"]))
                                       if unit.owner in fragment_owners]
                    if implementations:
                        fragments[id(method["unit"])] = (method, implementations)
            target = identifier("resource", "spring-data-repository", entry["fqname"])
            emitted = False
            for interface in interfaces:
                for method in interface["methods"]:
                    declaration = method["unit"]
                    if declaration.executable_body or id(declaration) in fragments:
                        continue
                    routed = [implementation for fragment, implementations in fragments.values()
                              if _same_signature(method, fragment)
                              for implementation in implementations]
                    if routed:
                        _add_source_candidates(declaration, routed, [heritage] + [
                            (unit.source, unit.start, unit.end) for unit in routed], diagnostics)
                        continue
                    relations = declaration.source.semantic_relations
                    if any(relation["source"] is declaration
                           and relation.get("external_target_id") == target for relation in relations):
                        continue
                    relations.append({
                        "source": declaration, "target": None, "candidate_targets": [],
                        "kind": "selects_implementation",
                        "start": declaration.start, "end": declaration.end,
                        "resolution": "unresolved", "outcome": "external",
                        "diagnostic_code": "SPRING_DATA_RUNTIME_IMPLEMENTATION",
                        "external_target_id": target,
                        "reason": (f"Spring Data implements {declaration.semantic_identity} at "
                                   f"runtime for repository {entry['fqname']} ({qualified_base}); "
                                   "the implementation is not in the analyzed source snapshot."),
                        "evidence_spans": [heritage],
                    })
                    emitted = True
            if emitted:
                diagnostics.append({"code": "SPRING_DATA_RUNTIME_IMPLEMENTATION",
                    "message": (f"Spring Data creates the implementation of {entry['fqname']} "
                                f"({qualified_base}) at runtime; it is not in the analyzed source snapshot."),
                    "subject_ids": [source.resource_id], "evidence_ids": []})


# Bean annotations recorded as evidence on candidates.
_SPRING_STEREOTYPES = {
    "org.springframework.stereotype.Component": "@Component",
    "org.springframework.stereotype.Service": "@Service",
    "org.springframework.stereotype.Repository": "@Repository",
    "org.springframework.stereotype.Controller": "@Controller",
    "org.springframework.web.bind.annotation.RestController": "@RestController",
    "org.springframework.context.annotation.Configuration": "@Configuration",
}
_SPRING_BEAN = "org.springframework.context.annotation.Bean"
_SPRING_SELECTORS = {
    "org.springframework.context.annotation.Primary",
    "org.springframework.beans.factory.annotation.Qualifier",
    "org.springframework.context.annotation.Profile",
}
# Matches ``@Qualifier("name") Type variable`` on a field or parameter.
_INJECTION_QUALIFIER = re.compile(
    r'@(?:[\w.]+\.)?Qualifier\s*\(\s*(?:value\s*=\s*)?"([^"]*)"\s*\)\s*'
    r'(?:(?:private|protected|public|final|static|transient|volatile)\s+)*'
    r'([A-Z][\w.]*)(?:<[^;(){}=]*?>)?\s+(\w+)')
_NO_PROOF = ("Spring evidence; the active bean set and profile are runtime "
             "configuration and are not established statically")


def _spring_label(source, annotation):
    """Return the display form of a reported Spring annotation, or None."""
    qualified = java_semantic._annotation_type(source, annotation)
    if qualified in _SPRING_STEREOTYPES:
        return _SPRING_STEREOTYPES[qualified]
    if qualified in _SPRING_SELECTORS:
        return "@" + re.sub(r"\s+", " ", annotation["text"].split("@", 1)[-1])
    return None


def _resolve_written(source, written):
    """Resolve a written type name in *source* to its qualified name."""
    written = re.sub(r"<.*>", "", written)
    if "." in written:
        return written
    return source.semantic["imports"].get(written) or ".".join(
        filter(None, [source.semantic.get("package"), written]))


def _spring_selection_evidence(sources, units):
    """Attach Spring bean annotations to implementation candidates as evidence.

    Records stereotypes, @Primary, @Qualifier, @Profile and @Bean factory
    methods. Does not change a relation's targets or resolution.
    """
    test_path = re.compile(CATALOG["test_path_pattern"])
    java_sources = sorted({id(unit.source): unit.source for unit in units
                           if unit.source.language == "java"
                           and getattr(unit.source, "semantic", None)}.values(),
                          key=lambda source: source.path)

    def annotation_evidence(source, annotations):
        return [(label, (source, item["start"], item["end"])) for item in annotations
                for label in [_spring_label(source, item)] if label]

    beans, injections = {}, {}
    for source in java_sources:
        if test_path.search(source.path):
            continue
        for entry in source.semantic["types"]:
            for method in entry["methods"]:
                if not any(java_semantic._annotation_type(source, item) == _SPRING_BEAN
                           for item in method["annotations"]):
                    continue
                unit = method["unit"]
                body = source.text[unit.start:unit.end]
                created = re.search(r"\breturn\s+new\s+([A-Z][\w.]*)\s*(?:<[^>]*>)?\s*\(", body)
                if created:
                    bean = next(item for item in method["annotations"]
                                if java_semantic._annotation_type(source, item) == _SPRING_BEAN)
                    beans.setdefault(_resolve_written(source, created.group(1)), []).append((
                        (f"@Bean {entry['name']}.{method['name']}()",
                         (source, bean["start"], bean["end"])),
                        annotation_evidence(source, method["annotations"])))
        for match in _INJECTION_QUALIFIER.finditer(source.text):
            requested = _resolve_written(source, match.group(2))
            injections.setdefault(requested, []).append(
                (f'@Qualifier("{match.group(1)}") {match.group(2)} {match.group(3)} in {source.path}',
                 (source, match.start(), match.end())))

    spring_data = {}
    for source in sources:
        for entry in getattr(source, "semantic", {}).get("types", []):
            if _spring_data_base(source, entry):
                spring_data[identifier("resource", "spring-data-repository", entry["fqname"])] = (
                    entry["name"], annotation_evidence(source, entry["annotations"]))

    def candidate_evidence(unit):
        owner = getattr(unit, "semantic_method", {}).get("owner")
        if owner is None:
            return unit.owner or unit.name, []
        found = annotation_evidence(unit.source, owner["annotations"])
        for declared, selectors in beans.get(owner["fqname"], []):
            found.append(declared)
            found.extend(selectors)
        return owner["name"], found

    for source in java_sources:
        for relation in getattr(source, "semantic_relations", []):
            if relation["kind"] != "selects_implementation":
                continue
            declaration = relation["source"]
            owner = getattr(declaration, "semantic_method", {}).get("owner")
            if relation.get("outcome") == "external":
                name, found = spring_data.get(relation.get("external_target_id"), (None, []))
                explained = [(name, found)] if found else []
            else:
                candidates = ([relation["target"]] if relation.get("target")
                              else list(relation.get("candidate_targets", [])))
                explained = [candidate_evidence(unit) for unit in candidates]
            requested = injections.get(owner["fqname"], []) if owner else []
            if not any(found for _, found in explained) and not requested:
                continue
            spans = [span for _, found in explained for _, span in found]
            spans += [span for _, span in requested]
            relation["evidence_spans"] = list(relation.get("evidence_spans", [])) + spans
            if relation.get("outcome") == "exact" or not relation.get("reason"):
                continue
            parts = [f"{name}: " + (", ".join(dict.fromkeys(label for label, _ in found))
                                    or "no Spring stereotype or @Bean declaration")
                     for name, found in explained]
            if requested:
                parts.append("injection points: " + "; ".join(label for label, _ in requested))
            relation["reason"] = f"{relation['reason']} {_NO_PROOF}: " + "; ".join(parts) + "."


# Server port and context path from application config, layered in Spring
# Boot's order. Profile-specific values become separate conditional bases.
# Defaults to port 8080 at the root context.
_BOOT_CONFIGURATION = re.compile(
    r"(?:^|/)src/main/resources/(config/)?application(?:-([^/]+?))?\.(properties|ya?ml)$")
_SERVER_PORT = "server.port"
_CONTEXT_PATH = "server.servlet.contextpath"
_BOOT_DEFAULT_PORT = 8080


def _relaxed(key):
    """Normalize a property key for relaxed binding (ignore case, dashes, underscores)."""
    return key.strip().lower().replace("-", "").replace("_", "")


_ACTIVATION = _relaxed("spring.config.activate.")
_ON_PROFILE = _relaxed("spring.config.activate.on-profile")
_LEGACY_ON_PROFILE = _relaxed("spring.profiles")


def _boot_properties(source):
    """Split a Properties file into documents on ``#---`` or ``!---``."""
    documents, values, offset = [], {}, 0
    for line in source.text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if re.fullmatch(r"[#!]---", content):
            documents.append(values)
            values = {}
        entry = re.match(r"\s*([^#!=:\s][^=:\s]*)\s*[=:\s]\s*(.*?)\s*$", content)
        if entry:
            values[_relaxed(entry.group(1))] = (entry.group(2), source, offset,
                                                 offset + len(content))
        offset += len(line)
    return documents + [values]


def _boot_yaml(source):
    import yaml
    from yaml.nodes import MappingNode, ScalarNode, SequenceNode
    try:
        nodes = list(yaml.compose_all(source.text, Loader=yaml.SafeLoader))
    except (yaml.YAMLError, RecursionError):
        return []

    def walk(node, prefix, values):
        if not isinstance(node, MappingNode):
            return
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                continue
            dotted = f"{prefix}.{key.value}" if prefix else str(key.value)
            if isinstance(value, ScalarNode):
                values[_relaxed(dotted)] = (str(value.value), source,
                                            key.start_mark.index, value.end_mark.index)
            elif (isinstance(value, SequenceNode)
                  and all(isinstance(item, ScalarNode) for item in value.value)):
                values[_relaxed(dotted)] = (",".join(str(item.value) for item in value.value),
                                            source, key.start_mark.index, value.end_mark.index)
            walk(value, dotted, values)

    documents = []
    for node in nodes:
        values = {}
        walk(node, "", values)
        documents.append(values)
    return documents


def _activation(profile, values):
    """Return the condition a config document applies under, or None."""
    terms = [f"Spring profile {profile} is active"] if profile else []
    for key in sorted(values):
        if key not in (_ON_PROFILE, _LEGACY_ON_PROFILE) and not key.startswith(_ACTIVATION):
            continue
        value = values[key][0].strip()
        if not value:
            continue
        if key in (_ON_PROFILE, _LEGACY_ON_PROFILE):
            terms.append(f"Spring profile {value} is active"
                         if re.fullmatch(r"[\w.-]+", value)
                         else f"the active Spring profiles match {value}")
        else:
            terms.append(f"{key} is {value}")
    return " && ".join(dict.fromkeys(terms)) or None


def _boot_layers(all_sources, scopes):
    """Return each scope's config documents as ``(condition, values)``, lowest precedence first."""
    layers = {}
    for source in all_sources:
        found = _BOOT_CONFIGURATION.search(source.path)
        if not found or source.service_scope not in scopes:
            continue
        config_dir, profile, extension = found.groups()
        documents = _boot_properties(source) if extension == "properties" else _boot_yaml(source)
        order = (profile is not None, config_dir is not None, extension == "properties",
                 profile or "", source.path)
        for index, values in enumerate(documents):
            layers.setdefault(source.service_scope, []).append(
                (order, index, _activation(profile, values), values))
    return {scope: [(condition, values) for _, _, condition, values in sorted(
                entries, key=lambda entry: entry[:2])]
            for scope, entries in layers.items()}


def _merged(layers, condition=None):
    values = {}
    for applies, document in layers:
        if applies is None or applies == condition:
            values.update(document)
    return values


def _served_at(values):
    return tuple((values.get(key) or (None,))[0] for key in (_SERVER_PORT, _CONTEXT_PATH))


def endpoint_bases(sources, all_sources):
    """Return the server bases for each selected service scope."""
    scopes = sorted({source.service_scope for source in sources})
    layers = _boot_layers(all_sources, set(scopes))
    bases = []
    for scope in scopes:
        scoped = layers.get(scope, [])
        default = _merged(scoped)
        variants = []
        for condition in dict.fromkeys(applies for applies, _ in scoped if applies):
            values = _merged(scoped, condition)
            if _served_at(values) != _served_at(default):
                variants.append((condition, values))
        active = default.get(_PROFILES_ACTIVE)
        declared_active = ({name.strip() for name in active[0].split(",")}
                           if active and "${" not in active[0] else set())
        selected = {condition for condition, _ in variants
                    if condition.removeprefix("Spring profile ").removesuffix(" is active")
                    in declared_active}
        otherwise = " && ".join(f"!({condition})" for condition, _ in variants) or None
        for condition, values in [(otherwise, default)] + variants:
            port_entry, path_entry = values.get(_SERVER_PORT), values.get(_CONTEXT_PATH)
            if port_entry and not port_entry[0].isdigit():
                continue
            port = int(port_entry[0]) if port_entry else _BOOT_DEFAULT_PORT
            path = http_base_path(path_entry[0] if path_entry else "")
            declared = [f"{name}={entry[0]} in {entry[1].path}"
                        for name, entry in (("server.port", port_entry),
                                            ("server.servlet.context-path", path_entry)) if entry]
            if not port_entry:
                declared.append(f"Spring Boot default port {_BOOT_DEFAULT_PORT}")
            if not path_entry:
                declared.append("Spring Boot default root context path")
            spans = [entry[1:] for entry in (port_entry, path_entry) if entry]
            if condition in selected or condition == otherwise and selected:
                declared.append(f"spring.profiles.active={active[0]} in {active[1].path} "
                                + ("selects this profile" if condition in selected
                                   else "selects an overriding profile")
                                + ", unless overridden at runtime")
                spans.append(active[1:])
            bases.append({
                "scope": scope, "role": "implementation", "source_id": None,
                "port": port, "path": path, "label": ", ".join(declared),
                "condition": condition, "evidence_spans": spans,
            })
    return bases

# Persistence: table reads/writes from JDBC SQL, SimpleJdbcInsert,
# EntityManager, JPQL and @Query. Unknown tables stay unresolved.

_PROFILES_ACTIVE = "spring.profiles.active"
_JDBC_TEMPLATES = {"JdbcTemplate", "NamedParameterJdbcTemplate", "JdbcOperations",
                   "NamedParameterJdbcOperations"}
_JDBC_STATEMENTS = {"query", "queryForObject", "queryForList", "queryForMap",
                    "queryForRowSet", "queryForStream", "update", "batchUpdate", "execute"}
_JDBC_INSERTS = {"execute", "executeAndReturnKey", "executeAndReturnKeyHolder", "executeBatch"}
_ENTITY_WRITES = {"persist", "merge", "remove"}
_ENTITY_READS = {"find", "getReference"}
_DERIVED_READ = re.compile(r"(?:find|read|get|query|search|stream|count|exists)(?:[A-Z]\w*)?$")
_DERIVED_WRITE = re.compile(r"(?:save|delete|remove)(?:[A-Z]\w*)?$")
_MEMBER_CALL = re.compile(r"\b(?:this\s*\.\s*)?([A-Za-z_]\w*)\s*\.\s*([A-Za-z_]\w*)\s*\(")
_JPQL_REFERENCE = re.compile(
    r"(?i)\b(from|join(?:\s+fetch)?|update)\s+([A-Za-z_][\w.]*)(?:\s+(?:as\s+)?([A-Za-z_]\w*))?")
_JPQL_KEYWORDS = {"where", "order", "group", "left", "right", "inner", "outer", "join", "set",
                  "having", "on", "fetch", "union"}


def configure(sources, all_sources):
    """Record each scope's declared default ``spring.profiles.active``."""
    scopes = {source.service_scope for source in sources}
    declared = {}
    for scope, layers in _boot_layers(all_sources, scopes).items():
        entry = _merged(layers).get(_PROFILES_ACTIVE)
        if entry and "${" not in entry[0]:
            declared[scope] = entry
    for source in sources:
        source.spring_declared_profiles = declared.get(source.service_scope)


def _java_mask(text):
    """Blank out comments and literal contents in *text*, keeping its length."""
    out, index = list(text), 0
    while index < len(text):
        if text.startswith("//", index):
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
        elif text.startswith('"""', index):
            end = text.find('"""', index + 3)
            end = len(text) if end < 0 else end + 3
            for position in range(index + 3, end - 3):
                out[position] = " "
            index = end
            continue
        elif text[index] in "\"'":
            quote, end = text[index], index + 1
            while end < len(text) and text[end] != quote:
                end += 2 if text[end] == "\\" else 1
            for position in range(index + 1, min(end, len(text))):
                out[position] = " "
            index = end + 1
            continue
        else:
            index += 1
            continue
        for position in range(index, end):
            out[position] = " "
        index = end
    return "".join(out)


def _closing(masked, opening):
    depth = 0
    for index in range(opening, len(masked)):
        if masked[index] in "([{":
            depth += 1
        elif masked[index] in ")]}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _top_level(masked, start, end, separator):
    pieces, depth, begin = [], 0, start
    for index in range(start, end):
        character = masked[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == separator and depth == 0:
            pieces.append((begin, index))
            begin = index + 1
    pieces.append((begin, end))
    return pieces


def _string_value(text, masked, start, end):
    """Return the string a Java expression builds, with runtime parts as ``:p``."""
    parts, literal = [], False
    for left, right in _top_level(masked, start, end, "+"):
        piece = text[left:right].strip()
        if piece.startswith('"""') and piece.endswith('"""') and len(piece) >= 6:
            parts.append(piece[3:-3])
            literal = True
        elif len(piece) >= 2 and piece[0] == '"' and piece[-1] == '"':
            parts.append(re.sub(r"\\(.)", r"\1", piece[1:-1]))
            literal = True
        else:
            parts.append(":p")
    return " ".join(" ".join(parts).split()) if literal else None


def _type_name(written):
    """Return the simple element type name, unwrapping one collection."""
    written = (written or "").strip()
    generic = re.search(r"<\s*([\w.]+)\s*>", written)
    return (generic.group(1) if generic else re.sub(r"<.*", "", written)).rsplit(".", 1)[-1]


def _annotation_strings(annotation):
    return re.findall(r'"((?:[^"\\]|\\.)*)"', annotation["text"])


def _java_types(units):
    sources = {id(unit.source): unit.source for unit in units
               if unit.source.language == "java" and getattr(unit.source, "semantic", None)}
    return [(source, entry) for source in sources.values()
            for entry in source.semantic["types"]]


def _entities(types):
    """Return JPA entities by name with their table and span."""
    entities = {}
    for source, entry in types:
        annotations = {item["name"]: item for item in entry["annotations"]}
        if "Entity" not in annotations:
            continue
        declared = re.search(r'name\s*=\s*"([^"]+)"', annotations["Entity"]["text"])
        table = annotations.get("Table")
        name = re.search(r'name\s*=\s*"([^"]+)"', table["text"]) if table else None
        entities[declared.group(1) if declared else entry["name"]] = {
            "entry": entry, "table": name.group(1) if name else None,
            "span": (source, table["start"], table["end"]) if table else None}
    return entities


def _table_resource(name, known, entity=None):
    if name and name.casefold() in known:
        return {"kind": "table", "name": name, "resolution": "resolved", "reason": None}
    if name:
        return {"kind": "table", "name": name, "resolution": "unresolved",
                "reason": f"Table {name} is named in source but not declared in the analyzed schema."}
    return {"kind": "entity", "name": entity, "resolution": "unresolved",
            "reason": (f"JPA entity {entity} declares no @Table; its physical table follows a "
                       "runtime naming strategy.")}


# sqlglot is loaded once. If it is missing or the wrong version, SQL is left
# unparsed and reported instead of failing extraction.
_SQL_PARSER = {}


def _sql_parser():
    if "module" not in _SQL_PARSER:
        try:
            _SQL_PARSER["module"] = registry.load_trusted_parser("sqlglot")
        except Exception as exc:
            _SQL_PARSER.update(module=None, error=type(exc).__name__)
    return _SQL_PARSER["module"]


def _sql_accesses(sql, known):
    """Return ``(kind, resource)`` pairs a SQL statement reads and writes, or None."""
    sqlglot = _sql_parser()
    if sqlglot is None:
        _SQL_PARSER["skipped"] = _SQL_PARSER.get("skipped", 0) + 1
        return None
    expressions = sqlglot.exp
    try:
        tree = sqlglot.parse_one(sql)
    except Exception:
        return None
    tables = [table.name for table in tree.find_all(expressions.Table) if table.name]
    if isinstance(tree, (expressions.Insert, expressions.Update, expressions.Delete)):
        written = next((table.name for table in tree.this.find_all(expressions.Table)), None) \
            if isinstance(tree.this, expressions.Expression) else None
        written = written or (tables[0] if tables else None)
        if not written:
            return None
        reads = sorted({name for name in tables if name.casefold() != written.casefold()})
        return [("data_write", _table_resource(written, known))] + [
            ("data_read", _table_resource(name, known)) for name in reads]
    if isinstance(tree, (expressions.Select, expressions.Union)):
        return [("data_read", _table_resource(name, known)) for name in sorted(set(tables))]
    return None


def _jpql_accesses(jpql, entities, known):
    """Return ``(kind, resource)`` pairs a JPQL statement reads and writes, or None."""
    statement = jpql.strip().lower()
    if statement.startswith(("update", "delete")):
        writes = True
    elif statement.startswith(("select", "from")):
        writes = False
    else:
        return None
    aliases, referenced = {}, []
    for found in _JPQL_REFERENCE.finditer(jpql):
        name, alias = found.group(2), found.group(3)
        if alias and alias.lower() in _JPQL_KEYWORDS:
            alias = None
        if "." in name:
            head, field = name.split(".", 1)
            owner = entities.get(aliases.get(head, ""))
            written = owner["entry"]["fields"].get(field.split(".")[0]) if owner else None
            target = _type_name(written) if written else None
            target = target if target in entities else None
        else:
            target = name if name in entities else None
        if target is None:
            return None
        if alias:
            aliases[alias] = target
        if target not in referenced:
            referenced.append(target)
    if not referenced:
        return None
    resources = [_table_resource(entities[name]["table"], known, name) for name in referenced]
    if writes:
        return [("data_write", resources[0])] + [("data_read", item) for item in resources[1:]]
    return [("data_read", item) for item in resources]


def _operation(unit, position, end, kind, resource, protocol, gaps=(), condition=None):
    return {"position": position, "end": end, "kind": kind, "resource": resource,
            "protocol": protocol, "condition": condition, "supporting": [],
            "gaps": [*gaps] + ([{"projection": "target", "code": "JAVA_DATA_TARGET_UNRESOLVED",
                                 "reason": resource["reason"]}]
                               if resource["resolution"] != "resolved" else [])}


def _statement_operations(source, entry, method, entities, known):
    """Return the persistence statements in a method body."""
    unit = method["unit"]
    text = unit.text
    masked = _java_mask(text)
    fields = entry["fields"]
    inserts = {}
    owner_text = source.text[entry["unit"].start:entry["unit"].end]
    for found in re.finditer(r"(?:this\s*\.\s*)?(\w+)\s*=\s*new\s+SimpleJdbcInsert\b[^;]*?"
                             r'\.withTableName\(\s*"([^"]+)"\s*\)', owner_text):
        if _type_name(fields.get(found.group(1))) == "SimpleJdbcInsert":
            inserts[found.group(1)] = found.group(2)
    parameters = dict(method["params"])
    result = []
    for found in _MEMBER_CALL.finditer(masked):
        receiver, name = found.group(1), found.group(2)
        receiver_type = _type_name(fields.get(receiver))
        opening = found.end() - 1
        closing = _closing(masked, opening)
        if closing < 0:
            continue
        span = (found.start(), closing + 1)
        arguments = _top_level(masked, opening + 1, closing, ",")
        accesses, protocol = None, "sql"
        if receiver_type in _JDBC_TEMPLATES and name in _JDBC_STATEMENTS and arguments:
            sql = _string_value(text, masked, *arguments[0])
            accesses = _sql_accesses(sql, known) if sql else None
        elif receiver_type == "SimpleJdbcInsert" and name in _JDBC_INSERTS and receiver in inserts:
            accesses = [("data_write", _table_resource(inserts[receiver], known))]
        elif receiver_type == "EntityManager" and name in {"createQuery", "createNativeQuery"} \
                and arguments:
            statement = _string_value(text, masked, *arguments[0])
            if statement:
                accesses = (_sql_accesses(statement, known) if name == "createNativeQuery"
                            else _jpql_accesses(statement, entities, known))
                protocol = "sql" if name == "createNativeQuery" else "jpql"
        elif receiver_type == "EntityManager" and name in _ENTITY_READS and arguments:
            first = text[arguments[0][0]:arguments[0][1]].strip()
            entity = re.fullmatch(r"([A-Za-z_]\w*)\s*\.\s*class", first)
            if entity and entity.group(1) in entities:
                accesses = [("data_read", _table_resource(
                    entities[entity.group(1)]["table"], known, entity.group(1)))]
                protocol = "jpa"
        elif receiver_type == "EntityManager" and name in _ENTITY_WRITES and arguments:
            argument = masked[arguments[0][0]:arguments[0][1]]
            typed = {_type_name(parameters[word]) for word in re.findall(r"\b[a-z_]\w*\b", argument)
                     if word in parameters and _type_name(parameters[word]) in entities}
            if len(typed) == 1:
                entity = typed.pop()
                accesses = [("data_write", _table_resource(entities[entity]["table"], known, entity))]
                protocol = "jpa"
        for kind, resource in accesses or ():
            result.append(_operation(unit, *span, kind, resource, protocol))
    return result


def _query_operations(source, method, entities, known):
    """Return the operation declared by a repository method's ``@Query``."""
    annotation = next((item for item in method["annotations"] if item["name"] == "Query"), None)
    if annotation is None or not source.semantic["imports"].get("Query", "").startswith(
            "org.springframework.data."):
        return []
    values = _annotation_strings(annotation)
    if not values:
        return []
    native = re.search(r"nativeQuery\s*=\s*true", annotation["text"])
    accesses = (_sql_accesses(values[0], known) if native
                else _jpql_accesses(values[0], entities, known))
    unit = method["unit"]
    start = annotation["start"] - unit.start
    if accesses is None or start < 0:
        return []
    return [_operation(unit, start, annotation["end"] - unit.start, kind, resource,
                       "sql" if native else "jpql") for kind, resource in accesses]


def _profile_guard(entry):
    """Return a type's @Profile names, () if unconditional, None if unknown."""
    annotation = next((item for item in entry["annotations"] if item["name"] == "Profile"), None)
    if annotation is None:
        return (), None
    values = _annotation_strings(annotation)
    if not values or any(not re.fullmatch(r"!?[\w.-]+", value) for value in values):
        return None, annotation
    return tuple(values), annotation


def _active(values, profiles):
    if not values:
        return True
    return any((value[1:] not in profiles) if value.startswith("!") else (value in profiles)
               for value in values)


def _spring_data_routes(types):
    """Return, per repository declaration, whether Spring Data serves it by redeclaration or proxy."""
    by_unit = {id(entry["unit"]): entry for _, entry in types}
    routes = {}
    for source, entry in types:
        base = _spring_data_base(source, entry)
        if base is None:
            continue
        domain = re.search(r"<\s*([\w.]+)\s*,", next((name for name in entry["bases"]
                           if re.sub(r"<.*>", "", name).rsplit(".", 1)[-1] == base[1]), ""))
        interfaces, queue = [entry], [entry]
        while queue and len(interfaces) <= 32:
            current = queue.pop(0)
            for relation in getattr(current["unit"].source, "semantic_relations", []):
                parent = getattr(relation.get("target"), "semantic_type", None) or by_unit.get(
                    id(relation.get("target")))
                if (relation["source"] is current["unit"] and relation["kind"] == "inherits"
                        and parent is not None and parent.get("kind") == "interface_declaration"
                        and all(parent is not seen for seen in interfaces)):
                    interfaces.append(parent)
                    queue.append(parent)
        for interface in interfaces[1:]:
            for method in interface["methods"]:
                declaration = method["unit"]
                if declaration.executable_body:
                    continue
                redeclared = next((own for own in entry["methods"]
                                   if _same_signature(own, method)), None)
                routes.setdefault(id(declaration), []).append({
                    "repository": entry, "source": source,
                    "domain": domain.group(1).rsplit(".", 1)[-1] if domain else None,
                    "redeclaration": redeclared["unit"] if redeclared else None,
                    "method": method, "heritage": _heritage_span(entry, base[1])})
    return routes


def _persistence(sources, units, diagnostics=None):
    types = _java_types(units)
    entities = _entities(types)
    known = {unit.name.casefold() for unit in units
             if unit.source.language == "sql" and unit.kind == "type"}
    test_path = re.compile(CATALOG["test_path_pattern"])
    declarations = {}
    unparsed = set()
    for source, entry in types:
        if test_path.search(source.path):
            continue
        skipped = _SQL_PARSER.get("skipped", 0)
        for method in entry["methods"]:
            unit = method["unit"]
            declarations[id(unit)] = (source, entry, method)
            found = (_statement_operations(source, entry, method, entities, known)
                     if unit.executable_body else _query_operations(source, method, entities, known))
            if found:
                unit.persistence_operations = getattr(unit, "persistence_operations", []) + found
        if _SQL_PARSER.get("skipped", 0) > skipped:
            unparsed.add(source.resource_id)
    if diagnostics is not None:
        for resource_id in sorted(unparsed):
            diagnostics.append({"code": "SPRING_SQL_PARSER_UNAVAILABLE",
                "message": f"java: sqlglot {_SQL_PARSER['error']}; SQL statements were not parsed",
                "subject_ids": [resource_id], "evidence_ids": []})
    declared = {source.service_scope: source.spring_declared_profiles for source in sources
                if getattr(source, "spring_declared_profiles", None)}
    routes = _spring_data_routes(types)
    owners = {id(method["unit"]): (source, entry) for source, entry in types
              for method in entry["methods"]}
    for key, (source, _, method) in declarations.items():
        declaration = method["unit"]
        if declaration.executable_body or declaration.trace_role not in {"interface", "abstract_declaration"}:
            continue
        setting = declared.get(source.service_scope)
        if not setting:
            continue
        profiles = {value.strip() for value in setting[0].split(",") if value.strip()}
        candidates = []
        for target in _selected(_selection(declaration)):
            guard, annotation = _profile_guard(owners[id(target)][1])
            candidates.append(("source", target, guard, annotation, owners[id(target)][1]["name"]))
        fragment_routed = any(owners[id(target)][1]["name"].startswith("SpringData")
                              and owners[id(target)][1]["name"].endswith("Impl")
                              for target in _selected(_selection(declaration)))
        for route in routes.get(key, []):
            guard, annotation = _profile_guard(route["repository"])
            if route["redeclaration"] is not None:
                candidates.append(("query", route["redeclaration"], guard, annotation,
                                   route["repository"]["name"]))
            elif not fragment_routed:
                candidates.append(("proxy", route, guard, annotation, route["repository"]["name"]))
        if len(candidates) < 2 or any(candidate[2] is None for candidate in candidates):
            continue
        active = [candidate for candidate in candidates if _active(candidate[2], profiles)]
        if len(active) != 1:
            continue
        kind, target, _, annotation, owner = active[0]
        property_source, start, end = setting[1], setting[2], setting[3]
        condition = (f"{_PROFILES_ACTIVE}={setting[0]} declared in {property_source.path} activates "
                     f"{owner} ({annotation['text'] if annotation else 'no @Profile'}); a runtime "
                     "profile override can select another implementation")
        inactive = [f"{candidate[4]} ({candidate[3]['text'] if candidate[3] else 'no @Profile'})"
                    for candidate in candidates if candidate is not active[0]]
        if kind in {"source", "query"}:
            spans = [(property_source, start, end), (target.source, target.start, target.end)] + [
                (candidate[3] and owners_span(candidate)) for candidate in candidates]
            source.semantic_relations.append({
                "source": declaration, "target": target, "candidate_targets": [target],
                "kind": "selects_implementation", "start": declaration.start, "end": declaration.end,
                "resolution": "resolved", "outcome": "exact", "reason": None,
                "condition": condition + "; inactive under it: " + ", ".join(inactive),
                "evidence_spans": [span for span in spans if span]})
            continue
        route = target
        entity = entities.get(route["domain"] or "")
        name = declaration.name
        operation = ("data_write" if _DERIVED_WRITE.match(name)
                     else "data_read" if _DERIVED_READ.match(name) else None)
        if entity is None or operation is None:
            continue
        resource = _table_resource(entity["table"], known, route["domain"])
        gap = {"projection": "condition", "code": "SPRING_DATA_GENERATED_QUERY",
               "reason": (f"Spring Data implements {name} at runtime for {owner} with domain type "
                          f"{route['domain']}; the table follows from that type's mapping, and the "
                          "generated SQL is not in source.")}
        declaration.persistence_operations = getattr(declaration, "persistence_operations", []) + [
            _operation(declaration, 0, len(declaration.text), operation, resource, "spring-data",
                       [gap], condition)]


def _profile_alternatives(units, diagnostics):
    """Split an ambiguous selection into one conditional selection per @Profile.

    Applies only when every candidate has a known @Profile and the list is not
    truncated; otherwise the selection stays ambiguous.
    """
    # The declaring interface may be in a source Spring was not selected for.
    sources = sorted({id(unit.source): unit.source for unit in units
                      if unit.source.language == "java"
                      and getattr(unit.source, "semantic", None)}.values(),
                     key=lambda source: source.path)
    repositories = {}
    for source in sources:
        for entry in getattr(source, "semantic", {}).get("types", []):
            if _spring_data_base(source, entry):
                repositories[identifier("resource", "spring-data-repository", entry["fqname"])] = entry

    def gate(entry):
        guard, annotation = _profile_guard(entry) if entry else (None, None)
        if not guard:
            return None
        return (f"{annotation['text']} on {entry['name']} matches the active Spring profiles",
                (entry["unit"].source, annotation["start"], annotation["end"]))

    for source in sources:
        relations = getattr(source, "semantic_relations", None)
        if not relations:
            continue
        rewritten = []
        for relation in relations:
            if (relation["kind"] != "selects_implementation" or relation.get("outcome") != "ambiguous"
                    or len(relation["candidate_targets"]) >= MAX_SEMANTIC_CANDIDATES):
                rewritten.append(relation)
                continue
            declaration = relation["source"]
            gates = [(unit, gate(getattr(unit, "semantic_method", {}).get("owner")))
                     for unit in relation["candidate_targets"]]
            proxies = [other for other in relations if other["source"] is declaration
                       and other["kind"] == "selects_implementation"
                       and other.get("outcome") == "external"]
            proxy_gates = [(other, gate(repositories.get(other.get("external_target_id"))))
                           for other in proxies]
            if any(found is None for _, found in gates + proxy_gates):
                rewritten.append(relation)
                continue
            for other, (condition, span) in proxy_gates:
                other["condition"] = condition
                other["evidence_spans"] = list(other.get("evidence_spans", [])) + [span]
            for unit, (condition, span) in gates:
                rewritten.append({"source": declaration, "target": unit, "candidate_targets": [unit],
                    "kind": "selects_implementation", "start": relation["start"], "end": relation["end"],
                    "resolution": "resolved", "outcome": "exact", "reason": None,
                    "condition": condition,
                    "evidence_spans": [(unit.source, unit.start, unit.end), span]})
            # Drop the earlier ambiguity diagnostics. They end with ';' or, with
            # Spring Data fragments, ','.
            named = tuple(f" implement {declaration.semantic_identity}{mark}" for mark in ";,")
            diagnostics[:] = [item for item in diagnostics
                              if not (item.get("code") == "JAVA_IMPLEMENTATION_AMBIGUOUS"
                                      and any(text in (item.get("message") or "")
                                              for text in named))]
        source.semantic_relations = rewritten


def owners_span(candidate):
    annotation = candidate[3]
    target = candidate[1] if candidate[0] != "proxy" else candidate[1]["repository"]["unit"]
    return (target.source, annotation["start"], annotation["end"])
