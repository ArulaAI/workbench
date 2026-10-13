"""Deterministic hierarchical work scopes for business-domain activity synthesis."""
from __future__ import annotations

import copy
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
    records cite, one coverage manifest per unit, and what SPEED derives about
    how the units connect: information one unit reads that only another
    writes, and domains of different units that one boundary may cover. Child
    concepts naming the same code type arrive as one concept. Raw graph
    records stay identity-only references: each unit already validated them
    against their full content, and re-sending them would rebuild the graph
    that did not fit.
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
    aliases = _merge_concepts(model, context)
    for unit in units:
        _manifest(context, unit, aliases)
    _state_links(model, context, units)
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
    manifests = [_renamed(coverage_manifest(unit), aliases) for unit in units]
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


def _manifest(context: dict, unit: Unit, aliases: dict) -> None:
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
        evidence_ids=list(dict.fromkeys(evidence))[:MANIFEST_EVIDENCE],
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
    declared = {}
    for symbol in model.get('symbols', {}).values():
        name = symbol.get('qualified_name') or ''
        if '::' in name:
            declared.setdefault(name.rpartition('::')[2], set()).add(name)

    def resolve(name):
        if '::' in name:
            return name
        matches = declared.get(name, ())
        return next(iter(matches)) if len(matches) == 1 else None

    parent = {}

    def root(concept_id):
        while parent.get(concept_id, concept_id) != concept_id:
            concept_id = parent[concept_id]
        return concept_id

    first = {}
    for concept_id in sorted(context['concepts']):
        for name in context['concepts'][concept_id]['qualified_type_names']:
            key = resolve(name)
            if key is None:
                continue
            if key not in first:
                first[key] = concept_id
                continue
            one, other = sorted((root(first[key]), root(concept_id)))
            if one != other:
                parent[other] = one
    # A concept a unit named without its type is the concept of the same name
    # another unit keeps in the same store.
    stores = {}
    for use in context['information_uses'].values():
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
    """The class, or else the module, that declares an anchor's symbol."""
    anchor = model.get('anchors', {}).get(anchor_id) or {}
    symbol = model.get('symbols', {}).get(anchor.get('symbol_id')) or {}
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


def expand_reconciliation(scope: dict, payload: dict) -> dict:
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
    _supersede_rules(expanded, supplied)
    _rehome(expanded, supplied, merged)
    _drop_orphan_rules(expanded, supplied, returned)
    _drop_replaced_references(expanded, supplied)
    _keep_writers(expanded)
    _collect_domain_rules(expanded)
    _link_claims(expanded)
    return expanded


def _keep_writers(expanded: dict) -> None:
    """Keep in each authoritative ownership only the activities that write it.

    Creating or maintaining information takes a write of it; an activity
    whose uses of the concept only read it, and those uses, leave a creates,
    maintains or authoritative ownership. One left with no writer stays as it
    is, for review to judge.
    """
    writes = {}
    for use_id, use in expanded['information_uses'].items():
        if use['access'] in WRITE_ACCESS:
            writes.setdefault((use['activity_id'], use['concept_id']), set()).add(use_id)
    for ownership in expanded['ownerships'].values():
        if ownership['kind'] not in ('creates', 'maintains', 'authoritative_source'):
            continue
        writers = [activity_id for activity_id in ownership['activity_ids']
                   if (activity_id, ownership['concept_id']) in writes]
        if not writers or writers == ownership['activity_ids']:
            continue
        written = set().union(*(writes[(activity_id, ownership['concept_id'])]
                                for activity_id in writers))
        ownership['activity_ids'] = writers
        ownership['information_use_ids'] = [
            use_id for use_id in ownership['information_use_ids']
            if use_id in written or expanded['information_uses'].get(use_id, {}).get(
                'activity_id') in writers]


