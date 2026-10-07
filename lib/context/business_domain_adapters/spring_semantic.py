"""Evidence-activated Spring endpoint enricher for normalized Java units."""
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
# Annotations on outbound HTTP client interfaces. Their mappings describe the
# remote endpoint being called, not an endpoint this service exposes.
_CLIENT_ANNOTATIONS = frozenset({"FeignClient", "HttpExchange"})
# A route evidenced only through a constant or expression. It must not
# collapse into the empty route, which would claim a different endpoint.
_DYNAMIC_ROUTE = "\0dynamic"
_STRING_LITERAL = r'"(?:[^"\\]|\\.)*"'


def _paths(text):
    """Return the route values of a mapping annotation.

    Only ``value``/``path`` or the first positional argument carry routes;
    ``produces``, ``consumes``, ``params``, ``headers`` and ``name`` do not.
    """
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
        if name in _MAPPING_METHODS:
            mappings.extend((_MAPPING_METHODS[name], path, annotation) for path in _paths(text))
        elif name == "RequestMapping":
            methods = _request_methods(text)
            mappings.extend((method if methods else None, path, annotation)
                            for method in (methods or [None]) for path in _paths(text))
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
            (owner["unit"].source, annotation["start"], annotation["end"])
            for owner, annotation in ((base_owner, base_annotation),
                (mapping_owner, mapping_annotation))
            if annotation
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


# Spring property conditions. A literal @ConditionalOnProperty links to the
# repository declarations of its key; which declaration takes effect when
# deployed is never decided here.
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
                # Spring's relaxed binding matches app.featureEnabled to
                # app.feature-enabled. The binding is named by the declared key,
                # so declarations spelled differently keep the exact one only.
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
                    # The Java adapter already selects implementations for every
                    # interface method, as one relation per declaration that may
                    # name this method as its target or among its candidates.
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
    return pending


# Spring Data repository interfaces: a project interface extending one of
# these is implemented by a proxy Spring Data creates at runtime.
_SPRING_DATA_PACKAGE = "org.springframework.data."


def _spring_data_base(source, entry):
    """``(qualified name, written name)`` of the Spring Data repository type *entry* extends."""
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
    """The span naming *simple* in *entry*'s ``extends`` clause, or the whole declaration."""
    unit = entry["unit"]
    text = unit.source.text[unit.start:unit.end]
    match = re.search(r"\bextends\b[^{]*?\b" + re.escape(simple) + r"\b", text)
    if not match:
        return unit.source, unit.start, unit.end
    start = unit.start + match.end() - len(simple)
    return unit.source, start, start + len(simple)


def _selection(declaration):
    """The Java adapter's source-implementation relation for *declaration*, if any."""
    return next((relation for relation in getattr(declaration.source, "semantic_relations", [])
                 if relation["source"] is declaration
                 and relation["kind"] == "selects_implementation"
                 and relation.get("outcome") != "external"), None)


def _selected(relation):
    if relation is None:
        return []
    return [relation["target"]] if relation.get("target") else list(relation["candidate_targets"])


def _add_source_candidates(declaration, additions, evidence_spans, diagnostics):
    """Join *additions* to *declaration*'s source implementations, keeping every candidate."""
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
    """Represent what a Spring Data repository proxy implements, without choosing it.

    A project interface extending a Spring Data repository type is implemented
    at runtime. Each abstract method it declares or inherits from a project
    interface gains an external implementation candidate: a resource standing
    for the generated proxy, kept beside, never instead of, the source classes
    that also implement the method. Spring Data routes a method to a custom
    fragment instead when one of the repository's parent interfaces has an
    implementation named ``<Fragment>Impl`` or ``<Repository>Impl``, its default
    naming; that implementation is real source, so it joins the method's
    ordinary candidates and no external candidate is added. Which candidate is
    active is a matter of configuration and is not decided here.
    """
    for source in sources:
        for entry in getattr(source, "semantic", {}).get("types", []):
            base = _spring_data_base(source, entry)
            if base is None:
                continue
            qualified_base, simple_base = base
            heritage = _heritage_span(entry, simple_base)
            # The repository and every project interface it inherits, through the
            # Java adapter's resolved heritage relations.
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


# Spring's own words for what makes a class a bean and how one bean is
# preferred, narrowed or switched on. Each is evidence about a candidate; none
# decides which candidate runs.
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
# ``@Qualifier("name") Type variable`` on a field or a constructor/method
# parameter: the type a bean is requested by and the name it is narrowed to.
_INJECTION_QUALIFIER = re.compile(
    r'@(?:[\w.]+\.)?Qualifier\s*\(\s*(?:value\s*=\s*)?"([^"]*)"\s*\)\s*'
    r'(?:(?:private|protected|public|final|static|transient|volatile)\s+)*'
    r'([A-Z][\w.]*)(?:<[^;(){}=]*?>)?\s+(\w+)')
_NO_PROOF = ("Spring evidence; the active bean set and profile are runtime "
             "configuration and are not established statically")


