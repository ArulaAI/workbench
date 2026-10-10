/*
 * The 3-D Secure step-up adapter. The only external call on the authorisation path.
 *
 * The adapter only reports outcomes. It does not decide what a failure means; the caller
 * holds or authorises the payment. Challenges live in this replica's memory only.
 */

import type { Decision } from './types.ts';

export type ChallengeStatus = 'pending' | 'authenticated' | 'not_authenticated' | 'unavailable' | 'cancelled';
export type ChallengeSource = 'policy' | 'block_match';
export type ChallengeOutcome = Exclude<ChallengeStatus, 'pending'>;

export type StepUpChallenge<R> = {
  id: string;
  source: ChallengeSource;
  /** The attack whose block caused this challenge. Set only for 'block_match'. */
  attackId?: string;
  request: R;
  decision: Decision;
  token: string;
  status: ChallengeStatus;
  createdAt: number;
  expiresAt: number;
  completedAt?: number;
};

export type StepUpStartArgs = {
  challengeId: string;
  token: string;
  amount: number;
  currency: string;
  merchantId: string;
};

export interface StepUpProvider {
  start(args: StepUpStartArgs): Promise<'started' | 'unavailable'>;
}

export type StepUpMeta = { amount: number; currency: string; merchantId: string };

export class ChallengeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ChallengeError';
  }
}

const CHALLENGE_TTL_MS = 10 * 60 * 1000;
const PAN_LIKE = /\d{13,19}/;

export type HttpStepUpOptions = {
  baseUrl?: string;
  apiKey?: string;
  timeoutMs?: number;
};

/** Thin, replaceable client. The REST shape is a placeholder until sandbox access. */
export class HttpStepUpProvider implements StepUpProvider {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;

  constructor(opts: HttpStepUpOptions = {}) {
    this.baseUrl = opts.baseUrl ?? process.env.STEPUP_BASE_URL ?? '';
    this.apiKey = opts.apiKey ?? process.env.STEPUP_API_KEY ?? '';
    this.timeoutMs = opts.timeoutMs ?? 10_000;
  }

  async start(args: StepUpStartArgs): Promise<'started' | 'unavailable'> {
    const body = JSON.stringify(args);
    if (PAN_LIKE.test(body)) {
      throw new Error('step-up payload holds a 13 to 19 digit number; only the vault token may be sent');
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const res = await fetch(`${this.baseUrl}/challenges`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${this.apiKey}` },
        body,
        signal: controller.signal,
      });
      return res.status >= 500 || !res.ok ? 'unavailable' : 'started';
    } catch {
      return 'unavailable';
    } finally {
      clearTimeout(timer);
    }
  }
}

export type StepUpAdapterOptions<R> = {
  clock?: () => number;
  answerTimeoutMs?: number;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (h: unknown) => void;
  onUnavailable?: (challenge: StepUpChallenge<R>, request: R) => void;
};

export class StepUpAdapter<R> {
  private readonly provider: StepUpProvider;
  private readonly clock: () => number;
  private readonly answerTimeoutMs: number;
  private readonly setTimer: (fn: () => void, ms: number) => unknown;
  private readonly clearTimer: (h: unknown) => void;
  private onUnavailable?: (challenge: StepUpChallenge<R>, request: R) => void;

  private readonly challenges = new Map<string, StepUpChallenge<R>>();
  /** Requests are held apart from the challenge record so release() can drop only them. */
  private readonly requests = new Map<string, R>();
  private readonly timers = new Map<string, unknown>();
  private counter = 0;

  constructor(provider: StepUpProvider, opts: StepUpAdapterOptions<R> = {}) {
    this.provider = provider;
    this.clock = opts.clock ?? Date.now;
    this.answerTimeoutMs = opts.answerTimeoutMs ?? 10_000;
    this.setTimer = opts.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
    this.clearTimer = opts.clearTimer ?? (h => clearTimeout(h as ReturnType<typeof setTimeout>));
    this.onUnavailable = opts.onUnavailable;
  }

  setOnUnavailable(fn: (challenge: StepUpChallenge<R>, request: R) => void): void {
    this.onUnavailable = fn;
  }

  begin(
    request: R,
    decision: Decision,
    token: string,
    meta: StepUpMeta,
    source: ChallengeSource = 'policy',
    attackId?: string,
  ): StepUpChallenge<R> {
    const createdAt = this.clock();
    const id = `chl_${String(++this.counter).padStart(6, '0')}`;
    const challenge: StepUpChallenge<R> = {
      id, source, request, decision, token, status: 'pending',
      createdAt, expiresAt: createdAt + CHALLENGE_TTL_MS,
    };
    if (attackId !== undefined) challenge.attackId = attackId;
    this.challenges.set(id, challenge);
    this.requests.set(id, request);

    this.timers.set(id, this.setTimer(() => this.providerFailed(id), this.answerTimeoutMs));

    let started: Promise<'started' | 'unavailable'>;
    try {
      started = this.provider.start({ challengeId: id, token, amount: meta.amount, currency: meta.currency, merchantId: meta.merchantId });
    } catch {
      started = Promise.reject(new Error('step-up provider threw'));
    }
    started.then(
      result => (result === 'started' ? this.cancelTimer(id) : this.providerFailed(id)),
      () => this.providerFailed(id),
    );
    return challenge;
  }

  complete(
    id: string,
    outcome: ChallengeOutcome,
  ): { challenge: StepUpChallenge<R>; request: R; repeat: boolean } {
    const challenge = this.challenges.get(id);
    if (!challenge) throw new ChallengeError(`unknown challenge ${id}`);
    if (challenge.status !== 'pending') {
      return { challenge, request: this.requests.get(id) as R, repeat: true };
    }
    if (this.clock() > challenge.expiresAt) throw new ChallengeError(`challenge ${id} has expired`);
    this.finish(challenge, outcome);
    return { challenge, request: this.requests.get(id) as R, repeat: false };
  }

  /** Drop the request once the caller has stored its result. The PAN-free record stays. */
  release(id: string): void {
    this.requests.delete(id);
  }

  get(id: string): StepUpChallenge<R> | undefined {
    return this.challenges.get(id);
  }

  expire(): void {
    const now = this.clock();
    for (const [id, challenge] of this.challenges) {
      if (now <= challenge.expiresAt) continue;
      if (challenge.status === 'pending') {
        this.finish(challenge, 'cancelled');
      } else {
        this.challenges.delete(id);
        this.requests.delete(id);
      }
    }
  }

  private finish(challenge: StepUpChallenge<R>, outcome: ChallengeOutcome): void {
    challenge.status = outcome;
    challenge.completedAt = this.clock();
    this.cancelTimer(challenge.id);
  }

  private cancelTimer(id: string): void {
    const handle = this.timers.get(id);
    if (handle === undefined) return;
    this.timers.delete(id);
    this.clearTimer(handle);
  }

  private providerFailed(id: string): void {
    const challenge = this.challenges.get(id);
    if (!challenge || challenge.status !== 'pending') return;
    const request = this.requests.get(id) as R;
    this.finish(challenge, 'unavailable');
    this.onUnavailable?.(challenge, request);
  }
}
