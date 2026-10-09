/*
 * The four invariants after a fixed scenario. Plan 3.7, satisfying FR-9 and FR-15.
 * A violation here is a counterexample, which is the strongest result the workflow returns.
 */
import { PaymentsService } from '../../src/payments/service.ts';
import { checkAll } from '../../src/domain/invariants.ts';
import { TEST_CARDS, EXPIRY } from '../../test/fixtures/cards.ts';
import type { Result } from '../lib.ts';

export function run(): Result {
  const svc = new PaymentsService();
  const p = svc.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount: 10_000 });
  const c1 = svc.capture(p.id, 6_000);
  svc.capture(p.id, 4_000);
  svc.refund(p.id, c1.id, 2_500);

  const violations = checkAll(svc.ledger, svc.payments);
  return {
    findings: violations.map(v => ({
      file: 'src/domain/invariants.ts',
      line: 1,
      summary: `${v.invariant}: ${v.detail}`,
      severity: 'high' as const,
    })),
  };
}
