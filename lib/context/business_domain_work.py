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


def graph_context(model: dict, selected: dict | None = None, *,
                  keep_references: bool = False) -> dict:
    """Project the canonical model, or a selection of it, into a GraphContext.

    Omitted evidence a selection cites is copied in, so every citation stays
    usable. A whole-graph scope omits nothing else. A slice may name records
    that belong to other scopes (`keep_references`): those stay identity-only
    `record_refs`, which never stand in for content the slice was not given.
    """
    context = record('GraphContext')
    context['capabilities'] = copy.deepcopy(model.get('capabilities', []))
    for collection in GRAPH_CONTEXT_COLLECTIONS:
        source = selected if selected is not None else model
        context[collection] = copy.deepcopy(source.get(collection, {}))
    if selected is not None:
        kept = {}
        for reference in selected.get('record_refs', {}).values():
            if reference['collection'] != 'evidence':
                if keep_references:
                    kept[reference['id']] = copy.deepcopy(reference)
                    continue
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
        context['record_refs'] = kept
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


# ── Hierarchical work ──────────────────────────────────────────────────
#
# When the complete graph does not fit one request's synthesis, verification,
# repair and reverification, the semantic work is partitioned (tech spec,
# "Large-repository hierarchical mode"). The graph stays whole in canonical
# storage; only requests are divided:
#
#   application boundary the complete trace closures of one service's anchors
#   entry-point bundle   the closures of several anchors of a boundary too
#                        large for one request
#   execution segment    part of one anchor's closure too large for a request,
#                        cut at typed execution edges
#   reconciliation       validated units rolled up; segments into their anchor,
#                        then groups of units, until one root covers them all
#
# A unit is publishable only through the root, which must keep every anchor a
# unit beneath it represented.

# Scope identities derive from content, never from the hierarchy above them, so
# an unchanged slice keeps its cache entry when other slices change.
ROOT_SCOPE_ID = identifier('scope', 'reconciliation', 'root')
SEMANTIC_COLLECTIONS = (
    'activities', 'rules', 'concepts', 'information_uses', 'ownerships',
    'rule_relationships', 'claims', 'domains', 'relationships')
COVERAGE_MANIFEST = 'coverage_manifest'
# Citations per coverage manifest: enough to locate a child's evidence without
# re-sending every excerpt it already had verified.
MANIFEST_EVIDENCE = 8


def anchor_scope_id(anchor_id: str) -> str:
    """The reconciliation scope that reunites one anchor's execution segments."""
    return identifier('scope', 'reconciliation', 'anchor', anchor_id)


def slice_scope(model: dict, anchor_ids, selected: dict, strategy: str, *,
                cross_scope_edge_ids=(), parent_scope_id: str = ROOT_SCOPE_ID) -> dict:
    """An unsized slice scope over `selected`, the closure of `anchor_ids`."""
    context = graph_context(model, selected, keep_references=True)
    anchors = sorted(set(anchor_ids))
    representations = sorted(context['anchor_representations'])
    cross = sorted(set(cross_scope_edge_ids))
    fingerprint = digest({
        'context': context, 'canonical_anchor_ids': anchors,
        'source_representation_ids': representations,
        'partition_strategy': strategy, 'cross_scope_edge_ids': cross,
    })
    scope = record(
        'GraphScope', scope_id=identifier('scope', strategy, fingerprint),
        scope_kind='slice', partition_strategy=strategy, estimated_input_tokens=0,
        parent_scope_id=parent_scope_id, input_fingerprint=fingerprint,
        context=context, source_representation_ids=representations,
        canonical_anchor_ids=anchors, child_scope_ids=[],
        cross_scope_edge_ids=cross)
    validate(scope, 'GraphScope')
    return scope


def _pack(items, build, fits):
    """Stable prefix packing: grow a group until the next item would not fit.

    Yields `(group, built)` pairs, where `built` is `build(group)`; a group the
    next item would overflow is closed and that item starts a new one. A
    single item that does not fit is yielded alone for the caller to handle.
    """
    group, built = [], None
    for item in items:
        if group:
            candidate = build(group + [item])
            if fits(candidate):
                group, built = group + [item], candidate
                continue
            yield group, built
        group, built = [item], build([item])
    if group:
        yield group, built


