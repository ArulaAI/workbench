"""Repositories too large for one whole-graph request, made small on purpose.

Hierarchical discovery (BD-40) applies when the complete synthesis,
verification, repair and reverification sequence does not fit one request.
Real repositories that large cost an hour of provider time per run, so these
fixtures are small and the request allowance is lowered instead:
`max_request_input_tokens` is the specified setting that bounds every request,
and `calibrate` measures each fixture to choose the allowance that forces the
partition a test needs.

The shapes follow BD-40's fixture list:

    write_monolith      one service, many entry points, one shared helper
                        module every entry point calls (overlapping shared code)
    write_long_chain    one entry point whose single trace runs many steps
                        (a single oversized trace)
    write_monorepo      several services, each its own deployable boundary
                        (a synthetic monorepo)
    InterruptingProvider
                        fails after a number of synthesis requests
                        (interrupted and resumed work)
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
    """One entry point whose single trace runs `steps` settlement steps.

    The entry point calls every step in turn, so the whole chain stays inside
    one trace however short the trace depth limit is.
    """
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
    """Configuration that bounds every semantic request to `allowance` tokens."""
    return {'business_domains': {'max_request_input_tokens': allowance}}


@dataclass(frozen=True)
class Calibration:
    """Measured request sizes of one fixture under one provider.

    `whole` is the complete graph scope; `anchors` maps each canonical anchor
    to the scope holding only its trace closure. `allowance(size)` is the
    request allowance at which a scope of `size` tokens exactly fits its
    complete synthesis, verification and repair sequence.
    """
    whole: int
    anchors: dict
    output_allowance: int

    def allowance(self, size: int) -> int:
        return size + 2 * self.output_allowance

    def splitting_allowance(self) -> int:
        """An allowance every single-anchor scope fits and the whole graph does not."""
        largest = max(self.anchors.values())
        low, high = self.allowance(largest), self.allowance(self.whole) - 1
        if low > high:
            raise AssertionError(
                f'Fixture cannot split: largest anchor needs {low}, '
                f'whole graph needs {high + 1}')
        return (low + high) // 2


def calibrate(root: Path, provider=None) -> Calibration:
    """Measure `root` exactly as discovery would size its requests."""
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
    """A provider that behaves as a model would in hierarchical mode.

    For a whole graph or a slice it proposes one activity per canonical anchor,
    citing that anchor's own evidence and traces, and groups them in one
    domain. For a reconciliation scope it keeps every child activity, groups
    them anew, and reports each child represented by exactly the records its
    coverage manifest lists.
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

    def _reconcile(self, graph, _allowed):
        context = graph['context']
        activities = copy.deepcopy(context['activities'])
        claims = {claim_id: copy.deepcopy(claim) for claim_id, claim in context['claims'].items()
                  if claim['kind'] != 'coverage_manifest'
                  and claim['subject_id'] in activities}
        evidence = sorted({eid for item in activities.values() for eid in item['evidence_ids']})
        domains = {'domain:orders': self._domain(activities, claims, evidence)}
        dispositions = []
        for index, child_id in enumerate(sorted(graph['child_scope_ids'])):
            manifest = next(claim for claim in context['claims'].values()
                            if claim['kind'] == 'coverage_manifest'
                            and claim['subject_id'] == child_id)
            listed = manifest['text'].split('Records it contributes: ', 1)[1]
            listed = listed.split('. Typed cross-scope edges', 1)[0]
            incorporated = sorted(item for item in listed.split(', ')
                                  if item in activities)
            dispositions.append(record('ScopeDisposition', id=f'disposition:c{index}',
                subject_kind='child_scope', subject_id=child_id, status='represented',
                incorporated_record_ids=incorporated))
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
    """Reject the first `rejections` verifications; repairs reword what was named.

    `interruptions` repair requests fail before any repair succeeds, which
    leaves a repair chain interrupted mid-way.
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
