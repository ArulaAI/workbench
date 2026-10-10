/*
 * Double-entry ledger. Plan 2.2, satisfying FR-4.
 *
 * Every movement writes a balanced pair. Nothing in the service may write a single
 * entry, which is what makes LEDGER_BALANCED assertable after any operation sequence.
 */

import { type Minor, minor } from './money.ts';

export type Account =
  | 'cardholder'
  | 'merchant_receivable'
  | 'merchant_settled'
  | 'scheme_fees'
  | 'refunds_payable';

export type Entry = {
  id: string;
  pairId: string;
  account: Account;
  amount: Minor;
  paymentId: string;
  kind: 'authorise' | 'capture' | 'refund' | 'void';
  at: number;
};

let seq = 0;
const nextId = (prefix: string) => `${prefix}_${(++seq).toString(36).padStart(6, '0')}`;

export class Ledger {
  private readonly rows: Entry[] = [];

  /** Read-only view of every entry. Callers cannot push, splice or reassign. */
  get entries(): ReadonlyArray<Entry> {
    return this.rows;
  }

  /*
   * The only write path. Writes exactly two entries sharing one pairId.
   * Sign convention (existing in this codebase): the debit account takes +amount and the
   * credit account takes -amount, so every pair sums to zero.
   */
  post(args: {
    debit: Account;
    credit: Account;
    amount: Minor;
    paymentId: string;
    kind: Entry['kind'];
    at?: number;
  }): string {
    if (!Number.isInteger(args.amount) || args.amount <= 0) {
      throw new RangeError(`ledger amount must be a positive integer, got ${args.amount}`);
    }
    if (args.debit === args.credit) {
      throw new RangeError(`ledger debit and credit must differ, got ${args.debit} for both`);
    }
    const pairId = nextId('pair');
    const at = args.at ?? Date.now();
    this.rows.push(
      { id: nextId('ent'), pairId, account: args.debit, amount: args.amount, paymentId: args.paymentId, kind: args.kind, at },
      { id: nextId('ent'), pairId, account: args.credit, amount: minor(-args.amount), paymentId: args.paymentId, kind: args.kind, at },
    );
    return pairId;
  }

  /** Signed balance of one account, or of the whole ledger when no account is given. */
  net(account?: Account): number {
    return this.rows
      .filter(e => account === undefined || e.account === account)
      .reduce((sum, e) => sum + e.amount, 0);
  }

  forPayment(paymentId: string): Entry[] {
    return this.rows.filter(e => e.paymentId === paymentId);
  }

  /** Entries grouped by pairId, for invariant checks. */
  pairs(): Map<string, Entry[]> {
    const groups = new Map<string, Entry[]>();
    for (const e of this.rows) {
      const group = groups.get(e.pairId);
      if (group) group.push(e);
      else groups.set(e.pairId, [e]);
    }
    return groups;
  }

  totalFor(paymentId: string, kind: Entry['kind']): number {
    return this.rows
      .filter(e => e.paymentId === paymentId && e.kind === kind && e.amount > 0)
      .reduce((sum, e) => sum + e.amount, 0);
  }

  reset(): void {
    this.rows.length = 0;
  }
}
