"""Discovery calls the existing SPEED invoker using local CLI fixtures."""
import ast
import copy
import time
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
import pytest

from lib.context.business_domain_schema import DEFAULTS, DomainError, limits, validate
from lib.context.business_domain_synthesis import Synthesis
from tests.test_business_domain_candidate_protocol import graph_scope

SCHEMA = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}


def test_business_domain_orchestration_has_no_technology_or_provider_name_branches():
    forbidden = {'codex','codex-cli','openai','claude','claude-code','anthropic',
                 'java','javascript','typescript','spring','oracle','postgres','postgresql'}
    root = Path(__file__).parents[1]
    for relative in ('lib/context/business_domain_synthesis.py',
                     'lib/context/business_domains.py',
                     'lib/context/business_domain_execution.py'):
        tree = ast.parse((root/relative).read_text(encoding='utf-8'))
        branches = [node.test for node in ast.walk(tree)
                    if isinstance(node,(ast.If,ast.IfExp,ast.While))]
        branches.extend(node.subject for node in ast.walk(tree) if isinstance(node,ast.Match))
        for branch in branches:
            literals = {value.value.lower() for value in ast.walk(branch)
                        if isinstance(value,ast.Constant) and isinstance(value.value,str)}
            assert not literals & forbidden, f'{relative} branches on {literals & forbidden}'
        imports = [node for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom))]
        assert not any(
            (isinstance(node,ast.ImportFrom) and
             (node.module == 'providers' or (node.module or '').startswith('providers.'))) or
            (isinstance(node,ast.Import) and any(
                alias.name == 'providers' or alias.name.startswith('providers.') for alias in node.names))
            for node in imports), relative


def test_legacy_error_record_without_provider_envelope_remains_valid():
    validate({'code':'BUILD_TIMEOUT','message':'legacy status','field':None,
              'retryable':False},'Error')


def fixture_cli(tmp_path, monkeypatch, provider, behavior='ok', model='fixture-model'):
    executable = tmp_path/'fixture-cli'
    log = tmp_path/'invocation.json'
    executable.write_text('#!'+sys.executable+'\n'+f'''
import json,sys,time
from pathlib import Path
args=sys.argv[1:]
behavior={behavior!r}
stdin_text=sys.stdin.read()
invocation=(
 {{'args':args,'stdin_length':len(stdin_text),'stdin_tail':stdin_text[-64:]}}
 if behavior=='capture_stdin' else args)
Path({str(log)!r}).write_text(json.dumps(invocation))
reply = '{{"ok":true}}'
if behavior == 'scripted':
 with Path({str(log.with_suffix('.jsonl'))!r}).open('a') as history:
  history.write(json.dumps(invocation)+'\\n')
 response = json.loads(Path({str(tmp_path/'reply.json')!r}).read_text())
 if 'exit_code' in response:
  sys.exit(response['exit_code'])
 reply = json.dumps(response['payload'])
if behavior=='fail':
 print('fixture service failure (not authentication)',file=sys.stderr)
 sys.exit(1)
if behavior=='forbidden':
 print('HTTP error: 403 Forbidden token=do-not-copy',file=sys.stderr)
 sys.exit(1)
if behavior=='capability':
 print('selected model not available secret=do-not-copy',file=sys.stderr)
 sys.exit(1)
if behavior=='rate_limit':
 print('HTTP 429 rate limit api_key=do-not-copy',file=sys.stderr)
 sys.exit(1)
if behavior=='transport':
 print('response websocket connection failed credential=do-not-copy',file=sys.stderr)
 sys.exit(1)
if behavior=='wait':time.sleep(30)
if behavior=='incomplete':
 print(json.dumps({{'type':'assistant','message':'unfinished'}}))
 sys.exit(0)
if behavior=='invalid':
 if {provider!r}=='codex-cli':
  print(json.dumps({{'type':'item.completed','item':{{'type':'agent_message','text':'not-json'}}}}))
 else:
  print(json.dumps({{'type':'result','subtype':'success','result':'not-json','num_turns':1,'duration_ms':1}},separators=(',',':')))
 sys.exit(0)
if behavior=='input_limit':
 print(json.dumps({{'type':'result','subtype':'success','is_error':True,
                   'result':'Prompt is too long','num_turns':1,'duration_ms':1}},separators=(',',':')))
 sys.exit(0)
if {provider!r}=='codex-cli':
 print(json.dumps({{'type':'thread.started','thread_id':'fixture'}}))
 print(json.dumps({{'type':'item.completed','item':{{'type':'agent_message','text':reply}}}}))
 print(json.dumps({{'type':'turn.completed','usage':{{'input_tokens':10,'output_tokens':4}}}}))
else:
 print(json.dumps({{'type':'result','subtype':'success','result':reply,'num_turns':1,'duration_ms':1}},separators=(',',':')))
''')
    executable.chmod(0o700)
    monkeypatch.setenv('SPEED_PROVIDER',provider)
    monkeypatch.setenv('CODEX_BIN',str(executable))
    monkeypatch.setenv('CLAUDE_BIN',str(executable))
    monkeypatch.delenv('SPEED_SUPPORT_MODEL',raising=False)
    (tmp_path/'speed.toml').write_text(
        f'[agent]\nsupport_model = "{model}" # ordinary SPEED config\n')
    return log


