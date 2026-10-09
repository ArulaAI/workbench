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

export const sinks = {
  logs: [] as LogRecord[],
  spans: [] as TelemetrySpan[],
  webhooks: [] as WebhookDelivery[],
};

export const log = {
  debug: (message: string) => sinks.logs.push({ level: 'debug', message, at: Date.now() }),
  info: (message: string) => sinks.logs.push({ level: 'info', message, at: Date.now() }),
  error: (message: string) => sinks.logs.push({ level: 'error', message, at: Date.now() }),
};

export const span = (name: string, attributes: Record<string, unknown>): void => {
  sinks.spans.push({ name, attributes });
};

export const webhook = (url: string, status: number, body: unknown): void => {
  sinks.webhooks.push({ url, status, body });
};

/*
 * Sink 5. Serialising a caught error together with the request that caused it is a
 * standard and useful debugging habit. It is also how a whole request object, including
 * whatever it holds, leaves the process.
 */
const PAN_FIELDS = new Set(['pan', 'cardNumber', 'primaryAccountNumber', 'cvv', 'cvc']);

export const redact = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) =>
        PAN_FIELDS.has(k) ? [k, '[redacted]'] : [k, redact(v)],
      ),
    );
  }
  return value;
};

export const serialiseFailure = (error: unknown, context: unknown): string =>
  JSON.stringify({ error: error instanceof Error ? error.message : String(error), context: redact(context) });

export const resetSinks = (): void => {
  sinks.logs.length = 0;
  sinks.spans.length = 0;
  sinks.webhooks.length = 0;
};
