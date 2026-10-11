"""Business-domain discovery on a TypeScript library with no framework.

A payments library exposes its behaviour as exported classes. Discovery must
anchor their public methods, follow those operations into the domain code they
call, and observe the guards that encode business rules. When nothing can be
anchored it must stop before any model call instead of publishing an empty
model.
"""
import json

import pytest

from lib.context.business_domain_cli import main
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import settings
from lib.context.business_domains import discover, load, paths
from lib.context.csg import resolve_source_reference
from lib.context.treesitter_extract import ExtractionResult, Reference
from tests.business_domains.provider_fixture import PassingProvider, write_service

MONEY = '''export type Minor = number;
export const minor = (n: number): Minor => {
  if (!Number.isInteger(n)) throw new Error('amounts are integer minor units');
  return n;
};
'''
LEDGER = '''export class Ledger {
  private entries: number[] = [];
  post(amount: number): void {
    this.entries.push(amount);
  }
}
'''
RULES = '''export class RiskRules {
  evaluate(amount: number): boolean {
    if (amount >= 100_000) {
      return false;
    }
    return true;
  }
}
'''
SERVICE = '''import { type Minor, minor } from '../domain/money.ts';
import { Ledger } from '../domain/ledger.ts';
import { RiskRules } from '../risk/rules.ts';

export class PaymentsService {
  readonly ledger = new Ledger();
  readonly rules: RiskRules;
  #audit = 0;

  constructor(rules = new RiskRules()) {
    this.rules = rules;
  }

  capture(amount: number): Minor {
    if (!this.rules.evaluate(amount)) {
      throw new Error('declined');
    }
    const value = minor(amount);
    this.ledger.post(this.fee(value));
    return value;
  }

  private fee(value: Minor): number {
    return value;
  }

  protected reconcile(): void {}

  #trail(): void {}
}

class InternalHelper {
  run(): void {}
}

export const formatAmount = (value: Minor): string => String(value);
'''
GATEWAY = '''import { PaymentsService } from './service.ts';

export class Gateway {
  constructor(private readonly payments: PaymentsService) {}

  charge(amount: number): number {
    return this.payments.capture(amount);
  }
}
'''


def _library(root):
    for path, text in {'src/domain/money.ts': MONEY, 'src/domain/ledger.ts': LEDGER,
                       'src/risk/rules.ts': RULES, 'src/payments/service.ts': SERVICE,
                       'src/payments/gateway.ts': GATEWAY}.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


def _facts(root):
    facts, _ = Extractor(root, settings({})).extract()
    return facts


def _name(facts, symbol_id):
    return facts['symbols'][symbol_id]['qualified_name'].split('::', 1)[1]


def _anchors(facts):
    return {_name(facts, anchor['symbol_id']): anchor for anchor in facts['anchors'].values()}


def _trace_reach(facts, anchor_name):
    anchor = _anchors(facts)[anchor_name]
    trace = next(trace for trace in facts['traces'].values()
                 if trace['anchor_id'] == anchor['id'])
    return {_name(facts, symbol_id) for symbol_id in trace['symbol_ids']}


# ── Library entry points ────────────────────────────────────────────────

def test_public_methods_of_exported_classes_are_resolved_library_anchors(tmp_path):
    facts = _facts(_library(tmp_path))

    anchors = _anchors(facts)

    assert set(anchors) == {'Ledger.post', 'RiskRules.evaluate',
                            'PaymentsService.capture', 'Gateway.charge'}
    capture = anchors['PaymentsService.capture']
    assert capture['kind'] == 'library'
    assert capture['resolution'] == 'resolved'
    representation = capture['representations'][0]
    assert representation['eligibility'] == 'eligible'
    assert representation['visibility'] == 'external'
    assert representation['identity_key'] == (
        'library:repository:src/payments/service.ts::PaymentsService.capture')
    assert representation['registration']['kind'] == 'library_export'
    assert capture['canonical_anchor_id'] == capture['id']


