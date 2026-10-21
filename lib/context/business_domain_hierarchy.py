"""Hierarchical domain synthesis for graphs too large for one request.

Slices the graph, synthesizes each slice, then reconciles the results up to a
single root. Responses are cached, so an interrupted run can resume.
"""
from __future__ import annotations

import json
import math
import threading
from collections import Counter
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait

from .business_domain_schema import DomainError, digest, identifier
from .business_domain_synthesis import OPERATIONS, POLICY, _model_ready_context, wire_schema
from .business_domain_schema import read_json
from .business_domain_work import (
    ROOT_SCOPE_ID, _affinity_pack, _edge_users, anchor_scope_id, expand_reconciliation,
    plan_reconciliation, plan_slices, reconciled_unit, reconciliation_findings,
    reconciliation_scope, slice_scope, slice_unit, verification_view,
)

SPLIT_HINTS = '.speed/context/business-domain-split-hints.json'


def _split_hints(synthesis) -> set:
    """Return scope ids of bundles an earlier run had to split."""
    try:
        return set(json.loads((synthesis.root / SPLIT_HINTS).read_text()))
    except (OSError, ValueError):
        return set()


def _remember_split(synthesis, scope_id: str) -> None:
    hints = _split_hints(synthesis) | {scope_id}
    path = synthesis.root / SPLIT_HINTS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(hints)))


def split_bundle(baseline: dict, synthesis, scope: dict) -> list[dict]:
    """Split a bundle into two, grouping entry points by shared code."""
    users = _edge_users(baseline)
    owned = {}
    for edge_id, anchors in users.items():
        for anchor_id in anchors:
            owned.setdefault(anchor_id, set()).add(edge_id)

    def build(anchor_ids):
        members = set(anchor_ids)
        edges = set().union(*(owned.get(anchor_id, set()) for anchor_id in anchor_ids))
        selected = _model_ready_context(baseline, anchor_ids)
        return synthesis._size_graph(slice_scope(
            baseline, anchor_ids, selected, 'entrypoint_bundle',
            cross_scope_edge_ids=sorted(e for e in edges if users[e] - members)))

    anchors = scope['canonical_anchor_ids']
    half = math.ceil(len(anchors) / 2)
    return [built for _, built in _affinity_pack(
        anchors, build, lambda built: len(built['canonical_anchor_ids']) <= half,
        lambda anchor_id: owned.get(anchor_id, set()))]


def plan(baseline: dict, synthesis) -> list[dict]:
    """Return sized slices covering every canonical anchor."""
    def bundle(anchor_ids, cross_scope_edge_ids, strategy):
        selected = _model_ready_context(baseline, anchor_ids)
        return synthesis._size_graph(slice_scope(
            baseline, anchor_ids, selected, strategy,
            cross_scope_edge_ids=cross_scope_edge_ids))

    def segment(view, anchor_id, cut_edge_ids):
        selected = _model_ready_context(view, [anchor_id])
        return synthesis._size_graph(slice_scope(
            view, [anchor_id], selected, 'execution_segment',
            cross_scope_edge_ids=cut_edge_ids, parent_scope_id=anchor_scope_id(anchor_id)))

    slices = plan_slices(baseline, bundle, segment, synthesis.sequence_fits,
                         synthesis.sequence_limit)
    hints = _split_hints(synthesis)
    planned = []
    while slices:
        scope = slices.pop(0)
        if scope['scope_id'] in hints and len(scope['canonical_anchor_ids']) > 1:
            slices[:0] = split_bundle(baseline, synthesis, scope)
        else:
            planned.append(scope)
    return planned


def reserve(slices: list[dict], synthesis) -> None:
    """Raise BUILD_BUDGET if the slices and root won't fit the token budget.

    Each request is charged at its full output allowance, and the root at the
    largest input one request allows, since its real size isn't known yet.
    """
    output = synthesis.effective_request_output_tokens
    root = synthesis.effective_request_input_tokens - 2 * output
    sizes = [scope['estimated_input_tokens'] for scope in slices]
    needed = {'input': sum(2 * size + output for size in sizes) + 4 * root + 4 * output,
              'output': 2 * output * len(sizes) + 4 * output}
    for kind, amount in needed.items():
        setting = f'max_build_{kind}_tokens'
        if amount > synthesis.config[setting]:
            raise DomainError('BUILD_BUDGET', (
                f'Hierarchical discovery needs {amount:,} {kind} tokens for '
                f'{len(slices)} slices and their root reconciliation, more than '
                f'{setting} = {synthesis.config[setting]:,}; nothing was dispatched. '
                f'Raise {setting} under [business_domains] in the project speed.toml '
                'and run again.'))


