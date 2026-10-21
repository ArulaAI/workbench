"""Tests for business-domain evidence extracted from TypeScript code."""
import pytest

from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import settings

STORE = '''export class Store {
  readonly items = new Map<string, number>();
  readonly history: number[] = [];
  readonly entries: Array<number> = [];

  put(key: string, value: number): void {
    this.items.set(key, value);
    this.history.push(value);
    this.entries.push(value);
  }

  total(): number {
    return this.history
      .filter(value => value > 0)
      .length;
  }

  guess(input: any): number {
    const copy = input.slice(0);
    return copy.length;
  }

  first(input: string[]): string {
    return input.slice(0, 1).join('');
  }
}
'''
VAULT = '''const store = new Map<string, string>();

export const keep = (token: string, value: string): void => {
  store.set(token, value);
};

export const shadowed = (store: { set(a: string, b: string): void }): void => {
  store.set('a', 'b');
};
'''
OBS = '''export const sinks = { logs: [] as string[] };

export const log = {
  info: (message: string) => sinks.logs.push(message),
  error(message: string) { sinks.logs.push(message); },
};

export const info = (message: string): string => message;
'''
SERVICE = '''import { log } from './obs.ts';

export class Service {
  run(): void {
    log.info('ran');
    log.error('failed');
  }
}
'''
GATEWAY = '''import { Service } from './service.ts';

export class Gateway {
  constructor(private readonly service: Service) {}

  run(): void {
    this.service.run();
  }
}
'''
TESTS = '''import test from 'node:test';
import { Service } from '../src/service.ts';
import { Gateway } from '../src/gateway.ts';

const svc = () => new Service();
const gw = () => new Gateway(new Service());
const runWith = (service: Service) => service.run();

test('a service runs', () => {
  const s = svc();
  s.run();
});

test('the gateway delegates', () => {
  gw().run();
});

test('a directly constructed service runs', () => {
  const direct = new Service();
  direct.run();
});

it('runs through a typed helper', () => {
  runWith(svc());
});
'''


def _write(root, files):
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


def _facts(root):
    facts, _ = Extractor(root, settings({})).extract()
    return facts


def _name(facts, symbol_id):
    return facts['symbols'][symbol_id]['qualified_name'].split('::', 1)[1]


def _base(name):
    """Strip the position suffix added to same-named symbols."""
    return name.split(':', 1)[0]


def _data(facts, caller):
    """Return (kind, store name) for each data edge from *caller*."""
    return {(edge['kind'], facts['resources'][edge['to_ref']['id']]['name'])
            for edge in facts['edges'].values()
            if edge['kind'] in {'reads_data', 'writes_data'}
            and _name(facts, edge['from_ref']['id']) == caller}


def _calls(facts, caller):
    """Return (excerpt, resolution, reason, to_ref) for each call edge from *caller*."""
    return [(edge['evidence_ids'] and facts['evidence'][edge['evidence_ids'][0]]['excerpt'],
             edge['resolution'], edge['reason'], edge['to_ref'])
            for edge in facts['edges'].values()
            if edge['kind'] == 'calls' and _name(facts, edge['from_ref']['id']) == caller]


# Calls on declared platform types

def test_writes_to_declared_map_and_array_members_are_writes_to_their_store(tmp_path):
    facts = _facts(_write(tmp_path, {'src/store.ts': STORE}))

    # Mutating a member collection counts as a data write to that member.
    assert _data(facts, 'Store.put') == {('writes_data', 'src/store.ts::Store.items'),
                                         ('writes_data', 'src/store.ts::Store.history'),
                                         ('writes_data', 'src/store.ts::Store.entries')}
    reasons = {reason for _, _, reason, _ in _calls(facts, 'Store.put')}
    assert not any(reason and reason.startswith('Call target') for reason in reasons)


def test_a_chain_split_across_lines_keeps_its_declared_receiver(tmp_path):
    facts = _facts(_write(tmp_path, {'src/store.ts': STORE}))

    assert ('reads_data', 'src/store.ts::Store.history') in _data(facts, 'Store.total')


def test_an_undeclared_local_receiver_stays_unresolved(tmp_path):
    facts = _facts(_write(tmp_path, {'src/store.ts': STORE}))

    calls = _calls(facts, 'Store.guess')

    assert ('unresolved', 'Call target slice: 0 source candidates') in {
        (resolution, reason) for _, resolution, reason, _ in calls}


