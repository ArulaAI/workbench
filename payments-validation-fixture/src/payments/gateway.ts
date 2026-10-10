/*
 * The authorisation gateway. Every merchant authorisation passes through here before it
 * reaches the payments service.
 *
 * Risk rules v1 run first. What happens next depends on the rollout flag
 * (src/risk/rollout.ts, RFC F2.1 Migration Strategy):
 *
 *   v1       the rules decide, as before. The scorer is never called.
 *   shadow   the rules decide; the scored decision is computed and logged beside them.
 *   enforce  for an enforced merchant only CARD_VELOCITY runs, then the scored decision
 *            approves, steps up, holds or declines. Other merchants stay in shadow.
 *
 * A decline keeps the scheme code `do_not_honour`. A scored decline also carries a
 * cardholder reason from the allowlist in src/risk/reasons.ts, never the rule, the score
 * or a feature. Logs and spans carry the masked card only.
 */

import { type AuthoriseRequest, type Payment, PaymentsService } from './service.ts';
import type { GatewayResult } from './result.ts';
import { RiskRules, type RiskDecision, type RuleId } from '../risk/rules.ts';
import { type Scorer, toScoringInput } from '../risk/scoring.ts';
import type { DecisionPolicy, PolicyDecision } from '../risk/policy.ts';
import { ChallengeError, type StepUpAdapter, type StepUpChallenge } from '../risk/stepup.ts';
import { CARDHOLDER_REASONS, cardholderReason } from '../risk/reasons.ts';
import { DEFAULT_ROLLOUT, type RiskRollout, scoredDecides } from '../risk/rollout.ts';
import { issuerCountry } from '../risk/issuers.ts';
import type { BlockList } from '../risk/blocks.ts';
import { type AttemptRecorder, cardKeyOf } from '../risk/attempts.ts';
import type { DetectorConfig } from '../risk/detector-config.ts';
import type { Decision } from '../risk/types.ts';
import type { ReviewQueue } from '../review/queue.ts';
import type { AuditLog } from '../review/audit.ts';
import { tokenise } from '../vault.ts';
import { log, span } from '../obs/index.ts';

export type { GatewayResult } from './result.ts';

export type GatewayRequest = AuthoriseRequest & {
  merchantId: string;
  /** Country of the shopper's IP address, ISO 3166 alpha-2. */
  ipCountry: string;
  /** Epoch milliseconds. Defaults to now. */
  at?: number;
};

export type GatewayDeps = {
  scorer: Scorer;
  policy: DecisionPolicy;
  stepUp: StepUpAdapter<AuthoriseRequest>;
  queue: ReviewQueue;
  audit: AuditLog;
  rollout?: RiskRollout;
  /** The request carries no MCC, so the category comes from a lookup. Defaults to 'unknown'. */
  merchantCategory?: (merchantId: string) => string;
  rules?: RiskRules;
  /** F2.2 card-testing blocks, checked before any scoring. Requires detectorConfig. */
  blocks?: BlockList;
  /** F2.2 small-authorisation recording. Requires detectorConfig. */
  attempts?: AttemptRecorder;
  detectorConfig?: DetectorConfig;
};

const masked = (bin: string, last4: string): string => `${bin}******${last4}`;

/** Drop the gateway-only fields before the request reaches the payments service. */
const toAuthorise = (req: GatewayRequest): AuthoriseRequest => {
  const { merchantId: _merchant, ipCountry: _ip, at: _at, ...authorise } = req;
  return authorise;
};

export class AuthorisationGateway {
  readonly payments: PaymentsService;
  readonly rules: RiskRules;
  readonly scorer: Scorer;
  readonly policy: DecisionPolicy;
  readonly stepUp: StepUpAdapter<AuthoriseRequest>;
  readonly queue: ReviewQueue;
  readonly audit: AuditLog;
  readonly rollout: RiskRollout;
  private readonly merchantCategory: (merchantId: string) => string;
  private readonly blocks?: BlockList;
  private readonly attempts?: AttemptRecorder;
  private readonly detectorConfig?: DetectorConfig;
  /** Final result per challenge id, kept until the challenge expires. */
  private readonly stepUpResults = new Map<string, GatewayResult>();
  /** Challenges begun here that have no stored result yet. */
  private readonly openChallenges = new Set<string>();

