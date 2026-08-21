"use client";

import type { DefinePanel as DefinePanelData, DraftSpec, Defect } from "@/lib/graphql/queries/landing";
import { PanelLabel, SurfaceLink } from "./PanelLabel";
import { VisionWarning } from "@/components/shared/vision-warning";

interface DefinePanelProps {
  define: DefinePanelData;
}

const SEVERITY_COLORS: Record<string, { color: string; bg: string; dim?: boolean }> = {
  P0: { color: "var(--color-red)", bg: "rgba(239, 68, 100, 0.05)" },
  P1: { color: "var(--color-amber)", bg: "rgba(240, 178, 50, 0.05)" },
  P2: { color: "var(--color-amber)", bg: "rgba(240, 178, 50, 0.05)" },
  P3: { color: "var(--color-text-tertiary)", bg: "var(--color-bg-card)", dim: true },
};

const STATUS_BADGE: Record<string, { color: string; bg: string }> = {
  unplanned: { color: "var(--color-text-tertiary)", bg: "rgba(85, 85, 106, 0.12)" },
  writing: { color: "var(--color-amber)", bg: "rgba(240, 178, 50, 0.08)" },
  executing: { color: "var(--color-accent)", bg: "rgba(0, 212, 170, 0.08)" },
  complete: { color: "var(--color-emerald)", bg: "rgba(68, 204, 119, 0.08)" },
};

const SPEC_TYPE_STYLE: Record<string, { color: string; dot: string }> = {
  product: { color: "var(--color-emerald)", dot: "var(--color-emerald)" },
  technical: { color: "var(--color-blue)", dot: "var(--color-blue)" },
  design: { color: "var(--color-violet)", dot: "var(--color-violet)" },
};

function DraftSpecItem({ spec }: { spec: DraftSpec }) {
  const badge = STATUS_BADGE[spec.status] ?? STATUS_BADGE.unplanned;
  return (
    <div
      style={{
        padding: "10px 10px",
        borderRadius: 7,
        cursor: "pointer",
        transition: "background 0.1s",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.02)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span
          title={spec.name}
          style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}
        >
          {spec.name}
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            fontWeight: 600,
            padding: "1px 5px",
            borderRadius: 3,
            textTransform: "uppercase",
            letterSpacing: "0.03em",
            color: badge.color,
            background: badge.bg,
          }}
        >
          {spec.status}
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        {(["product", "technical", "design"] as const).map((type) => {
          const has = spec.specTypes.includes(type);
          const st = SPEC_TYPE_STYLE[type] ?? { color: "var(--color-text-tertiary)", dot: "var(--color-text-tertiary)" };
          const color = has ? st.color : "var(--color-text-tertiary)";
          const dotColor = has ? st.dot : "var(--color-text-tertiary)";
          const bg = has ? `color-mix(in srgb, ${st.dot} 10%, transparent)` : "rgba(85, 85, 106, 0.06)";
          const opacity = has ? 1 : 0.35;
          return (
            <span
              key={type}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 3,
                fontSize: 9,
                fontWeight: 500,
                color,
                background: bg,
                padding: "2px 6px",
                borderRadius: 9999,
                opacity,
              }}
            >
              <span style={{ width: 4, height: 4, borderRadius: "50%", background: dotColor, display: "inline-block" }} />
              {type.charAt(0).toUpperCase() + type.slice(1)}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 9,
        fontWeight: 500,
        color: "var(--color-text-tertiary)",
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        marginTop: 20,
        marginBottom: 6,
      }}
    >
      {children}
    </div>
  );
}

function DefectRow({ defect }: { defect: Defect }) {
  const style = SEVERITY_COLORS[defect.severity] ?? SEVERITY_COLORS.P3;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 0",
        cursor: "pointer",
        opacity: style.dim ? 0.35 : 1,
        transition: "opacity 0.08s",
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 8,
          fontWeight: 600,
          padding: "1px 4px",
          borderRadius: 2,
          minWidth: 20,
          textAlign: "center",
          background: style.bg,
          color: style.color,
        }}
      >
        {defect.severity}
      </span>
      <span
        title={defect.name}
        style={{
          fontSize: 11,
          color: "var(--color-text-secondary)",
          flex: 1,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {defect.name}
      </span>
    </div>
  );
}

const MAX_VISIBLE = 5;

function ViewAllLink({ href, count }: { href: string; count: number }) {
  return (
    <a
      href={href}
      style={{
        fontSize: 11,
        color: "var(--color-violet)",
        fontWeight: 500,
        display: "flex",
        alignItems: "center",
        gap: 4,
        marginTop: 4,
        cursor: "pointer",
        textDecoration: "none",
      }}
    >
      View all {count}
      <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
        <path d="M5 12h14M12 5l7 7-7 7" />
      </svg>
    </a>
  );
}

export function DefinePanel({ define }: DefinePanelProps) {
  const { visionStatus, draftSpecs, defects } = define;

  const visibleSpecs = draftSpecs.slice(0, MAX_VISIBLE);
  const visibleDefects = defects.slice(0, MAX_VISIBLE);

  return (
    <>
      <PanelLabel name="Define" subtitle="Specs and Preparation" color="var(--color-violet)" />

      {visionStatus === "missing" && <VisionWarning />}

      {draftSpecs.length > 0 && (
        <SectionLabel>Specs · {draftSpecs.length}</SectionLabel>
      )}
      {visibleSpecs.map((spec) => (
        <DraftSpecItem key={spec.name} spec={spec} />
      ))}
      {draftSpecs.length > MAX_VISIBLE && (
        <ViewAllLink href="/specs" count={draftSpecs.length} />
      )}

      {defects.length > 0 && (
        <>
          <SectionLabel>Defects · {defects.length}</SectionLabel>
          {visibleDefects.map((defect, i) => (
            <DefectRow key={i} defect={defect} />
          ))}
          {defects.length > MAX_VISIBLE && (
            <ViewAllLink href="/defects" count={defects.length} />
          )}
        </>
      )}

      {draftSpecs.length === 0 && defects.length === 0 && visionStatus !== "missing" && (
        <p style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>Nothing to review.</p>
      )}

      <SurfaceLink href="/define" label="Open Define Surface" color="var(--color-violet)" />
    </>
  );
}
