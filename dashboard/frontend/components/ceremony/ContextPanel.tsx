"use client";

import { useState, useMemo } from "react";
import type {
  ContextPackage,
  CodebaseItem,
  LearningItem,
  DefectItem,
  KnowledgeItem,
  RelatedFeature,
  AuditHistoryItem,
} from "@/lib/graphql/queries/ceremony";
import { IntentAnchor } from "./IntentAnchor";
import { CodebaseCluster } from "./CodebaseCluster";
import { ProgressOverview, type ProgressRowData } from "./ownership";

/* ── Props ─────────────────────────────────────────────────── */

interface ContextPanelProps {
  featureName: string;
  contextPackage: ContextPackage;
  onRefine: (newText: string) => void;
  refining?: boolean;
  progressRows?: ProgressRowData[];
  activeSpecType?: string;
  onProgressRowClick?: (specType: string) => void;
}

/* ── Badge helper ──────────────────────────────────────────── */

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

/* ── Overflow threshold ────────────────────────────────────── */

const MAX_VISIBLE = 5;

/* ── Section component ─────────────────────────────────────── */

function Section({
  title,
  subtitle,
  count,
  defaultOpen = false,
  empty = false,
  children,
}: {
  title: string;
  subtitle: string;
  count: number;
  defaultOpen?: boolean;
  empty?: boolean;
  children?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen && !empty);

  return (
    <div style={{ marginBottom: 4 }}>
      {/* Header row */}
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
        {/* Chevron */}
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
        {/* Spacer when no chevron */}
        {empty && <div style={{ width: 10, flexShrink: 0 }} />}

        {/* Title */}
        <span
          title={subtitle}
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 13,
            fontWeight: 600,
            color: empty
              ? "var(--color-text-tertiary)"
              : "var(--color-text)",
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {title}
        </span>

        {/* Count */}
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

      {/* Subtitle (always visible) */}
      <div
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 11,
          fontWeight: 400,
          color: "var(--color-text-tertiary)",
          paddingLeft: 16,
          marginBottom: open ? 8 : 0,
        }}
      >
        {subtitle}
      </div>

      {/* Body */}
      {open && !empty && <div style={{ paddingLeft: 16 }}>{children}</div>}
    </div>
  );
}

/* ── Overflow wrapper ──────────────────────────────────────── */

function OverflowList<T>({
  items,
  renderItem,
}: {
  items: T[];
  renderItem: (item: T, index: number) => React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);

  const visible = expanded ? items : items.slice(0, MAX_VISIBLE);
  const remaining = items.length - MAX_VISIBLE;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {visible.map((item, i) => renderItem(item, i))}
      {!expanded && remaining > 0 && (
        <button
          onClick={() => setExpanded(true)}
          style={{
            background: "none",
            border: "none",
            fontFamily: "var(--font-sans)",
            fontSize: 10,
            fontWeight: 400,
            color: "var(--color-text-tertiary)",
            cursor: "pointer",
            padding: "4px 0",
            textAlign: "center",
          }}
        >
          {"── "}
          {remaining}
          {" more ──"}
        </button>
      )}
    </div>
  );
}

/* ── Main component ────────────────────────────────────────── */

