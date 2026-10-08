import json
import subprocess
import sys
from pathlib import Path

from lib.context.business_domain_extract import extraction_measurements


def test_measurements_group_unresolved_calls_by_normalized_language():
    facts = {
        'resources': {'resource:ts': {'id': 'resource:ts',
            'kind': 'repository_file', 'name': 'src/view.ts',
            'language': 'typescript'}},
        'symbols': {'symbol:caller': {'id': 'symbol:caller',
            'file': 'src/view.ts'}},
        'anchors': {'anchor:ui': {'id': 'anchor:ui', 'kind': 'ui'}},
        'traces': {'trace:ui': {'id': 'trace:ui', 'anchor_id': 'anchor:ui',
            'resolution': 'unresolved', 'ui_interaction': {}}},
        'trace_obligations': {'trace_obligation:call': {
            'id': 'trace_obligation:call', 'kind': 'call_target',
            'status': 'unresolved',
            'origin_ref': {'kind': 'symbol', 'id': 'symbol:caller'}}},
    }

    assert extraction_measurements(facts) == {
        'schema_version': 1,
        'traces': {'total': 1, 'resolved': 0, 'ambiguous': 0, 'unresolved': 1,
                   'complete': 0, 'bounded': 0, 'incomplete': 0},
        'relationships': {'open': 0, 'open_by_language': {}, 'open_at_boundaries': 0,
                          'open_outside_traces': 0},
        'call_targets': {'unresolved': 1,
                         'unresolved_by_language': {'typescript': 1},
                         'unresolved_sites': 1,
                         'unresolved_sites_by_language': {'typescript': 1}},
        'ui_interactions': {'eligible_traces': 1, 'populated_traces': 1},
    }


def test_one_call_site_reached_by_several_traces_is_one_unresolved_site():
    obligation = lambda trace, edge: {
        'id': f'trace_obligation:{trace}:{edge}', 'kind': 'call_target', 'status': 'unresolved',
        'edge_id': edge, 'origin_ref': {'kind': 'symbol', 'id': 'symbol:caller'}}
    facts = {
        'resources': {'resource:ts': {'id': 'resource:ts', 'kind': 'repository_file',
                                      'name': 'src/view.ts', 'language': 'typescript'}},
        'symbols': {'symbol:caller': {'id': 'symbol:caller', 'file': 'src/view.ts'}},
        'anchors': {},
        'traces': {},
        'trace_obligations': {item['id']: item for item in (
            obligation('a', 'edge:shared'), obligation('b', 'edge:shared'),
            obligation('c', 'edge:shared'), obligation('a', 'edge:own'))},
    }
    calls = extraction_measurements(facts)['call_targets']
    # Every trace still counts its own obligation; a site counts once.
    assert (calls['unresolved'], calls['unresolved_sites']) == (4, 2)
    assert calls['unresolved_sites_by_language'] == {'typescript': 2}


def _render(tmp_path, payload):
    path = tmp_path / 'result.json'
    path.write_text(json.dumps({
        'artifact': '.speed/context/business-domain-facts.json', 'trace_blockers': [],
        'coverage': {'edges_resolved': 0, 'edges_unresolved': 0, 'edges_ambiguous': 0},
        'measurements': {'traces': {'total': 0, 'resolved': 0, 'ambiguous': 0, 'unresolved': 0}},
        **payload}))
    return subprocess.run(
        ['bash', '-c', f'source lib/cmd/domains.sh; _domains_render_facts "{path}"'],
        cwd=Path(__file__).parents[1], capture_output=True, text=True,
        check=True).stdout.splitlines()


def test_terminal_reports_call_sites_first_and_the_per_trace_count_beside_them(tmp_path):
    calls = {'unresolved': 342, 'unresolved_by_language': {'java': 199},
             'unresolved_sites': 182, 'unresolved_sites_by_language': {'java': 115, 'tsx': 59}}
    rendered = _render(tmp_path, {'measurements': {
        'traces': {'total': 0, 'resolved': 0, 'ambiguous': 0, 'unresolved': 0},
        'call_targets': calls}, 'warnings': []})
    assert ('Unresolved calls: 182 call sites on traces (java 115, tsx 59); '
            '342 counted once per trace') in rendered


def test_terminal_lists_one_warning_code_per_line_most_frequent_first(tmp_path):
    warnings = [{'code': 'B'}] * 2 + [{'code': 'A'}] * 2 + [{'code': 'C'}] * 5
    from lib.context.business_domain_cli import warning_counts
    rendered = _render(tmp_path, {'measurements': {
        'traces': {'total': 0, 'resolved': 0, 'ambiguous': 0, 'unresolved': 0},
        'call_targets': {'unresolved': 0, 'unresolved_by_language': {},
                         'unresolved_sites': 0, 'unresolved_sites_by_language': {}}},
        'warnings': warnings, 'warning_counts': warning_counts(warnings)})
    start = rendered.index('Warnings:        9')
    assert [line.split() for line in rendered[start + 1:start + 4]] == [
        ['C', '5'], ['A', '2'], ['B', '2']]


