"""Rehearse a full discovery run without calling a model.

Manual check, not collected by the test runner. Copies a repository (without
its .speed directory) to a scratch folder and runs the real discovery pipeline
there with a fake provider: extraction, slicing, synthesis, verification,
repair, reconciliation and publication all run, so deterministic defects show
up before a paid run. The fake rejects the first verification of every scope,
so every scope also goes through one repair round.

Fake answers would poison a real cache, which is why it never runs in place.
Afterwards it replays the saved requests to estimate what the provider would
have been sent.

    python tests/business_domains/rehearse.py --repo ~/petclinic-test
    python tests/business_domains/rehearse.py --repo ~/petclinic-test --work /tmp/rehearsal --keep
"""
import argparse
import copy
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.context.business_domain_schema import (
    DEFINITIONS, DomainError, record, required_scope_subjects)
from lib.context.business_domain_synthesis import Synthesis
from lib.context.business_domains import discover
from tests.business_domains.oversized_fixture import ReconcilingProvider
from tests.business_domains.provider_fixture import encode


class RehearsalProvider(ReconcilingProvider):
    """Reject each scope's first verification once, then reword what it named.

    It takes the compact wire, as the real provider does, so requests are sized
    and focused exactly as in a paid run. Answers are built from the canonical
    request behind each wire request and returned under the wire's aliases.
    """

    provider_context_tokens = 1_000_000
    provider_max_output_tokens = 128_000
    accepts_projected_wire = True

    def __init__(self):
        super().__init__()
        self.rejected = set()
        self.focused = 0
        self.exchanges = {}

    def watch(self, synthesis_class):
        """Record the canonical request and projection behind each wire request."""
        original = synthesis_class.project_exchange
        exchanges = self.exchanges

        def project_exchange(runner, request, schema, projection=None):
            result = original(runner, request, schema, projection)
            # Sizing estimates project requests without an ID; nothing is sent for them.
            if 'request_id' in request:
                exchanges[request['request_id']] = (request, result[2])
            return result
        synthesis_class.project_exchange = project_exchange
        return original

    def generate(self, wire_request, schema, *rest):
        request, projection = self.exchanges[wire_request['request_id']]
        value, usage = self._answer(request, schema, *rest)
        return _record_ids_keep_kind(projection._rewrite(value, projection.aliases),
                                     projection), usage

    def _answer(self, request, schema, *rest):
        operation, graph = request['operation'], request['graph']
        if operation == 'verify' and graph['scope_id'] not in self.rejected:
            self.rejected.add(graph['scope_id'])
            self.requests.append(copy.deepcopy(request))
            # Name a record the repair answer will hold: compact reconciliation
            # answers return their domain, slices return everything.
            collections = (('domains',) if graph['scope_kind'] == 'reconciliation'
                           else ('activities', 'domains'))
            subject = sorted(record_id for collection in collections
                             for record_id in request['candidate'][collection])[0]
            report = record(
                'VerificationReport', scope_id=graph['scope_id'],
                input_fingerprint=graph['input_fingerprint'], verdict='fail',
                findings=[record('VerificationFinding', id='verification_finding:rehearsal',
                                 category='unsupported_claim', severity='blocking',
                                 message='The rehearsal rejects the first verification.',
                                 subject_ids=[subject])],
                checked_subject_ids=sorted(required_scope_subjects(graph)))
            return encode(report, DEFINITIONS['VerificationReport']), {
                'last': {'inputTokens': 10, 'outputTokens': 10}}
        if operation == 'repair':
            self.requests.append(copy.deepcopy(request))
            self.focused += 'provider_focus' in request
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


def _record_ids_keep_kind(value, projection):
    """Return continued record IDs as `<kind>:_ref:N`, as the real provider does."""
    if isinstance(value, list):
        return [_record_ids_keep_kind(item, projection) for item in value]
    if not isinstance(value, dict):
        return value
    value = {key: _record_ids_keep_kind(item, projection) for key, item in value.items()}
    identifier = value.get('id')
    if isinstance(identifier, str) and identifier.startswith('_ref:'):
        kind = projection.canonical_ids.get(identifier, '').partition(':')[0]
        if kind:
            value['id'] = f'{kind}:{identifier}'
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--work', type=Path,
                        help='Folder to create the scratch copy in (default: the system temp folder)')
    parser.add_argument('--keep', action='store_true', help='Keep the scratch copy')
    args = parser.parse_args()

    source = args.repo.expanduser().resolve()
    # Everything happens in a new folder this run creates, and only that folder
    # is ever deleted, so neither the repository nor --work can be lost.
    parent = args.work.expanduser().resolve() if args.work else None
    if parent is not None:
        if parent == source or source in parent.parents:
            parser.error('--work must be outside the repository')
        parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='speed-rehearsal-', dir=parent))
    target = work / source.name
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('.speed'))
    print(f'Rehearsing in {target}')

    provider = RehearsalProvider()
    original = provider.watch(Synthesis)
    try:
        model, status = discover(target, provider=provider)
    except DomainError as exc:
        model, status = None, {'phase': 'failed', 'error': exc.record()}
    finally:
        Synthesis.project_exchange = original
    failed = model is None
    if failed:
        error = status.get('error') or {}
        outcome = f"FAILED in phase {status.get('phase')}: {error.get('code')}: {error.get('message')}"
    else:
        outcome = (f"published ({status.get('phase')}): {len(model.get('domains', {}))} domains, "
                   f"{len(model.get('activities', {}))} activities")
    calls = Counter((request['operation'], request['graph']['scope_kind'])
                    for request in provider.requests)
    print(outcome)
    for (operation, kind), count in sorted(calls.items()):
        print(f'  {operation:<10} {kind:<15} {count}')
    repairs = sum(count for (operation, _), count in calls.items() if operation == 'repair')
    print(f'  focused repairs: {provider.focused} of {repairs}')

    cache = target / '.speed/context/business-domain-cache'
    if cache.is_dir():
        print('\nEstimated provider input for this run:')
        subprocess.run([sys.executable, str(Path(__file__).with_name('replay_focus.py')),
                        '--cache', str(cache)], check=False)
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
