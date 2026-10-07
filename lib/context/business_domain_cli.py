"""Command-line owner for `speed discover domains`.

Prints exactly one JSON result on stdout. Progress events go to stderr, one
per line, prefixed with EVENT_PREFIX so the shell can render them.

Exit codes: 0 complete or partial, 1 failed, 3 configuration or provider
unavailable, 130 cancelled.
"""
import argparse
import json
import re
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
# records. This only reports; it never changes how a trace is resolved. A
# blocker is a boundary when extraction classified its obligation as one (the
# trace then lists the assumption), and a gap otherwise.
BOUNDARY_LABELS = {
    'generated_implementation': 'Generated/runtime implementation',
    'config_selected': 'Profile/config-selected implementation',
    'transaction_completion': 'Caller/container transaction completion',
    'library_call': 'Known library/platform calls',
    'endpoint_in_repo': 'HTTP calls to endpoints in this repository',
}
GAP_LABELS = {
    'generated_implementation': 'Generated implementation without catalog evidence',
    'ambiguous_implementation': 'Ambiguous implementation selection',
    'persistence': 'Unresolved persistence target or statement',
    'library_call': 'Calls into unknown libraries',
    'missing_call_target': 'Missing call targets',
    'http_boundary': 'HTTP calls to no known endpoint',
    'ambiguous_call_target': 'Ambiguous call targets (overloads)',
    'contract_only': 'Contract-only/unpinnable',
    'navigation_depth': 'Navigation/depth or symbol limit',
    'other': 'Other',
}
BLOCKER_LABELS = GAP_LABELS
_HTTP_EDGES = {'invokes_endpoint', 'emits'}


def _blocker(obligation, edge_kind):
    """The gap category of one obligation that is not satisfied."""
    kind, status = obligation['kind'], obligation['status']
    if kind == 'implementation_selection':
        return {'external': 'generated_implementation',
                'ambiguous': 'ambiguous_implementation',
                'conditional': 'ambiguous_implementation'}.get(status, 'contract_only')
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
    """Unique traces per blocker category; a trace counts once per category.

    Each item is a ``boundary`` or a ``gap``: boundaries first, then gaps,
    each by trace count and then in label order.
    """
    obligations, edges = facts['trace_obligations'], facts['edges']
    traces = {}
    for trace in facts['traces'].values():
        for obligation_id in trace['obligation_ids']:
            obligation = obligations[obligation_id]
            if obligation['status'] == 'satisfied':
                continue
            if obligation.get('boundary'):
                key = ('boundary', obligation['boundary'])
            else:
                edge = edges.get(obligation.get('edge_id') or '')
                key = ('gap', _blocker(obligation, edge['kind'] if edge else None))
            traces.setdefault(key, set()).add(trace['id'])
    labels = {'boundary': BOUNDARY_LABELS, 'gap': GAP_LABELS}
    order = {'boundary': list(BOUNDARY_LABELS), 'gap': list(GAP_LABELS)}
    return [{'class': kind, 'category': category, 'label': labels[kind][category],
             'traces': len(ids)}
            for (kind, category), ids in sorted(traces.items(), key=lambda item: (
                item[0][0] != 'boundary', -len(item[1]), order[item[0][0]].index(item[0][1])))]


def _registration(anchor):
    return next((item['registration'] for item in anchor.get('representations', [])
                 if item.get('registration')), None)


def entry_point_counts(facts):
    """``[{kind, resolved, total}]`` per entry-point kind, most frequent first.

    The kind is the registration an adapter declared (``http_route``,
    ``route``, ``action``, ``database_trigger``...), or the anchor kind when
    the anchor has no registration of its own.
    """
    counts = {}
    for anchor in facts['anchors'].values():
        registration = _registration(anchor)
        kind = registration['kind'] if registration else anchor['kind']
        entry = counts.setdefault(kind, {'kind': kind, 'resolved': 0, 'total': 0})
        entry['total'] += 1
        entry['resolved'] += anchor['resolution'] == 'resolved'
    return sorted(counts.values(), key=lambda item: (-item['total'], item['kind']))


_CANDIDATE_LABELS = re.compile(r"one of ((?:'[^']*'(?:, )?)+)")


def screen_actions(facts):
    """Each UI action anchor with its screen and label, or why it has none."""
    actions = []
    for anchor in facts['anchors'].values():
        registration = _registration(anchor)
        if not registration or registration['kind'] != 'action':
            continue
        label = registration.get('label')
        candidates = []
        if not label:
            found = _CANDIDATE_LABELS.search(registration.get('reason') or anchor.get('reason') or '')
            candidates = re.findall(r"'([^']*)'", found.group(1)) if found else []
        reason = (registration.get('reason') or anchor.get('reason') or '').split(';')[0]
        actions.append({
            # The screen, or the declaring file when no route is established.
            'route': (anchor['operation'].get('path')
                      or facts['symbols'][anchor['symbol_id']]['file']),
            'label': label, 'candidates': candidates,
            'state': ('ambiguous' if candidates else
                      'labeled' if label and anchor['resolution'] == 'resolved' else
                      'labeled_unresolved' if label else 'unlabeled'),
            'reason': reason.rstrip('.') or None})
    return sorted(actions, key=lambda item: (item['route'] or '', item['label'] or ''))


def generated_declarations(facts):
    """Build-time declarations modelled from generator inputs, and calls into them.

    Generated symbols are named ``<build file>::generated-<kind>:<name>``; the
    kind is whatever the generating adapter declared.
    """
    generated = {}
    for symbol in facts['symbols'].values():
        marker = symbol['qualified_name'].split('::', 1)[-1]
        if not marker.startswith('generated-'):
            continue
        kind = marker.split(':', 1)[0].removeprefix('generated-')
        entry = generated.setdefault(kind, {'kind': kind, 'types': 0, 'members': 0, 'calls': 0})
        entry['types' if symbol['kind'] == 'type' else 'members'] += 1
    for edge in facts['edges'].values():
        target = edge['to_ref'] if edge['kind'] == 'calls' and edge['resolution'] == 'resolved' else None
        if target and target['kind'] == 'symbol':
            marker = facts['symbols'][target['id']]['qualified_name'].split('::', 1)[-1]
            if marker.startswith('generated-'):
                generated[marker.split(':', 1)[0].removeprefix('generated-')]['calls'] += 1
    return sorted(generated.values(), key=lambda item: item['kind'])


def warning_counts(warnings):
    """``[{code, count}]``, most frequent first, then by code."""
    counts = {}
    for warning in warnings:
        counts[warning['code']] = counts.get(warning['code'], 0) + 1
    return [{'code': code, 'count': count}
            for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


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
            'warning_counts': warning_counts(facts['warnings']),
            'entry_points': entry_point_counts(facts),
            'screen_actions': screen_actions(facts),
            'generated_declarations': generated_declarations(facts),
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
