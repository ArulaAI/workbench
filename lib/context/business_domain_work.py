"""Deterministic hierarchical work scopes for business-domain activity synthesis."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from .business_domain_schema import DomainError, digest, identifier, record, validate


GRAPH_CONTEXT_COLLECTIONS = (
    'resources', 'symbols', 'edges', 'anchors', 'bindings', 'traces',
    'trace_obligations', 'effects', 'evidence', 'source_snapshots',
    'rule_observations', 'activities', 'concepts', 'information_uses',
    'ownerships', 'rules', 'rule_relationships', 'claims', 'domains',
    'relationships', 'record_refs',
)


def graph_context(model: dict, selected: dict | None = None) -> dict:
    """Project the complete canonical model into the existing GraphContext."""
    context = record('GraphContext')
    context['capabilities'] = copy.deepcopy(model.get('capabilities', []))
    for collection in GRAPH_CONTEXT_COLLECTIONS:
        source = selected if selected is not None else model
        context[collection] = copy.deepcopy(source.get(collection, {}))
    if selected is not None:
        for reference in selected.get('record_refs', {}).values():
            if reference['collection'] != 'evidence':
                raise DomainError(
                    'INVALID_REFERENCE',
                    'Whole-graph scope cannot retain an omitted record reference',
                    reference['id'])
            evidence = copy.deepcopy(model['evidence'][reference['id']])
            context['evidence'][reference['id']] = evidence
            snapshot_id = evidence['locator'].get('snapshot_id')
            if snapshot_id:
                context['source_snapshots'][snapshot_id] = copy.deepcopy(
                    model['source_snapshots'][snapshot_id])
        context['record_refs'] = {}
    selected_anchors = context['anchors'].values()
    context['anchor_representations'] = {
        representation['id']: copy.deepcopy(representation)
        for anchor in selected_anchors
        for representation in anchor.get('representations', [])
    }
    context['anchor_correspondences'] = {
        correspondence['id']: copy.deepcopy(correspondence)
        for anchor in selected_anchors
        for correspondence in anchor.get('correspondences', [])
    }
    validate(context, 'GraphContext')
    return context


def whole_graph_scope(model: dict, selected: dict | None = None) -> dict:
    """Return the mandatory first semantic scope containing every anchor."""
    context = graph_context(model, selected)
    anchors = sorted(context['anchors'])
    representations = sorted(context['anchor_representations'])
    fingerprint = digest({
        'context': context,
        'canonical_anchor_ids': anchors,
        'source_representation_ids': representations,
    })
    scope = record(
        'GraphScope', scope_id=identifier('scope', 'whole_graph', fingerprint),
        scope_kind='whole_graph', partition_strategy='none',
        estimated_input_tokens=0, parent_scope_id=None,
        input_fingerprint=fingerprint, context=context,
        source_representation_ids=representations,
        canonical_anchor_ids=anchors, child_scope_ids=[],
        cross_scope_edge_ids=[])
    validate(scope, 'GraphScope')
    return scope


@dataclass(frozen=True)
class ActivityScope:
    """One immutable provider work unit; scope identity derives from its content."""

    id: str
    strategy: str
    packet: dict
    cut_edge_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidatedActivityChild:
    """A validated leaf or roll-up plus its stable reconciliation coverage."""

    scope_id: str
    strategy: str
    cut_edge_ids: tuple[str, ...]
    payload: dict


def _scope(strategy: str, packet: dict, cut_edge_ids=()) -> ActivityScope:
    return ActivityScope(
        identifier('scope', strategy, digest(packet), sorted(cut_edge_ids)),
        strategy, packet, tuple(sorted(set(cut_edge_ids))))


def plan_activity_scopes(model: dict, anchor_ids, packet_builder, fits) -> list[ActivityScope]:
    """Prefer the complete graph, then stable anchor bundles, then edge segments."""
    anchors = sorted(set(anchor_ids))
    if not anchors:
        return []
    whole = packet_builder(model, anchors)
    if fits(whole):
        return [_scope('whole_graph', whole)]

    scopes: list[ActivityScope] = []
    bundle: list[str] = []
    for anchor_id in anchors:
        # Stable prefix packing leaves no omitted or duplicated work. It keeps each
        # canonical anchor's entire trace closure together until it proves too
        # large on its own.
        candidate = packet_builder(model, bundle + [anchor_id])
        if bundle and not fits(candidate):
            packet = packet_builder(model, bundle)
            scopes.append(_scope('entrypoint_bundle', packet))
            bundle = []
            candidate = packet_builder(model, [anchor_id])
        if fits(candidate):
            bundle.append(anchor_id)
            continue
        scopes.extend(_segment_anchor(model, anchor_id, packet_builder, fits))
    if bundle:
        scopes.append(_scope('entrypoint_bundle',
                             packet_builder(model, bundle)))
    return scopes


def _segment_anchor(model: dict, anchor_id: str, packet_builder, fits) -> list[ActivityScope]:
    traces = sorted((trace for trace in model['traces'].values()
                     if trace['anchor_id'] == anchor_id), key=lambda value: value['id'])
    symbols = {symbol for trace in traces for symbol in trace['symbol_ids']}
    if not traces or not symbols:
        raise DomainError('OVERSIZED_ATOMIC_RECORD',
                          f'Canonical anchor {anchor_id} has no splittable typed trace closure',
                          anchor_id)
    execution_edges = {edge_id: model['edges'][edge_id]
                       for trace in traces for edge_id in trace['edge_ids']
                       if model['edges'][edge_id]['from_ref']['kind'] == 'symbol'
                       and model['edges'][edge_id].get('to_ref')
                       and model['edges'][edge_id]['to_ref']['kind'] == 'symbol'}
    order = _stable_breadth_first(model['anchors'][anchor_id]['symbol_id'], symbols,
                                  execution_edges)
    scopes: list[ActivityScope] = []
    selected: list[str] = []
    for symbol_id in order:
        candidate, cuts = _segment_packet(
            model, anchor_id, selected + [symbol_id], packet_builder)
        if selected and not fits(candidate):
            packet, cut_ids = _segment_packet(model, anchor_id, selected, packet_builder)
            scopes.append(_scope('execution_segment', packet, cut_ids))
            selected = []
            candidate, cuts = _segment_packet(model, anchor_id, [symbol_id], packet_builder)
        if not fits(candidate):
            raise DomainError('OVERSIZED_ATOMIC_RECORD',
                              f'Atomic graph record {symbol_id} plus mandatory evidence exceeds the request allowance',
                              symbol_id)
        selected.append(symbol_id)
    if selected:
        packet, cuts = _segment_packet(model, anchor_id, selected, packet_builder)
        scopes.append(_scope('execution_segment', packet, cuts))
    return scopes


def _stable_breadth_first(start: str, symbols: set[str], edges: dict) -> list[str]:
    outgoing = {}
    for edge_id, edge in edges.items():
        outgoing.setdefault(edge['from_ref']['id'], []).append(
            (edge_id, edge['to_ref']['id']))
    queue = [start] if start in symbols else []
    seen, ordered = set(), []
    while queue:
        symbol = queue.pop(0)
        if symbol in seen:
            continue
        seen.add(symbol); ordered.append(symbol)
        queue.extend(target for _, target in sorted(outgoing.get(symbol, []))
                     if target in symbols and target not in seen)
    ordered.extend(sorted(symbols - seen))
    return ordered


def _segment_packet(model: dict, anchor_id: str, primary_symbols,
                    packet_builder) -> tuple[dict, tuple[str, ...]]:
    """Build one closed trace subgraph and retain every typed cut explicitly."""
    primary = set(primary_symbols)
    sliced = copy.deepcopy(model)
    selected_edges, cut_edges, selected_obligations = set(), set(), set()
    sliced_traces, obligations_by_trace = {}, {}
    for trace in sorted(model['traces'].values(), key=lambda value: value['id']):
        if trace['anchor_id'] != anchor_id or not primary.intersection(trace['symbol_ids']):
            continue
        trace_symbols = set(trace['symbol_ids'])
        trace_edges = {edge_id: model['edges'][edge_id] for edge_id in trace['edge_ids']}
        for edge_id, edge in trace_edges.items():
            source = edge['from_ref']['id']
            target = edge.get('to_ref')
            target_symbol = target['id'] if target and target['kind'] == 'symbol' else None
            if target_symbol:
                if source in primary or target_symbol in primary:
                    selected_edges.add(edge_id)
                    if (source in primary) != (target_symbol in primary):
                        cut_edges.add(edge_id)
            elif source in primary:
                selected_edges.add(edge_id)
        trace_obligations = set()
        for obligation_id in trace.get('obligation_ids', []):
            obligation = model['trace_obligations'][obligation_id]
            if (obligation['origin_ref']['id'] in primary
                    or obligation.get('edge_id') in selected_edges):
                selected_obligations.add(obligation_id)
                trace_obligations.add(obligation_id)
        visible_symbols = primary & trace_symbols
        for edge_id in selected_edges & set(trace_edges):
            edge = trace_edges[edge_id]
            visible_symbols.add(edge['from_ref']['id'])
            if edge.get('to_ref') and edge['to_ref']['kind'] == 'symbol':
                visible_symbols.add(edge['to_ref']['id'])
        sliced_trace = copy.deepcopy(trace)
        sliced_trace['symbol_ids'] = sorted(visible_symbols)
        sliced_trace['edge_ids'] = sorted(selected_edges & set(trace_edges))
        sliced_trace['frontier_ids'] = sorted(
            set(trace['frontier_ids']) & (visible_symbols | selected_edges))
        sliced_trace['traversal_complete'] = not bool(cut_edges & set(trace_edges))
        if not sliced_trace['traversal_complete']:
            sliced_trace['resolution'] = 'unresolved'
            sliced_trace['reason'] = 'Typed execution edges continue in sibling segments.'
        sliced_traces[trace['id']] = sliced_trace
        obligations_by_trace[trace['id']] = trace_obligations

    sliced['traces'] = sliced_traces
    sliced['effects'] = {effect_id: effect for effect_id, effect in sliced['effects'].items()
                         if effect.get('edge_id') in selected_edges}
    for trace in sliced_traces.values():
        trace_obligations = obligations_by_trace[trace['id']]
        for edge_id in sorted(cut_edges & set(trace['edge_ids'])):
            edge = model['edges'][edge_id]
            obligation_id = identifier('trace_obligation', trace['id'],
                                       'execution_segment', edge_id)
            sliced['trace_obligations'][obligation_id] = record(
                'TraceObligation', id=obligation_id, trace_id=trace['id'],
                kind='execution_segment', origin_ref=edge['from_ref'], edge_id=edge_id,
                candidate_target_ids=([edge['to_ref']['id']]
                                      if edge.get('to_ref') else []),
                status='limit_reached', reason_code='EXECUTION_SEGMENT_CUT',
                reason='The typed execution edge crosses a deterministic segment boundary.',
                evidence_ids=sorted(edge['evidence_ids']))
            selected_obligations.add(obligation_id)
            trace_obligations.add(obligation_id)
        trace['obligation_ids'] = sorted(trace_obligations)
        evidence = {eid for symbol_id in trace['symbol_ids']
                    for eid in model['symbols'][symbol_id]['evidence_ids']}
        evidence.update(eid for edge_id in trace['edge_ids']
                        for eid in model['edges'][edge_id]['evidence_ids'])
        evidence.update(eid for obligation_id in trace['obligation_ids']
                        for eid in sliced['trace_obligations'][obligation_id]['evidence_ids'])
        trace['evidence_ids'] = sorted(evidence)
    sliced['trace_obligations'] = {
        key: value for key, value in sliced['trace_obligations'].items()
        if key in selected_obligations}
    packet = packet_builder(sliced, [anchor_id])
    return packet, tuple(sorted(cut_edges))


def reconciliation_packet(model: dict, child_payloads: list[dict], packet_builder,
                          manifest_builder) -> dict:
    """Create a compact root request from validated child semantic summaries."""
    children = normalized_children(child_payloads)
    anchors = sorted({anchor for child in children for payload in [child.payload]
                      for activity in payload['activities'].values()
                      for anchor in activity['anchor_ids']}
                     | {anchor for child in children for payload in [child.payload]
                        for anchor in payload['excluded_anchor_ids'] + payload['pending_anchor_ids']})
    packet = packet_builder(model, 'activity', anchors)
    context = record('PacketContext')
    context['capabilities'] = copy.deepcopy(model.get('capabilities', []))
    context['anchors'] = {key: copy.deepcopy(model['anchors'][key]) for key in anchors}
    for child in children:
        payload = _namespace_child_payload(child.payload, child.scope_id)
        for collection in ('activities', 'rules', 'concepts', 'information_uses', 'claims'):
            context[collection].update(copy.deepcopy(payload[collection]))
    # A compact reconciliation still supplies an exact usable citation. Other
    # already-validated excerpts stay hash references through the manifest.
    cited = sorted({evidence_id for child in children for payload in [child.payload]
                    for collection in ('activities', 'rules', 'concepts',
                                       'information_uses', 'claims')
                    for item in payload[collection].values()
                    for evidence_id in item.get('evidence_ids', [])})
    for child in children:
        child_payload, child_id = child.payload, child.scope_id
        child_anchors = sorted({anchor for activity in child_payload['activities'].values()
                                for anchor in activity['anchor_ids']}
                               | set(child_payload['excluded_anchor_ids'])
                               | set(child_payload['pending_anchor_ids']))
        claim_id = identifier('claim', 'coverage_manifest', child_id)
        context['claims'][claim_id] = record(
            'Claim', id=claim_id, subject_id=child_id,
            text=(f'Validated {child.strategy} child scope covers canonical anchors: '
                  + ', '.join(child_anchors) + '; typed cut edges: '
                  + (', '.join(child.cut_edge_ids) or 'none')),
            kind='coverage_manifest',
            evidence_ids=cited[:1],
            trace_ids=sorted({trace_id
                              for activity in child_payload['activities'].values()
                              for trace_id in activity['trace_ids']}),
            semantic_review='supported')
    if cited:
        evidence_id = cited[0]
        context['evidence'][evidence_id] = copy.deepcopy(model['evidence'][evidence_id])
        snapshot_id = context['evidence'][evidence_id]['locator'].get('snapshot_id')
        if snapshot_id:
            context['source_snapshots'][snapshot_id] = copy.deepcopy(
                model['source_snapshots'][snapshot_id])
    # Reconciliation consumes already validated semantic records. Raw trace,
    # edge and excerpt records remain content-hash references; rehydrating them
    # here would recreate the oversized leaf graph and defeat segmentation.
    manifest_builder(model, context)
    packet['context'] = context
    packet['input_fingerprint'] = digest(context)
    validate(packet, 'ActivityPacket')
    return packet


def grouping_reconciliation_packet(model: dict, child_payloads,
                                   manifest_builder) -> dict:
    """Build a compact, exhaustive grouping request from verified children."""
    context = record('PacketContext')
    context['capabilities'] = copy.deepcopy(model.get('capabilities', []))
    activity_ids = set()
    cited = set()
    for payload in sorted(child_payloads, key=digest):
        for collection in ('domains', 'ownerships', 'relationships',
                           'rule_relationships', 'claims'):
            overlap = set(context[collection]) & set(payload[collection])
            if overlap:
                raise DomainError('INVALID_ID',
                                  'Grouping children reused a semantic record ID')
            context[collection].update(copy.deepcopy(payload[collection]))
        activity_ids.update(
            membership['activity_id']
            for domain in payload['domains'].values()
            for membership in domain['activity_memberships'])
        activity_ids.update(
            claim['subject_id'] for claim in payload['claims'].values()
            if claim['subject_id'] in model['activities'])
        cited.update(
            evidence_id
            for collection in ('domains', 'ownerships', 'relationships',
                               'rule_relationships', 'claims')
            for item in payload[collection].values()
            for evidence_id in item.get('evidence_ids', []))
    context['evidence'] = {key: copy.deepcopy(model['evidence'][key])
                           for key in sorted(cited) if key in model['evidence']}
    snapshot_ids = {item['locator'].get('snapshot_id')
                    for item in context['evidence'].values()}
    context['source_snapshots'] = {
        key: copy.deepcopy(model['source_snapshots'][key])
        for key in sorted(snapshot_ids) if key in model['source_snapshots']}
    manifest_builder(model, context)
    packet = record('GroupingPacket', context=context,
                    activity_ids=sorted(activity_ids))
    packet['input_fingerprint'] = digest(context)
    validate(packet, 'GroupingPacket')
    return packet


def _namespace_child_payload(payload: dict, child_scope_id: str) -> dict:
    """Keep conflicting child proposals distinct inside a reconciliation request."""
    replacements = {}
    for collection in ('activities', 'rules', 'concepts', 'information_uses', 'claims'):
        for old in payload[collection]:
            replacements[old] = identifier(
                old.split(':', 1)[0], 'child', child_scope_id, old)
    def rewrite(value):
        if isinstance(value, str):
            return replacements.get(value, value)
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, dict):
            return {replacements.get(key, key): rewrite(item)
                    for key, item in value.items()}
        return value
    return rewrite(payload)


def normalized_children(values) -> list[ValidatedActivityChild]:
    children = []
    for value in values:
        if isinstance(value, ValidatedActivityChild):
            children.append(value)
        else:
            children.append(ValidatedActivityChild(
                identifier('scope', 'validated_child', digest(value)),
                'entrypoint_bundle', (), value))
    return sorted(children, key=lambda child: child.scope_id)
