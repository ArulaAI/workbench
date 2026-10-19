"""Deterministic hierarchical work scopes for business-domain activity synthesis."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from itertools import combinations

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
CROSS_SCOPE_INFORMATION = 'cross_scope_information'
MERGE_CANDIDATE = 'merge_candidate'
# What SPEED states about a reconciliation's children. The reconciliation reads
# and cites these claims; they are never part of its candidate.
SPEED_CLAIM_KINDS = frozenset({COVERAGE_MANIFEST, CROSS_SCOPE_INFORMATION, MERGE_CANDIDATE})
GROUPING_COLLECTIONS = ('domains', 'ownerships', 'relationships')
WRITE_ACCESS = frozenset({'creates', 'updates', 'deletes'})
# When two ownerships of one concept land in one domain, the stronger stands.
OWNERSHIP_STRENGTH = ('authoritative_source', 'creates', 'maintains', 'shared', 'unknown')
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


def _affinity_pack(items, build, fits, shared, tries=2):
    """Pack items into groups by the code they share, deterministically.

    A group starts from the first remaining item in canonical order and grows
    by the remaining item sharing the most with it (`shared(item)` is the set
    it brings), canonical order breaking ties; of the `tries` closest, the
    first that still fits joins. Items that share code land together, so the
    code is carried once per group instead of once per item's group. Yields
    `(group, built)` pairs like `_pack`; an item that does not fit alone is
    yielded alone for the caller to handle.
    """
    remaining = sorted(items)
    while remaining:
        group = [remaining.pop(0)]
        built = build(group)
        carried = set(shared(group[0]))
        while remaining and fits(built):
            closest = sorted(remaining, key=lambda item: (-len(shared(item) & carried), item))
            for item in closest[:tries]:
                candidate = build(group + [item])
                if fits(candidate):
                    group.append(item)
                    remaining.remove(item)
                    built, carried = candidate, carried | shared(item)
                    break
            else:
                break
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
    packed into entry-point bundles grouped by the code their traces share,
    and an anchor too large alone is cut into execution segments. No slice spans two boundaries.
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
        slices.extend(_bundles(model, anchors, build, build_segment, fits, limit,
                               lambda anchor_id: owned.get(anchor_id, set())))
    return slices


def _bundles(model, anchors, build, build_segment, fits, limit, shared) -> list[dict]:
    """Entry-point bundles over `anchors`, segmenting any anchor too large alone."""
    slices = []
    for anchor_ids, scope in _affinity_pack(anchors, build, fits, shared):
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
    # An effect several entry points reach names their traces too; in the
    # segment it serves only the segment's traces.
    view['effects'] = {key: {**effect, 'trace_ids': sorted(set(effect['trace_ids']) & set(traces))}
                       if 'trace_ids' in effect else effect
                       for key, effect in model['effects'].items()
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
    return _decode_prose_aliases(Unit(scope, payload, coverage))


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
    return _decode_prose_aliases(Unit(scope, payload, coverage))


def _ids(records, field) -> set:
    return {value for item in records for value in item.get(field) or []}


VERIFICATION_STRENGTH = ('verified', 'inferred', 'unresolved')


def _combine_records(existing, item):
    """One record two child scopes proposed under the same ID.

    An ID is derived from the fields that identify a record, never from its
    wording, so two versions describe the same thing in different words. The
    better verified version is kept, then the first child's, and the evidence
    either cites is kept.
    """
    if existing == item:
        return existing
    strength = lambda record: (VERIFICATION_STRENGTH.index(record['verification'])
                               if record.get('verification') in VERIFICATION_STRENGTH
                               else len(VERIFICATION_STRENGTH))
    kept = copy.deepcopy(item if strength(item) < strength(existing) else existing)
    if 'evidence_ids' in kept:
        kept['evidence_ids'] = sorted(
            set(existing.get('evidence_ids', [])) | set(item.get('evidence_ids', [])))
    return kept


PROSE_ALIAS = re.compile(r'_ref:(\d+)')


def _decode_prose_aliases(unit: Unit) -> Unit:
    """`unit` with the provider aliases its prose cites made readable.

    A provider names records by request-local aliases, and its explanations
    cite them. In a parent request the same alias names a different record,
    so carried prose would point at the wrong one. An alias of the unit's own
    request becomes the record's name or location; one its request did not
    send names the child scope.
    """
    text = json.dumps([unit.payload, unit.coverage])
    if not PROSE_ALIAS.search(text):
        return unit
    from .business_domain_synthesis import ProviderProjection
    try:
        canonical = ProviderProjection(unit.scope).canonical_ids
    except DomainError:
        canonical = {}
    context = unit.scope.get('context') or {}
    records = {record_id: item for collection in SEMANTIC_COLLECTIONS
               for record_id, item in unit.payload.get(collection, {}).items()}
    holders = {}
    for activity in unit.payload.get('activities', {}).values():
        for trace_id in activity.get('trace_ids', ()):
            holders.setdefault(trace_id, activity.get('name') or activity['id'])

    def label(match):
        ident = canonical.get(match.group(0))
        if ident is None:
            return f'a record of child scope {unit.scope["scope_id"]}'
        if records.get(ident, {}).get('name'):
            return f'"{records[ident]["name"]}"'
        if ident in holders:
            return f'the trace of "{holders[ident]}"'
        locator = (context.get('evidence', {}).get(ident) or {}).get('locator') or {}
        if locator.get('path'):
            return f"{locator['path']}:{locator.get('start_line', '')}".rstrip(':')
        return ident

    def rewrite(value, key=None):
        if isinstance(value, dict):
            return {name: rewrite(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item, key) for item in value]
        if isinstance(value, str) and not (key == 'id' or (key or '').endswith(('_id', '_ids'))):
            return PROSE_ALIAS.sub(label, value)
        return value
    return Unit(unit.scope, rewrite(unit.payload), rewrite(unit.coverage))


def reconciliation_scope(model: dict, units, *, scope_id: str,
                         parent_scope_id: str | None = None) -> dict:
    """An unsized reconciliation scope over validated `units`.

    It carries every unit's semantic records, the evidence excerpts those
    records cite, one coverage manifest per unit, and what SPEED derives about
    how the units connect: information one unit reads that only another
    writes, and domains of different units that one boundary may cover. Child
    concepts naming the same code type arrive as one concept. Raw graph
    records stay identity-only references: each unit already validated them
    against their full content, and re-sending them would rebuild the graph
    that did not fit.
    """
    units = [_decode_prose_aliases(unit)
             for unit in sorted(units, key=lambda unit: unit.scope['scope_id'])]
    context = record('GraphContext')
    context['capabilities'] = copy.deepcopy(model.get('capabilities', []))
    for unit in units:
        for collection in SEMANTIC_COLLECTIONS:
            for record_id, item in unit.payload[collection].items():
                existing = context[collection].get(record_id)
                context[collection][record_id] = (
                    copy.deepcopy(item) if existing is None
                    else _combine_records(existing, item))
    aliases = _merge_concepts(model, context)
    for unit in units:
        _manifest(context, unit, aliases, stable=scope_id == ROOT_SCOPE_ID)
    _state_links(model, context, units)
    semantic = [item for collection in SEMANTIC_COLLECTIONS
                for item in context[collection].values()]
    context['evidence'] = {key: copy.deepcopy(model['evidence'][key])
                           for key in sorted(_ids(semantic, 'evidence_ids'))
                           if key in model['evidence']}
    from .business_domain_synthesis import _reference_manifest
    _reference_manifest(model, context)
    child_ids = [unit.scope['scope_id'] for unit in units]
    cross = sorted({edge_id for unit in units for edge_id in unit.scope['cross_scope_edge_ids']})
    manifests = [_renamed(coverage_manifest(unit), aliases) for unit in units]
    # An anchor a child left unrepresented may be named by nothing but its
    # manifest once a reconciliation drops the records that cited it; the
    # manifest still references it, so the scope identifies it.
    for anchor_id in sorted({item['anchor_id'] for manifest in manifests
                             for status in ('represented', 'unrepresented')
                             for item in manifest[status]}):
        if (anchor_id not in context['record_refs'] and anchor_id not in context['anchors']
                and anchor_id in model.get('anchors', {})):
            context['record_refs'][anchor_id] = {
                'id': anchor_id, 'collection': 'anchors',
                'content_hash': digest(model['anchors'][anchor_id])}
    context['record_refs'] = dict(sorted(context['record_refs'].items()))
    validate(context, 'GraphContext')
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


def _manifest(context: dict, unit: Unit, aliases: dict, stable: bool = False) -> None:
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
    contributed = sorted({aliases.get(record_id, record_id)
                          for collection in SEMANTIC_COLLECTIONS
                          for record_id in unit.payload[collection]})
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
        # The root's units are reconciled in this process, in an order that
        # need not repeat; sorted, the root scope and so its repair
        # checkpoint are the same in every run.
        evidence_ids=(sorted(set(evidence)) if stable
                      else list(dict.fromkeys(evidence)))[:MANIFEST_EVIDENCE],
        trace_ids=sorted(_ids(unit.payload['activities'].values(), 'trace_ids')),
        semantic_review='supported')


def _merge_concepts(model: dict, context: dict) -> dict:
    """Merge child concepts that name one code type; return their aliases.

    Each unit names the concepts it meets independently, so one type can
    arrive as several concepts. Concepts whose qualified type names resolve to
    a common declared type are one concept, as are concepts of one name that
    information uses keep in a common store: the first by ID stands for all
    of them, with their names, symbols, evidence and claims, and every
    reference to another is rewritten to it. A bare type name resolves only
    when exactly one declared symbol carries it.
    """
    symbols = [symbol.get('qualified_name') or '' for symbol in model.get('symbols', {}).values()]
    # A dotted name such as a Java class's is the type its source file
    # declares, when exactly one file of that package path declares it.
    located = {}
    for name in symbols:
        path, _, declared_name = name.partition('::')
        if declared_name and '.' not in declared_name:
            stem = path.rpartition('.')[0] if '.' in path.rpartition('/')[2] else path
            if stem.endswith('/' + declared_name) or stem == declared_name:
                located.setdefault(declared_name, []).append((stem, name))

    def full(name):
        if '::' in name or '.' not in name:
            return name
        package_path = name.replace('.', '/')
        matches = [symbol for stem, symbol in located.get(name.rpartition('.')[2], ())
                   if stem == package_path or stem.endswith('/' + package_path)]
        return matches[0] if len(matches) == 1 else name

    def short(name):
        return name.rpartition('::')[2] if '::' in name else name.rpartition('.')[2]

    declared = {}
    qualified = [name for name in symbols if '::' in name]
    # A type another unit already named in full is declared too, though the
    # symbol table holds no symbol for it, as for a class property.
    qualified += [full(name) for concept in context['concepts'].values()
                  for name in concept['qualified_type_names']
                  if '::' in name or '.' in name]
    for name in qualified:
        declared.setdefault(short(name), set()).add(name)

    def resolve(name):
        if '::' in name:
            return name
        matches = declared.get(name, ())
        if len(matches) == 1:
            return next(iter(matches))
        return full(name) if '.' in name else None

    parent = {}

    def root(concept_id):
        while parent.get(concept_id, concept_id) != concept_id:
            concept_id = parent[concept_id]
        return concept_id

    def union(concept_id, other_id):
        one, other = sorted((root(concept_id), root(other_id)))
        if one != other:
            parent[other] = one

    # Concepts naming one type are that type's concept. One naming several
    # types joins them only where they are already one concept: it does not
    # make two types it happens to mention the same thing.
    keys = {concept_id: {key for key in map(resolve, concept['qualified_type_names'])
                         if key is not None}
            for concept_id, concept in context['concepts'].items()}
    first = {}
    for concept_id in sorted(context['concepts']):
        if len(keys[concept_id]) != 1:
            continue
        [key] = keys[concept_id]
        if key in first:
            union(first[key], concept_id)
        else:
            first[key] = concept_id
    same_types = {}
    for concept_id in sorted(context['concepts']):
        if len(keys[concept_id]) > 1:
            group = frozenset(keys[concept_id])
            if group in same_types:
                union(same_types[group], concept_id)
            else:
                same_types[group] = concept_id
    for concept_id in sorted(context['concepts']):
        if len(keys[concept_id]) > 1 and all(key in first for key in keys[concept_id]):
            roots = {root(first[key]) for key in keys[concept_id]}
            if len(roots) == 1:
                union(roots.pop(), concept_id)
    # A concept a unit named without its type is the concept of the same name
    # another unit keeps in the same store.
    stores = {}
    for use in context['information_uses'].values():
        if use.get('concept_id'):
            stores.setdefault(use['concept_id'], set()).update(use['resource_ids'])
    named = {}
    for concept_id in sorted(context['concepts']):
        name = _plain(context['concepts'][concept_id].get('name') or '')
        for other in named.get(name, ()) if name else ():
            if stores.get(concept_id, set()) & stores.get(other, set()):
                one, other = sorted((root(other), root(concept_id)))
                if one != other:
                    parent[other] = one
        named.setdefault(name, []).append(concept_id)
    # A concept named without any type is the one typed concept of its name.
    for name, concept_ids in named.items():
        typed = {root(concept_id) for concept_id in concept_ids
                 if context['concepts'][concept_id]['qualified_type_names']}
        if not name or len(typed) != 1:
            continue
        [kept] = typed
        for concept_id in concept_ids:
            if not context['concepts'][concept_id]['qualified_type_names']:
                one, other = sorted((kept, root(concept_id)))
                if one != other:
                    parent[other] = one
                kept = root(kept)
    aliases = {concept_id: root(concept_id) for concept_id in context['concepts']
               if root(concept_id) != concept_id}
    for alias, canonical in sorted(aliases.items()):
        kept, merged = context['concepts'][canonical], context['concepts'].pop(alias)
        for field in ('qualified_type_names', 'symbol_ids', 'evidence_ids', 'claim_ids'):
            kept[field] = sorted(set(kept[field]) | set(merged[field]))
    if aliases:
        for collection in SEMANTIC_COLLECTIONS:
            for record_id, item in context[collection].items():
                context[collection][record_id] = _renamed(item, aliases)
    return aliases


def _renamed(value, aliases):
    """`value` with every ID in `aliases` replaced, lists of IDs deduplicated."""
    if isinstance(value, str):
        return aliases.get(value, value)
    if isinstance(value, list):
        items = [_renamed(item, aliases) for item in value]
        if all(isinstance(item, str) for item in items):
            return list(dict.fromkeys(items))
        return items
    if isinstance(value, dict):
        return {key: _renamed(item, aliases) for key, item in value.items()}
    return value


def _children_of(units, activities: dict) -> dict:
    """The units whose anchors each activity carries."""
    unit_of = {anchor_id: unit.scope['scope_id'] for unit in units
               for anchor_id in unit.coverage}
    return {activity_id: {unit_of[anchor_id] for anchor_id in activity['anchor_ids']
                          if anchor_id in unit_of}
            for activity_id, activity in activities.items()}


def cross_scope_reads(activities: dict, uses: dict, children: dict) -> list:
    """`(reader, resource, writers)` for information only other units write.

    A unit validated the links between its own activities; what one unit's
    activity reads and only activities of other units create, update or
    delete is a dependency no unit could see.
    """
    writers, readers = {}, {}
    for use in uses.values():
        if use['activity_id'] not in activities:
            continue
        target = (writers if use['access'] in WRITE_ACCESS
                  else readers if use['access'] == 'reads' else None)
        for resource_id in use['resource_ids'] if target is not None else ():
            target.setdefault(resource_id, set()).add(use['activity_id'])
    found = []
    for resource_id, reading in sorted(readers.items()):
        writing = writers.get(resource_id, set())
        for reader in sorted(reading - writing):
            own = children.get(reader, set())
            if writing and not any(children.get(writer, set()) & own for writer in writing):
                found.append((reader, resource_id, sorted(writing)))
    return found


def _owner(model: dict, anchor_id: str) -> str | None:
    """The class, or else the module, that implements an anchor.

    An operation an API contract documents is owned by the code implementing
    it, not by the contract file every documented operation shares.
    """
    anchor = model.get('anchors', {}).get(anchor_id) or {}
    representations = [item for item in anchor.get('representations') or ()
                       if isinstance(item, dict)]
    implementations = sorted(item['symbol_id'] for item in representations
                             if item.get('role') == 'implementation' and item.get('symbol_id'))
    contracts = {item.get('symbol_id') for item in representations
                 if item.get('role') == 'contract'}
    symbol_id = implementations[0] if implementations else anchor.get('symbol_id')
    if not implementations and symbol_id in contracts:
        return None
    symbol = model.get('symbols', {}).get(symbol_id) or {}
    module, _, member = (symbol.get('qualified_name') or '').rpartition('::')
    if not module:
        return None
    return f'{module}::{member.rpartition(".")[0]}' if '.' in member else module


def _plain(name: str) -> str:
    return ''.join(character for character in name.casefold() if character.isalnum())


def merge_candidates(model: dict, domains: dict, activities: dict, children: dict) -> list:
    """`(domain, domain, shared owners)` that one business boundary may cover.

    Units are cut by size, so entry points one class or module declares can
    land in different units and come back as different domains. Two domains
    of disjoint units are candidates when their primary activities' anchors
    share a declaring class or module, or when the domains bear the same name.
    """
    owners, names, units = {}, {}, {}
    for domain_id, domain in domains.items():
        members = [membership['activity_id'] for membership in domain['activity_memberships']
                   if membership['activity_id'] in activities and membership['role'] == 'primary']
        owners[domain_id] = {_owner(model, anchor_id) for activity_id in members
                             for anchor_id in activities[activity_id]['anchor_ids']} - {None}
        names[domain_id] = _plain(domain['name'])
        units[domain_id] = set().union(*(children.get(activity_id, set())
                                         for activity_id in members))
    found = []
    for one, other in combinations(sorted(domains), 2):
        if not units[one] or not units[other] or units[one] & units[other]:
            continue
        shared = sorted(owners[one] & owners[other])
        if shared or names[one] == names[other]:
            found.append((one, other, shared))
    return found


def _state_links(model: dict, context: dict, units) -> None:
    """State, as claims, how the units connect where no unit could see it."""
    activities = context['activities']
    children = _children_of(units, activities)
    reads = {}
    for reader, resource_id, writers in cross_scope_reads(
            activities, context['information_uses'], children):
        reads.setdefault(resource_id, []).append((reader, writers))
    for resource_id, entries in sorted(reads.items()):
        resource = model.get('resources', {}).get(resource_id) or {}
        writers = sorted({writer for _, found in entries for writer in found})
        readers = [reader for reader, _ in entries]
        evidence = [eid for use in context['information_uses'].values()
                    if resource_id in use['resource_ids']
                    and use['activity_id'] in {*readers, *writers}
                    for eid in use['evidence_ids']]
        _speed_claim(context, CROSS_SCOPE_INFORMATION, resource_id, (
            f"{resource.get('name') or resource_id} ({resource_id}) is read by "
            f"{_named(activities, readers)} and written only in other child scopes, by "
            f"{_named(activities, writers)}. Link each reader to a writer with a "
            'uses_information_from relationship, or place them in one domain.'),
            evidence, model)
    for one, other, shared in merge_candidates(model, context['domains'], activities, children):
        domains = context['domains']
        basis = (f"entry points declared by {', '.join(shared)}" if shared
                 else 'the same name')
        _speed_claim(context, MERGE_CANDIDATE, one, (
            f"Domains {one} ({domains[one]['name']}) and {other} ({domains[other]['name']}) "
            f'come from different child scopes and share {basis}. Merge them into one '
            'returned domain, or return one of them with an alternative naming the other '
            'and the evidence for keeping them separate.'),
            [*domains[one]['evidence_ids'], *domains[other]['evidence_ids']], model,
            key=other)


def _named(activities: dict, activity_ids) -> str:
    return ', '.join(f"{activity_id} ({activities[activity_id]['name']})"
                     for activity_id in activity_ids)


def _speed_claim(context, kind, subject_id, text, evidence, model, key=None) -> None:
    claim_id = identifier('claim', kind, subject_id, key)
    context['claims'][claim_id] = record(
        'Claim', id=claim_id, subject_id=subject_id, kind=kind, text=text,
        evidence_ids=[eid for eid in dict.fromkeys(evidence)
                      if eid in model.get('evidence', {})][:MANIFEST_EVIDENCE],
        trace_ids=[], semantic_review='supported')


def expand_reconciliation(scope: dict, payload: dict, model: dict | None = None) -> dict:
    """The complete candidate a compact reconciliation answer stands for.

    A reconciliation returns only what it changes: merged or new records, the
    domains it forms or changes, and one disposition per child whose
    `incorporated_record_ids` name the child activities, rules, concepts and
    information uses it keeps. Kept records, and the claims, rules, concepts
    and information uses they rest on, are copied from the scope. A child
    activity whose anchors are all held by activities the answer returned was
    merged into them and is not copied.

    The children's groupings stay unless the answer changes them; see
    `_regroup`. SPEED does this bookkeeping so the answer never has to
    restate what it keeps.
    """
    if scope['scope_kind'] != 'reconciliation':
        return payload
    supplied = scope['context']
    expanded = copy.deepcopy(payload)
    returned = {record_id for collection in SEMANTIC_COLLECTIONS
                for record_id in expanded[collection]}
    supplied_ids = {record_id for collection in SEMANTIC_COLLECTIONS
                    for record_id in supplied[collection]}
    held = {anchor_id for activity in expanded['activities'].values()
            for anchor_id in activity['anchor_ids']}
    merged = {activity_id for activity_id, activity in supplied['activities'].items()
              if activity_id not in returned and set(activity['anchor_ids']) <= held}
    named = {record_id for disposition in expanded['dispositions']
             if disposition['subject_kind'] == 'child_scope'
             and disposition['status'] == 'represented'
             for record_id in disposition['incorporated_record_ids']}
    for disposition in expanded['dispositions']:
        if disposition['subject_kind'] == 'child_scope':
            # The answer's own records are not child records it incorporates.
            disposition['incorporated_record_ids'] = [
                record_id for record_id in disposition['incorporated_record_ids']
                if record_id not in returned or record_id in supplied_ids]
    _carry(expanded, supplied, named | _referenced(expanded, supplied), merged)
    _regroup(expanded, supplied, merged)
    groupings = {record_id for collection in GROUPING_COLLECTIONS
                 for record_id in expanded[collection]}
    _carry(expanded, supplied,
           _referenced({collection: expanded[collection] for collection in GROUPING_COLLECTIONS},
                       supplied)
           | {claim_id for claim_id, claim in supplied['claims'].items()
              if claim['subject_id'] in groupings},
           merged)
    # After everything kept is carried, so no kept domain or activity brings a
    # replaced rule back.
    # At the root, a child rule the answer returns changed is the answer's
    # revision of it: it replaces the child rules it describes, and no stale
    # copy is merged back into it.
    revised = (frozenset(rule_id for rule_id, rule in payload['rules'].items()
                         if rule_id in supplied['rules'] and rule != supplied['rules'][rule_id])
               if scope.get('scope_id') == ROOT_SCOPE_ID else frozenset())
    _supersede_rules(expanded, supplied, revised)
    _merge_duplicate_rules(expanded, scope, revised)
    _rehome(expanded, supplied, merged, listed=scope.get('scope_id') == ROOT_SCOPE_ID)
    _supersede_claims(expanded, supplied, returned)
    _drop_orphan_rules(expanded, supplied, returned)
    _drop_replaced_references(expanded, supplied, returned)
    if model is not None:
        _drop_delegating_owners(expanded, model)
        _attach_rules_to_enforcers(expanded, model)
        _link_direct_calls(expanded, model, set(supplied.get('evidence', {})))
        _contract_status_conflicts(expanded, model, set(supplied.get('evidence', {})))
    _link_information_flow(expanded, set(supplied.get('evidence', {})))
    _keep_writers(expanded)
    _prune_symbol_memberships(expanded)
    _collect_domain_rules(expanded, returned, supplied)
    _link_claims(expanded)
    return expanded


# Spring status names Python's HTTPStatus lacks, and ResponseEntity helpers.
SPRING_STATUS = {'MOVED_TEMPORARILY': 302, 'PAYLOAD_TOO_LARGE': 413, 'URI_TOO_LONG': 414,
                 'I_AM_A_TEAPOT': 418, 'CHECKPOINT': 103, 'METHOD_FAILURE': 420,
                 'DESTINATION_LOCKED': 421, 'INSUFFICIENT_SPACE_ON_RESOURCE': 419}
RESPONSE_HELPERS = {'ok': 200, 'created': 201, 'accepted': 202, 'noContent': 204,
                    'badRequest': 400, 'notFound': 404, 'unprocessableEntity': 422,
                    'internalServerError': 500}


def _returned_statuses(expression: str) -> set:
    from http import HTTPStatus
    codes = set()
    for name in re.findall(r'HttpStatus\.([A-Z_]+)', expression or ''):
        status = SPRING_STATUS.get(name) or getattr(HTTPStatus, name, None)
        if status is not None:
            codes.add(str(int(status)))
    for helper in re.findall(r'ResponseEntity\s*\.\s*(\w+)\s*\(', expression or ''):
        if helper in RESPONSE_HELPERS:
            codes.add(str(RESPONSE_HELPERS[helper]))
    return codes


def _contract_status_conflicts(expanded: dict, model: dict, citable: set) -> None:
    """State where an operation's code returns a status its contract omits.

    Both sides are facts: the contract's declared responses and the statuses
    the implementing method returns. Slices notice the difference unevenly,
    and a merge of one that did with one that did not reads as an ignored
    contradiction, so SPEED states each one, keyed by anchor so it follows
    whichever activity holds the anchor. Only a status the code returns and
    the contract omits is stated: a declared status the code never returns
    may come from an exception handler.
    """
    bindings = model.get('bindings', {})
    by_source = {}
    for binding in bindings.values():
        if binding.get('direction') == 'output':
            by_source.setdefault((binding.get('source') or {}).get('id'), []).append(binding)
    claims = expanded['claims']
    for activity_id in sorted(expanded['activities']):
        activity = expanded['activities'][activity_id]
        for anchor_id in activity.get('anchor_ids', ()):
            anchor = model.get('anchors', {}).get(anchor_id) or {}
            representations = {item['id']: item for item in anchor.get('representations') or ()
                               if isinstance(item, dict) and 'id' in item}
            for correspondence in anchor.get('correspondences') or ():
                contract = representations.get(correspondence.get('from_representation'))
                if (correspondence.get('state') != 'resolved' or not contract
                        or contract.get('role') != 'contract'):
                    continue
                declared = {binding['name'].split(':')[1]: binding
                            for binding in by_source.get(contract.get('symbol_id'), ())
                            if binding.get('name', '').startswith('response:')}
                if not declared or any(code == 'default' or code.upper().endswith('XX')
                                       for code in declared):
                    continue
                implementations = sorted({
                    representations[target]['symbol_id']
                    for target in correspondence.get('to_representations', ())
                    if representations.get(target, {}).get('role') == 'implementation'
                    and representations[target].get('symbol_id')})
                for symbol_id in implementations:
                    for binding in by_source.get(symbol_id, ()):
                        for code in sorted(_returned_statuses(binding.get('expression')) - set(declared)):
                            evidence = sorted({evidence_id for item in (*declared.values(), binding)
                                               for evidence_id in item.get('evidence_ids', ())
                                               if evidence_id in citable})
                            if len(evidence) < 2:
                                continue
                            claim_id = identifier('claim', 'contract_status', anchor_id, code)
                            if claim_id in claims:
                                claims[claim_id]['subject_id'] = activity_id
                                continue
                            if any(claim['subject_id'] == activity_id
                                   and claim.get('kind') == 'conflict' and code in claim['text']
                                   for claim in claims.values()):
                                continue
                            operation = anchor.get('operation') or {}
                            name = ' '.join(filter(None, (operation.get('method', '').upper()
                                                          if operation.get('method') else None,
                                                          operation.get('path'))))
                            claims[claim_id] = record(
                                'Claim', id=claim_id, subject_id=activity_id, kind='conflict',
                                text=(f'The contract for {name or anchor_id} declares responses '
                                      f'{", ".join(sorted(declared))}, but the implementation '
                                      f'returns {code}, which the contract does not declare.'),
                                evidence_ids=evidence,
                                trace_ids=sorted(activity.get('trace_ids', ())),
                                semantic_review='uncertain')


# The accesses that establish each kind of authoritative ownership.
OWNING_ACCESS = {'creates': frozenset({'creates'}),
                 'maintains': WRITE_ACCESS,
                 'authoritative_source': WRITE_ACCESS}


def _keep_writers(expanded: dict) -> None:
    """Keep in each authoritative ownership only the activities that write it.

    A creates ownership rests on creating the concept, and a maintains or
    authoritative one on writing it; an activity whose uses of the concept do
    neither leaves the ownership. One left with no such activity stays as it
    is, for review to judge. An ownership cites only its activities' uses.
    """
    uses = expanded['information_uses']
    for ownership in expanded['ownerships'].values():
        owning = OWNING_ACCESS.get(ownership['kind'])
        if owning is not None:
            writers = [activity_id for activity_id in ownership['activity_ids']
                       if any(use['activity_id'] == activity_id
                              and use['concept_id'] == ownership['concept_id']
                              and use['access'] in owning for use in uses.values())]
            if writers:
                ownership['activity_ids'] = writers
        held = set(ownership['activity_ids'])
        ownership['information_use_ids'] = [
            use_id for use_id in ownership['information_use_ids']
            if uses.get(use_id, {}).get('activity_id') in held]


def _call_graph(expanded: dict, model: dict) -> tuple[dict, dict]:
    """Each activity's entry-point symbols, and the symbols its traces reach."""
    entry, reached = {}, {}
    for activity_id, activity in expanded['activities'].items():
        entry[activity_id] = {model['anchors'][anchor_id].get('symbol_id')
                              for anchor_id in activity['anchor_ids']
                              if anchor_id in model.get('anchors', {})} - {None}
        reached[activity_id] = {symbol_id for trace_id in activity['trace_ids']
                                for symbol_id in model.get('traces', {}).get(
                                    trace_id, {}).get('symbol_ids', ())}
    return entry, reached


