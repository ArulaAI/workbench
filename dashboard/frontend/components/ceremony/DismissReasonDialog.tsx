"use client";

import React, { useState, useEffect, useRef } from "react";

interface DismissReasonDialogProps {
  isOpen: boolean;
  onDismiss: (reason: string) => void;
  onCancel: () => void;
}

export function DismissReasonDialog({ isOpen, onDismiss, onCancel }: DismissReasonDialogProps) {
  const [reason, setReason] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (isOpen) {
      setReason("");
      setTimeout(() => textareaRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
      style={{
        position: "fixed", inset: 0, background: "rgba(0, 0, 0, 0.6)",
        zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center",
        animation: "fadeIn 150ms ease-out",
      }}
    >
      <div
        className="surface"
        style={{ width: "100%", maxWidth: 400, padding: 24 }}
        role="dialog"
        aria-label="Dismiss suggestion"
      >
        <h3 style={{ fontSize: 15, fontWeight: 600, color: "var(--color-text)", marginBottom: 4 }}>
          Dismiss Suggestion
        </h3>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 16 }}>
          Provide a reason so the contributor understands your decision.
        </p>
        <textarea
          ref={textareaRef}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Why are you dismissing this suggestion?"
          style={{
            width: "100%", minHeight: 80, padding: 12, fontSize: 13,
            background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)",
            borderRadius: 8, color: "var(--color-text)", fontFamily: "var(--font-sans)",
            lineHeight: 1.5, resize: "vertical", outline: "none",
          }}
          onFocus={(e) => { e.currentTarget.style.borderColor = "var(--color-accent-glow)"; }}
          onBlur={(e) => { e.currentTarget.style.borderColor = "var(--color-border)"; }}
        />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
          <button
            onClick={onCancel}
            style={{
              fontSize: 13, padding: "8px 16px", borderRadius: 8,
              border: "1px solid var(--color-border)", background: "transparent",
              color: "var(--color-text-secondary)", cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={() => onDismiss(reason)}
            disabled={!reason.trim()}
            style={{
              fontSize: 13, fontWeight: 600, padding: "8px 16px", borderRadius: 8,
              border: "none", background: "var(--color-red)", color: "var(--color-bg)",
              cursor: reason.trim() ? "pointer" : "not-allowed",
              opacity: reason.trim() ? 1 : 0.5,
            }}
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}
