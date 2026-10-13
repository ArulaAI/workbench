"""What a provider call reports, and how it ends when discovery stops.

A provider that reports its token usage is charged what each request used,
not the full allowance reserved for it. A discovery told to stop ends every
provider call it started, in every thread, and kills its process group, so no
provider keeps running after the process that would read its answer is gone.
"""
import json
import os
import subprocess
import threading
import time

import pytest

from lib.context import business_domain_synthesis as synthesis_module
from lib.context.business_domain_schema import DomainError, settings
from lib.context.business_domain_synthesis import Synthesis, _reported_usage, request_shutdown
from tests.business_domains.provider_fixture import PassingProvider


@pytest.fixture
def synthesis(tmp_path):
    counters = {key: 0 for key in (
        'input_tokens_reserved', 'completion_input_tokens_reserved',
        'completion_output_tokens_reserved', 'semantic_units_active')}
    counters.update(input_tokens_reported=None, output_tokens_reported=None)
    instance = Synthesis(tmp_path, settings({}), PassingProvider(), counters)
    yield instance
    synthesis_module.SHUTDOWN.clear()


def test_reported_usage_reads_only_valid_token_counts(tmp_path):
    path = tmp_path / 'usage.json'
    path.write_text(json.dumps({'inputTokens': 1200, 'outputTokens': -1, 'other': 3}))

    assert _reported_usage(path) == {'inputTokens': 1200}
    assert _reported_usage(tmp_path / 'missing.json') == {}
    path.write_text('not json')
    assert _reported_usage(path) == {}


def test_an_agent_call_returns_the_usage_its_provider_reported(synthesis, monkeypatch):
    seen = {}

    def call(action, *args, timeout=30, env=None):
        seen['env'] = env
        with open(env['SPEED_PROVIDER_USAGE_FILE'], 'w') as stream:
            json.dump({'inputTokens': 4321, 'outputTokens': 987}, stream)
        return {'verdict': 'pass'}

    monkeypatch.setattr(synthesis, '_speed_call', call)
    synthesis.agent_config = {'agent_timeout': 60, 'kill_grace': 1}

    value, usage = synthesis._run_agent({'model': 'opus'}, {}, 30, 'verification')

    assert value == {'verdict': 'pass'}
    assert usage == {'last': {'inputTokens': 4321, 'outputTokens': 987}}
    assert 'SPEED_PROVIDER_USAGE_FILE' in seen['env']


def test_an_agent_call_without_reported_usage_keeps_its_reservation(synthesis, monkeypatch):
    monkeypatch.setattr(synthesis, '_speed_call',
                        lambda action, *args, timeout=30, env=None: {'verdict': 'pass'})
    synthesis.agent_config = {'agent_timeout': 60, 'kill_grace': 1}

    _, usage = synthesis._run_agent({'model': 'opus'}, {}, 30, 'verification')

    assert usage == {}


def test_a_shutdown_request_cancels_every_synthesis(synthesis):
    assert not synthesis.is_cancelled()

    request_shutdown()

    assert synthesis.is_cancelled()


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_shutdown_ends_every_process_the_provider_call_started(synthesis, monkeypatch, tmp_path):
    # A wrapper like `timeout` puts its child in a process group of its own,
    # out of reach of a signal to the call's group.
    marker = tmp_path / 'grandchild.pid'
    real_popen = subprocess.Popen
    started = {}

    def popen(command, **kwargs):
        if command[0] != 'bash':
            return real_popen(command, **kwargs)
        script = (f'perl -e \'setpgrp(0,0); print "$$"; exec "sleep", "30"\' > {marker} & '
                  'wait')
        process = real_popen(['/bin/bash', '-c', script], start_new_session=True,
                             stdout=kwargs['stdout'], stderr=kwargs['stderr'])
        started['pid'] = process.pid
        return process

    monkeypatch.setattr(subprocess, 'Popen', popen)
    threading.Timer(1.0, request_shutdown).start()
    began = time.monotonic()

    with pytest.raises(DomainError) as raised:
        synthesis._speed_call_unlogged('agent', timeout=30)

    grandchild = int(marker.read_text().strip())
    assert raised.value.code == 'CANCELLED'
    assert time.monotonic() - began < 8
    deadline = time.monotonic() + 3
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _alive(started['pid']) and not _alive(grandchild)


def test_the_cli_turns_a_termination_signal_into_a_shutdown(monkeypatch):
    from lib.context import business_domain_cli

    with pytest.raises(KeyboardInterrupt):
        business_domain_cli._stop(15, None)

    assert synthesis_module.SHUTDOWN.is_set()
    synthesis_module.SHUTDOWN.clear()


class _ReportingProvider(PassingProvider):
    """Report a fixed usage with every response."""

    def __init__(self, usage):
        super().__init__()
        self.usage = usage

    def generate(self, request, schema, *rest):
        value, _ = super().generate(request, schema, *rest)
        return value, {'last': dict(self.usage)}


def _discover_with(tmp_path, usage):
    from lib.context.business_domains import discover
    from tests.business_domains.provider_fixture import write_service
    write_service(tmp_path)
    return discover(tmp_path, provider=_ReportingProvider(usage))


def test_a_request_is_charged_its_total_and_bounded_by_its_largest_turn(tmp_path):
    # Three turns of 5,000 output tokens: 15,000 spent, each turn within the
    # 8,000-token request allowance.
    model, status = _discover_with(tmp_path, {
        'inputTokens': 30_000, 'outputTokens': 15_000,
        'peakInputTokens': 10_000, 'peakOutputTokens': 5_000})

    assert model is not None
    assert status['limits']['output_tokens_reported'] == 15_000 * 2


def test_a_turn_beyond_the_request_allowance_is_refused(tmp_path):
    model, status = _discover_with(tmp_path, {
        'inputTokens': 10_000, 'outputTokens': 9_000,
        'peakInputTokens': 10_000, 'peakOutputTokens': 9_000})

    assert model is None
    assert status['error']['code'] in {'PROVIDER_BUDGET', 'PROVIDER_UNAVAILABLE'}


def test_call_timeouts_do_not_change_the_provider_fingerprint(tmp_path, monkeypatch):
    configs = []

    def config(self, action, *args, timeout=30, env=None):
        return dict(configs[-1])

    base = {'provider': 'claude-code', 'model': 'opus', 'planning_model': 'opus',
            'agent_file': '', 'agent_timeout': 2400, 'kill_grace': 10,
            'provider_context_tokens': 1_000_000, 'provider_max_output_tokens': 128_000,
            'output_limit_enforcement': 'provider',
            'models': {'opus': {'provider_context_tokens': 1_000_000,
                                'provider_max_output_tokens': 128_000,
                                'output_limit_enforcement': 'provider'}}}
    monkeypatch.setattr(Synthesis, '_speed_call', config)
    hashes = []
    for timeout in (2400, 3600):
        configs.append({**base, 'agent_timeout': timeout})
        hashes.append(Synthesis(tmp_path, settings({}), None, {}).provider_hash)
    configs.append({**base, 'model': 'sonnet', 'planning_model': 'sonnet'})
    other = Synthesis(tmp_path, settings({}), None, {}).provider_hash

    assert hashes[0] == hashes[1]
    assert other != hashes[0]
