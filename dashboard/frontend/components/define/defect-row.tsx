"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowUpRight, Link2 } from "lucide-react";

import type { DefectData } from "@/lib/graphql/queries/define";
export type { DefectData };

interface DefectRowProps {
  defect: DefectData;
  isCompact?: boolean;
  mode?: "grid" | "table";
  returnPath?: string;
}

function severityColor(severity: string): string {
  if (severity === "P0" || severity === "P1") return "var(--color-red)";
  if (severity === "P2") return "var(--color-amber)";
  return "var(--color-text-tertiary)";
}

function statusStyle(status: string): { color: string; background: string } {
  if (status === "resolved" || status === "rejected") return { color: "var(--color-emerald)", background: "rgba(68, 204, 119, 0.10)" };
  if (status === "filed" || status === "reviewed") return { color: "var(--color-blue)", background: "rgba(75, 166, 238, 0.10)" };
  if (["triaging", "triaged", "reproduced", "fixing", "fixed", "integrating"].includes(status)) return { color: "var(--color-amber)", background: "rgba(240, 178, 50, 0.10)" };
  if (status === "unknown") return { color: "var(--color-red)", background: "rgba(239, 68, 100, 0.10)" };
  return { color: "var(--color-text-secondary)", background: "rgba(148, 148, 163, 0.10)" };
}

