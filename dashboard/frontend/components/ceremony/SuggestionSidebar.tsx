"use client";

import React, { useState } from "react";
import { MessageCircle, Plus } from "lucide-react";
import type { Suggestion } from "@/lib/graphql/queries/ceremony-suggestions";
import { SuggestionCard } from "./SuggestionCard";
import { SuggestionComposer } from "./SuggestionComposer";
import { DismissReasonDialog } from "./DismissReasonDialog";

interface SuggestionSidebarProps {
  suggestions: Suggestion[];
  isAuthor: boolean;
  onAccept: (id: string) => void;
  onDismiss: (id: string, reason: string) => void;
  onReply: (id: string, text: string) => void;
  onCreateSuggestion?: (sectionId: string, sectionTitle: string, text: string) => void;
  /** Section headings extracted from the spec content */
  specSections?: string[];
}

export function SuggestionSidebar({
  suggestions,
  isAuthor,
  onAccept,
  onDismiss,
  onReply,
  onCreateSuggestion,
  specSections = [],
}: SuggestionSidebarProps) {
  const [dismissTarget, setDismissTarget] = useState<string | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const [composerSection, setComposerSection] = useState("");

  const unresolvedCount = suggestions.filter((s) => s.status === "unresolved").length;

  return (
    <>
      <div
        style={{
          width: 280,
          flexShrink: 0,
          borderLeft: "1px solid var(--color-border)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "10px 16px",
            borderBottom: "1px solid var(--color-border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600, color: "var(--color-text)" }}>
            <MessageCircle size={14} />
            Suggestions
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                fontWeight: 500,
                color: unresolvedCount > 0 ? "var(--color-amber)" : "var(--color-text-tertiary)",
              }}
            >
              {unresolvedCount > 0 ? `${unresolvedCount} pending` : suggestions.length > 0 ? suggestions.length.toString() : ""}
            </span>
          </span>

          {onCreateSuggestion && (
            <button
              onClick={() => setComposerOpen(!composerOpen)}
              title="New suggestion"
              style={{
                display: "flex", alignItems: "center", justifyContent: "center",
                width: 24, height: 24, borderRadius: 4,
                background: composerOpen ? "var(--color-accent-dim)" : "transparent",
                border: "none", cursor: "pointer",
                color: composerOpen ? "var(--color-accent)" : "var(--color-text-tertiary)",
                transition: "all 150ms",
              }}
              onMouseEnter={(e) => { if (!composerOpen) e.currentTarget.style.color = "var(--color-text-secondary)"; }}
              onMouseLeave={(e) => { if (!composerOpen) e.currentTarget.style.color = "var(--color-text-tertiary)"; }}
            >
              <Plus size={14} />
            </button>
          )}
        </div>

        {/* Section picker + composer */}
        {composerOpen && (
          <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--color-border)" }}>
            {!composerSection ? (
              /* Section picker */
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", padding: "2px 0" }}>
                  Select a section:
                </span>
                {specSections.map((s) => (
                  <button
                    key={s}
                    onClick={() => setComposerSection(s)}
                    style={{
                      textAlign: "left", padding: "6px 8px", fontSize: 12,
                      color: "var(--color-text-secondary)", background: "transparent",
                      border: "1px solid var(--color-border)", borderRadius: 6,
                      cursor: "pointer", transition: "all 150ms",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.borderColor = "var(--color-accent-glow)";
                      e.currentTarget.style.color = "var(--color-text)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.borderColor = "var(--color-border)";
                      e.currentTarget.style.color = "var(--color-text-secondary)";
                    }}
                  >
                    {s}
                  </button>
                ))}
                <button
                  onClick={() => { setComposerOpen(false); setComposerSection(""); }}
                  style={{
                    fontSize: 11, padding: "4px 0", color: "var(--color-text-tertiary)",
                    background: "transparent", border: "none", cursor: "pointer",
                    marginTop: 4,
                  }}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <SuggestionComposer
                sectionId={composerSection.toLowerCase().replace(/\s+/g, "-")}
                sectionTitle={composerSection}
                onSubmit={(sectionId, sectionTitle, text) => {
                  onCreateSuggestion?.(sectionId, sectionTitle, text);
                  setComposerSection("");
                  setComposerOpen(false);
                }}
                onCancel={() => { setComposerSection(""); setComposerOpen(false); }}
              />
            )}
          </div>
        )}

        {/* Card list */}
        <div style={{ flex: 1, overflowY: "auto", padding: 8 }}>
          {suggestions.length === 0 && !composerOpen ? (
            <div
              style={{
                padding: "32px 16px",
                textAlign: "center",
                fontSize: 12,
                color: "var(--color-text-tertiary)",
                lineHeight: 1.6,
              }}
            >
              {onCreateSuggestion
                ? <>No suggestions yet.<br />Click <Plus size={11} style={{ verticalAlign: "middle" }} /> to add one.</>
                : "No suggestions yet"}
            </div>
          ) : (
            <>
              {/* Unresolved first */}
              {suggestions
                .filter((s) => s.status === "unresolved")
                .map((s) => (
                  <SuggestionCard
                    key={s.id}
                    suggestion={s}
                    isAuthor={isAuthor}
                    onAccept={onAccept}
                    onDismiss={(id) => setDismissTarget(id)}
                    onReply={onReply}
                  />
                ))}

              {/* Resolved divider + collapsed cards */}
              {suggestions.some((s) => s.status !== "unresolved") && (
                <>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "8px 4px 4px", margin: "4px 0",
                  }}>
                    <div style={{ flex: 1, height: 1, background: "var(--color-border)" }} />
                    <span style={{
                      fontSize: 10, fontFamily: "var(--font-mono)", fontWeight: 500,
                      color: "var(--color-text-tertiary)", whiteSpace: "nowrap",
                    }}>
                      {suggestions.filter((s) => s.status !== "unresolved").length} resolved
                    </span>
                    <div style={{ flex: 1, height: 1, background: "var(--color-border)" }} />
                  </div>
                  {suggestions
                    .filter((s) => s.status !== "unresolved")
                    .map((s) => (
                      <SuggestionCard
                        key={s.id}
                        suggestion={s}
                        isAuthor={isAuthor}
                        onAccept={onAccept}
                        onDismiss={(id) => setDismissTarget(id)}
                        onReply={onReply}
                      />
                    ))}
                </>
              )}
            </>
          )}
        </div>
      </div>

      {/* Dismiss reason dialog */}
      <DismissReasonDialog
        isOpen={!!dismissTarget}
        onDismiss={(reason) => {
          if (dismissTarget) {
            onDismiss(dismissTarget, reason);
            setDismissTarget(null);
          }
        }}
        onCancel={() => setDismissTarget(null)}
      />
    </>
  );
}
