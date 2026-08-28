"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useSubscription } from "urql";
import { Header } from "@/components/layout/header";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestHeader } from "@/components/digest/DigestHeader";
import { FootprintGrid } from "@/components/digest/FootprintGrid";
import { SystemMap } from "@/components/digest/SystemMap";
import { ReadinessPanel } from "@/components/digest/ReadinessPanel";
import { DomainList } from "@/components/digest/DomainList";
import { CommandList } from "@/components/digest/CommandList";
import { RiskPanel } from "@/components/digest/RiskPanel";
import { ConventionsPanel } from "@/components/digest/ConventionsPanel";
import {
  REPOSITORY_DIGEST_QUERY,
  REPOSITORY_DIGEST_STATUS_QUERY,
  REFRESH_REPOSITORY_DIGEST_MUTATION,
  REPOSITORY_DIGEST_UPDATED_SUBSCRIPTION,
  type RepositoryDigestData,
  type RepositoryDigestBuildStatus,
} from "@/lib/graphql/queries/repository-digest";

// A feature name follows the same rule Define's own route uses.
const FEATURE_RE = /^[a-z0-9][a-z0-9-]*$/;

function isValidFeatureName(name: string | null): name is string {
  return !!name && name.length <= 50 && FEATURE_RE.test(name);
}

export default function DigestPage() {
  const searchParams = useSearchParams();
  const returnTo = searchParams.get("returnTo");
  const featureParam = searchParams.get("feature");
  const returnToDefineHref =
    returnTo === "define" && isValidFeatureName(featureParam)
      ? `/define/${encodeURIComponent(featureParam)}`
      : null;

  const [{ data, fetching, error }, refetch] = useQuery<{ repositoryDigest: RepositoryDigestData | null }>({
    query: REPOSITORY_DIGEST_QUERY,
  });
  const [{ data: statusData }] = useQuery<{ repositoryDigestStatus: RepositoryDigestBuildStatus }>({
    query: REPOSITORY_DIGEST_STATUS_QUERY,
  });
  const [, executeRefresh] = useMutation(REFRESH_REPOSITORY_DIGEST_MUTATION);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const [subResult] = useSubscription({ query: REPOSITORY_DIGEST_UPDATED_SUBSCRIPTION });
  // The subscription only carries live updates once something changes;
  // the initial page load has to fall back to the plain status query so
  // Missing vs. Malformed can be told apart before any refresh ever runs.
  const status = subResult.data?.repositoryDigestUpdated ?? statusData?.repositoryDigestStatus ?? null;

  useEffect(() => {
    const update = subResult.data?.repositoryDigestUpdated;
    if (!update || update.state === "GENERATING") return;
    setRefreshing(false);
    // A failed rebuild can still resolve to CURRENT/STALE (not ERROR) when
    // an earlier successful digest is still on disk and readable — lastError
    // is what actually signals the failure in that case, so check it first
    // rather than gating the banner on state === "ERROR" alone.
    if (update.lastError) {
      setRefreshError(update.lastError);
    } else if (update.state === "CURRENT" || update.state === "STALE") {
      refetch({ requestPolicy: "network-only" });
    }
    // No separate refetchStatus() here: `status` (above) already reads
    // subResult.data?.repositoryDigestUpdated first, so the subscription's
    // own payload is already the live status — a second network round-trip
    // to re-fetch the same information would just re-run the server-side
    // freshness/fingerprint computation for no new data.
  }, [subResult.data, refetch]);

  const handleRefresh = useCallback(
    (rebuildDiscovery: boolean) => {
      setRefreshing(true);
      setRefreshError(null);
      executeRefresh({ rebuildDiscovery, narrative: false }).then((res) => {
        if (res.error) {
          setRefreshing(false);
          setRefreshError(res.error.message);
        } else if (res.data?.refreshRepositoryDigest && !res.data.refreshRepositoryDigest.accepted) {
          // Already generating elsewhere — subscription will resolve it.
        }
      });
    },
    [executeRefresh]
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      <Header />
      <main style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
        <ErrorBoundary>
          <DigestBody
            fetching={fetching}
            error={error}
            digest={data?.repositoryDigest ?? null}
            status={status}
            refreshing={refreshing}
            refreshError={refreshError}
            onRefresh={handleRefresh}
            returnToDefineHref={returnToDefineHref}
          />
        </ErrorBoundary>
      </main>
    </div>
  );
}

