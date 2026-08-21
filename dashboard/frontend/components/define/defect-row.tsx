"use client";

import { useState } from "react";
import type { CSSProperties } from "react";

import type { DefectData } from "@/lib/graphql/queries/define";
export type { DefectData };

interface DefectRowProps {
  defect: DefectData;
  isCompact?: boolean;
}

function severityColor(severity: string): string {
  if (severity === "P0" || severity === "P1") return "var(--color-red)";
  if (severity === "P2") return "var(--color-amber)";
  return "var(--color-text-tertiary)";
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

export function DefectRow({ defect, isCompact = false }: DefectRowProps) {
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
      {truncateName(defect.name)}
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
