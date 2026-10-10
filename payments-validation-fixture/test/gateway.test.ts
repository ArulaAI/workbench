/*
 * Characterisation tests for the gateway and risk rules v1, and the scored decision behind
 * the rollout flag.
 *
 * GW-01 to GW-04 pin what the gateway does in the default shadow mode, where v1 still
 * decides. GW-05 and GW-06 cover the F2.2 card-testing block. GW-10 onwards cover v1, shadow and enforce modes. A test that starts failing
 * because of the adaptive authorisation work is expected to be rewritten, deliberately,
 * alongside the spec that changed it.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { AuthorisationGateway } from '../src/payments/gateway.ts';
import { type AuthoriseRequest, PaymentsService } from '../src/payments/service.ts';
import { RiskRules } from '../src/risk/rules.ts';
import { ModelScorer, type Scorer } from '../src/risk/scoring.ts';
import { DEFAULT_THRESHOLDS, DecisionPolicy } from '../src/risk/policy.ts';
import { StepUpAdapter, type StepUpProvider } from '../src/risk/stepup.ts';
import { CARDHOLDER_REASONS, assertCardholderReasonSafe } from '../src/risk/reasons.ts';
import type { ScoringInput } from '../src/risk/types.ts';
import { type RiskRollout, rolloutFromEnv, scoredDecides } from '../src/risk/rollout.ts';
import { InMemoryReviewQueue } from '../src/review/queue.ts';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { sinks, resetSinks } from '../src/obs/index.ts';
import { TEST_CARDS, EXPIRY } from './fixtures/cards.ts';
import { CardTestingRuntime, InMemoryDetectorLease } from '../src/risk/card-testing-runtime.ts';
import { AttemptRecorder, InMemoryAttemptStore } from '../src/risk/attempts.ts';
import { AttackDetector, InMemoryAttackStore } from '../src/risk/attacks.ts';
import { BlockList, InMemoryBlockStore } from '../src/risk/blocks.ts';
import { loadDetectorConfig } from '../src/risk/detector-config.ts';
import { InMemoryNotificationSink, MerchantNotifier } from '../src/notify/merchant.ts';
import { readFileSync } from 'node:fs';
import { cardTestingBurst, domesticGroceries, travellerTelevision } from './fixtures/traffic.ts';

const detectorBase = JSON.parse(readFileSync(new URL('../config/detector.json', import.meta.url), 'utf8'));
const MODEL_PATH = fileURLToPath(new URL('./fixtures/model.json', import.meta.url));

/** A scorer that always returns the same score, and counts its calls. */
const fixedScorer = (score: number) => {
  const s = {
    calls: 0,
    score(_input: ScoringInput) {
      s.calls += 1;
      return { score, reasons: ['country_mismatch' as const], modelVersion: 'fixed-1' };
    },
  };
  return s;
};

const throwingScorer: Scorer = { score: () => { throw new Error('model unavailable'); } };

const fakeProvider: StepUpProvider = { start: async () => 'started' };

const build = (opts: { scorer?: Scorer; rollout?: RiskRollout } = {}) => {
  const payments = new PaymentsService();
  const audit = new InMemoryAuditLog();
  const queue = new InMemoryReviewQueue(audit, Date.now, payments);
  // No real timers: the provider answers at once, so the 10-second fallback never matters here.
  const stepUp = new StepUpAdapter<AuthoriseRequest>(fakeProvider, {
    setTimer: () => 0,
    clearTimer: () => {},
  });
  const gateway = new AuthorisationGateway(payments, {
    scorer: opts.scorer ?? fixedScorer(100),
    policy: new DecisionPolicy(DEFAULT_THRESHOLDS),
    stepUp,
    queue,
    audit,
    rollout: opts.rollout,
  });
  return { gateway, payments, audit, queue, stepUp };
};

const gw = () => build().gateway;

const enforce = (...merchants: string[]): RiskRollout => ({ mode: 'enforce', enforcedMerchants: new Set(merchants) });

/** An authorisation that no v1 rule declines, for the enforced merchant. */
const routine = { ...domesticGroceries.request, merchantId: 'm_electricals' };

test('[GW-01] a routine domestic purchase is approved', () => {
  const result = gw().authorise(domesticGroceries.request);
  assert.equal(result.status, 'approved');
});