def _link_direct_calls(expanded: dict, model: dict, citable: set) -> None:
    """Record a direct call from one domain's activity to another's.

    An activity whose own code calls another activity's entry point requests
    action from it. A call made inside a third activity it calls is that
    activity's, not a direct one. A call between domains no relationship
    records yet gets one, resting on the call's evidence the scope supplies.
    """
    entry, reached = _call_graph(expanded, model)
    activities = expanded['activities']
    home = _home_domains(expanded)
    linked = {frozenset((item['from_activity_id'], item['to_activity_id']))
              for item in expanded['relationships'].values()}
    calls = [edge for edge in model.get('edges', {}).values()
             if edge.get('kind') == 'calls' and (edge.get('to_ref') or {}).get('kind') == 'symbol'
             and edge.get('from_ref')]
    for caller in sorted(activities):
        delegated = set().union(*(reached[other] for other in activities
                                  if other != caller and entry[other] & reached[caller]))
        own = reached[caller] - delegated | entry[caller]
        for callee in sorted(activities):
            if (callee == caller or frozenset((caller, callee)) in linked
                    or home.get(caller) is None or home.get(callee) is None
                    or home[caller] == home[callee]):
                continue
            evidence = sorted({evidence_id for edge in calls
                               if edge['to_ref']['id'] in entry[callee]
                               and edge['from_ref'].get('id') in own
                               for evidence_id in edge['evidence_ids'] if evidence_id in citable})
            if not evidence:
                continue
            relationship_id = identifier('relationship', caller, callee, 'requests_action_from')
            expanded['relationships'][relationship_id] = record(
                'Relationship', id=relationship_id, from_activity_id=caller,
                to_activity_id=callee, from_domain_id=home[caller], to_domain_id=home[callee],
                kind='requests_action_from', trace_ids=list(activities[caller]['trace_ids']),
                evidence_ids=evidence[:MANIFEST_EVIDENCE])
            linked.add(frozenset((caller, callee)))


