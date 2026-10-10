/*
 * F2.2 card-testing replay acceptance suite: the criteria not already covered by GW-05 and
 * GW-06. AC1, AC4, AC5, AC8, AC9, AC10 and AC11, release then resume, and variant bursts.
 *
 * Every test builds an explicit enforce rollout over every merchant the fixtures use,
 * because the default rollout is shadow, where v1 rules decide and the step-up and hold
 * assertions would not hold. Time is a fake clock stepped in one-second ticks.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { AuthorisationGateway, type GatewayRequest, type GatewayResult } from '../src/payments/gateway.ts';
import { type AuthoriseRequest, PaymentsService } from '../src/payments/service.ts';
import { ModelScorer, type Scorer } from '../src/risk/scoring.ts';
import { DEFAULT_THRESHOLDS, DecisionPolicy } from '../src/risk/policy.ts';
import { StepUpAdapter, type StepUpProvider } from '../src/risk/stepup.ts';
import { CARDHOLDER_REASONS } from '../src/risk/reasons.ts';
import { CardTestingRuntime, InMemoryDetectorLease } from '../src/risk/card-testing-runtime.ts';
import { AttemptRecorder, InMemoryAttemptStore } from '../src/risk/attempts.ts';
import { type Attack, AttackDetector, InMemoryAttackStore } from '../src/risk/attacks.ts';
import { BlockList, InMemoryBlockStore } from '../src/risk/blocks.ts';
import { type DetectorMode, loadDetectorConfig } from '../src/risk/detector-config.ts';
import {
  type CardTestingNotice, type MerchantMessageType, type MerchantNotificationService, MerchantNotifier,
} from '../src/notify/merchant.ts';
import { InMemoryReviewQueue } from '../src/review/queue.ts';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { AttacksConsole } from '../src/review/attacks.ts';
import { EXPIRY } from './fixtures/cards.ts';
import {
  cardTestingBurst, domesticGroceries, genuineFlashSale, testingCard, travellerTelevision,
} from './fixtures/traffic.ts';

const detectorBase = JSON.parse(readFileSync(new URL('../config/detector.json', import.meta.url), 'utf8'));
const MODEL_PATH = fileURLToPath(new URL('./fixtures/model.json', import.meta.url));
const MINUTE = 60_000;

const MERCHANTS = [
  ...Array.from({ length: 20 }, (_, i) => `m_${String(i).padStart(2, '0')}`),
  ...Array.from({ length: 8 }, (_, i) => `m_flash_${String(i).padStart(2, '0')}`),
  'm_electricals',
  'm_grocer',
];

const approvingScorer: Scorer = { score: () => ({ score: 100, reasons: ['country_mismatch' as const], modelVersion: 'fixed-1' }) };

/** A notification service that stamps each notice with the fake clock. */
class TimedSink implements MerchantNotificationService {
  readonly sent: { merchantId: string; payload: CardTestingNotice; at: number }[] = [];
  private readonly clock: () => number;
  constructor(clock: () => number) { this.clock = clock; }
  send(merchantId: string, _type: MerchantMessageType, payload: CardTestingNotice): void {
    this.sent.push({ merchantId, payload: { ...payload }, at: this.clock() });
  }
}

