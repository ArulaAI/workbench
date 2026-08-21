"use client";

import { useState } from "react";
import type {
  ContextPackage,
  CodebaseItem,
  LearningItem,
  DefectItem,
  KnowledgeItem,
  RelatedFeature,
  AuditHistoryItem,
} from "@/lib/graphql/queries/ceremony";

/* ── Props ─────────────────────────────────────────────────── */

interface ContextSnapshotProps {
  contextPackage: ContextPackage;
  assembledAt: string;
}

/* ── Badge helpers ─────────────────────────────────────────── */

const badgeStyle = (color: string, bg: string): React.CSSProperties => ({
  display: "inline-block",
  fontFamily: "var(--font-sans)",
  fontSize: 10,
  fontWeight: 500,
  padding: "1px 5px",
  borderRadius: 3,
  marginRight: 4,
  color,
  background: bg,
});

const CONFIDENCE_BADGES: Record<string, React.CSSProperties> = {
  high: badgeStyle("var(--color-emerald)", "rgba(68, 204, 119, 0.12)"),
  medium: badgeStyle("var(--color-amber)", "rgba(240, 178, 50, 0.12)"),
  low: badgeStyle("var(--color-text-tertiary)", "rgba(85, 85, 106, 0.12)"),
  locked: badgeStyle("var(--color-violet)", "rgba(139, 92, 246, 0.10)"),
};

const SEVERITY_BADGES: Record<string, React.CSSProperties> = {
  critical: badgeStyle("var(--color-red)", "rgba(239, 68, 100, 0.12)"),
  major: badgeStyle("var(--color-amber)", "rgba(240, 178, 50, 0.12)"),
  minor: badgeStyle("var(--color-text-tertiary)", "rgba(85, 85, 106, 0.12)"),
};

const STATE_BADGES: Record<string, React.CSSProperties> = {
  ratified: badgeStyle("var(--color-emerald)", "rgba(68, 204, 119, 0.12)"),
  committed: badgeStyle("var(--color-blue)", "rgba(75, 166, 238, 0.12)"),
  drafting: badgeStyle("var(--color-text-tertiary)", "rgba(85, 85, 106, 0.12)"),
  rejected: badgeStyle("var(--color-red)", "rgba(239, 68, 100, 0.12)"),
  abandoned: badgeStyle("var(--color-text-tertiary)", "rgba(85, 85, 106, 0.12)"),
};

const VISION_DOTS: Record<string, { color: string; label: string }> = {
  available: { color: "var(--color-emerald)", label: "Available" },
  stale: { color: "var(--color-amber)", label: "Stale" },
  missing: { color: "var(--color-red)", label: "Missing" },
};

/* ── Section component ─────────────────────────────────────── */

function SnapshotSection({
  title,
  count,
  defaultOpen = false,
  empty = false,
  children,
}: {
  title: string;
  count: number;
  defaultOpen?: boolean;
  empty?: boolean;
  children?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen && !empty);

  return (
    <div style={{ marginBottom: 4 }}>
      <div
        onClick={() => {
          if (!empty) setOpen((o) => !o);
        }}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          cursor: empty ? "default" : "pointer",
          padding: "4px 0",
          userSelect: "none",
        }}
      >
        {!empty && (
          <svg
            width={10}
            height={10}
            viewBox="0 0 10 10"
            style={{
              flexShrink: 0,
              transition: "transform 0.15s",
              transform: open ? "rotate(90deg)" : "rotate(0deg)",
            }}
          >
            <path
              d="M3 1.5L7 5L3 8.5"
              fill="none"
              stroke="var(--color-text-tertiary)"
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
        {empty && <div style={{ width: 10, flexShrink: 0 }} />}

        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 13,
            fontWeight: 600,
            color: empty ? "var(--color-text-tertiary)" : "var(--color-text)",
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {title}
        </span>

        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            fontWeight: 500,
            color: "var(--color-text-secondary)",
            flexShrink: 0,
          }}
        >
          {empty ? "\u2014" : count}
        </span>
      </div>

      {open && !empty && (
        <div style={{ paddingLeft: 16, paddingTop: 4 }}>{children}</div>
      )}
    </div>
  );
}

/* ── Main component ────────────────────────────────────────── */