@pytest.mark.parametrize('provider',['claude-code','codex-cli'])
def test_discovery_reuses_normal_speed_json_invoker(tmp_path,monkeypatch,provider):
    log = fixture_cli(tmp_path,monkeypatch,provider)
    synthesis = Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))
    value,usage = synthesis._run_agent({'model':synthesis.agent_config['model'],'packet':{'stage':'activity'},'instructions':'not duplicated'},SCHEMA,5,role='activity')
    assert value=={'ok':True} and usage=={}
    assert synthesis.agent_config['provider'] == provider
    assert synthesis.agent_config['model'] == 'fixture-model'
    assert synthesis.agent_config['agent_file'] == ''
    assert synthesis.agent_config['provider_context_tokens'] is None
    assert synthesis.agent_config['provider_max_output_tokens'] is None
    assert synthesis.agent_config['output_limit_enforcement'] == 'unknown'
    assert synthesis.agent_config['agent_timeout'] > 0
    assert synthesis.agent_config['kill_grace'] >= 0
    assert synthesis.agent_config['model'] in synthesis.agent_config['models']
    assert synthesis.agent_config['planning_model'] in synthesis.agent_config['models']
    args=json.loads(log.read_text())
    assert args[args.index('--model')+1]=='fixture-model'
    if provider=='claude-code':
        assert '-p' in args
        assert args[args.index('--output-format')+1]=='stream-json'
        assert args[args.index('--tools')+1]==''
        assert '--safe-mode' not in args and '--setting-sources' not in args
    else:
        assert args[0]=='exec' and '--output-schema' in args
        assert args[args.index('--sandbox')+1]=='read-only'
        assert 'app-server' not in args


def test_codex_large_structured_request_uses_stdin_not_argv(tmp_path,monkeypatch):
    log = fixture_cli(tmp_path,monkeypatch,'codex-cli','capture_stdin')
    synthesis = Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))
    payload = 'x' * 2_500_000

    value,usage = synthesis._run_agent(
        {'model':synthesis.agent_config['model'],'packet':{'stage':'activity','payload':payload},'instructions':'not duplicated'},
        SCHEMA,5,role='activity')

    assert value == {'ok':True} and usage == {}
    invocation = json.loads(log.read_text())
    assert invocation['args'][-1] == '-'
    assert payload not in invocation['args']
    assert invocation['stdin_length'] > 2_500_000
    assert invocation['stdin_tail'].endswith('"}}')


def test_codex_luna_capabilities_are_reported_by_adapter(tmp_path,monkeypatch):
    fixture_cli(tmp_path,monkeypatch,'codex-cli',model='gpt-5.6-luna')
    synthesis = Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))

    assert synthesis.agent_config['provider_context_tokens'] == 1_050_000
    assert synthesis.agent_config['provider_max_output_tokens'] == 128_000
    assert synthesis.agent_config['output_limit_enforcement'] == 'provider'