const build = (opts: { mode?: DetectorMode; scorer?: Scorer; provider?: StepUpProvider; fireTimers?: boolean } = {}) => {
  const time = { now: 0 };
  const clock = () => time.now;
  const config = loadDetectorConfig({ ...detectorBase, mode: opts.mode ?? 'block' });
  const attemptStore = new InMemoryAttemptStore();
  const blockStore = new InMemoryBlockStore();
  const attackStore = new InMemoryAttackStore();
  const payments = new PaymentsService();
  const audit = new InMemoryAuditLog();
  const queue = new InMemoryReviewQueue(audit, clock, payments);
  const timers: Array<() => void> = [];
  const stepUp = new StepUpAdapter<AuthoriseRequest>(opts.provider ?? { start: async () => 'started' }, {
    clock,
    setTimer: opts.fireTimers ? (fn: () => void) => timers.push(fn) : () => 0,
    clearTimer: () => {},
  });
  const recorder = new AttemptRecorder(attemptStore, config, clock);
  const blocks = new BlockList(blockStore, attackStore, audit, config, clock);
  const detector = new AttackDetector(attemptStore, attackStore, config, clock);
  const sink = new TimedSink(clock);
  const notifier = new MerchantNotifier(sink, attackStore, detector, config, clock);
  const runtime = new CardTestingRuntime({
    recorder, detector, blocks, notifier, lease: new InMemoryDetectorLease(config.refreshIntervalMs),
    config, clock, logger: { info: () => {}, alert: () => {} },
  });
  const gateway = new AuthorisationGateway(payments, {
    scorer: opts.scorer ?? approvingScorer,
    policy: new DecisionPolicy(DEFAULT_THRESHOLDS),
    stepUp, queue, audit, blocks, attempts: recorder, detectorConfig: config,
    rollout: { mode: 'enforce', enforcedMerchants: new Set(MERCHANTS) },
  });
  const attacksConsole = new AttacksConsole(attackStore, blocks, audit, clock);
  return {
    time, clock, config, gateway, runtime, blocks, attackStore, audit, queue, payments, sink, stepUp,
    timers, attacksConsole,
  };
};
type Harness = ReturnType<typeof build>;

/** Advance the fake clock to `to`, ticking the runtime every second on the way. */
const advanceTo = (h: Harness, to: number): void => {
  for (let t = h.time.now + 1_000; t <= to; t += 1_000) {
    h.time.now = t;
    h.runtime.tick(t);
  }
  h.time.now = to;
};

/** Replay labelled traffic in order, ticking every second up to each attempt. */
const replay = (h: Harness, traffic: { request: GatewayRequest }[]): GatewayResult[] => {
  h.time.now = traffic[0].request.at! - 1_000;
  return traffic.map(({ request }) => {
    advanceTo(h, request.at!);
    return h.gateway.authorise(request);
  });
};

const shifted = (traffic: ReturnType<typeof cardTestingBurst>, ms: number) =>
  traffic.map(t => ({ ...t, request: { ...t.request, at: t.request.at! + ms } }));

const blockedAttacks = (h: Harness): Attack[] => h.attackStore.listByStatus('blocked');

test('[CT-01] AC1: the 3 October replay is flagged within 60 s of its first attempt', () => {
  const h = build();
  replay(h, cardTestingBurst(40));
  const attacks = blockedAttacks(h);
  assert.equal(attacks.length, 1);
  assert.ok(attacks[0].flaggedAt - attacks[0].firstSeenAt <= 60_000,
    `flagged ${attacks[0].flaggedAt - attacks[0].firstSeenAt} ms after the first attempt`);
});

test('[CT-02] AC4: during an active block the traveller is stepped up by policy and groceries are approved', () => {
  const h = build({ scorer: ModelScorer.load(MODEL_PATH) });
  const burst = cardTestingBurst(40);
  replay(h, burst);
  assert.equal(blockedAttacks(h).length, 1);
  assert.ok(h.blocks.matches({ bin: '411111', amount: 100 }), 'the block is active');

  const traveller = h.gateway.authorise(travellerTelevision.request);
  assert.equal(traveller.status, 'step_up');
  if (traveller.status !== 'step_up') return;
  assert.equal(h.stepUp.get(traveller.challengeId)?.source, 'policy');

  assert.equal(h.gateway.authorise(domesticGroceries.request).status, 'approved');
});

test('[CT-03] AC5: block_and_notify sends each affected merchant one initial notice within 15 minutes, with no card data', () => {
  const h = build({ mode: 'block_and_notify' });
  replay(h, cardTestingBurst(40));
  const [attack] = blockedAttacks(h);
  assert.ok(attack);
  advanceTo(h, attack.flaggedAt + 15 * MINUTE);

  const affected = attack.merchants.map(m => m.merchantId);
  assert.ok(affected.length >= 5);
  for (const merchantId of affected) {
    const notices = h.sink.sent.filter(n => n.merchantId === merchantId && n.payload.attackId === attack.id);
    assert.equal(notices.length, 1, `${merchantId} got ${notices.length} notices`);
    assert.ok(notices[0].at - attack.flaggedAt <= 15 * MINUTE);
  }
  assert.equal(h.sink.sent.length, affected.length);

  for (const { payload } of h.sink.sent) {
    assert.deepEqual(Object.keys(payload).sort(), ['attackId', 'attempts', 'windowEnd', 'windowStart']);
    const snapshot = JSON.stringify(payload);
    assert.doesNotMatch(snapshot, /411111/);
    assert.doesNotMatch(snapshot, /\d{6}\*+\d{4}/);
  }
});

