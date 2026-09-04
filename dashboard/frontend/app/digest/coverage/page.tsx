"use client";

import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestStateGate } from "@/components/digest/DigestStateGate";
import { useRepositoryDigest } from "@/lib/hooks/useRepositoryDigest";
import type { DigestCoverageStats, DigestGap } from "@/lib/graphql/queries/repository-digest";

export default function DigestCoveragePage() {
  const { digest, fetching, error, status, refreshing, refreshError, dismissRefreshError, handleRefresh } =
    useRepositoryDigest();

  return (
    <ErrorBoundary>
      <div className="digest-page-title">Coverage & conflicts</div>
      <DigestStateGate
        fetching={fetching}
        error={error}
        digest={digest}
        status={status}
        refreshing={refreshing}
        refreshError={refreshError}
        onDismissRefreshError={dismissRefreshError}
        onRefresh={handleRefresh}
        emptyMessage="The project map contains no indexed files. Coverage and conflicts will populate once the repository has content."
      >
        {(d) => (
          <>
            <CoverageSummary stats={d.coverageStats} />
            <ConflictsPanel gaps={d.gaps} />
            <WarningsPanel warnings={d.warnings} />
          </>
        )}
      </DigestStateGate>
    </ErrorBoundary>
  );
}

/**
 * source_files_parsed / source_files_total, both read straight from
 * build-summary.json's extraction_stats (lib/context/layer1.py) — the
 * exact denominator tree-sitter actually attempted, not project-wide
 * file count (which includes config/docs/assets nothing ever parses).
 * Absent whenever that artifact doesn't exist or predates this field —
 * shown as a real "not available" state, never a fabricated 0% or 100%.
 */
function CoverageSummary({ stats }: { stats: DigestCoverageStats | null }) {
  if (!stats) {
    return (
      <div className="surface" style={{ padding: 20 }}>
        <div className="type-section-title" style={{ marginBottom: 8 }}>
          Discovery coverage
        </div>
        <p className="type-body">
          Coverage statistics aren&apos;t available. This requires a Layer 1 discovery build
          (<span className="type-mono-value">speed digest --rebuild-discovery</span>) — a digest built without one
          has no extraction statistics to report coverage from.
        </p>
      </div>
    );
  }

  const pct = stats.parseCoveragePct;

  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 4 }}>
        Discovery coverage
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        Source files tree-sitter actually parsed, out of every source file it attempted.
      </p>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
        <span className="type-kpi-value" style={{ color: "var(--color-accent)" }}>
          {pct != null ? `${pct.toFixed(1)}%` : "—"}
        </span>
        <span className="type-caption">
          {stats.sourceFilesParsed.toLocaleString()} / {stats.sourceFilesTotal.toLocaleString()} source files
        </span>
      </div>
      {pct != null && (
        <div className="progress-track" style={{ height: 8, marginBottom: 16 }}>
          <div style={{ width: `${pct}%`, background: "var(--color-accent)" }} />
        </div>
      )}
      <div className="digest-kpi-grid">
        <div className="surface-elevated digest-subcard">
          <div className="type-kpi-label">Symbols extracted</div>
          <div className="type-kpi-value" style={{ fontSize: 20, marginTop: 4 }}>
            {stats.symbolsExtracted != null ? stats.symbolsExtracted.toLocaleString() : "—"}
          </div>
        </div>
        <div className="surface-elevated digest-subcard">
          <div className="type-kpi-label">References extracted</div>
          <div className="type-kpi-value" style={{ fontSize: 20, marginTop: 4 }}>
            {stats.referencesExtracted != null ? stats.referencesExtracted.toLocaleString() : "—"}
          </div>
        </div>
      </div>
    </div>
  );
}

function ConflictsPanel({ gaps }: { gaps: DigestGap[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Conflicting or ambiguous sources
      </div>
      {gaps.length === 0 ? (
        <p className="type-body">No conflicting or ambiguous sources were found during the last build.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {gaps.map((g, i) => (
            <div key={i} style={{ borderLeft: "3px solid var(--color-amber)", paddingLeft: 12 }}>
              <div className="type-cell-label" style={{ textTransform: "capitalize" }}>{g.type.replace(/_/g, " ")}</div>
              <p className="type-body" style={{ margin: "2px 0 0" }}>{g.description}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function WarningsPanel({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Build warnings
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {warnings.map((w, i) => (
          <p key={i} className="type-body" style={{ margin: 0 }}>⚠ {w}</p>
        ))}
      </div>
    </div>
  );
}