def _link_information_flow(expanded: dict, citable: set) -> None:
    """Record that an activity uses information another domain's activity writes.

    Information uses state what each activity reads and writes. A reader in
    one domain of a resource a writer in another domain writes uses
    information from it; a pair no relationship records yet gets one,
    resting on the reader's and writer's evidence for that resource.
    """
    home = _home_domains(expanded)
    activities = expanded['activities']
    linked = {frozenset((item['from_activity_id'], item['to_activity_id']))
              for item in expanded['relationships'].values()}
    readers, writers = {}, {}
    for use in expanded['information_uses'].values():
        if use['activity_id'] not in activities:
            continue
        # Deleting information is not a source of it.
        target = (writers if use['access'] in ('creates', 'updates')
                  else readers if use['access'] == 'reads' else None)
        for resource_id in use['resource_ids'] if target is not None else ():
            target.setdefault(resource_id, {}).setdefault(use['activity_id'], set()).update(
                evidence_id for evidence_id in use.get('evidence_ids', ()) if evidence_id in citable)
    for resource_id in sorted(readers):
        for reader, reader_evidence in sorted(readers[resource_id].items()):
            for writer, writer_evidence in sorted(writers.get(resource_id, {}).items()):
                pair = frozenset((reader, writer))
                if (reader == writer or pair in linked or home.get(reader) is None
                        or home.get(writer) is None or home[reader] == home[writer]):
                    continue
                evidence = sorted(reader_evidence | writer_evidence)
                if not evidence:
                    continue
                relationship_id = identifier('relationship', reader, writer, 'uses_information_from')
                expanded['relationships'][relationship_id] = record(
                    'Relationship', id=relationship_id, from_activity_id=reader,
                    to_activity_id=writer, from_domain_id=home[reader], to_domain_id=home[writer],
                    kind='uses_information_from',
                    trace_ids=list(activities[reader].get('trace_ids', ())),
                    evidence_ids=evidence[:MANIFEST_EVIDENCE])
                linked.add(pair)