test('[GW-02] a high-value purchase from abroad is declined', () => {
  const result = gw().authorise(travellerTelevision.request);
  assert.deepEqual(result, { status: 'declined', code: 'do_not_honour' });
});

test('[GW-03] a scored decline carries an allowlisted reason that tells the cardholder nothing about why', () => {
  resetSinks();
  const { gateway } = build({ scorer: fixedScorer(850), rollout: enforce('m_electricals') });
  const result = gateway.authorise(travellerTelevision.request);
  assert.equal(result.status, 'declined');
  if (result.status !== 'declined') return;
  assert.equal(result.code, 'do_not_honour');
  const reason = result.reason ?? '';
  assert.ok(Object.values(CARDHOLDER_REASONS).includes(reason));
  assert.ok(reason.length > 0 && reason.length <= 140);
  assert.doesNotThrow(() => assertCardholderReasonSafe(reason));
  assert.doesNotMatch(reason, /850|score|threshold|amount_unusual|country_mismatch|HIGH_VALUE/i);
});

test('[GW-03b] a v1 decline in shadow mode still tells the merchant nothing about why', () => {
  resetSinks();
  const result = gw().authorise(travellerTelevision.request);
  assert.deepEqual(Object.keys(result).sort(), ['code', 'status']);
  assert.match(sinks.logs.at(-1)?.message ?? '', /HIGH_VALUE_CROSS_BORDER/);
});

test('[GW-04] a sixth attempt on one card inside ten minutes is declined', () => {
  const g = gw();
  const at = Date.UTC(2026, 9, 3, 9, 0, 0);
  const attempt = (i: number) => g.authorise({
    pan: TEST_CARDS.mastercard, expiry: EXPIRY, amount: 1_000,
    merchantId: 'm_cafe', ipCountry: 'GB', at: at + i * 1_000,
  });
  for (let i = 0; i < 5; i += 1) assert.equal(attempt(i).status, 'approved');
  assert.equal(attempt(5).status, 'declined');
});

/** One gateway replica with its own recorder and BlockList, and the F2.2 runtime that feeds them. */
const buildCardTesting = (shared: {
  attemptStore: InMemoryAttemptStore; blockStore: InMemoryBlockStore;
  attackStore: InMemoryAttackStore; lease: InMemoryDetectorLease; clock: () => number;
}) => {
  const config = loadDetectorConfig({ ...detectorBase, mode: 'block' });
  const { clock } = shared;
  const payments = new PaymentsService();
  const audit = new InMemoryAuditLog();
  const queue = new InMemoryReviewQueue(audit, clock, payments);
  const stepUp = new StepUpAdapter<AuthoriseRequest>(fakeProvider, { setTimer: () => 0, clearTimer: () => {} });
  const recorder = new AttemptRecorder(shared.attemptStore, config, clock);
  const blocks = new BlockList(shared.blockStore, shared.attackStore, audit, config, clock);
  const detector = new AttackDetector(shared.attemptStore, shared.attackStore, config, clock);
  const notifier = new MerchantNotifier(new InMemoryNotificationSink(), shared.attackStore, detector, config, clock);
  const runtime = new CardTestingRuntime({
    recorder, detector, blocks, notifier, lease: shared.lease, config, clock,
    logger: { info: () => {}, alert: () => {} },
  });
  const merchants = Array.from({ length: 20 }, (_, i) => `m_${String(i).padStart(2, '0')}`);
  const gateway = new AuthorisationGateway(payments, {
    scorer: fixedScorer(100),
    policy: new DecisionPolicy(DEFAULT_THRESHOLDS),
    stepUp, queue, audit, blocks, attempts: recorder, detectorConfig: config,
    rollout: enforce(...merchants),
  });
  return { gateway, runtime };
};

const sharedStores = () => {
  const clock = { now: 0 };
  const config = loadDetectorConfig(detectorBase);
  return {
    attemptStore: new InMemoryAttemptStore(), blockStore: new InMemoryBlockStore(),
    attackStore: new InMemoryAttackStore(), lease: new InMemoryDetectorLease(config.refreshIntervalMs),
    clock: () => clock.now, time: clock,
  };
};