def test_normal_speed_model_override_is_respected(tmp_path,monkeypatch):
    fixture_cli(tmp_path,monkeypatch,'codex-cli')
    monkeypatch.setenv('SPEED_SUPPORT_MODEL','environment-model')
    synthesis=Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))
    assert synthesis.agent_config['model']=='environment-model'


@pytest.mark.parametrize(('model','context_tokens','output_tokens'),[
    ('sonnet',1_000_000,128_000),
    ('opus',1_000_000,128_000),
    ('haiku',200_000,64_000),
    ('claude-explicit-version',None,None),
])
def test_claude_adapter_owns_stable_alias_capabilities(
        tmp_path,monkeypatch,model,context_tokens,output_tokens):
    fixture_cli(tmp_path,monkeypatch,'claude-code',model=model)
    synthesis=Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))
    assert synthesis.agent_config['provider_context_tokens'] == context_tokens
    assert synthesis.agent_config['provider_max_output_tokens'] == output_tokens
    assert synthesis.agent_config['output_limit_enforcement'] == (
        'provider' if output_tokens is not None else 'unknown')
    assert synthesis.effective_request_input_tokens == min(
        DEFAULTS['max_request_input_tokens'],
        context_tokens or DEFAULTS['max_request_input_tokens'])
    assert synthesis.effective_request_output_tokens == min(
        DEFAULTS['max_request_output_tokens'],
        output_tokens or DEFAULTS['max_request_output_tokens'])


@pytest.mark.parametrize('provider',['claude-code','codex-cli'])
def test_explicit_shared_capabilities_override_provider_metadata_and_clamp_requests(
        tmp_path,monkeypatch,provider):
    fixture_cli(tmp_path,monkeypatch,provider,model='sonnet')
    monkeypatch.setenv('SPEED_PROVIDER_CONTEXT_TOKENS','12000')
    monkeypatch.setenv('SPEED_PROVIDER_MAX_OUTPUT_TOKENS','1000')
    config={**DEFAULTS,'max_request_input_tokens':16000,
            'max_request_output_tokens':2000}
    counters=limits(config)
    synthesis=Synthesis(tmp_path,config,None,counters)
    assert synthesis.agent_config['provider_context_tokens'] == 12000
    assert synthesis.agent_config['provider_max_output_tokens'] == 1000
    assert synthesis.effective_request_input_tokens == 12000
    assert synthesis.effective_request_output_tokens == 1000
    assert synthesis.request_for('synthesize', graph_scope(2))['max_output_tokens'] == 1000
    assert counters['provider_context_tokens'] == 12000
    assert counters['provider_max_output_tokens'] == 1000
    assert counters['effective_request_input_tokens'] == 12000
    assert counters['effective_request_output_tokens'] == 1000


def test_invalid_shared_capability_override_fails_before_provider_request(tmp_path,monkeypatch):
    log=fixture_cli(tmp_path,monkeypatch,'codex-cli')
    monkeypatch.setenv('SPEED_PROVIDER_CONTEXT_TOKENS','0')
    with pytest.raises(DomainError) as error:
        Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))
    assert error.value.code == 'PROVIDER_UNAVAILABLE'
    assert not log.exists()


def test_invoker_failure_preserves_diagnostics_without_guessing_authentication(tmp_path,monkeypatch):
    fixture_cli(tmp_path,monkeypatch,'claude-code','fail')
    synthesis=Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))
    with pytest.raises(DomainError) as error:
        synthesis._run_agent({'model':synthesis.agent_config['model'],'packet':{'stage':'activity'}},SCHEMA,5,role='activity')
    assert error.value.code=='PROVIDER_FAILED'
    assert error.value.provider_failure['category'] == 'process_failed'
    assert 'authentication' not in str(error.value)
    logs=list((tmp_path/'.speed/logs').glob('business-domain-*.log'))
    assert any('process_failed' in p.read_text() for p in logs)
    assert all('fixture service failure' not in p.read_text() for p in logs)


