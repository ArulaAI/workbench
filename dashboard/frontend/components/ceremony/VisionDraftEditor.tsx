"use client";

import React, { useState } from "react";
import { RefreshCw } from "lucide-react";

interface VisionDraftEditorProps {
  generatedContent: string;
  onCommit: (content: string) => void;
  onSkip: () => void;
  onRegenerate?: () => void;
  regenerating?: boolean;
}

export function VisionDraftEditor({
  generatedContent,
  onCommit,
  onSkip,
  onRegenerate,
  regenerating,
}: VisionDraftEditorProps) {
  const [editedContent, setEditedContent] = useState(generatedContent);

  return (
    <div>
      <div
        style={{
          display: "flex",
          gap: 1,
          background: "var(--color-border)",
          borderRadius: 8,
          overflow: "hidden",
          marginBottom: 12,
        }}
      >
        {/* Generated pane */}
        <div style={{ flex: 1, padding: 20, background: "var(--color-bg-elevated)", position: "relative" }}>
          <div
            style={{
              fontSize: 11, fontWeight: 500, textTransform: "uppercase",
              letterSpacing: "0.04em", marginBottom: 12,
              fontFamily: "var(--font-mono)", color: "var(--color-text-tertiary)",
            }}
          >
            Generated from codebase
          </div>
          <div
            style={{
              fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6,
              whiteSpace: "pre-wrap",
              opacity: regenerating ? 0.4 : 1,
              transition: "opacity 200ms",
            }}
          >
            {generatedContent || "No vision generated. Run bootstrap from CLI to generate."}
          </div>
          {onRegenerate && (
            <button
              onClick={onRegenerate}
              disabled={regenerating}
              style={{
                marginTop: 12, fontSize: 11, color: "var(--color-accent)",
                background: "none", border: "none", cursor: "pointer",
                display: "flex", alignItems: "center", gap: 4,
                opacity: regenerating ? 0.5 : 1,
              }}
            >
              <RefreshCw size={11} style={{ animation: regenerating ? "spin 1s linear infinite" : "none" }} />
              {regenerating ? "Regenerating..." : "Regenerate with different focus"}
            </button>
          )}
        </div>

        {/* Editable pane */}
        <div style={{ flex: 1, padding: 20, background: "var(--color-bg-card)" }}>
          <div
            style={{
              fontSize: 11, fontWeight: 500, textTransform: "uppercase",
              letterSpacing: "0.04em", marginBottom: 12,
              fontFamily: "var(--font-mono)", color: "var(--color-text)",
            }}
          >
            Your version (editable)
          </div>
          <textarea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            style={{
              width: "100%", minHeight: 200, padding: 0,
              fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6,
              background: "transparent", border: "none", outline: "none",
              fontFamily: "var(--font-sans)", resize: "vertical",
            }}
          />
        </div>
      </div>

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
          onClick={() => onCommit(editedContent)}
          style={{
            fontSize: 13, fontWeight: 600, padding: "8px 20px", borderRadius: 8,
            background: "var(--color-accent)", color: "var(--color-bg)",
            border: "none", cursor: "pointer",
          }}
        >
          Commit Vision
        </button>
      </div>
    </div>
  );
}
