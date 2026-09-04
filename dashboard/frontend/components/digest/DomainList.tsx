import type { DigestDomain } from "@/lib/graphql/queries/repository-digest";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { EvidenceAffordance } from "./EvidencePanel";

export function DomainList({ domains }: { domains: DigestDomain[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="digest-section-title" style={{ marginBottom: 12 }}>
        Major areas
      </div>
      {domains.length === 0 ? (
        <p className="type-body">No areas available — semantic graph not yet built.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {domains.map((d) => (
            <div key={d.id} style={{ borderTop: "1px solid var(--color-border-light)", paddingTop: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <span className="type-column-name">{d.label}</span>
                <span className="type-column-aggregate">
                  {d.fileCount} files · {d.symbolCount} symbols
                </span>
              </div>
              {d.summary && <p className="type-column-intent">{d.summary}</p>}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                <ConfidenceBadge confidence={d.confidence} />
                <EvidenceAffordance evidence={d.evidence} clusterId={d.id} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