def test_claude_success_subtype_input_limit_is_nonretryable_request_capability(
        tmp_path,monkeypatch):
    fixture_cli(tmp_path,monkeypatch,'claude-code','input_limit')
    synthesis=Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))
    with pytest.raises(DomainError) as bridge_error:
        synthesis._run_agent({'model':synthesis.agent_config['model'],'packet':{'stage':'activity'}},SCHEMA,5,role='activity')
    error=bridge_error.value
    assert error.code == 'PROVIDER_CAPABILITY_UNAVAILABLE'
    assert error.provider_failure['category'] == 'capability_unavailable'
    assert error.provider_failure['scope'] == 'request'
    assert error.provider_failure['retryable'] is False
    assert error.provider_failure['native_status'] == 'input_limit'

    calls=0
    def same_failure(*_args,**_kwargs):
        nonlocal calls
        calls += 1
        raise error
    monkeypatch.setattr(synthesis,'_run_once',same_failure)
    with pytest.raises(DomainError) as final_error:
        synthesis._run_with_retries({'stage':'activity'})
    assert final_error.value is error
    assert calls == 1
    assert synthesis.counters['retries'] == 0


@pytest.mark.parametrize('provider',['claude-code','codex-cli'])
@pytest.mark.parametrize(('behavior','code','category','retryable'),[
    ('forbidden','PROVIDER_UNAVAILABLE','authorization_denied',False),
    ('capability','PROVIDER_CAPABILITY_UNAVAILABLE','capability_unavailable',False),
    ('rate_limit','PROVIDER_FAILED','rate_limited',True),
    ('transport','PROVIDER_FAILED','transport_unavailable',True),
    ('incomplete','PROVIDER_FAILED','response_incomplete',True),
    ('invalid','INVALID_PROVIDER_OUTPUT','response_invalid',False),
])
def test_provider_native_failure_crosses_bridge_as_common_envelope(
        tmp_path,monkeypatch,provider,behavior,code,category,retryable):
    fixture_cli(tmp_path,monkeypatch,provider,behavior)
    synthesis=Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))
    with pytest.raises(DomainError) as error:
        synthesis._run_agent({'model':synthesis.agent_config['model'],'packet':{'stage':'activity'}},SCHEMA,5,role='activity')
    assert error.value.code == code
    envelope = error.value.provider_failure
    assert envelope['schema_version'] == 1
    assert envelope['category'] == category
    assert envelope['retryable'] is retryable
    assert envelope['scope'] == ('request' if behavior == 'invalid' else 'provider')
    assert len(envelope['diagnostic_log'] or '') <= 512
    diagnostic = tmp_path/envelope['diagnostic_log']
    assert diagnostic.stat().st_size <= 2048
    assert 'do-not-copy' not in diagnostic.read_text()
    assert set(json.loads(diagnostic.read_text())) == {
        'schema_version','category','scope','retryable','native_status','bridge_exit'}
    persisted = error.value.record()
    assert persisted['retryable'] is retryable
    assert persisted['provider_failure'] == envelope
    assert 'do-not-copy' not in json.dumps(persisted)


@pytest.mark.parametrize(('provider,function'),[
    ('codex-cli','_codex_record_failure'),
    ('claude-code','_claude_record_failure'),
])
def test_shared_failure_envelope_is_strict_bounded_and_secret_free(tmp_path,provider,function):
    failure_file = tmp_path/'failure.json'
    script = f'''
SCRIPT_DIR={str(Path(__file__).parents[1])!r}
EXIT_CONFIG_ERROR=2
SPEED_PROVIDER={provider!r}
CODEX_BIN=/usr/bin/true
CLAUDE_BIN=/usr/bin/true
log_error_block() {{ :; }}
log_warn() {{ :; }}
source "$SCRIPT_DIR/lib/provider.sh"
export SPEED_PROVIDER_FAILURE_FILE={str(failure_file)!r}
provider_failure_clear
{function} "$RAW_FAILURE" 1 ".speed/logs/provider-safe.jsonl"
provider_failure_read
'''
    result = subprocess.run(['bash','-c',script],cwd=Path(__file__).parents[1],
        env={**os.environ,'RAW_FAILURE':'HTTP 401 invalid API key sk-secret-value'},
        capture_output=True,text=True,check=True)
    envelope = json.loads(result.stdout)
    assert envelope == json.loads(failure_file.read_text())
    assert envelope['category'] == 'authentication_required'
    assert envelope['scope'] == 'provider' and envelope['retryable'] is False
    assert len(envelope['message']) <= 256 and len(envelope['diagnostic_log']) <= 512
    assert 'sk-secret-value' not in result.stdout


