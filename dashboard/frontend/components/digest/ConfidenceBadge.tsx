import type { DigestConfidence } from "@/lib/graphql/queries/repository-digest";

const LABELS: Record<DigestConfidence, string> = {
  CONFIRMED: "Confirmed",
  DERIVED: "Derived",
  INFERRED: "Inferred",
  UNKNOWN: "Unknown",
};

const COLORS: Record<DigestConfidence, string> = {
  CONFIRMED: "var(--color-emerald)",
  DERIVED: "var(--color-blue)",
  INFERRED: "var(--color-amber)",
  UNKNOWN: "var(--color-text-tertiary)",
};

export function ConfidenceBadge({ confidence }: { confidence: DigestConfidence }) {
  const color = COLORS[confidence];
  return (
    <span
      className="type-badge"
      style={{
        color,
        background: `color-mix(in srgb, ${color} 14%, transparent)`,
        padding: "4px 8px",
        borderRadius: 999,
        display: "inline-block",
      }}
    >
      {LABELS[confidence]}
    </span>
  );
}
