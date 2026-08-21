export type BadgeState = "complete" | "executing" | "writing" | "unplanned";

const BADGE_STYLES: Record<BadgeState, { background: string; color: string }> = {
  complete: {
    background: "rgba(68, 204, 119, 0.12)",
    color: "var(--color-emerald)",
  },
  executing: {
    background: "rgba(0, 212, 170, 0.10)",
    color: "var(--color-accent)",
  },
  writing: {
    background: "rgba(240, 178, 50, 0.08)",
    color: "var(--color-amber)",
  },
  unplanned: {
    background: "rgba(85, 85, 106, 0.12)",
    color: "var(--color-text-tertiary)",
  },
};

const BADGE_LABELS: Record<BadgeState, string> = {
  complete: "COMPLETE",
  executing: "EXECUTING",
  writing: "WRITING",
  unplanned: "UNPLANNED",
};

export function StateBadge({ state }: { state: BadgeState }) {
  const { background, color } = BADGE_STYLES[state] ?? BADGE_STYLES.unplanned;
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 8,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.03em",
        lineHeight: 1,
        color,
        background,
        padding: "2px 5px",
        borderRadius: 3,
        display: "inline-flex",
        alignItems: "center",
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      {BADGE_LABELS[state] ?? state.toUpperCase()}
    </span>
  );
}
