import type { DigestReadiness } from "@/lib/graphql/queries/repository-digest";

const STATUS_ICON: Record<string, string> = {
  AVAILABLE: "✓",
  PARTIAL: "⏳",
  UNAVAILABLE: "○",
  INVALID: "✗",
  STALE: "⏳",
};

const STATUS_COLOR: Record<string, string> = {
  AVAILABLE: "var(--color-emerald)",
  PARTIAL: "var(--color-amber)",
  UNAVAILABLE: "var(--color-text-tertiary)",
  INVALID: "var(--color-red)",
  STALE: "var(--color-amber)",
};

export function ReadinessPanel({ readiness }: { readiness: DigestReadiness[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Discovery readiness
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 16px" }}>
        {readiness.map((r) => (
          <div
            key={r.capability}
            title={r.reason ?? undefined}
            style={{ display: "flex", alignItems: "center", gap: 8 }}
          >
            <span style={{ color: STATUS_COLOR[r.status] }}>{STATUS_ICON[r.status] ?? "?"}</span>
            <span className="type-caption" style={{ textTransform: "capitalize", color: "var(--color-text-secondary)" }}>
              {r.capability.replace(/_/g, " ")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