  constructor(payments: PaymentsService, deps: GatewayDeps) {
    this.payments = payments;
    this.scorer = deps.scorer;
    this.policy = deps.policy;
    this.stepUp = deps.stepUp;
    this.queue = deps.queue;
    this.audit = deps.audit;
    this.rollout = deps.rollout ?? DEFAULT_ROLLOUT;
    this.merchantCategory = deps.merchantCategory ?? (() => 'unknown');
    this.rules = deps.rules ?? new RiskRules();
    if ((deps.blocks || deps.attempts) && !deps.detectorConfig) {
      throw new Error('AuthorisationGateway: blocks and attempts need a detectorConfig');
    }
    this.blocks = deps.blocks;
    this.attempts = deps.attempts;
    this.detectorConfig = deps.detectorConfig;
    this.stepUp.setOnUnavailable((c, request) => this.onChallengeUnavailable(c, request));
  }

  authorise(req: GatewayRequest): GatewayResult {
    const digits = req.pan.replace(/\D/g, '');
    const bin = digits.slice(0, 6);
    const last4 = digits.slice(-4);
    const card = masked(bin, last4);
    const input = {
      bin,
      last4,
      amount: req.amount,
      ipCountry: req.ipCountry,
      merchantId: req.merchantId,
      at: req.at ?? Date.now(),
    };

    const blocked = this.checkBlocks(req, input, card);
    if (blocked) return blocked;

    if (!scoredDecides(this.rollout, req.merchantId)) {
      const v1 = this.rules.evaluate(input);
      if (this.rollout.mode !== 'v1') this.recordShadow(req, v1, card);
      if (v1.outcome === 'decline') {
        this.recordDecline(v1.rule as RuleId, req.merchantId, card);
        return { status: 'declined', code: 'do_not_honour' };
      }
      return { status: 'approved', payment: this.payments.authorise(toAuthorise(req)) };
    }

    const velocity = this.rules.evaluate(input, { highValueCrossBorder: false });
    if (velocity.outcome === 'decline') {
      this.recordDecline(velocity.rule as RuleId, req.merchantId, card);
      return { status: 'declined', code: 'do_not_honour', reason: CARDHOLDER_REASONS.decline_generic };
    }

    const decision = this.decide(req);
    this.recordDecision(decision, req.merchantId, card);

    switch (decision.outcome) {
      case 'approve':
        return { status: 'approved', payment: this.payments.authorise(toAuthorise(req)) };
      case 'step_up': {
        const { token } = tokenise(req.pan, req.expiry);
        const meta = { amount: req.amount, currency: req.currency ?? 'GBP', merchantId: req.merchantId };
        // The whole request is held so a later hold (task 8) still has merchant and IP country.
        const challenge = this.stepUp.begin(req, decision, token, meta, 'policy');
        this.openChallenges.add(challenge.id);
        return { status: 'step_up', challengeId: challenge.id };
      }
      case 'hold':
        return this.hold(req, decision);
      case 'decline':
        return {
          status: 'declined',
          code: 'do_not_honour',
          reason: cardholderReason(decision.reasons[0] ?? 'issuer_unknown'),
        };
    }
  }