/** Replay a burst through the replicas in turn, advancing the clock to each attempt and ticking every second. */
const replay = (
  burst: ReturnType<typeof cardTestingBurst>,
  replicas: ReturnType<typeof buildCardTesting>[],
  time: { now: number },
) => {
  time.now = burst[0].request.at - 1_000;
  return burst.map(({ request }, i) => {
    for (let t = time.now + 1_000; t <= request.at; t += 1_000) {
      time.now = t;
      for (const r of replicas) r.runtime.tick(t);
    }
    time.now = request.at;
    const replica = replicas[i % replicas.length];
    return { replica, result: replica.gateway.authorise(request) };
  });
};

test('[GW-05] F2.2 AC2: a card-testing burst is challenged after the tenth attempt and never approved without authentication', () => {
  const shared = sharedStores();
  const replica = buildCardTesting(shared);
  const outcomes = replay(cardTestingBurst(40), [replica], shared.time);
  const later = outcomes.slice(10);
  const challenged = later.filter(o => o.result.status === 'step_up');
  assert.ok(challenged.length / later.length >= 0.95, `${challenged.length} of ${later.length} challenged`);
  let approved = 0;
  for (const { result } of challenged) {
    if (result.status !== 'step_up') continue;
    const final = replica.gateway.completeStepUp(result.challengeId, 'not_authenticated');
    assert.equal(final.status, 'declined');
  }
  for (const { result } of later) if (result.status === 'approved') approved += 1;
  assert.equal(approved, 0);
});

test('[GW-06] F2.2 AC3: two replicas sharing the attempt, block and attack stores flag one attack and both challenge', () => {
  const shared = sharedStores();
  const a = buildCardTesting(shared);
  const b = buildCardTesting(shared);
  const outcomes = replay(cardTestingBurst(40), [a, b], shared.time);
  assert.equal(shared.attackStore.listByStatus('blocked').length, 1);
  for (const replica of [a, b]) {
    const later = outcomes.slice(10).filter(o => o.replica === replica);
    assert.ok(later.some(o => o.result.status === 'step_up'));
    assert.ok(later.every(o => o.result.status === 'step_up'));
  }
});

test('[GW-10] an enforced merchant steps up the traveller instead of declining', () => {
  const { gateway } = build({ scorer: ModelScorer.load(MODEL_PATH), rollout: enforce('m_electricals') });
  const result = gateway.authorise(travellerTelevision.request);
  assert.deepEqual(result, { status: 'step_up', challengeId: 'chl_000001' });
});

test('[GW-11] shadow mode: v1 still declines the traveller and one risk.shadow span records the scored outcome', () => {
  resetSinks();
  const { gateway } = build({ scorer: ModelScorer.load(MODEL_PATH) });
  const result = gateway.authorise(travellerTelevision.request);
  assert.deepEqual(result, { status: 'declined', code: 'do_not_honour' });
  assert.match(sinks.logs.at(-1)?.message ?? '', /HIGH_VALUE_CROSS_BORDER/);
  const shadow = sinks.spans.filter(s => s.name === 'risk.shadow');
  assert.equal(shadow.length, 1);
  assert.equal(shadow[0].attributes.outcome, 'step_up');
  assert.equal(shadow[0].attributes.v1Outcome, 'decline');
  assert.equal(shadow[0].attributes.v1Rule, 'HIGH_VALUE_CROSS_BORDER');
  assert.equal(shadow[0].attributes.thresholdsVersion, DEFAULT_THRESHOLDS.version);
  assert.equal(shadow[0].attributes.card, '411111******1111');
});

test('[GW-12] v1 mode never calls the scorer', () => {
  const scorer = fixedScorer(100);
  const { gateway } = build({ scorer, rollout: { mode: 'v1', enforcedMerchants: new Set(['m_electricals']) } });
  assert.deepEqual(gateway.authorise(travellerTelevision.request), { status: 'declined', code: 'do_not_honour' });
  assert.equal(gateway.authorise(routine).status, 'approved');
  assert.equal(scorer.calls, 0);
});

test('[GW-13] enforce mode: a merchant not yet enforced still gets the v1 result', () => {
  const { gateway } = build({ scorer: fixedScorer(100), rollout: enforce('m_other') });
  assert.deepEqual(gateway.authorise(travellerTelevision.request), { status: 'declined', code: 'do_not_honour' });
});