def _edge_users(model: dict) -> dict:
    """Edge ID -> the canonical anchors whose traces include it."""
    users = {}
    for trace in model['traces'].values():
        for edge_id in trace['edge_ids']:
            users.setdefault(edge_id, set()).add(trace['anchor_id'])
    return users


def application_boundaries(model: dict) -> dict:
    """Boundary name -> its canonical anchors, from each anchor's service.

    A service is the deployable boundary extraction found for the anchor's
    source (its nearest build manifest); an anchor without one belongs to the
    repository boundary.
    """
    boundaries = {}
    for anchor_id, anchor in model['anchors'].items():
        resource = model['resources'].get(anchor['operation'].get('service_resource_id') or '')
        name = resource['name'] if resource else 'repository'
        boundaries.setdefault(name, []).append(anchor_id)
    return {name: sorted(anchor_ids) for name, anchor_ids in sorted(boundaries.items())}


def plan_slices(model: dict, build_bundle, build_segment, fits, limit) -> list[dict]:
    """Sized slices covering every canonical anchor, in a deterministic order.

    The primary partition is the application boundary: every anchor of one
    deployable service in one slice. A boundary too large for one request is
    packed into entry-point bundles in canonical-ID order, and an anchor too
    large alone is cut into execution segments. No slice spans two boundaries.
    Shared implementation appears in every slice that reaches it, and its
    edges are declared cross-scope so reconciliation recognises the shared
    records.

    `build_bundle(anchor_ids, cross_scope_edge_ids, strategy)` and
    `build_segment(view, anchor_id, cut_edge_ids)` return sized scopes;
    `fits(scope)` decides whether a scope's complete sequence can run and
    `limit(scope)` names the setting it exceeds when it cannot.
    """
    users = _edge_users(model)
    owned = {}
    for edge_id, anchors in users.items():
        for anchor_id in anchors:
            owned.setdefault(anchor_id, set()).add(edge_id)

    def build(anchor_ids, strategy='entrypoint_bundle'):
        members = set(anchor_ids)
        edges = set().union(*(owned.get(anchor_id, set()) for anchor_id in anchor_ids))
        return build_bundle(anchor_ids, sorted(e for e in edges if users[e] - members),
                            strategy)

    boundaries = application_boundaries(model)
    slices = []
    for anchors in boundaries.values():
        # A lone boundary is the whole graph, already known not to fit.
        if len(boundaries) > 1:
            scope = build(anchors, 'application_boundary')
            if fits(scope):
                slices.append(scope)
                continue
        slices.extend(_bundles(model, anchors, build, build_segment, fits, limit))
    return slices


def _bundles(model, anchors, build, build_segment, fits, limit) -> list[dict]:
    """Entry-point bundles over `anchors`, segmenting any anchor too large alone."""
    slices = []
    for anchor_ids, scope in _pack(anchors, build, fits):
        if fits(scope):
            slices.append(scope)
            continue
        [anchor_id] = anchor_ids
        exceeded = limit(scope)
        if exceeded != 'max_request_input_tokens':
            raise DomainError(
                'BUILD_BUDGET',
                f'Entry point {anchor_id} needs {scope["estimated_input_tokens"]:,} '
                'input tokens per request, and its synthesis, verification and '
                f'repair sequence exceeds {exceeded}; nothing was dispatched. '
                f'Raise {exceeded} under [business_domains] in the project '
                'speed.toml and run again.', anchor_id)
        slices.extend(plan_execution_segments(model, anchor_id, build_segment, fits))
    return slices