def _collect_domain_rules(expanded: dict) -> None:
    """A domain lists the rules its primary activities apply."""
    for domain in expanded['domains'].values():
        applied = [rule_id for membership in domain.get('activity_memberships', ())
                   if membership['role'] == 'primary'
                   for rule_id in expanded['activities'].get(
                       membership['activity_id'], {}).get('rule_ids', ())
                   if rule_id in expanded['rules']]
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
    return ('enforced', sites, rule.get('evaluation_kind')) if sites else None


def _supersede_rules(expanded: dict, supplied: dict) -> None:
    """Replace child rules with the returned rule describing the same rule.

    Children describe one rule independently; a rule the answer returns
    replaces every child rule with its basis, or citing only observations it
    cites, and what named a replaced rule names the returned one.
    """
    returned = {rule_id: rule for rule_id, rule in expanded['rules'].items()
                if rule_id not in supplied['rules'] and _rule_basis(rule)}
    replaced = {}
    for rule_id in sorted(supplied['rules']):
        rule = supplied['rules'][rule_id]
        basis, observed = _rule_basis(rule), set(rule.get('observation_ids') or ())
        if rule_id in returned or basis is None:
            continue
        successor = min((other for other, candidate in returned.items()
                         if _rule_basis(candidate) == basis
                         or (observed and observed <= set(candidate.get('observation_ids') or ()))),
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


def _rehome(expanded: dict, supplied: dict, merged: set) -> None:
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
    for use_id in sorted(supplied['information_uses']):
        use = supplied['information_uses'][use_id]
        if use['activity_id'] not in merged:
            continue
        target = target_of(use['activity_id'])
        if target is None or target in stated:
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
    for _, group in sorted(_by_owner(ownerships).items()):
        if len(group) < 2:
            continue
        group.sort(key=lambda ownership_id: (
            ownership_id not in expanded['ownerships'],
            OWNERSHIP_STRENGTH.index(ownerships[ownership_id]['kind']), ownership_id))
        kept = ownerships[group[0]]
        for ownership_id in group[1:]:
            other = ownerships.pop(ownership_id)
            for field in ('activity_ids', 'information_use_ids', 'claim_ids',
                          'evidence_ids', 'unresolved_questions'):
                kept[field] = list(dict.fromkeys([*kept[field], *other[field]]))
    expanded['ownerships'] = ownerships
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


def _drop_replaced_references(expanded: dict, supplied: dict) -> None:
    """Remove what the candidate still says about child records it replaced.

    A child record the candidate does not hold was merged away, retired or
    dropped. Records that depend on one, such as an information use of a
    merged activity or a claim about a retired domain, go with it, and lists
    that name one lose that entry, until nothing refers to a replaced record.
    """
    supplied_ids = {record_id for name in SEMANTIC_COLLECTIONS for record_id in supplied[name]}
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
                      for record_id, item in unit.payload['concepts'].items()}
                     if collection == 'concepts' else {})
        for collection in SEMANTIC_COLLECTIONS})
    contributed = {unit.scope['scope_id']: {aliases.get(record_id, record_id)
                                            for collection in SEMANTIC_COLLECTIONS
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
    return (findings + _link_findings(payload, units) + _merge_findings(model, units, payload)
            + _rule_findings(payload, units))


def _rule_findings(payload: dict, units) -> list[dict]:
    """Rules of different units describing the same rule are one rule."""
    unit_of = {rule_id: unit.scope['scope_id'] for unit in units
               for rule_id in unit.payload['rules']}
    groups = {}
    for rule_id, rule in payload['rules'].items():
        basis = _rule_basis(rule)
        if basis is not None:
            groups.setdefault(basis, []).append(rule_id)
    return [{'code': 'DUPLICATE_RULE', 'severity': 'error',
             'message': ('Rules from different child scopes describe the same rule, over the '
                         'same observations or enforced at the same sites; return one rule, '
                         'which replaces them'),
             'subject_ids': sorted(group), 'evidence_ids': []}
            for _, group in sorted(groups.items(), key=lambda item: sorted(item[1]))
            if len({unit_of.get(rule_id) for rule_id in group}) > 1]


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
