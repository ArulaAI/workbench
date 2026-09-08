import React, { useEffect, useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { Client, Provider, cacheExchange, fetchExchange, useQuery } from "urql";
import {
  AUTHORING_SESSION_QUERY,
  type AuthoringSessionData,
} from "@/lib/graphql/queries/authoring";

/**
 * Both /define/new and /define/:feature run the session query for the slug the
 * user is about to open, so during a route change the authoring route mounts
 * while another component holds the same urql operation key. urql subscribes to
 * that operation while rendering, and its guard against dispatching into other
 * components in that window reads a React internal that React 19 renamed, so
 * the outgoing component is updated mid-render. Deferring the subscription to a
 * mount effect is what keeps that from happening.
 */

const VARIABLES = { featureName: "shared-feature", artifactType: "prd" };
const CROSS_RENDER_WARNING = "while rendering a different component";

function makeClient(): Client {
  return new Client({
    url: "http://localhost/graphql",
    exchanges: [cacheExchange, fetchExchange],
  });
}

/** Stands in for a page that already holds the operation, e.g. /define/new. */
function OutgoingRoute() {
  const [{ data }] = useQuery<AuthoringSessionData>({
    query: AUTHORING_SESSION_QUERY,
    variables: VARIABLES,
    requestPolicy: "network-only",
  });
  return <div data-testid="outgoing">{data?.authoringSession?.status ?? "pending"}</div>;
}

/** The naive pattern: urql subscribes to the operation during first render. */
function NaiveIncomingRoute() {
  const [{ data }] = useQuery<AuthoringSessionData>({
    query: AUTHORING_SESSION_QUERY,
    variables: VARIABLES,
    requestPolicy: "network-only",
  });
  return <div data-testid="incoming">{data?.authoringSession?.status ?? "pending"}</div>;
}

/** The pattern used by app/define/[feature]/authoring/[artifact]/page.tsx. */
function IncomingRoute() {
  const [subscribed, setSubscribed] = useState(false);
  useEffect(() => setSubscribed(true), []);
  const [{ data }] = useQuery<AuthoringSessionData>({
    query: AUTHORING_SESSION_QUERY,
    variables: VARIABLES,
    pause: !subscribed,
    requestPolicy: "network-only",
  });
  return <div data-testid="incoming">{data?.authoringSession?.status ?? "pending"}</div>;
}

describe("authoring route transition", () => {
  let consoleErrors: string[] = [];

  beforeEach(() => {
    consoleErrors = [];
    vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
      consoleErrors.push(args.map(String).join(" "));
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          data: {
            authoringSession: {
              status: "question",
              revision: 0,
              message: "",
              featureName: VARIABLES.featureName,
              featureTitle: "Shared feature",
              artifactType: "prd",
              artifactPath: null,
              artifactContent: null,
              authoringUrl: null,
              draftAvailable: false,
              helperPath: null,
              interpreter: null,
              currentQuestion: null,
              coverage: {},
              sections: [],
              progress: { confirmed: 0, total: 0, deferred: [], remaining: [] },
              followUps: [],
              findings: [],
              selfReview: null,
              implementation: null,
            },
          },
        }),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  async function navigate(Incoming: React.ComponentType) {
    const client = makeClient();
    const { rerender } = render(
      <Provider value={client}>
        <OutgoingRoute />
      </Provider>,
    );
    await screen.findByTestId("outgoing");

    // A route change: the outgoing route unmounts in the same commit that
    // renders the incoming one, so its subscription is still live during that
    // render pass.
    rerender(
      <Provider value={client}>
        <Incoming />
      </Provider>,
    );

    // Not vacuous: the incoming query really does run.
    await waitFor(() =>
      expect(screen.getByTestId("incoming")).toHaveTextContent("question"),
    );

    return consoleErrors.filter((entry) => entry.includes(CROSS_RENDER_WARNING));
  }

  // Guards the workaround itself: if this ever stops warning, urql has fixed
  // its render-phase dispatch and the mount-effect deferral can be dropped.
  it("warns when the incoming route subscribes during its first render", async () => {
    expect(await navigate(NaiveIncomingRoute)).toHaveLength(1);
  });

  it("does not warn when the incoming route subscribes after mount", async () => {
    expect(await navigate(IncomingRoute)).toEqual([]);
  });
});
