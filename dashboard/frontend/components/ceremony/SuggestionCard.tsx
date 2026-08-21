"use client";

import React, { useState } from "react";
import { Undo2, Trash2 } from "lucide-react";
import type { Suggestion } from "@/lib/graphql/queries/ceremony-suggestions";

interface SuggestionCardProps {
  suggestion: Suggestion;
  isAuthor: boolean;
  onAccept: (id: string) => void;
  onDismiss: (id: string) => void;
  onReply: (id: string, text: string) => void;
  onDelete?: (id: string) => void;
}

export function SuggestionCard({
  suggestion,
  isAuthor,
  onAccept,
  onDismiss,
  onReply,
  onDelete,
}: SuggestionCardProps) {
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [expanded, setExpanded] = useState(false);

  const isResolved = suggestion.status !== "unresolved";
  const isAccepted = suggestion.status === "accepted";
  const isDismissed = suggestion.status === "dismissed";

  const handleReplySubmit = () => {
    if (!replyText.trim()) return;
    onReply(suggestion.id, replyText.trim());
    setReplyText("");
    setReplyOpen(false);
  };

  const statusColor = isAccepted
    ? "var(--color-emerald)"
    : isDismissed
      ? "var(--color-red)"
      : "var(--color-accent)";

  const statusLabel = isAccepted ? "Accepted" : isDismissed ? "Dismissed" : "";

  // ── Resolved: collapsed single-line ──────────────────────────
  if (isResolved && !expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          padding: "8px 12px",
          marginBottom: 4,
          background: "transparent",
          border: "none",
          borderLeft: `2px solid ${statusColor}`,
          borderRadius: 0,
          cursor: "pointer",
          textAlign: "left",
          transition: "background 150ms",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-bg-card-hover)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
      >
        <span style={{
          width: 6, height: 6, borderRadius: "50%",
          background: statusColor, flexShrink: 0,
        }} />
        <span style={{
          fontSize: 11, color: "var(--color-text-secondary)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          flex: 1, minWidth: 0,
        }}>
          {suggestion.author}
          <span style={{ color: "var(--color-text-tertiary)", margin: "0 4px" }}>·</span>
          {suggestion.sectionTitle}
        </span>
        <span style={{
          fontSize: 10, fontWeight: 500, color: statusColor,
          flexShrink: 0,
        }}>
          {statusLabel}
        </span>
      </button>
    );
  }

  // ── Resolved: expanded detail ────────────────────────────────
  if (isResolved && expanded) {
    return (
      <div
        style={{
          marginBottom: 8,
          borderLeft: `2px solid ${statusColor}`,
          padding: "10px 12px",
          background: "var(--color-bg-card)",
          borderRadius: "0 8px 8px 0",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: statusColor, flexShrink: 0 }} />
          <span style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text)" }}>
            {suggestion.author}
          </span>
          <span style={{ fontSize: 10, fontWeight: 500, color: statusColor, marginLeft: "auto" }}>
            {statusLabel}
          </span>
        </div>

        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginBottom: 6 }}>
          {suggestion.sectionTitle}
        </div>

        <div style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5, marginBottom: 8 }}>
          {suggestion.text}
        </div>

        {/* Dismiss reason */}
        {isDismissed && suggestion.resolution?.reason && (
          <div style={{
            fontSize: 11, color: "var(--color-text-tertiary)", lineHeight: 1.4,
            padding: "6px 8px", background: "rgba(239, 68, 100, 0.04)",
            borderRadius: 4, marginBottom: 8,
          }}>
            <span style={{ fontWeight: 500, color: "var(--color-red)", fontSize: 10 }}>Reason: </span>
            {suggestion.resolution.reason}
          </div>
        )}

        {/* Collapse + undo */}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={() => setExpanded(false)}
            style={{
              fontSize: 10, color: "var(--color-text-tertiary)",
              background: "none", border: "none", cursor: "pointer",
              padding: 0,
            }}
          >
            Collapse
          </button>
        </div>
      </div>
    );
  }

  // ── Unresolved: full card with actions ───────────────────────
  return (
    <div
      className="surface"
      style={{
        padding: 12,
        marginBottom: 8,
        borderLeft: "2px solid var(--color-accent)",
        borderRadius: "0 10px 10px 0",
      }}
    >
      {/* Author */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
        <span style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text)" }}>
          {suggestion.author}
        </span>
        {/* Delete (own suggestion only) */}
        {onDelete && suggestion.authorEmail && (
          <button
            onClick={() => onDelete(suggestion.id)}
            title="Delete suggestion"
            style={{
              marginLeft: "auto", display: "flex", alignItems: "center",
              padding: 2, background: "none", border: "none", cursor: "pointer",
              color: "var(--color-text-tertiary)", transition: "color 150ms",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = "var(--color-red)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = "var(--color-text-tertiary)"; }}
          >
            <Trash2 size={11} />
          </button>
        )}
      </div>

      {/* Section reference */}
      <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginBottom: 6 }}>
        {suggestion.sectionTitle}
      </div>

      {/* Suggestion text */}
      <div style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5, marginBottom: 10 }}>
        {suggestion.text}
      </div>

      {/* Reply thread */}
      {suggestion.thread.length > 0 && (
        <div style={{ paddingLeft: 10, borderLeft: "1px solid var(--color-border)", marginBottom: 10 }}>
          {suggestion.thread.map((reply) => (
            <div key={reply.id} style={{ marginBottom: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text)" }}>
                {reply.author}
              </span>
              <div style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.4 }}>
                {reply.text}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Actions */}
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {isAuthor && (
          <>
            <button
              onClick={() => onAccept(suggestion.id)}
              style={{
                fontSize: 11, fontWeight: 500, padding: "4px 10px", borderRadius: 4,
                border: "none", cursor: "pointer", color: "var(--color-emerald)",
                background: "rgba(68, 204, 119, 0.08)", transition: "background 150ms",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(68, 204, 119, 0.16)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(68, 204, 119, 0.08)"; }}
            >
              Accept
            </button>
            <button
              onClick={() => onDismiss(suggestion.id)}
              style={{
                fontSize: 11, fontWeight: 500, padding: "4px 10px", borderRadius: 4,
                border: "none", cursor: "pointer", color: "var(--color-text-secondary)",
                background: "rgba(239, 68, 100, 0.06)", transition: "background 150ms",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(239, 68, 100, 0.12)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(239, 68, 100, 0.06)"; }}
            >
              Dismiss
            </button>
          </>
        )}
        <button
          onClick={() => setReplyOpen(!replyOpen)}
          style={{
            fontSize: 11, fontWeight: 500, padding: "4px 10px", borderRadius: 4,
            border: "none", cursor: "pointer", color: "var(--color-text-tertiary)",
            background: "transparent", transition: "color 150ms",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.color = "var(--color-text-secondary)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = "var(--color-text-tertiary)"; }}
        >
          Reply
        </button>
      </div>

      {/* Inline reply input */}
      {replyOpen && (
        <div style={{ marginTop: 8 }}>
          <textarea
            value={replyText}
            onChange={(e) => setReplyText(e.target.value)}
            placeholder="Write a reply..."
            style={{
              width: "100%", minHeight: 56, padding: 8, fontSize: 12,
              background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)",
              borderRadius: 6, color: "var(--color-text)", fontFamily: "var(--font-sans)",
              resize: "vertical", outline: "none", lineHeight: 1.4,
            }}
            onFocus={(e) => { e.currentTarget.style.borderColor = "var(--color-accent-glow)"; }}
            onBlur={(e) => { e.currentTarget.style.borderColor = "var(--color-border)"; }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); handleReplySubmit(); }
            }}
            autoFocus
          />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 6, marginTop: 4 }}>
            <button
              onClick={() => { setReplyOpen(false); setReplyText(""); }}
              style={{
                fontSize: 11, padding: "3px 8px", borderRadius: 4,
                border: "1px solid var(--color-border)", background: "transparent",
                color: "var(--color-text-tertiary)", cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button
              onClick={handleReplySubmit}
              disabled={!replyText.trim()}
              style={{
                fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 4,
                border: "none", background: "var(--color-accent)", color: "var(--color-bg)",
                cursor: replyText.trim() ? "pointer" : "not-allowed",
                opacity: replyText.trim() ? 1 : 0.5,
              }}
            >
              Reply
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
