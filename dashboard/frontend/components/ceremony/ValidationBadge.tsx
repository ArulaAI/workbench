"use client";

import React from "react";
import {
  FileCheck,
  ListChecks,
  GitCompare,
  Code2,
  Ruler,
  Eye,
} from "lucide-react";
import type { ValidationDimension } from "@/lib/graphql/queries/ceremony";

const DIMENSION_ICONS: Record<string, React.ElementType> = {
  template: FileCheck,
  structure: ListChecks,
  cross_spec: GitCompare,
  codebase: Code2,
  sizing: Ruler,
  vision: Eye,
};

const DIMENSION_LABELS: Record<string, string> = {
  template: "Template",
  structure: "Structure",
  cross_spec: "Cross-spec",
  codebase: "Codebase",
  sizing: "Sizing",
  vision: "Vision",
};

const STATUS_COLORS: Record<string, string> = {
  pass: "var(--color-emerald)",
  warn: "var(--color-amber)",
  fail: "var(--color-red)",
  pending: "var(--color-text-tertiary)",
  stale: "var(--color-text-tertiary)",
};

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ago`;
}

interface ValidationBadgeProps {
  dimension: ValidationDimension;
  stale: boolean;
  expanded: boolean;
  onClick: () => void;
}

export function ValidationBadge({
  dimension,
  stale,
  expanded,
  onClick,
}: ValidationBadgeProps) {
  const Icon = DIMENSION_ICONS[dimension.name] || FileCheck;
  const label = DIMENSION_LABELS[dimension.name] || dimension.name;
  const color = STATUS_COLORS[dimension.status] || STATUS_COLORS.pending;
  const issueCount = dimension.issues.length;
  const opacity = stale ? 0.5 : 1;

  const tooltip = stale && dimension.checkedAt
    ? `${label}: ${dimension.status} (last checked: ${relativeTime(dimension.checkedAt)})`
    : `${label}: ${dimension.status}${issueCount > 0 ? ` (${issueCount} issue${issueCount > 1 ? "s" : ""})` : ""}`;

  return (
    <button
      onClick={onClick}
      title={tooltip}
      style={{
        display: "flex",
        alignItems: "center",
        gap: expanded ? 8 : 0,
        padding: expanded ? "6px 8px" : "6px 4px",
        width: "100%",
        background: "transparent",
        border: "none",
        borderRadius: 4,
        cursor: "pointer",
        opacity,
        transition: "background 150ms ease",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.background = "var(--color-bg-card-hover)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.background = "transparent";
      }}
    >
      <div style={{ position: "relative", flexShrink: 0 }}>
        <Icon size={14} style={{ color }} />
        {issueCount > 0 && (
          <span
            style={{
              position: "absolute",
              top: -4,
              right: -6,
              fontSize: 9,
              fontFamily: "var(--font-mono)",
              fontWeight: 600,
              color: "var(--color-bg)",
              background: color,
              borderRadius: 6,
              minWidth: 12,
              height: 12,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "0 2px",
              lineHeight: 1,
            }}
          >
            {issueCount > 9 ? "9+" : issueCount}
          </span>
        )}
      </div>
      {expanded && (
        <span
          style={{
            fontSize: 11,
            color: "var(--color-text-secondary)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {label}
        </span>
      )}
    </button>
  );
}
