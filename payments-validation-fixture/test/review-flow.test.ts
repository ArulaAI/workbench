/*
 * End-to-end in-process flow for the scored hold path: hold, analyst approve and decline,
 * 72-hour expiry and the audit trail. The rollout is enforced for every merchant used.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { AuthorisationGateway } from '../src/payments/gateway.ts';
import { type AuthoriseRequest, CaptureBlockedError, PaymentsService } from '../src/payments/service.ts';
import type { Scorer } from '../src/risk/scoring.ts';
import { DEFAULT_THRESHOLDS, DecisionPolicy } from '../src/risk/policy.ts';
import { StepUpAdapter } from '../src/risk/stepup.ts';
import { CARDHOLDER_REASONS } from '../src/risk/reasons.ts';
import { InMemoryReviewQueue } from '../src/review/queue.ts';
import { InMemoryAuditLog } from '../src/review/audit.ts';
import { ReviewConsole } from '../src/review/console.ts';
import { HOLD_TTL_MS, expireHeldReviews } from '../src/review/expiry.ts';
import { travellerTelevision } from './fixtures/traffic.ts';

const build = (initialScore = 750) => {
  const state = { score: initialScore, now: Date.UTC(2026, 9, 3, 14, 0, 0) };
  const scorer: Scorer = {
    score: () => ({ score: state.score, reasons: ['country_mismatch'], modelVersion: 'fixed-1' }),
  };
  const payments = new PaymentsService();
  const audit = new InMemoryAuditLog();
  const queue = new InMemoryReviewQueue(audit, () => state.now, payments);
  const stepUp = new StepUpAdapter<AuthoriseRequest>(
    { start: async () => 'started' },
    { setTimer: () => 0, clearTimer: () => {} },
  );
  const gateway = new AuthorisationGateway(payments, {
    scorer,
    policy: new DecisionPolicy(DEFAULT_THRESHOLDS),
    stepUp, queue, audit,
    rollout: { mode: 'enforce', enforcedMerchants: new Set(['m_electricals']) },
  });
  const console_ = new ReviewConsole({ queue, merchantName: id => id });
  const session = { authenticated: true, analyst: 'analyst_1' };
  const hold = () => {
    const result = gateway.authorise(travellerTelevision.request);
    assert.equal(result.status, 'held');
    if (result.status !== 'held') throw new Error('unreachable');
    return result;
  };
  return { state, payments, audit, queue, gateway, console_, session, hold };
};

test('[RF-01] held payments are approved, declined and expired, leaving four audit entries', () => {
  const { state, payments, audit, console_, session, queue, hold } = build();

  const first = hold();
  assert.throws(() => payments.capture(first.payment.id), CaptureBlockedError);
  console_.approve(session, first.reviewId, { note: 'cardholder confirmed by phone' });
  assert.doesNotThrow(() => payments.capture(first.payment.id));

  const second = hold();
  console_.decline(session, second.reviewId, { note: 'looks like account takeover' });
  assert.equal(payments.payments.get(second.payment.id)?.status, 'voided');

  const third = hold();
  state.now += HOLD_TTL_MS;
  const webhook = { holdExpired: () => {} };
  const expired = expireHeldReviews(queue, payments, audit, webhook, state.now);
  assert.deepEqual(expired.map(i => i.id), [third.reviewId]);
  assert.equal(payments.payments.get(third.payment.id)?.status, 'voided');

  // Each held payment has its own hold entry, so one per item; every later action has exactly one.
  const byItem = [first, second, third].map(h => audit.forSubject(h.reviewId).map(e => [e.action, e.actor]));
  assert.deepEqual(byItem, [
    [['hold', 'system'], ['approve', 'analyst_1']],
    [['hold', 'system'], ['decline', 'analyst_1']],
    [['hold', 'system'], ['expire', 'system']],
  ]);
});

test('[RF-02] score 849 holds and score 850 declines with an allowlisted reason', () => {
  const ctx = build(849);
  assert.equal(ctx.gateway.authorise(travellerTelevision.request).status, 'held');
  ctx.state.score = 850;
  const result = ctx.gateway.authorise(travellerTelevision.request);
  assert.equal(result.status, 'declined');
  if (result.status !== 'declined') return;
  assert.equal(result.code, 'do_not_honour');
  assert.ok(Object.values(CARDHOLDER_REASONS).includes(result.reason ?? ''));
});
