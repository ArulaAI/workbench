"use client";

import React, { useState, useEffect } from "react";
import { Check, AlertCircle, Loader2 } from "lucide-react";
import type { ValidationState } from "@/lib/graphql/queries/ceremony";

interface CommitDialogProps {
  isOpen: boolean;
  featureName: string;
  validationState: ValidationState | null;
  suggestionSummary: { resolved: number; pending: number };
  onCommit: () => void;
  onCancel: () => void;
  committing?: boolean;
}

export function CommitDialog({
  isOpen,
  featureName,
  validationState,
  suggestionSummary,
  onCommit,
  onCancel,
  committing,
}: CommitDialogProps) {
  const [comment, setComment] = useState("");

  useEffect(() => {
    if (isOpen) setComment("");
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !committing) onCancel();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isOpen, onCancel, committing]);

  if (!isOpen) return null;

  const dims = validationState?.dimensions ?? [];

  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget && !committing) onCancel(); }}
      style={{
        position: "fixed", inset: 0, background: "rgba(0, 0, 0, 0.6)",
        zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div className="surface" style={{ width: "100%", maxWidth: 480, padding: 24 }} role="dialog" aria-label="Commit spec">
        <h3 style={{ fontSize: 15, fontWeight: 600, color: "var(--color-text)", marginBottom: 4 }}>
          Commit Spec
        </h3>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 20 }}>
          {featureName}
        </div>

        {/* Checklist */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 20 }}>
          {dims.map((d) => (
            <div key={d.name} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
              {d.status === "pass" ? (
                <Check size={16} style={{ color: "var(--color-emerald)", flexShrink: 0 }} />
              ) : d.status === "fail" ? (
                <AlertCircle size={16} style={{ color: "var(--color-red)", flexShrink: 0 }} />
              ) : (
                <AlertCircle size={16} style={{ color: "var(--color-amber)", flexShrink: 0 }} />
              )}
              <span>
                {d.name.charAt(0).toUpperCase() + d.name.slice(1).replace("_", "-")} validation {d.status === "pass" ? "passed" : d.status}
                {d.status === "warn" && <span style={{ color: "var(--color-text-tertiary)" }}> (non-blocking)</span>}
              </span>
            </div>
          ))}

          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
            {suggestionSummary.pending === 0 ? (
              <Check size={16} style={{ color: "var(--color-emerald)", flexShrink: 0 }} />
            ) : (
              <AlertCircle size={16} style={{ color: "var(--color-red)", flexShrink: 0 }} />
            )}
            <span>
              {suggestionSummary.pending === 0
                ? `All suggestions resolved (${suggestionSummary.resolved} total)`
                : `${suggestionSummary.pending} unresolved suggestion${suggestionSummary.pending > 1 ? "s" : ""}`}
            </span>
          </div>
        </div>

        {/* Comment */}
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Optional commit comment..."
          style={{
            width: "100%", minHeight: 60, padding: 12, fontSize: 13,
            background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)",
            borderRadius: 8, color: "var(--color-text)", fontFamily: "var(--font-sans)",
            resize: "vertical", outline: "none", marginBottom: 16,
          }}
        />

        {/* Actions */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button
            onClick={onCancel}
            disabled={committing}
            style={{
              fontSize: 13, padding: "8px 16px", borderRadius: 8,
              border: "1px solid var(--color-border)", background: "transparent",
              color: "var(--color-text-secondary)", cursor: committing ? "not-allowed" : "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={onCommit}
            disabled={committing}
            style={{
              fontSize: 13, fontWeight: 600, padding: "8px 20px", borderRadius: 8,
              border: "none", background: "var(--color-accent)", color: "var(--color-bg)",
              cursor: committing ? "wait" : "pointer",
              display: "flex", alignItems: "center", gap: 6,
            }}
          >
            {committing && <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />}
            {committing ? "Committing..." : "Commit"}
          </button>
        </div>
      </div>
    </div>
  );
}
