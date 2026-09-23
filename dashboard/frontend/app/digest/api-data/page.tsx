"use client";

import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestStateGate } from "@/components/digest/DigestStateGate";
import { FeatureUnavailableNote } from "@/components/digest/FeatureUnavailableNote";
import { useRepositoryDigest } from "@/lib/hooks/useRepositoryDigest";
import type { DigestApiData, DigestRoute, DigestEntity } from "@/lib/graphql/queries/repository-digest";

export default function DigestApiDataPage() {
  const { digest, fetching, error, status, refreshing, refreshError, dismissRefreshError, handleRefresh } =
    useRepositoryDigest();

  return (
    <ErrorBoundary>
      <div className="digest-page-title">API &amp; data</div>
      <DigestStateGate
        fetching={fetching}
        error={error}
        digest={digest}
        status={status}
        refreshing={refreshing}
        refreshError={refreshError}
        onDismissRefreshError={dismissRefreshError}
        onRefresh={handleRefresh}
        emptyMessage="The project map contains no indexed files. API and data information will populate once the repository has content."
      >
        {(d) => <ApiDataBody apiData={d.apiData} />}
      </DigestStateGate>
    </ErrorBoundary>
  );
}

function ApiDataBody({ apiData }: { apiData: DigestApiData | null }) {
  if (!apiData) {
    return <FeatureUnavailableNote feature="API & data information" />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <PersistenceSummaryPanel summary={apiData.persistenceSummary} />
      <RoutesPanel routes={apiData.routes} />
      <EntitiesPanel entities={apiData.entities} />
    </div>
  );
}

function PersistenceSummaryPanel({ summary }: { summary: DigestApiData["persistenceSummary"] }) {
  return (
    <div className="digest-kpi-grid">
      <div className="surface" style={{ padding: 16 }}>
        <div className="type-kpi-label">Persistence mode</div>
        <div className="type-kpi-value" style={{ fontSize: 20, marginTop: 4 }}>
          {summary ? summary.mode : "unknown"}
        </div>
      </div>
      <div className="surface" style={{ padding: 16 }}>
        <div className="type-kpi-label">Entities discovered</div>
        <div className="type-kpi-value" style={{ fontSize: 20, marginTop: 4 }}>
          {summary ? summary.entityCount : 0}
        </div>
      </div>
    </div>
  );
}

function RoutesPanel({ routes }: { routes: DigestRoute[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 4 }}>
        Routes
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        Discovered from FastAPI/Flask, Express/NestJS, Spring MVC, and Strawberry GraphQL resolvers — never guessed from a filename.
      </p>
      {routes.length === 0 ? (
        <p className="type-body">No API routes were discovered from supported frameworks.</p>
      ) : (
        <div className="digest-table-scroll">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Method", "Path", "Handler", "Framework", "Source"].map((h) => (
                  <th key={h} className="type-cell-label" style={{ textAlign: "left", padding: "6px 10px", borderBottom: "1px solid var(--color-border)" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {routes.map((r, i) => (
                <tr key={i} style={{ height: 40 }}>
                  <td className="type-mono-value" style={{ padding: "6px 10px" }}>{r.method}</td>
                  <td className="type-mono-value" style={{ padding: "6px 10px" }}>{r.path}</td>
                  <td className="type-body" style={{ padding: "6px 10px" }}>{r.handler || "—"}</td>
                  <td className="type-caption" style={{ padding: "6px 10px" }}>{r.framework}</td>
                  <td className="type-caption" style={{ padding: "6px 10px" }}>{r.file}:{r.line}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function EntitiesPanel({ entities }: { entities: DigestEntity[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 4 }}>
        Entities
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        ORM model classes discovered by the semantic graph. Columns/relationships are reconstructed from nearby symbols and marked accordingly — never fabricated.
      </p>
      {entities.length === 0 ? (
        <p className="type-body">No ORM entities were discovered.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {entities.map((e, i) => (
            <div key={i} className="surface-elevated digest-subcard">
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span className="type-cell-label">{e.name}</span>
                <span className="type-caption">{e.file ?? "—"}</span>
                {e.columnsInferred && (
                  <span className="type-badge" style={{ color: "var(--color-amber)" }}>inferred</span>
                )}
              </div>
              {e.columns.length > 0 && (
                <p className="type-caption" style={{ marginTop: 6 }}>
                  Columns: {e.columns.map((c) => `${c.name}${c.primaryKey ? " (PK)" : ""}`).join(", ")}
                </p>
              )}
              {e.relationships.length > 0 && (
                <p className="type-caption" style={{ marginTop: 4 }}>
                  Relationships: {e.relationships.map((r) => `${r.field} → ${r.targetEntity ?? "?"} (${r.cardinality})`).join(", ")}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