def plan_execution_segments(model: dict, anchor_id: str, build, fits) -> list[dict]:
    """Cut one anchor's oversized trace closure into segments that each fit.

    Symbols are taken in stable breadth-first order from the anchor along its
    typed execution edges, and a segment grows until the next symbol would not
    fit. A segment keeps every edge touching its symbols; an edge into another
    segment is a cut, carried as an `execution_segment` obligation and declared
    cross-scope. Only the anchor's reconciliation disposes of the anchor.
    """
    traces = [trace for trace in model['traces'].values() if trace['anchor_id'] == anchor_id]
    symbols = {symbol_id for trace in traces for symbol_id in trace['symbol_ids']}
    if not symbols:
        raise DomainError('OVERSIZED_ATOMIC_RECORD',
                          f'Entry point {anchor_id} exceeds one request and has no '
                          'trace to cut into execution segments', anchor_id)
    edges = {edge_id: model['edges'][edge_id] for trace in traces
             for edge_id in trace['edge_ids']
             if model['edges'][edge_id]['from_ref']['kind'] == 'symbol'
             and (model['edges'][edge_id].get('to_ref') or {}).get('kind') == 'symbol'}
    order = _stable_breadth_first(model['anchors'][anchor_id]['symbol_id'], symbols, edges)

    def segment(symbol_ids):
        view, cuts = segment_view(model, anchor_id, symbol_ids)
        return build(view, anchor_id, cuts)

    segments = []
    for symbol_ids, scope in _pack(order, segment, fits):
        if not fits(scope):
            raise DomainError(
                'OVERSIZED_ATOMIC_RECORD',
                f'Symbol {symbol_ids[0]} of entry point {anchor_id} needs '
                f'{scope["estimated_input_tokens"]:,} input tokens with its mandatory '
                'evidence, more than one request allows', symbol_ids[0])
        segments.append(scope)
    return segments


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
        seen.add(symbol)
        ordered.append(symbol)
        queue.extend(target for _, target in sorted(outgoing.get(symbol, []))
                     if target in symbols and target not in seen)
    ordered.extend(sorted(symbols - seen))
    return ordered


def segment_view(model: dict, anchor_id: str, primary_symbols) -> tuple[dict, tuple[str, ...]]:
    """A view of `model` holding one segment of `anchor_id`'s traces.

    The view shares every record it does not change. Each trace keeps the
    edges touching the segment's symbols; an edge with one end outside the
    segment is a cut, recorded as an `execution_segment` obligation, and a
    trace that loses edges this way is no longer traversal-complete.
    Returns the view and the cut edge IDs.
    """
    primary = set(primary_symbols)
    selected_edges, cut_edges, kept_obligations = set(), set(), set()
    traces, obligations_by_trace = {}, {}
    for trace in sorted(model['traces'].values(), key=lambda value: value['id']):
        if trace['anchor_id'] != anchor_id or not primary & set(trace['symbol_ids']):
            continue
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
        carried = {obligation_id for obligation_id in trace.get('obligation_ids', [])
                   if model['trace_obligations'][obligation_id]['origin_ref']['id'] in primary
                   or model['trace_obligations'][obligation_id].get('edge_id') in selected_edges}
        kept_obligations |= carried
        visible = primary & set(trace['symbol_ids'])
        for edge_id in selected_edges & set(trace_edges):
            edge = trace_edges[edge_id]
            visible.add(edge['from_ref']['id'])
            if edge.get('to_ref') and edge['to_ref']['kind'] == 'symbol':
                visible.add(edge['to_ref']['id'])
        sliced = copy.deepcopy(trace)
        sliced['symbol_ids'] = sorted(visible)
        sliced['edge_ids'] = sorted(selected_edges & set(trace_edges))
        sliced['frontier_ids'] = sorted(set(trace['frontier_ids']) & (visible | selected_edges))
        sliced['traversal_complete'] = not cut_edges & set(trace_edges)
        if not sliced['traversal_complete']:
            sliced['resolution'] = 'unresolved'
            sliced['reason'] = 'Typed execution edges continue in sibling segments.'
        traces[trace['id']] = sliced
        obligations_by_trace[trace['id']] = carried

    obligations = {key: model['trace_obligations'][key] for key in kept_obligations}
    for trace in traces.values():
        carried = obligations_by_trace[trace['id']]
        for edge_id in sorted(cut_edges & set(trace['edge_ids'])):
            edge = model['edges'][edge_id]
            obligation_id = identifier('trace_obligation', trace['id'],
                                       'execution_segment', edge_id)
            obligations[obligation_id] = record(
                'TraceObligation', id=obligation_id, trace_id=trace['id'],
                kind='execution_segment', origin_ref=edge['from_ref'], edge_id=edge_id,
                candidate_target_ids=[edge['to_ref']['id']] if edge.get('to_ref') else [],
                status='limit_reached', reason_code='EXECUTION_SEGMENT_CUT',
                reason='The typed execution edge crosses a deterministic segment boundary.',
                evidence_ids=sorted(edge['evidence_ids']))
            carried.add(obligation_id)
        trace['obligation_ids'] = sorted(carried)
        if 'completion' in trace:
            # A segment keeps the assumptions of the boundaries it carries; a
            # cut is a gap of the segment, never a boundary.
            blocking = [obligations[key] for key in trace['obligation_ids']
                        if obligations[key]['status'] != 'satisfied']
            trace['assumptions'] = [item for item in trace.get('assumptions', [])
                                    if item['obligation_id'] in carried]
            trace['completion'] = ('complete' if not blocking else
                                   'bounded' if all(item.get('boundary') for item in blocking)
                                   else 'incomplete')
        evidence = {eid for symbol_id in trace['symbol_ids']
                    for eid in model['symbols'][symbol_id]['evidence_ids']}
        evidence.update(eid for edge_id in trace['edge_ids']
                        for eid in model['edges'][edge_id]['evidence_ids'])
        evidence.update(eid for key in trace['obligation_ids']
                        for eid in obligations[key]['evidence_ids'])
        trace['evidence_ids'] = sorted(evidence)

    view = dict(model)
    view['traces'] = traces
    view['trace_obligations'] = obligations
    view['effects'] = {key: effect for key, effect in model['effects'].items()
                       if effect.get('edge_id') in selected_edges}
    return view, tuple(sorted(cut_edges))


