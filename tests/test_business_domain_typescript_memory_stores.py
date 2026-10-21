"""Tests for TypeScript in-memory stores (Map, Set, array members and module state).

Collections that are never written, parameters and fresh locals stay platform calls.
"""
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import information_use_closure, settings

SERVICE = '''export type Capture = { id: string; amount: number };

export type Payment = {
  id: string;
  captures: Capture[];
};

const ALLOWED = new Set(['GBP', 'EUR']);

export class Payments {
  private readonly payments = new Map<string, Payment>();
  private readonly log: string[] = [];

  open(id: string, currency: string): Payment {
    if (!ALLOWED.has(currency)) throw new RangeError(currency);
    const payment: Payment = { id, captures: [] };
    this.payments.set(id, payment);
    return payment;
  }

  capture(id: string, amount: number): number {
    const payment = this.require(id);
    payment.captures.push({ id: `${id}-c`, amount });
    return payment.captures.reduce((sum, c) => sum + c.amount, 0);
  }

  summary(ids: string[]): string[] {
    const seen: string[] = [];
    for (const id of ids) seen.push(id);
    return seen.concat(ids.slice(0, 1));
  }

  reset(): void {
    this.payments.clear();
    this.log.length = 0;
  }

  private require(id: string): Payment {
    const found = this.payments.get(id);
    if (!found) throw new RangeError(id);
    return found;
  }
}
'''


def _facts(root):
    path = root / 'src/payments.ts'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SERVICE)
    facts, _ = Extractor(root, settings({})).extract()
    return facts


def _name(facts, symbol_id):
    return facts['symbols'][symbol_id]['qualified_name'].split('::', 1)[1].split(':', 1)[0]


def _data(facts, caller):
    return {(edge['kind'], facts['resources'][edge['to_ref']['id']]['name'])
            for edge in facts['edges'].values()
            if edge['kind'] in {'reads_data', 'writes_data'}
            and _name(facts, edge['from_ref']['id']) == caller}


def _calls(facts, caller):
    return {' '.join(facts['evidence'][edge['evidence_ids'][0]]['excerpt'].split())
            for edge in facts['edges'].values()
            if edge['kind'] == 'calls' and _name(facts, edge['from_ref']['id']) == caller}


def _trace(facts, anchor_name):
    return next(trace for trace in facts['traces'].values()
                if _name(facts, facts['anchors'][trace['anchor_id']]['symbol_id']) == anchor_name)


def test_a_member_collection_is_a_store_its_methods_read_and_write(tmp_path):
    facts = _facts(tmp_path)

    assert _data(facts, 'Payments.open') == {('writes_data', 'src/payments.ts::Payments.payments')}
    assert _data(facts, 'Payments.require') == {('reads_data', 'src/payments.ts::Payments.payments')}
    store = next(resource for resource in facts['resources'].values()
                 if resource['name'] == 'src/payments.ts::Payments.payments')
    assert (store['kind'], store['resolution']) == ('memory_store', 'resolved')


def test_a_store_access_replaces_the_platform_call_edge(tmp_path):
    facts = _facts(tmp_path)

    calls = _calls(facts, 'Payments.open')
    assert not any(call.startswith('this.payments.set') for call in calls)


def test_a_field_of_a_declared_record_is_a_store(tmp_path):
    facts = _facts(tmp_path)

    assert _data(facts, 'Payments.capture') == {
        ('writes_data', 'src/payments.ts::Payment.captures'),
        ('reads_data', 'src/payments.ts::Payment.captures')}


def test_clearing_and_truncating_are_writes(tmp_path):
    facts = _facts(tmp_path)

    assert _data(facts, 'Payments.reset') == {
        ('writes_data', 'src/payments.ts::Payments.payments'),
        ('writes_data', 'src/payments.ts::Payments.log')}


def test_a_write_is_an_effect_whose_trace_is_bounded_not_incomplete(tmp_path):
    facts = _facts(tmp_path)

    effects = {facts['resources'][effect['target']['id']]['name']: effect
               for effect in facts['effects'].values()
               if _name(facts, effect['origin_ref']['id']) == 'Payments.open'}
    assert effects['src/payments.ts::Payments.payments']['kind'] == 'data_write'
    trace = _trace(facts, 'Payments.open')
    assert trace['completion'] == 'bounded'
    assert any(item['kind'] == 'in_process_state' and 'does not survive the process' in item['statement']
               for item in trace['assumptions'])


def test_reference_data_and_local_collections_are_not_stores(tmp_path):
    facts = _facts(tmp_path)

    # Nothing changes ALLOWED, so reading it is a platform call.
    assert any(call.startswith('ALLOWED.has') for call in _calls(facts, 'Payments.open'))
    # `seen` is a fresh local and `ids` a parameter.
    assert _data(facts, 'Payments.summary') == set()
    assert not any(resource['kind'] == 'memory_store' and 'ALLOWED' in resource['name']
                   for resource in facts['resources'].values())


def test_an_information_use_may_cite_a_store_its_activity_writes(tmp_path):
    facts = _facts(tmp_path)
    trace = _trace(facts, 'Payments.open')
    store = next(rid for rid, resource in facts['resources'].items()
                 if resource['name'] == 'src/payments.ts::Payments.payments')
    model = {**facts,
             'activities': {'activity:open': {'id': 'activity:open', 'trace_ids': [trace['id']],
                                              'concept_ids': ['concept:payment']}}}
    use = {'activity_id': 'activity:open', 'concept_id': 'concept:payment',
           'access': 'creates', 'resource_ids': [store]}

    closure = information_use_closure(model, use)

    assert closure['effect_ids'] and closure['trace_ids'] == {trace['id']}
