"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useSubscription } from "urql";
import {
  REPOSITORY_DIGEST_QUERY,
  REPOSITORY_DIGEST_STATUS_QUERY,
  REFRESH_REPOSITORY_DIGEST_MUTATION,
  REPOSITORY_DIGEST_UPDATED_SUBSCRIPTION,
  type RepositoryDigestData,
  type RepositoryDigestBuildStatus,
} from "@/lib/graphql/queries/repository-digest";

/**
 * Single source of truth for the digest query/status/refresh/subscription
 * state, shared by every /digest/* screen. Extracted from the original
 * single-page DigestPage so each screen (Overview, Workflows, Quality, ...)
 * gets identical loading/stale/refresh behavior without re-deriving it.
 */
// How often to poll repositoryDigestStatus while a refresh is in flight —
// only used as a fallback for a disconnected/unavailable WebSocket, so it
// doesn't need to be tight; a real build takes seconds to low tens of
// seconds (see the backend's own _STALE_GENERATING_SECONDS grace period).
const REFRESH_POLL_INTERVAL_MS = 2000;

// Every field of RepositoryDigestBuildStatus, deliberately — comparing
// only a hand-picked subset (state/startedAt/completedAt/lastError, an
// earlier version of this function) meant a poll or subscription push
// that changed only currentGitHead/staleReasons/hasProjectMap/
// indexedGitHead/hasReadableDigest was treated as "no change," so
// setLiveStatus bailed out and the UI kept showing stale values for
// those fields indefinitely even though polling was succeeding.
export function statusEquals(
  a: RepositoryDigestBuildStatus | null,
  b: RepositoryDigestBuildStatus | null
): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.state === b.state &&
    a.startedAt === b.startedAt &&
    a.completedAt === b.completedAt &&
    a.lastError === b.lastError &&
    a.hasReadableDigest === b.hasReadableDigest &&
    a.hasProjectMap === b.hasProjectMap &&
    a.indexedGitHead === b.indexedGitHead &&
    a.currentGitHead === b.currentGitHead &&
    a.staleReasons.length === b.staleReasons.length &&
    a.staleReasons.every((reason, i) => reason === b.staleReasons[i])
  );
}

type RepositoryDigestState = ReturnType<typeof useRepositoryDigestState>;

