"use client";

import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestStateGate } from "@/components/digest/DigestStateGate";
import { FeatureUnavailableNote } from "@/components/digest/FeatureUnavailableNote";
import { useRepositoryDigest } from "@/lib/hooks/useRepositoryDigest";
import type { DigestCicd, DigestCiWorkflow, DigestOtherCiProvider } from "@/lib/graphql/queries/repository-digest";

export default function DigestCicdPage() {
  const { digest, fetching, error, status, refreshing, refreshError, dismissRefreshError, handleRefresh } =
    useRepositoryDigest();

  return (
    <ErrorBoundary>
      <div className="digest-page-title">CI/CD</div>
      <DigestStateGate
        fetching={fetching}
        error={error}
        digest={digest}
        status={status}
        refreshing={refreshing}
        refreshError={refreshError}
        onDismissRefreshError={dismissRefreshError}
        onRefresh={handleRefresh}
        emptyMessage="The project map contains no indexed files. CI/CD information will populate once the repository has content."
      >
        {(d) => <CicdBody cicd={d.cicd} />}
      </DigestStateGate>
    </ErrorBoundary>
  );
}

function CicdBody({ cicd }: { cicd: DigestCicd | null }) {
  if (!cicd) {
    return <FeatureUnavailableNote feature="CI/CD information" />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <WorkflowsPanel workflows={cicd.workflows} />
      <OtherProvidersPanel providers={cicd.otherProvidersDetected} />
    </div>
  );
}

function WorkflowsPanel({ workflows }: { workflows: DigestCiWorkflow[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 4 }}>
        Workflows
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        GitHub Actions workflows are structurally parsed (name, triggers, jobs, dependencies, commands). Other CI providers are detected but not parsed — see below.
      </p>
      {workflows.length === 0 ? (
        <p className="type-body">No CI/CD workflows were discovered.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {workflows.map((w, i) => (
            <div key={i} className="surface-elevated digest-subcard">
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span className="type-cell-label">{w.name}</span>
                <span className="type-caption">{w.provider}</span>
                <span className="type-caption">{w.configFile}</span>
              </div>
              {w.triggers.length > 0 && (
                <p className="type-caption" style={{ marginTop: 6 }}>Triggers: {w.triggers.join(", ")}</p>
              )}
              {w.jobs.length === 0 ? (
                <p className="type-caption" style={{ marginTop: 6 }}>No parseable jobs.</p>
              ) : (
                <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                  {w.jobs.map((j, ji) => (
                    <div key={ji} style={{ borderLeft: "2px solid var(--color-border)", paddingLeft: 10 }}>
                      <span className="type-body" style={{ fontWeight: 600 }}>{j.name}</span>
                      {j.runsOn && <span className="type-caption"> · {j.runsOn}</span>}
                      {j.needs.length > 0 && <span className="type-caption"> · needs: {j.needs.join(", ")}</span>}
                      {j.commands.length > 0 && (
                        <p className="type-mono-value" style={{ margin: "2px 0 0", fontSize: 12 }}>
                          {j.commands.join(" && ")}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function OtherProvidersPanel({ providers }: { providers: DigestOtherCiProvider[] }) {
  if (providers.length === 0) return null;
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 4 }}>
        Other CI configuration detected
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        Present in the repository but not structurally parsed by this screen today.
      </p>
      <ul style={{ margin: 0, paddingLeft: 16 }}>
        {providers.map((p, i) => (
          <li key={i} className="type-body">
            {p.provider} — <span className="type-mono-value">{p.configFile}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
