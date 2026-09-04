"use client";

import { useMemo, useState } from "react";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestStateGate } from "@/components/digest/DigestStateGate";
import { ArchitectureGraph, LANE_ORDER, LANE_LABELS, LANE_COLORS } from "@/components/digest/ArchitectureGraph";
import { useRepositoryDigest } from "@/lib/hooks/useRepositoryDigest";
import type {
  DigestDomain,
  DigestRelationship,
  DigestHotspot,
  DigestRisk,
  DigestLane,
} from "@/lib/graphql/queries/repository-digest";

export default function DigestArchitecturePage() {
  const { digest, fetching, error, status, refreshing, refreshError, dismissRefreshError, handleRefresh } =
    useRepositoryDigest();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <ErrorBoundary>
      <div className="digest-page-title">Architecture</div>
      <DigestStateGate
        fetching={fetching}
        error={error}
        digest={digest}
        status={status}
        refreshing={refreshing}
        refreshError={refreshError}
        onDismissRefreshError={dismissRefreshError}
        onRefresh={handleRefresh}
        emptyMessage="The project map contains no indexed files. The architecture graph will populate once the repository has content."
      >
        {(d) => (
          <ArchitectureBody
            domains={d.domains}
            relationships={d.relationships}
            hotspots={d.hotspots}
            risks={d.risks}
            selectedId={selectedId}
            onSelectDomain={setSelectedId}
          />
        )}
      </DigestStateGate>
    </ErrorBoundary>
  );
}

function ArchitectureBody({
  domains,
  relationships,
  hotspots,
  risks,
  selectedId,
  onSelectDomain,
}: {
  domains: DigestDomain[];
  relationships: DigestRelationship[];
  hotspots: DigestHotspot[];
  risks: DigestRisk[];
  selectedId: string | null;
  onSelectDomain: (id: string) => void;
}) {
  const laneCounts = useMemo(() => {
    const counts: Record<DigestLane, number> = { frontend: 0, api: 0, services: 0, data: 0, other: 0 };
    for (const d of domains) counts[d.lane] = (counts[d.lane] ?? 0) + 1;
    return counts;
  }, [domains]);

  const selectedDomain = domains.find((d) => d.id === selectedId) ?? null;

  if (domains.length === 0) {
    return (
      <div className="surface" style={{ padding: 24 }}>
        <div className="type-section-title" style={{ marginBottom: 8 }}>
          No domains discovered yet
        </div>
        <p className="type-body">
          The architecture graph needs a semantic graph with clusters. Run{" "}
          <span className="type-mono-value">speed digest --rebuild-discovery</span> to build one.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <LaneLegend counts={laneCounts} />

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <div className="surface" style={{ flex: 1, minWidth: 0, height: 560, position: "relative" }}>
          <ArchitectureGraph
            domains={domains}
            relationships={relationships}
            selectedId={selectedId}
            onSelectDomain={onSelectDomain}
          />
          {relationships.length === 0 && (
            <div
              className="type-caption"
              style={{
                position: "absolute", left: 16, bottom: 16, zIndex: 5,
                background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)",
                borderRadius: 8, padding: "8px 12px",
              }}
            >
              No cross-domain relationships were found among these domains.
            </div>
          )}
        </div>

        <div style={{ width: 320, flexShrink: 0 }}>
          <DomainDetailPanel
            domain={selectedDomain}
            domains={domains}
            relationships={relationships}
            hotspots={hotspots}
            risks={risks}
          />
        </div>
      </div>

      <EvidenceNote relationships={relationships} />
    </div>
  );
}

function LaneLegend({ counts }: { counts: Record<DigestLane, number> }) {
  return (
    <div className="surface" style={{ padding: 16, display: "flex", gap: 20, flexWrap: "wrap" }}>
      {LANE_ORDER.map((lane) => (
        <div key={lane} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 10, height: 10, borderRadius: 999, background: LANE_COLORS[lane] }} />
          <span className="type-cell-label">{LANE_LABELS[lane]}</span>
          <span className="type-caption">{counts[lane]}</span>
        </div>
      ))}
    </div>
  );
}

