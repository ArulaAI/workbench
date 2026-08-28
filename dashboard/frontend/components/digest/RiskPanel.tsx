import type { DigestHotspot, DigestRisk } from "@/lib/graphql/queries/repository-digest";

const SEVERITY_COLOR: Record<string, string> = {
  high: "var(--color-red)",
  medium: "var(--color-amber)",
  low: "var(--color-text-tertiary)",
};

export function RiskPanel({ hotspots, risks }: { hotspots: DigestHotspot[]; risks: DigestRisk[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Hotspots and risks
      </div>

      {hotspots.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          {hotspots.slice(0, 5).map((h) => (
            <div
              key={h.symbolId}
              style={{ display: "flex", justifyContent: "space-between", padding: "8px 0" }}
            >
              <span className="type-mono-value">{h.name}</span>
              <span className="type-column-aggregate">{h.blastRadius}</span>
            </div>
          ))}
        </div>
      )}

      {risks.length === 0 ? (
        <p className="type-body">No evidence-backed risks surfaced.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {risks.map((r, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <span
                style={{
                  width: 6, height: 6, borderRadius: "50%", marginTop: 6, flexShrink: 0,
                  background: SEVERITY_COLOR[r.severity] ?? SEVERITY_COLOR.medium,
                }}
              />
              <p className="type-body" style={{ margin: 0 }}>
                {r.description}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
