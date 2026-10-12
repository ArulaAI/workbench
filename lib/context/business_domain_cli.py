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
import time
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
    'in_process_state': 'Writes to in-process memory',
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
    'contract_only': 'Contract with no analyzed implementation',
    'unanalyzed_source': 'Implementation in unanalyzed source',
    'unidentified_entry_point': 'Entry point not fully identified',
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
        # Which capability is missing decides what the reader should do:
        # identify the entry point, or analyze the source behind it.
        return {'UNRESOLVED_ANCHOR': 'unidentified_entry_point',
                'CAPABILITY_UNAVAILABLE': 'unanalyzed_source'}.get(
                    obligation.get('reason_code'), 'contract_only')
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


def _language_names():
    """Display names of language ids, from the entry-point marker catalog."""
    from .business_domain_entrypoints import load_catalog
    return dict(load_catalog().display_names)


def warning_counts(warnings):
    """``[{code, count, boundary}]``, most frequent first, then by code.

    ``boundary`` marks codes the trace-boundary catalog classifies as known
    boundaries: expected records of a stated assumption, not problems.
    """
    from .business_domain_extract import TRACE_BOUNDARIES
    known = set(TRACE_BOUNDARIES['diagnostic_codes']) | set(TRACE_BOUNDARIES['library_codes'])
    counts = {}
    for warning in warnings:
        counts[warning['code']] = counts.get(warning['code'], 0) + 1
    return [{'code': code, 'count': count, 'boundary': code in known}
            for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _relative(root, path):
    return str(Path(path).relative_to(root))


# ── The --facts-only report ──────────────────────────────────────────────
#
# What a reader asks first is whether each entry point was followed to an end
# this tool can name, and if not, exactly where it stopped. The report answers
# that from the facts alone: it counts, never reclassifies. A call site on a
# trace is in this repository, at a platform or library boundary the facts
# name, or open; an open site is listed with its source line.

# Languages the entry-point catalog does not name: data and documentation.
_DATA_LANGUAGE_NAMES = {'json': 'JSON', 'yaml': 'YAML', 'markdown': 'Markdown',
                        'toml': 'TOML', 'xml': 'XML', 'properties': 'Properties',
                        'css': 'CSS', 'scss': 'SCSS', 'csv': 'CSV'}
MAX_OPEN_SITES = 8
MAX_UNANALYZED_PATHS = 4
_UNANALYZED = re.compile(r'^(?P<path>[^:]+): language=(?P<language>[^;]+);.*?'
                         r'cause=(?P<cause>[^;]+);.*?lost_facts=(?P<lost>\[[^\]]*\])')


def _call_site(facts, edge):
    """Where the call *edge* records its site: (path, line, excerpt)."""
    for evidence_id in edge.get('evidence_ids') or ():
        evidence = facts['evidence'].get(evidence_id) or {}
        locator = evidence.get('locator') or {}
        if locator.get('path'):
            excerpt = ' '.join((evidence.get('excerpt') or '').split())
            return locator['path'], locator.get('start_line'), excerpt
    return None, None, ''


def _call_class(facts, edge):
    """repository, platform, library, ambiguous or open."""
    if edge['resolution'] == 'resolved':
        return 'repository'
    if edge['resolution'] == 'ambiguous':
        return 'ambiguous'
    target = edge.get('to_ref') or {}
    resource = facts['resources'].get(target.get('id')) if target.get('kind') == 'resource' else None
    if not resource:
        return 'open'
    return 'platform' if (resource.get('provider') or '').startswith('global:') else 'library'


def _calls_on_traces(facts):
    """Each distinct call site any trace reaches, classified once."""
    edges = facts['edges']
    seen = {}
    for trace in facts['traces'].values():
        for edge_id in trace.get('edge_ids', ()):
            edge = edges.get(edge_id)
            if edge and edge['kind'] == 'calls' and edge_id not in seen:
                seen[edge_id] = edge
    counts = {'sites': len(seen), 'repository': 0, 'platform': 0, 'library': 0,
              'ambiguous': 0, 'open': 0}
    platforms, libraries, open_sites = {}, {}, []
    for edge in seen.values():
        kind = _call_class(facts, edge)
        counts[kind] += 1
        if kind in {'platform', 'library'}:
            resource = facts['resources'][edge['to_ref']['id']]
            provider = (resource.get('provider') or resource.get('name') or '?')
            provider = provider.split(':', 1)[-1]
            bucket = platforms if kind == 'platform' else libraries
            bucket[provider] = bucket.get(provider, 0) + 1
        elif kind in {'open', 'ambiguous'}:
            path, line, excerpt = _call_site(facts, edge)
            open_sites.append({'path': path, 'line': line, 'excerpt': excerpt,
                               'state': kind, 'reason': edge.get('reason')})
    ranked = lambda bucket: [{'name': name, 'sites': count} for name, count in
                             sorted(bucket.items(), key=lambda item: (-item[1], item[0]))]
    open_sites.sort(key=lambda item: (item['path'] or '', item['line'] or 0))
    return counts, ranked(platforms), ranked(libraries), open_sites


MAX_STORES = 6


def _data_on_traces(facts):
    """Reads and writes any trace reaches, per data resource, each site once."""
    edges = facts['edges']
    seen = {}
    for trace in facts['traces'].values():
        for edge_id in trace.get('edge_ids', ()):
            edge = edges.get(edge_id)
            if edge and edge['kind'] in {'reads_data', 'writes_data'} and edge['to_ref']:
                seen[edge_id] = edge
    stores = {}
    for edge in seen.values():
        resource = facts['resources'].get(edge['to_ref']['id']) or {}
        name = resource.get('name') or edge['to_ref']['id']
        entry = stores.setdefault(name, {'name': name.split('::', 1)[-1],
                                         'kind': resource.get('kind'), 'reads': 0, 'writes': 0})
        entry['reads' if edge['kind'] == 'reads_data' else 'writes'] += 1
    ranked = sorted(stores.values(), key=lambda item: (-(item['reads'] + item['writes']),
                                                       item['name']))
    return {'reads': sum(item['reads'] for item in ranked),
            'writes': sum(item['writes'] for item in ranked),
            'stores': len(ranked),
            'in_memory': all(item['kind'] == 'memory_store' for item in ranked),
            'top': ranked[:MAX_STORES], 'more': max(len(ranked) - MAX_STORES, 0)}


def _unanalyzed_sources(warnings):
    """Files discovery found but could not analyze, and what that cost."""
    files = []
    for warning in warnings:
        if warning.get('code') != 'SOURCE_CAPABILITY_UNAVAILABLE':
            continue
        match = _UNANALYZED.match(warning.get('message') or '')
        if match:
            files.append({'path': match['path'], 'language': match['language'],
                          'cause': match['cause'], 'facts_lost': match['lost'] != '[]'})
    return sorted(files, key=lambda item: item['path'])


def _relationships(facts, measured):
    """Resolved and unresolved relationships, and where the unresolved lie.

    An unresolved relationship on a trace either ends at a resource the facts
    name (a platform or library) or is open; one no trace reaches is counted
    apart, since no business flow depends on it.
    """
    traced = {edge_id for trace in facts['traces'].values() for edge_id in trace.get('edge_ids', ())}
    on_traces = [edge for edge in facts['edges'].values()
                 if edge['resolution'] != 'resolved' and edge['id'] in traced]
    named = sum((edge.get('to_ref') or {}).get('kind') == 'resource' for edge in on_traces)
    # Distinct edges, so the parts add up: the coverage counters count each
    # call occurrence, and two occurrences can record one edge.
    return {'resolved': sum(edge['resolution'] == 'resolved' for edge in facts['edges'].values()),
            'open': measured['open'],
            'outside_traces': measured['open_outside_traces'],
            'on_traces_at_boundaries': named,
            'on_traces_open': len(on_traces) - named}


def facts_report(facts, root=None, elapsed_ms=None):
    """The data the terminal summary shows, computed from *facts* alone."""
    code_names = _language_names()
    names = {**_DATA_LANGUAGE_NAMES, **code_names}
    measured = extraction_measurements(facts)
    files, code = {}, set(code_names.values())
    for resource in facts['resources'].values():
        if resource.get('kind') == 'repository_file' and resource.get('language'):
            label = names.get(resource['language'], resource['language'])
            files[label] = files.get(label, 0) + 1
    calls, platforms, libraries, open_sites = _calls_on_traces(facts)
    traces = measured['traces']
    edges = facts['edges'].values()
    unanalyzed = _unanalyzed_sources(facts.get('warnings', []))
    relationships = measured['relationships']
    return {
        'repository': Path(root).name if root else None,
        'elapsed_ms': elapsed_ms,
        # Source code first, then documentation and data, each most files first.
        'files': [{'language': language, 'files': count, 'code': language in code}
                  for language, count in sorted(files.items(), key=lambda item: (
                      item[0] not in code, -item[1], item[0]))],
        'symbols': len(facts['symbols']),
        'traces': {'total': traces['total'], 'complete': traces.get('complete', 0),
                   'bounded': traces.get('bounded', 0),
                   'incomplete': traces.get('incomplete', 0)},
        'calls': calls,
        'data': _data_on_traces(facts),
        'effects': len(facts.get('effects', {})),
        'platforms': platforms,
        'libraries': libraries,
        'open_sites': open_sites[:MAX_OPEN_SITES],
        'open_sites_more': max(len(open_sites) - MAX_OPEN_SITES, 0),
        'evidence': {
            'tests': sum(edge['kind'] == 'tests_behavior' for edge in edges),
            'documentation': sum(edge['kind'] == 'documents_behavior' for edge in edges),
            'inputs': sum(binding.get('direction') == 'input'
                          for binding in facts.get('bindings', {}).values()),
            'rule_observations': len(facts.get('rule_observations', {})),
        },
        'relationships': _relationships(facts, relationships),
        'unanalyzed': {'files': len(unanalyzed),
                       'facts_lost': sum(item['facts_lost'] for item in unanalyzed),
                       'languages': sorted({names.get(item['language'], item['language'])
                                            for item in unanalyzed}),
                       'causes': sorted({item['cause'] for item in unanalyzed}),
                       'paths': [item['path'] for item in unanalyzed[:MAX_UNANALYZED_PATHS]],
                       'more': max(len(unanalyzed) - MAX_UNANALYZED_PATHS, 0)},
    }


def facts_only(root):
    """Deterministic extraction only; never invokes a provider."""
    config = settings(load_speed_toml(str(root)))
    target = paths(root)['facts']
    _progress({'stage': 'domain.extract', 'level': 'step',
               'message': 'Extracting business-domain facts (no model calls)'})
    started = time.monotonic()
    with build_lock(root):
        facts, _ = Extractor(root, config).extract()
        atomic_write(target, facts, config['max_artifact_bytes'])
    elapsed_ms = round((time.monotonic() - started) * 1000)
    return {'mode': 'facts', 'artifact': _relative(root, target),
            'report': facts_report(facts, root, elapsed_ms),
            'measurements': extraction_measurements(facts),
            'trace_blockers': trace_blockers(facts),
            'warning_counts': warning_counts(facts['warnings']),
            'language_names': _language_names(),
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
        # A failed attempt leaves the previous model in place. It is still the
        # published model, but this attempt did not publish it.
        published = (model is not None and outcome in {'complete', 'partial'}
                     and status['published_build_id'] == status['attempt_build_id'])
        result = {'mode': 'run', 'status': status, 'published': published,
                  'published_build_id': status['published_build_id'] if published else None,
                  'preserved_build_id': None if published else status['published_build_id'],
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
