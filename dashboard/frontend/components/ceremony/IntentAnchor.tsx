"use client";

import { useState, useRef, useCallback } from "react";

/* ── Types ─────────────────────────────────────────────────── */

interface IntentAnchorProps {
  featureName: string;
  intentText: string;
  onRefine: (newText: string) => void;
  loading?: boolean;
}

/* ── Component ─────────────────────────────────────────────── */

export function IntentAnchor({
  featureName,
  intentText,
  onRefine,
  loading = false,
}: IntentAnchorProps) {
  const [editing, setEditing] = useState(false);
  const [hovered, setHovered] = useState(false);
  const intentRef = useRef<HTMLDivElement>(null);
  const originalRef = useRef(intentText);

  const activate = useCallback(() => {
    if (loading) return;
    originalRef.current = intentText;
    setEditing(true);
    const el = intentRef.current;
    if (el) {
      el.contentEditable = "true";
      el.focus();
      // Select all text
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
    }
  }, [intentText, loading]);

  const deactivate = useCallback(
    (commit: boolean) => {
      const el = intentRef.current;
      if (!el) return;

      if (commit) {
        const newText = (el.textContent ?? "").trim();
        if (newText && newText !== originalRef.current) {
          onRefine(newText);
        }
      } else {
        el.textContent = originalRef.current;
      }

      el.contentEditable = "false";
      setEditing(false);
      window.getSelection()?.removeAllRanges();
    },
    [onRefine]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        deactivate(true);
      } else if (e.key === "Escape") {
        e.preventDefault();
        deactivate(false);
      }
    },
    [deactivate]
  );

  const handleBlur = useCallback(() => {
    deactivate(false);
  }, [deactivate]);

  /* ── Intent text style ─────────────────────────────────── */

  const intentStyle: React.CSSProperties = {
    fontFamily: "var(--font-sans)",
    fontSize: 13,
    fontWeight: 400,
    lineHeight: 1.5,
    padding: "4px 6px",
    borderRadius: 6,
    outline: "none",
    cursor: loading ? "default" : "text",
    transition: "background 0.15s, color 0.15s, box-shadow 0.15s",
    // Default: tertiary, clamped
    color: "var(--color-text-tertiary)",
    background: "transparent",
    boxShadow: "none",
    display: "-webkit-box",
    WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical" as React.CSSProperties["WebkitBoxOrient"],
    overflow: "hidden",
  };

  if (editing) {
    intentStyle.color = "var(--color-text)";
    intentStyle.background = "var(--color-bg-card)";
    intentStyle.boxShadow = "0 0 0 2px rgba(0,212,170,0.12)";
    // Lift clamp
    intentStyle.display = "block";
    intentStyle.WebkitLineClamp = undefined;
    intentStyle.WebkitBoxOrient = undefined;
    intentStyle.overflow = "visible";
  } else if (hovered && !loading) {
    intentStyle.color = "var(--color-text-secondary)";
    intentStyle.background = "rgba(255,255,255,0.03)";
  }

  return (
    <div
      style={{
        padding: "16px 16px 12px",
        opacity: loading ? 0.5 : 1,
        transition: "opacity 0.2s",
      }}
    >
      {/* Feature name */}
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          fontWeight: 500,
          color: "var(--color-text-secondary)",
          letterSpacing: "-0.01em",
          marginBottom: 6,
        }}
      >
        {featureName}
      </div>

      {/* Intent preview / editable */}
      <div
        ref={intentRef}
        role="textbox"
        tabIndex={0}
        aria-label="Intent preview"
        suppressContentEditableWarning
        onClick={activate}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={intentStyle}
      >
        {intentText}
      </div>

      {/* Centered divider */}
      <div
        style={{
          width: "40%",
          height: 1,
          background: "var(--color-border)",
          margin: "12px auto 0",
        }}
      />
    </div>
  );
}
