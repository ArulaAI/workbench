"""Small fixture repositories for hierarchical discovery tests.

Tests lower `max_request_input_tokens` instead of using large repos; `calibrate`
picks an allowance that forces the split a test needs.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFINITIONS, DomainError, copy_facts, record, required_scope_subjects, settings,
)
from lib.context.business_domain_synthesis import Synthesis, _model_ready_context
from lib.context.business_domain_work import slice_scope

from tests.business_domains.provider_fixture import PassingProvider, encode

SHARED = '''"""Helpers every order endpoint uses."""


def normalise(payload):
    """Trim the fields an order carries."""
    return {key: value for key, value in payload.items() if value is not None}


def audit(action, payload):
    """Record that an action ran."""
    return {"action": action, "fields": sorted(payload)}
'''


def _endpoint(index):
    return f'''

@app.post("/orders/{index}")
def place_order_{index}(payload):
    """Place order kind {index}."""
    clean = normalise(payload)
    audit("place_order_{index}", clean)
    return price_order_{index}(clean)


def price_order_{index}(order):
    """Price order kind {index}: quantity times the kind's unit price."""
    quantity = int(order.get("quantity", 1))
    return {{"kind": {index}, "total": quantity * {index + 3}}}
'''


def write_monolith(root: Path, entry_points: int = 8) -> Path:
    """One service whose entry points all call one shared helper module."""
    package = root / 'orders'
    package.mkdir(parents=True, exist_ok=True)
    (package / 'shared.py').write_text(SHARED)
    (package / 'routes.py').write_text(
        'from orders.shared import audit, normalise\n'
        + ''.join(_endpoint(index) for index in range(entry_points)))
    return root


def write_long_chain(root: Path, steps: int = 24) -> Path:
    """One entry point that calls `steps` settlement steps directly, so they share one trace."""
    body = ''.join(f'    state = step_{index}(state)\n' for index in range(steps))
    functions = ''.join(f'''

def step_{index}(state):
    """Settlement step {index}: apply its adjustment."""
    state["adjustment_{index}"] = state.get("amount", 0) * {index + 1}
    return state
