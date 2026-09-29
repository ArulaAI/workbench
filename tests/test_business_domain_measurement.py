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
        'traces': {'total': 1, 'resolved': 0, 'ambiguous': 0, 'unresolved': 1},
        'call_targets': {'unresolved': 1,
                         'unresolved_by_language': {'typescript': 1}},
        'ui_interactions': {'eligible_traces': 1, 'populated_traces': 1},
    }


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