def test_a_module_constant_map_is_a_platform_boundary_unless_shadowed(tmp_path):
    facts = _facts(_write(tmp_path, {'src/vault.ts': VAULT}))

    shadowed = {reason for _, _, reason, _ in _calls(facts, 'shadowed')}

    assert _data(facts, 'keep') == {('writes_data', 'src/vault.ts::store')}
    assert shadowed == {'Call target set: 0 source candidates'}
    assert _data(facts, 'shadowed') == set()


# Members of exported objects

def test_functions_of_an_exported_object_are_owned_by_it(tmp_path):
    facts = _facts(_write(tmp_path, {'src/obs.ts': OBS}))

    names = {_base(_name(facts, symbol['id'])) for symbol in facts['symbols'].values()
             if symbol['kind'] == 'function'}

    assert {'log.info', 'log.error', 'info'} <= names


def test_a_call_through_an_imported_object_resolves_to_its_member(tmp_path):
    facts = _facts(_write(tmp_path, {'src/obs.ts': OBS, 'src/service.ts': SERVICE}))

    targets = {_base(_name(facts, to_ref['id']))
               for _, resolution, _, to_ref in _calls(facts, 'Service.run')
               if resolution == 'resolved'}

    # `log.info` should resolve to the member, not the top-level `info`.
    assert targets == {'log.info', 'log.error'}


def test_a_receiver_call_never_takes_a_same_file_name_match(tmp_path):
    facts = _facts(_write(tmp_path, {
        'src/service.ts': 'export class Service {\n  run(): void {}\n}\n',
        'src/gateway.ts': ('import { Service } from "./service.ts";\n'
                           'export class Gateway {\n  run(other: unknown): void {\n'
                           '    (other as any).run();\n  }\n}\n')}))

    calls = _calls(facts, 'Gateway.run')

    assert not any(to_ref and to_ref['kind'] == 'symbol'
                   and _name(facts, to_ref['id']) == 'Gateway.run' for _, _, _, to_ref in calls)


# Tests linked to the behaviour they exercise

def _tested(facts):
    return {(_name(facts, edge['from_ref']['id']), _name(facts, edge['to_ref']['id']))
            for edge in facts['edges'].values() if edge['kind'] == 'tests_behavior'}


def test_test_cases_are_units_named_by_their_title(tmp_path):
    facts = _facts(_write(tmp_path, {'src/obs.ts': OBS, 'src/service.ts': SERVICE,
                                     'src/gateway.ts': GATEWAY, 'test/service.test.ts': TESTS}))

    titles = {_name(facts, symbol['id']) for symbol in facts['symbols'].values()
              if symbol['file'] == 'test/service.test.ts' and symbol['kind'] == 'function'}

    assert {'a service runs', 'the gateway delegates', 'a directly constructed service runs',
            'runs through a typed helper'} <= titles


def test_tests_link_to_the_production_behaviour_they_call(tmp_path):
    facts = _facts(_write(tmp_path, {'src/obs.ts': OBS, 'src/service.ts': SERVICE,
                                     'src/gateway.ts': GATEWAY, 'test/service.test.ts': TESTS}))

    tested = _tested(facts)

    assert ('a service runs', 'Service.run') in tested                       # const s = svc()
    assert ('the gateway delegates', 'Gateway.run') in tested                # gw().run()
    assert ('a directly constructed service runs', 'Service.run') in tested  # new Service()
    assert ('runWith', 'Service.run') in tested                              # (service: Service)


def test_test_cases_never_become_anchors(tmp_path):
    facts = _facts(_write(tmp_path, {'src/obs.ts': OBS, 'src/service.ts': SERVICE,
                                     'src/gateway.ts': GATEWAY, 'test/service.test.ts': TESTS}))

    anchored = {_name(facts, anchor['symbol_id']) for anchor in facts['anchors'].values()}

    assert anchored == {'Service.run', 'Gateway.run'}


# Actionable budget and deadline failures

def test_a_budget_failure_names_the_exhausted_budget_and_its_setting():
    from lib.context.business_domain_synthesis import _budget_error
    error = _budget_error('output', 512_000, 128_000, 512_000)

    assert error.code == 'BUILD_BUDGET'
    message = str(error)
    assert 'output-token budget exhausted' in message
    assert '128,000 output tokens' in message
    assert 'max_build_output_tokens = 512,000' in message
    assert '[business_domains]' in message and 'speed.toml' in message


