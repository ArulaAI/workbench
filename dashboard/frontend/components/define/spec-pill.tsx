export type PillLabel = "Product" | "Technical" | "Design";
export type PillState = "present" | "warning" | "missing";

interface PillStyle {
  background: string;
  color: string;
  borderWidth: string;
  borderStyle: string;
  borderColor: string;
}

const PILL_STYLES: Record<PillState, PillStyle> = {
  present: {
    background: "rgba(68, 204, 119, 0.06)",
    color: "var(--color-emerald)",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "transparent",
  },
  warning: {
    background: "rgba(240, 178, 50, 0.06)",
    color: "var(--color-amber)",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "transparent",
  },
  missing: {
    background: "var(--color-bg-card)",
    color: "var(--color-text-tertiary)",
    borderWidth: "1px",
    borderStyle: "dashed",
    borderColor: "var(--color-text-tertiary)",
  },
};

export function SpecPill({ label, state }: { label: PillLabel; state: PillState }) {
  const { background, color, borderWidth, borderStyle, borderColor } = PILL_STYLES[state];
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 9,
        fontWeight: 500,
        lineHeight: 1,
        letterSpacing: "0.04em",
        color,
        background,
        borderWidth,
        borderStyle,
        borderColor,
        padding: "3px 6px",
        borderRadius: 3,
        display: "inline-flex",
        alignItems: "center",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}