def _attach_rules_to_enforcers(expanded: dict, model: dict) -> None:
    """A rule enforced inside an activity another one calls applies to both.

    A rule attached to a calling activity, whose enforcement sites all lie
    within the trace of an activity it calls, is enforced by that activity
    too, and is attached to it.
    """
    entry, reached = _call_graph(expanded, model)
    activities = expanded['activities']
    for rule_id in sorted(expanded['rules']):
        rule = expanded['rules'][rule_id]
        sites = {site['source_id'] for site in rule.get('enforcement_sites') or ()}
        if not sites:
            continue
        callers = [activity_id for activity_id, activity in activities.items()
                   if rule_id in activity.get('rule_ids', ())]
        for activity_id in sorted(activities):
            activity = activities[activity_id]
            if (rule_id not in activity.get('rule_ids', ()) and sites <= reached[activity_id]
                    and any(entry[activity_id] & reached[caller] for caller in callers)):
                activity['rule_ids'] = [*activity['rule_ids'], rule_id]


def _drop_delegating_owners(expanded: dict, model: dict) -> None:
    """Credit a write to the activity that performs it, not to one calling it.

    An activity whose trace calls another activity's entry point reaches that
    activity's writes too. Where every write it makes of a concept is one the
    called activity also makes, it only requests the change: it leaves the
    authoritative ownerships of that concept, and an ownership left with no
    activity goes when the called activity's domain owns the concept.
    """
    activities = expanded['activities']
    entry, reached = _call_graph(expanded, model)
    writes = {}
    for use in expanded['information_uses'].values():
        if use['access'] in WRITE_ACCESS and use['activity_id'] in activities:
            writes.setdefault((use['activity_id'], use['concept_id']), set()).update(use['effect_ids'])

    def delegate(activity_id, concept_id):
        """The activity `activity_id` calls that makes all its writes of the concept."""
        own = writes.get((activity_id, concept_id), set())
        return next((other for other in sorted(activities)
                     if other != activity_id and entry[other] & reached[activity_id]
                     and own and own <= writes.get((other, concept_id), set())), None)

    authoritative = ('creates', 'maintains', 'authoritative_source')
    removed = set()
    for ownership_id in sorted(expanded['ownerships']):
        ownership = expanded['ownerships'][ownership_id]
        if ownership['kind'] not in authoritative:
            continue
        concept_id = ownership['concept_id']
        delegated = {activity_id: delegate(activity_id, concept_id)
                     for activity_id in ownership['activity_ids']}
        kept = [activity_id for activity_id, other in delegated.items() if other is None]
        if kept:
            ownership['activity_ids'] = kept
            continue
        callees = set(delegated.values())
        owned_elsewhere = any(
            other_id != ownership_id and other['concept_id'] == concept_id
            and other['kind'] in authoritative and callees & set(other['activity_ids'])
            for other_id, other in expanded['ownerships'].items())
        if owned_elsewhere:
            del expanded['ownerships'][ownership_id]
            removed.add(ownership_id)
            removed |= {claim_id for claim_id, claim in expanded['claims'].items()
                        if claim['subject_id'] == ownership_id}
    for claim_id in removed & set(expanded['claims']):
        del expanded['claims'][claim_id]
    if removed:
        for name in SEMANTIC_COLLECTIONS:
            for record_id, item in expanded[name].items():
                expanded[name][record_id] = _without(item, removed)


