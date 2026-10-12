"""Receivers whose type TypeScript source declares away from the call.

A call is a platform call only when the source declares its receiver as a type
the language provides. These tests cover receivers whose declaration is one or
more steps away (a member of an aliased type, a method's return type, a local
assigned from a typed expression, a type guard) and the cases that must stay
unresolved because nothing is declared.
"""
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import settings

TYPES = '''export type Capture = { id: string; amount: number };

export type Payment = {
  id: string;
  captures: Capture[];
};

export type PaymentStore = Map<string, Payment>;

export type Request = {
  pan: string;
  amount: number;
};
'''
SERVICE = '''import { type Payment, type PaymentStore, type Request } from './types.ts';

let seq = 0;

export type Routed = Request & { merchantId: string };

export class Service {
  readonly payments: PaymentStore = new Map();
  private readonly attempts = new Map<string, number[]>();
  private counter = 0;

  nextId(prefix: string): string {
    return `${prefix}_${(++this.counter).toString(36).padStart(6, '0')}`;
  }

  capture(id: string): number {
    const payment = this.require(id);
    return payment.captures.reduce((sum, c) => sum + c.amount, 0);
  }

  card(req: Routed): string {
    const digits = req.pan.replace(/\\D/g, '');
    return digits.slice(-4);
  }

  velocity(key: string, at: number): number {
    const recent = (this.attempts.get(key) ?? []).filter(t => at - t < 600);
    recent.push(at);
    return recent.length;
  }

  private require(id: string): Payment {
    const found = this.payments.get(id);
    if (!found) throw new RangeError(id);
    return found;
  }
}

export const sinks = { logs: [] as string[] };

export const log = (message: string) => sinks.logs.push(message);

export const label = (): string => (++seq).toString(36);

export const audit = (store: PaymentStore): number => {
  let total = 0;
  for (const p of store.values()) {
    total += p.captures.length;
    p.captures.forEach(c => c.amount);
  }
  return total;
};
'''
GUARDS = '''export const flatten = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value === 'string') return value.trim();
  return value;
};

export const refused = (value: unknown): unknown => {
  if (!Array.isArray(value)) return value;
  return value.map(String);
};

export const either = (value: unknown, other: unknown): unknown => {
  if (Array.isArray(value) || other) return value.map(String);
  return value;
};
'''
UNDECLARED = '''export const loose = (value: any, items) => {
  items.push(value);
  return value.trim();
};

export const shadow = (values: string[]): number[] =>
  values.map(values => values.length);

export class Holder {
  constructor(private readonly items: unknown) {}

  first(): unknown {
    return (this.items as any).slice(0, 1);
  }
}
'''
LEDGER = '''export class Ledger {
  readonly entries: number[] = [];

  net(): number {
    return this.entries.reduce((sum, value) => sum + value, 0);
  }
}
'''
OWNER = '''import { Ledger } from './ledger.ts';

export class Owner {
  readonly ledger = new Ledger();
}
'''
CALLER = '''import { Owner } from './owner.ts';

export const run = (): number => {
  const owner = new Owner();
  return owner.ledger.net();
};
'''


def _facts(root, files):
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    facts, _ = Extractor(root, settings({})).extract()
    return facts


def _calls(facts, caller):
    """(written call, reason) for each call edge from *caller*."""
    found = []
    for edge in facts['edges'].values():
        if edge['kind'] != 'calls':
            continue
        name = facts['symbols'][edge['from_ref']['id']]['qualified_name'].split('::', 1)[1]
        if name.split(':', 1)[0] == caller:
            excerpt = facts['evidence'][edge['evidence_ids'][0]]['excerpt']
            found.append((' '.join(excerpt.split()), edge['reason'] or '', edge))
    return found


def _data(facts, caller):
    """(kind, store name) for each data edge from *caller*."""
    found = set()
    for edge in facts['edges'].values():
        name = facts['symbols'][edge['from_ref']['id']]['qualified_name'].split('::', 1)[1]
        if edge['kind'] in {'reads_data', 'writes_data'} and name.split(':', 1)[0] == caller:
            found.add((edge['kind'], facts['resources'][edge['to_ref']['id']]['name']))
    return found


def _reason(facts, caller, written):
    """The reason of the call whose source is *written*, or that starts with
    it when no call is written exactly so."""
    calls = _calls(facts, caller)
    reasons = ([reason for call, reason, _ in calls if call == written]
               or [reason for call, reason, _ in calls if call.startswith(written + '(')])
    assert reasons, f'no call {written!r} from {caller}: {_calls(facts, caller)}'
    return reasons[0]


def _platform(facts, caller, written, provider):
    reason = _reason(facts, caller, written)
    assert 'a type typescript provides' in reason and f' {provider}, ' in reason, reason
    return reason


# ── Declared one or more steps away ─────────────────────────────────────

def test_a_member_of_an_object_literal_is_typed_by_its_as_assertion(tmp_path):
    facts = _facts(tmp_path, {'src/types.ts': TYPES, 'src/service.ts': SERVICE})

    # `sinks.logs` is a module-level array, so pushing to it writes that store.
    assert ('writes_data', 'src/service.ts::sinks.logs') in _data(facts, 'log')


