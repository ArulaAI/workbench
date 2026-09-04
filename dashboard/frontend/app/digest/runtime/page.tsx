"use client";

import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestStateGate } from "@/components/digest/DigestStateGate";
import { FeatureUnavailableNote } from "@/components/digest/FeatureUnavailableNote";
import { useRepositoryDigest } from "@/lib/hooks/useRepositoryDigest";
import type {
  DigestRuntimeConfig,
  DigestRuntime,
  DigestFramework,
  DigestConfigSource,
  DigestEnvironmentVariable,
} from "@/lib/graphql/queries/repository-digest";

export default function DigestRuntimePage() {
  const { digest, fetching, error, status, refreshing, refreshError, dismissRefreshError, handleRefresh } =
    useRepositoryDigest();

  return (
    <ErrorBoundary>
      <div className="digest-page-title">Runtime &amp; config</div>
      <DigestStateGate
        fetching={fetching}
        error={error}
        digest={digest}
        status={status}
        refreshing={refreshing}
        refreshError={refreshError}
        onDismissRefreshError={dismissRefreshError}
        onRefresh={handleRefresh}
        emptyMessage="The project map contains no indexed files. Runtime and configuration information will populate once the repository has content."
      >
        {(d) => <RuntimeBody runtimeConfig={d.runtimeConfig} />}
      </DigestStateGate>
    </ErrorBoundary>
  );
}

function RuntimeBody({ runtimeConfig }: { runtimeConfig: DigestRuntimeConfig | null }) {
  if (!runtimeConfig) {
    return <FeatureUnavailableNote feature="Runtime and configuration information" />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="digest-two-col">
        <RuntimesPanel runtimes={runtimeConfig.runtimes} />
        <FrameworksPanel frameworks={runtimeConfig.frameworks} />
      </div>
      <ConfigSourcesPanel sources={runtimeConfig.configSources} />
      <EnvironmentVariablesPanel envVars={runtimeConfig.environmentVariables} />
    </div>
  );
}

function RuntimesPanel({ runtimes }: { runtimes: DigestRuntime[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Runtimes
      </div>
      {runtimes.length === 0 ? (
        <p className="type-body">No runtime versions were explicitly declared.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {runtimes.map((r, i) => (
            <div key={i}>
              <span className="type-cell-label">{r.language}</span>
              <span className="type-mono-value" style={{ marginLeft: 8 }}>{r.version ?? "unspecified"}</span>
              <span className="type-caption" style={{ marginLeft: 8 }}>{r.sourceFile}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FrameworksPanel({ frameworks }: { frameworks: DigestFramework[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Frameworks
      </div>
      {frameworks.length === 0 ? (
        <p className="type-body">No known frameworks were found among declared dependencies.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {frameworks.map((f, i) => (
            <div key={i}>
              <span className="type-cell-label">{f.name}</span>
              {f.version && <span className="type-mono-value" style={{ marginLeft: 8 }}>{f.version}</span>}
              <span className="type-caption" style={{ marginLeft: 8 }}>{f.sourceFile}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ConfigSourcesPanel({ sources }: { sources: DigestConfigSource[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Configuration sources
      </div>
      {sources.length === 0 ? (
        <p className="type-body">No known configuration files were found at the repository root.</p>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {sources.map((s, i) => (
            <span key={i} className="type-badge" style={{ padding: "6px 10px", borderRadius: 999, border: "1px solid var(--color-border)" }}>
              {s.file}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function EnvironmentVariablesPanel({ envVars }: { envVars: DigestEnvironmentVariable[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 4 }}>
        Environment variables
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        Names only — values are never read into the digest, GraphQL responses, or this UI.
      </p>
      {envVars.length === 0 ? (
        <p className="type-body">No environment variable names were discovered.</p>
      ) : (
        <div className="digest-table-scroll">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Name", "Source", "Status"].map((h) => (
                  <th key={h} className="type-cell-label" style={{ textAlign: "left", padding: "6px 10px", borderBottom: "1px solid var(--color-border)" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {envVars.map((e, i) => (
                <tr key={i} style={{ height: 40 }}>
                  <td className="type-mono-value" style={{ padding: "6px 10px" }}>{e.name}</td>
                  <td className="type-caption" style={{ padding: "6px 10px" }}>{e.sourceFile}</td>
                  <td style={{ padding: "6px 10px" }}>
                    {e.looksSensitive ? (
                      <span className="type-badge" style={{ color: "var(--color-amber)" }}>secret/declared</span>
                    ) : (
                      <span className="type-badge" style={{ color: "var(--color-text-secondary)" }}>declared</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