def _prune_symbol_memberships(expanded: dict) -> None:
    """A domain's symbol memberships name only activities the candidate holds.

    Acceptance derives them again from the activities; until then they must
    not credit an activity the reconciliation replaced.
    """
    for domain in expanded['domains'].values():
        if 'symbol_memberships' in domain:
            domain['symbol_memberships'] = [
                membership for membership in domain['symbol_memberships']
                if membership.get('activity_id') in expanded['activities']]


def _collect_domain_rules(expanded: dict, returned=frozenset(), supplied=None) -> None:
    """A domain lists the rules its primary activities apply, and a rule the
    activities that apply it.

    A rule naming an activity is listed back by it, unless the answer returned
    that activity without the rule a child carried: the answer's record wins.
    A technical rule is listed on a domain only where the domain names it.
    """
    carried = set((supplied or {}).get('rules', ())) - set(returned)
    for rule_id in sorted(expanded['rules']):
        rule = expanded['rules'][rule_id]
        for activity_id in list(rule.get('activity_ids') or ()):
            activity = expanded['activities'].get(activity_id)
            if activity is None or 'rule_ids' not in activity or rule_id in activity['rule_ids']:
                continue
            if activity_id in returned and rule_id in carried:
                rule['activity_ids'].remove(activity_id)
            elif rule.get('enforcement_status') != 'verified_on_trace':
                # Enforcement verified on a trace is checked against every
                # trace of each activity applying the rule; that is the
                # child's claim to make, not SPEED's.
                activity['rule_ids'] = [*activity['rule_ids'], rule_id]
    for rule_id, rule in expanded['rules'].items():
        if 'activity_ids' in rule:
            rule['activity_ids'] = list(dict.fromkeys([
                *rule['activity_ids'],
                *sorted(activity_id for activity_id, activity in expanded['activities'].items()
                        if rule_id in activity.get('rule_ids', ()))]))
    for domain in expanded['domains'].values():
        applied = [rule_id for membership in domain.get('activity_memberships', ())
                   if membership['role'] == 'primary'
                   for rule_id in expanded['activities'].get(
                       membership['activity_id'], {}).get('rule_ids', ())
                   if rule_id in expanded['rules']
                   and expanded['rules'][rule_id].get('category') != 'technical']
        if 'rules' in domain:
            domain['rules'] = list(dict.fromkeys([*domain['rules'], *applied]))


def _rule_basis(rule: dict):
    """What identifies the rule a record describes, or None.

    A rule over observations is the rule those observations show. One with
    none is identified by where it is enforced and what kind of check it is.
    """
    observed = frozenset(rule.get('observation_ids') or ())
    if observed:
        return ('observed', observed)
    sites = frozenset(site['source_id'] for site in rule.get('enforcement_sites') or ())
    if sites:
        return ('enforced', sites, rule.get('evaluation_kind'))
    # A rule only documented or tested is identified by what it is called.
    name = _plain(rule.get('name') or '')
    return ('named', name) if name else None


def _words(name: str) -> set:
    words = {''.join(character for character in word if character.isalnum())
             for word in name.casefold().split()}
    return {word for word in words if len(word) > 2}


def _same_rule(rule: dict, other: dict, *, within: bool = False) -> bool:
    """Whether two rule records describe one rule.

    Rules over observations are one rule when their observations agree; with
    `within`, when `rule`'s lie within `other`'s. Rules without are one rule
    when enforced at the same sites, or `rule`'s within `other`'s, and they
    are the same kind of check or plainly name the same rule.
    """
    observed, others = set(rule.get('observation_ids') or ()), set(other.get('observation_ids') or ())
    if observed or others:
        return bool(observed) and (observed <= others if within else observed == others)
    sites = {site['source_id'] for site in rule.get('enforcement_sites') or ()}
    covering = {site['source_id'] for site in other.get('enforcement_sites') or ()}
    if not sites and not covering:
        name = _plain(rule.get('name') or '')
        return bool(name) and name == _plain(other.get('name') or '')
    if not sites or not (sites <= covering if within else sites == covering):
        return False
    if rule.get('evaluation_kind') == other.get('evaluation_kind'):
        return True
    words, other_words = _words(rule.get('name', '')), _words(other.get('name', ''))
    return len(words & other_words) * 2 >= max(len(words), len(other_words), 1)


def _merge_duplicate_rules(expanded: dict, scope: dict, revised=frozenset()) -> None:
    """Make one rule of the copies different children kept of it.

    Children describe one rule independently. Where the answer left copies
    from different children that describe the same rule, the copy most
    activities apply stands for all of them, with their activities,
    concepts, sites, evidence, observations, conflicts and questions, and
    what named another names it.
    """
    child_of = {record_id: manifest['child_scope_id']
                for manifest in scope.get('coverage_manifests', ())
                for record_id in manifest.get('contributed_record_ids', ())
                if record_id not in revised}
    rules = expanded['rules']
    groups = []
    for rule_id in sorted(rules):
        if rule_id not in child_of or _rule_basis(rules[rule_id]) is None:
            continue
        group = next((group for group in groups if _same_rule(rules[rule_id], rules[group[0]])), None)
        if group is None:
            groups.append([rule_id])
        else:
            group.append(rule_id)
    replaced = {}
    for group in groups:
        if len({child_of[rule_id] for rule_id in group}) < 2:
            continue
        group.sort(key=lambda rule_id: (-len(rules[rule_id].get('activity_ids') or ()), rule_id))
        kept = rules[group[0]]
        for rule_id in group[1:]:
            other = rules.pop(rule_id)
            replaced[rule_id] = group[0]
            for field in ('activity_ids', 'concept_ids', 'evidence_ids', 'observation_ids',
                          'conflicts', 'unresolved_questions'):
                if field in kept:
                    kept[field] = list(dict.fromkeys([*kept[field], *(other.get(field) or ())]))
            if 'enforcement_sites' in kept:
                sources = {site['source_id'] for site in kept['enforcement_sites']}
                kept['enforcement_sites'] += [site for site in other.get('enforcement_sites') or ()
                                              if site['source_id'] not in sources]
    if replaced:
        for collection in SEMANTIC_COLLECTIONS:
            for record_id, item in expanded[collection].items():
                expanded[collection][record_id] = _renamed(item, replaced)


