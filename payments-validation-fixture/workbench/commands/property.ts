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

export const CASES = 200;
const MAX_STEPS = 12;
const FIXED_NOW = 1_700_000_000_001;

/** Deterministic PRNG (mulberry32), no dependencies, so a failure is reproducible from its seed. */
export const rng = (seed: number) => () => {
  seed = (seed + 0x6d2b79f5) >>> 0;
  let t = seed;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

/** Payments and captures are referenced by index so a sequence is data, not ids. */
export type Op =
  | { op: 'authorise'; amount: number; key?: string }
  | { op: 'capture'; payment: number; amount?: number; key?: string }
  | { op: 'refund'; payment: number; capture: number | 'unknown'; amount?: number }
  | { op: 'void'; payment: number }
  | { op: 'replay'; kind: 'authorise' | 'capture'; of: number }
  | { op: 'settlementSchedule'; payment: number; instalments: number };

export function generate(seed: number): Op[] {
  const rand = rng(seed);
  const int = (n: number) => Math.floor(rand() * n);
  const pick = <T>(xs: T[]): T => xs[int(xs.length)];
  const ops: Op[] = [];
  const steps = 1 + int(MAX_STEPS);
  for (let i = 0; i < steps; i += 1) {
    const payment = int(3);
    switch (int(8)) {
      case 0:
        ops.push({ op: 'authorise', amount: pick([1, 2, 100, 999, 10_000, 1 + int(90_000)]), key: rand() > 0.5 ? `k${i}` : undefined });
        break;
      case 1:
      case 2:
        // Random, boundary (1, huge, zero, negative) and omitted (capture the remainder) amounts.
        ops.push({
          op: 'capture',
          payment,
          amount: pick([undefined, 1, 1 + int(50_000), 0, -5, 10_000_000]),
          key: rand() > 0.7 ? `c${i}` : undefined,
        });
        break;
      case 3:
      case 4:
        // Emitted twice in a row about a third of the time: the retry that refund does not guard.
        for (let t = 0, n = rand() > 0.65 ? 2 : 1; t < n; t += 1) {
          ops.push({
            op: 'refund',
            payment,
            capture: rand() > 0.2 ? int(3) : 'unknown',
            amount: pick([undefined, 1, 1 + int(50_000), 0, 10_000_000]),
          });
        }
        break;
      case 5:
        ops.push({ op: 'void', payment });
        break;
      case 6:
        ops.push({ op: 'replay', kind: pick(['authorise', 'capture'] as const), of: int(steps) });
        break;
      default:
        ops.push({ op: 'settlementSchedule', payment, instalments: pick([0, 1, 2, 3, 7]) });
    }
  }
  return ops;
}

/** Runs one sequence. Returns the index of the first step after which an invariant failed. */
export function execute(ops: Op[]): { step: number; detail: string } | undefined {
  // Timestamps are 13 digits and Luhn-valid by chance about one time in ten, which would make
  // NO_PAN_AT_REST depend on the wall clock. A fixed clock keeps a seed reproducible.
  const realNow = Date.now;
  Date.now = () => FIXED_NOW;
  try {
    return executeOps(ops);
  } finally {
    Date.now = realNow;
  }
}

function executeOps(ops: Op[]): { step: number; detail: string } | undefined {
  const svc = new PaymentsService();
  const paymentIds: string[] = [];
  const keyed: Op[] = [];
  const pid = (i: number) => paymentIds[i % Math.max(paymentIds.length, 1)] ?? 'pay_missing';

  for (const [step, o] of ops.entries()) {
    try {
      if (o.op === 'authorise') {
        const p = svc.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount: o.amount, idempotencyKey: o.key });
        if (!paymentIds.includes(p.id)) paymentIds.push(p.id);
        if (o.key) keyed.push(o);
      } else if (o.op === 'capture') {
        svc.capture(pid(o.payment), o.amount, o.key);
        if (o.key) keyed.push(o);
      } else if (o.op === 'refund') {
        const id = pid(o.payment);
        const caps = svc.payments.get(id)?.captures ?? [];
        const captureId = o.capture === 'unknown' ? 'cap_unknown' : (caps[o.capture % Math.max(caps.length, 1)]?.id ?? 'cap_none');
        svc.refund(id, captureId, o.amount);
      } else if (o.op === 'void') {
        svc.void(pid(o.payment));
      } else if (o.op === 'replay') {
        const target = keyed.filter(k => k.op === o.kind);
        const k = target[o.of % Math.max(target.length, 1)];
        if (k?.op === 'authorise') svc.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount: k.amount, idempotencyKey: k.key });
        else if (k?.op === 'capture') svc.capture(pid(k.payment), k.amount, k.key);
      } else {
        svc.settlementSchedule(pid(o.payment), o.instalments);
      }
    } catch (error) {
      // Rejected input is a valid outcome. Anything other than a RangeError is a real defect.
      if (!(error instanceof RangeError)) {
        return { step, detail: `unexpected ${(error as Error).name}: ${(error as Error).message}` };
      }
    }
    const violations = checkAll(svc.ledger, svc.payments);
    if (violations.length > 0) {
      return { step, detail: violations.map(v => `${v.invariant}: ${v.detail}`).join('; ') };
    }
  }
  return undefined;
}

export function run(): Result {
  const findings: Finding[] = [];

  for (let seed = 1; seed <= CASES; seed += 1) {
    const ops = generate(seed);
    const failure = execute(ops);
    if (!failure) continue;

    console.error(`property failure at seed ${seed}, step ${failure.step}: ${failure.detail}`);
    console.error(`operations:\n${ops.map((o, i) => `  ${i}: ${JSON.stringify(o)}`).join('\n')}`);
    findings.push({
      file: 'src/payments/service.ts',
      line: 1,
      summary: `property failed at seed ${seed}, step ${failure.step}: ${failure.detail}. Ops: ${JSON.stringify(ops)}`,
      severity: 'high',
    });
    break; // shrink to the first failing seed rather than reporting all of them
  }

  return { findings };
}
