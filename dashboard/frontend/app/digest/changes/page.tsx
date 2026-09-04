"use client";

import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestStateGate } from "@/components/digest/DigestStateGate";
import { FeatureUnavailableNote } from "@/components/digest/FeatureUnavailableNote";
import { useRepositoryDigest } from "@/lib/hooks/useRepositoryDigest";
import type {
  DigestChangesHistory,
  DigestChangeSection,
  DigestSnapshotMeta,
} from "@/lib/graphql/queries/repository-digest";

export default function DigestChangesPage() {
  const { digest, fetching, error, status, refreshing, refreshError, dismissRefreshError, handleRefresh } =
    useRepositoryDigest();

  return (
    <ErrorBoundary>
      <div className="digest-page-title">Changes since last digest</div>
      <DigestStateGate
        fetching={fetching}
        error={error}
        digest={digest}
        status={status}
        refreshing={refreshing}
        refreshError={refreshError}
        onDismissRefreshError={dismissRefreshError}
        onRefresh={handleRefresh}
        emptyMessage="The project map contains no indexed files. Changes history will populate once the repository has content."
      >
        {(d) => <ChangesBody changes={d.changesHistory} />}
      </DigestStateGate>
    </ErrorBoundary>
  );
}

function ChangesBody({ changes }: { changes: DigestChangesHistory | null }) {
  if (!changes) {
    return <FeatureUnavailableNote feature="Changes history" />;
  }

  if (changes.status === "FIRST_RUN") {
    return (
      <div className="surface" style={{ padding: 24 }}>
        <div className="type-section-title" style={{ marginBottom: 8 }}>
          No previous digest is available yet
        </div>
        <p className="type-body">
          Changes are compared against the digest snapshot immediately before this one. Build another digest
          (<span className="type-mono-value">speed digest --refresh</span>) to start tracking changes — this
          screen will populate the next time a digest is built after that.
        </p>
      </div>
    );
  }

  const hasAnyChange = changes.summary.length > 0;
  const availableSections = changes.sections.filter((s) => s.available);
  const unavailableSections = changes.sections.filter((s) => !s.available);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <ComparisonHeader previous={changes.previousSnapshot} current={changes.currentSnapshot} />
      {changes.warnings.length > 0 && <WarningsPanel warnings={changes.warnings} />}
      <SummaryPanel summary={changes.summary} hasAnyChange={hasAnyChange} />
      {availableSections
        .filter((s) => s.added.length + s.removed.length + s.changed.length > 0)
        .map((s) => (
          <SectionPanel key={s.key} section={s} />
        ))}
      {unavailableSections.length > 0 && <UnavailableSectionsPanel sections={unavailableSections} />}
    </div>
  );
}

function ComparisonHeader({ previous, current }: { previous: DigestSnapshotMeta | null; current: DigestSnapshotMeta | null }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Comparison period
      </div>
      <div className="digest-two-col">
        <div>
          <div className="type-cell-label" style={{ marginBottom: 4 }}>Previous snapshot</div>
          <p className="type-caption">{previous?.generatedAt ?? "—"}</p>
          <p className="type-caption">
            {previous?.gitHead ? `git ${previous.gitHead.slice(0, 7)}` : "git revision unavailable"}
          </p>
        </div>
        <div>
          <div className="type-cell-label" style={{ marginBottom: 4 }}>Current snapshot</div>
          <p className="type-caption">{current?.generatedAt ?? "—"}</p>
          <p className="type-caption">
            {current?.gitHead ? `git ${current.gitHead.slice(0, 7)}` : "git revision unavailable"}
          </p>
        </div>
      </div>
    </div>
  );
}

function WarningsPanel({ warnings }: { warnings: string[] }) {
  return (
    <div className="surface" style={{ padding: "12px 16px", borderLeft: "3px solid var(--color-amber)" }}>
      {warnings.map((w, i) => (
        <p key={i} className="type-body" style={{ margin: i === 0 ? 0 : "4px 0 0" }}>⚠ {w}</p>
      ))}
    </div>
  );
}

function SummaryPanel({ summary, hasAnyChange }: { summary: string[]; hasAnyChange: boolean }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Summary
      </div>
      {!hasAnyChange ? (
        <p className="type-body">No meaningful changes were detected since the last digest.</p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 16 }}>
          {summary.map((line, i) => (
            <li key={i} className="type-mono-value" style={{ marginBottom: 4 }}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SectionPanel({ section }: { section: DigestChangeSection }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        {section.label}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {section.added.map((item, i) => (
          <div key={`added-${i}`} style={{ borderLeft: "3px solid var(--color-emerald)", paddingLeft: 10 }}>
            <span className="type-badge" style={{ color: "var(--color-emerald)" }}>added</span>{" "}
            <span className="type-body">{item.title}</span>
          </div>
        ))}
        {section.removed.map((item, i) => (
          <div key={`removed-${i}`} style={{ borderLeft: "3px solid var(--color-red)", paddingLeft: 10 }}>
            <span className="type-badge" style={{ color: "var(--color-red)" }}>removed</span>{" "}
            <span className="type-body">{item.title}</span>
          </div>
        ))}
        {section.changed.map((item, i) => (
          <div key={`changed-${i}`} style={{ borderLeft: "3px solid var(--color-amber)", paddingLeft: 10 }}>
            <span className="type-badge" style={{ color: "var(--color-amber)" }}>changed</span>{" "}
            <span className="type-body">{item.title}</span>
            <ul style={{ margin: "4px 0 0", paddingLeft: 16 }}>
              {item.fields.map((f, fi) => (
                <li key={fi} className="type-caption">
                  {f.field}: {formatValue(f.before)} → {formatValue(f.after)}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.length === 0 ? "(none)" : value.join(", ");
  return String(value);
}

function UnavailableSectionsPanel({ sections }: { sections: DigestChangeSection[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 4 }}>
        Not comparable
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        These sections weren&apos;t present in one of the two snapshots being compared, so no honest
        added/removed/changed judgment can be made — never treated as "everything removed" or "everything added."
      </p>
      <ul style={{ margin: 0, paddingLeft: 16 }}>
        {sections.map((s) => (
          <li key={s.key} className="type-caption">
            <span className="type-cell-label">{s.label}</span> — {s.reason}
          </li>
        ))}
      </ul>
    </div>
  );
}
