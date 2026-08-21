"use client";

import { useState } from "react";
import { useQuery } from "urql";
import {
  ChevronDown,
  ChevronRight,
  Check,
  X,
  HelpCircle,
  Copy,
  CheckCircle,
} from "lucide-react";
import {
  SPEC_ALIGNMENT_QUERY,
  type SpecAlignmentClaim,
  type SpecAlignmentSection,
  type SpecAlignmentSpec,
  type SpecAlignmentView,
} from "@/lib/graphql/queries/spec-alignment";
import { ProgressBar } from "@/components/shared/progress-bar";
import { CardSkeleton } from "@/components/shared/loading-skeleton";
import { formatPercent } from "@/lib/utils/format";
import { coverageColor } from "@/lib/utils/colors";

/* ── Claim status helpers ──────────────────────────────────────── */

const statusConfig: Record<
  string,
  { icon: typeof Check; color: string; bg: string; label: string }
> = {
  confirmed: {
    icon: Check,
    color: "var(--color-emerald)",
    bg: "rgba(68, 204, 119, 0.10)",
    label: "Confirmed",
  },
  missing: {
    icon: X,
    color: "var(--color-red)",
    bg: "rgba(239, 68, 100, 0.10)",
    label: "Missing",
  },
  unverifiable: {
    icon: HelpCircle,
    color: "var(--color-text-tertiary)",
    bg: "rgba(85, 85, 106, 0.10)",
    label: "Unverifiable",
  },
  divergent: {
    icon: HelpCircle,
    color: "var(--color-amber)",
    bg: "rgba(240, 178, 50, 0.10)",
    label: "Divergent",
  },
};

/* ── Claim Row ─────────────────────────────────────────────────── */

function ClaimRow({ claim }: { claim: SpecAlignmentClaim }) {
  const cfg = statusConfig[claim.status] || statusConfig.unverifiable;
  const Icon = cfg.icon;
  const [copied, setCopied] = useState(false);

  const copyEvidence = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!claim.evidence) return;
    navigator.clipboard.writeText(claim.evidence);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div
      className="flex gap-3 border-l-2 py-2.5 pl-4 pr-3"
      style={{ borderLeftColor: cfg.color }}
    >
      <Icon
        className="mt-0.5 h-3.5 w-3.5 shrink-0"
        style={{ color: cfg.color }}
      />
      <div className="min-w-0 flex-1">
        <div className="type-body">{claim.claimText}</div>
        {claim.evidence && (
          <button
            onClick={copyEvidence}
            className="mt-1.5 flex items-center gap-1.5 rounded px-1.5 py-0.5 text-text-tertiary transition-colors hover:bg-bg-card-hover hover:text-accent"
          >
            {copied ? (
              <CheckCircle className="h-3 w-3 text-emerald" />
            ) : (
              <Copy className="h-3 w-3" />
            )}
            <span
              className="max-w-md truncate text-[11px]"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {copied ? "Copied" : claim.evidence}
            </span>
          </button>
        )}
        {claim.divergence && (
          <div className="mt-1 text-[11px] text-amber">
            Divergence: {claim.divergence}
          </div>
        )}
      </div>
      <div className="shrink-0">
        <span
          className="type-badge rounded-full px-2 py-0.5"
          style={{ color: cfg.color, backgroundColor: cfg.bg }}
        >
          {cfg.label}
        </span>
      </div>
    </div>
  );
}

/* ── Section Row ───────────────────────────────────────────────── */

