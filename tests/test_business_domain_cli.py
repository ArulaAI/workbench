"""`speed discover domains` modes that never invoke a provider."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lib.context.business_domain_cli import EVENT_PREFIX, main

SPEED_ROOT = Path(__file__).parents[1]
CONTROLLER = '''
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.GetMapping;
@RestController class Controller {
  @GetMapping("/leaf") public void leaf() {}
}
'''


def run(root, *flags):
    return subprocess.run(
        [sys.executable, '-m', 'lib.context.business_domain_cli',
         '--root', str(root), *flags],
        cwd=SPEED_ROOT, capture_output=True, text=True, timeout=60)


def test_facts_only_writes_facts_and_never_publishes(tmp_path):
    (tmp_path/'Controller.java').write_text(CONTROLLER)

    result = run(tmp_path, '--facts-only')

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output['ok'] and output['mode'] == 'facts'
    assert output['measurements']['traces']['total'] == 1
    assert output['artifact'] == '.speed/context/business-domain-facts.json'
    assert (tmp_path/output['artifact']).is_file()
    assert not (tmp_path/'.speed/context/business-domains.json').exists()
    assert not (tmp_path/'.speed/context/business-domain-status.json').exists()
    assert any(line.startswith(EVENT_PREFIX) for line in result.stderr.splitlines())


def test_status_before_any_run_reports_nothing_published(tmp_path, capsys):
    assert main(['--root', str(tmp_path), '--status']) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {'mode': 'status', 'ok': True, 'published': False,
                      'published_build_id': None, 'status': None}


def test_cancel_without_a_build_is_a_domain_error(tmp_path, capsys):
    assert main(['--root', str(tmp_path), '--cancel']) == 1

    output = json.loads(capsys.readouterr().out)
    assert output['ok'] is False
    assert output['error']['code'] == 'BUILD_NOT_RUNNING'


@pytest.mark.parametrize('flag', ['--facts-only', '--status', '--cancel'])
def test_missing_root_is_a_configuration_error(tmp_path, capsys, flag):
    assert main(['--root', str(tmp_path/'missing'), flag]) == 3

    output = json.loads(capsys.readouterr().out)
    assert output['error']['code'] == 'INVALID_ROOT'


def test_modes_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit):
        main(['--root', str(tmp_path), '--status', '--cancel'])