  /**
   * F2.2, before any scoring. A block match outside shadow mode becomes a step-up and never
   * reaches the scheme. Otherwise a small authorisation is recorded for the detector, and a
   * recorder failure never fails the authorisation.
   */
  private checkBlocks(
    req: GatewayRequest,
    input: { bin: string; last4: string; amount: number; merchantId: string; ipCountry: string; at: number },
    card: string,
  ): GatewayResult | undefined {
    const config = this.detectorConfig;
    if (!config) return undefined;

    const block = this.blocks?.matches({ bin: input.bin, amount: input.amount });
    span('risk.block_check', {
      merchantId: req.merchantId,
      card,
      matched: block !== undefined,
      attackId: block?.attackId,
      mode: config.mode,
    });

    if (block) {
      if (config.mode === 'shadow') {
        log.info(`card_testing.shadow_match ${card} at ${req.merchantId}: attack ${block.attackId}`);
        return undefined;
      }
      const decision: Decision = {
        outcome: 'step_up',
        score: 0,
        reasons: ['card_testing_pattern'],
        thresholdsVersion: config.version,
      };
      const { token } = tokenise(req.pan, req.expiry);
      const meta = { amount: req.amount, currency: req.currency ?? 'GBP', merchantId: req.merchantId };
      const challenge = this.stepUp.begin(req, decision, token, meta, 'block_match', block.attackId);
      this.openChallenges.add(challenge.id);
      return { status: 'step_up', challengeId: challenge.id };
    }

    if (this.attempts && input.amount <= config.smallAmountCeiling) {
      try {
        this.attempts.record({
          cardKey: cardKeyOf(input.bin, input.last4),
          bin: input.bin,
          amount: input.amount,
          merchantId: input.merchantId,
          ipCountry: input.ipCountry,
          at: input.at,
        });
      } catch {
        log.error('attempts.record_failed');
      }
    }
    return undefined;
  }

  /** Finish a step-up challenge once. A repeat call returns the first result unchanged. */
  completeStepUp(
    challengeId: string,
    outcome: 'authenticated' | 'not_authenticated' | 'unavailable' | 'cancelled',
  ): GatewayResult {
    const stored = this.stepUpResults.get(challengeId);
    if (stored) return stored;

    let completed: ReturnType<StepUpAdapter<AuthoriseRequest>['complete']>;
    try {
      completed = this.stepUp.complete(challengeId, outcome);
    } catch (error) {
      if (!(error instanceof ChallengeError)) throw error;
      log.info(`stepup.unknown_challenge ${challengeId}`);
      return { status: 'declined', code: 'do_not_honour' };
    }
    const { challenge } = completed;
    if (completed.repeat) return { status: 'declined', code: 'do_not_honour' };
    const request = completed.request as GatewayRequest;

    let result: GatewayResult;
    if (challenge.source === 'block_match' && outcome !== 'authenticated') {
      result = this.declineBlockMatch(challenge, request);
      this.storeStepUpResult(challengeId, result);
      return result;
    }
    switch (outcome) {
      case 'authenticated':
        result = { status: 'approved', payment: this.payments.authorise(toAuthorise(request)) };
        break;
      case 'not_authenticated':
        result = {
          status: 'declined',
          code: 'do_not_honour',
          reason: cardholderReason('step_up_not_confirmed'),
        };
        break;
      case 'unavailable':
        result = this.holdForUnavailable(challenge, request);
        break;
      case 'cancelled':
        log.info(`stepup.cancelled ${challengeId}`);
        result = { status: 'declined', code: 'do_not_honour' };
        break;
    }
    this.storeStepUpResult(challengeId, result);
    return result;
  }

  /** Cancel challenges past their 10-minute expiry and forget results of expired ones. */
  expireChallenges(): void {
    this.stepUp.expire();
    for (const id of this.openChallenges) {
      if (this.stepUp.get(id)?.status !== 'cancelled') continue;
      log.info(`stepup.cancelled ${id}`);
      this.storeStepUpResult(id, { status: 'declined', code: 'do_not_honour' });
    }
    for (const id of [...this.stepUpResults.keys()]) {
      if (!this.stepUp.get(id)) this.stepUpResults.delete(id);
    }
  }

  /** The provider did not answer. A block_match challenge is declined; a policy challenge is held. */
  private onChallengeUnavailable(challenge: StepUpChallenge<AuthoriseRequest>, request: AuthoriseRequest): void {
    if (this.stepUpResults.has(challenge.id)) return;
    const gatewayRequest = request as GatewayRequest;
    const result = challenge.source === 'block_match'
      ? this.declineBlockMatch(challenge, gatewayRequest)
      : this.holdForUnavailable(challenge, gatewayRequest);
    this.storeStepUpResult(challenge.id, result);
  }