# ── Units and reconciliation ───────────────────────────────────────────

@dataclass(frozen=True)
class Unit:
    """A validated scope and what it established about each anchor.

    `coverage` maps each anchor the unit accounts for to its status
    (`represented`, `excluded` or `unresolved`), the unit's activities that
    represent it, and the reason and evidence for any other status.
    """
    scope: dict
    payload: dict
    coverage: dict


def _anchor_activities(payload: dict) -> dict:
    activities = {}
    for activity_id, activity in payload['activities'].items():
        for anchor_id in activity['anchor_ids']:
            activities.setdefault(anchor_id, set()).add(activity_id)
    return activities


def slice_unit(scope: dict, payload: dict) -> Unit:
    """The unit a validated slice forms, from its anchor dispositions."""
    activities = _anchor_activities(payload)
    coverage = {}
    for disposition in payload['dispositions']:
        if disposition['subject_kind'] == 'anchor':
            coverage[disposition['subject_id']] = {
                'status': disposition['status'],
                'activity_ids': sorted(activities.get(disposition['subject_id'], ())),
                'reason': disposition['reason'],
                'evidence_ids': sorted(disposition['evidence_ids']),
            }
    return Unit(scope, payload, coverage)


def reconciled_unit(scope: dict, payload: dict, children) -> Unit:
    """The unit a validated reconciliation forms over `children`.

    Anchors its activities hold are represented; any other anchor keeps the
    first status a child gave it.
    """
    activities = _anchor_activities(payload)
    coverage = {}
    for child in children:
        for anchor_id, item in child.coverage.items():
            if anchor_id in activities:
                coverage[anchor_id] = {'status': 'represented',
                                       'activity_ids': sorted(activities[anchor_id]),
                                       'reason': None, 'evidence_ids': []}
            else:
                coverage.setdefault(anchor_id, copy.deepcopy(item))
    return Unit(scope, payload, coverage)


def _ids(records, field) -> set:
    return {value for item in records for value in item.get(field) or []}


def reconciliation_scope(model: dict, units, *, scope_id: str,
                         parent_scope_id: str | None = None) -> dict:
    """An unsized reconciliation scope over validated `units`.

    It carries every unit's semantic records, the evidence excerpts those
    records cite, and one coverage manifest per unit. Raw graph records stay
    identity-only references: each unit already validated them against their
    full content, and re-sending them would rebuild the graph that did not fit.
    """
    units = sorted(units, key=lambda unit: unit.scope['scope_id'])
    context = record('GraphContext')
    context['capabilities'] = copy.deepcopy(model.get('capabilities', []))
    for unit in units:
        for collection in SEMANTIC_COLLECTIONS:
            for record_id, item in unit.payload[collection].items():
                existing = context[collection].get(record_id)
                if existing is not None and existing != item:
                    raise DomainError(
                        'INVALID_ID',
                        f'Child scopes proposed different records under {record_id}',
                        record_id)
                context[collection][record_id] = copy.deepcopy(item)
    for unit in units:
        _manifest(context, unit)
    semantic = [item for collection in SEMANTIC_COLLECTIONS
                for item in context[collection].values()]
    context['evidence'] = {key: copy.deepcopy(model['evidence'][key])
                           for key in sorted(_ids(semantic, 'evidence_ids'))
                           if key in model['evidence']}
    from .business_domain_synthesis import _reference_manifest
    _reference_manifest(model, context)
    validate(context, 'GraphContext')
    child_ids = [unit.scope['scope_id'] for unit in units]
    cross = sorted({edge_id for unit in units for edge_id in unit.scope['cross_scope_edge_ids']})
    manifests = [coverage_manifest(unit) for unit in units]
    scope = record(
        'GraphScope', scope_id=scope_id, scope_kind='reconciliation',
        partition_strategy='reconciliation', estimated_input_tokens=0,
        parent_scope_id=parent_scope_id,
        input_fingerprint=digest({'context': context, 'child_scope_ids': child_ids,
                                  'cross_scope_edge_ids': cross,
                                  'coverage_manifests': manifests}),
        context=context, source_representation_ids=[], canonical_anchor_ids=[],
        child_scope_ids=child_ids, cross_scope_edge_ids=cross,
        coverage_manifests=manifests)
    validate(scope, 'GraphScope')
    return scope


