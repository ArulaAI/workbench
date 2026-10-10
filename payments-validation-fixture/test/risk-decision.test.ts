/*
 * Fixture traffic replay: risk decision latency (40 ms budget) and data handling.
 *
 * The gateway runs in enforce mode for every merchant the fixtures use. The default is
 * shadow, where v1 rules decide and none of the step_up or held outcomes would appear.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { fileURLToPath } from 'node:url';
import { AuthorisationGateway, type GatewayRequest } from '../src/payments/gateway.ts';
import { type AuthoriseRequest, PaymentsService } from '../src/payments/service.ts';
import { ModelScorer, toScoringInput } from '../src/risk/scoring.ts';
import { DEFAULT_THRESHOLDS, DecisionPolicy } from '../src/risk/policy.ts';
import { StepUpAdapter, type StepUpProvider, type StepUpStartArgs } from '../src/risk/stepup.ts';
import { CARDHOLDER_REASONS } from '../src/risk/reasons.ts';
import { InMemoryReviewQueue } from '../src/review/queue.ts';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { cardTestingBurst, domesticGroceries, travellerTelevision } from './fixtures/traffic.ts';

const MODEL_PATH = fileURLToPath(new URL('./fixtures/model.json', import.meta.url));
const LATENCY_BUDGET_MS = 40;
const ITERATIONS = 1_000;

const traffic = (): GatewayRequest[] =>
  [travellerTelevision, domesticGroceries, ...cardTestingBurst()].map(t => t.request);

const merchants = (): Set<string> => new Set(traffic().map(r => r.merchantId));

const build = () => {
  const started: StepUpStartArgs[] = [];
  const provider: StepUpProvider = {
    start: async args => {
      started.push(args);
      return 'started';
    },
  };
  const payments = new PaymentsService();
  const audit = new InMemoryAuditLog();
  const queue = new InMemoryReviewQueue(audit, Date.now, payments);
  const stepUp = new StepUpAdapter<AuthoriseRequest>(provider, { setTimer: () => 0, clearTimer: () => {} });
  const gateway = new AuthorisationGateway(payments, {
    scorer: ModelScorer.load(MODEL_PATH),
    policy: new DecisionPolicy(DEFAULT_THRESHOLDS),
    stepUp,
    queue,
    audit,
    rollout: { mode: 'enforce', enforcedMerchants: merchants() },
  });
  return { gateway, started };
};

test('[RD-01] scorer plus policy p99 is under 40 ms over replayed traffic', () => {
  const scorer = ModelScorer.load(MODEL_PATH);
  const policy = new DecisionPolicy(DEFAULT_THRESHOLDS);
  const requests = traffic();
  const samples: number[] = [];
  for (let i = 0; i < ITERATIONS; i += 1) {
    const req = requests[i % requests.length];
    const start = performance.now();
    policy.decide(scorer.score(toScoringInput(req, 'unknown')));
    samples.push(performance.now() - start);
  }
  samples.sort((a, b) => a - b);
  const p99 = samples[Math.ceil(samples.length * 0.99) - 1];
  assert.ok(samples.length >= 1_000);
  assert.ok(p99 < LATENCY_BUDGET_MS, `p99 ${p99.toFixed(3)} ms exceeds ${LATENCY_BUDGET_MS} ms`);
});

test('[RD-02] every replayed result carries no reason or an allowlisted one', () => {
  const { gateway } = build();
  const allowed = new Set(Object.values(CARDHOLDER_REASONS));
  for (const request of traffic()) {
    const result = gateway.authorise(request);
    const reason = 'reason' in result ? result.reason : undefined;
    assert.ok(reason === undefined || allowed.has(reason), `unexpected reason ${JSON.stringify(reason)}`);
  }
});

test('[RD-03] the step-up provider never receives a PAN', () => {
  const { gateway, started } = build();
  for (const request of traffic()) gateway.authorise(request);
  assert.ok(started.length > 0, 'replay should reach the provider at least once');
  for (const args of started) assert.doesNotMatch(JSON.stringify(args), /\d{13,19}/);
});

test('[RD-04] the traveller is stepped up', () => {
  const { gateway } = build();
  assert.equal(gateway.authorise(travellerTelevision.request).status, 'step_up');
});

// Task 8 adds completeStepUp. Until it has merged this stays skipped.
const hasCompleteStepUp = typeof (AuthorisationGateway.prototype as { completeStepUp?: unknown }).completeStepUp === 'function';

test('[RD-05] the traveller is approved once step-up authenticates', { skip: !hasCompleteStepUp }, () => {
  const { gateway } = build();
  const first = gateway.authorise(travellerTelevision.request);
  assert.equal(first.status, 'step_up');
  const complete = (gateway as unknown as {
    completeStepUp(id: string, outcome: string): { status: string };
  }).completeStepUp;
  const { challengeId } = first as { challengeId: string };
  assert.equal(complete.call(gateway, challengeId, 'authenticated').status, 'approved');
});