def test_helpers_constructors_and_non_public_members_are_not_anchors(tmp_path):
    facts = _facts(_library(tmp_path))

    names = set(_anchors(facts))

    for excluded in ('PaymentsService.fee', 'PaymentsService.reconcile',
                     'PaymentsService.#trail', 'PaymentsService.constructor',
                     'Gateway.constructor', 'InternalHelper.run', 'formatAmount', 'minor'):
        assert excluded not in names


def test_library_entry_points_are_counted_and_no_entry_point_gap_remains(tmp_path):
    facts = _facts(_library(tmp_path))

    assert not facts['coverage'].get('entrypoint_gaps')
    assert not any(warning['code'].startswith('ENTRYPOINT_') for warning in facts['warnings'])


def test_test_sources_never_contribute_library_anchors(tmp_path):
    _library(tmp_path)
    (tmp_path / 'test').mkdir()
    (tmp_path / 'test/service.test.ts').write_text(
        'export class ServiceSpec {\n  checksCapture(): void {}\n}\n')

    assert 'ServiceSpec.checksCapture' not in _anchors(_facts(tmp_path))


# ── Traces into supporting domain logic ─────────────────────────────────

def test_operation_trace_reaches_ledger_risk_and_money_logic(tmp_path):
    facts = _facts(_library(tmp_path))

    reached = _trace_reach(facts, 'PaymentsService.capture')

    # Imported with an explicit `.ts` extension, a `new`-initialised field, a
    # typed field and a private method of the same class.
    assert {'minor', 'Ledger.post', 'RiskRules.evaluate', 'PaymentsService.fee'} <= reached


def test_parameter_property_receiver_reaches_the_injected_service(tmp_path):
    facts = _facts(_library(tmp_path))

    assert 'PaymentsService.capture' in _trace_reach(facts, 'Gateway.charge')


def test_private_methods_are_named_by_their_name_not_their_modifier(tmp_path):
    facts = _facts(_library(tmp_path))

    methods = {_name(facts, symbol['id']) for symbol in facts['symbols'].values()
               if symbol['kind'] == 'method'}

    assert {'PaymentsService.fee', 'PaymentsService.reconcile'} <= methods
    assert not any(name.split('.')[-1].split(':')[0] in {'private', 'protected'}
                   for name in methods)


def test_javascript_modifier_methods_are_named_by_their_name(tmp_path):
    (tmp_path / 'clock.js').write_text(
        'export class Clock {\n  static now() { return 1; }\n'
        '  async tick() { return Clock.now(); }\n  get value() { return 2; }\n}\n')

    facts = _facts(tmp_path)

    methods = {_name(facts, symbol['id']) for symbol in facts['symbols'].values()
               if symbol['kind'] == 'method'}
    assert {'Clock.now', 'Clock.tick', 'Clock.value'} <= methods


@pytest.mark.parametrize('specifier', ['./money.ts', './money.js', './money.mjs', './money'])
def test_relative_script_imports_resolve_with_or_without_an_extension(specifier):
    nodes = [{'id': 'src/money.ts::minor', 'name': 'minor', 'file': 'src/money.ts',
              'kind': 'function'}]
    extractions = {
        'src/money.ts': ExtractionResult('src/money.ts', 'typescript'),
        'src/service.ts': ExtractionResult('src/service.ts', 'typescript', references=[
            Reference(name=specifier, kind='import', file='src/service.ts', line=1,
                      module=specifier, symbols=['minor'])]),
    }

    assert resolve_source_reference('minor', 'src/service.ts', nodes, extractions) == \
        'src/money.ts::minor'


# ── Rule observations ───────────────────────────────────────────────────

def test_library_guards_are_rule_observations(tmp_path):
    facts = _facts(_library(tmp_path))

    observed = {(facts['evidence'][item['evidence_ids'][0]]['locator']['path'],
                 item['native_expression'], item['source_location_kind'])
                for item in facts['rule_observations'].values()}

    assert ('src/risk/rules.ts', '(amount >= 100_000)', 'api') in observed
    assert ('src/payments/service.ts', '(!this.rules.evaluate(amount))', 'api') in observed
    assert ('src/domain/money.ts', '(!Number.isInteger(n))', 'api') in observed