function compactDate(value?: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function truncateName(name: string): string {
  return name.length > 40 ? name.slice(0, 40) + "\u2026" : name;
}

function lineClamp(lines: number): CSSProperties {
  return {
    display: "-webkit-box",
    WebkitLineClamp: lines,
    WebkitBoxOrient: "vertical",
    overflow: "hidden",
  } as CSSProperties;
}

export function DefectRow({ defect, isCompact = false, mode = "grid", returnPath }: DefectRowProps) {
  const [hovered, setHovered] = useState(false);
  const isP3 = defect.severity === "P3";
  const badgeColor = severityColor(defect.severity);
  const cellBg = hovered ? "var(--color-bg-card)" : "var(--color-bg)";

  const badge = (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 8,
        fontWeight: 600,
        color: badgeColor,
        flexShrink: 0,
        marginTop: 1,
      }}
    >
      {defect.severity}
    </span>
  );

  const nameEl = (
    <span
      style={{
        fontFamily: "var(--font-sans)",
        fontSize: 12,
        fontWeight: 500,
        color: "var(--color-text)",
        lineHeight: 1.4,
      }}
    >
      {truncateName(defect.title || defect.name)}
    </span>
  );

  const statusEl = (
    <div
      style={{
        fontFamily: "var(--font-sans)",
        fontSize: 12,
        fontWeight: 400,
        color: "var(--color-text-secondary)",
        lineHeight: 1.4,
      }}
    >
      {defect.status}
    </div>
  );

  const descriptionEl = (
    <div
      style={{
        fontFamily: "var(--font-sans)",
        fontSize: 12,
        fontWeight: 400,
        color: "var(--color-text-secondary)",
        lineHeight: 1.5,
        ...lineClamp(3),
      }}
    >
      {defect.description}
    </div>
  );

  const impactEl = (
    <div
      style={{
        fontFamily: "var(--font-sans)",
        fontSize: 12,
        fontWeight: 400,
        color: defect.impact
          ? "var(--color-text-secondary)"
          : "var(--color-text-tertiary)",
        lineHeight: 1.5,
        ...(defect.impact ? lineClamp(2) : {}),
      }}
    >
      {defect.impact ?? "\u2014"}
    </div>
  );

  if (mode === "table") {
    const canonical = defect.canonicalPath;
    const state = statusStyle(defect.status);
    const updated = compactDate(defect.updatedAt || defect.filedAt);
    return (
      <div role="row" className="grid grid-cols-[80px_120px_minmax(260px,1fr)_220px_130px] items-center border-b border-border/70 bg-bg-card transition-colors last:border-b-0 hover:bg-bg-card-hover/60">
        <div role="cell" className="px-4 py-4">
          <span className="inline-flex rounded-full px-2 py-1 font-mono text-[10px] font-semibold" style={{ color: badgeColor, backgroundColor: `color-mix(in srgb, ${badgeColor} 10%, transparent)` }}>{defect.severity}</span>
        </div>
        <div role="cell" className="px-4 py-4">
          <span className="inline-flex rounded-full px-2.5 py-1 text-[10px] font-medium capitalize" style={{ color: state.color, backgroundColor: state.background }}>{defect.status.replaceAll("_", " ")}</span>
        </div>
        <div role="cell" className="min-w-0 px-4 py-4">
          {canonical ? <Link href={`/editor?spec=${encodeURIComponent(canonical)}${returnPath ? `&return=${encodeURIComponent(returnPath)}` : ""}`} className="group inline-flex max-w-full items-center gap-1.5 text-[12px] font-semibold text-text hover:text-accent">
            <span className="truncate">{defect.title || defect.name}</span><ArrowUpRight className="h-3 w-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
          </Link> : <span className="text-[12px] font-semibold text-text-secondary">{defect.title || defect.name}</span>}
          {defect.description && <p className="mt-1 line-clamp-1 text-[10px] text-text-tertiary">{defect.description}</p>}
          {!!defect.warnings?.length && <div className="mt-2 flex items-start gap-1.5 text-[9px] leading-4 text-amber"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" /> <span>{defect.warnings.join(" · ")}</span></div>}
        </div>
        <div role="cell" className="flex flex-wrap gap-1.5 px-4 py-4">{(defect.relatedFeatures || []).length ? defect.relatedFeatures?.map((feature) => <span key={feature} className="rounded-full border border-border bg-bg px-2 py-1 text-[9px] font-medium text-text-secondary">{feature}</span>) : <span className="text-[10px] italic text-text-tertiary">Unassigned</span>}</div>
        <div role="cell" className="px-4 py-4">
          <div className="text-[10px] font-medium capitalize text-text-secondary">{(defect.source || "unknown").replaceAll("_", " ")}</div>
          {updated && <div className="mt-1 font-mono text-[8px] text-text-tertiary">{updated}</div>}
          {defect.sourceFeature && defect.sourceFindingId && <Link className="mt-1.5 inline-flex items-center gap-1 text-[9px] text-blue hover:underline" href={`/define/${defect.sourceFeature}/findings?finding=${encodeURIComponent(defect.sourceFindingId)}${returnPath ? `&return=${encodeURIComponent(returnPath)}` : ""}`}><Link2 className="h-2.5 w-2.5" /> Finding</Link>}
        </div>
      </div>
    );
  }

  if (isCompact) {
    return (
      <div
        style={{
          padding: "12px 20px",
          background: cellBg,
          transition: "background 0.15s",
          opacity: isP3 ? 0.45 : 1,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
          {badge}
          {nameEl}
        </div>
        {statusEl}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {descriptionEl}
          {impactEl}
        </div>
      </div>
    );
  }

  const cellBase: CSSProperties = {
    padding: "12px 20px",
    background: cellBg,
    transition: "background 0.15s",
  };

  return (
    <div
      style={{
        gridColumn: "1 / -1",
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        gap: 1,
        background: "var(--color-border)",
        opacity: isP3 ? 0.45 : 1,
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Col 1: severity badge + name */}
      <div
        style={{
          ...cellBase,
          display: "flex",
          alignItems: "flex-start",
          gap: 8,
        }}
      >
        {badge}
        {nameEl}
      </div>

      {/* Col 2: status */}
      <div style={cellBase}>{statusEl}</div>

      {/* Col 3: description + impact */}
      <div
        style={{
          ...cellBase,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {descriptionEl}
        {impactEl}
      </div>
    </div>
  );
}