def test_measurement_command_is_json_and_does_not_publish_a_model(tmp_path):
    (tmp_path / 'checkout.html').write_text(
        '<form action="/orders" method="post">'
        '<button type="submit">Save</button></form>')
    result = subprocess.run(
        [sys.executable,
         str(Path(__file__).parents[1]
             / 'scripts/measure-business-domain-extraction.py'),
         '--repo', str(tmp_path)], cwd=tmp_path,
        capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    measured = json.loads(result.stdout)
    assert measured['ui_interactions'] == {
        'eligible_traces': 1, 'populated_traces': 1}
    assert not (tmp_path / '.speed/context/business-domains.json').exists()
    assert not (tmp_path / '.speed/context/repository-digest.json').exists()


# ── Entry points, screen actions and generated declarations ──────────────

def _anchor(anchor_id, kind, registration, resolution='resolved', path=None, reason=None):
    representations = [{'registration': registration}] if registration else []
    return {'id': anchor_id, 'kind': kind, 'symbol_id': 'symbol:s', 'resolution': resolution,
            'reason': reason, 'operation': {'path': path}, 'representations': representations}


SUMMARY_FACTS = {
    'symbols': {
        'symbol:s': {'id': 'symbol:s', 'kind': 'method', 'file': 'web/Login.cshtml',
                     'qualified_name': 'web/Login.cshtml::Login.default'},
        'symbol:t': {'id': 'symbol:t', 'kind': 'type',
                     'qualified_name': 'pom.xml::generated-model:com.ex.dto.PetDto'},
        'symbol:m': {'id': 'symbol:m', 'kind': 'method',
                     'qualified_name': 'pom.xml::generated-model:com.ex.dto.PetDto.getName()'},
        'symbol:c': {'id': 'symbol:c', 'kind': 'method', 'qualified_name': 'A.java::A.run()'},
    },
    'edges': {
        'edge:1': {'id': 'edge:1', 'kind': 'calls', 'resolution': 'resolved',
                   'to_ref': {'kind': 'symbol', 'id': 'symbol:m'}},
        'edge:2': {'id': 'edge:2', 'kind': 'calls', 'resolution': 'resolved',
                   'to_ref': {'kind': 'symbol', 'id': 'symbol:c'}},
    },
    'anchors': {
        'anchor:h': _anchor('anchor:h', 'http', {'kind': 'http_route'}),
        'anchor:t': _anchor('anchor:t', 'sql', {'kind': 'database_trigger'}, 'unresolved'),
        'anchor:c': _anchor('anchor:c', 'http', None),
        'anchor:a1': _anchor('anchor:a1', 'ui', {'kind': 'action', 'label': 'Add Owner'},
                             path='/owners/new'),
        'anchor:a2': _anchor('anchor:a2', 'ui', {
            'kind': 'action', 'label': None,
            'reason': "Visible action label on /e is one of 'Add Owner', 'Update Owner': runtime."},
            'ambiguous', path='/e'),
        'anchor:a3': _anchor('anchor:a3', 'ui', {
            'kind': 'action', 'label': 'Login',
            'reason': 'Form submission action is not statically determined; identity keeps the form location.'},
            'unresolved'),
        'anchor:a4': _anchor('anchor:a4', 'ui', {'kind': 'action', 'label': None,
                             'reason': 'The label is a runtime value.'}, 'unresolved', path='/notes'),
    },
}


def test_entry_points_are_counted_by_declared_kind():
    from lib.context.business_domain_cli import entry_point_counts
    assert entry_point_counts(SUMMARY_FACTS) == [
        {'kind': 'action', 'resolved': 1, 'total': 4},
        {'kind': 'database_trigger', 'resolved': 0, 'total': 1},
        {'kind': 'http', 'resolved': 1, 'total': 1},
        {'kind': 'http_route', 'resolved': 1, 'total': 1}]


def test_each_screen_action_states_its_label_or_why_it_has_none():
    from lib.context.business_domain_cli import screen_actions
    by_route = {item['route']: item for item in screen_actions(SUMMARY_FACTS)}
    assert by_route['/owners/new']['state'] == 'labeled'
    assert (by_route['/e']['state'], by_route['/e']['candidates']) == (
        'ambiguous', ['Add Owner', 'Update Owner'])
    # No route: the declaring file stands in, and the label is kept with its reason.
    assert by_route['web/Login.cshtml']['state'] == 'labeled_unresolved'
    assert by_route['web/Login.cshtml']['reason'] == 'Form submission action is not statically determined'
    assert (by_route['/notes']['state'], by_route['/notes']['reason']) == (
        'unlabeled', 'The label is a runtime value')


def test_generated_declarations_count_types_members_and_calls_into_them():
    from lib.context.business_domain_cli import generated_declarations
    assert generated_declarations(SUMMARY_FACTS) == [
        {'kind': 'model', 'types': 1, 'members': 1, 'calls': 1}]


def test_terminal_renders_entry_points_screen_actions_and_generated_declarations(tmp_path):
    from lib.context.business_domain_cli import (
        entry_point_counts, generated_declarations, screen_actions)
    rendered = _render(tmp_path, {
        'measurements': {'traces': {'total': 0, 'resolved': 0, 'ambiguous': 0, 'unresolved': 0,
                                    'complete': 0, 'bounded': 0, 'incomplete': 0},
                         'call_targets': {'unresolved': 0, 'unresolved_by_language': {},
                                          'unresolved_sites': 0, 'unresolved_sites_by_language': {}}},
        'warnings': [], 'entry_points': entry_point_counts(SUMMARY_FACTS),
        'screen_actions': screen_actions(SUMMARY_FACTS),
        'generated_declarations': generated_declarations(SUMMARY_FACTS)})
    assert ('Entry points:    7 (action 1/4, database_trigger 0/1, http 1/1, '
            'http_route 1/1 resolved)') in rendered
    start = rendered.index('Screen actions:')
    rows = [' '.join(line.split()) for line in rendered[start + 1:start + 5]]
    assert rows == [
        "/e ambiguous: 'Add Owner' or 'Update Owner'",
        '/notes unlabeled: The label is a runtime value',
        '/owners/new Add Owner',
        'web/Login.cshtml Login (unresolved: Form submission action is not statically determined)']
    assert '  model: 1 type, 1 member; 1 call resolves to them' in rendered


def test_open_relationships_are_attributed_by_language_boundary_and_trace():
    facts = {
        'resources': {'resource:a': {'id': 'resource:a', 'kind': 'repository_file',
                                     'name': 'a.sql', 'language': 'sql'},
                      'resource:b': {'id': 'resource:b', 'kind': 'repository_file',
                                     'name': 'b.cs', 'language': 'c_sharp'}},
        'symbols': {'symbol:a': {'id': 'symbol:a', 'file': 'a.sql'},
                    'symbol:b': {'id': 'symbol:b', 'file': 'b.cs'}},
        'anchors': {}, 'trace_obligations': {},
        'traces': {'trace:t': {'id': 'trace:t', 'anchor_id': 'anchor:x', 'resolution': 'unresolved',
                               'edge_ids': ['edge:write', 'edge:gap']}},
        'edges': {
            'edge:write': {'id': 'edge:write', 'resolution': 'unresolved',
                           'from_ref': {'kind': 'symbol', 'id': 'symbol:a'}},
            'edge:gap': {'id': 'edge:gap', 'resolution': 'unresolved',
                         'from_ref': {'kind': 'symbol', 'id': 'symbol:a'}},
            'edge:cs': {'id': 'edge:cs', 'resolution': 'unresolved',
                        'from_ref': {'kind': 'symbol', 'id': 'symbol:b'}},
            'edge:ok': {'id': 'edge:ok', 'resolution': 'resolved',
                        'from_ref': {'kind': 'symbol', 'id': 'symbol:a'}}},
        'warnings': [{'code': 'SQL_COMPLETION_UNRESOLVED', 'subject_ids': ['edge:write']},
                     {'code': 'SQL_DYNAMIC_TABLE', 'subject_ids': ['edge:gap']}],
    }
    assert extraction_measurements(facts)['relationships'] == {
        'open': 3, 'open_by_language': {'sql': 2, 'c_sharp': 1},
        'open_at_boundaries': 1, 'open_outside_traces': 1}


def test_boundary_warning_codes_are_marked():
    from lib.context.business_domain_cli import warning_counts
    counts = {item['code']: item['boundary'] for item in warning_counts(
        [{'code': 'SQL_COMPLETION_UNRESOLVED'}, {'code': 'SQL_DYNAMIC_TABLE'}])}
    assert counts == {'SQL_COMPLETION_UNRESOLVED': True, 'SQL_DYNAMIC_TABLE': False}


def test_a_call_into_a_catalogued_platform_counts_as_a_boundary():
    facts = {
        'resources': {'resource:f': {'id': 'resource:f', 'kind': 'repository_file',
                                     'name': 'a.sql', 'language': 'sql'},
                      'resource:p': {'id': 'resource:p', 'kind': 'service', 'language': 'sql',
                                     'provider': 'module:supabase/postgres'},
                      'resource:u': {'id': 'resource:u', 'kind': 'service', 'language': 'sql',
                                     'provider': 'module:unknown-vendor'}},
        'symbols': {'symbol:a': {'id': 'symbol:a', 'file': 'a.sql'}},
        'anchors': {}, 'trace_obligations': {}, 'traces': {}, 'warnings': [],
        'edges': {
            'edge:p': {'id': 'edge:p', 'resolution': 'unresolved',
                       'from_ref': {'kind': 'symbol', 'id': 'symbol:a'},
                       'to_ref': {'kind': 'resource', 'id': 'resource:p'}},
            'edge:u': {'id': 'edge:u', 'resolution': 'unresolved',
                       'from_ref': {'kind': 'symbol', 'id': 'symbol:a'},
                       'to_ref': {'kind': 'resource', 'id': 'resource:u'}}},
    }
    assert extraction_measurements(facts)['relationships']['open_at_boundaries'] == 1
