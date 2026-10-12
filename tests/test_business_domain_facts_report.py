"""The --facts-only report and the terminal summary rendered from it.

The report counts what the facts record and never reclassifies: every call
site on a trace is in this repository, at a named platform or library, or
open, and the parts add up to the whole.
"""
import json
import subprocess
from pathlib import Path

from lib.context.business_domain_cli import facts_only, facts_report

SPEED_ROOT = Path(__file__).parents[1]

LIBRARY = {
    'src/ledger.ts': '''export class Ledger {
  readonly entries: number[] = [];

  post(amount: number): number {
    this.entries.push(amount);
    return this.total();
  }

  total(): number {
    return this.entries.reduce((sum, value) => sum + value, 0);
  }
}
''',
    'src/loose.ts': '''export class Loose {
  trim(value: any): string {
    return value.trim();
  }
}
''',
    'corpus/golden.json': '{"cases": []}\n',
}


def _write(root, files):
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


def _result(tmp_path, files=LIBRARY):
    result, code = facts_only(_write(tmp_path, files))
    assert code == 0
    facts = json.loads((tmp_path / result['artifact']).read_text())
    return result, facts


def _render(tmp_path, result, env=None):
    payload = tmp_path / 'result.json'
    payload.write_text(json.dumps(result))
    return subprocess.run(
        ['bash', '-c', f'source lib/cmd/domains.sh; _domains_render_facts "{payload}"'],
        cwd=SPEED_ROOT, capture_output=True, text=True, check=True, env=env).stdout


def test_call_sites_on_traces_add_up_and_name_their_providers(tmp_path):
    result, facts = _result(tmp_path)
    calls = result['report']['calls']

    assert calls['sites'] == (calls['repository'] + calls['platform'] + calls['library']
                              + calls['ambiguous'] + calls['open'])
    assert calls['repository'] >= 1          # post -> total
    data = result['report']['data']
    assert (data['stores'], data['in_memory']) == (1, True)
    assert data['top'] == [{'name': 'Ledger.entries', 'kind': 'memory_store',
                            'reads': 1, 'writes': 1}]
    assert result['report'] == facts_report(facts, tmp_path, result['report']['elapsed_ms'])


def test_an_open_call_site_is_listed_with_its_source_line(tmp_path):
    result, _ = _result(tmp_path)
    report = result['report']

    assert report['calls']['open'] == 1
    assert report['open_sites'] == [{'path': 'src/loose.ts', 'line': 3, 'excerpt': 'value.trim()',
                                     'state': 'open',
                                     'reason': 'Call target trim: 0 source candidates'}]
    assert report['traces']['incomplete'] == 1


def test_unanalyzed_files_say_what_was_lost(tmp_path):
    result, _ = _result(tmp_path)

    assert result['report']['unanalyzed'] == {
        'files': 1, 'facts_lost': 0, 'languages': ['JSON'], 'causes': ['owner_not_installed'],
        'paths': ['corpus/golden.json'], 'more': 0}


def test_relationship_parts_add_up_to_the_unresolved_total(tmp_path):
    result, _ = _result(tmp_path)
    relationships = result['report']['relationships']

    assert relationships['open'] == (relationships['outside_traces']
                                     + relationships['on_traces_at_boundaries']
                                     + relationships['on_traces_open'])


def test_summary_leads_with_the_traced_count_and_lists_open_sites(tmp_path):
    result, _ = _result(tmp_path)

    rendered = _render(tmp_path, result).splitlines()

    assert rendered[0] == f'  {tmp_path.name}'
    assert '  ▲ 2 of 3 entry points traced to a known end · 1 stops at an open call' in rendered
    assert any(line.split() == ['unresolved', '1', 'calls', 'with', 'no', 'known', 'target']
               for line in rendered)
    assert any(line.split()[:2] == ['src/loose.ts:3', 'value.trim()'] for line in rendered)
    assert '  Not analysed      1 file (JSON): no analyser installed · no facts lost' in rendered
    assert rendered[-2:] == ['Facts written to:', result['artifact']]


def test_summary_states_success_when_every_entry_point_ends(tmp_path):
    files = {path: text for path, text in LIBRARY.items() if path != 'src/loose.ts'}
    result, _ = _result(tmp_path, files)

    rendered = _render(tmp_path, result).splitlines()

    assert '  ✓ All 2 entry points were traced to a known end' in rendered
    assert any(line.split()[:2] == ['unresolved', '0'] and 'every call on a trace has a known target'
               in line for line in rendered)


def test_summary_has_no_escape_codes_without_a_terminal(tmp_path):
    result, _ = _result(tmp_path)

    assert '\x1b[' not in _render(tmp_path, result)