def coverage_manifest(unit: Unit) -> dict:
    """What one validated unit established, as its parent receives it."""
    coverage = unit.coverage
    return {
        'child_scope_id': unit.scope['scope_id'],
        'partition_strategy': unit.scope['partition_strategy'],
        'represented': [{'anchor_id': anchor_id, 'activity_ids': item['activity_ids']}
                        for anchor_id, item in sorted(coverage.items())
                        if item['status'] == 'represented' and item['activity_ids']],
        'unrepresented': [{'anchor_id': anchor_id, 'status': item['status'],
                           'reason': item['reason']}
                          for anchor_id, item in sorted(coverage.items())
                          if item['status'] != 'represented'],
        'contributed_record_ids': sorted(record_id for collection in SEMANTIC_COLLECTIONS
                                         for record_id in unit.payload[collection]),
        'cross_scope_edge_ids': list(unit.scope['cross_scope_edge_ids']),
    }


def _manifest(context: dict, unit: Unit) -> None:
    """State one unit's coverage as a claim the reconciliation can cite."""
    scope, coverage = unit.scope, unit.coverage
    by_status = {status: sorted(anchor_id for anchor_id, item in coverage.items()
                                if item['status'] == status)
                 for status in ('represented', 'excluded', 'unresolved')}
    represented = '; '.join(
        f"{anchor_id} by {', '.join(coverage[anchor_id]['activity_ids']) or 'no activity'}"
        for anchor_id in by_status['represented']) or 'none'
    others = '; '.join(
        f"{anchor_id} {coverage[anchor_id]['status']}: {coverage[anchor_id]['reason']}"
        for anchor_id in by_status['excluded'] + by_status['unresolved']) or 'none'
    contributed = sorted(record_id for collection in SEMANTIC_COLLECTIONS
                         for record_id in unit.payload[collection])
    # Cite the unit's own evidence, its dispositions first: a citation chosen
    # for another unit would not support this unit's coverage.
    evidence = [eid for item in coverage.values() for eid in item['evidence_ids']]
    evidence += [eid for collection in SEMANTIC_COLLECTIONS
                 for item in unit.payload[collection].values()
                 for eid in item.get('evidence_ids') or []]
    claim_id = identifier('claim', COVERAGE_MANIFEST, scope['scope_id'])
    context['claims'][claim_id] = record(
        'Claim', id=claim_id, subject_id=scope['scope_id'], kind=COVERAGE_MANIFEST,
        text=(f"Validated {scope['partition_strategy']} child scope {scope['scope_id']}. "
              f"Represented anchors: {represented}. "
              f"Excluded or unresolved anchors: {others}. "
              f"Records it contributes: {', '.join(contributed) or 'none'}. "
              f"Typed cross-scope edges: {', '.join(scope['cross_scope_edge_ids']) or 'none'}."),
        evidence_ids=list(dict.fromkeys(evidence))[:MANIFEST_EVIDENCE],
        trace_ids=sorted(_ids(unit.payload['activities'].values(), 'trace_ids')),
        semantic_review='supported')


