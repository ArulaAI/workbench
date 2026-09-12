import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from lib.context.business_domain_schema import DEFAULTS, DomainError, digest, limits, record
from lib.context.business_domain_synthesis import Synthesis


def provider_error(message='Transport failed', diagnostic_log=None, *,
                   category='transport_unavailable', native_status='ECONNRESET',
                   retryable=True):
    failure = {'schema_version': 1, 'category': category, 'scope': 'provider',
               'retryable': retryable, 'native_status': native_status,
               'message': message, 'diagnostic_log': diagnostic_log}
    code = 'PROVIDER_FAILED' if retryable else 'PROVIDER_UNAVAILABLE'
    return DomainError(code, message, retryable=retryable, provider_failure=failure)


class EmptyProvider:
    model = 'fixture'

    def generate(self, *args):
        return {key: [] for key in record('ActivityPayload')}, {}


def packet(name):
    return record('ActivityPacket', input_fingerprint=digest(name), anchor_ids=[name])


def test_normalized_failure_signature_opens_once_and_ignores_variable_diagnostics(
        tmp_path, monkeypatch):
    synthesis = Synthesis(tmp_path, DEFAULTS, EmptyProvider(), limits(DEFAULTS))
    failures = [
        provider_error('failure at 10:01', '.speed/logs/first.log'),
        provider_error('failure at 10:02', '.speed/logs/second.log'),
    ]
    attempts = []

    def fail(*args):
        attempts.append(True)
        raise failures[len(attempts) - 1]

    monkeypatch.setattr(synthesis, '_run_once', fail)
    with pytest.raises(DomainError) as error:
        synthesis.run({})
    assert error.value.code == 'PROVIDER_UNAVAILABLE'
    assert 'repeated equivalent provider failure' in str(error.value)
    assert error.value.retryable is False
    # Preserve the adapter's native/request policy in the nested envelope;
    # only the exhausted build-level error becomes non-retryable.
    assert error.value.provider_failure['retryable'] is True
    assert synthesis.provider_open_signature == (
        synthesis.provider_hash, 'transport_unavailable', 'ECONNRESET')
    assert len(attempts) == 2 and synthesis.counters['retries'] == 1

    with pytest.raises(DomainError) as repeated:
        synthesis.run({})
    assert repeated.value is synthesis.provider_failure
    assert len(attempts) == 2


def test_nonretryable_provider_failure_opens_initial_gate_without_retry(
        tmp_path, monkeypatch):
    synthesis = Synthesis(tmp_path, DEFAULTS, EmptyProvider(), limits(DEFAULTS))
    attempts = []

    def denied(*args):
        attempts.append(True)
        raise provider_error('Access denied', category='authorization_denied',
                             native_status='403', retryable=False)

    monkeypatch.setattr(synthesis, '_run_once', denied)
    with pytest.raises(DomainError) as error:
        synthesis.run({})
    assert error.value.code == 'PROVIDER_UNAVAILABLE'
    assert error.value.provider_failure['category'] == 'authorization_denied'
    assert error.value.provider_failure['native_status'] == '403'
    assert attempts == [True]
    assert synthesis.counters['retries'] == 0


def test_previously_healthy_provider_confirms_nonretryable_failure_once(
        tmp_path, monkeypatch):
    synthesis = Synthesis(tmp_path, DEFAULTS, EmptyProvider(), limits(DEFAULTS))
    synthesis.provider_generation = 1
    synthesis.provider_healthy = True
    failures = [
        provider_error('403 at 10:01', '.speed/logs/first-403.log',
                       category='authorization_denied', native_status='403',
                       retryable=False),
        provider_error('403 at 10:02', '.speed/logs/second-403.log',
                       category='authorization_denied', native_status='403',
                       retryable=False),
    ]
    attempts = []

    def denied(*args):
        attempts.append(True)
        raise failures[len(attempts) - 1]

    monkeypatch.setattr(synthesis, '_run_once', denied)
    with pytest.raises(DomainError) as error:
        synthesis.run({})
    assert error.value.code == 'PROVIDER_UNAVAILABLE'
    assert 'repeated equivalent provider failure' in str(error.value)
    assert error.value.provider_failure['category'] == 'authorization_denied'
    assert attempts == [True, True]
    assert synthesis.counters['retries'] == 1


def test_request_scoped_invalid_response_repairs_without_opening_circuit(
        tmp_path, monkeypatch):
    synthesis = Synthesis(tmp_path, DEFAULTS, EmptyProvider(), limits(DEFAULTS))
    attempts = []
    failure = {'schema_version': 1, 'category': 'response_invalid',
               'scope': 'request', 'retryable': False, 'native_status': None,
               'message': 'Malformed response', 'diagnostic_log': None}

    def repair(*args):
        attempts.append(True)
        if len(attempts) == 1:
            raise DomainError('INVALID_PROVIDER_OUTPUT', failure['message'],
                              provider_failure=failure)
        return {'accepted': True}

    monkeypatch.setattr(synthesis, '_run_once', repair)
    assert synthesis.run({}) == {'accepted': True}
    assert attempts == [True, True]
    assert synthesis.counters['retries'] == 1
    assert synthesis.provider_failure is None
    assert not synthesis.stopping.is_set()


