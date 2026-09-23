"use client";

import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestStateGate } from "@/components/digest/DigestStateGate";
import { FeatureUnavailableNote } from "@/components/digest/FeatureUnavailableNote";
import { useRepositoryDigest } from "@/lib/hooks/useRepositoryDigest";
import type {
  DigestSecurity,
  DigestSecretIndicator,
  DigestSensitiveConfigFinding,
  DigestAuthIndicator,
  DigestSecurityTool,
} from "@/lib/graphql/queries/repository-digest";

const SEVERITY_COLOR: Record<string, string> = {
  high: "var(--color-red)",
  medium: "var(--color-amber)",
  low: "var(--color-text-tertiary)",
};

export default function DigestSecurityPage() {
  const { digest, fetching, error, status, refreshing, refreshError, dismissRefreshError, handleRefresh } =
    useRepositoryDigest();

  return (
    <ErrorBoundary>
      <div className="digest-page-title">Security</div>
      <DigestStateGate
        fetching={fetching}
        error={error}
        digest={digest}
        status={status}
        refreshing={refreshing}
        refreshError={refreshError}
        onDismissRefreshError={dismissRefreshError}
        onRefresh={handleRefresh}
        emptyMessage="The project map contains no indexed files. Security information will populate once the repository has content."
      >
        {(d) => <SecurityBody security={d.security} />}
      </DigestStateGate>
    </ErrorBoundary>
  );
}

function SecurityBody({ security }: { security: DigestSecurity | null }) {
  if (!security) {
    return <FeatureUnavailableNote feature="Security information" />;
  }

  const totalFindings =
    security.secretIndicators.length +
    security.sensitiveConfiguration.length +
    security.authenticationIndicators.length +
    security.securityToolingDetected.length;

  if (totalFindings === 0) {
    return (
      <div className="surface" style={{ padding: 24 }}>
        <p className="type-body">No security findings were discovered from supported repository evidence.</p>
        <p className="type-caption" style={{ marginTop: 8 }}>{UNSUPPORTED_CAPABILITY_TEXT}</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SecretIndicatorsPanel indicators={security.secretIndicators} />
      <SensitiveConfigPanel findings={security.sensitiveConfiguration} />
      <div className="digest-two-col">
        <AuthIndicatorsPanel indicators={security.authenticationIndicators} />
        <SecurityToolingPanel tools={security.securityToolingDetected} />
      </div>
      <UnsupportedCapabilityNote />
    </div>
  );
}

function SecretIndicatorsPanel({ indicators }: { indicators: DigestSecretIndicator[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 4 }}>
        Secret indicators
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        Names and locations only — values are never read into the digest, GraphQL responses, or this UI.
      </p>
      {indicators.length === 0 ? (
        <p className="type-body">No secret indicators were discovered.</p>
      ) : (
        <div className="digest-table-scroll">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Name", "Category", "Pattern", "Source", "Redacted"].map((h) => (
                  <th key={h} className="type-cell-label" style={{ textAlign: "left", padding: "6px 10px", borderBottom: "1px solid var(--color-border)" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {indicators.map((ind, i) => (
                <tr key={i} style={{ height: 40 }}>
                  <td className="type-mono-value" style={{ padding: "6px 10px" }}>{ind.name || "—"}</td>
                  <td className="type-caption" style={{ padding: "6px 10px" }}>{ind.category.replace(/_/g, " ")}</td>
                  <td className="type-caption" style={{ padding: "6px 10px" }}>{ind.patternType ?? "—"}</td>
                  <td className="type-caption" style={{ padding: "6px 10px" }}>
                    {ind.file}{ind.line != null ? `:${ind.line}` : ""}
                  </td>
                  <td style={{ padding: "6px 10px" }}>
                    {ind.redacted && <span className="type-badge" style={{ color: "var(--color-text-secondary)" }}>redacted</span>}
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

function SensitiveConfigPanel({ findings }: { findings: DigestSensitiveConfigFinding[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Sensitive configuration
      </div>
      {findings.length === 0 ? (
        <p className="type-body">No sensitive configuration patterns were found.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {findings.map((f, i) => (
            <div key={i} style={{ borderLeft: `3px solid ${f.severity ? SEVERITY_COLOR[f.severity] ?? "var(--color-text-secondary)" : "var(--color-text-secondary)"}`, paddingLeft: 12 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span className="type-cell-label">{f.title}</span>
                <span className="type-caption">{f.severity ? f.severity : "severity unknown"}</span>
              </div>
              <p className="type-body" style={{ margin: "2px 0 4px" }}>{f.description}</p>
              <p className="type-caption">
                {f.file}{f.line != null ? `:${f.line}` : ""}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AuthIndicatorsPanel({ indicators }: { indicators: DigestAuthIndicator[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 4 }}>
        Authentication indicators
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        Presence only — whether auth is correctly implemented isn&apos;t assessed.
      </p>
      {indicators.length === 0 ? (
        <p className="type-body">No authentication indicators were discovered.</p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 16 }}>
          {indicators.map((ind, i) => (
            <li key={i} className="type-caption">
              {ind.name} <span style={{ opacity: 0.7 }}>({ind.type})</span> — {ind.file}
              {ind.line != null ? `:${ind.line}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SecurityToolingPanel({ tools }: { tools: DigestSecurityTool[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Security tooling detected
      </div>
      {tools.length === 0 ? (
        <p className="type-body">No security tooling configuration was found.</p>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {tools.map((t, i) => (
            <span key={i} className="type-badge" style={{ padding: "6px 10px", borderRadius: 999, border: "1px solid var(--color-border)" }}>
              {t.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

const UNSUPPORTED_CAPABILITY_TEXT =
  "Dependency/CVE vulnerability scanning is not supported — it would require an external vulnerability " +
  "database and a network call, which this build does not perform.";

function UnsupportedCapabilityNote() {
  return (
    <div className="surface" style={{ padding: 16 }}>
      <p className="type-caption">{UNSUPPORTED_CAPABILITY_TEXT}</p>
    </div>
  );
}
