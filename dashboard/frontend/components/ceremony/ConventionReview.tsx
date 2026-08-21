"use client";

import React, { useState } from "react";
import { Check, X } from "lucide-react";
import type { Convention } from "@/lib/graphql/queries/ceremony-bootstrap";

interface ConventionReviewProps {
  conventions: Convention[];
  onResolve: (id: string, action: "accept" | "reject") => void;
  onCommit: (acceptedIds: string[], persona: string) => void;
  onSkip: () => void;
}

const CONFIDENCE_COLORS: Record<string, string> = {
  high: "var(--color-emerald)",
  medium: "var(--color-amber)",
  low: "var(--color-text-tertiary)",
};

const SOURCE_COLORS: Record<string, { color: string; bg: string }> = {
  "code structure": { color: "var(--color-violet)", bg: "rgba(139, 92, 246, 0.1)" },
  "commit patterns": { color: "var(--color-amber)", bg: "rgba(240, 178, 50, 0.1)" },
  "file patterns": { color: "var(--color-blue)", bg: "rgba(75, 166, 238, 0.1)" },
  detected: { color: "var(--color-violet)", bg: "rgba(139, 92, 246, 0.1)" },
  inferred: { color: "var(--color-amber)", bg: "rgba(240, 178, 50, 0.1)" },
  explicit: { color: "var(--color-blue)", bg: "rgba(75, 166, 238, 0.1)" },
};

export function ConventionReview({ conventions, onResolve, onCommit, onSkip }: ConventionReviewProps) {
  const [persona, setPersona] = useState("");

  const acceptedIds = conventions.filter((c) => c.status === "accepted").map((c) => c.id);
  const pendingCount = conventions.filter((c) => c.status === "pending").length;

  const handleAcceptAll = () => {
    conventions.forEach((c) => {
      if (c.status === "pending") onResolve(c.id, "accept");
    });
  };

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
          {conventions.length} conventions derived
        </span>
        {pendingCount > 0 && (
          <button
            onClick={handleAcceptAll}
            style={{
              fontSize: 11, fontWeight: 500, padding: "4px 10px", borderRadius: 4,
              border: "none", cursor: "pointer", color: "var(--color-emerald)",
              background: "rgba(68, 204, 119, 0.08)",
            }}
          >
            Accept All
          </button>
        )}
      </div>

      {/* Convention list */}
      <div
        className="surface"
        style={{ borderRadius: 8, overflow: "hidden", marginBottom: 16 }}
      >
        {conventions.map((c) => {
          const text = c.convention || c.text || "";
          const isAccepted = c.status === "accepted";
          const isRejected = c.status === "rejected";
          const source = c.source || "detected";
          const confidence = c.confidence || "medium";
          const sourceStyle = SOURCE_COLORS[source] || SOURCE_COLORS.detected;

          return (
            <div
              key={c.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "12px 16px",
                borderBottom: "1px solid var(--color-border-light)",
                background: isAccepted ? "rgba(68, 204, 119, 0.04)" : "transparent",
                opacity: isRejected ? 0.4 : 1,
                transition: "background 150ms, opacity 150ms",
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 13,
                    color: "var(--color-text-secondary)",
                    textDecoration: isRejected ? "line-through" : "none",
                    lineHeight: 1.5,
                  }}
                >
                  {text}
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 4, alignItems: "center" }}>
                  <span
                    style={{
                      fontSize: 10,
                      fontFamily: "var(--font-mono)",
                      padding: "1px 5px",
                      borderRadius: 3,
                      color: sourceStyle.color,
                      background: sourceStyle.bg,
                    }}
                  >
                    {source}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      fontFamily: "var(--font-mono)",
                      color: CONFIDENCE_COLORS[confidence] || "var(--color-text-tertiary)",
                    }}
                  >
                    {confidence}
                  </span>
                </div>
              </div>

              {c.status === "pending" && (
                <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                  <button
                    onClick={() => onResolve(c.id, "accept")}
                    style={{
                      width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center",
                      borderRadius: 6, border: "none", cursor: "pointer",
                      color: "var(--color-emerald)", background: "transparent", transition: "background 150ms",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(68, 204, 119, 0.08)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                  >
                    <Check size={14} />
                  </button>
                  <button
                    onClick={() => onResolve(c.id, "reject")}
                    style={{
                      width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center",
                      borderRadius: 6, border: "none", cursor: "pointer",
                      color: "var(--color-text-tertiary)", background: "transparent", transition: "all 150ms",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.color = "var(--color-red)"; e.currentTarget.style.background = "rgba(239, 68, 100, 0.08)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.color = "var(--color-text-tertiary)"; e.currentTarget.style.background = "transparent"; }}
                  >
                    <X size={14} />
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Persona input */}
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", display: "block", marginBottom: 6 }}>
          Add team context (optional)
        </label>
        <textarea
          value={persona}
          onChange={(e) => setPersona(e.target.value)}
          placeholder="e.g., We're a 3-person team shipping weekly, favoring speed over ceremony"
          style={{
            width: "100%", minHeight: 60, padding: 12, fontSize: 13,
            background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)",
            borderRadius: 8, color: "var(--color-text)", fontFamily: "var(--font-sans)",
            lineHeight: 1.5, resize: "vertical", outline: "none",
          }}
        />
      </div>

      {/* Actions */}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button
          onClick={onSkip}
          style={{
            fontSize: 13, fontWeight: 600, padding: "8px 20px", borderRadius: 8,
            background: "transparent", color: "var(--color-text-secondary)",
            border: "1px solid var(--color-border)", cursor: "pointer",
          }}
        >
          Skip
        </button>
        <button
          onClick={() => onCommit(acceptedIds, persona)}
          style={{
            fontSize: 13, fontWeight: 600, padding: "8px 20px", borderRadius: 8,
            background: "var(--color-accent)", color: "var(--color-bg)",
            border: "none", cursor: "pointer",
          }}
        >
          Commit Conventions
        </button>
      </div>
    </div>
  );
}
