"""TypeScript and JavaScript semantics over the shared declarative reader.

The rules adapter remains the single owner of declarations, references,
routes, bindings, operations, and base UI records.  This adapter adds the
language-specific boundary decisions that require JavaScript module meaning.
"""
from __future__ import annotations

from . import rules
from .base import SemanticResult
from ..business_domain_schema import identifier, record


PREPARE_PHASE = 50


def extract(source):
    return rules.extract(source)


def _modules(source):
    return sorted({
        (reference.module or '').strip('\'"')
        for reference in source.references
        if reference.module
    })


def activation_evidence(source):
    """Expose normalized imports; this never searches source text."""
    return {'imports': _modules(source)}


def _external_import_boundaries(source):
    bindings = rules._import_bindings(source)
    boundaries = {}
    for reference in source.references:
        if reference.kind != 'call' or not reference.callee_name:
            continue
        root = rules._receiver_root(reference)
        module = bindings.get(root)
        if not module or module.startswith(('.', '/')):
            continue
        start, _ = rules.span(source, {'range': reference.source_range})
        if (start, reference.callee_name) in getattr(
                source, 'resolved_call_targets', {}):
            continue
        boundaries[(start, reference.callee_name)] = (module,
            f'{reference.callee_name} is reached through {root}, imported '
            f'from external module {module}.')
    return boundaries


def prepare(sources, units, diagnostics=None):
    rules.prepare(sources, units, diagnostics)
    for source in sources:
        source.external_import_boundaries = _external_import_boundaries(source)


def calls(unit):
    """Avoid a duplicate call edge for a call already modeled as an effect."""
    effects = set()
    for match in unit.source.rule_outputs:
        if match.output_type != 'semantic_effect':
            continue
        start, end = rules.span(unit.source, match)
        if rules.owns(unit, start, end):
            effects.add((start - unit.start, end - unit.start))
    return [call for call in rules.calls(unit)
            if (call['position'], call['end']) not in effects]


def candidates(unit, receiver, name, available, position=None):
    return rules.candidates(unit, receiver, name, available, position)


def resolve_call(unit, receiver, name, candidates, position, evidence_id=None):
    evidence = (evidence_id or unit.evidence_id,)
    boundary = getattr(unit.source, 'framework_call_boundaries', {}).get(
        (unit.start + position, name))
    code = 'JS_EXTERNAL_CALL'
    if not boundary:
        boundary = getattr(unit.source, 'external_import_boundaries', {}).get(
            (unit.start + position, name))
    if boundary and not candidates:
        owner, reason = boundary
        return SemanticResult(capability='callable_resolution', outcome='external',
            subject_id=unit.symbol_id,
            target_id=identifier('resource', 'javascript-external-call', owner, name),
            evidence_ids=evidence, diagnostic_code=code, reason=reason)
    return rules.resolve_call(unit, receiver, name, candidates, position, evidence_id)


def _enriched_interaction(unit, evidence, facts, result):
    if not result:
        return result
    traced = {sid for trace in facts['traces'].values()
              if trace['anchor_id'] == unit.anchor_id for sid in trace['symbol_ids']}
    events = {event['handler_symbol_id']: event['id']
              for event in result['events'].values() if event['handler_symbol_id']}
    states = {}
    additions = getattr(unit.source, 'ui_enrichments', [])
    context = getattr(unit, 'anchor_context_unit', None) or unit
    components = {context.name, context.owner}
    for item in additions:
        if item['component'] not in components or item['kind'] != 'state':
            continue
        eid = evidence(unit.source, item['start'], item['end'])
        sid = identifier('ui_state', unit.anchor_id, item['component'], item['label'])
        states[(item['component'], item['label'])] = sid
        result['states'][sid] = record('UIState', id=sid, label=item['label'],
            render_evidence_ids=[eid], evidence_ids=[eid], resolution='resolved', reason=None)
    for item in additions:
        owner_symbol_id = item['owner'].symbol_id
        if owner_symbol_id not in traced or item['kind'] != 'transition':
            continue
        event_id = events.get(owner_symbol_id)
        state_id = states.get((item['component'], item['label']))
        if not event_id or not state_id:
            continue
        eid = evidence(unit.source, item['start'], item['end'])
        tid = identifier('ui_transition', unit.anchor_id, event_id, item['start'])
        result['transitions'][tid] = record('UITransition', id=tid,
            from_state_id=state_id, event_id=event_id, guard_evidence_ids=[],
            to_state_id=state_id, call_ids=[], output_ids=[], evidence_ids=[eid],
            resolution='resolved', reason=None)
    return result


def interaction(unit, evidence, facts):
    return _enriched_interaction(unit, evidence, facts,
                                 rules.interaction(unit, evidence, facts))


def bindings(unit):
    return rules.bindings(unit)


def resources(unit):
    return rules.resources(unit)


def observations(unit):
    return rules.observations(unit)


def operations(unit):
    result = rules.operations(unit)
    occupied = {(item['position'], item['end']) for item in result}
    for match in getattr(unit.source, 'framework_operations', []):
        start, end = rules.span(unit.source, match)
        relative = (start-unit.start, end-unit.start)
        if rules.owns(unit, start, end) and relative not in occupied:
            result.append(rules.http_operation(unit, match, {
                'effect_kind': 'external_action', 'resource_kind': 'service',
                'protocol': 'http', 'target_var': match.attributes['target_var'],
            }))
    return result


def relations(source):
    return rules.relations(source)


def symbol_key(name):
    return name
