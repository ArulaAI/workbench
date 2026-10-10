/*
 * The narrative is wired through queue.onHeld, so it can never sit on the authorisation
 * path. AC8: no client call inside authorise. AC9: no card data or merchant descriptor in
 * the prompt. A failing client leaves the item held without a narrative.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { AuthorisationGateway } from '../src/payments/gateway.ts';
import { type AuthoriseRequest, PaymentsService } from '../src/payments/service.ts';
import { DEFAULT_THRESHOLDS, DecisionPolicy } from '../src/risk/policy.ts';
import { StepUpAdapter } from '../src/risk/stepup.ts';
import type { Scorer } from '../src/risk/scoring.ts';
import type { RiskRollout } from '../src/risk/rollout.ts';
import { type NarrativeClient, NarrativeWriter } from '../src/risk/narrative.ts';
import { InMemoryReviewQueue } from '../src/review/queue.ts';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { attachNarrativeWriter } from '../src/review/narrative-scheduler.ts';
import { TEST_CARDS } from './fixtures/cards.ts';
import { travellerTelevision } from './fixtures/traffic.ts';

const MERCHANT = 'm_electricals';
const DESCRIPTOR = 'ACME ELECTRICALS LTD*LONDON';

/** Deterministic stand-in for the Phase 1 scorer, keyed to the hold band. */
const stubScorer: Scorer = {
  score: () => ({ score: 750, reasons: ['country_mismatch'], modelVersion: 'stub-1' }),
};

const enforce: RiskRollout = { mode: 'enforce', enforcedMerchants: new Set([MERCHANT]) };

const flush = () => new Promise<void>(resolve => setImmediate(() => setImmediate(resolve)));

const build = (complete: (prompt: string) => Promise<string>) => {
  const prompts: string[] = [];
  const client: NarrativeClient = {
    complete: prompt => {
      prompts.push(prompt);
      return complete(prompt);
    },
  };
  const payments = new PaymentsService();
  const audit = new InMemoryAuditLog();
  const queue = new InMemoryReviewQueue(audit, Date.now, payments);
  const gateway = new AuthorisationGateway(payments, {
    scorer: stubScorer,
    policy: new DecisionPolicy(DEFAULT_THRESHOLDS),
    stepUp: new StepUpAdapter<AuthoriseRequest>({ start: async () => 'started' }, { setTimer: () => 0, clearTimer: () => {} }),
    queue,
    audit,
    rollout: enforce,
  });
  attachNarrativeWriter(queue, new NarrativeWriter(client), item => ({
    merchantCategory: item.merchantCategory,
    issuerCountry: item.issuerCountry,
    ipCountry: item.ipCountry,
  }));
  return { gateway, queue, prompts };
};

test('[NARR-INT-01] AC8: no client call inside authorise, one call after the event loop turns', async () => {
  const { gateway, queue, prompts } = build(async () => 'Held because the IP country differs from the issuer country.');
  const result = gateway.authorise(travellerTelevision.request);
  assert.equal(result.status, 'held');
  if (result.status !== 'held') return;
  assert.equal(prompts.length, 0);
  assert.equal(queue.get(result.reviewId)?.narrative, null);

  await flush();
  assert.equal(prompts.length, 1);
  assert.equal(queue.get(result.reviewId)?.narrative, 'Held because the IP country differs from the issuer country.');
});

test('[NARR-INT-02] AC9: the prompt carries no PAN, BIN, token, last four or merchant descriptor', async () => {
  const { gateway, queue, prompts } = build(async () => 'ok');
  const result = gateway.authorise({ ...travellerTelevision.request, merchantId: MERCHANT });
  assert.equal(result.status, 'held');
  if (result.status !== 'held') return;
  await flush();
  assert.equal(prompts.length, 1);
  const prompt = prompts[0];
  const pan = TEST_CARDS.visa;
  const item = queue.get(result.reviewId);
  assert.doesNotMatch(prompt, /\d{6,}/);
  assert.ok(!prompt.includes(pan.slice(0, 6)));
  assert.ok(!prompt.includes(pan.slice(-4)));
  assert.ok(!prompt.includes(result.payment.token));
  assert.ok(!prompt.includes(item?.maskedCard ?? 'unreachable'));
  assert.ok(!prompt.includes(MERCHANT));
  assert.ok(!prompt.includes(DESCRIPTOR));
});

test('[NARR-INT-03] a rejecting client leaves the item without a narrative and still listed', async () => {
  const { gateway, queue, prompts } = build(async () => { throw new Error('vendor down'); });
  const result = gateway.authorise(travellerTelevision.request);
  assert.equal(result.status, 'held');
  if (result.status !== 'held') return;
  await flush();
  assert.equal(prompts.length, 1);
  assert.equal(queue.get(result.reviewId)?.narrative ?? undefined, undefined);
  assert.ok(queue.listHeld().some(i => i.id === result.reviewId));
});
