"""HTML form and template semantics over declarative tree-sitter rules."""
from __future__ import annotations

import re

from . import rules
from .base import (declare_anchor_registration, declare_anchor_representation,
                   declare_operation_observation, declare_trace_contract)


PREPARE_PHASE = 50


def extract(source):
    units = rules.extract(source)
    form_spans = {rules.span(source, match) for match in source.rule_outputs
                  if match.rule_id == 'html-form-definition'}
    for unit in units:
        unit.html_form = (unit.start, unit.end) in form_spans
    return units


def prepare(sources, units, diagnostics=None):
    rules.prepare(sources, units, diagnostics)
    for source in sources:
        for unit in source.units:
            if not getattr(unit, 'html_form', False):
                continue
            unit.anchor_kind = 'ui'
            unit.anchor_resolution = 'resolved'
            unit.anchor_reason = None
            identity = f'ui:{source.service_scope}:form:{source.path}:{unit.start}'
            declare_anchor_representation(unit, 'exposure', identity, 'eligible', 'external')
            declare_anchor_registration(unit, 'action', event='submit', target=unit.name,
                scope=source.service_scope, resolution='resolved', reason=None)
            declare_trace_contract(unit, 'implementation')


def activation_evidence(source):
    return {}


def _attribute(text):
    match = re.fullmatch(
        r'\s*([^\s=]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))\s*', text,
        re.DOTALL)
    if not match:
        return None, None
    return match.group(1), next(value for value in match.groups()[1:]
                                     if value is not None)


def calls(unit):
    result = []
    for match in unit.source.rule_outputs:
        if match.output_type != 'template_binding' \
                or match.attributes.get('binding_kind') != 'event':
            continue
        start, end = rules.span(unit.source, match)
        if not rules.owns(unit, start, end):
            continue
        _, expression = _attribute(match.text)
        expression = expression or ''
        handler = re.match(r'\s*([A-Za-z_$][\w$]*)\s*\(', expression)
        if handler:
            result.append({'receiver':None, 'name':handler.group(1),
                'position':start-unit.start, 'end':end-unit.start})
    return result


def candidates(unit, receiver, name, available, position=None):
    targets = getattr(unit.source, 'template_handler_targets', {})
    target = targets.get(name)
    return [target] if target and target in available else []


def interaction(unit, evidence, facts):
    result = rules.interaction(unit, evidence, facts)
    if not result:
        return result
    targets = getattr(unit.source, 'template_handler_targets', {})
    for event in result['events'].values():
        eid = event['evidence_ids'][0]
        excerpt = facts['evidence'][eid]['excerpt']
        attribute, expression = _attribute(excerpt)
        if attribute and attribute.startswith('('):
            event['trigger'] = attribute[1:-1]
        handler = re.match(r'\s*([A-Za-z_$][\w$]*)\s*\(', expression or '')
        target = targets.get(handler.group(1)) if handler else None
        if target:
            event['handler_symbol_id'] = target.symbol_id
            event['resolution'] = 'resolved'
            event['reason'] = None
    return rules.hydrate_ui_calls(unit, facts, result)


def bindings(unit):
    result = []
    parsed_spans = set()
    for match in unit.source.rule_outputs:
        if match.output_type != 'binding' or not match.attributes.get('parse_attribute'):
            continue
        start, end = rules.span(unit.source, match)
        if not rules.owns(unit, start, end):
            continue
        name, value = _attribute(match.text)
        if name and value is not None:
            parsed_spans.add((start, end))
            result.append({'name': value, 'value_type': 'text',
                'direction': match.attributes['direction'], 'expression': value})
    result.extend(binding for binding in rules.bindings(unit)
                  if not any(binding['expression'] == unit.source.text[start:end]
                             for start, end in parsed_spans))
    return result


def resources(unit):
    return rules.resources(unit)


def observations(unit):
    return rules.observations(unit)


def operations(unit):
    result = []
    for match in unit.source.rule_outputs:
        if match.output_type != 'semantic_effect' \
                or not match.attributes.get('target_from_attribute'):
            continue
        start, end = rules.span(unit.source, match)
        if not rules.owns(unit, start, end):
            continue
        _, target = _attribute(match.text)
        if not target:
            continue
        position = start - unit.start
        target_at = match.text.find(target)
        input_binding = {'name': f'http.target@{position}', 'value_type': 'http',
            'expression': target, 'position': position + target_at,
            'end': position + target_at + len(target), 'resolution': 'resolved',
            'reason': None}
        output_binding = {'name': f'http.response@{position}', 'value_type': 'http',
            'expression': match.text, 'position': position, 'end': end - unit.start,
            'resolution': 'unresolved',
            'reason': 'The response exists only after the form submission executes.'}
        result.append(declare_operation_observation(unit, position=position,
            end=end-unit.start, kind='external_action', outcome=match.text,
            resource={'kind': 'service', 'name': target, 'resolution': 'resolved',
                      'reason': None}, input_bindings=[input_binding],
            output_bindings=[output_binding], protocol='http',
            projection_gaps=[{
                'projection': 'completion', 'code': 'HTML_FORM_OUTCOME_UNVERIFIED',
                'reason': 'The form action is declared, but runtime completion is not established.'
            }, {
                'projection': 'condition', 'code': 'HTML_FORM_CONTROL_FLOW_NOT_ESTABLISHED',
                'reason': 'Submission conditions are not established statically.'
            }, {
                'projection': 'output_bindings', 'code': 'HTML_FORM_RESPONSE_UNRESOLVED',
                'reason': 'The response mapping is unavailable until the submission executes.'
            }], resolution='unresolved',
            reason='The form target is exact; remote implementation and outcome are unverified.'))
    return result


def relations(source):
    return rules.relations(source)


def resolve_call(unit, receiver, name, candidates, position, evidence_id=None):
    return rules.resolve_call(unit, receiver, name, candidates, position, evidence_id)


def symbol_key(name):
    return name
