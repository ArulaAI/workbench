"""The facts-only trace-blocker report counts unique traces per category.

It reads the obligations each trace already records and never changes how a
trace is resolved.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from lib.context.business_domain_cli import BLOCKER_LABELS, facts_only, trace_blockers
from lib.context.business_domain_extract import extraction_measurements
from tests.test_business_domain_endpoint_links import BACKEND, CLIENT

SPEED_ROOT = Path(__file__).parents[1]


def _facts(traces, edges=(), warnings=()):
    """Minimal facts: ``traces`` maps trace ID to (kind, status, edge kind) tuples."""
    facts = {'traces': {}, 'trace_obligations': {}, 'edges': {},
             'warnings': list(warnings)}
    for edge_id, kind in edges:
        facts['edges'][edge_id] = {'id': edge_id, 'kind': kind}
    for trace_id, obligations in traces.items():
        ids = []
        for index, (kind, status, edge_id) in enumerate(obligations):
            obligation_id = f'{trace_id}:{index}'
            facts['trace_obligations'][obligation_id] = {
                'id': obligation_id, 'kind': kind, 'status': status, 'edge_id': edge_id}
            ids.append(obligation_id)
        facts['traces'][trace_id] = {'id': trace_id, 'obligation_ids': ids}
    return facts


def _counts(facts):
    return {item['category']: item['traces'] for item in trace_blockers(facts)}


@pytest.mark.parametrize('kind, status, edge_kind, category', [
    ('implementation_selection', 'external', None, 'generated_implementation'),
    ('implementation_selection', 'ambiguous', None, 'ambiguous_implementation'),
    ('implementation_selection', 'unresolved', None, 'contract_only'),
    ('data_target', 'unresolved', 'writes_data', 'persistence'),
    ('external_boundary', 'external', 'invokes_endpoint', 'http_boundary'),
    ('external_boundary', 'external', 'calls', 'library_call'),
    ('call_target', 'unresolved', 'calls', 'missing_call_target'),
    ('call_target', 'ambiguous', 'calls', 'ambiguous_call_target'),
    ('call_target', 'ambiguous', 'navigates_to', 'navigation_depth'),
    ('depth_limit', 'limit_reached', None, 'navigation_depth'),
    ('capability', 'unresolved', None, 'contract_only'),
    ('execution_segment', 'unresolved', None, 'other'),
])
def test_each_obligation_maps_to_one_category(kind, status, edge_kind, category):
    facts = _facts({'t': [(kind, status, 'e' if edge_kind else None)]},
                   edges=[('e', edge_kind)] if edge_kind else [])
    assert _counts(facts) == {category: 1}


def test_a_trace_counts_once_per_category_however_many_obligations_it_has():
    facts = _facts({'t': [('call_target', 'unresolved', None)] * 5})
    assert _counts(facts) == {'missing_call_target': 1}


def test_one_trace_with_several_blockers_appears_in_each_category():
    facts = _facts({
        'a': [('implementation_selection', 'external', None),
              ('data_target', 'unresolved', None),
              ('call_target', 'unresolved', None)],
        'b': [('data_target', 'unresolved', None)],
    })
    assert _counts(facts) == {'generated_implementation': 1, 'persistence': 2,
                              'missing_call_target': 1}


def test_satisfied_obligations_and_resolved_traces_are_not_blockers():
    facts = _facts({'resolved': [('call_target', 'satisfied', None)] * 3,
                    'empty': []})
    assert trace_blockers(facts) == []


def test_warnings_are_never_counted_as_traces():
    warnings = [{'code': 'JAVA_CALL_AMBIGUOUS'}] * 18
    facts = _facts({'t': [('call_target', 'ambiguous', None)]}, warnings=warnings)
    assert _counts(facts) == {'ambiguous_call_target': 1}


def test_categories_are_ordered_by_trace_count_then_fixed_order():
    facts = _facts({'a': [('data_target', 'unresolved', None)],
                    'b': [('data_target', 'unresolved', None),
                          ('implementation_selection', 'external', None)]})
    assert [item['category'] for item in trace_blockers(facts)] == [
        'persistence', 'generated_implementation']
    assert set(BLOCKER_LABELS) >= {item['category'] for item in trace_blockers(facts)}


@pytest.fixture(scope='module')
def petclinic_shaped(tmp_path_factory):
    root = tmp_path_factory.mktemp('blockers')
    for name, text in {**BACKEND, **CLIENT}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    result, code = facts_only(root)
    return root, result, code


def test_facts_only_reports_blockers_without_changing_trace_measurements(petclinic_shaped):
    root, result, code = petclinic_shaped
    assert code == 0
    facts = json.loads((root / result['artifact']).read_text())
    assert result['measurements'] == extraction_measurements(facts)
    assert result['trace_blockers'] == trace_blockers(facts)
    unresolved = sum(trace['resolution'] != 'resolved' for trace in facts['traces'].values())
    blocked = {trace['id'] for trace in facts['traces'].values()
               if any(facts['trace_obligations'][oid]['status'] != 'satisfied'
                      for oid in trace['obligation_ids'])}
    assert len(blocked) == unresolved
    assert all(0 < item['traces'] <= unresolved for item in result['trace_blockers'])


def test_terminal_output_lists_blockers_with_the_overlap_note(petclinic_shaped, tmp_path):
    _, result, _ = petclinic_shaped
    payload = tmp_path / 'result.json'
    payload.write_text(json.dumps(result))
    rendered = subprocess.run(
        ['bash', '-c', f'source lib/cmd/domains.sh; _domains_render_facts "{payload}"'],
        cwd=SPEED_ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    traces = result['measurements']['traces']
    assert rendered[0] == (f"Traces:          {traces['resolved']}/{traces['total']} resolved "
                           f"({traces['ambiguous']} ambiguous, {traces['unresolved']} unresolved)")
    assert rendered[1] == (f"Completion:      {traces['complete']} complete, "
                           f"{traces['bounded']} bounded, {traces['incomplete']} incomplete")
    boundaries = [item for item in result['trace_blockers'] if item['class'] == 'boundary']
    gaps = [item for item in result['trace_blockers'] if item['class'] == 'gap']
    sections = {line: index for index, line in enumerate(rendered)}
    if boundaries:
        assert 'Trace boundaries (known; the trace lists each assumption):' in sections
    assert 'Trace gaps:' in sections
    for item in boundaries + gaps:
        suffix = 'trace' if item['traces'] == 1 else 'traces'
        assert any(line.startswith('  ' + item['label']) and
                   line.endswith(f"{item['traces']} {suffix}") for line in rendered)
    # Every gap row follows the gap heading; every boundary row precedes it.
    gap_heading = sections['Trace gaps:']
    for item in gaps:
        assert any(index > gap_heading and line.startswith('  ' + item['label'])
                   for index, line in enumerate(rendered))
    assert '  Note: categories may overlap; a trace can have' in rendered
    assert rendered[-2:] == ['Facts written to:', result['artifact']]


def test_terminal_output_omits_the_section_when_nothing_blocks(tmp_path):
    payload = tmp_path / 'result.json'
    payload.write_text(json.dumps({
        'artifact': '.speed/context/business-domain-facts.json', 'trace_blockers': [],
        'measurements': {'traces': {'total': 1, 'resolved': 1, 'ambiguous': 0, 'unresolved': 0},
                         'call_targets': {'unresolved': 0, 'unresolved_by_language': {}}},
        'coverage': {'edges_resolved': 1, 'edges_unresolved': 0, 'edges_ambiguous': 0},
        'warnings': []}))
    rendered = subprocess.run(
        ['bash', '-c', f'source lib/cmd/domains.sh; _domains_render_facts "{payload}"'],
        cwd=SPEED_ROOT, capture_output=True, text=True, check=True).stdout
    assert 'Trace resolution blockers' not in rendered
    assert rendered.startswith('Traces:          1/1 resolved')


PETCLINIC = Path(os.environ.get('SPEED_PETCLINIC_FACTS', Path.home() /
    'Desktop/spring-petclinic-reactjs-master/.speed/context/business-domain-facts.json'))


@pytest.mark.skipif(not PETCLINIC.is_file(), reason='PetClinic facts are not available')
def test_petclinic_blockers_cover_every_unresolved_trace():
    facts = json.loads(PETCLINIC.read_text())
    traces = extraction_measurements(facts)['traces']
    blockers = trace_blockers(facts)
    # 52 traces before per-route actions; each shared action now has one per screen.
    assert (traces['resolved'], traces['total']) == (2, 54)
    assert traces['complete'] == traces['resolved']
    boundaries = {item['category'] for item in blockers if item['class'] == 'boundary'}
    gaps = {item['category'] for item in blockers if item['class'] == 'gap'}
    assert boundaries == {'generated_implementation', 'config_selected', 'transaction_completion',
                          'library_call', 'endpoint_in_repo'}
    assert {'missing_call_target', 'navigation_depth', 'ambiguous_call_target',
            'http_boundary', 'contract_only'} <= gaps
    assert all(item['traces'] <= traces['unresolved'] + traces['ambiguous'] for item in blockers)
