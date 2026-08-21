"use client";

import React, { useState, useRef, useEffect } from "react";
import { MessageSquarePlus } from "lucide-react";

interface SuggestionComposerProps {
  sectionId: string;
  sectionTitle: string;
  onSubmit: (sectionId: string, sectionTitle: string, text: string) => void;
  onCancel: () => void;
}

export function SuggestionComposer({
  sectionId,
  sectionTitle,
  onSubmit,
  onCancel,
}: SuggestionComposerProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleSubmit = () => {
    if (!text.trim()) return;
    onSubmit(sectionId, sectionTitle, text.trim());
    setText("");
  };

  return (
    <div
      className="surface"
      style={{
        padding: 16,
        margin: "8px 0",
        animation: "slideDown 200ms ease-out",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 8,
          fontSize: 12,
          color: "var(--color-text-secondary)",
        }}
      >
        <MessageSquarePlus size={13} style={{ color: "var(--color-amber)" }} />
        <span>
          Suggesting on: <strong style={{ color: "var(--color-text)" }}>{sectionTitle}</strong>
        </span>
      </div>
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Describe your suggestion..."
        style={{
          width: "100%",
          minHeight: 80,
          padding: 12,
          fontSize: 13,
          background: "var(--color-bg-elevated)",
          border: "1px solid var(--color-border)",
          borderRadius: 8,
          color: "var(--color-text)",
          fontFamily: "var(--font-sans)",
          lineHeight: 1.5,
          resize: "vertical",
          outline: "none",
        }}
        onFocus={(e) => {
          e.currentTarget.style.borderColor = "var(--color-accent-glow)";
        }}
        onBlur={(e) => {
          e.currentTarget.style.borderColor = "var(--color-border)";
        }}
      />
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
        <button
          onClick={onCancel}
          style={{
            fontSize: 12, padding: "6px 12px", borderRadius: 6,
            border: "1px solid var(--color-border)", background: "transparent",
            color: "var(--color-text-secondary)", cursor: "pointer",
          }}
        >
          Cancel
        </button>
        <button
          onClick={handleSubmit}
          disabled={!text.trim()}
          style={{
            fontSize: 12, fontWeight: 600, padding: "6px 14px", borderRadius: 6,
            border: "none", background: "var(--color-accent)", color: "var(--color-bg)",
            cursor: text.trim() ? "pointer" : "not-allowed",
            opacity: text.trim() ? 1 : 0.5,
          }}
        >
          Submit
        </button>
      </div>
    </div>
  );
}
