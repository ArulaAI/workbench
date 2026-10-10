import type { ReasonCode } from './reasons.ts';

/** Input to the scorer. Carries no PAN and no token. */
export type ScoringInput = {
  bin: string;
  amount: number; // Minor units
  currency: string;
  issuerCountry: string | undefined;
  ipCountry: string;
  merchantId: string;
  merchantCategory: string;
  at: number;
};

export type ScoreResult = { score: number; reasons: ReasonCode[]; modelVersion: string };

export type DecisionOutcome = 'approve' | 'step_up' | 'hold' | 'decline';

export type Decision = {
  outcome: DecisionOutcome;
  score: number;
  reasons: ReasonCode[];
  thresholdsVersion: string;
};