FINAL_REQUEST_CEILING = 800000


class _Run:
    """State for one hierarchical run."""

    def __init__(self, baseline, synthesis, accept, status, heartbeat, recorder):
        self.baseline = baseline
        self.synthesis = synthesis
        self.accept = accept
        self.status = status
        self.heartbeat = heartbeat
        self.recorder = recorder
        self.lock = threading.Lock()

    def progress(self, message, level='step'):
        if self.recorder:
            self.recorder.progress('semantic', message, level=level)

    def beat(self, scope_id=None):
        with self.lock:
            self.status['current_scope_id'] = scope_id
            self.heartbeat()

    def add_units(self, count):
        with self.lock:
            limits = self.status['limits']
            limits['semantic_units_total'] += count
            limits['semantic_units_pending'] = (limits['semantic_units_total']
                                                - limits['semantic_units_validated'])

    def dispatch(self, jobs, label, runner=None):
        """Run (scope, validate, review) jobs concurrently and return results in order.

        After the first failure, pending jobs are cancelled and running ones
        finish (so their responses get cached) before the error is raised.
        """
        results = {}

        def one(index, scope, validate, review):
            self.progress(f'{label} {index + 1}/{len(jobs)} started')
            self.beat(scope['scope_id'])
            payload = (runner or self.synthesis.run)(scope, validate, review=review)
            with self.lock:
                results[index] = payload
                done = len(results)
            self.progress(f'{label} {index + 1}/{len(jobs)} validated '
                          f'({done}/{len(jobs)} done)', level='success')
            self.beat()
            return payload

        workers = max(1, min(self.synthesis.config['provider_concurrency'], len(jobs)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='domain-scope') as pool:
            futures = [pool.submit(one, index, *job) for index, job in enumerate(jobs)]
            _, unfinished = wait(futures, return_when=FIRST_EXCEPTION)
            failed = [future for future in futures
                      if future.done() and not future.cancelled() and future.exception()]
            if failed:
                for future in unfinished:
                    future.cancel()
                wait(futures)
                raise failed[0].exception()
        return [results[index] for index in range(len(jobs))]

    def run_slice(self, scope, validate, review=None):
        """Run a slice and return its (scope, payload) pairs.

        A bundle that hits PROVIDER_BUDGET is split in two and recorded so the
        next run plans the split up front.
        """
        try:
            return [(scope, self.synthesis.run(scope, validate, review=review))]
        except DomainError as exc:
            if (exc.code != 'PROVIDER_BUDGET' or scope['partition_strategy'] != 'entrypoint_bundle'
                    or len(scope['canonical_anchor_ids']) < 2):
                raise
        _remember_split(self.synthesis, scope['scope_id'])
        halves = split_bundle(self.baseline, self.synthesis, scope)
        self.add_units(len(halves) - 1)
        self.progress(f'A slice of {len(scope["canonical_anchor_ids"])} entry points needed a '
                      f'longer answer than one response allows; split into {len(halves)}',
                      level='warning')
        results = []
        for half in halves:
            results += self.run_slice(*self.slice_job(half))
        return results

    def slice_job(self, scope):
        return scope, lambda candidate: self.accept(scope, candidate), None

    def reconciliation_job(self, scope, children):
        """Build a reconciliation job that validates the expanded candidate."""
        def review(graph, candidate):
            complete = expand_reconciliation(graph, candidate, self.baseline)
            return verification_view(graph, complete), complete

        def validate(candidate):
            complete = expand_reconciliation(scope, candidate, self.baseline)
            self.accept(scope, complete)
            return reconciliation_findings(self.baseline, children, complete)
        return scope, validate, review

    def run_reconciliation(self, scope, validate, review=None):
        """Reuse a previously validated reconciliation if there is one."""
        reused = self.validated_reconciliation(scope, validate, review)
        if reused is not None:
            self.progress('Reconciliation reused a validated answer from an earlier run')
            return reused
        return self.synthesis.run(scope, validate, review=review)

    def validated_reconciliation(self, scope, validate, review):
        """Return a cached reconciliation answer for this scope, or None.

        The verifier saw the expanded candidate, so the cached answer is only
        reused if it expands to the same thing and still passes validation.
        """
        synthesis = self.synthesis
        try:
            request = synthesis.request_for('synthesize', scope)
            output_type, _ = OPERATIONS['synthesize']
            _, provider_schema, _ = synthesis.project_exchange(
                request, wire_schema(output_type, request['graph']))
            request_key, response_key, prompt_hash, schema_hash = \
                synthesis._cache_identity(request, provider_schema)
            directory = synthesis.root/'.speed/context/business-domain-cache'
            limit = synthesis.config['max_artifact_bytes']
            artifact = read_json(directory/(response_key+'.json'), limit)
            if not artifact or artifact.get('kind') != 'response' or any(
                    artifact.get(field) != value for field, value in (
                        ('request_key', request_key), ('prompt_hash', prompt_hash),
                        ('output_schema_hash', schema_hash),
                        ('provider_fingerprint', synthesis.provider_hash))):
                return None
            response = artifact['response']
            if (response.get('operation') != 'synthesize'
                    or response.get('input_fingerprint') != request['input_fingerprint']):
                return None
            linked = read_json(directory/(str(artifact.get('verification_response_key'))+'.json'), limit)
            if not linked or linked['response']['verification_report']['verdict'] != 'pass':
                return None
            judged = read_json(directory/(linked['request_key']+'.json'), limit)
            if not judged:
                return None
            candidate = response['candidate']
            view, complete = review(scope, candidate)
            if judged['request']['candidate'] != complete or judged['request']['graph'] != view:
                return None
            if any(finding['severity'] == 'error' for finding in validate(candidate)):
                return None
            return candidate
        except (DomainError, KeyError, TypeError, OSError):
            return None

    def sized_reconciliation(self, units, scope_id, parent_scope_id=None):
        return self.synthesis._size_graph(reconciliation_scope(
            self.baseline, units, scope_id=scope_id, parent_scope_id=parent_scope_id))

    def reconcile(self, groups, label):
        """Reconcile each (scope_id, parent_id, units) group into one unit."""
        scopes = [self.sized_reconciliation(units, scope_id, parent_id)
                  for scope_id, parent_id, units in groups]
        for scope in scopes:
            if not self.synthesis.sequence_fits(scope):
                raise DomainError(
                    'PACKET_LIMIT',
                    f'Reconciling {len(scope["child_scope_ids"])} validated units needs '
                    f'{scope["estimated_input_tokens"]:,} input tokens, more than one '
                    'request allows', scope['scope_id'])
        payloads = self.dispatch(
            [self.reconciliation_job(scope, units)
             for scope, (_, _, units) in zip(scopes, groups)], label,
            runner=self.run_reconciliation)
        return [reconciled_unit(scope, expand_reconciliation(scope, payload, self.baseline), units)
                for scope, payload, (_, _, units) in zip(scopes, payloads, groups)]

    def widen_for_root(self) -> bool:
        """Raise the input limit for the final root reconciliation.

        Returns False if the limit can't grow. Only used when no two units fit
        in one request at the normal limit.
        """
        synthesis = self.synthesis
        current = synthesis.effective_request_input_tokens
        # Repairs resend the scope, candidate and prior attempt, so leave room.
        widened = max(math.floor(current * POLICY['final_reconciliation_input_factor']),
                      min(FINAL_REQUEST_CEILING,
                          synthesis.provider_context_tokens or FINAL_REQUEST_CEILING))
        if synthesis.provider_context_tokens:
            widened = min(widened, synthesis.provider_context_tokens)
        if widened <= current:
            return False
        with synthesis.accounting_lock:
            synthesis.effective_request_input_tokens = widened
            synthesis.counters['effective_request_input_tokens'] = widened
        return True

    def to_root(self, units):
        """Reconcile units level by level until a single root remains."""
        level = 1
        while True:
            if len(units) == 1 and units[0].scope['scope_kind'] == 'reconciliation':
                return units[0]
            root = self.sized_reconciliation(units, ROOT_SCOPE_ID)
            if self.synthesis.sequence_fits(root):
                self.add_units(1)
                self.progress(f'Root reconciliation over {len(units)} units')
                [unit] = self.reconcile([(ROOT_SCOPE_ID, None, units)], 'Root')
                return unit
            groups = plan_reconciliation(
                units,
                lambda group: self.sized_reconciliation(group, _group_id(group), ROOT_SCOPE_ID),
                self.synthesis.sequence_fits)
            merged = [group for group in groups if len(group) > 1]
            if not merged and self.widen_for_root():
                root = self.sized_reconciliation(units, ROOT_SCOPE_ID)
                if self.synthesis.sequence_fits(root):
                    self.add_units(1)
                    self.progress(
                        f'Root reconciliation over {len(units)} units with the final '
                        f'request allowance of '
                        f'{self.synthesis.effective_request_input_tokens:,} input tokens')
                    [unit] = self.reconcile([(ROOT_SCOPE_ID, None, units)], 'Root')
                    return unit
            if not merged:
                raise DomainError(
                    'PACKET_LIMIT',
                    f'No two of {len(units)} validated units can be reconciled in one '
                    'request; raise max_request_input_tokens under [business_domains] '
                    'in the project speed.toml', ROOT_SCOPE_ID)
            self.add_units(len(merged))
            self.progress(f'Reconciliation level {level}: {len(units)} units into '
                          f'{len(groups)}')
            reconciled = iter(self.reconcile(
                [(_group_id(group), ROOT_SCOPE_ID, group) for group in merged],
                f'Level {level} group'))
            units = [next(reconciled) if len(group) > 1 else group[0] for group in groups]
            level += 1


def _describe(slices, segmented) -> str:
    counts = Counter(scope['partition_strategy'] for scope in slices)
    parts = [f'{counts[strategy]} {label}' for strategy, label in (
        ('application_boundary', 'application boundaries'),
        ('entrypoint_bundle', 'entry-point bundles'),
        ('execution_segment', f'execution segments of {len(segmented)} oversized entry points'),
    ) if counts[strategy]]
    return ', '.join(parts)


def _group_id(units) -> str:
    return identifier('scope', 'reconciliation',
                      digest(sorted(unit.scope['scope_id'] for unit in units)))


def run(baseline: dict, synthesis, accept, *, status, heartbeat, recorder=None):
    """Synthesize every slice and reconcile them to a root.

    accept(scope, candidate) should raise DomainError when a candidate is
    invalid. Returns (root scope, root payload, root unit).
    """
    slices = plan(baseline, synthesis)
    reserve(slices, synthesis)
    segmented = sorted({scope['parent_scope_id'] for scope in slices
                        if scope['partition_strategy'] == 'execution_segment'})
    status['execution_mode'] = 'hierarchical'
    status['root_reconciled'] = False
    status['limits'].update(semantic_units_total=0, semantic_units_validated=0,
                            semantic_units_pending=0)
    attempt = _Run(baseline, synthesis, accept, status, heartbeat, recorder)
    attempt.add_units(len(slices) + len(segmented))
    attempt.progress(f'Hierarchical mode: {_describe(slices, segmented)} '
                     '(the complete graph does not fit one request)')
    attempt.beat()

    results = attempt.dispatch([attempt.slice_job(scope) for scope in slices], 'Slice',
                               runner=attempt.run_slice)
    units = [slice_unit(scope, payload) for pairs in results for scope, payload in pairs]
    if segmented:
        segments = {parent: [unit for unit in units if unit.scope['parent_scope_id'] == parent
                             and unit.scope['partition_strategy'] == 'execution_segment']
                    for parent in segmented}
        anchors = iter(attempt.reconcile(
            [(parent, ROOT_SCOPE_ID, segments[parent]) for parent in segmented],
            'Segmented entry point'))
        reunited = {parent: next(anchors) for parent in segmented}
        units = [unit for unit in units if unit.scope['partition_strategy'] != 'execution_segment']
        units += [reunited[parent] for parent in segmented]
    root = attempt.to_root(units)
    attempt.progress('Root reconciliation validated', level='success')
    attempt.beat()
    return root.scope, root.payload, root
