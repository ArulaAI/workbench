"use client";

import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestStateGate } from "@/components/digest/DigestStateGate";
import { ReadinessPanel } from "@/components/digest/ReadinessPanel";
import { QualityWarningsTable } from "@/components/digest/QualityWarningsTable";
import { useRepositoryDigest } from "@/lib/hooks/useRepositoryDigest";
import type { RepositoryDigestData } from "@/lib/graphql/queries/repository-digest";

export default function DigestQualityPage() {
  const { digest, fetching, error, status, refreshing, refreshError, dismissRefreshError, handleRefresh } =
    useRepositoryDigest();

  return (
    <ErrorBoundary>
      <div className="digest-page-title">Discovery quality</div>
      <DigestStateGate
        fetching={fetching}
        error={error}
        digest={digest}
        status={status}
        refreshing={refreshing}
        refreshError={refreshError}
        onDismissRefreshError={dismissRefreshError}
        onRefresh={handleRefresh}
        emptyMessage="The project map contains no indexed files. Readiness and warnings will populate once the repository has content."
      >
        {(d) => (
          <>
            <FreshnessStrip digest={d} />
            <ReadinessPanel readiness={d.readiness} />
            <QualityWarningsTable warnings={d.warnings} />
          </>
        )}
      </DigestStateGate>
    </ErrorBoundary>
  );
}

function FreshnessStrip({ digest }: { digest: RepositoryDigestData }) {
  const stateColor =
    digest.effectiveState === "CURRENT"
      ? "var(--color-emerald)"
      : digest.effectiveState === "STALE"
      ? "var(--color-amber)"
      : "var(--color-text-tertiary)";

  return (
    <div className="surface" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span className="type-badge" style={{ color: stateColor }}>{digest.effectiveState}</span>
        <span className="type-caption">
          Indexed {digest.freshness.indexedGitHead?.slice(0, 7) ?? "—"}
          {digest.freshness.currentGitHead && digest.freshness.currentGitHead !== digest.freshness.indexedGitHead
            ? ` · repository now at ${digest.freshness.currentGitHead.slice(0, 7)}`
            : ""}
        </span>
      </div>
      {digest.freshness.staleReasons.length > 0 && (
        <p className="type-body" style={{ margin: 0 }}>
          Stale because: {digest.freshness.staleReasons.join(", ")}
        </p>
      )}
    </div>
  );
}