def _spring_label(source, annotation):
    """The written form of a Spring annotation SPEED reports, or None."""
    qualified = java_semantic._annotation_type(source, annotation)
    if qualified in _SPRING_STEREOTYPES:
        return _SPRING_STEREOTYPES[qualified]
    if qualified in _SPRING_SELECTORS:
        return "@" + re.sub(r"\s+", " ", annotation["text"].split("@", 1)[-1])
    return None


def _resolve_written(source, written):
    """The qualified name a written type refers to in *source*: in full, imported, or same package."""
    written = re.sub(r"<.*>", "", written)
    if "." in written:
        return written
    return source.semantic["imports"].get(written) or ".".join(
        filter(None, [source.semantic.get("package"), written]))


def _spring_selection_evidence(sources, units):
    """Explain each implementation candidate in Spring's terms, without choosing one.

    For every candidate of a ``selects_implementation`` relation, the class's
    Spring stereotype, ``@Primary``, ``@Qualifier`` and ``@Profile``, and any
    ``@Bean`` method that returns a new instance of it, are attached as evidence
    spans and, on an unsettled selection, named in its reason. Qualifiers
    written at injection points that request the declaring type are recorded
    the same way. A candidate with none of this is kept and said to have none:
    a class can be created with ``new``. Configuration files are not read, and
    nothing here changes a relation's targets, candidates or resolution.
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


# Where Spring Boot serves the endpoints of a service. The application
# configuration on the main classpath names the port and the servlet context
# path. Its documents layer in Spring Boot's order: the classpath root before
# config/, YAML before Properties in one location, profile-specific files
# after the others, and later documents of one file after earlier ones. A
# document applies unconditionally unless its file is profile-specific or it
# activates on a profile (``spring.config.activate.on-profile``). Each
# activation that changes the port or context path is a separate base that
# applies only under it, and the default base then applies only while none of
# those does. A declared ``spring.profiles.active`` is named on the bases it
# selects but never assumed, because a runtime override can change it.
# Without any declaration, Spring Boot listens on 8080 at the root context.
_BOOT_CONFIGURATION = re.compile(
    r"(?:^|/)src/main/resources/(config/)?application(?:-([^/]+?))?\.(properties|ya?ml)$")
_SERVER_PORT = "server.port"
_CONTEXT_PATH = "server.servlet.contextpath"
_BOOT_DEFAULT_PORT = 8080


def _relaxed(key):
    """Spring Boot's relaxed binding: case, dashes and underscores do not count."""
    return key.strip().lower().replace("-", "").replace("_", "")


_ACTIVATION = _relaxed("spring.config.activate.")
_ON_PROFILE = _relaxed("spring.config.activate.on-profile")
_LEGACY_ON_PROFILE = _relaxed("spring.profiles")


def _boot_properties(source):
    """The documents of a Properties file; ``#---`` or ``!---`` separates them."""
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
    """The condition under which one configuration document applies, or None."""
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
    """Each scope's configuration documents as ``(condition, values)``, lowest precedence first."""
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
    """Server bases of every service scope this enricher was selected for."""
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

# Persistence
#
# What a repository operation reads or writes, and which implementation runs
# under the profiles the project declares. Each statement the source spells
# out (Spring JDBC SQL, SimpleJdbcInsert, EntityManager calls, JPQL, @Query)
# becomes a data read or write on the table its text or its entity's @Table
# names; a table name the schema does not declare stays unresolved. The
# declared ``spring.profiles.active`` conditions an additional implementation
# selection when it activates exactly one candidate; the static selection and
# every inactive candidate are kept, and the condition names the property
# because a runtime override can change it. A repository method the active
# Spring Data proxy implements at runtime reads or writes its domain type's
# table by Spring Data's contract; the SQL it generates is not in source and
# that operation stays unresolved.

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
    """*text* with comments and the contents of literals blanked, length preserved."""
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
    """The string a Java expression spells, runtime pieces as ``:p`` parameters."""
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
    """The simple element type a declared type names, unwrapping one collection."""
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
    """JPA entities by entity name, each with its declared table and evidence span."""
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


# The trusted sqlglot parser, verified and loaded once per process. A missing or
# mismatched install leaves SQL statements unparsed and is reported, rather than
# aborting extraction.
_SQL_PARSER = {}


def _sql_parser():
    if "module" not in _SQL_PARSER:
        try:
            _SQL_PARSER["module"] = registry.load_trusted_parser("sqlglot")
        except Exception as exc:
            _SQL_PARSER.update(module=None, error=type(exc).__name__)
    return _SQL_PARSER["module"]


def _sql_accesses(sql, known):
    """``(kind, resource)`` pairs one SQL statement reads and writes, or None."""
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
    """``(kind, resource)`` pairs a JPQL statement reads and writes, or None."""
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
    """Persistence statements one method body spells out."""
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
    """The operation a repository method's ``@Query`` declares."""
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
    """The profiles a type's @Profile names, () when unconditional, None when not decidable."""
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
    """Per repository declaration, how Spring Data serves it: redeclared or by its proxy."""
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


def owners_span(candidate):
    annotation = candidate[3]
    target = candidate[1] if candidate[0] != "proxy" else candidate[1]["repository"]["unit"]
    return (target.source, annotation["start"], annotation["end"])