def expand_reconciliation(scope: dict, payload: dict) -> dict:
    """The complete candidate a compact reconciliation answer stands for.

    A reconciliation returns only what it changes: merged or new records, its
    domains and one disposition per child, whose `incorporated_record_ids`
    name the child records it keeps or merges. Kept records, and the claims,
    rules, concepts and information uses they rest on, are copied from the
    scope into the candidate. A record the answer returns itself stands as
    returned, and a child activity whose anchors are all held by activities
    the answer returned was merged into them and is not copied.
    """
    if scope['scope_kind'] != 'reconciliation':
        return payload
    supplied = scope['context']
    expanded = copy.deepcopy(payload)
    present = {record_id for collection in SEMANTIC_COLLECTIONS
               for record_id in expanded[collection]}
    held = {anchor_id for activity in expanded['activities'].values()
            for anchor_id in activity['anchor_ids']}
    merged = {activity_id for activity_id, activity in supplied['activities'].items()
              if activity_id not in present and set(activity['anchor_ids']) <= held}
    pending = {record_id for disposition in expanded['dispositions']
               if disposition['subject_kind'] == 'child_scope'
               and disposition['status'] == 'represented'
               for record_id in disposition['incorporated_record_ids']}
    pending |= _referenced(expanded, supplied)
    while pending:
        record_id = pending.pop()
        if record_id in present or record_id in merged:
            continue
        collection = next((name for name in SEMANTIC_COLLECTIONS
                           if record_id in supplied[name]), None)
        if collection is None:
            continue
        item = copy.deepcopy(supplied[collection][record_id])
        if item.get('kind') == COVERAGE_MANIFEST:
            continue
        expanded[collection][record_id] = item
        present.add(record_id)
        pending |= _referenced({collection: {record_id: item}}, supplied) - present
        pending |= {dependent_id for name in ('information_uses', 'claims')
                    for dependent_id, dependent in supplied[name].items()
                    if dependent_id not in present and dependent.get('kind') != COVERAGE_MANIFEST
                    and record_id in (dependent.get('activity_id'), dependent.get('subject_id'))
                    and not {dependent.get('activity_id'), dependent.get('subject_id')} & merged}
    return expanded


def _referenced(payload: dict, supplied: dict) -> set:
    """Supplied semantic records the records of `payload` name."""
    known = {record_id for name in SEMANTIC_COLLECTIONS for record_id in supplied[name]}
    found = set()

    def walk(value):
        if isinstance(value, str):
            if value in known:
                found.add(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    for name in SEMANTIC_COLLECTIONS:
        walk(payload.get(name, {}))
    return found


def reconciliation_findings(units, payload: dict) -> list[dict]:
    """Repairable findings for coverage a reconciliation candidate must keep.

    Reconciliation may merge or regroup activities, never drop an anchor a
    unit represented. A child reported as represented must name records it
    contributed.
    """
    represented = set(_anchor_activities(payload))
    lost = sorted({anchor_id for unit in units for anchor_id, item in unit.coverage.items()
                   if item['status'] == 'represented' and anchor_id not in represented})
    findings = []
    if lost:
        findings.append({
            'code': 'INVALID_COVERAGE', 'severity': 'error',
            'message': ('Reconciliation dropped anchors a validated child represented; '
                        'every such anchor must stay in a reconciled activity'),
            'subject_ids': lost, 'evidence_ids': []})
    contributed = {unit.scope['scope_id']: {record_id for collection in SEMANTIC_COLLECTIONS
                                            for record_id in unit.payload[collection]}
                   for unit in units}
    for disposition in payload['dispositions']:
        if disposition['subject_kind'] == 'child_scope' and disposition['status'] == 'represented':
            unknown = set(disposition['incorporated_record_ids']) - contributed.get(
                disposition['subject_id'], set())
            if unknown:
                findings.append({
                    'code': 'INVALID_COVERAGE', 'severity': 'error',
                    'message': 'A represented child names records it did not contribute',
                    'subject_ids': sorted({disposition['subject_id'], *unknown}),
                    'evidence_ids': []})
    return findings


def unassigned_anchors(unit: Unit) -> list[dict]:
    """Published dispositions of the anchors the root does not represent."""
    return [record('Unassigned', subject_id=anchor_id,
                   status='excluded' if item['status'] == 'excluded' else 'pending',
                   reason=item['reason'])
            for anchor_id, item in sorted(unit.coverage.items())
            if item['status'] != 'represented']


def plan_reconciliation(units, build, fits) -> list[list[Unit]]:
    """Group units, in order, into the fewest stable groups whose rollup fits.

    `build(units)` returns a sized reconciliation scope. A unit that fits with
    no neighbour forms a group of one, which the caller passes up unchanged.
    """
    return [group for group, _ in _pack(list(units), build, fits)]
