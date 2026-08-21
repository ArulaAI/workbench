"use client";

import React, { useState, useCallback } from "react";
import { ChevronLeft, ChevronRight, ChevronDown, AlertCircle, AlertTriangle, Info } from "lucide-react";
import type {
  ValidationState,
  ValidationIssue,
  ValidationDimension,
} from "@/lib/graphql/queries/ceremony";
import { ValidationBadge } from "./ValidationBadge";

const SEVERITY_ICONS: Record<string, React.ElementType> = {
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};

const SEVERITY_COLORS: Record<string, string> = {
  error: "var(--color-red)",
  warning: "var(--color-amber)",
  info: "var(--color-blue)",
};

const STATUS_COLORS: Record<string, string> = {
  pass: "var(--color-emerald)",
  warn: "var(--color-amber)",
  fail: "var(--color-red)",
  pending: "var(--color-text-tertiary)",
  stale: "var(--color-text-tertiary)",
};

interface ValidationGutterProps {
  validationState: ValidationState | null;
  expanded: boolean;
  onToggle: () => void;
  onIssueClick: (issue: ValidationIssue) => void;
  draftEditedSinceLastCheck: boolean;
  loading: boolean;
}

export function ValidationGutter({
  validationState,
  expanded,
  onToggle,
  onIssueClick,
  draftEditedSinceLastCheck,
  loading,
}: ValidationGutterProps) {
  const width = expanded ? 240 : 40;
  const dimensions = validationState?.dimensions ?? [];
  const [expandedDims, setExpandedDims] = useState<Set<string>>(new Set());

  // Sort: Tier 1 first, then Tier 2. Within tier, fail > warn > pass
  const statusOrder: Record<string, number> = { fail: 0, warn: 1, pending: 2, stale: 3, pass: 4 };
  const sorted = [...dimensions].sort((a, b) => {
    if (a.tier !== b.tier) return a.tier - b.tier;
    return (statusOrder[a.status] ?? 3) - (statusOrder[b.status] ?? 3);
  });

  const toggleDim = useCallback((name: string) => {
    setExpandedDims((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  return (
    <div
      className="surface"
      style={{
        width,
        minWidth: width,
        display: "flex",
        flexDirection: "column",
        background: "var(--color-bg-elevated)",
        borderLeft: "1px solid var(--color-border)",
        transition: "width 200ms ease",
        overflow: "hidden",
      }}
    >
      {/* Toggle button */}
      <button
        onClick={onToggle}
        title={expanded ? "Collapse validation" : "Expand validation"}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "8px 4px",
          background: "transparent",
          border: "none",
          borderBottom: "1px solid var(--color-border-light)",
          cursor: "pointer",
          color: "var(--color-text-tertiary)",
        }}
      >
        {expanded ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        {expanded && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 500,
              color: "var(--color-text-secondary)",
              marginLeft: 4,
              whiteSpace: "nowrap",
            }}
          >
            Validation
          </span>
        )}
      </button>

      {/* Summary counts */}
      {validationState && expanded && (
        <div
          style={{
            display: "flex",
            gap: 8,
            padding: "6px 8px",
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            borderBottom: "1px solid var(--color-border-light)",
          }}
        >
          {validationState.passCount > 0 && (
            <span style={{ color: "var(--color-emerald)" }}>
              {validationState.passCount} pass
            </span>
          )}
          {validationState.warnCount > 0 && (
            <span style={{ color: "var(--color-amber)" }}>
              {validationState.warnCount} warn
            </span>
          )}
          {validationState.failCount > 0 && (
            <span style={{ color: "var(--color-red)" }}>
              {validationState.failCount} fail
            </span>
          )}
          {loading && (
            <span style={{ color: "var(--color-text-tertiary)" }}>checking...</span>
          )}
        </div>
      )}

      {/* Dimension list with accordion */}
      <div style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}>
        {sorted.map((dim) => {
          const isOpen = expandedDims.has(dim.name);
          const issueCount = dim.issues.length;
          const dimColor = STATUS_COLORS[dim.status] || STATUS_COLORS.pending;
          const isStale = draftEditedSinceLastCheck && dim.tier === 2;

          return (
            <div key={dim.name}>
              {/* Dimension header (clickable to expand/collapse) */}
              {expanded ? (
                <button
                  onClick={() => issueCount > 0 ? toggleDim(dim.name) : undefined}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    width: "100%",
                    padding: "6px 8px",
                    background: "transparent",
                    border: "none",
                    cursor: issueCount > 0 ? "pointer" : "default",
                    opacity: isStale ? 0.5 : 1,
                    transition: "background 150ms",
                  }}
                  onMouseEnter={(e) => {
                    if (issueCount > 0) e.currentTarget.style.background = "var(--color-bg-card-hover)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "transparent";
                  }}
                >
                  {/* Expand chevron (only if has issues) */}
                  {issueCount > 0 ? (
                    <ChevronDown
                      size={12}
                      style={{
                        color: "var(--color-text-tertiary)",
                        flexShrink: 0,
                        transform: isOpen ? "rotate(0deg)" : "rotate(-90deg)",
                        transition: "transform 150ms",
                      }}
                    />
                  ) : (
                    <span style={{ width: 12, flexShrink: 0 }} />
                  )}

                  {/* Status dot */}
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: dimColor,
                      flexShrink: 0,
                    }}
                  />

                  {/* Dimension name */}
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 500,
                      color: "var(--color-text)",
                      flex: 1,
                      textAlign: "left",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {dim.name.charAt(0).toUpperCase() + dim.name.slice(1).replace("_", "-")}
                  </span>

                  {/* Issue count */}
                  {issueCount > 0 && (
                    <span
                      style={{
                        fontSize: 10,
                        fontFamily: "var(--font-mono)",
                        fontWeight: 500,
                        color: dimColor,
                        minWidth: 16,
                        textAlign: "right",
                      }}
                    >
                      {issueCount}
                    </span>
                  )}
                </button>
              ) : (
                <ValidationBadge
                  dimension={dim}
                  stale={isStale}
                  expanded={false}
                  onClick={onToggle}
                />
              )}

              {/* Issue cards (accordion content) */}
              {expanded && isOpen && dim.issues.length > 0 && (
                <div style={{ padding: "0 0 4px 0" }}>
                  {dim.issues.map((issue) => {
                    const SevIcon = SEVERITY_ICONS[issue.severity] || Info;
                    const sevColor = SEVERITY_COLORS[issue.severity] || "var(--color-text-tertiary)";
                    return (
                      <button
                        key={issue.id}
                        onClick={() => onIssueClick(issue)}
                        title={issue.section ? `Jump to ${issue.section}${issue.line ? `:${issue.line}` : ""}` : undefined}
                        style={{
                          display: "flex",
                          alignItems: "flex-start",
                          gap: 6,
                          padding: "5px 8px 5px 26px",
                          width: "100%",
                          background: "transparent",
                          border: "none",
                          borderLeft: `2px solid ${sevColor}`,
                          marginLeft: 8,
                          cursor: issue.section || issue.line ? "pointer" : "default",
                          textAlign: "left",
                          transition: "background 150ms ease",
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLElement).style.background = "var(--color-bg-card-hover)";
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLElement).style.background = "transparent";
                        }}
                      >
                        <SevIcon
                          size={11}
                          style={{ color: sevColor, flexShrink: 0, marginTop: 2 }}
                        />
                        <div style={{ minWidth: 0 }}>
                          <div
                            style={{
                              fontSize: 11,
                              color: "var(--color-text-secondary)",
                              lineHeight: 1.4,
                              wordBreak: "break-word",
                            }}
                          >
                            {issue.message}
                          </div>
                          {issue.section && (
                            <div
                              style={{
                                fontSize: 10,
                                color: "var(--color-text-tertiary)",
                                marginTop: 2,
                                fontFamily: "var(--font-mono)",
                              }}
                            >
                              {issue.section}
                              {issue.line ? `:${issue.line}` : ""}
                            </div>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {expanded && dimensions.every((d) => d.issues.length === 0) && (
          <div
            style={{
              padding: "16px 8px",
              fontSize: 11,
              color: "var(--color-text-tertiary)",
              textAlign: "center",
            }}
          >
            No issues found
          </div>
        )}
      </div>
    </div>
  );
}
