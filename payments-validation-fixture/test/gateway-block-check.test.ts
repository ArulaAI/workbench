/*
 * The gateway's F2.2 pre-scoring block check and small-authorisation recording.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { AuthorisationGateway } from '../src/payments/gateway.ts';
import { type AuthoriseRequest, PaymentsService } from '../src/payments/service.ts';
import { DEFAULT_THRESHOLDS, DecisionPolicy } from '../src/risk/policy.ts';
import { StepUpAdapter, type StepUpProvider } from '../src/risk/stepup.ts';
import { BlockList, InMemoryBlockStore } from '../src/risk/blocks.ts';
import { InMemoryAttackStore, type Attack } from '../src/risk/attacks.ts';
import { AttemptRecorder, InMemoryAttemptStore } from '../src/risk/attempts.ts';
import { type DetectorConfig, type DetectorMode, loadDetectorConfig } from '../src/risk/detector-config.ts';
import type { RiskRollout } from '../src/risk/rollout.ts';
import type { ScoringInput } from '../src/risk/types.ts';
import { InMemoryReviewQueue } from '../src/review/queue.ts';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { cardholderReason } from '../src/risk/reasons.ts';
import { resetSinks, sinks } from '../src/obs/index.ts';
import { EXPIRY } from './fixtures/cards.ts';
import { testingCard } from './fixtures/traffic.ts';

const baseConfig = loadDetectorConfig(
  JSON.parse(readFileSync(new URL('../config/detector.json', import.meta.url), 'utf8')),
);
const NOW = Date.UTC(2026, 9, 3, 14, 0, 0);
const fakeProvider: StepUpProvider = { start: async () => 'started' };

const countingScorer = () => {
  const s = {
    calls: 0,
    score(_input: ScoringInput) {
      s.calls += 1;
      return { score: 100, reasons: ['country_mismatch' as const], modelVersion: 'fixed-1' };
    },
  };
  return s;
};

const attack: Attack = {
  id: 'atk_000001', bin: '411111', amount: 100, firstSeenAt: NOW - 60_000, flaggedAt: NOW, cards: 12,
  merchants: [], status: 'blocked', releasedBy: null, releaseReason: null,
};

const build = (
  opts: { mode?: DetectorMode; block?: boolean; attempts?: AttemptRecorder; provider?: StepUpProvider; fireTimers?: boolean; rollout?: RiskRollout; score?: number } = {},
) => {
  const config: DetectorConfig = { ...baseConfig, mode: opts.mode ?? 'block' };
  const payments = new PaymentsService();
  let authoriseCalls = 0;
  const realAuthorise = payments.authorise.bind(payments);
  payments.authorise = (req: AuthoriseRequest) => { authoriseCalls += 1; return realAuthorise(req); };
  const audit = new InMemoryAuditLog();
  const queue = new InMemoryReviewQueue(audit, () => NOW, payments);
  const timers: Array<() => void> = [];
  const stepUp = new StepUpAdapter<AuthoriseRequest>(opts.provider ?? fakeProvider, {
    setTimer: opts.fireTimers ? (fn: () => void) => timers.push(fn) : () => 0,
    clearTimer: () => {},
  });
  const blocks = new BlockList(new InMemoryBlockStore(), new InMemoryAttackStore(), audit, config, () => NOW);
  if (opts.block ?? true) {
    blocks.createFor(attack);
    blocks.refresh(NOW);
  }
  const attemptStore = new InMemoryAttemptStore();
  const attempts = opts.attempts ?? new AttemptRecorder(attemptStore, config, () => NOW);
  const scorer = countingScorer();
  if (opts.score !== undefined) scorer.score = (_i: ScoringInput) => {
    scorer.calls += 1;
    return { score: opts.score as number, reasons: ['country_mismatch' as const], modelVersion: 'fixed-1' };
  };
  const gateway = new AuthorisationGateway(payments, {
    scorer,
    policy: new DecisionPolicy(DEFAULT_THRESHOLDS),
    stepUp,
    queue,
    audit,
    blocks,
    attempts,
    detectorConfig: config,
    rollout: opts.rollout,
  });
  return { gateway, payments, stepUp, queue, fireTimers: () => timers.forEach(f => f()), scorer, attempts, attemptStore, authoriseCalls: () => authoriseCalls };
};

const onBlockedBin = (amount: number): Parameters<AuthorisationGateway['authorise']>[0] => ({
  pan: testingCard(1), expiry: EXPIRY, amount, currency: 'GBP',
  merchantId: 'm_01', ipCountry: 'GB', at: NOW + 1_000,
});

test('[BC-01] block mode: a 1.00 GBP request on the blocked BIN steps up and never reaches the scheme', () => {
  const { gateway, payments, scorer, authoriseCalls } = build();
  const result = gateway.authorise(onBlockedBin(100));
  assert.equal(result.status, 'step_up');
  assert.equal(authoriseCalls(), 0);
  assert.equal(payments.payments.size, 0);
  assert.equal(scorer.calls, 0);
});

test('[BC-02] the block-match challenge has source block_match, card_testing_pattern and the attack id', () => {
  const { gateway, stepUp } = build();
  const result = gateway.authorise(onBlockedBin(100));
  assert.equal(result.status, 'step_up');
  if (result.status !== 'step_up') return;
  const challenge = stepUp.get(result.challengeId);
  assert.ok(challenge);
  assert.equal(challenge.source, 'block_match');
  assert.equal(challenge.attackId, 'atk_000001');
  assert.deepEqual(challenge.decision, {
    outcome: 'step_up', score: 0, reasons: ['card_testing_pattern'], thresholdsVersion: baseConfig.version,
  });
  assert.match(challenge.token, /^tok_/);
});

test('[BC-03] shadow mode: the same request goes to scoring and the shadow match is logged', () => {
  resetSinks();
  const { gateway, scorer, authoriseCalls } = build({ mode: 'shadow' });
  const result = gateway.authorise(onBlockedBin(100));
  assert.notEqual(result.status, 'step_up');
  assert.equal(scorer.calls, 1);
  assert.equal(authoriseCalls(), 1);
  const line = sinks.logs.find(l => l.message.startsWith('card_testing.shadow_match'));
  assert.ok(line);
  assert.match(line.message, /411111\*{6}\d{4}/);
  assert.doesNotMatch(line.message, /\d{13,}/);
  assert.equal(sinks.spans.filter(s => s.name === 'risk.block_check').length, 1);
});

test('[BC-04] a 2,499 GBP request on the blocked BIN is not affected by the block', () => {
  const { gateway, scorer, stepUp } = build();
  const result = gateway.authorise(onBlockedBin(249_900));
  assert.notEqual(result.status, 'step_up');
  assert.equal(scorer.calls, 1);
  assert.equal(stepUp.get('chl_000001'), undefined);
});

test('[BC-05] a small request with no block records one attempt', () => {
  const { gateway, attempts, attemptStore } = build({ block: false });
  const result = gateway.authorise(onBlockedBin(100));
  assert.equal(result.status, 'approved');
  attempts.flush();
  const recorded = attemptStore.since(0);
  assert.equal(recorded.length, 1);
  assert.deepEqual(recorded[0], {
    cardKey: `411111:${testingCard(1).slice(-4)}`, bin: '411111', amount: 100,
    merchantId: 'm_01', ipCountry: 'GB', at: NOW + 1_000,
  });
});

test('[BC-06] an AttemptRecorder that throws does not fail the authorisation', () => {
  const throwing = { record: () => { throw new Error('store down'); } } as unknown as AttemptRecorder;
  const { gateway } = build({ block: false, attempts: throwing });
  assert.equal(gateway.authorise(onBlockedBin(100)).status, 'approved');
});

test('[BC-07] a request above the small-amount ceiling records no attempt', () => {
  const { gateway, attempts, attemptStore } = build({ block: false });
  gateway.authorise(onBlockedBin(baseConfig.smallAmountCeiling + 1));
  attempts.flush();
  assert.equal(attemptStore.since(0).length, 0);
});

const challengeOf = (gateway: AuthorisationGateway): string => {
  const result = gateway.authorise(onBlockedBin(100));
  assert.equal(result.status, 'step_up');
  return result.status === 'step_up' ? result.challengeId : '';
};

const declined = {
  status: 'declined', code: 'do_not_honour', reason: cardholderReason('card_testing_pattern'),
};

test('[BC-08] block-match authenticated returns approved with an authorised payment', () => {
  const { gateway, payments, authoriseCalls } = build();
  const result = gateway.completeStepUp(challengeOf(gateway), 'authenticated');
  assert.equal(result.status, 'approved');
  assert.equal(authoriseCalls(), 1);
  assert.equal(payments.payments.size, 1);
});

test('[BC-09] block-match not_authenticated and cancelled decline with the card_testing_pattern reason', () => {
  for (const outcome of ['not_authenticated', 'cancelled'] as const) {
    resetSinks();
    const { gateway, authoriseCalls } = build();
    assert.deepEqual(gateway.completeStepUp(challengeOf(gateway), outcome), declined);
    assert.equal(authoriseCalls(), 0);
    const line = sinks.logs.find(l => l.message.startsWith('card_testing.challenge_declined'));
    assert.ok(line);
    assert.match(line.message, /411111\*{6}\d{4}.*atk_000001/);
  }
});

test('[BC-10] block-match unavailable declines with no review item and no authorise', () => {
  const { gateway, queue, authoriseCalls } = build();
  assert.deepEqual(gateway.completeStepUp(challengeOf(gateway), 'unavailable'), declined);
  assert.equal(authoriseCalls(), 0);
  assert.equal(queue.listHeld().length, 0);
});

test('[BC-11] block-match: a provider that resolves unavailable, or times out, is declined and stored', async () => {
  const unavailable = build({ provider: { start: async () => 'unavailable' } });
  const id = challengeOf(unavailable.gateway);
  await new Promise(r => setImmediate(r));
  assert.deepEqual(unavailable.gateway.completeStepUp(id, 'authenticated'), declined);
  assert.equal(unavailable.authoriseCalls(), 0);
  assert.equal(unavailable.queue.listHeld().length, 0);

  const silent = build({ provider: { start: () => new Promise(() => {}) }, fireTimers: true });
  const id2 = challengeOf(silent.gateway);
  silent.fireTimers();
  assert.deepEqual(silent.gateway.completeStepUp(id2, 'authenticated'), declined);
  assert.equal(silent.authoriseCalls(), 0);
  assert.equal(silent.queue.listHeld().length, 0);
});

test('[BC-12] a policy challenge completed unavailable is still held', () => {
  const { gateway, queue } = build({
    block: false, score: 500, rollout: { mode: 'enforce', enforcedMerchants: new Set(['m_01']) },
  });
  const result = gateway.authorise({ ...onBlockedBin(249_900) });
  assert.equal(result.status, 'step_up');
  if (result.status !== 'step_up') return;
  assert.equal(gateway.completeStepUp(result.challengeId, 'unavailable').status, 'held');
  assert.equal(queue.listHeld().length, 1);
});

test('[BC-13] a second completeStepUp on a block-match challenge returns the first result', () => {
  const { gateway, authoriseCalls } = build();
  const id = challengeOf(gateway);
  const first = gateway.completeStepUp(id, 'authenticated');
  assert.equal(first.status, 'approved');
  assert.equal(gateway.completeStepUp(id, 'not_authenticated'), first);
  assert.equal(authoriseCalls(), 1);
});
