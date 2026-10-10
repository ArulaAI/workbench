import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ChallengeError, HttpStepUpProvider, StepUpAdapter,
  type StepUpChallenge, type StepUpProvider,
} from '../src/risk/stepup.ts';
import type { Decision } from '../src/risk/types.ts';

type Req = { amount: number; merchantId: string };
const REQ: Req = { amount: 5000, merchantId: 'm_1' };
const DECISION: Decision = { outcome: 'step_up', score: 0.5, reasons: [], thresholdsVersion: 'v1' };
const META = { amount: 5000, currency: 'GBP', merchantId: 'm_1' };

class FakeStepUpProvider implements StepUpProvider {
  calls = 0;
  private readonly impl: () => Promise<'started' | 'unavailable'>;
  constructor(impl: () => Promise<'started' | 'unavailable'> = async () => 'started') {
    this.impl = impl;
  }
  start() {
    this.calls += 1;
    return this.impl();
  }
}

const fakeClock = () => {
  const c = { now: 1_000_000 };
  const timers: { fn: () => void; at: number; id: number; live: boolean }[] = [];
  return {
    c, timers,
    clock: () => c.now,
    setTimer: (fn: () => void, ms: number) => {
      const t = { fn, at: c.now + ms, id: timers.length, live: true };
      timers.push(t);
      return t;
    },
    clearTimer: (h: unknown) => { (h as { live: boolean }).live = false; },
    advance(ms: number) {
      c.now += ms;
      for (const t of timers) if (t.live && t.at <= c.now) { t.live = false; t.fn(); }
    },
  };
};

const setup = (provider: StepUpProvider) => {
  const f = fakeClock();
  const unavailable: [StepUpChallenge<Req>, Req][] = [];
  const adapter = new StepUpAdapter<Req>(provider, {
    clock: f.clock, setTimer: f.setTimer, clearTimer: f.clearTimer,
    onUnavailable: (c, r) => unavailable.push([c, r]),
  });
  return { f, adapter, unavailable };
};

const tick = () => new Promise(resolve => setImmediate(resolve));

test('begin returns chl_000001, pending, expiring in 10 minutes', () => {
  const { adapter } = setup(new FakeStepUpProvider(() => new Promise(() => {})));
  const c = adapter.begin(REQ, DECISION, 'tok_1', META);
  assert.equal(c.id, 'chl_000001');
  assert.equal(c.status, 'pending');
  assert.equal(c.expiresAt, c.createdAt + 600_000);
});

test('complete throws for unknown id and for pending past expiry', () => {
  const { adapter, f } = setup(new FakeStepUpProvider(() => new Promise(() => {})));
  assert.throws(() => adapter.complete('chl_999999', 'authenticated'), ChallengeError);
  const c = adapter.begin(REQ, DECISION, 'tok_1', META);
  f.c.now += 600_001;
  assert.throws(() => adapter.complete(c.id, 'authenticated'), ChallengeError);
});

test('a challenge completes once; a repeat leaves it unchanged', () => {
  const { adapter } = setup(new FakeStepUpProvider(() => new Promise(() => {})));
  const c = adapter.begin(REQ, DECISION, 'tok_1', META);
  const first = adapter.complete(c.id, 'authenticated');
  assert.equal(first.challenge.status, 'authenticated');
  assert.equal(first.repeat, false);
  const second = adapter.complete(c.id, 'not_authenticated');
  assert.equal(second.challenge.status, 'authenticated');
  assert.equal(second.repeat, true);
});

test('start never resolving completes unavailable after 10s, onUnavailable once', () => {
  const { adapter, f, unavailable } = setup(new FakeStepUpProvider(() => new Promise(() => {})));
  const c = adapter.begin(REQ, DECISION, 'tok_1', META);
  f.advance(9_999);
  assert.equal(c.status, 'pending');
  f.advance(1);
  assert.equal(c.status, 'unavailable');
  f.advance(60_000);
  assert.equal(unavailable.length, 1);
});

