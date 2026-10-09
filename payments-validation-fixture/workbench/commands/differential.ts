/*
 * Golden-corpus replay. Plan 3.10, satisfying FR-15. Home for F7.
 *
 * Replays a recorded transaction corpus and diffs the result against the golden file.
 * A pass is statistical, not proof: it says no divergence was found over the shapes the
 * corpus contains. The corpus is the boundary of the claim, and corpus drift is the
 * standing risk. Say that on the profile card.
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { PaymentsService } from '../../src/payments/service.ts';
import { TEST_CARDS, EXPIRY } from '../../test/fixtures/cards.ts';
import { type Finding, type Result, ROOT } from '../lib.ts';

const GOLDEN = join(ROOT, 'corpus', 'golden.json');

type Row = { amount: number; captures: number[]; refund?: number; instalments: number };

/** Fixed, ordered, and boring on purpose. A corpus that changes is not a control. */
const CORPUS: Row[] = [
  { amount: 10_000, captures: [10_000], instalments: 3 },
  { amount: 10_000, captures: [6_000, 4_000], refund: 2_500, instalments: 2 },
  { amount: 9_999, captures: [3_333, 3_333, 3_333], instalments: 7 },
  { amount: 1, captures: [1], instalments: 1 },
  { amount: 123_457, captures: [123_457], refund: 1, instalments: 11 },
  { amount: 2_500, captures: [1_250, 1_250], refund: 1_250, instalments: 4 },
];

const replay = () =>
  CORPUS.map(row => {
    const s = new PaymentsService();
    const p = s.authorise({ pan: TEST_CARDS.visa, expiry: EXPIRY, amount: row.amount });
    const captureIds = row.captures.map(a => s.capture(p.id, a).id);
    if (row.refund) s.refund(p.id, captureIds[0], row.refund);
    return {
      amount: row.amount,
      schedule: s.settlementSchedule(p.id, row.instalments),
      fees: s.ledger.entries.filter(e => e.account === 'scheme_fees').reduce((t, e) => t + e.amount, 0),
      settled: s.ledger.entries.filter(e => e.account === 'merchant_settled').reduce((t, e) => t + e.amount, 0),
      net: s.ledger.net(),
    };
  });

export function run(): Result {
  const actual = replay();
  if (!existsSync(GOLDEN)) {
    writeFileSync(GOLDEN, `${JSON.stringify(actual, null, 2)}\n`);
    return { findings: [], skipped: 'no golden file, recorded one from this run' };
  }
  const golden = JSON.parse(readFileSync(GOLDEN, 'utf8'));
  const findings: Finding[] = [];
  actual.forEach((row, i) => {
    const before = JSON.stringify(golden[i]);
    const after = JSON.stringify(row);
    if (before !== after) {
      findings.push({
        file: 'corpus/golden.json',
        line: i + 1,
        summary: `row ${i} diverged from the golden corpus: ${before} became ${after}`,
        severity: 'high',
      });
    }
  });
  return { findings };
}