''' for index in range(steps))
    (root / 'settlement.py').write_text(
        '@app.post("/settlements")\n'
        'def settle(payload):\n'
        '    """Settle a batch by running every settlement step."""\n'
        '    state = dict(payload)\n'
        + body + '    return state\n' + functions)
    return root


def write_monorepo(root: Path, services=('billing', 'catalog', 'shipping'),
                   entry_points: int = 3) -> Path:
    """Several services, each a deployable boundary with its own entry points."""
    for service in services:
        directory = root / 'services' / service
        package = directory / service
        package.mkdir(parents=True, exist_ok=True)
        (directory / 'pyproject.toml').write_text(
            f'[project]\nname = "{service}"\nversion = "1.0.0"\n')
        (package / 'shared.py').write_text(SHARED)
        (package / 'routes.py').write_text(
            f'from {service}.shared import audit, normalise\n'
            + ''.join(_endpoint(index) for index in range(entry_points)).replace(
                '/orders/', f'/{service}/'))
    return root


def force_split(allowance: int) -> dict:
    """Return config that caps every semantic request at `allowance` tokens."""
    return {'business_domains': {'max_request_input_tokens': allowance}}


@dataclass(frozen=True)
class Calibration:
    """Measured request sizes for one fixture.

    `whole` is the whole-graph scope size; `anchors` maps each canonical anchor
    to the size of its own scope.
    """
    whole: int
    anchors: dict
    output_allowance: int

    def allowance(self, size: int) -> int:
        return size + 2 * self.output_allowance

    def splitting_allowance(self) -> int:
        """Return an allowance that fits every single-anchor scope but not the whole graph."""
        largest = max(self.anchors.values())
        low, high = self.allowance(largest), self.allowance(self.whole) - 1
        if low > high:
            raise AssertionError(
                f'Fixture cannot split: largest anchor needs {low}, '
                f'whole graph needs {high + 1}')
        return (low + high) // 2


def calibrate(root: Path, provider=None) -> Calibration:
    """Measure request sizes for `root` the same way discovery does."""
    provider = provider or PassingProvider()
    facts, _ = Extractor(root, settings({})).extract()
    model = copy_facts(facts, 'calibration')
    counters = copy.deepcopy(facts['limits'])
    synthesis = Synthesis(root, settings({}), provider, counters)
    whole = synthesis.graph_scope(copy.deepcopy(model))['estimated_input_tokens']
    anchors = {}
    for anchor_id in sorted(model['anchors']):
        selected = _model_ready_context(model, [anchor_id])
        scope = synthesis._size_graph(
            slice_scope(model, [anchor_id], selected, 'entrypoint_bundle'))
        anchors[anchor_id] = scope['estimated_input_tokens']
    return Calibration(whole, anchors, synthesis.effective_request_output_tokens)


class ReconcilingProvider(PassingProvider):
    """Fake provider for hierarchical mode.

    Slices get one activity per canonical anchor in a single domain.
    Reconciliation merges activities that share an anchor and keeps the rest by ID.
    """

    def generate(self, request, schema, *rest):
        graph = request['graph']
        if request['operation'] != 'synthesize':
            return super().generate(request, schema, *rest)
        self.requests.append(copy.deepcopy(request))
        if self.fail:
            raise DomainError('PROVIDER_FAILED', 'Fixture provider unavailable',
                              retryable=True)
        allowed = set(request['allowed_evidence_ids'])
        if graph['scope_kind'] == 'reconciliation':
            payload = self._reconcile(graph, allowed)
        else:
            payload = self._synthesize(graph, allowed)
        return encode(payload, DEFINITIONS['CandidatePayload']), {
            'last': {'inputTokens': 10, 'outputTokens': 10}}

    @staticmethod
    def _claim(claim_id, subject_id, text, evidence_ids, trace_ids=()):
        return record('Claim', id=claim_id, subject_id=subject_id, text=text,
                      kind='behavior', evidence_ids=sorted(evidence_ids),
                      trace_ids=sorted(trace_ids), semantic_review='uncertain')

    def _domain(self, activities, claims, evidence_ids):
        claims['claim:domain'] = self._claim(
            'claim:domain', 'domain:orders', 'The activities change order state.',
            evidence_ids)
        return record('Domain', id='domain:orders', name='Order management',
            summary='Owns evidenced order behaviour.',
            boundary_rationale='Every supplied activity changes order state.',
            activity_memberships=[record('ActivityMembership', activity_id=activity_id,
                role='primary', claim_ids=['claim:domain'])
                for activity_id in sorted(activities)],
            evidence_ids=sorted(evidence_ids), claim_ids=['claim:domain'],
            support='partial')

    def _synthesize(self, graph, allowed):
        context = graph['context']
        activities, claims, dispositions = {}, {}, []
        for index, anchor_id in enumerate(sorted(graph['canonical_anchor_ids'])):
            anchor = context['anchors'][anchor_id]
            evidence = sorted(set(anchor['evidence_ids']) & allowed) or sorted(allowed)[:1]
            traces = sorted(trace_id for trace_id, trace in context['traces'].items()
                            if trace['anchor_id'] == anchor_id)
            activity_id, claim_id = f'activity:a{index}', f'claim:a{index}'
            claims[claim_id] = self._claim(claim_id, activity_id,
                                           f'Handles entry point {anchor_id}.', evidence, traces)
            activities[activity_id] = record('Activity', id=activity_id,
                name=f'Handle {anchor["operation"].get("name") or anchor_id}',
                description=f'Handles entry point {anchor_id}.',
                anchor_ids=[anchor_id], trace_ids=traces, evidence_ids=evidence,
                claim_ids=[claim_id], support='partial')
        evidence = sorted({eid for item in activities.values() for eid in item['evidence_ids']})
        domains = {'domain:orders': self._domain(activities, claims, evidence)}
        by_anchor = {item['anchor_ids'][0]: item_id for item_id, item in activities.items()}
        for index, (subject_id, kind) in enumerate(sorted(required_scope_subjects(graph).items())):
            if kind == 'anchor':
                values = {'status': 'represented', 'activity_ids': [by_anchor[subject_id]]}
            else:
                values = {'status': 'excluded', 'evidence_ids': evidence[:1],
                          'reason': 'The unresolved correspondence adds no separate behaviour.'}
            dispositions.append(record('ScopeDisposition', id=f'disposition:d{index}',
                                       subject_kind=kind, subject_id=subject_id, **values))
        return record('CandidatePayload', scope_id=graph['scope_id'],
                      input_fingerprint=graph['input_fingerprint'], activities=activities,
                      domains=domains, claims=claims, dispositions=dispositions)

    def _merge_by_anchor(self, context):
        """Return kept activity IDs plus one merged activity per anchor with several."""
        groups = {}
        for activity_id, activity in sorted(context['activities'].items()):
            groups.setdefault(tuple(activity['anchor_ids']), []).append(activity)
        kept, merged, claims = [], {}, {}
        for index, (anchor_ids, members) in enumerate(sorted(groups.items())):
            if len(members) == 1:
                kept.append(members[0]['id'])
                continue
            activity_id, claim_id = f'activity:merged{index}', f'claim:merged{index}'
            traces = sorted({trace for member in members for trace in member['trace_ids']})
            evidence = sorted({eid for member in members for eid in member['evidence_ids']})
            claims[claim_id] = self._claim(claim_id, activity_id,
                                           f'Handles entry point {anchor_ids[0]}.', evidence, traces)
            merged[activity_id] = record('Activity', id=activity_id, name=members[0]['name'],
                description=f'Handles entry point {anchor_ids[0]}.', anchor_ids=list(anchor_ids),
                trace_ids=traces, evidence_ids=evidence, claim_ids=[claim_id], support='partial')
        return kept, merged, claims

    def _reconcile(self, graph, _allowed):
        """Return merged activities and the domain; other activities are kept by ID."""
        context = graph['context']
        kept, activities, claims = self._merge_by_anchor(context)
        grouped = {activity_id: True for activity_id in kept}
        grouped.update(activities)
        evidence = sorted({eid for activity_id in kept
                           for eid in context['activities'][activity_id]['evidence_ids']}
                          | {eid for item in activities.values() for eid in item['evidence_ids']})
        domains = {'domain:orders': self._domain(grouped, claims, evidence)}
        manifests = {item['child_scope_id']: item for item in graph['coverage_manifests']}
        dispositions = []
        for index, child_id in enumerate(sorted(graph['child_scope_ids'])):
            contributed = set(manifests[child_id]['contributed_record_ids'])
            dispositions.append(record('ScopeDisposition', id=f'disposition:c{index}',
                subject_kind='child_scope', subject_id=child_id, status='represented',
                incorporated_record_ids=sorted(contributed & set(kept))
                or sorted(contributed & set(context['activities']))))
        return record('CandidatePayload', scope_id=graph['scope_id'],
                      input_fingerprint=graph['input_fingerprint'], activities=activities,
                      domains=domains, claims=claims, dispositions=dispositions)


class InterruptingProvider(ReconcilingProvider):
    """Pass every request until `allowed` synthesis requests have succeeded."""

    def __init__(self, allowed: int):
        super().__init__()
        self.allowed = allowed
        self.synthesized = 0

    def generate(self, request, schema, *rest):
        if request['operation'] == 'synthesize':
            if self.synthesized >= self.allowed:
                raise DomainError('PROVIDER_FAILED', 'Fixture provider interrupted',
                                  retryable=False)
            self.synthesized += 1
        return super().generate(request, schema, *rest)


class RepairingProvider(ReconcilingProvider):
    """Fail the first `rejections` verifications and reword the named records on repair.

    The first `interruptions` repair requests raise.
    """

    def __init__(self, rejections: int = 1, interruptions: int = 0):
        super().__init__()
        self.rejections = rejections
        self.interruptions = interruptions

    def generate(self, request, schema, *rest):
        operation = request['operation']
        if operation == 'verify' and self.rejections:
            self.rejections -= 1
            self.requests.append(copy.deepcopy(request))
            graph = request['graph']
            subject = sorted(record_id for collection in ('activities', 'domains')
                             for record_id in request['candidate'][collection])[0]
            report = record(
                'VerificationReport', scope_id=graph['scope_id'],
                input_fingerprint=graph['input_fingerprint'], verdict='fail',
                findings=[record('VerificationFinding', id='verification_finding:fixture',
                                 category='unsupported_claim', severity='blocking',
                                 message='The fixture rejects the first verification.',
                                 subject_ids=[subject])],
                checked_subject_ids=sorted(required_scope_subjects(graph)))
            return encode(report, DEFINITIONS['VerificationReport']), {
                'last': {'inputTokens': 10, 'outputTokens': 10}}
        if operation == 'repair':
            self.requests.append(copy.deepcopy(request))
            if self.interruptions:
                self.interruptions -= 1
                raise DomainError('PROVIDER_FAILED', 'Fixture provider interrupted',
                                  retryable=False)
            candidate = copy.deepcopy(request['candidate'])
            named = {subject for finding in request['verification_report']['findings']
                     for subject in finding['subject_ids']}
            for collection, field in (('activities', 'description'), ('domains', 'summary')):
                for record_id, item in candidate[collection].items():
                    if record_id in named:
                        item[field] += ' Restated after review.'
            payload = record('RepairPayload',
                             parent_candidate_hash=request['parent_candidate_hash'],
                             candidate=candidate)
            return encode(payload, DEFINITIONS['RepairPayload']), {
                'last': {'inputTokens': 10, 'outputTokens': 10}}
        return super().generate(request, schema, *rest)


class SplittingProvider(ReconcilingProvider):
    """Split the first anchor's behaviour into two activities until repaired."""

    def _synthesize(self, graph, allowed):
        payload = super()._synthesize(graph, allowed)
        first = sorted(payload['activities'])[0]
        # The extra concept gives the twin its own identity.
        twin = copy.deepcopy(payload['activities'][first])
        twin.update(id='activity:twin', name=twin['name'] + ': record the result',
                    claim_ids=['claim:twin'], concept_ids=['concept:result'])
        payload['concepts']['concept:result'] = record(
            'Concept', id='concept:result', name='Order result',
            qualified_type_names=[], symbol_ids=[],
            evidence_ids=twin['evidence_ids'], claim_ids=['claim:twin'])
        payload['activities'][twin['id']] = twin
        payload['claims']['claim:twin'] = self._claim(
            'claim:twin', twin['id'], twin['description'], twin['evidence_ids'],
            twin['trace_ids'])
        payload['domains']['domain:orders']['activity_memberships'].append(record(
            'ActivityMembership', activity_id=twin['id'], role='supporting',
            claim_ids=['claim:domain']))
        anchor = twin['anchor_ids'][0]
        for disposition in payload['dispositions']:
            if disposition['subject_id'] == anchor:
                disposition['activity_ids'] = sorted(disposition['activity_ids'] + [twin['id']])
        return payload

    def generate(self, request, schema, *rest):
        if request['operation'] == 'verify' and request['deterministic_findings']:
            # Fail verification when deterministic checks already found problems.
            self.requests.append(copy.deepcopy(request))
            graph = request['graph']
            subjects = sorted({subject for finding in request['deterministic_findings']
                               for subject in finding['subject_ids']
                               if subject in request['candidate']['activities']})
            report = record(
                'VerificationReport', scope_id=graph['scope_id'],
                input_fingerprint=graph['input_fingerprint'], verdict='fail',
                findings=[record('VerificationFinding', id='verification_finding:split',
                                 category='incorrect_split', severity='blocking',
                                 message='One trace is split into several activities.',
                                 subject_ids=subjects)],
                checked_subject_ids=sorted(required_scope_subjects(graph)))
            return encode(report, DEFINITIONS['VerificationReport']), {
                'last': {'inputTokens': 10, 'outputTokens': 10}}
        if request['operation'] == 'repair':
            self.requests.append(copy.deepcopy(request))
            merged = ReconcilingProvider._synthesize(
                self, request['graph'], set(request['allowed_evidence_ids']))
            payload = record('RepairPayload',
                             parent_candidate_hash=request['parent_candidate_hash'],
                             candidate=merged)
            return encode(payload, DEFINITIONS['RepairPayload']), {
                'last': {'inputTokens': 10, 'outputTokens': 10}}
        return super().generate(request, schema, *rest)