test('[GW-14] enforced merchant: score 100 approves and authorises once', () => {
  const { gateway, payments } = build({ scorer: fixedScorer(100), rollout: enforce('m_electricals') });
  let calls = 0;
  const authorise = payments.authorise.bind(payments);
  payments.authorise = req => { calls += 1; return authorise(req); };
  const result = gateway.authorise(travellerTelevision.request);
  assert.equal(result.status, 'approved');
  assert.equal(calls, 1);
});

test('[GW-15] enforced merchant: score 750 holds with capture blocked, a review item and a system audit', () => {
  const { gateway, payments, queue, audit } = build({ scorer: fixedScorer(750), rollout: enforce('m_electricals') });
  const result = gateway.authorise(travellerTelevision.request);
  assert.equal(result.status, 'held');
  if (result.status !== 'held') return;
  assert.equal(payments.isCaptureBlocked(result.payment.id), true);
  const held = queue.listHeld();
  assert.equal(held.length, 1);
  assert.equal(held[0].id, result.reviewId);
  assert.equal(held[0].maskedCard, '411111******1111');
  assert.equal(held[0].issuerCountry, 'GB');
  assert.equal(held[0].merchantCategory, 'unknown');
  const entries = audit.forSubject(result.reviewId);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].action, 'hold');
  assert.equal(entries[0].actor, 'system');
});

test('[GW-16] enforced merchant: score 900 declines with an allowlisted reason', () => {
  const { gateway } = build({ scorer: fixedScorer(900), rollout: enforce('m_electricals') });
  const result = gateway.authorise(travellerTelevision.request);
  assert.equal(result.status, 'declined');
  if (result.status !== 'declined') return;
  assert.equal(result.code, 'do_not_honour');
  assert.ok(Object.values(CARDHOLDER_REASONS).includes(result.reason ?? ''));
});

test('[GW-17] enforced merchant: a scorer that throws holds, never approves', () => {
  const { gateway, queue } = build({ scorer: throwingScorer, rollout: enforce('m_electricals') });
  assert.equal(gateway.authorise(routine).status, 'held');
  assert.equal(queue.listHeld().length, 1);
});

test('[GW-18] enforced merchant: an out-of-range score holds, never approves', () => {
  const { gateway } = build({ scorer: fixedScorer(1500), rollout: enforce('m_electricals') });
  assert.equal(gateway.authorise(routine).status, 'held');
});

test('[GW-19] enforced merchant: a CARD_VELOCITY decline carries an allowlisted reason', () => {
  const { gateway } = build({ scorer: fixedScorer(100), rollout: enforce('m_cafe') });
  const at = Date.UTC(2026, 9, 3, 9, 0, 0);
  const attempt = (i: number) => gateway.authorise({
    pan: TEST_CARDS.mastercard, expiry: EXPIRY, amount: 1_000,
    merchantId: 'm_cafe', ipCountry: 'GB', at: at + i * 1_000,
  });
  for (let i = 0; i < 5; i += 1) assert.equal(attempt(i).status, 'approved');
  assert.deepEqual(attempt(5), {
    status: 'declined', code: 'do_not_honour', reason: CARDHOLDER_REASONS.decline_generic,
  });
});

test('[GW-20] no log line or span written during authorise holds a 16-digit PAN', () => {
  resetSinks();
  for (const score of [100, 500, 750, 900]) {
    const { gateway } = build({ scorer: fixedScorer(score), rollout: enforce('m_electricals') });
    gateway.authorise(travellerTelevision.request);
  }
  build({ scorer: fixedScorer(500) }).gateway.authorise(travellerTelevision.request);
  assert.ok(sinks.logs.length > 0);
  for (const { message } of sinks.logs) assert.doesNotMatch(message, /\d{16}/);
  for (const { attributes } of sinks.spans) assert.doesNotMatch(JSON.stringify(attributes), /\d{16}/);
});

