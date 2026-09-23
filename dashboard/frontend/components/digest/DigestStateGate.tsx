"use client";

import { useEffect, useState } from "react";
import type { RepositoryDigestData, RepositoryDigestBuildStatus } from "@/lib/graphql/queries/repository-digest";

/**
 * Shared loading / error / missing / malformed / stale / refresh-error
 * handling for every /digest/* screen. Each screen supplies its own
 * `children` render function for the "digest is loaded" case and an
 * optional `emptyMessage` for what "no indexed files yet" means on that
 * specific screen — everything else (the five non-happy-path states) is
 * identical across screens by design, so it lives here once.
 */
export function DigestStateGate({
  fetching,
  error,
  digest,
  status,
  refreshing,
  refreshError,
  onDismissRefreshError,
  onRefresh,
  emptyMessage,
  children,
}: {
  fetching: boolean;
  error: unknown;
  digest: RepositoryDigestData | null;
  status: RepositoryDigestBuildStatus | null;
  refreshing: boolean;
  refreshError: string | null;
  onDismissRefreshError: () => void;
  onRefresh: (rebuildDiscovery: boolean) => void;
  emptyMessage?: string;
  children: (digest: RepositoryDigestData) => React.ReactNode;
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

    // Missing — no digest exists yet. Which action is primary depends on
    // whether the repository has ever been indexed at all: "Build digest"
    // only makes sense once project-map.json already exists — otherwise
    // it would fail immediately, and "Index repository and build digest"
    // is the actual first step.
    const hasIndex = status?.hasProjectMap ?? true; // unknown → assume indexed, the more common case
    return (
      <div className="surface" style={{ padding: 32, textAlign: "center" }}>
        <div className="type-section-title">No repository digest yet</div>
        <p className="type-body" style={{ margin: "8px 0 16px" }}>
          {hasIndex
            ? "Build one from the existing discovery index."
            : "This repository hasn't been indexed yet — index it and build a digest."}
        </p>
        <button
          type="button"
          onClick={() => onRefresh(!hasIndex)}
          disabled={refreshing}
          className="type-badge"
          style={primaryButtonStyle}
        >
          {refreshing ? "Building…" : hasIndex ? "Build digest" : "Index repository and build digest"}
        </button>
        {hasIndex && (
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
        )}
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
          <button
            type="button"
            onClick={() => {
              setErrorDismissed(true);
              onDismissRefreshError();
            }}
            className="type-caption"
            style={{ background: "none", border: "none", cursor: "pointer" }}
          >
            Dismiss
          </button>
        </div>
      )}

      {empty ? (
        <div className="surface" style={{ padding: 24 }}>
          <p className="type-body">
            {emptyMessage ?? "The project map contains no indexed files. This screen will populate once the repository has content."}
          </p>
        </div>
      ) : (
        children(digest)
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
