"use client";

import { useState } from "react";

/* ── Types ─────────────────────────────────────────────────── */

interface CodebaseClusterProps {
  name: string;
  count: number;
  files: string[];
  description?: string;
  colorIndex: number;
}

/* ── Dot colors ────────────────────────────────────────────── */

const DOT_COLORS = [
  "rgba(139,92,246,0.5)",   // violet
  "rgba(75,166,238,0.5)",   // blue
  "rgba(68,204,119,0.5)",   // emerald
  "rgba(240,178,50,0.5)",   // amber
  "rgba(0,212,170,0.5)",    // accent
  "rgba(255,102,153,0.5)",  // rose
  "rgba(68,221,238,0.5)",   // cyan
];

/* ── Component ─────────────────────────────────────────────── */

export function CodebaseCluster({
  name,
  count,
  files,
  description,
  colorIndex,
}: CodebaseClusterProps) {
  const [expanded, setExpanded] = useState(false);
  const [expandHovered, setExpandHovered] = useState(false);

  const dotColor = DOT_COLORS[colorIndex % DOT_COLORS.length];
  const visibleFiles = expanded ? files : files.slice(0, 2);
  const remaining = files.length - 2;

  return (
    <div style={{ marginBottom: 10 }}>
      {/* Header row: dot + name + count */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: dotColor,
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontSize: 12,
            fontWeight: 500,
            color: "var(--color-text)",
            flex: 1,
          }}
        >
          {name}
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            fontWeight: 400,
            color: "var(--color-text-tertiary)",
          }}
        >
          {count}
        </span>
      </div>

      {/* File names */}
      {files.length > 0 && (
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--color-text-tertiary)",
            marginTop: 4,
            paddingLeft: 14, // align with text after dot
            lineHeight: 1.6,
          }}
        >
          {visibleFiles.join(" \u00b7 ")}
          {!expanded && remaining > 0 && (
            <span
              role="button"
              tabIndex={0}
              onClick={() => setExpanded(true)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setExpanded(true);
                }
              }}
              onMouseEnter={() => setExpandHovered(true)}
              onMouseLeave={() => setExpandHovered(false)}
              style={{
                marginLeft: 4,
                cursor: "pointer",
                color: expandHovered
                  ? "var(--color-text-secondary)"
                  : "var(--color-text-tertiary)",
                transition: "color 0.15s",
              }}
            >
              +{remaining}
            </span>
          )}
        </div>
      )}

      {/* Description */}
      {description && (
        <div
          style={{
            fontSize: 11,
            color: "var(--color-text-secondary)",
            marginTop: 4,
            paddingLeft: 14,
            lineHeight: 1.5,
          }}
        >
          {description}
        </div>
      )}
    </div>
  );
}