export function ContextSnapshot({
  contextPackage,
  assembledAt,
}: ContextSnapshotProps) {
  const formattedDate = new Date(assembledAt).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "var(--color-bg-elevated)",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "16px 20px",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          fontWeight: 500,
          color: "var(--color-text-tertiary)",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
          flexShrink: 0,
        }}
      >
        SNAPSHOT FROM {formattedDate}
      </div>

      {/* Scrollable sections */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "0 16px 16px",
        }}
      >
        {/* 1. Codebase */}
        <SnapshotSection
          title="Codebase"
          count={contextPackage.codebase.length}
          defaultOpen
          empty={contextPackage.codebase.length === 0}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {contextPackage.codebase.map((item: CodebaseItem, i: number) => (
              <div key={i}>
                <div
                  style={{
                    fontFamily: "var(--font-sans)",
                    fontSize: 12,
                    fontWeight: 400,
                    color: "var(--color-text)",
                    lineHeight: 1.4,
                  }}
                >
                  {item.path}
                </div>
                {item.description && (
                  <div
                    style={{
                      fontFamily: "var(--font-sans)",
                      fontSize: 10,
                      fontWeight: 400,
                      color: "var(--color-text-tertiary)",
                      marginTop: 2,
                    }}
                  >
                    {item.description}
                  </div>
                )}
              </div>
            ))}
          </div>
        </SnapshotSection>

        {/* 2. Learnings */}
        <SnapshotSection
          title="Learnings"
          count={contextPackage.learnings.length}
          defaultOpen={contextPackage.learnings.length > 0}
          empty={contextPackage.learnings.length === 0}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {contextPackage.learnings.map((item: LearningItem, i: number) => (
              <div key={i}>
                <div style={{ display: "flex", alignItems: "flex-start" }}>
                  <span
                    style={
                      CONFIDENCE_BADGES[item.confidence] ??
                      CONFIDENCE_BADGES.low
                    }
                  >
                    {item.confidence}
                  </span>
                  <span
                    style={{
                      fontFamily: "var(--font-sans)",
                      fontSize: 12,
                      fontWeight: 400,
                      color: "var(--color-text-secondary)",
                      lineHeight: 1.4,
                    }}
                  >
                    {item.text}
                  </span>
                </div>
                <div
                  style={{
                    fontFamily: "var(--font-sans)",
                    fontSize: 10,
                    fontWeight: 400,
                    color: "var(--color-text-tertiary)",
                    marginTop: 2,
                  }}
                >
                  from {item.sourceFeature}
                </div>
              </div>
            ))}
          </div>
        </SnapshotSection>

        {/* 3. Defects */}
        <SnapshotSection
          title="Defects"
          count={contextPackage.defects.length}
          defaultOpen={contextPackage.defects.length > 0}
          empty={contextPackage.defects.length === 0}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {contextPackage.defects.map((item: DefectItem, i: number) => (
              <div
                key={i}
                style={{ display: "flex", alignItems: "flex-start" }}
              >
                <span
                  style={
                    SEVERITY_BADGES[item.severity] ?? SEVERITY_BADGES.minor
                  }
                >
                  {item.severity}
                </span>
                <span
                  style={{
                    fontFamily: "var(--font-sans)",
                    fontSize: 12,
                    fontWeight: 400,
                    color: "var(--color-text-secondary)",
                    lineHeight: 1.4,
                  }}
                >
                  {item.name}
                </span>
              </div>
            ))}
          </div>
        </SnapshotSection>

        {/* 4. Project Knowledge */}
        <SnapshotSection
          title="Project Knowledge"
          count={contextPackage.projectKnowledge.length}
          defaultOpen={contextPackage.projectKnowledge.length > 0}
          empty={contextPackage.projectKnowledge.length === 0}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {contextPackage.projectKnowledge.map(
              (item: KnowledgeItem, i: number) => (
                <div key={i}>
                  <div style={{ display: "flex", alignItems: "flex-start" }}>
                    <span
                      style={
                        CONFIDENCE_BADGES[item.confidence] ??
                        CONFIDENCE_BADGES.low
                      }
                    >
                      {item.confidence}
                    </span>
                    <span
                      style={{
                        fontFamily: "var(--font-sans)",
                        fontSize: 12,
                        fontWeight: 400,
                        color: "var(--color-text-secondary)",
                        lineHeight: 1.4,
                      }}
                    >
                      {item.text}
                    </span>
                  </div>
                  <div
                    style={{
                      fontFamily: "var(--font-sans)",
                      fontSize: 10,
                      fontWeight: 400,
                      color: "var(--color-text-tertiary)",
                      marginTop: 2,
                    }}
                  >
                    {item.source}
                  </div>
                </div>
              )
            )}
          </div>
        </SnapshotSection>

        {/* 5. Vision */}
        <SnapshotSection
          title="Vision"
          count={contextPackage.visionContent ? 1 : 0}
          defaultOpen={contextPackage.visionStatus !== "missing"}
          empty={
            contextPackage.visionStatus === "missing" &&
            !contextPackage.visionContent
          }
        >
          {(() => {
            const dot =
              VISION_DOTS[contextPackage.visionStatus] ?? VISION_DOTS.missing;
            return (
              <div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    marginBottom: 6,
                  }}
                >
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: dot.color,
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      fontFamily: "var(--font-sans)",
                      fontSize: 12,
                      fontWeight: 400,
                      color: "var(--color-text-secondary)",
                    }}
                  >
                    {dot.label}
                  </span>
                </div>
                {(contextPackage.visionStatus === "available" ||
                  contextPackage.visionStatus === "stale") &&
                  contextPackage.visionContent && (
                    <div
                      style={{
                        fontFamily: "var(--font-sans)",
                        fontSize: 13,
                        fontWeight: 400,
                        color: "var(--color-text-secondary)",
                        lineHeight: 1.5,
                        display: "-webkit-box",
                        WebkitLineClamp: 3,
                        WebkitBoxOrient:
                          "vertical" as React.CSSProperties["WebkitBoxOrient"],
                        overflow: "hidden",
                      }}
                    >
                      {contextPackage.visionContent}
                    </div>
                  )}
              </div>
            );
          })()}
        </SnapshotSection>

        {/* 6. Related Features */}
        <SnapshotSection
          title="Related Features"
          count={contextPackage.relatedFeatures.length}
          defaultOpen={contextPackage.relatedFeatures.length > 0}
          empty={contextPackage.relatedFeatures.length === 0}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {contextPackage.relatedFeatures.map(
              (item: RelatedFeature, i: number) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--font-sans)",
                      fontSize: 12,
                      fontWeight: 400,
                      color: "var(--color-text)",
                      lineHeight: 1.4,
                    }}
                  >
                    {item.name}
                  </span>
                  <span
                    style={
                      STATE_BADGES[item.state.toLowerCase()] ??
                      STATE_BADGES.drafting
                    }
                  >
                    {item.state}
                  </span>
                </div>
              )
            )}
          </div>
        </SnapshotSection>

        {/* 7. Audit History */}
        <SnapshotSection
          title="Audit History"
          count={contextPackage.auditHistory.length}
          defaultOpen={contextPackage.auditHistory.length > 0}
          empty={contextPackage.auditHistory.length === 0}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {contextPackage.auditHistory.map(
              (item: AuditHistoryItem, i: number) => (
                <div key={i}>
                  <div style={{ display: "flex", alignItems: "flex-start" }}>
                    <span
                      style={
                        SEVERITY_BADGES[item.severity] ??
                        SEVERITY_BADGES.minor
                      }
                    >
                      {item.severity}
                    </span>
                    <span
                      style={{
                        fontFamily: "var(--font-sans)",
                        fontSize: 12,
                        fontWeight: 400,
                        color: "var(--color-text-secondary)",
                        lineHeight: 1.4,
                      }}
                    >
                      {item.finding}
                    </span>
                  </div>
                  <div
                    style={{
                      fontFamily: "var(--font-sans)",
                      fontSize: 10,
                      fontWeight: 400,
                      color: "var(--color-text-tertiary)",
                      marginTop: 2,
                    }}
                  >
                    from {item.featureName} &middot; {item.section}
                  </div>
                </div>
              )
            )}
          </div>
        </SnapshotSection>
      </div>
    </div>
  );
}