def _supersede_rules(expanded: dict, supplied: dict, revised=frozenset()) -> None:
    """Replace child rules with the returned rule describing the same rule.

    Children describe one rule independently; a rule the answer returns
    replaces every child rule with its basis, or citing only observations it
    cites, and what named a replaced rule names the returned one.
    """
    returned = {rule_id: rule for rule_id, rule in expanded['rules'].items()
                if (rule_id not in supplied['rules'] or rule_id in revised) and _rule_basis(rule)}
    replaced = {}
    for rule_id in sorted(supplied['rules']):
        rule = supplied['rules'][rule_id]
        if rule_id in returned or _rule_basis(rule) is None:
            continue
        successor = min((other for other, candidate in returned.items()
                         if _same_rule(rule, candidate, within=True)
                         and not _different_checks(rule, candidate)),
                        default=None)
        if successor is not None:
            replaced[rule_id] = successor
    if not replaced:
        return
    for rule_id in replaced:
        expanded['rules'].pop(rule_id, None)
    for collection in SEMANTIC_COLLECTIONS:
        for record_id, item in expanded[collection].items():
            expanded[collection][record_id] = _renamed(item, replaced)


def _different_checks(rule: dict, other: dict) -> bool:
    """Whether two rules are plainly different checks, whatever they cite.

    One observation cited by mistake should not make an authorization check
    part of a data constraint enforced elsewhere.
    """
    categories = {rule.get('category'), other.get('category')} - {None, 'unclassified'}
    sites = {site['source_id'] for site in rule.get('enforcement_sites') or ()}
    other_sites = {site['source_id'] for site in other.get('enforcement_sites') or ()}
    return len(categories) == 2 and bool(sites) and bool(other_sites) and not sites & other_sites


def _rehome(expanded: dict, supplied: dict, merged: set, listed: bool = False) -> None:
    """Give a merged activity what was established about the activities it replaced.

    A child activity's information uses and the claims about its behaviour
    follow its anchors and traces, which the activity now holding those
    anchors holds; they move to it unless the answer stated that activity's
    uses, or its claims, itself.
    """
    activities = expanded['activities']
    holder = {}
    for activity_id in sorted(activities):
        for anchor_id in activities[activity_id]['anchor_ids']:
            holder.setdefault(anchor_id, activity_id)

    def target_of(activity_id):
        return next((holder[anchor_id] for anchor_id
                     in supplied['activities'][activity_id]['anchor_ids']
                     if anchor_id in holder), None)

    described = {claim['subject_id'] for claim in expanded['claims'].values()}
    for claim_id in sorted(supplied['claims']):
        claim = supplied['claims'][claim_id]
        if claim['subject_id'] not in merged or claim.get('kind') in SPEED_CLAIM_KINDS:
            continue
        target = target_of(claim['subject_id'])
        if target is not None and target not in described and claim_id not in expanded['claims']:
            expanded['claims'][claim_id] = {**copy.deepcopy(claim), 'subject_id': target}
    stated = {use['activity_id'] for use in expanded['information_uses'].values()}
    seen = {_use_key(use) for use in expanded['information_uses'].values()}
    # With `listed`, a merged activity the answer returns naming its uses
    # takes only the child uses it names.
    chosen = {activity_id: set(activity['information_use_ids'])
              for activity_id, activity in activities.items()
              if listed and activity_id not in supplied['activities']
              and activity.get('information_use_ids')}
    for use_id in sorted(supplied['information_uses']):
        use = supplied['information_uses'][use_id]
        if use['activity_id'] not in merged:
            continue
        target = target_of(use['activity_id'])
        if target is None or target in stated:
            continue
        if target in chosen and use_id not in chosen[target]:
            continue
        item = {**copy.deepcopy(use), 'activity_id': target}
        if _use_key(item) in seen:
            continue
        seen.add(_use_key(item))
        expanded['information_uses'][use_id] = item
        activity = activities[target]
        activity['information_use_ids'] = list(dict.fromkeys(
            [*activity['information_use_ids'], use_id]))
        if use['concept_id'] in expanded['concepts'] or use['concept_id'] in supplied['concepts']:
            activity['concept_ids'] = list(dict.fromkeys([*activity['concept_ids'],
                                                          use['concept_id']]))
            if use['concept_id'] not in expanded['concepts']:
                expanded['concepts'][use['concept_id']] = copy.deepcopy(
                    supplied['concepts'][use['concept_id']])


def _use_key(use: dict) -> tuple:
    return (use['activity_id'], use['concept_id'], tuple(sorted(use['resource_ids'])),
            use['access'])


def _supersede_claims(expanded: dict, supplied: dict, returned: set) -> None:
    """Keep the answer's word on what is claimed about the records it returns.

    A claim the answer makes about a record replaces the children's claims of
    the same kind about it, and a record the answer returns rests on the
    claims it lists: a child claim about it the answer left out is dropped.
    """
    restated = {(claim['subject_id'], claim['kind']) for claim_id, claim in expanded['claims'].items()
                if claim_id in returned and claim_id not in supplied['claims']}
    listed = {record_id: set(item['claim_ids'])
              for collection in SEMANTIC_COLLECTIONS if collection != 'claims'
              for record_id, item in expanded[collection].items()
              if record_id in returned and item.get('claim_ids')}
    for claim_id in sorted(expanded['claims']):
        claim = expanded['claims'][claim_id]
        if claim_id not in supplied['claims'] or claim_id in returned:
            continue
        subject = claim['subject_id']
        # A claim moved here from a replaced record was not the answer's to list.
        about_it = supplied['claims'][claim_id]['subject_id'] == subject
        if (subject, claim['kind']) in restated or (
                about_it and subject in listed and claim_id not in listed[subject]):
            del expanded['claims'][claim_id]


def _drop_orphan_rules(expanded: dict, supplied: dict, returned: set) -> None:
    """Remove carried child rules nothing in the candidate applies any more.

    A rule the answer merged into one it returned is still named by the child
    records that cited it; once no activity or domain does, it is gone.
    """
    applied = {rule_id for activity in expanded['activities'].values()
               for rule_id in activity.get('rule_ids', ())}
    applied |= {rule_id for domain in expanded['domains'].values()
                for rule_id in domain.get('rules', ())}
    for rule_id in sorted(set(expanded['rules'])):
        if rule_id in supplied['rules'] and rule_id not in returned and rule_id not in applied:
            del expanded['rules'][rule_id]


def _link_claims(expanded: dict) -> None:
    """List every claim about a record in that record's `claim_ids`.

    A domain membership the answer gave no claim rests on the claims about
    its activity.
    """
    about = {}
    for claim_id in sorted(expanded['claims']):
        about.setdefault(expanded['claims'][claim_id]['subject_id'], []).append(claim_id)
    for collection in SEMANTIC_COLLECTIONS:
        for record_id, item in expanded[collection].items():
            if 'claim_ids' in item and record_id in about:
                item['claim_ids'] = list(dict.fromkeys([*item['claim_ids'], *about[record_id]]))
    for domain in expanded['domains'].values():
        for membership in domain.get('activity_memberships', ()):
            if not membership['claim_ids']:
                membership['claim_ids'] = list(about.get(membership['activity_id'], ()))


def verification_view(scope: dict, complete: dict) -> dict:
    """The reconciliation scope as verification of `complete` receives it.

    The complete candidate already holds every child record it keeps, so the
    scope keeps only the child records the candidate replaced, merged or
    retired, against which verification checks the change, and SPEED's own
    claims. Verification then costs no more than the scope it reviews.
    """
    view = copy.deepcopy(scope)
    context = view['context']
    held = {record_id for collection in SEMANTIC_COLLECTIONS
            for record_id in complete[collection]}
    omitted = {}
    for collection in SEMANTIC_COLLECTIONS:
        records = context[collection]
        context[collection] = {
            record_id: item for record_id, item in records.items()
            if record_id not in held or item.get('kind') in SPEED_CLAIM_KINDS}
        omitted.update((record_id, (collection, item)) for record_id, item in records.items()
                       if record_id not in context[collection])
    # What the scope still cites, in its records or its coverage manifests,
    # stays identifiable, as any record a scope omits does.
    cited = {key: value for key, value in view.items() if key != 'context'}
    cited['context'] = {key: value for key, value in context.items() if key != 'record_refs'}
    for record_id in sorted(_referenced_ids(cited, set(omitted))):
        collection, item = omitted[record_id]
        context['record_refs'][record_id] = {'id': record_id, 'collection': collection,
                                             'content_hash': digest(item)}
    return view


def _referenced_ids(value, known: set) -> set:
    found = set()

    def walk(item):
        if isinstance(item, str):
            if item in known:
                found.add(item)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, dict):
            for child in item.values():
                walk(child)

    walk(value)
    return found


