import { Client, cacheExchange, fetchExchange, subscriptionExchange } from "urql";
import { createClient as createWSClient } from "graphql-ws";

const GRAPHQL_URL =
  process.env.NEXT_PUBLIC_GRAPHQL_URL || "http://127.0.0.1:4440/graphql";
const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:4440/graphql";

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