def test_cancellation_stops_the_shared_invocation(tmp_path,monkeypatch):
    fixture_cli(tmp_path,monkeypatch,'codex-cli','wait')
    stop=threading.Event()
    synthesis=Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS),cancelled=stop.is_set)
    timer=threading.Timer(0.5,stop.set)
    timer.start()
    try:
        with pytest.raises(DomainError) as error:
            synthesis._run_agent({'model':synthesis.agent_config['model'],'packet':{'stage':'activity'}},SCHEMA,5,role='activity')
        assert error.value.code=='CANCELLED'
    finally:timer.cancel()


def test_provider_crosses_bridge_with_distinct_retryable_category(tmp_path,monkeypatch):
    fixture_cli(tmp_path,monkeypatch,'codex-cli','wait')
    synthesis=Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))
    with pytest.raises(DomainError) as error:
        synthesis._run_agent({'model':synthesis.agent_config['model'],'packet':{'stage':'activity'}},SCHEMA,0.05,role='activity')
    assert error.value.code == 'PROVIDER_TIMEOUT'
    assert error.value.retryable is True
    assert error.value.provider_failure['category'] == 'timeout'
    assert error.value.provider_failure['scope'] == 'provider'


def test_unknown_shared_failure_remains_unknown_with_bounded_diagnostic(tmp_path):
    failure_file = tmp_path/'failure.json'
    script = f'''
SCRIPT_DIR={str(Path(__file__).parents[1])!r}
EXIT_CONFIG_ERROR=2
SPEED_PROVIDER=codex-cli
CODEX_BIN=/usr/bin/true
log_error_block() {{ :; }}
log_warn() {{ :; }}
source "$SCRIPT_DIR/lib/provider.sh"
export SPEED_PROVIDER_FAILURE_FILE={str(failure_file)!r}
provider_failure_record "novel_native_failure" "provider" "true" "future_1" \
    "Provider invocation failed" ".speed/logs/safe-reference.log"
provider_failure_read
'''
    result = subprocess.run(['bash','-c',script],cwd=Path(__file__).parents[1],
        capture_output=True,text=True,check=True)
    envelope = json.loads(result.stdout)
    assert envelope['category'] == 'unknown'
    assert envelope['native_status'] == 'future_1'
    assert envelope['diagnostic_log'] == '.speed/logs/safe-reference.log'


def test_normal_project_instructions_participate_in_cache_identity(tmp_path,monkeypatch):
    log=fixture_cli(tmp_path,monkeypatch,'claude-code')
    instructions=tmp_path/'AGENTS.md'
    instructions.write_text('Ordinary SPEED project instruction.')
    synthesis=Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))
    synthesis._run_agent({'model':synthesis.agent_config['model'],'packet':{'stage':'activity'}},SCHEMA,5,role='activity')
    args=json.loads(log.read_text())
    assert 'Ordinary SPEED project instruction.' in args[args.index('--system-prompt')+1]
    instructions.write_text('Changed SPEED project instruction.')
    changed=Synthesis(tmp_path,DEFAULTS,None,limits(DEFAULTS))
    assert changed.provider_hash!=synthesis.provider_hash


@pytest.mark.parametrize('recovery_error', ['BUILD_BUDGET', 'BUILD_TIMEOUT'])
def test_failed_recovery_preserves_provider_cause_and_stops_later_packets(tmp_path, monkeypatch, recovery_error):
    class FixtureProvider:
        model = 'fixture'

    synthesis = Synthesis(tmp_path, DEFAULTS, FixtureProvider(), limits(DEFAULTS))
    attempts = []

    def attempt(*args):
        attempts.append(True)
        code = 'PROVIDER_FAILED' if len(attempts) == 1 else recovery_error
        raise DomainError(code, 'Fixture failure')

    monkeypatch.setattr(synthesis, '_run_once', attempt)
    for _ in range(3):
        with pytest.raises(DomainError) as error:
            synthesis.run(graph_scope(2), lambda candidate: [])
        assert error.value.code == 'PROVIDER_UNAVAILABLE'
        assert 'PROVIDER_FAILED' in str(error.value)
    assert len(attempts) == 2
    assert synthesis.counters['retries'] == 1
    assert synthesis.is_cancelled()  # Active transports receive the shutdown signal.
    assert not synthesis.cancelled()  # Provider failure is not user cancellation.