@pytest.mark.parametrize('setting', ['deadline_seconds', '[business_domains]', 'speed.toml'])
def test_a_deadline_failure_names_its_setting(setting):
    from lib.context.business_domain_synthesis import DEADLINE_EXCEEDED
    assert setting in DEADLINE_EXCEEDED


# Documentation linked to the operations it describes

LEDGER = '''export class Ledger {
  net(): number { return 0; }
  post(amount: number): void {}
}
'''
SPEC = '''# Ledger

The ledger keeps every movement of money.

## Network outages

Avoid posting twice when the network drops; a reposted entry is a defect.

## Balance

The ledger's net balance is zero after every operation. Call post once per pair.
'''


def _documented(facts, path='docs/ledger.md'):
    """Map operation name to the cited line ranges in *path*."""
    names = {anchor['id']: anchor['operation']['name'] for anchor in facts['anchors'].values()}
    resources = facts['resources']
    links = {}
    for edge in facts['edges'].values():
        if (edge['kind'] == 'documents_behavior' and edge['to_ref']['kind'] == 'anchor'
                and resources[edge['from_ref']['id']]['name'] == path):
            locators = [facts['evidence'][evidence_id]['locator']
                        for evidence_id in edge['evidence_ids']]
            links[names[edge['to_ref']['id']]] = sorted(
                (item['start_line'], item['end_line']) for item in locators)
    return links


def test_documentation_links_only_whole_word_mentions(tmp_path):
    facts = _facts(_write(tmp_path, {'src/ledger.ts': LEDGER, 'docs/ledger.md': SPEC}))

    links = _documented(facts)

    # "Network" and "reposted" contain "net" and "post" but only as substrings.
    assert set(links) == {'net', 'post'}
    assert links['net'] == links['post'] == [(9, 11)]


def test_documentation_cites_the_section_not_the_whole_file(tmp_path):
    facts = _facts(_write(tmp_path, {'src/ledger.ts': LEDGER, 'docs/ledger.md': SPEC}))

    for ranges in _documented(facts).values():
        assert all(end - start + 1 < SPEC.count('\n') for start, end in ranges)


# Inputs of declared callables

PAYMENTS = '''export class Payments {
  capture(paymentId: string, amount?: number, retries = 0): number {
    return [amount ?? 0].reduce((sum, value) => sum + value, retries);
  }
}

export const quote = (rate: number) => rate;
'''


def _inputs(facts):
    return {(_name(facts, binding['source']['id']), binding['name'], binding['value_type'])
            for binding in facts['bindings'].values() if binding['direction'] == 'input'}


def test_parameters_of_declared_callables_are_input_bindings(tmp_path):
    facts = _facts(_write(tmp_path, {'src/payments.ts': PAYMENTS}))

    inputs = _inputs(facts)

    assert {('Payments.capture', 'paymentId', 'string'),
            ('Payments.capture', 'amount', 'number'),        # optional
            ('Payments.capture', 'retries', 'unknown'),      # untyped default
            ('quote', 'rate', 'number')} <= inputs


def test_inline_callback_parameters_are_not_inputs(tmp_path):
    facts = _facts(_write(tmp_path, {'src/payments.ts': PAYMENTS}))

    names = {name for _, name, _ in _inputs(facts)}

    assert not names & {'sum', 'value'}


# Tests and documentation reach the model

def test_the_synthesis_context_carries_tests_and_documentation(tmp_path):
    from lib.context.business_domain_synthesis import _model_ready_context
    from lib.context.business_domains import copy_facts
    _write(tmp_path, {'src/obs.ts': OBS, 'src/service.ts': SERVICE, 'src/gateway.ts': GATEWAY,
                      'test/service.test.ts': TESTS,
                      'docs/service.md': '# Service\n\n## Running\n\nA service can run once.\n'})
    model = copy_facts(_facts(tmp_path), 'build')

    context = _model_ready_context(model, sorted(model['anchors']))

    kinds = {edge['kind'] for edge in context['edges'].values()}
    assert {'tests_behavior', 'documents_behavior'} <= kinds
    tests = {_name(model, symbol_id) for symbol_id in context['symbols']
             if model['symbols'][symbol_id]['file'].startswith('test/')}
    assert 'a service runs' in tests
    # The test's span, including its assertions, can be cited as evidence.
    test_case = next(symbol for symbol in model['symbols'].values()
                     if _name(model, symbol['id']) == 'a service runs')
    assert set(test_case['evidence_ids']) <= set(context['evidence']) | set(
        context.get('record_refs', {}))