function EvidenceNote({ relationships }: { relationships: DigestRelationship[] }) {
  const total = relationships.length;
  // Computed from the actual data, not assumed: today every relationship
  // this pipeline produces is evidence_type "verified" (see
  // lib/context/repository_digest_architecture.py), but this note must
  // reflect what the data says, not what has always been true so far —
  // if a future build ever surfaces a non-"verified" relationship, this
  // message adapts instead of continuing to claim 100% verified.
  const verifiedCount = relationships.filter((r) => r.evidenceType === "verified").length;
  const allVerified = total > 0 && verifiedCount === total;

  let message: string;
  if (total === 0) {
    message = "This dataset currently has no cross-domain relationships to classify.";
  } else if (allVerified) {
    message = `All ${total} relationship${total === 1 ? "" : "s"} shown ${total === 1 ? "is" : "are"} VERIFIED — derived directly from concrete cross-domain code references (function calls, type usage, inheritance, imports). This dataset currently contains no separate "inferred" relationship category; see the arrow between two domains for direction, and edge thickness for reference count.`;
  } else {
    message = `${verifiedCount} of ${total} relationships shown ${verifiedCount === 1 ? "is" : "are"} VERIFIED; the rest have an unrecognized or unknown evidence type. See the arrow between two domains for direction, and edge thickness for reference count.`;
  }

  return (
    <div className="surface" style={{ padding: 16 }}>
      <p className="type-caption">{message}</p>
    </div>
  );
}

function DomainDetailPanel({
  domain,
  domains,
  relationships,
  hotspots,
  risks,
}: {
  domain: DigestDomain | null;
  domains: DigestDomain[];
  relationships: DigestRelationship[];
  hotspots: DigestHotspot[];
  risks: DigestRisk[];
}) {
  if (!domain) {
    return (
      <div className="surface" style={{ padding: 20 }}>
        <div className="type-section-title" style={{ marginBottom: 8 }}>
          Domain details
        </div>
        <p className="type-body">Select a domain in the graph to see its details.</p>
      </div>
    );
  }

  const labelById = new Map(domains.map((d) => [d.id, d.label]));
  const relCount = relationships.filter((r) => r.source === domain.id || r.target === domain.id).length;
  const domainHotspots = hotspots.filter((h) => h.domainId === domain.id);
  const domainRisks = risks.filter((r) => r.domainId === domain.id);

  return (
    <div className="surface" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }} data-testid="architecture-detail-panel">
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 10, height: 10, borderRadius: 999, background: LANE_COLORS[domain.lane] }} />
          <div className="type-section-title">{domain.label}</div>
        </div>
        <p className="type-caption" style={{ marginTop: 4 }}>
          {LANE_LABELS[domain.lane]} · {domain.fileCount} files · {domain.symbolCount} symbols · {relCount} relationship{relCount === 1 ? "" : "s"}
        </p>
      </div>

      {domain.representativeFiles.length > 0 && (
        <DetailList title="Representative files" items={domain.representativeFiles} />
      )}
      {domain.representativeSymbols.length > 0 && (
        <DetailList title="Representative symbols" items={domain.representativeSymbols} />
      )}

      <DetailRefs title="Depends on" ids={domain.dependsOn} labelById={labelById} emptyText="No outgoing dependencies recorded." />
      <DetailRefs title="Used by" ids={domain.usedBy} labelById={labelById} emptyText="No incoming dependents recorded." />

      <div>
        <div className="type-cell-label" style={{ marginBottom: 4 }}>Hotspots</div>
        {domainHotspots.length === 0 ? (
          <p className="type-caption">No hotspots among the top-ranked repository-wide are in this domain.</p>
        ) : (
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {domainHotspots.map((h) => (
              <li key={h.symbolId} className="type-caption">{h.name} — {h.reason}</li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <div className="type-cell-label" style={{ marginBottom: 4 }}>Risks</div>
        {domainRisks.length === 0 ? (
          <p className="type-caption">No risks are associated with this domain.</p>
        ) : (
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {domainRisks.map((r, i) => (
              <li key={i} className="type-caption">{r.description}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function DetailList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="type-cell-label" style={{ marginBottom: 4 }}>{title}</div>
      <ul style={{ margin: 0, paddingLeft: 16 }}>
        {items.map((item) => (
          <li key={item} className="type-caption" style={{ fontFamily: "var(--font-mono)" }}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function DetailRefs({
  title,
  ids,
  labelById,
  emptyText,
}: {
  title: string;
  ids: string[];
  labelById: Map<string, string>;
  emptyText: string;
}) {
  return (
    <div>
      <div className="type-cell-label" style={{ marginBottom: 4 }}>{title}</div>
      {ids.length === 0 ? (
        <p className="type-caption">{emptyText}</p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 16 }}>
          {ids.map((id) => (
            <li key={id} className="type-caption">{labelById.get(id) ?? id}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
