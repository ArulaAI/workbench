"use client";

import type {
  LearnPanel as LearnPanelData,
  CoverageTrend as CoverageTrendItem,
  Insight,
  EscalationTrend as EscalationTrendItem,
} from "@/lib/graphql/queries/landing";
import { PanelLabel, SurfaceLink } from "./PanelLabel";

function ViewAllLink({ href, count }: { href: string; count: number }) {
  return (
    <a
      href={href}
      style={{
        fontSize: 11,
        color: "var(--color-blue)",
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

function CoverageTrendRow({ feature, coveragePct }: CoverageTrendItem) {
  const isHighlight = coveragePct >= 90;
  const barColor = isHighlight ? "var(--color-accent)" : "var(--color-text-tertiary)";
  const valColor = isHighlight ? "var(--color-accent)" : "var(--color-text-tertiary)";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.025)" }}>
      <span
        style={{
          fontSize: 12,
          color: isHighlight ? "var(--color-text)" : "var(--color-text-secondary)",
          fontWeight: isHighlight ? 500 : 400,
          flex: 1,
        }}
      >
        {feature}
      </span>
      <div style={{ width: 48, height: 3, background: "rgba(255,255,255,0.04)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${Math.min(100, coveragePct)}%`, background: barColor, borderRadius: 2 }} />
      </div>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 500, minWidth: 36, textAlign: "right", color: valColor }}>
        {Math.round(coveragePct)}%
      </span>
    </div>
  );
}

function InsightCard({ type, text }: Insight) {
  const isGood = type === "good";
  const borderColor = isGood ? "rgba(68, 204, 119, 0.08)" : "rgba(240, 178, 50, 0.08)";
  const bgColor = isGood ? "rgba(68, 204, 119, 0.04)" : "rgba(240, 178, 50, 0.04)";
  const iconColor = isGood ? "var(--color-emerald)" : "var(--color-amber)";

  return (
    <div
      style={{
        padding: "10px 12px",
        borderRadius: 7,
        marginTop: 8,
        fontSize: 11,
        color: "var(--color-text-secondary)",
        lineHeight: 1.6,
        background: bgColor,
        border: `1px solid ${borderColor}`,
      }}
    >
      <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke={iconColor} strokeWidth={2} style={{ verticalAlign: -1, marginRight: 4 }}>
        {isGood ? (
          <path d="M20 6L9 17l-5-5" />
        ) : (
          <>
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4M12 16h.01" />
          </>
        )}
      </svg>
      {text}
    </div>
  );
}

function EscalationTrendRow({ feature, count }: EscalationTrendItem) {
  const isHighlight = count > 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.025)" }}>
      <span style={{ fontSize: 12, color: isHighlight ? "var(--color-text)" : "var(--color-text-secondary)", fontWeight: isHighlight ? 500 : 400, flex: 1 }}>
        {feature}
      </span>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 500, color: isHighlight ? "var(--color-accent)" : "var(--color-text-tertiary)" }}>
        {count}
      </span>
    </div>
  );
}

export function LearnPanel({
  coverageTrend,
  insights,
  escalationTrend,
}: LearnPanelData) {
  const isEmpty =
    coverageTrend.length === 0 &&
    insights.length === 0 &&
    escalationTrend.length === 0;

  const sortedCoverage = [...coverageTrend].sort(
    (a, b) => b.coveragePct - a.coveragePct
  );
  const visibleInsights = insights.slice(0, 5);

  const MAX_VISIBLE = 5;
  const visibleCoverage = sortedCoverage.slice(0, MAX_VISIBLE);
  const visibleEscalation = escalationTrend.slice(0, MAX_VISIBLE);

  return (
    <>
      <PanelLabel name="Learn" subtitle="Patterns and Improvement" color="var(--color-blue)" />

      {isEmpty ? (
        <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", lineHeight: 1.6 }}>
          No learning data yet.
        </div>
      ) : (
        <>
          {visibleCoverage.length > 0 && (
            <>
              <SectionLabel>Coverage trend</SectionLabel>
              {visibleCoverage.map((item) => (
                <CoverageTrendRow key={item.feature} {...item} />
              ))}
              {sortedCoverage.length > MAX_VISIBLE && (
                <ViewAllLink href="/learning" count={sortedCoverage.length} />
              )}
            </>
          )}

          {visibleInsights.length > 0 && (
            <>
              <SectionLabel>Latest insights</SectionLabel>
              {visibleInsights.map((insight, i) => (
                <InsightCard key={i} {...insight} />
              ))}
            </>
          )}

          {visibleEscalation.length > 0 && (
            <>
              <SectionLabel>Escalation trend</SectionLabel>
              {visibleEscalation.map((item) => (
                <EscalationTrendRow key={item.feature} {...item} />
              ))}
              {escalationTrend.length > MAX_VISIBLE && (
                <ViewAllLink href="/learning" count={escalationTrend.length} />
              )}
            </>
          )}
        </>
      )}

      <SurfaceLink href="/learning" label="Open Learn Surface" color="var(--color-blue)" />
    </>
  );
}
