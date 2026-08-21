"use client";

import React, { useState } from "react";

interface RatificationControlsProps {
  onApprove: () => void;
  onReject: (comment: string) => void;
  disabled: boolean;
  hasVoted: boolean;
  isAuthor: boolean;
}

export function RatificationControls({
  onApprove,
  onReject,
  disabled,
  hasVoted,
  isAuthor,
}: RatificationControlsProps) {
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectComment, setRejectComment] = useState("");

  if (hasVoted) {
    return (
      <div style={{ fontSize: 13, color: "var(--color-text-tertiary)", textAlign: "center", padding: "12px 0" }}>
        You have already submitted your verdict
      </div>
    );
  }

  if (isAuthor) {
    return (
      <div style={{ fontSize: 13, color: "var(--color-text-tertiary)", textAlign: "center", padding: "12px 0" }}>
        You cannot ratify your own spec
      </div>
    );
  }

  return (
    <div>
      {rejectOpen ? (
        <div>
          <textarea
            value={rejectComment}
            onChange={(e) => setRejectComment(e.target.value)}
            placeholder="Reason for rejection (required)..."
            style={{
              width: "100%", minHeight: 80, padding: 12, fontSize: 13,
              background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)",
              borderRadius: 8, color: "var(--color-text)", fontFamily: "var(--font-sans)",
              resize: "vertical", outline: "none", marginBottom: 8,
            }}
            autoFocus
          />
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={() => { setRejectOpen(false); setRejectComment(""); }}
              style={{
                flex: 1, padding: 10, fontSize: 13, fontWeight: 600,
                background: "transparent", color: "var(--color-text-secondary)",
                border: "1px solid var(--color-border)", borderRadius: 8, cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button
              onClick={() => { onReject(rejectComment); setRejectOpen(false); }}
              disabled={!rejectComment.trim()}
              style={{
                flex: 1, padding: 10, fontSize: 13, fontWeight: 600,
                background: "var(--color-red)", color: "var(--color-bg)",
                border: "none", borderRadius: 8,
                cursor: rejectComment.trim() ? "pointer" : "not-allowed",
                opacity: rejectComment.trim() ? 1 : 0.5,
              }}
            >
              Reject
            </button>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 12 }}>
          <button
            onClick={onApprove}
            disabled={disabled}
            style={{
              flex: 1, padding: 10, fontSize: 13, fontWeight: 600,
              background: "var(--color-emerald)", color: "var(--color-bg)",
              border: "none", borderRadius: 8, cursor: disabled ? "not-allowed" : "pointer",
              transition: "opacity 150ms",
            }}
          >
            Approve
          </button>
          <button
            onClick={() => setRejectOpen(true)}
            disabled={disabled}
            style={{
              flex: 1, padding: 10, fontSize: 13, fontWeight: 600,
              background: "transparent", color: "var(--color-red)",
              border: "1px solid var(--color-red)", borderRadius: 8,
              cursor: disabled ? "not-allowed" : "pointer", transition: "background 150ms",
            }}
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}