test('[RR-01] RiskRules.evaluate declines the traveller by HIGH_VALUE_CROSS_BORDER unless it is switched off', () => {
  const input = { bin: '411111', last4: '1111', amount: 249_900, ipCountry: 'JP', merchantId: 'm_electricals', at: 0 };
  assert.deepEqual(new RiskRules().evaluate(input), { outcome: 'decline', rule: 'HIGH_VALUE_CROSS_BORDER' });
  assert.deepEqual(new RiskRules().evaluate(input, { highValueCrossBorder: false }), { outcome: 'approve' });
});

test('[RO-01] scoredDecides only for an enforced merchant in enforce mode', () => {
  assert.equal(scoredDecides(enforce('m_a'), 'm_a'), true);
  assert.equal(scoredDecides(enforce('m_a'), 'm_b'), false);
  assert.equal(scoredDecides({ mode: 'shadow', enforcedMerchants: new Set(['m_a']) }, 'm_a'), false);
  assert.equal(scoredDecides({ mode: 'v1', enforcedMerchants: new Set(['m_a']) }, 'm_a'), false);
});

test('[RO-02] the rollout is read from configuration and defaults to shadow with no merchants', () => {
  const fallback = rolloutFromEnv({});
  assert.equal(fallback.mode, 'shadow');
  assert.equal(fallback.enforcedMerchants.size, 0);
  const configured = rolloutFromEnv({ RISK_MODE: 'enforce', RISK_ENFORCED_MERCHANTS: 'm_a, m_b,' });
  assert.equal(configured.mode, 'enforce');
  assert.deepEqual([...configured.enforcedMerchants], ['m_a', 'm_b']);
  assert.throws(() => rolloutFromEnv({ RISK_MODE: 'enforced' }), /RISK_MODE/);
});

/** A gateway whose step-up provider, clock and answer timer the test controls. */
const buildStepUp = (provider: StepUpProvider = fakeProvider, score = 500) => {
  const payments = new PaymentsService();
  const audit = new InMemoryAuditLog();
  const queue = new InMemoryReviewQueue(audit, Date.now, payments);
  const clock = { now: Date.UTC(2026, 9, 3, 14, 0, 0) };
  const timers: Array<() => void> = [];
  const stepUp = new StepUpAdapter<AuthoriseRequest>(provider, {
    clock: () => clock.now,
    setTimer: fn => timers.push(fn),
    clearTimer: () => {},
  });
  const gateway = new AuthorisationGateway(payments, {
    scorer: fixedScorer(score),
    policy: new DecisionPolicy(DEFAULT_THRESHOLDS),
    stepUp, queue, audit,
    rollout: enforce('m_electricals'),
  });
  return { gateway, payments, audit, queue, stepUp, clock, timers };
};

const begun = (ctx = buildStepUp()) => {
  const result = ctx.gateway.authorise(travellerTelevision.request);
  assert.equal(result.status, 'step_up');
  return { ...ctx, id: result.status === 'step_up' ? result.challengeId : '' };
};

test('[SU-01] authenticated approves with one payment matching the request', () => {
  const { gateway, payments, id } = begun();
  assert.equal(id, 'chl_000001');
  const result = gateway.completeStepUp(id, 'authenticated');
  assert.equal(result.status, 'approved');
  if (result.status !== 'approved') return;
  assert.equal(result.payment.status, 'authorised');
  assert.equal(result.payment.authorised, travellerTelevision.request.amount);
  assert.equal(payments.payments.size, 1);
});

test('[SU-02] not_authenticated declines with the bank reason and creates no payment', () => {
  const { gateway, payments, id } = begun();
  assert.deepEqual(gateway.completeStepUp(id, 'not_authenticated'), {
    status: 'declined', code: 'do_not_honour', reason: "Your bank couldn't confirm this payment.",
  });
  assert.equal(payments.payments.size, 0);
});

test('[SU-02b] not_authenticated carries the allowlisted bank-could-not-confirm reason', () => {
  const { gateway, id } = begun();
  const result = gateway.completeStepUp(id, 'not_authenticated');
  assert.equal(result.status, 'declined');
  if (result.status !== 'declined') return;
  assert.equal(result.reason, CARDHOLDER_REASONS.step_up_not_confirmed);
  assert.doesNotThrow(() => assertCardholderReasonSafe(result.reason ?? ''));
});