def test_an_increment_is_a_number_and_its_string_is_a_string(tmp_path):
    facts = _facts(tmp_path, {'src/types.ts': TYPES, 'src/service.ts': SERVICE})

    _platform(facts, 'Service.nextId', "(++this.counter).toString(36).padStart(6, '0')", 'String')
    _platform(facts, 'Service.nextId', '(++this.counter).toString(36)', 'Number')
    _platform(facts, 'label', '(++seq).toString(36)', 'Number')


def test_a_member_is_typed_through_a_method_return_type_and_an_alias(tmp_path):
    facts = _facts(tmp_path, {'src/types.ts': TYPES, 'src/service.ts': SERVICE})

    reason = _platform(facts, 'Service.capture', 'payment.captures.reduce', 'Array')

    # The derivation reads from the receiver down, each step citing its line.
    steps = reason.split('Declared by: ')[1]
    assert steps.index('payment = this.require(id)') < steps.index('Service.require(): Payment')
    assert steps.index('Service.require(): Payment') < steps.index('captures: Capture[] (src/types.ts:5)')


def test_a_typed_parameter_reaches_a_member_of_an_imported_intersection(tmp_path):
    facts = _facts(tmp_path, {'src/types.ts': TYPES, 'src/service.ts': SERVICE})

    reason = _platform(facts, 'Service.card', 'req.pan.replace', 'String')

    assert 'req: Routed' in reason and 'pan: string (src/types.ts:' in reason


def test_a_local_takes_the_declared_return_type_of_its_initializer(tmp_path):
    facts = _facts(tmp_path, {'src/types.ts': TYPES, 'src/service.ts': SERVICE})

    reason = _platform(facts, 'Service.card', 'digits.slice', 'String')

    assert "digits = req.pan.replace(/\\D/g, '')" in reason


def test_a_map_value_and_a_coalesced_array_literal_agree_on_array(tmp_path):
    facts = _facts(tmp_path, {'src/types.ts': TYPES, 'src/service.ts': SERVICE})

    _platform(facts, 'Service.velocity', '(this.attempts.get(key) ?? []).filter', 'Array')
    _platform(facts, 'Service.velocity', 'recent.push', 'Array')


def test_a_loop_variable_takes_the_element_type_of_its_iterable(tmp_path):
    facts = _facts(tmp_path, {'src/types.ts': TYPES, 'src/service.ts': SERVICE})

    _platform(facts, 'audit', 'store.values', 'Map')
    reason = _platform(facts, 'audit', 'p.captures.forEach', 'Array')

    assert 'p of store.values()' in reason


def test_a_declared_class_member_resolves_a_call_into_this_repository(tmp_path):
    facts = _facts(tmp_path, {'src/ledger.ts': LEDGER, 'src/owner.ts': OWNER,
                              'src/run.ts': CALLER})

    [(_, _, edge)] = [call for call in _calls(facts, 'run') if call[0].startswith('owner.ledger.net')]

    assert edge['resolution'] == 'resolved'
    target = facts['symbols'][edge['to_ref']['id']]['qualified_name']
    assert target.split('::', 1) == ['src/ledger.ts', 'Ledger.net']


# ── Type guards the platform declares ───────────────────────────────────

def test_a_type_guard_narrows_inside_the_branch_it_protects(tmp_path):
    facts = _facts(tmp_path, {'src/guards.ts': GUARDS})

    reason = _reason(facts, 'flatten', 'value.map')
    assert reason.startswith('value is narrowed to Array, a type typescript provides')
    assert 'value narrowed by Array.isArray(value) (src/guards.ts:2)' in reason
    assert _reason(facts, 'flatten', 'value.trim').startswith('value is narrowed to String')


def test_a_negated_or_disjoint_guard_does_not_narrow(tmp_path):
    facts = _facts(tmp_path, {'src/guards.ts': GUARDS})

    assert _reason(facts, 'refused', 'value.map') == 'Call target map: 0 source candidates'
    assert _reason(facts, 'either', 'value.map') == 'Call target map: 0 source candidates'


# ── Nothing declared: the call stays unresolved ─────────────────────────

def test_any_unknown_and_untyped_receivers_stay_unresolved(tmp_path):
    facts = _facts(tmp_path, {'src/loose.ts': UNDECLARED})

    assert _reason(facts, 'loose', 'items.push') == 'Call target push: 0 source candidates'
    assert _reason(facts, 'loose', 'value.trim') == 'Call target trim: 0 source candidates'
    assert _reason(facts, 'Holder.first', '(this.items as any).slice') == \
        'Call target slice: 0 source candidates'


def test_a_callback_parameter_shadows_the_outer_declaration(tmp_path):
    facts = _facts(tmp_path, {'src/loose.ts': UNDECLARED})

    # `values` inside the callback is the element, not the declared array.
    assert _reason(facts, 'shadow', 'values.map').startswith('values is declared as Array')
    inner = [reason for call, reason, _ in _calls(facts, 'shadow') if call == 'values.length']
    assert not any('declared as Array' in reason for reason in inner)


def test_javascript_initializers_are_not_declarations(tmp_path):
    facts = _facts(tmp_path, {'src/plain.js': 'export const keep = () => {\n'
                                              '  let items = [];\n  items.push(1);\n'
                                              '  return items;\n};\n'})

    [(_, reason, edge)] = [call for call in _calls(facts, 'keep') if call[0] == 'items.push(1)']
    assert edge['resolution'] == 'unresolved' and 'declared as' not in reason
