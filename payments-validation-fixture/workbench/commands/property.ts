/*
 * Generated operation sequences. Plan 3.9, satisfying FR-10 and FR-15.
 *
 * Encodes the invariant rather than the example. The generator deliberately emits
 * duplicate refund calls, because that is the interleaving the F8 gap makes possible.
 * A clean run here is statistical: N cases, no violation. It is not proof.
 */
import { PaymentsService } from '../../src/payments/service.ts';
import { checkAll } from '../../src/domain/invariants.ts';
import { TEST_CARDS, EXPIRY } from '../../test/fixtures/cards.ts';
import type { Finding, Result } from '../lib.ts';

const CASES = 200;

/** Deterministic PRNG so a failure is reproducible from its seed. */
const rng = (seed: number) => () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;

export function run(): Result {
  const findings: Finding[] = [];

  for (let seed = 1; seed <= CASES; seed += 1) {
    const rand = rng(seed);
    const svc = new PaymentsService();
    const amount = 1000 + Math.floor(rand() * 90_000);
    const p = svc.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount });

    const captures: string[] = [];
    const parts = 1 + Math.floor(rand() * 3);
    let left = amount;
    for (let i = 0; i < parts && left > 0; i += 1) {
      const take = i === parts - 1 ? left : 1 + Math.floor(rand() * left);
      captures.push(svc.capture(p.id, take).id);
      left -= take;
    }

    for (const captureId of captures) {
      const cap = svc.payments.get(p.id)!.captures.find(c => c.id === captureId)!;
      const times = rand() > 0.6 ? 2 : 1; // retry, which refund does not guard against
      for (let t = 0; t < times; t += 1) {
        try {
          svc.refund(p.id, captureId, cap.amount);
        } catch {
          /* a rejected refund is a valid outcome, not a violation */
        }
      }
    }

    for (const v of checkAll(svc.ledger, svc.payments)) {
      findings.push({
        file: 'src/payments/service.ts',
        line: 1,
        summary: `${v.invariant} violated at seed ${seed}: ${v.detail}`,
        severity: 'high',
      });
      break; // shrink to the first violating seed rather than reporting all 200
    }
    if (findings.length > 0) break;
  }

  return { findings };
}
