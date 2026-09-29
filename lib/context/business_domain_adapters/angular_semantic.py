"""Angular component, template, and HttpClient enrichment."""
from __future__ import annotations

import posixpath
import re

from . import rules
from .base import (declare_anchor_registration, declare_anchor_representation,
                   declare_trace_contract)


PREPARE_PHASE = 75


def _owner(source, start, end):
    return min((unit for unit in source.units
                if unit.start <= start < end <= unit.end),
               key=lambda unit: unit.end - unit.start, default=None)


def prepare(sources, units, diagnostics=None):
    units_by_path = {}
    for unit in units:
        units_by_path.setdefault(unit.source.path, []).append(unit)
    for source in sources:
        clients = set()
        components = []
        for match in source.rule_outputs:
            start, end = rules.span(source, match)
            if match.output_type == 'receiver_binding' \
                    and match.attributes.get('framework') == 'angular':
                client = rules.capture(match, match.attributes.get('receiver_var'))
                if client:
                    clients.add(client)
            elif match.output_type == 'component_marker' \
                    and match.attributes.get('framework') == 'angular':
                owner = _owner(source, start, end)
                metadata = rules.capture(match, match.attributes.get('metadata_var')) or ''
                template = re.search(r'\btemplateUrl\s*:\s*["\']([^"\']+)["\']', metadata)
                if owner:
                    components.append((owner, template.group(1) if template else None, start, end))
        boundaries = getattr(source, 'framework_call_boundaries', {})
        operations = getattr(source, 'framework_operations', [])
        for reference in source.references:
            if reference.kind != 'call' or not reference.callee_name:
                continue
            start, _ = rules.span(source, {'range':reference.source_range})
            receiver = reference.receiver or ''
            root = receiver.removeprefix('this.').split('.', 1)[0]
            if root in clients and reference.callee_name in {'get','post','put','patch','delete'}:
                boundaries[(start, reference.callee_name)] = ('angular-http',
                    f'{reference.callee_name} is provided by the evidenced Angular HttpClient.')
        source.framework_call_boundaries = boundaries
        for match in source.rule_outputs:
            if match.output_type != 'ui_transition' \
                    or match.attributes.get('framework') != 'angular':
                continue
            receiver = rules.capture(match, match.attributes.get('receiver_var')) or ''
            root = receiver.removeprefix('this.').split('.', 1)[0]
            if root in clients:
                operations.append(match)
        source.framework_operations = operations
        for component, template, start, end in components:
            if not template:
                continue
            path = posixpath.normpath(posixpath.join(posixpath.dirname(source.path), template))
            template_units = units_by_path.get(path, [])
            if not template_units:
                continue
            handlers = {unit.name:unit for unit in source.units
                        if unit.owner == component.name and unit.kind == 'method'}
            forms = [unit for unit in template_units
                     if getattr(unit, 'html_form', False)]
            template_unit = (min(forms, key=lambda unit: unit.end-unit.start)
                             if forms else max(template_units,
                                               key=lambda unit: unit.end-unit.start))
            template_source = template_unit.source
            template_source.template_handler_targets = handlers
            template_unit.anchor_kind = 'ui'
            template_unit.anchor_resolution = 'resolved'
            template_unit.anchor_reason = None
            template_unit.anchor_context_unit = component
            identity = f'ui:{source.service_scope}:component:{component.qualified}'
            declare_anchor_representation(
                template_unit, 'exposure', identity, 'eligible', 'external')
            declare_anchor_registration(template_unit, 'invocation',
                target=component.name, scope=source.service_scope,
                resolution='resolved', reason=None)
            declare_trace_contract(template_unit, 'implementation')
            source.normalized_relations = getattr(source, 'normalized_relations', [])
            source.normalized_relations.append({'source':component,
                'target':template_unit, 'kind':'composes', 'start':start, 'end':end,
                'resolution':'resolved', 'reason':None})