function SectionRow({ section }: { section: SpecAlignmentSection }) {
  const [expanded, setExpanded] = useState(false);
  const Chevron = expanded ? ChevronDown : ChevronRight;

  return (
    <div className="border-b border-border/30 last:border-b-0">
      {/* Section header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-bg-elevated/50"
      >
        <Chevron className="h-3.5 w-3.5 shrink-0 text-text-tertiary" />

        {/* Section name */}
        <span className="type-section-header min-w-0 flex-1 truncate">
          {section.section}
        </span>

        {/* Progress bar */}
        <div className="w-48 shrink-0">
          <ProgressBar
            total={section.claimCount}
            segments={[
              { value: section.confirmed, color: "var(--color-emerald)", label: "Confirmed" },
              { value: section.missing, color: "var(--color-red)", label: "Missing" },
              { value: section.unverifiable, color: "var(--color-text-tertiary)", label: "Other" },
            ]}
            height={4}
          />
        </div>

        {/* Coverage % */}
        <span
          className="w-14 shrink-0 text-right text-[13px] font-semibold tabular-nums"
          style={{
            fontFamily: "var(--font-mono)",
            color: coverageColor(section.coveragePct),
          }}
        >
          {formatPercent(section.coveragePct)}
        </span>

        {/* Fraction */}
        <span className="w-12 shrink-0 text-right font-mono text-[11px] text-text-tertiary">
          {section.confirmed}/{section.claimCount}
        </span>
      </button>

      {/* Expanded claims */}
      {expanded && (
        <div className="space-y-0.5 bg-bg/50 px-4 pb-3 pl-10">
          {section.claims.map((claim, i) => (
            <ClaimRow key={i} claim={claim} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Page ──────────────────────────────────────────────────────── */

export default function SpecAlignmentPage() {
  const [{ data, fetching, error }] = useQuery({
    query: SPEC_ALIGNMENT_QUERY,
  });

  if (fetching) {
    return (
      <div className="grid gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="surface p-4 text-red">Error: {error.message}</div>
    );
  }

  const sa: SpecAlignmentView | undefined = data?.specAlignment;
  if (!sa) {
    return (
      <div className="text-text-secondary">
        No spec alignment data found. Run{" "}
        <code className="rounded bg-bg-card px-1.5 py-0.5 text-accent">
          speed plan
        </code>{" "}
        to generate.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="surface flex items-center gap-8 px-5 py-3">
        <Stat
          label="Coverage"
          value={formatPercent(sa.overallCoveragePct)}
          color={coverageColor(sa.overallCoveragePct)}
        />
        <Stat label="Claims" value={sa.totalClaims} />
        <Stat label="Confirmed" value={sa.totalConfirmed} color="var(--color-emerald)" />
        <Stat label="Missing" value={sa.totalMissing} color="var(--color-red)" />

        {/* Overall progress */}
        <div className="ml-auto w-64">
          <ProgressBar
            total={sa.totalClaims}
            segments={[
              { value: sa.totalConfirmed, color: "var(--color-emerald)", label: "Confirmed" },
              { value: sa.totalMissing, color: "var(--color-red)", label: "Missing" },
              { value: sa.totalUnverifiable, color: "var(--color-text-tertiary)", label: "Other" },
            ]}
            height={4}
          />
        </div>
      </div>

      {/* Spec tables */}
      {sa.specs.map((spec: SpecAlignmentSpec) => (
          <div key={spec.specFile} className="surface overflow-hidden">
            {/* Spec file header */}
            <div
              className="flex items-center justify-between border-b border-border px-5 py-3"
              style={{
                boxShadow: "0 1px 2px rgba(0,0,0,0.1)",
              }}
            >
              <span
                className="text-[13px] font-semibold text-text"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {spec.specFile.split("/").pop()}
              </span>
              <div className="flex items-center gap-4">
                <span className="type-caption">
                  {spec.confirmed}/{spec.totalClaims} claims
                </span>
                <span
                  className="text-[15px] font-bold tabular-nums"
                  style={{
                    fontFamily: "var(--font-mono)",
                    color: coverageColor(spec.coveragePct),
                  }}
                >
                  {formatPercent(spec.coveragePct)}
                </span>
              </div>
            </div>

            {/* Column headers */}
            <div className="flex items-center gap-3 border-b border-border/50 px-4 py-2">
              <span className="type-table-header flex-1 pl-7">Section</span>
              <span className="type-table-header w-48 shrink-0">Coverage</span>
              <span className="type-table-header w-14 shrink-0 text-right">%</span>
              <span className="type-table-header w-12 shrink-0 text-right">Done</span>
            </div>

            {/* Sections */}
            <div>
              {spec.sections.map((sec: SpecAlignmentSection) => (
                <SectionRow key={sec.section} section={sec} />
              ))}
            </div>
          </div>
        )
      )}
    </div>
  );
}

/* ── Stat ──────────────────────────────────────────────────────── */

function Stat({
  label,
  value,
  color,
}: {
  label: string;
  value: number | string;
  color?: string;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span
        className="text-[18px] font-semibold tabular-nums"
        style={{
          fontFamily: "var(--font-mono)",
          color: color ?? "var(--color-text)",
        }}
      >
        {value}
      </span>
      <span className="type-kpi-label">{label}</span>
    </div>
  );
}
