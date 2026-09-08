import { Client, cacheExchange, fetchExchange, subscriptionExchange } from "urql";
import { createClient as createWSClient } from "graphql-ws";

const GRAPHQL_URL =
  process.env.NEXT_PUBLIC_GRAPHQL_URL || "http://127.0.0.1:4440/graphql";
const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:4440/graphql";

const REQUEST_TIMEOUT_MS = 310_000;

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const controller = new AbortController();
  const forwardAbort = () => controller.abort(init.signal?.reason);
  if (init.signal?.aborted) {
    forwardAbort();
  } else {
    init.signal?.addEventListener("abort", forwardAbort, { once: true });
  }
  const timer = globalThis.setTimeout(
    () => controller.abort(new DOMException("GraphQL request timed out", "TimeoutError")),
    REQUEST_TIMEOUT_MS,
  );
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    globalThis.clearTimeout(timer);
    init.signal?.removeEventListener("abort", forwardAbort);
  }
}

const wsClient =
  typeof window !== "undefined"
    ? createWSClient({
        url: WS_URL,
        retryAttempts: Infinity,
        retryWait: async (retries) => {
          await new Promise((r) =>
            setTimeout(r, Math.min(1000 * 2 ** retries, 30000))
          );
        },
      })
    : null;

export const client = new Client({
  url: GRAPHQL_URL,
  fetch: fetchWithTimeout,
  exchanges: [
    cacheExchange,
    fetchExchange,
    ...(wsClient
      ? [
          subscriptionExchange({
            forwardSubscription(request) {
              const input = { ...request, query: request.query || "" };
              return {
                subscribe(sink) {
                  const unsubscribe = wsClient.subscribe(input, sink);
                  return { unsubscribe };
                },
              };
            },
          }),
        ]
      : []),
  ],
});
