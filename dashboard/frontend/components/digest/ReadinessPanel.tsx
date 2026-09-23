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

// Project Knowledge has no backing pipeline yet (no
// .speed/shared/knowledge/project-knowledge.json is ever written without
// running `speed learn` plus human curation), so it always renders as a
// permanently-unchecked item with no path to ever becoming checked.
// Hidden here rather than dropped from the backend's readiness
// computation, so the underlying data/schema is unchanged for anyone
// querying it directly.
const HIDDEN_CAPABILITIES = new Set(["project_knowledge"]);

export function ReadinessPanel({ readiness }: { readiness: DigestReadiness[] }) {
  const visible = readiness.filter((r) => !HIDDEN_CAPABILITIES.has(r.capability));

  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Discovery readiness
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 16px" }}>
        {visible.map((r) => (
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