def test_provider_failure_during_schema_repair_propagates_through_same_circuit(
        tmp_path):
    class RepairFailureProvider(EmptyProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, *args):
            self.calls += 1
            if self.calls == 1:
                return {}, {}  # Transport succeeded; request payload is invalid.
            raise provider_error('Access denied during repair',
                                 category='authorization_denied',
                                 native_status='403', retryable=False)

    provider = RepairFailureProvider()
    synthesis = Synthesis(tmp_path, DEFAULTS, provider, limits(DEFAULTS))
    with pytest.raises(DomainError) as error:
        synthesis.run(packet('repair'))
    assert error.value.code == 'PROVIDER_UNAVAILABLE'
    assert error.value.provider_failure['category'] == 'authorization_denied'
    assert provider.calls == 3  # Invalid response, repair attempt, confirmation.
    assert synthesis.counters['requests'] == 3
    assert synthesis.counters['retries'] == 2
    assert not [path for path in
        (tmp_path / '.speed/context/business-domain-cache').glob('*.json')
        if not path.name.startswith('pending-')]


def test_waiter_deadline_retains_the_active_provider_recovery_cause(tmp_path):
    synthesis = Synthesis(tmp_path, DEFAULTS, EmptyProvider(), limits(DEFAULTS))
    cause = provider_error()
    with synthesis.provider_gate:
        synthesis.provider_probe_owner = -1
        synthesis.provider_recovery_cause = cause
        synthesis.provider_recovery_signature = synthesis._provider_failure_signature(cause)
    synthesis.deadline = time.monotonic() - 1

    with pytest.raises(DomainError) as error:
        synthesis._await_provider_gate()
    assert error.value.code == 'PROVIDER_UNAVAILABLE'
    assert error.value.provider_failure['category'] == 'transport_unavailable'
    assert error.value.retryable is False
    assert synthesis.counters['requests'] == 0
    assert synthesis.counters['input_tokens_reserved'] == 0
    assert synthesis.output_reserved == 0


def test_late_failure_from_recovered_generation_does_not_close_a_second_gate(tmp_path):
    late_started = threading.Event()
    release_late = threading.Event()
    recovery_started = threading.Event()
    release_recovery = threading.Event()
    late_replay_started = threading.Event()
    release_late_replay = threading.Event()
    fresh_dispatched = threading.Event()
    lock = threading.Lock()
    calls = {}

    class ConcurrentProvider(EmptyProvider):
        def generate(self, request, *args):
            name = request['packet']['anchor_ids'][0]
            with lock:
                calls[name] = calls.get(name, 0) + 1
                attempt = calls[name]
            if name == 'late' and attempt == 1:
                late_started.set()
                assert release_late.wait(5)
                raise provider_error('Failure from the old health generation')
            if name == 'recovery' and attempt == 1:
                raise provider_error('Failure that owns recovery')
            if name == 'recovery' and attempt == 2:
                recovery_started.set()
                assert release_recovery.wait(5)
            if name == 'late' and attempt == 2:
                late_replay_started.set()
                assert release_late_replay.wait(5)
            if name == 'fresh':
                fresh_dispatched.set()
            return super().generate(request, *args)

    # This health-gate schedule intentionally dispatches six maximum-output
    # reservations; isolate it from the RFC default four-request build budget.
    config = {**DEFAULTS, 'max_build_output_tokens':1_000_000}
    synthesis = Synthesis(tmp_path, config, ConcurrentProvider(), limits(config))
    assert synthesis.run(packet('warm')) == record('ActivityPayload')
    assert synthesis.provider_generation == 1

    with ThreadPoolExecutor(max_workers=3) as executor:
        late = executor.submit(synthesis.run, packet('late'))
        assert late_started.wait(5)
        recovery = executor.submit(synthesis.run, packet('recovery'))
        assert recovery_started.wait(5)
        release_recovery.set()
        assert recovery.result(timeout=5) == record('ActivityPayload')
        assert synthesis.provider_generation == 2

        release_late.set()
        assert late_replay_started.wait(5)
        fresh = executor.submit(synthesis.run, packet('fresh'))
        try:
            assert fresh_dispatched.wait(2), 'A stale failure closed a second recovery gate'
        finally:
            release_late_replay.set()
        assert late.result(timeout=5) == record('ActivityPayload')
        assert fresh.result(timeout=5) == record('ActivityPayload')

    assert synthesis.provider_healthy
    assert synthesis.provider_probe_owner is None
    assert synthesis.provider_generation == 2
    assert calls == {'warm': 1, 'late': 2, 'recovery': 2, 'fresh': 1}