@pytest.mark.parametrize('reason', ['CANCELLED', 'BUILD_TIMEOUT'])
def test_probe_wait_observes_cancellation_and_deadline(tmp_path, reason):
    from concurrent.futures import ThreadPoolExecutor

    class FixtureProvider:
        model = 'fixture'

    cancelled = threading.Event()
    config = {**DEFAULTS, 'deadline_seconds': 0.1 if reason == 'BUILD_TIMEOUT' else 30}
    synthesis = Synthesis(tmp_path, config, FixtureProvider(), limits(config), cancelled.is_set)
    synthesis._await_provider_gate()  # The main thread owns the initial probe.
    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(synthesis._await_provider_gate)
        if reason == 'CANCELLED':
            cancelled.set()
        with pytest.raises(DomainError) as error:
            waiting.result(timeout=2)
    assert error.value.code == reason
    assert synthesis.counters['requests'] == 0
    assert synthesis.counters['input_tokens_reserved'] == 0
    assert synthesis.output_reserved == 0


def test_context_bridge_has_no_digest_or_provider_dispatch():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'lib/context_bridge.sh').read_text()
    assert 'digest' not in source.lower()
    assert 'provider_run_json' not in source
    assert 'provider_model_capabilities' not in source
    assert 'BASH_SOURCE[0]' not in source


def test_digest_command_can_be_sourced_without_provider_bootstrap():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            'bash', '-c',
            'source "$1"; '
            'declare -F digest_status digest_build digest_markdown',
            'test', str(root / 'lib/cmd/digest.sh'),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        'digest_status', 'digest_build', 'digest_markdown',
    ]
    assert result.stderr == ''

