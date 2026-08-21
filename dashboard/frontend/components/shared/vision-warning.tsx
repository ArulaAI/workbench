interface VisionWarningProps {
  variant?: "card" | "full";
}

export function VisionWarning({ variant = "card" }: VisionWarningProps) {
  return (
    <div
      style={{
        padding: 14,
        marginBottom: 10,
        border: "1.5px dashed rgba(239, 68, 100, 0.20)",
        borderRadius: 9,
        background: "linear-gradient(135deg, rgba(239, 68, 100, 0.025) 0%, transparent 50%)",
        cursor: "pointer",
        transition: "border-color 0.15s",
        width: variant === "full" ? "100%" : undefined,
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-red)", marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
        <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
          <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
          <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
        </svg>
        Product vision missing
      </div>
      <div style={{ fontSize: 11, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
        <code style={{ fontFamily: "var(--font-mono)", fontSize: 10, background: "var(--color-bg-card)", padding: "1px 4px", borderRadius: 3, color: "var(--color-text-tertiary)" }}>overview.md</code> is missing. Guardian alignment and Architect planning depend on it.
      </div>
      <div style={{ fontSize: 11, color: "var(--color-violet)", fontWeight: 500, marginTop: 8, display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
        Create vision
        <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M5 12h14M12 5l7 7-7 7" />
        </svg>
      </div>
    </div>
  );
}
