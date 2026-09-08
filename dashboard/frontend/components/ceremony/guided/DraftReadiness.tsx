"use client";

import type {
  CurrentQuestion,
  SectionProvenanceEntry,
} from "@/lib/graphql/queries/authoring";

export function DraftReadiness({
  draftAvailable,
  confirmed,
  currentQuestion,
  sections,
  onSelectQuestion,
}: {
  draftAvailable: boolean;
  confirmed: number;
  currentQuestion: CurrentQuestion | null;
  sections: SectionProvenanceEntry[];
  onSelectQuestion?: (questionId: string) => void;
}) {
  const supported = sections.filter((section) =>
    ["confirmed", "evidence_backed", "inferred", "manual"].includes(section.state),
  );

  return (
    <aside
      className="surface-elevated guided-authoring-coverage"
      aria-label="Draft readiness"
      style={{
        width: 240,
        flexShrink: 0,
        padding: 16,
        borderRadius: 10,
        overflowY: "auto",
      }}
    >
      <div className="type-compact-label">Draft readiness</div>
      <div
        className="type-section-title"
        style={{ marginTop: 12, color: draftAvailable ? "var(--color-emerald)" : undefined }}
      >
        {draftAvailable ? "V1 draft ready" : "Interview in progress"}
      </div>
      <div className="type-caption" style={{ marginTop: 6, lineHeight: 1.5 }}>
        {draftAvailable
          ? "Review it now. Only material gaps are asked as follow-ups."
          : "V1 appears after the applicable product decisions have meaningful values."}
      </div>

      <div
        style={{
          marginTop: 16,
          paddingTop: 14,
          borderTop: "1px solid var(--color-border-light)",
        }}
      >
        <div className="type-compact-label">
          {draftAvailable ? "Used in this draft" : "Information captured"}
        </div>
        <div className="type-mono-value" style={{ marginTop: 8, color: "var(--color-text)" }}>
          {confirmed} confirmed input{confirmed === 1 ? "" : "s"}
        </div>
        {supported.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 7, marginTop: 10 }}>
            {supported.map((section) => (
              <button
                key={section.title}
                type="button"
                disabled={!section.question_ids?.[0] || !onSelectQuestion}
                onClick={() => {
                  const id = section.question_ids?.[0];
                  if (id) onSelectQuestion?.(id);
                }}
                style={{
                  padding: 0,
                  border: "none",
                  background: "transparent",
                  color: "var(--color-text-secondary)",
                  fontFamily: "var(--font-sans)",
                  fontSize: 11,
                  lineHeight: 1.35,
                  textAlign: "left",
                  cursor: section.question_ids?.[0] ? "pointer" : "default",
                }}
              >
                {section.state === "manual" ? "Manual · " : ""}{section.title}
              </button>
            ))}
          </div>
        )}
      </div>

      {currentQuestion && (
        <div
          style={{
            marginTop: 16,
            paddingTop: 14,
            borderTop: "1px solid var(--color-border-light)",
          }}
        >
          <div className="type-compact-label">Why this question matters</div>
          <div className="type-body" style={{ marginTop: 8, lineHeight: 1.5 }}>
            {currentQuestion.purpose || "Resolve the highest-impact gap in the current draft."}
          </div>
          <div className="type-caption" style={{ marginTop: 8 }}>
            One answer can complete several PRD sections; non-material areas stay concise and explicit.
          </div>
        </div>
      )}
    </aside>
  );
}
