/*
 * The observability surface. Plan 2.5, satisfying FR-7.
 *
 * Five sinks, each capable of carrying a PAN out of the process. This is the home for
 * F2, and the sink list comes straight from PCI DSS v4.0 requirements 3.x and 10.x.
 *
 *   1. application log
 *   2. webhook error body
 *   3. telemetry attributes
 *   4. test fixture files (see test/fixtures)
 *   5. serialised exception path
 *
 * The fifth is the one worth having. A regex over source will not find it, because the
 * PAN is never written literally. Taint analysis will, because it follows the value.
 */

export type LogRecord = { level: 'debug' | 'info' | 'error'; message: string; at: number };
export type TelemetrySpan = { name: string; attributes: Record<string, unknown> };
export type WebhookDelivery = { url: string; status: number; body: unknown };

import { findLuhnCandidates } from '../vault.ts';

export const sinks = {
  logs: [] as LogRecord[],
  spans: [] as TelemetrySpan[],
  webhooks: [] as WebhookDelivery[],
};

/*
 * Sink 5. Serialising a caught error together with the request that caused it is a
 * standard and useful debugging habit. It is also how a whole request object, including
 * whatever it holds, leaves the process. Every sink below passes through redact.
 */
const PAN_FIELDS = new Set(['pan', 'cardNumber', 'primaryAccountNumber', 'cvv', 'cvc']);

/** Keep at most the first 6 and last 4 digits, mask the rest. */
const maskCandidate = (candidate: string): string => {
  const digits = candidate.replace(/\D/g, '');
  return `${digits.slice(0, 6)}${'*'.repeat(digits.length - 10)}${digits.slice(-4)}`;
};

const redactString = (text: string): string => {
  let out = text;
  for (const candidate of new Set(findLuhnCandidates(text))) {
    out = out.split(candidate).join(maskCandidate(candidate));
  }
  return out;
};

const walk = (value: unknown, ancestors: WeakSet<object>): unknown => {
  if (typeof value === 'string') return redactString(value);
  if (!value || typeof value !== 'object') return value;
  if (value instanceof Date) return value;
  if (ancestors.has(value)) return '[circular]';
  ancestors.add(value);
  try {
    if (Array.isArray(value)) return value.map(v => walk(v, ancestors));
    const entries: [string, unknown][] = Object.entries(value as Record<string, unknown>).map(([k, v]) => [
      k,
      PAN_FIELDS.has(k) ? '[redacted]' : walk(v, ancestors),
    ]);
    if (value instanceof Error) {
      const err = value as Error & { cause?: unknown };
      const base: [string, unknown][] = [
        ['name', err.name],
        ['message', walk(err.message, ancestors)],
        ['stack', walk(err.stack, ancestors)],
      ];
      if ('cause' in err) base.push(['cause', walk(err.cause, ancestors)]);
      const seen = new Set(base.map(([k]) => k));
      return Object.fromEntries([...base, ...entries.filter(([k]) => !seen.has(k))]);
    }
    return Object.fromEntries(entries);
  } finally {
    ancestors.delete(value);
  }
};

export const redact = (value: unknown): unknown => walk(value, new WeakSet());

const record = (level: LogRecord['level'], message: string): number =>
  sinks.logs.push({ level, message: redactString(String(message)), at: Date.now() });

export const log = {
  debug: (message: string) => record('debug', message),
  info: (message: string) => record('info', message),
  error: (message: string) => record('error', message),
};

export const span = (name: string, attributes: Record<string, unknown>): void => {
  sinks.spans.push({
    name: redactString(name),
    attributes: redact(attributes) as Record<string, unknown>,
  });
};

export const webhook = (url: string, status: number, body: unknown): void => {
  sinks.webhooks.push({ url: redactString(url), status, body: redact(body) });
};

/** A redacted, JSON-safe object for an error and the errors it was caused by. */
export const serialiseError = (err: unknown): unknown =>
  JSON.parse(JSON.stringify(redact(err instanceof Error ? err : { message: String(err) })) ?? 'null');

export const serialiseFailure = (error: unknown, context: unknown): string =>
  JSON.stringify({ error: redact(error instanceof Error ? error.message : String(error)), context: redact(context) });

export const resetSinks = (): void => {
  sinks.logs.length = 0;
  sinks.spans.length = 0;
  sinks.webhooks.length = 0;
};