def test_angular_component_conditions_are_not_api_observations(tmp_path):
    (tmp_path / 'list.component.ts').write_text(
        "import { Component } from '@angular/core';\n"
        "@Component({ selector: 'app-list', template: '' })\n"
        "export class ListComponent {\n"
        "  show(count: number): boolean {\n    if (count > 0) { return true; }\n"
        "    return false;\n  }\n}\n")

    facts = _facts(tmp_path)

    assert not [item for item in facts['rule_observations'].values()
                if item['native_expression'] == '(count > 0)']


# ── No usable entry points ──────────────────────────────────────────────

def _helpers_only(root):
    (root / 'src').mkdir(parents=True, exist_ok=True)
    (root / 'src/money.ts').write_text(MONEY)
    return root


def test_no_usable_anchor_stops_before_any_provider_call(tmp_path):
    provider = PassingProvider()

    model, status = discover(_helpers_only(tmp_path), provider=provider)

    assert provider.calls == 0
    assert model is None
    assert status['phase'] == 'failed'
    assert status['error']['code'] == 'NO_ENTRY_POINTS'
    assert 'no model call was made' in status['error']['message']
    assert not paths(tmp_path)['model'].exists()
    # The facts that explain the stop are still written for inspection.
    facts = json.loads(paths(tmp_path)['facts'].read_text())
    assert facts['coverage']['entrypoint_gaps'][0]['code'] == 'ENTRYPOINT_NONE_DETECTED'


def test_no_usable_anchor_after_a_publication_preserves_it(tmp_path):
    write_service(tmp_path)
    provider = PassingProvider()
    published, _ = discover(tmp_path, provider=provider)
    original = paths(tmp_path)['model'].read_bytes()
    calls = provider.calls
    (tmp_path / 'service.py').unlink()
    _helpers_only(tmp_path)

    retained, status = discover(tmp_path, provider=provider)

    assert provider.calls == calls
    assert status['error']['code'] == 'NO_ENTRY_POINTS'
    assert status['published_build_id'] == published['build_id']
    assert retained['build_id'] == published['build_id']
    assert paths(tmp_path)['model'].read_bytes() == original


def test_library_discovery_publishes_through_the_provider(tmp_path):
    provider = PassingProvider()

    model, status = discover(_library(tmp_path), provider=provider)

    assert provider.calls >= 2  # synthesize, then verify
    assert status['phase'] in {'complete', 'partial'}
    assert status['published_build_id'] == model['build_id'] == status['attempt_build_id']
    assert model['coverage']['anchors_total'] == 4


# ── Cache reuse and invalidation ────────────────────────────────────────

def test_unchanged_library_reuses_the_verified_result_and_a_change_does_not(tmp_path):
    provider = PassingProvider()
    _library(tmp_path)
    first, _ = discover(tmp_path, provider=provider)
    after_first = provider.calls

    second, _ = discover(tmp_path, provider=provider)
    assert provider.calls == after_first
    assert second['coverage'] == first['coverage']

    (tmp_path / 'src/domain/ledger.ts').write_text(
        LEDGER.replace('  post(', '  reverse(amount: number): void {}\n  post('))
    third, _ = discover(tmp_path, provider=provider)

    assert provider.calls > after_first
    assert third['coverage']['anchors_total'] == 5


# ── CLI outcome reporting ───────────────────────────────────────────────

def _cli_with(monkeypatch, provider):
    from lib.context import business_domain_cli
    real = business_domain_cli.discover
    monkeypatch.setattr(business_domain_cli, 'discover',
                        lambda root, config=None, **kwargs: real(
                            root, config, provider=provider, **kwargs))


def test_cli_reports_a_successful_attempt_as_its_own_publication(tmp_path, monkeypatch, capsys):
    _cli_with(monkeypatch, PassingProvider())

    code = main(['--root', str(_library(tmp_path))])

    output = json.loads(capsys.readouterr().out)
    assert code == 0 and output['ok'] is True
    assert output['published'] is True
    assert output['published_build_id'] == output['status']['attempt_build_id']
    assert output['artifact'] == '.speed/context/business-domains.json'