test('[CT-04] AC8: after blockTtlMs the block expires, an audit expire entry is written and the next burst attempt is not challenged', () => {
  const h = build();
  replay(h, cardTestingBurst(40));
  const [attack] = blockedAttacks(h);
  assert.ok(attack);
  assert.equal(h.gateway.authorise({ ...cardTestingBurst(1)[0].request, pan: testingCard(70), at: h.time.now }).status, 'step_up');

  advanceTo(h, attack.flaggedAt + h.config.blockTtlMs);

  assert.equal(h.attackStore.get(attack.id)?.status, 'expired');
  const expiry = h.audit.forSubject(attack.id).filter(e => e.action === 'expire');
  assert.equal(expiry.length, 1);
  assert.equal(expiry[0].actor, 'system');
  assert.equal(h.blocks.matches({ bin: '411111', amount: 100 }), undefined);
  const next = h.gateway.authorise({ ...cardTestingBurst(1)[0].request, pan: testingCard(71), at: h.time.now });
  assert.equal(next.status, 'approved');
});

test('[CT-05] AC9: the block check adds under 1 ms p99 across 10,000 calls', () => {
  const withBlocks = build();
  replay(withBlocks, cardTestingBurst(40));
  assert.ok(withBlocks.blocks.matches({ bin: '411111', amount: 100 }));

  const baseline = build();
  const ITERATIONS = 10_000;
  const p99 = (samples: number[]): number => {
    const sorted = [...samples].sort((a, b) => a - b);
    return sorted[Math.ceil(sorted.length * 0.99) - 1];
  };

  // Amounts above the ceiling miss the block and skip attempt recording, so the only
  // difference between the two gateways is the block check itself.
  const request = (i: number): GatewayRequest => ({
    ...domesticGroceries.request, pan: testingCard(5_000 + i), amount: 6_420, at: withBlocks.time.now,
  });
  const matchSamples: number[] = [];
  const gatewayWith: number[] = [];
  const gatewayWithout: number[] = [];
  for (let i = 0; i < ITERATIONS; i += 1) {
    const hit = i % 2 === 0;
    let start = performance.now();
    withBlocks.blocks.matches({ bin: hit ? '411111' : '555555', amount: hit ? 100 : 6_420 });
    matchSamples.push(performance.now() - start);

    start = performance.now();
    withBlocks.gateway.authorise(request(i));
    gatewayWith.push(performance.now() - start);

    baseline.time.now = withBlocks.time.now;
    start = performance.now();
    baseline.gateway.authorise(request(i));
    gatewayWithout.push(performance.now() - start);
  }
  const overhead = Math.max(0, p99(gatewayWith) - p99(gatewayWithout)) + p99(matchSamples);
  assert.ok(overhead < 1, `block check p99 overhead ${overhead.toFixed(3)} ms`);
});

test('[CT-06] AC10: a flash-sale payment matching the block returns step_up, and authenticating it approves', () => {
  const h = build();
  replay(h, cardTestingBurst(40));
  assert.equal(blockedAttacks(h).length, 1);

  const sale = genuineFlashSale(1)[0];
  const result = h.gateway.authorise({ ...sale.request, at: h.time.now });
  assert.equal(result.status, 'step_up');
  if (result.status !== 'step_up') return;
  const challenge = h.stepUp.get(result.challengeId);
  assert.equal(challenge?.source, 'block_match');
  assert.equal(challenge?.attackId, blockedAttacks(h)[0].id);

  const final = h.gateway.completeStepUp(result.challengeId, 'authenticated');
  assert.equal(final.status, 'approved');
});