function useRepositoryDigestState() {
  const [{ data, fetching, error }, refetch] = useQuery<{ repositoryDigest: RepositoryDigestData | null }>({
    query: REPOSITORY_DIGEST_QUERY,
  });
  const [{ data: statusData }, reexecuteStatusQuery] = useQuery<{ repositoryDigestStatus: RepositoryDigestBuildStatus }>({
    query: REPOSITORY_DIGEST_STATUS_QUERY,
  });
  const [, executeRefresh] = useMutation(REFRESH_REPOSITORY_DIGEST_MUTATION);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const [subResult] = useSubscription({ query: REPOSITORY_DIGEST_UPDATED_SUBSCRIPTION });

  // `status` reflects whichever source produced a value most recently —
  // a WebSocket push, or a polled query response — via two independent
  // effects each overwriting the same state, rather than a fixed
  // "subscription always wins" fallback. That fixed order was the bug:
  // once the subscription had pushed anything at all (even a single
  // GENERATING event before the socket died), it permanently shadowed
  // every later, fresher poll response, so a disconnected WebSocket left
  // the page reading a stale GENERATING forever.
  const [liveStatus, setLiveStatus] = useState<RepositoryDigestBuildStatus | null>(null);
  // setLiveStatus only when the *value* actually changed, via the
  // updater-function form — a query client re-render can hand back a
  // new object for logically-identical data, and setting state to a
  // new-but-equal value on every render would re-trigger both this
  // effect and the polling effect below in a loop that never settles.
  useEffect(() => {
    const next = subResult.data?.repositoryDigestUpdated;
    if (!next) return;
    setLiveStatus((prev) => (statusEquals(prev, next) ? prev : next));
  }, [subResult.data]);
  useEffect(() => {
    const next = statusData?.repositoryDigestStatus;
    if (!next) return;
    setLiveStatus((prev) => (statusEquals(prev, next) ? prev : next));
  }, [statusData]);
  const status = liveStatus;

  // Terminal-state handling — fires for a status update from either
  // source, subscription or poll.
  useEffect(() => {
    if (!status || status.state === "GENERATING") return;
    setRefreshing(false);
    // A failed rebuild can still resolve to CURRENT/STALE (not ERROR) when
    // an earlier successful digest is still on disk and readable — lastError
    // is what actually signals the failure in that case, so check it first
    // rather than gating the banner on state === "ERROR" alone.
    if (status.lastError) {
      setRefreshError(status.lastError);
    } else if (status.state === "CURRENT" || status.state === "STALE") {
      refetch({ requestPolicy: "network-only" });
    }
  }, [status, refetch]);

  // Cold-load coverage: if this page loads (or the subscription first
  // connects) while some *other* owner's build is already in flight,
  // start "refreshing" from that observation alone — not only from a
  // refresh this tab itself initiated — so the polling fallback below
  // engages for that build too.
  useEffect(() => {
    if (status?.state === "GENERATING") setRefreshing(true);
  }, [status]);

  // Polling fallback: a disconnected or unavailable WebSocket must not
  // leave the page refreshing indefinitely (every accepted OR
  // rejected-because-another-owner refresh still sets `refreshing`, and
  // the cold-load effect above sets it too) — poll status on an interval
  // the whole time `refreshing` is true, regardless of subscription
  // health. A subscription event that arrives in the meantime still ends
  // polling immediately via the terminal-state effect above (it clears
  // `refreshing`, which tears this interval down).
  useEffect(() => {
    if (!refreshing) return;
    const interval = setInterval(() => {
      reexecuteStatusQuery({ requestPolicy: "network-only" });
    }, REFRESH_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refreshing, reexecuteStatusQuery]);

  const handleRefresh = useCallback(
    (rebuildDiscovery: boolean) => {
      setRefreshing(true);
      setRefreshError(null);
      executeRefresh({ rebuildDiscovery, narrative: false }).then((res) => {
        if (res.error) {
          setRefreshing(false);
          setRefreshError(res.error.message);
        }
        // res.data?.refreshRepositoryDigest.accepted === false means a
        // build is already running for another owner — `refreshing`
        // deliberately stays true in that case too: the poll/
        // subscription above resolves that other build's terminal
        // status the same way it would one started locally.
      });
    },
    [executeRefresh]
  );

  return {
    digest: data?.repositoryDigest ?? null,
    fetching,
    error,
    status,
    refreshing,
    refreshError,
    dismissRefreshError: () => setRefreshError(null),
    handleRefresh,
  };
}

// Every /digest/* screen used to call useRepositoryDigestState() (then
// just named useRepositoryDigest) directly, each independently opening
// its own useQuery/useSubscription for the *same* GraphQL operations.
// That's redundant on its own, but it also caused a real bug: urql's
// useQuery/useSubscription must call setState once after mount to stay
// concurrent-mode-safe (this is intentional upstream behavior, not a
// bug in urql), and when navigating between two /digest/* pages that
// each hold a live subscription to the identical operation, the
// outgoing page's subscriber could be notified synchronously while the
// incoming page was still rendering — "Cannot update a component
// (DigestXPage) while rendering a different component (DigestYPage)."
// RepositoryDigestProvider fixes this at the root rather than papering
// over the symptom: DigestLayout (app/digest/layout.tsx) mounts it once
// and it never unmounts across sibling /digest/* navigations, so there
// is only ever one subscriber to these operations, not two racing
// during a transition.
const RepositoryDigestContext = createContext<RepositoryDigestState | null>(null);

export function RepositoryDigestProvider({ children }: { children: ReactNode }) {
  const state = useRepositoryDigestState();
  return <RepositoryDigestContext.Provider value={state}>{children}</RepositoryDigestContext.Provider>;
}

export function useRepositoryDigest(): RepositoryDigestState {
  const state = useContext(RepositoryDigestContext);
  if (!state) {
    throw new Error("useRepositoryDigest() must be called within a RepositoryDigestProvider (see app/digest/layout.tsx)");
  }
  return state;
}