  private holdForUnavailable(challenge: StepUpChallenge<AuthoriseRequest>, request: GatewayRequest): GatewayResult {
    return this.hold(request, challenge.decision);
  }

  /** A block-match challenge that was not passed: no review item, no authorisation. */
  private declineBlockMatch(challenge: StepUpChallenge<AuthoriseRequest>, request: GatewayRequest): GatewayResult {
    const digits = request.pan.replace(/\D/g, '');
    const card = masked(digits.slice(0, 6), digits.slice(-4));
    log.info(`card_testing.challenge_declined ${card}: attack ${challenge.attackId}`);
    span('card_testing.challenge_declined', { card, attackId: challenge.attackId });
    return { status: 'declined', code: 'do_not_honour', reason: cardholderReason('card_testing_pattern') };
  }

  private storeStepUpResult(id: string, result: GatewayResult): void {
    this.stepUpResults.set(id, result);
    this.openChallenges.delete(id);
    this.stepUp.release(id);
  }

  /** Score and apply the policy. A scorer that throws or returns garbage becomes a hold. */
  private decide(req: GatewayRequest): PolicyDecision {
    try {
      return this.policy.decide(this.scorer.score(toScoringInput(req, this.merchantCategory(req.merchantId))));
    } catch (error) {
      return this.policy.decide({ error });
    }
  }

  /**
   * Authorise, block capture and queue the payment for an analyst. The queue records the
   * audit 'hold' by 'system'.
   */
  private hold(req: GatewayRequest, decision: PolicyDecision): GatewayResult {
    const payment: Payment = this.payments.authorise(toAuthorise(req));
    this.payments.blockCapture(payment.id);
    const bin = req.pan.replace(/\D/g, '').slice(0, 6);
    const item = this.queue.hold({
      paymentId: payment.id,
      maskedCard: masked(bin, payment.last4),
      merchantId: req.merchantId,
      amount: req.amount,
      currency: payment.currency,
      score: decision.score,
      reasons: decision.reasons,
      merchantCategory: this.merchantCategory(req.merchantId),
      issuerCountry: issuerCountry(bin),
      ipCountry: req.ipCountry,
    });
    return { status: 'held', payment, reviewId: item.id };
  }

  /** Shadow mode: the scored decision is logged next to the v1 result and never changes it. */
  private recordShadow(req: GatewayRequest, v1: RiskDecision, card: string): void {
    const scored = this.decide(req);
    const v1Result = v1.rule ? `${v1.outcome} by ${v1.rule}` : v1.outcome;
    log.info(
      `risk.shadow ${card} at ${req.merchantId}: v1 ${v1Result}, scored ${scored.outcome} ` +
      `(${scored.score}, thresholds ${scored.thresholdsVersion})`,
    );
    span('risk.shadow', {
      merchantId: req.merchantId,
      card,
      v1Outcome: v1.outcome,
      v1Rule: v1.rule,
      outcome: scored.outcome,
      score: scored.score,
      reasons: scored.reasons,
      thresholdsVersion: scored.thresholdsVersion,
      scorerFailed: scored.scorerFailed ?? false,
    });
  }

  private recordDecision(decision: PolicyDecision, merchantId: string, card: string): void {
    log.info(
      `risk.decision ${card} at ${merchantId}: ${decision.outcome} ` +
      `(${decision.score}, thresholds ${decision.thresholdsVersion})`,
    );
    span('risk.decision', {
      merchantId,
      card,
      outcome: decision.outcome,
      score: decision.score,
      reasons: decision.reasons,
      thresholdsVersion: decision.thresholdsVersion,
      scorerFailed: decision.scorerFailed ?? false,
    });
  }

  private recordDecline(rule: RuleId, merchantId: string, card: string): void {
    log.info(`declined ${card} at ${merchantId} by ${rule}`);
    span('payment.decline', { rule, merchantId, card });
  }
}
