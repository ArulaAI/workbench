"use client";

import Link from "next/link";
import type { JudgePanel as JudgePanelData, CompletedFeature, DecisionItem, QualityGate } from "@/lib/graphql/queries/landing";
import { PanelLabel, SurfaceLink } from "./PanelLabel";

interface JudgePanelProps {
  judge: JudgePanelData;
  narrative: string | null;
}

function formatDate(isoString: string | null): string {
  if (!isoString) return "";
  return new Date(isoString).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function GuardianMetric({ verdict }: { verdict: string }) {
  const container: React.CSSProperties = { height: 28, display: "flex", alignItems: "flex-end" };
  if (verdict === "approve" || verdict === "pass") {
    return (
      <div style={container}>
        <svg width={22} height={22} viewBox="0 0 24 24" fill="none" stroke="var(--color-emerald)" strokeWidth={2.5}>
          <path d="M20 6L9 17l-5-5" />
        </svg>
      </div>
    );
  }
  if (verdict === "unknown" || !verdict) {
    return (
      <div style={container}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 28, fontWeight: 600, lineHeight: 1, color: "var(--color-text-tertiary)" }}>
          —
        </span>
      </div>
    );
  }
  return (
    <div style={container}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 28, fontWeight: 600, lineHeight: 1, color: "var(--color-text)" }}>
        {verdict}
      </span>
    </div>
  );
}

function GuardianInline({ verdict }: { verdict: string }) {
  if (verdict === "approve" || verdict === "pass") {
    return (
      <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="var(--color-emerald)" strokeWidth={2.5} style={{ verticalAlign: -2 }}>
        <path d="M20 6L9 17l-5-5" />
      </svg>
    );
  }
  if (verdict === "unknown" || !verdict) {
    return <span style={{ color: "var(--color-text-tertiary)" }}>—</span>;
  }
  return <span style={{ fontSize: 11, color: "var(--color-red)" }}>{verdict}</span>;
}

/* ── Hero feature (first / most urgent) ── */

function HeroSummary({ features, narrative }: { features: CompletedFeature[]; narrative: string | null }) {
  if (narrative) {
    return (
      <div style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 20 }}>
        {narrative}
      </div>
    );
  }

  const totalPassed = features.reduce((s, f) => s + f.criteriaPassed, 0);
  const totalCriteria = features.reduce((s, f) => s + f.criteriaTotal, 0);
  const pct = totalCriteria > 0 ? Math.round(totalPassed / totalCriteria * 100) : 0;
  return (
    <div style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 20 }}>
      <strong style={{ color: "var(--color-text)", fontWeight: 500 }}>{pct}% requirement coverage</strong> across {features.length} feature{features.length === 1 ? "" : "s"}.{" "}
      {totalPassed} of {totalCriteria} criteria passed.
    </div>
  );
}

function HeroMetrics({ features }: { features: CompletedFeature[] }) {
  const totalPassed = features.reduce((s, f) => s + f.criteriaPassed, 0);
  const totalCriteria = features.reduce((s, f) => s + f.criteriaTotal, 0);
  const avgCoverage = totalCriteria > 0 ? Math.round(totalPassed / totalCriteria * 100) : 0;
  const totalDecisions = features.reduce((s, f) => s + f.decisionsNeeded, 0);

  // Guardian: worst-case across features
  const verdicts = features.map(f => f.guardianVerdict);
  const hasReject = verdicts.some(v => v === "reject");
  const hasFlag = verdicts.some(v => v === "flag");
  const allApproved = verdicts.every(v => v === "approve" || v === "pass");
  const aggregateVerdict = hasReject ? "reject" : hasFlag ? "flag" : allApproved ? "approve" : "unknown";

  return (
    <div style={{ display: "flex", gap: 28, marginBottom: 20 }}>
      <div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 28, fontWeight: 600, lineHeight: 1, color: "var(--color-accent)" }}>
          {avgCoverage}<span style={{ fontSize: 15, fontWeight: 400, color: "var(--color-text-tertiary)" }}>%</span>
        </div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.04em", marginTop: 4 }}>Coverage</div>
      </div>
      <div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 28, fontWeight: 600, lineHeight: 1, color: "var(--color-text)" }}>
          {totalPassed}<span style={{ fontSize: 15, fontWeight: 400, color: "var(--color-text-tertiary)" }}>/{totalCriteria}</span>
        </div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.04em", marginTop: 4 }}>Criteria</div>
      </div>
      <div>
        <GuardianMetric verdict={aggregateVerdict} />
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.04em", marginTop: 4 }}>Guardian</div>
      </div>
      <div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 28, fontWeight: 600, lineHeight: 1, color: totalDecisions > 0 ? "var(--color-amber)" : "var(--color-text-secondary)" }}>
          {totalDecisions}
        </div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.04em", marginTop: 4 }}>Decisions</div>
      </div>
    </div>
  );
}

