/*
 * The authorisation gateway. Every merchant authorisation passes through here before it
 * reaches the payments service.
 *
 * The gateway runs the v1 risk rules and either forwards the request or declines it.
 * A decline carries the generic scheme response `do_not_honour` and nothing else. The
 * rule that fired is logged for the fraud operations team but is never returned to the
 * merchant, so neither the merchant nor the cardholder learns why a payment failed.
 */

import { type AuthoriseRequest, type Payment, PaymentsService } from './service.ts';
import { RiskRules, type RuleId } from '../risk/rules.ts';
import { log, span } from '../obs/index.ts';

export type GatewayRequest = AuthoriseRequest & {
  merchantId: string;
  /** Country of the shopper's IP address, ISO 3166 alpha-2. */
  ipCountry: string;
  /** Epoch milliseconds. Defaults to now. */
  at?: number;
};

export type GatewayResult =
  | { status: 'approved'; payment: Payment }
  | { status: 'declined'; code: 'do_not_honour' };

export class AuthorisationGateway {
  readonly payments: PaymentsService;
  readonly rules: RiskRules;

  constructor(payments = new PaymentsService(), rules = new RiskRules()) {
    this.payments = payments;
    this.rules = rules;
  }

  authorise(req: GatewayRequest): GatewayResult {
    const digits = req.pan.replace(/\D/g, '');
    const bin = digits.slice(0, 6);
    const last4 = digits.slice(-4);

    const decision = this.rules.evaluate({
      bin,
      last4,
      amount: req.amount,
      ipCountry: req.ipCountry,
      merchantId: req.merchantId,
      at: req.at ?? Date.now(),
    });

    if (decision.outcome === 'decline') {
      this.recordDecline(decision.rule as RuleId, req.merchantId, `${bin}******${last4}`);
      return { status: 'declined', code: 'do_not_honour' };
    }

    const { merchantId: _merchant, ipCountry: _ip, at: _at, ...authorise } = req;
    return { status: 'approved', payment: this.payments.authorise(authorise) };
  }

  private recordDecline(rule: RuleId, merchantId: string, card: string): void {
    log.info(`declined ${card} at ${merchantId} by ${rule}`);
    span('payment.decline', { rule, merchantId, card });
  }
}