test('started provider: cardholder authenticates after 5 minutes, no onUnavailable', async () => {
  const { adapter, f, unavailable } = setup(new FakeStepUpProvider());
  const c = adapter.begin(REQ, DECISION, 'tok_1', META);
  await tick();
  f.advance(5 * 60_000);
  assert.equal(adapter.complete(c.id, 'authenticated').challenge.status, 'authenticated');
  assert.equal(unavailable.length, 0);
});

test('async unavailable and rejection each complete unavailable with one callback', async () => {
  for (const impl of [async () => 'unavailable' as const, async () => { throw new Error('boom'); }]) {
    const { adapter, unavailable } = setup(new FakeStepUpProvider(impl));
    const c = adapter.begin(REQ, DECISION, 'tok_1', META);
    await tick();
    assert.equal(c.status, 'unavailable');
    assert.equal(unavailable.length, 1);
    assert.equal(unavailable[0][1], REQ);
  }
});

test('source defaults to policy and records block_match', () => {
  const { adapter } = setup(new FakeStepUpProvider(() => new Promise(() => {})));
  assert.equal(adapter.begin(REQ, DECISION, 'tok_1', META).source, 'policy');
  assert.equal(adapter.begin(REQ, DECISION, 'tok_1', META, 'block_match').source, 'block_match');
});

test('expire cancels overdue pending challenges and drops old completed ones', () => {
  const { adapter, f } = setup(new FakeStepUpProvider(() => new Promise(() => {})));
  const pending = adapter.begin(REQ, DECISION, 'tok_1', META);
  const done = adapter.begin(REQ, DECISION, 'tok_2', META);
  adapter.complete(done.id, 'authenticated');
  f.c.now += 600_001;
  adapter.expire();
  assert.equal(pending.status, 'cancelled');
  assert.equal(adapter.get(done.id), undefined);
  assert.equal(adapter.get(pending.id)?.status, 'cancelled');
});

test('complete returns the original request; repeat after release still works', () => {
  const { adapter } = setup(new FakeStepUpProvider(() => new Promise(() => {})));
  const c = adapter.begin(REQ, DECISION, 'tok_1', META);
  const done = adapter.complete(c.id, 'authenticated');
  assert.equal(done.request.amount, 5000);
  assert.equal(done.request.merchantId, 'm_1');
  adapter.release(c.id);
  const again = adapter.complete(c.id, 'authenticated');
  assert.equal(again.repeat, true);
  assert.equal(again.challenge.status, 'authenticated');
});

test('HttpStepUpProvider maps rejection, 503 and timeout to unavailable', async () => {
  const realFetch = globalThis.fetch;
  const args = { challengeId: 'chl_000001', token: 'tok_00000001', amount: 100, currency: 'GBP', merchantId: 'm_1' };
  try {
    const p = new HttpStepUpProvider({ baseUrl: 'http://x', apiKey: 'k', timeoutMs: 20 });
    globalThis.fetch = (async () => { throw new TypeError('network'); }) as typeof fetch;
    assert.equal(await p.start(args), 'unavailable');
    globalThis.fetch = (async () => new Response('', { status: 503 })) as typeof fetch;
    assert.equal(await p.start(args), 'unavailable');
    globalThis.fetch = ((_url: unknown, init?: RequestInit) =>
      new Promise((_res, rej) => init?.signal?.addEventListener('abort', () => rej(new Error('aborted'))))) as typeof fetch;
    assert.equal(await p.start(args), 'unavailable');
    globalThis.fetch = (async () => new Response('{}', { status: 200 })) as typeof fetch;
    assert.equal(await p.start(args), 'started');
  } finally {
    globalThis.fetch = realFetch;
  }
});

test('HttpStepUpProvider rejects a 16-digit number before any fetch', async () => {
  const realFetch = globalThis.fetch;
  let fetched = 0;
  globalThis.fetch = (async () => { fetched += 1; return new Response('{}'); }) as typeof fetch;
  try {
    const p = new HttpStepUpProvider({ baseUrl: 'http://x', apiKey: 'k' });
    await assert.rejects(p.start({
      challengeId: 'chl_000001', token: '4111111111111111', amount: 100, currency: 'GBP', merchantId: 'm_1',
    }));
    assert.equal(fetched, 0);
  } finally {
    globalThis.fetch = realFetch;
  }
});
