"use client";

import { useState } from "react";
import { Check, X } from "lucide-react";

/**
 * RatifyControl — swaps in for the Commit button when the viewer is a
 * non-committer of a committed spec. Renders Approve (emerald) and
 * Reject (red outline) buttons with an optional/required comment field.
 *
 * Design spec rules:
 * - Approve: comment optional
 * - Reject: comment REQUIRED (the resolver rejects a reject with no
 *   comment, but we enforce at the UI layer too for a better UX)
 * - Already-voted state: both buttons disabled with "You voted: X"
 * - Threshold display: "N of M approvals needed"
 */

interface RatifyControlProps {
  specType: string;
  approvalCount: number;
  approvalThreshold: number;
  hasVoted: boolean;
  viewerVerdict?: "approve" | "reject" | null;
  busy: boolean;
  onApprove: (comment?: string) => void;
  onReject: (comment: string) => void;
}

function formatSpecType(specType: string): string {
  if (specType === "prd") return "PRD";
  if (specType === "design") return "Design";
  if (specType === "rfc") return "RFC";
  if (specType.startsWith("rfc-")) return `RFC: ${specType.slice(4)}`;
  return specType.toUpperCase();
}

export function RatifyControl({
  specType,
  approvalCount,
  approvalThreshold,
  hasVoted,
  viewerVerdict,
  busy,
  onApprove,
  onReject,
}: RatifyControlProps) {
  const [mode, setMode] = useState<"idle" | "approve" | "reject">("idle");
  const [comment, setComment] = useState("");

  const thresholdMet = approvalCount >= approvalThreshold;

  if (hasVoted) {
    return (
      <div
        role="group"
        aria-label={`Ratification verdict for ${formatSpecType(specType)}`}
        style={{ display: "flex", alignItems: "center", gap: 10 }}
      >
        <style>{STYLES}</style>
        <span className="ratify-threshold">
          <strong>{approvalCount}</strong> of{" "}
          <strong>{approvalThreshold}</strong> approvals
        </span>
        <span className="ratify-voted">
          You voted: <strong>{viewerVerdict ?? "—"}</strong>
        </span>
      </div>
    );
  }

  if (mode !== "idle") {
    const rejectRequired = mode === "reject";
    const commentValid = !rejectRequired || comment.trim().length > 0;
    return (
      <div
        role="group"
        aria-label={`Submit ${mode} verdict for ${formatSpecType(specType)}`}
        className="ratify-compose"
      >
        <style>{STYLES}</style>
        <input
          type="text"
          className="ratify-comment"
          placeholder={
            rejectRequired
              ? "Reason for rejection (required)"
              : "Optional comment"
          }
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          maxLength={280}
          autoFocus
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setMode("idle");
              setComment("");
            }
            if (e.key === "Enter" && commentValid && !busy) {
              if (mode === "approve") onApprove(comment.trim() || undefined);
              else onReject(comment.trim());
              setComment("");
              setMode("idle");
            }
          }}
        />
        <button
          className={`ratify-btn ratify-btn--${mode === "approve" ? "approve" : "reject"}`}
          onClick={() => {
            if (!commentValid || busy) return;
            if (mode === "approve") onApprove(comment.trim() || undefined);
            else onReject(comment.trim());
            setComment("");
            setMode("idle");
          }}
          disabled={!commentValid || busy}
        >
          {busy ? "…" : mode === "approve" ? "Submit approve" : "Submit reject"}
        </button>
        <button
          className="ratify-cancel"
          onClick={() => {
            setMode("idle");
            setComment("");
          }}
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div
      role="group"
      aria-label={`Ratification verdict for ${formatSpecType(specType)}`}
      style={{ display: "flex", alignItems: "center", gap: 10 }}
    >
      <style>{STYLES}</style>
      <span
        className="ratify-threshold"
        aria-describedby="ratify-count"
      >
        <strong id="ratify-count" style={{ color: thresholdMet ? "var(--color-accent)" : "var(--color-text)" }}>
          {approvalCount}
        </strong>{" "}
        of <strong>{approvalThreshold}</strong> approvals
      </span>
      <button
        className="ratify-btn ratify-btn--approve"
        onClick={() => setMode("approve")}
        disabled={busy}
        aria-label={`Approve ${formatSpecType(specType)}`}
      >
        <Check size={13} strokeWidth={2.5} />
        Approve
      </button>
      <button
        className="ratify-btn ratify-btn--reject"
        onClick={() => setMode("reject")}
        disabled={busy}
        aria-label={`Reject ${formatSpecType(specType)}`}
      >
        <X size={13} strokeWidth={2.5} />
        Reject
      </button>
    </div>
  );
}

const STYLES = `
  .ratify-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-family: var(--font-sans);
    font-size: 13px;
    font-weight: 600;
    padding: 7px 16px;
    border-radius: 6px;
    cursor: pointer;
    transition: background 150ms ease, border-color 150ms ease, transform 100ms ease;
  }
  .ratify-btn:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
  .ratify-btn--approve {
    background: var(--color-emerald);
    color: var(--color-bg);
    border: none;
  }
  .ratify-btn--approve:hover:not(:disabled) {
    background: rgba(68, 204, 119, 0.9);
  }
  .ratify-btn--approve:focus-visible {
    outline: 2px solid var(--color-emerald);
    outline-offset: 2px;
  }
  .ratify-btn--reject {
    background: transparent;
    color: var(--color-red);
    border: 1px solid var(--color-red);
  }
  .ratify-btn--reject:hover:not(:disabled) {
    background: rgba(239, 68, 100, 0.08);
  }
  .ratify-btn--reject:focus-visible {
    outline: 2px solid var(--color-red);
    outline-offset: 2px;
  }
  .ratify-btn:active:not(:disabled) {
    transform: scale(0.98);
  }
  .ratify-threshold {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--color-text-secondary);
  }
  .ratify-voted {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--color-text-tertiary);
  }
  .ratify-voted strong {
    color: var(--color-text-secondary);
  }
  .ratify-compose {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1 1 auto;
  }
  .ratify-comment {
    flex: 1;
    min-width: 200px;
    padding: 7px 10px;
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-border);
    border-radius: 4px;
    color: var(--color-text);
    font-family: var(--font-sans);
    font-size: 12px;
  }
  .ratify-comment:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 0;
  }
  .ratify-cancel {
    padding: 6px 10px;
    background: transparent;
    border: 1px solid var(--color-border);
    border-radius: 4px;
    color: var(--color-text-tertiary);
    font-family: var(--font-mono);
    font-size: 11px;
    cursor: pointer;
  }
  .ratify-cancel:hover {
    color: var(--color-text-secondary);
    border-color: var(--color-text-tertiary);
  }
`;