@pytest.mark.parametrize('current_model,retry_count,expected', [
    ('support', 0, {'model': 'planning'}),
    ('planning', 0, None),
    ('support', 1, None),
])
def test_digest_timeout_model_selection(current_model, retry_count, expected):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([
        'bash', '-c',
        'source "$1"; MODEL_PLANNING=planning; '
        '_digest_retry_model "$2" "$3"',
        'test', str(root/'lib/cmd/digest.sh'),
        current_model, str(retry_count),
    ], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected
    assert result.stderr == ''


def scripted_synthesis(tmp_path, monkeypatch, provider, failures=()):
    """Real shell adapters with local canned responses, never a live provider."""
    from tests.test_business_domain_candidate_protocol import ProtocolProvider
    from lib.context.discovery_logging import DiscoveryRecorder

    fixture_cli(tmp_path, monkeypatch, provider, behavior='scripted')
    monkeypatch.setenv('SPEED_PLANNING_MODEL', 'fixture-planning')
    config = {**DEFAULTS, 'max_request_output_tokens': 8000}
    progress = []
    recorder = DiscoveryRecorder(tmp_path, progress=progress.append)
    engine = Synthesis(
        tmp_path, config, None, limits(config), recorder=recorder)
    graph = graph_scope(2)
    responses = ProtocolProvider(graph)
    exchange = engine.project_exchange
    invoke = engine._run_agent
    projection = None
    calls = []

    def project(*args, **kwargs):
        nonlocal projection
        value = exchange(*args, **kwargs)
        projection = value[2]
        return value

    def agent(request, schema, timeout, role):
        calls.append(copy.deepcopy(request))
        if len(calls) in failures:
            reply = {'exit_code': 124}
        else:
            payload, _ = responses.generate(request, schema)
            reply = {'payload': projection._rewrite(payload, projection.aliases)}
        (tmp_path/'reply.json').write_text(json.dumps(reply))
        return invoke(request, schema, timeout, role)

    monkeypatch.setattr(engine, 'project_exchange', project)
    monkeypatch.setattr(engine, '_run_agent', agent)
    return engine, graph, calls, recorder, progress


def test_semantic_progress_reports_payload_counts_and_failed_verdict(
        tmp_path, monkeypatch):
    engine, graph, _, recorder, progress = scripted_synthesis(
        tmp_path, monkeypatch, 'codex-cli')
    try:
        engine.run(graph, lambda candidate: [])
    finally:
        recorder.finish('complete')

    accepted = [event for event in progress
                if 'attempt 1 accepted' in event['message']]
    synthesis = next(event for event in accepted
                     if event['message'].startswith('Synthesize'))
    failed_verification = next(
        event for event in accepted
        if event['message'].startswith('Verify')
        and event['details'].get('verdict') == 'fail')
    repair = next(event for event in accepted
                  if event['message'].startswith(
                      'Repair round 1, provider attempt 1'))

    assert synthesis['message'].endswith(
        '1 activities, 0 rules, 0 domains')
    assert synthesis['details']['record_counts'] == {
        'activities': 1, 'rules': 0, 'domains': 0}
    assert failed_verification['level'] == 'warning'
    assert failed_verification['message'].endswith(
        'verdict fail, 1 finding(s), 1 blocking')
    assert failed_verification['details'] == {
        'verdict': 'fail',
        'finding_count': 1,
        'blocking_finding_count': 1,
    }
    assert repair['message'].startswith(
        'Repair round 1, provider attempt 1 accepted')


@pytest.mark.parametrize('provider', ['claude-code', 'codex-cli'])
@pytest.mark.parametrize('timeout_call', [1, 2, 3, 4])
def test_timeout_escalation_is_charged_verified_and_logged(
        tmp_path, monkeypatch, provider, timeout_call):
    engine, graph, calls, recorder, progress = scripted_synthesis(
        tmp_path, monkeypatch, provider, failures=(timeout_call,))
    deadline = engine.deadline
    try:
        result = engine.run(graph, lambda candidate: [])
        assert result['activities'] == {}
        models = ['fixture-model'] * 5
        models[timeout_call] = 'fixture-planning'
        assert [request['model'] for request in calls] == models
        operations = ['synthesize', 'verify', 'repair', 'verify']
        operations.insert(timeout_call, operations[timeout_call-1])
        assert [request['operation'] for request in calls] == operations
        previous, escalated = calls[timeout_call-1:timeout_call+1]
        assert previous['request_id'] != escalated['request_id']
        assert engine._request_key(previous) != engine._request_key(escalated)
        assert engine.deadline == deadline
        assert engine.counters['requests'] == 5
        assert engine.counters['retries'] == 1
        assert engine.output_reserved == 5 * 8000
        assert engine.counters['input_tokens_reserved'] > 0
        invocations = [
            json.loads(line) for line in
            (tmp_path/'invocation.jsonl').read_text().splitlines()]
        assert [args[args.index('--model')+1] for args in invocations] == [
            request['model'] for request in calls]
        assert any('escalating to fixture-planning' in event['message']
                   for event in progress)
        # Candidate cache publication must retain the actual escalated request.
        cached = [
            json.loads(path.read_text()) for path in
            (tmp_path/'.speed/context/business-domain-cache').glob('*.json')]
        assert any(artifact.get('request', {}).get('model') == 'fixture-planning'
                   for artifact in cached)
    finally:
        recorder.finish('complete')
    text = recorder.events_path.read_text()
    assert 'escalating to fixture-planning' in text
    assert 'UNCLOSED_BOUNDARY' not in text


@pytest.mark.parametrize('provider', ['claude-code', 'codex-cli'])
@pytest.mark.parametrize('stop', ['second_timeout', 'planning', 'budget', 'deadline'])
def test_timeout_escalation_stops_without_extra_dispatch(
        tmp_path, monkeypatch, provider, stop):
    engine, graph, calls, recorder, _ = scripted_synthesis(
        tmp_path, monkeypatch, provider, failures=(1, 2))
    if stop == 'planning':
        engine.agent_config['model'] = 'fixture-planning'
    invoke = engine._run_agent

    def agent(*args):
        try:
            return invoke(*args)
        finally:
            if stop == 'budget':
                engine.config['max_build_output_tokens'] = engine.output_reserved
            elif stop == 'deadline':
                engine.deadline = time.monotonic() - 1

    monkeypatch.setattr(engine, '_run_agent', agent)
    try:
        with pytest.raises(DomainError) as error:
            engine.run(graph, lambda candidate: [])
        assert error.value.code == 'PROVIDER_UNAVAILABLE'
        assert error.value.provider_failure['category'] == 'timeout'
        expected = 2 if stop == 'second_timeout' else 1
        assert len(calls) == expected
        assert engine.counters['requests'] == expected
        assert engine.output_reserved == expected * 8000
        assert engine.provider_failure is not None
    finally:
        recorder.finish('failed')


def test_escalation_respects_selected_model_caps(tmp_path, monkeypatch):
    engine, graph, calls, recorder, _ = scripted_synthesis(
        tmp_path, monkeypatch, 'codex-cli', failures=(1,))
    engine.agent_config['models']['fixture-planning'] = {
        'provider_context_tokens': 1,
        'provider_max_output_tokens': 1000,
        'output_limit_enforcement': 'provider',
    }
    request = engine.request_for('synthesize', graph)
    try:
        assert request['max_output_tokens'] == 8000
        with pytest.raises(DomainError) as error:
            engine._run_with_retries(request)
        assert error.value.code == 'PACKET_LIMIT'
        assert request['model'] == 'fixture-planning'
        assert request['max_output_tokens'] == 1000
        assert len(calls) == 1
        assert engine.counters['requests'] == 1
        assert engine.output_reserved == 8000
    finally:
        recorder.finish('failed')


def test_agent_timeout_uses_existing_setting_and_remaining_deadline(
        tmp_path, monkeypatch):
    fixture_cli(tmp_path, monkeypatch, 'codex-cli')
    monkeypatch.setenv('SPEED_TIMEOUT', '7')
    engine = Synthesis(tmp_path, DEFAULTS, None, limits(DEFAULTS))
    calls = []

    def capture(action, *args, **kwargs):
        calls.append((action, args, kwargs))
        return {'ok': True}

    monkeypatch.setattr(engine, '_speed_call', capture)
    request = {'model': engine.agent_config['planning_model']}
    engine._run_agent(request, SCHEMA, 60, 'synthesis')
    assert calls[-1][1][-2:] == (request['model'], 7)
    assert calls[-1][2]['timeout'] == 19
    engine._run_agent(request, SCHEMA, 0.5, 'synthesis')
    assert calls[-1][1][-1] == 1
    assert calls[-1][2]['timeout'] == 0.5

@pytest.mark.parametrize('provider', ['claude-code', 'codex-cli'])
def test_smaller_escalated_output_limit_is_charged(tmp_path, monkeypatch, provider):
    engine, graph, calls, recorder, _ = scripted_synthesis(
        tmp_path, monkeypatch, provider, failures=(1,))
    engine.agent_config['models']['fixture-planning']['provider_max_output_tokens'] = 1000
    try:
        engine.run(graph, lambda candidate: [])
        assert calls[0]['max_output_tokens'] == 8000
        assert calls[1]['max_output_tokens'] == 1000
        assert engine.output_reserved == 4*8000 + 1000
        assert engine.counters['requests'] == 5
    finally:
        recorder.finish('complete')


@pytest.mark.parametrize('provider', ['claude-code', 'codex-cli'])
def test_authentication_failure_does_not_escalate(tmp_path, monkeypatch, provider):
    fixture_cli(tmp_path, monkeypatch, provider, behavior='forbidden')
    monkeypatch.setenv('SPEED_PLANNING_MODEL', 'fixture-planning')
    engine = Synthesis(tmp_path, DEFAULTS, None, limits(DEFAULTS))
    request = engine.request_for('synthesize', graph_scope(2))
    with pytest.raises(DomainError) as error:
        engine._run_with_retries(request)
    assert error.value.code == 'PROVIDER_UNAVAILABLE'
    assert engine.counters['requests'] == 1
    assert request['model'] == 'fixture-model'
    assert engine.counters['retries'] == 0