function DigestBody({
  fetching,
  error,
  digest,
  status,
  refreshing,
  refreshError,
  onRefresh,
  returnToDefineHref,
}: {
  fetching: boolean;
  error: unknown;
  digest: RepositoryDigestData | null;
  status: RepositoryDigestBuildStatus | null;
  refreshing: boolean;
  refreshError: string | null;
  onRefresh: (rebuildDiscovery: boolean) => void;
  returnToDefineHref: string | null;
}) {
  const [errorDismissed, setErrorDismissed] = useState(false);
  useEffect(() => {
    if (refreshError) setErrorDismissed(false);
  }, [refreshError]);
  // Loading — skeleton title, four KPI cells, two large panels.
  if (fetching && !digest) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div className="surface" style={{ height: 96, animation: "pulse 1.5s ease-in-out infinite" }} />
        <div className="digest-kpi-grid">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="surface" style={{ height: 88 }} />
          ))}
        </div>
        <div className="digest-two-col">
          <div className="surface" style={{ height: 220 }} />
          <div className="surface" style={{ height: 220 }} />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="surface" style={{ padding: 24 }}>
        <div className="type-section-title" style={{ color: "var(--color-red)" }}>
          Digest could not be read
        </div>
        <p className="type-body" style={{ marginTop: 8 }}>{error instanceof Error ? error.message : String(error)}</p>
        <button type="button" onClick={() => onRefresh(false)} className="type-badge" style={buttonStyle}>
          Rebuild digest
        </button>
      </div>
    );
  }

  if (!digest) {
    // repositoryDigest returns null both for "never built" and "stored
    // artifact is malformed/unsupported schema" — repositoryDigestStatus
    // is what distinguishes them (state ERROR + lastError vs. MISSING).
    // See Dashboard Design > Page states: Missing vs. Malformed artifact.
    if (status?.state === "ERROR") {
      return (
        <div className="surface" style={{ padding: 24 }}>
          <div className="type-section-title" style={{ color: "var(--color-red)" }}>
            Repository digest is malformed
          </div>
          {status.lastError && <p className="type-body" style={{ marginTop: 8 }}>{status.lastError}</p>}
          <button
            type="button"
            onClick={() => onRefresh(false)}
            disabled={refreshing}
            className="type-badge"
            style={{ ...buttonStyle, marginTop: 12 }}
          >
            {refreshing ? "Rebuilding…" : "Rebuild digest"}
          </button>
        </div>
      );
    }

    // Missing — no digest exists yet.
    return (
      <div className="surface" style={{ padding: 32, textAlign: "center" }}>
        <div className="type-section-title">No repository digest yet</div>
        <p className="type-body" style={{ margin: "8px 0 16px" }}>
          Build one from the existing discovery index.
        </p>
        <button type="button" onClick={() => onRefresh(false)} disabled={refreshing} className="type-badge" style={primaryButtonStyle}>
          {refreshing ? "Building…" : "Build digest"}
        </button>
        <div style={{ marginTop: 8 }}>
          <button
            type="button"
            onClick={() => onRefresh(true)}
            disabled={refreshing}
            className="type-caption"
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-secondary)" }}
          >
            No index yet? Index repository and build digest
          </button>
        </div>
      </div>
    );
  }

  const empty = digest.footprint.fileCount === 0;

  return (
    <>
      {digest.effectiveState === "STALE" && (
        <div
          className="surface"
          style={{
            padding: "12px 16px", display: "flex", justifyContent: "space-between", alignItems: "center",
            borderLeft: "3px solid var(--color-amber)",
          }}
        >
          <span className="type-body">
            Digest describes {digest.freshness.indexedGitHead?.slice(0, 7)}; repository is now{" "}
            {digest.freshness.currentGitHead?.slice(0, 7)}. Changed content may make domains and hotspots
            inaccurate.
          </span>
          <button type="button" onClick={() => onRefresh(false)} className="type-badge" style={buttonStyle}>
            Refresh
          </button>
        </div>
      )}

      {refreshError && !errorDismissed && (
        <div
          className="surface"
          style={{ padding: "12px 16px", borderLeft: "3px solid var(--color-red)", display: "flex", justifyContent: "space-between" }}
        >
          <span className="type-body">{refreshError}</span>
          <button type="button" onClick={() => setErrorDismissed(true)} className="type-caption" style={{ background: "none", border: "none", cursor: "pointer" }}>
            Dismiss
          </button>
        </div>
      )}

      <DigestHeader digest={digest} onRefresh={() => onRefresh(false)} refreshing={refreshing} returnToDefineHref={returnToDefineHref} />

      {empty ? (
        <div className="surface" style={{ padding: 24 }}>
          <p className="type-body">
            The project map contains no indexed files. Domains and commands will populate once the
            repository has content.
          </p>
        </div>
      ) : (
        <>
          <FootprintGrid footprint={digest.footprint} />
          <div className="digest-two-col">
            <SystemMap domains={digest.domains} />
            <ReadinessPanel readiness={digest.readiness} />
          </div>
          <DomainList domains={digest.domains} />
          <div className="digest-two-col">
            <CommandList commands={digest.commands} />
            <RiskPanel hotspots={digest.hotspots} risks={digest.risks} />
          </div>
          <ConventionsPanel conventions={digest.conventions} gaps={digest.gaps} />
        </>
      )}
    </>
  );
}

const buttonStyle: React.CSSProperties = {
  padding: "8px 12px", borderRadius: 8, border: "1px solid var(--color-border)",
  background: "transparent", color: "var(--color-text-secondary)", cursor: "pointer",
};

const primaryButtonStyle: React.CSSProperties = {
  padding: "10px 18px", borderRadius: 8, border: "1px solid var(--color-accent)",
  background: "var(--color-accent-dim)", color: "var(--color-accent)", cursor: "pointer",
};