test('[CT-07] AC11: an unavailable block-match challenge is declined with the card-testing reason and creates no review item', () => {
  const h = build();
  replay(h, cardTestingBurst(40));
  const before = h.payments.payments.size;
  const sale = genuineFlashSale(2);

  const first = h.gateway.authorise({ ...sale[0].request, at: h.time.now });
  assert.equal(first.status, 'step_up');
  if (first.status !== 'step_up') return;
  const unavailable = h.gateway.completeStepUp(first.challengeId, 'unavailable');
  assert.equal(unavailable.status, 'declined');
  if (unavailable.status !== 'declined') return;
  assert.equal(unavailable.code, 'do_not_honour');
  assert.equal(unavailable.reason, CARDHOLDER_REASONS.card_testing_pattern);

  assert.equal(h.queue.listHeld().length, 0);
  assert.equal(h.payments.payments.size, before);
});

test('[CT-08] AC11: a block-match challenge that times out is declined with the card-testing reason and creates no review item', () => {
  const h = build({ fireTimers: true });
  replay(h, cardTestingBurst(40));
  const before = h.payments.payments.size;
  h.timers.length = 0;

  const result = h.gateway.authorise({ ...genuineFlashSale(1)[0].request, at: h.time.now });
  assert.equal(result.status, 'step_up');
  if (result.status !== 'step_up') return;
  assert.equal(h.timers.length, 1);
  h.timers[0]();

  const final = h.gateway.completeStepUp(result.challengeId, 'authenticated');
  assert.equal(final.status, 'declined');
  if (final.status !== 'declined') return;
  assert.equal(final.reason, CARDHOLDER_REASONS.card_testing_pattern);
  assert.equal(h.queue.listHeld().length, 0);
  assert.equal(h.payments.payments.size, before);
});

test('[CT-09] release then resume: renewed traffic after AttacksConsole.release produces a new attack id', () => {
  const h = build();
  replay(h, cardTestingBurst(40));
  const [first] = blockedAttacks(h);
  assert.ok(first);

  h.attacksConsole.release(first.id, { analyst: 'ana', authenticated: true }, 'confirmed false positive');
  assert.equal(h.attackStore.get(first.id)?.status, 'released');
  assert.equal(h.blocks.matches({ bin: '411111', amount: 100 }), undefined);

  replay(h, shifted(cardTestingBurst(40), 10 * MINUTE));
  const active = blockedAttacks(h);
  assert.equal(active.length, 1);
  assert.notEqual(active[0].id, first.id);
  assert.equal(h.attackStore.get(first.id)?.status, 'released');
});

test('[CT-10] variant bursts with two BINs and varying amounts: records which variants are caught', (t) => {
  const luhn = (body: string): string => {
    let sum = 0;
    for (let i = 0; i < body.length; i += 1) {
      let d = body.charCodeAt(body.length - 1 - i) - 48;
      if (i % 2 === 0) { d *= 2; if (d > 9) d -= 9; }
      sum += d;
    }
    return body + String((10 - (sum % 10)) % 10);
  };
  const variants = [
    { bin: '411111', amounts: [100, 100, 100, 150] },
    { bin: '520000', amounts: [100, 150, 200, 250] },
  ];
  const base = cardTestingBurst(1)[0].request.at!;
  const traffic = Array.from({ length: 80 }, (_, i) => {
    const v = variants[i % 2];
    const n = Math.floor(i / 2);
    return {
      request: {
        pan: luhn(`${v.bin}${String(200_000 + n).padStart(9, '0')}`), expiry: EXPIRY,
        amount: v.amounts[n % v.amounts.length], currency: 'GBP',
        merchantId: `m_${String(n % 20).padStart(2, '0')}`, ipCountry: ['GB', 'NL', 'US', 'DE'][n % 4],
        at: base + i * 4_000,
      },
    };
  });

  const h = build();
  replay(h, traffic);
  const flagged = h.attackStore.listByStatus('blocked');
  const caught = flagged.map(a => `${a.bin}/${a.amount}`).sort();
  const seen = new Set(traffic.map(t => `${t.request.pan.slice(0, 6)}/${t.request.amount}`));
  const missed = [...seen].filter(v => !caught.includes(v)).sort();
  t.diagnostic(`caught variants: ${caught.join(', ') || 'none'}; not caught: ${missed.join(', ') || 'none'}`);

  for (const a of flagged) {
    assert.ok(seen.has(`${a.bin}/${a.amount}`), `attack ${a.id} is for an unknown variant`);
    assert.ok(a.flaggedAt - a.firstSeenAt <= h.config.windowMs);
  }
});