function HeroDecisions({ items, totalCount }: { items: DecisionItem[]; totalCount: number }) {
  if (totalCount === 0) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-amber)", marginBottom: 8, display: "flex", alignItems: "center", gap: 5 }}>
        <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
          <circle cx="12" cy="12" r="10" />
          <path d="M12 8v4M12 16h.01" />
        </svg>
        Decisions Needed
      </div>
      {items.map((item, i) => {
        // Extract feature tag from description (format: "feature-name · source")
        const parts = item.description?.split(" · ") ?? [];
        const featureTag = parts.length > 1 ? parts[0] : null;
        const source = parts.length > 1 ? parts.slice(1).join(" · ") : item.description;
        return (
          <div key={i} style={{ padding: "8px 0", borderBottom: i < items.length - 1 ? "1px solid rgba(255,255,255,0.025)" : "none", fontSize: 12, color: "var(--color-text-secondary)" }}>
            {featureTag && (
              <span style={{
                fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500,
                padding: "1px 5px", borderRadius: 3,
                color: "var(--color-violet)", background: "rgba(139, 92, 246, 0.08)",
                marginRight: 6,
              }}>
                {featureTag}
              </span>
            )}
            <strong style={{ color: "var(--color-text)", fontWeight: 500 }}>{item.title}</strong>
            {source && <span style={{ color: "var(--color-text-tertiary)" }}> — {source}</span>}
          </div>
        );
      })}
    </div>
  );
}

function HeroSection({ features, narrative }: { features: CompletedFeature[]; narrative: string | null }) {
  const allDecisionItems = features.flatMap(f => f.decisionItems);
  const totalCount = allDecisionItems.length;
  const visibleItems = allDecisionItems.slice(0, 5);

  return (
    <div style={{ marginBottom: 16 }}>
      <HeroSummary features={features} narrative={narrative} />
      <HeroMetrics features={features} />
      <HeroDecisions items={visibleItems} totalCount={totalCount} />
    </div>
  );
}

/* ── Compact row (remaining features) ── */

function CompactRow({ feature }: { feature: CompletedFeature }) {
  const pct = Math.round(feature.coveragePct);
  const dateStr = formatDate(feature.completedAt);
  const isPending = feature.reviewStatus === "pending";

  return (
    <Link href={`/outcome-review?feature=${feature.feature}`} style={{ textDecoration: "none", display: "block" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 0",
          borderBottom: "1px solid rgba(255,255,255,0.025)",
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {feature.feature}
            </span>
            {isPending && (
              <span style={{
                fontFamily: "var(--font-mono)", fontSize: 8, fontWeight: 600,
                padding: "1px 4px", borderRadius: 3, textTransform: "uppercase",
                color: "var(--color-amber)", background: "rgba(240, 178, 50, 0.08)",
              }}>
                Review
              </span>
            )}
          </div>
          {dateStr && (
            <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{dateStr}</span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 500, color: "var(--color-accent)" }}>{pct}%</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)" }}>{feature.criteriaPassed}/{feature.criteriaTotal}</span>
          <GuardianInline verdict={feature.guardianVerdict} />
        </div>
      </div>
    </Link>
  );
}

/* ── Quality gates ── */

const GATE_ICONS: Record<string, { color: string; icon: "check" | "warn" | "dash" }> = {
  pass: { color: "var(--color-emerald)", icon: "check" },
  fail: { color: "var(--color-red)", icon: "warn" },
  warn: { color: "var(--color-amber)", icon: "warn" },
  unknown: { color: "var(--color-text-tertiary)", icon: "dash" },
};

function GateIcon({ type }: { type: "check" | "warn" | "dash" }) {
  if (type === "check") {
    return (
      <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} style={{ verticalAlign: -2 }}>
        <path d="M20 6L9 17l-5-5" />
      </svg>
    );
  }
  if (type === "warn") {
    return (
      <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} style={{ verticalAlign: -2 }}>
        <circle cx="12" cy="12" r="10" />
        <path d="M12 8v4M12 16h.01" />
      </svg>
    );
  }
  return <span style={{ fontSize: 14 }}>—</span>;
}

function QualityGates({ gates }: { gates: QualityGate[] }) {
  if (gates.length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 16, paddingTop: 12, borderTop: "1px solid rgba(255,255,255,0.025)" }}>
      {gates.map((gate) => {
        const style = GATE_ICONS[gate.status] ?? GATE_ICONS.unknown;
        return (
          <div key={gate.name} style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
            <span style={{ color: style.color, flexShrink: 0, marginTop: 1 }}>
              <GateIcon type={style.icon} />
            </span>
            <div>
              <span style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text)" }}>
                {gate.name}
              </span>
              {gate.detail && (
                <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                  {" — "}{gate.detail}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Panel ── */

export function JudgePanel({ judge, narrative }: JudgePanelProps) {
  if (judge.completedFeatures.length === 0) {
    return (
      <>
        <PanelLabel name="Judge" subtitle="Quality Review" color="var(--color-emerald)" />
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>No completed features yet.</p>
      </>
    );
  }

  const subtitle = judge.awaitingReview > 0
    ? `${judge.awaitingReview} Awaiting Review · ${judge.totalFeatures} Complete`
    : `${judge.totalFeatures} Feature${judge.totalFeatures === 1 ? "" : "s"} Complete`;

  return (
    <>
      <PanelLabel name="Judge" subtitle={subtitle} color="var(--color-emerald)" />
      <HeroSection features={judge.completedFeatures} narrative={narrative} />
      <QualityGates gates={judge.qualityGates} />
      {judge.completedFeatures.map((feature) => (
        <CompactRow key={feature.feature} feature={feature} />
      ))}
      <SurfaceLink href="/outcome-review" label="Open Judge Surface" color="var(--color-emerald)" />
    </>
  );
}