def test_cli_failed_attempt_does_not_report_the_previous_build_as_published(
        tmp_path, monkeypatch, capsys):
    write_service(tmp_path)
    provider = PassingProvider()
    previous, _ = discover(tmp_path, provider=provider)
    (tmp_path / 'service.py').write_text(
        "@app.post('/orders')\ndef create(order):\n    return {'accepted': order}\n")
    provider.fail = True
    _cli_with(monkeypatch, provider)

    code = main(['--root', str(tmp_path)])

    output = json.loads(capsys.readouterr().out)
    assert code != 0 and output['ok'] is False
    assert output['published'] is False
    assert output['status']['phase'] in {'failed', 'unavailable'}
    assert output['status']['attempt_build_id'] != previous['build_id']
    # The previous publication stays available and is named as such.
    assert output['published_build_id'] is None
    assert output['preserved_build_id'] == previous['build_id']
    assert load(tmp_path)[0]['build_id'] == previous['build_id']


def test_cli_no_entry_points_exits_nonzero_without_publishing(tmp_path, monkeypatch, capsys):
    provider = PassingProvider()
    _cli_with(monkeypatch, provider)

    code = main(['--root', str(_helpers_only(tmp_path))])

    output = json.loads(capsys.readouterr().out)
    assert code == 1 and output['ok'] is False
    assert output['published'] is False and output['preserved_build_id'] is None
    assert output['status']['error']['code'] == 'NO_ENTRY_POINTS'
    assert provider.calls == 0


# ── Configuration ───────────────────────────────────────────────────────

def test_facts_only_needs_no_speed_toml(tmp_path, capsys):
    _library(tmp_path)

    assert main(['--root', str(tmp_path), '--facts-only']) == 0

    output = json.loads(capsys.readouterr().out)
    assert {item['kind']: item['resolved'] for item in output['entry_points']} == {
        'library_export': 4}


def test_unknown_business_domain_setting_is_a_configuration_error(tmp_path, capsys):
    _library(tmp_path)
    (tmp_path / 'speed.toml').write_text('[business_domains]\nmax_bild_tokens = 1\n')

    assert main(['--root', str(tmp_path), '--facts-only']) == 3

    output = json.loads(capsys.readouterr().out)
    assert output['error']['code'] == 'INVALID_CONFIG'


def _render_status(tmp_path, result):
    import subprocess
    from pathlib import Path
    payload = tmp_path / 'result.json'
    payload.write_text(json.dumps(result))
    script = Path(__file__).parents[1] / 'lib/cmd/domains.sh'
    return subprocess.run(
        ['bash', '-c', f'source "{script}"; _domains_render_status "{payload}"'],
        capture_output=True, text=True, check=True, timeout=30).stdout


def test_rendered_failure_names_the_outcome_and_the_preserved_build(tmp_path):
    status = {'started_at': 's', 'completed_at': 'c', 'phase': 'failed',
              'attempt_build_id': 'new-attempt', 'warnings': [], 'coverage': None,
              'error': {'code': 'NO_ENTRY_POINTS', 'message': 'nothing to trace'}}

    text = _render_status(tmp_path, {'status': status, 'published': False,
                                     'published_build_id': None,
                                     'preserved_build_id': 'old-build'})

    assert 'Outcome:     failed (attempt new-attempt)' in text
    assert 'Published:   no' in text
    assert 'Preserved:   build old-build is still the published model' in text
    assert 'Error:       NO_ENTRY_POINTS: nothing to trace' in text
    assert 'yes (build old-build)' not in text


def test_rendered_success_names_its_own_build(tmp_path):
    status = {'started_at': 's', 'completed_at': 'c', 'phase': 'partial',
              'attempt_build_id': 'b1', 'warnings': [], 'error': None,
              'coverage': {'anchors_processed': 12, 'anchors_total': 12}}

    text = _render_status(tmp_path, {'status': status, 'published': True,
                                     'published_build_id': 'b1', 'preserved_build_id': None})

    assert 'Outcome:     partial (attempt b1)' in text
    assert 'Published:   yes (build b1)' in text
    assert 'Preserved:' not in text
    assert 'Anchors:     12/12 processed' in text