test('[SU-03] unavailable holds, blocks capture and audits a hold', () => {
  const { gateway, payments, queue, audit, id } = begun();
  const result = gateway.completeStepUp(id, 'unavailable');
  assert.equal(result.status, 'held');
  if (result.status !== 'held') return;
  assert.equal(payments.isCaptureBlocked(result.payment.id), true);
  assert.equal(result.payment.authorised, travellerTelevision.request.amount);
  assert.equal(queue.listHeld()[0].merchantId, travellerTelevision.request.merchantId);
  assert.equal(audit.forSubject(result.reviewId)[0].action, 'hold');
});

test('[SU-04] cancelled declines with no payment and no ledger entries', () => {
  resetSinks();
  const { gateway, payments, id } = begun();
  assert.deepEqual(gateway.completeStepUp(id, 'cancelled'), { status: 'declined', code: 'do_not_honour' });
  assert.equal(payments.payments.size, 0);
  assert.equal(payments.ledger.entries.length, 0);
  assert.ok(sinks.logs.some(l => l.message.includes('stepup.cancelled')));
});

test('[SU-05] a second completeStepUp returns the first result and creates nothing', () => {
  const { gateway, payments, id } = begun();
  const first = gateway.completeStepUp(id, 'authenticated');
  assert.equal(gateway.completeStepUp(id, 'cancelled'), first);
  assert.equal(gateway.completeStepUp(id, 'authenticated'), first);
  assert.equal(payments.payments.size, 1);
});

test('[SU-06] an unknown challenge declines and logs stepup.unknown_challenge', () => {
  resetSinks();
  const { gateway } = buildStepUp();
  assert.deepEqual(gateway.completeStepUp('chl_999999', 'authenticated'), { status: 'declined', code: 'do_not_honour' });
  assert.ok(sinks.logs.some(l => l.message.includes('stepup.unknown_challenge') && l.message.includes('chl_999999')));
});

test('[SU-07] a provider that resolves unavailable holds, and completeStepUp returns that result', async () => {
  const { gateway, payments, queue, id } = begun(buildStepUp({ start: async () => 'unavailable' }));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(queue.listHeld().length, 1);
  const result = gateway.completeStepUp(id, 'authenticated');
  assert.equal(result.status, 'held');
  assert.equal(payments.payments.size, 1);
  assert.equal(queue.listHeld().length, 1);
  if (result.status !== 'held') return;
  assert.equal(result.payment.authorised, travellerTelevision.request.amount);
  assert.equal(payments.isCaptureBlocked(result.payment.id), true);
});

test('[SU-08] no provider answer within 10 seconds holds with capture blocked and a review item', () => {
  const { gateway, payments, queue, timers, id } = begun(buildStepUp({ start: () => new Promise(() => {}) }));
  assert.equal(timers.length, 1);
  timers[0]();
  assert.equal(queue.listHeld().length, 1);
  const result = gateway.completeStepUp(id, 'authenticated');
  assert.equal(result.status, 'held');
  if (result.status !== 'held') return;
  assert.equal(payments.isCaptureBlocked(result.payment.id), true);
  assert.equal(result.reviewId, queue.listHeld()[0].id);
});

test('[SU-09] no result from authorise or completeStepUp has a code other than do_not_honour', () => {
  for (const outcome of ['authenticated', 'not_authenticated', 'unavailable', 'cancelled'] as const) {
    const { gateway, id } = begun();
    const result = gateway.completeStepUp(id, outcome);
    if (result.status === 'declined') assert.equal(result.code, 'do_not_honour');
  }
  const unknown = buildStepUp().gateway.completeStepUp('nope', 'cancelled');
  assert.equal(unknown.status === 'declined' && unknown.code, 'do_not_honour');
});

test('[SU-10] after 10 minutes expireChallenges cancels the pending challenge', () => {
  const { gateway, stepUp, payments, clock, id } = begun();
  clock.now += 10 * 60 * 1000 + 1;
  gateway.expireChallenges();
  assert.equal(stepUp.get(id)?.status, 'cancelled');
  assert.equal(payments.payments.size, 0);
  assert.deepEqual(gateway.completeStepUp(id, 'authenticated'), { status: 'declined', code: 'do_not_honour' });
  assert.equal(payments.payments.size, 0);
});