def _carry(expanded: dict, supplied: dict, pending: set, merged: set) -> None:
    """Copy `pending` supplied records, and what they rest on, into `expanded`.

    Groupings are `_regroup`'s; SPEED's own claims and records about merged
    activities are never copied.
    """
    present = {record_id for collection in SEMANTIC_COLLECTIONS
               for record_id in expanded[collection]}
    pending = set(pending)
    while pending:
        record_id = pending.pop()
        if record_id in present or record_id in merged:
            continue
        collection = next((name for name in SEMANTIC_COLLECTIONS
                           if record_id in supplied[name]), None)
        if collection is None or collection in GROUPING_COLLECTIONS:
            continue
        item = copy.deepcopy(supplied[collection][record_id])
        if (item.get('kind') in SPEED_CLAIM_KINDS
                or {item.get('activity_id'), item.get('subject_id')} & merged):
            continue
        expanded[collection][record_id] = item
        present.add(record_id)
        pending |= _referenced({collection: {record_id: item}}, supplied) - present
        pending |= {dependent_id for name in ('information_uses', 'claims')
                    for dependent_id, dependent in supplied[name].items()
                    if dependent_id not in present
                    and record_id in (dependent.get('activity_id'), dependent.get('subject_id'))}


def _regroup(expanded: dict, supplied: dict, merged: set) -> None:
    """Settle the children's domains, ownerships and relationships.

    A returned domain claims its member activities. A child domain keeps the
    activities no returned domain claims, and is retired when none remain;
    each of its ownerships moves to the domain now holding the activities it
    rests on. Two ownerships of one concept in one domain combine. Relationships follow their activities: each end's domain
    is its activity's primary domain, and links to activities that no longer
    exist, or within one activity, are dropped.
    """
    activities = expanded['activities']
    holder = {}
    for activity_id in sorted(activities):
        for anchor_id in activities[activity_id]['anchor_ids']:
            holder.setdefault(anchor_id, activity_id)

    def current(activity_id):
        if activity_id in activities:
            return activity_id
        if activity_id in merged:
            return next((holder[anchor_id] for anchor_id
                         in supplied['activities'][activity_id]['anchor_ids']
                         if anchor_id in holder), None)
        return None

    domains = expanded['domains']
    returned = set(domains)
    # A returned domain may name a child activity the answer merged away; it
    # means the activity that replaced it.
    for domain in domains.values():
        members = {}
        for membership in domain['activity_memberships']:
            activity_id = current(membership['activity_id']) or membership['activity_id']
            if activity_id not in members:
                members[activity_id] = {**membership, 'activity_id': activity_id}
            elif membership['role'] == 'primary':
                members[activity_id]['role'] = 'primary'
        domain['activity_memberships'] = list(members.values())
    claimed = {membership['activity_id'] for domain in domains.values()
               for membership in domain['activity_memberships']}
    primary = {membership['activity_id'] for domain in domains.values()
               for membership in domain['activity_memberships']
               if membership['role'] == 'primary'}
    retiring = []
    for domain_id in sorted(set(supplied['domains']) - returned):
        domain = copy.deepcopy(supplied['domains'][domain_id])
        members = {}
        for membership in domain['activity_memberships']:
            activity_id = current(membership['activity_id'])
            if activity_id is None or activity_id in claimed or activity_id in members:
                continue
            role = membership['role']
            if role == 'primary' and activity_id in primary:
                role = 'supporting'
            primary |= {activity_id} if role == 'primary' else set()
            members[activity_id] = {**membership, 'activity_id': activity_id, 'role': role}
        if members:
            domain['activity_memberships'] = list(members.values())
            domains[domain_id] = domain
        else:
            retiring.append(domain_id)

    home = {}
    for domain_id in sorted(domains):
        for membership in domains[domain_id]['activity_memberships']:
            if membership['role'] == 'primary':
                home.setdefault(membership['activity_id'], domain_id)
    for domain_id in sorted(domains):
        for membership in domains[domain_id]['activity_memberships']:
            home.setdefault(membership['activity_id'], domain_id)
    successor = {}
    for domain_id in retiring:
        targets = [home[activity_id] for membership
                   in supplied['domains'][domain_id]['activity_memberships']
                   if (activity_id := current(membership['activity_id'])) in home]
        successor[domain_id] = min(targets, key=lambda target: (-targets.count(target), target),
                                   default=None)

    ownerships = {}
    for ownership_id in sorted(expanded['ownerships']) + sorted(
            set(supplied['ownerships']) - set(expanded['ownerships'])):
        item = copy.deepcopy(expanded['ownerships'].get(ownership_id)
                             or supplied['ownerships'][ownership_id])
        origin = item['domain_id']
        if (ownership_id not in expanded['ownerships'] and origin in returned
                and ownership_id not in domains[origin]['ownership_ids']):
            continue
        item['activity_ids'] = list(dict.fromkeys(
            activity_id for activity_id in map(current, item['activity_ids']) if activity_id))
        if origin in domains or not origin:
            item['domain_id'] = origin
        else:
            # A retired domain's activities may now sit in several domains;
            # its ownership goes where the activities it rests on went.
            homes = [home[activity_id] for activity_id in item['activity_ids']
                     if activity_id in home]
            item['domain_id'] = min(homes, key=lambda target: (-homes.count(target), target),
                                    default=successor.get(origin))
        if item['domain_id'] is None:
            continue
        ownerships[ownership_id] = item
    combined = {}
    for _, group in sorted(_by_owner(ownerships).items()):
        if len(group) < 2:
            continue
        stated = [ownership_id for ownership_id in group if ownership_id in expanded['ownerships']]
        group.sort(key=lambda ownership_id: (
            ownership_id not in stated,
            OWNERSHIP_STRENGTH.index(ownerships[ownership_id]['kind']), ownership_id))
        if stated:
            # The answer's ownership of a concept in a domain replaces the
            # children's there; it is not widened with what they listed.
            for ownership_id in group:
                if ownership_id not in stated:
                    ownerships.pop(ownership_id)
                    combined[ownership_id] = group[0]
            group = [ownership_id for ownership_id in group if ownership_id in stated]
        kept = ownerships[group[0]]
        for ownership_id in group[1:]:
            combined[ownership_id] = group[0]
            other = ownerships.pop(ownership_id)
            for field in ('activity_ids', 'information_use_ids', 'claim_ids',
                          'evidence_ids', 'unresolved_questions'):
                kept[field] = list(dict.fromkeys([*kept[field], *other[field]]))
    expanded['ownerships'] = ownerships
    if combined:
        # What named a combined ownership names the one it became.
        for collection in SEMANTIC_COLLECTIONS:
            if collection != 'ownerships':
                for record_id, item in expanded[collection].items():
                    expanded[collection][record_id] = _renamed(item, combined)
    for domain_id, domain in domains.items():
        domain['ownership_ids'] = sorted(ownership_id for ownership_id, item in ownerships.items()
                                         if item['domain_id'] == domain_id)

    relationships, seen = {}, set()
    for relationship_id in sorted(expanded['relationships']) + sorted(
            set(supplied['relationships']) - set(expanded['relationships'])):
        item = copy.deepcopy(expanded['relationships'].get(relationship_id)
                             or supplied['relationships'][relationship_id])
        source, target = current(item['from_activity_id']), current(item['to_activity_id'])
        key = (source, target, item['kind'])
        if source is None or target is None or source == target or key in seen:
            continue
        if source not in home or target not in home:
            continue
        seen.add(key)
        item.update(from_activity_id=source, to_activity_id=target,
                    from_domain_id=home[source], to_domain_id=home[target])
        relationships[relationship_id] = item
    expanded['relationships'] = relationships


def _by_owner(ownerships: dict) -> dict:
    groups = {}
    for ownership_id, item in ownerships.items():
        groups.setdefault((item['domain_id'], item['concept_id']), []).append(ownership_id)
    return groups


def _drop_replaced_references(expanded: dict, supplied: dict, returned: set = frozenset()) -> None:
    """Remove what the candidate still says about child records it replaced.

    A child record the candidate does not hold was merged away, retired or
    dropped. Records that depend on one, such as an information use of a
    merged activity or a claim about a retired domain, go with it, and lists
    that name one lose that entry, until nothing refers to a replaced record.
    """
    # Records the answer returned that the bookkeeping since removed are gone
    # as well as replaced child records.
    supplied_ids = {record_id for name in SEMANTIC_COLLECTIONS for record_id in supplied[name]}
    supplied_ids |= set(returned)
    dependent_fields = {'information_uses': ('activity_id', 'concept_id'),
                        'claims': ('subject_id',), 'ownerships': ('concept_id',)}
    while True:
        present = {record_id for name in SEMANTIC_COLLECTIONS for record_id in expanded[name]}
        replaced = supplied_ids - present
        orphans = {(name, record_id) for name, fields in dependent_fields.items()
                   for record_id, item in expanded[name].items()
                   if any(item.get(field) in replaced for field in fields)}
        if not orphans:
            break
        for name, record_id in orphans:
            del expanded[name][record_id]
    for name in SEMANTIC_COLLECTIONS:
        for record_id, item in expanded[name].items():
            expanded[name][record_id] = _without(item, replaced)


