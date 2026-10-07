"""HTML form and template semantics over declarative tree-sitter rules."""
from __future__ import annotations

import re
from html.parser import HTMLParser

from . import rules
from .base import (declare_anchor_registration, declare_anchor_representation,
                   declare_operation_observation, declare_trace_contract)


PREPARE_PHASE = 50


# Marks an identity part that is not statically determined. Such an identity
# also carries the form's location, so incomplete forms never merge.
_UNRESOLVED_PART = '<unresolved>'
_SUBMIT_INPUT_TYPES = frozenset({'submit', 'image'})
_HTTP_FORM_METHODS = frozenset({'get', 'post'})


class _FormReader(HTMLParser):
    """The form's own attributes and its submit controls, in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.form = None
        self.controls = []
        self._button = None

    def handle_starttag(self, tag, attrs):
        attributes = {name: value for name, value in attrs}
        if tag == 'form' and self.form is None:
            self.form = attributes
        elif tag == 'button' and (attributes.get('type') or 'submit').strip().lower() == 'submit':
            self._button = {'attributes': attributes, 'text': []}
            self.controls.append(self._button)
        elif tag == 'input' and (attributes.get('type') or '').strip().lower() in _SUBMIT_INPUT_TYPES:
            self.controls.append({'attributes': attributes,
                                  'text': [attributes.get('value') or '']})

    def handle_endtag(self, tag):
        if tag == 'button':
            self._button = None

    def handle_data(self, data):
        if self._button is not None:
            self._button['text'].append(data)


def _computed(attributes, pattern):
    return bool(pattern) and any(re.fullmatch(pattern, name) for name in attributes)


def _form_submission(text, metadata):
    """``(method, action, label, missing)`` of a form; unknown parts are None.

    Each value is the literal one the browser submits. A part a template
    engine computes, or one the markup leaves open, is reported missing
    rather than guessed.
    """
    reader = _FormReader()
    reader.feed(text)
    reader.close()
    form = reader.form or {}
    template = metadata.get('template_expression')
    dynamic = lambda value: bool(template and re.search(template, value))
    overridden = any(_computed(control['attributes'],
                               metadata.get('submission_override_attribute'))
                     for control in reader.controls)
    missing = []
    action = (form.get('action') or '').strip()
    if (overridden or not action or dynamic(action)
            or _computed(form, metadata.get('computed_action_attribute'))):
        action = None
        missing.append('action')
    written = (form.get('method') or '').strip().lower()
    computed_method = _computed(form, metadata.get('computed_method_attribute'))
    if overridden or dynamic(written) or (computed_method and not written) or (
            written and written not in _HTTP_FORM_METHODS):
        method = None
        missing.append('method')
    else:
        # HTML submits with GET when no method is written.
        method = (written or 'get').upper()
    labels = set()
    for control in reader.controls:
        label = ' '.join(''.join(control['text']).split())
        if (not label or dynamic(label)
                or _computed(control['attributes'], metadata.get('computed_label_attribute'))):
            labels.add(None)
        else:
            labels.add(label)
    label = next(iter(labels)) if len(labels) == 1 else None
    if label is None:
        missing.append('label')
    return method, action, label, missing


def _identity_part(value):
    return _UNRESOLVED_PART if value is None else value


def extract(source):
    units = rules.extract(source)
    forms = {rules.span(source, match): match.attributes for match in source.rule_outputs
             if match.rule_id == 'html-form-definition'}
    for unit in units:
        unit.html_form = (unit.start, unit.end) in forms
        unit.html_form_metadata = forms.get((unit.start, unit.end), {})
    return units


def prepare(sources, units, diagnostics=None):
    rules.prepare(sources, units, diagnostics)
    for source in sources:
        for unit in source.units:
            if not getattr(unit, 'html_form', False):
                continue
            method, action, label, missing = _form_submission(
                source.text[unit.start:unit.end], unit.html_form_metadata)
            scope = source.service_scope
            # The label is the last part, so escaping its separators keeps the
            # key unambiguous for actions that themselves contain ':'.
            written_label = (None if label is None else
                             label.replace('%', '%25').replace(':', '%3A'))
            identity = (f'ui:{scope}:form:{_identity_part(method)}:'
                        f'{_identity_part(action)}:{_identity_part(written_label)}')
            if missing:
                identity += f'@{source.path}:{unit.start}'
            reason = (None if not missing else
                      'Form submission ' + ', '.join(missing) +
                      (' is' if len(missing) == 1 else ' are') +
                      ' not statically determined; identity keeps the form location.')
            unit.anchor_kind = 'ui'
            unit.method = method
            unit.route = action
            unit.anchor_resolution = 'unresolved' if missing else 'resolved'
            unit.anchor_reason = reason
            declare_anchor_representation(unit, 'exposure', identity, 'eligible', 'external')
            declare_anchor_registration(unit, 'action', event='submit', target=unit.name,
                scope=scope, label=label, resolution=unit.anchor_resolution, reason=reason)
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
