"""Command-line owner for `speed discover domains`.

Prints exactly one JSON result on stdout. Progress events go to stderr, one
per line, prefixed with EVENT_PREFIX so the shell can render them.

Exit codes: 0 complete or partial, 1 failed, 3 configuration or provider
unavailable, 130 cancelled.
"""
import argparse
import json
import sys
from pathlib import Path

from .business_domain_extract import Extractor, extraction_measurements
from .business_domain_schema import DomainError, atomic_write, read_status, settings
from .business_domains import build_lock, cancel_build, discover, load, paths
from .discovery_logging import DiscoveryRecorder
from .utils import load_speed_toml

EVENT_PREFIX = '__SPEED_DISCOVERY_EVENT__'
CONFIG_ERRORS = {'INVALID_CONFIG', 'INVALID_ROOT', 'PROVIDER_UNAVAILABLE',
                 'PROVIDER_CAPABILITY_UNAVAILABLE'}
EXIT_BY_PHASE = {'complete': 0, 'partial': 0, 'cancelled': 130, 'unavailable': 3}


def _progress(event):
    print(EVENT_PREFIX + json.dumps(event, separators=(',', ':')),
          file=sys.stderr, flush=True)


# Why traces are not resolved, read from the obligations each trace already
# records. This only reports; it never changes how a trace is resolved.
BLOCKER_LABELS = {
    'generated_implementation': 'Generated/runtime implementation',
    'ambiguous_implementation': 'Ambiguous implementation selection',
    'persistence': 'Persistence completion',
    'library_call': 'Library calls',
    'missing_call_target': 'Missing call targets',
    'http_boundary': 'HTTP boundaries',
    'ambiguous_call_target': 'Ambiguous call targets (overloads)',
    'contract_only': 'Contract-only/unpinnable',
    'navigation_depth': 'Navigation/depth',
    'other': 'Other',
}
_HTTP_EDGES = {'invokes_endpoint', 'emits'}


def _blocker(obligation, edge_kind):
    """The blocker category of one obligation that is not satisfied."""
    kind, status = obligation['kind'], obligation['status']
    if kind == 'implementation_selection':
        return {'external': 'generated_implementation',
                'ambiguous': 'ambiguous_implementation'}.get(status, 'contract_only')
    if kind == 'data_target':
        return 'persistence'
    if kind == 'external_boundary':
        return 'http_boundary' if edge_kind in _HTTP_EDGES else 'library_call'
    if kind == 'call_target':
        if status != 'ambiguous':
            return 'missing_call_target'
        return 'navigation_depth' if edge_kind == 'navigates_to' else 'ambiguous_call_target'
    if kind in {'depth_limit', 'symbol_limit'}:
        return 'navigation_depth'
    if kind == 'capability':
        return 'contract_only'
    return 'other'


def trace_blockers(facts):
    """Unique traces per blocker category; a trace counts once per category."""
    obligations, edges = facts['trace_obligations'], facts['edges']
    traces = {category: set() for category in BLOCKER_LABELS}
    for trace in facts['traces'].values():
        for obligation_id in trace['obligation_ids']:
            obligation = obligations[obligation_id]
            if obligation['status'] == 'satisfied':
                continue
            edge = edges.get(obligation.get('edge_id') or '')
            traces[_blocker(obligation, edge['kind'] if edge else None)].add(trace['id'])
    order = list(BLOCKER_LABELS)
    return [{'category': category, 'label': BLOCKER_LABELS[category],
             'traces': len(ids)}
            for category, ids in sorted(traces.items(),
                key=lambda item: (-len(item[1]), order.index(item[0])))
            if ids]


def _relative(root, path):
    return str(Path(path).relative_to(root))


def facts_only(root):
    """Deterministic extraction only; never invokes a provider."""
    config = settings(load_speed_toml(str(root)))
    target = paths(root)['facts']
    _progress({'stage': 'domain.extract', 'level': 'step',
               'message': 'Extracting business-domain facts (no model calls)'})
    with build_lock(root):
        facts, _ = Extractor(root, config).extract()
        atomic_write(target, facts, config['max_artifact_bytes'])
    return {'mode': 'facts', 'artifact': _relative(root, target),
            'measurements': extraction_measurements(facts),
            'trace_blockers': trace_blockers(facts),
            'coverage': facts['coverage'], 'warnings': facts['warnings']}, 0


def run(root):
    """Full pipeline: extract, synthesize, verify, publish."""
    recorder = DiscoveryRecorder(root, progress=_progress)
    outcome, result = 'failed', None
    try:
        model, status = discover(root, load_speed_toml(str(root)),
                                 recorder=recorder, run_id=recorder.run_id)
        outcome = status['phase']
        result = {'mode': 'run', 'status': status, 'published': model is not None,
                  'published_build_id': status['published_build_id'],
                  'artifact': _relative(root, paths(root)['model']) if model else None,
                  'log': recorder.relative_path}
        return result, EXIT_BY_PHASE.get(outcome, 1)
    finally:
        recorder.finish(outcome, result)


def status(root):
    model, current = load(root)
    return {'mode': 'status', 'status': current, 'published': model is not None,
            'published_build_id': model['build_id'] if model else None}, 0


def cancel(root):
    current = read_status(paths(root)['status'])
    if not current:
        raise DomainError('BUILD_NOT_RUNNING', 'No domain build has been started')
    return {'mode': 'cancel', **cancel_build(root, current['attempt_build_id'])}, 0


MODES = {'run': run, 'facts': facts_only, 'status': status, 'cancel': cancel}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='speed discover domains')
    parser.add_argument('--root', default='.')
    mode = parser.add_mutually_exclusive_group()
    for flag, name in (('--facts-only', 'facts'), ('--status', 'status'),
                       ('--cancel', 'cancel')):
        mode.add_argument(flag, dest='mode', action='store_const', const=name)
    parser.set_defaults(mode='run')
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if not root.is_dir():
            raise DomainError('INVALID_ROOT', 'Repository root does not exist')
        result, code = MODES[args.mode](root)
        result['ok'] = code == 0
    except KeyboardInterrupt:
        result, code = {'ok': False, 'mode': args.mode,
                        'error': {'code': 'CANCELLED', 'message': 'Interrupted'}}, 130
    except DomainError as exc:
        code = 3 if exc.code in CONFIG_ERRORS else 1
        result = {'ok': False, 'mode': args.mode,
                  'error': {'code': exc.code, 'message': str(exc)}}
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == '__main__':
    sys.exit(main())