def _without(value, replaced: set):
    """`value` with every ID in `replaced` removed from its lists of IDs."""
    if isinstance(value, list):
        return [_without(item, replaced) for item in value
                if not (isinstance(item, str) and item in replaced)]
    if isinstance(value, dict):
        return {key: _without(item, replaced) for key, item in value.items()}
    return value


def _referenced(payload: dict, supplied: dict) -> set:
    """Supplied semantic records the records of `payload` name."""
    known = {record_id for name in SEMANTIC_COLLECTIONS for record_id in supplied[name]}
    return _referenced_ids([payload.get(name, {}) for name in SEMANTIC_COLLECTIONS], known)


def _home_domains(payload: dict) -> dict:
    """Each activity's primary domain, else the first domain holding it."""
    home = {}
    for role in ('primary', 'supporting'):
        for domain_id in sorted(payload['domains']):
            for membership in payload['domains'][domain_id]['activity_memberships']:
                if membership['role'] == role:
                    home.setdefault(membership['activity_id'], domain_id)
    return home


def reconciliation_findings(model: dict, units, payload: dict) -> list[dict]:
    """Repairable findings on a complete reconciliation candidate.

    Reconciliation may merge or regroup activities, never drop an anchor a
    unit represented, and a child reported as represented must name records
    it contributed. Where units connect in ways no unit could see, the
    candidate must account for it: information one unit reads that only
    another writes needs a relationship or a shared domain, and domains that
    one boundary may cover need merging or a recorded decision to keep them
    apart.
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
    # A child contributed a concept merged into another under that one's ID.
    aliases = _merge_concepts(model, {
        collection: ({record_id: copy.deepcopy(item) for unit in units
                      for record_id, item in unit.payload[collection].items()}
                     if collection in ('concepts', 'information_uses') else {})
        for collection in SEMANTIC_COLLECTIONS})
    contributed = {unit.scope['scope_id']: {aliases.get(record_id, record_id)
                                            for collection in SEMANTIC_COLLECTIONS
                                            for record_id in unit.payload[collection]}
                   for unit in units}
    for disposition in payload['dispositions']:
        if disposition['subject_kind'] == 'child_scope' and disposition['status'] == 'represented':
            unknown = {record_id for record_id in disposition['incorporated_record_ids']
                       if aliases.get(record_id, record_id) not in contributed.get(
                           disposition['subject_id'], set())}
            if unknown:
                findings.append({
                    'code': 'INVALID_COVERAGE', 'severity': 'error',
                    'message': 'A represented child names records it did not contribute',
                    'subject_ids': sorted({disposition['subject_id'], *unknown}),
                    'evidence_ids': []})
    return (findings + _link_findings(payload, units) + _merge_findings(model, units, payload)
            + _rule_findings(payload, units)
            + _mixed_observation_findings(payload, units))


def _rule_findings(payload: dict, units) -> list[dict]:
    """Rules of different units describing the same rule are one rule."""
    unit_of = {rule_id: unit.scope['scope_id'] for unit in units
               for rule_id in unit.payload['rules']}
    groups = []
    for rule_id in sorted(payload['rules']):
        rule = payload['rules'][rule_id]
        if _rule_basis(rule) is None:
            continue
        group = next((group for group in groups
                      if _same_rule(rule, payload['rules'][group[0]])), None)
        if group is None:
            groups.append([rule_id])
        else:
            group.append(rule_id)
    return [{'code': 'DUPLICATE_RULE', 'severity': 'error',
             'message': ('Rules from different child scopes describe the same rule, over the '
                         'same observations or enforced at the same sites; return one rule, '
                         'which replaces them'),
             'subject_ids': sorted(group), 'evidence_ids': []}
            for group in groups
            if len({unit_of.get(rule_id) for rule_id in group}) > 1]


def _mixed_observation_findings(payload: dict, units) -> list[dict]:
    """A returned rule that cites most of one child rule's observations and
    some of another's instead of the rest.

    A returned rule replaces each child rule whose observations it cites, so
    one observation cited in place of another replaces the wrong rule and
    leaves the right one standing. The finding names both observations, which
    the symptoms the reviewer sees do not.
    """
    children = {rule_id: rule for unit in units for rule_id, rule in unit.payload['rules'].items()}
    cited_by = {}
    for rule_id, rule in children.items():
        for observation_id in rule.get('observation_ids') or ():
            cited_by.setdefault(observation_id, []).append(rule_id)
    findings = []
    for rule_id in sorted(set(payload['rules']) - set(children)):
        observed = set(payload['rules'][rule_id].get('observation_ids') or ())
        if not observed:
            continue
        best = max(sorted(children), default=None, key=lambda child: len(
            observed & set(children[child].get('observation_ids') or ())))
        if best is None:
            continue
        expected = set(children[best].get('observation_ids') or ())
        missing, extra = sorted(expected - observed), sorted(observed - expected)
        if not (expected & observed) or not missing:
            continue
        borrowed = sorted({other for observation_id in extra
                           for other in cited_by.get(observation_id, ()) if other != best})
        if not borrowed:
            continue
        names = '; '.join(f"'{children[other].get('name')}' ({other})" for other in borrowed)
        findings.append({
            'code': 'MIXED_RULE_OBSERVATIONS', 'severity': 'error',
            'message': (f"Rule {rule_id} cites {len(expected & observed)} of the "
                        f"{len(expected)} observations of child rule '{children[best].get('name')}' "
                        f"({best}) but not {', '.join(missing)}, and cites {', '.join(extra)}, "
                        f"which child rule {names} cites. A returned rule replaces every child "
                        'rule whose observations it cites, so it would replace that rule and '
                        'leave the one it describes standing; cite exactly the observations of '
                        'the rule it describes.'),
            'subject_ids': sorted({rule_id, best, *borrowed, *missing, *extra}),
            'evidence_ids': []})
    return findings


def _link_findings(payload: dict, units) -> list[dict]:
    home = _home_domains(payload)
    linked = {frozenset((item['from_activity_id'], item['to_activity_id']))
              for item in payload['relationships'].values()}
    findings = []
    for reader, resource_id, writers in cross_scope_reads(
            payload['activities'], payload['information_uses'],
            _children_of(units, payload['activities'])):
        if any(frozenset((reader, writer)) in linked
               or (home.get(reader) is not None and home.get(reader) == home.get(writer))
               for writer in writers):
            continue
        findings.append({
            'code': 'MISSING_RELATIONSHIP', 'severity': 'error',
            'message': ('An activity reads information that only other child scopes write; '
                        'link it to a writer with a uses_information_from relationship, '
                        'or place them in one domain'),
            'subject_ids': sorted({reader, resource_id, *writers}), 'evidence_ids': []})
    return findings


def _merge_findings(model: dict, units, payload: dict) -> list[dict]:
    activities = {activity_id: activity for unit in units
                  for activity_id, activity in unit.payload['activities'].items()}
    domains = {domain_id: domain for unit in units
               for domain_id, domain in unit.payload['domains'].items()}
    holder = {}
    for activity_id in sorted(payload['activities']):
        for anchor_id in payload['activities'][activity_id]['anchor_ids']:
            holder.setdefault(anchor_id, activity_id)
    home = _home_domains(payload)

    def settled(domain_id):
        """The candidate domains now holding a child domain's activities."""
        return {home[holder[anchor_id]]
                for membership in domains[domain_id]['activity_memberships']
                if membership['activity_id'] in activities
                for anchor_id in activities[membership['activity_id']]['anchor_ids']
                if anchor_id in holder and holder[anchor_id] in home}

    def decided(sides):
        """Whether a domain on one side records a boundary decision naming the other."""
        for side, other in (sides, sides[::-1]):
            for domain_id in side:
                domain = payload['domains'].get(domain_id)
                if domain and any(set(item['subject_ids']) & other
                                  for item in domain['alternatives'] + domain['exclusions']):
                    return True
        return False

    findings = []
    for one, other, _ in merge_candidates(model, domains, activities,
                                          _children_of(units, activities)):
        now = settled(one), settled(other)
        if now[0] & now[1] or decided(({one, *now[0]}, {other, *now[1]})):
            continue
        findings.append({
            'code': 'UNDECIDED_MERGE', 'severity': 'error',
            'message': ('Domains of different child scopes that one boundary may cover are '
                        'still separate with no recorded decision; merge them, or record '
                        'an alternative naming the other domain with the evidence for '
                        'keeping them apart'),
            'subject_ids': sorted({one, other, *now[0], *now[1]}), 'evidence_ids': []})
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
