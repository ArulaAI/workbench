"""Exercise Repository Digest through the normal command dispatcher."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lib.context.repository_digest import build_repository_digest
from tests.test_business_domain_provider import fixture_cli
from tests.test_repository_digest import minimal_repo


@pytest.mark.parametrize('json_output', [False, True])
@pytest.mark.parametrize('has_digest', [False, True])
@pytest.mark.parametrize('refresh', [None, '--refresh', '--rebuild-discovery'])
def test_digest_cli_output_and_failed_refresh(
        tmp_path, monkeypatch, json_output, has_digest, refresh):
    invocation = fixture_cli(tmp_path, monkeypatch, 'codex-cli')
    if has_digest:
        minimal_repo(tmp_path)
        digest = build_repository_digest(str(tmp_path), config={})
        artifact = tmp_path / '.speed/context/repository-digest.json'
        original = artifact.read_bytes()
    if refresh:
        # Reject refresh before discovery or provider execution begins.
        (tmp_path / 'speed.toml').write_text(
            '[business_domains]\ndeadline_seconds = 0\n')

    args = ['bash', str(Path(__file__).resolve().parents[1] / 'speed'), 'digest']
    if refresh:
        args.append(refresh)
    if json_output:
        args.append('--json')
    result = subprocess.run(
        args, cwd=tmp_path,
        env={**os.environ, 'SPEED_PROJECT_ROOT': str(tmp_path),
             'SPEED_PYTHON': sys.executable, 'LC_ALL': 'C'},
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )

    assert result.returncode == (3 if refresh or not has_digest else 0), result.stderr
    assert not invocation.exists()
    if has_digest:
        assert artifact.read_bytes() == original
        if json_output:
            assert json.loads(result.stdout)['identity'] == digest['identity']
        else:
            assert result.stdout.startswith('# Repository Digest:')
            assert digest['identity']['name'] in result.stdout
            assert len(result.stdout) <= 16_000
    else:
        assert result.stdout == ''
        assert 'digest' in result.stderr.lower()
    if refresh:
        assert 'Digest build failed:' in result.stderr
        assert 'deadline_seconds' in result.stderr
    assert '__SPEED_DISCOVERY_EVENT__' not in result.stdout + result.stderr

def test_digest_escalation_progress_stays_off_json_stdout(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = r'''
source "$1/lib/config.sh"
source "$1/lib/log.sh"
source "$1/lib/cleanup.sh"
source "$1/lib/cmd/digest.sh"
trap cleanup_all EXIT
JSON_OUTPUT=true
digest_build() {
    printf '%s\n' '__SPEED_DISCOVERY_EVENT__{"level":"warning","message":"Timeout on support; escalating to planning"}' >&2
    printf '%s\n' '{"ok":true,"outcome":"complete","warnings":[]}'
}
digest_status() {
    printf '%s\n' '{"load_status":"ok","digest":{"identity":{"name":"fixture"}}}'
}
cmd_digest --refresh
'''
    result = subprocess.run(
        ['bash', '-c', script, 'test', str(root)],
        cwd=tmp_path,
        env={**os.environ, 'SPEED_PROJECT_ROOT': str(tmp_path),
             'TMPDIR': str(tmp_path)},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'identity': {'name': 'fixture'}}
    assert 'escalating to planning' in result.stderr
    assert '__SPEED_DISCOVERY_EVENT__' not in result.stdout + result.stderr
    assert not list(tmp_path.glob('tmp.*'))
