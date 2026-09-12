"""Evidence-activated Spring endpoint enricher for normalized Java units."""
from __future__ import annotations

import re

from .base import (declare_anchor_registration, declare_anchor_representation,
                   declare_trace_contract, http_identity)


_MAPPING_METHODS = {
    "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
    "PatchMapping": "PATCH", "DeleteMapping": "DELETE",
}


def _paths(text):
    quoted = re.findall(r'["\']([^"\']*)["\']', text)
    return quoted or [""]


def _mappings(annotations):
    mappings = []
    for annotation in annotations:
        name, text = annotation["name"], annotation["text"]
        if name in _MAPPING_METHODS:
            mappings.extend((_MAPPING_METHODS[name], path, annotation) for path in _paths(text))
        elif name == "RequestMapping":
            methods = re.findall(r"RequestMethod\.(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)", text)
            mappings.extend((method if methods else None, path, annotation)
                            for method in (methods or [None]) for path in _paths(text))
    return mappings


def _join(*parts):
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
        unit.anchor_resolution = "resolved" if http_method else "unresolved"
        unit.anchor_reason = None if http_method else (
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


def prepare(sources, units, diagnostics=None):
    diagnostics = diagnostics if diagnostics is not None else []
    all_types = [item for source in sources for item in getattr(source, "semantic", {}).get("types", [])]
    by_unit = {id(item["unit"]): item for item in all_types}
    for interface in (item for item in all_types
                      if item["kind"] == "interface_declaration"):
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
                    if not any(existing["source"] is reverse["source"] and
                               existing["target"] is reverse["target"] and
                               existing["kind"] == reverse["kind"]
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
