"use client";

import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestStateGate } from "@/components/digest/DigestStateGate";
import { ConventionsPanel } from "@/components/digest/ConventionsPanel";
import { useRepositoryDigest } from "@/lib/hooks/useRepositoryDigest";
import type { DigestKnowledgeDraft, DigestKnowledgeEntry, DigestRisk } from "@/lib/graphql/queries/repository-digest";

export default function DigestKnowledgePage() {
  const { digest, fetching, error, status, refreshing, refreshError, dismissRefreshError, handleRefresh } =
    useRepositoryDigest();

  return (
    <ErrorBoundary>
      <div className="digest-page-title">Team knowledge</div>
      <DigestStateGate
        fetching={fetching}
        error={error}
        digest={digest}
        status={status}
        refreshing={refreshing}
        refreshError={refreshError}
        onDismissRefreshError={dismissRefreshError}
        onRefresh={handleRefresh}
        emptyMessage="The project map contains no indexed files. Conventions and knowledge will populate once the repository has content."
      >
        {(d) => (
          <>
            <ConventionsPanel conventions={d.conventions} gaps={d.gaps} />
            <ApprovedKnowledge entries={d.approvedKnowledge} />
            <PendingDrafts drafts={d.pendingKnowledge} />
            <RecurringSignals risks={d.risks} />
          </>
        )}
      </DigestStateGate>
    </ErrorBoundary>
  );
}

/** .speed/memory/project-knowledge.json — human-approved only. */
function ApprovedKnowledge({ entries }: { entries: DigestKnowledgeEntry[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Approved project knowledge
      </div>
      {entries.length === 0 ? (
        <p className="type-body">No approved project knowledge is available yet.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {entries.map((e) => (
            <div key={e.id} style={{ borderTop: "1px solid var(--color-border-light)", paddingTop: 12 }}>
              <p className="type-body" style={{ margin: 0 }}>{e.knowledge}</p>
              {e.whyItMatters && <p className="type-column-intent" style={{ margin: "4px 0 0" }}>{e.whyItMatters}</p>}
              <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
                {e.appliesTo.map((scope) => (
                  <span key={scope} className="type-caption" style={{ background: "var(--color-bg-elevated)", padding: "2px 6px", borderRadius: 4 }}>
                    {scope}
                  </span>
                ))}
                {e.stalenessFlag && (
                  <span className="type-caption" style={{ color: "var(--color-amber)" }}>⚠ {e.stalenessFlag}</span>
                )}
                {e.lastVerified && (
                  <span className="type-caption">Verified {new Date(e.lastVerified).toLocaleDateString()}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** .speed/memory/project-knowledge-drafts.json — pending human review;
 * never influences the digest's own conclusions. Kept visibly separate
 * from approved knowledge, per the RFC's trust-boundary requirement. */
function PendingDrafts({ drafts }: { drafts: DigestKnowledgeDraft[] }) {
  return (
    <div className="surface" style={{ padding: 20, borderLeft: "3px solid var(--color-amber)" }}>
      <div className="type-section-title" style={{ marginBottom: 4 }}>
        Pending human review
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        Drafts only — not included in guidance or any other digest conclusion.
      </p>
      {drafts.length === 0 ? (
        <p className="type-body">No drafts are pending review.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {drafts.map((d) => (
            <div key={d.id} style={{ opacity: 0.85 }}>
              <p className="type-body" style={{ margin: 0 }}>{d.knowledge}</p>
              <p className="type-caption" style={{ margin: "4px 0 0" }}>{d.draftReason || d.source}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * "Signals" here means exactly one already-existing, named risk category
 * — repeated_failure (lib/context/repository_digest.py:_derive_risks,
 * 3+ failure/error observations sharing a scope). No broader "learning
 * signal" system exists yet, so nothing broader is claimed here.
 */
function RecurringSignals({ risks }: { risks: DigestRisk[] }) {
  const signals = risks.filter((r) => r.type === "REPEATED_FAILURE");
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 4 }}>
        Recurring signals
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        Repeated failure/error observations sharing the same scope, from task and review history.
      </p>
      {signals.length === 0 ? (
        <p className="type-body">No recurring failure patterns have been observed.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {signals.map((s, i) => (
            <p key={i} className="type-body" style={{ margin: 0 }}>{s.description}</p>
          ))}
        </div>
      )}
    </div>
  );
}