export function ContextPanel({
  featureName,
  contextPackage,
  onRefine,
  refining = false,
  progressRows,
  activeSpecType,
  onProgressRowClick,
}: ContextPanelProps) {
  /* ── Codebase clusters ───────────────────────────────────── */

  const clusters = useMemo(() => {
    // Group by file path, not by node ID
    const map = new Map<string, CodebaseItem[]>();
    for (const item of contextPackage.codebase) {
      const key = item.path || "__ungrouped__";
      const group = map.get(key) ?? [];
      group.push(item);
      map.set(key, group);
    }
    return Array.from(map.entries())
      .sort((a, b) => b[1].length - a[1].length)  // most symbols first
      .map(([filePath, items], index) => ({
        nodeId: filePath,
        name: filePath,
        count: items.length,
        files: items.map((it) => it.description).filter(Boolean),
        description: `${items.length} symbol${items.length !== 1 ? "s" : ""}`,
        colorIndex: index,
      }));
  }, [contextPackage.codebase]);

  return (
    <div
      style={{
        width: 320,
        flexShrink: 0,
        background: "var(--color-bg-elevated)",
        borderRight: "1px solid var(--color-border)",
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
      }}
    >
      {/* Intent anchor (pinned at top) */}
      <IntentAnchor
        featureName={featureName}
        intentText={contextPackage.intent}
        onRefine={onRefine}
        loading={refining}
      />

      {/* Scrollable sections */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "12px 16px",
        }}
      >
        {/* 0. Progress Overview — first section above context package data */}
        {progressRows !== undefined && activeSpecType && onProgressRowClick && (
          <ProgressOverview
            rows={progressRows}
            activeSpecType={activeSpecType}
            onRowClick={onProgressRowClick}
          />
        )}
        {/* 1. Codebase */}
        <Section
          title="Codebase"
          subtitle="What code exists in this area?"
          count={clusters.length}
          defaultOpen={false}
          empty={clusters.length === 0}
        >
          {clusters.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {clusters.map((cluster) => (
                <CodebaseCluster
                  key={cluster.nodeId}
                  name={cluster.name}
                  count={cluster.count}
                  files={cluster.files}
                  description={cluster.description}
                  colorIndex={cluster.colorIndex}
                />
              ))}
            </div>
          ) : (
            <div
              style={{
                fontFamily: "var(--font-sans)",
                fontSize: 12,
                fontWeight: 400,
                color: "var(--color-text-tertiary)",
                fontStyle: "italic",
              }}
            >
              No files matched
            </div>
          )}
        </Section>

        {/* 2. Learnings */}
        <Section
          title="Learnings"
          subtitle="What has the team learned from working here?"
          count={contextPackage.learnings.length}
          defaultOpen={false}
          empty={contextPackage.learnings.length === 0}
        >
          <OverflowList
            items={contextPackage.learnings}
            renderItem={(item: LearningItem, i: number) => (
              <div
                key={i}
                style={{
                  opacity: item.confidence === "low" ? 0.5 : 1,
                }}
              >
                <div style={{ display: "flex", alignItems: "flex-start", minWidth: 0 }}>
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
                      fontSize: 11,
                      fontWeight: 400,
                      color: "var(--color-text-secondary)",
                      lineHeight: 1.4,
                      overflowWrap: "break-word",
                      wordBreak: "break-word",
                      minWidth: 0,
                      display: "-webkit-box",
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: "vertical" as React.CSSProperties["WebkitBoxOrient"],
                      overflow: "hidden",
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
            )}
          />
        </Section>

        {/* 3. Defects */}
        <Section
          title="Defects"
          subtitle="What's broken in this area right now?"
          count={contextPackage.defects.length}
          defaultOpen={false}
          empty={contextPackage.defects.length === 0}
        >
          <OverflowList
            items={contextPackage.defects}
            renderItem={(item: DefectItem, i: number) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  minWidth: 0,
                  opacity: item.severity === "minor" ? 0.5 : 1,
                }}
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
                    fontSize: 11,
                    fontWeight: 400,
                    color: "var(--color-text-secondary)",
                    lineHeight: 1.4,
                    overflowWrap: "break-word",
                    wordBreak: "break-word",
                    minWidth: 0,
                  }}
                >
                  {item.name}
                </span>
              </div>
            )}
          />
        </Section>

        {/* 4. Project Knowledge */}
        <Section
          title="Project Knowledge"
          subtitle="What conventions apply here?"
          count={contextPackage.projectKnowledge.length}
          defaultOpen={false}
          empty={contextPackage.projectKnowledge.length === 0}
        >
          <OverflowList
            items={contextPackage.projectKnowledge}
            renderItem={(item: KnowledgeItem, i: number) => (
              <div
                key={i}
                style={{
                  opacity: item.confidence === "low" ? 0.5 : 1,
                }}
              >
                <div style={{ display: "flex", alignItems: "flex-start", minWidth: 0 }}>
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
                      fontSize: 11,
                      fontWeight: 400,
                      color: "var(--color-text-secondary)",
                      lineHeight: 1.4,
                      overflowWrap: "break-word",
                      wordBreak: "break-word",
                      minWidth: 0,
                      display: "-webkit-box",
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: "vertical" as React.CSSProperties["WebkitBoxOrient"],
                      overflow: "hidden",
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
            )}
          />
        </Section>

        {/* 5. Vision */}
        <Section
          title="Vision"
          subtitle="Is there a product direction to align with?"
          count={contextPackage.visionContent ? 1 : 0}
          defaultOpen={false}
          empty={contextPackage.visionStatus === "missing" && !contextPackage.visionContent}
        >
          {(() => {
            const dot = VISION_DOTS[contextPackage.visionStatus] ?? VISION_DOTS.missing;
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
                        WebkitBoxOrient: "vertical" as React.CSSProperties["WebkitBoxOrient"],
                        overflow: "hidden",
                      }}
                    >
                      {contextPackage.visionContent}
                    </div>
                  )}
              </div>
            );
          })()}
        </Section>

        {/* 6. Related Features */}
        <Section
          title="Related Features"
          subtitle="Is anyone else working in this area?"
          count={contextPackage.relatedFeatures.length}
          defaultOpen={false}
          empty={contextPackage.relatedFeatures.length === 0}
        >
          <OverflowList
            items={contextPackage.relatedFeatures}
            renderItem={(item: RelatedFeature, i: number) => (
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
            )}
          />
        </Section>

        {/* 7. Audit History */}
        <Section
          title="Audit History"
          subtitle="What have past spec audits flagged here?"
          count={contextPackage.auditHistory.length}
          defaultOpen={false}
          empty={contextPackage.auditHistory.length === 0}
        >
          <OverflowList
            items={contextPackage.auditHistory}
            renderItem={(item: AuditHistoryItem, i: number) => (
              <div
                key={i}
                style={{
                  opacity: item.severity === "minor" ? 0.5 : 1,
                }}
              >
                <div style={{ display: "flex", alignItems: "flex-start", minWidth: 0 }}>
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
                      fontSize: 11,
                      fontWeight: 400,
                      color: "var(--color-text-secondary)",
                      lineHeight: 1.4,
                      overflowWrap: "break-word",
                      wordBreak: "break-word",
                      minWidth: 0,
                      display: "-webkit-box",
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: "vertical" as React.CSSProperties["WebkitBoxOrient"],
                      overflow: "hidden",
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
            )}
          />
        </Section>
      </div>
    </div>
  );
}
