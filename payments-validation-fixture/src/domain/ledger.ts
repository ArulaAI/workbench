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
  readonly entries: Entry[] = [];

  /** Write a balanced pair. Debit and credit are the same magnitude, opposite sign. */
  post(args: {
    debit: Account;
    credit: Account;
    amount: Minor;
    paymentId: string;
    kind: Entry['kind'];
  }): string {
    const pairId = nextId('pair');
    const at = Date.now();
    this.entries.push(
      { id: nextId('ent'), pairId, account: args.debit, amount: args.amount, paymentId: args.paymentId, kind: args.kind, at },
      { id: nextId('ent'), pairId, account: args.credit, amount: minor(-args.amount), paymentId: args.paymentId, kind: args.kind, at },
    );
    return pairId;
  }

  net(): number {
    return this.entries.reduce((sum, e) => sum + e.amount, 0);
  }

  forPayment(paymentId: string): Entry[] {
    return this.entries.filter(e => e.paymentId === paymentId);
  }

  totalFor(paymentId: string, kind: Entry['kind']): number {
    return this.entries
      .filter(e => e.paymentId === paymentId && e.kind === kind && e.amount > 0)
      .reduce((sum, e) => sum + e.amount, 0);
  }

  reset(): void {
    this.entries.length = 0;
  }
}
