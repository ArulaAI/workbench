"use client";

import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestStateGate } from "@/components/digest/DigestStateGate";
import { ConfidenceBadge } from "@/components/digest/ConfidenceBadge";
import { TestSuiteTable } from "@/components/digest/TestSuiteTable";
import { useRepositoryDigest } from "@/lib/hooks/useRepositoryDigest";
import type { DigestCommand } from "@/lib/graphql/queries/repository-digest";

export default function DigestWorkflowsPage() {
  const { digest, fetching, error, status, refreshing, refreshError, dismissRefreshError, handleRefresh } =
    useRepositoryDigest();

  return (
    <ErrorBoundary>
      <div className="digest-page-title">Build &amp; tests</div>
      <DigestStateGate
        fetching={fetching}
        error={error}
        digest={digest}
        status={status}
        refreshing={refreshing}
        refreshError={refreshError}
        onDismissRefreshError={dismissRefreshError}
        onRefresh={handleRefresh}
        emptyMessage="The project map contains no indexed files. Commands will populate once the repository has content."
      >
        {(d) => (
          <>
            <GroupedCommandList commands={d.commands} />
            <TestSuiteTable commands={d.commands} />
          </>
        )}
      </DigestStateGate>
    </ErrorBoundary>
  );
}

/** Groups commands by working directory, per the reference design. */
function GroupedCommandList({ commands }: { commands: DigestCommand[] }) {
  if (commands.length === 0) {
    return (
      <div className="surface" style={{ padding: 20 }}>
        <div className="type-section-title" style={{ marginBottom: 8 }}>
          Commands
        </div>
        <p className="type-body">No commands discovered in CLAUDE.md, AGENTS.md, or project manifests.</p>
      </div>
    );
  }

  const byDirectory = new Map<string, DigestCommand[]>();
  for (const c of commands) {
    const group = byDirectory.get(c.workingDirectory) ?? [];
    group.push(c);
    byDirectory.set(c.workingDirectory, group);
  }
  const directories = [...byDirectory.keys()].sort((a, b) => (a === "." ? -1 : b === "." ? 1 : a.localeCompare(b)));

  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Commands by working directory
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        {directories.map((dir) => (
          <div key={dir}>
            <div className="type-mono-value" style={{ marginBottom: 6, color: "var(--color-text-secondary)" }}>
              {dir}
            </div>
            <div className="digest-table-scroll">
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <tbody>
                  {byDirectory.get(dir)!.map((c, i) => (
                    <tr key={i} style={{ borderTop: i > 0 ? "1px solid var(--color-border-light)" : undefined }}>
                      <td className="type-table-header" style={{ padding: "8px 8px 8px 0", textTransform: "uppercase", whiteSpace: "nowrap" }}>
                        {c.purpose}
                      </td>
                      <td className="type-mono-value" style={{ padding: "8px 12px 8px 0", whiteSpace: "nowrap" }}>
                        {c.command}
                      </td>
                      <td style={{ padding: "8px 0", textAlign: "right" }}>
                        <ConfidenceBadge confidence={c.confidence} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
