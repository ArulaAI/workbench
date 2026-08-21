"use client";

interface PanelLabelProps {
  name: string;
  subtitle: string;
  color?: string;
}

export function PanelLabel({ name, subtitle, color }: PanelLabelProps) {
  return (
    <div>
      <div
        style={{
          fontSize: 15,
          fontWeight: 600,
          letterSpacing: "-0.01em",
          marginBottom: 4,
          color: color ?? "var(--color-text)",
        }}
      >
        {name}
      </div>
      <div
        style={{
          fontSize: 11,
          fontWeight: 400,
          color: "var(--color-text-tertiary)",
          marginBottom: 16,
        }}
      >
        {subtitle}
      </div>
    </div>
  );
}

export function SurfaceLink({ href, label, color }: { href: string; label: string; color?: string }) {
  return (
    <a
      href={href}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 4,
        fontSize: 11,
        fontWeight: 500,
        color: color ?? "var(--color-text-tertiary)",
        textDecoration: "none",
        marginTop: 16,
        paddingTop: 12,
        borderTop: "1px solid rgba(255,255,255,0.025)",
        cursor: "pointer",
      }}
    >
      {label}
      <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
        <path d="M5 12h14M12 5l7 7-7 7" />
      </svg>
    </a>
  );
}
